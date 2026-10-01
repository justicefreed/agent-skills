#!/usr/bin/env python3
"""Deterministic checks for route-aware pricing eligibility.

Run: python3 test_pricing.py
"""

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone


HERE = os.path.dirname(os.path.realpath(__file__))
_spec = importlib.util.spec_from_file_location(
    "pricing", os.path.join(HERE, "pricing.py"))
pricing = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = pricing
_spec.loader.exec_module(pricing)

NOW = datetime(2026, 9, 18, tzinfo=timezone.utc)
FAILURES = []


def rate_row(model, write, read, evidence="documented", route="cursor"):
    return {
        "route": route,
        "model": model,
        "source_id": "test-source",
        "rates": {"input": "1.00", "cache_write": write,
                  "cache_read": read, "output": "2.00"},
        "cache_semantics": {"evidence": evidence},
    }


def snapshot():
    return {
        "schema_version": 2,
        "snapshot_id": "test-snapshot",
        "generator_version": "test",
        "generated_at": "2026-09-18T00:00:00+00:00",
        "refresh_after": "2026-09-19T00:00:00+00:00",
        "expires_at": "2026-10-01T00:00:00+00:00",
        "currency": "USD",
        "unit": "per_million_tokens",
        "validation_status": "valid",
        "sources": [{"id": "test-source", "provider": "test",
                     "url": "https://example.test/pricing",
                     "retrieved_at": "2026-09-18T00:00:00+00:00",
                     "payload_sha256": "a" * 64}],
        "routes": {"cursor": {"harnesses": ["cursor"], "prefix": "cursor/"}},
        "models": [{"id": "target", "provider": "cursor", "source": "test"},
                   {"id": "source", "provider": "cursor", "source": "test"}],
        "names": [{"route": "cursor", "name": "target-slug", "model": "target"}],
        "aliases": {"cursor": {"retrieved_at": "2026-09-18", "map": {"fast": "target"}}},
        "rates": [rate_row("target", "0.30", "0.05"),
                  rate_row("source", "1.00", "0.50")],
    }


def options():
    return {
        "schema_version": 3,
        "models": [
            {"id": "target", "provider": "cursor", "rungs": ["minimal"]},
            {"id": "source", "provider": "cursor", "rungs": ["economy"]},
        ],
    }


def check(name, value, expected):
    if value != expected:
        FAILURES.append(name)
        print("FAIL %s: got %r, want %r" % (name, value, expected))
    else:
        print("ok   %s" % name)


base = snapshot()
check("valid snapshot has no warnings", pricing.validate_snapshot(base, NOW), [])

positive = pricing.eligibility(base, options(), "target", "source", 2, NOW, "cursor")
check("positive target is eligible", positive["eligible"], True)
check("positive cache-only savings", positive["per_million"]["savings"], "0.65")

marginal = copy.deepcopy(base)
marginal["rates"][0]["rates"]["cache_write"] = "0.40"
result = pricing.eligibility(marginal, options(), "target", "source", 2, NOW, "cursor")
check("write bound is strict", result["eligible"], False)
check("write boundary reason", result["reasons"],
      ["target cache_write must be below $0.40/M"])

negative = copy.deepcopy(base)
negative["rates"][0]["rates"]["cache_write"] = "0.39"
negative["rates"][0]["rates"]["cache_read"] = "0.10"
negative["rates"][1]["rates"]["cache_read"] = "0.24"
result = pricing.eligibility(negative, options(), "target", "source", 2, NOW, "cursor")
check("negative pricing is rejected", result["eligible"], False)
check("negative calculation reason", "cache-only estimate is not positive" in result["reasons"], True)

missing = copy.deepcopy(base)
missing["rates"][0]["rates"]["cache_write"] = None
result = pricing.eligibility(missing, options(), "target", "source", 2, NOW, "cursor")
check("missing cache price fails closed", result["eligible"], False)
check("missing cache price reason", result["reasons"],
      ["target lacks cache_write pricing"])

unknown = copy.deepcopy(base)
unknown["rates"][0]["cache_semantics"]["evidence"] = "unknown"
result = pricing.eligibility(unknown, options(), "target", "source", 2, NOW, "cursor")
check("unknown cache behavior fails closed", result["eligible"], False)
check("unknown cache behavior reason", result["reasons"],
      ["target cache semantics are unknown"])

expired = copy.deepcopy(base)
expired["generated_at"] = "2026-09-15T00:00:00+00:00"
expired["refresh_after"] = "2026-09-16T00:00:00+00:00"
expired["expires_at"] = "2026-09-17T00:00:00+00:00"
result = pricing.eligibility(expired, options(), "target", "source", 2, NOW, "cursor")
check("expired snapshot fails closed", result["eligible"], False)
check("expired snapshot reason", result["reasons"],
      ["snapshot is stale or expired"])

for actions in (2, 3):
    result = pricing.eligibility(base, options(), "target", "source", actions, NOW, "cursor")
    check("%s-action bound is eligible" % actions, result["eligible"], True)


# Registry validation: each rule has a fixture that must be rejected.
def rejects(name, mutate, needle):
    bad = snapshot()
    mutate(bad)
    try:
        pricing.validate_snapshot(bad, NOW)
    except pricing.PricingError as exc:
        check(name, needle in str(exc), True)
        if needle not in str(exc):
            print("     message was: %s" % exc)
    else:
        check(name, "accepted", "rejected")


rejects("name mapping to a non-canonical id is rejected",
        lambda s: s["names"].append({"route": "cursor", "name": "x", "model": "nope"}),
        "not a canonical id")
rejects("name resolving to two ids is rejected",
        lambda s: s["names"].append({"route": "cursor", "name": "target-slug", "model": "source"}),
        "resolves to both")
rejects("alias resolving to a non-canonical id is rejected",
        lambda s: s["aliases"]["cursor"]["map"].update(slow="nope"),
        "not a canonical id")
rejects("alias colliding with a route name is rejected",
        lambda s: s["aliases"]["cursor"]["map"].update({"target-slug": "source"}),
        "resolves to both")
rejects("route name that is a canonical id is rejected",
        lambda s: s["names"].append({"route": "cursor", "name": "source", "model": "target"}),
        "also a canonical id")
rejects("alias that is a canonical id is rejected",
        lambda s: s["aliases"]["cursor"]["map"].update(target="source"),
        "also a canonical id")
rejects("duplicate (route, model) rate row is rejected",
        lambda s: s["rates"].append(rate_row("target", "0.10", "0.01")),
        "duplicate rate (cursor, target)")
rejects("rate row on a non-canonical id is rejected",
        lambda s: s["rates"].append(rate_row("target-slug", "0.10", "0.01")),
        "not a canonical id")
rejects("undated alias table is rejected",
        lambda s: s["aliases"]["cursor"].pop("retrieved_at"),
        "must be dated")
rejects("rate row mixing flat and tiered fields is rejected",
        lambda s: s["rates"][0]["rates"].update(cache_write_1h="1.00"),
        "rates must be exactly")


def options_rejects(name, mutate, needle):
    bad = options()
    mutate(bad)
    try:
        pricing.validate_options(bad, pricing.Registry(snapshot()))
    except pricing.PricingError as exc:
        check(name, needle in str(exc), True)
    else:
        check(name, "accepted", "rejected")


options_rejects("model option that is not a canonical id is rejected",
                lambda o: o["models"].append({"id": "target-slug", "provider": "cursor"}),
                "not a canonical id")
options_rejects("model option keeping a pricing_key is rejected",
                lambda o: o["models"][0].update(pricing_key="cursor/target"),
                "pricing_key")
options_rejects("duplicate model option is rejected",
                lambda o: o["models"].append(dict(o["models"][0])),
                "duplicate model policy id")
# Policy, not just shape. Each of these is a way the map drifted or could
# drift back: a preference ranking a model its rung tags never select (the
# frontier preference once named a model tagged only advanced), an archetype
# starting above the anchor, an absolute effort that erased the verifier's
# one-below-default step.
options_rejects("preference for a model not tagged with that rung is rejected",
                lambda o: o.update(preferences={"economy": ["target"]}),
                "is not tagged economy")
options_rejects("unknown rung tag is rejected",
                lambda o: o["models"][0].update(rungs=["premium"]),
                "unknown rung")
options_rejects("archetype starting above economy is rejected",
                lambda o: o.update(archetypes={"reviewer": {"rung": "advanced",
                                                            "effort": "default"}}),
                "reach higher only by escalation")
options_rejects("archetype with an absolute effort is rejected",
                lambda o: o.update(archetypes={"verifier": {"rung": "economy",
                                                            "effort": "medium"}}),
                "must be relative")

# Input translation: canonical ids pass through, names and aliases translate
# with the table date, anything else is an error rather than a guess.
registry = pricing.Registry(snapshot())
check("canonical id passes through untranslated",
      registry.resolve_model("target", "cursor"), {"model": "target"})
check("route name translates and reports its table",
      registry.resolve_model("target-slug", "cursor"),
      {"model": "target", "translated_from": "target-slug",
       "alias_table": "2026-09-18", "alias_source": "route:cursor"})
check("harness alias translates and reports its date",
      registry.resolve_model("fast", "cursor")["alias_table"], "2026-09-18")
for bad_name, harness in (("mystery", "cursor"), ("fast", "claude-code")):
    try:
        registry.resolve_model(bad_name, harness)
    except pricing.PricingError as exc:
        check("unknown %r under %s is an error" % (bad_name, harness),
              "unknown model" in str(exc), True)
    else:
        check("unknown %r under %s is an error" % (bad_name, harness), "resolved", "error")
translated = pricing.eligibility(base, options(), "target-slug", "source", 2, NOW, "cursor")
check("eligibility reports the canonical id, not the input name",
      translated["target_model"], "target")
check("eligibility reports the translation",
      translated["translations"][0]["translated_from"], "target-slug")

# The shipped snapshot and options: validation passes, and under claude-code
# Anthropic rows give Haiku a computed verdict rather than a missing price.
_, shipped, _ = pricing.load_snapshot()
shipped_options = pricing.load_json(pricing.default_options_path())
pricing.validate_options(shipped_options, pricing.Registry(shipped))
check("shipped options validate against the shipped registry", True, True)
check("shipped map has no rung whose cheaper model costs more",
      pricing.rung_order_warnings(shipped_options, shipped), [])
_order_options = {"preferences": {"economy": ["cheap"], "advanced": ["dear"]},
                  "models": [{"id": "cheap", "lineage": "x", "rungs": ["economy"]},
                             {"id": "dear", "lineage": "x", "rungs": ["advanced"]},
                             {"id": "other", "lineage": "y", "rungs": ["advanced"]}]}
_order_snapshot = {"rates": [
    {"route": "r", "model": "cheap", "rates": {"input": "1.00", "cache_read": "0.50"}},
    {"route": "r", "model": "dear", "rates": {"input": "4.00", "cache_read": "0.20"}},
    {"route": "r", "model": "other", "rates": {"input": "0.10", "cache_read": "0.01"}}]}
check("an economy model dearer on cache reads than its lineage's advanced is warned",
      pricing.rung_order_warnings(_order_options, _order_snapshot),
      ["economy cheap costs more than advanced dear for cache_read on r (0.50 > 0.20)"])
haiku = pricing.eligibility(shipped, shipped_options, "claude-haiku-4-5-20251001",
                            "claude-opus-5-5", 2, NOW, "claude-code")
check("claude-code prices haiku on the anthropic route", haiku["target_route"], "anthropic")
check("claude-code haiku verdict is computed", "per_million" in haiku, True)
check("claude-code haiku is not rejected for a missing price",
      any("no reviewed price" in r for r in haiku["reasons"]), False)
check("haiku alias translates under claude-code",
      pricing.eligibility(shipped, shipped_options, "haiku", "claude-opus-5-5", 2, NOW,
                          "claude-code")["target_model"], "claude-haiku-4-5-20251001")

# Guard: no model field in any JSON output of `spend models`, `pricing
# eligibility` or `pricing eligible-models` may be an alias or route name, even
# when the input was one. Inputs below are deliberately aliases and route names.
KNOWN_NAMES = pricing.Registry(shipped).known_names()


def model_fields(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            here = "%s.%s" % (path, key)
            if (key == "model" or key.endswith("_model")) and isinstance(item, str):
                yield here, item
            yield from model_fields(item, here)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from model_fields(item, "%s[%d]" % (path, index))


def cli_json(script, *argv):
    done = subprocess.run([sys.executable, os.path.join(HERE, script)] + list(argv),
                          capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    try:
        return json.loads(done.stdout)
    except ValueError:
        print("     %s %s -> %s" % (script, " ".join(argv), done.stderr.strip()))
        return None


catalog_fd, catalog_path = tempfile.mkstemp(suffix=".json")
with os.fdopen(catalog_fd, "w") as fh:
    json.dump({"models": [
        {"slug": "cursor/claude-sonnet-5", "supported_reasoning_levels": [{"effort": "medium"}]},
        {"slug": "cursor/claude-4.6-sonnet", "supported_reasoning_levels": [{"effort": "medium"}]},
        {"slug": "claude-ocx-cursor--gpt-5.6-terra",
         "supported_reasoning_levels": [{"effort": "medium"}]},
        {"slug": "gpt-5.6-luna", "supported_reasoning_levels": [{"effort": "low"}]},
        {"slug": "cursor/gemini-3.1-pro", "supported_reasoning_levels": [{"effort": "medium"}]},
    ]}, fh)
outputs = {
    # --harness cursor pins this to the loaded-catalog path regardless of the
    # ambient environment (this test process itself may carry CLAUDECODE),
    # and keeps it out of the claude-code catalog / real ~/.claude/agents.
    "spend models economy": cli_json("spend.py", "models", "--rung", "economy",
                                     "--catalog", catalog_path, "--harness", "cursor",
                                     "--format", "json"),
    "spend models advanced": cli_json("spend.py", "models", "--rung", "advanced",
                                      "--catalog", catalog_path, "--harness", "cursor",
                                      "--format", "json"),
    "pricing eligibility": cli_json("pricing.py", "eligibility", "--model", "haiku",
                                    "--source-model", "opus", "--harness", "claude-code"),
    "pricing eligible-models": cli_json("pricing.py", "eligible-models", "--rung", "minimal",
                                        "--source-model", "claude-ocx-cursor--claude-opus-5",
                                        "--harness", "claude-code"),
}
os.unlink(catalog_path)
for label, output in outputs.items():
    fields = list(model_fields(output)) if output is not None else []
    check("%s emits model fields" % label, bool(fields), True)
    leaked = [(path, value) for path, value in fields if value in KNOWN_NAMES]
    check("%s emits no alias or route name" % label, leaked, [])

# Step 5, end to end through the CLI: under claude-code the catalog is
# derived (no --catalog needed) and every selected model carries a spawn
# field the Agent tool accepts. Forcing --harness codex against the same
# --catalog must reproduce today's Codex output: no spawn field at all.
_cli_agents_dir = tempfile.mkdtemp()
with open(os.path.join(_cli_agents_dir, "claude-haiku-4-5-20251001.md"), "w") as fh:
    fh.write('---\nname: "claude-haiku-4-5-20251001"\ndescription: "Routed worker."\n'
             'model: "claude-haiku-4-5-20251001"\n---\n')

_cc_models = cli_json("spend.py", "models", "--rung", "minimal", "--harness", "claude-code",
                      "--agents-dir", _cli_agents_dir, "--format", "json")
check("claude-code models has a derived catalog with no --catalog flag",
      _cc_models is not None and bool(_cc_models["models"]), True)
check("claude-code models all carry a spawn field",
      all("spawn" in row for row in (_cc_models or {}).get("models", [])), True)
check("claude-code haiku spawns via its alias even beside its own agent definition",
      next((row["spawn"] for row in _cc_models["models"]
            if row["model"] == "claude-haiku-4-5-20251001"), None),
      {"kind": "alias", "value": "haiku", "alias_table": "2026-09-30", "route": "anthropic"})

codex_fd, codex_catalog_path = tempfile.mkstemp(suffix=".json")
with os.fdopen(codex_fd, "w") as fh:
    json.dump({"models": [{"slug": "claude-haiku-4-5-20251001",
                           "supported_reasoning_levels": [{"effort": "low"}]}]}, fh)
_codex_models = cli_json("spend.py", "models", "--rung", "minimal", "--harness", "codex",
                         "--catalog", codex_catalog_path, "--format", "json")
os.unlink(codex_catalog_path)
check("codex output has no spawn field (today's behaviour, reproduced)",
      any("spawn" in row for row in (_codex_models or {}).get("models", [])), False)
shutil.rmtree(_cli_agents_dir, ignore_errors=True)

# Case-fold: a route-prefixed name normalizes case because a provider id has
# exactly one lowercase spelling -- not because an alias is being guessed at.
check("resolve_model case-folds a route-prefixed name",
           pricing.Registry(shipped).resolve_model(
               "cursor/GPT-5.6-sol", "cursor")["model"], "gpt-5.6-sol")

# Harness detection: --harness first, then CLAUDECODE/CLAUDE_CODE_SESSION_ID,
# then CODEX_HOME, otherwise cursor -- and every result says which fired.
_ENV_KEYS = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CODEX_HOME")


def detect(explicit=None, **env_vars):
    saved = {k: os.environ.pop(k, None) for k in _ENV_KEYS}
    os.environ.update(env_vars)
    try:
        return pricing.detect_harness(explicit)
    finally:
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


check("--harness wins over every environment signal",
           detect("cursor", CLAUDECODE="1"), {"harness": "cursor", "detected_by": "--harness"})
check("CLAUDECODE selects claude-code",
           detect(CLAUDECODE="1"), {"harness": "claude-code", "detected_by": "CLAUDECODE"})
check("CLAUDE_CODE_SESSION_ID selects claude-code",
           detect(CLAUDE_CODE_SESSION_ID="abc"),
           {"harness": "claude-code", "detected_by": "CLAUDE_CODE_SESSION_ID"})
check("CLAUDECODE is checked before CODEX_HOME",
           detect(CLAUDECODE="1", CODEX_HOME="/tmp"),
           {"harness": "claude-code", "detected_by": "CLAUDECODE"})
check("CODEX_HOME selects codex",
           detect(CODEX_HOME="/tmp"), {"harness": "codex", "detected_by": "CODEX_HOME"})
check("no signal falls back to cursor",
           detect(), {"harness": "cursor", "detected_by": "fallback"})

# Agent definitions and the Claude Code catalog: an ocx-cursor model is only
# reachable when an `ocx-*` agent definition actually carries it, resolved
# through the registry rather than pattern-matched on the filename.
_agents_dir = tempfile.mkdtemp()


def write_agent(filename, name, model, generated_by=None):
    text = '---\nname: "%s"\ndescription: "Routed worker."\nmodel: "%s"\n---\n' % (name, model)
    if generated_by:
        text += "\n<!-- generated-by: %s -->\n" % generated_by
    with open(os.path.join(_agents_dir, filename), "w") as fh:
        fh.write(text)


write_agent("ocx-claude-sonnet-5.md", "ocx-claude-sonnet-5",
           "claude-ocx-cursor--claude-sonnet-5", generated_by="opencodex")
write_agent("claude-opus-5-5.md", "claude-opus-5-5", "claude-opus-5-5")

_agents = pricing.read_agent_definitions(_agents_dir)
check("agent definitions resolve their model through the registry",
           sorted(_agents), ["claude-opus-5-5", "ocx-claude-sonnet-5"])
check("an opencodex-generated agent is marked as such",
           _agents["ocx-claude-sonnet-5"]["generated_by"], "opencodex")
check("a hand-written agent has no generator marker",
           _agents["claude-opus-5-5"]["generated_by"], None)

_shipped_registry = pricing.Registry(shipped)
_agent_index = pricing.index_agents_by_model(_agents, _shipped_registry)
_, _catalog = pricing.claude_code_catalog(_shipped_registry, _agents_dir)
_catalog_slugs = {row["slug"] for row in _catalog}
check("a bare anthropic id is reachable with no agent definition needed",
           "claude-haiku-4-5-20251001" in _catalog_slugs, True)
check("an ocx-cursor model with an agent definition is reachable",
           "claude-ocx-cursor--claude-sonnet-5" in _catalog_slugs, True)
check("an ocx-cursor model with NO agent definition is not reachable",
           "claude-ocx-cursor--gpt-5.6-terra" in _catalog_slugs, False)

# Spawn field preference (ruling (a)): `spawn` must stay on the route the
# recommendation was priced on. An agent named for the canonical id, then an
# undrifted alias -- both restricted to that route. A routed `ocx-*` agent on
# a *different* route is never the primary spawn; it is a `via` alternative
# with its own route and price.
# An undrifted alias outranks an id-named agent definition: the alias spawns
# the built-in general-purpose agent, whose system prompt a bare definition
# would replace.
check("case 1: an undrifted alias wins over an agent definition named for the id",
           pricing.spawn_field("claude-opus-5-5", "claude-opus", "claude-code",
                               _shipped_registry, _agent_index)["spawn"],
           {"kind": "alias", "value": "opus", "alias_table": "2026-09-30", "route": "anthropic"})

# Ruling (a)'s falsification: `claude-sonnet-5` prices on `anthropic`. Its
# only agent definition here (`ocx-claude-sonnet-5`) is on `ocx-cursor` -- a
# different, more expensive route -- while the `sonnet` alias is undrifted
# on the anthropic route itself. The OLD tier order (agent-named check, then
# ANY routed agent, then alias) picked the ocx-cursor bridge as `spawn`
# before ever considering the alias, because it never restricted the routed
# check to the priced route. That is exactly the bug ruling (a) names: a
# recommendation priced on one route silently spawning on another. Confirmed
# by temporarily reverting to the pre-ruling `spawn_field` and re-running this
# file: this check went red (`spawn` came back
# `{"kind": "routed-agent", "value": "ocx-claude-sonnet-5", "route":
# "ocx-cursor"}`, and there was no `via` key at all) before the fix, and green
# after it -- see docs/canonical-model-ids-L3-notes.md, Falsification.
_sonnet = pricing.spawn_field("claude-sonnet-5", "claude-sonnet", "claude-code",
                              _shipped_registry, _agent_index)
check("ruling (a): spawn stays on the priced route (alias, not the ocx-cursor bridge)",
           _sonnet["spawn"],
           {"kind": "error", "route": "anthropic",
            "error": "alias 'sonnet' drifted to 'claude-sonnet-5-5', not 'claude-sonnet-5'"})
check("ruling (a): the ocx-cursor bridge is demoted to a `via` alternative",
           [(entry["route"], entry["value"]) for entry in _sonnet["via"]],
           [("ocx-cursor", "ocx-claude-sonnet-5")])
check("ruling (a): the `via` alternative carries its own route's price",
           _sonnet["via"][0]["rates"] is not None, True)

check("case 3: an undrifted alias, on the model's native route",
           pricing.spawn_field("claude-haiku-4-5-20251001", "claude-haiku", "claude-code",
                               _shipped_registry, {})["spawn"],
           {"kind": "alias", "value": "haiku", "alias_table": "2026-09-30", "route": "anthropic"})
# The shipped alias table's `opus` points at the current `claude-opus-5-5`,
# so for last generation's `claude-opus-4-8` the alias has drifted. A spawn
# field must refuse that alias, not guess it -- unless an agent definition
# named for the id can pin it instead.
_drifted = pricing.spawn_field("claude-opus-4-8", "claude-opus", "claude-code",
                               _shipped_registry, {})["spawn"]
check("a drifted alias is refused, not silently spawned", _drifted["kind"], "error")
check("the refusal names the drift", "drifted" in _drifted["error"], True)
check("a drifted alias falls back to an agent definition named for the id",
           pricing.spawn_field("claude-opus-4-8", "claude-opus", "claude-code", _shipped_registry,
                               {"claude-opus-4-8": [{"name": "claude-opus-4-8",
                                                     "route": "anthropic"}]})["spawn"],
           {"kind": "agent", "value": "claude-opus-4-8", "route": "anthropic"})

# If the priced route has no spawn path at all, `spawn` refuses while `via`
# still lists whatever agent definitions exist on other routes.
_no_path = pricing.spawn_field("claude-sonnet-4-6", "claude-sonnet", "claude-code",
                               _shipped_registry, _agent_index)
check("no spawn path on the priced route is refused, not guessed",
           _no_path["spawn"]["kind"], "error")
check("refusing spawn still surfaces via alternatives when any exist",
           _no_path["via"], [])

shutil.rmtree(_agents_dir, ignore_errors=True)

if FAILURES:
    print("%d failure(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
    sys.exit(1)
print("all pass")
