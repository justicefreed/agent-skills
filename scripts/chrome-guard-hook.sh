#!/usr/bin/env bash
# Enable, disable, or inspect the browser-verification guard hook for installs that use
# scripts/link-skills.sh instead of `claude plugin install` (plugin installs carry the hook in
# hooks/hooks.json automatically; disable those with `claude plugin disable browser-verification@justicefreed`).
#
#   scripts/chrome-guard-hook.sh enable  [--project DIR]   # add a PreToolUse(Bash) entry
#   scripts/chrome-guard-hook.sh disable [--project DIR]   # remove every entry we added
#   scripts/chrome-guard-hook.sh status  [--project DIR]
#
# Default target is ~/.claude/settings.json (user scope: the policy is machine-wide). --project
# targets DIR/.claude/settings.json instead. Idempotent; other hooks in the file are untouched.
# The hook itself auto-detects the managed policy and is a no-op elsewhere; set
# NO_GOOGLE_CHROME_HOOK=off in the environment to silence it without uninstalling.
set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$REPO/plugins/browser-verification/hooks/no-google-chrome.sh"
ACTION="${1:-status}"; shift || true
TARGET="$HOME/.claude/settings.json"
if [ "${1:-}" = "--project" ]; then
  [ -n "${2:-}" ] || { echo "--project needs a directory" >&2; exit 64; }
  TARGET="$(cd "$2" && pwd)/.claude/settings.json"
  shift 2
fi
case "$ACTION" in enable|disable|status) ;; *) echo "usage: $0 enable|disable|status [--project DIR]" >&2; exit 64 ;; esac
[ -x "$HOOK" ] || { echo "hook script missing or not executable: $HOOK" >&2; exit 66; }

python3 - "$ACTION" "$TARGET" "$HOOK" <<'PY'
import json, os, sys
action, target, hook = sys.argv[1:4]
MARK = "no-google-chrome.sh"

data = {}
if os.path.exists(target):
    with open(target) as fh:
        text = fh.read().strip()
    data = json.loads(text) if text else {}

pre = data.get("hooks", {}).get("PreToolUse", [])
ours = [g for g in pre if any(MARK in (h.get("command") or "") for h in g.get("hooks", []))]

if action == "status":
    print(f"{target}: {'ENABLED' if ours else 'not enabled'}")
    for g in ours:
        for h in g.get("hooks", []):
            print("  " + h.get("command", ""))
    sys.exit(0)

if action == "enable":
    if ours:
        print(f"already enabled in {target}")
        sys.exit(0)
    entry = {"matcher": "Bash",
             "hooks": [{"type": "command", "command": f'"{hook}"', "timeout": 5}]}
    data.setdefault("hooks", {}).setdefault("PreToolUse", []).append(entry)
    verb = "enabled"
else:
    if not ours:
        print(f"not enabled in {target}; nothing to do")
        sys.exit(0)
    kept = [g for g in pre if g not in ours]
    if kept:
        data["hooks"]["PreToolUse"] = kept
    else:
        del data["hooks"]["PreToolUse"]
        if not data["hooks"]:
            del data["hooks"]
    verb = "disabled"

os.makedirs(os.path.dirname(target), exist_ok=True)
tmp = target + ".tmp"
with open(tmp, "w") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
os.replace(tmp, target)
print(f"{verb} guard hook in {target}")
if action == "enable":
    print("Claude Code re-reads settings, so running sessions pick it up on their next Bash call; "
          "set NO_GOOGLE_CHROME_HOOK=off to silence without disabling")
PY
