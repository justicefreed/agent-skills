# Design — `orchestration` plugin

Decision record for the orchestration skill, distilled from a multi-month, multi-agent code
remediation program run on a private codebase. Written before implementation so the rationale is
durable rather than reconstructed.

Status: **agreed 2026-09-04.** Spine written; tooling and content migration pending.

---

## 1. Scope and tiers

Orchestration knowledge splits three ways. The skill owns the first two and *generates* the third.

| Tier | Content | Home |
|---|---|---|
| **A** universal mechanics | delegation criteria, substrate choice, isolation policy, brief contract, report shape, tracker discipline, liveness, model/effort selection | the skill |
| **B** transferable patterns | "make the guard go red before believing it", "state which tree a number came from", "an append-only registration list conflicts out of order", "commit with explicit paths while agents are live" | the skill |
| **C** project facts | build flags, formatter exclusions, cache paths, version bumps, known traps, output-verbosity preferences | generated per repo, committed there |

Tier C is generated from `assets/STANDING-RULES.template.md`. Briefs **reference** it and never
restate it — the pattern that originally cut ~500 words of boilerplate per dispatch and, more
importantly, single-sourced rules that had previously been hand-carried into every new brief (a
corrected constraint had shipped stale exactly that way).

## 2. Repo and distribution

Layout 2 — one marketplace repo, many plugins, each `plugins/<name>/`. Chosen over root-as-plugin
because future skills are of unknown relatedness, and the migration cost is asymmetric: Layout 2
costs one directory level now, while Layout 1 → 2 later rewrites every manifest path *and* the
plugin name that installs are keyed on.

Grouping rule: skills sharing a `references/` corpus, or always enabled together, belong to one
plugin — because `${CLAUDE_PLUGIN_ROOT}` resolves per-plugin and cross-plugin sharing is not clean.

Cross-harness support follows `mattpocock/skills`: `AGENTS.md` symlinked to `CLAUDE.md`, a
`scripts/link-skills.sh` that links into both `~/.claude/skills` and `~/.agents/skills`, and skill-
local `references/` (portable, unlike `${CLAUDE_PLUGIN_ROOT}`).

## 3. One skill, not several

`orchestrating`, model-invoked. Rejected during design:

- **`orchestration-checkpoint`** — would have written a consolidated resume document. Dropped
  because its content decomposed into three obligations at three *different* times: worker intent
  (write at dispatch), liveness (re-derive at read), ephemeral rulings (materialise when ruled).
  Fusing them into one end-of-session document is what let liveness get frozen into a false fact.
- **`RESUME.md`** — dropped for the same reason. It is a write-back cache: it batches dirty state in
  the orchestrator's context and needs a flush, and the orchestrator can die at any moment. Write-
  through has no flush and no crash window.
- **`orchestration-bootstrap`** — a spine branch, not a skill; it fires once per repo.

A generic conversation-compaction handoff skill remains complementary and is not reimplemented.

## 4. Capability verbs and adapters

The spine names no tool. Verbs: `SPAWN ISOLATE POLL HARVEST CLOSE ESCALATE PEER RETUNE WAKE
SCHEDULE`. Adapters: `paseo`, `claude-native` (in-harness agent teams treated as a variant whose
`SPAWN` is human-performed), `none`.

`NUDGE` was specified and then **deleted** — mid-task instruction of a running worker is not
implementable on any substrate examined. Corrections come from the worker (`ESCALATE`), wait, or
destroy work explicitly.

Acceptance test: grep the spine for tool and substrate names and find none. The cautionary example
is an abstraction the source program already had — a clean interface with two implementations,
bypassed in practice because the caller held one of them concretely. An abstraction survives only
when the caller *cannot* name the implementation.

## 5. Model and effort

Profiles-first, because the substrate has a purpose-built mechanism (named provider/model/mode
bundles with human-written `notes`) that was sitting unused while every dispatch hardcoded one
model. Fallback is an **archetype catalog** — per-archetype guidance, tradeoffs, failure signature,
and an example model/effort *range*, not a single pair. Falling back is disclosed to the user.

Archetypes: integrator/lander · implementer · verifier · doc writer · inventory. Adversarial review
and second-opinion analysis route to existing vendor skills for *workflow*, while the catalog
supplies the *selection fallback* those skills lack.

Constraints: two dials on Anthropic-family models, one on Cursor-hosted models (no thinking
options). `RETUNE` makes start-cheap-escalate-later viable. Contrast compares **model family**, not
provider id — a bridged provider with the same family is a quota path, not an independent opinion.

### 5a. The anchor drifted, and relative rungs are why nobody noticed

Rungs are deliberately relative — `frontier` / `default` / `economy` / `minimal`, resolved against
the provider's live model list — because a table of model names is wrong the next time a provider
ships. That decision was right and it had a cost nobody priced: **a relative rung can change
referent without changing spelling.** A stale name (`sonnet-4-5`) looks stale on sight; a stale rung
reads as current forever.

`default` is the rung that moved. The catalog's justification for anchoring there was empirical — in
the program it was derived from, every worker ran on the provider default at default effort, and that
included the adversarial passes which correctly refuted the orchestrator. But the provider default
was a Sonnet-class model when that was measured and is an Opus-class one now, so the unchanged
sentence became a 2.5x instruction. Measured across four days on one machine (§9c): 6,509 calls in
lane worktrees cost **$616 where the same tokens one rung down cost $246** — 39% of the entire bill,
and the single largest lever found, against 11.6% for capping every context at 120K.

Read correctly, the original evidence never supported the frontier tier; it supported *whatever the
everyday tier happens to be*. So the anchor is now **`economy`**, seven of nine archetypes start at
or below it, and none starts above it. Two things follow:

- **The cheap-tier claim is untested one rung down, so it is instrumented rather than asserted.** The
  baseline is on record — 28 of 31 lane tasks finished in a single round on the old anchor. The
  verifier is the one archetype that held at `economy` while the doc writer and the cleanup sweep
  dropped to `minimal`, because a bad doc is visible in the artifact and a bad sweep fails loudly,
  whereas a bad verdict is indistinguishable from a good one until something downstream breaks. Its
  `minimal` carve-out is a separate row with a narrow precondition, not a discount on the same row.
- **The dial is enforced where the mode already is, and for the identical reason.** Both are decided
  at `orch open` rather than at spawn, because a field remembered at spawn time is a field that gets
  forgotten — and neither fails safe: omitting the mode selects Always Ask, omitting the model
  selects the provider default. `open` refuses `frontier` without `--model-reason`; `roster` prints
  `TIER:<rung>` above `economy` with a `:NO-REASON` suffix when unjustified, because spend, unlike a
  stall, never announces itself.

`orch escalate <e> --to <rung> --reason R` is the escape hatch, and its mandatory reason is the point
rather than the friction. Escalation records land in `escalations.json`, the one sidecar that
**outlives the entry it describes** — every other record here dies when its subject closes, but this
one answers a question no single dispatch can see: which archetypes actually earn a higher rung. It
can only answer it by accumulating across dispatches that are individually gone, and nothing else
records it, since the reason a human raised a dial appears in no transcript, commit or plan document.
An archetype that escalates every time is a wrong default, not bad luck — the log is how that becomes
visible, and the catalog row is what should change.

## 6. Tracker

`${XDG_STATE_HOME:-~/.local/state}/agent-orchestration/<repo-basename>-<hash8>/<program>/<id>.json`

- **Repo key** from `git rev-parse --git-common-dir`, so every linked worktree of a repo maps to one
  key, and the tracker outlives any lane worktree.
- **Program name** derived from the plan-document directory, notified not confirmed; asked *only*
  when minting a second program alongside an existing one, since that is the one failure that splits
  state into two internally-consistent halves. `orch rename` makes a poor name recoverable.
- **Tracker ids** parent-minted and ordinal (`root`, `root.1`, `root.1.2`), so the filename encodes
  the tree and `roster --recursive` needs no file reads. Recovery is a read, never a mint — a child
  that mints its own id creates a silent split-brain.
- **Working set, not a log.** Open dispatches only; entries mutate and are deleted on consumption.
  History is a deliberate non-goal; retrospectives come from the substrate's own activity records.
- **Format JSON**, atomic whole-file rewrite. SQLite was specified and dropped once per-orchestrator
  scoping made the file single-writer and deletion kept it bounded — every distinctive property of a
  database was load-bearing only under assumptions the scoping removed, and it would have added a
  schema-migration story across skill versions.

Outside the repo, never committed. Provenance graduates into in-repo artifacts at harvest.

## 7. Briefs

Machine-local at `<program>/briefs/`. Governing seam: **inputs outside the repo, outputs inside it**
— which also makes it impossible for a commit-everything to sweep a brief into a worker's branch.

Front matter supplies the required tracker fields so they are recorded without restatement, and so
the worker's own understanding of what it may touch and the tracker's record are *the same bytes*.
Body follows an existing vendor handoff structure. Additions: standing-rules reference, a **progress
artifact** for long tasks, an **if-interrupted resume clause**, and a report contract requiring a
decision block, detail-to-file, and a **falsification line**.

Brief-as-file was chosen for single-sourcing and repetition savings; it turned out to also be the
interruption-recovery mechanism (an interrupted worker's transcript survives — what is lost is the
*instruction to continue*) and the enabler of step-addressable resumption.

## 8. Messaging — verified, not assumed

Every row below was established by experiment against workers running an externally-logged 20-step
task, with an uninterrupted control.

| Path | Semantics |
|---|---|
| substrate send tool | interrupts and replaces; **reports success** |
| substrate CLI send, `--no-wait` | interrupts and replaces (flag is caller-side) |
| harness-native peer message | queues, drains at end of turn, **race-free by construction** |
| deferred send held in the tracker | any provider; one drain per finish notification, in-flight guard, post-send verification |

Mid-task correction exists nowhere — the vendor's own desktop client defers rather than interrupts.
Peer questions default to **artifact reads**; peer interrupts require parent authorisation in both
briefs plus a tracker record. Single-sender discipline, because status-check-then-send is TOCTOU and
no atomic send exists.

## 9. Liveness, intake, closeout

Notifications are the good path; heartbeats are the insurance; explicit reconciliation is for a
failed heartbeat or a fresh context — **never a wait loop**. This resolves a real conflict: the
vendor skill forbids polling, while the source program mandated per-turn reconciliation. Both are
right in their own regime, and the discriminator is whether a notification could have been lost.

Intake requires a falsification line always, and independent verification when the same agent
authored both the change and its check **and** the change is hard to reverse — narrower and more
checkable than "important."

Closeout: explicit-path commits while agents are live, entry deletion as the completion criterion,
resource reclamation by explicit name.

## 9a. Availability, and why the orchestrator kept doing the work

Measured from one three-hour program's transcript: 30 worker dispatches, **zero** integrators, and
71 of 106 minutes of orchestrator busy time spent landing other agents' work across 20 of 35 turns.
The orchestrator never *decided* to merge inline; merging arrived at intake and was simply done, on
the program's most capable model, while the human's queued input waited.

Two structural causes, and one fix each.

**Emergent work never reached the delegate-or-inline decision.** Step 1 marks *planned* units of
work. A merge, a doc patch, a re-verification are not units when you plan — they surface at intake
with the orchestrator's context already loaded, which is exactly the condition under which inline is
cheapest to start and most expensive to finish. Fixes: Principle 5, an explicit re-ask in Step 1, a
meta-work archetype table, and a standing integrator lane so landing has a home.

**Availability was not a named resource.** Optimising context alone permits a ten-minute inline
merge, because a merge is cheap in tokens and ruinous in latency. Availability is now the third
scarce resource, with bounded turns as the rule and stated exceptions for work that genuinely cannot
be split.

The review question that follows — if the orchestrator no longer reads every diff, who does — is
answered by observing what `verification.md` actually protects: **two different readers**, not the
orchestrator specifically. So the integrator is the second reader, at its own tier, and the
`review:` mode is declared in the brief at dispatch rather than judged at landing time by the agent
holding the finished diff. `in-brief` is the escape hatch for lanes whose own spec already required
an independent or adversarial pass; it is honoured only when the report carries that pass's result,
and escalates rather than silently downgrading when it does not.

## 9b. The inbox

Queued input is an append-only JSONL file per target plus a cursor, drained by the receiver at the
end of a turn. It exists because §8 established that **no substrate offers a safe send to a running
agent.** The inbox does not solve that; it removes the send. Senders append, the receiver drains, and
there is no check-then-send window to lose.

It is the only multi-writer state in the design, and the exception is bought rather than assumed:
small appends land whole, lines are never mutated, and a line's index never changes — so the one
mutable file, the cursor, still has exactly one writer, and Principle 3 holds where it decides
correctness. One claimant per worktree, resting on the existing one-writer-per-worktree rule.

Drain paths, in order of preference: a turn-end hook in this skill's own front matter (covers every
Claude-harness agent including Paseo-hosted ones, registers on skill load, prints nothing on an empty
inbox so an idle turn costs zero tokens); an optional bundled Paseo daemon plugin for providers with
no turn-end hook; and `peek` by hand. The hook reads the working directory from the payload the
harness pipes it, because a hook is not guaranteed to run where the agent is working.

## 9c. Cost, measured

Four days of one machine's transcripts, 16,156 model calls, ~$1,140. Cache reads — re-reading the
context on every model call — were **55%** of it (1.66 billion tokens), output 24%, cache writes
21%, fresh input ~0%. Reasoning was about a fifth of the output, so a few percent of the bill.

The load-bearing measurement is cost per model call against context carried, over 9,138 Opus calls:
$0.077 under 100K, $0.105 at 100-200K, $0.152 at 200-300K, $0.224 at 300-400K, $0.271 at 400-500K.
Same agent, same kind of work, 3.5x across the range. By composition that context was 35% tool
results, 29% its own tool-call text, 32% its own prose and reasoning, and 4% worker notifications —
**self-inflicted, not imposed by the workers.**

Two corrections to how this was originally measured, because both inflated the answer and the second
one silently changed a threshold. `orch cost` summed transcript *lines*, but the harness writes one
line per content block and repeats the same `usage` object on each, so a 714-response session counted
as 1,592 calls; responses are now deduplicated on `requestId`. And `DEFAULT_RATES` carried no `opus`
or `fable` row, so both fell through to a `default` still priced at the Claude 3/4 era $15/$75 with
cache reads at $1.50 against a real $0.50. Together they reported $1,025 for a session that cost
$127. The same line-counting bug sat in `scan_compaction`, where distances are compared against
`CYCLE_MIN_CALLS` — so a detector documented as firing at 15 calls apart was really firing near 7.

Hence Principle 6: an orchestrator's context is a tax on every remaining step, so a large read is a
recurring charge. Three consequences the skill did not previously draw:

- **Rotation is a practice, not a recovery path.** The tracker, brief files and plan document already
  exist to make an orchestrator replaceable; §9 treated that as insurance against compaction. Used
  deliberately at ~200K, it is the largest available saving.
- **The effort dial is a trap.** It is the most visible knob and worth ~3%. Turning it down buys
  almost nothing and makes every decision worse. Say so explicitly, because it is the first thing
  anyone reaches for.
- **Fan-out width is an intake problem.** Every open dispatch is a report that must be read, and
  intake is what grows the context. Width beyond what can be landed is deferred intake, not
  parallelism.

`orch cost` derives all of this from the harness transcript, so measuring costs no model tokens, and
the turn-end hook speaks only when a threshold trips — context, fan-out width, or a budget the human
set. It re-speaks only on a *new* condition or 1.5x growth: a hook that nags gets switched off, and
then it is worth nothing at the moment it would have mattered. Rates are an overridable estimate,
never stored as truth.

## 9d. Rotation as compaction; the front desk

**Compaction is the rotation mechanism.** It is what produced the $0.23 figure, and the harness
exposes its trigger point (`autoCompactWindow`, 100K–1M). Two things made it insufficient on its
own: it fired late, and the summary is a recollection of state. The fixes are a Paseo `session_open`
hook that sets the window to ~200K for Claude agents, and a `SessionStart` hook on `compact|resume`
that runs `orch resume` — roster, inbox state, plan document, front desk — printed from disk into the
fresh context. Nothing about the program depends on what the summary kept; Principle 1 applied to
compaction. Full agent replacement is the fallback for a summary that went wrong, not the routine.

**Hygiene gets one deterministic nudge.** By composition, 304KB of that orchestrator's context was
shell heredocs writing briefs and review documents inline — doc-writer work done at frontier tier
and then re-read forever. A `PreToolUse` hook notes any large `Write`/`Edit`/`Bash` input once per
cooldown. It never blocks, because the content is sometimes rightly the orchestrator's; it makes the
choice visible at the moment it is made.

**The front desk** is the pair pattern from the first design pass, revived with a cost justification
and a narrower job. Measured, a third of one session's human turns were routing — approvals, task
adds, status — at $5–20 each because a frontier orchestrator turned to answer them. An economy-tier
router takes those: it forwards verbatim to the orchestrator's inbox, answers status from files, and
relays the orchestrator's questions back. Its whitelist is the design; a cheap model that *helps* is
the failure mode, so it may not paraphrase, decide, spawn, or edit. The saving it produces directly
is second-order (~12% of that session). Its first-order value is structural: the human's chat surface
is no longer attached to the orchestrator, so the orchestrator becomes headless — no prose to
re-read — and can be compacted or replaced without the human noticing. It is phase-gated: the
frontier orchestrator plans in direct conversation, then *proposes* the front desk once the human's
messages have become routing, and sets it up as an ordinary dispatch. The human can always bypass it.

The tracker keeps one writer throughout. The front desk writes only to inboxes, which are
multi-writer safe by construction, and claims its own inbox in its own worktree.

## 9e. The status surface

Status has three audiences and they are not interchangeable: the human right now, this turn's
model, and *every later turn's* model. The third is the one that costs money — anything narrated
into a transcript is re-read as input on every subsequent call, and cache reads were 61% of the
measured bill in 9c. So the roster is not prose. It is chrome: a Claude Code `statusLine` command
and a Paseo composer pill, both of which the human reads and the model never sees.

**One collector, two adapters.** `orch statusline` renders from disk state only. `--format line` is
the terminal's; `--format json` is the GUI's, and it embeds the same rendered `line` so the two
surfaces cannot drift into disagreeing. Segments are subsettable (`--segments`), because a composer
pill has less width than a terminal, and the choice of what to drop belongs to the surface rather
than to a second formatter written in another language.

**It never fails loudly and it is often silent.** On any internal error it prints nothing and exits
0 — a renderer that reports its own failure into a status bar is a renderer the human switches off;
`--debug` raises instead. In a repo where no program has ever run it prints nothing at all. And
where several programs exist and none was chosen it says `pick --program`, the same refusal to guess
that `resolve_program` makes everywhere else.

**The expensive reads were already paid for.** The status line runs on *every* assistant message, so
it may not open a transcript — those are megabytes. `orch cost`, which the turn-end hook already
runs, now writes a per-target snapshot (`<program>/cost/<target>.json`, one writer per file) that
the renderer reads in microseconds. The snapshots carry their own age, so the line marks a stale
number rather than quietly reporting an old one: a dead hook becomes visible instead of invisible.
The borrowed agent-track count is TTL-cached the same way.

**The boundary with agent-track is one number.** That tool owns work items, gates and the critical
path; this surface owns lanes — who is dispatched, with what, waiting on whom, at what cost. They
overlap only in "items awaiting a human", which is fetched by running `track inbox --json`, never by
parsing `.track/`, and omitted entirely when the repo has no `.track/` or no `track` on `PATH`. The
surface is therefore useful in a repo that has never heard of agent-track, and additive in one that
has. Paseo's own `agent-monitor` plugin already renders a daemon-wide liveness roster, which is why
this one renders *intent* — dispatch entries, inbox depth, program spend, advisories — instead of a
second liveness list.

**Where the Paseo surface's shape came from.** A composer pill needs a `workspaceId` and an
`agentId`, and 0.8 hands a client callback both only from a slash command or a Command Center item.
There is no per-agent registration event, so a pill cannot appear by itself; `/orch` pins one. That
constraint agrees with the intent — status is worth composer space on the one or two agents actually
orchestrating, not on all fifteen lanes. The pill and its panel share one query key, so the panel
opens from the pill's cache and the two can never show different numbers at the same instant.

## 9f. Wake lifetime, and the view a turn cannot have

Observed: an orchestrator kept a liveness heartbeat running after its last lane closed, and looped.
Each firing re-derived state, found no worker, correctly did nothing, and returned. Every tick was
individually defensible; the waste existed only in the sequence.

Two distinct defects, and the fix for each is structural rather than advisory.

**A wake had no recorded lifetime.** A heartbeat insures one thing — the finish-notification of a
*running worker* — so its lifetime is the lifetime of the lanes it watches, not of the program or
the session. The substrate knows a heartbeat exists and when it next fires; it has no idea what it
was set up to watch. That binding is therefore non-derivable state, which by Principle 1 means it is
recorded: `wake.json`, one entry per wake, naming the entries it insures. Registration refuses a
lane that is not open, and `orch close` reports which wakes the close just orphaned — teardown
belongs in CLOSE beside deleting the tracker entry, for the same reason that deletion lives there.
Separate housekeeping is the category of work that gets deferred forever.

**The loop was invisible from inside a turn.** No per-turn agent gets the across-ticks view for
free, so it is kept on disk: a count of consecutive turn ends with an empty roster, raised by the
turn-end hook as `WAKE ORPHANED` (a registered wake with no live lane, first tick) or `IDLE LOOP`
(two consecutive no-change turn ends, which catches an unregistered wake). The counter is armed only
after the program's first close, so a pre-dispatch conversation never trips it, and it has exactly
one writer — the agent that claimed the program's inbox. Every other agent reads and leaves it
alone; an earlier cut let any worker's turn end reset the count, which would have erased the only
evidence that spans ticks.

Two design choices are worth recording because the first attempt got both wrong. Advisories are
**not** filtered by wake ownership: filtering silenced the detector in exactly the case it was built
for, an inherited or environment-owned heartbeat that nobody recognises as theirs. And the escape
hatch is explicit rather than a loosened rule — `--insures 'external:<what>'` for a wake watching
something the tracker cannot see, which trades the zero-lane rule for a staleness clock, plus
`orch wake hold --minutes N --reason R` for a genuinely idle session. A hold demands its reason,
because suppressing the only cross-tick detector is a decision the next session has to be able to
read.

## 10. Principles

1. Persist what cannot be re-derived; re-derive what can.
2. Write through, never write back — the record is a precondition, not a follow-up.
3. Reduce every writer set to one. Concurrency is designed out, not solved.
4. An unfalsifiable check is worse than no check.
5. Only do what only you can do. Emergent work gets the same decision as planned work.
6. Your context is a tax on every remaining step. A large read is a recurring charge.

Principles 1–3 generated most of the structure. Principle 4 is why the messaging table above was
measured rather than inferred — and the measurement overturned two assumptions, including one taken
from vendor documentation. Principle 5 was added after measuring a real program against the skill
and finding the skill silent on its largest cost.

## 11. Deliberate non-goals

- Plan and progress tracking (task-oriented state). Referenced if present, never required, never
  owned.
- Dispatch history and orchestration retrospectives.
- Reimplementing the substrate. A bundled script wraps a substrate operation **only** where the
  documented surface's default is unsafe or the capability is absent.
- An adapter for a substrate whose verbs cannot be verified. A documented gap beats a stub the
  detection step would route to.
