# Cross-repo programs

One **planning repo P** holds the program: `orch` state, agent-track items, the orchestrator. Workers
run in linked worktrees of any **code repo C**. Workers never write agent-track; `consume` never
writes a progress artifact.

## Home binding

`repo_identity` resolves the program home: `ORCH_HOME` (a path inside P), else the **home marker**
`<per-worktree git dir>/orch-home.json`, else the cwd's own repo. **A bound lane resolves exactly
as a linked worktree of P does** — no command special-cases cross-repo.

- `orch open` writes the marker when the brief's `worktree` is in another repo. It refuses a
  missing worktree, a primary checkout (the marker would bind every session there), and a marker
  naming a different program or entry.
- `orch close`/`consume` remove it when it names that entry.
- `orch audit` reports `home-unbound` if a running cross-repo entry's marker is gone.

## One integrator per target repo

Lanes landing into the same C go through one integrator. Per-repo integration is a convention, not
code.

## Rework

Correction after acceptance: `orch update` the entry, then `orch inbox send` the correction
**verbatim**. No track write — the item has not advanced.

## `orch consume <entry>`

`--consumed "<text>" --evidence <ev>...` (`commit:<repo>@<sha>[,on=<ref>]`, `file:<abs path>`);
`--skip-target <id> --reason`, `--no-notify`. Evidence is verified first; the decision is recorded
before any effect.

| Exit | Meaning |
|---|---|
| 0 | all targets `applied`/`already`/`skipped`; entry closed |
| 1 | evidence or arguments rejected; no state change |
| 3 | a target failed; entry stays `harvested`; exception written |

Resolve an exception by fixing the cause named in its repair line and re-running `orch consume
<entry>` (no flags; evidence re-verified, only unapplied targets retried), or by
`--skip-target <id> --reason "<why>"`. `orch resume` prints each unapplied exception.

## `orch audit [--json]`

Report-only; exit 1 on any finding. Codes: `checkpoint-missing`, `checkpoint-stale`
(`ORCH_CHECKPOINT_STALE_MIN`, default 30), `checkpoint-incomplete`, `harvested-unfinished`,
`exception`, `home-unbound`, `target-moved`.
