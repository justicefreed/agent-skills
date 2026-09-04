---
name: orchestrating
description: Orchestrate work across multiple agents — decide whether to delegate at all, choose the execution substrate and isolation, pick model and effort, write briefs, track dispatches, and verify what comes back. Use when the user wants work fanned out to subagents or run in parallel, wants an agent given its own branch or worktree, is resuming a multi-agent program, is deciding whether a task is worth delegating, or when another skill needs the delegation and brief-contract rules.
---

# Orchestrating

You are coordinating work that other agents perform. Your scarce resources are **your own context**
and **the human's attention**. Everything below exists to spend those two well.

This skill names no tools. It speaks in **capability verbs**; one substrate adapter maps them to
concrete calls. If you find yourself reaching for a specific tool before Step 0 has bound an
adapter, stop — you are about to hard-code the substrate.

## Principles

These four generate most of the rules. When a rule below seems arbitrary, it is one of these.

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

Do **not** delegate when the task is a single lookup you could do faster yourself, or when the
delegation overhead exceeds the work. Fan-out is not free: each worker costs a brief, a record, an
intake and a closeout.

Workers may themselves orchestrate. When a delegated task decomposes further, say so in the brief
and tell the worker to load this skill. Recommend a fan-out shape rather than leaving it open.

See `references/delegation.md` for substrate choice, isolation choice, and the archetype catalog
with model/effort guidance.

**Done when:** each unit of work is marked *delegate* or *do inline*, with a reason.

## Step 2 — Locate or mint program state

Before the first dispatch, find the tracker: run `orch programs` (see the Reference map for the
path). Then:

- **Programs exist and one matches** → use it.
- **None exist** → mint one. Derive the name from the plan document's directory if there is a plan
  document, otherwise `default`. **Notify, do not ask.**
- **Programs exist and none match** → **ask.** This is the one place minting warrants an
  interruption, because a second namespace alongside an existing one splits your state, and each
  half will look internally consistent.

A plan document is optional. If one exists, link it and patch it **at the moment a decision is
ruled** — a ruling that lives only in conversation is the defect. If none exists, the plan lives in
session context; say so, and point the human at a handoff skill if they need to transfer it.

**Done when:** exactly one program is bound, and its plan-document link is set or explicitly absent.

## Step 3 — Compose the dispatch, in this order

**Brief → record → spawn.** Never reorder; see Principle 2.

1. **Write the brief to a file.** Not into the spawn prompt. A file is single-sourced with the
   tracker, survives the worker's own context loss, gives a replacement worker byte-identical
   instructions, and is the only way an interrupted worker can recover its task. Use
   `assets/BRIEF.template.md`; the contract is in `references/briefs.md`.
2. **Record it**, passing the brief so its front matter supplies the required fields rather than you
   restating them. A dispatch the tracker does not know about is undispatched work.
3. **`SPAWN`**, with `ISOLATE` if the work earns its own branch or worktree.

Reference the project's standing-rules file; never restate its contents in a brief. Repeated prose
costs your output tokens on every dispatch and goes stale the first time a rule is corrected.

**Done when:** a brief file exists, a tracker entry exists naming its worker handle, and the worker
is running — in that order.

## Step 4 — While work is in flight

**Liveness.** Notifications are the good path. Heartbeats are the insurance. Explicit
reconciliation is for a failed heartbeat or for re-deriving state from a fresh context — *never* as
a wait loop. Details in `references/liveness.md`.

**Messaging.** Read `references/messaging.md` before sending anything to a running worker. The
short version: mid-task correction does not exist on any substrate, so a correction either waits,
destroys work, or comes from the worker via `ESCALATE`. Peer questions are usually artifact reads in
disguise — ask the filesystem, not the agent.

**Resources.** Global constraints (build capacity, one writer per worktree) are enforced against the
operating system, never against a tracker or a peer's claim.

**Tuning.** `RETUNE` changes a running worker's model or effort without touching its instructions.
It is the only safe way to influence work already underway; prefer starting cheap and escalating.

## Step 5 — Intake

For every returned report:

1. **Read the falsification line.** What would have made this red, and was it observed red? "I could
   not make it fail" is itself the finding — surface it.
2. **Check the claim's provenance.** A number produced in a tree that does not contain the change
   under test is always green. Require the report to state *where* a result came from and whether
   that context could have failed.
3. **Escalate to independent verification** when both hold: the same agent authored the change *and*
   its check, and the change is hard to reverse. Not merely "important."
4. **Graduate the provenance** — what was commissioned, what it produced, what was ruled — into a
   durable in-repo artifact. Then patch the plan document if a ruling came out of it.

**Done when:** the report's central claim is falsifiable and either falsified or corroborated, and
its provenance lives somewhere durable.

## Step 6 — Closeout

- **Commit with explicit paths** whenever any worker is live. A commit-everything always succeeds,
  including at sweeping up another lane's uncommitted work.
- **`CLOSE`** the worker, then delete its tracker entry. An entry you cannot delete is an output
  nobody consumed — that is the signal, not a nuisance.
- **Reclaim resources by explicit name, never by glob**, and never while any build is running.

**Done when:** the entry is deleted, provenance is durable, and resources are reclaimed.

## Reference map

Load these on demand, not up front.

| File | When |
|---|---|
| `references/substrates/_capabilities.md` | Step 0, always — verb vocabulary and detection |
| `references/substrates/*.md` | the one adapter Step 0 selects |
| `references/delegation.md` | substrate, isolation, archetype, model and effort |
| `references/briefs.md` | brief front matter, body, and report contract |
| `references/state.md` | tracker layout, ids, and the `orch` command surface |
| `references/liveness.md` | notifications, heartbeats, reconciliation |
| `references/messaging.md` | what may be sent to a worker, and when |
| `references/verification.md` | the checks-that-cannot-fail catalog |
| `references/closeout.md` | commits, hygiene, resource reclamation |

**Tooling.** Tracker operations go through `scripts/orch.py`, resolved relative to this skill's base
directory. Harness-specific path resolution is in `references/substrates/_capabilities.md`. Never
edit tracker files by hand: the script enforces the required fields, and the enforcement is the
point.

**Project rules.** A repo running a program should carry a standing-rules file holding *its* facts —
build discipline, formatter exclusions, known traps, output-verbosity preferences. Generate it from
`assets/STANDING-RULES.template.md` on first use. Those facts belong to the project, not to this
skill, and briefs reference that file rather than repeating it.
