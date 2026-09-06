#!/usr/bin/env bash
# Entry OpenCode smoke plus the TEMPORARY auto/best-free capacity bridge.
#
# Factory 11 run 34029915567 (also F9/10/71): auto/coding:free hung, timeout
# exited 124, and the step aborted before --next-after-smoke-failure. The
# previous smoke_once helper did `set -e` then `return "$status"`, which
# globally re-enabled errexit and killed the step.
#
# Smoke invocations stay guarded with `|| status=$?` so timeout 124 and
# other non-zero statuses reach the existing bridge retry. Errexit stays
# on for later unguarded failures (including $GITHUB_OUTPUT writes).
# Disable the bridge with FACTORY_OMNIROUTE_CAPACITY_BRIDGE=off.

set -Eeuo pipefail

: "${RUNTIME_MODEL:?RUNTIME_MODEL is required}"
: "${LANE_MODEL:?LANE_MODEL is required}"
: "${RUNNER_TEMP:?RUNNER_TEMP is required}"
: "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"

# Primary hangs should fail fast enough that one best-free retry still fits
# the previous 180s single-attempt budget. Override in tests.
PRIMARY_TIMEOUT="${FACTORY_SMOKE_PRIMARY_TIMEOUT_SECONDS:-90}"
BRIDGE_TIMEOUT="${FACTORY_SMOKE_BRIDGE_TIMEOUT_SECONDS:-90}"
KILL_AFTER="${FACTORY_SMOKE_KILL_AFTER_SECONDS:-10}"

SMOKE_LOG="${FACTORY_SMOKE_LOG:-$RUNNER_TEMP/fixed-model-smoke.log}"
SMOKE_DIR="${FACTORY_SMOKE_DIR:-$RUNNER_TEMP/smoke-workspace}"
ROUTE_HELPER="${FACTORY_OMNIROUTE_ROUTE_HELPER:-.github/scripts/factory_omniroute_route.py}"

# Lean smoke workspace: avoid loading repo AGENTS.md / build-agent
# context that blows past free-tier TPM (seen as HTTP 413 ~12k vs 8k).
rm -rf "$SMOKE_DIR"
mkdir -p "$SMOKE_DIR"
git -C "$SMOKE_DIR" init --quiet

smoke_once() {
  local runtime="$1"
  local log_file="$2"
  local timeout_seconds="$3"
  local status=0
  # Caller must use `smoke_once ... || status=$?`. Do not `set +e` globally
  # and do not `set -e` inside this function — the latter persists after
  # return and can abort the caller before the capacity-bridge retry
  # (Factory 11 run 34029915567).
  timeout --signal=TERM --kill-after="${KILL_AFTER}s" "${timeout_seconds}s" \
    opencode run -m "$runtime" --dir "$SMOKE_DIR" \
    --title 'ComicPile fixed-model smoke' \
    'Use a read-only shell tool to run `git status --short`. Do not edit files. After the tool call succeeds, reply with exactly FIXED_MODEL_OPENCODE_OK.' \
    2>&1 | tee "$log_file"
  status=${PIPESTATUS[0]}
  return "$status"
}

is_native_intent=false
case "${LANE_MODEL:-}" in
  auto/*) is_native_intent=true ;;
esac

record_smoke_model_outcome() {
  local recorded_runtime="${1:-$RUNTIME_MODEL}"
  local smoke_log="$SMOKE_LOG"
  if grep -Eiq 'HTTP[^0-9]*410|410 Gone' "$smoke_log"; then
    printf 'model_retired_410\t%s\n' \
      "${recorded_runtime} returned HTTP 410 and is permanently retired" \
      > "$RUNNER_TEMP/factory-discovery-outcome"
  elif grep -Eiq 'HTTP[^0-9]*413|Request too large|tokens per minute|\bTPM\b' "$smoke_log"; then
    printf 'provider_throttle\t%s\n' \
      "${recorded_runtime} hit a provider token/TPM or request-size limit (HTTP 413)" \
      > "$RUNNER_TEMP/factory-discovery-outcome"
  elif grep -Eiq '429|Too Many Requests|rate.?limit|cooling down' "$smoke_log"; then
    printf 'provider_throttle\t%s\n' \
      "${recorded_runtime} was throttled or all upstream credentials were cooling down" \
      > "$RUNNER_TEMP/factory-discovery-outcome"
  elif grep -Eiq 'model[^[:alnum:]]+(not found|not available|unavailable|does not exist)|unknown model|invalid model|HTTP[^0-9]*404|404 Not Found|Model is unavailable' "$smoke_log"; then
    # Native intents (auto/coding:free) must not be marked unavailable
    # when a backing fallback model is missing from the live catalog.
    if [[ "$is_native_intent" == true ]]; then
      printf 'provider_failure\t%s\n' \
        "${recorded_runtime} native intent exhausted backing routes (backing model unavailable)" \
        > "$RUNNER_TEMP/factory-discovery-outcome"
    else
      printf 'model_unavailable\t%s\n' \
        "${recorded_runtime} was rejected as unavailable by OmniRoute" \
        > "$RUNNER_TEMP/factory-discovery-outcome"
    fi
  elif grep -Eiq 'all targets were skipped|pre-dispatch filters|ALL_TARGETS_SKIPPED|bad gateway|gateway timeout|service unavailable|HTTP[^0-9]*(502|503|504)|ECONNRESET|ETIMEDOUT|connection reset' "$smoke_log"; then
    printf 'provider_failure\t%s\n' \
      "${recorded_runtime} failed with a transient gateway or upstream error" \
      > "$RUNNER_TEMP/factory-discovery-outcome"
  fi
}

smoke_transient_re='429|Too Many Requests|rate.?limit|overloaded|temporar(il)?y unavailable|all targets were skipped|pre-dispatch filters|ALL_TARGETS_SKIPPED|HTTP[^0-9]*413|Request too large|tokens per minute|\bTPM\b|bad gateway|gateway timeout|service unavailable|HTTP[^0-9]*(502|503|504)|ECONNRESET|ETIMEDOUT|connection reset'
emit_transient_smoke_message() {
  local recorded_runtime="${1:-$RUNTIME_MODEL}"
  if [[ "$is_native_intent" == true ]]; then
    echo "Transient smoke failure for native intent ${recorded_runtime} (TPM/throttle/upstream); not quarantining the intent selector" >&2
  else
    echo "Transient smoke failure detected for ${recorded_runtime}; quarantining this route for the next selection" >&2
  fi
}

status=0
attempt_runtime="$RUNTIME_MODEL"
smoke_once "$RUNTIME_MODEL" "$SMOKE_LOG" "$PRIMARY_TIMEOUT" || status=$?

smoke_succeeded=false
if (( status == 0 )) && grep -q 'FIXED_MODEL_OPENCODE_OK' "$SMOKE_LOG"; then
  smoke_succeeded=true
fi
override=''
effective_model="$LANE_MODEL"
if [[ "$smoke_succeeded" != true ]]; then
  # TEMPORARY 2026-09-06: auto/coding:free is ALL_TARGETS_SKIPPED / hanging.
  # One retry on auto/best-free. Disable with FACTORY_OMNIROUTE_CAPACITY_BRIDGE=off.
  bridge="$(python3 "$ROUTE_HELPER" --next-after-smoke-failure \
    --primary "$LANE_MODEL" --status "$status" --log-file "$SMOKE_LOG" || true)"
  if [[ -n "$bridge" ]]; then
    echo "TEMPORARY OmniRoute capacity bridge: ${LANE_MODEL} skipped/timed out; retrying ${bridge}" >&2
    cat "$SMOKE_LOG" >&2 || true
    status=0
    attempt_runtime="omniroute/${bridge}"
    smoke_once "omniroute/${bridge}" "$SMOKE_LOG" "$BRIDGE_TIMEOUT" || status=$?
    if (( status == 0 )) && grep -q 'FIXED_MODEL_OPENCODE_OK' "$SMOKE_LOG"; then
      smoke_succeeded=true
      override="$bridge"
      effective_model="$bridge"
      RUNTIME_MODEL="$attempt_runtime"
      echo "TEMPORARY capacity bridge succeeded on ${bridge}"
    fi
  fi
fi

{
  echo "model=$effective_model"
  echo "runtime_model=omniroute/${effective_model}"
  echo "override=$override"
} >> "$GITHUB_OUTPUT"
printf '%s\n' "$effective_model" > "$RUNNER_TEMP/factory-effective-model"
if [[ "$smoke_succeeded" == true ]]; then
  exit 0
fi
if (( status != 0 )); then
  if (( status == 124 || status == 137 || status == 143 )) || \
    grep -Eiq "$smoke_transient_re" "$SMOKE_LOG"; then
    record_smoke_model_outcome "$attempt_runtime"
    emit_transient_smoke_message "$attempt_runtime"
    cat "$SMOKE_LOG" >&2 || true
    exit 1
  fi
  record_smoke_model_outcome "$attempt_runtime"
  exit "$status"
fi
echo "Smoke did not return FIXED_MODEL_OPENCODE_OK" >&2
cat "$SMOKE_LOG" >&2 || true
record_smoke_model_outcome "$attempt_runtime"
exit 1
