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

---

## `orchestration`

Coordinating work across multiple agents.

| Skill | Invocation | What it does |
|---|---|---|
| [`orchestrating`](./plugins/orchestration/skills/orchestrating/SKILL.md) | model-invoked | Decide whether to delegate, choose substrate and isolation, select model and effort, write briefs, track dispatches, verify results |

Design record: [`docs/DESIGN.md`](./docs/DESIGN.md).

### Who this is for

You are running a body of work too large for one agent session — a migration, an audit remediation,
a refactor spanning many independent changes — and you have hit the point where the *coordination*
is harder than any individual task.

Spawning subagents is easy. What is not easy is everything around it: knowing what is still running
after your context compacts, telling a legitimate uncommitted file from another lane's, keeping the
cost of fan-out proportionate to the work, and getting a truthful answer back rather than a
confident one. This skill is the accumulated answer to those, from a multi-month multi-agent
remediation program.

It is **not** a task tracker, a plan, or a workflow engine. It assumes you already have a plan (or
don't need one) and concerns itself only with dispatching, tracking and verifying delegated work.

### The pitfalls it navigates

**Keeping fan-out token- and cost-efficient.** Repeated boilerplate in every dispatch is paid in the
orchestrator's *output* tokens, so shared constraints live in one referenced file rather than being
restated per brief — which also stops a corrected rule from having to be hand-carried into every
future brief. Briefs are files, so a re-dispatch, a nudge or a replacement worker costs nothing to
instruct. Reports are capped at a ≤300-word decision block with detail written to disk, so a
verbose worker cannot flood the window you need for the next decision. And the model/effort catalog
starts no archetype above the provider's *default*, putting three of its eight below, with
escalation triggered by an observed failure signature rather than a hunch.

**Tracking progress robustly, with deterministic tooling, outside version control.** A bundled
`orch` script owns a small JSON working set per orchestrator, in your state directory rather than
in the repo. It is keyed on the repository's common git dir, so every worktree of a repo resolves to
the same tracker and it survives any individual lane worktree being deleted. Living outside the repo
also means a `git add -A` can never sweep it into someone's branch. The script — not prose — enforces
the required fields, rejects placeholder and unfilled-template values, and refuses to close an entry
without a statement of what consumed its output.

**Resuming after an interruption.** Every non-derivable fact is made durable at the moment it is
created, and the record is a *precondition* of the action rather than a follow-up — so a crash
between recording and spawning leaves a findable orphan instead of an unknown agent. Nothing
derivable is stored: liveness is always re-queried, because a persisted "nothing is in flight" is a
claim that cannot be falsified. Picking up cold is a defined procedure, not archaeology.

**Recovering from task failures.** An interrupted worker's transcript survives; what it loses is the
instruction to continue. So briefs carry a resume clause and name a progress artifact, which makes
the resume point *computable* rather than remembered. The skill also documents what is genuinely
unrecoverable — mid-task correction of a running worker does not exist on any substrate tested — so
you design around it instead of discovering it at the worst moment.

**Keeping orchestration status separate from plan status.** These are two different things that get
fused into one document and then rot. The tracker is worker-keyed, bounded, machine-local, and its
entries are *deleted* once consumed. Your plan is item-keyed, durable, and lives in your repo in
whatever format you already use. A single `advances:` field joins them. The skill will link a plan
document if one exists and requires none if it doesn't.

### Substrates

The skill speaks in capability verbs and binds one adapter at runtime, so the decision logic never
names a tool. Adapters ship for [Paseo](https://paseo.sh), for in-harness subagents, and for neither
— the last degrading to sequential execution while keeping the dispatch discipline, which still pays
because context loss is the failure mode that does not require a second agent.

#### Using it with Paseo

Paseo is the substrate this was built against, and the one to prefer when both are available: its
agents are managed by a daemon and **survive the orchestrator's session ending**, which matters
because orchestrator death by context compaction is routine rather than exceptional. It also gives
each worker a real workspace with worktree isolation, so a human can review a lane's branch and diff
directly — something a temporary in-harness worktree cannot offer.

To get the most out of it:

- **Configure agent profiles.** Paseo's named `provider/model/mode` bundles are the intended way to
  control model and effort, and the skill checks them first — reading each profile's `notes` to
  match the work. Without profiles it falls back to a built-in archetype catalog and tells you it
  fell back. A handful of profiles ("integration work", "adversarial review", "mechanical sweep")
  turns model selection from the skill's guess into your policy.
- **Let the notifications do the waiting.** Paseo notifies on finish; the skill does not poll.
  Reconciliation against the daemon is reserved for resuming cold or for a missed heartbeat.
- **Know the send semantics before messaging a running worker.** Verified by experiment and
  documented in the adapter: `send_agent_prompt` — and `paseo send --no-wait` — *replace* a running
  task, and the worker then reports success, so the damage is invisible from its own report. Desktop
  queueing is client-side and not exposed over MCP or the CLI. The skill's messaging rules exist
  because of this, and give you safe alternatives for each case.
- **Use `update_agent` to retune rather than respawn.** Model and effort can be changed on a running
  worker without touching its instructions, which is what makes "start at the default, escalate on a
  signal" cheap.
- **Reach for the existing Paseo skills for what they already do well.** The adapter points at the
  `paseo` skill for the tool surface rather than duplicating it, and routes adversarial review and
  second opinions to `paseo-committee` and `paseo-advisor` instead of reinventing them.

Optional: pre-approve the tracker script to avoid permission prompts, in `.claude/settings.json`:

```json
{
  "permissions": {
    "allow": ["Bash(python3 \"${CLAUDE_PLUGIN_ROOT}/skills/orchestrating/scripts/orch.py\" *)"]
  }
}
```

---

## Repo conventions

See [`CLAUDE.md`](./CLAUDE.md) (symlinked as `AGENTS.md`). In short: one plugin per cohesive idea;
`plugin.json`'s `skills` array is an explicit ship list, so `in-progress/` is version-controlled but
never installed.

## License

MIT
