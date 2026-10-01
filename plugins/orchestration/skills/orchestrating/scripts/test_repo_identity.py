#!/usr/bin/env python3
"""repo_identity's filesystem fast path must agree with git everywhere it answers."""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orch  # noqa: E402

FAILURES = []


def check_same(name, got, want):
    ok = got == want
    if not ok:
        FAILURES.append(name)
    print("  %-66s %s" % (name, "ok" if ok else "FAIL"))
    if not ok:
        print("    got  %r\n    want %r" % (got, want))


def git(cwd, *args):
    return subprocess.run(["git"] + list(args), cwd=cwd, check=True, text=True,
                          capture_output=True).stdout.strip()


def git_common(cwd):
    return os.path.realpath(git(cwd, "rev-parse", "--path-format=absolute",
                                "--git-common-dir"))


base = os.path.realpath(tempfile.mkdtemp(prefix="orch-identity-"))
main = os.path.join(base, "main")
os.makedirs(os.path.join(main, "a", "b"))
git(base, "init", "-q", main)
git(main, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
    "--allow-empty", "-m", "init")
lane = os.path.join(base, "lane")
git(main, "worktree", "add", "-q", lane)
os.makedirs(os.path.join(lane, "deep"))

for label, where in [("checkout root", main), ("checkout subdirectory", os.path.join(main, "a", "b")),
                     ("linked worktree", lane), ("linked worktree subdirectory",
                                                 os.path.join(lane, "deep"))]:
    check_same("fast path matches git: %s" % label, orch._fs_common_dir(where), git_common(where))

check_same("a worktree and its main checkout share one repo key",
           orch.repo_identity(lane)[0], orch.repo_identity(main)[0])
check_same("a start inside the git dir defers to git",
           orch._fs_common_dir(os.path.join(main, ".git")), None)
check_same("outside any repository there is no fast answer",
           orch._fs_common_dir(base), None)

os.environ["GIT_DIR"] = os.path.join(main, ".git")
check_same("a GIT_DIR override defers to git", orch._fs_common_dir(main), None)
del os.environ["GIT_DIR"]

print("\n  %s" % ("all pass" if not FAILURES else
                  "%d failure(s): %s" % (len(FAILURES), ", ".join(FAILURES))))
sys.exit(1 if FAILURES else 0)
