# Adapter — in-harness subagents

The harness's own subagent and session tools. Best for **context isolation** — you want the result,
not the process — and for short-lived work where a fresh restart is cheap.

## Verb map

| Verb | Call | Semantics | Evidence |
|---|---|---|---|
| `SPAWN` | the subagent-launch tool, with a named agent type; `run_in_background` for long work | **does not survive this session ending**; there is no mode parameter — a subagent runs under *your* session's permission mode, so `paseo.md`'s Always Ask trap cannot occur here | documented |
| `ISOLATE` | that tool's `isolation: "worktree"` option | **temporary and auto-cleaned** — enough for isolation, not for human review | documented |
| `POLL` | the peer/agent listing tool; the background-task output tool | listing rows observed to show only `interactive · started Nm ago` — **no busy/idle field**, despite the docs describing one | observed |
| `HARVEST` | the subagent's final report, or its background-task output | the final message is not shown to the user — relay what matters | documented |
| `CLOSE` | the task-stop tool for background work | | documented |
| `ESCALATE` | the message tool addressed to `"main"` | **background subagents only** — so escalation-capable dispatch implies background dispatch | documented |
| `PEER` | the message tool, addressed to a listed peer | **queues and drains at the receiver's next tool round**; race-free | documented |
| `RETUNE` | none | model is fixed at spawn; **no effort dial** — effort comes from the agent definition | documented |
| `WAKE` | the wakeup/cron scheduling tools | | documented |
| `SCHEDULE` | the cron-creation tool | | documented |
| `ROTATE` | **not available for yourself.** A subagent cannot replace its parent, and a session cannot spawn its own successor | a subagent dies with this session, so a "successor" spawned here is not a replacement | documented |

`ROTATE` is the one verb this substrate cannot supply, and the reason is the same one that makes it
second choice in the detection order: its agents do not outlive the session. Rotating an orchestrator
here means the **human** starts a fresh session on the handoff note — so `orch rotate begin` still
applies (write the note, record the rotation), and the new session runs `orch rotate claim` and then
`orch rotate complete --assume-none-alive`, because ending the old session *is* the close. Tell the
human that explicitly; it is a step only they can take. See `../rotation.md`.

## The messaging asymmetry

Peer messaging **queues**, which makes it the safest messaging path available anywhere — N senders
enqueue in order, so there is no race to lose.

But there is a hard limit for subagents: *a subagent's send goes out under its parent session's
address, and any reply is delivered to the parent session's conversation, not to the subagent.* So a
subagent's peer channel is **outbound only**. Genuine sibling-to-sibling dialogue is not available
here; route it through the parent, or use a substrate whose agents are separately addressable.

`"main"` gives background subagents a real upward channel, which is what makes `ESCALATE` work.

Two rules the tools state explicitly and this skill adopts:

- **Never poll in a loop or send "are you done?" messages.** Use the one-shot idle subscription
  instead — available from the main conversation only.
- **Never ask a peer to perform an action denied or blocked in your own session.** A peer doing it
  for you launders the human's permission decision. Route blocked work back to the human.

## Agent Teams — a variant, not a separate substrate

Teammates share this entire tool surface: the same messaging tool addresses them by name, the same
listing tool enumerates them, and the same per-session permission boundary applies. Treat them as
this adapter with one substitution:

| Verb | Teams |
|---|---|
| `SPAWN` | **human-performed.** No model-callable path to create a teammate was found; teammate creation appears to be a host/UI action |
| `ISOLATE` | unverified |
| everything else | as above |

**Documented gap, deliberately not stubbed.** Writing a `SPAWN` row here that has not been verified
would make the detection step route to it, and the failure would then surface mid-dispatch instead
of at detection time. If you establish a model-callable path, add it with the evidence.

## Policy

- **Prefer the durable external substrate when both are available.** Only its workers survive the
  orchestrator's death, and death by context compaction is routine.
- **Use this substrate deliberately for context isolation**: a broad search across many files, a
  summarisation, a bounded review — anything where the file dumps must not enter your window.
- **Run multiple independent subagents in one message** so they execute concurrently.
- **Keep the tracker anyway.** Even for short-lived subagents the discipline pays: an entry with
  `expected_artifacts` is what tells you which dirty files are legitimate when several finish at
  once.
- **A temporary worktree is not a review artifact.** If the human needs to read the branch, this is
  the wrong substrate.
