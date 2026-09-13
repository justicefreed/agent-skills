#!/bin/sh
# headless-browser.sh — a headless browser for front-end checks that never launches the user's
# installed Google Chrome.
#
# Why: some Macs carry a managed Chrome policy (DefaultBrowserSettingEnabled = 1 in
# /Library/Managed Preferences/com.google.chrome.plist). Chromium applies it on every browser
# start — headless included, regardless of --no-default-browser-check — by calling the macOS
# set-default-browser API, which pops a "change your default browser?" dialog at the user.
# chrome-headless-shell and Chrome for Testing are separate builds under a different bundle id,
# so they never read that policy. See ../references/google-chrome-policy-prompt.md.
#
# Usage:
#   headless-browser.sh [--engine shell|cft] <chrome flags...> <url>
#   headless-browser.sh --dump-dom http://127.0.0.1:4311/driver.html
#   headless-browser.sh --screenshot=/tmp/x.png --window-size=1400,1300 http://127.0.0.1:4311/
#
# --engine shell (default): chrome-headless-shell. Exits on its own after --dump-dom/--screenshot.
# --engine cft:             Chrome for Testing (new headless). Only when shell lacks a feature.
#                           Known: new headless may not exit after --dump-dom/--screenshot on
#                           macOS; the watchdog below caps the run.
# A private --user-data-dir is created and removed unless you pass your own.
# Binaries live in ${PUPPETEER_CACHE_DIR:-~/.cache/puppeteer}; a missing one is installed with
# `npx @puppeteer/browsers install <pkg>@stable` (needs node and network once).
# Run time is capped at ${HEADLESS_BROWSER_TIMEOUT_SECS:-30}s. On timeout, ctrl-C, or normal exit,
# the browser's process group/tree is killed by pid — never by name/pattern.
set -eu

CACHE="${PUPPETEER_CACHE_DIR:-$HOME/.cache/puppeteer}"
TIMEOUT="${HEADLESS_BROWSER_TIMEOUT_SECS:-30}"
ENGINE=shell
if [ "${1:-}" = "--engine" ]; then ENGINE=${2:?--engine needs shell|cft}; shift 2; fi
case $ENGINE in
  shell) PKG=chrome-headless-shell ;;
  cft)   PKG=chrome ;;
  *) echo "headless-browser: unknown engine '$ENGINE' (use shell or cft)" >&2; exit 64 ;;
esac

find_bin() {
  case $ENGINE in
    shell) find "$CACHE/chrome-headless-shell" -type f -name chrome-headless-shell 2>/dev/null ;;
    cft)   find "$CACHE/chrome" -type f \( -name 'Google Chrome for Testing' -path '*/Contents/MacOS/*' -o -name chrome -path '*/chrome-linux64/*' \) 2>/dev/null ;;
  esac | sort | tail -1
}

BIN=$(find_bin)
if [ -z "$BIN" ]; then
  echo "headless-browser: installing $PKG@stable into $CACHE" >&2
  npx --yes @puppeteer/browsers install "$PKG@stable" --path "$CACHE" >&2
  BIN=$(find_bin)
fi
[ -n "$BIN" ] || { echo "headless-browser: could not find or install $PKG" >&2; exit 69; }
case $BIN in
  */Google\ Chrome.app/*) echo "headless-browser: refusing to run Google Chrome.app" >&2; exit 70 ;;
esac

PROFILE=
PROFILE_OWNED=
for a in "$@"; do case $a in --user-data-dir=*) PROFILE=given ;; esac; done
if [ -z "$PROFILE" ]; then
  PROFILE=$(mktemp -d "${TMPDIR:-/tmp}/headless-browser.XXXXXX")
  PROFILE_OWNED=1
  set -- "--user-data-dir=$PROFILE" "$@"
fi

# Prints $1 and every live descendant pid, walked by pid via `pgrep -P` — never by name, since a
# pattern kill could hit an unrelated chrome process on this machine.
collect_tree() {
  pending=$1
  all=
  while [ -n "$pending" ]; do
    next=
    for pid in $pending; do
      all="$all $pid"
      children=$(pgrep -P "$pid" 2>/dev/null || :)
      next="$next $children"
    done
    pending=$next
  done
  echo "$all"
}

BROWSER_PID=
BROWSER_PGID=
BROWSER_WAITED=
TIMER_PID=
CLEANED=
cleanup() {
  [ -z "$CLEANED" ] || return
  CLEANED=1
  trap - EXIT
  if [ -n "$TIMER_PID" ]; then
    kill "$TIMER_PID" 2>/dev/null || :
    wait "$TIMER_PID" 2>/dev/null || :
  fi
  if [ -n "$BROWSER_PID" ]; then
    tree=
    if [ -z "$BROWSER_WAITED" ]; then tree=$(collect_tree "$BROWSER_PID"); fi
    if [ -n "$BROWSER_PGID" ]; then kill -TERM "-$BROWSER_PGID" 2>/dev/null || :; fi
    for pid in $tree; do kill -TERM "$pid" 2>/dev/null || :; done
    sleep 1
    # Walk again before KILL so TERM-trapping children cannot keep inherited stdout/stderr open.
    if [ -z "$BROWSER_WAITED" ]; then tree="$tree $(collect_tree "$BROWSER_PID")"; fi
    if [ -n "$BROWSER_PGID" ]; then kill -KILL "-$BROWSER_PGID" 2>/dev/null || :; fi
    for pid in $tree; do kill -KILL "$pid" 2>/dev/null || :; done
    if [ -z "$BROWSER_WAITED" ]; then wait "$BROWSER_PID" 2>/dev/null || :; fi
    for _ in 1 2 3 4 5; do
      live=
      for pid in $tree; do kill -0 "$pid" 2>/dev/null && live=1; done
      [ -n "$live" ] || break
      sleep 0.2
    done
  fi
  if [ -n "$PROFILE_OWNED" ]; then rm -rf "$PROFILE"; fi
}

on_int() {
  trap - INT TERM
  cleanup
  exit 130
}

on_term() {
  trap - INT TERM
  cleanup
  exit 143
}

SCRIPT_PGID=$(ps -o pgid= -p "$$" 2>/dev/null | tr -d ' ' || :)

if command -v perl >/dev/null 2>&1; then
  perl -MPOSIX=setsid -e 'setsid or die "setsid: $!"; exec @ARGV or die "exec: $!"' \
    "$BIN" --headless --disable-gpu --hide-scrollbars --no-first-run --no-default-browser-check "$@" &
else
  "$BIN" --headless --disable-gpu --hide-scrollbars --no-first-run --no-default-browser-check "$@" &
fi
BROWSER_PID=$!
BROWSER_PGID=$(ps -o pgid= -p "$BROWSER_PID" 2>/dev/null | tr -d ' ' || :)
if [ "$BROWSER_PGID" = "$SCRIPT_PGID" ]; then BROWSER_PGID=; fi
trap cleanup EXIT
trap on_int INT
trap on_term TERM
# Signals the script itself, not $BROWSER_PID directly: killing the browser root here would let
# its children get reparented before cleanup's kill_tree walk ever looks for them.
(
  sleep_pid=
  trap '[ -z "$sleep_pid" ] || kill "$sleep_pid" 2>/dev/null; exit 0' INT TERM
  sleep "$TIMEOUT" &
  sleep_pid=$!
  wait "$sleep_pid" || exit 0
  kill -TERM "$$" 2>/dev/null
) >/dev/null 2>&1 &
TIMER_PID=$!

STATUS=0
wait "$BROWSER_PID" 2>/dev/null || STATUS=$?
BROWSER_WAITED=1
cleanup
exit "$STATUS"
