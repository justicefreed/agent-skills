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
   deliberately instead of waiting for it. A rotation at ~200-300K would have held most of that
   session near $0.30 a call instead of drifting to $1.35 — and the sessions that went wrong went
   wrong in the other direction, peaking at 731K-899K with no compaction at all. See "Rotating" below.
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

## Rotating — compaction, made early and lossless

Compaction already *is* rotation: it is what dropped that session from $1.35 to $0.23 a call. The
only thing wrong with it was timing — the harness waited until the window was nearly full, so the
session spent five hundred calls in the expensive band first — and the fact that the summary is a
recollection of state rather than the state itself. Both are fixed without a new agent.

**Make it early.** The harness's auto-compact window is configurable from 100K to 1M tokens, and it
otherwise waits until near the model's limit. But the window is not a free dial, and the failure mode
at the bottom of the range is worse than the cost at the top.

Every session has a **context floor**: the system prompt, tool schemas, the skills list, `CLAUDE.md`,
memory, session-start hook output, and — after the first compaction — the summary. Measured across
one machine's transcripts, floors ran **7K to 97K at session open (p90 50K)** and **39K to 63K
post-compaction**. Set a window that is not comfortably above the floor and the session compacts,
lands back at or above the trigger, and compacts again. It does not error; it hangs. In the observed
cases sessions compacted at model call 4, 6 and 11, and one compacted at call 11 and then made no
further model call at all.

So the rule is **relative, not absolute**: keep the window at roughly **three times the measured
floor**, and never below 200K.

```bash
orch compaction measure     # this session's floor, peak, and the window it should use
orch compaction check       # the loop detector; this is what the session-start hook runs
```

| Where | How |
|---|---|
| Paseo-hosted agents | the bundled `assets/paseo-inbox-plugin/` asks `orch compaction window` at session open and sets `CLAUDE_CODE_AUTO_COMPACT_WINDOW` only if a safe number comes back. Providers `claude` and `claude-cursor` (Claude Code over the Cursor bridge); `cursor` is Cursor's own agent and has no such setting. It raises an inherited window and never lowers one — **Paseo injects 200K of its own**, which is under 3x the worst floor measured. `ORCH_AUTOCOMPACT_WINDOW=` empty disables |
| Claude Code CLI | `/autocompact 300k` in the session, or `autoCompactWindow` in `.claude/settings.json` |

Three safeguards sit behind that, because a bad window breaks agents silently:

- **Only long-lived roles get one.** `orch compaction window` answers for a worktree whose inbox
  claim is `root`, `frontdesk` or an integrator (`ORCH_AUTOCOMPACT_ROLES`; `--any-role` overrides),
  and exits 3 otherwise. A worker carries a small context and dies with its task, so an early window
  saves it nothing and costs it a half-finished task.
- **Nothing unmeasured gets a tight number.** With no measurement the answer is **300K**, which
  clears the worst floor observed. `orch compaction measure` records the real floor, and the
  recommendation is then `max(3 × floor, 200K)`, clamped to the harness's range and rounded to 50K.
  A recorded floor only ever grows.
- **The loop is detected, not just avoided.** The session-start hook runs `orch compaction check`,
  which scans the transcript for compactions less than 15 model calls apart and for a window with
  less headroom than the floor warrants. It says nothing on a healthy session. It cannot fix one from
  the inside — the window is read at launch — so it names the number the *next* session needs.

Note the direction of the token argument: a lower window means a lower average context and a cheaper
session, so cost pressure and loop safety pull against each other. Three-times-floor is a **lower
bound for safety**, not a target to sit on. Do not lower it to save money; the saving is small and
the failure is a hung agent.

**Make it lossless.** This skill's front matter registers a session-start hook on `compact` and
`resume` that runs `orch resume`: the roster, the inbox state, the plan document path, and the front
desk if one exists, printed from disk into the fresh context. Nothing about the program's state
depends on what the summary chose to keep. Add a `# Compact instructions` section to the repo's
`CLAUDE.md` if there is conversational state worth steering the summary toward — rulings mid-flight,
a decision the human made but that has not landed in the plan document yet.

**Before compacting, if you have the choice**, do the two things a summary cannot: land and close
what is finished, and patch the plan document with anything ruled but not yet written down. Then
compact at a seam rather than mid-request.

**Full replacement** — a fresh agent on a handoff note — is the fallback for when a summary has gone
wrong, not the routine. It has its own protocol, because a predecessor cannot verify its own closure
and must not try: see `rotation.md`. With a front desk in place (`frontdesk.md`) it costs the human
nothing, because their chat surface was never attached to you.

## Hygiene rules, with the numbers that justify them

Measured composition of what one orchestrator wrote into its own permanent context:

| Source | Size |
|---|---|
| Shell heredocs over 2KB — briefs and review docs written inline | 304KB in 62 writes |
| Prose to the human | 111KB in 150 messages |
| Worker launch prompts | 31KB in 53 spawns |

Four rules follow, each checkable:

1. **Anything longer than a paragraph is authored by a worker.** A brief is a short delta on the
   template and the standing rules. A review document belongs to the lane that did the work. A plan
   patch is a doc writer's job with the ruling handed over verbatim. The PreToolUse hook in this
   skill's front matter says so at the moment a large input is about to land, once per ten minutes
   (`ORCH_GUARD_BYTES`, `ORCH_GUARD_COOLDOWN`). It never blocks; sometimes the content is rightly
   yours.
2. **Independent tool calls go in one message.** Each model call re-reads the whole context. Median
   twelve calls a turn, maximum sixty-one; every one avoided is the full context size saved.
3. **Large reads happen in a worker.** The worker's context dies with it. Yours does not.
4. **Status goes to files, not to chat.** During execution, tell the human what changed in a line or
   two and put the rest in the plan document. With a front desk, say nothing in your own session at all.
