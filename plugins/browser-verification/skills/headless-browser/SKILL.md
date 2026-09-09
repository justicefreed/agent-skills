---
name: headless-browser
description: Check front-end work in a real browser from the CLI — DOM dump, screenshot, JS probe — without launching the user's installed Google Chrome. Use before running Google Chrome --headless, --dump-dom, --screenshot, or `open -a "Google Chrome"`, when verifying a dashboard, page render, or layout, or when a hook has refused a Chrome launch.
---

# Headless browser checks

Never launch `/Applications/Google Chrome.app`, headless or not. On Macs with a managed Chrome
policy (`DefaultBrowserSettingEnabled`) every launch calls the macOS set-default-browser API and
pops a dialog at the user, and no Chrome flag suppresses it. The mechanism, the evidence, and how
to check a machine are in [references/google-chrome-policy-prompt.md](references/google-chrome-policy-prompt.md).

## 1. Pick the tool

- **Paseo `browser_*` tools are in your tool list** (`browser_new_tab`, `browser_snapshot`, ...):
  use them for anything interactive — clicking through a flow, reading an accessibility tree,
  viewport resizing, console logs. The user can watch the tab. Details and limits:
  [references/paseo-browser.md](references/paseo-browser.md).
- **Otherwise, or for a scripted probe** (dump a sentinel, diff a screenshot, measure text):
  `scripts/headless-browser.sh`, next to this file. It runs chrome-headless-shell from the
  puppeteer cache and installs it on first use.

Done when: you know which of the two you are using and have not typed a Google Chrome.app path.

## 2. Run a scripted probe

```bash
SKILL_DIR=<directory holding this SKILL.md>
"$SKILL_DIR/scripts/headless-browser.sh" --dump-dom http://127.0.0.1:4311/ | grep -o 'SENTINEL.*END'
"$SKILL_DIR/scripts/headless-browser.sh" --screenshot=/tmp/page.png --window-size=1400,1300 http://127.0.0.1:4311/
```

- Chrome flags pass straight through. `--virtual-time-budget=<ms>` advances timers deterministically.
- A private profile dir is created and removed per run. Pass your own `--user-data-dir=` to keep one.
- Have the page write a single sentinel-delimited line into the DOM and grep for it. Keep the
  whole DOM out of the transcript.
- A page holding an open connection (SSE, WebSocket) never goes idle. Probe a driver page that
  loads the real page in an iframe, or serve a copy without the stream.
- `requestAnimationFrame` may never fire headless on macOS. Await `setTimeout(r, 0)` instead.
- `--engine cft` switches to Chrome for Testing when new-headless features are needed. It may not
  exit after `--dump-dom`; run it in the background, `sleep`, then kill its pid.
- To stop a run, kill its pid or match its own `--user-data-dir`. Never `pkill -f` a generic
  Chrome pattern; sibling agents run their own.

Done when: the probe's output is one short line or one image, the process has exited, and no
temp profile of yours remains.

## 3. If a hook refused your command

The `browser-verification` plugin ships a PreToolUse guard that denies Bash commands naming the
Google Chrome.app binary or `open -a "Google Chrome"`. It is a no-op on machines without the
policy. Rewrite the command with section 2; do not work around the guard by assembling the path
from variables.

Done when: the same check runs through `headless-browser.sh` or Paseo browser tools.
