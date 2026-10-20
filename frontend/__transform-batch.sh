#!/usr/bin/env bash
# Transform a batch of frontend unit test files away from module mocking.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
FILES=("$@")
for f in "${FILES[@]}"; do
  out=$(node __transform-nmm.mjs "$f" --apply 2>&1)
  if echo "$out" | grep -q '^MANUAL:'; then
    echo "=== $f"
    echo "$out" | sed -n '/^MANUAL:/,$p'
  fi
done
