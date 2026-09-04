# agent-skills

Justice Reed's agent skills, structured as a Claude Code plugin marketplace and kept portable to
other harnesses (Codex, Cursor) where the harness allows it.

## Layout

```
.claude-plugin/marketplace.json     # the marketplace index; one entry per plugin
plugins/<plugin>/
  .claude-plugin/plugin.json        # manifest; `skills` is an explicit SHIP LIST, not a glob
  skills/<skill>/SKILL.md
  skills/<skill>/references/        # skill-local, so it is portable across harnesses
  skills/<skill>/assets/            # templates the skill writes into a target repo
  skills/<skill>/scripts/           # bundled tooling
in-progress/<skill>/                # version-controlled, absent from every manifest
docs/                               # design records, one per plugin
```

**One plugin per cohesive idea.** Skills that share a `references/` corpus, or that would always be
enabled together, belong in the same plugin — `${CLAUDE_PLUGIN_ROOT}` resolves per-plugin, so
cross-plugin sharing is not clean. Unrelated ideas get their own plugin; that is the whole reason
for this layout.

**`plugin.json`'s `skills` array is a ship list.** A skill on disk but absent from the array is not
installed. That is the staging mechanism: work in `in-progress/`, promote by moving it under a
plugin *and* adding the path.

## Skill conventions

- **Model-invoked** (no `disable-model-invocation`) only when the agent must reach the skill on its
  own or another skill must reach it. Its `description` sits in context every turn, so it carries
  triggers and nothing else. Otherwise make it user-invoked and pay no context load.
- **`SKILL.md` stays lean** — target 1,500–2,000 words. Detail goes to `references/`, loaded on
  demand. Information lives in `SKILL.md` *or* a reference file, never both.
- **Every step ends on a checkable completion criterion.** "Done when X" that the agent can actually
  evaluate — a vague criterion invites premature completion.
- **Reference, do not restate.** If another skill, a vendor doc, or a target repo's own file owns a
  fact, point at it. Duplicated prose goes stale exactly when it matters, and it costs output tokens
  every time it is reproduced.

## Portability

`AGENTS.md` is a symlink to this file, for harnesses that read `AGENTS.md`. Keep skill assets under
the skill directory and reference them relatively; `${CLAUDE_PLUGIN_ROOT}` is Claude Code-specific
and must not appear in a path a non-Claude harness has to resolve. Where a path genuinely differs by
harness, put the resolution table in a reference file rather than in `SKILL.md`.

Run `scripts/link-skills.sh` to link every shipped skill into `~/.claude/skills` and
`~/.agents/skills`. Entries are symlinks into this repo, so `git pull` keeps them current; re-run
after adding, renaming or removing a skill.

## Validating

```bash
claude plugin validate . --strict          # after touching either manifest
```

Keep `plugin.json`'s `version` meaningful — Claude Code uses it to decide when installed users see
an update.
