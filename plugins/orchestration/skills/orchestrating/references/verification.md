# Verification — checks that cannot fail

Nearly every real analytical error in the program this skill came from was **a check that could not
fail**. Not a wrong answer — a *question that had only one possible outcome*, reported as
confirmation. An unfalsifiable check is worse than no check: no check leaves you uncertain, while an
unfalsifiable one manufactures confidence.

The one habit that pays for all of this:

> **Make the guard go red on demand before believing it green.**

A green run is worth something only if you have seen the same machinery produce red. When a landing
reddens twice on the way to passing, the pass means something; when it is green on the first attempt
and was never seen otherwise, you have learned almost nothing.

## The catalog

Each is a shape, with the instance that produced it and the remedy.

### 1. The empty-set pass

An assertion over nothing succeeds. A structural probe that cannot locate its target does not fail —
it passes **against nothing**. An absence-assertion (`X does not appear in this region`) evaluated
over an empty region is vacuously true, and goes green on the very change it was written to catch.

*Remedy:* assert the subject was **found** before asserting anything about it. In a negative control,
**count the assertion flips** — don't just check that red appears somewhere. A guard whose flip count
doesn't change when you break the thing is not guarding.

### 2. The absent-subject green

A test suite run in a tree that does not contain the change under test is **always** green. So is a
build of a configuration the change never reaches, and a probe of a code path compiled out.

*Remedy:* every reported number states **which tree, branch, or configuration it came from, and
whether that context could have gone red.** A number from a tree structurally incapable of failing is
not a weak signal, it is no signal — and quoting it as a gate is a false green.

### 3. The always-succeeds operation

Some operations cannot fail and therefore certify nothing. Staging every change succeeds regardless
of who else wrote to the tree — which is how it swept a running worker's unstaged work into an
unrelated commit, twice.

*Remedy:* ask what input would make this operation fail. If none exists, it is not a check, and you
need a different one.

### 4. The correlate proxy

Proving X by measuring Y, because Y usually tracks X. Equal output sizes do **not** prove a stale
build: a genuine change has come out byte-identical in size. Nor does a size delta prove which
component grew.

*Remedy:* measure the thing you are claiming. Use a content hash to answer "did this actually
rebuild"; attribute a change using the authoritative breakdown rather than a filtered listing that
silently omits whole categories. Where a proxy is unavoidable, say that it is one.

### 5. The empty-comparison

Two empty values are equal, so a comparison whose *inputs* silently failed reports SAME. A shell that
reparses an argument can make a command return empty; every comparison downstream then agrees.

*Remedy:* assert non-emptiness of both operands **before** comparing. Do consequential comparisons in
a language with real assertions rather than in shell string equality, and be aware that shells differ
— word-splitting and history expansion are not portable between them.

### 6. Reading instead of executing

Static review substituted for the real gate. Reading a dead code branch found one of four compile
errors in it; the compiler found four.

*Remedy:* run the actual gate. If a branch has never been compiled, compiling it *is* the check.

### 7. The unscoped pattern match

A whole-file token count cannot localise anything, and it collides with prose: a comment naming a
symbol trips a grep that was asserting about code. Line-number citations rot the moment anything
above them shifts.

*Remedy:* scope structural assertions to a function body or a declaration, not a file. Locate by
**content**, never by line number, and expect any citation you write to drift.

### 8. The self-satisfied precondition

A gate whose pattern matches the checker itself, or matches stale artifacts that never clear, either
never opens or opens while work is still running.

*Remedy:* verify the gate's pattern against a known-busy state **and** a known-idle state before
trusting it.

## Applying it at intake

For every report:

1. **Read the falsification line.** What would have made this red, and was it observed red? *"I could
   not make it fail"* is itself the finding — surface it rather than letting it read as success.
2. **Check provenance.** Where did each number come from, and could that context have failed?
3. **Escalate to independent verification** when *both*: the same agent authored the change **and**
   its check — a shared blind spot — **and** the change is hard to reverse. That is narrower and more
   checkable than "important."
4. **Distinguish** *wrong* from *unverified* from *stylistically different*. Only the first two are
   findings.

## The orchestration layer is not exempt

The same shapes appear in coordination itself, and are easier to miss there because the tooling
reports success:

- A destructive interruption reports **"done"** while having abandoned most of a task. Only an
  external progress artifact reveals it.
- A lost send race is **indistinguishable from a delivery** unless you verify the turn that started
  is yours.
- A syntax check passes a script that uses a builtin the target shell does not have.
- A recorded roster describes intent, not execution; treating it as liveness is the same error as
  trusting an absent notification.

When you add a guard to this system, break it on purpose first.
