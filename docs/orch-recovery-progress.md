# orch checkpoint and recovery progress

## Completed

- Added atomic per-agent checkpoints under the external program state directory.
- Added required checkpoint fields for completed step, next step, and test state,
  with repeatable changed-file, pending-decision, and uncertain-operation lists.
- Added explicit recovery generations, a durable recovery ledger, and
  `orch recover <agent>` creation/adoption of the existing rotation protocol.
- Recovery is idempotent for an active matching generation, refuses a different
  successor, and refuses a second obligation after completion or abort.
- Uncertain external operations are recorded and printed as review-only; no
  replay path exists.
- Documented exact command usage, sidecar locations, atomicity, and substrate
  limitations in `references/state.md`.

## Verification

Tree: `/Users/jureed/.paseo/worktrees/30o9cik6/orch-recovery`

- `python3 -m py_compile plugins/orchestration/skills/orchestrating/scripts/orch.py`
  — pass.
- CLI help for `orch`, `orch checkpoint`, and `orch recover` — pass; both new
  commands are exposed.
- `git diff --check` — pass.
- Temporary `XDG_STATE_HOME` harness — pass: placeholder rejection (red path),
  checkpoint persistence, uncertain-operation warning, generation 7 recovery,
  repeated matching recovery adoption, different-successor refusal, rotation
  completion, and post-completion “already complete” behavior.
- Temporary `XDG_STATE_HOME` lifecycle harness — pass: recovery followed by the
  existing `orch rotate claim` and `orch rotate complete` commands.

No repository commit was made.
