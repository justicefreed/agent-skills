# agent-skills

Agent skills by [@justicefreed](https://github.com/justicefreed), packaged as a Claude Code plugin
marketplace and kept portable to other harnesses where possible.

## Install

```bash
claude plugin marketplace add justicefreed/agent-skills   # or a local path while developing
claude plugin install orchestration@justicefreed
```

Or link skills directly into local harness skill directories (`~/.claude/skills`, `~/.agents/skills`):

```bash
scripts/link-skills.sh
```

## Plugins

### `orchestration`

Coordinating work across multiple agents.

| Skill | Invocation | What it does |
|---|---|---|
| [`orchestrating`](./plugins/orchestration/skills/orchestrating/SKILL.md) | model-invoked | Decide whether to delegate, choose substrate and isolation, select model and effort, write briefs, track dispatches, verify results |

Design record: [`docs/DESIGN.md`](./docs/DESIGN.md).

The skill is substrate-agnostic — it speaks in capability verbs and binds one adapter at runtime, so
it works with an external agent daemon, with in-harness subagents, or with neither (degrading to
sequential execution while keeping the dispatch discipline).

Optional: pre-approve the tracker script to avoid permission prompts, in `.claude/settings.json`:

```json
{
  "permissions": {
    "allow": ["Bash(python3 \"${CLAUDE_PLUGIN_ROOT}/skills/orchestrating/scripts/orch.py\" *)"]
  }
}
```

## Repo conventions

See [`CLAUDE.md`](./CLAUDE.md) (symlinked as `AGENTS.md`). In short: one plugin per cohesive idea;
`plugin.json`'s `skills` array is an explicit ship list, so `in-progress/` is version-controlled but
never installed.

## License

MIT
