#!/usr/bin/env bash
# Rotate models between independent factory heartbeats.
#
# The full single-heartbeat implementation lives in
# comic-pile-opencode-factory-heartbeat.sh. Keeping orchestration here makes
# model selection happen for every heartbeat instead of once per long-lived run.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HEARTBEAT_RUNNER="$SCRIPT_DIR/comic-pile-opencode-factory-heartbeat.sh"
MANIFEST_HELPER="$SCRIPT_DIR/opencode-model-manifest.sh"
SOURCE_REPO="${COMIC_PILE_REPO:-/mnt/extra/josh/code/comic-pile}"
STATE_DIR="${COMIC_PILE_FACTORY_STATE_DIR:-}"
DEFAULT_MODEL="${COMIC_PILE_DEFAULT_MODEL:-deepseek/deepseek-v4-flash}"
PINNED_MODEL="${OPENCODE_MODEL:-}"
IDLE_SECONDS="${FACTORY_IDLE_SECONDS:-60}"
MODE="drain"
RUN_ONCE=0
STATE_DIR_EXPLICIT=0
FORWARD_ARGS=()
MAX_FAILURES="${FACTORY_MAX_FAILURES:-2}"

usage() {
  "$HEARTBEAT_RUNNER" --help
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

is_nonnegative_integer() {
  [[ "$1" =~ ^[0-9]+$ ]]
}

while (($#)); do
  case "$1" in
    --watch)
      MODE="watch"
      shift
      ;;
    --once)
      RUN_ONCE=1
      shift
      ;;
    --model)
      (($# >= 2)) || die "--model requires an id"
      PINNED_MODEL="$2"
      shift 2
      ;;
    --repo)
      (($# >= 2)) || die "--repo requires a path"
      SOURCE_REPO="$2"
      FORWARD_ARGS+=("$1" "$2")
      shift 2
      ;;
    --state-dir)
      (($# >= 2)) || die "--state-dir requires a path"
      STATE_DIR="$2"
      STATE_DIR_EXPLICIT=1
      shift 2
      ;;
    --idle-seconds)
      (($# >= 2)) || die "--idle-seconds requires a number"
      IDLE_SECONDS="$2"
      FORWARD_ARGS+=("$1" "$2")
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      FORWARD_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ -z "$STATE_DIR" || "$STATE_DIR_EXPLICIT" == "0" && -z "${COMIC_PILE_FACTORY_STATE_DIR:-}" ]]; then
  STATE_DIR="${SOURCE_REPO%/}-factory-state"
fi

is_nonnegative_integer "$IDLE_SECONDS" || die "FACTORY_IDLE_SECONDS must be an integer"
is_nonnegative_integer "$MAX_FAILURES" || die "FACTORY_MAX_FAILURES must be an integer"
((MAX_FAILURES >= 1)) || die "FACTORY_MAX_FAILURES must be at least 1"
[[ -x "$HEARTBEAT_RUNNER" ]] || die "heartbeat runner is not executable: $HEARTBEAT_RUNNER"
[[ -x "$MANIFEST_HELPER" ]] || die "manifest helper is not executable: $MANIFEST_HELPER"
mkdir -p "$STATE_DIR"
"$MANIFEST_HELPER" init "$STATE_DIR"

select_model() {
  if [[ -n "$PINNED_MODEL" ]]; then
    printf '%s\n' "$PINNED_MODEL"
  else
    "$MANIFEST_HELPER" next "$DEFAULT_MODEL" "$STATE_DIR"
  fi
}

heartbeat=0
while true; do
  heartbeat=$((heartbeat + 1))
  model="$(select_model)"
  result_file="$(mktemp "$STATE_DIR/.factory-result.XXXXXX")"
  printf '\nFactory wrapper heartbeat %d using model %s\n' "$heartbeat" "$model"

  set +e
  "$HEARTBEAT_RUNNER" --once --state-dir "$STATE_DIR" --model "$model" \
    "${FORWARD_ARGS[@]}" 2>&1 | tee "$result_file"
  status=${PIPESTATUS[0]}
  set -e

  # The heartbeat implementation owns its watchdog files, but the wrapper owns
  # process lifetime. Remove completed files so they cannot accumulate forever.
  rm -f "$STATE_DIR"/heartbeats/factory_heartbeat_*.hb 2>/dev/null || true

  if ((status != 0)); then
    # Retire this model from confirmed rotation so the next heartbeat gets a
    # different known-good candidate. Keep the failure in the manifest.
    "$MANIFEST_HELPER" fail "$model" "$STATE_DIR" >/dev/null 2>&1 || true
    rm -f "$result_file"
    if [[ -n "$PINNED_MODEL" ]]; then
      printf 'Factory stopped after failure of pinned model %s.\n' "$model" >&2
      exit "$status"
    fi
    if ! "$MANIFEST_HELPER" confirmed "$STATE_DIR" | grep -q .; then
      printf 'Factory stopped: no confirmed models remain after failure of %s.\n' "$model" >&2
      exit "$status"
    fi
    printf 'Heartbeat failed for %s; immediately rotating to the next model (no cooldown).\n' \
      "$model" >&2
    continue
  fi

  if grep -Fq 'FACTORY_RESULT: changed' "$result_file"; then
    rm -f "$result_file"
    if ((RUN_ONCE == 1)); then
      exit 0
    fi
    continue
  fi

  if grep -Fq 'FACTORY_RESULT: idle' "$result_file"; then
    rm -f "$result_file"
    if ((RUN_ONCE == 1)) || [[ "$MODE" == "drain" ]]; then
      exit 0
    fi
    sleep "$IDLE_SECONDS"
    continue
  fi

  rm -f "$result_file"
  die "heartbeat runner returned success without a terminal FACTORY_RESULT marker"
done
