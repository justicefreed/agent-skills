# agent-skills

Agent skills by [@justicefreed](https://github.com/justicefreed), packaged as a Claude Code plugin
marketplace and kept portable to other harnesses where possible.

## Install

```bash
claude plugin marketplace add justicefreed/agent-skills   # or a local path while developing
claude plugin install orchestration@justicefreed
```

Or link skills straight into local harness skill directories (`~/.claude/skills`, `~/.agents/skills`):

```bash
scripts/link-skills.sh
```

**Then pre-approve the tracker script**, or you will be prompted on every dispatch. In
`.claude/settings.json`:

```json
{
  "permissions": {
    "allow": ["Bash(python3 \"${CLAUDE_PLUGIN_ROOT}/skills/orchestrating/scripts/orch.py\" *)"]
  }
}
```

---

## `orchestration`

Coordinating work across multiple agents.

| Skill | Invocation | What it does |
|---|---|---|
| [`orchestrating`](./plugins/orchestration/skills/orchestrating/SKILL.md) | model-invoked | Decide whether to delegate, choose substrate and isolation, select model and effort, write briefs, track dispatches, land finished work, verify results |

Design record: [`docs/DESIGN.md`](./docs/DESIGN.md).

### Who this is for

You are running work too big for one agent session — a migration, an audit remediation, a refactor
spanning many independent changes — and the coordination has become harder than any single task.

Spawning subagents is the easy part. The hard parts are knowing what is still running after your
context compacts, keeping fan-out from costing more than the work, and getting a truthful answer
back instead of a confident one.

It is **not** a task tracker, a plan, or a workflow engine. It assumes you already have a plan, or
don't need one, and handles only dispatching, tracking and verifying delegated work.

### What it helps with

| Problem | What the skill does |
|---|---|
| **Fan-out costs more than the work** | Shared rules live in one referenced file instead of being retyped into every brief. Briefs are files, so re-dispatching is free. Reports are capped at a 300-word decision block with detail written to disk. |
| **Picking a model is a guess** | An archetype catalog with a starting model and effort for each kind of work. Nothing starts above the provider's default; three of eight start below. Escalation needs an observed failure, not a hunch. |
| **You lose track of what is running** | A bundled `orch` script keeps a small JSON file per orchestrator, outside the repo, keyed so every worktree of a repo shares one tracker. It enforces the required fields itself, rather than asking nicely. |
| **Your context compacts mid-program** | Every fact is written down before the action that needs it, so a crash leaves a findable orphan rather than an unknown agent. Nothing re-derivable is stored — liveness is always re-checked, never remembered. |
| **A worker gets interrupted** | Briefs name a progress file and carry resume instructions, so the worker can work out where it left off. The skill also documents what is genuinely unrecoverable, so you design around it. |
| **Progress tracking turns into mush** | Two separate things stay separate: the tracker holds open dispatches and deletes them once used; your plan holds items and lives in your repo. One field links them. A plan is optional. |
| **The orchestrator ends up doing the work** | Merging and landing arrive after planning, so they never get the delegate-or-inline decision and default to the priciest agent you have. Landing gets a standing lane, emergent work is re-decided explicitly, and each brief declares who reads its diff before it lands. |
| **You wait to tell it something** | Input for a busy agent goes to an append-only inbox and is delivered at the end of its turn, so nothing races a running task and nothing has to be timed. A turn-end hook ships with the skill and costs nothing when the inbox is empty. |

### Substrates

The skill names no tools directly — it picks one adapter at runtime:

| Adapter | Use when |
|---|---|
| [Paseo](https://paseo.sh) | you want workers that outlive your session, and branches a human can review |
| In-harness subagents | short tasks where you want a summary, not the file dumps |
| Neither | no delegation available; runs sequentially and keeps the tracking discipline |

#### With Paseo

Prefer Paseo when you have it. Its agents are run by a daemon, so they **survive your session
ending** — which matters because losing an orchestrator to context compaction is normal, not rare.
Each worker also gets a real workspace with its own worktree, so you can review a lane's branch and
diff yourself.

Two things worth doing:

- **Set up a few agent profiles.** Profiles are Paseo's named model/effort presets, and the skill
  checks them before anything else, reading each profile's notes to pick one. Three or four
  ("integration work", "adversarial review", "mechanical sweep") is enough to make model choice your
  policy instead of the skill's fallback. Without them it falls back to the archetype catalog and
  tells you it did.
- **Send follow-ups from the desktop app, not the CLI.** A prompt sent to a *busy* agent over the
  CLI or the MCP tools **replaces what it was doing** — and the agent then reports success as though
  nothing was lost. The app's message queue avoids this, but it is a feature of the app itself, so
  it does not protect the other two paths. If you must use them, wait for the agent to go idle or
  cancel it deliberately.

---

## Repo conventions

See [`CLAUDE.md`](./CLAUDE.md) (symlinked as `AGENTS.md`). In short: one plugin per cohesive idea;
`plugin.json`'s `skills` array is an explicit ship list, so `in-progress/` is version-controlled but
never installed.

## License

MIT
