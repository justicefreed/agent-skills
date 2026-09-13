# Recovery guard progress

## Scope

Implemented the bundled `orch-inbox` Paseo plugin recovery guard. The only changed
paths are the four expected plugin artifacts and this progress record.

## Completed

- Read the binding `AGENTS.md`, plugin skill, Paseo v0.8 plugin docs, and substrate
  guidance.
- Added structured-code and exact fallback-phrase classification for
  `cursor_root_envelope_limit` versus `cursor_blob_capacity`.
- Added generation/idempotency-aware compact records persisted through
  `orch inbox send`; reloads preflight `orch inbox list --all` before appending.
- Added a supported Paseo timeline row with separate actionable rulings.
- Preserved the no-replay rule.

## API ruling

Paseo supports agent creation, but the documented SDK does not offer a
transactionally idempotent same-workspace replacement operation. Automatic
successor creation is therefore intentionally not enabled. The existing
`orch rotate` protocol remains the operator-managed boundary.

## Falsification / red observations

The classifier returns `null` for generic “request too large”, unknown provider
codes, and a root phrase presented as a blob phrase (and vice versa). These are
deliberately red cases: the guard must not guess across the two failure classes.

## Verification

- `npm run typecheck` passes for both client and server programs.
- `npx --yes tsx --test server/recovery.test.ts` passes 2 tests, including the
  deliberate generic “request too large” red case and cross-family structured
  code precedence case.
- `git diff --check` passes.
