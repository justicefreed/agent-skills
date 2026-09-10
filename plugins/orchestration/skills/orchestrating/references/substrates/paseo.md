# Adapter — Paseo

**Read the `paseo` skill for the tool surface.** It is maintained by the vendor and covers projects,
workspaces, workspace scripts, agents, profiles, provider discovery, schedules and heartbeats. Do
not restate it here; a duplicated tool table goes stale the first time the API moves.

This file holds only the **delta**: verb mapping, semantics the vendor skill does not state, and
orchestration policy.

## Verb map

| Verb | Call | Semantics | Evidence |
|---|---|---|---|
| `SPAWN` | `create_agent` (`title`, `provider`, `initialPrompt`, `settings`, `workspaceId`) | agent-scoped calls create *your* subagent; omit `workspaceId` for your own workspace | documented |
| `ISOLATE` | `create_workspace` (`isolation: "worktree"`, `mode: branch-off\|checkout-branch\|checkout-pr`) | **placement never changes parentage** — a cross-workspace child is still your subagent | documented |
| `POLL` | `get_agent_status` → `status`, `activeTurn`, `attentionReason` | the only reliable idle/running signal available | observed |
| `HARVEST` | the finish notification's `agent-response`, plus artifacts on disk | | documented |
| `CLOSE` | `archive_agent` | interrupts if running | documented |
| `ESCALATE` | worker → parent; see `../messaging.md` for the safe path | | observed |
| `PEER` | see `../messaging.md`; **default to artifact reads instead** | | observed |
| `RETUNE` | `update_agent` (`settings.model`, `thinkingOptionId`, `modeId`) | changes config on a **running** agent; does not touch instructions | documented |
| `WAKE` | `create_heartbeat` | prompts *you* on a cadence; no update tool — delete and recreate | documented |
| `SCHEDULE` | `create_schedule` | spawns a **fresh** agent per firing | documented |
| `ROTATE` | `create_agent` with `workspaceId` **omitted**, then the successor calls `archive_agent` on you | omitting `workspaceId` places the successor in your own workspace, which is both the same worktree and the same tab strip the human was watching. There is no replace-in-place API | documented |

On `ROTATE`, two Paseo facts do the deciding. `archive_agent` **interrupts if running**, so an agent
that archives itself never reaches its next line and cannot observe the result — the successor must
be the one to call it. And an agent-scoped `create_agent` already defaults to the caller's workspace,
so the correct placement is the default one: pass `initialPrompt` verbatim from `orch rotate begin`
and pass no `workspaceId`. Full order in `../rotation.md`.

## Send semantics — verified by experiment

Three send paths were tested against workers running a 20-step, externally-logged task. Interrupting
prompts were injected mid-task and the log inspected for steps completed afterwards. An
uninterrupted control completed all 20.

| Path | Result | Evidence |
|---|---|---|
| `send_agent_prompt` | **interrupts and replaces.** Task abandoned at step 4; the agent then reported success and went idle | observed |
| `paseo send <id> --no-wait` | **interrupts and replaces.** Task abandoned at step 5. `--no-wait` is caller-side ("return immediately without waiting"), not receiver-side queueing | observed |
| Harness-native peer message | **queues**; drained after the worker's turn ended. All 20 steps completed, *then* the message | observed |

**There is no queue path in Paseo's own send surface.** Desktop-app queueing is implemented
client-side: the app holds the message in its own session store, subscribes to an agent-stopped-
running event, and then performs an ordinary send, guarded against double-drain. It is not a daemon
capability and is not exposed over MCP or the CLI.

Two consequences:

- **A destructive send reports success.** The agent's own report cannot distinguish "did the new
  thing" from "did the new thing and abandoned 15 steps." Only an external artifact reveals it.
- **Deferred send is reproducible, and provider-agnostic.** Hold the message in the tracker
  (`pending_message`) and send it when the finish notification fires. Unlike the native peer-message
  path this works for workers on *any* provider, not just Claude-hosted ones. Drain **one** message
  per notification behind an in-flight guard, and verify after sending that the turn which started
  is yours — there is no atomic send, so a lost race looks exactly like a delivery.

## Inbox drain paths

Paseo-hosted Claude agents get the turn-end hook from this skill's front matter, unchanged — that is
the baseline and needs no Paseo-specific setup. For agents on providers with no turn-end hook, or for
a target sitting idle with no turn coming, install `../../assets/paseo-inbox-plugin/`: a daemon-side
plugin that injects `ORCH_INBOX_TARGET` on session open and drains on `agent.turn_ended`.

The same plugin is also how a Paseo-hosted agent gets an early auto-compact window: it asks
`orch compaction window` at session open and sets `CLAUDE_CODE_AUTO_COMPACT_WINDOW` only for a
long-lived role on a Claude Code provider (`claude`, `claude-cursor`) with a safe measured number.
Nothing else can set that variable — it is read at launch, so no running session can change its own
window. See `../cost.md`.

Two facts about it worth knowing before relying on it. There is **no idle event and no timer** in the
plugin API, so an agent that never takes another turn never drains — the orchestrator must peek on
its behalf. And its pre-delivery settle delay is a mitigation, not a lock: a human message arriving
inside that window can still race it.

## Policy

- **Profiles first.** Call `list_profiles` and read every profile's `notes` before choosing how to
  launch. Materialise the chosen profile into the create call; there is no profile parameter. If no
  profile fits, fall back to `../delegation.md`'s archetype catalog **and tell the user you fell
  back**. A profile is launch configuration only — never record it as a worker's current state,
  because `RETUNE` can have changed it since.
- **Effort dials are provider-dependent.** Anthropic-family models expose thinking options; Cursor-
  hosted models report none. An archetype's "model and effort" collapses to model alone there.
- **Session-name mapping is undocumented.** A worker's agent id does not reveal its harness session
  name, and the mapping is needed for native messaging. Have each worker report its own session name
  in its first message and record it at dispatch.
- **Detach is a human gesture** in the subagents track. A CLI `agent detach` exists, but do not
  encode independence as part of a spawn.
- **One worker per worktree.** Two agents writing one tree corrupts work. `ISOLATE` or serialise.

## Known unknowns

Record these rather than guessing, and update with evidence:

- Whether the desktop client's queued messages survive an app restart.
- Whether a worker can read its own agent id from inside its session (assume **no**; parent-minted
  identifiers are used instead).
- Whether `cancel_agent` followed immediately by a send is race-free against an in-flight tool call.
