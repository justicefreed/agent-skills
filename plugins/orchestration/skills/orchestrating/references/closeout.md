# Closeout — commits, provenance, and reclaiming resources

Closing a dispatch has four steps. Skipping the third is how a program ends with results nobody can
find; skipping the fourth is how a machine fills up.

## 1. Commit with explicit paths

**Whenever any worker is live, commit named paths — never everything.** Staging every change succeeds
regardless of who else wrote to the tree, which is precisely why it is dangerous: it has twice swept
a running worker's unstaged work into an unrelated commit, and it cannot fail in a way that warns
you.

The lane's worker does not commit its own landing. The decision about what belongs in history, and
in what order, stays with the orchestrator — it is the only agent that knows what else is in flight.

**Authority and labor are separable, and only authority is yours.** Performing the merge, resolving
the conflict and staging the paths is the integrator lane's job (`integration.md`); ruling on order
and inclusion is yours. An orchestrator that does both has quietly become the most expensive
integrator available, and it is unreachable for the duration.

**Ordering rule for paired updates:** patch the **source of truth first**, then any derived or
presentational copy, then any revision marker. Doing it the other way round produced an inconsistent
pair of files once. Generalised: when two artifacts must agree, write the authoritative one first, so
an interruption leaves a recoverable state rather than a contradiction.

## 2. Verify before believing

Apply `verification.md` to the worker's own claims, not just to its output. In particular: a worker
that was interrupted will not tell you it abandoned work — check the progress artifact reaches its
target.

## 3. Graduate the provenance

The tracker is a **working set**, not a record of what happened. Before deleting an entry, move what
matters into the repository:

- **what was commissioned, under what constraints** — into the work's detail document or commit
  message;
- **what it produced** — identifiers, artifacts;
- **what was ruled about the result** — into the plan document, at the moment it is ruled.

A ruling that lives only in conversation is the defect. It is the one class of state that cannot be
re-derived from anywhere, and it is why an end-of-session summary feels necessary — materialise
rulings as they happen and the need evaporates.

Briefs are inputs and do **not** graduate; the detail document quotes whichever constraints turned
out to matter. Copying both duplicates the same facts in two places, which is the drift mechanism
this whole design avoids.

## 4. Close the entry, then reclaim

```bash
orch close e1 --consumed "landed as <id>; review doc written; plan rows updated"
```

`--consumed` is required. **An entry you cannot describe as consumed is an output nobody used** —
that is a finding, not paperwork. Resist the temptation to close it anyway.

**Delete any wake the close just orphaned, here.** `close` names them. A heartbeat set to catch a
lost finish-notification has nothing to insure the moment its last lane stops running, and every
firing after that is a no-change tick that only looks wasteful from outside the turn. Delete it at
the substrate, then `orch wake clear --id <id>`. `liveness.md` has the rule and the escape hatch for
a wake that genuinely watches something the tracker cannot see.

Then reclaim what the lane held.

**Archive the lane's container first, if the substrate gave it one.** `close` names it, the same way
it names an orphaned wake, and for the same reason: this is the last moment an agent is reliably
looking. One call takes the lane's agents, its terminals and its worktree together — delete the
worktree by hand instead and the agents survive it, still listed, still asking the human to review
work that was never theirs to review. Steps 1 and 2 are what make this safe to do: archiving keeps
the branch and not the uncommitted tree, so a lane whose work is committed and verified loses
nothing. `close` can only name a container that was recorded, so record it at dispatch:
`orch update <e> --workspace-id <id>`. Substrate semantics — and why there is no "mark as reviewed"
to reach for instead — in `substrates/paseo.md`.

Then the rest:

- **Delete by explicit name, never by glob.** A glob in a shared cache directory takes out sibling
  lanes' work. Name each path.
- **Never while any build is running anywhere.** Check the system, not your notes.
- **Keep what is still needed** — anything still landing, awaiting re-verification, or belonging to
  a human's own checkout. Maintain an explicit never-touch list in the project's standing-rules file.
- **Re-inventory before deleting.** Something may already be gone, or newly in use, since you last
  looked. Deleting from a stale inventory is how the wrong thing goes.

Worktrees, build caches, and temporary state each accumulate independently — reclaiming one does not
reclaim the others, and each has its own never-touch list.

## 5. Tearing down a worker that shares infrastructure

**Never terminate processes by pattern.** A pattern broad enough to catch a worker's toolchain is
broad enough to catch a sibling lane's, and your own shell. Terminate by process id, or by process
group, filtered to the specific worktree.

## When the whole program ends

- Every entry closed, so the tracker directory holds no open work.
- Every wake deleted at the substrate, so `orch wake list` is empty. A program with no lanes and a
  live heartbeat is a loop with no one left to notice it.
- Provenance in the repository; the plan document current.
- Resources reclaimed by explicit name.
- The tracker itself may be left — it is machine-local, bounded, and cheap. `orch prune` clears
  entries whose agents are gone if it was left untidy.

No final summary document is required, and writing one is usually a signal that steps 3 and 4 were
skipped along the way.
