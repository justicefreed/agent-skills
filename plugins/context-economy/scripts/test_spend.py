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
