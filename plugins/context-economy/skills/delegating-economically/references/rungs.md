# Rungs — which work sits where, and what earns an escalation

Every archetype sets two independent axes, and a row that names only one is
incomplete:

- **Rung** — capability and cost. Relative to the provider, never an absolute
  model name. Ask the substrate for its live model list at spawn time and map
  the rung then.
- **Independence** — how far the worker stands from the author of what it
  touches: `none`, `not the author` (a fresh context that did not write the
  thing), or `different family`. A different family is never a rung; it is
  chosen *at* a rung.

The model ladder is `minimal` → `economy` → `advanced` → `frontier`.
`advanced` is for complex, interconnected, or sustained work that merits more
capability than the economy anchor.

**`frontier` is a designation, not "the most expensive model".** The option map
names which models serve it, and those may be `advanced` models judged capable
enough for frontier work — that is deliberate, and it caps what an escalation to
the top can cost. A pricier model the map does not tag `frontier` is off the
ladder: no rung selects it, and it is reached only on an explicit human request
naming it.

## The provider default is not a rung

The provider default is whatever model the provider or harness selects when the
model is omitted. It can land on any rung and can move without a configuration
change. At session start, identify the actual selected model and map it to the
ladder before relying on its cost or capability. At subagent spawn, set the
intended rung or current model explicitly.

Do not translate an omitted model to `advanced`. In one observed case, the
provider default moved from a Sonnet-class model to an Opus-class model while
still being called "default"; 6,509 calls cost $616 where the same tokens one
rung down cost $246.

Effort, where the provider exposes a separate dial: **default** (what the model
reports as its own default), **one below default**, **lowest**, and — escalation
only — **above default**. Here `default` names an effort setting, not a model
rung. Some providers expose no such dial, and there the archetype's "model and
effort" collapses to model alone.

## Resolve the rung mechanically

Do not make the agent remember which current model belongs on a rung. Ask the
local selector immediately before dispatch:

```bash
spend models --archetype implementer
spend models --rung advanced
spend models --archetype reviewer --exclude-family claude-opus
```

The selector intersects a small, versioned capability map with the harness's
live model catalog. Its output therefore contains only models that are both
appropriate for the requested work and available to this session, using the
exact slug and a supported effort value. `--format json` gives an agent a
machine-readable result.

Every model the selector returns is a **canonical id** — the provider's own API
id, never a Cursor slug, an `ocx-*` route name, or a short alias like `sonnet`
or `opus`. Aliases are accepted as *input* (`--source-model opus`) and
translated, with the translation and its table date reported; they never come
back out as a recommendation. Under Claude Code, each row also carries a `spawn` field — the exact value
the Agent tool accepts, kept on the route the recommendation was priced on:
an alias, when the harness's dated alias table still maps it to this exact
id, else an agent definition named for the canonical id. The alias comes
first because it spawns the built-in general-purpose agent; a definition's
markdown body *replaces* that system prompt, so a bare one leaves the worker
with almost none.
A drifted alias — the table's `opus` pointing at last generation's Opus
while the recommendation is this generation's — is refused rather than
spawning the wrong model, and refusal still surfaces `via` alternatives. A
routed (`ocx-*`) definition on a *different* route never appears as `spawn`;
it is listed separately in `via` with its own route and price, because a
different route bills differently for the same model. `spend agents --write`
writes id-named definitions, needed only for a model no current alias
reaches, such as a previous generation (`--all` for every anthropic-route
option), on request only; `--prune` also removes the files it stamped whose model no
longer is.

Codex catalogs are discovered at `$CODEX_HOME/models_cache.json` or
`~/.codex/models_cache.json`. Other harnesses can pass their equivalent JSON
with `--catalog` or `SPEND_MODEL_CATALOG`; the accepted shape is either a list
of model records or an object with a `models` list. Each record needs `slug`
and may provide `visibility` and `supported_reasoning_levels`.

The capability map is `model-options.json`, beside this file. Model names live
there because they are volatile data, not durable guidance. Update that map
when providers ship or retire models; do not add another provider section here.
`validate_options` enforces the policy as well as the shape: no archetype
starts above `economy`, archetype effort is relative, and a rung's preference
must be tagged with that rung. Done when `spend models` returns at least one
exact live slug for the intended rung or archetype.

## The table

This table is the prose owner of the catalogue; `model-options.json` is its
machine form, and a test fails when the two disagree. The orchestration-only
archetypes (`integrator`, `frontdesk`) are in the map so the selector resolves
them, and their prose lives in the orchestrating skill.

| Archetype | What it does | How it fails | Rung / effort | Independence | Escalate when |
|---|---|---|---|---|---|
| **Implementer** | writes the change for one scoped item | scope creep into neighbouring items; edits a generated file instead of its source | economy / default | none | the change spans several files — then above-default effort; the brief names the subsystems the change spans, or a first attempt came back with the scope wrong — then advanced |
| **Analyst** | traces behaviour, enumerates cases, builds an argument | confident narrative resting on an unverified premise | economy / default | none | the deliverable is an analytical document or report — then above-default effort; the argument is many hops deep, a premise is disputed, or a prior pass was refuted — then advanced |
| **Reviewer** | judges an artifact someone else produced — code, a claim, a decision, a plan | agrees for the author's reason; or returns speculative nits with no evidence | economy / default | different family | see *Reviewing* below — family first, then rung |
| **Verifier** | runs the suite, the build, the assertions; reports numbers | reports a green that could not have gone red | economy / one-below-default | not the author | the guard cannot be made to go red and nobody knows why — then advanced |
| **Verifier, low-risk** | re-runs a check whose pass/fail is mechanical and trivially re-checkable at intake | same, but it is caught at intake | minimal / lowest | not the author | any doubt at all — then it is the row above |
| **Doc writer** | reports, review docs, structured artifacts | narrates the journey instead of the result | minimal / lowest | none | rarely — prefer a better outline over more thinking |
| **Inventory / cleanup** | disk audits, mechanical sweeps, resource reclamation | deletes by glob; deletes something still in use | minimal / lowest | none | never; if it needs thought it is not this archetype |

**Reviewer and verifier are different jobs.** A verifier *runs* something and
its evidence is output. A reviewer *reads* something and its evidence is an
argument. They fail differently, so they carry different contracts.

## Reviewing

One archetype covers every "second pair of eyes": a code review, a premise
audit, a contrasting opinion, a second opinion on a decision. The object
differs; the rule does not.

- **Independence is what you are buying, so it is mandatory.** Always a fresh
  context; never the author's session. A different *lineage* from the *author*
  of the thing reviewed — not from whoever dispatches the review — resolved
  with `spend models --archetype reviewer --exclude-family <author's family>`,
  which rules out the family's whole lineage: excluding `claude-opus` excludes
  `claude-sonnet` too, because two sizes of one lineage share its blind spots. The
  selector refuses the archetype without it. When no other family is
  reachable, `--same-family-ok "<why>"` waives it and puts the reason on
  record; never fall back silently.
- **The rung follows the brief's specificity, not the author's rung.** A review
  whose brief enumerates the sites, the rulings it must hold the change to, and
  the mutations or counter-examples it must try is economy work. A brief that
  can only say "find anything" is the one pre-dispatch case for `advanced` —
  but first try to narrow it; a narrower brief is cheaper than a higher rung
  and compounds. Matching the author's rung would import every escalation the
  author earned into a job that did not earn it.
- **The floor is `economy`, never `minimal`.** A bad verdict is
  indistinguishable from a good one until something downstream breaks.
- **Contract: every finding cites a location and its evidence** — `file:line`
  plus a reproducing input, or the enumerated mutation that exposes it. For a
  claim, the evidence that would settle it either way. A finding without
  evidence is dropped at intake, not weighed.
- **Escalate the axis that failed.** A pass found nothing and you have
  specific reason to doubt it → switch family first, since a shared blind spot
  is the likelier cause. A pass found only shallow issues and missed a
  many-hop interaction → raise the rung.

For a premise audit specifically, **capability is not the lever** — an auditor
that shares your model's training and your context's framing agrees with you
for exactly the reason you are wrong, and a higher rung of the same family does
not fix that.

## Why the anchor is `economy`

An earlier version of this table anchored at the provider default, arguing
that a more capable model is cheap relative to a wrong answer. Two things were
wrong with that.

**The referent drifted.** "Default" names whichever model the provider currently
selects, and that moved up a tier while the rung wording stayed put. Nothing
looked stale. The sentence that once meant a Sonnet-class model came to mean an
Opus-class one, and the bill recorded it: **6,509 subagent calls at $616 where
the same tokens one rung down cost $246** — 39% of a four-day bill.

**The asymmetry was assumed, not measured.** A wrong answer is expensive only if
it is not caught. Of 31 subagent tasks measured at the higher anchor, **28
finished correctly on the first attempt and only 3 needed rework** — so the rung
above was paying a 2.5x premium to avoid an outcome that occurred three times.

The same argument now applies when choosing `advanced` over `economy`, and is
*untested there*, which is exactly why escalation should be recorded. An
archetype that escalates every time has the wrong starting rung: fix its row
rather than escalating it forever.

## Escalating

Evidence may be visible before dispatch: interconnected scope, a long dependent
chain, or high restart cost justifies starting at `advanced`. Otherwise start at
the table's rung and escalate on an observed signal. A running subagent's model
can usually be changed without restating its instructions, so an escalation
costs one message when the starting rung turns out to be wrong.

Never start at **frontier**; `validate_options` refuses an archetype that does. Reserve the top of the
dial for work the human has explicitly asked for at that level, or for an
escalation you can justify from something you observed.

## Contrast is a family, not a provider

A bridged provider hosting the same underlying model family is a billing path,
not an independent opinion. `--exclude-family` compares the map's `lineage`
field, never the route, for exactly this reason — and never the finer
`family`, which separates sizes of one lineage.
