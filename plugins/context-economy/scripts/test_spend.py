#!/usr/bin/env python3
"""Pin the parts of spend.py that are wrong in a way no one notices.

Run: python3 test_spend.py

Every case here is a rate or dedup rule that produced plausible-looking
numbers while being wrong. A cost tool that is quietly 10% low is worse than
one that fails, because its output still gets used.

No test framework, matching the plugin: one file, standard library only.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
_spec = importlib.util.spec_from_file_location("spend", os.path.join(HERE, "spend.py"))
spend = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spend)

# (anthropic, claude-opus-5), $/M: in 5.0 · out 25.0 · write-5m 6.25 · write-1h 10.0 · read 0.5
RATES = spend.default_rates()
_tmp = []


def transcript(rows):
    fh = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for row in rows:
        fh.write(json.dumps(row) + "\n")
    fh.close()
    _tmp.append(fh.name)
    return fh.name


def call(request_id, **usage):
    return {"type": "assistant", "requestId": request_id,
            "message": {"model": "claude-opus-5", "id": "m" + request_id,
                        "usage": usage}}


def write(total, ephemeral_1h=None):
    """A call whose only cost is `total` cache-creation tokens."""
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
             "cache_creation_input_tokens": total}
    if ephemeral_1h is not None:
        usage["cache_creation"] = {"ephemeral_1h_input_tokens": ephemeral_1h}
    return usage


FAILURES = []


def check(name, got, want):
    ok = abs(got - want) < 1e-9
    if not ok:
        FAILURES.append(name)
    print("  %-48s %14.6f  want %14.6f  %s"
          % (name, got, want, "ok" if ok else "FAIL"))


def check_same(name, got, want):
    """Exact equality, for the things that are strings rather than money."""
    ok = got == want
    if not ok:
        FAILURES.append(name)
    print("  %-48s %s" % (name, "ok" if ok else "FAIL"))
    if not ok:
        print("    got  %r\n    want %r" % (got, want))


M = 1_000_000

# Rates are an exact (route, canonical id) lookup. A route prefix picks the
# route; a bare Anthropic id is the anthropic route; nothing matches by substring.
def rate(**r):
    return {"in": r["i"], "out": r["o"], "cache_write": r["w5"],
            "cache_write_1h": r["w1"], "cache_read": r["r"]}


check_same("bare claude-opus-5-5 prices from its own row, not opus-5's",
           spend.rate_for("claude-opus-5-5", RATES),
           rate(i=4.0, o=20.0, w5=5.0, w1=8.0, r=0.2))
check_same("lookup names the route and canonical id",
           {k: v for k, v in RATES.lookup("claude-opus-5-5").items() if k != "rate"},
           {"route": "anthropic", "model": "claude-opus-5-5", "reason": None})
check_same("cursor prefix prices from the cursor row",
           spend.rate_for("cursor/gpt-5.6-sol", RATES),
           rate(i=4.0, o=20.0, w5=5.0, w1=5.0, r=0.4))
check_same("cursor's untiered write covers both buckets for Fable 5.1",
           spend.rate_for("cursor/claude-fable-5-1", RATES),
           rate(i=10.0, o=50.0, w5=12.5, w1=12.5, r=0.25))
check_same("anthropic Fable 5.1 keeps its 1h tier",
           spend.rate_for("claude-fable-5-1", RATES),
           rate(i=10.0, o=50.0, w5=12.5, w1=20.0, r=0.25))
check_same("ocx-cursor bills from cursor's row",
           spend.rate_for("claude-ocx-cursor--gpt-5.6-terra", RATES),
           rate(i=2.0, o=12.0, w5=2.5, w1=2.5, r=0.2))
check_same("anthropic API alias resolves to the dated haiku id",
           RATES.lookup("claude-haiku-4-5")["model"], "claude-haiku-4-5-20251001")
check_same("cursor route name maps to its canonical id",
           RATES.lookup("cursor/gemini-3.1-pro")["model"], "gemini-3.1-pro-preview")
check_same("cursor dash stays null, not zero",
           spend.rate_for("cursor/composer-2.5", RATES)["cache_write"], None)
check_same("a model with no route rate is unpriced, with a reason",
           (spend.rate_for("cursor/claude-opus-5", RATES),
            RATES.lookup("cursor/claude-opus-5")["reason"]),
           (None, "no cursor rate for claude-opus-5"))
check_same("an unknown model is unpriced, never defaulted",
           spend.rate_for("provider/notopus-model", RATES), None)
# Case-fold is normalization, not alias guessing: provider ids, names and
# prefixes are all lowercase, so a re-cased spelling has exactly one meaning.
check_same("case is folded to the one thing it could mean",
           spend.rate_for("cursor/GPT-5.6-sol", RATES),
           rate(i=4.0, o=20.0, w5=5.0, w1=5.0, r=0.4))
check_same("no short-name key survives in the rate table",
           sorted({route for route, _ in RATES.rows}),
           ["anthropic", "cursor", "openai"])

# Overrides keep working, keyed by (route, canonical id). The old short-name
# format is rejected with the canonical ids it could have meant.
_over = RATES.with_overrides({"rates": [{
    "route": "anthropic", "model": "claude-opus-5-5", "input": 1, "output": 2,
    "cache_write_5m": 3, "cache_write_1h": 4, "cache_read": 0.5}]}, "test")
check_same("a (route, id) override replaces that row",
           spend.rate_for("claude-opus-5-5", _over),
           rate(i=1.0, o=2.0, w5=3.0, w1=4.0, r=0.5))


def rejected(data):
    try:
        RATES.with_overrides(data, "test")
    except spend.SpendError as exc:
        return str(exc)
    return None


_msg = rejected({"opus-5": {"in": 5.0, "out": 25.0, "cache_write": 6.25, "cache_read": 0.5}})
check_same("short-name override key is rejected naming canonical ids",
           bool(_msg) and "claude-opus-5" in _msg and "claude-opus-5-5" in _msg, True)
check_same("override on a route name is rejected naming the canonical id",
           "claude-sonnet-4-6" in (rejected({"rates": [{
               "route": "cursor", "model": "claude-4.6-sonnet", "input": 1, "output": 1,
               "cache_write": 1, "cache_read": 1}]}) or ""), True)
check_same("override with only a 5m write tier is rejected",
           "rates must be exactly" in (rejected({"rates": [{
               "route": "anthropic", "model": "claude-opus-5", "input": 1, "output": 1,
               "cache_write_5m": 1, "cache_read": 1}]}) or ""), True)
check_same("override on a route that bills elsewhere is rejected",
           "bills as 'cursor'" in (rejected({"rates": [{
               "route": "ocx-cursor", "model": "claude-sonnet-5", "input": 1, "output": 1,
               "cache_write": 1, "cache_read": 1}]}) or ""), True)

# Model selection is two deterministic filters: the versioned policy says what
# fits, and the live catalog says what can actually be spawned. A prose table
# cannot make the second guarantee.
_model_options = {
    "preferences": {"economy": ["claude-sonnet-5"]},
    "archetypes": {
        "implementer": {
            "aliases": ["implementation"],
            "rung": "economy",
            "effort": "medium",
        },
    },
    "models": [
        {"id": "gpt-5.6-luna", "family": "gpt-5.6",
         "rungs": ["minimal", "economy"], "use": "bounded work"},
        {"id": "claude-sonnet-5", "family": "claude-sonnet",
         "rungs": ["economy", "advanced"], "use": "interconnected work"},
        {"id": "retired-model", "family": "retired",
         "rungs": ["economy"], "use": "must not appear"},
    ],
}
_model_catalog = [
    {"slug": "cursor/gpt-5.6-luna",
     "supported_reasoning_levels": [
         {"effort": "low"}, {"effort": "medium"}, {"effort": "high"}]},
    {"slug": "cursor/claude-sonnet-5",
     "supported_reasoning_levels": [{"effort": "low"}]},
]
_selected = spend.select_models(
    _model_options, _model_catalog, "economy", "medium")
check_same("model selector returns canonical ids",
           [row["model"] for row in _selected],
           ["claude-sonnet-5", "gpt-5.6-luna"])
check_same("model selector keeps the live slug that matched",
           [row["catalog_slug"] for row in _selected],
           ["cursor/claude-sonnet-5", "cursor/gpt-5.6-luna"])
check_same("model selector emits only supported efforts",
           [row["effort"] for row in _selected], ["low", "medium"])
check_same("model selector can require an independent family",
           [row["model"] for row in spend.select_models(
               _model_options, _model_catalog, "economy", "medium", "gpt-5.6")],
           ["claude-sonnet-5"])
check_same("model preference never overrides an excluded family",
           [row["model"] for row in spend.select_models(
               _model_options, _model_catalog, "economy", "medium", "claude-sonnet")],
           ["gpt-5.6-luna"])
check_same("archetype aliases resolve to canonical policy",
           spend.resolve_archetype(
               "implementation", _model_options["archetypes"])[0],
           "implementer")

# The 1-hour cache-write tier bills at 2x input; the 5-minute tier at 1.25x.
# `cache_creation_input_tokens` is their sum and did not change when the
# breakdown was added, so code reading only it prices 1h writes at the 5m rate.
# Measured at a 10.3% understatement on a 1h-TTL harness.
check("1M cache write, all 1h -> 2x input",
      spend.read_usage(transcript([call("a", **write(M, ephemeral_1h=M))]), RATES)["cost"],
      10.0)
check("1M cache write, all 5m -> 1.25x input",
      spend.read_usage(transcript([call("b", **write(M, ephemeral_1h=0))]), RATES)["cost"],
      6.25)
check("mixed: 5m derived by subtracting 1h from the total",
      spend.read_usage(transcript([call("c", **write(M, ephemeral_1h=400_000))]), RATES)["cost"],
      0.6 * 6.25 + 0.4 * 10.0)

# A transcript predating the breakdown must degrade to the old answer. Reading
# the tiers alone and ignoring the flat field would price it at zero.
_legacy = spend.read_usage(transcript([call("d", **write(M))]), RATES)
check("no breakdown -> all 5m, nothing dropped", _legacy["cost"], 6.25)
check("no breakdown -> tokens still total 1M",
      float(_legacy["tokens"]["cache_write"] + _legacy["tokens"]["cache_write_1h"]), float(M))

# An unpriced model's tokens still count, its cost is excluded, and the call is
# reported with its reason. `<synthetic>` is not a model call at all.
def model_call(request_id, model, **usage):
    row = call(request_id, **usage)
    row["message"]["model"] = model
    return row


_mixed = spend.read_usage(transcript([
    call("e1", **write(M, ephemeral_1h=M)),
    model_call("e2", "cursor/claude-opus-5", **write(M)),
    model_call("e3", "<synthetic>", **write(M)),
]), RATES)
check("unpriced call's cost is excluded", _mixed["cost"], 10.0)
check_same("unpriced call is reported with count and reason", _mixed["unpriced"],
           {"cursor/claude-opus-5": {"calls": 1, "reason": "no cursor rate for claude-opus-5"}})
check("synthetic lines are not model calls", float(_mixed["steps"]), 2.0)
check("unpriced tokens still count", float(_mixed["tokens"]["cache_write"]), float(M))
_dash = spend.read_usage(transcript([model_call("e4", "cursor/composer-2.5", **write(M))]), RATES)
check_same("tokens in a null-priced bucket make the call unpriced",
           _dash["unpriced"]["cursor/composer-2.5"]["reason"],
           "composer-2.5 has no cache_write price")

# One API response occupies one transcript line per content block, each with an
# identical copy of `usage`. Summing lines overstated a measured bill by 2.23x.
_dup = spend.read_usage(
    transcript([call("f", **write(M, ephemeral_1h=M))] * 3), RATES)
check("3 content blocks, 1 response -> counted once", _dup["cost"], 10.0)
check("3 content blocks, 1 response -> 1 step", float(_dup["steps"]), 1.0)

# Context is every token the call carried, so both write tiers count.
_ctx = spend.read_usage(transcript([call("g", **write(M, ephemeral_1h=600_000))]), RATES)
check("context counts both write tiers", float(_ctx["context"]), float(M))

# on_line sees every raw line, including ones with no usage block. This is what
# lets orch.py add its relay counts without a second copy of the pricing loop.
_seen = []
spend.read_usage(transcript([{"type": "user", "message": {"content": "hi"}},
                             call("h", **write(M, ephemeral_1h=M))]),
                 RATES, on_line=_seen.append)
check("on_line observes non-usage lines too", float(len(_seen)), 2.0)

# The four hooks ship through two channels -- `plugin.json` for a marketplace
# install, `spend install` for the symlink path -- and nothing about a session
# that is missing its cost line tells you which channel delivered the hook that
# did not fire. So they are generated from one place and pinned here.
_manifest = os.path.join(HERE, "..", ".claude-plugin", "plugin.json")
with open(_manifest) as fh:
    check_same("plugin.json hooks match the generator",
               json.load(fh).get("hooks"), spend.desired_hooks_object())

# The bug this replaced: `install` baked in the absolute path of whichever copy
# of spend.py ran it. From a git worktree that path is reclaimed along with the
# worktree, and every hook ends in `exit 0`, so the whole plugin goes quiet
# without erroring. Resolution must therefore happen when the hook fires.
_installed = spend.hook_command("guard", marker=True)
check_same("install command carries no absolute path",
           os.path.realpath(spend.__file__) in _installed, False)
check_same("install command is the manifest one, plus a marker",
           _installed, spend.hook_command("guard") + "  # " + spend.HOOK_MARKER)

# Naming `python3` and letting PATH answer cost 14x on a machine with a pyenv
# shim first -- 1.25s per tool call at 6% CPU, blocked rather than computing,
# holding a shell open the whole time in every concurrent session. The script
# was never the expense; the name was. Prose did not hold this the first time,
# so it is pinned: every hook must run an interpreter it resolved itself.
for _action in (action for _, _, action in spend.DESIRED_HOOKS):
    _cmd = spend.hook_command(_action)
    check_same("%r resolves its own interpreter" % _action.split()[0],
               "PY=/usr/bin/python3" in _cmd and "SPEND_PYTHON" in _cmd, True)
    check_same("%r runs $PY, never a bare python3" % _action.split()[0],
               ' python3 "$d/scripts/spend.py"' in _cmd, False)

# The prefilter decides in shell what the guard would spend ~88ms of Python
# startup to decide. Several ways it can be silently wrong, all of which lose
# the signal rather than break anything:
_guard = spend.hook_command("guard")
# It consumes stdin, which `hook_payload` deliberately refuses to do on a
# terminal. Without this check ahead of the `cat`, an interactive run blocks
# forever holding a shell -- the exact failure the whole change is about.
check_same("guard checks for a terminal before reading stdin",
           _guard.index("-t 0") < _guard.index("$(cat)"), True)
# Filtering at GUARD_BYTES would drop every heredoc between the two floors, and
# heredoc detection is the guard's most actionable signal. Filtering at only the
# heredoc floor is the mirror bug: it swallows warnings for anyone who tuned
# GUARD_BYTES below it. Both floors are resolved at fire time; the smaller wins.
check_same("guard prefilter carries both payload floors, not one",
           str(spend.GUARD_HEREDOC_BYTES_DEFAULT) in _guard
           and str(spend.GUARD_BYTES_DEFAULT) in _guard, True)
# The override names are the ones `env()` honours, SPEND_ then ORCH_. Naming the
# bare constant here would read a threshold nobody set and ignore the tuned one.
for _name in ("SPEND_GUARD_HEREDOC_BYTES", "ORCH_GUARD_HEREDOC_BYTES",
              "SPEND_GUARD_BYTES", "ORCH_GUARD_BYTES"):
    check_same("guard prefilter reads %s" % _name, _name in _guard, True)
# `_unbounded_read_bytes` sizes the file, not the payload, so a Read can be
# small on the wire and still worth warning about. It must never be filtered.
check_same("guard prefilter always lets a Read through", "*Read*" in _guard, True)

# Everything above is a substring assertion, and the failure mode of generating
# shell out of Python is QUOTING, which no substring assertion can see. So the
# generated command is actually run, against the payload shapes whose handling
# differs. `sh` rather than the caller's shell: that is what a hook runs under.
_FLOOR_VARS = ("SPEND_GUARD_BYTES", "ORCH_GUARD_BYTES",
               "SPEND_GUARD_HEREDOC_BYTES", "ORCH_GUARD_HEREDOC_BYTES")


def guard_out(command=None, payload=None, **overrides):
    """stdout of the real guard hook for one payload. Fresh state dir each call,
    so the per-kind cooldown never makes an earlier case suppress a later one."""
    if payload is None:
        payload = {"tool_name": "Bash", "tool_input": {"command": command},
                   "cwd": HERE}
    env = {k: v for k, v in os.environ.items() if k not in _FLOOR_VARS}
    env.update(SPEND_SKILL_DIR=os.path.dirname(HERE),
               SPEND_STATE_HOME=tempfile.mkdtemp(), **overrides)
    return subprocess.run(
        ["sh", "-c", spend.hook_command("guard")],
        input=json.dumps(payload), text=True, env=env, timeout=60,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.strip()


check_same("live: an ordinary small command says nothing",
           guard_out("ls -la"), "")
check_same("live: a big inline doc warns",
           "inline doc" in guard_out("cat > /tmp/x.md <<EOF\n%s\nEOF" % ("x " * 900)),
           True)
# The regression the two-floor fix exists for: with GUARD_BYTES tuned under the
# heredoc floor, a payload between the two must still reach Python. A prefilter
# hardcoded at 1200 returns "" here and the tuned threshold is silently dead.
check_same("live: a floor tuned below the heredoc one is honoured",
           "input" in guard_out("echo " + "a" * 40, SPEND_GUARD_BYTES="20"), True)
# A Read payload is tiny on the wire; the file it names is not.
check_same("live: a whole-file Read of a big file warns", "read whole" in guard_out(
    payload={"tool_name": "Read",
             "tool_input": {"file_path": os.path.join(HERE, "spend.py")},
             "cwd": HERE}), True)
# The payload is attacker-adjacent data -- it is whatever the model just wrote.
# `p=$(cat)` and `printf %s "$p"` must never re-expand it. If either loses its
# quoting, this substitution runs and the marker appears.
_marker = os.path.join(tempfile.mkdtemp(), "expanded")
guard_out("echo '`touch %s`$(touch %s)' %s" % (_marker, _marker, "b" * 40),
          SPEND_GUARD_BYTES="20")
check_same("live: a payload is never re-expanded by the hook shell",
           os.path.exists(_marker), False)

# Step 7: the transcript lookup tries the session id before the cwd slug, so
# `spend cost` still finds this session's transcript from a subdirectory --
# where the cwd-slug lookup, keyed to the directory the session STARTED in,
# cannot.
_proj_base = tempfile.mkdtemp()
os.makedirs(os.path.join(_proj_base, "some-project-slug"))
_session_transcript = os.path.join(_proj_base, "some-project-slug", "sess-xyz.jsonl")
with open(_session_transcript, "w") as fh:
    fh.write(json.dumps(call("s1", **write(1000))) + "\n")
_env_saved = {k: os.environ.get(k) for k in
             ("SPEND_CLAUDE_PROJECTS_DIR", "CLAUDE_CODE_SESSION_ID")}
os.environ["SPEND_CLAUDE_PROJECTS_DIR"] = _proj_base
os.environ["CLAUDE_CODE_SESSION_ID"] = "sess-xyz"
try:
    check_same("transcript lookup finds this session by id",
               spend.find_transcript_by_session(), _session_transcript)

    class _Args:
        transcript = None
        repo = "/nonexistent/subdirectory/of/the/repo"

    check_same("find_transcript prefers the session id over the cwd slug",
               spend.find_transcript(_Args()), _session_transcript)
finally:
    for key, value in _env_saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
shutil.rmtree(_proj_base, ignore_errors=True)

# Step 5: `spend agents --write` writes one file per recommended Claude model,
# explicitly and only when asked -- never touching a file this tool did not
# generate itself, most concretely one of opencodex's `ocx-*` definitions.
_write_dir = tempfile.mkdtemp()
_write_out = subprocess.run(
    [sys.executable, os.path.join(HERE, "spend.py"), "agents",
     "--agents-dir", _write_dir, "--write", "--format", "json"],
    capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
_written = json.loads(_write_out.stdout)
check_same("agents --write reports wrote: true", _written["wrote"], True)
_haiku_path = os.path.join(_write_dir, "claude-haiku-4-5-20251001.md")
check_same("agents --write creates a file named for the canonical id",
           os.path.isfile(_haiku_path), True)
check_same("the written file's own model: frontmatter is the canonical id",
           spend.pricing_module().read_agent_definitions(_write_dir)
           ["claude-haiku-4-5-20251001"]["model"], "claude-haiku-4-5-20251001")

# Ruling (b): the default scope is only the Claude models a rung preference
# currently recommends, not every anthropic-route option. The shipped
# `model-options.json` has 8 anthropic-provider rows but only 3 appear in any
# rung's `preferences` list (haiku/minimal, sonnet-5-5/economy, opus-5-5/
# advanced+frontier); the other 5 (`claude-sonnet-4-6`, `claude-sonnet-5`,
# `claude-opus-4-8`, `claude-opus-5`, `claude-fable-5-1`) are options the rung/archetype system
# could select in principle but does not currently prefer.
check_same("agents --write default scope is the 3 currently-preferred Claude models",
           sorted(row["id"] for row in _written["models"]),
           ["claude-haiku-4-5-20251001", "claude-opus-5-5", "claude-sonnet-5-5"])
shutil.rmtree(_write_dir, ignore_errors=True)

# `--all` restores the full anthropic-option scope (8 models) -- this is the
# behaviour the default used to have unconditionally before ruling (b).
# Falsification: dropping `--all` from this invocation and re-running against
# the corrected `cmd_agents` reproduces the narrower 3-model default above,
# i.e. `--all` is the thing making the difference, not stale caching.
_all_dir = tempfile.mkdtemp()
_all_out = subprocess.run(
    [sys.executable, os.path.join(HERE, "spend.py"), "agents",
     "--agents-dir", _all_dir, "--all", "--write", "--format", "json"],
    capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
_all_written = json.loads(_all_out.stdout)
check_same("agents --write --all covers every anthropic model option",
           sorted(row["id"] for row in _all_written["models"]),
           sorted(["claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-sonnet-5", "claude-sonnet-5-5",
                   "claude-opus-4-8", "claude-opus-5", "claude-opus-5-5",
                   "claude-fable-5-1"]))
shutil.rmtree(_all_dir, ignore_errors=True)

_rewrite_dir = tempfile.mkdtemp()
with open(os.path.join(_rewrite_dir, "claude-sonnet-5-5.md"), "w") as fh:
    fh.write('---\nname: "claude-sonnet-5-5"\ndescription: "hand written"\n'
             'model: "claude-sonnet-5-5"\n---\n\n<!-- generated-by: opencodex -->\n')
_rerun = subprocess.run(
    [sys.executable, os.path.join(HERE, "spend.py"), "agents",
     "--agents-dir", _rewrite_dir, "--write", "--format", "json"],
    capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
_rerun_rows = {row["id"]: row for row in json.loads(_rerun.stdout)["models"]}
check_same("agents --write never overwrites a file it did not generate",
           _rerun_rows["claude-sonnet-5-5"]["skipped"], "generated by opencodex")
shutil.rmtree(_rewrite_dir, ignore_errors=True)

# `--prune` removes only files this tool stamped whose id fell out of scope.
# Falsification: dropping the `generated_by` check deletes `ocx-claude-opus-5`
# and the hand-written file, and the survivors check goes red.
_prune_dir = tempfile.mkdtemp()
for _name, _marker in (("claude-sonnet-5", "context-economy"),
                       ("ocx-claude-opus-5", "opencodex"),
                       ("hand-written", None)):
    with open(os.path.join(_prune_dir, "%s.md" % _name), "w") as fh:
        fh.write('---\nname: "%s"\nmodel: "claude-opus-5"\n---\n' % _name
                 + ("\n<!-- generated-by: %s -->\n" % _marker if _marker else ""))

def _prune(*extra):
    out = subprocess.run(
        [sys.executable, os.path.join(HERE, "spend.py"), "agents", "--agents-dir",
         _prune_dir, "--prune", "--format", "json"] + list(extra),
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    return json.loads(out.stdout)

_preview = _prune()
check_same("agents --prune previews the stale generated file",
           [row["id"] for row in _preview["pruned"]], ["claude-sonnet-5"])
check_same("agents --prune without --write deletes nothing",
           os.path.exists(os.path.join(_prune_dir, "claude-sonnet-5.md")), True)
_prune("--write")
check_same("agents --prune --write removes only its own stale file",
           sorted(f for f in os.listdir(_prune_dir) if f.endswith(".md")),
           ["claude-haiku-4-5-20251001.md", "claude-opus-5-5.md", "claude-sonnet-5-5.md",
            "hand-written.md", "ocx-claude-opus-5.md"])
check_same("agents --prune keeps a file the current scope still recommends",
           _prune("--write")["pruned"], [])
shutil.rmtree(_prune_dir, ignore_errors=True)

# Step 7: the rung hook stays silent when subagent_type names an agent
# definition that already pins a model -- the choice has already been made,
# even though the Task/Agent call itself carries no `model` field.
_rung_agents_dir = tempfile.mkdtemp()
with open(os.path.join(_rung_agents_dir, "ocx-claude-opus-5.md"), "w") as fh:
    fh.write('---\nname: "ocx-claude-opus-5"\ndescription: "Routed worker."\n'
             'model: "claude-ocx-cursor--claude-opus-5"\n---\n')


def rung_out(tool_input):
    payload = {"tool_name": "Task", "tool_input": tool_input}
    env = dict(os.environ, SPEND_AGENTS_DIR=_rung_agents_dir,
              SPEND_STATE_HOME=tempfile.mkdtemp())
    return subprocess.run(
        [sys.executable, os.path.join(HERE, "spend.py"), "rung"],
        input=json.dumps(payload), text=True, env=env, timeout=60,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.strip()


check_same("rung hook warns when model is unset and subagent_type is unset",
           "MODEL unset" in rung_out({}), True)
check_same("rung hook is silent when subagent_type pins a model",
           rung_out({"subagent_type": "ocx-claude-opus-5"}), "")
check_same("rung hook is silent when model is set explicitly",
           rung_out({"model": "opus"}), "")
shutil.rmtree(_rung_agents_dir, ignore_errors=True)

# The shipped catalogue. `preferences` only rank; the rung tags decide what a
# rung can select at all. `frontier` is a designation: the advanced-rung models
# judged capable enough for frontier work, and never a pricier model the map
# does not tag -- the owner's explicit cap on what an escalation can cost.
_shipped = spend.load_model_options()
_every_model = [{"slug": row["id"], "default_reasoning_level": "medium",
                 "supported_reasoning_levels": [
                     {"effort": "low"}, {"effort": "medium"}, {"effort": "high"}]}
                for row in _shipped["models"]]
check_same("frontier selects only the designated models",
           sorted(row["model"] for row in spend.select_models(
               _shipped, _every_model, "frontier", "default")),
           ["claude-opus-5-5", "gpt-5.6-sol"])
check_same("no rung selects the off-ladder frontier model",
           [rung for rung in spend.MODEL_RUNGS
            if "claude-fable-5-1" in [row["model"] for row in spend.select_models(
                _shipped, _every_model, rung, "default")]],
           [])

# Every "second pair of eyes" is one reviewer archetype: the old names resolve
# to it, so a brief written against any of them gets the same rung and family
# rule rather than an unanchored "any rung".
check_same("review-shaped names all resolve to the reviewer archetype",
           sorted({spend.resolve_archetype(name, _shipped["archetypes"])[0]
                   for name in ("premise-auditor", "adversarial-reviewer",
                                "second-opinion", "contrasting-opinion", "review")}),
           ["reviewer"])

# Effort is relative, so the verifier's step down survives on any model: on a
# model whose own default is medium, the implementer gets medium and the
# verifier the level below it. Both were `medium` before, which erased it.
def _archetype_effort(name):
    policy = _shipped["archetypes"][name]
    return spend.select_models(_shipped, [{"slug": "claude-sonnet-5",
                               "default_reasoning_level": "medium",
                               "supported_reasoning_levels": [
                                   {"effort": "low"}, {"effort": "medium"},
                                   {"effort": "high"}]}],
                               policy["rung"], policy["effort"])[0]["effort"]
check_same("implementer effort is the model's own default",
           _archetype_effort("implementer"), "medium")
check_same("verifier effort is one below the model's default",
           _archetype_effort("verifier"), "low")

_review_catalog = transcript([])
with open(_review_catalog, "w") as fh:
    json.dump({"models": [{"slug": "claude-sonnet-5"}, {"slug": "gpt-5.6-terra"}]}, fh)


def _spend_models(*argv):
    return subprocess.run(
        [sys.executable, os.path.join(HERE, "spend.py"), "models",
         "--catalog", _review_catalog, "--harness", "cursor", "--format", "json"]
        + list(argv), capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)


# spend exits 0 on every error so a hook can never fail a turn; a refusal is
# no result on stdout and the reason on stderr.
_no_family = _spend_models("--archetype", "reviewer")
check_same("reviewer without --exclude-family is refused",
           (_no_family.stdout, "--same-family-ok" in _no_family.stderr),
           ("", True))
check_same("every shipped model row names its lineage",
           [row["id"] for row in _shipped["models"] if not row.get("lineage")], [])
# Independence is judged on lineage, not family: excluding the author's
# claude-opus must also exclude claude-sonnet, or a Claude reviewer lands on
# Claude builders -- the exact failure the reviewer archetype exists to stop.
check_same("excluding a family excludes its whole lineage",
           [row["model"] for row in spend.select_models(
               _shipped, _every_model, "economy", "default", "claude-opus")
            if row["model"].startswith("claude-")], [])
_contrast = _spend_models("--archetype", "reviewer", "--exclude-family", "claude-opus")
check_same("reviewer resolves to a different family from the author",
           [row["model"] for row in json.loads(_contrast.stdout)["models"]],
           ["gpt-5.6-terra"])
_waived = _spend_models("--archetype", "reviewer", "--same-family-ok", "only claude reachable")
check_same("--same-family-ok waives the family rule and records why",
           json.loads(_waived.stdout)["same_family_ok"], "only claude reachable")
check_same("--rung without --effort asks for the model's own default effort",
           json.loads(_spend_models("--rung", "economy").stdout)["effort"], "default")

# rungs.md's table is the prose owner of the catalogue and model-options.json
# its machine form. Two copies of one table drifted before (verifier effort,
# missing archetypes); this fails the moment they disagree again.
_ROW_KEYS = {"Implementer": "implementer", "Analyst": "analyst", "Reviewer": "reviewer",
             "Verifier": "verifier", "Verifier, low-risk": "verifier-low-risk",
             "Doc writer": "doc-writer", "Inventory / cleanup": "inventory"}
with open(os.path.join(os.path.dirname(HERE), "skills", "delegating-economically",
                       "references", "rungs.md"), encoding="utf-8") as fh:
    _doc_rows = {}
    for line in fh:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 6 and cells[0].startswith("**"):
            _doc_rows[_ROW_KEYS.get(cells[0].strip("*"), cells[0])] = cells[3]
check_same("rungs.md table and model-options.json agree on rung / effort",
           _doc_rows,
           {key: "%s / %s" % (_shipped["archetypes"][key]["rung"],
                              _shipped["archetypes"][key]["effort"])
            for key in _ROW_KEYS.values()})

for path in _tmp:
    try:
        os.unlink(path)
    except OSError:
        pass

print()
if FAILURES:
    print("  %d FAILURE(S): %s" % (len(FAILURES), ", ".join(FAILURES)))
    sys.exit(1)
print("  all pass")
