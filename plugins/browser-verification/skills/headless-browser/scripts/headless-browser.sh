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
#                           macOS. Run it in the background, sleep, then kill its pid.
# A private --user-data-dir is created and removed unless you pass your own.
# Binaries live in ${PUPPETEER_CACHE_DIR:-~/.cache/puppeteer}; a missing one is installed with
# `npx @puppeteer/browsers install <pkg>@stable` (needs node and network once).
set -eu

CACHE="${PUPPETEER_CACHE_DIR:-$HOME/.cache/puppeteer}"
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
for a in "$@"; do case $a in --user-data-dir=*) PROFILE=given ;; esac; done
if [ -z "$PROFILE" ]; then
  PROFILE=$(mktemp -d "${TMPDIR:-/tmp}/headless-browser.XXXXXX")
  trap 'rm -rf "$PROFILE"' EXIT INT TERM
  set -- "--user-data-dir=$PROFILE" "$@"
fi

"$BIN" --headless --disable-gpu --hide-scrollbars --no-first-run --no-default-browser-check "$@"
