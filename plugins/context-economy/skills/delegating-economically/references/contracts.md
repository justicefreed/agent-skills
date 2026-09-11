# The task contract — three lines that decide what comes back

A subagent prompt without a contract returns prose. The prose lands in your
context and is re-read on every later model call, so an under-specified dispatch
is not merely low quality — it is a recurring charge.

Three fields. They are small deliberately: a contract nobody writes is worth
nothing.

## Artifacts — what must exist when this is done

Paths and names, not adjectives. "Improve error handling" names no artifact;
"`src/client.ts` handles the 429 path, with a test in `tests/client.test.ts`"
does.

The test is mechanical: **could someone check it without asking you what you
meant?** If not, it is a wish rather than an artifact.

## Consumption — how you will use the result

This is the field people skip and the one that pays. It bounds what comes back,
and what comes back is permanent context.

> "Reply with the file path and a one-line summary. Do not paste the diff."

> "Reply with PASS or FAIL and, if FAIL, the first failing assertion only."

> "Reply with the three candidate locations and one sentence each."

Measured in a program where every dispatch carried this field, subagent reports
were **4% of the orchestrator's context** — against 35% for its own tool results
and 32% for its own prose. Without the field, a report arrives at whatever length
the subagent felt like, and you pay for that length for the rest of the session.

It is also the fix for the doc-writer failure mode: an agent that narrates its
journey was never told you only wanted the destination.

## Falsification — what would show this is wrong

An unfalsifiable check is worse than no check: it manufactures confidence. Before
believing a green, know what would have made it red — and prefer to have seen it
red.

> "The test must fail if the retry is removed. Confirm you saw it fail."

For an analyst, the falsification is the premise that would collapse the
argument. For a verifier, it is the mutation that should break the suite. For a
premise auditor, it is the evidence that would settle the claim either way — and
naming it up front is what stops the auditor from simply agreeing with you.

## Placeholders

A required field answered `unknown`, `TBD`, `n/a` or `see above` is an omission
wearing a costume. Rejecting these is the difference between enforcement and
ritual. If you genuinely cannot say what the artifact is, the task is not ready
to delegate — which is itself useful information, and usually means it needs
splitting.

## What this is not

This is deliberately **not** a brief in the orchestration sense. A brief also
carries a worktree, a tracker id, what plan item it advances, and a review mode —
all of which need a dispatch tracker and a multi-agent program to mean anything.
Those live in the `orchestrating` skill and stay there.

What ports is the part that governs **what a subagent produces and what it sends
back**, because that is true of a one-off `Task` call in a plain session just as
much as of a tracked lane.
