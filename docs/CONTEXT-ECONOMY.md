# Design — `context-economy` plugin

Decision record for the plugin extracted from `orchestrating` on 2026-09-11. It captures what
moved, what deliberately did not, and the arguments that were settled along the way — including
the ones that reversed an earlier decision.

Status: **implemented 2026-09-11.** v0.1.0.

---

## 1. Why extract at all

`orchestrating` had accumulated cost machinery that was written for fan-out but is not *about*
fan-out. Fan-out only multiplies the stakes. Picking a model rung for a subagent, deciding whether
delegating beats doing the work inline, and keeping a session's context from filling with material
that will be re-read on every subsequent call are all true of a plain single-agent session, and
they were reachable only by loading a multi-agent framework.

The test applied was **what does the code depend on**, not which skill currently holds it. On that
test most of the cost surface depends on nothing but a transcript path and a rate table.

This was proved rather than assumed: `orch cost` and `orch compaction measure` were run in a bare
`/tmp` git repo with no program, no tracker, and no dispatch state, against a real transcript.
Both produced full output. The extraction was therefore a refactor, not a rewrite.

## 2. The seam

| Concern | Home | Why |
|---|---|---|
| Model rate table | `context-economy` | Single source of truth. `orch` now loads it from here. |
| Rung selection, archetype → rung | `context-economy` | Depends on the nature of the work, not on a program. |
| Delegate-vs-inline economics | `context-economy` | True of a one-off `Task` call. |
| Task contract (artifacts / consumption / falsification) | `context-economy` | Governs what a subagent produces and returns. |
| Context guards (heredoc, large input, large read) | `context-economy` | Session hygiene; no orchestration state involved. |
| Compaction floor and window safety | `context-economy` | A property of the session, not the program. |
| Brief front matter (worktree, tracker id, advances, review mode) | `orchestrating` | Meaningless without a dispatch tracker. |
| Fan-out advisory | `orchestrating` | Only applies to genuinely parallel execution. |
| Front-desk / relay handling | `orchestrating` | Multi-agent by construction. |

### Disagreements recorded

Three points where the extraction argument was pushed back on, and the outcome:

- **Seam C was originally classified as not portable.** That was wrong, and the correction was
  accepted. The classification had been made by *which skill owns the code today* rather than
  *what the code depends on*. Model-tier-to-work matching and delegate-vs-inline economics belong
  to every session.
- **Briefs were said to have no portable kernel.** Partly wrong. The front matter does not port,
  but the *consumption* field does, and it is the field that pays — it bounds what comes back, and
  what comes back is permanent context. It shipped in `references/contracts.md`; the rest stayed.
- **Fan-out was said to have no portable cousin.** It does not have one as fan-out, but its
  underlying question — "is this worth a separate context at all?" — is the delegate-vs-inline
  test, which shipped.

## 3. Rotation: proposed, narrowed, then dropped

Rotation (retire this session, start a fresh one with a handoff) was scoped, then cut entirely.
The reasoning is recorded because the conclusion is not obvious and the feature is tempting.

**Autocompaction beats rotation whenever the context is merely *large*.** Compaction is automatic,
needs no new agent, preserves the thread, and costs the human nothing — they never reattach to
anything. Rotation requires someone to manage handoff state, spawn the successor, and archive the
predecessor. For the large-context case, rotation is a worse version of something that already
happens for free.

That leaves rotation with exactly one case that compaction cannot serve: **bad context** — not
bulky, but *wrong*. Splitting that case decided the feature:

- **Type A, known-dead residue** — approaches that were tried and failed, work that has closed.
  Compaction can prune this, and prunes it better when steered. That is what
  `assets/compact-instructions.md` is for: collapse refuted work into the negative constraint it
  produced (not omit it — omitting causes the retry loop), and prune closed work down to its
  durable artifact.
- **Type B, unknown-bad framing** — a false premise currently believed. Compaction *launders*
  this: the summarizer runs on the same context, holds the same premise, and re-emits it as an
  authoritative line with the refuting evidence dropped. Rotation does not fix it either, for the
  same reason — a handoff written by the holder of the premise carries the premise.

The answer to Type B is a **clean context that never held the premise**, which is a subagent, not
a new session. That is §4 of the skill: the premise audit, with `Premise auditor` in the archetype
table and falsification named up front so the auditor does not simply agree.

So rotation's remaining case was one the agent is unlikely to self-identify (you do not know which
of your premises is the false one — that is what makes it Type B), and where the correct remedy is
something else entirely. It earns no place. `spend rotate` and the rotation skill were dropped.

`rotation_advisory` in `orch.py` is unrelated and stays: it detects dangling predecessors across
agents, which is a multi-agent liveness concern that happens to share a word.

## 4. Context footprint is itself a cost

A plugin whose purpose is reducing context cost must not be a context cost. Two rules, both
enforced mechanically by `spend footprint`:

- **Standing cost** — the skill description sits in context every turn. Budget 250 tokens for the
  plugin's whole standing footprint; measured **52**. The skill description is 36 words of pure
  triggers, against the 99-word description `orchestrating` carried before this work (154 tokens,
  trimmed in the same change).
- **Per-fire cost** — hook output is permanent for the session: a one-time good sold on a
  recurring contract. Budget 40 tokens for the worst single hook fire; measured **34**. Hooks are
  therefore pointers, not essays — each names the problem in one line and ends with
  `spend why <topic>`. All rationale lives in the `WHY` dict and is fetched only when wanted.

`spend footprint` is a real check with a pass/fail, so the budget survives future edits.

## 5. Implementation notes

**Rates are single-sourced.** `orch.py` no longer holds `DEFAULT_RATES`; it loads `spend.py` as a
module through a search path (`SPEND_SKILL_DIR` → `$CLAUDE_PLUGIN_ROOT/../context-economy` →
sibling in a source checkout → `~/.claude/plugins` → `~/.agents/plugins`) and layers its
per-program `rates.json` on top. Agreement is verified: `steps orch=25 spend=25`,
`cost orch=0.3555 spend=0.3555`.

**The dependency fails loudly.** If `spend.py` cannot be found, `orch cost` raises with an
instruction to install the plugin or set `SPEND_SKILL_DIR`. A silent fallback to a stale local
rate table would produce confident wrong numbers, which is worse than no numbers.

**Hooks never fail a turn.** `main()` swallows `SpendError` and returns 0. A cost tool that breaks
the session it is measuring has cost more than it saved.

**State is keyed by repo, not by program**, at `~/.local/state/context-economy` — because there is
no program in the general case. `repo_key()` uses `git rev-parse --show-toplevel`, falling back to
a hashed realpath.

**Rungs, not model names.** `minimal` / `economy` / `default` / `frontier` are relative to the
provider and stay correct as models turn over; names rot. The anchor is `economy`, not `default`,
because `default` drifted from Sonnet-class to Opus-class and cost $616 against a measured $246 —
an anchor that moves under you is worse than no anchor.

**`..` through a symlink is kernel-resolved.** The hook fallback path needs `../..` from a linked
skill directory to reach the plugin root, because the kernel resolves the symlink before applying
`..`. The `spend install` path is immune — it bakes in `os.path.realpath(__file__)` at install
time.

## 6. Always-on

`spend install` writes the four hooks into `~/.claude/settings.json`, marked with
`context-economy` so a re-run replaces only its own entries. `--uninstall` and `--dry-run` are
supported. This is the answer to "an always-applicable default for all sessions": installing the
plugin gets the skill; running `spend install` gets the hooks everywhere, including repos that
have never heard of this marketplace.

## 7. Deferred

Recorded so they are not silently lost.

- **Compaction loop detector.** `spend compaction check` warns on a window set below ~3× the
  session floor, which is the condition that causes a compaction *loop* — the session hangs rather
  than erroring, which is why it is worth detecting. An actual loop *detector* (observing repeated
  compaction events and concluding) is deliberately not shipped: it needs tuning against real data,
  and shipping an untuned detector is exactly the mistake the archetype table already made once.
- **Session state / constraints file and `spend resume`.** Writing rulings, negative constraints
  and artifact paths somewhere durable as they happen is what makes compaction safe to be
  aggressive with — see the trust note in `assets/compact-instructions.md`. Nothing implements it
  yet.
- **`spend report`.** A session-level cost report for the non-orchestrated case. `orch`'s
  session-report is currently the only thing that produces one, and it needs a program.
