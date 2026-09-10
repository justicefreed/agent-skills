# orch-inbox (optional Paseo plugin)

Delivers pending `orch` inbox items to an agent at the end of its turn, so a requester never has to
send a prompt into a running agent's turn.

**This is a fallback, not the primary path.** The primary drain is a Claude Code `Stop` hook running
`orch inbox drain --format hook`. Prefer it. Install this plugin only when:

- the target agent runs on a provider with no Stop hook (Codex, Cursor-hosted models); or
- the target is idle, so no turn will end inside the target's own harness to trigger its hook.

## What it does

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

## Install

```bash
paseo plugin install /absolute/path/to/paseo-inbox-plugin
paseo plugin logs orch-inbox
```

The tracker is found the same way the skill's turn-end hook finds it: `ORCH_SKILL_DIR`, then
`~/.claude/skills/orchestrating`, then `~/.agents/skills/orchestrating`, each plus
`scripts/orch.py`. Set `ORCH_INBOX_ORCH_BIN` in the daemon environment to override with a specific
executable.

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
