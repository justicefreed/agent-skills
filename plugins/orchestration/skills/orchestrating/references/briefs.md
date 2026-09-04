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
consumption: review doc for sign-off, then mark rows Merged   # required
progress_artifact: docs/migration-2026-09/BATCH-C-LANDING.md  # required for long tasks
archetype: integrator                            # optional, provenance
tracker_id: root.1                                # only for a sub-orchestrator
plan_doc: docs/migration-2026-09/PLAN.md          # optional
---
```

Why these five are required and nothing else is:

- **`worktree`** — isolation checks, and knowing whose uncommitted files are whose.
- **`expected_artifacts`** — the field that lets a fresh orchestrator tell a legitimate dirty file
  from another lane's. Directly addresses the commit-everything failure.
- **`advances`** — the join key to the plan document. The literal `none` is accepted because an
  explicit *none* is a decision; a blank is an omission.
- **`consumption`** — the **delete condition**. Without it nobody can tell when the entry is done,
  which is why `orch close` demands a matching statement.
- **`title`** — free, and it is what the roster prints.

`orch` rejects placeholders (`unknown`, `tbd`, `n/a`, …). A required field answered with a
placeholder is an omission wearing a costume, and accepting one turns validation into ritual.

Everything else — constraints, rationale, history — goes in the body, because the body is what the
*worker* reads and duplicating it into structured fields creates two copies that drift.

## Body

Use `../assets/BRIEF.template.md`. Sections: Task · Context · Relevant files (by path, don't paste)
· Current state · What was tried · Decisions · Acceptance criteria · Constraints.

Two rules that matter more than the structure:

- **Reference the project's standing-rules file; never restate it.** Restated prose costs your output
  tokens on every dispatch, and goes stale the first time a rule is corrected — the corrected
  version then has to be hand-carried into every future brief, which is exactly how a stale
  constraint ships.
- **Preserve task semantics.** Investigate-only means *"do not edit, create, or delete any files; do
  not write code."* Fix means implement it. Refactor means refactor, not rewrite. Carry the human's
  exact intent; a widened scope is not a favour.

Include the **if-interrupted clause** (see `messaging.md`) and, for a sub-orchestrator, the
instruction to load this skill plus a recommended fan-out shape.

## The report contract

Every brief specifies the shape of the reply, because an unshaped reply costs the orchestrator
context it cannot get back.

**The contract binds every artifact the worker produces, not only its reply.** A review document, a
detail file, a summary written to disk — all of them follow the suppression rules below. A worker
that keeps a disciplined reply and then writes a sprawling document has moved the cost rather than
removed it, and the document is what the human actually reads.

### When you may report

A report is due when the task is **finished**, not when the worker next has something to say.

- **Complete the task in one run.** Waiting for a long-running command is work; reporting
  "in progress" as though finished is not.
- **A tool or shell call that times out is an infrastructure event, not a result.** Re-issue it. Do
  not treat the timeout as a failure of the task, and do not report a partial outcome as final — but
  *do* say you re-issued, because a command that times out repeatedly is itself a finding.
- **If you genuinely cannot finish**, say so explicitly and name what is incomplete. An honest
  partial report is fine; a partial report shaped like a complete one is not.

This is the precondition the rest of the contract assumes. An orchestrator reading a well-formed
decision block has no way to tell that the work behind it stopped halfway — which is the same
indistinguishable-failure shape as everything in `verification.md`.

**Open with a decision block, ≤300 words:**

1. **Verdict** — one line.
2. **What changed** — identifiers with one line each.
3. **Needs a human ruling** — one line each, or "none".
4. **Falsification** — *what would have made this red? Was it observed red?* If it could not be made
   to fail, say so — **that is the finding**.
5. **Numbers that matter** — only those crossing a threshold that changes a decision.

Then long-form detail **to a file**, with the path given. Not pasted into the reply.

**Do the verification; don't narrate it.** Suppress unless actionable, in the reply *and in every
document you write*:

- **measurements** that cross no threshold that changes a decision;
- **test-suite contents** — surface a suite only when it needed loosening, when a guard could not be
  written, when something pre-existing broke, or when coverage the human should know about is absent;
- **the adversarial pass**, which is part of *drafting*, not a deliverable — report the final state,
  calling out only (a) a scope change or (b) a newly surfaced unfixed issue;
- **alternatives not taken**, beyond a genuine close runner-up or a decision that turned on a real
  tradeoff;
- **changelog narration** — give the **result**, not the path to it. No "first I tried X, then the
  review said Y, so I changed to Z." Keep the callouts that change the human's decision; drop the
  journey. This one matters most in documents, where the temptation to narrate is strongest and the
  reader is least interested.

**Always surface:** anything needing a ruling, stated as a decision with options; anything you could
not verify, and anything you are guessing; behaviour that changes in the field; findings outside
your scope that you did not fix.

**Honesty clause.** Concede or defend — no hedging, no splitting the difference to be agreeable. If
the brief's premise is wrong, say so; orchestrator briefs have been wrong before and saying so was
the right call. Distinguish *wrong* from *unverified* from *I would have done it differently*; the
last is the least interesting.

**State the provenance of every number.** Which tree it came from, and whether that tree could have
gone red. A suite run where the change under test is absent is always green.

Also: **do not commit** — the orchestrator commits, with explicit paths, because a worker's
commit-everything can sweep a sibling's work.
