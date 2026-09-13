#!/usr/bin/env python3
"""spend -- what this session costs, and the three levers that change it.

Measured across four days of one machine's transcripts (16,156 model calls,
about $1,140): cache reads were 55% of the bill, output 24%, cache writes 21%,
fresh input ~0%. Reasoning tokens were a few percent. The thing that makes a
session expensive is not what it thinks, it is **what it carries** -- context is
re-read on every model call, so a 20K tool result read once is 20K re-read a
few hundred times.

That fact is not specific to multi-agent work, which is why this lives outside
the orchestration skill. Three levers follow from it and all three apply to any
session that can spawn a subagent:

  1. Do not read large things into this session. Delegate the read.
  2. Pick the model rung deliberately, especially for subagents.
  3. Keep the compaction window safely above this session's floor.

Everything here reads the harness transcript on disk, so it costs no model
tokens, and every hook is silent unless something is actually wrong.

This file is the single source of truth for MODEL RATES. The measured failure it
exists to prevent was a rate table three model generations stale in one place:
together with a request-counting bug it reported $1,025 for a session that cost
$127. A second copy of this table is the same bug waiting to happen.
"""

import argparse
import hashlib
import json
import os
import stat
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

SCHEMA_VERSION = 1


class SpendError(Exception):
    pass


def env(name: str, default: Any = None) -> Any:
    """SPEND_* first, ORCH_* second.

    The orchestration skill shipped these knobs under ORCH_ before this script
    existed. Anyone who tuned a threshold there should not have it silently
    ignored the day the code moves.
    """
    return os.environ.get("SPEND_" + name) or os.environ.get("ORCH_" + name) or default


# --------------------------------------------------------------------------- #
# rates
# --------------------------------------------------------------------------- #
#
# Dollars per million tokens. Read the CACHE_READ column before assuming a
# cheaper-sounding model is cheaper: cache reads are the majority of a real
# bill, and the ordering there is not the ordering of the headline price. Moving
# 580 measured Fable calls to Opus would have SAVED $0.26, because Fable prices
# cache reads at $0.25/MTok against Opus's $0.50.
#
# Source for named rows: https://cursor.com/docs/models-and-pricing,
# retrieved 2026-09-13. A dash in Cursor's cache-write column is represented as
# zero. Anthropic's documented 1-hour cache tier remains 2x input; models whose
# page has one cache-write price use that price for either transcript bucket.
def _rate(input_rate: float, cache_write: float, cache_read: float,
          output_rate: float,
          cache_write_1h: Optional[float] = None) -> Dict[str, float]:
    return {
        "in": input_rate,
        "out": output_rate,
        "cache_write": cache_write,
        "cache_write_1h": (cache_write if cache_write_1h is None
                           else cache_write_1h),
        "cache_read": cache_read,
    }


DEFAULT_RATES = {
    # Conservative fallback and broad aliases for old transcript model ids.
    "default": _rate(5.0, 6.25, 0.5, 25.0, 10.0),
    "opus": _rate(5.0, 6.25, 0.5, 25.0, 10.0),
    "fable": _rate(10.0, 12.5, 0.25, 50.0, 20.0),
    "mythos": _rate(10.0, 12.5, 0.25, 50.0, 20.0),
    "sonnet": _rate(2.0, 2.5, 0.2, 10.0, 4.0),
    "haiku": _rate(1.0, 1.25, 0.1, 5.0, 2.0),

    # Cursor models.
    "grok-4.6-fast": _rate(4.0, 0.0, 1.0, 12.0),
    "grok-4.6": _rate(2.0, 0.0, 0.5, 6.0),
    "grok-4.5-fast": _rate(4.0, 0.0, 1.0, 18.0),
    "grok-4.5": _rate(2.0, 0.0, 0.5, 6.0),
    "composer-2.5-fast": _rate(3.0, 0.0, 0.5, 15.0),
    "composer-2.5": _rate(0.5, 0.0, 0.2, 2.5),

    # Anthropic.
    "sonnet-4-1m": _rate(6.0, 7.5, 0.6, 22.5, 12.0),
    "sonnet-4": _rate(3.0, 3.75, 0.3, 15.0, 6.0),
    "haiku-4.5": _rate(1.0, 1.25, 0.1, 5.0, 2.0),
    "opus-4.5": _rate(5.0, 6.25, 0.5, 25.0, 10.0),
    "sonnet-4.5": _rate(3.0, 3.75, 0.3, 15.0, 6.0),
    "opus-4.6": _rate(5.0, 6.25, 0.5, 25.0, 10.0),
    "sonnet-4.6": _rate(3.0, 3.75, 0.3, 15.0, 6.0),
    "opus-4.7-fast": _rate(30.0, 37.5, 3.0, 150.0, 60.0),
    "opus-4.7": _rate(5.0, 6.25, 0.5, 25.0, 10.0),
    "opus-4.8-fast": _rate(10.0, 12.5, 1.0, 50.0, 20.0),
    "opus-4.8": _rate(5.0, 6.25, 0.5, 25.0, 10.0),
    "fable-5.1": _rate(10.0, 12.5, 0.25, 50.0, 20.0),
    "fable-5": _rate(10.0, 12.5, 1.0, 50.0, 20.0),
    "opus-5": _rate(5.0, 6.25, 0.5, 25.0, 10.0),
    "sonnet-5": _rate(2.0, 2.5, 0.2, 10.0, 4.0),

    # OpenAI.
    "gpt-5.6-luna-fast": _rate(0.4, 0.5, 0.04, 2.4),
    "gpt-5.6-luna": _rate(0.2, 0.25, 0.02, 1.2),
    "gpt-5.6-terra-fast": _rate(4.0, 5.0, 0.4, 24.0),
    "gpt-5.6-terra": _rate(2.0, 2.5, 0.2, 12.0),
    "gpt-5.6-sol-fast": _rate(8.0, 10.0, 0.8, 40.0),
    "gpt-5.6-sol": _rate(4.0, 5.0, 0.4, 20.0),
    "gpt-5.4-nano": _rate(0.2, 0.0, 0.02, 1.25),
    "gpt-5.4-mini": _rate(0.75, 0.0, 0.075, 4.5),
    "gpt-5.4-fast": _rate(5.0, 0.0, 0.5, 30.0),
    "gpt-5.4": _rate(2.5, 0.0, 0.25, 15.0),
    "gpt-5.3-codex": _rate(1.75, 0.0, 0.175, 14.0),
    "gpt-5.2-codex": _rate(1.75, 0.0, 0.175, 14.0),
    "gpt-5.2": _rate(1.75, 0.0, 0.175, 14.0),
    "gpt-5.1-codex-mini": _rate(0.25, 0.0, 0.025, 2.0),
    "gpt-5.1-codex-max": _rate(1.25, 0.0, 0.125, 10.0),
    "gpt-5.1-codex": _rate(1.25, 0.0, 0.125, 10.0),
    "gpt-5-codex": _rate(1.25, 0.0, 0.125, 10.0),
    "gpt-5-mini": _rate(0.25, 0.0, 0.025, 2.0),
    "gpt-5-fast": _rate(2.5, 0.0, 0.25, 20.0),
    "gpt-5": _rate(1.25, 0.0, 0.125, 10.0),

    # Google.
    "gemini-2.5-flash": _rate(0.3, 0.0, 0.03, 2.5),
    "gemini-3.8-flash": _rate(0.75, 0.0, 0.075, 3.5),
    "gemini-3.7-flash": _rate(0.75, 0.0, 0.075, 3.5),
    "gemini-3.6-flash": _rate(1.5, 0.0, 0.15, 7.5),
    "gemini-3.5-flash": _rate(1.5, 0.0, 0.15, 9.0),
    "gemini-3.1-pro": _rate(2.0, 0.0, 0.2, 12.0),
    "gemini-3-pro-image-preview": _rate(2.0, 0.0, 0.2, 12.0),
    "gemini-3-pro": _rate(2.0, 0.0, 0.2, 12.0),
    "gemini-3-flash": _rate(0.5, 0.0, 0.05, 3.0),

    # Moonshot.
    "kimi-k2.7-code": _rate(0.95, 0.0, 0.19, 4.0),
    "kimi-k3": _rate(3.0, 0.0, 0.3, 15.0),

    # Z.ai.
    "glm-5.2": _rate(1.4, 0.0, 0.26, 4.4),
}

# Model RUNGS are relative to the provider, never absolute names. A name written
# down today is wrong the next time the provider ships; a rung stays correct.
# The measured cost of getting this wrong: `default` drifted from a Sonnet-class
# model to an Opus-class one without the rung name changing, and 6,509 lane
# calls cost $616 where the same tokens one rung down cost $246.
MODEL_RUNGS = ("minimal", "economy", "advanced", "frontier")
WORKER_MODEL_DEFAULT = env("WORKER_MODEL", "economy")
MODEL_OPTIONS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
    "skills", "delegating-economically", "references", "model-options.json")
EFFORT_ORDER = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")
RELATIVE_EFFORTS = ("lowest", "one-below-default", "default")


def load_rates() -> Dict[str, Any]:
    """DEFAULT_RATES, overridden by SPEND_RATES json or ./rates.json.

    A price change should not be a code change.
    """
    override = env("RATES")
    if override:
        try:
            return {**DEFAULT_RATES, **json.loads(override)}
        except ValueError:
            pass
    for path in ("rates.json", os.path.join(state_root(), "rates.json")):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return {**DEFAULT_RATES, **json.load(fh)}
        except (OSError, ValueError):
            continue
    return dict(DEFAULT_RATES)


def _model_tokens(value: str) -> Tuple[str, ...]:
    """Normalize provider wrappers and punctuation into comparable tokens."""
    return tuple(re.findall(r"[a-z]+|\d+", (value or "").lower()))


def _contains_tokens(name: Tuple[str, ...], key: Tuple[str, ...]) -> bool:
    """Whether key is a contiguous token sequence inside name."""
    width = len(key)
    return bool(width and any(name[i:i + width] == key
                              for i in range(len(name) - width + 1)))


def rate_for(model: str, rates: Dict[str, Any]) -> Dict[str, float]:
    """Choose the most specific normalized model key.

    Provider wrappers and punctuation do not affect matching:
    `cursor/GPT-5.6-sol` matches `gpt-5.6-sol`, and
    `cursor/claude-fable-5-1` matches `fable-5.1`.
    """
    name = _model_tokens(model)
    best = None
    for key, value in rates.items():
        if key == "default":
            continue
        tokens = _model_tokens(key)
        if _contains_tokens(name, tokens):
            score = (len(tokens), len(key))
            if best is None or score > best[0]:
                best = (score, value)
    rate = best[1] if best else rates["default"]
    if "cache_write_1h" not in rate:
        # A rates.json written before the 1h tier existed prices every cache
        # write at the 5m rate. Synthesize rather than fall back to it: the
        # tier is 2x input, and silently undercharging is the bug this fixes.
        rate = dict(rate, cache_write_1h=rate["in"] * 2.0)
    return rate


def load_model_options(path: Optional[str] = None) -> Dict[str, Any]:
    source = os.path.expanduser(path or MODEL_OPTIONS_PATH)
    try:
        with open(source, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise SpendError("cannot read model options %s: %s" % (source, exc))
    if not isinstance(data.get("models"), list) or not isinstance(
            data.get("archetypes"), dict):
        raise SpendError("invalid model options in %s" % source)
    return data


def find_model_catalog(path: Optional[str] = None) -> str:
    candidates = []
    if path:
        candidates.append(path)
    configured = env("MODEL_CATALOG")
    if configured:
        candidates.append(str(configured))
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        candidates.append(os.path.join(codex_home, "models_cache.json"))
    candidates.append(os.path.expanduser("~/.codex/models_cache.json"))
    for candidate in candidates:
        expanded = os.path.expanduser(candidate)
        if os.path.isfile(expanded):
            return expanded
    raise SpendError(
        "no live model catalog; pass --catalog or set SPEND_MODEL_CATALOG")


def load_model_catalog(path: Optional[str] = None) -> Tuple[str, List[Dict[str, Any]]]:
    source = find_model_catalog(path)
    try:
        with open(source, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise SpendError("cannot read model catalog %s: %s" % (source, exc))
    models = data.get("models") if isinstance(data, dict) else data
    if not isinstance(models, list):
        raise SpendError("model catalog %s has no models list" % source)
    available = [m for m in models if isinstance(m, dict)
                 and isinstance(m.get("slug"), str)
                 and m.get("visibility", "list") != "hide"]
    return source, available


def resolve_archetype(
        name: str, archetypes: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    wanted = name.strip().lower().replace("_", "-")
    for canonical, policy in archetypes.items():
        aliases = policy.get("aliases", []) if isinstance(policy, dict) else []
        if wanted == canonical or wanted in aliases:
            return canonical, policy
    raise SpendError("unknown archetype %r; try: %s"
                     % (name, ", ".join(sorted(archetypes))))


def _catalog_match(option_id: str, slug: str) -> bool:
    option = _model_tokens(option_id)
    candidate = _model_tokens(slug)
    return bool(option and candidate[-len(option):] == option)


def _supported_efforts(model: Dict[str, Any]) -> List[str]:
    rows = model.get("supported_reasoning_levels", [])
    return [row.get("effort") for row in rows
            if isinstance(row, dict) and isinstance(row.get("effort"), str)]


def choose_effort(preferred: str, supported: List[str],
                  model_default: Optional[str] = None) -> Optional[str]:
    if not supported:
        return None
    ranked = [value for value in EFFORT_ORDER if value in supported]
    if preferred == "lowest":
        return ranked[0] if ranked else supported[0]
    if preferred in ("default", "one-below-default"):
        target = model_default if model_default in supported else None
        if target is None:
            return None
        if preferred == "default":
            return target
        if target not in EFFORT_ORDER or not ranked:
            return None
        below = [value for value in ranked
                 if EFFORT_ORDER.index(value) < EFFORT_ORDER.index(target)]
        return below[-1] if below else target
    target = preferred
    if target in supported:
        return target
    if not ranked:
        return supported[0]
    try:
        target_index = EFFORT_ORDER.index(target)
    except ValueError:
        target_index = EFFORT_ORDER.index("medium")
    return min(ranked, key=lambda value: (
        abs(EFFORT_ORDER.index(value) - target_index),
        EFFORT_ORDER.index(value)))


def select_models(options: Dict[str, Any], catalog: List[Dict[str, Any]],
                  rung: str, effort: str,
                  exclude_family: Optional[str] = None) -> List[Dict[str, Any]]:
    selected = []
    excluded = (exclude_family or "").strip().lower()
    for option in options["models"]:
        if rung not in option.get("rungs", []):
            continue
        if excluded and option.get("family", "").lower() == excluded:
            continue
        for model in catalog:
            if not _catalog_match(option.get("id", ""), model["slug"]):
                continue
            supported = _supported_efforts(model)
            selected.append({
                "model": model["slug"],
                "family": option.get("family"),
                "rung": rung,
                "effort": choose_effort(
                    effort, supported, model.get("default_reasoning_level")),
                "use": option.get("use"),
            })
            break
    return selected


def cmd_models(args: argparse.Namespace) -> int:
    options = load_model_options(args.options)
    archetype = None
    policy = None
    if args.archetype:
        archetype, policy = resolve_archetype(
            args.archetype, options["archetypes"])
        rung = policy["rung"]
        effort = policy["effort"]
        if policy.get("requires_exclude_family") and not args.exclude_family:
            raise SpendError(
                "%s requires --exclude-family for an independent opinion"
                % archetype)
    else:
        rung = args.rung
        effort = args.effort or "medium"

    source, catalog = load_model_catalog(args.catalog)
    selected = select_models(
        options, catalog, rung, effort, args.exclude_family)
    if not selected:
        raise SpendError(
            "no %s models from the option map are present in %s"
            % (rung, source))

    result = {
        "rung": rung,
        "effort": effort,
        "archetype": archetype,
        "escalate": policy.get("escalate") if policy else None,
        "models": selected,
    }
    if args.format == "json":
        print(json.dumps(result, indent=2))
        return 0

    if archetype:
        print("%s: %s / %s effort" % (archetype, rung, effort))
        print("escalate: %s" % policy["escalate"])
    else:
        print("%s / %s effort" % (rung, effort))
    for row in selected:
        suffix = (" / %s effort" % row["effort"]
                  if row["effort"] else "")
        print("%s%s — %s" % (row["model"], suffix, row["use"]))
    return 0


# --------------------------------------------------------------------------- #
# state -- keyed by repo, never by "program"
# --------------------------------------------------------------------------- #
#
# The orchestration version of this code keyed its cooldowns and budgets to a
# multi-agent "program" and then went silent when there wasn't one -- which
# disabled a session-hygiene check in exactly the sessions that had no
# orchestrator watching them. Scope here is the repository (or the working
# directory, outside a repo), because that is what a session actually has.


def state_root() -> str:
    base = env("STATE_HOME") or os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "context-economy")


def repo_key(start: str = ".") -> str:
    """A stable key for this repo, falling back to the directory outside one."""
    try:
        top = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5)
        root = top.stdout.strip() if top.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        root = ""
    if not root:
        root = os.path.realpath(start if os.path.isdir(start) else ".")
    digest = hashlib.sha256(root.encode("utf-8")).hexdigest()[:10]
    return "%s-%s" % (re.sub(r"[^A-Za-z0-9]+", "-", os.path.basename(root)) or "repo",
                      digest)


def state_dir(start: str = ".") -> str:
    return os.path.join(state_root(), repo_key(start))


def _load_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_json(path: str, data: Dict[str, Any]) -> None:
    """Write atomically, without widening the file's permissions.

    os.replace takes the temp file's mode, and a fresh open() lands at
    0666 & ~umask -- usually 0644. Applied to ~/.claude/settings.json, which
    people put API keys in, a save would quietly turn an owner-only config
    world-readable. Carry the existing mode over; default new files to 0600.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        mode = 0o600
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# hook plumbing
# --------------------------------------------------------------------------- #
#
# HOOK OUTPUT IS PERMANENT CONTEXT. A hook that prints 130 tokens of persuasive
# rationale has sold a one-time good on a recurring contract: the argument works
# once, on the read that changes the decision, and is then re-read on every
# model call for the rest of the session. So every message below is a terse
# ACTION plus a pointer, and the rationale lives in `spend why <topic>`, which
# costs nothing until someone asks.
HOOK_TOKEN_BUDGET = int(env("HOOK_TOKENS", 40))

_HOOK_PAYLOAD: Optional[Dict[str, Any]] = None
_HOOK_PAYLOAD_READ = False


def hook_payload() -> Dict[str, Any]:
    """The hook's JSON payload, or {} when not running as a hook.

    Read at most once -- stdin is not re-readable -- and silent on every failure
    path, because an interactive invocation has a terminal on stdin and must not
    block.
    """
    global _HOOK_PAYLOAD, _HOOK_PAYLOAD_READ
    if _HOOK_PAYLOAD_READ:
        return _HOOK_PAYLOAD or {}
    _HOOK_PAYLOAD_READ = True
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        raw = sys.stdin.read(1 << 20)
    except (OSError, ValueError):
        return {}
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    _HOOK_PAYLOAD = parsed if isinstance(parsed, dict) else None
    return _HOOK_PAYLOAD or {}


def _hook_cwd() -> Optional[str]:
    cwd = hook_payload().get("cwd")
    return cwd if isinstance(cwd, str) and os.path.isdir(cwd) else None


def est_tokens(text: str) -> int:
    """Rough token count for English prose. Used to hold hooks to their budget."""
    return max(1, len(text) // 4)


def emit(event: str, text: str) -> None:
    """Print hook context, and never exceed the budget silently."""
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": event, "additionalContext": text}}))


# --------------------------------------------------------------------------- #
# transcript
# --------------------------------------------------------------------------- #

def project_dir_for(cwd: str) -> Optional[str]:
    base = os.path.join(os.path.expanduser("~"), ".claude", "projects")
    slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd))
    path = os.path.join(base, slug)
    return path if os.path.isdir(path) else None


def find_transcript(args: argparse.Namespace) -> Optional[str]:
    if getattr(args, "transcript", None):
        return os.path.expanduser(args.transcript)
    from_hook = hook_payload().get("transcript_path")
    if isinstance(from_hook, str) and os.path.isfile(os.path.expanduser(from_hook)):
        return os.path.expanduser(from_hook)
    start = args.repo if os.path.isdir(args.repo) else "."
    pdir = project_dir_for(start)
    if not pdir:
        return None
    files = [os.path.join(pdir, f) for f in os.listdir(pdir) if f.endswith(".jsonl")]
    return max(files, key=os.path.getmtime) if files else None


def read_usage(path: str, rates: Dict[str, Any],
               on_line: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Summarise a transcript's model calls. Streams; keeps only aggregates.

    `on_line` is handed every raw line before parsing, so a caller needing its
    own per-line tally (orchestration counts human turns and relay shapes) gets
    it from this single pass instead of keeping a second copy of the pricing
    loop -- which is how the two drifted apart on the 1h cache tier.

    **One API response can occupy several transcript lines.** The harness writes
    one line per content block, so a response holding thinking + text + tool_use
    is three lines, each carrying an identical copy of the same `usage` object.
    Summing lines multiplies the bill by the average block count: on a measured
    session, 1,592 lines were 714 responses -- a 2.23x overstatement.
    `requestId` is the response identity.
    """
    totals = {"in": 0, "out": 0, "cache_write": 0, "cache_write_1h": 0,
              "cache_read": 0}
    component_cost = {k: 0.0 for k in totals}
    seen: Set[str] = set()
    steps = 0
    cost = 0.0
    recent: List[Tuple[int, float]] = []
    models: Dict[str, int] = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if on_line is not None:
                    on_line(line)
                if '"usage"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("type") != "assistant":
                    continue
                message = row.get("message") or {}
                usage = message.get("usage") or {}
                if not usage:
                    continue
                request_id = row.get("requestId") or message.get("id")
                if request_id:
                    if request_id in seen:
                        continue
                    seen.add(request_id)
                model = message.get("model") or ""
                rate = rate_for(model, rates)
                models[model] = models.get(model, 0) + 1
                # Cache writes bill at two tiers. `cache_creation_input_tokens`
                # is their sum and stayed put when the breakdown was added, so
                # reading only it prices the 1h tier at the 5m rate -- measured
                # at a 10.3% understatement on a 1h-TTL harness, where 91% of
                # writes are 1h. Derive 5m by subtraction so the flat field
                # stays authoritative and an absent breakdown degrades to
                # today's behaviour rather than to zero.
                created = usage.get("cache_creation_input_tokens", 0) or 0
                breakdown = usage.get("cache_creation") or {}
                write_1h = breakdown.get("ephemeral_1h_input_tokens", 0) or 0
                fields = {
                    "in": usage.get("input_tokens", 0) or 0,
                    "out": usage.get("output_tokens", 0) or 0,
                    "cache_write": max(created - write_1h, 0),
                    "cache_write_1h": write_1h,
                    "cache_read": usage.get("cache_read_input_tokens", 0) or 0,
                }
                step_cost = sum(fields[k] * rate[k] for k in fields) / 1e6
                for key, value in fields.items():
                    totals[key] += value
                    component_cost[key] += value * rate[key] / 1e6
                cost += step_cost
                steps += 1
                recent.append((fields["in"] + fields["cache_write"]
                               + fields["cache_write_1h"]
                               + fields["cache_read"], step_cost))
                if len(recent) > 25:
                    recent.pop(0)
    except OSError:
        return {}
    if not steps:
        return {}
    return {
        "transcript": path,
        "steps": steps,
        "tokens": totals,
        "cost": cost,
        "context": recent[-1][0] if recent else 0,
        "cost_per_step": sum(c for _, c in recent) / len(recent) if recent else 0.0,
        "models": models,
        # Priced per call as it was read, not by re-pricing totals at one rate:
        # a mixed-tier session has no single rate, and picking the commonest
        # model misattributes every other tier's spend.
        "shares": {k: (component_cost[k] / cost if cost else 0) for k in totals},
    }


# --------------------------------------------------------------------------- #
# cost advisories
# --------------------------------------------------------------------------- #
#
# Measured cost per model call against context carried, over 9,138 Opus calls:
# under 100K $0.077 · 100-200K $0.105 · 200-300K $0.152 · 300-400K $0.224 ·
# 400-500K $0.271. The thresholds below sit where the curve starts to bite and
# where it has plainly won.
CONTEXT_WARN = int(env("CONTEXT_WARN", 250_000))
CONTEXT_URGENT = int(env("CONTEXT_URGENT", 400_000))


def load_budget(start: str = ".") -> Dict[str, Any]:
    return _load_json(os.path.join(state_dir(start), "budget.json"))


def cost_advisories(usage: Dict[str, Any], budget: Dict[str, Any]) -> List[str]:
    """Terse, actionable, and nothing else. See the note on HOOK_TOKEN_BUDGET.

    Note what is NOT here: fan-out width and front-desk relay belong to the
    orchestration skill, because both need a dispatch tracker to count. This
    file only ever speaks about the session it is running in.
    """
    out = []
    context = usage.get("context", 0)
    per_step = usage.get("cost_per_step", 0.0)
    if context >= CONTEXT_URGENT:
        out.append("CONTEXT %dK · $%.2f/call. Compact at the next seam; "
                   "delegate large reads. `spend why context`"
                   % (context // 1000, per_step))
    elif context >= CONTEXT_WARN:
        out.append("CONTEXT %dK · $%.2f/call and rising. Delegate large reads; "
                   "keep conclusions only. `spend why context`"
                   % (context // 1000, per_step))
    limit = budget.get("limit")
    if isinstance(limit, (int, float)) and limit > 0:
        spent = usage.get("cost", 0.0)
        if spent >= limit:
            out.append("BUDGET $%.0f of $%.0f. Say so and let the human decide."
                       % (spent, limit))
        elif spent >= 0.75 * limit:
            out.append("BUDGET $%.0f of $%.0f." % (spent, limit))
    return out


def _should_warn(start: str, usage: Dict[str, Any],
                 advisories: List[str]) -> bool:
    """Speak on a NEW condition, or when context has grown by half again.

    A hook that nags every turn gets switched off, and is then worth nothing at
    the moment it would have mattered.
    """
    path = os.path.join(state_dir(start), "warned.json")
    prior = _load_json(path)
    kinds = sorted({a.split()[0] for a in advisories})
    last_context = int(prior.get("context") or 0)
    context = usage.get("context", 0)
    fresh = kinds != prior.get("kinds")
    grown = last_context and context >= last_context * 1.5
    if not (fresh or grown):
        return False
    try:
        _save_json(path, {"kinds": kinds, "context": context, "at": _now()})
    except OSError:
        pass
    return True


def cmd_cost(args: argparse.Namespace) -> int:
    quiet = args.format == "hook"
    if quiet and args.repo == ".":
        args.repo = _hook_cwd() or args.repo
    rates = load_rates()
    path = find_transcript(args)
    if not path:
        if quiet:
            return 0
        raise SpendError("no transcript found; pass --transcript")
    usage = read_usage(path, rates)
    if not usage:
        if quiet:
            return 0
        raise SpendError("no model calls found in %s" % path)
    budget = load_budget(args.repo)
    advisories = cost_advisories(usage, budget)

    if args.format == "json":
        print(json.dumps({**usage, "advisories": advisories}, indent=2))
        return 0
    if quiet:
        if not advisories or not _should_warn(args.repo, usage, advisories):
            return 0
        emit("Stop", "\n".join(advisories))
        return 0

    t = usage["tokens"]
    print("transcript   %s" % usage["transcript"])
    print("model calls  %d" % usage["steps"])
    print("context now  %dK tokens" % (usage["context"] // 1000))
    print("tokens       in %s · out %s · cache write %s (5m) + %s (1h) · "
          "cache read %s"
          % tuple("{:,}".format(t[k]) for k in
                  ("in", "out", "cache_write", "cache_write_1h", "cache_read")))
    print("cost (est)   $%.2f total · $%.2f per model call (last 25)"
          % (usage["cost"], usage["cost_per_step"]))
    print("cost share   %s" % " · ".join(
        "%s %.0f%%" % (k.replace("_", " "), v * 100)
        for k, v in sorted(usage["shares"].items(), key=lambda x: -x[1])))
    if usage["models"]:
        print("models       %s" % " · ".join(
            "%s x%d" % (m or "?", n) for m, n in
            sorted(usage["models"].items(), key=lambda x: -x[1])))
    if budget.get("limit"):
        print("budget       $%s" % budget["limit"])
    for line in advisories:
        print("\n! %s" % line)
    if not advisories:
        print("\nno advisories: context is within thresholds.")
    return 0


def cmd_budget(args: argparse.Namespace) -> int:
    path = os.path.join(state_dir(args.repo), "budget.json")
    if args.set is not None:
        _save_json(path, {"limit": args.set, "at": _now()})
        print("budget set to $%.2f for %s" % (args.set, repo_key(args.repo)))
        return 0
    budget = load_budget(args.repo)
    print("budget $%s" % budget["limit"] if budget.get("limit") else "no budget set")
    return 0


# --------------------------------------------------------------------------- #
# guard -- the moment a large thing is about to become permanent
# --------------------------------------------------------------------------- #
#
# Measured composition of what one session wrote into its own permanent context:
# shell heredocs over 2KB, 304KB across 62 writes; prose to the human, 111KB
# across 150 messages; subagent launch prompts, 31KB across 53 spawns.
#
# This never blocks. Sometimes the content is rightly yours.
# The defaults are named separately from the resolved values because the guard's
# shell prefilter has to know the same numbers before this file is ever parsed.
# See `GUARD_PREFILTER`.
GUARD_BYTES_DEFAULT = 6000
GUARD_BYTES = int(env("GUARD_BYTES", GUARD_BYTES_DEFAULT))
GUARD_COOLDOWN_S = int(env("GUARD_COOLDOWN", 600))
# A document authored inline through a heredoc gets a much lower floor. Of 42
# heredoc-authored briefs measured in one program the median was 4.4KB and 32 of
# the 42 sat UNDER GUARD_BYTES -- so the threshold that is right for an
# arbitrary large input let three quarters of the single biggest self-inflicted
# context item through. The shape is the signal, not the size.
GUARD_HEREDOC_BYTES_DEFAULT = 1200
GUARD_HEREDOC_BYTES = int(env("GUARD_HEREDOC_BYTES", GUARD_HEREDOC_BYTES_DEFAULT))
# A file this big read whole is a recurring charge, not a one-off read.
GUARD_READ_BYTES = int(env("GUARD_READ_BYTES", 24_000))

_DOC_HEREDOC_RE = re.compile(
    r"""(?:^|[;&|]|\bthen\b|\bdo\b)\s*(?:cat\s*>>?|tee\s*-?a?)\s*"""
    r"""[^\s;&|<>]+\.(?:md|markdown|mdx)["']?\s*<<""",
    re.IGNORECASE | re.MULTILINE)


def _is_doc_heredoc(name: str, tool_input: Dict[str, Any]) -> bool:
    if name != "Bash":
        return False
    return bool(_DOC_HEREDOC_RE.search(str(tool_input.get("command", ""))))


def _tool_input_size(name: str, tool_input: Dict[str, Any]) -> int:
    if name == "Bash":
        return len(str(tool_input.get("command", "")))
    if name == "Write":
        return len(str(tool_input.get("content", "")))
    if name in ("Edit", "MultiEdit"):
        return len(str(tool_input.get("new_string", "")))
    return 0


def _unbounded_read_bytes(name: str, tool_input: Dict[str, Any]) -> int:
    """Size of a file about to be read whole, or 0.

    A bounded read (`limit`/`offset`) is a deliberate slice and says nothing
    alarming. An unbounded read of a large file is the single cheapest thing to
    delegate: the worker's context dies with it, yours does not.
    """
    if name != "Read" or tool_input.get("limit"):
        return 0
    path = tool_input.get("file_path")
    if not isinstance(path, str):
        return 0
    try:
        return os.path.getsize(os.path.expanduser(path))
    except OSError:
        return 0


def _guard_kind(name: str, tool_input: Dict[str, Any]) -> Optional[Tuple[str, int]]:
    read_size = _unbounded_read_bytes(name, tool_input)
    if read_size >= GUARD_READ_BYTES:
        return ("large-read", read_size)
    size = _tool_input_size(name, tool_input)
    if _is_doc_heredoc(name, tool_input):
        if size >= GUARD_HEREDOC_BYTES:
            return ("doc-heredoc", size)
        return None
    if size >= GUARD_BYTES:
        return ("large-input", size)
    return None


# Cooled down PER KIND, so a heredoc-authored document still speaks when an
# unrelated large edit has just warned. One shared timer let the rarer and more
# actionable signal be masked by the commoner one.
_GUARD_TEXT = {
    "doc-heredoc": "CONTEXT ~%dKB inline doc — permanent this session. "
                   "Delegate authoring; keep the path. `spend why heredoc`",
    "large-input": "CONTEXT ~%dKB %s input — permanent this session. "
                   "If it is a document, delegate it. `spend why input`",
    "large-read":  "CONTEXT ~%dKB read whole — re-read on every later call. "
                   "Delegate the read, keep the conclusion. `spend why read`",
}


def cmd_guard(args: argparse.Namespace) -> int:
    payload = hook_payload()
    name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(name, str) or not isinstance(tool_input, dict):
        return 0
    found = _guard_kind(name, tool_input)
    if not found:
        return 0
    kind, size = found
    start = payload.get("cwd") if isinstance(payload.get("cwd"), str) else args.repo
    marker = os.path.join(state_dir(start), "guard-warned.json")
    prior = _load_json(marker)
    stamps = prior.get("kinds") if isinstance(prior.get("kinds"), dict) else {}
    try:
        last = datetime.fromisoformat(stamps.get(kind, "1970-01-01T00:00:00+00:00"))
    except ValueError:
        last = datetime.fromtimestamp(0, timezone.utc)
    if (datetime.now(timezone.utc) - last).total_seconds() < GUARD_COOLDOWN_S:
        return 0
    stamps[kind] = _now()
    try:
        _save_json(marker, {"kinds": stamps, "tool": name, "bytes": size})
    except OSError:
        pass
    kb = size // 1024 or 1
    text = (_GUARD_TEXT[kind] % (kb, name) if kind == "large-input"
            else _GUARD_TEXT[kind] % kb)
    emit("PreToolUse", text)
    return 0


# --------------------------------------------------------------------------- #
# rung -- the model tier of a subagent, decided rather than defaulted
# --------------------------------------------------------------------------- #
#
# A dial left to the spawn call takes the provider's current default, and that
# default is the most expensive rung anyone reaches by accident. This fires when
# a subagent is about to be spawned with no model set. It never blocks: plenty
# of tasks deserve the default, but the choice should be made.
RUNG_COOLDOWN_S = int(env("RUNG_COOLDOWN", 1800))
SPAWN_TOOLS = tuple(t.strip() for t in str(
    env("SPAWN_TOOLS", "Task,Agent")).split(",") if t.strip())


def cmd_rung(args: argparse.Namespace) -> int:
    payload = hook_payload()
    name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if name not in SPAWN_TOOLS or not isinstance(tool_input, dict):
        return 0
    if tool_input.get("model"):
        return 0
    start = payload.get("cwd") if isinstance(payload.get("cwd"), str) else args.repo
    marker = os.path.join(state_dir(start), "rung-warned.json")
    prior = _load_json(marker)
    try:
        last = datetime.fromisoformat(prior.get("at", "1970-01-01T00:00:00+00:00"))
    except ValueError:
        last = datetime.fromtimestamp(0, timezone.utc)
    if (datetime.now(timezone.utc) - last).total_seconds() < RUNG_COOLDOWN_S:
        return 0
    try:
        _save_json(marker, {"at": _now()})
    except OSError:
        pass
    emit("PreToolUse",
         "MODEL unset — this subagent takes the provider default, the priciest "
         "rung reached by accident. Most work wants `%s`. `spend why rung`"
         % WORKER_MODEL_DEFAULT)
    return 0


# --------------------------------------------------------------------------- #
# compaction -- measure the floor, and catch a window set too low
# --------------------------------------------------------------------------- #
#
# A session has an irreducible FLOOR: system prompt, tool schemas, skill and
# project instructions, plus the compaction summary and whatever session-start
# hooks print. A window set near that floor leaves almost no working room -- the
# session compacts, lands back at or above the trigger, and compacts again. It
# does not error; it hangs. Measured, session-open floors ran 7K to 97K (p90
# 50K) and post-compaction floors 39K to 63K, so "200K" is safe in one repo and
# a loop in another. Everything here works from a MEASURED floor.
FLOOR_SAFETY_RATIO = float(env("FLOOR_RATIO", 3.0))
WINDOW_BLIND_DEFAULT = int(env("AUTOCOMPACT_WINDOW", 300_000) or 0)
# A safety device that recommends LOWERING a setting has misunderstood its job.
# A lower window is genuinely cheaper per unit of work, so going below this is a
# deliberate cost decision, never something a floor measurement should trigger.
WINDOW_SAFE_MIN = int(env("WINDOW_MIN", 200_000))
WINDOW_FLOOR = 100_000
WINDOW_CEILING = 1_000_000
# A floor measured before this session's first compaction has not paid for the
# summary yet, so it understates where the NEXT cycle starts. Measured,
# post-compaction floors ran 5-15K above session-open floors in the same repos;
# this errs to the top of that range because erring low means a loop.
SUMMARY_ALLOWANCE = int(env("SUMMARY_ALLOWANCE", 15_000))
# Two compactions closer than this are not a cycle, they are a loop. Healthy
# cycles in the measured transcripts ran 76-140 model calls apart.
LOOP_CALL_GAP = int(env("LOOP_CALL_GAP", 15))
# Below this a call is a title generation or similar side call, not a step of
# the conversation, and would drag the floor estimate down.
MIN_REAL_CONTEXT = 1_000


def scan_compaction(path: str) -> Dict[str, Any]:
    """Floor, observed window and compaction spacing, from a transcript.

    A boundary appears twice (the summary message and the boundary metadata), so
    consecutive markers with no model call between them collapse to one event --
    hence `pending` is a latch, not a counter. Calls are deduplicated by
    requestId for the reason given in `read_usage`: distances here are quoted in
    model calls, so counting lines made the detector roughly twice as tolerant
    as it reads.
    """
    calls = 0
    seen: Set[str] = set()
    prev = 0
    first = None
    events: List[Dict[str, Any]] = []
    pending = False
    peak = 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"usage"' not in line and "ompact" not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if (row.get("isCompactSummary")
                        or row.get("subtype") == "compact_boundary"):
                    if not pending:
                        pending = True
                        events.append({"at_call": calls, "before": prev,
                                       "after": None})
                    continue
                if row.get("type") != "assistant":
                    continue
                usage = (row.get("message") or {}).get("usage") or {}
                if not usage:
                    continue
                request_id = row.get("requestId") or (row.get("message") or {}).get("id")
                if request_id:
                    if request_id in seen:
                        continue
                    seen.add(request_id)
                context = ((usage.get("input_tokens") or 0)
                           + (usage.get("cache_creation_input_tokens") or 0)
                           + (usage.get("cache_read_input_tokens") or 0))
                if context < MIN_REAL_CONTEXT:
                    continue
                calls += 1
                peak = max(peak, context)
                if first is None:
                    first = context
                if pending:
                    events[-1]["after"] = context
                    pending = False
                prev = context
    except OSError:
        return {}
    if not calls:
        return {}
    landed = [e["after"] for e in events if e.get("after")]
    # The floor that matters is where a cycle STARTS, so post-compaction beats
    # session-open. Take the worst observed, not the best: a margin computed
    # from the friendliest cycle is not a margin.
    floor = max(landed) if landed else (first or 0)
    return {
        "transcript": path,
        "calls": calls,
        "floor": floor,
        "floor_source": "post-compaction" if landed else "session-open",
        "open_floor": first or 0,
        "peak": peak,
        "observed_window": max([e["before"] for e in events if e.get("before")]
                               or [0]),
        "events": events,
        "compactions": len(events),
    }


def effective_floor(scan: Dict[str, Any]) -> int:
    floor = int(scan.get("floor") or 0)
    if scan.get("floor_source") != "post-compaction":
        floor += SUMMARY_ALLOWANCE
    return floor


def recommend_window(floor: int) -> int:
    want = max(floor * FLOOR_SAFETY_RATIO, WINDOW_SAFE_MIN)
    want = min(max(want, WINDOW_FLOOR), WINDOW_CEILING)
    return int(round(want / 50_000.0) * 50_000)


def compaction_advisories(scan: Dict[str, Any], window: int,
                          floor: int) -> List[str]:
    """Only the two conditions that mean the window is WRONG, not merely tight."""
    out = []
    events = scan.get("events", [])
    effective = window or scan.get("observed_window", 0)
    room = effective - floor if effective else 0
    gaps = []
    prev_call = 0
    for event in events:
        gaps.append(event["at_call"] - prev_call)
        prev_call = event["at_call"]
    tight = [g for g in gaps[1:] if g < LOOP_CALL_GAP]
    if tight:
        out.append("COMPACTION LOOP — %d compactions <%d calls apart; floor %dK. "
                   "Next session needs window %dK. `spend why loop`"
                   % (len(tight), LOOP_CALL_GAP, floor // 1000,
                      recommend_window(floor) // 1000))
    elif effective and room < floor * (FLOOR_SAFETY_RATIO - 1):
        out.append("COMPACTION HEADROOM — floor %dK against a %dK window. "
                   "Next session needs %dK. `spend why headroom`"
                   % (floor // 1000, effective // 1000,
                      recommend_window(floor) // 1000))
    return out


def compaction_record(start: str) -> str:
    return os.path.join(state_dir(start), "compaction.json")


def cmd_compaction(args: argparse.Namespace) -> int:
    quiet = getattr(args, "format", "text") == "hook"
    if quiet and args.repo == ".":
        args.repo = _hook_cwd() or args.repo

    # `window` answers from the record alone. It is called at session open,
    # before any transcript for the new session exists, so it must never depend
    # on one.
    if args.action == "window":
        recorded = _load_json(compaction_record(args.repo))
        window = max(int(recorded.get("window") or 0), WINDOW_BLIND_DEFAULT)
        if not window:
            return 3
        print(window)
        if args.explain:
            print("floor %dK measured · window %dK"
                  % (int(recorded.get("floor") or 0) // 1000, window // 1000),
                  file=sys.stderr)
        return 0

    path = find_transcript(args)
    if not path:
        if quiet:
            return 0
        raise SpendError("no transcript found; pass --transcript")
    scan = scan_compaction(path)
    if not scan:
        if quiet:
            return 0
        raise SpendError("no model calls found in %s" % path)
    floor = effective_floor(scan)
    configured = int(os.environ.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW") or 0)
    window = configured or scan.get("observed_window", 0)
    advisories = compaction_advisories(scan, window, floor)

    if args.action == "measure":
        # A recorded floor only ever grows: a small measurement from a short
        # session must not lower a window that a long one justified.
        recorded = _load_json(compaction_record(args.repo))
        best = max(floor, int(recorded.get("floor") or 0))
        try:
            _save_json(compaction_record(args.repo),
                       {"floor": best, "window": recommend_window(best),
                        "peak": scan["peak"], "at": _now(),
                        "version": SCHEMA_VERSION})
        except OSError:
            pass

    if args.format == "json":
        print(json.dumps({**scan, "effective_floor": floor,
                          "recommended_window": recommend_window(floor),
                          "advisories": advisories}, indent=2))
        return 0
    if quiet:
        if advisories:
            emit("SessionStart", "\n".join(advisories))
        return 0

    print("transcript   %s" % scan["transcript"])
    print("floor        %dK tokens effective (%s; session-open was %dK)"
          % (floor // 1000, scan["floor_source"], scan["open_floor"] // 1000))
    print("peak         %dK tokens over %d model calls"
          % (scan["peak"] // 1000, scan["calls"]))
    print("compactions  %d" % scan["compactions"])
    if window:
        print("window       %dK (%s)" % (window // 1000,
              "configured" if configured else "observed"))
    print("minimum safe %dK (max of floor x %.1f and the %dK floor this tool "
          "will not go below)" % (recommend_window(floor) // 1000,
                                  FLOOR_SAFETY_RATIO, WINDOW_SAFE_MIN // 1000))
    for line in advisories:
        print("\n! %s" % line)
    if not advisories:
        print("\nno advisories: compaction spacing and headroom are healthy.")
    return 0


# --------------------------------------------------------------------------- #
# footprint -- this tool, audited by its own standard
# --------------------------------------------------------------------------- #
#
# A context-economy plugin whose presence taxes every turn refutes itself. The
# two numbers that matter are the STANDING cost (skill descriptions, in the
# session floor, paid on every model call and never compacted away) and the
# PER-FIRE cost of each hook message (permanent from the moment it prints).
FOOTPRINT_FLOOR_BUDGET = int(env("FOOTPRINT_FLOOR_BUDGET", 250))


def _skill_descriptions(plugin_root: str) -> List[Tuple[str, str]]:
    out = []
    skills = os.path.join(plugin_root, "skills")
    for name in sorted(os.listdir(skills)) if os.path.isdir(skills) else []:
        path = os.path.join(skills, name, "SKILL.md")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                head = fh.read(4000)
        except OSError:
            continue
        match = re.search(r"^description:\s*(.+)$", head, re.M)
        if match:
            out.append((name, match.group(1).strip()))
    return out


def cmd_footprint(args: argparse.Namespace) -> int:
    root = args.plugin_root or os.path.dirname(os.path.dirname(
        os.path.realpath(__file__)))
    standing = 0
    rows = []
    for name, desc in _skill_descriptions(root):
        tokens = est_tokens(desc)
        standing += tokens
        rows.append(("skill: %s" % name, tokens, "every turn"))

    worst = 0
    for kind, template in sorted(_GUARD_TEXT.items()):
        sample = template % ((99, "Write") if kind == "large-input" else (99,))
        tokens = est_tokens(sample)
        worst = max(worst, tokens)
        rows.append(("hook: guard/%s" % kind, tokens, "per fire"))
    for label, sample in (
        ("hook: rung", "MODEL unset — this subagent takes the provider default, "
                       "the priciest rung reached by accident. Most work wants "
                       "economy. `spend why rung`"),
        ("hook: cost", "CONTEXT 260K · $0.11/call and rising. Delegate large "
                       "reads; keep conclusions only. `spend why context`"),
        ("hook: compaction", "COMPACTION HEADROOM — floor 52K against a 200K "
                             "window. Next session needs 200K. `spend why headroom`"),
    ):
        tokens = est_tokens(sample)
        worst = max(worst, tokens)
        rows.append((label, tokens, "per fire"))

    width = max(len(r[0]) for r in rows)
    for label, tokens, when in rows:
        print("%-*s  %4d tok  %s" % (width, label, tokens, when))
    print()
    print("standing (floor) %d tok · budget %d" % (standing, FOOTPRINT_FLOOR_BUDGET))
    print("worst hook fire  %d tok · budget %d" % (worst, HOOK_TOKEN_BUDGET))

    failures = []
    if standing > FOOTPRINT_FLOOR_BUDGET:
        failures.append("standing cost %d > %d" % (standing, FOOTPRINT_FLOOR_BUDGET))
    if worst > HOOK_TOKEN_BUDGET:
        failures.append("hook fire %d > %d" % (worst, HOOK_TOKEN_BUDGET))
    if failures:
        print("\nFAIL: %s" % "; ".join(failures))
        return 1
    print("\nPASS: within budget.")
    return 0


# --------------------------------------------------------------------------- #
# why -- the rationale, fetched on demand instead of billed forever
# --------------------------------------------------------------------------- #

WHY = {
    "context": "Cost per model call against context carried, over 9,138 Opus "
               "calls: <100K $0.077 · 100-200K $0.105 · 200-300K $0.152 · "
               "300-400K $0.224 · 400-500K $0.271. Context is re-read on every "
               "call, so a large read is a recurring charge, not a one-off. "
               "Composition of one measured session's context: 35% tool "
               "results, 29% its own tool-call text, 32% its own prose and "
               "reasoning, 4% subagent reports -- almost entirely self-inflicted.",
    "heredoc": "Of 42 heredoc-authored documents measured in one program the "
               "median was 4.4KB and 32 sat under the 6000-byte floor that is "
               "right for an arbitrary large input -- so shape, not size, is "
               "the signal. 304KB across 62 writes was the single largest "
               "self-inflicted context item measured. A doc-writer subagent at "
               "the economy rung authors it from a one-paragraph spec and you "
               "hold only the path.",
    "input":   "Large tool inputs are permanent context: written once, re-read "
               "on every later model call. Prose to the human measured 111KB "
               "across 150 messages in one session. Status belongs in a file; "
               "tell the human what changed in a line or two.",
    "read":    "A worker carries a small context and dies at the end of its "
               "task, so its cache-read tax never accumulates. Yours does. "
               "Delegating a large read and taking back a conclusion is the "
               "cheapest structural saving available, and it is why 'cheaper to "
               "just do it inline' is usually wrong: that comparison weighs "
               "dispatch overhead against the task and ignores what the task's "
               "residue charges every future step.",
    "rung":    "Rung names are relative to the provider and stay correct; model "
               "names rot the next time the provider ships. The measured cost "
               "of leaving the dial alone: `default` drifted from a "
               "Sonnet-class model to an Opus-class one without the rung name "
               "changing, and 6,509 subagent calls cost $616 where the same "
               "tokens one rung down cost $246 -- 39% of a four-day bill, from "
               "a default nobody chose. Check the cache-read column before "
               "assuming a cheaper-sounding model is cheaper: moving 580 "
               "measured Fable calls to Opus would have SAVED $0.26.",
    "loop":    "A session has an irreducible floor. A window set near it means "
               "the session compacts, lands back at or above the trigger, and "
               "compacts again -- it does not error, it hangs. Observed cases "
               "compacted at model call 4, 6 and 11, and one made no further "
               "model call at all. The window is read at launch, so nothing can "
               "fix it from inside the running session.",
    "headroom": "Keep the window at roughly three times the measured floor and "
                "never below 200K. Measured floors: 7K-97K at session open (p90 "
                "50K), 39K-63K post-compaction. Note the direction of the "
                "token argument -- a lower window means a cheaper session, so "
                "cost pressure and loop safety pull against each other. "
                "Three-times-floor is a lower bound for safety, not a target.",
}


def cmd_why(args: argparse.Namespace) -> int:
    if not args.topic:
        print("topics: %s" % ", ".join(sorted(WHY)))
        return 0
    if args.topic not in WHY:
        raise SpendError("no such topic %r; try: %s"
                         % (args.topic, ", ".join(sorted(WHY))))
    print(WHY[args.topic])
    return 0


# --------------------------------------------------------------------------- #
# install -- make it the default for every session
# --------------------------------------------------------------------------- #

HOOK_MARKER = "context-economy"


def settings_path() -> str:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude")
    return os.path.join(base, "settings.json")


# Where a firing hook looks for this script, in order. Resolution happens at
# fire time rather than at install time, and that is the whole point: an earlier
# cut baked in `os.path.realpath(__file__)`, which pins all four hooks to
# whichever copy of spend.py happened to run `install`. Run it once from a git
# worktree and every hook points into a directory that disappears when the
# worktree is reclaimed -- and since each one ends in `exit 0`, the result is no
# cost line, no guard, no rung prompt, and no error to notice. These candidates
# outlive any checkout.
HOOK_DIRS = (
    '"$SPEND_SKILL_DIR"',
    '"$CLAUDE_PLUGIN_ROOT"',
    '"$HOME/.claude/skills/delegating-economically/../.."',
    '"$HOME/.agents/skills/delegating-economically/../.."',
)

DESIRED_HOOKS = (
    ("Stop", None, "cost --format hook"),
    ("PreToolUse", "Write|Edit|Bash|Read", "guard"),
    ("PreToolUse", "Task|Agent", "rung"),
    ("SessionStart", "compact|resume", "compaction check --format hook"),
)

# `python3` off PATH is an expensive thing to NAME in a hook, and the expense is
# invisible in this file: the script is cheap, getting an interpreter is not.
# Where a pyenv/asdf/conda shim sits first on PATH, resolving the name costs a
# bash process that re-execs into another bash process. Measured on one machine:
# `python3 -c pass` 477ms against 54ms for /usr/bin/python3, and the `guard` hook
# end to end 1.25s at 6% CPU against 88ms at 73% CPU -- 14x, all of it BLOCKED
# rather than computing. A blocked hook holds its shell, its shim's shell and an
# interpreter open for that whole second, and these hooks fire per tool call, in
# every concurrent session. That is how a hook nobody reads becomes a process
# storm and a load spike in the directory service that every exec consults.
#
# Resolution stays at FIRE time, for the same reason the directory search does
# (see HOOK_DIRS): a path chosen by `install` pins one machine's state into a
# settings file that outlives it.
#
# /usr/bin/python3 is preferred because it is the one interpreter whose path is
# a platform guarantee rather than a PATH accident. Everything here runs on the
# system interpreter (3.9 on macOS); `SPEND_PYTHON` is the escape hatch for
# anyone who needs a specific one, including the rare Mac with no Command Line
# Tools, where /usr/bin/python3 is present but a stub.
HOOK_PY = ('PY="${SPEND_PYTHON:-}"; [ -x "$PY" ] || PY=/usr/bin/python3; '
           '[ -x "$PY" ] || PY=python3;')

# The guard fires on every Write/Edit/Bash/Read and, on the overwhelming
# majority of them, has nothing to say. Even with the interpreter resolved that
# is ~88ms of Python startup per tool call spent reaching silence, so the common
# path is decided in the shell instead: the payload lands in a variable and
# `${#p}` is a builtin, leaving one `cat`. This is the pattern
# `browser-verification/hooks/no-google-chrome.sh` already uses.
#
# Four things this must not get wrong:
#   * `[ -t 0 ]` first. `hook_payload` returns {} rather than read a terminal,
#     precisely so an interactive run cannot block; a bare `cat` would throw
#     that away and hang forever holding a shell -- the disease, not the cure.
#   * the floor is the SMALLEST payload-size threshold the guard will apply, and
#     by default that is the heredoc one, not GUARD_BYTES. Filtering at 6000
#     would silently kill heredoc detection, the signal the guard exists for.
#     Both are resolved here and the smaller wins, because whichever one is
#     lower is the one a payload has to clear -- hardcoding the heredoc default
#     would swallow real warnings for anyone who tuned GUARD_BYTES below it.
#     GUARD_READ_BYTES is deliberately absent: a Read never reaches the compare.
#   * a Read must always reach Python: `_unbounded_read_bytes` sizes the FILE,
#     not the payload, so a 300-byte payload can still deserve a warning. The
#     match is loose on purpose -- over-matching costs one spawn, under-matching
#     loses the signal.
#   * the override names are the ones `env()` honours (SPEND_ then ORCH_), not
#     the bare constant name, or a tuned threshold is read here and ignored.
# `${#p}` counts characters rather than bytes, which is what `_tool_input_size`
# counts too, so the two agree on a multi-byte payload.
# Every numeric compare is `2>/dev/null`-guarded and fails OPEN: a threshold set
# to something non-numeric makes `[` return an error, the `&& exit 0` is skipped,
# and the payload reaches Python. A misconfigured knob costs a spawn rather than
# the warning.
GUARD_PREFILTER = (
    '[ -t 0 ] && exit 0; p=$(cat); '
    'f=${SPEND_GUARD_HEREDOC_BYTES:-${ORCH_GUARD_HEREDOC_BYTES:-%d}}; '
    'b=${SPEND_GUARD_BYTES:-${ORCH_GUARD_BYTES:-%d}}; '
    '{ [ "$b" -lt "$f" ] && f=$b; } 2>/dev/null; '
    'case "$p" in *Read*) ;; *) '
    '{ [ ${#p} -lt "$f" ] && exit 0; } 2>/dev/null ;; esac;'
    % (GUARD_HEREDOC_BYTES_DEFAULT, GUARD_BYTES_DEFAULT))


def hook_command(action: str, marker: bool = False) -> str:
    """The exact shell one hook runs. `plugin.json` ships this verbatim.

    `..` from the *skill* directory lands on the plugin root because the kernel
    resolves the symlink before applying `..` -- which is why the candidate is
    the linked skill and not the plugin directory it lives in.

    `marker` appends the comment that makes `install` idempotent: it is how a
    re-run finds its own entries in a settings file full of other people's.
    """
    prefix = HOOK_PY
    run = 'exec "$PY" "$d/scripts/spend.py" %s' % action
    if action == "guard":
        # The prefilter has already eaten stdin, so the payload is replayed on a
        # pipe. `|| continue` rather than `&& <run>` because `&&` leaves a
        # non-zero $? on a missing candidate, and `exit $?` would then abandon
        # the remaining candidates instead of trying them.
        prefix = "%s %s" % (GUARD_PREFILTER, HOOK_PY)
        run = 'printf %s "$p" | "$PY" "$d/scripts/spend.py" guard; exit $?'
    return ('%s for d in %s ; do [ -f "$d/scripts/spend.py" ] || continue; '
            '%s; done; exit 0%s'
            % (prefix, " ".join(HOOK_DIRS), run,
               "  # " + HOOK_MARKER if marker else ""))


def desired_hooks_object(marker: bool = False) -> Dict[str, Any]:
    """`DESIRED_HOOKS` as the structure both channels write.

    Single-sourced because the two channels -- `plugin.json` for a marketplace
    install, this script's `install` for the symlink path -- have to agree, and
    nothing about a session tells you which one delivered the hook that did not
    fire. `test_spend.py` asserts `plugin.json` still matches.
    """
    hooks: Dict[str, Any] = {}
    for event, matcher, action in DESIRED_HOOKS:
        entry: Dict[str, Any] = {
            "hooks": [{"type": "command", "command": hook_command(action, marker)}]}
        if matcher:
            entry["matcher"] = matcher
        hooks.setdefault(event, []).append(entry)
    return hooks


def cmd_install(args: argparse.Namespace) -> int:
    path = settings_path()
    settings = _load_json(path)
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}

    # Idempotent: every entry carries a marker comment, so a re-run replaces our
    # own hooks and never touches anyone else's.
    # Strip our own entries once per event, before adding any back. Stripping
    # inside the add loop lets a second desired hook for an event delete the
    # first -- PreToolUse has two, and the guard never survived the rung.
    removed = 0
    for event in dict.fromkeys(event for event, _, _ in DESIRED_HOOKS):
        existing = hooks.get(event, [])
        kept = [e for e in existing
                if not (isinstance(e, dict) and HOOK_MARKER in json.dumps(e))]
        removed += len(existing) - len(kept)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)

    added = 0
    if not args.uninstall:
        for event, entries in desired_hooks_object(marker=True).items():
            hooks.setdefault(event, []).extend(entries)
            added += len(entries)
    changed = removed if args.uninstall else added

    settings["hooks"] = hooks
    if args.dry_run:
        print(json.dumps({"hooks": hooks}, indent=2))
        return 0
    _save_json(path, settings)
    print("%s %d hook(s) in %s"
          % ("removed" if args.uninstall else "installed", changed, path))
    if not args.uninstall:
        print("every session in every repo now reports context cost, guards "
              "large inputs and reads, and prompts for a subagent model rung.")
    return 0


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spend", description="session cost, context hygiene, compaction safety")
    p.add_argument("--repo", default=".", help="working directory (default: .)")
    sub = p.add_subparsers(dest="command", required=True)

    cost = sub.add_parser("cost", help="what this session has cost so far")
    cost.add_argument("--transcript")
    cost.add_argument("--format", choices=("text", "json", "hook"), default="text")
    cost.set_defaults(func=cmd_cost)

    budget = sub.add_parser("budget", help="a spend limit for this repo")
    budget.add_argument("--set", type=float)
    budget.set_defaults(func=cmd_budget)

    guard = sub.add_parser("guard", help="PreToolUse: large input or read")
    guard.set_defaults(func=cmd_guard)

    rung = sub.add_parser("rung", help="PreToolUse: subagent spawned with no model")
    rung.set_defaults(func=cmd_rung)

    models = sub.add_parser(
        "models", help="live model options for a rung or task archetype")
    choice = models.add_mutually_exclusive_group(required=True)
    choice.add_argument("--rung", choices=MODEL_RUNGS)
    choice.add_argument("--archetype")
    models.add_argument(
        "--effort", choices=RELATIVE_EFFORTS + EFFORT_ORDER,
        help="preferred effort for --rung (default: default)")
    models.add_argument(
        "--exclude-family",
        help="omit an underlying family when an independent opinion is needed")
    models.add_argument("--catalog", help="live model catalog JSON")
    models.add_argument("--options", help="rung and archetype option map JSON")
    models.add_argument("--format", choices=("text", "json"), default="text")
    models.set_defaults(func=cmd_models)

    comp = sub.add_parser("compaction", help="floor, window and loop safety")
    comp.add_argument("action", choices=("measure", "check", "window"))
    comp.add_argument("--transcript")
    comp.add_argument("--format", choices=("text", "json", "hook"), default="text")
    comp.add_argument("--explain", action="store_true")
    comp.set_defaults(func=cmd_compaction)

    foot = sub.add_parser("footprint", help="this plugin's own context cost")
    foot.add_argument("--plugin-root")
    foot.set_defaults(func=cmd_footprint)

    why = sub.add_parser("why", help="the rationale behind an advisory")
    why.add_argument("topic", nargs="?")
    why.set_defaults(func=cmd_why)

    inst = sub.add_parser("install", help="register hooks for every session")
    inst.add_argument("--uninstall", action="store_true")
    inst.add_argument("--dry-run", action="store_true")
    inst.set_defaults(func=cmd_install)

    rates = sub.add_parser("rates", help="the rate table, as json")
    rates.set_defaults(func=lambda a: (print(json.dumps(load_rates(), indent=2)), 0)[1])

    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SpendError as exc:
        print("spend: %s" % exc, file=sys.stderr)
        # Hooks must never fail a turn. A cost tool that breaks the session it
        # is measuring has cost more than it saved.
        return 0
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
