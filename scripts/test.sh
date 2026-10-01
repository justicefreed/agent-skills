#!/usr/bin/env bash
# Run every plugin test suite in parallel; print only failing suites' output.
#
# The interpreter is the one the hooks run (`spend.py`'s HOOK_PY), so a suite
# that passes here passes in production -- including on /usr/bin/python3's 3.9.
# It is resolved to a real binary: naming `python3` through a pyenv shim costs
# 0.5-2.7s per launch. Suites are independent -- each makes its own temp repos
# and agent dirs -- so they run concurrently.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"

PY="${TEST_PYTHON:-}"
[ -x "$PY" ] || PY=/usr/bin/python3
[ -x "$PY" ] || PY=python3

out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
pids=()
suites=()
for t in "$REPO"/plugins/*/scripts/test_*.py "$REPO"/plugins/*/skills/*/scripts/test_*.py; do
  [ -f "$t" ] || continue
  log="$out/${#suites[@]}.log"
  "$PY" "$t" >"$log" 2>&1 &
  pids+=($!)
  suites+=("$t")
done

failed=0
for i in "${!pids[@]}"; do
  name="${suites[$i]#"$REPO"/}"
  if wait "${pids[$i]}"; then
    echo "ok    $name"
  else
    failed=$((failed + 1))
    echo "FAIL  $name"
    grep -v ' ok$' "$out/$i.log" | sed 's/^/      /'
  fi
done

[ "$failed" -eq 0 ] && echo "all suites pass" || echo "$failed suite(s) failed"
exit "$((failed > 0))"
