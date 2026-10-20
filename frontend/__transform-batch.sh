#!/usr/bin/env bash
# Transform a batch of frontend unit test files away from module mocking.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1
FILES=("$@")
for f in "${FILES[@]}"; do
  f_abs=$(realpath "$f")
  out=$(node __transform-nmm.mjs "$f_abs" --apply 2>&1)
  status=$?
  if [ $status -ne 0 ]; then
    echo "=== $f FAILED (exit $status)"
    echo "$out"
  elif echo "$out" | grep -q '^MANUAL:'; then
    echo "=== $f"
    echo "$out" | sed -n '/^MANUAL:/,$p'
  fi
done
