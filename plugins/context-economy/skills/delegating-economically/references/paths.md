# Where `spend` lives

`spend` is `scripts/spend.py` in the **plugin root**, not in the skill directory. Run it as
`python3 <plugin root>/scripts/spend.py <command>`.

| Install | Plugin root |
|---|---|
| Claude Code plugin install | `${CLAUDE_PLUGIN_ROOT}` |
| `scripts/link-skills.sh` (any harness) | `~/.agents/plugins/context-economy` |
| Source checkout | `plugins/context-economy` in the agent-skills repo |

`SPEND_SKILL_DIR`, if set, overrides all of these. Never reach the plugin root with `..` from the
skill directory: installed skills are copies, so `..` leads to the harness's skills folder.
