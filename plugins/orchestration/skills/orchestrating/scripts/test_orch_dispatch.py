#!/usr/bin/env python3
"""Pin the dispatch decision: the archetype sets the rung, and the spawn honours it.

Run: python3 test_orch_dispatch.py

One program opened every lane a rung above its archetype -- copied from the
previous brief, justified after the fact -- and spawned each on the provider
default, which happened to be that rung, so nothing ever looked wrong. Each
block below is one of the gaps that let it happen:

  1. The archetype is required and decides the start; above it is an
     escalation that needs a signal and a checkable pointer to its evidence.
  2. `open` resolves the rung to exact models, and a reviewer's exclude the
     author's whole lineage.
  3. Escalation has a scope: a task-scope one carries to a fresh lane from the
     same brief, an attempt-scope one does not.
  4. The spawn guard refuses a spawn or RETUNE that does not match the entry,
     and counts follow-up rounds.

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
# This test intentionally opens many unrelated entries to exercise the model
# matrix; admission-limit behavior is tested independently.
os.environ.setdefault("ORCH_FANOUT_MAX", "100")
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
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = orch.main(["--repo", repo, command] + list(rest))
    return code, out.getvalue(), err.getvalue()


def hook(repo, tool, tool_input):
    """Run the spawn guard on one PreToolUse payload; its decision, or None."""
    orch._HOOK_PAYLOAD = {"tool_name": tool, "tool_input": tool_input, "cwd": repo}
    orch._HOOK_PAYLOAD_READ = True
    try:
        code, out, err = run(repo, "spawn-guard")
    finally:
        orch._HOOK_PAYLOAD, orch._HOOK_PAYLOAD_READ = None, False
    if not out.strip():
        return None
    return json.loads(out)["hookSpecificOutput"]


def denied(decision):
    return bool(decision) and decision.get("permissionDecision") == "deny"


def make_repo():
    root = tempfile.mkdtemp(prefix="orch-dispatch-")
    subprocess.run(["git", "init", "-q", root], check=True)
    return root


def write_brief(root, name="brief.md", **fields):
    lines = ["title: dispatch test", "worktree: %s" % root,
             "expected_artifacts:", "  - out.txt", "advances: none",
             "consumption: this test reads it"]
    lines += ["%s: %s" % (key, value) for key, value in fields.items()]
    path = os.path.join(root, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("---\n%s\n---\n\n# body\n" % "\n".join(lines))
    return path


def entry(root, ref):
    repo_key, _, _ = orch.repo_identity(root)
    program = orch.resolve_program(repo_key, None)
    data = orch.load_tracker(orch.tracker_path(repo_key, program, "root"))
    return orch.find_entry(data, ref)


# --------------------------------------------------------------------------- #
# 1. The archetype decides the start.
# --------------------------------------------------------------------------- #

root = make_repo()
code, out, err = run(root, "open", "--brief", write_brief(root, "none.md"))
check_true("a brief without an archetype is refused",
           code != 0 and "archetype" in err)
code, out, err = run(root, "open", "--brief",
                     write_brief(root, "odd.md", archetype="wizard"))
check_true("an archetype outside the catalogue is refused, naming the catalogue",
           code != 0 and "implementer" in err)

code, out, err = run(root, "open", "--brief",
                     write_brief(root, "impl.md", archetype="implementer"))
e_impl = out.strip()
check_same("an implementer with no model starts at economy",
           entry(root, e_impl)["model"], "economy")
check_same("and at the archetype's relative effort",
           entry(root, e_impl)["effort"], "default")
check_true("open resolves the rung to exact models",
           "claude-sonnet-5" in entry(root, e_impl)["resolved_models"])
check_same("an unannotated lane receives a persisted bounded contract",
           entry(root, e_impl)["limits"],
           {"max_model_calls": 40, "max_context_tokens": 150000,
            "max_cost_usd": 8.0, "checkpoint_every_calls": 20,
            "slice_id": "unsliced", "read_set": [], "write_set": []})
check_true("open prints the models and the label to spawn with",
           "claude-sonnet-5" in err and '"orch_entry": "%s"' % e_impl in err)
check_true("the resolution never offers a model above the rung",
           "claude-opus-5-5" not in entry(root, e_impl)["resolved_models"])

code, out, err = run(root, "open", "--brief",
                     write_brief(root, "copied.md", archetype="implementer",
                                 model="advanced"))
check_true("a rung copied into the brief above the start is refused",
           code != 0 and "escalation" in err)
code, out, err = run(root, "open", "--brief",
                     write_brief(root, "copied2.md", archetype="implementer",
                                 model="advanced"),
                     "--model-reason", "large network-state change")
check_true("a reason without evidence is still refused",
           code != 0 and "--evidence" in err)
code, out, err = run(root, "open", "--brief",
                     write_brief(root, "copied3.md", archetype="implementer",
                                 model="advanced"),
                     "--model-reason", "spans subsystems",
                     "--evidence", "field:subsystems")
check_true("evidence pointing at a brief field that is absent is refused",
           code != 0 and "subsystems" in err)
code, out, err = run(root, "open", "--brief",
                     write_brief(root, "copied4.md", archetype="implementer",
                                 model="advanced"),
                     "--model-reason", "spans subsystems",
                     "--evidence", "/nonexistent/report.md")
check_true("evidence naming a path that does not exist is refused",
           code != 0 and "neither" in err)

brief_wide = write_brief(root, "wide.md", archetype="implementer", model="advanced",
                         subsystems="[configurator, network state, persistence]")
code, out, err = run(root, "open", "--brief", brief_wide, "--model-reason",
                     "the change spans three subsystems",
                     "--evidence", "field:subsystems")
e_wide = out.strip()
check_same("a pre-dispatch escalation with named evidence opens", code, 0)
check_true("it resolves to advanced models only",
           entry(root, e_wide)["resolved_models"][0] == "claude-opus-5-5")
repo_key, _, _ = orch.repo_identity(root)
program = orch.resolve_program(repo_key, None)
log = orch.load_escalations(repo_key, program)
check_same("and it is in the escalation log, at open, task scope, with evidence",
           [(r["entry"], r["at_open"], r["scope"], r["evidence"]) for r in log],
           [(e_wide, True, "task", "field:subsystems")])
check_true("the roster names the tier and that it was justified",
           "TIER:advanced" in orch.entry_summary(entry(root, e_wide))
           and "NO-REASON" not in orch.entry_summary(entry(root, e_wide)))

code, out, err = run(root, "open", "--brief",
                     write_brief(root, "effort.md", archetype="verifier",
                                 effort="above-default"))
check_true("an effort above the archetype's is an escalation too",
           code != 0 and "effort above-default" in err)
code, out, err = run(root, "open", "--brief",
                     write_brief(root, "ver.md", archetype="verification"))
check_same("aliases resolve, and the verifier starts one below default",
           (entry(root, out.strip())["archetype"], entry(root, out.strip())["effort"]),
           ("verifier", "one-below-default"))
code, out, err = run(root, "open", "--brief",
                     write_brief(root, "long.md", archetype="implementer"),
                     "--long-context")
check_true("a long-context lane is an escalation",
           code != 0 and "long-context" in err)

# --------------------------------------------------------------------------- #
# 2. A reviewer comes from a different lineage than its author.
# --------------------------------------------------------------------------- #

code, out, err = run(root, "open", "--brief",
                     write_brief(root, "rev0.md", archetype="reviewer"))
check_true("a reviewer with no author is refused",
           code != 0 and "author_family" in err)
code, out, err = run(root, "open", "--brief",
                     write_brief(root, "rev1.md", archetype="adversarial-reviewer",
                                 author_family="claude-opus"))
rev = entry(root, out.strip())
check_same("a reviewer excludes the author's whole lineage",
           [m for m in rev["resolved_models"] if m.startswith("claude-")], [])
check_true("and still resolves at economy", "gpt-5.6-terra" in rev["resolved_models"])

hook(root, "mcp__paseo__create_agent",
     {"title": "w", "initialPrompt": "go", "provider": "claude/claude-sonnet-5",
      "labels": {"orch_entry": e_impl}, "settings": {"modeId": "auto"}})
code, out, err = run(root, "open", "--brief",
                     write_brief(root, "rev2.md", archetype="reviewer", reviews=e_impl))
check_same("`reviews: <entry>` takes the author from what that lane spawned",
           entry(root, out.strip())["exclude_lineages"], ["claude"])
code, out, err = run(root, "open", "--brief",
                     write_brief(root, "rev3.md", archetype="reviewer"),
                     "--same-family-ok", "only claude reachable here")
check_true("--same-family-ok waives it and the roster says so",
           code == 0 and "SAME-FAMILY" in orch.entry_summary(entry(root, out.strip())))

# --------------------------------------------------------------------------- #
# 3. Escalation scope.
# --------------------------------------------------------------------------- #

root2 = make_repo()
brief2 = write_brief(root2, "lane.md", archetype="implementer")
e1 = run(root2, "open", "--brief", brief2)[1].strip()
code, out, err = run(root2, "escalate", e1, "--to", "advanced",
                     "--reason", "first pass came back with the scope wrong",
                     "--evidence", "entry:%s" % e1)
check_true("escalate without --scope is refused", code != 0 and "--scope" in err)
code, out, err = run(root2, "escalate", e1, "--to", "advanced", "--scope", "attempt",
                     "--reason", "first pass came back with the scope wrong")
check_true("escalate without --evidence is refused", code != 0 and "--evidence" in err)
code, out, err = run(root2, "escalate", e1, "--to", "advanced", "--scope", "attempt",
                     "--reason", "first pass came back with the scope wrong",
                     "--evidence", "entry:%s" % e1)
check_same("an attempt-scope escalation records", code, 0)
check_same("and re-resolves the lane's models to the new rung",
           entry(root2, e1)["resolved_models"][0], "claude-opus-5-5")
code, out, err = run(root2, "open", "--brief",
                     write_brief(root2, "lane.md", archetype="implementer", model="advanced"))
check_true("an attempt-scope escalation does not carry to a fresh lane",
           code != 0)
run(root2, "escalate", e1, "--effort", "above-default", "--scope", "task",
    "--reason", "the argument is many hops deep", "--evidence", "entry:%s" % e1)
code, out, err = run(root2, "open", "--brief",
                     write_brief(root2, "lane.md", archetype="implementer",
                                 effort="above-default"))
check_same("a task-scope escalation carries to a fresh lane from the same brief",
           code, 0)
check_true("with the carried reason on record",
           "carried from" in (entry(root2, out.strip())["model_reason"] or ""))

# --------------------------------------------------------------------------- #
# 4. The spawn guard.
# --------------------------------------------------------------------------- #

root3 = make_repo()
e3 = run(root3, "open", "--brief", write_brief(root3, "g.md", archetype="implementer"))[1].strip()
spawn = {"title": "w", "initialPrompt": "go", "settings": {"modeId": "auto"}}

check_true("an unlabelled spawn is refused while an entry is pending",
           denied(hook(root3, "mcp__paseo__create_agent",
                       dict(spawn, provider="claude/claude-sonnet-5"))))
check_same("an agent labelled as not a lane is allowed",
           hook(root3, "mcp__paseo__create_agent",
                dict(spawn, provider="claude/claude-opus-5-5",
                     labels={"orch_entry": "none"})), None)
check_true("the provider default for an economy lane is refused",
           denied(hook(root3, "mcp__paseo__create_agent",
                       dict(spawn, provider="claude/claude-opus-5-5",
                            labels={"orch_entry": e3}))))
check_true("an alias is refused, because what it names drifts",
           denied(hook(root3, "mcp__paseo__create_agent",
                       dict(spawn, provider="claude/sonnet", labels={"orch_entry": e3}))))
check_true("a spawn with no mode is refused",
           denied(hook(root3, "mcp__paseo__create_agent",
                       {"title": "w", "initialPrompt": "go",
                        "provider": "claude/claude-sonnet-5",
                        "labels": {"orch_entry": e3}})))
check_true("a long-context variant is refused without its escalation",
           denied(hook(root3, "mcp__paseo__create_agent",
                       dict(spawn, provider="claude/claude-sonnet-5[1m]",
                            labels={"orch_entry": e3}))))
check_same("the resolved model, labelled, in the recorded mode, is allowed",
           hook(root3, "mcp__paseo__create_agent",
                dict(spawn, provider="claude/claude-sonnet-5",
                     labels={"orch_entry": e3})), None)
check_same("and what was spawned is recorded on the entry",
           entry(root3, e3)["spawned_model"], "claude-sonnet-5")

run(root3, "update", e3, "--agent-id", "agent-3")
_cleared = hook(root3, "mcp__paseo__update_agent",
                {"agentId": "agent-3", "settings": {"model": None}})
check_true("a RETUNE that clears the model onto the provider default is refused",
           denied(_cleared) and "provider default" in _cleared["permissionDecisionReason"])
check_true("a RETUNE above the recorded rung is refused",
           denied(hook(root3, "mcp__paseo__update_agent",
                       {"agentId": "agent-3", "settings": {"model": "claude-opus-5-5"}})))
run(root3, "escalate", e3, "--to", "advanced", "--scope", "attempt",
    "--reason", "guard cannot be made to go red", "--evidence", "entry:%s" % e3)
check_same("after `orch escalate` the same RETUNE is allowed",
           hook(root3, "mcp__paseo__update_agent",
                {"agentId": "agent-3", "settings": {"model": "claude-opus-5-5"}}), None)

advice = [hook(root3, "mcp__paseo__send_agent_prompt",
               {"agentId": "agent-3", "prompt": "round"})
          for _ in range(orch.LANE_ROUNDS_MAX + 1)]
check_same("follow-up rounds within the limit are silent",
           advice[:orch.LANE_ROUNDS_MAX], [None] * orch.LANE_ROUNDS_MAX)
check_true("the round past the limit advises a fresh agent, without blocking",
           advice[-1] and not denied(advice[-1])
           and "fresh agent" in advice[-1]["additionalContext"])
check_true("and the roster counts the rounds",
           "ROUNDS:%d" % (orch.LANE_ROUNDS_MAX + 1) in orch.entry_summary(entry(root3, e3)))

e4 = run(root3, "open", "--brief", write_brief(root3, "o.md", archetype="doc-writer"))[1].strip()
check_same("an override label lets a mismatched spawn through",
           hook(root3, "mcp__paseo__create_agent",
                dict(spawn, provider="claude/claude-opus-5-5",
                     labels={"orch_entry": e4, "orch_override": "haiku is down"})), None)
check_true("and the roster flags both the override and the mismatch",
           "SPAWN-OVERRIDE" in orch.entry_summary(entry(root3, e4))
           and "TIER-MISMATCH:claude-opus-5-5" in orch.entry_summary(entry(root3, e4)))

e5 = run(root3, "open", "--brief", write_brief(root3, "m.md", archetype="implementer"))[1].strip()
run(root3, "update", e5, "--spawned-model", "claude-opus-5-5")
check_true("--spawned-model records a spawn no hook saw, and the roster compares it",
           "TIER-MISMATCH:claude-opus-5-5" in orch.entry_summary(entry(root3, e5)))

# --------------------------------------------------------------------------- #
# 5. Claude Code's native subagents: no labels, so the entry rides in the prompt.
# --------------------------------------------------------------------------- #

_agents = tempfile.mkdtemp(prefix="orch-agents-")
for _name, _model in (("claude-sonnet-5", "claude-sonnet-5"),
                      ("claude-opus-5-5", "claude-opus-5-5"),
                      ("inherits", "inherit")):
    with open(os.path.join(_agents, _name + ".md"), "w") as fh:
        fh.write('---\nname: "%s"\ndescription: "t"\nmodel: "%s"\n---\n' % (_name, _model))
_env_saved = {k: os.environ.get(k) for k in ("ORCH_AGENTS_DIR", "CLAUDECODE")}
os.environ["ORCH_AGENTS_DIR"] = _agents
os.environ["CLAUDECODE"] = "1"
try:
    root4 = make_repo()
    code, out, err = run(root4, "open", "--brief",
                         write_brief(root4, "a.md", archetype="implementer"))
    e6 = out.strip()
    check_true("under Claude Code, open prints the subagent_type and prompt marker",
               "subagent_type claude-sonnet-5" in err and "`orch_entry: %s`" % e6 in err)

    def agent(**tool_input):
        tool_input.setdefault("description", "lane")
        return hook(root4, "Agent", tool_input)

    marked = "orch_entry: %s\nDo the work in the brief." % e6
    check_true("a subagent naming no entry is refused while one is pending",
               denied(agent(prompt="do the work", subagent_type="claude-sonnet-5")))
    check_same("a subagent marked `orch_entry: none` is allowed",
               agent(prompt="orch_entry: none\nlook something up"), None)
    _inherit = agent(prompt=marked)
    check_true("a lane subagent with no model inherits the session's, and is refused",
               denied(_inherit) and "inherits" in _inherit["permissionDecisionReason"])
    check_true("the refusal names what to spawn with instead",
               "subagent_type claude-sonnet-5" in _inherit["permissionDecisionReason"])
    check_true("an agent type that pins no model is refused the same way",
               denied(agent(prompt=marked, subagent_type="inherits")))
    check_true("an agent definition on the wrong rung is refused",
               denied(agent(prompt=marked, subagent_type="claude-opus-5-5")))
    check_true("the `opus` alias is refused for an economy lane",
               denied(agent(prompt=marked, model="opus")))
    check_same("the agent definition for the resolved model is allowed",
               agent(prompt=marked, subagent_type="claude-sonnet-5"), None)
    check_same("and the spawn is recorded, via the Agent tool",
               (entry(root4, e6)["spawned_model"], entry(root4, e6)["spawned_via"]),
               ("claude-sonnet-5", "agent-tool"))
    check_same("a spawned lane no longer counts as pending for the next subagent",
               hook(root4, "Agent", {"description": "x", "prompt": "unrelated"}), None)

    e7 = run(root4, "open", "--brief",
             write_brief(root4, "b.md", archetype="implementer"))[1].strip()
    check_same("an override line in the prompt lets a mismatch through",
               agent(prompt="orch_entry: %s\norch_override: sonnet quota is out\ngo" % e7,
                     subagent_type="claude-opus-5-5"), None)
    check_true("and the roster shows it",
               "SPAWN-OVERRIDE" in orch.entry_summary(entry(root4, e7)))
finally:
    for _k, _v in _env_saved.items():
        if _v is None:
            os.environ.pop(_k, None)
        else:
            os.environ[_k] = _v

# --------------------------------------------------------------------------- #
# 6. Program budget admission reserves an open lane before it spends.
# --------------------------------------------------------------------------- #

root5 = make_repo()
run(root5, "open", "--brief", write_brief(root5, "first.md", archetype="implementer"))
run(root5, "budget", "--set", "10")
code, out, err = run(root5, "open", "--brief",
                     write_brief(root5, "second.md", archetype="implementer"))
check_true("a second lane is refused when reservations exceed the budget",
           code != 0 and "budget admission refused" in err)

# A broken tracker must not turn the guard into a wall: exit 2 is a refusal to
# Claude Code, so the guard's own failure has to let the call through.
repo_key3, _, _ = orch.repo_identity(root3)
program3 = orch.resolve_program(repo_key3, None)
with open(orch.tracker_path(repo_key3, program3, "root"), "w") as fh:
    fh.write("{not json")
orch._HOOK_PAYLOAD = {"tool_name": "mcp__paseo__create_agent", "cwd": root3,
                      "tool_input": dict(spawn, provider="claude/claude-opus-5-5",
                                         labels={"orch_entry": e3})}
orch._HOOK_PAYLOAD_READ = True
try:
    code, out, err = run(root3, "spawn-guard")
finally:
    orch._HOOK_PAYLOAD, orch._HOOK_PAYLOAD_READ = None, False
check_same("an unreadable tracker fails open: exit 0, no decision",
           (code, out.strip()), (0, ""))

print()
if FAILURES:
    print("  %d FAILURE(S): %s" % (len(FAILURES), ", ".join(FAILURES)))
    sys.exit(1)
print("  all pass")
