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

## 10. Principles

1. Persist what cannot be re-derived; re-derive what can.
2. Write through, never write back — the record is a precondition, not a follow-up.
3. Reduce every writer set to one. Concurrency is designed out, not solved.
4. An unfalsifiable check is worse than no check.

Principles 1–3 generated most of the structure. Principle 4 is why the messaging table above was
measured rather than inferred — and the measurement overturned two assumptions, including one taken
from vendor documentation.

## 11. Deliberate non-goals

- Plan and progress tracking (task-oriented state). Referenced if present, never required, never
  owned.
- Dispatch history and orchestration retrospectives.
- Reimplementing the substrate. A bundled script wraps a substrate operation **only** where the
  documented surface's default is unsafe or the capability is absent.
- An adapter for a substrate whose verbs cannot be verified. A documented gap beats a stub the
  detection step would route to.
