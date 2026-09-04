# Worker standing rules — <program name>

**Binding on every subagent in this program.** Briefs reference this file instead of restating it.
If a brief contradicts this file, the brief wins for that task only, and it must say so explicitly.

> **How to use this template.** It carries the *project-specific* half of the orchestration rules —
> the facts a generic skill cannot know. The universal half (report shape, verification discipline,
> messaging, closeout) lives in the `orchestrating` skill and must **not** be copied here; briefs
> reference both.
>
> Fill each section by interviewing the human and reading the repo. **Delete a section rather than
> leaving it speculative** — a rule nobody verified is worse than an absent one, because workers
> will follow it. Every entry should be a fact someone has observed, ideally with the evidence.
>
> This file is the single source for these rules. When one is corrected, correct it *here* — the
> reason this file exists is that a corrected constraint otherwise has to be hand-carried into every
> future brief, which is exactly how a stale rule ships.
>
> **Migrating an existing standing-rules document into this structure:** map it **rule by rule, not
> section by section.** Number every rule in the old file; for each one record either "now covered by
> skill reference `<file>`" or "retained in section N". A rule mapping to neither is a **gap in the
> skill** — surface it and keep the rule here until it is upstreamed. Then state the rule count
> before and after.
>
> The count is the check, and it is the only one available: a migration that quietly drops a rule
> produces a shorter, better-reading file either way, so success and failure look identical without
> it. Section-level mapping reliably loses the rules that sit inside a section whose *heading*
> matches something the skill covers — which is exactly where the losses hide.

---

## 1. Build and verification commands

<The exact commands. Include flags that are load-bearing and say why.>

- Build: `<command>`
- Test: `<command>`
- Format: `<command>` — and **which files the formatter must never touch**, with the reason.
- Preprocessing or codegen steps that must run first.

**Parallelism and resource limits.** <Does the build tolerate parallel jobs? Do concurrent builds
fail, and how does that failure *present*? An infrastructure failure that looks like a code failure
belongs here, because it wastes whole dispatches when misread.>

**Capacity gate.** <The exact check for "is it safe to start heavy work now", and the patterns that
must NOT be used because they self-match or match stale processes.>

**What "clean" means.** <Which directories must be wiped, by explicit name. Note anything a naive
clean does *not* remove.>

## 2. What to surface, and what to suppress

<The human's output-verbosity preferences for this program. Which measurements matter and at what
threshold; what counts as actionable. Default: suppress numbers that cross no decision threshold,
suppress test-suite contents unless a test needs attention, treat an adversarial pass as part of
drafting rather than a deliverable.>

**Thresholds that change a decision:**

- <metric> — <floor/ceiling, and what it means to cross it>

## 3. Isolation and ownership

- Worktree layout: <where lanes live>
- **Never-touch list:** <paths, branches, caches belonging to a human's own checkout or to another
  lane — the things that must survive any cleanup>
- Files under human management: <e.g. sign-off state, revision markers — say who owns them>
- <Any file that is an append-only list, and therefore conflicts when changes land out of order.
  State the resolution rule.>

## 4. Formatting and file conventions

- <Files the formatter reflows destructively — name them and say what happens.>
- <Vendored vs submodule directories, and which are excluded from tooling.>
- <Ordering conventions that are not obvious from the file (e.g. tables ordered by wire value, not
  alphabetically).>
- <Anything that must be bumped exactly once per release rather than per change.>

## 5. Known traps

<The ones that have actually bitten. For each: the symptom, the cause, and the remedy. Prefer
concrete evidence over general caution — "X presents as Y, the cause is Z" beats "be careful with X".>

- **<Symptom>** — <cause> — <remedy>

## 6. Do not

<Short, blunt list of the things that have gone wrong before.>

---

## Maintenance

Add a rule here the first time it has to be explained twice. Remove one when it stops being true —
and when you remove it, say so in the commit, because workers may still be running with the old
version in their context.
