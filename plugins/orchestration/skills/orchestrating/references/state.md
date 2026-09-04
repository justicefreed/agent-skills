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

Required brief front matter — `title`, `worktree`, `expected_artifacts`, `advances`,
`consumption` — is read from the file, never retyped. `orch` rejects placeholders (`unknown`,
`tbd`, `n/a`, …): a required field answered with a placeholder is an omission in costume.
`advances` accepts the literal `none`, because an explicit *none* is a decision and a blank is not.

## Command surface

| Command | Purpose |
|---|---|
| `orch programs` | what programs exist for this repo |
| `orch open --brief P [--agent-id ID] [--program N] [--tracker ID]` | record a dispatch |
| `orch update E [--agent-id] [--session-name] [--status] [--pending-message] [--note]` | amend an open entry |
| `orch mint-child E` | allocate a sub-orchestrator's tracker id (idempotent) |
| `orch close E --consumed "<what happened>"` | delete a consumed entry |
| `orch roster [--recursive] [--json]` | open entries, with flags |
| `orch render [--recursive]` | the same, as markdown |
| `orch whoami [--worktree P]` | recover a sub-orchestrator's tracker id |
| `orch prune --alive <ids> [--dry-run]` | drop entries whose agent is gone |

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

## Deferred send

For a substrate whose send path replaces a running task (see `messaging.md`), park the message:

```bash
orch update e1 --pending-message "answer X, then resume per your brief"
```

On the worker's finish notification, drain **one** message, send it, then verify the turn that
started is yours; if not, restore it — there is no atomic send, so a lost race looks exactly like a
delivery. `roster` flags `MSG-QUEUED`.

## Deliberate non-goals

No history, no status log, no completed-work archive. Retrospectives come from the substrate's own
activity records; provenance comes from the repo. A tracker that accumulated history would grow
unbounded, cost tokens on every read, and duplicate two other sources of truth.
