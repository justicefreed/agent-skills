# Canonical model ids and harness-aware selection: delivery plan

## Objective

Make `context-economy`'s model selection, rate table and pricing eligibility correct in every
harness, starting with Claude Code, by keying all stored data on one canonical model id.

## Decisions

- **Canonical id is the provider's own API id.** Anthropic models use Anthropic's id, OpenAI models
  OpenAI's, Cursor-native models (Composer) Cursor's. Haiku uses the dated id
  (`claude-haiku-4-5-20251001`), never the undated pointer.
- **Every other name is a route-specific name that maps to a canonical id**: Cursor slugs
  (`claude-4.6-sonnet`), ocx routes (`claude-ocx-cursor--claude-sonnet-5`), harness aliases
  (`sonnet`, `opus`).
- **Stored data uses canonical ids only**: `model-options.json`, the rate table, the pricing
  snapshot.
- **Recommendations are canonical ids only.** A spawn instruction is a separate, derived field, never
  the recommendation.
- **Aliases are accepted on input and translated.** The translation is reported with its table date;
  an unknown or ambiguous alias is an error, never a guess.
- **Price is keyed by (route, canonical id).** The same model can bill differently per route.

## Data model

One route registry, versioned with the pricing snapshot
(`plugins/context-economy/references/pricing/`):

```jsonc
{
  "routes": {
    "anthropic":  { "harnesses": ["claude-code"], "name_pattern": "<id>" },
    "cursor":     { "harnesses": ["cursor", "paseo"] },
    "ocx-cursor": { "harnesses": ["claude-code"], "prefix": "claude-ocx-cursor--" }
  },
  "names": [   // route-specific name -> canonical id
    { "route": "cursor", "name": "claude-4.6-sonnet", "model": "claude-sonnet-4-6" }
  ],
  "aliases": { // input-only; dated because aliases move
    "claude-code": { "retrieved_at": "…", "map": { "sonnet": "claude-sonnet-5", "haiku": "claude-haiku-4-5-20251001" } }
  },
  "rates": [   // one row per (route, model)
    { "route": "anthropic", "model": "claude-sonnet-5", "input": "…", "cache_write_5m": "…",
      "cache_write_1h": "…", "cache_read": "…", "output": "…", "source_id": "…",
      "cache_semantics": { "evidence": "documented" } }
  ]
}
```

`model-options.json` moves to `schema_version: 3`: `id` is canonical, `provider` names the id's
owner, `pricing_key` is removed (price comes from the route in effect).

## 1. Verify canonical ids

For each of the 16 rows in `model-options.json` (listed below), record the provider API id from a
primary source: Anthropic's Models API or docs (the `claude-api` skill), OpenAI's, Google's, xAI's,
Moonshot's, and Cursor's for Composer. Do not derive ids by reformatting names. Unverified today:
`claude-4.6-sonnet`, `claude-opus-4.8`, `claude-opus-5`, `gemini-*`, `grok-4.6`, `kimi-*`.
Verified from the session environment: `claude-opus-5-5`, `claude-sonnet-5`, `claude-fable-5-1`,
`claude-haiku-4-5-20251001`.

Also record ids for historical models that appear in local transcripts, so `spend cost` can still
price old sessions.

**Done when:** every model row and every model id seen in `~/.claude/projects/**/*.jsonl` has a
canonical id with a source URL, or is explicitly listed as `unresolved`.

## 2. Registry, schema v3 and validation

Write the registry above and migrate `model-options.json` to canonical ids. Extend
`pricing.py validate`:

- every `model-options` id exists as a canonical model
- every name and alias resolves to exactly one canonical id
- no alias or route name appears as a canonical id
- each (route, model) has at most one rate row

**Done when:** `pricing validate` passes on the migrated files and rejects fixtures for each violation.

## 3. Rate table on canonical ids

Replace `DEFAULT_RATES` and token-substring matching in `spend.rate_for` with
`resolve(name) -> (route, canonical id)` followed by an exact (route, id) lookup:

- **Route inference from transcript model strings:** an ocx prefix means `ocx-cursor`; a bare
  Anthropic id in a Claude Code transcript means `anthropic`.
- **No `default` fallback.** An unresolvable model is reported as `unpriced` with its call count.
  Its cost is excluded, not guessed.
- **`SPEND_RATES` and `rates.json` overrides** keep working but must be keyed by (route, id); old
  short-name keys are rejected with a message naming the canonical id.
- **`orch.py`** keeps importing `load_rates` and `rate_for`. Its cost report surfaces `unpriced`
  instead of summing a fallback.

**Done when:**

- `test_spend.py` rate cases are rewritten to canonical ids and pass.
- `spend cost` on this repo's transcripts prices `claude-opus-5-5` from its own row.
- `orch.py`'s tests pass.

## 4. Alias translation on input

Add one `resolve_model(name, harness)` used by every `--model`, `--source-model` and `--target`
parameter. Output includes `"translated_from": "sonnet", "alias_table": "<date>"` when it fires.

**Done when:** a test proves that no model field in any JSON output of `spend models`,
`pricing eligibility` or `pricing eligible-models` equals a known alias or route name.

## 5. Harness detection and a Claude Code catalog

- **Detection.** Add `detect_harness()`: the `--harness` flag, then `CLAUDECODE` /
  `CLAUDE_CODE_SESSION_ID` → `claude-code`, then `CODEX_HOME` → `codex`, otherwise `cursor`.
  Every result names the harness it used.
- **Claude Code catalog.** It is derived, not shipped: canonical ids reachable through the registry's
  `claude-code` routes, plus agent definitions found in `~/.claude/agents/*.md` (`model:`
  frontmatter resolved to a canonical id).
- **Spawn field.** It keeps the route the recommendation was priced on. Within that route:
  1. an agent definition whose name is the canonical id
  2. an Agent-tool alias, only when the dated alias table maps that alias to exactly this id;
     otherwise it fails with "alias drifted"

  A routed definition on another route (e.g. `ocx-claude-sonnet-5`) is listed separately as a
  `via` alternative with its own route and price, never as the primary spawn. (Ruling (a) in the
  progress Log.)
- **`spend agents --write`.** An explicit command, not a hook, that writes one
  `~/.claude/agents/<canonical-id>.md` per recommended Claude model. It never touches files
  generated by opencodex.

**Done when:** with `CLAUDECODE=1`, `spend models --archetype implementer` prints canonical ids, each
with a spawn field the Agent tool accepts. With the harness forced to `codex` it reproduces today's
Codex output.

## 6. Pricing eligibility per route

`eligibility()` looks up (route, id) for source and target, using the harness's route. Anthropic
rows, with documented cache-write prices, are the first complete candidates.

**Done when:** under `claude-code`, `pricing eligible-models --rung minimal --source-model
claude-opus-5-5` gives a computed verdict for `claude-haiku-4-5-20251001`, not a "no reviewed
price" rejection. The Cursor fixtures keep their current results.

## 7. Transcript lookup and the rung hook

- **Transcript lookup.** `find_transcript` tries `~/.claude/projects/*/$CLAUDE_CODE_SESSION_ID.jsonl`
  before the cwd slug.
- **Rung hook.** `cmd_rung` names the rung's recommended canonical id and its spawn field. It stays
  silent when `subagent_type` resolves to an agent definition that pins a model.

**Done when:** `spend cost` succeeds from a subdirectory. Hook fixtures cover the three cases: unset
model, pinned `subagent_type`, and explicit `model`.

## 8. Guidance, version, validation

- Update `SKILL.md` §2 and `references/rungs.md` to say that recommendations are canonical ids and
  that aliases are input only.
- Bump `plugin.json` `version`.
- Reconcile `docs/self-switching-model-plan.md` §2 ("normalized effective route ID and aliases") with
  this registry.

**Done when:** `claude plugin validate . --strict` passes and all plugin test suites pass.

## Order and dependencies

1 → 2 → 3 → 4 are sequential; each consumes the previous step's data.

5 and 7 depend only on 2 and can run beside 3–4. 6 needs 3.

Builds on the uncommitted `spend.py`, `model-options.json` and `pricing.py` work in the tree.
