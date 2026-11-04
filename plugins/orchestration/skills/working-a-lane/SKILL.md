---
name: working-a-lane
description: Obligations of the agent currently working a lane for an orchestrator — the brief, the checkpoint, the report, the inbox. Use when your prompt has an `orch_entry:` line or names a brief to read.
# HOOKS: filled by the core lane (orch-working-a-lane.md W1).
---

# Working a lane

You are a worker on a lane: a tracked unit of work an orchestrator dispatched to you. This skill is
what you owe upward. What you may decide is in your brief. If you are also orchestrating children,
the `orchestrating` skill governs that half.

## 1. Read your brief

Your prompt's `orch_entry:` line names your entry; the brief is the file your prompt points at. Read
it first and obey its constraints, read set and write set. **Re-read it after any context loss,
compaction, or out-of-band instruction**, then resume from your checkpoint's next safe action. Do not
report completion until the original task is done.

**Done when:** you can state your task, write set and acceptance criteria without looking.

## 2. Keep your checkpoint

The brief's `progress_artifact` is your checkpoint. Chat history is never one. Append only facts a
fresh agent cannot re-derive. Update it after each milestone, at each `checkpoint_every_calls`
boundary, and immediately before a context-heavy read, rotation, compaction, or external mutation.
Relative paths resolve against your worktree. It must carry four labels, each a `Label:` line or a
`## Label` heading with real content:

- `Last durable milestone`
- `Verification`
- `Uncertain external effects` (`none` is valid)
- `Next safe action`

**Done when:** a replacement worker could continue from the file alone.

## 3. Drain your inbox

Messages from the orchestrator reach you through your inbox, not your chat. Drain it at every turn
end and whenever you finish a milestone (`orch inbox drain`, via the `orchestrating` skill's
scripts), and act on what it holds before continuing.

**Done when:** the inbox is empty at turn end.

## 4. Stop and report if the premise is wrong

If the brief's premise is false, a constraint contradicts the code, or finishing needs a file outside
your write set, **say so in your report instead of improvising**. Distinguish *wrong* from
*unverified* from *I would have done it differently*; only the first two matter. Concede or defend;
do not hedge. Never write to agent-track: the orchestrator advances plan items.

**Done when:** every deviation from the brief is in your report, not silently in the diff.

## 5. Report when finished

Report when the task is **finished**, not when you next have something to say. Complete it in one
run: waiting on a long command is work. A timed-out tool call is an infrastructure event, not a
result; re-issue it and say you did. If you cannot finish, say so and name what is incomplete; a
partial report shaped like a complete one is the failure.

**The contract binds every artifact you write, not only your reply.** Open your reply with a decision
block, at most 300 words:

1. **Verdict** — one line.
2. **What changed** — identifiers, one line each.
3. **Needs a human ruling** — one line each, or "none".
4. **Falsification** — what would have made this red, and did you observe it red? If you could not
   make it fail, say so; that is the finding.
5. **Numbers that matter** — only those crossing a threshold that changes a decision, each with the
   tree or configuration it came from and whether that tree could have gone red.

Put long-form detail in a file and give its path; do not paste analysis into the reply.

**Do the verification; do not narrate it.** Omit, in the reply and in every document: sub-threshold
measurements; test-suite contents (unless a suite needed loosening, a guard could not be written, or
something pre-existing broke); the adversarial pass (report its final state, noting only a scope
change or a newly surfaced unfixed issue); alternatives not taken beyond a real close runner-up; and
changelog narration, which is the result, never the path to it.

**Always surface:** anything needing a ruling; anything unverified or guessed; behaviour that changes
in the field; findings outside your scope that you did not fix.

### Evidence the orchestrator can verify

Cite landed work as `commit:<abs repo path>@<sha>`, optionally `,on=<ref>` to assert the commit is an
ancestor of that ref; a produced file as `file:<abs path>`. The orchestrator consumes the lane with
these, and a reference that does not resolve fails the consumption. Commit only as your brief says;
by default the orchestrator commits, with explicit paths.

**Done when:** your reply opens with the decision block, and every claim in it can be checked from
the paths and evidence you gave.
