# Capability verbs, detection, and path resolution

The spine speaks only in the verbs below. This file defines them, tells you how to pick an adapter,
and holds the harness-specific details the spine deliberately excludes.

## The verbs

| Verb | Meaning | Notes |
|---|---|---|
| `SPAWN` | start a worker on a brief | |
| `ISOLATE` | give a worker its own branch / worktree / workspace | orthogonal to parentage on some substrates |
| `POLL` | determine a worker's true state | see `../liveness.md` — not a wait loop |
| `HARVEST` | collect a worker's final report | |
| `CLOSE` | end a worker and release what it held | |
| `ESCALATE` | worker → parent, out of band, mid-task | the **primary** correction channel |
| `PEER` | worker → sibling | narrow; pre-authorised only; see `../messaging.md` |
| `RETUNE` | change a running worker's model / effort / mode | does **not** change instructions |
| `WAKE` | recurring prompt back to *this* orchestrator | heartbeat semantics |
| `SCHEDULE` | recurring spawn of a *fresh* worker on a cadence | distinct from `WAKE` |

There is deliberately no `NUDGE`. Mid-task instruction of a running worker is not implementable on
any substrate examined — see `../messaging.md` for the evidence. Corrections arrive via `ESCALATE`,
wait for the worker to finish, or destroy work explicitly.

There is also no verb for the **inbox**. Queuing is a filesystem append and a turn-end drain, so it
needs no adapter and is available even under `none.md` — which is why it is the preferred way to get
anything to a busy agent. What *is* substrate-specific is how the drain gets triggered
(`../availability.md`), and an adapter should say which of those paths it supports.

## Detection procedure

Run in order and stop at the first match. Bind exactly one adapter.

1. **Are durable, externally-managed agent-and-workspace tools available** — tools that create an
   agent, create a workspace with worktree isolation, and report agent status, whose agents survive
   this session ending? → bind `paseo.md`.
2. **Are in-harness subagent tools available** — a tool that launches a subagent, optionally in the
   background and optionally in a temporary worktree, plus a way to list and message peer sessions?
   → bind `claude-native.md`.
3. **Neither** → bind `none.md` and execute sequentially, retaining the tracker.

**Prefer 1 over 2 when both are present.** Only substrate 1's workers survive the orchestrator's
death, and orchestrator death by context compaction is a routine event rather than an edge case.

Two cross-cutting facts that survive whichever adapter you bind:

- **Messaging and lifecycle can come from different substrates.** Where substrate 1's workers are
  also addressable as substrate 2's peer sessions, use substrate 1 for lifecycle and substrate 2 for
  messaging — substrate 2's messages queue, substrate 1's replace. Conditions and limits are in
  `../messaging.md`.
- **Record what your adapter cannot do.** An unavailable verb is a plan constraint. If `ISOLATE` is
  unavailable, sequential work is your only safe shape. If `SPAWN` is unavailable, you are not
  orchestrating and should say so rather than pretending.

## Path resolution for bundled scripts

The tracker script lives at `scripts/orch.py` relative to this skill's base directory. How to get
that path depends on the harness:

| Harness | Resolution |
|---|---|
| Claude Code (plugin install) | `${CLAUDE_PLUGIN_ROOT}/skills/orchestrating/scripts/orch.py` |
| Claude Code (`~/.claude/skills` link) | `~/.claude/skills/orchestrating/scripts/orch.py` |
| Codex / `~/.agents/skills` link | `~/.agents/skills/orchestrating/scripts/orch.py` |
| Anything else | the skill base directory the harness announced, plus `scripts/orch.py` |

Verify the path resolves before the first dispatch. A tracker command that silently fails to run
means every subsequent dispatch is unrecorded, which is the one failure this design cannot absorb.

## Adding an adapter

A new adapter is a new file plus one detection branch. It must not require an edit to `SKILL.md` —
if it does, the spine has leaked a substrate assumption and that is the bug to fix first.

An adapter must state, for every verb: the concrete call, its **failure and disruption semantics**
(does it queue, replace, or reject?), and whether that behaviour is **documented, observed, or
assumed**. Never write an adapter row you have not verified; a stub that the detection step routes
to is worse than an absent adapter, because the failure surfaces mid-dispatch instead of at
detection time.
