#!/usr/bin/env python3
"""Pin the deterministic-adherence levers (spec orch-adherence, section P8).

Run: python3 test_orch_adherence.py

Expected to be red until the core lane lands; every failing check names its P8
item. A fake `track` (testdata/fake-track) logs every call so the suite can
assert that `stop-check` never calls it. Standard library only; Python 3.9.
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.realpath(__file__))
os.environ.setdefault("ORCH_FANOUT_MAX", "100")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp(prefix="orch-adh-state-")
for _k in ("ORCH_HOME", "ORCH_CHECKPOINT_STALE_MIN"):
    os.environ.pop(_k, None)
_spec = importlib.util.spec_from_file_location("orch", os.path.join(HERE, "orch.py"))
orch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(orch)

BASE_PATH = os.environ.get("PATH", "")
BIN = tempfile.mkdtemp(prefix="orch-adh-bin-")
shutil.copy(os.path.join(HERE, "testdata", "fake-track"), os.path.join(BIN, "track"))
os.chmod(os.path.join(BIN, "track"), 0o755)
NO_TRACK_PATH = "/usr/bin:/bin"

FAILURES = []


def check_same(name, got, want):
    ok = got == want
    if not ok:
        FAILURES.append(name)
    print("  %-78s %s" % (name, "ok" if ok else "FAIL"))
    if not ok:
        print("    got  %r\n    want %r" % (got, want))


def check_true(name, got):
    check_same(name, bool(got), True)


def case(fn):
    try:
        fn()
    except BaseException as exc:  # noqa: BLE001 - report, keep going
        if isinstance(exc, KeyboardInterrupt):
            raise
        FAILURES.append(fn.__name__)
        print("  %-78s FAIL (crashed)" % fn.__name__)
        print("    " + traceback.format_exc().strip().replace("\n", "\n    "))
    finally:
        os.environ["PATH"] = BIN + os.pathsep + BASE_PATH
        os.environ.pop("FAKE_TRACK_CALLS", None)


def fresh():
    cache = getattr(orch, "_repo_identity", None)
    if hasattr(cache, "cache_clear"):
        cache.cache_clear()


def run(repo, command, *rest, **kw):
    out, err = io.StringIO(), io.StringIO()
    stdin = sys.stdin
    sys.stdin = io.StringIO(kw.get("stdin", ""))
    orch._HOOK_PAYLOAD, orch._HOOK_PAYLOAD_READ = None, False
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = orch.main(["--repo", repo, command] + list(rest))
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 2
            except BaseException as exc:  # noqa: BLE001 - a crash is a failed check, not a dead suite
                if isinstance(exc, KeyboardInterrupt):
                    raise
                code = 99
                err.write("crashed: %r\n" % (exc,))
    finally:
        sys.stdin = stdin
    fresh()
    return code, out.getvalue(), err.getvalue()


def sh(*cmd):
    return subprocess.run(list(cmd), check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, universal_newlines=True).stdout.strip()


def make_repo():
    root = os.path.realpath(tempfile.mkdtemp(prefix="orch-adh-"))
    sh("git", "init", "-q", root)
    sh("git", "-C", root, "-c", "user.name=t", "-c", "user.email=t@t",
       "commit", "-q", "--allow-empty", "-m", "init")
    return root


def linked_worktree(repo, name):
    path = os.path.join(os.path.dirname(repo), "%s-%s" % (os.path.basename(repo), name))
    sh("git", "-C", repo, "worktree", "add", "-q", "-b", name, path)
    return os.path.realpath(path)


TASKS = [{"label": "Implement retry policy", "checked": False},
         {"label": "Verify production behavior", "checked": False}]
ADV = "\n  - track: T-015\n    expect: Implement retry policy"
GOOD_CKPT = ("Last durable milestone: committed the retry module\n"
             "Verification: unit tests pass\n"
             "Uncertain external effects: none\n"
             "Next safe action: open the pull request\n")
VACUOUS_CKPT = GOOD_CKPT.replace("open the pull request", "continue")


def write_brief(where, worktree, name, advances, **extra):
    lines = ["title: adherence lane", "worktree: %s" % worktree,
             "expected_artifacts:", "  - out.txt", "advances: %s" % advances,
             "consumption: this test reads it", "archetype: implementer"]
    lines += ["%s: %s" % kv for kv in extra.items()]
    path = os.path.join(where, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("---\n%s\n---\n\n# body\n" % "\n".join(lines))
    return path


class Scenario(object):
    """P (planning repo, also the home root) with one lane opened at policy `off`."""

    def __init__(self, advances="none", track_dir=False, **brief):
        self.p = make_repo()
        self.fixture = os.path.join(tempfile.mkdtemp(prefix="orch-adh-fx-"), "fx.json")
        self.log = self.fixture + ".log"
        with open(self.fixture, "w", encoding="utf-8") as fh:
            json.dump({"items": {"T-015": {"title": "retry work", "blockedBy": [],
                                           "tasks": [dict(t) for t in TASKS]}}}, fh)
        os.environ["FAKE_TRACK_FIXTURE"] = self.fixture
        os.environ["FAKE_TRACK_LOG"] = self.log
        os.environ["PATH"] = BIN + os.pathsep + BASE_PATH
        if track_dir:
            os.makedirs(os.path.join(self.p, ".track"))
        self.cw = linked_worktree(self.p, "lane")
        self.opened = self.open(advances, "brief.md", self.cw, **brief)
        self.eid = self.entry()["entry"] if self.entry() else None

    def open(self, advances, name, worktree=None, **brief):
        wt = worktree or linked_worktree(self.p, name.replace(".", "-"))
        return run(self.p, "open", "--agent-id", "agent-%s" % name,
                   "--brief", write_brief(self.p, wt, name, advances, **brief))

    @property
    def key(self):
        return orch.repo_identity(self.p)[0]

    def program_dir(self):
        return orch.program_dir(self.key, orch.resolve_program(self.key, None))

    def tracker(self):
        return orch.tracker_path(self.key, orch.resolve_program(self.key, None), "root")

    def entries(self):
        if not os.path.exists(self.tracker()):
            return []
        return orch.load_tracker(self.tracker())["entries"]

    def entry(self):
        ents = self.entries()
        return ents[0] if ents else None

    def set_level(self, level):
        """Write policy.json in the spec's format, independent of the `policy` command."""
        with open(os.path.join(self.program_dir(), "policy.json"), "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "level": level, "set_at": "2026-01-01T00:00:00+00:00"}, fh)

    def overrides(self):
        try:
            with open(os.path.join(self.program_dir(), "overrides.jsonl"), "r",
                      encoding="utf-8") as fh:
                return [json.loads(ln) for ln in fh.read().splitlines() if ln.strip()]
        except OSError:
            return []

    def ckpt(self, text, age_min=0):
        path = os.path.join(self.cw, "progress.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        when = time.time() - age_min * 60
        os.utime(path, (when, when))

    def write_exception(self):
        path = os.path.join(self.program_dir(), "exceptions", "root.%s.json" % self.eid)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "tracker": "root", "entry": self.eid, "title": "x",
                       "attempts": 1, "targets": [{"track": "T-015", "state": "failed",
                                                   "code": "WRITE_CONFLICT", "repair": "r"}]}, fh)


def lane_scenario(level="strict", ckpt=VACUOUS_CKPT, **kw):
    sc = Scenario(progress_artifact="progress.md", **kw)
    if ckpt is not None:
        sc.ckpt(ckpt)
    sc.set_level(level)
    return sc


def stop(cwd, **payload):
    """Run the hook; return (code, raw stdout, parsed JSON or None)."""
    payload.setdefault("cwd", cwd)
    code, out, err = run(cwd, "stop-check", "--format", "hook", stdin=json.dumps(payload))
    try:
        parsed = json.loads(out) if out.strip() else None
    except ValueError:
        parsed = "unparseable"
    return code, out, parsed


def blocks(parsed):
    return isinstance(parsed, dict) and parsed.get("decision") == "block"


def reason_of(parsed):
    return str(parsed.get("reason", "")) if isinstance(parsed, dict) else ""


def context(parsed):
    if not isinstance(parsed, dict):
        return None
    return parsed.get("hookSpecificOutput", {}).get("additionalContext")


# --------------------------------------------------------------------------- #
# P8.1  P1 policy
# --------------------------------------------------------------------------- #

def case_p1_policy():
    sc = Scenario()
    code, out, err = run(sc.p, "policy")
    check_true("P8.1: default level is off", code == 0 and "off" in out)
    for level in ("warn", "strict", "off"):
        code, out, err = run(sc.p, "policy", level)
        code2, out2, err2 = run(sc.p, "policy")
        check_true("P8.1: `policy %s` sets it and `policy` shows it" % level,
                   code == 0 and code2 == 0 and level in out2)
    run(sc.p, "policy", "strict")
    code, out, err = run(sc.p, "policy", "paranoid")
    check_true("P8.1: an invalid level is refused", code != 0)
    check_true("P8.1: the refused level left `strict` in place",
               "strict" in run(sc.p, "policy")[1])
    code, out, err = run(sc.p, "roster")
    check_true("P8.1: roster header shows strict", "strict" in out)
    code, out, err = run(sc.p, "resume")
    check_true("P8.1: resume prints the level when not off", "strict" in out)


# --------------------------------------------------------------------------- #
# P8.2  P2 close refuses track-linked entries
# --------------------------------------------------------------------------- #

def case_p2_close():
    sc = Scenario(advances=ADV)
    before = open(sc.tracker(), "rb").read()
    code, out, err = run(sc.p, "close", sc.eid, "--consumed", "it landed")
    check_true("P8.2: close refuses a mapping entry and names the track target",
               code != 0 and "T-015" in err and "--untracked" in err)
    check_same("P8.2: the tracker is unchanged after the refusal",
               open(sc.tracker(), "rb").read(), before)
    code, out, err = run(sc.p, "close", sc.eid, "--consumed", "it landed", "--untracked", "TBD")
    check_true("P8.2: a placeholder --untracked reason is refused",
               code != 0 and len(sc.entries()) == 1)
    code, out, err = run(sc.p, "close", sc.eid, "--consumed", "it landed",
                         "--untracked", "item superseded by a manual fix")
    check_true("P8.2: --untracked with a real reason closes the entry",
               code == 0 and sc.entry() is None)
    ovr = sc.overrides()
    check_true("P8.2: the close appended one untracked-close override (P6)",
               len(ovr) == 1 and ovr[0].get("kind") == "untracked-close"
               and ovr[0].get("entry") == sc.eid
               and "superseded" in str(ovr[0].get("reason")))
    legacy = Scenario(advances="\n  - 3.4")
    code, out, err = run(legacy.p, "close", legacy.eid, "--consumed", "done by hand")
    check_true("P8.2: a legacy plan-id entry closes as before",
               code == 0 and legacy.entry() is None)


# --------------------------------------------------------------------------- #
# P8.3  P3 open requires a track target
# --------------------------------------------------------------------------- #

def p3_scenario(level, track_dir=True):
    sc = Scenario(track_dir=track_dir)   # seed lane opened at off so the program exists
    sc.set_level(level)
    return sc


def case_p3_open():
    sc = p3_scenario("strict")
    code, out, err = sc.open("none", "m1.md")
    check_true("P8.3: strict + .track + track: an unmapped brief is refused",
               code != 0 and "untracked_reason" in err and len(sc.entries()) == 1)
    code, out, err = sc.open("\n  - 3.4", "m2.md")
    check_true("P8.3: a legacy plan id does not count as a track target",
               code != 0 and len(sc.entries()) == 1)
    code, out, err = sc.open("none", "m3.md", untracked_reason="spike with no tracked item")
    ovr = sc.overrides()
    check_true("P8.3: untracked_reason opens the lane", code == 0 and len(sc.entries()) == 2)
    check_true("P8.3: ... and appends an untracked-open override (P6)",
               len(ovr) == 1 and ovr[0].get("kind") == "untracked-open"
               and "spike" in str(ovr[0].get("reason")))
    code, out, err = sc.open("none", "m4.md", untracked_reason="TBD")
    check_true("P8.3: a placeholder untracked_reason is refused", code != 0)

    sc = p3_scenario("warn")
    code, out, err = sc.open("none", "m5.md")
    check_true("P8.3: warn opens with a one-line stderr warning",
               code == 0 and len(sc.entries()) == 2 and "untracked_reason" in err)

    sc = p3_scenario("strict", track_dir=False)
    code, out, err = sc.open("none", "m6.md")
    check_true("P8.3: strict without .track/ opens (the non-agent-track user)",
               code == 0 and len(sc.entries()) == 2)

    sc = p3_scenario("strict")
    os.environ["PATH"] = NO_TRACK_PATH
    code, out, err = sc.open("none", "m7.md")
    check_true("P8.3: strict with .track/ but no `track` on PATH opens",
               code == 0 and len(sc.entries()) == 2)


# --------------------------------------------------------------------------- #
# P8.4  P4 lane
# --------------------------------------------------------------------------- #

def case_p4_lane():
    sc = lane_scenario("strict")
    code, out, parsed = stop(sc.cw, session_id="s1")
    reason = reason_of(parsed)
    check_true("P8.4: strict + vacuous checkpoint -> decision block", blocks(parsed))
    check_true("P8.4: the reason names the entry, CHECKPOINT REQUIRED and the label",
               sc.eid in reason and "CHECKPOINT REQUIRED" in reason
               and "Next safe action" in reason)
    sc.ckpt(GOOD_CKPT)
    code, out, parsed = stop(sc.cw, session_id="s2")
    check_same("P8.4: a good fresh checkpoint -> no output", out.strip(), "")
    sc.ckpt(VACUOUS_CKPT)
    sc.set_level("warn")
    code, out, parsed = stop(sc.cw, session_id="s3")
    check_true("P8.4: warn -> additionalContext, not block",
               not blocks(parsed) and sc.eid in str(context(parsed)))
    sc.set_level("off")
    code, out, parsed = stop(sc.cw, session_id="s4")
    check_same("P8.4: off -> no output", out.strip(), "")


# --------------------------------------------------------------------------- #
# P8.5  P4 loop guard
# --------------------------------------------------------------------------- #

def case_p4_loop_guard():
    sc = lane_scenario("strict")
    code, out, parsed = stop(sc.cw, session_id="g1", stop_hook_active=True)
    check_true("P8.5: stop_hook_active -> not block, still reports",
               not blocks(parsed) and context(parsed))
    code, out, parsed = stop(sc.cw, session_id="g2")
    check_true("P8.5 setup: first stop for a session blocks", blocks(parsed))
    code, out, parsed = stop(sc.cw, session_id="g2")
    check_true("P8.5: the same session and fingerprint a second time -> not block",
               not blocks(parsed))
    os.remove(os.path.join(sc.cw, "progress.md"))      # a different obligation code
    code, out, parsed = stop(sc.cw, session_id="g2")
    check_true("P8.5: a changed fingerprint blocks again", blocks(parsed))
    sc.ckpt(VACUOUS_CKPT)
    code, out, parsed = stop(sc.cw)
    check_true("P8.5: no session_id -> never block, only report",
               not blocks(parsed) and context(parsed))


# --------------------------------------------------------------------------- #
# P8.6  P4 orchestrator
# --------------------------------------------------------------------------- #

def case_p4_orchestrator():
    sc = lane_scenario("strict", ckpt=GOOD_CKPT)
    sc.write_exception()
    code, out, parsed = stop(sc.p, session_id="o1")
    check_true("P8.6: an exception outstanding -> block for the orchestrator",
               blocks(parsed) and sc.eid in reason_of(parsed)
               and "UNAPPLIED CONSUMPTION" in reason_of(parsed))
    sc = lane_scenario("strict")
    code, out, parsed = stop(sc.p, session_id="o2")
    check_true("P8.6: a lane checkpoint problem alone never blocks the orchestrator",
               not blocks(parsed))
    bare = make_repo()
    code, out, parsed = stop(bare, session_id="o3")
    check_true("P8.6: a cwd in a repo with no program -> no output",
               code == 0 and out.strip() == "")
    plain = tempfile.mkdtemp(prefix="orch-adh-nongit-")
    code, out, parsed = stop(plain, session_id="o4")
    check_true("P8.6: a non-git cwd -> no output", code == 0 and out.strip() == "")


def case_p4_several_programs():
    # Enforcement must not switch off silently when a repo holds two programs.
    sc = lane_scenario("strict", ckpt=GOOD_CKPT)
    sc.write_exception()
    first_dir = sc.program_dir()
    wt = linked_worktree(sc.p, "other-lane")
    code, out, err = run(sc.p, "open", "--program", "other", "--agent-id", "agent-other",
                         "--brief", write_brief(sc.p, wt, "other.md", "none"))
    check_same("P8.6: a second program opens alongside the first", code, 0)
    check_true("P8.6: the repo now holds two programs (test sanity)",
               len(orch.list_programs(sc.key)) == 2)
    code, out, parsed = stop(sc.p, session_id="multi1")
    check_true("P8.6: two programs -> the enforcing one still blocks the orchestrator",
               blocks(parsed) and "UNAPPLIED CONSUMPTION" in reason_of(parsed))
    code, out, parsed = stop(sc.p, session_id="multi1")
    check_true("P8.6: two programs -> the loop guard still holds on a repeat",
               not blocks(parsed) and "UNAPPLIED CONSUMPTION" in (context(parsed) or ""))
    os.remove(os.path.join(first_dir, "policy.json"))
    code, out, parsed = stop(sc.p, session_id="multi2")
    check_true("P8.6: two programs, neither enforcing -> no output", out.strip() == "")


# --------------------------------------------------------------------------- #
# P8.7  stop-check never calls track
# --------------------------------------------------------------------------- #

def case_p4_no_track_calls():
    sc = lane_scenario("strict", advances=ADV)
    calls = sc.fixture + ".calls"
    os.environ["FAKE_TRACK_CALLS"] = calls
    run(sc.p, "audit")
    positive = os.path.exists(calls) and open(calls).read().strip() != ""
    check_true("P8.7 control: the fake track logs the calls `audit` makes", positive)
    if os.path.exists(calls):
        os.remove(calls)
    sc.write_exception()
    stop(sc.cw, session_id="t1")
    stop(sc.p, session_id="t2")
    stop(sc.cw, session_id="t3", stop_hook_active=True)
    made = open(calls).read().strip() if os.path.exists(calls) else ""
    check_same("P8.7: stop-check made no `track` call (lane or orchestrator)", made, "")


# --------------------------------------------------------------------------- #
# P8.8  P5 audit summary line
# --------------------------------------------------------------------------- #

def audit_lines(text):
    return [ln for ln in text.splitlines() if ln.startswith("audit:")]


def case_p5_summary():
    sc = lane_scenario("off")
    for cmd in ("resume", "roster"):
        code, out, err = run(sc.p, cmd)
        lines = audit_lines(out)
        check_true("P8.8: %s prints one `audit:` line for a finding" % cmd,
                   len(lines) == 1 and "checkpoint-incomplete" in lines[0]
                   and "orch audit" in lines[0])
    sc.ckpt(GOOD_CKPT)
    for cmd in ("resume", "roster"):
        code, out, err = run(sc.p, cmd)
        check_same("P8.8: %s prints no `audit:` line when clean" % cmd, audit_lines(out), [])


# --------------------------------------------------------------------------- #
# P8.9  P6 overrides in audit
# --------------------------------------------------------------------------- #

def case_p6_overrides():
    sc = Scenario(advances=ADV)
    run(sc.p, "close", sc.eid, "--consumed", "it landed", "--untracked", "manual fix landed")
    code, out, err = run(sc.p, "audit")
    check_same("P8.9: audit exits 0 on a program whose only content is overrides", code, 0)
    check_true("P8.9: audit lists the recent override under an `overrides` heading",
               "overrides" in out.lower() and "manual fix landed" in out)
    check_same("P8.9: an override never adds the P5 audit line",
               audit_lines(run(sc.p, "roster")[1]), [])


# --------------------------------------------------------------------------- #
# hook cost: the bytecode-cached launcher and the `enforcing` flag prefilter
# --------------------------------------------------------------------------- #

SKILL_DIR = os.path.dirname(HERE)


def hook_commands():
    """Every `command:` in SKILL.md's frontmatter, unquoted, keyed by its subcommand text."""
    with open(os.path.join(SKILL_DIR, "SKILL.md"), "r", encoding="utf-8") as fh:
        front = fh.read().split("\n---", 1)[0]
    cmds = []
    for line in front.splitlines():
        line = line.strip()
        if line.startswith("command: '") and line.endswith("'"):
            cmds.append(line[len("command: '"):-1].replace("''", "'"))
    return cmds


def case_hooks_use_launcher():
    cmds = hook_commands()
    check_true("hook: the frontmatter holds hook commands (test sanity)", len(cmds) >= 9)
    check_same("hook: every frontmatter hook names orch_hook.py, none orch.py",
               [c for c in cmds if "orch_hook.py" not in c or "/orch.py" in c], [])


for fn in (case_p1_policy, case_p2_close, case_p3_open, case_p4_lane, case_p4_loop_guard,
           case_p4_orchestrator, case_p4_several_programs, case_p4_no_track_calls, case_p5_summary, case_p6_overrides,
           case_hooks_use_launcher):
    case(fn)

print("\n%s" % ("all adherence cases pass" if not FAILURES
                else "FAILED: %d -- %s" % (len(FAILURES), "; ".join(FAILURES))))
sys.exit(1 if FAILURES else 0)
