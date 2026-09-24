# Canonical model ids — L4 independent verification

Verifier: L4 lane (e17, paseo 40037dfa, claude-sonnet-5). Scope: the uncommitted tree against
`docs/canonical-model-ids-plan.md` and the ruling Log in `docs/canonical-model-ids-progress.md`,
including L5's orch rung change. `docs/canonical-model-ids-L2-notes.md` and `-L3-notes.md` were
read as claims to test, not evidence.

## Verdict: pass with findings

One finding, and it is not a defect in this program: an unrelated, undocumented change is sitting
in the same working tree (see Findings). Every guard this program built stayed correct under
direct sabotage; every test suite and validator passes; the sampled pricing data matches primary
sources; live behavior under `CLAUDECODE=1` matches every "Done when" I could exercise.

## 1. Test suites and validation (re-run by me, not trusted from notes)

```
python3 plugins/context-economy/scripts/test_spend.py         -> all pass
python3 plugins/context-economy/scripts/test_pricing.py       -> all pass
python3 plugins/orchestration/skills/orchestrating/scripts/test_orch_rungs.py -> all pass (23/23)
claude plugin validate . --strict                              -> Validation passed
python3 plugins/context-economy/scripts/pricing.py validate    -> valid: true; only warnings are
  "missing cache_write" for 4 Cursor models with no cache pricing published (composer-2.5,
  composer-2.5-fast, gemini-3.1-pro-preview, gemini-3.8-flash) — a documented gap, not an error.
```

## 2. Sabotage — central guards, in a scratch copy (`/tmp/l4verify-scratch`, never the tree)

All five went red under sabotage and green again on restore. None of the five guards stays green
under direct sabotage.

| Guard | Sabotage | Result |
|---|---|---|
| unpriced-not-guessed | `RateTable.lookup`: a missing (route, id) rate now synthesizes an all-zero rate instead of returning `rate=None` | `test_spend.py`: "a model with no route rate is unpriced, with a reason" → **FAIL** (got a synthesized rate, wanted `unpriced`) |
| alias-drift refusal | `spawn_field`: alias branch always returns `{"kind": "alias", ...}` regardless of whether the alias table's target matches the model | `test_pricing.py`: "a drifted alias is refused, not silently spawned" → **FAIL** (`got 'alias', want 'error'`); "the refusal names the drift" also fails |
| no-alias-in-output | `eligibility()`: `result["target_model"]`/`["source_model"]` set from the raw input string instead of the resolved canonical id | `test_pricing.py`: "eligibility reports the canonical id, not the input name" → **FAIL**; "pricing eligibility emits no alias or route name" → **FAIL** (leaked `haiku`, `opus`); "haiku alias translates under claude-code" → **FAIL** |
| spawn stays on priced route (ruling a) | `spawn_field`: `on_route = list(entries)` (every route), `off_route = []` — the priced-route restriction is gone | `test_pricing.py`: "ruling (a): the ocx-cursor bridge is demoted to a `via` alternative" → **FAIL** (got `[]`, wanted the ocx-cursor entry — the bridge was pulled into on-route eligibility instead of staying a `via`) |
| orch `default`-rung rejection | `reject_default_rung`: body replaced with `if False:` (never raises) | `test_orch_rungs.py`: 4 failures — "brief/`--model`/`--to`/`update --model` default names it not a rung" all → **FAIL** (message text absent). Note: the "rejected (nonzero exit)" checks stayed green even under this sabotage — rejection still happens, but for the wrong reason (a downstream crash on an unrecognized rung index, not the named refusal), so a shallower test that only checked exit code would have missed this sabotage entirely. The message-content checks are load-bearing here, not the exit-code ones. |

## 3. Pricing data spot-check (delegated to a research subagent, WebFetch against primary sources)

5 rows sampled, live-checked against `docs.claude.com`/`platform.claude.com` (Anthropic) and
`cursor.com/docs/models-and-pricing` (Cursor):

| Route | Model | Stored | Live | Result |
|---|---|---|---|---|
| anthropic | claude-opus-5-5 | 4/5/8/0.20/20 | 4/5/8/0.20/20 | MATCH |
| anthropic | claude-haiku-4-5-20251001 | 1/1.25/2/0.10/5 | 1/1.25/2/0.10/5 | MATCH |
| anthropic | claude-sonnet-4-6 | 3/3.75/6/0.30/15 | 3/3.75/6/0.30/15 | MATCH |
| cursor | gemini-3.1-pro-preview | 2/-/0.20/12 | 2/-/0.20/12 | MATCH |
| cursor | gpt-5.6-luna | 0.20/0.25/0.02/1.20 | 0.20/0.25/0.02/1.20 | MATCH |

No stored `rates[].model` value is an alias or route slug; the confined aliases (`sonnet`, `opus`,
`haiku`, `fable`) and Cursor display names (`claude-4.6-sonnet`, `claude-opus-4.8`,
`gemini-3.1-pro`) only ever appear in `aliases`/`names`, never as a canonical `model` field.

Not independently re-verified beyond the plan's own scope: whether `claude-opus-5` and
`claude-sonnet-4-6` are correctly *distinct*, currently-shipping Anthropic models rather than stale
duplicates of `claude-opus-5-5`/`claude-sonnet-5` — `docs/canonical-model-ids-research.md` sources
each separately with its own URL and I did not re-fetch those two.

## 4. Live behavior, `CLAUDECODE=1`, in this repo

- `spend models --archetype implementer`: prints canonical ids with `[spawn: ...]`/`[via: ...]`.
  `gpt-5.6-terra` spawns via `ocx-gpt-5-6-terra`; `claude-sonnet-5` spawns via the `sonnet` alias
  with `ocx-claude-sonnet-5` demoted to `via`; `claude-sonnet-4-6` correctly shows the alias-drift
  refusal (`alias 'sonnet' drifted to 'claude-sonnet-5', not 'claude-sonnet-4-6'`) rather than
  silently spawning the wrong model or being hidden.
- `spend cost` from `docs/` (a subdirectory): finds this session's transcript by id, prices it,
  no crash.
- `pricing eligible-models --rung minimal --source-model claude-opus-5-5`: `claude-haiku-4-5-20251001`
  gets a **computed verdict** (`target cache_write must be below $0.40/M`, `source cache_read must
  be at or above $0.25/M`, `cache-only estimate is not positive`) — rejected on the numbers, not on
  a missing price. Matches step 6's "Done when" exactly.
- `orch cost` and `orch roster`: both run clean against the live tracker (no crash on the existing
  L4 entry); `roster`'s root row and this lane's row render without a bare `default` anywhere.

## 5. Regressions and undocumented changes (delegated to an Explore subagent, independently spot-checked)

- No caller outside `plugins/context-economy/scripts/{spend.py,pricing.py}` and
  `plugins/orchestration/skills/orchestrating/scripts/orch.py` (and their own test files)
  references `DEFAULT_RATES`, `rate_for`, `pricing_key`, `load_rates`, `resolve_model`,
  `spawn_field`, `MODEL_RUNGS`, `default_harness`, or `detect_harness`. Every other hit is prose in
  docs, none of it executable.
- **Finding (informational, not a program defect):** the working tree carries an unrelated,
  undocumented change set: `plugins/orchestration/skills/orchestrating/references/substrates/paseo.md`
  gained a `SELF_RETUNE` note (confirmed via `git diff`, lines +8), and three new untracked files —
  `docs/self-switching-paseo-feasibility-research.md`, `docs/self-switching-paseo-lifecycle-research.md`,
  `docs/self-switching-pricing-research.md` — exist alongside `docs/self-switching-model-plan.md`.
  None of the four canonical-model-ids tracking docs (plan/progress/L2-notes/L3-notes) mention
  touching `paseo.md` or these three files; only `self-switching-model-plan.md` is claimed (L3 step
  8's reconciliation note). This is a different, apparently still-live research thread sharing the
  same uncommitted tree. It does not touch anything this program's tests or guards cover, but it
  means "the tree" is not solely this program's work — a commit or revert done in this program's
  name must not silently sweep it up or lose it.
- Everything else the four docs claim to have touched matches `git status`/`git diff --stat`
  exactly; nothing claimed is missing.

## Numbers that matter

- `test_spend.py`: all pass (spend-specific + pre-existing guard/rung/compaction checks).
- `test_pricing.py`: all pass, no count printed by the harness but every check line is `ok`.
- `test_orch_rungs.py`: 23/23.
- `claude plugin validate . --strict`: pass.
- `pricing validate`: valid, 4 non-fatal warnings (documented Cursor cache-write gaps).
- Sabotage: 5/5 guards go red on sabotage, green on restore.
- Pricing spot-check: 5/5 rows match; 0 alias/route-name-as-canonical-id violations.
- `plugin.json` versions: context-economy 0.4.1, orchestration 0.11.0 (both bumped from the
  pre-program versions the plan implied).
