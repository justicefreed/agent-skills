# Adherence

A rule an agent can skip is a suggestion. Each obligation below is enforced by the strongest lever
that fits it: a **refusal** in `orch` (any harness), then a **turn-end block** (Claude Code Stop
hook). Every way out takes a reason, and the reason is recorded.

## Levels

`orch policy` shows the level; `orch policy off|warn|strict` sets it for the program. Unset is
`off`.

| Rule | `off` | `warn` | `strict` |
|---|---|---|---|
| `close` refuses an entry with `track:` targets | refuses | refuses | refuses |
| `resume` and `roster` print an `audit:` line when there are findings | yes | yes | yes |
| `open` requires a `track:` target (agent-track programs only) | — | warns | refuses |
| A lane's turn end checks its own checkpoint | — | reports | **blocks** |
| The orchestrator's turn end checks exceptions and unfinished consumptions | — | reports | **blocks** |

**Start at `warn`.** It runs every check and blocks nothing, which shows what `strict` would have
stopped before you rely on it.

**A program uses agent-track** when the planning repo has a `.track/` directory and `track` is on
PATH. Without both, the agent-track rules never apply — a program without agent-track can run at
`strict` and meets only the checkpoint and consumption checks.

## The turn-end check

`orch stop-check` runs as a Stop hook in every session and is silent unless the session belongs to a
program at `warn` or `strict`.

- **A lane** — the session whose worktree is exactly one running entry's `worktree` — must leave a
  checkpoint that exists, is fresh, and fills all four labels (`briefs.md`). The block names the
  missing labels.
- **The orchestrator** — every other session in the program — must not leave an exception or a
  harvested entry whose consumption never finished. Lane checkpoint problems never block it: it
  cannot fix them in its own turn.

**It blocks once per problem.** A turn the hook already continued (`stop_hook_active`), or a session
already blocked for the same set of problems, gets the text as context instead of a second block.
A changed set blocks again. A problem that cannot be fixed now — the worker is waiting on a human —
therefore costs one continuation, not a loop.

## Ways out

| Need | Command | Recorded as |
|---|---|---|
| Close track-linked work whose item must not advance | `orch close <e> --consumed "…" --untracked "<why>"` | `untracked-close` |
| Dispatch work that has no track item, at `strict` | `untracked_reason: <why>` in the brief | `untracked-open` |

Overrides go to `<program dir>/overrides.jsonl`. `orch audit` lists the last seven days under a
separate heading. They are decisions, not defects: they never fail `audit`.
