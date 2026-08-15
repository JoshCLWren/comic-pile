#!/usr/bin/env bash
set -Eeuo pipefail

TIMEOUT_SECONDS="${1:?timeout seconds required}"
TITLE="${2:?title required}"
PROMPT="${3:?prompt required}"
LOG_PATH="${4:?log path required}"
RUNTIME_MODEL="${FACTORY_RUNTIME_MODEL:-kilo/kilo-auto/free}"

# This experiment must prove anonymous/free Kilo routing. Do not inherit an
# account token or local Kilo state that could make a paid route available.
unset KILO_API_KEY KILOCODE_API_KEY
export XDG_CONFIG_HOME="${RUNNER_TEMP:?RUNNER_TEMP is required}/kilo-config"
export XDG_DATA_HOME="$RUNNER_TEMP/kilo-data"
export XDG_CACHE_HOME="$RUNNER_TEMP/kilo-cache"
mkdir -p "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_CACHE_HOME"

set +e
timeout --signal=TERM --kill-after=30s "${TIMEOUT_SECONDS}s" \
  kilo run -m "$RUNTIME_MODEL" --auto --format json --dir "${GITHUB_WORKSPACE:?GITHUB_WORKSPACE is required}" \
  --title "$TITLE" "$PROMPT" \
  2>&1 | tee "$LOG_PATH"
status=${PIPESTATUS[0]}
set -e

if (( status != 0 )); then
  exit "$status"
fi

step_count="$(jq -R -s '[split("\n")[] | fromjson? | select(.type == "step_finish")] | length' "$LOG_PATH")"
if [[ "$step_count" == "0" ]]; then
  echo 'Kilo run returned success without observable step_finish telemetry' >&2
  exit 85
fi

if jq -R -e -s 'any(split("\n")[] | fromjson? | select(.type == "step_finish"); ((.part.cost // 0) | tonumber) > 0)' "$LOG_PATH" >/dev/null; then
  echo 'Kilo Auto Free reported non-zero cost; refusing any paid execution path' >&2
  exit 86
fi

telemetry="$(jq -R -r '
  fromjson?
  | select(.type == "step_finish")
  | [
      (.part.model.providerID // "unreported"),
      (.part.model.modelID // "unreported"),
      (.part.generationID // "unreported"),
      ((.part.cost // "unreported") | tostring),
      ((.part.time.elapsed // "unreported") | tostring)
    ]
  | @tsv
' "$LOG_PATH" | tail -n 1)"

if [[ -n "$telemetry" ]]; then
  IFS=$'\t' read -r provider model generation cost elapsed <<< "$telemetry"
  printf 'Kilo telemetry: requested_route=kilo-auto/free runtime_model=%s provider_id=%s resolved_model=%s generation_id=%s cost=%s elapsed_ms=%s\n' \
    "$RUNTIME_MODEL" "$provider" "$model" "$generation" "$cost" "$elapsed"
else
  echo 'Kilo telemetry: requested_route=kilo-auto/free resolved metadata unavailable'
fi
