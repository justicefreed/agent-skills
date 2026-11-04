---
title: <one line, imperative — this is what the roster prints>
worktree: <absolute path the worker must work in>
expected_artifacts:
  - <branch, file, or doc this worker may create or modify>
  - <one per line; this is what tells a fresh orchestrator whose dirty files are whose>
advances: [<plan item ids>]        # or the literal: none
consumption: <what the orchestrator will do with the result — this is the delete condition>
progress_artifact: <path the worker appends progress to — REQUIRED for long tasks>
archetype: <implementer|analyst|reviewer|verifier|verifier-low-risk|doc-writer|inventory|integrator>   # REQUIRED: sets the start rung, effort and independence
slice_id: <one acceptance-criterion-sized slice; use a shared slice map id>
read_set:
  - <paths or named sections this lane may inspect; never “the whole repo”>
write_set:
  - <paths this lane may change; empty only for analysis work>
# max_model_calls: <positive integer; defaults are resolved and recorded at open>
# max_context_tokens: <positive integer; checkpoint/replace before this retained context>
# max_cost_usd: <positive number; this is the lane's reservation against program budget>
# checkpoint_every_calls: <positive integer; persist progress before continuing>
# model: <minimal|economy|advanced|frontier>  # optional RUNG, never a name; defaults to the archetype's
# effort: <lowest|one-below-default|default|above-default>   # optional policy level; `open` resolves a declared model-specific provider option
# model_reason: <the observed signal>         # required for any rung or effort above the archetype's
# escalation_evidence: <field:NAME|entry:eN|path>   # required with model_reason; field: must be non-empty
# subsystems: [<a>, <b>]                      # e.g. what escalation_evidence: field:subsystems points at
# author_family: <family of what is reviewed> # reviewer only; or reviews: <entry id>
# same_family_ok: <why no other lineage>      # reviewer only; waives the lineage rule, on record
review: <integrator|in-brief|none>  # who reads the diff before it lands; default integrator
# review_waiver: <why no second reader is needed>   # required only with review: none
# tracker_id: <root.N>             # only when this worker is itself an orchestrator
# plan_doc: <path>                 # only on the first brief of a program
---

# <Title>

**Read `<path to the project's standing-rules file>` first. It is binding. Do not restate it back to
me.** If anything below contradicts it, this brief wins for this task only — and where it does, it
says so explicitly.

## Task

<Imperative. One paragraph. Preserve semantics exactly: investigate-only means do not edit; fix
means implement; refactor means refactor, not rewrite.>

## Context

<Why this task exists. What the reader needs and cannot infer.>

## Relevant files

- `<path>` — <what it is, why it matters>
- <Reference by path. Do not paste contents; the worker can read.>
- <Large file? Name the sections, headings or line ranges needed, with a one-line reason each — never "read X in full".>

## Current state

<What is done, what works, what does not.>

## What was tried

- <Approach> — <why it failed or was abandoned>

## Decisions already made

- <Decision> — <rationale, and who ruled it>

## Acceptance criteria

- [ ] <Checkable condition>
- [ ] <Include the guard you expect to go red on demand, if there is one>

## Constraints

- <Must-not / must-preserve, specific to this task only.>
- Stay inside `read_set` and `write_set`. A new file range is an escalation to the
  orchestrator, not a reason to widen the task.
- Keep `progress_artifact` current as `working-a-lane` describes.
- Do **not** commit. The orchestrator commits, with explicit paths.
- <For analysis-only work, include verbatim:>
  This is analysis only. Do NOT edit, create, or delete any files. Do NOT write code.

## If interrupted

Your instructions are this file. Your progress is recorded in `<progress_artifact>`. If you receive
an out-of-band instruction mid-task: complete it, then re-read this brief, determine the last
completed step from the progress artifact, and continue from the next one. **Do not report
completion until the original task is done.**

## Sub-orchestration

<Delete if not applicable.> This task decomposes. Load the `orchestrating` skill before starting.
Your tracker id is `<root.N>` — it was minted for you; never mint your own. Suggested fan-out:
<shape>.

## Report contract

Load the `working-a-lane` skill with the Skill tool before anything else; it owns the checkpoint,
inbox, evidence and report rules. Report when the task is finished, opening with its decision block
and writing long-form detail to a file.
