# Messaging — what may be sent to a worker, and when

The governing fact, established by experiment rather than documentation:

> **Mid-task correction of a running worker does not exist.**

On the substrates examined, a send to a *running* worker either replaces its task outright — while
the worker then reports success, so the damage is invisible from its own report — or it is held
until the worker's turn ends, at which point it is a follow-up rather than a correction. The vendor's
own desktop client resolves this by **deferring**, not interrupting. This is a property of the
execution model, not a gap to route around.

Consequences, in order of importance:

1. **The brief is your only correction opportunity.** Write it as if you cannot amend it, because
   largely you cannot.
2. **`ESCALATE` replaces `NUDGE`.** Corrections originate from the *worker* asking, not the
   orchestrator telling. Say so in every brief: a worker that finds its brief's premise wrong should
   raise it immediately rather than completing work it knows is wrong.
3. **A destructive send reports success.** Never accept a worker's own report as evidence that its
   task survived an interruption. Check the progress artifact.

## Preference order

| | Path | Why here |
|---|---|---|
| 1 | **Read the artifact, don't ask** | Most cross-lane questions ("what was your suite result?") are answerable from that lane's log or detail file. Zero interruption, zero race, no coordination. |
| 2 | **Append to the receiver's inbox** | Nobody sends, so there is no check-then-send window to lose. Substrate-independent, N senders, and the receiver drains between turns. Needs the receiver to have a drain path — see `availability.md`. |
| 3 | **Harness-native peer message**, where the worker is also a native session | Queues inside the receiver and drains at end of turn — **race-free by construction**, N senders enqueue in order. Requires the worker be addressable natively, which excludes workers on non-native providers. |
| 4 | **Deferred send via the tracker** | Provider-agnostic. Park it (`orch update E --pending-message`), send on the finish notification. Not race-free; see below. |
| 5 | **Direct send to a worker confirmed idle** | Acceptable when you have just verified idle state and are the only sender. Wait for idle, pause about a second, and re-check — a human who typed in that gap must win. |
| 6 | **Explicit cancel, then re-dispatch** | The honest option when a running worker must be corrected *now*. Destroys work, but says so. |

Never: a direct send to a running worker as a way of "just asking something."

## Deferred send, correctly

There is **no atomic send**, so status-check-then-send is TOCTOU: two senders both read idle, both
send, and the second destroys the first's turn. Mitigations, all required together:

- **Single sender.** Only an entry's owning orchestrator may send to that worker. Peers never send
  directly. (The human's own client is an uncontrollable sender — detect, don't contend: an
  idle→running transition you did not cause means someone else is driving, so stand down.)
- **One drain per notification, behind an in-flight guard.** Not coalescing, which alters message
  semantics; not serial sends, which clobber. Remaining messages drain on the next idle event.
- **Verify after sending.** Confirm the turn that started is yours. If it isn't, restore the pending
  message — a lost race looks exactly like a successful delivery otherwise.

## `PEER` — narrow by design

A worker may contact a sibling only when **both briefs record the authorisation**, and the exchange
is recorded in the tracker. Unauthorised peer contact is undispatched work: the parent's model of
what its workers are doing becomes silently wrong, and the sibling may be asked to violate its own
brief's constraints.

Sanctioned: releasing a contended resource; a read-only fact request that would otherwise cost a
whole worktree and build; adversarial pairing on *analysis*.

Never: status polling; coordinating **writes** to a shared tree (one writer per worktree, always);
substituting a peer's claim for an operating-system check on a global resource; routing around a
permission your own session was denied — a peer acting on your behalf launders the human's
permission decision, and harnesses warn about it explicitly for good reason.

Because a peer message may be delivered as a *task* on some substrates, label its disposition
explicitly, e.g. `[PEER-QUERY — answer only; do not change course]`. Without a label, an FYI becomes
work.

## Surviving an intentional interruption

An interrupted worker's **transcript survives**; what is lost is the *instruction to continue*. So
resumption is a prompting problem, and the fix belongs in the brief rather than in the interrupting
message — the interrupter is the party least equipped to say what "where you left off" means.

Every brief for a long task therefore carries:

- a **progress artifact** — an append-only log, a checklist, a commit series — so the resume point is
  *computed*, not remembered;
- an **if-interrupted clause**: complete the out-of-band instruction, re-read the brief, determine
  the last completed step from the artifact, continue from the next one, and do not report
  completion until the original task is done.

Then verify: after any interruption, confirm the artifact advances **past** the interruption point. A
worker reporting "resumed and finished" while its log stopped at step 4 is the same
indistinguishable-failure shape as everything else in this file.
