---
name: orchestrating
description: Orchestrate work across multiple agents with tracked dispatches, briefs and verification. Use when the user wants work fanned out or run in parallel, wants an agent given its own branch or worktree, is resuming a multi-agent program, needs input delivered to a busy agent, wants a front desk in front of an orchestrator, or when another skill needs the brief-contract rules.
# Every command below resolves its own interpreter rather than naming `python3` and
# letting PATH answer: a shim on PATH costs a blocked shell per fire, and these fire
# per tool call and per turn in every concurrent session. `ORCH_PYTHON` overrides.
# Measured, and reasoned through, in `context-economy`'s `spend.py` -- see HOOK_PY.
hooks:
  Stop:
    - hooks:
        - type: command
          command: 'PY="${ORCH_PYTHON:-}"; [ -x "$PY" ] || PY=/usr/bin/python3; [ -x "$PY" ] || PY=python3; for d in "$ORCH_SKILL_DIR" "$CLAUDE_PLUGIN_ROOT/skills/orchestrating" "$HOME/.claude/skills/orchestrating" "$HOME/.agents/skills/orchestrating"; do [ -f "$d/scripts/orch.py" ] && exec "$PY" "$d/scripts/orch.py" inbox drain --format hook; done; exit 0'
        - type: command
          command: 'PY="${ORCH_PYTHON:-}"; [ -x "$PY" ] || PY=/usr/bin/python3; [ -x "$PY" ] || PY=python3; for d in "$ORCH_SKILL_DIR" "$CLAUDE_PLUGIN_ROOT/skills/orchestrating" "$HOME/.claude/skills/orchestrating" "$HOME/.agents/skills/orchestrating"; do [ -f "$d/scripts/orch.py" ] && exec "$PY" "$d/scripts/orch.py" cost --format hook; done; exit 0'
        - type: command
          command: 'PY="${ORCH_PYTHON:-}"; [ -x "$PY" ] || PY=/usr/bin/python3; [ -x "$PY" ] || PY=python3; for d in "$ORCH_SKILL_DIR" "$CLAUDE_PLUGIN_ROOT/skills/orchestrating" "$HOME/.claude/skills/orchestrating" "$HOME/.agents/skills/orchestrating"; do [ -f "$d/scripts/orch.py" ] && exec "$PY" "$d/scripts/orch.py" wake check --format hook; done; exit 0'
  SessionStart:
    - matcher: "compact|resume"
      hooks:
        - type: command
          command: 'PY="${ORCH_PYTHON:-}"; [ -x "$PY" ] || PY=/usr/bin/python3; [ -x "$PY" ] || PY=python3; for d in "$ORCH_SKILL_DIR" "$CLAUDE_PLUGIN_ROOT/skills/orchestrating" "$HOME/.claude/skills/orchestrating" "$HOME/.agents/skills/orchestrating"; do [ -f "$d/scripts/orch.py" ] && exec "$PY" "$d/scripts/orch.py" resume --format hook; done; exit 0'
        - type: command
          command: 'PY="${ORCH_PYTHON:-}"; [ -x "$PY" ] || PY=/usr/bin/python3; [ -x "$PY" ] || PY=python3; for d in "$ORCH_SKILL_DIR" "$CLAUDE_PLUGIN_ROOT/skills/orchestrating" "$HOME/.claude/skills/orchestrating" "$HOME/.agents/skills/orchestrating"; do [ -f "$d/scripts/orch.py" ] && exec "$PY" "$d/scripts/orch.py" compaction check --format hook; done; exit 0'
        - type: command
          command: 'PY="${ORCH_PYTHON:-}"; [ -x "$PY" ] || PY=/usr/bin/python3; [ -x "$PY" ] || PY=python3; for d in "$ORCH_SKILL_DIR" "$CLAUDE_PLUGIN_ROOT/skills/orchestrating" "$HOME/.claude/skills/orchestrating" "$HOME/.agents/skills/orchestrating"; do [ -f "$d/scripts/orch.py" ] && exec "$PY" "$d/scripts/orch.py" model check --format hook; done; exit 0'
  PreToolUse:
    # Prefiltered in shell, like the `spend.py` guard: this fires on every Write,
    # Edit and Bash and almost always has nothing to say, so the payload is sized
    # by a shell builtin before an interpreter is started. The floor is the SMALLER
    # of the two guard floors -- the heredoc one, by default -- because filtering at
    # ORCH_GUARD_BYTES would silently drop heredoc detection. Reading stdin is
    # guarded by `[ -t 0 ]` so an interactive run cannot block, matching
    # `hook_payload`, and every compare fails open so a bad threshold costs a spawn
    # rather than the warning. No Read case: it is absent from the matcher, and
    # `_tool_input_size` scores it 0 regardless.
    - matcher: "Write|Edit|Bash"
      hooks:
        - type: command
          command: '[ -t 0 ] && exit 0; p=$(cat); f=${ORCH_GUARD_HEREDOC_BYTES:-1200}; b=${ORCH_GUARD_BYTES:-6000}; { [ "$b" -lt "$f" ] && f=$b; } 2>/dev/null; { [ ${#p} -lt "$f" ] && exit 0; } 2>/dev/null; PY="${ORCH_PYTHON:-}"; [ -x "$PY" ] || PY=/usr/bin/python3; [ -x "$PY" ] || PY=python3; for d in "$ORCH_SKILL_DIR" "$CLAUDE_PLUGIN_ROOT/skills/orchestrating" "$HOME/.claude/skills/orchestrating" "$HOME/.agents/skills/orchestrating"; do [ -f "$d/scripts/orch.py" ] || continue; printf %s "$p" | "$PY" "$d/scripts/orch.py" guard; exit $?; done; exit 0'
    # The spawn guard: a spawn or RETUNE -- Paseo, or a Claude Code subagent --
    # must honour its entry's recorded rung and mode, and follow-up rounds to one
    # lane are counted. Rare calls, so no shell prefilter. It can refuse
    # (permissionDecision: deny); every other path, including an internal error,
    # lets the call through.
    - matcher: "^(Agent|Task|mcp__paseo__create_agent|mcp__paseo__update_agent|mcp__paseo__send_agent_prompt)$"
      hooks:
        - type: command
          command: '[ -t 0 ] && exit 0; PY="${ORCH_PYTHON:-}"; [ -x "$PY" ] || PY=/usr/bin/python3; [ -x "$PY" ] || PY=python3; for d in "$ORCH_SKILL_DIR" "$CLAUDE_PLUGIN_ROOT/skills/orchestrating" "$HOME/.claude/skills/orchestrating" "$HOME/.agents/skills/orchestrating"; do [ -f "$d/scripts/orch.py" ] && exec "$PY" "$d/scripts/orch.py" spawn-guard; done; exit 0'
---

# Orchestrating

You are coordinating work that other agents perform. Your scarce resources are **your own context**,
**the human's attention**, and **your own availability** — how long until their next input is acted
on. Everything below exists to spend those three well.

This skill names no tools. It speaks in **capability verbs**; one substrate adapter maps them to
concrete calls. If you find yourself reaching for a specific tool before Step 0 has bound an
adapter, stop — you are about to hard-code the substrate.

## Principles

These six generate most of the rules. When a rule below seems arbitrary, it is one of these.

1. **Persist what cannot be re-derived; re-derive what can.** A stored copy of derivable state is
   not a convenience, it is a liability — it competes with the source of truth and wins on cost.
   Worker liveness is always re-derived. Worker *intent* is always persisted.
2. **Write through, never write back.** Every non-derivable fact becomes durable at the moment it is
   created. The record is a **precondition** of the action, never a follow-up: a spawn that fails
   after its record is recoverable, a record that fails after its spawn leaves an orphan.
3. **Reduce every writer set to one.** One writer per state file, one minter per id namespace, one
   sender per worker. Concurrency here is designed out, not solved.
4. **An unfalsifiable check is worse than no check.** It manufactures confidence. Before believing a
   green, know what would have made it red — and prefer to have seen it red.
5. **Only do what only you can do.** You are the most expensive agent in the program and the only
   one the human can reach. Work that merely *arrived* in your lap — landing a branch, patching a
   document — is work you are badly placed to perform.
6. **Your context is a tax on every remaining step.** It is re-read on every model call: 61% of a
   measured bill, against 3% for reasoning. A large read is a recurring charge, and rotating a
   bloated orchestrator is the cheapest saving available (`references/cost.md`).

## Step 0 — Bind a substrate

Read `references/substrates/_capabilities.md`. Follow its detection procedure and load **exactly
one** adapter. That adapter is now your only source for concrete calls.

Record which adapter you bound and what it cannot do. A verb your substrate lacks is a plan
constraint, not a thing to improvise around.

**Done when:** one adapter is loaded and its unavailable verbs are known.

## Step 1 — Decide whether to delegate at all

Delegate when at least one holds:

- the work wants its own branch, worktree, or reviewable workspace
- the work is genuinely independent and parallelisable
- you want only the *result*, not the process — the work would otherwise pollute your context
- a cheaper model or lower effort can do it without materially worse output

Do it inline when the dispatch costs more than the task — but weigh that against what the work's
residue charges every remaining call, not just the dispatch (`references/delegation.md`).

**Re-ask this question for work that arrives later.** A merge, a fix-up, a document patch — none were
units of work when you planned, so none were ever marked. They surface at intake with your context
already loaded, which is exactly why they get done inline. Route them back through this step; landing
has a standing home in `references/integration.md`.

**Keep turns bounded** so the human stays able to reach you. Rules of thumb, and the exceptions that
justify a long turn, are in `references/availability.md`.

Workers may themselves orchestrate; a decomposing task says so in its brief and gets a recommended
fan-out shape. Work that can outlive a turn gets a `progress_artifact` before its first dispatch —
the checkpoint contract is in `references/briefs.md`.

Substrate, isolation and archetype are chosen in `references/delegation.md`. Choose the archetype
and let `orch open` set the rung from it; never copy a `model:` from an earlier brief.

**Done when:** each unit of work is marked *delegate* or *do inline*, with a reason.

## Step 2 — Locate or mint program state

Before the first dispatch, find the tracker: run `orch programs` (see the Reference map for the
path). Use a matching program if one exists; otherwise mint one and **notify, do not ask**. `orch`
refuses to guess when others already exist — that is the one place minting warrants an interruption.

A plan document is optional. If one exists, link it and patch it **at the moment a decision is
ruled** — a ruling that lives only in conversation is the defect. If none exists, the plan lives in
session context; say so, and point the human at a handoff skill if they need to transfer it.

Then **claim your inbox** — `orch inbox claim --as root` — so queued input reaches you at the end of
a turn instead of racing your current one. One call, once per program. If the human named a spend
limit, record it with `orch budget --set <usd>` so the warning is measured against their intent
rather than a default.

**Done when:** exactly one program is bound, its plan-document link is set or explicitly absent, and
this worktree's inbox is claimed.

## Step 3 — Compose the dispatch, in this order

**Brief → record → spawn.** Never reorder; see Principle 2.

1. **Write the brief to a file.** Not into the spawn prompt. A file is single-sourced with the
   tracker, survives the worker's own context loss, gives a replacement worker byte-identical
   instructions, and is the only way an interrupted worker can recover its task. Use
   `assets/BRIEF.template.md`; the contract is in `references/briefs.md`. Set `review:` here — who
   reads this lane's diff before it lands is a property of the spec, not a call made later with the
   finished diff in hand (`references/integration.md`).
   For build work, make the brief one acceptance-criterion-sized **slice**. Declare its read and
   write sets; parallel lanes may not overlap a write set, and a shared discovery map must replace
   repeated whole-repository reading. Let the resolved lane limits reserve budget before spawning.
2. **Record it**, passing the brief so its front matter supplies the required fields rather than you
   restating them. A dispatch the tracker does not know about is undispatched work.
3. **`SPAWN`**, with `ISOLATE` if the work earns its own branch or worktree, using exactly the
   model, mode and label `orch open` printed — the spawn guard refuses anything else.

Reference the project's standing-rules file — generated from `assets/STANDING-RULES.template.md` on
first use — and never restate it: repeated prose costs output tokens every dispatch and goes stale on
the first correction.

**Done when:** a brief file exists, a tracker entry exists naming its worker handle, and the worker
is running — in that order.

## Step 4 — While work is in flight

**Liveness.** Notifications are the good path. Heartbeats are the insurance. Explicit
reconciliation is for a failed heartbeat or for re-deriving state from a fresh context — *never* as
a wait loop. Register every `WAKE` with `orch wake register`, because a heartbeat's lifetime is the
lifetime of the lanes it insures and nothing else will retire it. Details in
`references/liveness.md`.

**Messaging.** Read `references/messaging.md` before sending anything to a running worker. Mid-task
correction does not exist on any substrate: a correction waits, destroys work, or comes from the
worker via `ESCALATE`. Peer questions are usually artifact reads in disguise — ask the filesystem.

**Queued input.** Anything addressed to a busy agent — including you — goes to its inbox and is
drained between turns. Nobody sends; senders append. `references/availability.md`.

**Resources.** Capacity gates are enforced against the operating system, never against a tracker or
a peer's claim.

**Lane budgets.** `orch open` resolves and records limits for model calls, retained context, cost
and checkpoint cadence. `orch budget` shows measured program spend plus live reservations; it is
an admission gate, not a warning after the money is gone. At a lane boundary, checkpoint and replace
from the artifact rather than continue a bloated history. If recovery is necessary, preserve the
worktree and patch first; a successor inspects and verifies uncommitted work before committing it.

**Rotate before you are expensive.** Compaction fires early and a session-start hook re-derives
your state afterwards; act at a seam when the turn-end hook warns (`references/cost.md`). When a
summary will not do, `orch rotate begin` — **never spawn a successor and archive yourself**
(`references/rotation.md`, which also covers `cursor_root_envelope_limit` and
`cursor_blob_capacity`). When the hook raises `FRONT-DESK`, offer one once (`references/frontdesk.md`).

**Tuning.** `RETUNE` is the only safe way to influence work underway, and what makes starting cheap
safe. Raise a lane only on an observed signal, recorded first — `orch escalate <e> --to <rung>
--scope task|attempt --reason "<what you saw>" --evidence <pointer>` — then RETUNE to a model it
prints. Lane tier is the largest cost lever measured here (`references/cost.md`).

**Done when:** every lane in `orch roster` has either reported or is insured by a wake in `orch wake
list`, and no hook advisory from this turn is unanswered.

## Step 5 — Intake

For every returned report:

1. **Read the falsification line.** What would have made this red, and was it observed red? "I could
   not make it fail" is itself the finding — surface it.
2. **Check the claim's provenance.** A number produced in a tree that does not contain the change
   under test is always green. Require the report to state *where* a result came from and whether
   that context could have failed.
3. **Escalate to independent verification** when both hold: the same agent authored the change *and*
   its check, and the change is hard to reverse. Not merely "important."
4. **Hand the landing to the integrator lane**, with the report and the brief's `review:` mode.
   Reading a worker's diff to decide whether it may land is the second reader's job, and the second
   reader need not be you — `references/integration.md`. What stays yours is this list.
5. **Graduate the provenance** — what was commissioned, what it produced, what was ruled — into a
   durable in-repo artifact. Then patch the plan document if a ruling came out of it.

**Done when:** the report's central claim is falsifiable and either falsified or corroborated, its
landing is commissioned or ruled unnecessary, and its provenance lives somewhere durable.

## Step 6 — Closeout

- **Commit with explicit paths** whenever any worker is live. A commit-everything always succeeds,
  including at sweeping up another lane's uncommitted work. You hold the *authority* over what enters
  history and in what order; the integrator does the *labor*.
- **`CLOSE`** the worker, then delete its tracker entry. An entry you cannot delete is an output
  nobody consumed — that is the signal, not a nuisance.
- **Delete any wake the close just orphaned, and `RECLAIM` any container the lane held** — here, not
  as later housekeeping. `orch close` names both. A heartbeat that outlives its lanes is a loop, not
  insurance; a workspace that outlives its worker is a row the human has to dismiss. Commit first —
  reclaiming keeps the branch, not the uncommitted tree.
- **Reclaim everything else by explicit name, never by glob**, and never while any build is running.

**Done when:** the entry is deleted, every wake it orphaned is gone, every container it held is archived, provenance is durable, and resources are reclaimed.

## Reference map

Each step names the reference it needs; load them on demand. Not pointed to above:
`references/state.md` (tracker layout, ids, the full `orch` command surface),
`references/verification.md` (the checks-that-cannot-fail catalog), `references/closeout.md`
(commits, hygiene, reclamation), and `references/statusline.md` (the human's status surface).

**Tooling.** Tracker and inbox operations go through `scripts/orch.py`; per-harness path resolution,
`ORCH_SKILL_DIR` included, is in `references/substrates/_capabilities.md`. Never edit tracker files
by hand — the script's field enforcement is the point. The hooks this skill registers speak only
when they have something to say, and say what to do.

**Status for the human.** Never narrate the roster into chat — it becomes permanent context re-read
every later turn. `orch statusline` renders it into harness chrome the model never pays for.
