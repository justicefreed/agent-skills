# Canonical model ids — L2 notes (plan steps 2, 3, 4, 6)

Brief: `L2-core.md`. Log: `docs/canonical-model-ids-progress.md`. Nothing committed.

## Shape

- `references/pricing/current.json`, schema 2, holds everything: `sources` (with digests),
  `routes`, `models` (canonical ids + provider + source), `names`, `aliases`, and `rates` (one row
  per (route, canonical id)).
- **Two rate shapes.** A row is either flat (`input`, `cache_write`, `cache_read`, `output`), as
  Cursor and OpenAI publish, or tiered (`… cache_write_5m`, `cache_write_1h` …), as Anthropic
  publishes. A row that mixes the two is rejected. spend bills a flat `cache_write` into both
  transcript buckets.
- **`billing_route`.** `ocx-cursor` has `billing_route: cursor`, so it has no rate rows of its
  own. Lookups go to (cursor, id). This follows the ruling that ocx-cursor uses Cursor-route rates,
  without duplicating rows.
- **Route inference** (`Registry.resolve_route_name`):
  1. The longest matching route `prefix` names the route.
  2. Otherwise a bare canonical id arrives on the route named for its provider (`anthropic`,
     `openai`, `cursor`).
  3. Otherwise a bare name is looked up in `names`, then in alias tables that declare a `route`.
     Only `anthropic-api` does, so the transcript string `claude-haiku-4-5` prices as the dated id.
- `pricing.py` owns the registry. `spend.py` loads it by file path under a private module name,
  because orch loads spend by path from another plugin.

## Behaviour that changes in the field

1. **Totals drop, and 196 corpus calls become `unpriced`.** Across 1,786 transcripts the total
   goes from $2,994.42 to $2,911.33.
   - $78.45 comes from `cursor/claude-opus-5` (185 calls): Cursor no longer lists it.
   - $4.84 comes from `claude-opus-5-5` (99 calls): it used to be priced at the `opus-5` row by
     substring match.
   - Every other model's total is unchanged.
2. **This session's transcript**, frozen at 51 calls, goes from $6.73 to $4.07. All calls are
   `claude-opus-5-5`, which now prices at its own row: $4 in / $20 out / $8 1h write / $0.20 read,
   against the old $5 / $25 / $10 / $0.50.
3. **Transcript counts shrink.** `<synthetic>` lines are skipped outright (744 calls), and 46
   transcripts that contain only synthetic lines now report "no model calls".
4. **Tokens in a null bucket make the call unpriced.** A call with tokens in a bucket its route
   prices as null (Cursor's dash, e.g. composer cache writes) is unpriced. It used to be billed at
   0. This is fail-closed and deliberate.
5. **Model-string lookup is exact and case-sensitive.** `cursor/GPT-5.6-sol` is unpriced now; the
   old test pinned case-insensitivity. Provider ids are lowercase, so I chose exactness. It's a
   one-line change (`.lower()` in `resolve_route_name`) if you disagree.
6. **Malformed overrides are errors now.** An old short-name `rates.json` or `SPEND_RATES`,
   invalid JSON, or an orch program-local `rates.json` in the old format used to be silently
   ignored or substring-matched. Now it's a hard error that names candidate canonical ids.
   - spend's `main` turns errors into exit 0 plus a stderr message, so hooks don't break a turn,
     but `spend cost` output disappears until the file is fixed.
   - orch exits 2.
7. **`spend models` output changes.** It prints canonical ids, with the matched catalog slug in a
   new `catalog_slug` field. Under Codex the two are identical, so `spend models --archetype
   implementer` output is byte-identical to before.
8. **Two options changes.** `model-options.json` loses `grok-4.6` (its canonical id is unresolved,
   so it can't pass the "every option is canonical" rule). `claude-haiku-4-5` becomes
   `claude-haiku-4-5-20251001`.
9. **Cursor's 1h write price for Fable 5.1 changes.** It is now the untiered $12.50, where the old
   table synthesized $20. The corpus had no 1h writes on that route, so the delta is $0.

## Guessed or inferred (defend or concede)

- **`default_harness()` returns `cursor`.** That is the plan's final fallback. It is the seam L3
  replaces with `detect_harness()`. Until then, pass `--harness claude-code` to price Anthropic
  rows.
- **`ocx-cursor` carries every Cursor-priced model.** So under `claude-code`, `composer-2.5` and
  `gpt-5.6-luna` resolve to route `ocx-cursor`. That holds only if opencodex can route any Cursor
  slug. Step 5 should restrict ocx-cursor to models that have an `ocx-*` agent definition. I did
  not, because that data belongs to the catalog lane.
- **Cursor names I added.** The research JSON's `names` list omitted `claude-4.6-sonnet` →
  `claude-sonnet-4-6` and `claude-opus-4.8` → `claude-opus-4-8`. The research unresolved list
  calls those canonical ids confirmed, and the plan's own example uses the first mapping.
  Without these rows the old option ids would not translate.
- **Eligibility bills a tiered target's switch at `cache_write_5m`.** A micro-op prefix is read
  back within minutes.
- **The Claude Code alias table is L1's inference** (research caveat 8), not a published binding:
  `opus` → `claude-opus-5`, not `-5-5`. It is dated 2026-09-23 and every translation reports that
  date.

## Needs a human ruling

1. **`grok-4.6`.** Drop it (done), or record it as canonical on the strength of the xAI release
   note plus Cursor's matching price?
2. **OpenAI now publishes terra and luna.** L1 reported no OpenAI source for `gpt-5.6-terra` or
   `gpt-5.6-luna`, but it got a 403. With a browser user-agent, `platform.openai.com/docs/pricing`
   returns 200 today and lists both at standard tier:
   - terra: $2 in / $0.20 cached / $2.50 write / $12 out
   - luna: $0.20 / $0.02 / $0.25 / $1.20

   That confirms the orchestrator's ruling from a primary source. I cited it on the two model
   entries and recorded the digest, but added no `openai`-route rate rows for them: the brief
   makes the research JSON the only rate source. Adding them would give Codex-harness eligibility
   a price.
3. **Case-insensitive lookup** (field change 5).

## Verification

- `python3 plugins/context-economy/scripts/test_spend.py` → all pass.
- `python3 plugins/context-economy/scripts/test_pricing.py` → all pass. This includes a rejection
  fixture per step-2 rule, the translation cases, the step-6 Haiku verdict, and the step-4 guard.
- **Guard seen red three times**, each green after revert:
  - on the pre-change `spend models` output, which leaked `cursor/claude-sonnet-5` and
    `claude-ocx-cursor--gpt-5.6-terra`;
  - with `spend models` temporarily emitting `sonnet`;
  - with `eligibility` echoing its input names.
- **orch has no Python test suite in this repo.** The only test file under `plugins/orchestration`
  is a TypeScript one for the Paseo plugin. `py_compile` passes. `orch cost` was smoke-tested:
  - text and JSON output list unpriced calls and exclude their cost;
  - a short-name `SPEND_RATES` is rejected with the canonical ids named.
- `claude plugin validate . --strict` passes. `plugin.json` version is untouched (step 8).

## Stale prose left for step 8

`docs/CONTEXT-ECONOMY.md` (lines ~108, ~163) and `docs/DESIGN.md` (~255) still describe
`DEFAULT_RATES` and the 1h-synthesis rule. `SKILL.md` and `rungs.md` are step 8's job.
