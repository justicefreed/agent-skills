# Envelope-guidance progress

## Durable state

- Milestone complete: orchestration guidance now requires a small progress artifact for work that
  can outlive a turn.
- Milestone complete: `cursor_root_envelope_limit` and `cursor_blob_capacity` have distinct
  recovery procedures and loop guards.
- Milestone complete: uncertain external side effects are explicitly reconciled before replay.
- Next safe action: run the repository validation relevant to the three edited guidance files,
  then inspect the diff and working tree for scope violations.

## Decisions

- Exact proactive replay-envelope byte measurement is not claimed; OpenCodex may expose final
  replay-root bytes, but the skill only gives conservative checkpoint guidance.
- Root-envelope failure stops growth of the current replay root and leads to a seam-based
  rotation or compaction.
- Blob-capacity failure is treated as transient shared capacity and does not trigger recursive
  rotation.
- Mutation replay is prohibited while the external outcome is `unknown`.

## Verification record

- `claude plugin validate . --strict`: passed from this worktree.
- `git diff --check`: passed from this worktree.
- Falsification: the guidance would be red if either failure class lacked a distinct response, if
  blob capacity triggered recursive rotation, or if uncertain mutations were replayed
  automatically. A text-level adversarial check found all three prohibitions and both class names
  in the edited files; no red was observed.
- Scope check: only the three specified guidance files and this progress artifact are changed.
