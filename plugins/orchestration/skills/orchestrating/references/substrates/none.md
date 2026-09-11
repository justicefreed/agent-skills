# Adapter — none (no delegation available)

No agent-spawning capability is present. You are not orchestrating; say so plainly rather than
implying work is running elsewhere.

## Verb map

| Verb | Available | Degradation |
|---|---|---|
| `SPAWN` | no | execute the work yourself, **one unit at a time, in dependency order** |
| `ISOLATE` | partially | you can still create a git branch or worktree and work in it sequentially |
| `POLL` `ESCALATE` `PEER` `RETUNE` `WAKE` `SCHEDULE` | no | not applicable — there is no second agent |
| `HARVEST` | n/a | the work's output is in front of you |
| `CLOSE` | yes | close the tracker entry as usual |
| `RECLAIM` | n/a | nothing created a container, so nothing owns one. A branch or worktree you made yourself is yours to delete by name |

## Keep the tracker anyway

This is the part worth insisting on. Most of the value of the dispatch discipline is **not** about
coordinating agents:

- **A unit of work recorded before it starts is recoverable** if your context is lost mid-way — and
  context loss is the failure mode that does not require a second agent.
- **`expected_artifacts` still tells you which uncommitted files belong to which unit**, which is
  what keeps a commit scoped.
- **`consumption` is still the delete condition**, so "I finished something and nobody used it"
  remains visible instead of silent.
- **`advances` still joins to the plan**, so progress survives the session.

So: write the brief file, `orch open` it, do the work, verify it, graduate the provenance,
`orch close --consumed`. The only thing missing is the parallelism.

## What still applies in full

- **The brief as a file.** Here it is a note to your future self after a compaction, which is the
  same purpose it serves for a worker.
- **The falsification discipline.** `verification.md` is entirely substrate-independent, and it is
  where most of this skill's value lives. Doing the work yourself removes none of the ways a check
  can fail to be a check — if anything it removes the second pair of eyes.
- **Write-through.** Materialise rulings when ruled; patch the plan document as you go.
- **Closeout hygiene.** Explicit-path commits, explicit-name resource reclamation.

## What to tell the human

If they asked for work to be fanned out and this adapter is what you bound, say so up front, name
what is missing, and offer the sequential plan with an honest ordering. Do not silently serialise
work that was requested in parallel — the schedule implication is theirs to accept.
