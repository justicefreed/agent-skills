# Rungs — which work sits where, and what earns an escalation

Both columns are **relative to the provider**, never absolute model names. Ask
the substrate for its live model list at spawn time and map the rung then.
A model name written into a document is wrong the next time the provider ships.

Effort, where the provider exposes a separate dial: **default** (what the model
reports as its own default), **one below default**, **lowest**, and — escalation
only — **above default**. Some providers expose no such dial, and there the
archetype's "model and effort" collapses to model alone.

## The table

| Archetype | What it does | How it fails | Rung | Escalate when |
|---|---|---|---|---|
| **Implementer** | writes the change for one scoped item | scope creep into neighbouring items; edits a generated file instead of its source | economy / default effort | the change spans subsystems, or a first attempt came back with the scope wrong |
| **Analyst** | traces behaviour, enumerates cases, builds an argument | confident narrative resting on an unverified premise | economy / default effort | the argument is many hops deep, a premise is disputed, or a prior pass was refuted |
| **Premise auditor** | takes a claim plus its evidence and says whether it holds | agrees with you, which is the one thing it exists not to do | economy / default effort | never — capability is not what you are buying. See below |
| **Verifier** | runs the suite, the build, the assertions; reports numbers | reports a green that could not have gone red | economy / one below default | the guard cannot be made to go red and nobody knows why |
| **Verifier, low-risk** | re-runs a check whose pass/fail is mechanical and trivially re-checkable at intake | same, but it is caught at intake | minimal / lowest effort | any doubt at all — then it is the row above |
| **Doc writer** | reports, review docs, structured artifacts | narrates the journey instead of the result | minimal / lowest effort | rarely — prefer a better outline over more thinking |
| **Inventory / cleanup** | disk audits, mechanical sweeps, resource reclamation | deletes by glob; deletes something still in use | minimal / lowest effort | never; if it needs thought it is not this archetype |
| **Contrasting opinion** | a second read from a different *model family* | agrees for the same wrong reason | any rung, different family | — |

## Why the anchor is `economy`

An earlier version of this table anchored at the provider's `default`, arguing
that a more capable model is cheap relative to a wrong answer. Two things were
wrong with that.

**The referent drifted.** `default` names whichever model the provider currently
selects, and that moved up a tier while the rung wording stayed put. Nothing
looked stale. The sentence that once meant a Sonnet-class model came to mean an
Opus-class one, and the bill recorded it: **6,509 subagent calls at $616 where
the same tokens one rung down cost $246** — 39% of a four-day bill.

**The asymmetry was assumed, not measured.** A wrong answer is expensive only if
it is not caught. Of 31 subagent tasks measured at the higher anchor, **28
finished correctly on the first attempt and only 3 needed rework** — so the rung
above was paying a 2.5x premium to avoid an outcome that occurred three times.

The same argument now applies one rung lower and is *untested there*, which is
exactly why escalation should be recorded. An archetype that escalates every time
is a wrong default, not a run of bad luck: fix its row rather than escalating it
forever.

## Escalating

Escalate from an observed signal, never from a feeling that the task looks hard.
A running subagent's model can usually be changed without restating its
instructions, so starting at the table's rung costs one message when it turns out
to be wrong — and nothing at all the 28 times out of 31 it does not.

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
