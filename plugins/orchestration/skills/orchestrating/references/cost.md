# Cost — where an orchestration program's money actually goes

Measured across four days of one machine's transcripts: **16,156 model calls, about $1,140** at the
rates in `orch.py`. The *shape* generalises, and it is not the shape most people expect.

## Where the money went

| Component | Share |
|---|---|
| Cache reads — re-reading the context on every model call | 55% |
| Output tokens | 24% |
| Cache writes | 21% |
| Fresh input tokens | ~0% |

Those 55% are **1.66 billion** cache-read tokens. Of the output, **reasoning was around a fifth** —
so thinking tokens were a few percent of the total bill.

**Count responses, not transcript lines.** The harness writes one line per content block, so a
response holding thinking + text + tool_use is three lines, each repeating the same `usage` object.
An earlier version of `orch cost` summed lines and reported 1,592 calls for a session that made 714
— a 2.23x overstatement, on top of a rate table three model generations stale. Together those made
it report $1,025 for a session that cost $127. If you are computing this yourself, deduplicate on
`requestId`.

**Do not reach for the effort dial to save money.** It is the most visible knob and nearly the least
significant, and turning it down buys a few percent by making every decision worse.

**Model tier is the exception, and it applies to workers, not to you.** An earlier version of this
file lumped model choice in with effort as a knob not worth turning. That is right for the
orchestrator and wrong for the fleet, and the difference is large enough to matter: in the measured
four days, 6,509 Opus calls in lane worktrees cost $616, and the same tokens on Sonnet 5 would have
cost $246 — **$370 from one default**, against $97 for the orchestrator's own calls and 11.6% for
capping every context at 120K. Tier multiplies the cache-read tax rather than replacing it, so it
compounds with every other lever here instead of competing with them.

Check the direction before assuming a cheaper model is cheaper, though. Fable 5.1 prices cache reads
at $0.25/MTok against Opus 5's $0.50, so moving 580 Fable calls to Opus would have *saved $0.26* —
nothing. Read the cache-read column, not the headline input/output price, because cache reads are
the majority of the bill.

See `delegation.md` for which lanes earn a frontier tier and how a lane escalates when the cheap
tier is visibly failing.

## Replay-envelope guardrails

Context-token warnings are not byte telemetry. The skill cannot measure the serialized replay
root before Cursor does, so use conservative checkpoints rather than claiming a precise
remaining envelope. Before a long read, milestone transition, compaction, rotation, or external
mutation, update the durable progress artifact with the last known state and one safe next step.
The artifact is the recovery boundary, not a transcript copy.

Treat `cursor_root_envelope_limit` as a root-size failure: stop retrying the same growing root and
rotate or compact from the checkpoint. Treat `cursor_blob_capacity` as transient shared capacity:
preserve the root, use ordinary backoff, and retry only read-only work after recovery. Never
recursively rotate for blob capacity. If a failed call might have changed an external system,
reconcile it before replaying and record `applied`, `not applied`, or `unknown`; `unknown` blocks
automatic mutation replay. OpenCodex may expose final replay-root bytes, but the orchestration
guidance must not pretend to have proactive exact-byte measurement.

## The finding that matters

Cost per model call against context carried, measured over 9,138 Opus calls:

| Context carried | Calls measured | Cost per model call |
|---|---|---|
| under 100K | 3,932 | $0.077 |
| 100–200K | 4,452 | $0.105 |
| 200–300K | 517 | $0.152 |
| 300–400K | 176 | $0.224 |
| 400–500K | 61 | $0.271 |

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
   deliberately instead of waiting for it. The measured sessions that went wrong went wrong by
   drifting up: one peaked at 711K, another ran 714 calls at a 311K median, and the worst reached
   731K-899K with no compaction at all. See "Rotating" below.

   Be honest about the size of this lever, though. Capping *every* call in the measured four days at
   120K of context would have saved 11.6% — real, but not the difference between a $96 day and a
   $553 day. The distribution is dominated by the *many* calls near 105K, not the few enormous ones,
   which is why the next two levers matter more.
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

   This one is the only advisory with a hard stop behind it, because it is the only one whose cost
   lands somewhere none of these numbers look. Context and budget are charges against the program,
   and an advisory is the right instrument for those: the orchestrator reads it and decides. A live
   lane is also a harness process, its MCP servers, a checkout for the filesystem watcher to walk,
   and a share of the per-tool-call hook traffic — and past some width those stop being a cost and
   become an outage on the machine, at which point every lane is lost, not just the marginal one.
   So `orch open` refuses past `ORCH_FANOUT_MAX`; `--over-fanout` is the one-dispatch override.

Worth knowing about the other side: a **worker** carries a small context and dies at the end of its
task, so its cache-read tax never accumulates. Cheap workers and an expensive orchestrator are the
same fact seen twice — which is why moving work out is a bigger saving than making the work cheaper.

## Measuring, and being told

```bash
orch cost                      # this session: calls, context, $/call, share by component
orch cost --format json        # the same, for a script
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
| Offer the human a front desk | 6 repeated routing turns, 20 turns, 6 dispatches | `ORCH_FRONTDESK_RELAY` |

Fan-out is the only one of these with a hard stop behind it. `orch open` **refuses** a dispatch once
the program holds `ORCH_FANOUT_MAX` lanes that have not been harvested — four past the warn
threshold by default, so lowering `ORCH_FANOUT_WARN` lowers the ceiling with it. An advisory is the
wrong instrument here because it is read by the one party it does not bind: a lane is dispatched by
an orchestrator that has already decided to dispatch it, and the cost lands on the machine rather
than on any number this program prints — each live lane is a harness process, its MCP servers, a
worktree, and a share of the per-tool-call hook traffic. Land and `orch close` what is finished, or
pass `--over-fanout` for the dispatch that genuinely cannot wait.

The front desk advisory fires at most **once per program** rather than following the rule below —
it asks the human to authorise another agent, and a declined offer must not come back. Conditions
and the reasoning behind the relay measurement are in `frontdesk.md`.

It repeats itself only when a *new* condition becomes true or the context has grown by half again,
because a hook that nags on every turn gets switched off — and then it is worth nothing at the moment
it would have mattered.

Rates are an estimate for advisory purposes, not a bill. Override them with `ORCH_RATES` as JSON or a
`rates.json` in the program directory rather than editing the script, so a price change is not a code
change.

## Rotating — compaction, made early and lossless

Compaction already *is* rotation: it is what dropped that session from the 400K band to the 100K
one, better than halving the per-call cost. The
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
   per kind (`ORCH_GUARD_BYTES`, `ORCH_GUARD_COOLDOWN`). It never blocks; sometimes the content is
   rightly yours.

   A document authored inline through a shell heredoc gets a **much lower floor** —
   `ORCH_GUARD_HEREDOC_BYTES`, 1200 bytes, against 6000 for an arbitrary large input. The shape is
   the signal there, not the size: `cat > brief.md <<EOF` is you writing a document, however short.
   This matters because the sizes are deceptive. Of the 42 heredoc-authored briefs measured in one
   program, the median was 4.4KB and **32 of the 42 sat under the ordinary 6000-byte floor** — so
   the threshold that is right for a large tool input was letting three quarters of the single
   biggest self-inflicted context item through unremarked.
2. **Independent tool calls go in one message.** Each model call re-reads the whole context. Median
   twelve calls a turn, maximum sixty-one; every one avoided is the full context size saved.
3. **Large reads happen in a worker.** The worker's context dies with it. Yours does not.
4. **Status goes to files, not to chat.** During execution, tell the human what changed in a line or
   two and put the rest in the plan document. With a front desk, say nothing in your own session at all.
