# Spec addendum — `working-a-lane`, and turn-end checks that reach every lane

Status: **approved for build**. Extends `orch-adherence.md`. Target `orchestration` 0.19.0. Claude
Code only for the hooks. Rationale graduates into `docs/DESIGN.md` §9h at merge.

## Vocabulary — fixed here, used everywhere

- **Lane:** the tracked unit of work — an open entry with its brief, container, limits, checkpoint
  and current worker. It outlives any one worker.
- **Worker:** one agent instance currently working a lane. It can lose context and be replaced.
- **Dispatch:** one act of sending a lane to a worker. A lane may be dispatched more than once.

`orch_entry: none` spawns are not lanes and owe nothing below.

## Probed facts this design rests on (Claude Code 2.1.295, 2026-11-04)

1. A `SubagentStop` hook in the parent session fires when an `Agent` subagent finishes. Its
   payload carries `agent_id`, `agent_type`, `agent_transcript_path` (the subagent's own JSONL;
   its first line is the user message holding the spawn prompt, `orch_entry:` line included),
   `stop_hook_active` and `last_assistant_message`. `cwd` and `session_id` are the **parent's**.
2. `{"decision":"block","reason":…}` from `SubagentStop` continues the subagent with the reason.
3. A `/skill` line in a subagent's prompt is **not** executed. A subagent told to invoke the Skill
   tool **does** load a skill — but only one without `disable-model-invocation`.
4. A PreToolUse `updatedInput` is **not** applied to `Agent` spawns, so the orchestrator cannot
   inject the contract into a prompt; the prompt must carry the instruction itself.

## W1. The `working-a-lane` skill

New `plugins/orchestration/skills/working-a-lane/SKILL.md`, added to `plugin.json`'s ship list.

- **Model-invocable** (fact 3). Description, triggers only: *"Obligations of the agent currently
  working a lane for an orchestrator — the brief, the checkpoint, the report, the inbox. Use when
  your prompt has an `orch_entry:` line or names a brief to read."*
- **Content is moved, not copied:** the worker-facing parts of `assets/BRIEF.template.md`'s
  `## Report contract` and of `references/briefs.md` (the `progress_artifact` paragraph's
  checkpoint rules and four labels, how to report evidence so it can be consumed —
  `commit:<abs repo>@<sha>`), plus: drain your inbox; never write agent-track; a worker that finds
  its brief's premise wrong reports that rather than improvising. The orchestrator-facing halves
  stay where they are and point at the new skill. Target ≤1,000 words.
- **Frontmatter hooks:** `Stop` → `inbox drain --format hook` and `stop-check --format hook`, each
  **byte-identical** to the corresponding command in `orchestrating`'s frontmatter, so a session
  loading both registers one command, not two. Add `"$HOME/.agents/plugins/orchestration/skills/orchestrating"`
  to the resolution loop in **both** skills (CLAUDE.md: a skill script outside its own directory
  is found through the installed plugin root, never `..`). The `stop-check` shell prefilter stays.

## W2. `stop-check` handles `SubagentStop`

Add a `SubagentStop` hook to `orchestrating`'s frontmatter, same command as its Stop
`stop-check`. Branch on `hook_event_name`:

- **`SubagentStop`:** never the cwd-based role check (the cwd is the parent's). Read the first
  line of `agent_transcript_path` (cap 256 KB), find `orch_entry: <ref>`. No path, no label,
  `none`, or no open entry → silent. Otherwise this subagent is that entry's worker: **lane
  obligations only** — the three checkpoint codes for that entry, plus `lane-skill-not-loaded`
  when the transcript (cap 8 MB; skip the check above it) has no Skill tool call naming
  `working-a-lane`. Reason text for it: *"Load the working-a-lane skill with the Skill tool, then
  finish as its report contract says."*
- Loop guard keyed per subagent: `<program>/stop-blocks/agent-<agent_id>.json`, same fingerprint
  rule as today. `stop_hook_active` still suppresses.
- A `working-a-lane` loaded *inside* a subagent registers its Stop hooks there, where they fire
  as `SubagentStop` with the same payload — so the branch above also makes that path correct,
  and it can never block a subagent for the orchestrator's obligations.

## W3. A session can be a lane and an orchestrator at once

Replace the either/or role for `Stop`:

- **Lane obligations** if the session's worktree is exactly one running entry's (unchanged rule).
- **Orchestrator obligations** (`exception`, `harvested-unfinished`) **scoped to the trackers the
  session owns**: a lane session owns its entry's `child_tracker`, if any; a non-lane session
  owns `root`. Exception files are `<tracker>.<entry>.json`, so filter on `<tracker>`.

A sub-orchestrator therefore gets both; the root is no longer blocked by a grandchild's exception.

## W4. The spawn guard requires the load instruction

At `warn`/`strict` only, for a spawn labelled with an open entry (`Agent`/`Task` and
`mcp__paseo__create_agent`): the prompt must contain `working-a-lane` on a line that also says
`Skill` (case-insensitive). `strict` denies naming the line to add; `warn` allows with that text as
context. `orch open`'s spawn instructions print the line to paste:
`Before anything else, load the working-a-lane skill with the Skill tool.`

## W5. Vocabulary fixes

The fan-out advisory says "open lanes", not "open dispatches". `DESIGN.md` gains the three
definitions above. `references/substrates/paseo.md` notes that `claude-lane` matches by directory
(lane roots), which is looser than the tracker's entry-based definition.

## W6. Docs

`orchestrating` `SKILL.md`: Step 3 says every lane prompt carries the load line (≤40 words).
`references/adherence.md`: a coverage table — `Agent` subagent via `SubagentStop`, separate Claude
session via the skill's `Stop`, non-Claude lanes via CLI refusals only.

## W7. Tests — acceptance list

New `scripts/test_orch_lane.py` (copy helpers from `test_orch_adherence.py`). Fixtures write a
fake subagent transcript JSONL. Each check must fail on the pre-change code:

1. W2: strict + vacuous checkpoint + transcript with `orch_entry: eN` and a Skill call → block naming
   the labels; same with a good checkpoint → no output.
2. W2: no Skill call for `working-a-lane` → block with `lane-skill-not-loaded`; the 8 MB cap skips it.
3. W2: missing path, no label, `orch_entry: none`, unknown entry → no output.
4. W2: an outstanding orchestrator exception never appears in a `SubagentStop` reason.
5. W2 loop guard: `stop_hook_active` → no block; same `agent_id` + fingerprint twice → second is
   context; a different `agent_id` with the same problem → blocks.
6. W3: a lane session with a `child_tracker` exception → blocked with both kinds; the root
   session is not blocked by an exception in a child tracker.
7. W4: strict + labelled spawn without the line → deny; with it → allow; `warn` → allow with
   context; `off` and `orch_entry: none` → unchanged.
8. W1: both skills' `stop-check` and `inbox drain` commands are byte-identical; `plugin.json`
   ships `working-a-lane`; the skill has no `disable-model-invocation`.
9. W5: the fan-out advisory text says "open lanes".

**Done when** `scripts/test.sh` passes and `claude plugin validate . --strict` is clean.

## Deferred

`lane-settings.json` hooks for Paseo lanes that never load the skill (a deterministic backstop;
needs a dedup check first, since hooks run in parallel and a doubled `stop-check` would double-block).
Making orchestrator-only hooks (`resume` roster, `cost` advisories, `guard` cooldown) quiet in lane
sessions.

## Lanes

| Lane | Owns | Rung |
|---|---|---|
| core | `scripts/orch.py`; the `hooks:` frontmatter of **both** skills | frontier |
| skill | `working-a-lane/SKILL.md` body; moving content out of `BRIEF.template.md`/`briefs.md`; W5–W6 docs | standard |
| tests | `scripts/test_orch_lane.py` | standard |

A stub `working-a-lane/SKILL.md` and the `plugin.json` ship-list entry (0.19.0) are committed with this
spec: the core lane replaces only the `# HOOKS` frontmatter line, the skill lane only the `BODY` line. Working rules of `orch-cross-repo-consume.md`
§I apply. **Wall-clock time matters more than polish.**
