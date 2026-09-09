# Paseo browser tools as the interactive alternative

Paseo can give agents `browser_*` MCP tools that drive tabs hosted by the Paseo desktop app.
The tabs are Electron webviews inside Paseo.app, brokered by the daemon, so Google Chrome.app is
never launched and the managed policy in
[google-chrome-policy-prompt.md](google-chrome-policy-prompt.md) cannot reach them.

Vendor docs own the details; do not restate them here:

- Overview and enablement: https://paseo.sh/docs/browser.md
- Tool reference (`browser_new_tab`, `browser_snapshot`, `browser_click`, `browser_fill`,
  `browser_screenshot`, `browser_logs`, `browser_resize`, ...): https://paseo.sh/docs/browser-tools.md
- When to prefer it over a standalone browser: https://paseo.sh/docs/browser-when.md

## Enable

Off by default, per host. Either in the app (Settings → host → Agents → Browser tools) or in
`~/.paseo/config.json`:

```json
{ "daemon": { "browserTools": { "enabled": true } } }
```

then `paseo reload` (runtime-safe; no daemon restart). Disable by setting it back to `false` and
reloading. Tools are only served while the desktop app is connected.

## Trade-offs against `scripts/headless-browser.sh`

- Paseo wins for interactive verification: accessibility-tree snapshots with element refs,
  real input events, viewport resizing, console and network logs, and the user can watch.
- The wrapper wins for scripted probes and for worktrees where no desktop app is attached:
  dump a sentinel, grep it, exit.
- Paseo tabs share Paseo's logged-in browser profile, including cookies. That is why the feature
  is opt-in; keep it to hosts you trust.
- Both are immune to the Google Chrome policy prompt. Neither needs Google Chrome installed.
