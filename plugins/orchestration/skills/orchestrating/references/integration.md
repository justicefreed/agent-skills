# Integration — the standing lane that lands work

Merging finished work is the largest thing an orchestrator does by accident. It arrives at intake,
never through the delegate-or-inline decision, and it arrives with your context already loaded — so
you do it, on the most capable model in the program, once per lane, forever.

Measured on one program: two thirds of the orchestrator's busy time went to landing work, across
twenty of thirty-five turns, with thirty worker dispatches and **not one** integrator among them.
The choice was never made. That is the failure this file exists to prevent.

## The lane

**One long-lived integrator per program**, on its own integration branch or worktree, fed through
the inbox, with a progress artifact. Not one integrator per landing: the chain's accumulated context
— which conflicts recur, which files are volatile, what the last five landings did — is the whole
value, and a fresh worker per merge throws it away and re-reads the tree instead.

Dispatch it like any other worker (`../SKILL.md` Step 3), with `archetype: integrator` and a
progress artifact that records one line per landing. Then queue work to it:

```bash
orch inbox send --to integrator --kind task --ref e3 \
  --body 'Land e3: branch lane/t-010, report at docs/lanes/T-010-PROGRESS.md, review: integrator'
```

Because it is long-lived, it survives your own compaction, and `orch inbox list --all` on its inbox
is a record of every landing you commissioned.

**The orchestrator keeps commit authority; the integrator does the commit labor.** You decide what
belongs in history and in what order, because you are the only agent that knows what else is in
flight. It performs the merge, resolves the conflict, and stages by explicit path. Both halves of
`closeout.md`'s rule survive; only the expensive half moves.

## Who reads the diff before it lands

The integrator reads it. It is the second reader, and being second is the point: `verification.md`'s
rule is that the agent who wrote a change may not be the only agent who checked it. What the rule
protects is *two different readers*, not *the orchestrator specifically* — so satisfying it at the
integrator's tier costs a fraction and loses nothing.

Each lane declares its mode in its brief's front matter, at dispatch time:

| `review:` | Means | Integrator's job |
|---|---|---|
| `integrator` (default) | nobody has independently checked this yet | read the diff against the brief, then land |
| `in-brief` | this lane's own spec required an independent or adversarial pass | land on that pass's evidence |
| `none` | mechanical or trivial; requires `review_waiver:` saying why | land |

**Why the mode is declared and not decided at landing time.** An integrator holding a finished diff,
asked whether it needs reviewing, has every incentive to say no. The mode is a property of the spec,
so it is set by the party writing the spec, before the work exists.

**The `in-brief` escape hatch has one condition, and it is not optional.** The report must actually
carry the independent pass's result — who ran it, what it attacked, what it found. If the report does
not, the integrator **escalates and does not land**. It must not quietly fall back to reviewing the
change itself: a brief that claimed a pass it did not get is a defect in the program, and silently
absorbing it hides the one thing you needed to know. This is Principle 4 — a review you cannot
falsify is worse than no review, because it manufactures confidence.

`review: none` is for sweeps and mechanical renames, and the waiver is what stops it becoming the
default. If you find yourself writing waivers routinely, the lanes are too small to be worth
dispatching at all.

## What the integrator escalates

It lands what holds and raises what does not. Escalation is cheap; a bad landing is not.

- a conflict needing semantic reconstruction rather than a mechanical resolution;
- a diff outside the brief's stated scope, or touching files no expected artifact named;
- a report whose falsification line is absent, vacuous, or contradicted by the tree;
- an `in-brief` claim with no evidence behind it;
- a green produced in a tree that did not contain the change under test.

Everything on that list is a judgment the orchestrator has context for and the integrator does not.
Everything *off* it is a mechanical decision the integrator should simply make.

## What the orchestrator still does

Read escalations. Read the integration branch, at a gate or on a cadence, not per landing. Rule on
what escalations raise, and patch the plan document at the moment you rule. Keep the falsification
check at intake (`../SKILL.md` Step 5) for reports you commissioned directly — delegating the
landing does not delegate the intake discipline, it moves the *diff reading*.

You have not stopped reviewing. You have stopped being the first reader of every diff, which is the
part that scaled badly.
