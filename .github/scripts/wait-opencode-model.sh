#!/usr/bin/env bash
# OpenCode 2 refreshes its bundled catalog asynchronously on a cold runner.
# Poll for the exact selected model before inference; never change providers/models.
set -Eeuo pipefail
model="${1:?exact provider/model selector required}"
binary="${OPENCODE_BIN:-opencode}"
deadline=$((SECONDS + 45))
while (( SECONDS < deadline )); do
  remaining=$((deadline - SECONDS))
  request_timeout=$((remaining < 10 ? remaining : 10))
  if catalog="$(timeout --signal=TERM --kill-after=1s "${request_timeout}s" \
    "$binary" models --standalone)" && grep -Fxq -- "$model" <<< "$catalog"; then
    printf 'OpenCode catalog ready for %s\n' "$model"
    exit 0
  fi
  if (( SECONDS < deadline )); then
    echo "Waiting for OpenCode catalog to include $model" >&2
    sleep 1
  fi
done
printf 'OpenCode catalog did not expose %s within 45 seconds\n' "$model" >&2
exit 1
