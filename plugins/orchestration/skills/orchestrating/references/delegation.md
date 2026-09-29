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

The archetype names the *kind* of work, and the kind of work sets two axes: the **rung** (capability
and cost) and the **independence** (none, not the author, or a different model family). The catalogue
— rungs, relative efforts, failure signatures, escalation signals, and the reviewing rule — is owned
by the `delegating-economically` skill's `references/rungs.md`, and its machine form resolves an
archetype to live models:

```bash
spend models --archetype implementer
spend models --archetype reviewer --exclude-family <author's family>
```

Read the rung vocabulary there, not here. Two points are orchestration's own: `frontier` is whatever
the option map designates, so an escalation to it never reaches a pricier model the map did not name;
and `default` is not a rung — it names whatever the provider selects when nothing is specified, which
is how the rung above `economy` once moved without its name changing. `orch` refuses `default`
wherever a rung is asked for, on `open`, `escalate --to`, and brief front matter, and suggests
`advanced` in the error.

Two archetypes exist only because orchestration does. Both are in the option map so `spend models`
resolves them; their prose lives here:

| Archetype | Work | Failure signature | Rung / effort | Independence | Escalate when |
|---|---|---|---|---|---|
| **Integrator** | serial cherry-picks, conflict resolution, keeping a chain green | resolves a conflict by dropping a hunk; declares green from the wrong tree | economy / default | none | a conflict needs semantic reconstruction rather than a mechanical resolution — then advanced |
| **Front desk** | relays the human's approvals and task adds during execution | helps instead of routing; acts outside its whitelist | economy / lowest | none | never; a router that needs judgment is not a front desk — `frontdesk.md` |

**Reviews route by object.** A reviewer of *code* is an ordinary lane dispatched from here, under the
reviewing rule in `rungs.md`. A reviewer of a *draft's premises* routes to a committee-style skill, and
a second opinion on a *decision* to an advisor-style skill — same archetype, same rung and family rule,
different workflow. Whether a lane needs review at all is the brief's `review:` field
(`integration.md`); who reviews it is the catalogue's.

### Meta-work has archetypes too

The work a program generates *about itself* — landing branches, patching plan documents, tidying the
tracker — is where an orchestrator most often skips the catalogue, because the work arrives at intake
rather than in a plan. It is ordinary delegable work with ordinary archetypes:

| Meta-work | Archetype | Notes |
|---|---|---|
| Landing a lane; conflict resolution | integrator | one standing lane, not one worker per merge — `integration.md` |
| Patching a plan document from a ruling | doc-writer | give it the ruling verbatim; it is transcription, not judgment |
| Tracker hygiene, orphan sweeps, reclamation | inventory | never by glob |
| Re-running a check someone else's report claimed | verifier | must state which tree it ran in; `verifier-low-risk` only when the check is mechanical |
| Reviewing a lane's diff before it lands | reviewer | a different family from the lane that wrote it |
| Relaying the human's approvals and task adds during execution | frontdesk | a router with a whitelist, never a helper — `frontdesk.md` |
| Ruling on an escalation; ordering history | **not delegable** | you hold the program's context; this is Principle 5's other half |

The last row is the point of the table. Principle 5 cuts both ways: work that only you can do must
stay with you, and everything else must not.

**Why nothing starts above `economy`, from where an orchestrator sits.** The anchor's measured case —
the drift that cost $616 where one rung down cost $246, and the 28-of-31 single-round baseline it is
being tested against — is in `rungs.md` and `cost.md`. What orchestration adds:

- **The catalogue is the unsupervised path.** It fires precisely when the human has *not* configured
  a profile for this kind of work. Choosing an expensive setting there spends their budget on the
  model's speculation, without their having expressed a preference. Reserve the top of the dial for
  work the human has asked for at that level, or for an escalation you can justify from an observed
  failure.
- **Escalation is cheap and reversible; over-provisioning is neither.** `RETUNE` raises a running
  worker's model or effort without touching its instructions, so the cost of starting at the
  catalogue's rung and being wrong is one adjustment. The cost of starting high on every dispatch is
  paid on every dispatch, including the majority that did not need it.
- **The cheap verifier and reviewer depend on a contract, and are only safe because of it.** A cheaper
  model is more likely to accept a vacuous green or wave through a plausible diff — the exact failures
  that matter most. That is acceptable *only* because the report contract requires a falsification
  line, every review finding carries its evidence, and the orchestrator re-checks both at intake
  (`verification.md`). Remove either safeguard and the archetype belongs a rung up. This is also why
  neither drops to `minimal` while the doc writer and the cleanup sweep do: a bad doc is visible in
  the artifact and a bad sweep fails loudly, whereas a bad verdict is *indistinguishable from a good
  one* until something downstream breaks.
- **Model and effort are separate decisions, and the model matters more.** Most of the available
  saving is in the *model*, not the dial. Reach for the model rung first.

If you find yourself wanting `advanced`, the frontier model, or an above-default effort dial as a
*starting point*, that is a signal the **brief** is underspecified — fixing the brief is cheaper and
compounds across every future dispatch, whereas more capability buys one better guess at the same
ambiguity.

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

**The model rung is decided in the same place, for the same reason — and the archetype decides it.**
A dial left to the spawn call gets forgotten, and a dial left to the brief gets copied from the last
brief; neither fails safe. Omitting the mode selects Always Ask, and omitting the model selects the
provider default — which in one program happened to be the advanced rung, so every lane ran a rung
high and nothing looked wrong. So `orch open`:

- **requires `archetype:`** and takes the lane's rung and effort from it. A brief's `model:` or
  `effort:` may only restate or lower that start;
- **treats anything above the start as an escalation made before dispatch**, and refuses it without
  `--model-reason "<the signal>"` *and* `--evidence` — `field:<brief field>` (the brief itself names
  the subsystems or dependent steps, and the field must be non-empty), `entry:<id>`, or a path to the
  report that shows the signal. It is logged like any escalation, so `escalate --log` shows which
  archetypes start high;
- **resolves the rung to exact models** from the catalogue and prints them, with the settings and
  labels to spawn with. For a `reviewer` it first excludes the author's whole lineage — from
  `author_family:`, or from what the `reviews:` entry actually spawned — unless `--same-family-ok
  "<why>"` puts the exception on record;
- **prints the roster's flags for the new entry at once**, rather than waiting for someone to run
  `roster`.

The **long-context variant** (`[1m]` and the like) is its own dial with its own price: `--long-context`
at open, or `escalate --long-context`, under the same reason-and-evidence rule.

**The spawn guard checks the spawn against the decision.** A PreToolUse hook on Paseo's
`create_agent`, `update_agent` and `send_agent_prompt`, and on Claude Code's `Agent` tool, refuses a spawn labelled with an entry whose
model is not one the entry resolved to, whose mode differs from the recorded one, or that asks for a
long-context variant nobody escalated; refuses an unlabelled spawn while entries are pending (label
`orch_entry: none` for an agent that is not a lane); refuses a RETUNE above the recorded rung or one
that clears the model onto the provider default; and records what was spawned. A mismatch that is
genuinely right goes through with label `orch_override: "<why>"` and shows on the roster.

A Claude Code subagent takes no labels, so the entry rides in its prompt as a line of its own —
`orch_entry: e5`, and `orch_override: <why>` the same way — and its model is whatever the `model`
alias resolves to in the dated alias table, else whatever the `subagent_type`'s agent definition
pins. A subagent with neither inherits the session's model, which is refused for a lane for the same
reason an omitted Paseo model is. `open` prints the `subagent_type` to use; `spend agents --write`
creates the definitions, one per canonical id. Where no
hook runs, record the spawn with `orch update <e> --spawned-model <id>`; `roster` flags
`TIER-MISMATCH` either way.

**A lane is not free to reuse.** Every follow-up prompt re-reads the lane's whole history, so the
guard counts them and, past `ORCH_LANE_ROUNDS_MAX` (default 3), advises a fresh agent from the brief
and its progress artifact — `orch open` the same brief again, spawn from it, and `orch close` the old
entry; `roster` shows `ROUNDS:<n>`. (Replacing the *orchestrator* is a different procedure:
`rotation.md`.) One ramp-up is cheaper than a
sixth round that is mostly the first five.

Never write a model name into a brief: it is wrong the next time the provider ships, and `orch`
rejects it. The names live in the catalogue, dated, and `open` reads them there.

**Mode alone is not enough.** A brief lives outside the worker's worktree, and so does the skill's
own `references/` corpus; in Claude Code a read outside the working directory prompts under *every*
mode except `bypassPermissions` — so both the first line of a brief-driven spawn and the reference it
sends the worker to are things that stall it. Run `orch permissions --install` once per machine; see
`state.md`.

**Profiles first.** If the substrate offers named launch bundles configured by the human, list them,
read every profile's notes, and pick the one whose notes match the work. Materialise it into the
spawn call. **If none fits, fall back to the catalogue and tell the user you fell back** — silent
fallback hides the fact that the human's configuration didn't cover this case.

Then:

- **Two dials or one.** Some providers expose a thinking/effort dial in addition to the model; others
  expose none, and there the archetype's "model and effort" collapses to model alone. Check before
  planning around effort.
- **Escalate with `RETUNE`, from an observed signal, and record it.** A running worker's model and
  effort can be changed without touching its instructions, so starting at the catalogue's rung costs one
  adjustment when it turns out to be wrong. Escalate on a *signal* — the failure signature in the
  table, a refuted premise, a worker that says it cannot make its guard go red — not on a hunch that
  this task feels hard. Then run it through the tracker, which demands the signal in writing:

  ```bash
  orch escalate e1 --to advanced --scope attempt \
    --reason "first pass came back with the scope wrong" --evidence entry:e1
  ```

  **Say what the signal is about.** `--scope task` means the work itself needs the rung — it spans
  subsystems — and a fresh lane opened from the same brief keeps it without re-arguing. `--scope
  attempt` answers one weak pass; a fresh lane restarts at the archetype's rung, which is usually
  what a rotation wants. `--effort` and `--long-context` escalate the other two dials the same way.

  `escalate` only ever raises; to fix a *mis-recorded* rung use `orch update e1 --model <rung>`. The
  reason is mandatory and the record outlives the entry, because the reasons are the only thing that
  ever corrects a rung's fallback start by measurement instead of by feel. `orch escalate --log`
  reads them back grouped by archetype — and **an archetype that escalates every time has the wrong
  fallback, not a run of bad luck.** Fix its row in the catalogue (`rungs.md` and
  `model-options.json`) rather than escalating it forever.
- **A profile is launch configuration only.** Never treat it as a worker's current state — `RETUNE`
  may have changed it. Record model/effort as provenance if useful, never as truth.
- **Contrast compares model *family*, not provider id.** A bridged provider hosting the same
  model family is a billing path, not an independent opinion. The reviewer archetype requires a
  different family from the author; see the reviewing rule in `rungs.md`.

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
