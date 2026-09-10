# Delegation — substrate, isolation, archetype, model, effort

Four decisions, in dependency order. Each one narrows the next.

## 1. Which substrate

| Use the durable, externally-managed substrate when | Use in-harness subagents when |
|---|---|
| the worker needs its own **branch or worktree that outlives the session** | the task is trivial or short-lived |
| a **human will review** the worker's branch and diff | the point of delegating is to **avoid context pollution** and get a summary back |
| the work is long-running or multi-step | mid-task failure is cheap — a fresh restart costs little |
| the worker may **sub-orchestrate** | the only valuable outcome is the final message, or files on disk |
| mid-run coordination or heartbeats help | |

**Required**, not merely preferred, for the durable substrate: a worker needing a branch or worktree
distinct from the parent's, or a workspace a human will review.

The sharp distinction: in-harness subagents can often be given a *temporary, auto-cleaned* worktree,
which is enough for isolation but not for review. Isolation is not the discriminator — **durability
and reviewability** are. The other discriminator is survival: only the external substrate's workers
outlive the orchestrator, and orchestrator death by context compaction is routine.

## 2. New branch/worktree, or inherit the parent's

**New** when the work is genuinely independent and parallel — not merely concurrent information
gathering — or when it produces artifacts useful to follow-on work but not belonging on the parent's
branch.

**Inherit** for information gathering, planning, and sequential work. Sequential work that happens to
contain parallel sub-steps still inherits at the top; the parallelism belongs one level down.

**One writer per worktree, always.** Two agents in one tree corrupts work. This is the constraint
that makes `whoami` ambiguous for inherited worktrees, and it is worth the tradeoff.

## 3. Which archetype

The archetype names the *kind* of work, which then drives model and effort. Two archetypes are
implemented by other skills; for those, route the workflow out and keep only the selection fallback.

Both columns below are **relative to the provider**, never absolute model names — a table of names
rots the moment a provider ships a release. Resolve them at dispatch time against the provider's own
model list.

| Rung | Means |
|---|---|
| **frontier** | the provider's most capable model, above its default. **Escalation only** — never a starting point |
| **default** | the model the provider selects when you choose nothing. Its flagship for everyday work |
| **economy** | a cheaper, faster model — the provider's "good for everyday tasks" tier |
| **minimal** | the smallest/fastest offered |
| **contrasting family** | a different *model family*, chosen for independence rather than capability |

Effort rungs are likewise relative: **default** (what the model reports as its own default),
**one below default**, **lowest**, and — escalation only — **above default**.

| Archetype | Work | Failure signature | Fallback start | Escalate only when |
|---|---|---|---|---|
| **Integrator / lander** | serial cherry-picks, conflict resolution, keeping a chain green | resolves a conflict by dropping a hunk; declares green from the wrong tree | default model / default effort | a conflict needs semantic reconstruction rather than a mechanical resolution |
| **Implementer** | writes the change for one scoped item | scope creep into neighbouring items; edits a generated file instead of its source | default model / default effort | the change spans subsystems, or the first attempt came back with the scope wrong |
| **Analyst** | traces behaviour, enumerates cases, builds an argument | confident narrative resting on an unverified premise | default model / default effort | the argument is many hops deep, a premise is disputed, or a prior pass was refuted |
| **Verifier / prober** | runs the suite, the build, the assertions; reports numbers | reports a green that could not have gone red | economy model / one below default | the guard cannot be made to go red and nobody knows why |
| **Doc / HTML writer** | review docs, structured artifacts, plan patches | narrates the journey instead of the result | economy model / one below default | rarely — prefer a better outline over more thinking |
| **Inventory / cleanup** | disk audits, resource reclamation, mechanical sweeps | deletes by glob; deletes something still in use | minimal model / lowest effort | never; if it needs thought it is not this archetype |
| **Adversarial reviewer** | attacks a draft's premises | → route the workflow to a committee-style skill | contrasting family / default effort | the first pass found nothing, *and* you have specific reason to doubt that |
| **Second opinion** | independent judgment on a decision | → route the workflow to an advisor-style skill | contrasting family / default effort | — |

### Meta-work has archetypes too

The work a program generates *about itself* — landing branches, patching plan documents, tidying the
tracker — is where an orchestrator most often skips this table, because the work arrives at intake
rather than in a plan. It is ordinary delegable work with ordinary tiers:

| Meta-work | Archetype | Fallback start | Notes |
|---|---|---|---|
| Landing a lane; conflict resolution | integrator | default / default | one standing lane, not one worker per merge — `integration.md` |
| Patching a plan document from a ruling | doc writer | economy / one below default | give it the ruling verbatim; it is transcription, not judgment |
| Tracker hygiene, orphan sweeps, reclamation | inventory | minimal / lowest | never by glob |
| Re-running a check someone else's report claimed | verifier | economy / one below default | must state which tree it ran in |
| Relaying the human's approvals and task adds during execution | front desk | economy / lowest | a router with a whitelist, never a helper — `frontdesk.md` |
| Ruling on an escalation; ordering history | **not delegable** | — | you hold the program's context; this is Principle 5's other half |

The last row is the point of the table. Principle 5 cuts both ways: work that only you can do must
stay with you, and everything else must not.

**Why the defaults sit where they do, and why nothing starts above the provider default.**

- **The provider default is the anchor, not a floor to improve on — on both dials.** In the program
  this catalog was derived from, *every* worker ran on the provider's **default model** at its
  **default effort**; neither dial was ever set, and a more capable model was available the whole
  time. That includes the analyses and adversarial passes that produced the best results, and the
  ones that correctly refuted the orchestrator. The evidence for "default is enough" is strong; the
  evidence for "more is better" is absent. Do not spend past it on a guess.
- **The fallback is the unsupervised path.** It fires precisely when the human has *not* configured a
  profile for this kind of work. Choosing an expensive setting there spends their budget on the
  model's speculation, without their having expressed a preference. Reserve the top of the dial for
  work the human has asked for at that level, or for an escalation you can justify from an observed
  failure.
- **Escalation is cheap and reversible; over-provisioning is neither.** `RETUNE` raises a running
  worker's effort without touching its instructions, so the cost of starting at default and being
  wrong is one adjustment. The cost of starting high on every dispatch is paid on every dispatch,
  including the majority that did not need it.
- **The two below-default rows depend on a contract, and are only safe because of it.** A cheaper
  verifier is more likely to accept a vacuous green — the exact failure that matters most. It is
  acceptable here *only* because the report contract requires a falsification line and the
  orchestrator re-checks it at intake (`../verification.md`). Remove either safeguard and the
  verifier belongs back at the default.
- **Model and effort are separate decisions, and the model matters more.** Most of the available
  saving is in the *model*, not the dial: a mechanical sweep on a minimal model at lowest effort is
  far cheaper than the same work on the default model at any setting. Reach for the model rung first.

Three of these eight archetypes start *below* the provider's defaults and none starts above them. If you
find yourself wanting the frontier model or an above-default dial as a starting point, that is a
signal the **brief** is underspecified — fixing the brief is cheaper and compounds across every
future dispatch, whereas more capability buys one better guess at the same ambiguity.

## 4. Model, effort, and mode

**Set the session mode explicitly at every spawn. Never let it default.** It is the only one of the
three dials that can deadlock a worker, and its failure mode is silent — an agent halted on a
permission prompt is indistinguishable from an agent thinking hard, so a stalled lane can sit for
hours looking busy.

The trap is the mode *id*. On Claude providers the id `default` reads like "whatever the sensible
default is"; its actual label is **Always Ask**, and it is what a spawn receives when `modeId` is
omitted — even though the provider advertises `defaultMode: auto`. Verified on a live worker created
with no mode: it came up `currentModeId: "default"` and stopped on its first tool call, which was
the read of its own brief. A worker has no human watching its session, so Always Ask is not caution
there; it is a hang.

| Want | Claude / claude-cursor | Cursor |
|---|---|---|
| A worker that runs unattended but still screens its own actions | `auto` — a classifier reviews each prompt | `agent` + feature `auto_accept` |
| Edits without prompts, commands still screened | `acceptEdits` | — |
| Genuinely unattended, no prompt possible | `bypassPermissions` — a real security decision, per dispatch | `agent` + `auto_accept` |
| Read-only investigation, and you accept it will stop to ask | `plan` | `plan` or `ask` |

`orch open` records the mode and prints the exact `settings` fragment to pass; it refuses `default`,
`plan` and `ask` unless you pass `--ask-mode-ok`, because those stop and wait. `ORCH_WORKER_MODE`
changes the default it fills in. `orch roster` flags a recorded blocking mode as `ASK-MODE`.

**Mode alone is not enough.** A brief lives outside the worker's worktree, and in Claude Code a read
outside the working directory prompts under *every* mode except `bypassPermissions` — so the first
line of a brief-driven spawn is the thing that stalls it. Run `orch permissions --install` once per
machine; see `state.md`.

**Profiles first.** If the substrate offers named launch bundles configured by the human, list them,
read every profile's notes, and pick the one whose notes match the work. Materialise it into the
spawn call. **If none fits, fall back to the table above and tell the user you fell back** — silent
fallback hides the fact that the human's configuration didn't cover this case.

Then:

- **Two dials or one.** Some providers expose a thinking/effort dial in addition to the model; others
  expose none, and there the archetype's "model and effort" collapses to model alone. Check before
  planning around effort.
- **Escalate with `RETUNE`, from an observed signal.** A running worker's model and effort can be
  changed without touching its instructions, so starting at the table's default costs one adjustment
  when it turns out to be wrong. Escalate on a *signal* — the failure signature in the table, a
  refuted premise, a worker that says it cannot make its guard go red — not on a hunch that this
  task feels hard.
- **A profile is launch configuration only.** Never treat it as a worker's current state — `RETUNE`
  may have changed it. Record model/effort as provenance if useful, never as truth.
- **Contrast compares model *family*, not provider id.** A bridged provider hosting the same
  model family is a billing path, not an independent opinion. Genuine contrast means a different
  family — and where a harness offers several families, an adversarial reviewer should use one.

## 5. Sub-orchestration

A worker may orchestrate. When a delegated task decomposes further:

- say so in the brief, and tell the worker to load this skill;
- **recommend a fan-out shape** rather than leaving it open — the parent has context the child lacks;
- mint the child's tracker id (`orch mint-child`) and put it in the brief. A child never mints its
  own.

Nested orchestrators track **only their own direct children**. A parent holds no handle to a
grandchild, so tracking one would be state it cannot act on. Whole-tree visibility comes from
`orch roster --recursive`, which walks filenames; orphan detection comes from the substrate's own
global agent listing.

## 6. When not to delegate

Fan-out is not free — each worker costs a brief, a record, an intake, and a closeout. Do it inline
when the task is a single lookup, when the delegation overhead exceeds the work, or when you would
have to explain more context than the task contains.

But weigh that against what inline work costs *you*, not just what the dispatch costs. An inline
task is billed at your tier, it makes you unreachable for as long as it runs, and — the term nobody
counts — whatever it leaves in your context is re-read on **every remaining model call of the
program**. Measured, that residue is the single largest line in an orchestration bill. "Cheaper than
a dispatch" is a claim about three numbers, and orchestrators routinely evaluate one.

A worker, by contrast, carries a small context and then dies, so its own re-read tax never
accumulates. See `cost.md` for the measurements.
