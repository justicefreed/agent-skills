# browser-verification — design record

**Problem.** Agents verifying front-end work reach for the installed Google Chrome
(`Google Chrome --headless --dump-dom`, `--screenshot`, `open -a "Google Chrome"`). On a Mac with
the managed Chrome policy `DefaultBrowserSettingEnabled = 1`, every such launch makes Chrome call
the macOS set-default-browser API and the user gets a "change your default browser?" dialog. No
Chrome flag or profile pref stops it; the policy path runs before any of them and ignores
headless mode. Root-cause trace with Chromium source references:
`plugins/browser-verification/skills/headless-browser/references/google-chrome-policy-prompt.md`.

**Shape.** One plugin, three layers that fail independently:

1. **A convenient path** — `skills/headless-browser/scripts/headless-browser.sh` runs
   chrome-headless-shell (or Chrome for Testing) from the puppeteer cache, installing on first
   use. Neither build reads the `com.google.Chrome` policy domain.
2. **A written rule** — the `headless-browser` skill, model-invoked, whose description triggers
   on the exact commands agents were typing. It also routes to Paseo's `browser_*` tools when
   they are present.
3. **A mechanical stop** — `hooks/no-google-chrome.sh`, a PreToolUse(Bash) hook that denies
   commands naming the Chrome binary or `open -a "Google Chrome"`, with a reason that names the
   replacement. It auto-detects the managed plist and is a no-op on other machines, so shipping
   it enabled is safe.

**Opt-in, two install routes.**

- `claude plugin install browser-verification@justicefreed`: skill and hook arrive together;
  `claude plugin disable browser-verification@justicefreed` removes both.
- `scripts/link-skills.sh` links only the skill. `scripts/chrome-guard-hook.sh enable|disable|status`
  adds or removes the hook entry in `~/.claude/settings.json` (or a project's, with `--project`),
  touching nothing else in the file. `NO_GOOGLE_CHROME_HOOK=off|always|auto` overrides at runtime.

**Not done, deliberately.** The hook is a string match; a path assembled from variables slips
past it. Tightening that means parsing shell, which is not worth it — the skill carries the rule
and the hook catches the common case. The durable fix is administrative: IT unsets the policy.

**Verified 2026-09-09.** chrome-headless-shell 152 dumps a DOM sentinel and exits in ~2 s with
the temp profile removed; the hook denied 7 launch variants and allowed 5 benign commands
including a `grep "Google Chrome"`; Paseo browser tools enable with `paseo reload` and no restart.
