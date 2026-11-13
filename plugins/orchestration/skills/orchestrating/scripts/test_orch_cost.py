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

# The floor policy in isolation: with turn-end compaction on, `window` is also
# raised clear of ORCH_COMPACT_AT (section 7), which would mask every number here.
_compact_at = orch.COMPACT_AT
orch.COMPACT_AT = 0
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

orch.COMPACT_AT = _compact_at
code, out, err = run(root, "compaction", "window", "--any-role")
check_same("with turn-end compaction on, the window sits above its threshold",
           (code, out.strip()), (0, str(orch.COMPACT_AT + orch.COMPACT_WINDOW_MARGIN)))

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

_current = transcript([model_row("claude-sonnet-5-5", _recent)])
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

# --------------------------------------------------------------------------- #
# 4. Hooks find their program in a repo with several, and the context
#    advisory's dedupe is per session. Both silenced one orchestrator at 642K.
# --------------------------------------------------------------------------- #

print("\nprogram from claim, warn dedupe")
_saved_state = os.environ.get("XDG_STATE_HOME")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
_repo = make_repo()
_rk, _, _ = orch.repo_identity(_repo)
for _name in ("alpha", "beta"):
    _pdir = orch.program_dir(_rk, _name)
    os.makedirs(_pdir, exist_ok=True)
    with open(os.path.join(_pdir, "root.json"), "w") as _fh:
        json.dump({"entries": []}, _fh)
try:
    orch.resolve_program(_rk, None, _repo)
    check_true("two programs and no claim still refuses", False)
except orch.OrchError:
    check_true("two programs and no claim still refuses", True)
with open(orch.claims_path(_rk), "w") as _fh:
    json.dump({os.path.realpath(_repo): {"target": "root", "program": "beta"}}, _fh)
check_same("the worktree's claim names the program", orch.resolve_program(_rk, None, _repo), "beta")
with open(orch.claims_path(_rk), "w") as _fh:
    json.dump({os.path.realpath(_repo): {"target": "root", "program": "gone"}}, _fh)
try:
    orch.resolve_program(_rk, None, _repo)
    check_true("a claim naming no existing program is not trusted", False)
except orch.OrchError:
    check_true("a claim naming no existing program is not trusted", True)

_adv = ["CONTEXT 300K"]
_w = lambda ctx, sess: orch._should_warn(_rk, "beta", {"context": ctx}, _adv, session=sess)
check_same("first warning speaks", _w(300_000, "a"), True)
check_same("the same level again stays quiet", _w(320_000, "a"), False)
check_same("a successor session speaks below its predecessor's mark", _w(260_000, "b"), True)
check_same("after compacting, the next climb speaks", (_w(395_000, "b"), _w(255_000, "b")), (True, True))
if _saved_state is None:
    del os.environ["XDG_STATE_HOME"]
else:
    os.environ["XDG_STATE_HOME"] = _saved_state

# --------------------------------------------------------------------------- #
# 5. `compaction due`: when the plugin should send /compact at a turn end.
# --------------------------------------------------------------------------- #

print("\ncompaction due")
_scan = lambda last, calls=200, at=None: {"last": last, "calls": calls,
    "events": [] if at is None else [{"at_call": at}]}
_due = lambda scan, floor=30_000, req=None, now=1000.0: orch.compaction_due(
    scan, floor, req or {}, "s1", now)[0]
check_same("under the threshold is not due", _due(_scan(250_000)), False)
check_same("over the threshold is due", _due(_scan(310_000)), True)
check_same("a high floor raises the threshold past COMPACT_AT",
           _due(_scan(310_000), floor=150_000), False)
check_same("a compaction a few calls ago is a loop, not due",
           _due(_scan(310_000, calls=200, at=195)), False)
check_same("a recent request for this session is not re-sent",
           _due(_scan(320_000), req={"session": "s1", "at_epoch": 900, "context": 310_000}), False)
check_same("a request that has aged out is re-sent",
           _due(_scan(320_000), req={"session": "s1", "at_epoch": 0, "context": 310_000}), True)
check_same("another session's request does not block this one",
           _due(_scan(320_000), req={"session": "s0", "at_epoch": 900, "context": 310_000}), True)
check_true("the prompt asks for a Do first list",
           "## Do first" in orch.compact_prompt())

# --------------------------------------------------------------------------- #
# 6. `compaction followup`: the first turn after a requested compaction.
# --------------------------------------------------------------------------- #

print("\ncompaction followup")
_req = {"session": "s1", "followup": "pending", "at_epoch": 900, "compactions": 1}
_fu = lambda compactions, req=_req, now=1000.0: orch.followup_due(
    {"compactions": compactions}, req, "s1", now)[0]
check_same("not owed before the compaction lands", _fu(1), False)
check_same("owed once it lands", _fu(2), True)
check_same("not owed twice", _fu(2, {**_req, "followup": "sent"}), False)
check_same("not owed for a compaction nobody requested", _fu(2, {}), False)
check_same("not owed once stale", _fu(2, now=900.0 + orch.COMPACT_FOLLOWUP_S + 1), False)

_saved_state = os.environ.get("XDG_STATE_HOME")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
_repo = make_repo()
_big = [call("r%d" % i, input_tokens=10, cache_read_input_tokens=1000 * i,
             cache_creation_input_tokens=0, output_tokens=5) for i in range(1, 40)]
_big.append(call("rlast", input_tokens=10, cache_read_input_tokens=320_000,
                 cache_creation_input_tokens=0, output_tokens=5))
_t = transcript(_big)
code, out, err = run(_repo, "compaction", "due", "--any-role", "--transcript", _t)
check_true("due prints the /compact line", code == 0 and out.startswith("/compact "))
code, out, err = run(_repo, "compaction", "followup", "--any-role", "--transcript", _t)
check_same("followup waits for the compaction", code, 3)
with open(_t, "a") as _fh:
    _fh.write(json.dumps({"type": "system", "subtype": "compact_boundary"}) + "\n")
    _fh.write(json.dumps(call("rpost", input_tokens=10, cache_read_input_tokens=30_000,
                              cache_creation_input_tokens=0, output_tokens=5)) + "\n")
code, out, err = run(_repo, "compaction", "followup", "--any-role", "--transcript", _t)
check_true("followup prints the Do-first prompt once it lands",
           code == 0 and "Do first" in out)
code, out, err = run(_repo, "compaction", "followup", "--any-role", "--transcript", _t)
check_same("and only once", code, 3)
if _saved_state is None:
    del os.environ["XDG_STATE_HOME"]
else:
    os.environ["XDG_STATE_HOME"] = _saved_state

# --------------------------------------------------------------------------- #
# 6b. A `/compact` cancelled by a notification is retried on a backoff.
# --------------------------------------------------------------------------- #

print("\ncompaction cancelled")
_B, _MAX, _WIN = (orch.COMPACT_BACKOFF_S, orch.COMPACT_MAX_ATTEMPTS,
                  orch.COMPACT_ATTEMPT_WINDOW_S)
_cscan = lambda cancels, compactions=0: {"last": 320_000, "calls": 200, "events": [],
    "compactions": compactions, "cancels": cancels}
_creq = lambda attempts, at=1000.0, **kw: {"session": "s1", "at_epoch": at, "context": 310_000,
    "compactions": 0, "attempts": attempts, "first_epoch": 1000.0, **kw}
_cdue = lambda scan, req, now: orch.compaction_due(scan, 30_000, req, "s1", now)
_sc = _cscan([1012.0])
check_same("a cancelled request is refused inside the first backoff",
           _cdue(_sc, _creq(1), 1012.0 + _B - 1)[0], False)
check_true("and the reason says cancelled and which retry",
           "cancelled; retry 2/%d in" % _MAX in _cdue(_sc, _creq(1), 1020.0)[1])
check_same("it is allowed once the backoff has passed",
           _cdue(_sc, _creq(1), 1012.0 + _B)[0], True)
check_same("a cancelled request is retried well inside COMPACT_RETRY_S",
           _cdue(_sc, _creq(1), 1012.0 + _B)[0] and _B < orch.COMPACT_RETRY_S, True)
check_same("the second backoff is double", (
    _cdue(_sc, _creq(2), 1012.0 + 2 * _B - 1)[0], _cdue(_sc, _creq(2), 1012.0 + 2 * _B)[0]),
    (False, True))
check_same("the third is quadruple", (
    _cdue(_sc, _creq(3), 1012.0 + 4 * _B - 1)[0], _cdue(_sc, _creq(3), 1012.0 + 4 * _B)[0]),
    (False, True))
check_same("the cap refuses even long after the backoff",
           _cdue(_sc, _creq(_MAX), 1012.0 + 10 * _B)[0], False)
check_true("with a reason that says so",
           "cancelled %d times" % _MAX in _cdue(_sc, _creq(_MAX), 1100.0)[1])
check_same("once the window has passed the series restarts",
           _cdue(_sc, _creq(_MAX), 1000.0 + _WIN)[0], True)
check_same("a landed compaction resets the attempts",
           orch.compaction_attempts(_cscan([1012.0], compactions=1), _creq(3), "s1", 1100.0)[0], 0)
check_same("and a boundary after the cancel means it is not cancelled",
           orch.compaction_cancelled_at(_cscan([1012.0], compactions=1), _creq(1), "s1"), 0.0)
check_same("another session's attempts do not count",
           orch.compaction_attempts(_sc, _creq(3), "s0", 1100.0)[0], 0)
check_same("a cancel row older than the request is not this request's",
           _cdue(_cscan([900.0]), _creq(1), 1100.0)[0], False)
check_true("so the old in-flight guard still speaks for it",
           "already requested" in _cdue(_cscan([900.0]), _creq(1), 1100.0)[1])
check_same("an in-flight request with no cancel row is allowed after COMPACT_RETRY_S",
           _cdue(_cscan([]), _creq(1), 1000.0 + orch.COMPACT_RETRY_S)[0], True)
check_same("a marker from before `attempts` counts as one",
           orch.compaction_attempts(_sc, {k: v for k, v in _creq(1).items()
                                          if k not in ("attempts", "first_epoch")},
                                    "s1", 1100.0)[0], 1)
check_same("exhaustion is reported only at the cap",
           (orch.compaction_exhausted(_sc, _creq(_MAX - 1), "s1", 1100.0),
            orch.compaction_exhausted(_sc, _creq(_MAX), "s1", 1100.0)), (0, _MAX))
check_same("and not once its window has passed",
           orch.compaction_exhausted(_sc, _creq(_MAX), "s1", 1000.0 + _WIN), 0)

_saved_state = os.environ.get("XDG_STATE_HOME")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
_repo = make_repo()
_rk, _, _ = orch.repo_identity(_repo)
_big = [call("r%d" % i, input_tokens=10, cache_read_input_tokens=1000 * i,
             cache_creation_input_tokens=0, output_tokens=5) for i in range(1, 40)]
_big.append(call("rlast", input_tokens=10, cache_read_input_tokens=320_000,
                 cache_creation_input_tokens=0, output_tokens=5))
_t = transcript(_big)
code, out, err = run(_repo, "compaction", "due", "--any-role", "--transcript", _t)
check_true("e2e: due prints the first time", code == 0 and out.startswith("/compact "))
_stamp = lambda secs: (datetime.now(timezone.utc) + timedelta(seconds=secs)).isoformat()
with open(_t, "a") as _fh:
    _fh.write(json.dumps({"type": "system", "subtype": "local_command", "timestamp": _stamp(1),
        "content": "<local-command-stdout>Compaction canceled.</local-command-stdout>"}) + "\n")
code, out, err = run(_repo, "compaction", "due", "--any-role", "--explain", "--transcript", _t)
check_true("e2e: refused inside the backoff, saying why",
           code == 3 and "cancelled; retry 2/" in err)
_mfiles = [os.path.join(d, f) for d, _, fs in os.walk(os.environ["XDG_STATE_HOME"])
           for f in fs if f == "compact-requested.json"]
check_same("e2e: one marker was written", len(_mfiles), 1)
_m = json.load(open(_mfiles[0]))
check_same("e2e: and it counts the attempt", _m["attempts"], 1)
_m["at_epoch"] -= _B + 5
_m["first_epoch"] -= _B + 5
with open(_mfiles[0], "w") as _fh:
    json.dump(_m, _fh)
# The cancel row is stamped 1s after the real request; age the whole series so
# the backoff has run out without sleeping.
_rows = [json.loads(l) for l in open(_t)]
for _r in _rows:
    if _r.get("subtype") == "local_command":
        _r["timestamp"] = _stamp(-(_B + 4))
with open(_t, "w") as _fh:
    _fh.write("".join(json.dumps(r) + "\n" for r in _rows))
code, out, err = run(_repo, "compaction", "due", "--any-role", "--transcript", _t)
check_true("e2e: printed again after the backoff", code == 0 and out.startswith("/compact "))
check_same("e2e: attempt 2 recorded", json.load(open(_mfiles[0]))["attempts"], 2)
if _saved_state is None:
    del os.environ["XDG_STATE_HOME"]
else:
    os.environ["XDG_STATE_HOME"] = _saved_state

# --------------------------------------------------------------------------- #
# 7. The harness window is a backstop, above the turn-end threshold.
# --------------------------------------------------------------------------- #

print("\nbackstop window")
check_same("a blind 300K window is raised clear of ORCH_COMPACT_AT",
           orch.backstop_window(300_000), orch.COMPACT_AT + orch.COMPACT_WINDOW_MARGIN)
check_same("a window already higher is kept", orch.backstop_window(700_000), 700_000)
check_same("never past the harness ceiling", orch.backstop_window(2_000_000), orch.WINDOW_CEILING)

print()
if FAILURES:
    print("  %d FAILURE(S): %s" % (len(FAILURES), ", ".join(FAILURES)))
    sys.exit(1)
print("  all pass")
