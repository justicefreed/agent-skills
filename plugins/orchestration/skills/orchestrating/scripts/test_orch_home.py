#!/usr/bin/env python3
"""Pin cross-repo home binding (rationale: docs/DESIGN.md §9h).

Run: python3 test_orch_home.py

  A. Rollback tolerance: main's orch reads the state the branch writes
     (mapping `advances`, consumed_text/evidence/consumed_at, `exceptions/`).
  B. Home binding: a lane whose cwd is a linked worktree of another repo C
     resolves to the planning repo P, by marker or by ORCH_HOME, exactly as a
     linked worktree of P would. Four refusals guard the marker.

Expected to be red until the core lane lands; each failing check names the
section and the behaviour it wants. No test framework: standard library only.
"""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.realpath(__file__))
os.environ.setdefault("ORCH_FANOUT_MAX", "100")
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp(prefix="orch-home-state-")
os.environ.pop("ORCH_HOME", None)
_spec = importlib.util.spec_from_file_location("orch", os.path.join(HERE, "orch.py"))
orch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(orch)

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
    """Run one case; a crash is a failure of that case, not of the suite."""
    try:
        fn()
    except BaseException as exc:  # noqa: BLE001 - report, keep going
        if isinstance(exc, KeyboardInterrupt):
            raise
        FAILURES.append(fn.__name__)
        print("  %-72s FAIL (crashed)" % fn.__name__)
        print("    " + traceback.format_exc().strip().replace("\n", "\n    "))


def fresh():
    """Drop the per-process identity cache: a real hook is a new process."""
    cache = getattr(orch, "_repo_identity", None)
    if hasattr(cache, "cache_clear"):
        cache.cache_clear()


def run(repo, command, *rest, **kw):
    out, err = io.StringIO(), io.StringIO()
    stdin = sys.stdin
    sys.stdin = io.StringIO(kw.get("stdin", ""))
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = orch.main(["--repo", repo, command] + list(rest))
            except SystemExit as exc:  # argparse: unknown command or flag
                code = exc.code if isinstance(exc.code, int) else 2
    finally:
        sys.stdin = stdin
    return code, out.getvalue(), err.getvalue()


def sh(*cmd, **kw):
    subprocess.run(list(cmd), check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, **kw)


def make_repo():
    root = os.path.realpath(tempfile.mkdtemp(prefix="orch-home-"))
    sh("git", "init", "-q", root)
    sh("git", "-C", root, "-c", "user.name=t", "-c", "user.email=t@t",
       "commit", "-q", "--allow-empty", "-m", "init")
    return root


def linked_worktree(repo, name):
    path = os.path.join(os.path.dirname(repo), "%s-%s" % (os.path.basename(repo), name))
    sh("git", "-C", repo, "worktree", "add", "-q", "-b", name, path)
    return os.path.realpath(path)


def git_dir(worktree):
    with open(os.path.join(worktree, ".git"), "r", encoding="utf-8") as fh:
        line = fh.read().strip()
    return os.path.realpath(os.path.join(worktree, line[len("gitdir:"):].strip()))


def marker(worktree):
    return os.path.join(git_dir(worktree), "orch-home.json")


def write_brief(where, worktree, name="brief.md", title="cross lane", advances="none"):
    lines = ["title: %s" % title, "worktree: %s" % worktree,
             "expected_artifacts:", "  - out.txt", "advances: %s" % advances,
             "consumption: this test reads it", "archetype: implementer"]
    path = os.path.join(where, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("---\n%s\n---\n\n# body\n" % "\n".join(lines))
    return path


def tracker(repo, program=None):
    key, _, _ = orch.repo_identity(repo)
    program = program or orch.resolve_program(key, None)
    path = orch.tracker_path(key, program, "root")
    return path, orch.load_tracker(path)


def open_cross(prog_repo, worktree, name="brief.md", title="cross lane", *extra):
    code, out, err = run(prog_repo, "open", "--brief",
                         write_brief(prog_repo, worktree, name, title), *extra)
    fresh()
    return code, out, err


# --------------------------------------------------------------------------- #
# A. Rollback tolerance (this commit must also pass on main's orch).
# --------------------------------------------------------------------------- #

def case_a_rollback_compat():
    repo = make_repo()
    code, out, err = run(repo, "open", "--brief", write_brief(repo, repo, "a.md"))
    check_same("A: setup open succeeds", code, 0)
    path, data = tracker(repo)
    entry = data["entries"][0]
    entry["advances"] = ["3.4", {"track": "T-015", "expect": "Implement retry policy"}]
    entry.update({"consumed_text": "shipped", "evidence": ["commit:/x@abc"],
                  "consumed_at": "2026-01-01T00:00:00Z"})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.makedirs(os.path.join(os.path.dirname(path), "exceptions"), exist_ok=True)
    for cmd in (("roster",), ("render",), ("resume",), ("statusline",)):
        try:
            code, out, err = run(repo, *cmd)
        except Exception as exc:  # main's render crashes on a mapping today
            code, out, err = 99, "", repr(exc)
        check_same("A: main's `%s` succeeds on branch-written state" % cmd[0], code, 0)
        if cmd[0] == "render":  # roster has never printed advances
            check_true("A: `%s` prints a mapping advance as track:T-015" % cmd[0],
                       "track:T-015" in out)
    eid = entry["entry"]
    # A second open rewrites the tracker; unknown keys must survive it.
    code, _, _ = run(repo, "open", "--brief", write_brief(repo, repo, "b.md", title="second"))
    check_same("A: a second `open` succeeds with exceptions/ present", code, 0)
    _, data = tracker(repo)
    kept = [e for e in data["entries"] if e["entry"] == eid]
    check_true("A: the rewrite preserves consumed_text/evidence/consumed_at",
               kept and all(k in kept[0] for k in ("consumed_text", "evidence", "consumed_at")))
    names = orch.tracker_names(os.path.dirname(path))
    check_true("A: tracker_names does not list exceptions/ as a tracker",
               "exceptions" not in names and "root" in names)
    code, out, err = run(repo, "close", eid, "--consumed", "used the output",
                         "--untracked", "compat test: the item must not advance")
    check_same("A: main's `close` succeeds on branch-written state", code, 0)


# --------------------------------------------------------------------------- #
# B. Home binding.
# --------------------------------------------------------------------------- #

def case_b_marker_delivery_whoami_resume_close():
    p, c = make_repo(), make_repo()
    cw = linked_worktree(c, "lane1")
    code, out, err = open_cross(p, cw)
    check_same("B: cross-repo `open` from P succeeds", code, 0)
    check_true("B: `open` writes <worktree gitdir>/orch-home.json", os.path.isfile(marker(cw)))
    _, data = tracker(p)
    eid = data["entries"][0]["entry"]
    try:
        with open(marker(cw), "r", encoding="utf-8") as fh:
            mk = json.load(fh)
    except (OSError, ValueError):
        mk = {}
    key_p, root_p, common_p = orch.repo_identity(p)
    check_same("B: marker names P's repo_key/root/common, the entry",
               (mk.get("repo_key"), mk.get("root"), mk.get("common"), mk.get("entry"),
                mk.get("tracker"), mk.get("version")),
               (key_p, root_p, common_p, eid, "root", 1))
    check_true("B: marker records the program", bool(mk.get("program")))
    mtime = os.path.getmtime(marker(cw)) if os.path.exists(marker(cw)) else None
    key_c = orch.repo_identity(c)[0]
    check_true("B: C and P are distinct repos (test sanity)", key_c != key_p)

    code, out, err = run(p, "inbox", "send", "--to", "w1", "--body", "ping from the planner",
                         "--kind", "fyi")
    check_same("B: `inbox send` from P succeeds", code, 0)
    code, out, err = run(cw, "inbox", "drain", "--format", "hook", "--to", "w1")
    check_true("B: `inbox drain --format hook` in C's worktree delivers P's item",
               "ping from the planner" in out)
    code, out, err = run(cw, "whoami", "--worktree", cw)
    check_true("B: `whoami` in C's worktree returns the entry (%s)" % eid,
               code == 0 and eid in err)
    code, out, err = run(cw, "resume")
    check_true("B: `resume` in C's worktree shows P's program (cross lane)",
               code == 0 and "cross lane" in out)

    code, _, _ = open_cross(p, cw)
    check_true("B: re-opening the identical binding is idempotent or refused as duplicate-free",
               mtime is None or os.path.getmtime(marker(cw)) == mtime or code != 0)

    code, out, err = run(p, "close", eid, "--consumed", "used the lane output")
    check_same("B: `close` succeeds", code, 0)
    check_true("B: `close` removes the marker", not os.path.exists(marker(cw)))


def case_b_env_override():
    p, c = make_repo(), make_repo()
    cw = linked_worktree(c, "envlane")
    # Open from P with the marker, then drop the marker: only ORCH_HOME remains.
    code, _, _ = open_cross(p, cw)
    _, data = tracker(p)
    eid = data["entries"][0]["entry"]
    if os.path.exists(marker(cw)):
        os.unlink(marker(cw))
    fresh()
    run(p, "inbox", "send", "--to", "w2", "--body", "env route ping", "--kind", "fyi")
    check_same("B: without marker or ORCH_HOME the lane does not see P",
               "env route ping" in run(cw, "inbox", "drain", "--format", "hook",
                                       "--to", "w2")[1], False)
    fresh()
    os.environ["ORCH_HOME"] = p
    try:
        code, out, err = run(cw, "inbox", "drain", "--format", "hook", "--to", "w2")
        check_true("B: ORCH_HOME (no marker) routes `inbox drain` to P", "env route ping" in out)
        fresh()
        code, out, err = run(cw, "whoami", "--worktree", cw)
        check_true("B: ORCH_HOME (no marker) makes `whoami` return the entry",
                   code == 0 and eid in err)
        fresh()
        code, out, err = run(cw, "resume")
        check_true("B: ORCH_HOME (no marker) makes `resume` show P's program",
                   code == 0 and "cross lane" in out)
    finally:
        del os.environ["ORCH_HOME"]
        fresh()


def case_b_refusals():
    p, c = make_repo(), make_repo()
    # (a) worktree does not exist
    code, out, err = open_cross(p, os.path.join(c, "no-such-worktree"), "r1.md", "ghost")
    check_true("B refusal (a): cross-repo brief with a missing worktree is refused",
               code != 0)
    # (b) primary checkout
    code, out, err = open_cross(p, c, "r2.md", "primary")
    check_true("B refusal (b): a primary checkout is refused, naming linked worktrees",
               code != 0 and "linked worktree" in err)
    check_true("B refusal (b): no marker was written into the primary checkout",
               not os.path.exists(os.path.join(c, ".git", "orch-home.json")))
    # (c) marker already exists for a different entry
    cw = linked_worktree(c, "taken")
    code, _, _ = open_cross(p, cw, "r3.md", "first")
    check_same("B refusal setup: first cross-repo open succeeds", code, 0)
    code, out, err = open_cross(p, cw, "r4.md", "second")
    check_true("B refusal (c): a marker for a different entry is refused", code != 0)
    # (d) marker already exists for a different program
    code, out, err = open_cross(p, cw, "r5.md", "third", "--program", "other-program")
    check_true("B refusal (d): a marker for a different program is refused", code != 0)
    check_true("B refusal: the original marker is intact",
               os.path.isfile(marker(cw)))


for fn in (case_a_rollback_compat, case_b_marker_delivery_whoami_resume_close,
           case_b_env_override, case_b_refusals):
    case(fn)

print("\n%s" % ("all home cases pass" if not FAILURES
                else "FAILED: %d -- %s" % (len(FAILURES), "; ".join(FAILURES))))
sys.exit(1 if FAILURES else 0)
