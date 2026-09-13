# Rotation — replacing a live orchestrator without leaving two behind

Compaction is the routine rotation and needs none of this (`cost.md`). **Rotation** is the other
kind: a *new agent* on a handoff note, for when the context is too polluted for a summary to save,
when a summary has already gone wrong, or when the human wants a different model driving.

It is the one procedure in this skill where the agent performing it cannot verify its own last step,
and that single fact determines the whole design.

## The two things that go wrong, and why

**A predecessor cannot close itself.** `CLOSE` interrupts the turn that calls it. An agent that
archives itself never reaches the next line, so it can neither confirm the archive worked nor react
if it did not. Every "spawn a successor then archive yourself" instruction is therefore an
instruction to *maybe* archive yourself, and the observed failure — a fresh agent running beside a
predecessor that never went away — is what that looks like in practice.

**Inbox claims are keyed by worktree, not by role.** `_worktree_key` is the realpath of the git
toplevel (`availability.md`). A successor spawned in a *different* worktree that runs `orch inbox
claim --as root --force` does not take the inbox over — it adds a second claim on the same target.
Both agents then drain it, each getting whichever items it reached first. This is worse than a
missed handoff, because nothing errors and each half looks correct from the inside.

Both are fixed by inverting ownership: **the successor closes the predecessor**, and the transfer is
one tool-mediated act rather than two independent claims.

## The protocol

Five commands. The tool prints the next step at each stage, so this section is the shape, not a
script to retype.

| Step | Who | Command |
|---|---|---|
| 1 | predecessor | `orch rotate begin --handoff <path> --agent-id <your own id>` |
| 2 | predecessor | SPAWN the successor, same worktree, with the printed prompt verbatim |
| 3 | successor | `orch rotate claim` |
| 4 | successor | `CLOSE <predecessor id>` |
| 5 | successor | `orch rotate complete --alive <live ids>` |

`begin` requires the handoff note to already exist and be non-empty, and requires **your own agent
id** — that id is the only thing that lets the successor close the right agent, and you are the only
one who reliably knows it. It then prints the successor's first-turn instructions; paste them
verbatim rather than paraphrasing, because steps 3–5 are refusals waiting to happen if reordered.

Before `begin`, do the two things a handoff note cannot do for you: land and close what is finished,
and patch the plan document with anything ruled but not written down.

**After spawning, stop.** Not "then archive yourself" — see above.

`claim` is the transfer. It refuses when the successor is not in the predecessor's worktree, and on
success **deletes every other worktree's claim on that target in the same write**, so a split inbox
is not a reachable state. It reports what is still queued; the log and cursor never move, so nothing
in flight is lost. Never hand-run `orch inbox claim` to take over — that is the duplicate-claim bug.

`complete` demands the live agent set and **refuses while the predecessor is in it**. That refusal
is the whole point of the step: it is the only moment in the procedure where a human-visible error
appears if the close silently failed.

## Replay-envelope recovery

A `cursor_root_envelope_limit` is a durable replay-root size failure, not a token-window
diagnosis. At the observed 524,288 serialized-byte boundary, stop growing that root. Write the
progress artifact, including the last completed milestone and the next safe action, then rotate
or compact at a seam. A fresh root may continue from the artifact; do not replay the failed
prompt merely because the transport did not report completion.

A `cursor_blob_capacity` is a transient, shared capacity failure. Keep the existing root and
progress artifact, use the substrate's ordinary backoff, and retry only a read-only operation
after capacity recovery. It is not a reason to recursively rotate or spawn a replacement. If
the failed operation could have caused an external mutation, pause replay and reconcile the
provider state first. Record `applied`, `not applied`, or `unknown`; only the first two permit a
deterministic next action.

For either class, recovery is complete when the durable artifact can reconstruct the last known
state and the next action is safe. If the error is ambiguous, preserve the artifact and escalate
instead of guessing. Never automatically replay a mutation with an uncertain outcome.

## When it is not clean

| Situation | What to do |
|---|---|
| The successor is in a different worktree and cannot move | Close the predecessor **first**, then `orch rotate claim --force-different-worktree` |
| The predecessor is already gone (crashed, killed) | `orch rotate complete --assume-none-alive` |
| A stale record blocks a new rotation | `orch rotate begin --force`, or `orch rotate abort` to drop it |
| You do not know what is in flight | `orch rotate status` — exit 3 means nothing is |

A rotation left pending past ten minutes (`ORCH_ROTATION_STALE`) raises an advisory on the turn-end
hook, in the *successor's* session, naming the predecessor's id and the command still owed. That is
the dangling-session detector: a rotation nobody finished stops being invisible.

`orch resume` prints any pending rotation with its outstanding steps, so a successor that compacts
mid-rotation recovers the obligation from disk rather than from the summary.

## Same tab

The human's request is that the replacement appear where the old agent was. There is no
replace-in-place API on any substrate here, so "same tab" resolves to **same workspace, same
worktree** — which is also exactly the precondition for the inbox transfer. Conveniently, an
agent-scoped `create_agent` defaults to the caller's own workspace, so the correct thing is the
default thing; see `substrates/paseo.md` for the ROTATE verb. The old tab disappears at step 4 and
the new one is already beside it.

Front-desk-driven rotation (the human never talks to the orchestrator directly) is the same protocol
with the relay in front of it: `frontdesk.md`.
