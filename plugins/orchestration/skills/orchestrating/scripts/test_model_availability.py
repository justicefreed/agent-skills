#!/usr/bin/env python3
"""Model-policy fixtures for `orch open` and `orch models check`.

Run: python3 test_model_availability.py
"""

import contextlib
import importlib.util
import io
import json
import os
import tempfile
from pathlib import Path

HERE = Path(__file__).parent


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


availability = module("model_availability", "model_availability.py")
orch = module("orch", "orch.py")
FAILURES = []


def check(name, got, want):
    if got != want:
        FAILURES.append(name)
    print("  %-68s %s" % (name, "ok" if got == want else "FAIL"))
    if got != want:
        print("    got %r\n    want %r" % (got, want))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


root = Path(tempfile.mkdtemp(prefix="orch-model-policy-"))
managed = root / "managed"
claude = root / "claude"
paseo = root / "paseo"
write(managed / "managed-settings.json", {
    "availableModels": ["claude-sonnet-5-5"],
    "availableModelsMatch": "exact",
    "deniedModels": ["claude-opus-5"],
})
write(paseo / "config.json", {"agents": {"providers": {"claude": {
    "models": [
        {"id": "claude-sonnet-5-5", "label": "Sonnet 5.5",
         "thinkingOptions": ["low", "medium", "high"]},
        {"id": "claude-opus-5-5", "label": "Opus 5.5"},
    ],
    # The same id only changes its presentation; it must not become a second
    # allowed model. Plain strings remain accepted for older configurations.
    "additionalModels": [
        {"id": "claude-opus-5-5", "label": "Opus 5.5 (preferred)"},
        "claude-haiku-5-5",
    ],
}}}})
policy = availability.policy(environ={"CLAUDE_CONFIG_DIR": str(claude)},
                             managed_root=managed, paseo_home=paseo)
claude_code_only = dict(policy, paseo=None)
check("exact availableModels retains a dated spelling",
      availability.allowed("claude-sonnet-5-5-20260101", claude_code_only)[0], True)
check("exact availableModels rejects another minor",
      availability.allowed("claude-sonnet-5-6", claude_code_only)[0], False)
check("managed deniedModels blocks later minor versions",
      availability.allowed("claude-opus-5-5", policy)[1], "Claude Code availableModels")
check("Paseo ProviderProfileModel object id permits its model",
      availability.allowed("claude-sonnet-5-5", policy)[0], True)

# The prior check proves availableModels.  With the allowlist broadened, a
# managed denial itself makes the candidate go red; this is the regression
# fixture the dispatch filter is intended to prevent.
write(managed / "managed-settings.json", {
    "availableModels": ["opus"],
    "deniedModels": ["claude-opus-5"],
})
policy = availability.policy(environ={"CLAUDE_CONFIG_DIR": str(claude)},
                             managed_root=managed, paseo_home=paseo)
check("a managed deniedModels fixture blocks the recommended Opus",
      availability.allowed("claude-opus-5-5", policy)[1], "Claude Code deniedModels")
policy_without_claude_allowlist = dict(policy, available=None, denied=[])
check("Paseo static list is also enforced",
      availability.allowed("claude-fable-5-2", policy_without_claude_allowlist)[1],
      "Paseo agents.providers.claude.models")
check("a Paseo additionalModels relabel does not duplicate its id",
      policy["paseo"].count("claude-opus-5-5"), 1)

unrestricted = availability.policy(environ={"CLAUDE_CONFIG_DIR": str(root / "empty")},
                                   managed_root=root / "none", paseo_home=root / "none-paseo")
check("absent configuration allows every Claude model",
      availability.allowed("claude-opus-5-5", unrestricted)[0], True)

original = orch.availability_for
try:
    orch.availability_for = lambda repo: policy
    rows = orch.rung_models("advanced", availability=policy)
    check("availability filtering drops a disallowed Claude recommendation",
          "claude-opus-5-5" in [row["model"] for row in rows], False)

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = orch.main(["models", "check"])
    check("models check returns nonzero for a disallowed recommendation", code, 1)
    check("models check identifies the rung and model",
          "advanced claude-opus-5-5" in out.getvalue(), True)
finally:
    orch.availability_for = original

print()
if FAILURES:
    print("  %d FAILURE(S): %s" % (len(FAILURES), ", ".join(FAILURES)))
    raise SystemExit(1)
print("  all pass")
