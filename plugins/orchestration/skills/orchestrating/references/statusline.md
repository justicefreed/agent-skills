# The status surface

A program's status has three possible audiences, and they are not interchangeable:

| Audience | Channel | What it costs |
|---|---|---|
| the human, now | harness chrome (status line, composer pill) | nothing to the model |
| you, this turn | a command you run and read | one tool result |
| you, every later turn | anything narrated into the transcript | re-read as input on **every** later turn |

The third is the trap. A status paragraph written into chat is permanent context: in a measured
program, cache reads were 61% of the bill, and they are re-read at every subsequent model call.
This is why the roster does not belong in prose. It belongs in chrome the human reads and the model
never sees.

`orch statusline` is that chrome. One collector, two surfaces:

- **Claude Code** — a `statusLine` command; all of stdout is displayed.
- **Paseo** — the `orch-inbox` plugin's composer pill and `orch status` panel, which render the same
  JSON. See `assets/paseo-inbox-plugin/README.md`.

It reads **disk state only** and it never fails loudly: on any internal error it prints nothing and
exits 0, because a renderer that reports its own failure into a status bar is a renderer the human
switches off. Pass `--debug` to make it raise instead.

In a repo where no program has ever run, it prints nothing at all. Silence is the correct amount of
chrome for "nothing is being orchestrated here."

## Output

```bash
orch statusline                      # one line, for a status bar
orch statusline --format multiline    # that line plus one row per dispatch entry
orch statusline --format json         # everything, for a GUI adapter
```

A representative line:

```
orch:agent-track · 3 run · 1 pend · ✉2+1 · $41 · ctx 63% · !ctx unrecorded · trk 1
```

| Segment | Reads | Says |
|---|---|---|
| `prog` | the program directory | which program, when not `default` |
| `lanes` | every tracker under the program | entries by status; `idle` when none |
| `inbox` | `inbox/*.jsonl` and their cursors | `✉<mine>+<others>`; the count is omitted when only others have items |
| `cost` | `cost/*.json` snapshots and `budget.json` | program spend, `/limit` when one is set, `~` when the snapshots are stale |
| `ctx` | the harness payload, else the own-target snapshot | context depth as a percentage |
| `alerts` | the same thresholds the turn-end hooks use | `!` plus one word per live advisory |
| `track` | `track inbox --json`, cached | `trk N` — items awaiting a human in agent-track |

`--segments lanes,inbox` renders a subset; `--ascii` drops the glyphs; `--max-lanes` and `--width`
bound the multiline rows. `--format json` never emits ANSI escapes, so a GUI can use `line` verbatim.

### Advisories

| Code | Meaning |
|---|---|
| `rotate` | this session is past the rotation threshold — `references/cost.md` |
| `ctx` | context depth is deep enough to be paying the tax |
| `budget` | program spend is at or over `budget.json`'s limit |
| `fanout` | more running lanes than the fan-out guide recommends |
| `unrecorded` | a running entry has no recorded agent id, so nothing can reach it |
| `brief` | an entry's `brief_path` no longer exists on disk |

The thresholds are the ones `orch cost` and `orch guard` already use. That is deliberate: two
surfaces disagreeing about whether something is wrong is worse than one surface saying nothing.

## Where the numbers come from

Every read the collector makes is a small JSON file, so the reads themselves are microseconds — the
expensive reads were already paid for elsewhere. Note where that leaves the cost: what a render
actually spends is dominated by starting a Python interpreter, not by anything the collector reads.
That is why the snippets below name an interpreter rather than letting `PATH` answer — with a shim
first on `PATH`, resolving the name costs far more than the whole collection it precedes, on a
command the harness runs after every assistant message.

- **Cost** comes from `<program>/cost/<target>.json`, written by `orch cost` — which the skill's
  turn-end hook already runs. The status line never opens a transcript itself; transcripts are
  megabytes and this runs on every assistant message. If those snapshots go stale the line says so
  (`stale` in JSON), so a dead hook is visible instead of quietly reporting an old number.
- **Context depth** comes from the harness payload when there is one, else from the same snapshot.
- **The agent-track count** is fetched by running `track inbox --json` and cached for 15s in
  `<program>/track-cache.json`. On any failure the cached value stands.

What the reads cost is not what the *command* costs. Starting it dominates: one Python interpreter,
plus the `git rev-parse` that identifies the repo. Both are bounded — `git` by `ORCH_GIT_TIMEOUT`,
because a dozen linked worktrees sharing one common git dir make `index.lock` contention ordinary,
and an unbounded wait on a per-message command does not fail, it wedges and then overlaps with the
next render. The interpreter is bounded only by which one you name: leave `python3` to `PATH` and a
pyenv or asdf shim in front of it can turn a 50ms start into most of a second, on a command the
harness runs after every assistant message. Hence the resolution in the snippets below — prefer a
known-absolute interpreter, and let `PATH` answer only as a last resort.

## Claude Code

`~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "PY=\"${ORCH_PYTHON:-}\"; [ -x \"$PY\" ] || PY=/usr/bin/python3; [ -x \"$PY\" ] || PY=python3; exec \"$PY\" ~/.claude/skills/orchestrating/scripts/orch.py statusline"
  }
}
```

`orch.py` runs on the system interpreter, so `/usr/bin/python3` is the right default: it is the one
path that is a platform guarantee rather than a `PATH` accident. `ORCH_PYTHON` names a different one
where that matters.

Claude Code re-runs this on session start and resume, after every assistant message, on `/compact`
completion, and on permission-mode or vim-mode changes. It hands the command a JSON payload on
stdin — `workspace.current_dir`, `cost.total_cost_usd`, `context_window.used_percentage`, and the
rest — which is why the default `--repo .` is repointed at the payload's cwd, and why session cost
and context depth are exact rather than inferred when the payload is present.

**Composing with a status line you already have.** Most people already run one, and the payload can
only be read once. Forward it:

```bash
#!/usr/bin/env bash
PY="${ORCH_PYTHON:-}"; [ -x "$PY" ] || PY=/usr/bin/python3; [ -x "$PY" ] || PY=python3
INPUT=$(cat)
ORCH=$(printf '%s' "$INPUT" | "$PY" ~/.claude/skills/orchestrating/scripts/orch.py statusline)
printf '%s' "$INPUT" | your-existing-statusline
[ -n "$ORCH" ] && printf '\n%s' "$ORCH"    # second line, only when there is something to say
```

One interpreter, not two: a wrapper that spawns `python3` twice pays the start twice on every
message.

Multi-line output is supported, so the orch line can sit under the existing one rather than fight it
for width. `--stdin never` skips the payload wait entirely for a caller that has nothing to hand it.

## Paseo

Install the plugin (`assets/paseo-inbox-plugin/`), then `/orch` in an agent's composer pins the pill
for that agent. The pill's label is this same rendered line; pressing it opens the roster panel. The
plugin's README covers the pinning model, the poll intervals, and why the pill cannot appear by
itself.

## The agent-track boundary

agent-track owns work items, gates, dependencies and the critical path. This surface owns *lanes* —
which agents are dispatched, what they were given, who is waiting on whom, and what it is costing.
They overlap in exactly one number: how many items are awaiting a human.

That number is borrowed, never recomputed:

- it comes from the `track` CLI, never from parsing `.track/` files;
- it is skipped entirely when the repo has no `.track/` directory or no `track` on `PATH`;
- `--track off` opts out.

So the surface is useful in a repo that has never heard of agent-track, and additive in one that
uses it.

## Environment

| Variable | Effect |
|---|---|
| `ORCH_INBOX_TARGET` | which inbox target counts as "mine" (also `--to`) |
| `ORCH_AUTOCOMPACT_WINDOW` | the context window the percentage is measured against, absent a payload |
| `ORCH_STATUSLINE_STDIN_WAIT` | seconds to wait for a harness payload before giving up (default 2) |
| `ORCH_GIT_TIMEOUT` | seconds a `git` call may take before the line goes quiet (default 5) |
| `ORCH_PYTHON` | interpreter the snippets above run; read by the shell, not by `orch.py` |
| `NO_COLOR` | disables ANSI colour, as does `--color never` |

## When it says nothing

In order: the repo has no program (correct, and intended); several programs exist and none was
chosen, in which case the line says `pick --program (a, b)` rather than guessing; or the collector
raised. Distinguish the last one with:

```bash
orch statusline --debug --format json
```
