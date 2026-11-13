You are summarising an ORCHESTRATOR mid-program. Its lanes keep running while it compacts, and it resumes from this summary plus `orch resume` (roster, inbox, plan path), which is re-read from disk. Do not restate what `orch resume` prints; record what only this conversation knows.

Write these sections, in this order:

## Do first
A numbered list the resumed orchestrator works through before anything else. Include every item below that applies, most urgent first:
- a ruling or decision the human made that is not yet written into the plan document or tracker: quote it, name the file it belongs in;
- a question that was put to the human and is still unanswered, with its options verbatim;
- a lane report that was received but not yet acted on (landed, reviewed, closed, or followed up);
- anything you said you would come back to or double-check.
If none apply, write "nothing pending".

## In flight
One line per live lane: entry id, agent id, branch or worktree, what it is doing, what you are waiting for from it.

## Rulings and constraints
Human rulings and standing instructions for the rest of the program, quoted where wording matters. Approaches that were tried and abandoned, one line each: `X was tried; fails because Z. Chose Y.` Never drop one silently.

## Next up
The next items to dispatch or decide once "Do first" is clear, with the reason they are next.

## Artifacts
Paths, commit SHAs, PR numbers and test names produced or relied on this session.

Drop: tool output whose conclusion is recorded above, deliberation whose result is in a commit or file, superseded plans, and narration of what was about to happen.
