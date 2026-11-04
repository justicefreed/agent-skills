# Briefs and the report contract

A brief is a **file**, never inline prompt text. Four things follow from that, and the last two were
not the reason for the decision:

1. Its front matter single-sources the tracker's required fields, so they are recorded rather than
   restated.
2. A nudge, a re-dispatch, or a replacement worker costs nothing to instruct — no retyping, and
   byte-identical instructions.
3. A worker that loses its own context can **re-read its task**.
4. A worker whose turn was destroyed can **recover**, because the instruction survives outside the
   transcript.

Briefs live at `<program>/briefs/` in the tracker's state directory — **outside the repo**. That is
the general seam: *inputs outside the repo, outputs inside it.* It also makes it impossible for a
commit-everything to sweep a brief into a worker's branch.

## Front matter

```yaml
---
title: Land the batch-c cherry-pick chain        # required
worktree: /path/to/lane-a                        # required
expected_artifacts:                              # required, non-empty
  - branch draft/batch-c
  - docs/migration-2026-09/BATCH-C-LANDING.md
advances: [3.1, 3.4, 3.7]                        # required; or the literal `none`
#   an item may instead be a mapping `{track: T-015, expect: "<task label>"}`: an agent-track
#   item in the program repo and the exact task this lane completes. `open` refuses a missing
#   item, an unmatched label, a done task, or any other key; `orch consume` advances it.
consumption: review doc for sign-off, then mark rows Merged   # required
progress_artifact: docs/migration-2026-09/BATCH-C-LANDING.md  # required for long tasks
archetype: integrator                            # required; sets the start rung, effort, independence
mode: auto                                       # optional; session mode to spawn with
model: economy                                   # optional; RUNG, not a name; default the archetype's
review: integrator                               # optional; integrator | in-brief | none
tracker_id: root.1                                # only for a sub-orchestrator
plan_doc: docs/migration-2026-09/PLAN.md          # optional
---
```

Why these six are required and nothing else is:

- **`worktree`** — isolation checks, and knowing whose uncommitted files are whose.
- **`expected_artifacts`** — the field that lets a fresh orchestrator tell a legitimate dirty file
  from another lane's. Directly addresses the commit-everything failure.
- **`advances`** — the join key to the plan document. The literal `none` is accepted because an
  explicit *none* is a decision; a blank is an omission.
- **`consumption`** — the **delete condition**. Without it nobody can tell when the entry is done,
  which is why `orch close` demands a matching statement.
- **`title`** — free, and it is what the roster prints.
- **`archetype`** — the field that decides what the lane costs: `open` takes the starting rung and
  effort from it and refuses anything higher without an escalation. As provenance it was ignored,
  and rungs were copied from the previous brief instead (`delegation.md` §4).

`orch` rejects placeholders (`unknown`, `tbd`, `n/a`, …). A required field answered with a
placeholder is an omission wearing a costume, and accepting one turns validation into ritual.

**`review:` is optional but consequential**, and it defaults to `integrator`. It declares who reads
this lane's diff before it lands: `integrator` (the default second reader), `in-brief` (this lane's
own spec requires an independent or adversarial pass, and the integrator lands on that evidence), or
`none` (mechanical work, and `review_waiver:` must say why). Set it here, at dispatch, because it is
a property of the spec — deciding it later, with a finished diff in hand, is deciding it under the
wrong incentive. A brief claiming `in-brief` whose report carries no such pass does not land; the
integrator escalates. See `integration.md`.

**`progress_artifact:` is the checkpoint for work that can outlive a turn**, and exists before the
first dispatch. The worker's rules for it (what to write, when, the four labels `orch audit` checks)
live in the `working-a-lane` skill. Relative paths resolve against the entry's `worktree`.

Everything else — constraints, rationale, history — goes in the body, because the body is what the
*worker* reads and duplicating it into structured fields creates two copies that drift.

## Body

Use `../assets/BRIEF.template.md`. Sections: Task · Context · Relevant files (by path, don't paste)
· Current state · What was tried · Decisions · Acceptance criteria · Constraints.

Three rules that matter more than the structure:

- **Reference the project's standing-rules file; never restate it.** Restated prose costs your output
  tokens on every dispatch, and goes stale the first time a rule is corrected — the corrected
  version then has to be hand-carried into every future brief, which is exactly how a stale
  constraint ships.
- **Preserve task semantics.** Investigate-only means *"do not edit, create, or delete any files; do
  not write code."* Fix means implement it. Refactor means refactor, not rewrite. Carry the human's
  exact intent; a widened scope is not a favour.
- **Point the worker at the sections, headings or line ranges it needs, with a one-line reason
  each — never "read X in full".** A large reference read in full becomes the lane's floor for
  every call that follows; a worker or subagent that reads it and returns the conclusion keeps the
  floor small.

Include the **if-interrupted clause** (see `messaging.md`) and, for a sub-orchestrator, the
instruction to load this skill plus a recommended fan-out shape.

## The report contract

Every brief specifies the shape of the reply, because an unshaped reply costs the orchestrator
context it cannot get back. The shape (decision block, suppression rules, when a report is due, how
to cite evidence) is the `working-a-lane` skill's, which every lane prompt tells the worker to load.
The orchestrator's side of it:

- A report is due only when the task is finished; a partial report shaped like a complete one is
  indistinguishable from a finished lane (`verification.md`).
- The contract binds every artifact the worker writes, not only its reply: the document is what the
  human actually reads.
- The brief's premise may be wrong; the skill tells workers to say so. Treat that as a finding.
