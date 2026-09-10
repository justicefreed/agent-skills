# Front desk — a cheap router between the human and the orchestrator

Once a program is executing, most of what the human says is routing: *approved*, *add a task for X*,
*did you see my review*. Measured, a third of one session's human turns were that, and each cost
$5–20 because a frontier orchestrator carrying hundreds of thousands of tokens turned to answer it.

A front desk is an economy-tier agent that takes those turns instead. It is not a helper and not a
second orchestrator. It is a **router with a whitelist**, and everything about its design exists to
keep it from becoming more than that.

## When to propose it

The orchestrator proposes; the human decides. Propose when all three hold:

- the plan document exists and the first wave of dispatches is out;
- the last several human messages were approvals, task adds, or status questions, not decisions;
- you expect the program to run long enough that the saving is real — a couple of hours or more.

Do **not** propose it during planning. Planning is a conversation, and a router in the middle of a
conversation loses meaning and adds latency. Say plainly that the human can open you directly at any
time; the front desk is a convenience, not a gate.

## Setting it up

The front desk is an ordinary dispatch: brief, record, spawn. Its brief is
`../assets/FRONTDESK-BRIEF.template.md`, and it should stay short — the template already carries the
contract, so the brief fills in names and paths.

1. **Give it its own worktree or workspace.** Inbox claims are per worktree, and it must not share
   yours. It writes nothing to the repo, so the worktree is read-only in practice.
2. **Write the brief, `orch open` it with `archetype: frontdesk`, spawn at the economy rung and
   lowest effort.** It reads a few files and relays text. Nothing about that needs a capable model,
   and a capable model here is the risk, not the safeguard.
3. **Record it**: `orch frontdesk --set frontdesk --agent-id <id>`. `orch resume` will then remind a
   compacted or rotated orchestrator that the human is reachable only through it.
4. **Tell the human where to go**, in one line, and stop narrating to your own session. From this
   point your questions to them travel through the inbox.

**Done when:** the front desk has claimed its inbox, the human has been pointed at it, and
`orch frontdesk` names it.

## What the front desk may do — the whitelist

| Human says | Front desk does |
|---|---|
| approval, denial, revision, an answer to a question | `orch inbox send --to root --from human --kind <approval\|answer\|correction>` with the text **verbatim** |
| add a task, change a priority, a new constraint | same, `--kind task` or `--kind correction`, verbatim |
| what is running / blocked / next | answer from `orch roster`, the plan document, the tracking tool if the repo has one. **Never asks the orchestrator.** |
| anything else — a design question, a request to change approach | forward verbatim as `--kind question`, and say it has been forwarded |

And on the other direction: every item the orchestrator sends to the front desk's inbox is relayed to
the human, verbatim, marked as coming from the orchestrator.

**Never:** paraphrase, summarise, decide, spawn a worker, edit a repo file, send a prompt into the
orchestrator's running turn, or answer a question it would have to think about. The failure this
prevents is specific — a cheap model helpfully resolving something it should have forwarded, so that
the human believes the orchestrator ruled when it never saw the question.

**Waking the other side.** Appending to an inbox delivers at the target's next turn end. If the
target is idle there is no next turn, so after appending, check the substrate's status and, only if
idle, send exactly the text `Drain your inbox.` — nothing else. That is the one prompt the front desk
may send directly, and the one prompt the orchestrator may send it.

## The orchestrator with a front desk

You are now headless. Three things change:

- **Input arrives only through your inbox**, tagged `from human`. Treat it as authoritative — it is
  the human's words, unparaphrased.
- **Questions to the human go out as inbox items**: `orch inbox send --to frontdesk --kind question`.
  Then continue with whatever does not depend on the answer. Do not wait in a turn.
- **Stop narrating.** There is nobody in your session to read it, and prose is re-read on every later
  call. Status lives in the plan document and the tracker; the front desk reads it from there.

If the human opens your session directly anyway, their message is authoritative and the front desk
keeps running. Nothing needs to be torn down for the human to bypass it.

## Cost watch and replacement

The front desk runs `orch cost --for root` when it has nothing else to do — after each relay is
enough — and tells the human when an advisory appears. Compaction handles the ordinary case on its
own. Replacement is for when it does not: an orchestrator that is confused after compaction, or a
budget the human has decided to stop at.

The replacement procedure, driven by the front desk on the human's say-so:

1. `orch inbox send --to root --kind correction --body "ROTATE: land and close what is finished,
   patch the plan document, write a handoff note to <path>, then send 'HANDOFF READY' to frontdesk."`
2. On `HANDOFF READY`, spawn a fresh orchestrator on the handoff note with the orchestrating skill,
   in the **same** worktree the old one used. Its `orch inbox claim --as root --force` takes over the
   inbox; queued items are preserved because the log and cursor never moved.
3. Close the old orchestrator. Two orchestrators on one program is the split-brain `state.md`
   designs against.
4. Tell the human in one line.

This is rarely needed. The measured saving comes from compaction firing early; replacement is the
fallback for when a summary has gone wrong, and the front desk exists so that fallback costs the human
nothing.

## Without Paseo

On a CLI harness the front desk is a second interactive session on an economy model, started in its
own worktree with the brief as its first prompt. The human types there. Native peer messaging between
local sessions queues race-free, so `Drain your inbox.` may be sent that way without an idle check.
