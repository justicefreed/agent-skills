# Availability — staying reachable, and the inbox

The human's next thought arrives on their schedule, not yours. Every minute you spend inside a turn
is a minute their input sits unread — and the input they most want to give you mid-program
("approved", "do T-010 first", "stop that lane") is the input most likely to change what you do
next. An orchestrator that is busy for ten minutes at a time is a bottleneck no amount of worker
parallelism fixes.

Two mechanisms. **Bounded turns** keep you reachable. **The inbox** makes the input safe to send
while you are not.

## Bounded turns

Aim to end a turn within about a minute. Treat these as prompts to reconsider, not a hard gate:

- more than about five tool calls in one turn;
- any read whose purpose is to *understand* a worker's change rather than to route it;
- any git write beyond committing files you authored yourself;
- any wait on a build, suite, or install.

When one trips, ask the delegate-or-inline question again (`../SKILL.md` Step 1). Usually the answer
is now *delegate*, because the trigger fired precisely on the work that has a cheaper archetype.

**Where the rule does not apply.** Some work genuinely cannot be split and is right to own: a
single indivisible read that grounds the whole program, a decision only you have the context to make,
a conflict whose resolution needs the plan in your head. Own it, and say so — "this will take a
while, your input will queue" is a fine sentence. What is not fine is drifting into ten minutes of
integration work without ever having decided to.

**Splitting is not the only tool.** Announcing a dispatch and ending the turn is faster than
narrating it. Reporting three finished lanes in one line beats three paragraphs. The output tokens
you do not write are the cheapest saving available, and they are yours to skip.

## The inbox

An append-only queue of items addressed to an agent, drained by that agent at the end of a turn.

It exists because of the finding in `messaging.md`: **there is no safe way to send to a running
agent.** The inbox does not solve that, it sidesteps it. Nobody sends — senders *append*, the
receiver drains when it is between turns. There is no check-then-send window, so there is no race to
lose, and it works for any sender: a peer worker, the orchestrator queueing work for a standing lane,
an external tool, or a human's own script.

```bash
orch inbox claim --as root                 # once, at Step 2: this worktree drains `root`
orch inbox send --to root --kind approval --ref e3 --body 'T-022 approved.'
orch inbox peek                            # exit 0 if pending, 3 if empty
orch inbox drain                           # print pending, mark delivered
orch inbox list --all                      # the log, including delivered items — provenance
```

Kinds are `approval`, `correction`, `task`, `answer`, `fyi`. `--ref` names the tracker entry or plan
item the item concerns.

### Rules that keep it correct

- **One claimant per worktree, and one worktree per name.** The claim maps a worktree to an inbox
  name, which is sound only because of the one-writer-per-worktree rule. Two agents draining one
  inbox split its items and neither sender can tell — so `orch inbox claim` now **refuses** a target
  another worktree already claims, rather than quietly adding a second claimant. That refusal is why
  taking over an inbox from a live agent is `orch rotate claim` and not a forced re-claim; see
  `rotation.md`.
- **A claim outranks `ORCH_INBOX_TARGET`.** When both exist, commands address the claim. The
  environment variable is a substrate-injected default that usually carries an agent id, and an agent
  id cannot be handed to anyone else; a claim is a deliberate act naming a role. `--to` still beats
  both.
- **Only the receiver drains.** Draining marks items delivered. A drain whose output is discarded
  loses them — the cursor has already moved. Never drain an inbox to *inspect* it; use `peek` or
  `list`.
- **Deliver what you drained.** If you drain and then fail, the items are gone. Anything that drains
  on an agent's behalf must send the text onward in the same breath.
- **Items are small.** The line limit is 4,000 bytes and oversize is refused, not truncated. A big
  item is a document: write the file, send a body that points at it.
- **A queued item is not a brief.** It is input. Route it through Step 1 like anything else — the
  moment you are handed something small with your context already loaded is exactly when you start
  doing work you should have delegated.

### Draining automatically

| Path | Covers | Notes |
|---|---|---|
| Turn-end hook in this skill's front matter | any Claude-harness agent, including inside Paseo | the baseline; registers on skill load, no config |
| `assets/paseo-inbox-plugin/` | agents on providers with no turn-end hook | optional; daemon-side, delivers after a settle delay |
| `orch inbox peek` by hand | anything | before a long dispatch, and on resume |

The hook runs `orch inbox drain --format hook`, which prints a turn-end JSON object carrying the
items as context and **nothing at all** when the inbox is empty. That is deliberate: a hook that
printed on every idle turn would cost tokens forever and be deleted within a day. It is also why the
drain exits silently rather than erroring outside a repo or with no claim.

Delivery continues the turn rather than interrupting it, so items land after your current work
completes. Repeated delivery cannot loop: the cursor advances on drain, so the next turn's drain is
empty. Harnesses additionally cap consecutive hook continuations.

### External senders

An outside tool should append with `orch inbox send` and let the receiver drain. Where a tool must
instead deliver a prompt itself — because the target has no drain path — it needs all three
mitigations from `messaging.md`, and one more that experiment showed matters: **wait for idle, then
pause about a second and re-check idle before sending.** A human who typed in that gap makes the
agent non-idle, and the tool must then stand down rather than race them. Accumulate events into a
log while waiting and send one coalesced prompt, so a storm produces one delivery instead of dozens.

The inbox file format is the canonical one. A sender that cannot use `orch` may append the same
JSON-line shape directly: one object per line, keys `at`, `kind`, `from`, `body`, optional `ref`,
written with a single append.
