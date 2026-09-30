#!/usr/bin/env python3
"""Pin the lane profile launcher: what it injects, and when it stays out.

Run: python3 test_claude_lane.py

The launcher is configured as the Paseo `claude` provider's command, so every
Claude Code launch in a lane worktree goes through it. The cases below pin
when it injects the lane settings, when it merges them into an existing
--settings, and when it must pass through untouched -- a launch that blocks
is a worker that never starts.

No test framework, matching the plugin: one file, standard library only.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
LANE = os.path.join(os.path.dirname(HERE), "assets", "lane-profile", "claude-lane")
SETTINGS = os.path.join(os.path.dirname(HERE), "assets", "lane-profile",
                        "lane-settings.json")

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


def make_fake_claude():
    """A fake `claude` binary that echoes its argv as JSON."""
    root = tempfile.mkdtemp(prefix="claude-lane-")
    path = os.path.join(root, "claude")
    with open(path, "w") as fh:
        fh.write("#!/usr/bin/env python3\n"
                 "import json, sys\n"
                 "print(json.dumps(sys.argv))\n")
    os.chmod(path, 0o755)
    return root, path


def run_lane(cwd, argv, env_extra=None, lane_script=LANE):
    env = dict(os.environ)
    env.update(env_extra or {})
    proc = subprocess.run([lane_script] + argv, cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=120)
    return proc


def argv_of(proc):
    """The argv the fake claude received, or None if it never ran."""
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return json.loads(proc.stdout.strip())


def settings_json():
    with open(SETTINGS, encoding="utf-8") as fh:
        return json.load(fh)


def find_settings(argv):
    """The --settings value in an argv, or None."""
    for i, arg in enumerate(argv):
        if arg == "--settings" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--settings="):
            return arg[len("--settings="):]
    return None


# --------------------------------------------------------------------------- #
# Setup: a fake claude on PATH, a lane root, and a worktree inside it.
# --------------------------------------------------------------------------- #

_fake_dir, _fake_bin = make_fake_claude()
_lane_root = tempfile.mkdtemp(prefix="lane-root-")
_worktree = os.path.join(_lane_root, "wt-1")
os.makedirs(_worktree)
_outside = tempfile.mkdtemp(prefix="outside-")
_path = _fake_dir + os.pathsep + os.environ.get("PATH", "")
_env = {"PATH": _path, "CLAUDE_LANE_ROOTS": _lane_root}

# --------------------------------------------------------------------------- #
# 1. Inside a lane root, the settings are injected.
# --------------------------------------------------------------------------- #

proc = run_lane(_worktree, ["--foo"], _env)
argv = argv_of(proc)
check_same("inside a lane root, the real claude runs", bool(argv), True)
check_same("and the lane settings are appended",
           json.loads(find_settings(argv)), settings_json())
check_same("and the original arg is kept", argv[-3], "--foo")

# --------------------------------------------------------------------------- #
# 2. Outside a lane root, nothing is injected.
# --------------------------------------------------------------------------- #

proc = run_lane(_outside, ["--foo"], _env)
check_same("outside a lane root, argv passes through",
           argv_of(proc), [_fake_bin, "--foo"])

# --------------------------------------------------------------------------- #
# 3. A bare informational call passes through even inside a lane root.
# --------------------------------------------------------------------------- #

for _flag in ("--version", "-v", "--help", "-h"):
    proc = run_lane(_worktree, [_flag], _env)
    check_same("%s passes through" % _flag, argv_of(proc),
               [_fake_bin, _flag])

# --------------------------------------------------------------------------- #
# 4. An existing --settings JSON is merged, lane entries winning.
# --------------------------------------------------------------------------- #

_caller = {"permissions": {"allow": ["Bash"]},
           "enabledPlugins": {"claude-mem@thedotmack": True,
                              "other-plugin@x": True}}
proc = run_lane(_worktree, ["--settings", json.dumps(_caller)], _env)
argv = argv_of(proc)
merged = json.loads(find_settings(argv))
check_same("an existing --settings JSON is merged",
           merged["permissions"], {"allow": ["Bash"]})
check_same("the lane profile's enabledPlugins entries win",
           merged["enabledPlugins"]["claude-mem@thedotmack"], False)
check_same("the caller's other enabledPlugins entries are kept",
           merged["enabledPlugins"]["other-plugin@x"], True)
check_same("and the merged settings replace the original flag",
           argv.count("--settings"), 1)

proc = run_lane(_worktree, ["--settings=" + json.dumps(_caller)], _env)
argv = argv_of(proc)
check_same("the --settings= form merges the same way",
           json.loads(find_settings(argv))["enabledPlugins"]["claude-mem@thedotmack"],
           False)

# --------------------------------------------------------------------------- #
# 5. An existing --settings file path is merged.
# --------------------------------------------------------------------------- #

_settings_file = os.path.join(_outside, "caller-settings.json")
with open(_settings_file, "w", encoding="utf-8") as fh:
    json.dump({"permissions": {"allow": ["Bash"]}}, fh)
proc = run_lane(_worktree, ["--settings", _settings_file], _env)
argv = argv_of(proc)
merged = json.loads(find_settings(argv))
check_same("an existing --settings file path is merged",
           merged["permissions"], {"allow": ["Bash"]})
check_same("and the lane settings ride along",
           merged["enabledPlugins"], settings_json()["enabledPlugins"])

# --------------------------------------------------------------------------- #
# 6. A missing settings file passes through, with one stderr line.
# --------------------------------------------------------------------------- #

_lonely = tempfile.mkdtemp(prefix="lonely-lane-")
_lonely_script = os.path.join(_lonely, "claude-lane")
shutil.copy2(LANE, _lonely_script)
os.chmod(_lonely_script, 0o755)
proc = run_lane(_worktree, ["--foo"], _env, lane_script=_lonely_script)
check_same("a missing settings file passes through",
           argv_of(proc), [_fake_bin, "--foo"])
check_true("and says so on stderr", "missing or invalid" in proc.stderr)

# --------------------------------------------------------------------------- #
# 7. CLAUDE_LANE_PROFILE=0 disables injection.
# --------------------------------------------------------------------------- #

proc = run_lane(_worktree, ["--foo"], dict(_env, CLAUDE_LANE_PROFILE="0"))
check_same("CLAUDE_LANE_PROFILE=0 passes through",
           argv_of(proc), [_fake_bin, "--foo"])

print()
if FAILURES:
    print("  %d FAILURE(S): %s" % (len(FAILURES), ", ".join(FAILURES)))
    sys.exit(1)
print("  all pass")
