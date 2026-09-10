---
name: orchestrating
description: Orchestrate work across multiple agents — decide whether to delegate at all, choose the execution substrate and isolation, pick model and effort, write briefs, track dispatches, land finished work, and verify what comes back. Use when the user wants work fanned out to subagents or run in parallel, wants an agent given its own branch or worktree, is resuming a multi-agent program, is deciding whether a task is worth delegating, needs queued input delivered to a busy agent, wants a cheap front desk between themselves and a running orchestrator, or when another skill needs the delegation and brief-contract rules.
hooks:
  Stop:
    - hooks:
        - type: command
          command: 'for d in "$ORCH_SKILL_DIR" "$CLAUDE_PLUGIN_ROOT/skills/orchestrating" "$HOME/.claude/skills/orchestrating" "$HOME/.agents/skills/orchestrating"; do [ -f "$d/scripts/orch.py" ] && exec python3 "$d/scripts/orch.py" inbox drain --format hook; done; exit 0'
        - type: command
          command: 'for d in "$ORCH_SKILL_DIR" "$CLAUDE_PLUGIN_ROOT/skills/orchestrating" "$HOME/.claude/skills/orchestrating" "$HOME/.agents/skills/orchestrating"; do [ -f "$d/scripts/orch.py" ] && exec python3 "$d/scripts/orch.py" cost --format hook; done; exit 0'
  SessionStart:
    - matcher: "compact|resume"
      hooks:
        - type: command
          command: 'for d in "$ORCH_SKILL_DIR" "$CLAUDE_PLUGIN_ROOT/skills/orchestrating" "$HOME/.claude/skills/orchestrating" "$HOME/.agents/skills/orchestrating"; do [ -f "$d/scripts/orch.py" ] && exec python3 "$d/scripts/orch.py" resume --format hook; done; exit 0'
        - type: command
          command: 'for d in "$ORCH_SKILL_DIR" "$CLAUDE_PLUGIN_ROOT/skills/orchestrating" "$HOME/.claude/skills/orchestrating" "$HOME/.agents/skills/orchestrating"; do [ -f "$d/scripts/orch.py" ] && exec python3 "$d/scripts/orch.py" compaction check --format hook; done; exit 0'
  PreToolUse:
    - matcher: "Write|Edit|Bash"
      hooks:
        - type: command
          command: 'for d in "$ORCH_SKILL_DIR" "$CLAUDE_PLUGIN_ROOT/skills/orchestrating" "$HOME/.claude/skills/orchestrating" "$HOME/.agents/skills/orchestrating"; do [ -f "$d/scripts/orch.py" ] && exec python3 "$d/scripts/orch.py" guard; done; exit 0'
---

# Orchestrating

You are coordinating work that other agents perform. Your scarce resources are **your own context**,
**the human's attention**, and **your own availability** — how long until their next input is acted
on. Everything below exists to spend those three well.

This skill names no tools. It speaks in **capability verbs**; one substrate adapter maps them to
concrete calls. If you find yourself reaching for a specific tool before Step 0 has bound an
adapter, stop — you are about to hard-code the substrate.

## Principles

These six generate most of the rules. When a rule below seems arbitrary, it is one of these.

1. **Persist what cannot be re-derived; re-derive what can.** A stored copy of derivable state is
   not a convenience, it is a liability — it competes with the source of truth and wins on cost.
   Worker liveness is always re-derived. Worker *intent* is always persisted.
2. **Write through, never write back.** Every non-derivable fact becomes durable at the moment it is
   created. The record is a **precondition** of the action, never a follow-up: a spawn that fails
   after its record is recoverable, a record that fails after its spawn leaves an orphan.
3. **Reduce every writer set to one.** One writer per state file, one minter per id namespace, one
   sender per worker. Concurrency here is designed out, not solved.
4. **An unfalsifiable check is worse than no check.** It manufactures confidence. Before believing a
   green, know what would have made it red — and prefer to have seen it red.
5. **Only do what only you can do.** You are the most expensive agent in the program and the only
   one the human can reach. Work that merely *arrived* in your lap — landing a branch, patching a
   document — is work you are badly placed to perform.
6. **Your context is a tax on every remaining step.** It is re-read on every model call: 61% of a
   measured bill, against 3% for reasoning. A large read is a recurring charge, and rotating a
   bloated orchestrator is the cheapest saving available (`references/cost.md`).

## Step 0 — Bind a substrate

Read `references/substrates/_capabilities.md`. Follow its detection procedure and load **exactly
one** adapter. That adapter is now your only source for concrete calls.

Record which adapter you bound and what it cannot do. A verb your substrate lacks is a plan
constraint, not a thing to improvise around.

**Done when:** one adapter is loaded and its unavailable verbs are known.

## Step 1 — Decide whether to delegate at all

Delegate when at least one holds:

- the work wants its own branch, worktree, or reviewable workspace
- the work is genuinely independent and parallelisable
- you want only the *result*, not the process — the work would otherwise pollute your context
- a cheaper model or lower effort can do it without materially worse output

Do it inline when the dispatch costs more than the task — but weigh that against what the work's
residue charges every remaining call, not just the dispatch (`references/delegation.md`).

**Re-ask this question for work that arrives later.** A merge, a fix-up, a document patch — none were
units of work when you planned, so none were ever marked. They surface at intake with your context
already loaded, which is exactly why they get done inline. Route them back through this step; landing
has a standing home in `references/integration.md`.

**Keep turns bounded** so the human stays able to reach you. Rules of thumb, and the exceptions that
justify a long turn, are in `references/availability.md`.

Workers may themselves orchestrate; a decomposing task says so in its brief and gets a recommended
fan-out shape.

See `references/delegation.md` for substrate choice, isolation choice, and the archetype catalog
with model/effort guidance.

**Done when:** each unit of work is marked *delegate* or *do inline*, with a reason.

## Step 2 — Locate or mint program state

Before the first dispatch, find the tracker: run `orch programs` (see the Reference map for the
path). Use a matching program if one exists; otherwise mint one and **notify, do not ask**. `orch`
refuses to guess when others already exist — that is the one place minting warrants an interruption.

A plan document is optional. If one exists, link it and patch it **at the moment a decision is
ruled** — a ruling that lives only in conversation is the defect. If none exists, the plan lives in
session context; say so, and point the human at a handoff skill if they need to transfer it.

Then **claim your inbox** — `orch inbox claim --as root` — so queued input reaches you at the end of
a turn instead of racing your current one. One call, once per program. If the human named a spend
limit, record it with `orch budget --set <usd>` so the warning is measured against their intent
rather than a default.

**Done when:** exactly one program is bound, its plan-document link is set or explicitly absent, and
this worktree's inbox is claimed.

## Step 3 — Compose the dispatch, in this order

**Brief → record → spawn.** Never reorder; see Principle 2.

1. **Write the brief to a file.** Not into the spawn prompt. A file is single-sourced with the
   tracker, survives the worker's own context loss, gives a replacement worker byte-identical
   instructions, and is the only way an interrupted worker can recover its task. Use
   `assets/BRIEF.template.md`; the contract is in `references/briefs.md`. Set `review:` here — who
   reads this lane's diff before it lands is a property of the spec, not a call made later with the
   finished diff in hand (`references/integration.md`).
2. **Record it**, passing the brief so its front matter supplies the required fields rather than you
   restating them. A dispatch the tracker does not know about is undispatched work.
3. **`SPAWN`**, with `ISOLATE` if the work earns its own branch or worktree, and with the session
   mode `orch open` prints. Omitting the mode is not a neutral default: it selects *Always Ask*, and
   a worker nobody is watching then halts on its first tool call. `references/delegation.md`.

Reference the project's standing-rules file; never restate it — repeated prose costs output tokens
every dispatch and goes stale on the first correction.

**Done when:** a brief file exists, a tracker entry exists naming its worker handle, and the worker
is running — in that order.

## Step 4 — While work is in flight

**Liveness.** Notifications are the good path. Heartbeats are the insurance. Explicit
reconciliation is for a failed heartbeat or for re-deriving state from a fresh context — *never* as
a wait loop. Details in `references/liveness.md`.

**Messaging.** Read `references/messaging.md` before sending anything to a running worker. Mid-task
correction does not exist on any substrate: a correction waits, destroys work, or comes from the
worker via `ESCALATE`. Peer questions are usually artifact reads in disguise — ask the filesystem.

**Queued input.** Anything addressed to a busy agent — including you — goes to its inbox and is
drained between turns. Nobody sends; senders append. `references/availability.md`.

**Resources.** Capacity gates are enforced against the operating system, never against a tracker or
a peer's claim.

**Rotate before you are expensive.** Compaction is the rotation mechanism, set to fire early; a
session-start hook re-derives your state from disk afterwards. The turn-end hook warns when context,
fan-out, or a set budget crosses a threshold. Act at a seam: land and close what is finished, patch
the plan document, then compact. `references/cost.md`.

When a summary will not do, `ROTATE` onto a fresh agent — but **never spawn a successor and then
archive yourself.** `CLOSE` interrupts the turn that calls it, so you cannot observe that it worked,
and the inbox does not follow you. Run `orch rotate begin`, spawn what it prints in your own
worktree, and stop; the successor claims the inbox and closes you. `references/rotation.md`.

**Propose a front desk once execution is routine.** The turn-end hook raises `FRONT-DESK` when the
human's own turns have become routing traffic. It fires once; the offer is theirs to accept, and they
can always open you directly. `references/frontdesk.md`.

**Tuning.** `RETUNE` changes a running worker's model or effort without touching its instructions.
It is the only safe way to influence work already underway; prefer starting cheap and escalating.

## Step 5 — Intake

For every returned report:

1. **Read the falsification line.** What would have made this red, and was it observed red? "I could
   not make it fail" is itself the finding — surface it.
2. **Check the claim's provenance.** A number produced in a tree that does not contain the change
   under test is always green. Require the report to state *where* a result came from and whether
   that context could have failed.
3. **Escalate to independent verification** when both hold: the same agent authored the change *and*
   its check, and the change is hard to reverse. Not merely "important."
4. **Hand the landing to the integrator lane**, with the report and the brief's `review:` mode.
   Reading a worker's diff to decide whether it may land is the second reader's job, and the second
   reader need not be you — `references/integration.md`. What stays yours is this list.
5. **Graduate the provenance** — what was commissioned, what it produced, what was ruled — into a
   durable in-repo artifact. Then patch the plan document if a ruling came out of it.

**Done when:** the report's central claim is falsifiable and either falsified or corroborated, its
landing is commissioned or ruled unnecessary, and its provenance lives somewhere durable.

## Step 6 — Closeout

- **Commit with explicit paths** whenever any worker is live. A commit-everything always succeeds,
  including at sweeping up another lane's uncommitted work. You hold the *authority* over what enters
  history and in what order; the integrator does the *labor*.
- **`CLOSE`** the worker, then delete its tracker entry. An entry you cannot delete is an output
  nobody consumed — that is the signal, not a nuisance.
- **Reclaim resources by explicit name, never by glob**, and never while any build is running.

**Done when:** the entry is deleted, provenance is durable, and resources are reclaimed.

## Reference map

Load these on demand, not up front.

| File | When |
|---|---|
| `references/substrates/_capabilities.md` | Step 0, always — verb vocabulary and detection |
| `references/substrates/*.md` | the one adapter Step 0 selects |
| `references/delegation.md` | substrate, isolation, archetype, model and effort |
| `references/availability.md` | bounded turns, and the inbox for queued input |
| `references/cost.md` | what a program actually spends, compaction, hygiene |
| `references/rotation.md` | replacing a live orchestrator without leaving two behind |
| `references/frontdesk.md` | the cheap router between the human and you |
| `references/integration.md` | the standing integrator lane, and who reviews before landing |
| `references/briefs.md` | brief front matter, body, and report contract |
| `references/state.md` | tracker layout, ids, and the `orch` command surface |
| `references/liveness.md` | notifications, heartbeats, reconciliation |
| `references/messaging.md` | what may be sent to a worker, and when |
| `references/verification.md` | the checks-that-cannot-fail catalog |
| `references/closeout.md` | commits, hygiene, resource reclamation |
| `references/statusline.md` | the status surface for the human: status line, Paseo pill |

**Tooling.** Tracker and inbox operations go through `scripts/orch.py`; path resolution per harness
is in `references/substrates/_capabilities.md`. Never edit tracker files by hand — the script's field
enforcement is the point. This skill's front matter registers hooks that drain, advise, re-derive
state, check for a compaction loop and guard large inputs; all are silent when there is nothing to
say. Export `ORCH_SKILL_DIR` if this skill lives somewhere their candidate list does not cover.

**Status for the human.** Do not narrate the roster into chat — it becomes permanent context re-read
on every later turn. `orch statusline` renders it into harness chrome the model never pays for: a
Claude Code status line, or the Paseo pill in `assets/paseo-inbox-plugin/`. Install once per
machine; `references/statusline.md`.

**Project rules.** A repo running a program should carry a standing-rules file holding *its* facts —
build discipline, formatter exclusions, known traps, output-verbosity preferences. Generate it from
`assets/STANDING-RULES.template.md` on first use. Those facts belong to the project, not to this
skill, and briefs reference that file rather than repeating it.
