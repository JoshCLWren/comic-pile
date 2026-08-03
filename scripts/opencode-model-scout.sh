#!/usr/bin/env bash
# OpenCode model scout: concurrently probes candidate models through opencode's
# ACP for tool-calling support, and updates the shared model manifest as each
# probe completes.
#
# Every probe writes a heartbeat file on each line of model output. A watchdog
# in the supervisor kills any probe that has not written to its heartbeat for
# MODEL_SCOUT_TIMEOUT (default 15 minutes), and marks it failed in the manifest.
#
# Usage:
#   opencode-model-scout.sh [options]
#
# Options:
#   --models "id1 id2 ..."      Explicit model list (overrides discovery).
#   --candidates-file PATH      Newline-separated candidate list.
#   --state-dir DIR             Manifest state directory (default: COMIC_PILE_FACTORY_STATE_DIR).
#   --parallel N                Concurrent probes (default MODEL_SCOUT_PARALLEL=4).
#   --timeout SECONDS           Heartbeat timeout (default MODEL_SCOUT_TIMEOUT=900).
#   --watch                     Re-scan for new/pending candidates on an interval.
#   --recheck-seconds N         Watch-mode re-scan interval (default 600).
#   --force                     Re-probe models already confirmed in the manifest.
#   --limit N                   Probe at most N candidates per pass.
#   --once                      Run a single pass and exit (default).
#   -h, --help                  Show help.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_REPO="${COMIC_PILE_REPO:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
MANIFEST_HELPER="$SCRIPT_DIR/opencode-model-manifest.sh"
STATE_DIR="${COMIC_PILE_FACTORY_STATE_DIR:-${SOURCE_REPO%/}-factory-state}"
PARALLEL="${MODEL_SCOUT_PARALLEL:-4}"
TIMEOUT="${MODEL_SCOUT_TIMEOUT:-900}"
WATCH=0
RECHECK_SECONDS=600
FORCE=0
LIMIT=0
EXPLICIT_MODELS=()
CANDIDATES_FILE=""

usage() {
  sed -n '2,24p' "$0" | sed 's/^# //; /^$/d'
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
    --models)
      (($# >= 2)) || die "--models requires a value"
      read -r -a EXPLICIT_MODELS <<<"$2"
      shift 2
      ;;
    --candidates-file)
      (($# >= 2)) || die "--candidates-file requires a path"
      CANDIDATES_FILE="$2"
      shift 2
      ;;
    --state-dir)
      (($# >= 2)) || die "--state-dir requires a path"
      STATE_DIR="$2"
      shift 2
      ;;
    --parallel)
      (($# >= 2)) || die "--parallel requires a number"
      PARALLEL="$2"
      shift 2
      ;;
    --timeout)
      (($# >= 2)) || die "--timeout requires a number"
      TIMEOUT="$2"
      shift 2
      ;;
    --watch) WATCH=1; shift ;;
    --recheck-seconds)
      (($# >= 2)) || die "--recheck-seconds requires a number"
      RECHECK_SECONDS="$2"
      shift 2
      ;;
    --force) FORCE=1; shift ;;
    --limit)
      (($# >= 2)) || die "--limit requires a number"
      LIMIT="$2"
      shift 2
      ;;
    --once) WATCH=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

is_nonnegative_integer "$PARALLEL" || die "--parallel must be an integer"
((PARALLEL >= 1)) || die "--parallel must be at least 1"
is_nonnegative_integer "$TIMEOUT" || die "--timeout must be an integer"
is_nonnegative_integer "$RECHECK_SECONDS" || die "--recheck-seconds must be an integer"

for command in opencode jq date kill grep xargs flock; do
  command -v "$command" >/dev/null 2>&1 || die "required command not found: $command"
done

HB_DIR="$STATE_DIR/heartbeats"
LOG_DIR="$STATE_DIR/scout"
mkdir -p "$HB_DIR" "$LOG_DIR"

"$MANIFEST_HELPER" init "$STATE_DIR"

safe_name() {
  printf '%s' "$1" | tr '/:@._ ' '______'
}

# Non-chat models that should never be probed as coding agents.
non_chat() {
  [[ "$1" == *embedding* || "$1" == *"rerank"* || "$1" == *whisper* || "$1" == *"tts"* \
    || "$1" == *"-image"* || "$1" == *"image-"* || "$1" == *safeguard* \
    || "$1" == *"content-safety"* || "$1" == *cosmos* || "$1" == *riva* \
    || "$1" == *nemotron-mini* || "$1" == *"prompt-guard"* || "$1" == *esm* ]]
}

discover_candidates() {
  if ((${#EXPLICIT_MODELS[@]} > 0)); then
    printf '%s\n' "${EXPLICIT_MODELS[@]}"
    return
  fi
  if [[ -n "$CANDIDATES_FILE" ]]; then
    [[ -f "$CANDIDATES_FILE" ]] || die "candidates file not found: $CANDIDATES_FILE"
    grep -v '^\s*#' "$CANDIDATES_FILE" | grep -v '^\s*$'
    return
  fi
  opencode models 2>/dev/null | grep -vE '^opencode/' | while IFS= read -r m; do
    non_chat "$m" || printf '%s\n' "$m"
  done
}

# probe MODEL  — writes result to manifest; heartbeat updated per output line.
# Heartbeat file contains this probe's process-group id so the watchdog can kill
# the whole probe group when the heartbeat goes stale.
probe_model() {
  local model="$1"
  local safe
  safe="$(safe_name "$model")"
  local hb="$HB_DIR/$safe.hb"
  local log="$LOG_DIR/${safe}.log"
  local prompt="Use the bash tool to run this exact command: printf 'TOOL_OK_1234'. After the tool returns, reply with the word DONE."

  printf '%s' "$$" >"$hb"
  touch "$hb"
  local out
  # Touch heartbeat per line of opencode output; if the model stalls with no
  # output for TIMEOUT seconds, the supervisor kills this probe.
  out="$(timeout "$TIMEOUT" opencode run --model "$model" --auto --format json --print-logs=false "$prompt" 2>&1 | \
    while IFS= read -r line; do touch "$hb"; printf '%s\n' "$line"; done)"
  local status=${PIPESTATUS[0]}

  local tool_state tool_out tool
  tool_state="$(printf '%s' "$out" | jq -r 'select(.type=="tool_use" and .part.tool=="bash") | .part.state.status' 2>/dev/null | head -1)"
  tool_out="$(printf '%s' "$out" | jq -r 'select(.type=="tool_use" and .part.tool=="bash") | .part.state.output' 2>/dev/null | head -1)"
  tool="no"
  if [[ "$tool_state" == "completed" && "$tool_out" == *"TOOL_OK_1234"* ]]; then
    tool="yes"
  fi

  if [[ "$tool" == "yes" ]]; then
    printf '%s\n' "$out" >"$log"
    "$MANIFEST_HELPER" set "$model" confirmed "$tool" "$STATE_DIR"
    printf 'PASS  %-45s tool-call ok\n' "$model"
  else
    if ((status == 124)); then
      printf '%s\n' "$out" >"$log"
      "$MANIFEST_HELPER" set "$model" failed "$tool" "$STATE_DIR"
      printf 'KILL  %-45s heartbeat timeout after %ss\n' "$model" "$TIMEOUT"
    else
      printf '%s\n' "$out" >"$log"
      "$MANIFEST_HELPER" set "$model" failed "$tool" "$STATE_DIR"
      printf 'FAIL  %-45s no tool-call (exit %s)\n' "$model" "$status"
    fi
  fi
  rm -f "$hb"
}
export -f probe_model
export HB_DIR LOG_DIR MANIFEST_HELPER STATE_DIR TIMEOUT

watchdog() {
  # Kill any probe whose heartbeat file is stale for TIMEOUT seconds. Scans the
  # heartbeat dir on the filesystem so it can run in a subshell without access
  # to the parent's job table.
  while :; do
    local now
    now="$(date +%s)"
    for hb in "$HB_DIR"/*.hb; do
      [[ -f "$hb" ]] || continue
      local age
      age=$((now - $(stat -c %Y "$hb" 2>/dev/null || printf '%s' "$now")))
      if ((age <= TIMEOUT)); then continue; fi
      local model="${hb##*/}"
      model="${model%.hb}"
      local pgid
      pgid="$(cat "$hb" 2>/dev/null || true)"
      printf 'WATCHDOG: killing %s (pgid %s) — no heartbeat for %ss\n' "$model" "$pgid" "$age" >&2
      if [[ -n "$pgid" ]] && kill -0 "$pgid" 2>/dev/null; then
        kill -9 -- "-$pgid" 2>/dev/null || kill -9 "$pgid" 2>/dev/null || true
      fi
      "$MANIFEST_HELPER" set "$model" failed no "$STATE_DIR" >/dev/null 2>&1 || true
    done
    sleep 15
  done
}

run_pass() {
  local candidates
  candidates="$(discover_candidates | sed '/^$/d')"
  if [[ "$FORCE" != "1" ]]; then
    candidates="$(printf '%s\n' "$candidates" | while IFS= read -r m; do
      [[ -z "$m" ]] && continue
      local st
      st="$(awk -F'\t' -v m="$m" 'NR>1 && $1==m {print $2}' "$STATE_DIR/model_manifest.tsv" 2>/dev/null | head -1)"
      [[ "$st" != "confirmed" ]] && printf '%s\n' "$m"
    done)"
  fi
  candidates="$(printf '%s\n' "$candidates" | sed '/^$/d' | sort -u)"
  local total
  total="$(printf '%s\n' "$candidates" | sed '/^$/d' | wc -l | tr -d ' ')"
  if ((LIMIT > 0 && total > LIMIT)); then
    candidates="$(printf '%s\n' "$candidates" | head -n "$LIMIT")"
    total="$LIMIT"
  fi

  if ((total == 0)); then
    printf 'Scout: no pending candidates%s.\n' "$([[ "$FORCE" == "1" ]] && printf ' (--force)' || printf '')"
    return 0
  fi

  printf 'Scout: probing %d candidate model(s) (parallel=%d, heartbeat timeout=%ss)\n' "$total" "$PARALLEL" "$TIMEOUT"

  local launched=0
  local -a jobs=()
  while IFS= read -r model; do
    [[ -z "$model" ]] && continue
    # setsid: give each probe its own process group so the watchdog can kill the
    # whole tree (opencode + its children) with a single group kill.
    setsid bash -c 'probe_model "$1"' _ "$model" &
    local pid=$!
    jobs+=("$pid")
    launched=$((launched + 1))
    if ((launched % PARALLEL == 0)); then
      # Reap one finished job so we never exceed PARALLEL concurrent probes.
      wait -n "${jobs[@]}" 2>/dev/null || true
      # Drop PIDs that have exited.
      local -a alive=()
      local p
      for p in "${jobs[@]}"; do
        kill -0 "$p" 2>/dev/null && alive+=("$p")
      done
      jobs=("${alive[@]}")
    fi
  done <<<"$candidates"

  while ((${#jobs[@]} > 0)); do
    wait -n "${jobs[@]}" 2>/dev/null || true
    local -a alive=()
    local p
    for p in "${jobs[@]}"; do
      kill -0 "$p" 2>/dev/null && alive+=("$p")
    done
    jobs=("${alive[@]}")
  done
}

export -f safe_name non_chat discover_candidates run_pass

ACTIVE_PIDS_MAIN_PID="$$"
watchdog &
WATCHDOG_PID=$!
trap 'kill "$WATCHDOG_PID" 2>/dev/null || true' EXIT

printf 'OpenCode model scout (state=%s, parallel=%s, timeout=%ss)\n' "$STATE_DIR" "$PARALLEL" "$TIMEOUT"

if ((WATCH == 1)); then
  while true; do
    run_pass
    printf 'Scout: sleeping %ss before re-scan.\n' "$RECHECK_SECONDS"
    sleep "$RECHECK_SECONDS"
  done
else
  run_pass
fi

printf '\n=== Confirmed models ===\n'
"$MANIFEST_HELPER" summary "$STATE_DIR"
