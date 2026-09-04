---
title: <one line, imperative — this is what the roster prints>
worktree: <absolute path the worker must work in>
expected_artifacts:
  - <branch, file, or doc this worker may create or modify>
  - <one per line; this is what tells a fresh orchestrator whose dirty files are whose>
advances: [<plan item ids>]        # or the literal: none
consumption: <what the orchestrator will do with the result — this is the delete condition>
progress_artifact: <path the worker appends progress to — REQUIRED for long tasks>
archetype: <integrator|implementer|analyst|verifier|doc|inventory>   # optional, provenance
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

**Report when the task is finished, not when you next have something to say.** Complete it in one
run — waiting on a long command is work; reporting "in progress" as though finished is not. A tool
or shell call that times out is an infrastructure event, not a result: re-issue it, and say that you
did. If you genuinely cannot finish, say so and name what is incomplete.

Open your reply with a **decision block, ≤300 words**:

1. **Verdict** — one line.
2. **What changed** — identifiers, one line each.
3. **Needs a human ruling** — one line each, or "none".
4. **Falsification** — what would have made this red, and did you observe it red? If you could not
   make it fail, say so; that is the finding.
5. **Numbers that matter** — only those crossing a threshold that changes a decision. State which
   tree or configuration each came from, and whether it could have gone red.

Then write long-form detail **to a file** and give me the path. Do not paste the analysis into your
reply.

Do the verification; do not narrate it — **in your reply and in every document you write.** Suppress
unless actionable: measurements that cross no threshold; test-suite contents; the adversarial pass,
which is part of drafting (report the final state, calling out only a scope change or a newly
surfaced unfixed issue); alternatives not taken; and **changelog narration** — give the result, not
the path to it, and never "first I tried X, then Y, so I changed to Z".

Always surface: anything needing a ruling, anything you could not verify, anything you are guessing,
behaviour that changes in the field, and findings outside your scope that you did not fix.

**Concede or defend — no hedging.** If this brief's premise is wrong, say so.
