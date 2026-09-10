# Cost — where an orchestration program's money actually goes

Measured from one three-hour program's transcripts, 1,632 model calls, about $1,100 estimated.
Numbers here are that program's; the *shape* generalises, and it is not the shape most people expect.

## Where the money went

| Component | Share |
|---|---|
| Cache reads — re-reading the context on every model call | 61% |
| Output tokens | 16% |
| Cache writes | 23% |
| Fresh input tokens | ~0% |

Of the output, **reasoning was 21%** — so thinking tokens were about 3% of the total bill.

**Do not reach for the effort dial to save money.** It is the most visible knob and nearly the least
significant, and turning it down buys a 3% saving by making every decision worse. The same is true of
model choice *for the orchestrator*: it is the number of calls and the size of the context that
decide the bill, not the price per token.

## The finding that matters

The same orchestrator, doing the same kind of work, at three points in one session:

| Phase | Context carried | Cost per model call |
|---|---|---|
| Early | 118K | $0.42 |
| Late, before auto-compaction | 668K | $1.35 |
| After auto-compaction | 88K | $0.23 |

**An orchestrator's context is not a private convenience. It is a tax on every remaining step of the
program.** A 20K tool result read once is 20K re-read on every subsequent call — a dozen calls a turn,
hundreds of calls a session. Read it at 600K of context and it costs six times what it costs at 100K.

This inverts the usual intuition about delegation. "Cheaper to just do it inline" compares the
dispatch overhead against the task, and ignores the term that dominates: what the task's *residue*
charges every future step. That is the real content of Principle 5.

By composition, that residue was **35% tool results, 29% the orchestrator's own tool-call text, 32%
its own prose and reasoning, and only 4% worker notifications.** The context that made the program
expensive was almost entirely self-inflicted, not imposed by the workers.

## Levers, in order of measured effect

1. **Rotate the orchestrator on purpose.** This skill already treats orchestrator death by
   compaction as routine and makes recovery work: tracker, brief files, plan document. Use that
   deliberately instead of waiting for it. A rotation at ~200K would have held most of that session
   near $0.30 a call instead of drifting to $1.35. See "Rotating" below.
2. **Never read anything large into the orchestrator.** Delegate the read and take back a
   conclusion. The existing rule says this to avoid "context pollution", which undersells it: a big
   read is a recurring charge, not a one-off.
3. **Fewer steps per turn.** Each step re-reads the whole context. That session ran a median of 12
   model calls per turn and a maximum of 61. Independent tool calls issued together are one step
   instead of several; the saving is the full context size per call avoided.
4. **Keep large text out of tool-call arguments.** Writing a brief through a shell heredoc puts the
   whole brief in context as tool-call text, then again if anything reads it back. Write files with a
   file-writing tool and refer to them by path.
5. **Close entries promptly, and keep fan-out narrow enough to consume.** Every open dispatch is a
   report you must eventually read, and intake is what grows the context. Width past what you can
   land is not parallelism, it is deferred intake.

Worth knowing about the other side: a **worker** carries a small context and dies at the end of its
task, so its cache-read tax never accumulates. Cheap workers and an expensive orchestrator are the
same fact seen twice — which is why moving work out is a bigger saving than making the work cheaper.

## Measuring, and being told

```bash
orch cost                      # this session: calls, context, $/call, share by component
orch cost --json               # the same, for a script
orch budget --set 150          # a limit for this program, in USD
```

`orch cost` reads the harness transcript directly, so it costs no model tokens, and it works on any
past transcript with `--transcript <path>` if you want to audit a program that already ran.

The skill's turn-end hook runs `orch cost --format hook` and speaks **only** when a threshold trips:

| Advisory | Default trigger | Override |
|---|---|---|
| Context, plan a rotation | 250K | `ORCH_CONTEXT_WARN` |
| Context, rotate now | 400K | `ORCH_CONTEXT_URGENT` |
| Fan-out too wide to consume | 8 open dispatches | `ORCH_FANOUT_WARN` |
| Budget | 75% and 100% of the limit | `orch budget --set` |

It repeats itself only when a *new* condition becomes true or the context has grown by half again,
because a hook that nags on every turn gets switched off — and then it is worth nothing at the moment
it would have mattered.

Rates are an estimate for advisory purposes, not a bill. Override them with `ORCH_RATES` as JSON or a
`rates.json` in the program directory rather than editing the script, so a price change is not a code
change.

## Rotating

When the advisory fires, and before the human's next big ask rather than in the middle of one:

1. **Land and close what is finished.** A rotation with open, unconsumed entries hands the next
   orchestrator work it cannot describe.
2. **Patch the plan document with anything ruled but not yet written down.** This is the only state
   that cannot be re-derived, and it is the whole reason rotation is safe.
3. **Write a handoff note** naming the program, the tracker id, the plan document, what is in flight,
   and any ruling too fresh to have landed anywhere else. Where the harness offers a handoff skill,
   use it rather than inventing a format.
4. **Start a fresh orchestrator on the note**, and have it reconcile before acting — tracker, then
   substrate, then the operating system, per `liveness.md`. Its first act is `orch inbox claim`.
5. **Close the old session.** Two orchestrators driving one program is the split-brain that
   `state.md` designs against.

Rotation is not failure recovery. It is the cheapest thing in this file, and the only one that
resets the tax rather than slowing its growth.
