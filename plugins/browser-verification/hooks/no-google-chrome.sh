#!/bin/sh
# PreToolUse hook (matcher: Bash). Refuses Bash commands that launch the installed Google Chrome
# on a Mac where a managed Chrome policy makes every launch prompt the user.
#
# Why: when /Library/Managed Preferences/com.google.chrome.plist (system or per-user) sets
# DefaultBrowserSettingEnabled = 1, Chromium's BrowserProcessImpl::ApplyDefaultBrowserPolicy runs
# on every start of the Google Chrome app — headless or not, whatever flags are passed — and calls
# the macOS set-default-browser API. macOS answers with a "change your default browser?" dialog.
# No Chrome flag suppresses it. The headless-browser skill's scripts/headless-browser.sh runs
# chrome-headless-shell or Chrome for Testing instead; neither reads that policy.
#
# Activation (NO_GOOGLE_CHROME_HOOK):
#   auto (default)  deny only when the managed policy is present on this machine; otherwise no-op.
#   always          deny regardless of policy.
#   off             never deny (temporary escape hatch; the hook stays installed).
#
# Cost: this runs before every Bash call, so the common path is one grep over stdin (a few ms).
# Only commands that mention Chrome pay for the policy lookup and JSON parsing.
#
# Input: PreToolUse JSON on stdin. Output: a deny decision, or nothing. Always drains stdin and
# exits 0 so a hook failure never blocks unrelated commands.

mode=${NO_GOOGLE_CHROME_HOOK:-auto}
input=$(cat)
[ "$mode" = "off" ] && exit 0

# Cheap pre-filter on the raw JSON. A backslash-escaped space arrives as "\\ ", hence .{0,3}.
printf '%s' "$input" | grep -qiE 'Google.{0,3}Chrome|com\.google\.chrome' || exit 0

policy_present() {
  for f in "/Library/Managed Preferences/com.google.chrome.plist" \
           "/Library/Managed Preferences/com.google.Chrome.plist" \
           "/Library/Managed Preferences/${USER:-nobody}/com.google.chrome.plist" \
           "/Library/Managed Preferences/${USER:-nobody}/com.google.Chrome.plist"; do
    [ -f "$f" ] || continue
    v=$(defaults read "${f%.plist}" DefaultBrowserSettingEnabled 2>/dev/null) || continue
    [ "$v" = "1" ] && return 0
  done
  return 1
}
if [ "$mode" != "always" ]; then policy_present || exit 0; fi

# Extract tool_input.command. Prefer fast parsers; a pyenv shim python3 can cost >1 s.
extract() {
  if command -v jq >/dev/null 2>&1; then
    jq -r '.tool_input.command // empty'
  elif [ -x /usr/bin/python3 ]; then
    /usr/bin/python3 -c 'import json,sys
try: sys.stdout.write(str(json.load(sys.stdin).get("tool_input",{}).get("command","")))
except Exception: pass'
  elif command -v node >/dev/null 2>&1; then
    node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{try{process.stdout.write(String(JSON.parse(s).tool_input?.command??""))}catch{}})'
  else
    python3 -c 'import json,sys
try: sys.stdout.write(str(json.load(sys.stdin).get("tool_input",{}).get("command","")))
except Exception: pass'
  fi
}
cmd=$(printf '%s' "$input" | extract 2>/dev/null) || exit 0

# (\\ | ) accepts a plain or backslash-escaped space, so the unquoted form
# /Applications/Google\ Chrome.app/... is caught as well as the quoted one.
pattern='Google(\\ | )Chrome\.app/Contents/MacOS/Google(\\ | )Chrome|open +(-[A-Za-z]+ +)*-a +["'"'"']?Google(\\ | )Chrome|open +(-[A-Za-z]+ +)*-b +["'"'"']?com\.google\.Chrome'
if printf '%s' "$cmd" | grep -qE "$pattern"; then
  cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Do not launch /Applications/Google Chrome.app on this Mac, headless or not. A managed Chrome policy (DefaultBrowserSettingEnabled) makes every launch call the macOS set-default-browser API, which pops a dialog at the user; no Chrome flag suppresses it. Use the headless-browser skill: run its scripts/headless-browser.sh <chrome flags> <url> (chrome-headless-shell by default, --engine cft for Chrome for Testing), or Paseo's browser_* tools when they are available."}}
JSON
fi
exit 0
