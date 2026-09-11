# Durable state — the tracker

One question the tracker answers: **what did I commission, and what will I do with it?**
Everything else is either derivable (so it is re-derived) or belongs somewhere else.

`orch` is `scripts/orch.py`; see `substrates/_capabilities.md` for path resolution. **Never
hand-edit a tracker file** — the script's field validation is the whole mechanism.

## Where it lives, and why not in the repo

```
${XDG_STATE_HOME:-~/.local/state}/agent-orchestration/
  <repo-basename>-<sha256(git-common-dir)[:8]>/
    <program>/
      root.json            root.1.json      root.1.2.json
      briefs/
```

Outside the repository, never committed:

- **Lane worktrees get deleted.** State inside one dies with the thing it tracked.
- **The orchestrator moves between worktrees.** The key comes from `git rev-parse
  --git-common-dir`, so every linked worktree of a repo resolves to one key.
- **A commit-everything cannot sweep it.** Untracked orchestration state living inside a repo is
  how an unrelated commit acquires another lane's files.

**The one cost of living outside the repo, and how it is paid.** Briefs live here too, so a brief is
outside the worktree of the worker that must read it — and in Claude Code a read outside the working
directory raises a permission prompt under every session mode except `bypassPermissions`. The first
instruction of a brief-driven spawn is therefore the thing most likely to stall it, and a worker
halted on a prompt looks exactly like a worker thinking. Four were found stopped this way at once:
three on a brief, one on a *reference* — the skill's own `references/` corpus is outside the worktree
for the same reason and stalls a worker the same way.

Choosing a better mode does not fix either; only scope does. `orch permissions --install` adds one
narrow `Read(//<dir>/**)` rule per directory to `~/.claude/settings.json` (or `$CLAUDE_CONFIG_DIR`),
covering the state root and the installed skill, which settles it for every worker in every
repository. Run it once per machine; `orch permissions` alone checks and exits 3. Three details are
deliberate: both spellings of each directory are granted, since the installed skill is a symlink into
a checkout and a rule for one spelling need not match a read of the other; the skill path comes from
where the skill is *installed* rather than from where the script is running, so a throwaway worktree
never earns a permanent rule; and a settings file that does not parse is never rewritten. `orch open`
warns when the rules are absent. Settings are read at launch, so a grant reaches the next worker
spawned, not one already stalled.

Durable *provenance* — what was commissioned, what it produced, what was ruled — graduates into
in-repo artifacts at harvest. The tracker is not the record of what happened; it is the record of
what is **still open**.

## Identity, and what is re-derivable

| Thing | Re-derivable? | From |
|---|---|---|
| repo key | **fully** | one git command, from any worktree |
| program name | **discoverable, not derivable** | `orch programs`, else ask |
| `root.json` | **fully** | fixed name |
| child tracker id | **fully** | parent id + ordinal; encoded in the filename |
| substrate agent id | **no** | minted at spawn — the field that makes this tracker necessary |
| worker liveness | **fully** | the substrate; never stored here |

Program names are derived from the plan document's directory when there is one, otherwise
`default`. **Notify, don't ask** — except when minting a *new* program while others exist, which
`orch` refuses to guess at, because a second namespace splits state into two halves that each look
internally consistent.

## The dispatch sequence

Two phases, because the record must precede the action but the agent id only exists after it.

```bash
orch open --brief briefs/batch-c.md         # -> e1, status pending
# ...SPAWN...
orch update e1 --agent-id <id> --session-name <name>
```

If the process dies between them, you are left with a `pending` entry naming a brief and a worktree
— enough to find the orphan. Recording *after* the spawn instead would leave an agent nobody knows
exists. `orch roster` flags `NO-AGENT-ID` for exactly this.

The mode is decided here too, not at the spawn. `open` fills in `ORCH_WORKER_MODE` (default `auto`)
unless the brief's front matter or `--mode` says otherwise, refuses a mode that stops to ask a human
without `--ask-mode-ok`, and prints the `settings` fragment to pass — because a field that has to be
remembered at spawn time is a field that gets forgotten, and forgetting this one selects Always Ask.
`roster` then flags `ASK-MODE:<id>` on any entry recorded in a blocking mode, and `NO-MODE` on one
recorded before the mode was tracked. Use `orch update <e> --mode <id>` to record what a worker is
*actually* in; `update` does not refuse a blocking mode, because the repair path has to be able to
write down the bad state before anyone can report it.

**The model rung rides the same rails**, because it has the same failure mode — forgotten at spawn,
and expensive rather than neutral when forgotten. `open` fills in `ORCH_WORKER_MODEL` (default
`economy`) unless front matter or `--model` says otherwise, refuses `frontier` without
`--model-reason`, and names the rung in the same printed fragment. `roster` flags `TIER:<rung>` above
`economy`, suffixed `:NO-REASON` when unjustified, and `NO-MODEL` on an entry recorded before the
rung was tracked. `orch update <e> --model <rung>` is the correction path; raising a rung goes
through `orch escalate`, which demands the signal and keeps it. Rungs only — a model *name* in a
brief is rejected, because it is wrong the next time the provider ships. See `delegation.md` §3–4.

Required brief front matter — `title`, `worktree`, `expected_artifacts`, `advances`,
`consumption` — is read from the file, never retyped. `orch` rejects placeholders (`unknown`,
`tbd`, `n/a`, …): a required field answered with a placeholder is an omission in costume.
`advances` accepts the literal `none`, because an explicit *none* is a decision and a blank is not.

## Command surface

| Command | Purpose |
|---|---|
| `orch programs` | what programs exist for this repo |
| `orch open --brief P [--agent-id ID] [--mode M] [--model R] [--model-reason S] [--program N] [--tracker ID]` | record a dispatch |
| `orch update E [--agent-id] [--session-name] [--mode] [--model] [--status] [--pending-message] [--note]` | amend an open entry |
| `orch permissions [--install]` | check, or grant, the one read a worker needs to start |
| `orch mint-child E` | allocate a sub-orchestrator's tracker id (idempotent) |
| `orch close E --consumed "<what happened>"` | delete a consumed entry |
| `orch roster [--recursive] [--json]` | open entries, with flags |
| `orch render [--recursive]` | the same, as markdown |
| `orch whoami [--worktree P]` | recover a sub-orchestrator's tracker id |
| `orch prune --alive <ids> [--dry-run]` | drop entries whose agent is gone |
| `orch inbox claim --as T` | record that this worktree drains inbox `T` |
| `orch inbox send --to T --body B [--kind K] [--ref E] [--from W]` | append one queued item |
| `orch inbox peek [--to T]` | pending count; exit 3 when empty |
| `orch inbox drain [--to T] [--format text\|json\|hook]` | print pending items and mark delivered |
| `orch inbox list [--to T] [--all]` | the inbox log, delivered items included |
| `orch cost [--transcript P \| --for T] [--format json]` | calls, context, cost per call, share by component |
| `orch budget [--set N]` | show or set this program's spend limit in USD |
| `orch escalate E --to R --reason S` | raise a lane's model rung, on a signal that is recorded |
| `orch escalate --log [--json]` | the escalations so far, grouped by archetype |
| `orch wake register --id I --insures E[,E\|external:W] [--kind K]` | bind a heartbeat to the lanes it insures |
| `orch wake clear --id I [--reason R]` | forget a wake you have deleted at the substrate |
| `orch wake list [--json]` | what is set to wake this program, and the idle-tick count |
| `orch wake hold --minutes N --reason R \| --clear` | suppress idle advisories while waiting on something untracked |
| `orch wake check [--format hook]` | the turn-end wake-loop detector |
| `orch resume` | orchestration state re-derived from disk; the session-start hook after compaction |
| `orch frontdesk [--set T --agent-id A \| --clear]` | record which inbox target relays the human |
| `orch guard` | the PreToolUse hook; notes a large tool input once per cooldown |
| `orch compaction measure\|check\|window` | context floor and safe auto-compact window; `check` is the session-start loop detector; `window` is what a launcher asks |
| `orch rotate begin\|claim\|complete\|status\|abort` | replace a live agent; see `../rotation.md` for the order and who runs which |

`roster` prints **recorded intent, not liveness**, and says so. It never contacts a substrate — that
boundary is why the adapters stay swappable. `prune` likewise takes the live agent set as an
argument rather than querying, and refuses an empty set instead of interpreting it as "nothing is
alive."

## Closing is the completion criterion

`close` demands `--consumed`. An entry you cannot describe as consumed is an output nobody used —
that is a finding, not paperwork. Closing an entry whose sub-orchestrator still has open work warns
rather than blocks.

## Sub-orchestration

The parent is the **only minter**. `orch mint-child e1` returns `root.1`; put `tracker_id: root.1`
in that worker's brief front matter. A child recovers its id from its brief, or via `orch whoami`
when it has its own worktree. If neither works it must **ask, never mint** — two tracker files for
one job is a split-brain where each half is internally consistent and neither is complete.

## Records that are neither tracker nor inbox

`compaction.json` and `rotation.json` sit beside the tracker in the program directory, and both are
there for the same reason: they carry a fact **the next session cannot re-derive**.

A session cannot measure its own context floor before it has one, and it cannot change its own
auto-compact window at all — that is read at launch. So the measured floor is recorded for whoever
launches next. It only ever grows: a floor that shrank would be a smaller reading of the same
irreducible context, not a smaller context.

A rotation record is the obligation the *successor* inherits — which inbox to take, which agent to
close — and it must survive the predecessor going away mid-handoff, which is precisely the case it
exists for. It is deleted on `rotate complete`, and a record still pending after ten minutes raises
an advisory on the turn-end hook. That is the dangling-session detector.

`escalations.json` is the fourth, and the only one that must outlive the work it describes. Every
other record here is deleted when its subject closes; this one is kept precisely *because* the
tracker is a working set. It answers a question no single dispatch can — **which archetypes actually
earn a rung above the cheap default** — and it can only answer it by accumulating across dispatches
that are individually gone. Nothing else records it: the reason a human raised a dial appears in no
transcript, no commit and no plan document. Hence the mandatory `--reason` on `orch escalate`; an
escalation with no reason is a hunch, and a hunch cannot be checked a month later. Read it with
`orch escalate --log`, and treat an archetype that escalates every time as a wrong default in
`delegation.md` rather than as a run of bad luck.

`wake.json` is there for the third instance of the same reason, and it carries two different kinds
of fact. The first is a binding the substrate does not hold: *which lanes a heartbeat insures*. A
substrate knows a heartbeat exists and when it next fires; it has no idea what it was set up to
watch, so nothing but this record can decide when it has stopped watching anything. The second is
the **idle-tick count** — how many consecutive turn ends have found the roster empty. That one is
recorded precisely because it is the view a single turn cannot have: each no-change tick is
individually defensible, and only the count across them says *loop*. It has exactly one writer, the
agent that claimed the program's inbox; every other agent reads it and leaves it alone, because a
worker's turn end resetting the count would erase the only evidence that spans ticks.

Nine smaller sidecars share that directory — `budget.json`, `rates.json`, `transcripts.json`,
`frontdesk.json`, `escalations.json`, and the fire-once markers `cost-warned.json`,
`guard-warned.json` and `frontdesk-suggested.json`. **Only files named `root`, `root.1`, `root.1.2` are trackers**, and the
recursive reader filters on exactly that grammar. It has to: a sidecar has no tracker schema
version, so a reader that globbed `*.json` aborted on the first one it met. Callers that swallowed
the error then saw an empty program, which is why the fan-out advisory silently reported zero open
dispatches once a program acquired any sidecar at all. Add a sidecar freely; never name one `root*`.

## The inbox is state with different rules

The tracker is one-writer, mutable, and a working set. The inbox files under `<program>/inbox/` are
the opposite on two of three counts: **many writers, append-only, never mutated.** They are the only
multi-writer state here, and they are safe because appends of small lines land whole and a line's
index never changes. The single mutable file per inbox is its `.cursor`, written only by the one
agent that drains — so Principle 3 holds where it matters.

They are also the one place a log is *wanted*: `orch inbox list --all` is a record of what was asked
of a lane and when, which no other source of truth carries. See `availability.md` for the contract.

## Deferred send

Prefer the inbox: it needs no idle check and cannot lose a race. Where the receiver has no drain path
at all, park the message on the entry instead:

```bash
orch update e1 --pending-message "answer X, then resume per your brief"
```

On the worker's finish notification, drain **one** message, send it, then verify the turn that
started is yours; if not, restore it — there is no atomic send, so a lost race looks exactly like a
delivery. `roster` flags `MSG-QUEUED`.

## Cost state is derived, not stored

`orch cost` reads the harness's own transcript and computes. Nothing about spend is recorded in the
tracker, because all of it is re-derivable from a file the harness already writes — Principle 1. The
only stored pieces are the two that are *decisions*: the program's budget, and which advisory was
last spoken, so the hook does not repeat itself. Both live beside the tracker, not inside it.

## Deliberate non-goals

No history, no status log, no completed-work archive. Retrospectives come from the substrate's own
activity records; provenance comes from the repo. A tracker that accumulated history would grow
unbounded, cost tokens on every read, and duplicate two other sources of truth.
