#!/usr/bin/env python3
"""Pin the working-a-lane addendum (spec orch-working-a-lane, section W7).

Run: python3 test_orch_lane.py

Expected to be red until the core and skill lanes land; every failing check
names its W7 item. A fake `track` (testdata/fake-track) logs every call so the suite can
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
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp(prefix="orch-lane-state-")
for _k in ("ORCH_HOME", "ORCH_CHECKPOINT_STALE_MIN"):
    os.environ.pop(_k, None)
_spec = importlib.util.spec_from_file_location("orch", os.path.join(HERE, "orch.py"))
orch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(orch)

BASE_PATH = os.environ.get("PATH", "")
BIN = tempfile.mkdtemp(prefix="orch-lane-bin-")
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
    root = os.path.realpath(tempfile.mkdtemp(prefix="orch-lane-"))
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
        self.fixture = os.path.join(tempfile.mkdtemp(prefix="orch-lane-fx-"), "fx.json")
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
# SubagentStop fixtures (payload shape from the spec's "Probed facts")
# --------------------------------------------------------------------------- #

TRANSCRIPT_DIR = tempfile.mkdtemp(prefix="orch-lane-tr-")
_SEQ = [0]
CAP_BYTES = 8 * 1024 * 1024


def transcript(label="orch_entry: {eid}", skill=True, pad=0):
    """Write a fake subagent transcript JSONL; return its path."""
    _SEQ[0] += 1
    path = os.path.join(TRANSCRIPT_DIR, "agent-%d.jsonl" % _SEQ[0])
    lines = [json.dumps({"type": "user", "message": {
        "role": "user", "content": "%s\nImplement the retry policy." % label}})]
    if skill:
        lines.append(json.dumps({"type": "assistant", "message": {
            "role": "assistant", "content": [
                {"type": "text", "text": "loading"},
                {"type": "tool_use", "id": "tu1", "name": "Skill",
                 "input": {"skill": "working-a-lane"}}]}}))
    lines.append(json.dumps({"type": "assistant", "message": {
        "role": "assistant", "content": [{"type": "text", "text": "working"}]}}))
    filler = json.dumps({"type": "assistant", "message": {
        "role": "assistant", "content": [{"type": "text", "text": "x" * 4000}]}})
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
        written = 0
        while written < pad:
            fh.write(filler + "\n")
            written += len(filler) + 1
    return path


def sub_stop(sc, path, agent_id="ag1", **extra):
    payload = {"hook_event_name": "SubagentStop", "session_id": "parent-session",
               "agent_id": agent_id, "agent_type": "general-purpose",
               "agent_transcript_path": path, "stop_hook_active": False}
    payload.update(extra)
    payload = {k: v for k, v in payload.items() if v is not None}
    return stop(sc.p, **payload)


def lbl(sc):
    return "orch_entry: %s" % sc.eid


# --------------------------------------------------------------------------- #
# W7.1
# --------------------------------------------------------------------------- #

def case_w71_checkpoint():
    sc = lane_scenario("strict")
    code, out, parsed = sub_stop(sc, transcript(lbl(sc)), agent_id="w71a")
    check_true("W7.1: strict + vacuous checkpoint + Skill call -> block", blocks(parsed))
    check_true("W7.1: the reason names the entry and the checkpoint label",
               sc.eid in reason_of(parsed) and "Next safe action" in reason_of(parsed))
    sc.ckpt(GOOD_CKPT)
    code, out, parsed = sub_stop(sc, transcript(lbl(sc)), agent_id="w71b")
    check_same("W7.1: a good checkpoint -> no output", out.strip(), "")


# --------------------------------------------------------------------------- #
# W7.2
# --------------------------------------------------------------------------- #

def case_w72_skill_not_loaded():
    sc = lane_scenario("strict", ckpt=GOOD_CKPT)
    code, out, parsed = sub_stop(sc, transcript(lbl(sc), skill=False), agent_id="w72a")
    check_true("W7.2: no Skill call for working-a-lane -> block (lane-skill-not-loaded)",
               blocks(parsed) and "working-a-lane" in reason_of(parsed))
    code, out, parsed = sub_stop(sc, transcript(lbl(sc), skill=True), agent_id="w72b")
    check_same("W7.2: the Skill call present + good checkpoint -> no output", out.strip(), "")
    big = transcript(lbl(sc), skill=False, pad=CAP_BYTES + 100000)
    check_true("W7.2 setup: the padded transcript is over 8 MB", os.path.getsize(big) > CAP_BYTES)
    code, out, parsed = sub_stop(sc, big, agent_id="w72c")
    check_same("W7.2: the 8 MB cap skips the skill check -> no output", out.strip(), "")


# --------------------------------------------------------------------------- #
# W7.3
# --------------------------------------------------------------------------- #

def case_w73_silent():
    sc = lane_scenario("strict")     # vacuous checkpoint: a matched lane WOULD block
    for name, path in (("missing path", None),
                       ("nonexistent path", os.path.join(TRANSCRIPT_DIR, "nope.jsonl")),
                       ("no label", transcript("just a task")),
                       ("orch_entry: none", transcript("orch_entry: none")),
                       ("unknown entry", transcript("orch_entry: e999"))):
        code, out, parsed = sub_stop(sc, path, agent_id="w73-" + name.replace(" ", "-"))
        check_same("W7.3: %s -> no output" % name, out.strip(), "")


# --------------------------------------------------------------------------- #
# W7.4
# --------------------------------------------------------------------------- #

def case_w74_no_orchestrator_obligations():
    sc = lane_scenario("strict", ckpt=GOOD_CKPT)
    sc.write_exception()
    code, out, parsed = sub_stop(sc, transcript(lbl(sc)), agent_id="w74a")
    check_same("W7.4: only an orchestrator exception outstanding -> no output", out.strip(), "")
    sc.ckpt(VACUOUS_CKPT)
    code, out, parsed = sub_stop(sc, transcript(lbl(sc)), agent_id="w74b")
    text = reason_of(parsed) + str(context(parsed))
    check_true("W7.4: with a lane problem it blocks, but the reason never carries the exception",
               blocks(parsed) and "UNAPPLIED CONSUMPTION" not in text)


# --------------------------------------------------------------------------- #
# W7.5
# --------------------------------------------------------------------------- #

def case_w75_loop_guard():
    sc = lane_scenario("strict")
    path = transcript(lbl(sc))
    code, out, parsed = sub_stop(sc, path, agent_id="w75a", stop_hook_active=True)
    check_true("W7.5: stop_hook_active -> no block", not blocks(parsed))
    code, out, parsed = sub_stop(sc, path, agent_id="w75b")
    check_true("W7.5 setup: first stop for an agent_id blocks", blocks(parsed))
    code, out, parsed = sub_stop(sc, path, agent_id="w75b")
    check_true("W7.5: same agent_id + fingerprint twice -> second is context, not block",
               not blocks(parsed) and context(parsed))
    code, out, parsed = sub_stop(sc, path, agent_id="w75c")
    check_true("W7.5: a different agent_id with the same problem blocks", blocks(parsed))


# --------------------------------------------------------------------------- #
# W7.6
# --------------------------------------------------------------------------- #

def case_w76_both_roles():
    sc = lane_scenario("strict")
    code, out, err = run(sc.p, "mint-child", sc.eid)
    child = out.strip().splitlines()[0] if out.strip() else "root.1"
    path = os.path.join(sc.program_dir(), "exceptions", "%s.%s.json" % (child, sc.eid))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "tracker": child, "entry": sc.eid, "title": "x",
                   "attempts": 1, "targets": [{"track": "T-015", "state": "failed",
                                               "code": "WRITE_CONFLICT", "repair": "r"}]}, fh)
    code, out, parsed = stop(sc.cw, session_id="w76a")
    check_true("W7.6: a lane session with a child_tracker exception -> blocked, both kinds",
               blocks(parsed) and "CHECKPOINT REQUIRED" in reason_of(parsed)
               and "UNAPPLIED CONSUMPTION" in reason_of(parsed))
    sc.ckpt(GOOD_CKPT)
    code, out, parsed = stop(sc.p, session_id="w76b")
    check_true("W7.6: the root session is not blocked by an exception in a child tracker",
               not blocks(parsed))


# --------------------------------------------------------------------------- #
# W7.7
# --------------------------------------------------------------------------- #

LOAD_LINE = "Before anything else, load the working-a-lane skill with the Skill tool."


def spawn_guard(repo, tool, tool_input):
    # Fed on stdin like a real hook: run() resets the payload cache before each call.
    payload = {"tool_name": tool, "tool_input": tool_input, "cwd": repo}
    code, out, err = run(repo, "spawn-guard", stdin=json.dumps(payload))
    fresh()
    if not out.strip():
        return None
    return json.loads(out)["hookSpecificOutput"]


def case_w77_spawn_guard():
    sc = Scenario()

    # orch_override waives the model-rung check so only the load-line rule is under test
    def agent_in(line):
        body = "orch_entry: %s\norch_override: testing the load line\nDo the work." % sc.eid
        return {"description": "lane", "prompt": body + ("\n" + LOAD_LINE if line else "")}

    def paseo_in(line):
        prompt = "Do the work." + ("\n" + LOAD_LINE if line else "")
        return {"title": "w", "initialPrompt": prompt, "provider": "claude/claude-sonnet-5",
                "labels": {"orch_entry": sc.eid, "orch_override": "testing the load line"},
                "settings": {"modeId": sc.entry().get("mode")}}

    for tool, builder in (("Agent", agent_in), ("mcp__paseo__create_agent", paseo_in)):
        tag = "W7.7 [%s]:" % tool.split("__")[-1]
        sc.set_level("strict")
        got = spawn_guard(sc.p, tool, builder(False))
        reason = (got or {}).get("permissionDecisionReason", "")
        check_true("%s strict + labelled spawn without the line -> deny naming the line" % tag,
                   got and got.get("permissionDecision") == "deny"
                   and "working-a-lane" in reason)
        check_same("%s strict + the line present -> allow" % tag,
                   spawn_guard(sc.p, tool, builder(True)), None)
        sc.set_level("warn")
        got = spawn_guard(sc.p, tool, builder(False))
        check_true("%s warn + no line -> allow with the line as context" % tag,
                   got and got.get("permissionDecision") != "deny"
                   and "working-a-lane" in str(got.get("additionalContext")))
        sc.set_level("off")
        check_same("%s off + no line -> unchanged (allow)" % tag,
                   spawn_guard(sc.p, tool, builder(False)), None)

    sc.set_level("strict")
    none_in = {"description": "x", "prompt": "orch_entry: none\nDo the work."}
    check_same("W7.7: strict + `orch_entry: none` -> unchanged (allow)",
               spawn_guard(sc.p, "Agent", none_in), None)


# --------------------------------------------------------------------------- #
# W7.8
# --------------------------------------------------------------------------- #

SKILL_DIR = os.path.dirname(HERE)
PLUGIN = os.path.dirname(os.path.dirname(SKILL_DIR))


def frontmatter(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read().split("\n---", 1)[0]


def commands(path, needle):
    found = set()
    for line in frontmatter(path).splitlines():
        line = line.strip()
        if line.startswith("command: '") and line.endswith("'") and needle in line:
            found.add(line)
    return found


def case_w78_skill_wiring():
    orch_md = os.path.join(SKILL_DIR, "SKILL.md")
    lane_md = os.path.join(os.path.dirname(SKILL_DIR), "working-a-lane", "SKILL.md")
    for needle in ("stop-check", "inbox drain"):
        a, b = commands(orch_md, needle), commands(lane_md, needle)
        check_true("W7.8: both skills carry a `%s` hook command" % needle, a and b)
        check_true("W7.8: `%s` command is byte-identical across the two skills" % needle,
                   len(a) == 1 and a == b)
    with open(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"), "r", encoding="utf-8") as fh:
        skills = json.load(fh).get("skills", [])
    check_true("W7.8: plugin.json ships ./skills/working-a-lane",
               "./skills/working-a-lane" in skills)
    check_true("W7.8: working-a-lane is model-invocable (no disable-model-invocation)",
               os.path.exists(lane_md) and "disable-model-invocation" not in frontmatter(lane_md))


# --------------------------------------------------------------------------- #
# W7.9
# --------------------------------------------------------------------------- #

def case_w79_vocabulary():
    text = " ".join(orch.cost_advisories({}, {}, max(orch.FANOUT_WARN, 8)))
    check_true("W7.9: the fan-out advisory says \"open lanes\"",
               "open lanes" in text and "open dispatches" not in text)


for fn in (case_w71_checkpoint, case_w72_skill_not_loaded, case_w73_silent,
           case_w74_no_orchestrator_obligations, case_w75_loop_guard, case_w76_both_roles,
           case_w77_spawn_guard, case_w78_skill_wiring, case_w79_vocabulary):
    case(fn)

print("\n%s" % ("all lane cases pass" if not FAILURES
                else "FAILED: %d -- %s" % (len(FAILURES), "; ".join(FAILURES))))
sys.exit(1 if FAILURES else 0)
