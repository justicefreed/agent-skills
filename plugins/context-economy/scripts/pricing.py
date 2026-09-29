#!/usr/bin/env python3
"""Reviewed, route-aware pricing snapshots for bounded micro-operations.

The snapshot (``references/pricing/current.json``) is the single source of
model rates, the route registry and the input-alias tables. ``spend.py`` reads
the same snapshot through ``Registry`` to price historical transcripts; this
module makes prospective control-plane decisions. Both fail closed: a model with
no reviewed (route, canonical id) row is unpriced, never approximated.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


SCHEMA_VERSION = 2
OPTIONS_SCHEMA_VERSION = 3
# Policy the option map must obey, not just shape. Archetypes start at or below
# the economy anchor -- anything higher is an escalation, never a start -- and
# name effort relative to the model, because an absolute `medium` means a
# different thing on every model and silently erased the verifier's step down.
OPTION_RUNGS = ("minimal", "economy", "advanced", "frontier")
ARCHETYPE_START_RUNGS = ("minimal", "economy")
ARCHETYPE_EFFORTS = ("lowest", "one-below-default", "default")
GENERATOR_VERSION = "2"
ROUTE_SOURCES = {
    "vercel": "https://ai-gateway.vercel.sh/v1/models",
    "openrouter": "https://openrouter.ai/api/v1/models",
}
# A rate row carries exactly one of these field sets. Cursor and OpenAI publish
# one cache-write price; Anthropic publishes a 5-minute and a 1-hour price, and
# collapsing those two into one number is how 1h writes got billed at the 5m rate.
FLAT_RATES = ("input", "cache_write", "cache_read", "output")
TIERED_RATES = ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output")
ALLOWED_CACHE_EVIDENCE = ("documented", "observed", "assumed", "unknown")
ELIGIBLE_CACHE_EVIDENCE = {"documented", "observed"}
# Transcript markers that are not model calls at all. They are skipped, not
# reported as unpriced: there is nothing to price.
NOT_MODEL_CALLS = frozenset(("<synthetic>",))


class PricingError(Exception):
    """A safe, user-facing pricing-policy failure."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise PricingError("%s must be an ISO-8601 timestamp" % field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PricingError("%s is not an ISO-8601 timestamp" % field) from exc
    if parsed.tzinfo is None:
        raise PricingError("%s must include a timezone" % field)
    return parsed.astimezone(timezone.utc)


def _decimal(value: Any, field: str, allow_none: bool = True) -> Optional[Decimal]:
    if value is None and allow_none:
        return None
    if isinstance(value, bool):
        raise PricingError("%s must be a decimal string or null" % field)
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise PricingError("%s must be a decimal string or null" % field) from exc
    if not parsed.is_finite() or parsed < 0:
        raise PricingError("%s must be a finite non-negative decimal" % field)
    return parsed


def _decimal_text(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else format(value, "f")


def default_snapshot_path() -> Path:
    return Path(__file__).resolve().parent.parent / "references" / "pricing" / "current.json"


def default_options_path() -> Path:
    return (Path(__file__).resolve().parent.parent / "skills" /
            "delegating-economically" / "references" / "model-options.json")


def detect_harness(explicit: Optional[str] = None) -> Dict[str, str]:
    """The harness in effect, and how that was decided.

    Order: an explicit value (the `--harness` flag) first; then
    `CLAUDECODE` or `CLAUDE_CODE_SESSION_ID` -> `claude-code`; then
    `CODEX_HOME` -> `codex`; otherwise `cursor`, the harness with no
    session-environment fingerprint of its own. Every result names its
    source so a caller never has to guess why a harness came out the way
    it did -- unlike the placeholder this replaces, which always said
    `cursor` and left the reason to context.
    """
    if explicit:
        return {"harness": explicit, "detected_by": "--harness"}
    if os.environ.get("CLAUDECODE"):
        return {"harness": "claude-code", "detected_by": "CLAUDECODE"}
    if os.environ.get("CLAUDE_CODE_SESSION_ID"):
        return {"harness": "claude-code", "detected_by": "CLAUDE_CODE_SESSION_ID"}
    if os.environ.get("CODEX_HOME"):
        return {"harness": "codex", "detected_by": "CODEX_HOME"}
    return {"harness": "cursor", "detected_by": "fallback"}


def default_agents_dir() -> str:
    """Where Claude Code agent definitions live, overridable for tests.

    `SPEND_AGENTS_DIR` / `ORCH_AGENTS_DIR` follow the same override
    convention as every other path in this plugin, so a test can point this
    at a fixture directory instead of the real `~/.claude/agents` -- which
    `spend agents --write` must never touch except when explicitly told to.
    """
    override = os.environ.get("SPEND_AGENTS_DIR") or os.environ.get("ORCH_AGENTS_DIR")
    if override:
        return os.path.expanduser(override)
    return os.path.join(os.path.expanduser("~"), ".claude", "agents")


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n", re.DOTALL)
_GENERATED_BY_RE = re.compile(r"<!--\s*generated-by:\s*(\S+?)\s*-->")


def _parse_frontmatter(text: str) -> Optional[Dict[str, str]]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None
    fields: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            fields[key] = value
    return fields


def read_agent_definitions(agents_dir: Optional[str] = None) -> Dict[str, Dict[str, Optional[str]]]:
    """Every agent file's declared model and generator, keyed by agent name.

    `name` comes from the file's own frontmatter, falling back to the
    filename, so a lookup by `subagent_type` and a lookup by canonical id
    both work the same way regardless of who wrote the file. This never
    writes anything; `spend agents --write` is the only path that does.
    """
    directory = agents_dir or default_agents_dir()
    found: Dict[str, Dict[str, Optional[str]]] = {}
    try:
        filenames = sorted(f for f in os.listdir(directory) if f.endswith(".md"))
    except OSError:
        return found
    for filename in filenames:
        path = os.path.join(directory, filename)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        frontmatter = _parse_frontmatter(text)
        if not frontmatter or not frontmatter.get("model"):
            continue
        name = frontmatter.get("name") or filename[:-3]
        generated = _GENERATED_BY_RE.search(text)
        found[name] = {"model": frontmatter["model"],
                       "generated_by": generated.group(1) if generated else None,
                       "path": path}
    return found


def load_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PricingError("cannot read %s: %s" % (path, exc))
    if not isinstance(data, dict):
        raise PricingError("%s must contain a JSON object" % path)
    return data


def rate_fields(rates: Any, label: str) -> Dict[str, Optional[Decimal]]:
    """Parse one rate object, which must be exactly flat or exactly tiered."""
    if not isinstance(rates, dict):
        raise PricingError("%s has no rates object" % label)
    keys = set(rates)
    for fields in (FLAT_RATES, TIERED_RATES):
        if keys == set(fields):
            return {name: _decimal(rates[name], "%s rates.%s" % (label, name))
                    for name in fields}
    raise PricingError("%s rates must be exactly {%s} or {%s}; got {%s}"
                       % (label, ", ".join(FLAT_RATES), ", ".join(TIERED_RATES),
                          ", ".join(sorted(keys))))


def switch_write_field(rates: Dict[str, Any]) -> str:
    """The cache-write price a micro-operation switch pays.

    A switch writes a prefix that is read back within minutes, so a tiered
    route bills it at the 5-minute rate.
    """
    return "cache_write_5m" if "cache_write_5m" in rates else "cache_write"


# --------------------------------------------------------------------------- #
# registry: canonical ids, route names, input aliases
# --------------------------------------------------------------------------- #
#
# The canonical id is the provider's own API id. Every other spelling -- a
# Cursor slug, an ocx-routed name, a harness alias -- is a name that maps to one.
# Stored data (model options, rate rows) uses canonical ids only; names and
# aliases exist so input can be translated, never so output can use them.

def _validate_registry(snapshot: Dict[str, Any], source_ids: set) -> List[str]:
    warnings: List[str] = []
    routes = snapshot.get("routes")
    if not isinstance(routes, dict) or not routes:
        raise PricingError("snapshot must contain a non-empty routes object")
    for route_id, route in routes.items():
        if not isinstance(route, dict):
            raise PricingError("route %r must be an object" % route_id)
        harnesses = route.get("harnesses")
        if not isinstance(harnesses, list) or not all(isinstance(h, str) and h for h in harnesses):
            raise PricingError("route %r must list its harnesses" % route_id)
        prefix = route.get("prefix")
        if prefix is not None and (not isinstance(prefix, str) or not prefix):
            raise PricingError("route %r prefix must be a non-empty string" % route_id)
        billing = route.get("billing_route")
        if billing is not None:
            if billing not in routes or routes[billing].get("billing_route"):
                raise PricingError("route %r bills through %r, which is not a pricing route"
                                   % (route_id, billing))

    models = snapshot.get("models")
    if not isinstance(models, list) or not models:
        raise PricingError("snapshot must contain a non-empty models list")
    model_ids = set()
    for row in models:
        if not isinstance(row, dict):
            raise PricingError("model entry must be an object")
        model_id = row.get("id")
        if not isinstance(model_id, str) or not model_id:
            raise PricingError("model entry has no id")
        if model_id in model_ids:
            raise PricingError("duplicate canonical model %r" % model_id)
        for field in ("provider", "source"):
            if not isinstance(row.get(field), str) or not row.get(field):
                raise PricingError("model %r has no %s" % (model_id, field))
        model_ids.add(model_id)

    # Every name and alias must resolve to exactly one canonical id, and none
    # may shadow a canonical id: an input that is both would be translated or
    # not depending on lookup order.
    resolved_to: Dict[str, str] = {}

    def claim(name: str, model: str, what: str) -> None:
        if not isinstance(name, str) or not name:
            raise PricingError("%s has an empty name" % what)
        if name in model_ids:
            raise PricingError("%s %r is also a canonical id" % (what, name))
        if model not in model_ids:
            raise PricingError("%s %r maps to %r, which is not a canonical id"
                               % (what, name, model))
        prior = resolved_to.get(name)
        if prior is not None and prior != model:
            raise PricingError("%s %r resolves to both %r and %r"
                               % (what, name, prior, model))
        resolved_to[name] = model

    names = snapshot.get("names", [])
    if not isinstance(names, list):
        raise PricingError("snapshot names must be a list")
    for row in names:
        if not isinstance(row, dict):
            raise PricingError("name entry must be an object")
        if row.get("route") not in routes:
            raise PricingError("name %r refers to unknown route %r"
                               % (row.get("name"), row.get("route")))
        claim(row.get("name"), row.get("model"), "route name")

    aliases = snapshot.get("aliases", {})
    if not isinstance(aliases, dict):
        raise PricingError("snapshot aliases must be an object")
    harnesses = {h for route in routes.values() for h in route["harnesses"]}
    for table_id, table in aliases.items():
        if not isinstance(table, dict) or not isinstance(table.get("map"), dict):
            raise PricingError("alias table %r must have a map" % table_id)
        if not isinstance(table.get("retrieved_at"), str) or not table["retrieved_at"]:
            raise PricingError("alias table %r must be dated (aliases move)" % table_id)
        route = table.get("route")
        if route is not None and route not in routes:
            raise PricingError("alias table %r refers to unknown route %r" % (table_id, route))
        if route is None and table_id not in harnesses:
            raise PricingError("alias table %r names neither a harness nor a route" % table_id)
        for alias, model in table["map"].items():
            claim(alias, model, "alias")

    rates = snapshot.get("rates")
    if not isinstance(rates, list) or not rates:
        raise PricingError("snapshot must contain non-empty rates")
    seen = set()
    for row in rates:
        if not isinstance(row, dict):
            raise PricingError("rate entry must be an object")
        route, model = row.get("route"), row.get("model")
        label = "rate (%s, %s)" % (route, model)
        if route not in routes:
            raise PricingError("%s refers to unknown route" % label)
        if routes[route].get("billing_route"):
            raise PricingError("%s: route %r bills as %r; key the row there"
                               % (label, route, routes[route]["billing_route"]))
        if model not in model_ids:
            raise PricingError("%s: %r is not a canonical id" % (label, model))
        if (route, model) in seen:
            raise PricingError("duplicate %s" % label)
        seen.add((route, model))
        if row.get("source_id") not in source_ids:
            raise PricingError("%s refers to unknown source" % label)
        evidence = (row.get("cache_semantics") or {}).get("evidence")
        if evidence not in ALLOWED_CACHE_EVIDENCE:
            raise PricingError("%s has invalid cache evidence" % label)
        parsed = rate_fields(row.get("rates"), label)
        missing = [name for name, value in parsed.items() if value is None]
        if missing:
            warnings.append("%s/%s: missing %s" % (route, model, ", ".join(missing)))
        if evidence not in ELIGIBLE_CACHE_EVIDENCE:
            warnings.append("%s/%s: cache semantics %s" % (route, model, evidence))
    return warnings


def validate_snapshot(snapshot: Dict[str, Any], now: Optional[datetime] = None) -> List[str]:
    """Validate shape and return non-fatal policy warnings.

    A partial snapshot is valid evidence but cannot make a route eligible. This
    distinction records unavailable routes without inventing zero prices.
    """
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise PricingError("unsupported pricing schema_version %r" % snapshot.get("schema_version"))
    for field in ("snapshot_id", "generator_version", "generated_at", "refresh_after", "expires_at"):
        if not snapshot.get(field):
            raise PricingError("snapshot has no %s" % field)
    generated = _parse_time(snapshot["generated_at"], "generated_at")
    refresh_after = _parse_time(snapshot["refresh_after"], "refresh_after")
    expires = _parse_time(snapshot["expires_at"], "expires_at")
    if not generated <= refresh_after <= expires:
        raise PricingError("snapshot timestamps must satisfy generated <= refresh <= expiry")
    if snapshot.get("currency") != "USD" or snapshot.get("unit") != "per_million_tokens":
        raise PricingError("snapshot must use USD per_million_tokens")
    sources = snapshot.get("sources")
    if not isinstance(sources, list) or not sources:
        raise PricingError("snapshot must contain non-empty sources")
    source_ids = set()
    for source in sources:
        if not isinstance(source, dict):
            raise PricingError("source entry must be an object")
        for field in ("id", "provider", "url", "retrieved_at", "payload_sha256"):
            if not source.get(field):
                raise PricingError("source has no %s" % field)
        _parse_time(source["retrieved_at"], "source.retrieved_at")
        if len(str(source["payload_sha256"])) != 64:
            raise PricingError("source payload_sha256 must be a SHA-256 digest")
        source_ids.add(source["id"])
    warnings = _validate_registry(snapshot, source_ids)
    if snapshot.get("validation_status") not in ("valid", "partial"):
        raise PricingError("validation_status must be valid or partial")
    now = now or _now()
    if now > expires:
        warnings.append("snapshot expired at %s" % snapshot["expires_at"])
    elif now > refresh_after:
        warnings.append("snapshot stale since %s" % snapshot["refresh_after"])
    return warnings


def load_snapshot(path: Optional[str] = None) -> Tuple[Path, Dict[str, Any], List[str]]:
    resolved = Path(path).expanduser() if path else default_snapshot_path()
    snapshot = load_json(resolved)
    return resolved, snapshot, validate_snapshot(snapshot)


class Registry:
    """Read-only view of a validated snapshot's routes, names, aliases and rates."""

    def __init__(self, snapshot: Dict[str, Any]):
        self.snapshot_id = snapshot["snapshot_id"]
        self.table_date = snapshot["generated_at"][:10]
        self.routes: Dict[str, Dict[str, Any]] = snapshot["routes"]
        self.models: Dict[str, Dict[str, Any]] = {m["id"]: m for m in snapshot["models"]}
        self.names: Dict[Tuple[str, str], str] = {
            (row["route"], row["name"]): row["model"] for row in snapshot.get("names", [])}
        self.aliases: Dict[str, Dict[str, Any]] = snapshot.get("aliases", {})
        self.rates: Dict[Tuple[str, str], Dict[str, Any]] = {
            (row["route"], row["model"]): row for row in snapshot["rates"]}

    def billing_route(self, route: str) -> str:
        return self.routes[route].get("billing_route") or route

    def rate_row(self, route: Optional[str], model: str) -> Optional[Dict[str, Any]]:
        if route is None:
            return None
        return self.rates.get((self.billing_route(route), model))

    def native_route(self, model: str) -> Optional[str]:
        """The route a bare canonical id arrives on: the one named for its provider."""
        provider = self.models[model]["provider"]
        return provider if provider in self.routes else None

    def routes_for_harness(self, harness: str) -> List[str]:
        return [route_id for route_id, route in self.routes.items()
                if harness in route["harnesses"]]

    def known_names(self) -> set:
        """Every spelling that is not a canonical id: route names, their prefixed
        forms (`cursor/claude-sonnet-5`), and aliases."""
        found = {name for _, name in self.names}
        for route_id, route in self.routes.items():
            prefix = route.get("prefix")
            if prefix:
                found.update(prefix + model for model in self.models)
                found.update(prefix + name for rid, name in self.names if rid == route_id)
        for table in self.aliases.values():
            found.update(table["map"])
        return found

    def _route_candidates(self, value: str) -> List[Tuple[Optional[str], str]]:
        # Case-folded: provider ids, names and prefixes are all lowercase, so
        # this is normalization (`cursor/GPT-5.6-sol` -> `gpt-5.6-sol`), not a
        # guess -- unlike an alias, there is exactly one thing a re-cased
        # provider id or route name could mean.
        value = value.lower()
        prefixed = sorted(((route_id, route["prefix"]) for route_id, route in self.routes.items()
                           if route.get("prefix")), key=lambda item: -len(item[1]))
        for route_id, prefix in prefixed:
            if value.startswith(prefix):
                rest = value[len(prefix):]
                model = self.names.get((route_id, rest)) or (rest if rest in self.models else None)
                return [(route_id, model)] if model else []
        if value in self.models:
            return [(self.native_route(value), value)]
        found = [(route_id, model) for (route_id, name), model in self.names.items()
                 if name == value]
        for table in self.aliases.values():
            if table.get("route") and value in table["map"]:
                found.append((table["route"], table["map"][value]))
        return found

    def resolve_route_name(self, value: str) -> Optional[Tuple[Optional[str], str]]:
        """A transcript or catalog model string -> (route, canonical id), or None.

        A route prefix names the route (`cursor/`, `claude-ocx-cursor--`); a bare
        canonical id arrives on its provider's route. The route is None when the
        id is known but no registered route carries it bare.
        """
        found = self._route_candidates((value or "").strip())
        if len({model for _, model in found}) != 1:
            return None
        return found[0]

    def resolve_model(self, name: str, harness: str) -> Dict[str, Any]:
        """Translate one input model name to its canonical id.

        Canonical ids pass through. Route names and aliases are translated and
        the translation is reported with the table's date. Unknown or ambiguous
        input is an error, never a guess.
        """
        value = (name or "").strip()
        if value in self.models:
            return {"model": value}
        hits = []
        for table_id, table in self.aliases.items():
            applies = table_id == harness or table.get("route") in self.routes_for_harness(harness)
            if applies and value in table["map"]:
                hits.append((table_id, table))
        candidates = {table["map"][value] for _, table in hits}
        if len(candidates) > 1:
            raise PricingError("model %r is ambiguous under harness %r: %s"
                               % (name, harness, ", ".join(sorted(candidates))))
        if hits:
            table_id, table = hits[0]
            return {"model": table["map"][value], "translated_from": value,
                    "alias_table": table["retrieved_at"], "alias_source": table_id}
        found = self._route_candidates(value)
        candidates = {model for _, model in found}
        if len(candidates) > 1:
            raise PricingError("model %r is ambiguous: %s" % (name, ", ".join(sorted(candidates))))
        if candidates:
            route, model = found[0]
            return {"model": model, "translated_from": value,
                    "alias_table": self.table_date, "alias_source": "route:%s" % route}
        raise PricingError("unknown model %r under harness %r; use a canonical id"
                           % (name, harness))

    def priced_route(self, model: str, harness: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """The first of the harness's routes with a reviewed rate for this id."""
        for route in self.routes_for_harness(harness):
            row = self.rate_row(route, model)
            if row is not None:
                return route, row
        return None, None


def resolve_model(name: str, harness: str, registry: Optional[Registry] = None) -> Dict[str, Any]:
    """The one input translation every `--model`/`--source-model` goes through.

    `harness` is required: which aliases apply depends on it. Harness detection
    (plan step 5) decides the value; this function never guesses one.
    """
    if registry is None:
        _, snapshot, _ = load_snapshot()
        registry = Registry(snapshot)
    return registry.resolve_model(name, harness)


def index_agents_by_model(agents: Dict[str, Dict[str, Optional[str]]],
                          registry: Registry) -> Dict[str, List[Dict[str, str]]]:
    """Canonical id -> every agent definition that resolves to it.

    An agent's `model:` frontmatter is a route name or a bare canonical id,
    never an alias -- opencodex and this registry both write route-carrying
    values -- so this goes through `resolve_route_name`, not `resolve_model`.
    """
    index: Dict[str, List[Dict[str, str]]] = {}
    for name, info in agents.items():
        resolved = registry.resolve_route_name(info["model"] or "")
        if not resolved or resolved[0] is None:
            continue
        route, model = resolved
        index.setdefault(model, []).append({"name": name, "route": route})
    return index


def claude_code_catalog(registry: Registry,
                        agents_dir: Optional[str] = None) -> Tuple[str, List[Dict[str, Any]]]:
    """The Claude Code model catalog: derived, never shipped.

    A bare canonical id is reachable on its native route (`anthropic`) with
    no extra condition -- the registry already says Claude Code can reach
    it. A prefixed route (`ocx-cursor`) is restricted to models with a
    matching agent definition under `agents_dir`: opencodex, not this
    registry, decides which Cursor-routed models this session can actually
    spawn, and a model the registry prices but opencodex never wired up is
    not reachable here even though `resolve_route_name` would happily price
    it from a transcript.
    """
    directory = agents_dir or default_agents_dir()
    agent_index = index_agents_by_model(read_agent_definitions(directory), registry)
    rows: List[Dict[str, Any]] = []
    for route in registry.routes_for_harness("claude-code"):
        prefix = registry.routes[route].get("prefix")
        if not prefix:
            for model in registry.models:
                if registry.native_route(model) == route:
                    rows.append({"slug": model})
            continue
        for model, entries in agent_index.items():
            for entry in entries:
                if entry["route"] == route:
                    rows.append({"slug": prefix + model, "agent": entry["name"]})
    return directory, rows


def spawn_field(model: str, family: Optional[str], harness: str,
                registry: Registry,
                agent_index: Dict[str, List[Dict[str, str]]]) -> Dict[str, Any]:
    """The value the Claude Code Agent tool accepts to spawn this canonical id.

    `spawn` must stay on the route the recommendation was priced on
    (`registry.priced_route`) -- otherwise the number `spend models` printed
    and the bill the spawn actually incurs would name two different routes.
    Within that route, in order: an agent definition named for the canonical
    id; any other agent definition already on that route (this covers a
    model whose priced route *is* a prefixed one, e.g. `ocx-cursor` billing
    directly -- the plan's literal "id-named agent, then alias" pair is
    silent on this case, since it was written for the anthropic-native case
    where an id-named agent and the priced route coincide); a harness alias,
    but only when the dated alias table still maps it to exactly this id. A
    stale alias -- the table's `opus` pointing at last generation's Opus
    while this id is the new one -- is refused rather than silently spawning
    the wrong model.

    A routed agent definition on a *different* route (an `ocx-*` bridge for
    a model priced on `anthropic`) is a different bill for the same model; it
    is never `spawn`, only a `via` alternative naming its own route and price.
    """
    entries = agent_index.get(model, [])
    priced_route, _ = registry.priced_route(model, harness)
    on_route = [e for e in entries if priced_route is not None and e["route"] == priced_route]
    off_route = [e for e in entries if e not in on_route]

    spawn: Dict[str, Any]
    if priced_route is None:
        spawn = {"kind": "error", "error": "no reviewed price for %r under harness %r" % (model, harness)}
    else:
        spawn = None
        named = next((e for e in on_route if e["name"] == model), None)
        if named:
            spawn = {"kind": "agent", "value": model, "route": priced_route}
        if spawn is None:
            alias_name = family[len("claude-"):] if family and family.startswith("claude-") else None
            if alias_name:
                for table_id, table in registry.aliases.items():
                    applies = (table.get("route") == priced_route or
                              (table.get("route") is None and table_id == harness and
                               registry.native_route(model) == priced_route))
                    if not applies or alias_name not in table["map"]:
                        continue
                    mapped = table["map"][alias_name]
                    if mapped == model:
                        spawn = {"kind": "alias", "value": alias_name,
                                "alias_table": table["retrieved_at"], "route": priced_route}
                    else:
                        spawn = {"kind": "error", "route": priced_route,
                                "error": "alias %r drifted to %r, not %r"
                                        % (alias_name, mapped, model)}
                    break
        if spawn is None and on_route:
            entry = on_route[0]
            spawn = {"kind": "routed-agent", "value": entry["name"], "route": priced_route}
        if spawn is None:
            spawn = {"kind": "error", "route": priced_route,
                    "error": "no agent definition or alias spawns %r on %r" % (model, priced_route)}

    via = []
    for entry in off_route:
        row = registry.rate_row(entry["route"], model)
        via.append({"route": entry["route"], "value": entry["name"],
                    "rates": row["rates"] if row else None})
    return {"spawn": spawn, "via": via}


def validate_options(options: Dict[str, Any], registry: Registry) -> None:
    """Every policy row is a canonical id, known to the registry, exactly once."""
    if options.get("schema_version") != OPTIONS_SCHEMA_VERSION:
        raise PricingError("unsupported model options schema_version %r"
                           % options.get("schema_version"))
    models = options.get("models")
    if not isinstance(models, list) or not models:
        raise PricingError("model options has no models list")
    model_ids = set()
    for row in models:
        if not isinstance(row, dict):
            raise PricingError("model policy entry must be an object")
        model_id = row.get("id")
        if not isinstance(model_id, str) or not model_id:
            raise PricingError("model policy entry has no id")
        if "pricing_key" in row:
            raise PricingError("model %r has a pricing_key; price comes from the route in effect"
                               % model_id)
        if model_id not in registry.models:
            raise PricingError("model option %r is not a canonical id in the registry" % model_id)
        if row.get("provider") != registry.models[model_id]["provider"]:
            raise PricingError("model option %r has provider %r; the registry says %r"
                               % (model_id, row.get("provider"),
                                  registry.models[model_id]["provider"]))
        if model_id in model_ids:
            raise PricingError("duplicate model policy id %r" % model_id)
        model_ids.add(model_id)
        for rung in row.get("rungs", []):
            if rung not in OPTION_RUNGS:
                raise PricingError("model option %r has unknown rung %r" % (model_id, rung))
    tagged = {row["id"]: set(row.get("rungs", [])) for row in models}
    for rung, preferred in (options.get("preferences") or {}).items():
        for model_id in preferred:
            if model_id not in model_ids:
                raise PricingError("preference %s -> %r is not a model option" % (rung, model_id))
            # Preferences only rank; the rung tags decide eligibility. A
            # preference the tags do not back is a ranking nobody can select.
            if rung not in tagged[model_id]:
                raise PricingError("preference %s -> %r is not tagged %s in its model row"
                                   % (rung, model_id, rung))
    for name, policy in (options.get("archetypes") or {}).items():
        if policy.get("rung") not in ARCHETYPE_START_RUNGS:
            raise PricingError("archetype %r starts at %r; archetypes start at %s and "
                               "reach higher only by escalation"
                               % (name, policy.get("rung"), " or ".join(ARCHETYPE_START_RUNGS)))
        if policy.get("effort") not in ARCHETYPE_EFFORTS:
            raise PricingError("archetype %r effort %r must be relative: %s"
                               % (name, policy.get("effort"), ", ".join(ARCHETYPE_EFFORTS)))


def _model_policy(options: Dict[str, Any], model: str) -> Dict[str, Any]:
    matches = [row for row in options["models"] if row.get("id") == model]
    if len(matches) != 1:
        raise PricingError("model %r has no unique policy entry" % model)
    return matches[0]


def _availability_reasons(row: Optional[Dict[str, Any]], role: str, harness: str) -> List[str]:
    if row is None:
        return ["%s has no reviewed price on a %s route" % (role, harness)]
    rates = rate_fields(row["rates"], role)
    missing = [name for name, value in rates.items() if value is None]
    if missing:
        return ["%s lacks %s pricing" % (role, ", ".join(missing))]
    evidence = row["cache_semantics"]["evidence"]
    if evidence not in ELIGIBLE_CACHE_EVIDENCE:
        return ["%s cache semantics are %s" % (role, evidence)]
    return []


def eligibility(snapshot: Dict[str, Any], options: Dict[str, Any], target_model: str,
                source_model: str, actions: int = 2,
                now: Optional[datetime] = None,
                harness: Optional[str] = None) -> Dict[str, Any]:
    """Calculate the documented cache-only estimate and all rejection reasons."""
    if actions not in (2, 3):
        raise PricingError("micro-operation actions must be 2 or 3")
    detected = detect_harness(harness)
    harness = detected["harness"]
    warnings = validate_snapshot(snapshot, now)
    registry = Registry(snapshot)
    validate_options(options, registry)
    target_in = registry.resolve_model(target_model, harness)
    source_in = registry.resolve_model(source_model, harness)
    target_id, source_id = target_in["model"], source_in["model"]
    _model_policy(options, target_id)
    result: Dict[str, Any] = {
        "snapshot_id": snapshot["snapshot_id"], "harness": harness,
        "harness_source": detected["detected_by"],
        "target_model": target_id, "source_model": source_id,
        "actions": actions, "eligible": False, "reasons": [], "warnings": warnings,
        "assumptions": [
            "cache-only calculation; excludes fresh input, output, replay, tools, and quality costs",
            "each target turn after the first is billed as a cache read",
            "a tiered route bills the switch write at its 5-minute cache-write rate",
        ],
    }
    translations = [dict(field=field, **{k: v for k, v in resolved.items() if k != "model"})
                    for field, resolved in (("target_model", target_in), ("source_model", source_in))
                    if "translated_from" in resolved]
    if translations:
        result["translations"] = translations
    if any(w.startswith("snapshot stale") or w.startswith("snapshot expired") for w in warnings):
        result["reasons"].append("snapshot is stale or expired")
    target_route, target = registry.priced_route(target_id, harness)
    source_route, source = registry.priced_route(source_id, harness)
    result["target_route"] = target_route
    result["source_route"] = source_route
    result["reasons"].extend(_availability_reasons(target, "target", harness))
    result["reasons"].extend(_availability_reasons(source, "source", harness))
    if result["reasons"]:
        return result
    assert target is not None and source is not None
    target_rates = rate_fields(target["rates"], "target")
    source_rates = rate_fields(source["rates"], "source")
    write = target_rates[switch_write_field(target_rates)]
    target_read = target_rates["cache_read"]
    source_read = source_rates["cache_read"]
    assert write is not None and target_read is not None and source_read is not None
    per_million_savings = Decimal(actions) * source_read - write - Decimal(actions - 1) * target_read
    result["per_million"] = {
        "continue": _decimal_text(Decimal(actions) * source_read),
        "switch": _decimal_text(write + Decimal(actions - 1) * target_read),
        "savings": _decimal_text(per_million_savings),
    }
    if write >= Decimal("0.40"):
        result["reasons"].append("target cache_write must be below $0.40/M")
    if target_read > Decimal("0.10"):
        result["reasons"].append("target cache_read must be at or below $0.10/M")
    if source_read < Decimal("0.25"):
        result["reasons"].append("source cache_read must be at or above $0.25/M")
    if per_million_savings <= 0:
        result["reasons"].append("cache-only estimate is not positive")
    result["eligible"] = not result["reasons"]
    return result


def _fetch(url: str) -> Tuple[bytes, Dict[str, str]]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read(), dict(response.headers.items())
    except (OSError, urllib.error.HTTPError) as exc:
        raise PricingError("refresh failed for %s: %s" % (url, exc))


def candidate_refresh(provider: str, offline: bool) -> Dict[str, Any]:
    if provider not in ROUTE_SOURCES:
        raise PricingError("automatic refresh is unsupported for provider %r" % provider)
    if offline:
        raise PricingError("offline refresh has no locally staged candidate")
    payload, headers = _fetch(ROUTE_SOURCES[provider])
    try:
        decoded = json.loads(payload)
    except ValueError as exc:
        raise PricingError("refresh returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise PricingError("refresh returned a non-object JSON payload")
    return {
        "provider": provider, "url": ROUTE_SOURCES[provider],
        "retrieved_at": _now().isoformat(),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "http_cache_control": headers.get("Cache-Control"),
        "record_count": len(decoded.get("data", [])) if isinstance(decoded.get("data"), list) else None,
        "status": "candidate-only",
        "warning": ("Downloaded data is not activated. Route mapping, cache semantics, "
                    "and material price changes require manual review."),
    }


def _load_options(args: argparse.Namespace) -> Dict[str, Any]:
    return load_json(Path(args.options).expanduser() if args.options else default_options_path())


def cmd_validate(args: argparse.Namespace) -> int:
    path, snapshot, warnings = load_snapshot(args.snapshot)
    options = _load_options(args)
    validate_options(options, Registry(snapshot))
    print(json.dumps({"snapshot": str(path), "snapshot_id": snapshot["snapshot_id"],
                      "options_schema_version": options["schema_version"],
                      "valid": True, "warnings": warnings}, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    path, snapshot, warnings = load_snapshot(args.snapshot)
    print(json.dumps({"snapshot": str(path), "snapshot_id": snapshot["snapshot_id"],
                      "validation_status": snapshot["validation_status"],
                      "generated_at": snapshot["generated_at"],
                      "refresh_after": snapshot["refresh_after"],
                      "expires_at": snapshot["expires_at"], "routes": len(snapshot["routes"]),
                      "models": len(snapshot["models"]), "rates": len(snapshot["rates"]),
                      "warnings": warnings}, indent=2))
    return 0


def cmd_eligibility(args: argparse.Namespace) -> int:
    _, snapshot, _ = load_snapshot(args.snapshot)
    result = eligibility(snapshot, _load_options(args), args.model, args.source_model,
                         args.actions, harness=args.harness)
    print(json.dumps(result, indent=2))
    return 0 if result["eligible"] else 2


def cmd_eligible_models(args: argparse.Namespace) -> int:
    _, snapshot, _ = load_snapshot(args.snapshot)
    options = _load_options(args)
    detected = detect_harness(args.harness)
    harness = detected["harness"]
    source = Registry(snapshot).resolve_model(args.source_model, harness)
    rows = []
    for policy in options.get("models", []):
        if args.rung not in policy.get("rungs", []):
            continue
        result = eligibility(snapshot, options, policy["id"], source["model"], args.actions,
                             harness=harness)
        rows.append({"model": policy["id"], "eligible": result["eligible"],
                     "reasons": result["reasons"], "target_route": result["target_route"]})
    output = {"rung": args.rung, "harness": harness, "harness_source": detected["detected_by"],
              "source_model": source["model"], "actions": args.actions, "models": rows}
    if "translated_from" in source:
        output["translations"] = [dict(field="source_model",
                                       **{k: v for k, v in source.items() if k != "model"})]
    print(json.dumps(output, indent=2))
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    providers = [args.provider] if args.provider else sorted(ROUTE_SOURCES)
    results, failures = [], []
    for provider in providers:
        try:
            results.append(candidate_refresh(provider, args.offline))
        except PricingError as exc:
            failures.append(str(exc))
    print(json.dumps({"candidates": results, "failures": failures, "dry_run": args.dry_run,
                      "activated": False}, indent=2))
    # No candidate is ever activated by refresh. Failure cannot replace the prior snapshot.
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pricing", description="route-aware, reviewed pricing snapshots")
    parser.add_argument("--snapshot", help="path to reviewed pricing snapshot")
    sub = parser.add_subparsers(dest="command", required=True)
    refresh = sub.add_parser("refresh", help="fetch route-specific candidate metadata")
    refresh.add_argument("--provider", choices=sorted(ROUTE_SOURCES))
    refresh.add_argument("--offline", action="store_true")
    refresh.add_argument("--dry-run", action="store_true")
    refresh.set_defaults(func=cmd_refresh)
    status = sub.add_parser("status", help="show snapshot freshness and warnings")
    status.set_defaults(func=cmd_status)
    validate = sub.add_parser("validate", help="validate snapshot, registry and model options")
    validate.add_argument("--options")
    validate.set_defaults(func=cmd_validate)
    eligibility_parser = sub.add_parser("eligibility", help="evaluate a micro-operation target")
    eligibility_parser.add_argument("--model", required=True)
    eligibility_parser.add_argument("--source-model", required=True)
    eligibility_parser.add_argument("--archetype", default="micro-operation", choices=("micro-operation",))
    eligibility_parser.add_argument("--actions", type=int, default=2, choices=(2, 3))
    eligibility_parser.add_argument("--options")
    eligibility_parser.add_argument("--harness", help="harness whose routes price the models")
    eligibility_parser.set_defaults(func=cmd_eligibility)
    models = sub.add_parser("eligible-models", help="evaluate every model in one rung")
    models.add_argument("--rung", required=True, choices=("minimal", "economy"))
    models.add_argument("--source-model", required=True)
    models.add_argument("--actions", type=int, default=2, choices=(2, 3))
    models.add_argument("--options")
    models.add_argument("--harness", help="harness whose routes price the models")
    models.set_defaults(func=cmd_eligible_models)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return args.func(args)
    except PricingError as exc:
        print("pricing: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
