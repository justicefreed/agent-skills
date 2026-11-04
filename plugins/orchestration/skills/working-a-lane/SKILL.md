---
name: working-a-lane
description: Obligations of the agent currently working a lane for an orchestrator — the brief, the checkpoint, the report, the inbox. Use when your prompt has an `orch_entry:` line or names a brief to read.
hooks:
  Stop:
    - hooks:
        - type: command
          command: 'PY="${ORCH_PYTHON:-}"; [ -x "$PY" ] || PY=/usr/bin/python3; [ -x "$PY" ] || PY=python3; for d in "$ORCH_SKILL_DIR" "$CLAUDE_PLUGIN_ROOT/skills/orchestrating" "$HOME/.claude/skills/orchestrating" "$HOME/.agents/skills/orchestrating" "$HOME/.agents/plugins/orchestration/skills/orchestrating"; do [ -f "$d/scripts/orch_hook.py" ] && exec "$PY" "$d/scripts/orch_hook.py" inbox drain --format hook; done; exit 0'
        - type: command
          command: 'S="${XDG_STATE_HOME:-$HOME/.local/state}/agent-orchestration/enforcing"; [ -e "$S" ] || exit 0; PY="${ORCH_PYTHON:-}"; [ -x "$PY" ] || PY=/usr/bin/python3; [ -x "$PY" ] || PY=python3; for d in "$ORCH_SKILL_DIR" "$CLAUDE_PLUGIN_ROOT/skills/orchestrating" "$HOME/.claude/skills/orchestrating" "$HOME/.agents/skills/orchestrating" "$HOME/.agents/plugins/orchestration/skills/orchestrating"; do [ -f "$d/scripts/orch_hook.py" ] && exec "$PY" "$d/scripts/orch_hook.py" stop-check --format hook; done; exit 0'
---

# Working a lane

BODY: written by the skill lane (orch-working-a-lane.md W1).
