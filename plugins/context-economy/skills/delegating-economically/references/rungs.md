# Rungs — which work sits where, and what earns an escalation

Model rungs are **relative to the provider**, never absolute model names. Ask
the substrate for its live model list at spawn time and map the rung then.
Adjacent rungs may resolve to the same model when the live catalog has no useful
distinction between them.

The model ladder is `minimal` → `economy` → `advanced` → `frontier`.
`advanced` is for complex, interconnected, or sustained work that merits more
capability than the economy anchor without requiring the provider's absolute
best model.

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
spend models --archetype premise-auditor --exclude-family gpt-5.6
```

The selector intersects a small, versioned capability map with the harness's
live model catalog. Its output therefore contains only models that are both
appropriate for the requested work and available to this session, using the
exact slug and a supported effort value. `--format json` gives an agent a
machine-readable result.

Codex catalogs are discovered at `$CODEX_HOME/models_cache.json` or
`~/.codex/models_cache.json`. Other harnesses can pass their equivalent JSON
with `--catalog` or `SPEND_MODEL_CATALOG`; the accepted shape is either a list
of model records or an object with a `models` list. Each record needs `slug`
and may provide `visibility` and `supported_reasoning_levels`.

The capability map is `model-options.json`, beside this file. Model names live
there because they are volatile data, not durable guidance. Update that map
when providers ship or retire models; do not add another provider section here.
Done when `spend models` returns at least one exact live slug for the intended
rung or archetype.

## The table

| Archetype | What it does | How it fails | Rung | Escalate when |
|---|---|---|---|---|
| **Implementer** | writes the change for one scoped item | scope creep into neighbouring items; edits a generated file instead of its source | economy / default effort | use or escalate to advanced when the change spans subsystems, or a first attempt came back with the scope wrong |
| **Analyst** | traces behaviour, enumerates cases, builds an argument | confident narrative resting on an unverified premise | economy / default effort | use or escalate to advanced when the argument is many hops deep, a premise is disputed, or a prior pass was refuted |
| **Premise auditor** | takes a claim plus its evidence and says whether it holds | agrees with you, which is the one thing it exists not to do | economy / default effort | never — capability is not what you are buying. See below |
| **Verifier** | runs the suite, the build, the assertions; reports numbers | reports a green that could not have gone red | economy / one below default | escalate to advanced when the guard cannot be made to go red and nobody knows why |
| **Verifier, low-risk** | re-runs a check whose pass/fail is mechanical and trivially re-checkable at intake | same, but it is caught at intake | minimal / lowest effort | any doubt at all — then it is the row above |
| **Doc writer** | reports, review docs, structured artifacts | narrates the journey instead of the result | minimal / lowest effort | rarely — prefer a better outline over more thinking |
| **Inventory / cleanup** | disk audits, mechanical sweeps, resource reclamation | deletes by glob; deletes something still in use | minimal / lowest effort | never; if it needs thought it is not this archetype |
| **Contrasting opinion** | a second read from a different *model family* | agrees for the same wrong reason | any rung, different family | — |

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

Never start at **frontier**. No row above begins there. Reserve the top of the
dial for work the human has explicitly asked for at that level, or for an
escalation you can justify from something you observed.

## Contrast is a family, not a provider

A bridged provider hosting the same underlying model family is a billing path,
not an independent opinion. Genuine contrast means a different model family. This
matters most for the premise auditor: an auditor that shares your model's
training and your context's framing can agree with you for exactly the reason you
are wrong.

For the premise audit specifically, **capability is not the lever** — independence
is. The economy rung is right, and a different family is worth more than a higher
rung.
