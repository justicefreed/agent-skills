# Why launching Google Chrome pops the macOS "default browser" dialog

Diagnosed 2026-09-09 on macOS 26.6 with Google Chrome 153, default browser Arc.

## Mechanism

1. An IT-managed policy file sets `DefaultBrowserSettingEnabled = 1`:
   `/Library/Managed Preferences/com.google.chrome.plist` (root-owned; a per-user copy under
   `/Library/Managed Preferences/<user>/` may exist too).
2. Chromium loads it as a *managed* pref (`components/policy/core/common/policy_loader_mac.mm`,
   keyed by the app's bundle id `com.google.Chrome`).
3. `BrowserProcessImpl::PreMainMessageLoopRun` calls `ApplyDefaultBrowserPolicy()` whenever the
   pref is managed and true (`chrome/browser/browser_process_impl.cc`). That path has no headless
   gate and ignores `--no-default-browser-check`; the `interactive_permitted=false` it sets only
   matters on Windows.
4. `DefaultBrowserWorker::StartSetAsDefault` → `shell_integration::SetAsDefaultBrowser()` →
   `[NSWorkspace setDefaultApplicationAtURL:toOpenURLsWithScheme:@"http"]`
   (`chrome/browser/shell_integration_mac.mm`). macOS presents the confirmation dialog through
   CoreServicesUIAgent. Chrome's own source comments say so.
5. Chrome's in-window infobar path (`ShowDefaultBrowserPrompt`) returns early when the pref is
   managed, so the profile's `check_default_browser = false` and earlier "don't ask again" clicks
   are irrelevant.

Every launch of `Google Chrome.app` therefore prompts once: headless, throwaway
`--user-data-dir`, `--no-first-run`, `--no-default-browser-check` — none of it matters.

## Check a machine

```bash
defaults read "/Library/Managed Preferences/com.google.chrome" DefaultBrowserSettingEnabled 2>/dev/null
defaults read "/Library/Managed Preferences/$USER/com.google.chrome" DefaultBrowserSettingEnabled 2>/dev/null
# 1 → the policy is active. No output → not managed here; the guard hook is a no-op.
```

Current default browser, for context:

```bash
plutil -convert json -o - ~/Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist \
  | python3 -c 'import json,sys; [print(h["LSHandlerRoleAll"]) for h in json.load(sys.stdin)["LSHandlers"] if h.get("LSHandlerURLScheme")=="https"]'
```

## What works

| Option | Why it is immune | Notes |
| --- | --- | --- |
| `chrome-headless-shell` (`npx @puppeteer/browsers install chrome-headless-shell@stable`) | No `chrome/browser` layer at all: no policy loader, no default-browser code | Exits on its own after `--dump-dom`/`--screenshot`. Default engine of `scripts/headless-browser.sh`. |
| Chrome for Testing (`npx @puppeteer/browsers install chrome@stable`) | Bundle id `com.google.chrome.for.testing`; no managed plist under that name | New headless. May hang after `--dump-dom` on macOS. |
| Playwright's bundled Chromium | Bundle id is not `com.google.Chrome` | Not used by these skills, but equally safe. |
| Paseo browser tools | Electron webviews inside Paseo.app; Electron has no Chrome policy layer | See [paseo-browser.md](paseo-browser.md). |

## What does not work

- Any flag on `Google Chrome.app`. The policy path is applied before command-line prompt logic.
- Profile prefs (`check_default_browser`, "don't ask again"). Bypassed when the pref is managed.
- Editing or deleting the managed plist. Root-owned and re-pushed by MDM. The durable fix is to
  ask IT to unset `DefaultBrowserSettingEnabled` for the machine; that also fixes launching Chrome
  by hand.

## The guard hook

`hooks/no-google-chrome.sh` in the plugin denies Bash commands matching the Chrome binary path
(quoted or backslash-escaped) or `open -a "Google Chrome"` / `open -b com.google.Chrome`. It is a
string match: a path assembled from variables slips past it, which is why the rule also lives in
the skill. `NO_GOOGLE_CHROME_HOOK=auto|always|off` controls activation; `auto` (default) checks
for the managed plist and does nothing elsewhere.
