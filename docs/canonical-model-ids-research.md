# Canonical model ids, Anthropic rates, and route names — research

Plan: `docs/canonical-model-ids-plan.md` step 1. All web sources fetched 2026-09-23 via `curl`
inside `ctx_execute` (WebFetch/MCP fetch-and-index were both non-functional this session — WebFetch
was redirected to a broken context-mode plugin, and `ctx_fetch_and_index` itself errored on a
mismatched native `better-sqlite3` build). Raw HTML was stripped of `<script>`/`<style>` and tags,
then grepped; no page content is quoted beyond short excerpts below.

## Caveats (read before consuming the JSON)

1. **Cursor's live lineup has moved past the `model-options.json` snapshot (2026-09-18).** Cursor's
   current pricing page (fetched today) lists only **Claude Sonnet 5, Claude Opus 5.5, Claude Fable
   5.1** for Claude, plus Gemini 3.1 Pro, Gemini 3.8 Flash, Muse Spark 1.3, GPT-5.6 Sol/Terra/Luna,
   Grok 4.7/4.6/4.5, and Composer 2.5. **`claude-4.6-sonnet`, `claude-opus-4.8`, `claude-opus-5`
   (non-5.5), and both Kimi models are absent from the current page entirely** — grepped for
   case-insensitively across the full fetched HTML including `<script>` payloads, zero hits. They
   may still work as pinned model strings against Cursor's API, but there is no live primary source
   for their current price or even their continued existence on the Cursor side.
2. **`gpt-5.6-luna` and `gpt-5.6-terra` have no OpenAI primary source at all.** OpenAI's own
   `docs/models` and `docs/pricing` pages (fetched in full, confirmed complete — the pricing page
   ends at "Finetuning" with no truncation) show a `GPT-6` flagship generation (`gpt-6-astra`,
   `gpt-6-sol`, `gpt-6-luna`) and a legacy `gpt-5.6-sol` (still billed, promotional pricing through
   2026-11-21) and `gpt-5.6-cyber` (Daybreak). **There is no `gpt-5.6-terra` anywhere on
   OpenAI's site, and no `gpt-5.6-luna`.** "Terra" does not appear as any OpenAI model name in either
   document. Cursor names a model "GPT-5.6 Terra" and "GPT-5.6 Luna" today, but that is Cursor's own
   display name — it is not traceable to an OpenAI-issued id. Both go to `unresolved`.
3. **`gpt-5.6-sol` is confirmed and its rate matches exactly.** OpenAI's "All models" legacy pricing
   table lists `gpt-5.6-sol` at $4 / $0.40 (cached) / $5.00 (cache write) / $20 output per MTok —
   identical to the number already in `DEFAULT_RATES["gpt-5.6-sol"]` and to Cursor's own listed price
   for "GPT-5.6 Sol". This is the one OpenAI-family id in `model-options.json` with a clean primary
   source.
4. **`gemini-3.1-pro` (the id used in `model-options.json` and Cursor's display name) is not
   Google's real id.** Google's own pricing page gives the model as `gemini-3.1-pro-preview` (and a
   `-customtools` variant); pricing is tiered by prompt size (≤200k vs >200k tokens). The ≤200k tier
   ($2 in / $12 out / $0.20 cache) matches Cursor's flat number, so Cursor is presumably always
   billing the ≤200k tier. `gemini-3.8-flash` is exact and needed no correction.
5. **`grok-4.6`'s canonical id could not be freshly confirmed.** xAI's live model pages
   (`docs.x.ai/docs/models`, `/developers/grok-4-6`) now redirect/render as the current flagship
   (`grok-4.7`) — Grok 4.6 has no live page. The **xAI release notes** (dated Aug 12) confirm "Grok
   4.6" shipped with pricing $2/$0.50/$6 (≤200k) and $4/$1/$12 (>200k) per MTok, matching Cursor's
   number exactly, but the notes never spell out the literal API string, and xAI's confirmed ids use
   dotted form (`grok-4.7`, verified live) — so `grok-4-6` vs `grok-4.6` is inferred by pattern, not
   observed. Flagged `unresolved` per the "never reformat" rule, despite strong circumstantial
   evidence.
6. **`kimi-k3` and `kimi-k2.7-code` are both confirmed real, current Moonshot ids** (present in
   Moonshot's own model list and curl/Python examples), but **no rate could be sourced** — Moonshot's
   pricing pages render numbers client-side (only labels came back in static HTML), and Kimi is no
   longer listed on Cursor's pricing page at all. Ids go in `models`; no `rates` row exists for them.
7. **Claude Fable 5 and Claude Fable 5.1 have different cache-read prices** ($1.00 vs $0.25 per
   MTok) despite identical input/output/cache-write prices — easy to miss since every other number
   matches. Confirmed directly from Anthropic's pricing table text.
8. **The Claude Code alias table (`sonnet`/`opus`/`haiku`/`fable`) is not published anywhere as a
   literal "alias → id" table for *today*.** Anthropic's docs only describe alias *behavior*
   ("latest Sonnet model", etc.), not the current binding. What's below is inferred from two
   evidence sources: (a) this session's own system context ("You are powered by Sonnet 5,
   claude-sonnet-5" — direct, first-party evidence the `sonnet` alias is live-bound to
   `claude-sonnet-5`), and (b) local transcript call-volume, where `claude-opus-5` dominates
   `claude-opus-5-5` 31545:193 and `claude-fable-5-1` dominates `claude-fable-5` 2569:483 — strong
   behavioral evidence `opus`→`claude-opus-5` and `fable`→`claude-fable-5-1` today, notably
   *contradicting* the assumption that "opus" already points at the newer 5.5 (the `claude-api`
   skill explicitly documents Opus 5.5 as "launching — use only when named," consistent with `opus`
   still resolving to plain Opus 5). This is inference, not a citation, and an org-level model
   override would invalidate it silently.
9. **`sonnet-4.5` and `gpt-5.4-mini` in the transcript inventory are unresolved.** `sonnet-4.5` uses
   dot notation and no `claude-` prefix, which matches no observed Anthropic id convention (all
   confirmed Anthropic ids are dash-separated, e.g. `claude-sonnet-4-6`) — likely a bare Cursor
   model string missing its `cursor/` prefix, but not confirmed. `gpt-5.4-mini` (1 occurrence) has no
   primary source in the OpenAI pages fetched (which only cover the current + immediately-legacy
   tiers). `<synthetic>` (770 occurrences) is not a model call at all — it's Claude Code's internal
   marker for injected/synthetic turns (e.g. compaction) and carries no canonical id.
10. **Transcript `message.model` strings are themselves first-party evidence** for Anthropic route
    ids — they are the literal string the Anthropic API returned in that response. Every bare
    `claude-*` string in the inventory below is treated as self-confirming for id purposes; Anthropic
    pricing-page corroboration is cited separately for the *rate*.

11. **`names` omits identity mappings.** Several Cursor/ocx-cursor names are byte-identical to the
    canonical id (e.g. Cursor's own `claude-sonnet-5`, `composer-2.5`, `gpt-5.6-sol`). Per plan step
    2's validation rule ("no alias or route name appears as a canonical id"), those are left out of
    `names` entirely — a route resolver should try the canonical-id table directly before consulting
    `names`. Only genuine renames (Cursor's `gemini-3.1-pro` → Google's real `gemini-3.1-pro-preview`)
    and the two resolvable ocx-cursor prefixed names appear below.

## Sources consulted

- `https://docs.claude.com/en/docs/about-claude/pricing` — full Anthropic rate table (all models).
- `https://docs.claude.com/en/docs/about-claude/models/overview` — current 4-model lineup, Claude API
  alias table (`claude-haiku-4-5` → `claude-haiku-4-5-20251001`).
- `https://docs.claude.com/en/docs/claude-code/model-config` — alias *behavior* descriptions (no
  literal current bindings).
- `https://platform.openai.com/docs/pricing`, `https://platform.openai.com/docs/models` — GPT-6
  flagship lineup, legacy `gpt-5.6-sol`/`gpt-5.6-cyber` table, Daybreak aliases.
- `https://ai.google.dev/gemini-api/docs/pricing` — Gemini 3.1 Pro Preview and 3.8 Flash pricing.
- `https://docs.x.ai/docs/models`, `https://docs.x.ai/docs/release-notes` — Grok 4.7 confirmed live;
  Grok 4.6 release note (no live model page).
- `https://platform.moonshot.ai/docs/models`, `.../docs/pricing/list` — Kimi model list (ids
  confirmed), pricing page renders client-side (no static numbers).
- `https://cursor.com/docs/models-and-pricing` — current Cursor lineup and rates.
- Local: `~/.claude/agents/ocx-*.md` (ocx-cursor route names), `~/.claude/projects/**/*.jsonl`
  (transcript inventory, via a script — files were never read into context, only aggregate counts).
- This session's own system context (`sonnet` → `claude-sonnet-5`, direct).

## Transcript inventory (counts across all local `~/.claude/projects/**/*.jsonl`)

| raw `message.model` | count | route | canonical id |
|---|---|---|---|
| `claude-opus-5` | 31545 | anthropic | `claude-opus-5` |
| `claude-haiku-4-5-20251001` | 28077 | anthropic | `claude-haiku-4-5-20251001` |
| `claude-sonnet-5` | 7665 | anthropic | `claude-sonnet-5` |
| `claude-fable-5-1` | 2569 | anthropic | `claude-fable-5-1` |
| `claude-opus-4-7` | 1633 | anthropic | `claude-opus-4-7` |
| `cursor/gpt-5.6-terra` | 1143 | cursor | **unresolved** |
| `<synthetic>` | 770 | n/a | **unresolved** (not a model) |
| `cursor/claude-opus-5` | 517 | cursor | `claude-opus-5` |
| `claude-fable-5` | 483 | anthropic | `claude-fable-5` |
| `cursor/claude-sonnet-5` | 264 | cursor | `claude-sonnet-5` |
| `cursor/gpt-5.6-luna` | 249 | cursor | **unresolved** |
| `cursor/claude-fable-5-1` | 234 | cursor | `claude-fable-5-1` |
| `claude-opus-5-5` | 193 | anthropic | `claude-opus-5-5` |
| `sonnet-4.5` | 15 | **unresolved route** | **unresolved** |
| `claude-sonnet-4-6` | 11 | anthropic | `claude-sonnet-4-6` |
| `claude-haiku-4-5` | 4 | anthropic (alias) | `claude-haiku-4-5-20251001` |
| `cursor/gemini-3.8-flash` | 2 | cursor | `gemini-3.8-flash` |
| `claude-ocx-cursor--claude-opus-5` | 2 | ocx-cursor | `claude-opus-5` |
| `cursor/gpt-5.4-mini` | 1 | cursor | **unresolved** |
| `composer-2.5-fast` | 1 | cursor | `composer-2.5-fast` |

Every row is accounted for above as mapped or unresolved (acceptance criterion 1).

## JSON registry block

```json
{
  "names": [
    { "route": "cursor", "name": "gemini-3.1-pro", "model": "gemini-3.1-pro-preview" },
    { "route": "ocx-cursor", "name": "claude-ocx-cursor--claude-opus-5", "model": "claude-opus-5" },
    { "route": "ocx-cursor", "name": "claude-ocx-cursor--claude-sonnet-5", "model": "claude-sonnet-5" }
  ],
  "aliases": {
    "claude-code": {
      "retrieved_at": "2026-09-23",
      "confidence": "inferred, not published — see caveat 8",
      "map": {
        "sonnet": "claude-sonnet-5",
        "opus": "claude-opus-5",
        "haiku": "claude-haiku-4-5-20251001",
        "fable": "claude-fable-5-1"
      }
    },
    "anthropic-api": {
      "retrieved_at": "2026-09-23",
      "source_url": "https://docs.claude.com/en/docs/about-claude/models/overview",
      "map": {
        "claude-haiku-4-5": "claude-haiku-4-5-20251001"
      }
    }
  },
  "rates": [
    { "route": "anthropic", "model": "claude-fable-5-1", "input": 10.0, "cache_write_5m": 12.5, "cache_write_1h": 20.0, "cache_read": 0.25, "output": 50.0, "source_url": "https://docs.claude.com/en/docs/about-claude/pricing", "retrieved_at": "2026-09-23" },
    { "route": "anthropic", "model": "claude-opus-5-5", "input": 4.0, "cache_write_5m": 5.0, "cache_write_1h": 8.0, "cache_read": 0.20, "output": 20.0, "source_url": "https://docs.claude.com/en/docs/about-claude/pricing", "retrieved_at": "2026-09-23" },
    { "route": "anthropic", "model": "claude-sonnet-5", "input": 2.0, "cache_write_5m": 2.5, "cache_write_1h": 4.0, "cache_read": 0.20, "output": 10.0, "source_url": "https://docs.claude.com/en/docs/about-claude/pricing", "retrieved_at": "2026-09-23" },
    { "route": "anthropic", "model": "claude-haiku-4-5-20251001", "input": 1.0, "cache_write_5m": 1.25, "cache_write_1h": 2.0, "cache_read": 0.10, "output": 5.0, "source_url": "https://docs.claude.com/en/docs/about-claude/pricing", "retrieved_at": "2026-09-23" },
    { "route": "anthropic", "model": "claude-fable-5", "input": 10.0, "cache_write_5m": 12.5, "cache_write_1h": 20.0, "cache_read": 1.00, "output": 50.0, "source_url": "https://docs.claude.com/en/docs/about-claude/pricing", "retrieved_at": "2026-09-23" },
    { "route": "anthropic", "model": "claude-opus-5", "input": 5.0, "cache_write_5m": 6.25, "cache_write_1h": 10.0, "cache_read": 0.50, "output": 25.0, "source_url": "https://docs.claude.com/en/docs/about-claude/pricing", "retrieved_at": "2026-09-23" },
    { "route": "anthropic", "model": "claude-opus-4-8", "input": 5.0, "cache_write_5m": 6.25, "cache_write_1h": 10.0, "cache_read": 0.50, "output": 25.0, "source_url": "https://docs.claude.com/en/docs/about-claude/pricing", "retrieved_at": "2026-09-23" },
    { "route": "anthropic", "model": "claude-opus-4-7", "input": 5.0, "cache_write_5m": 6.25, "cache_write_1h": 10.0, "cache_read": 0.50, "output": 25.0, "source_url": "https://docs.claude.com/en/docs/about-claude/pricing", "retrieved_at": "2026-09-23" },
    { "route": "anthropic", "model": "claude-opus-4-6", "input": 5.0, "cache_write_5m": 6.25, "cache_write_1h": 10.0, "cache_read": 0.50, "output": 25.0, "source_url": "https://docs.claude.com/en/docs/about-claude/pricing", "retrieved_at": "2026-09-23" },
    { "route": "anthropic", "model": "claude-sonnet-4-6", "input": 3.0, "cache_write_5m": 3.75, "cache_write_1h": 6.0, "cache_read": 0.30, "output": 15.0, "source_url": "https://docs.claude.com/en/docs/about-claude/pricing", "retrieved_at": "2026-09-23" },

    { "route": "cursor", "model": "claude-fable-5-1", "input": 10.0, "cache_write": 12.5, "cache_read": 0.25, "output": 50.0, "note": "Cursor shows one untiered cache-write price, not Anthropic's 5m/1h split", "source_url": "https://cursor.com/docs/models-and-pricing", "retrieved_at": "2026-09-23" },
    { "route": "cursor", "model": "claude-opus-5-5", "input": 4.0, "cache_write": 5.0, "cache_read": 0.20, "output": 20.0, "source_url": "https://cursor.com/docs/models-and-pricing", "retrieved_at": "2026-09-23" },
    { "route": "cursor", "model": "claude-sonnet-5", "input": 2.0, "cache_write": 2.5, "cache_read": 0.20, "output": 10.0, "source_url": "https://cursor.com/docs/models-and-pricing", "retrieved_at": "2026-09-23" },
    { "route": "cursor", "model": "gemini-3.1-pro-preview", "input": 2.0, "cache_write": null, "cache_read": 0.20, "output": 12.0, "note": "Cursor's flat number matches Google's <=200k-token tier only", "source_url": "https://cursor.com/docs/models-and-pricing", "retrieved_at": "2026-09-23" },
    { "route": "cursor", "model": "gemini-3.8-flash", "input": 0.75, "cache_write": null, "cache_read": 0.075, "output": 3.5, "source_url": "https://cursor.com/docs/models-and-pricing", "retrieved_at": "2026-09-23" },
    { "route": "cursor", "model": "gpt-5.6-sol", "input": 4.0, "cache_write": 5.0, "cache_read": 0.40, "output": 20.0, "source_url": "https://cursor.com/docs/models-and-pricing", "retrieved_at": "2026-09-23" },
    { "route": "cursor", "model": "composer-2.5", "input": 0.5, "cache_write": null, "cache_read": 0.20, "output": 2.5, "source_url": "https://cursor.com/docs/models-and-pricing", "retrieved_at": "2026-09-23" },
    { "route": "cursor", "model": "composer-2.5-fast", "input": 3.0, "cache_write": null, "cache_read": 0.50, "output": 15.0, "source_url": "https://cursor.com/docs/models-and-pricing", "retrieved_at": "2026-09-23" },

    { "route": "openai", "model": "gpt-5.6-sol", "input": 4.0, "cache_write": 5.0, "cache_read": 0.40, "output": 20.0, "source_url": "https://platform.openai.com/docs/pricing", "retrieved_at": "2026-09-23" }
  ],
  "models": [
    { "id": "claude-fable-5-1", "provider": "anthropic", "source_url": "https://docs.claude.com/en/docs/about-claude/pricing" },
    { "id": "claude-fable-5", "provider": "anthropic", "source_url": "https://docs.claude.com/en/docs/about-claude/pricing" },
    { "id": "claude-opus-5-5", "provider": "anthropic", "source_url": "https://docs.claude.com/en/docs/about-claude/models/overview" },
    { "id": "claude-opus-5", "provider": "anthropic", "source_url": "https://docs.claude.com/en/docs/about-claude/pricing" },
    { "id": "claude-opus-4-8", "provider": "anthropic", "source_url": "https://docs.claude.com/en/docs/about-claude/pricing" },
    { "id": "claude-opus-4-7", "provider": "anthropic", "source_url": "https://docs.claude.com/en/docs/about-claude/pricing" },
    { "id": "claude-opus-4-6", "provider": "anthropic", "source_url": "https://docs.claude.com/en/docs/about-claude/pricing" },
    { "id": "claude-sonnet-5", "provider": "anthropic", "source_url": "https://docs.claude.com/en/docs/about-claude/models/overview" },
    { "id": "claude-sonnet-4-6", "provider": "anthropic", "source_url": "https://docs.claude.com/en/docs/about-claude/pricing" },
    { "id": "claude-haiku-4-5-20251001", "provider": "anthropic", "source_url": "https://docs.claude.com/en/docs/about-claude/models/overview" },
    { "id": "gemini-3.8-flash", "provider": "google", "source_url": "https://ai.google.dev/gemini-api/docs/pricing" },
    { "id": "gemini-3.1-pro-preview", "provider": "google", "source_url": "https://ai.google.dev/gemini-api/docs/pricing" },
    { "id": "gpt-6-astra", "provider": "openai", "source_url": "https://platform.openai.com/docs/models" },
    { "id": "gpt-6-sol", "provider": "openai", "source_url": "https://platform.openai.com/docs/models" },
    { "id": "gpt-6-luna", "provider": "openai", "source_url": "https://platform.openai.com/docs/models" },
    { "id": "gpt-5.6-sol", "provider": "openai", "source_url": "https://platform.openai.com/docs/pricing" },
    { "id": "grok-4.7", "provider": "xai", "source_url": "https://docs.x.ai/docs/models" },
    { "id": "kimi-k3", "provider": "moonshot", "source_url": "https://platform.moonshot.ai/docs/models" },
    { "id": "kimi-k2.7-code", "provider": "moonshot", "source_url": "https://platform.moonshot.ai/docs/models" },
    { "id": "composer-2.5", "provider": "cursor", "source_url": "https://cursor.com/docs/models-and-pricing" },
    { "id": "composer-2.5-fast", "provider": "cursor", "source_url": "https://cursor.com/docs/models-and-pricing" }
  ],
  "unresolved": [
    { "id": "gpt-5.6-luna", "appears_in": ["model-options.json", "spend.py DEFAULT_RATES", "transcript: cursor/gpt-5.6-luna (249)", "~/.claude/agents/ocx-gpt-5-6-luna.md"], "reason": "No 'luna' or '5.6-luna' string anywhere on OpenAI's docs/models or docs/pricing pages (both fetched in full). Cursor names it 'GPT-5.6 Luna' but that is Cursor's own display name, not traceable to an OpenAI id." },
    { "id": "gpt-5.6-terra", "appears_in": ["model-options.json", "spend.py DEFAULT_RATES", "transcript: cursor/gpt-5.6-terra (1143)", "~/.claude/agents/ocx-gpt-5-6-terra.md"], "reason": "No 'terra' string anywhere on OpenAI's docs/models or docs/pricing pages. Highest-volume unresolved transcript entry (1143 calls) — worth prioritizing if a source turns up." },
    { "id": "grok-4.6", "appears_in": ["model-options.json", "spend.py DEFAULT_RATES"], "reason": "xAI's live model pages now redirect to the current flagship (grok-4.7); no page confirms the literal id string today. Release notes (2026-08-12) confirm the model and its price ($2/$0.5/$6 <=200k, $4/$1/$12 >200k) but never spell out the API string. Cursor's own current price for 'Grok 4.6' matches the release-note number exactly ($2/-/$0.5/$6), so the model itself is real and priced consistently — only the exact id string is unconfirmed." },
    { "id": "sonnet-4.5", "appears_in": ["transcript (15 calls)"], "reason": "Dotted, unprefixed form matches no confirmed Anthropic id convention (all confirmed Anthropic ids are dash-separated: claude-sonnet-4-6). Likely a bare Cursor model string missing its 'cursor/' prefix; not confirmed either way." },
    { "id": "gpt-5.4-mini", "appears_in": ["transcript: cursor/gpt-5.4-mini (1 call)"], "reason": "Not present on OpenAI's current docs/pricing or docs/models pages (which cover the current + immediately-legacy tiers only); likely a fully retired id with no page left to confirm it." },
    { "id": "<synthetic>", "appears_in": ["transcript (770 occurrences)"], "reason": "Not a model call — Claude Code's internal marker for injected/synthetic turns (e.g. compaction). No canonical id applies." },
    { "id": "claude-ocx-cursor--gpt-5.6-luna", "appears_in": ["~/.claude/agents/ocx-gpt-5-6-luna.md"], "reason": "ocx-cursor route name is well-defined from the local agent file, but its underlying model (gpt-5.6-luna) is itself unresolved — see above." },
    { "id": "claude-ocx-cursor--gpt-5.6-terra", "appears_in": ["~/.claude/agents/ocx-gpt-5-6-terra.md"], "reason": "Same as above, for gpt-5.6-terra." },
    { "id": "gemini-3.1-pro", "appears_in": ["model-options.json"], "reason": "No primary source for the bare string 'gemini-3.1-pro'. Google's confirmed id is gemini-3.1-pro-preview (see models array) — very likely the same model under a corrected id, but the plan forbids deriving ids by reformatting, so this is flagged rather than silently substituted; L2 should treat gemini-3.1-pro-preview as the intended replacement pending a human ruling." },
    { "id": "kimi-k3 (rate)", "appears_in": ["model-options.json"], "reason": "Id is confirmed (see models array) but no rate could be sourced — Moonshot's pricing pages render numbers client-side, and Cursor no longer lists Kimi models at all." },
    { "id": "kimi-k2.7-code (rate)", "appears_in": ["model-options.json"], "reason": "Same as kimi-k3: id confirmed, no sourceable rate." },
    { "id": "claude-4.6-sonnet (cursor rate)", "appears_in": ["model-options.json"], "reason": "Canonical id claude-sonnet-4-6 is confirmed via Anthropic's own pricing page (see models/rates), but Cursor's current pricing page no longer lists this model under any name — zero hits case-insensitively across the full fetched page including embedded scripts. No current Cursor rate exists to source." },
    { "id": "claude-opus-4.8 / claude-opus-5 (cursor rate)", "appears_in": ["model-options.json"], "reason": "Canonical ids are confirmed Anthropic ids, but neither appears on Cursor's current pricing page (superseded there by Claude Opus 5.5) — no current Cursor rate to source, though claude-opus-5 remains observable in transcripts under the anthropic and cursor routes." }
  ]
}
```
