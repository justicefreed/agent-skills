# Spec — cross-repo programs and `orch consume`

Status: **draft, awaiting approval**. Target: `orchestration` 0.17.0. Rationale graduates into
`docs/DESIGN.md` §9h at merge; this file is the build contract and is deleted after.

## Goal

One planning repo **P** holds the program: the `orch` state, the agent-track items, the
orchestrator. Workers run in linked worktrees of any code repo **C**. After the orchestrator accepts
a lane's output, **one command** verifies the evidence, advances the agent-track item, and closes the
entry — or leaves a persistent, visible exception that names the exact repair. Nothing depends on
the orchestrator remembering a second write.

Single source of truth, by owner:

| Store | Owns | Sole writer |
|---|---|---|
| agent-track in P | work items, tasks, gates, dependencies | the orchestrator, via `track` (or `orch consume` on its behalf) |
| `orch` state for P | lanes, briefs, inboxes, harvested state, exceptions | `orch` |
| progress artifact in C's worktree | the lane's recovery checkpoint | the worker |
| git in C | the code and the landing evidence | the worker / integrator |

Workers never write agent-track. `consume` never writes a progress artifact.

## Non-goals (deferred, not rejected)

Program clerk; control-event queue and `finalize`; plan-document projection; `orch rule`,
`orch rework`, `orch report`; statusline `!ops` segment; `audit --nudge`; per-repo integrator
*code* (documentation only).

## A. Rollback tolerance — first commit, cherry-pickable to `main`

Before any trial install, main's `orch` must read state the branch writes without erroring:

1. `advances` items may be mappings (see §C). Main accepts a mapping that has a `track` key and does
   no further validation of it; `render`/`roster` print it as `track:<id>`.
2. A program directory may contain `exceptions/`. Nothing on main may treat it as a tracker
   (`tracker_names` lists by name — confirm with a test, do not assume).
3. Tracker entries may carry `consumed_text`, `evidence`, `consumed_at`. Main preserves unknown
   entry keys on rewrite.

**Done when:** a test writes a brief with a mapping `advances`, an entry with the three new keys and
an `exceptions/` directory, and main's `open`/`roster`/`render`/`resume`/`close`/`statusline` all
succeed on it. This commit lands alone, first, with no other change.

## B. Home binding

### Resolution

`repo_identity(start)` resolves the program home in this order, first match wins:

1. `ORCH_HOME` env var — a path inside P. Manual override for harnesses and humans.
2. **Home marker** — `<per-worktree git dir of start>/orch-home.json`.
3. `start`'s own repository — today's behaviour, unchanged.

Return value is P's `(repo_key, root, common)` for 1–2. The marker is read from the filesystem
only, never by spawning git: `statusline` runs this after every message. Extend `_fs_common_dir`'s
walk to also yield the per-worktree git dir (for a linked worktree, the `gitdir:` target of the
`.git` file). If the filesystem walk returns None, fall back to `git rev-parse --absolute-git-dir`.
Cache exactly as today.

**Equivalence principle:** a lane bound to P resolves *exactly* as a linked worktree of P does
today. That is the whole design. No command gets cross-repo special-casing; the guards, statusline,
cost and inbox hooks behave for a bound lane as they already do for a same-repo lane. If a command
seems to need special handling, that is a spec question — stop and report it, do not patch around it.

### Marker

```json
{"version": 1, "repo_key": "<P key>", "root": "<P root>", "common": "<P common dir>",
 "program": "<program>", "tracker": "root", "entry": "e3"}
```

- **Written by `orch open`** when the brief's `worktree` resolves to a repo_key different from the
  orchestrator's. Atomic write (temp + rename). Idempotent when the content matches.
- `open` **refuses** a cross-repo brief whose `worktree` (a) does not exist, or (b) is a primary
  checkout (`git-dir == common-dir`): "cross-repo lanes need a linked worktree — a marker in a
  primary checkout would bind every session in that repo". It refuses if a marker already exists
  for a *different* program or entry.
- **Removed by `orch close`** (and by `consume`'s close) when the marker names that entry. A marker
  for another entry is left alone.
- `resolve_program(repo_key, None)` prefers the marker's `program` when resolved via a marker.

**Done when:** in a test with two temp repos P and C (C on a linked worktree), with the lane's cwd
inside C: `orch inbox send` from P is delivered by C's `inbox drain --format hook`; `orch whoami`
returns the entry; `orch resume` in C shows P's program. The same with `ORCH_HOME` set and no
marker. Closing removes the marker. Each of the four refusals has a test.

## C. Structured `advances`

The list may mix the legacy form and a new mapping form:

```yaml
advances:
  - 3.4                                   # legacy: plan row; no automated effect
  - track: T-015                          # agent-track item in P
    expect: "Implement retry policy"      # required: the task label this lane completes
```

- Mapping keys: `track` (required), `expect` (required, non-placeholder). Any other key is
  rejected. `op` is reserved for later; absent means "advance".
- At `open`, for each track target, `orch` runs `track show <id> --json --cwd <P root>` and refuses
  the brief if: `track` is not on PATH; the item does not exist; no task has label `expect`
  exactly; that task is already done. A target whose task is not yet *current* is allowed.
- Map field names to the real `track show --json` output (`tasks[]`, `currentTask.label`); verify
  against a live run, do not trust this spec's guesses.

## D. `orch consume`

```bash
orch consume <entry> --consumed "<what happened>" --evidence <ev> [--evidence <ev> ...] \
  [--tracker <id>] [--no-notify] [--skip-target <track id> --reason "<why>"]
```

### Evidence (≥1 required; all must verify)

| Form | Verified by |
|---|---|
| `commit:<repo path>@<sha>` | `git -C <repo> cat-file -e <sha>^{commit}` |
| `commit:<repo path>@<sha>,on=<ref>` | the above, plus `git -C <repo> merge-base --is-ancestor <sha> <ref>` |
| `file:<abs path>` | exists, non-empty |

Repo paths are realpath'd; relative paths are an error. No `#` in the syntax (the user's shell
guards refuse comments).

### Sequence

1. Load the entry (existing locking). Refuse a `pending` entry. Refuse a placeholder `--consumed`.
2. Verify every evidence item. Any failure: exit 1, **no state change**, print which item failed.
3. Record the decision: `status: harvested`, `consumed_text`, `evidence`, `consumed_at`. Save. The
   decision is durable before any effect is attempted.
4. For each track target, in order, against P (`--cwd <P root>`):
   - `track show <id> --json`. If the `expect` task is done → state `already`.
   - Else if it is `currentTask` → `track advance <id> --expect "<expect>" --json [--notify]`.
     Success → `applied`.
   - Else, or on any `track` error code (`WRITE_CONFLICT`, `GATE_REQUIRES_RULING`,
     `ITEM_COMPLETE`, not found) → `failed`, with the code and a repair line.
   - A `--skip-target` id → `skipped`, with the reason recorded.
   Legacy plan-id targets: print `plan <id>: update by hand`; never automated.
5. All targets `applied`/`already`/`skipped` → delete any exception file and close the entry through
   the **same code path as `orch close`** (refactor `cmd_close`'s body into a shared function: wake
   and reclaim obligations, child-tracker note, marker removal). Exit 0.
6. Any `failed` → write/overwrite the exception file (§E), leave the entry `harvested`, print the
   repair lines, **exit 3**.

Output on success is decision-relevant deltas only, one line per target, from the write's JSON:
`T-015 advanced → "Verify production behavior" (blocked by T-019)`.

### Retry

On an already-`harvested` entry, `--consumed` and `--evidence` may be omitted; the recorded values
are reused (evidence is re-verified). Retrying re-runs step 4 for non-`applied` targets only.
`--notify` is on by default; `--no-notify` suppresses it.

## E. Exceptions

`<program dir>/exceptions/<tracker>.<entry>.json`, one per entry, overwritten on retry:

```json
{"version": 1, "tracker": "root", "entry": "e3", "title": "…", "created_at": "…",
 "updated_at": "…", "attempts": 2, "consumed": "…", "evidence": ["commit:…"],
 "targets": [{"track": "T-015", "expect": "…", "state": "failed",
              "code": "WRITE_CONFLICT", "detail": "current task is \"Approve design\"",
              "repair": "track show T-015 --cwd <P>; then: orch consume e3"}]}
```

Surfacing — no new segment, only existing surfaces:

- `orch resume` (and so the SessionStart hook) prints an `UNAPPLIED CONSUMPTION` block listing each
  exception and its repair lines.
- `roster`/`render` mark the entry `harvested !track`.
- The statusline already counts `harv`; no change.

## F. `orch audit`

Report-only. `orch audit [--json]`; exit 1 if any finding (like `track lint`), 0 if clean. Findings:

| Code | Condition |
|---|---|
| `checkpoint-missing` | running entry has `progress_artifact` but the file does not exist |
| `checkpoint-stale` | file mtime older than `ORCH_CHECKPOINT_STALE_MIN` (default 30) minutes while the entry is running |
| `checkpoint-incomplete` | any of the four labels below is absent, empty, or vacuous |
| `harvested-unfinished` | harvested for >10 min with no exception file (a crashed `consume`, or a hand-set status) |
| `exception` | an exception file exists |
| `home-unbound` | a cross-repo running entry's marker is missing or names another entry |
| `target-moved` | a running entry's track target task is already done |

`progress_artifact` relative paths resolve against the **entry's `worktree`**, never cwd or P.

The checkpoint contract, added to `briefs.md`: four labels, each as a `Label:` line or a
`## Label` heading followed by content — `Last durable milestone`, `Verification`,
`Uncertain external effects`, `Next safe action`. Vacuous = matches `PLACEHOLDERS` or one of
`continue`, `ongoing`, `in progress`, `wip`, `pending`, `see above` (case-insensitive, whole value).
`Uncertain external effects: none` is valid.

## G. Docs

- `SKILL.md`: a short cross-repo subsection, and "use `consume`, not `close`, for track-linked
  work". Net addition ≤150 words; the detail goes in a reference.
- New `references/cross-repo.md`: layout, home binding and marker, the one-integrator-per-target-repo
  rule, the rework recipe (`orch update` + `orch inbox send` with the correction verbatim; no track
  write), the exception-resolution paths.
- `references/briefs.md`: the mapping `advances` form and the checkpoint labels.
- `docs/DESIGN.md` §9h: the why — the equivalence principle, marker over env, decision-before-effect,
  why no clerk yet.
- `plugin.json` 0.17.0.

## H. Tests — the acceptance list

New suites `scripts/test_orch_home.py` and `scripts/test_orch_consume.py`, auto-discovered by
`scripts/test.sh`. A **fake `track`** on PATH (a small script that reads and writes a JSON fixture
and emits the real error codes) keeps them hermetic and fast. One extra case runs the real `track`
when it is installed and skips otherwise.

Each of these must fail before the code exists and pass after:

1. §A compatibility case.
2. §B delivery, whoami, resume, env override, marker removal, the four refusals.
3. §C: open refuses a missing item, a missing label, a done task, an unknown key, a missing `track`.
4. §D happy path: verified evidence → advanced → entry gone → marker gone → exit 0.
5. §D: bad evidence → exit 1 and the tracker file byte-identical.
6. §D: `WRITE_CONFLICT` → exit 3, entry harvested, exception file has the code; fix the fixture,
   retry with no flags → exit 0 and the exception file gone.
7. §D idempotency: the expected task already done → `already`, and the fake `track` saw no write.
8. §D: `--skip-target` resolves a failed target.
9. §F: each finding code triggered by one deliberately corrupted fixture — including a vacuous
   checkpoint with a fresh mtime — and a clean program exits 0.

**Done when** `scripts/test.sh` reports `all suites pass` and `claude plugin validate . --strict`
is clean.

## I. Lane plan

Time is the priority. Every brief carries the working rules below verbatim.

| Lane | Owns | Rung |
|---|---|---|
| core | `scripts/orch.py` only — §A, then §B, §C, §D–E, §F, one commit each | frontier |
| tests | the two new suites and the fake `track` | standard |
| docs | `SKILL.md`, `references/`, `docs/DESIGN.md`, `plugin.json` | standard |

Each lane works in its own worktree off this branch. The orchestrator merges, runs the full suite,
and does one real two-repo dry run.

**Working rules (all lanes):**

- **Wall-clock time matters more than polish.** Build exactly what this spec says. No refactors,
  renames or cleanups beyond what a section requires.
- Read only the files you own and the functions this spec names. No survey of the codebase.
- When the spec is ambiguous, take the simpler reading, note it in one line in your report, and
  keep going. Stop and ask **only** if the simpler reading would break the equivalence principle or
  write a store this spec says you do not own.
- Iterate on your own suite only; run `scripts/test.sh` once, at the end.
- Keep a progress artifact in your worktree with the §F labels; update it after each section.
- Report in ≤150 words: what landed (commit SHAs), the ambiguities you resolved, and anything
  that is red.
