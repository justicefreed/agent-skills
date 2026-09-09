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
| [`orchestrating`](./plugins/orchestration/skills/orchestrating/SKILL.md) | model-invoked | Decide whether to delegate, choose substrate and isolation, select model and effort, write briefs, track dispatches, verify results |

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

## `browser-verification`

Agents checking front-end work like to run the installed Google Chrome headless. On a Mac with the
managed Chrome policy `DefaultBrowserSettingEnabled = 1`, every such launch pops the macOS "change
your default browser?" dialog at you, and no Chrome flag stops it. This plugin gives agents a
policy-immune path and, optionally, a guard.

- **`headless-browser` skill** — routes to Paseo's `browser_*` tools when present, otherwise to
  `scripts/headless-browser.sh`, which runs chrome-headless-shell (or Chrome for Testing) from the
  puppeteer cache and installs it on first use.
- **Guard hook** — a PreToolUse hook that denies Bash commands launching Google Chrome.app, with
  the replacement in the reason. It checks for the managed policy and is a no-op elsewhere.

| Skill | Invocation | What it does |
|---|---|---|
| [`headless-browser`](./plugins/browser-verification/skills/headless-browser/SKILL.md) | model-invoked | Pick Paseo browser tools or the bundled headless wrapper, run a scripted probe, recover from a guard refusal |

Design record: [`docs/BROWSER-VERIFICATION.md`](./docs/BROWSER-VERIFICATION.md).

### Enable

```bash
# Route A — plugin install: skill + hook together
claude plugin install browser-verification@justicefreed

# Route B — symlinked skills: link, then opt in to the hook separately
scripts/link-skills.sh
scripts/chrome-guard-hook.sh enable                 # ~/.claude/settings.json
scripts/chrome-guard-hook.sh enable --project DIR   # or one repo's .claude/settings.json
scripts/chrome-guard-hook.sh status
```

Optional: turn on Paseo's browser tools (Settings → host → Agents → Browser tools, or
`daemon.browserTools.enabled: true` in `~/.paseo/config.json` then `paseo reload`) so agents get
an interactive browser you can watch. See the skill's `references/paseo-browser.md`.

### Disable / revert

```bash
claude plugin disable browser-verification@justicefreed   # Route A: skill + hook off
scripts/chrome-guard-hook.sh disable [--project DIR]       # Route B: removes only our hook entry
NO_GOOGLE_CHROME_HOOK=off claude                           # silence the hook for one session
```

The hook never modifies Chrome, the policy, or your default browser; reverting is removing the
entry. Is the policy really the cause on your machine? Run the check in
`plugins/browser-verification/skills/headless-browser/references/google-chrome-policy-prompt.md`.

## Repo conventions

See [`CLAUDE.md`](./CLAUDE.md) (symlinked as `AGENTS.md`). In short: one plugin per cohesive idea;
`plugin.json`'s `skills` array is an explicit ship list, so `in-progress/` is version-controlled but
never installed.

## License

MIT
