#!/usr/bin/env python3
"""Pin the parts of spend.py that are wrong in a way no one notices.

Run: python3 test_spend.py

Every case here is a rate or dedup rule that produced plausible-looking
numbers while being wrong. A cost tool that is quietly 10% low is worse than
one that fails, because its output still gets used.

No test framework, matching the plugin: one file, standard library only.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
_spec = importlib.util.spec_from_file_location("spend", os.path.join(HERE, "spend.py"))
spend = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spend)

# opus-5, $/M: in 5.0 · out 25.0 · write-5m 6.25 · write-1h 10.0 · read 0.5
RATES = spend.DEFAULT_RATES
_tmp = []


def transcript(rows):
    fh = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for row in rows:
        fh.write(json.dumps(row) + "\n")
    fh.close()
    _tmp.append(fh.name)
    return fh.name


def call(request_id, **usage):
    return {"type": "assistant", "requestId": request_id,
            "message": {"model": "claude-opus-5", "id": "m" + request_id,
                        "usage": usage}}


def write(total, ephemeral_1h=None):
    """A call whose only cost is `total` cache-creation tokens."""
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
             "cache_creation_input_tokens": total}
    if ephemeral_1h is not None:
        usage["cache_creation"] = {"ephemeral_1h_input_tokens": ephemeral_1h}
    return usage


FAILURES = []


def check(name, got, want):
    ok = abs(got - want) < 1e-9
    if not ok:
        FAILURES.append(name)
    print("  %-48s %14.6f  want %14.6f  %s"
          % (name, got, want, "ok" if ok else "FAIL"))


def check_same(name, got, want):
    """Exact equality, for the things that are strings rather than money."""
    ok = got == want
    if not ok:
        FAILURES.append(name)
    print("  %-48s %s" % (name, "ok" if ok else "FAIL"))
    if not ok:
        print("    got  %r\n    want %r" % (got, want))


M = 1_000_000

# Provider wrappers, case, and punctuation must not change the underlying rate.
check_same("cursor prefix resolves GPT-5.6 Sol",
           spend.rate_for("cursor/GPT-5.6-sol", RATES),
           RATES["gpt-5.6-sol"])
check_same("cursor/claude prefix resolves Fable 5.1",
           spend.rate_for("cursor/claude-fable-5-1", RATES),
           RATES["fable-5.1"])
check_same("GPT-5.6 Sol published rates",
           RATES["gpt-5.6-sol"],
           {"in": 4.0, "out": 20.0, "cache_write": 5.0,
            "cache_write_1h": 5.0, "cache_read": 0.4})
check_same("Fable 5.1 published rates",
           RATES["fable-5.1"],
           {"in": 10.0, "out": 50.0, "cache_write": 12.5,
            "cache_write_1h": 20.0, "cache_read": 0.25})
check_same("versioned model beats generic family alias",
           spend.rate_for("anthropic/claude-sonnet-4-6", RATES),
           RATES["sonnet-4.6"])
check_same("fast variant beats base model",
           spend.rate_for("cursor/GPT-5.6-Terra-Fast", RATES),
           RATES["gpt-5.6-terra-fast"])
check_same("generic alias requires a complete token",
           spend.rate_for("provider/notopus-model", RATES),
           RATES["default"])

# Model selection is two deterministic filters: the versioned policy says what
# fits, and the live catalog says what can actually be spawned. A prose table
# cannot make the second guarantee.
_model_options = {
    "archetypes": {
        "implementer": {
            "aliases": ["implementation"],
            "rung": "economy",
            "effort": "medium",
        },
    },
    "models": [
        {"id": "gpt-5.6-luna", "family": "gpt-5.6",
         "rungs": ["minimal", "economy"], "use": "bounded work"},
        {"id": "claude-sonnet-5", "family": "claude-sonnet",
         "rungs": ["economy", "advanced"], "use": "interconnected work"},
        {"id": "retired-model", "family": "retired",
         "rungs": ["economy"], "use": "must not appear"},
    ],
}
_model_catalog = [
    {"slug": "cursor/gpt-5.6-luna",
     "supported_reasoning_levels": [
         {"effort": "low"}, {"effort": "medium"}, {"effort": "high"}]},
    {"slug": "cursor/claude-sonnet-5",
     "supported_reasoning_levels": [{"effort": "low"}]},
]
_selected = spend.select_models(
    _model_options, _model_catalog, "economy", "medium")
check_same("model selector returns exact live slugs",
           [row["model"] for row in _selected],
           ["cursor/gpt-5.6-luna", "cursor/claude-sonnet-5"])
check_same("model selector emits only supported efforts",
           [row["effort"] for row in _selected], ["medium", "low"])
check_same("model selector can require an independent family",
           [row["model"] for row in spend.select_models(
               _model_options, _model_catalog, "economy", "medium", "gpt-5.6")],
           ["cursor/claude-sonnet-5"])
check_same("archetype aliases resolve to canonical policy",
           spend.resolve_archetype(
               "implementation", _model_options["archetypes"])[0],
           "implementer")

# The 1-hour cache-write tier bills at 2x input; the 5-minute tier at 1.25x.
# `cache_creation_input_tokens` is their sum and did not change when the
# breakdown was added, so code reading only it prices 1h writes at the 5m rate.
# Measured at a 10.3% understatement on a 1h-TTL harness.
check("1M cache write, all 1h -> 2x input",
      spend.read_usage(transcript([call("a", **write(M, ephemeral_1h=M))]), RATES)["cost"],
      10.0)
check("1M cache write, all 5m -> 1.25x input",
      spend.read_usage(transcript([call("b", **write(M, ephemeral_1h=0))]), RATES)["cost"],
      6.25)
check("mixed: 5m derived by subtracting 1h from the total",
      spend.read_usage(transcript([call("c", **write(M, ephemeral_1h=400_000))]), RATES)["cost"],
      0.6 * 6.25 + 0.4 * 10.0)

# A transcript predating the breakdown must degrade to the old answer. Reading
# the tiers alone and ignoring the flat field would price it at zero.
_legacy = spend.read_usage(transcript([call("d", **write(M))]), RATES)
check("no breakdown -> all 5m, nothing dropped", _legacy["cost"], 6.25)
check("no breakdown -> tokens still total 1M",
      float(_legacy["tokens"]["cache_write"] + _legacy["tokens"]["cache_write_1h"]), float(M))

# A rates.json written before the tier existed has no cache_write_1h key.
# Falling back to the 5m rate would silently reintroduce the bug.
_legacy_rates = {"default": {"in": 5.0, "out": 25.0,
                             "cache_write": 6.25, "cache_read": 0.5}}
check("rates table without cache_write_1h -> synthesized at 2x",
      spend.read_usage(transcript([call("e", **write(M, ephemeral_1h=M))]),
                       _legacy_rates)["cost"],
      10.0)

# One API response occupies one transcript line per content block, each with an
# identical copy of `usage`. Summing lines overstated a measured bill by 2.23x.
_dup = spend.read_usage(
    transcript([call("f", **write(M, ephemeral_1h=M))] * 3), RATES)
check("3 content blocks, 1 response -> counted once", _dup["cost"], 10.0)
check("3 content blocks, 1 response -> 1 step", float(_dup["steps"]), 1.0)

# Context is every token the call carried, so both write tiers count.
_ctx = spend.read_usage(transcript([call("g", **write(M, ephemeral_1h=600_000))]), RATES)
check("context counts both write tiers", float(_ctx["context"]), float(M))

# on_line sees every raw line, including ones with no usage block. This is what
# lets orch.py add its relay counts without a second copy of the pricing loop.
_seen = []
spend.read_usage(transcript([{"type": "user", "message": {"content": "hi"}},
                             call("h", **write(M, ephemeral_1h=M))]),
                 RATES, on_line=_seen.append)
check("on_line observes non-usage lines too", float(len(_seen)), 2.0)

# The four hooks ship through two channels -- `plugin.json` for a marketplace
# install, `spend install` for the symlink path -- and nothing about a session
# that is missing its cost line tells you which channel delivered the hook that
# did not fire. So they are generated from one place and pinned here.
_manifest = os.path.join(HERE, "..", ".claude-plugin", "plugin.json")
with open(_manifest) as fh:
    check_same("plugin.json hooks match the generator",
               json.load(fh).get("hooks"), spend.desired_hooks_object())

# The bug this replaced: `install` baked in the absolute path of whichever copy
# of spend.py ran it. From a git worktree that path is reclaimed along with the
# worktree, and every hook ends in `exit 0`, so the whole plugin goes quiet
# without erroring. Resolution must therefore happen when the hook fires.
_installed = spend.hook_command("guard", marker=True)
check_same("install command carries no absolute path",
           os.path.realpath(spend.__file__) in _installed, False)
check_same("install command is the manifest one, plus a marker",
           _installed, spend.hook_command("guard") + "  # " + spend.HOOK_MARKER)

# Naming `python3` and letting PATH answer cost 14x on a machine with a pyenv
# shim first -- 1.25s per tool call at 6% CPU, blocked rather than computing,
# holding a shell open the whole time in every concurrent session. The script
# was never the expense; the name was. Prose did not hold this the first time,
# so it is pinned: every hook must run an interpreter it resolved itself.
for _action in (action for _, _, action in spend.DESIRED_HOOKS):
    _cmd = spend.hook_command(_action)
    check_same("%r resolves its own interpreter" % _action.split()[0],
               "PY=/usr/bin/python3" in _cmd and "SPEND_PYTHON" in _cmd, True)
    check_same("%r runs $PY, never a bare python3" % _action.split()[0],
               ' python3 "$d/scripts/spend.py"' in _cmd, False)

# The prefilter decides in shell what the guard would spend ~88ms of Python
# startup to decide. Several ways it can be silently wrong, all of which lose
# the signal rather than break anything:
_guard = spend.hook_command("guard")
# It consumes stdin, which `hook_payload` deliberately refuses to do on a
# terminal. Without this check ahead of the `cat`, an interactive run blocks
# forever holding a shell -- the exact failure the whole change is about.
check_same("guard checks for a terminal before reading stdin",
           _guard.index("-t 0") < _guard.index("$(cat)"), True)
# Filtering at GUARD_BYTES would drop every heredoc between the two floors, and
# heredoc detection is the guard's most actionable signal. Filtering at only the
# heredoc floor is the mirror bug: it swallows warnings for anyone who tuned
# GUARD_BYTES below it. Both floors are resolved at fire time; the smaller wins.
check_same("guard prefilter carries both payload floors, not one",
           str(spend.GUARD_HEREDOC_BYTES_DEFAULT) in _guard
           and str(spend.GUARD_BYTES_DEFAULT) in _guard, True)
# The override names are the ones `env()` honours, SPEND_ then ORCH_. Naming the
# bare constant here would read a threshold nobody set and ignore the tuned one.
for _name in ("SPEND_GUARD_HEREDOC_BYTES", "ORCH_GUARD_HEREDOC_BYTES",
              "SPEND_GUARD_BYTES", "ORCH_GUARD_BYTES"):
    check_same("guard prefilter reads %s" % _name, _name in _guard, True)
# `_unbounded_read_bytes` sizes the file, not the payload, so a Read can be
# small on the wire and still worth warning about. It must never be filtered.
check_same("guard prefilter always lets a Read through", "*Read*" in _guard, True)

# Everything above is a substring assertion, and the failure mode of generating
# shell out of Python is QUOTING, which no substring assertion can see. So the
# generated command is actually run, against the payload shapes whose handling
# differs. `sh` rather than the caller's shell: that is what a hook runs under.
_FLOOR_VARS = ("SPEND_GUARD_BYTES", "ORCH_GUARD_BYTES",
               "SPEND_GUARD_HEREDOC_BYTES", "ORCH_GUARD_HEREDOC_BYTES")


def guard_out(command=None, payload=None, **overrides):
    """stdout of the real guard hook for one payload. Fresh state dir each call,
    so the per-kind cooldown never makes an earlier case suppress a later one."""
    if payload is None:
        payload = {"tool_name": "Bash", "tool_input": {"command": command},
                   "cwd": HERE}
    env = {k: v for k, v in os.environ.items() if k not in _FLOOR_VARS}
    env.update(SPEND_SKILL_DIR=os.path.dirname(HERE),
               SPEND_STATE_HOME=tempfile.mkdtemp(), **overrides)
    return subprocess.run(
        ["sh", "-c", spend.hook_command("guard")],
        input=json.dumps(payload), text=True, env=env, timeout=60,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.strip()


check_same("live: an ordinary small command says nothing",
           guard_out("ls -la"), "")
check_same("live: a big inline doc warns",
           "inline doc" in guard_out("cat > /tmp/x.md <<EOF\n%s\nEOF" % ("x " * 900)),
           True)
# The regression the two-floor fix exists for: with GUARD_BYTES tuned under the
# heredoc floor, a payload between the two must still reach Python. A prefilter
# hardcoded at 1200 returns "" here and the tuned threshold is silently dead.
check_same("live: a floor tuned below the heredoc one is honoured",
           "input" in guard_out("echo " + "a" * 40, SPEND_GUARD_BYTES="20"), True)
# A Read payload is tiny on the wire; the file it names is not.
check_same("live: a whole-file Read of a big file warns", "read whole" in guard_out(
    payload={"tool_name": "Read",
             "tool_input": {"file_path": os.path.join(HERE, "spend.py")},
             "cwd": HERE}), True)
# The payload is attacker-adjacent data -- it is whatever the model just wrote.
# `p=$(cat)` and `printf %s "$p"` must never re-expand it. If either loses its
# quoting, this substitution runs and the marker appears.
_marker = os.path.join(tempfile.mkdtemp(), "expanded")
guard_out("echo '`touch %s`$(touch %s)' %s" % (_marker, _marker, "b" * 40),
          SPEND_GUARD_BYTES="20")
check_same("live: a payload is never re-expanded by the hook shell",
           os.path.exists(_marker), False)

for path in _tmp:
    try:
        os.unlink(path)
    except OSError:
        pass

print()
if FAILURES:
    print("  %d FAILURE(S): %s" % (len(FAILURES), ", ".join(FAILURES)))
    sys.exit(1)
print("  all pass")
