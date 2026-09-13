---
name: delegating-economically
description: Pick the model rung for a subagent, decide whether delegating beats doing it inline, and write a task contract. Use when spawning a subagent, choosing a model tier, or auditing a premise with a clean context.
---

# Delegating economically

Your context is re-read on every model call. That single fact decides all three
questions below, and it decides them differently from how intuition does.

Measured over four days of one machine's transcripts — 16,156 calls, ~$1,140:
cache reads were **55%** of the bill and reasoning a few percent. Cost per call
against context carried, over 9,138 Opus calls:

| Context carried | $/call |
|---|---|
| under 100K | $0.077 |
| 200–300K | $0.152 |
| 400–500K | $0.271 |

Run `spend cost` for this session's numbers. Everything below is on disk, so
asking costs no model tokens.

## 1. Delegate, or do it inline?

The usual comparison — dispatch overhead against the size of the task — omits
the term that dominates. **What a task leaves in your context is charged again
on every remaining call of the session.** A 20K tool result read once is 20K
re-read a few hundred times.

A subagent carries a small context and dies at the end of its task, so its
cache-read tax never accumulates. Yours does.

**Delegate when the work produces more than it concludes:**

- reading anything large — a file, a log, a diff, a dependency tree
- searching broadly when you need the answer, not the matches
- authoring a document: a plan, a review, a report, a spec
- a mechanical sweep across many files
- **auditing a premise you can no longer see around** (see §4)

**Do it inline when** the result *is* the residue — a targeted edit, a short
read you will quote, or work needing context a subagent cannot cheaply be given.

Composition of one measured session's own context: 35% tool results, 29% its own
tool-call text, 32% its own prose and reasoning, **4% subagent reports**. The
expensive part was self-inflicted, not imposed by delegation.

## 2. Which rung?

Choose a **rung**, then resolve it to a live model at spawn time. Rung names
describe stable capability and cost positions; model names rot when the provider
ships.

| Rung | Meaning |
|---|---|
| **frontier** | the provider's most capable. **Escalation only** — never a starting point |
| **advanced** | above the everyday tier for complex, interconnected, or long-running work; below frontier |
| **economy** | cheaper and faster; "good for everyday tasks". **The anchor** |
| **minimal** | the cheapest that can do the job at all |

The **provider default is not a rung**. It is an implicit selection made when no
model is supplied, and it may drift to any rung. At session start, identify the
actual selected model and map it to a rung before relying on its cost or
capability. At subagent spawn, set the intended rung or its current model
explicitly. Do not treat an omitted model as `advanced`. In one observed drift,
the provider default moved from a Sonnet-class model to an Opus-class one with
no rename; 6,509 subagent calls cost **$616 where the same tokens one rung down
cost $246** — 39% of a four-day bill, from a choice nobody made.

**Start at `economy` and escalate on evidence.** Evidence can be known before
dispatch: use `advanced` when the task spans subsystems, has a long chain of
dependent steps, or would be expensive to restart after a weak pass. It can
also arrive from a failed economy pass. Of 31 measured subagent tasks run one
rung above the anchor, 28 finished correctly on the first attempt — so do not
choose `advanced` merely because it sounds safer. Reserve `frontier` for an
observed capability limit or an explicit human request.

Full archetype table — which kind of work sits on which rung, and what triggers
an escalation — in `references/rungs.md`. Before dispatch, run
`spend models --archetype <name>` or `spend models --rung <rung>` to intersect
that policy with the harness's live catalog and get exact spawnable model slugs.

**Check the cache-read column before assuming a cheaper-sounding model is
cheaper.** Cache reads are the majority of a real bill and their ordering is not
the headline ordering: moving 580 measured Fable calls to Opus would have *saved
$0.26*. `spend rates` prints the table.

## 3. The task contract

Three lines. Without them a subagent returns prose instead of work, and the prose
lands in your context permanently.

- **Artifacts** — what must exist when it is done. Paths, not adjectives.
- **Consumption** — how you will use the result, which *bounds what comes back*.
  This is a cost control, not a style note: it is why subagent reports were only
  4% of the measured context.
- **Falsification** — what would show the work is wrong. A check nobody can fail
  manufactures confidence.

A field answered "unknown" is an omission wearing a costume. Details and worked
examples in `references/contracts.md`.

## 4. When your own context has gone bad

Two different problems wear the same clothes:

**Known-dead residue** — you tried X, it failed, you know it failed. This is
bulk, not poison: it costs money and dilutes attention but misleads nobody.
Compaction handles it, and `assets/compact-instructions.md` makes compaction
prune it properly.

**Unknown-bad framing** — you believe P, P is wrong, and nothing in your context
marks P as suspect. Compaction cannot fix this and will make it worse: it
*launders* the bad premise into an authoritative summary with the evidence
dropped. You cannot self-diagnose it either, because the diagnosis runs on the
same premise.

So don't try. **Delegate the audit to a clean context**: hand a subagent the
claim and the evidence, and ask whether it holds. Economy rung — you are buying
independence, not capability. If it comes back refuted you now hold a *known*
refutation, which is the first problem, which compaction already handles.

You do not need to replace your session to get an unpoisoned opinion. You need
to ask something that does not share your context.

## Hygiene, with the numbers behind each

1. **Anything longer than a paragraph is authored by a subagent.** Heredoc-written
   documents were 304KB across 62 writes — the largest self-inflicted item
   measured.
2. **Independent tool calls go in one message.** Each model call re-reads
   everything. One measured session ran a median of 12 calls per turn, max 61.
3. **Large reads happen in a subagent.** Its context dies; yours does not.
4. **Status goes to files, not chat.** Prose to the human: 111KB across 150
   messages.

`spend why <topic>` prints the evidence for any of these on demand — deliberately
not inline, because a rationale in your context is billed on every later call
and persuades only once.
