#!/usr/bin/env python3
"""Pin structured `advances`, `orch consume`, exceptions and `orch audit`
(rationale: docs/DESIGN.md §9h).

Run: python3 test_orch_consume.py

A fake `track` (testdata/fake-track) reads and writes a JSON fixture and logs
every advance it receives, so the suite is hermetic and can assert "no write".
Expected to be red until the core lane lands; each failing check names the
section and the behaviour it wants. Standard library only.
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
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp(prefix="orch-consume-state-")
for _k in ("ORCH_HOME", "ORCH_CHECKPOINT_STALE_MIN"):
    os.environ.pop(_k, None)
_spec = importlib.util.spec_from_file_location("orch", os.path.join(HERE, "orch.py"))
orch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(orch)

REAL_TRACK = shutil.which("track")
BASE_PATH = os.environ.get("PATH", "")
BIN = tempfile.mkdtemp(prefix="orch-consume-bin-")
shutil.copy(os.path.join(HERE, "testdata", "fake-track"), os.path.join(BIN, "track"))
os.chmod(os.path.join(BIN, "track"), 0o755)
NO_TRACK_PATH = "/usr/bin:/bin"

FAILURES = []


def check_same(name, got, want):
    ok = got == want
    if not ok:
        FAILURES.append(name)
    print("  %-72s %s" % (name, "ok" if ok else "FAIL"))
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
        print("  %-72s FAIL (crashed)" % fn.__name__)
        print("    " + traceback.format_exc().strip().replace("\n", "\n    "))
    finally:
        os.environ["PATH"] = BIN + os.pathsep + BASE_PATH


def fresh():
    cache = getattr(orch, "_repo_identity", None)
    if hasattr(cache, "cache_clear"):
        cache.cache_clear()


def run(repo, command, *rest):
    out, err = io.StringIO(), io.StringIO()
    stdin = sys.stdin
    sys.stdin = io.StringIO("")
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = orch.main(["--repo", repo, command] + list(rest))
            except SystemExit as exc:  # argparse: unknown command or flag
                code = exc.code if isinstance(exc.code, int) else 2
    finally:
        sys.stdin = stdin
    return code, out.getvalue(), err.getvalue()


def sh(*cmd):
    return subprocess.run(list(cmd), check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, universal_newlines=True).stdout.strip()


def make_repo():
    root = os.path.realpath(tempfile.mkdtemp(prefix="orch-consume-"))
    sh("git", "init", "-q", root)
    sh("git", "-C", root, "-c", "user.name=t", "-c", "user.email=t@t",
       "commit", "-q", "--allow-empty", "-m", "init")
    return root


def linked_worktree(repo, name):
    path = os.path.join(os.path.dirname(repo), "%s-%s" % (os.path.basename(repo), name))
    sh("git", "-C", repo, "worktree", "add", "-q", "-b", name, path)
    return os.path.realpath(path)


def marker(worktree):
    with open(os.path.join(worktree, ".git"), "r", encoding="utf-8") as fh:
        line = fh.read().strip()
    gd = os.path.realpath(os.path.join(worktree, line[len("gitdir:"):].strip()))
    return os.path.join(gd, "orch-home.json")


TASKS = [{"label": "Implement retry policy", "checked": False},
         {"label": "Verify production behavior", "checked": False}]
ADV = "\n  - track: T-015\n    expect: Implement retry policy"


def write_brief(where, worktree, name="brief.md", advances=ADV, **extra):
    lines = ["title: consume lane", "worktree: %s" % worktree,
             "expected_artifacts:", "  - out.txt", "advances: %s" % advances,
             "consumption: this test reads it", "archetype: implementer"]
    lines += ["%s: %s" % kv for kv in extra.items()]
    path = os.path.join(where, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("---\n%s\n---\n\n# body\n" % "\n".join(lines))
    return path


def set_fixture(path, tasks=TASKS, item="T-015"):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"items": {item: {"title": "retry work",
                                    "tasks": [dict(t) for t in tasks],
                                    "blockedBy": ["T-019"]}}}, fh)


def read_fixture(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class Scenario(object):
    """P (planning repo), C (code repo) with a linked worktree, a fixture, a lane."""

    def __init__(self, tasks=TASKS, cross=True, open_lane=True, advances=ADV, **brief):
        self.p, self.c = make_repo(), make_repo()
        self.cw = linked_worktree(self.c if cross else self.p, "lane")
        self.fixture = os.path.join(tempfile.mkdtemp(prefix="orch-consume-fx-"), "fx.json")
        self.log = self.fixture + ".log"
        set_fixture(self.fixture, tasks)
        os.environ["FAKE_TRACK_FIXTURE"] = self.fixture
        os.environ["FAKE_TRACK_LOG"] = self.log
        os.environ["PATH"] = BIN + os.pathsep + BASE_PATH
        self.opened = None
        if open_lane:
            self.opened = self.open(advances, **brief)
        self.sha = sh("git", "-C", self.cw, "rev-parse", "HEAD")

    def open(self, advances=ADV, name="brief.md", *extra, **brief):
        res = run(self.p, "open", "--agent-id", "agent-%s" % name,
                  "--brief", write_brief(self.p, self.cw, name, advances, **brief), *extra)
        fresh()
        return res

    @property
    def key(self):
        return orch.repo_identity(self.p)[0]

    def tracker(self):
        program = orch.resolve_program(self.key, None)
        return orch.tracker_path(self.key, program, "root")

    def data(self):
        return orch.load_tracker(self.tracker())

    def entry(self):
        if not os.path.exists(self.tracker()):  # every open refused: none minted
            return None
        entries = self.data()["entries"]
        return entries[0] if entries else None

    def eid(self):
        return self.entry()["entry"]

    def ev(self):
        return "commit:%s@%s" % (self.cw, self.sha)

    def consume(self, *rest):
        res = run(self.p, "consume", self.eid_cached, *rest)
        fresh()
        return res

    def exception_path(self, eid):
        program = orch.resolve_program(self.key, None)
        return os.path.join(orch.program_dir(self.key, program), "exceptions",
                            "root.%s.json" % eid)

    def writes(self):
        try:
            with open(self.log, "r", encoding="utf-8") as fh:
                return [ln for ln in fh.read().splitlines() if ln.strip()]
        except OSError:
            return []

    def start(self):
        self.eid_cached = self.eid()
        return self


def consumed(sc, *rest):
    return sc.consume("--consumed", "retry policy landed and verified", *rest)


# --------------------------------------------------------------------------- #
# C. Structured advances: open validates each track target.
# --------------------------------------------------------------------------- #

def case_c_open_accepts_valid_mapping():
    sc = Scenario()
    check_same("C: `open` accepts a mapping advance whose task exists", sc.opened[0], 0)
    check_true("C: the entry records the mapping (track T-015)",
               sc.entry() and "T-015" in json.dumps(sc.entry().get("advances")))


def case_c_refusals():
    sc = Scenario(open_lane=False)
    code, out, err = sc.open(ADV.replace("T-015", "T-404"), "m1.md")
    check_true("C: `open` refuses a track item that does not exist", code != 0 and "T-404" in err)
    code, out, err = sc.open(ADV.replace("Implement retry policy", "No such task"), "m2.md")
    check_true("C: `open` refuses an `expect` label no task has", code != 0 and "No such task" in err)
    done = [dict(TASKS[0], checked=True), dict(TASKS[1])]
    set_fixture(sc.fixture, done)
    code, out, err = sc.open(ADV, "m3.md")
    check_true("C: `open` refuses an `expect` task that is already done", code != 0 and "done" in err)
    set_fixture(sc.fixture)
    code, out, err = sc.open(ADV + "\n    bogus: 1", "m4.md")
    check_true("C: `open` refuses an unknown mapping key", code != 0 and "bogus" in err)
    code, out, err = sc.open("\n  - track: T-015", "m5.md")
    check_true("C: `open` refuses a mapping with no `expect`", code != 0 and "expect" in err)
    os.environ["PATH"] = NO_TRACK_PATH
    code, out, err = sc.open(ADV, "m6.md")
    check_true("C: `open` refuses a track target when `track` is not on PATH",
               code != 0 and "track" in err)
    check_same("C: no entry was recorded by any refused open", sc.entry(), None)


def case_c_target_not_yet_current_allowed():
    tasks = [{"label": "Approve design", "checked": False}, dict(TASKS[0])]
    sc = Scenario(tasks=tasks)
    check_same("C: a target whose task is not yet current is allowed at `open`", sc.opened[0], 0)


def case_c_real_track():
    if not REAL_TRACK:
        print("  %-72s skip (track not installed)" % "C: real track refuses a missing item")
        return
    os.environ["PATH"] = os.path.dirname(REAL_TRACK) + os.pathsep + BASE_PATH
    p, c = make_repo(), make_repo()
    cw = linked_worktree(c, "real")
    code, out, err = run(p, "open", "--agent-id", "a-real", "--brief",
                         write_brief(p, cw, "real.md", ADV.replace("T-015", "T-9999")))
    check_true("C: with the real `track`, an item that does not exist refuses `open`",
               code != 0 and "T-9999" in err)


# --------------------------------------------------------------------------- #
# D. consume.
# --------------------------------------------------------------------------- #

def case_d_happy_path():
    sc = Scenario().start()
    eid = sc.eid_cached
    check_true("D setup: lane is running with a marker", os.path.exists(marker(sc.cw)))
    code, out, err = consumed(sc, "--evidence", sc.ev(), "--evidence", "file:" + sc.fixture,
                              "--no-notify")
    check_same("D1: verified evidence -> exit 0", code, 0)
    check_true("D1: the entry is gone (closed through the shared path)", sc.entry() is None)
    check_true("D1: the marker is gone", not os.path.exists(marker(sc.cw)))
    fx = read_fixture(sc.fixture)["items"]["T-015"]["tasks"]
    check_true("D1: the track task was advanced", fx[0]["checked"] and not fx[1]["checked"])
    check_true("D1: output is one delta line naming T-015 and the next task",
               "T-015" in out and "Verify production behavior" in out)
    check_true("D1: no exception file remains", not os.path.exists(sc.exception_path(eid)))
    check_true("D1: --no-notify means the write carried no --notify",
               all("notify=False" in w for w in sc.writes()) and len(sc.writes()) == 1)


def case_d_notify_default_on():
    sc = Scenario().start()
    consumed(sc, "--evidence", sc.ev())
    check_true("D: --notify is on by default for the track write",
               any("notify=True" in w for w in sc.writes()))


def case_d_evidence_on_ref():
    sc = Scenario().start()
    code, out, err = consumed(sc, "--evidence", sc.ev() + ",on=HEAD")
    check_same("D: `commit:...,on=HEAD` verifies and consume succeeds", code, 0)
    sc = Scenario().start()
    sc.data()
    other = sh("git", "-C", sc.cw, "-c", "user.name=t", "-c", "user.email=t@t",
               "commit-tree", "HEAD^{tree}", "-m", "orphan")
    code, out, err = consumed(sc, "--evidence", "commit:%s@%s,on=HEAD" % (sc.cw, other))
    check_true("D: `,on=<ref>` fails when the commit is not an ancestor of the ref",
               code == 1 and sc.entry() is not None)


def case_d_bad_evidence():
    sc = Scenario().start()
    before = open(sc.tracker(), "rb").read()
    bogus = "commit:%s@%s" % (sc.cw, "0" * 40)
    code, out, err = consumed(sc, "--evidence", sc.ev(), "--evidence", bogus)
    check_same("D2: one bad evidence item -> exit 1", code, 1)
    check_true("D2: the failing item is named", ("0" * 40) in out + err)
    check_true("D2: the tracker file is byte-identical", open(sc.tracker(), "rb").read() == before)
    check_same("D2: the fake track saw no write", sc.writes(), [])
    code, out, err = consumed(sc, "--evidence", "commit:relative/path@abc")
    check_same("D2: a relative repo path in evidence is an error (exit 1)", code, 1)
    code, out, err = consumed(sc, "--evidence", "file:" + os.path.join(sc.cw, "missing.txt"))
    check_same("D2: a missing evidence file is an error (exit 1)", code, 1)
    code, out, err = sc.consume("--consumed", "retry policy landed")
    check_true("D2: no evidence on a fresh entry is refused", code != 0)
    code, out, err = sc.consume("--consumed", "tbd", "--evidence", sc.ev())
    check_true("D2: a placeholder --consumed is refused", code != 0)
    check_true("D2: refusals left the tracker byte-identical",
               open(sc.tracker(), "rb").read() == before)


def case_d_pending_refused():
    sc = Scenario(open_lane=False)
    run(sc.p, "open", "--brief", write_brief(sc.p, sc.cw, "pend.md"))
    fresh()
    sc.start()
    check_same("D setup: entry is pending", sc.entry()["status"], "pending")
    code, out, err = consumed(sc, "--evidence", sc.ev())
    check_true("D1: a pending entry is refused", code != 0 and sc.entry() is not None)


def case_d_write_conflict_and_retry():
    tasks = [{"label": "Approve design", "checked": False}, dict(TASKS[0]), dict(TASKS[1])]
    sc = Scenario(tasks=tasks).start()
    eid = sc.eid_cached
    code, out, err = consumed(sc, "--evidence", sc.ev())
    check_same("D3: a different current task -> exit 3", code, 3)
    ent = sc.entry()
    check_true("D3: the entry is left harvested with the decision recorded",
               ent and ent["status"] == "harvested" and ent.get("consumed_text")
               and ent.get("evidence") and ent.get("consumed_at"))
    try:
        with open(sc.exception_path(eid), "r", encoding="utf-8") as fh:
            exc = json.load(fh)
    except (OSError, ValueError):
        exc = {}
    tg = (exc.get("targets") or [{}])[0]
    check_same("E: exception file records tracker, entry, state, code",
               (exc.get("tracker"), exc.get("entry"), tg.get("state"), tg.get("code")),
               ("root", eid, "failed", "NOT_CURRENT"))
    check_true("E: exception target has a repair line and an attempts count",
               tg.get("repair") and exc.get("attempts") == 1)
    check_true("D3: repair lines are printed", "orch consume" in out + err)
    check_true("D3: the marker survives a failed consume (entry not closed)",
               os.path.exists(marker(sc.cw)))
    code, out, err = run(sc.p, "roster")
    check_true("E: roster marks the entry `harvested !track`", "!track" in out)
    code, out, err = run(sc.p, "resume")
    check_true("E: resume prints an UNAPPLIED CONSUMPTION block",
               "UNAPPLIED CONSUMPTION" in out and eid in out)
    # Fix the fixture (the gate task is done), retry with no flags.
    fx = read_fixture(sc.fixture)
    fx["items"]["T-015"]["tasks"][0]["checked"] = True
    with open(sc.fixture, "w", encoding="utf-8") as fh:
        json.dump(fx, fh)
    code, out, err = sc.consume()
    check_same("D3: retry with no flags -> exit 0", code, 0)
    check_true("D3: retry removes the exception file", not os.path.exists(sc.exception_path(eid)))
    check_true("D3: retry closes the entry and removes the marker",
               sc.entry() is None and not os.path.exists(marker(sc.cw)))


def case_d_track_write_conflict_race():
    sc = Scenario().start()
    eid = sc.eid_cached
    os.environ["FAKE_TRACK_ADVANCE_ERROR"] = "WRITE_CONFLICT"
    try:
        code, out, err = consumed(sc, "--evidence", sc.ev())
    finally:
        del os.environ["FAKE_TRACK_ADVANCE_ERROR"]
    check_same("D3: track's own WRITE_CONFLICT on advance -> exit 3", code, 3)
    try:
        with open(sc.exception_path(eid), "r", encoding="utf-8") as fh:
            tg = (json.load(fh).get("targets") or [{}])[0]
    except (OSError, ValueError):
        tg = {}
    check_same("E: the exception carries track's code verbatim", tg.get("code"), "WRITE_CONFLICT")


def case_d_retry_counts_attempts():
    tasks = [{"label": "Approve design", "checked": False}, dict(TASKS[0])]
    sc = Scenario(tasks=tasks).start()
    consumed(sc, "--evidence", sc.ev())
    code, out, err = sc.consume()
    check_same("D: a second failing retry still exits 3", code, 3)
    try:
        with open(sc.exception_path(sc.eid_cached), "r", encoding="utf-8") as fh:
            attempts = json.load(fh).get("attempts")
    except (OSError, ValueError):
        attempts = None
    check_same("E: the exception file is overwritten with attempts == 2", attempts, 2)


def case_d_idempotent_already():
    sc = Scenario().start()
    fx = read_fixture(sc.fixture)
    fx["items"]["T-015"]["tasks"][0]["checked"] = True  # someone advanced it already
    with open(sc.fixture, "w", encoding="utf-8") as fh:
        json.dump(fx, fh)
    code, out, err = consumed(sc, "--evidence", sc.ev())
    check_same("D7: expected task already done -> exit 0", code, 0)
    check_true("D7: the target is reported `already`", "already" in out)
    check_same("D7: the fake track saw no write", sc.writes(), [])
    check_true("D7: the entry is closed", sc.entry() is None)


def case_d_skip_target():
    tasks = [{"label": "Approve design", "checked": False}, dict(TASKS[0])]
    sc = Scenario(tasks=tasks).start()
    code, out, err = consumed(sc, "--evidence", sc.ev())
    check_same("D8 setup: the target fails first (exit 3)", code, 3)
    code, out, err = sc.consume("--skip-target", "T-015")
    check_true("D8: --skip-target without --reason is refused", code != 0 and sc.entry() is not None)
    code, out, err = sc.consume("--skip-target", "T-015", "--reason", "advanced by hand in P")
    check_same("D8: --skip-target with --reason resolves the failed target (exit 0)", code, 0)
    check_true("D8: the entry is closed and the exception file is gone",
               sc.entry() is None and not os.path.exists(sc.exception_path(sc.eid_cached)))
    check_same("D8: the skipped target caused no track write", sc.writes(), [])


def case_d_legacy_plan_target():
    sc = Scenario(advances="\n  - 3.4").start()
    code, out, err = consumed(sc, "--evidence", sc.ev())
    check_true("D: a legacy plan-id target prints `update by hand` and still closes",
               code == 0 and "update by hand" in out + err and sc.entry() is None)


# --------------------------------------------------------------------------- #
# F. audit: one corrupted fixture per finding code.
# --------------------------------------------------------------------------- #

GOOD_CKPT = ("Last durable milestone: committed the retry module\n"
             "Verification: unit tests pass\n"
             "Uncertain external effects: none\n"
             "Next safe action: open the pull request\n")


def audit_codes(sc):
    code, out, err = run(sc.p, "audit", "--json")
    return code, out + err


def write_ckpt(sc, text, age_min=0, name="progress.md"):
    path = os.path.join(sc.cw, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    when = time.time() - age_min * 60
    os.utime(path, (when, when))
    return path


def audit_scenario(**brief):
    return Scenario(cross=False, advances="none", progress_artifact="progress.md",
                    **brief).start()


def case_f_clean():
    sc = audit_scenario()
    write_ckpt(sc, GOOD_CKPT)
    code, text = audit_codes(sc)
    check_same("F: a clean program exits 0", code, 0)


def case_f_checkpoint_missing():
    sc = audit_scenario()
    code, text = audit_codes(sc)
    check_true("F: checkpoint-missing (artifact path relative to the entry's worktree)",
               code == 1 and "checkpoint-missing" in text)


def case_f_checkpoint_stale():
    sc = audit_scenario()
    write_ckpt(sc, GOOD_CKPT, age_min=120)
    code, text = audit_codes(sc)
    check_true("F: checkpoint-stale (mtime older than 30 min while running)",
               code == 1 and "checkpoint-stale" in text and "checkpoint-incomplete" not in text)


def case_f_checkpoint_incomplete():
    sc = audit_scenario()
    write_ckpt(sc, GOOD_CKPT.replace("open the pull request", "continue"))
    code, text = audit_codes(sc)
    check_true("F: checkpoint-incomplete for a vacuous label with a FRESH mtime",
               code == 1 and "checkpoint-incomplete" in text)
    write_ckpt(sc, GOOD_CKPT.replace("Verification: unit tests pass\n", ""))
    code, text = audit_codes(sc)
    check_true("F: checkpoint-incomplete for an absent label", "checkpoint-incomplete" in text)
    write_ckpt(sc, "## Last durable milestone\nshipped x\n## Verification\ntests\n"
                   "## Uncertain external effects\nnone\n## Next safe action\nmerge\n")
    code, text = audit_codes(sc)
    check_same("F: `## Label` headings with content are a valid checkpoint", code, 0)


def case_f_harvested_unfinished():
    sc = audit_scenario()
    write_ckpt(sc, GOOD_CKPT)
    data = sc.data()
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    ent = data["entries"][0]
    ent.update({"status": "harvested", "consumed_at": old, "harvested_at": old,
                "updated_at": old})
    with open(sc.tracker(), "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    code, text = audit_codes(sc)
    check_true("F: harvested-unfinished (harvested >10 min, no exception file)",
               code == 1 and "harvested-unfinished" in text)


def case_f_exception():
    sc = audit_scenario()
    write_ckpt(sc, GOOD_CKPT)
    path = sc.exception_path(sc.eid_cached)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "tracker": "root", "entry": sc.eid_cached, "title": "x",
                   "attempts": 1, "targets": [{"track": "T-015", "state": "failed",
                                               "code": "WRITE_CONFLICT", "repair": "r"}]}, fh)
    code, text = audit_codes(sc)
    check_true("F: exception (an exception file exists)", code == 1 and "exception" in text)


def case_f_home_unbound():
    sc = Scenario(progress_artifact="progress.md").start()
    write_ckpt(sc, GOOD_CKPT)
    check_same("F setup: a bound cross-repo lane audits clean", audit_codes(sc)[0], 0)
    if os.path.exists(marker(sc.cw)):
        os.unlink(marker(sc.cw))
    fresh()
    code, text = audit_codes(sc)
    check_true("F: home-unbound (cross-repo running entry, marker missing)",
               code == 1 and "home-unbound" in text)


def case_f_target_moved():
    sc = Scenario(progress_artifact="progress.md").start()
    write_ckpt(sc, GOOD_CKPT)
    fx = read_fixture(sc.fixture)
    fx["items"]["T-015"]["tasks"][0]["checked"] = True
    with open(sc.fixture, "w", encoding="utf-8") as fh:
        json.dump(fx, fh)
    code, text = audit_codes(sc)
    check_true("F: target-moved (running entry's track task already done)",
               code == 1 and "target-moved" in text)


def case_g_track_argv_injection():
    base = {f: "x" for f in orch.REQUIRED_BRIEF_FIELDS}
    base.update(expected_artifacts=["a.md"])
    for key, adv in (("track", {"track": "--allow-complete", "expect": "Approve design"}),
                     ("expect", {"track": "T-015", "expect": "--reassign-gate"})):
        try:
            orch.validate_brief(dict(base, advances=[adv]), "b.md")
            refused = None
        except orch.OrchError as exc:
            refused = str(exc)
        check_true("G: a flag-shaped %s is refused by validate_brief" % key,
                   refused and "must not start with `-`" in refused)
    try:
        orch.run_track("show", ["--allow-complete"], ".")
        refused = False
    except orch.OrchError:
        refused = True
    check_true("G: run_track itself refuses a flag-shaped positional", refused)

    sc = Scenario(open_lane=False)
    calls = sc.fixture + ".calls"
    os.environ["FAKE_TRACK_CALLS"] = calls
    try:
        ok, item = orch.run_track("show", ["T-015"], sc.p)
        ok2, res = orch.run_track("advance", ["T-015"], sc.p,
                                  ["--expect", "Implement retry policy", "--notify"])
    finally:
        del os.environ["FAKE_TRACK_CALLS"]
    check_true("G: a show still works through the new argv", ok and item.get("id") == "T-015")
    check_true("G: an advance still works through the new argv", ok2)
    with open(calls, "r", encoding="utf-8") as fh:
        argvs = [ln[len("call "):] for ln in fh.read().splitlines()]
    check_same("G: argv is sub, flags, then `--`, then the id", argvs, [
        "show --json --cwd %s -- T-015" % sc.p,
        "advance --json --cwd %s --expect Implement retry policy --notify -- T-015" % sc.p])
    check_true("G: nothing follows the `--` but the id",
               all(a.endswith(" -- T-015") for a in argvs))


for fn in (case_c_open_accepts_valid_mapping, case_c_refusals,
           case_c_target_not_yet_current_allowed, case_c_real_track,
           case_d_happy_path, case_d_notify_default_on, case_d_evidence_on_ref,
           case_d_bad_evidence, case_d_pending_refused,
           case_d_write_conflict_and_retry, case_d_track_write_conflict_race,
           case_d_retry_counts_attempts,
           case_d_idempotent_already, case_d_skip_target, case_d_legacy_plan_target,
           case_f_clean, case_f_checkpoint_missing, case_f_checkpoint_stale,
           case_f_checkpoint_incomplete, case_f_harvested_unfinished, case_f_exception,
           case_f_home_unbound, case_f_target_moved,
           case_g_track_argv_injection):
    case(fn)

print("\n%s" % ("all consume cases pass" if not FAILURES
                else "FAILED: %d -- %s" % (len(FAILURES), "; ".join(FAILURES))))
sys.exit(1 if FAILURES else 0)
