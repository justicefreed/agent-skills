# Envelope integration progress

## Landed source commits

- `d08b947` guidance: replay-envelope recovery guidance and durable checkpoints.
- `191e108` orch recovery: checkpoint persistence and generation-safe recovery.
- `af1c117` recovery guard: classifier, durable notice, and timeline status.

## Integration

- Cherry-picked as `4f9912a`, `3766536`, and `7ce46a3`.
- Accepted all three lane diffs; no out-of-scope edits or semantic conflicts.
- The plugin guard intentionally does not create successors automatically because Paseo
  lacks a transactionally idempotent replacement primitive.

## Validation

- `claude plugin validate . --strict` — pass.
- Plugin `npm run typecheck` and `npx --yes tsx --test server/recovery.test.ts` — pass.
- Python compilation and `git diff --check` — pass.
- Temporary checkpoint/recovery harness — pass, including uncertain-operation warning and
  duplicate-successor refusal.
- Deliberate red observations: generic `request too large` is unclassified; placeholder
  checkpoint agent id is rejected; duplicate successor is refused.
