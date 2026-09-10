# orch-inbox (optional Paseo plugin)

Two things, both optional, sharing one `orch` resolution:

1. **Inbox delivery** — delivers pending `orch` inbox items to an agent at the end of its turn, so a
   requester never has to send a prompt into a running agent's turn.
2. **The program status pill** — a composer pill whose one line is exactly what `orch statusline`
   prints into a terminal status bar, and an agent panel with the roster behind it.

The second is the Paseo half of the status surface; the Claude Code half is the `statusLine` command
in `references/statusline.md`. Both render the same JSON from the same collector.

## Inbox delivery

**Delivery here is a fallback, not the primary path.** The primary drain is a Claude Code `Stop`
hook running `orch inbox drain --format hook`. Prefer it. Install this plugin for delivery only
when:

- the target agent runs on a provider with no Stop hook (Codex, Cursor-hosted models); or
- the target is idle, so no turn will end inside the target's own harness to trigger its hook.

What the delivery half does:

- On `agent.session_open`, injects `ORCH_INBOX_TARGET` (the agent id) into the launch env unless one
  is already set, so an agent can address its own inbox without being told its id. For Claude agents
  it also sets `CLAUDE_CODE_AUTO_COMPACT_WINDOW=200000` unless already set, so the agent compacts at
  about 200K tokens rather than near the window limit — measured, the same orchestrator cost 5.9x
  more per model call at 668K of context than at 88K. Override with `ORCH_AUTOCOMPACT_WINDOW` in the
  daemon environment; set it empty to disable.
- On `agent.turn_ended`, waits a short settle delay, then drains and sends the drained text to that
  same agent as a new turn. A `canceled` outcome is skipped entirely — a cancelled turn means a human
  is driving. There is no separate `peek`: a drain on an empty inbox prints nothing and advances
  nothing, so peeking first would only add a second process spawn on every turn of every agent.

It never polls, never sends mid-turn, and never drains an inbox it is not about to deliver.

## The program status pill

`/orch` in an agent's composer pins a pill on that agent; `/orch` again removes it. `/orch <program>`
picks a program when the repo has more than one and `orch` refuses to guess. The Command Center has
both **Toggle orch status pill** and **Open orch status**.

The pill's label is `orch statusline`'s line, verbatim — `orch:agent-track · 4 run · ✉+2 · !ctx` —
and it turns amber when the collector raises an advisory. Pressing it opens the **orch status**
panel: the lanes and who holds them, queued inbox depth per target, program spend against its
limit, context depth, and the advisories spelled out. The panel refreshes every 5s while open, the
pill every 15s; both are the same query, so they can never disagree.

It is pinned by hand rather than appearing everywhere for a structural reason — a pill needs a
`workspaceId` *and* an `agentId`, and the only client callbacks handed both are a slash command and
a Command Center item. That matches the intent anyway: program status is worth composer space on
the one or two agents actually orchestrating, not on all fifteen lanes.

**It renders nothing into any agent's context.** That is the entire point of a status surface: the
same status narrated in chat becomes part of the model's input on every later turn, and cache reads
are the dominant line item in a large program's bill. Reading `orch.status` costs one short-lived
Python process on the daemon and zero tokens.

What it does *not* show: work items, gates, or a critical path. That is agent-track's job. The one
number borrowed from it is "awaiting a human", which `orch` reads through the `track` CLI, caches
for 15s, and omits entirely when the repo has no `.track/`.

## Install

```bash
paseo plugin install /absolute/path/to/paseo-inbox-plugin
paseo plugin logs orch-inbox
```

Reinstall after pulling a change to this directory — `paseo plugin install` copies it, so an
already-installed `orch-inbox` keeps running the old code until it is reinstalled or reloaded.

The tracker is found the same way the skill's turn-end hook finds it: `ORCH_SKILL_DIR`, then
`~/.claude/skills/orchestrating`, then `~/.agents/skills/orchestrating`, each plus
`scripts/orch.py`. Set `ORCH_INBOX_ORCH_BIN` in the daemon environment to override with a specific
executable.

## Typechecking

```bash
npm install
npm run typecheck    # the client bundle and the daemon bundle, as separate programs
```

Two tsconfigs on purpose: `client/` gets React Native and no Node, `server/` gets Node and no React.
That is the boundary Paseo's own compiler enforces at install time, so checking it here is what
keeps an install failure from being the first place it shows up.

## Limitations

- **The settle delay is a mitigation, not a lock.** It exists so a human typing right after a turn
  ends wins the race. A message that arrives *inside* that window can still collide with the
  plugin's send. There is no way to hold a lock on an agent's input from a plugin.
- **A drained-but-unsent item is lost.** Draining advances the inbox cursor. If the `send` then
  fails, the plugin cannot put the items back; it logs them (`LOST INBOX ITEMS`) and gives up. It
  does not retry — retrying is how a plugin livelocks an agent. Recover the text from
  `paseo plugin logs orch-inbox`.
- **There is no idle event and no timer event.** Delivery is driven only by a turn ending, so an
  agent that never takes another turn never drains its inbox. Wake it yourself, or drain from the
  requester side.
- **Claude-hosted agents get both paths.** If the Stop hook is also installed, whichever fires first
  drains; the other finds an empty inbox. That is harmless but means delivery order across the two
  mechanisms is not guaranteed.
- **The pill cannot appear by itself.** See above: no per-agent client registration event exists in
  0.8, so an unpinned agent has no pill until a human runs `/orch` on it.
- **`/orch <program>` is read when the pill mounts.** Changing the choice means unpinning and
  re-pinning, which is what `/orch` twice does.
- **A status read is a subprocess.** Nothing in the read path opens a transcript — the turn-end cost
  hook writes a snapshot for it — but a daemon with no `python3` or no `orch.py` will show
  `orch: unavailable`, with the reason in the panel.
