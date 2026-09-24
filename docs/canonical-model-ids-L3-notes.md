# Canonical model ids — L3 notes (plan steps 5, 7, 8)

Brief: `L3-harness.md`. Log: `docs/canonical-model-ids-progress.md`. Built on L2's registry
(`pricing.Registry`, `resolve_model`, `resolve_route_name`) and L1's research. Nothing committed.

## Shape

- `pricing.detect_harness(explicit)` returns `{"harness", "detected_by"}`. Order: `--harness` flag,
  `CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`, `CODEX_HOME`, else `cursor`. It replaces
  `default_harness()` outright — no call site still hardcodes `cursor`. `eligibility()`,
  `cmd_eligible_models` and `spend models` all surface `harness_source` next to `harness`, which is
  new in their JSON output (a visible field addition, not a behavior change under any given
  harness).
- `pricing.read_agent_definitions(agents_dir)` parses `~/.claude/agents/*.md` frontmatter with a
  hand-rolled parser (no YAML dependency, matching the plugin's stdlib-only convention): `name`
  (falling back to the filename), `model`, and a `<!-- generated-by: X -->` marker. An agent's
  `model:` value is a route name or bare canonical id — never an alias — so it resolves through
  `Registry.resolve_route_name`, not `resolve_model`.
- `pricing.claude_code_catalog(registry, agents_dir)` derives the Claude Code catalog rather than
  loading one from disk: every canonical id is reachable bare on its native (unprefixed) route —
  `anthropic` today — with no extra condition; a prefixed route (`ocx-cursor`) is restricted to
  models with a matching agent definition. This is the restriction L2 flagged as deferred ("Step 5
  should restrict ocx-cursor to models that have an ocx-* agent definition. I did not, because that
  data belongs to the catalog lane").
- `pricing.spawn_field(model, family, harness, registry, agent_index)` returns
  `{"spawn": {...}, "via": [...]}`, per ruling (a): `spawn` must stay on the route the
  recommendation was priced on (`registry.priced_route`). Within that route, in order: an agent
  named for the canonical id; any other agent definition already on that route (needed for a model
  whose priced route *is* a prefixed one, e.g. `ocx-cursor` billing directly — the plan's literal
  "id-named agent, then alias" pair is silent on this case, since it assumes the id-named-agent and
  priced-route cases coincide, which they do for every anthropic-native model but not for one priced
  on a bridge route; this on-route fallback is my inference, flagged below); a harness alias, only
  when the table still maps it to this exact id. A stale alias — the table's `opus` pointing at last
  generation's Opus while this id is the new one — is refused: `{"kind": "error", "route":
  "anthropic", "error": "alias 'opus' drifted to 'claude-opus-5', not 'claude-opus-5-5'"}`. If the
  priced route has no agent and no undrifted alias, `spawn` itself is `{"kind": "error", ...}` while
  `via` still lists whatever's true. `via` holds every agent definition on a *different* route from
  the priced one — an `ocx-*` bridge for an anthropic-priced model, most concretely — each entry
  carrying its own route and rate row (`{"route", "value", "rates"}`), never as `spawn`, because a
  different route is a different bill for the same model.
- `spend models` uses the derived catalog when the resolved harness is `claude-code` **and no
  `--catalog` was given** (an explicit catalog always wins, so existing Codex-catalog callers are
  unaffected regardless of which harness the environment happens to detect); it then adds a
  `spawn` field to every selected row. Under any other harness, or with an explicit `--catalog`,
  output is otherwise unchanged from before this work — verified with a fixture against a
  `--harness codex` run.
- `spend agents --write` writes `<agents_dir>/<canonical-id>.md`, in the same three-line frontmatter
  shape opencodex's own `ocx-*` files use, plus its own `<!-- generated-by: context-economy -->`
  marker. Per ruling (b), its **default** scope is only the `provider: anthropic` rows some rung's
  `preferences` list currently recommends (`_preferred_model_ids`: the union of every
  `preferences[rung]` list — an archetype has no model list of its own, it just names a rung, so
  "recommended by a rung preference or archetype" reduces to this union). `--all` restores the
  original every-anthropic-option scope. It never overwrites a file whose existing marker names a
  different generator. It is a plain CLI command: no hook, no `install` wiring, `--agents-dir`
  required for any test.
- `find_transcript` now tries `find_transcript_by_session()` — a direct
  `<projects-dir>/*/​$CLAUDE_CODE_SESSION_ID.jsonl` glob — before the cwd-slug scan.
  `claude_projects_dir()` is overridable via `SPEND_CLAUDE_PROJECTS_DIR` / `ORCH_CLAUDE_PROJECTS_DIR`,
  the same convention every other path in the file follows.
- `cmd_rung` reads `subagent_type` from the Task/Agent payload and checks it against
  `read_agent_definitions()`; if the name resolves to a definition that has a `model:` field, the
  hook returns silently rather than warning that "model unset."

## Behaviour that changes in the field

1. **`spend models` and `pricing eligibility`/`eligible-models` no longer silently default to
   Cursor.** Under a real Claude Code session (`CLAUDECODE=1` or `CLAUDE_CODE_SESSION_ID` set,
   which is the normal case) they now resolve `claude-code` automatically. L2's documented
   workaround ("pass `--harness claude-code` until L3 lands") is no longer necessary, though it
   still works.
2. **`spend models` gains a `harness` and `harness_source` field, and, under Claude Code, a
   `spawn` field per row.** This is new JSON shape; nothing that previously read only `model`,
   `catalog_slug`, `family`, `rung`, `effort`, `use` is affected, but a consumer doing strict key-set
   validation on this output would need updating.
3. **`cursor/GPT-5.6-sol` (or any re-cased route-prefixed name) now prices**, where it was
   `unpriced` after L2. One existing `test_spend.py` assertion pinned the old behavior and is now
   pinned to the new one instead.
4. **`spend cost` and `spend compaction` work from any subdirectory of a repo**, not just the one
   the session started in. This was a real, reproduced gap: `project_dir_for()` from a subdirectory
   of this very repo returns `None` today, and `find_transcript` used to have no other way to find
   the transcript.
5. **A subagent spawned via a `subagent_type` that pins its own model no longer trips the "model
   unset" rung warning.** Previously every `Task`/`Agent` call with no literal `model` field
   warned, including ones whose `subagent_type` already fixed the model via an agent definition —
   which describes every `ocx-*` worker in this environment right now.
6. **A new destructive-adjacent command exists: `spend agents --write`.** It is opt-in and explicit
   (no hook path reaches it), but it is the first command in this plugin that writes into
   `~/.claude/agents` by default. It was exercised only against temp directories in this work; the
   real directory's four `ocx-*.md` files are untouched (confirmed by mtime before and after).

## Guessed or inferred (defend or concede)

- **The alias-to-family mapping for spawn tier 3 is my inference, not written anywhere in the
  registry.** I derive the alias name to try from `model["family"]` by stripping a leading
  `"claude-"` (`"claude-opus"` → `"opus"`), rather than the registry declaring
  `family -> alias name` directly. This matches the shipped alias table's four keys exactly
  (`sonnet`, `opus`, `haiku`, `fable`) and the four `claude-*` families in `model-options.json`, but
  it is a naming convention I read off the data rather than a rule the schema enforces. If a future
  family doesn't fit `claude-<word>` → `<word>`, tier 3 silently stops applying for it (falls to
  `"no agent definition or alias spawns"`), which is fail-closed, not a wrong answer — but it is a
  convention, not a contract. **Defend**: it is exactly what let me observe the live drift
  (`claude-opus-5-5` vs. the table's `opus` → `claude-opus-5`) without hand-wiring anything
  model-specific.
- **Resolved by ruling (a)** (`docs/canonical-model-ids-progress.md` Log): the original tier order
  let a routed `ocx-*` agent outrank a clean alias even for a model priced on `anthropic` —
  `claude-sonnet-5` spawned through the `ocx-claude-sonnet-5` Cursor bridge instead of the undrifted
  `sonnet` alias, silently switching the bill's route out from under the recommendation's own
  price. Fixed by anchoring `spawn` to `registry.priced_route(model, harness)` and demoting any
  agent on a different route to `via`. See Falsification below for the red→green transition.
- **Still my inference, not the ruling's literal text**: within the priced route, I added a third
  tier — *any* on-route agent definition, not just one named for the canonical id — before falling
  to alias. This only matters for a model whose priced route is itself a prefixed one (e.g. an
  `ocx-cursor`-priced, non-Anthropic model): without it, such a model's only agent definition (never
  id-named, since `spend agents --write` only ever writes Claude ids) would have no way to become
  `spawn` even though it is sitting right on the priced route. The plan's literal "id-named agent,
  then alias" pair was written for the anthropic-native case, where those two happen to coincide,
  and doesn't speak to this case. **Defend**: it is a strict extension, not a contradiction — it
  never promotes an off-route agent, and every existing test (including the ruling-(a) sonnet case)
  passes on the literal ordering alone; it only adds coverage the literal text left silent.
- **Resolved by ruling (b)**: `agents --write` now defaults to the union of every rung's
  `preferences` list (an archetype has no model list of its own, so "recommended by a rung
  preference or archetype" reduces to that union), and `--all` restores the original
  every-`provider: anthropic` scope.

## Needs a human ruling

1. **Whether `harness`/`harness_source` belong in `spend models`' text-format output too** — they
   are JSON-only today; the text format still prints just `rung / effort` (now also `[via: ...]`
   when a `via` alternative exists).
2. **The on-route "any agent, not just id-named" tier** noted above under "Guessed or inferred" —
   confirm it's the intended reading of ruling (a) rather than a gap that should instead route such
   a model straight to a spawn refusal.

## Falsification

- Reverted the case-fold line in `Registry._route_candidates` and re-ran `test_spend.py`: the
  new "case is folded to the one thing it could mean" check went red (`None != <rate dict>`);
  re-applied the fold and it went green.
- Ran `spend models --archetype implementer` under `CLAUDECODE=1` against the real, unmodified
  `~/.claude/agents` (four `ocx-*.md` files, no case-1 files) and watched the alias-drift guard
  fire for real: `claude-sonnet-4-6`'s spawn field came back
  `{"kind": "error", "error": "alias 'sonnet' drifted to 'claude-sonnet-5', not
  'claude-sonnet-4-6'"}` — the drift the table itself documents ("`opus` → `claude-opus-5`, not
  `-5-5`") reproduced for the sonnet family too. This is now pinned as a permanent regression test
  in `test_pricing.py` against the shipped registry, so it stays red if the alias table is ever
  updated to match without the code changing.
- Confirmed the subdirectory transcript-lookup bug is real, not hypothetical: called
  `project_dir_for('.')` from `docs/` in this actual repo and got `None` back before relying on the
  session-id path.
- Confirmed `spend agents --write` never touched the real `~/.claude/agents`: compared file
  mtimes (`2026-09-23 11:22:22`, before any of this work started) before and after the full test
  run and manual verification session; unchanged.
- **Ruling (a), red then green.** Wrote the new `test_pricing.py` checks asserting the corrected
  shape first (`spawn` = the `sonnet` alias on the `anthropic` route; `ocx-claude-sonnet-5` demoted
  to `via`), then temporarily reverted just `spawn_field` to its pre-ruling body (flat return, no
  route restriction) and re-ran the suite: `spend.py`'s `cmd_models` — already rewritten to consume
  the new `{"spawn", "via"}` shape — raised `KeyError: 'spawn'` against the old flat return, and the
  CLI-level "derived catalog" and "haiku spawns via its own agent definition" checks failed/crashed
  outright. Restored the fixed `spawn_field` and reran: all 3 previously-broken checks and the new
  ruling-(a) checks passed. This demonstrates both that the old tier order was wrong (it would have
  handed a Cursor-billed spawn for an Anthropic-priced recommendation) and that the fix is what
  makes the difference, not test-authoring error.
- **Ruling (b), red then green.** Added `agents --write default scope is the 3
  currently-preferred Claude models` to `test_spend.py`, then temporarily reverted `cmd_agents` to
  its pre-ruling body (no `preferred` filter): the check failed, reporting all 7 anthropic-provider
  options (`got` included `claude-sonnet-4-6`, `claude-opus-4-8`, `claude-opus-5`,
  `claude-fable-5-1`, none of which any rung currently prefers). Restored the fixed `cmd_agents` and
  reran: the check passed with exactly the 3 preferred ids, and the new `--all` check independently
  confirmed all 7 are still reachable on request.

## Verification

- `python3 plugins/context-economy/scripts/test_pricing.py` → all pass (74 checks), including the
  original harness/catalog/case-fold suite plus the ruling-(a) rework: `spawn_field` route-anchored
  to `priced_route`, the sonnet alias-vs-ocx-cursor-bridge case, the drifted-alias refusal, and the
  no-spawn-path-but-via-still-listed case.
- `python3 plugins/context-economy/scripts/test_spend.py` → all pass, including the ruling-(b)
  rework: `agents --write` default scope (3 preferred models), `--all` (7 anthropic options), the
  opencodex-generated-file skip, the session-id transcript lookup, and the rung hook's three cases.
- `claude plugin validate . --strict` passes. `plugin.json` 0.3.0 → 0.4.0 → 0.4.1 (this ruling
  round).
- Did not touch `plugins/orchestration` (L5's lane). Did not commit.
