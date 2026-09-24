#!/usr/bin/env python3
"""Pin the rung rename: minimal/economy/advanced/frontier, `default` retired.

Run: python3 test_orch_rungs.py

`default` used to sit in MODEL_RUNGS as the rung above `economy`. It was
renamed to `advanced` because `default` never named a fixed point -- it meant
whatever the provider currently selects, and that drifted up a tier without
the word changing (see orch.py's comment on MODEL_RUNGS). This file pins three
things that must all still hold:

  1. `advanced` works everywhere `default` used to.
  2. `default` is refused everywhere it is offered as a rung, with a hint
     toward `advanced` -- not a generic "not one of ..." error.
  3. A tracker entry written before the rename, still holding the literal
     string "default", loads without crashing and renders as legacy rather
     than as a silently-accepted rung.

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

HERE = os.path.dirname(os.path.realpath(__file__))
_spec = importlib.util.spec_from_file_location("orch", os.path.join(HERE, "orch.py"))
orch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(orch)

FAILURES = []


def check_same(name, got, want):
    ok = got == want
    if not ok:
        FAILURES.append(name)
    print("  %-64s %s" % (name, "ok" if ok else "FAIL"))
    if not ok:
        print("    got  %r\n    want %r" % (got, want))


def check_true(name, got):
    check_same(name, bool(got), True)


def run(repo, command, *rest):
    """Call orch.main() in-process, capturing its stdout/stderr and exit code.

    `--repo` is a top-level flag that must precede the subcommand -- argparse
    treats anything after `open`/`update`/... as that subcommand's own args.
    """
    out, err = io.StringIO(), io.StringIO()
    argv = ["--repo", repo, command] + list(rest)
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = orch.main(argv)
    return code, out.getvalue(), err.getvalue()


def make_repo():
    root = tempfile.mkdtemp(prefix="orch-rungs-")
    subprocess.run(["git", "init", "-q", root], check=True)
    subprocess.run(["git", "-C", root, "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", root, "config", "user.name", "t"], check=True)
    return root


def write_brief(root, model):
    path = os.path.join(root, "brief.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            "---\n"
            "title: rung rename test\n"
            "worktree: %s\n"
            "expected_artifacts:\n"
            "  - out.txt\n"
            "advances: none\n"
            "consumption: this test reads it\n"
            "model: %s\n"
            "---\n\n# body\n" % (root, model)
        )
    return path


# --------------------------------------------------------------------------- #
# 1. `advanced` works where `default` used to.
# --------------------------------------------------------------------------- #

root = make_repo()
brief = write_brief(root, "advanced")
code, out, err = run(root, "open", "--brief", brief)
check_same("open with model: advanced succeeds", code, 0)
check_true("open with model: advanced prints an entry id", out.strip().startswith("e"))

repo_key, _, _ = orch.repo_identity(root)
program = orch.resolve_program(repo_key, None)
tracker_file = orch.tracker_path(repo_key, program, "root")
data = orch.load_tracker(tracker_file)
check_same("recorded entry carries the advanced rung", data["entries"][0]["model"], "advanced")

# --------------------------------------------------------------------------- #
# 2. `default` is refused, everywhere it is offered as a rung, with the hint.
# --------------------------------------------------------------------------- #

root2 = make_repo()
brief_default = write_brief(root2, "default")
code, out, err = run(root2, "open", "--brief", brief_default)
check_same("brief model: default is rejected (nonzero exit)", code == 0, False)
check_true("brief model: default names it not a rung", "not a rung" in err)
check_true("brief model: default hints at advanced", "advanced" in err)

root3 = make_repo()
brief_ok = write_brief(root3, "economy")
run(root3, "open", "--brief", brief_ok)
code, out, err = run(root3, "open", "--brief", brief_ok, "--model", "default")
check_same("--model default is rejected (nonzero exit)", code == 0, False)
check_true("--model default names it not a rung", "not a rung" in err)
check_true("--model default hints at advanced", "advanced" in err)

repo_key3, _, _ = orch.repo_identity(root3)
program3 = orch.resolve_program(repo_key3, None)
tracker3 = orch.tracker_path(repo_key3, program3, "root")
entry_id = orch.load_tracker(tracker3)["entries"][0]["entry"]
code, out, err = run(root3, "escalate", entry_id, "--to", "default",
                       "--reason", "checking the retired rung is refused")
check_same("escalate --to default is rejected (nonzero exit)", code == 0, False)
check_true("escalate --to default names it not a rung", "not a rung" in err)

code, out, err = run(root3, "update", entry_id, "--model", "default")
check_same("update --model default is rejected (nonzero exit)", code == 0, False)
check_true("update --model default names it not a rung", "not a rung" in err)

check_same("MODEL_RUNGS has the four current names, in order", orch.MODEL_RUNGS,
           ("minimal", "economy", "advanced", "frontier"))
check_true("'default' is not itself one of the rungs", "default" not in orch.MODEL_RUNGS)

# --------------------------------------------------------------------------- #
# 3. A legacy tracker entry (written before the rename) loads and renders as
#    legacy, without crashing and without being displayed as a plain rung.
# --------------------------------------------------------------------------- #

root4 = make_repo()
brief4 = write_brief(root4, "economy")
run(root4, "open", "--brief", brief4)
repo_key4, _, _ = orch.repo_identity(root4)
program4 = orch.resolve_program(repo_key4, None)
tracker4 = orch.tracker_path(repo_key4, program4, "root")
data4 = orch.load_tracker(tracker4)
data4["entries"][0]["model"] = "default"   # simulate a pre-rename tracker file
orch.save_tracker(tracker4, data4)

reloaded = orch.load_tracker(tracker4)   # must not raise
check_same("a legacy 'default' tracker entry loads without crashing",
           reloaded["entries"][0]["model"], "default")

code, out, err = run(root4, "roster")
check_same("roster runs against a legacy tracker", code, 0)
check_true('roster renders it as advanced, labelled legacy',
           'TIER:advanced (legacy "default")' in out)
check_true("roster never prints the bare retired rung as a tier",
           "TIER:default" not in out)

check_same("stored_rung_index treats legacy 'default' as advanced",
           orch.stored_rung_index("default"), orch.rung_index("advanced"))
check_same("rung_index refuses to resolve 'default' at all",
           orch.rung_index("default"), -1)
check_same("display_rung labels the legacy spelling",
           orch.display_rung("default"), 'advanced (legacy "default")')

# --------------------------------------------------------------------------- #
# `orch cost` still runs -- unrelated to the rung rename, but a regression this
# change could plausibly cause if MODEL_RUNGS were imported at the wrong time
# or a rung helper broke an unrelated code path. No transcript exists in this
# throwaway repo, so the expected outcome is the ordinary, unrelated
# "no transcript found" OrchError -- not a crash on the rung machinery.
# --------------------------------------------------------------------------- #

code, out, err = run(root4, "cost", "--format", "text")
check_same("orch cost fails cleanly on the expected, unrelated cause", code, 2)
check_true("orch cost's failure is 'no transcript found', not a rung crash",
           "no transcript found" in err)

print()
if FAILURES:
    print("  %d FAILURE(S): %s" % (len(FAILURES), ", ".join(FAILURES)))
    sys.exit(1)
print("  all pass")
