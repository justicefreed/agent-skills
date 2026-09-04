# Liveness — knowing what is actually running

Two rules that look contradictory and are not:

- **Do not poll to wait.** Notifications exist; a poll loop burns tokens and adds nothing.
- **Do reconcile on resume.** A notification may have been delivered into a context that no longer
  exists, so its absence proves nothing.

The discriminator is **whether a notification could have been lost.** Waiting on a healthy worker in
a live session: trust the notification. Picking up after an interrupt, a compaction, or as a fresh
orchestrator: reconcile, because you may have missed it.

## The three-tier check, in order

Use it on resume, after a failed heartbeat, or before an action that assumes a worker's state — never
on a timer.

1. **The tracker** — what you *believe* is in flight. Recorded intent, not liveness. `orch roster`
   says so in its own output.
2. **The substrate** — its agent listing and status. Authoritative for "does this worker exist and
   what is its lifecycle state."
3. **The operating system and the disk** — live processes, worktree and artifact mtimes.

Tier 2 outranks tier 1, and tier 3 outranks tier 2. An agent the substrate reports as gone may have
left a live build process behind; a worker the substrate reports as running may have produced nothing
for an hour. **Absence from a status API is not proof of death** — check for live processes before
replacing a worker, or you will end up with two.

## Heartbeats are the insurance, not the mechanism

Set a recurring prompt back to yourself when work is long-running and you have nothing else to do.
Its purpose is to catch the case where a notification never arrives — not to check on progress.

Distinguish the two recurring primitives: one prompts **you** on a cadence (a heartbeat); the other
spawns a **fresh worker** per firing (a schedule). Reaching for the second when you wanted the first
silently multiplies workers.

## Global resources are checked against the system

A capacity gate — "no second heavyweight build anywhere", "one writer per worktree" — is enforced by
querying the operating system, never by reading the tracker and never by trusting a peer's claim.
Two failure modes to avoid:

- **Gating on a pattern that matches yourself**, or that matches stale wrapper processes which never
  exit. The gate then never clears, or clears while work is still running. Match the *actual*
  worker process, and verify the pattern against a known-busy and a known-idle state.
- **Gating on recorded state.** A tracker entry says what was commissioned, not what is executing.

## Signals worth acting on

| Observation | Means |
|---|---|
| entry flagged `NO-AGENT-ID`, minutes old | the spawn may have failed, or its id was never recorded — reconcile against the substrate before re-spawning |
| worker reports "standing by" mid-task | stalled, not working. Nudging is safe *only* because it is already idle — see `messaging.md`. The worker-side rule against reporting in-progress as finished is in `briefs.md` → "When you may report"; if a worker does it anyway, its brief was missing that clause |
| worker idle, progress artifact short of its target | it stopped early, or was interrupted. Its own report will not say so |
| idle→running you did not cause | someone else is driving. Stand down rather than contend |
| build exits 137/143 with no compiler error | resource kill, not a code failure. Retry sequentially; do not bisect it |

That last one generalises: **before treating an infrastructure failure as a defect in the work, rule
out the environment.** Concurrency and memory pressure produce failures that look like bugs and
waste entire dispatches when misread.
