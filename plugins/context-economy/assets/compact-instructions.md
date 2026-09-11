# Compact instructions

Copy this into a `# Compact instructions` section of a repo's `CLAUDE.md`. It
steers what a compaction summary keeps, and it is the cheapest context lever
available — it runs automatically, needs no new agent, and the human never has
to reattach to anything.

Two transforms. Both exist because the default summary preserves the *shape* of
the conversation rather than its *result*.

---

## Compact instructions

**Collapse refuted work into the constraint it produced — do not simply drop
it.** An approach that was tried and abandoned should survive as one line naming
what failed and why, not as the narrative of trying it, and not as nothing:

> ❌ 400 lines of attempting X, hitting Z, backing out
> ❌ (omitted entirely)
> ✅ `X was tried; fails because Z. Chose Y.`

Dropping it entirely is worse than keeping it. Without the negative constraint a
later turn re-proposes X, re-tries it, and re-fails — the agent-in-circles
failure, engineered deliberately.

**Prune work that closed, keeping the pointer to its durable record.** Where work
landed in a commit, a written file or a passing test, the deliberation about it
is redundant with a better record: the artifact is auditable and the conversation
about it is not. Keep the SHA, the path, or the test name and the ruling; drop
the deliberation.

Anchor this to artifacts that actually exist — a commit SHA, a file path, a test
that runs — rather than to an impression that something felt finished. "Seems
done" is a judgment; `git log` is a fact.

**Keep, always:**

- rulings the human made, and anything they explicitly asked for
- negative constraints from the collapse above
- open threads, and what the next action on each one is
- paths to artifacts produced this session

**Drop, freely:**

- tool results whose conclusion has already been recorded
- your own narration of what you were about to do
- superseded plans, once the ruling that superseded them is kept
- successful deliberation whose outcome is now in a commit

---

## What this cannot do, and why it matters

These instructions prune **known-dead** residue: work you know failed, work you
know closed. That is most of the volume, and pruning it is a large and automatic
win.

They cannot prune **unknown-bad framing** — a premise you believe that happens to
be false. The summarizer runs on the same context and holds the same premise, so
it will carry the error forward as established fact, now compressed into an
authoritative-sounding line with the evidence that might have refuted it dropped.
Compaction makes that case *worse*, not better.

The answer to that case is not a better summary. It is a second opinion from a
context that never held the premise — see §4 of the `delegating-economically`
skill.

## A note on trust

The steering above is advisory: the summarizer honours it as an instruction, not
as a guarantee. So do not let anything load-bearing depend on it. Write rulings,
constraints and artifact paths somewhere durable as they happen, and compaction
becomes free to be as aggressive as you like — because nothing important is
riding on what the summary chose to keep.
