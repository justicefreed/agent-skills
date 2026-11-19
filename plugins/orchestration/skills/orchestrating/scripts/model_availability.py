"""Claude model availability as configured on this machine.

The catalogue is portable; these settings are not.  Keep this reader separate
from ``orch.py`` so callers can inject every path in tests and so a missing or
malformed optional configuration never makes dispatch unavailable.
"""

import json
import os
import platform
from pathlib import Path


FAMILY_ALIASES = ("fable", "opus", "sonnet", "haiku")
IGNORED_ALIASES = ("best", "opusplan", "default")


def _json(path):
    try:
        with Path(path).open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def paths(repo=None, environ=None, system=None, managed_root=None):
    """Configuration paths, ordered from highest to lowest precedence."""
    environ = os.environ if environ is None else environ
    system = platform.system() if system is None else system
    managed_root = Path(managed_root or (
        "/Library/Application Support/ClaudeCode" if system == "Darwin"
        else "/etc/claude-code"))
    managed = [managed_root / "managed-settings.json"]
    dropins = managed_root / "managed-settings.d"
    if dropins.is_dir():
        managed.extend(reversed(sorted(path for path in dropins.glob("*.json")
                                       if not path.name.startswith("."))))
    claude_home = Path(environ.get("CLAUDE_CONFIG_DIR",
                                   str(Path.home() / ".claude")))
    result = managed + [claude_home / "settings.json"]
    if repo:
        root = Path(repo)
        result.extend((root / ".claude" / "settings.local.json",
                       root / ".claude" / "settings.json"))
    return result


def _first(layers, key):
    for layer in layers:
        if key in layer:
            return layer[key]
    return None


def _models(value):
    return [str(item).strip().lower() for item in value
            if isinstance(item, str) and str(item).strip()
            and str(item).strip().lower() not in IGNORED_ALIASES] if isinstance(value, list) else None


def _family(model):
    for family in FAMILY_ALIASES:
        if model.startswith("claude-" + family + "-"):
            return family
    return None


def _normal(model):
    """Claude Code's denied-model comparison ignores dates, fast and routes."""
    model = model.lower().split("/", 1)[-1]
    model = model.replace("-fast", "")
    return model.split("-202", 1)[0]


def _matches(model, rule, exact=False):
    if rule in FAMILY_ALIASES:
        return _family(model) == rule
    if exact:
        # Claude Code documents exact as retaining dated and -fast spellings
        # of the named release, but not permitting a later minor release.
        return _normal(model) == _normal(rule)
    return model == rule or model.startswith(rule + "-")


def _paseo_models(path):
    """Paseo ProviderProfileModel entries are objects; old configs use strings."""
    def ids(value):
        if not isinstance(value, list):
            return None
        result = []
        for item in value:
            model_id = item if isinstance(item, str) else (
                item.get("id") if isinstance(item, dict) else None)
            if isinstance(model_id, str) and model_id.strip():
                result.append(model_id.strip().lower())
        return result

    data = _json(path)
    try:
        claude = data["agents"]["providers"]["claude"]
    except (KeyError, TypeError):
        return None
    models = ids(claude.get("models"))
    extra = ids(claude.get("additionalModels")) or []
    if models is None:
        return None
    # `additionalModels` is a union, not a second provider row: an object
    # sharing an id can relabel or add thinking options without changing reach.
    return list(dict.fromkeys(models + extra))


def policy(repo=None, environ=None, system=None, managed_root=None, paseo_home=None):
    """Return effective Claude policy; omitted restrictions mean all allowed."""
    environ = os.environ if environ is None else environ
    config_paths = paths(repo, environ, system, managed_root)
    layers = [_json(path) for path in config_paths]
    managed_count = 1 + sum(1 for path in config_paths[1:]
                            if path.parent.name == "managed-settings.d")
    managed_layers = layers[:managed_count]
    allowed = _models(_first(layers, "availableModels"))
    match = str(_first(managed_layers, "availableModelsMatch") or "prefix").lower()
    denied = []
    for layer in managed_layers:
        denied.extend(_models(layer.get("deniedModels")) or [])
    paseo_root = Path(paseo_home or environ.get("PASEO_HOME") or Path.home() / ".paseo")
    paseo = _paseo_models(paseo_root / "config.json")
    return {"available": allowed, "match": match, "denied": denied, "paseo": paseo,
            "paths": [str(path) for path in config_paths],
            "paseo_path": str(paseo_root / "config.json")}


def allowed(model, current):
    """Whether one canonical Claude ID survives all active restrictions."""
    model = str(model).lower()
    available = current["available"]
    if available is not None and not any(
            _matches(model, rule, current["match"] == "exact") for rule in available):
        return False, "Claude Code availableModels"
    normal = _normal(model)
    if any(_matches(normal, _normal(rule)) for rule in current["denied"]):
        return False, "Claude Code deniedModels"
    paseo = current["paseo"]
    if paseo is not None and model not in paseo:
        return False, "Paseo agents.providers.claude.models"
    return True, ""


def filter_rows(rows, current):
    kept, dropped = [], []
    for row in rows:
        if row.get("provider") != "anthropic":
            kept.append(row)
            continue
        ok, reason = allowed(row["model"], current)
        (kept if ok else dropped).append(row if ok else (row, reason))
    return kept, dropped
