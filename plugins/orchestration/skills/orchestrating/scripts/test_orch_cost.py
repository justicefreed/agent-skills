#!/usr/bin/env python3
"""Pin the cost-side changes: the per-turn call advisory, the compaction
window honouring a measured floor, and the resumed-session model check.

Run: python3 test_orch_cost.py

Three behaviours, one file, because all three are the same kind of fix: a
number that was being computed or applied even though a better one had been
measured. The turn-call count was not computed at all; the compaction window
overrode a measured 200K with a blind 300K; the model check did not exist.

No test framework, matching the plugin: one file, standard library only.
"""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.realpath(__file__))
_spec = importlib.util.spec_from_file_location("orch", os.path.join(HERE, "orch.py"))
orch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(orch)

FAILURES = []


def check_same(name, got, want):
    ok = got == want
    if not ok:
        FAILURES.append(name)
    print("  %-66s %s" % (name, "ok" if ok else "FAIL"))
    if not ok:
        print("    got  %r\n    want %r" % (got, want))


def check_true(name, got):
    check_same(name, bool(got), True)


def run(repo, command, *rest):
    out, err = io.StringIO(), io.StringIO()
    argv = (["--repo", repo] if repo else []) + [command] + list(rest)
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = orch.main(argv)
    return code, out.getvalue(), err.getvalue()


def make_repo():
    root = tempfile.mkdtemp(prefix="orch-cost-")
    subprocess.run(["git", "init", "-q", root], check=True)
    return root


def transcript(rows):
    fh = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for row in rows:
        fh.write(json.dumps(row) + "\n")
    fh.close()
    return fh.name


def call(request_id, **usage):
    return {"type": "assistant", "requestId": request_id,
            "message": {"model": "claude-opus-5", "id": "m" + request_id,
                        "usage": usage}}


def human(text):
    return {"type": "user", "message": {"content": text}}


def model_row(model, timestamp, context=1000):
    return {"type": "assistant", "requestId": "r1", "timestamp": timestamp,
            "message": {"model": model, "id": "m1",
                        "usage": {"input_tokens": context, "output_tokens": 10,
                                  "cache_read_input_tokens": 0,
                                  "cache_creation_input_tokens": 0}}}


def hook_model_check(transcript_path, source="resume"):
    """Run `model check --format hook` with a synthetic SessionStart payload."""
    orch._HOOK_PAYLOAD = {"source": source, "transcript_path": transcript_path}
    orch._HOOK_PAYLOAD_READ = True
    try:
        code, out, err = run(None, "model", "check", "--format", "hook")
    finally:
        orch._HOOK_PAYLOAD, orch._HOOK_PAYLOAD_READ = None, False
    return code, out, err


# --------------------------------------------------------------------------- #
# 1. The compaction window honours a measured floor.
# --------------------------------------------------------------------------- #

root = make_repo()
repo_key, _, _ = orch.repo_identity(root)
program = orch.resolve_program(repo_key, None)
cpath = orch.compaction_path(repo_key, program)
os.makedirs(os.path.dirname(cpath), exist_ok=True)

with open(cpath, "w", encoding="utf-8") as fh:
    json.dump({"floor": 51000, "window": 200000}, fh)
code, out, err = run(root, "compaction", "window", "--any-role", "--explain")
check_same("a measured floor keeps its recorded window", (code, out.strip()),
           (0, "200000"))
check_true("and the explain line says the window is measured",
           "measured" in err and "blind" not in err)

with open(cpath, "w", encoding="utf-8") as fh:
    json.dump({"window": 200000}, fh)
code, out, err = run(root, "compaction", "window", "--any-role", "--explain")
check_same("no measured floor falls back to the blind default",
           (code, out.strip()), (0, "300000"))
check_true("and the explain line says the window is blind",
           "blind" in err)

with open(cpath, "w", encoding="utf-8") as fh:
    json.dump({"floor": 51000, "window": 150000}, fh)
code, out, err = run(root, "compaction", "window", "--any-role", "--explain")
check_same("a recorded window below the safe minimum is clamped up",
           (code, out.strip()), (0, "200000"))

# --------------------------------------------------------------------------- #
# 2. The per-turn call count, and the STEPS advisory.
# --------------------------------------------------------------------------- #

_rates = orch.load_rates(None, None)
rows = [human("first turn")] + [call("r%d" % i, input_tokens=1000,
                                     output_tokens=10) for i in range(5)]
rows += [human("second turn")] + [call("r%d" % (10 + i), input_tokens=1000,
                                       output_tokens=10) for i in range(3)]
usage = orch.read_usage(transcript(rows), _rates)
check_same("turn_calls counts calls since the most recent human turn",
           usage["turn_calls"], 3)
check_same("and human_turns still counts both turns", usage["human_turns"], 2)

rows = [human("turn")] + [call("dup", input_tokens=1000, output_tokens=10)] * 3
usage = orch.read_usage(transcript(rows), _rates)
check_same("a response spanning several lines counts once",
           usage["turn_calls"], 1)

rows = [human("turn")] + [call("r%d" % i, input_tokens=1000,
                               output_tokens=10) for i in range(12)]
usage = orch.read_usage(transcript(rows), _rates)
check_same("turn_calls is in the usage dict for --format json",
           usage["turn_calls"], 12)
adv = orch.cost_advisories(usage, {}, 0)
check_true("12 calls in one turn raises the STEPS advisory",
           any(a.startswith("STEPS") for a in adv))
check_true("and the advisory carries the action",
           any("stop polling" in a for a in adv))
adv = orch.cost_advisories(dict(usage, turn_calls=11), {}, 0)
check_same("11 calls in one turn stays silent", adv, [])

# --------------------------------------------------------------------------- #
# 3. The resumed-session model check.
# --------------------------------------------------------------------------- #

_now = datetime.now(timezone.utc)
_recent = _now.isoformat()
_stale = (_now - timedelta(hours=2)).isoformat().replace("+00:00", "Z")

_superseded = transcript([model_row("claude-opus-5", _recent)])
code, out, err = run(None, "model", "check", "--transcript", _superseded)
check_same("a superseded model reports in text format", code, 0)
check_true("naming the preferred sibling",
           "claude-opus-5-5" in out and "superseded" in out)

_unknown = transcript([model_row("gpt-4o", _recent)])
code, out, err = run(None, "model", "check", "--transcript", _unknown)
check_true("a model outside the catalogue reports it cannot be checked",
           "not in the model catalogue" in out)

_current = transcript([model_row("claude-sonnet-5", _recent)])
code, out, err = hook_model_check(_current)
check_same("a current model is silent in hook format", (code, out.strip()), (0, ""))
code, out, err = run(None, "model", "check", "--transcript", _current)
check_true("and text format still reports it", "current" in out)

_cold = transcript([model_row("claude-opus-5", _stale, context=61000)])
code, out, err = run(None, "model", "check", "--transcript", _cold)
check_true("a session idle past an hour gets the cold-cache note",
           "cache is cold" in out and "61K" in out)

code, out, err = hook_model_check(_superseded, source="startup")
check_same("a non-resume SessionStart stays silent", (code, out.strip()), (0, ""))
code, out, err = hook_model_check(_superseded, source="resume")
check_true("a resume SessionStart speaks", code == 0 and "MODEL" in out)

print()
if FAILURES:
    print("  %d FAILURE(S): %s" % (len(FAILURES), ", ".join(FAILURES)))
    sys.exit(1)
print("  all pass")
