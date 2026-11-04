# Spec addendum — deterministic adherence

Status: **approved for build**. Extends `orch-cross-repo-consume.md` (same target, 0.17.0). Claude
Code only: the turn-end checks are Claude Code Stop hooks; every refusal is in the CLI and so works
in any harness. Rationale graduates into `docs/DESIGN.md` §9h at merge; this file is then deleted.

## Goal

Each place adherence slipped gets the strongest lever that fits it — a refusal in the CLI, then a
turn-end block — and every way out takes a recorded reason. Prose is not a lever.

| Slip | Lever | Applies at |
|---|---|---|
| A track-linked entry closed with `close` | `close` refuses; `--untracked "<reason>"` | every level |
| A brief for planned work with no track target | `open` refuses; `untracked_reason:` | `strict`, in a program that uses agent-track |
| A worker stops with a missing, stale or vacuous checkpoint | Stop hook blocks the lane's turn end | `strict` (`warn`: reports) |
| The orchestrator stops with an exception or a crashed consume outstanding | Stop hook blocks the orchestrator's turn end | `strict` (`warn`: reports) |
| Nobody runs `audit` | one summary line in `resume` and `roster` | every level |

Deferred: PreToolUse denials of hand-run `track` writes (orchestrator or worker); Paseo-plugin
enforcement for non-Claude lanes. Revisit with `warn`-mode data.

## P1. Policy

`orch policy` prints the level; `orch policy off|warn|strict` sets it. Stored at
`<program dir>/policy.json` as `{"version": 1, "level": "...", "set_at": "..."}`. Absent means
`off`, which is 0.16.3 behaviour plus P2 and P5. Any other value is refused. `roster`'s header and
`resume` print the level when it is not `off`.

**A program uses agent-track** when `<home root>/.track/` is a directory **and** `track` is on
PATH. Every agent-track-dependent rule below is conditional on this, so a user without agent-track
never meets one.

## P2. `close` refuses track-linked entries — every level

An entry whose `advances` contains any mapping (`track:` target) is refused by `orch close`:

```
e3 has agent-track targets (T-015). Close it with `orch consume e3 --consumed ... --evidence ...`,
or, if the item must not advance, `orch close e3 --consumed "..." --untracked "<why>"`.
```

`--untracked` with a non-placeholder reason closes it and appends an override (P6). This applies at
`off` too: mapping `advances` are new in 0.17.0, so no existing program is affected.

## P3. `open` requires a track target — `strict`, agent-track programs only

At `strict` in a program that uses agent-track, a brief must have ≥1 mapping target **or** a
non-placeholder `untracked_reason:` front-matter field. Otherwise `open` refuses and names both
fixes. With `untracked_reason:`, `open` succeeds and appends an override. At `warn`, `open`
succeeds and prints the same text as a one-line warning on stderr. Legacy plan ids do not count as
track targets.

`untracked_reason` joins `OPTIONAL_BRIEF_FIELDS`. **First, check whether main's brief validator
rejects unknown front-matter keys.** If it does, rollback to main would break on any brief using
this field: add the tolerance as its own first commit, cherry-pickable like §A was.

## P4. `orch stop-check --format hook` — the turn-end check

Wired as a fourth Stop hook in `SKILL.md`'s frontmatter, using the existing resolution loop
verbatim. It runs at every turn end in every session, so the fast path is the existing one: exit 0
with no output unless `list_programs` finds a program. **It never calls `track` or git
subprocesses.**

Payload fields used: `cwd`, `session_id`, `stop_hook_active`. Resolve the program through
`repo_identity(cwd)`, which is marker-aware. Level `off` → no output.

**Role.** Resolve the cwd's worktree top-level from the filesystem. If exactly one open entry's
`worktree` (realpath) equals it and its status is `running`, this session is that **lane**. More
than one match → no output (an inherited worktree is ambiguous; `whoami` takes the same view).
Otherwise it is the **orchestrator**.

**Obligations**, using the same checks and codes as `audit` (refactor; do not duplicate):

- lane: `checkpoint-missing`, `checkpoint-stale`, `checkpoint-incomplete` for its own entry only;
- orchestrator: `exception`, `harvested-unfinished`. Lane checkpoint findings never block the
  orchestrator: it cannot fix them in its own turn.

**Output.** No obligations → no output. Otherwise build one reason text that names each obligation
and the exact fix, for example:

```
CHECKPOINT REQUIRED for e3: /…/C-lane1/PROGRESS.md — Verification, Next safe action absent,
empty or vacuous. Update it with the last durable milestone, verification evidence, uncertain
external effects and one safe next action, then stop.
```

```
UNAPPLIED CONSUMPTION e3: T-015 NOT_CURRENT — track show T-015; then: orch consume e3
```

- `strict`, not suppressed → `{"decision": "block", "reason": "<text>"}`.
- `warn`, or `strict` but suppressed → `{"hookSpecificOutput": {"hookEventName": "Stop",
  "additionalContext": "<text>"}}`.

**Suppression — the loop guard.** Suppressed when `stop_hook_active` is true, **or** this
`session_id` was already blocked for the same obligation fingerprint (sha256 of the sorted
`code:tracker.entry` list). Record each block in `<program dir>/stop-blocks/<session_id>.json` as
`{"fingerprint", "at"}`. A *changed* fingerprint blocks again. Missing `session_id` → never block,
only report.

## P5. Audit summary in `resume` and `roster` — every level

When `audit` would report findings, both print one line:
`audit: 3 findings (checkpoint-stale ×2, exception) — orch audit`. Clean → nothing. Computed
without the `target-moved` check (no `track` subprocess on these paths), so the line can be clean
while `orch audit` is not; the full command is authoritative.

## P6. Overrides

Every way out — `--untracked`, `untracked_reason:` — appends one JSON line to
`<program dir>/overrides.jsonl`: `{"at", "kind", "tracker", "entry", "targets", "reason"}`, with
`kind` `untracked-close` or `untracked-open`. `orch audit` prints overrides from the last 7 days
under a separate `overrides` heading. They **are not findings**: they never change the exit code or
the P5 line. An override is a decision someone made, not a defect.

## P7. Docs (orchestrator writes these)

`cross-repo.md`: agent-track is optional, where to get it (github.com/justicefreed/agent-track),
and what a program without it does. A new `references/adherence.md`: levels, which rule applies
where, the loop guard, overrides. `SKILL.md`: ≤60 words pointing at it. `DESIGN.md` §9h: the
lever ordering and why `close` refuses at every level.

## P8. Tests — acceptance list

Extend `test_orch_consume.py` or add `test_orch_adherence.py`. Every check must fail before the
code exists:

1. P1: default `off`; set and show each level; an invalid level is refused; `roster` header shows
   `strict`.
2. P2: `close` refuses a mapping entry and the tracker is unchanged; `--untracked` closes it and
   appends an override; a placeholder reason is refused; a legacy entry closes as before.
3. P3: strict plus a track program → an unmapped brief is refused; `untracked_reason:` opens and
   logs an override; `warn` opens with a warning; strict without `.track/` → opens (the non-agent-track
   user); strict with `.track/` but no `track` on PATH → opens.
4. P4 lane: strict plus a vacuous checkpoint → `decision: block` naming the labels; a good fresh
   checkpoint → no output; `warn` → `additionalContext`, not block; `off` → no output.
5. P4 loop guard: `stop_hook_active` → not block; the same session and fingerprint a second time →
   not block; a changed fingerprint → block; no `session_id` → not block.
6. P4 orchestrator: an exception → block; a lane checkpoint problem alone → no block for the
   orchestrator; a cwd in a repo with no program → no output; a non-git cwd → no output.
7. P4: the fake `track`'s log shows no call made by `stop-check`.
8. P5: a finding → one `audit:` line in both `resume` and `roster`; clean → none.
9. P6: `audit` lists recent overrides and still exits 0 on a program whose only content is overrides.

**Done when** `scripts/test.sh` prints `all suites pass` and `claude plugin validate . --strict` is
clean.

## Lanes

| Lane | Owns | Rung |
|---|---|---|
| core | `scripts/orch.py`; `SKILL.md` frontmatter only (the new Stop hook entry) | frontier |
| tests | the new or extended suite and the fake `track` | standard |
| docs | the orchestrator (P7) | — |

The working rules of `orch-cross-repo-consume.md` §I apply verbatim. **Wall-clock time matters
more than polish.**
