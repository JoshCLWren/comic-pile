#!/usr/bin/env bash
set -Eeuo pipefail

FACTORY_SEMANTIC_STATUS_APPROVED='semantic_review_approved'
FACTORY_SEMANTIC_STATUS_BLOCKED='semantic_review_blocked'
FACTORY_SEMANTIC_STATUS_RECOVERED='semantic_review_verdict_recovered'
FACTORY_SEMANTIC_STATUS_MISSING='semantic_review_missing_verdict'
FACTORY_SEMANTIC_STATUS_CONFLICTING='semantic_review_conflicting_verdict'
FACTORY_SEMANTIC_STATUS_RECOVERY_FAILED='semantic_review_recovery_failed'
FACTORY_SEMANTIC_STATUS_TIMEOUT='semantic_review_timeout'
FACTORY_SEMANTIC_STATUS_MODEL_ERROR='semantic_review_model_error'
FACTORY_SEMANTIC_STATUS_HEAD_CHANGED='semantic_review_head_changed'

factory_strip_ansi() {
  sed -E $'s/\x1B\[[0-9;?]*[ -\/]*[@-~]//g'
}

factory_normalize_terminal_line() {
  local line="$1"
  line="$(printf '%s' "$line" | factory_strip_ansi)"
  line="$(sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//' <<< "$line")"
  # Permit harmless Markdown wrappers while keeping equality exact.
  line="$(sed -E 's/^(\*\*|__|`)//; s/(\*\*|__|`)$//' <<< "$line")"
  printf '%s\n' "$line"
}

factory_terminal_marker() {
  local log_file="$1" line
  [[ -f "$log_file" ]] || return 1
  line="$(factory_strip_ansi < "$log_file" | sed -E '/^[[:space:]]*$/d' | tail -n 1 || true)"
  [[ -n "$line" ]] || return 1
  factory_normalize_terminal_line "$line"
}

factory_verdict_from_marker() {
  local marker="$1"
  case "$marker" in
    FACTORY_GATE_READY) printf '%s\n' approve ;;
    FACTORY_GATE_BLOCKED|FACTORY_GATE_NOT_READY) printf '%s\n' repair ;;
    FACTORY_GATE_REJECT) printf '%s\n' reject ;;
    *) return 1 ;;
  esac
}

factory_extract_semantic_verdict() {
  local log_file="$1" marker
  marker="$(factory_terminal_marker "$log_file" || true)"
  [[ -n "$marker" ]] || return 1
  factory_verdict_from_marker "$marker"
}

factory_review_has_conflicting_terminal_markers() {
  local log_file="$1" markers
  [[ -f "$log_file" ]] || return 1
  markers="$(factory_strip_ansi < "$log_file" \
    | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//' \
    | sed -E 's/^(\*\*|__|`)//; s/(\*\*|__|`)$//' \
    | grep -E '^FACTORY_GATE_(READY|BLOCKED|NOT_READY|REJECT)$' \
    | sort -u || true)"
  [[ "$(wc -l <<< "$markers" | tr -d ' ')" -gt 1 ]]
}

factory_review_is_substantive() {
  local log_file="$1" base_ref="${2:-origin/main}" bytes path basename
  [[ -f "$log_file" ]] || return 1
  bytes="$(tr -d '[:space:]' < "$log_file" | wc -c | tr -d ' ')"
  (( bytes >= 500 )) || return 1

  while IFS= read -r path; do
    [[ -n "$path" ]] || continue
    basename="${path##*/}"
    if grep -Fq -- "$path" "$log_file" || grep -Fq -- "$basename" "$log_file"; then
      return 0
    fi
  done < <(git diff --name-only "$base_ref"...HEAD 2>/dev/null || true)

  return 1
}

factory_primary_review_denies_ready_recovery() {
  local log_file="$1"
  [[ -f "$log_file" ]] || return 0
  # This check may only deny approval. It can never manufacture approval.
  grep -Eiq 'FACTORY_GATE_(BLOCKED|NOT_READY|REJECT)|\bnot[[:space:]-]+ready\b|\bcannot[[:space:]]+approve\b|\bblocking[[:space:]]+(issue|defect|problem)\b|\brequest(ed)?[[:space:]]+changes\b' "$log_file"
}

factory_sanitize_review_log() {
  local input="$1" output="$2"
  factory_strip_ansi < "$input" \
    | sed -E 's#https://x-access-token:[^@[:space:]]+@github\.com/#https://x-access-token:[REDACTED]@github.com/#g' \
    | sed -E 's/(github_pat_[A-Za-z0-9_]+|gh[pousr]_[A-Za-z0-9_]+)/[REDACTED_GITHUB_TOKEN]/g' \
    | sed -E 's/(Authorization:[[:space:]]*Bearer[[:space:]]+)[^[:space:]]+/\1[REDACTED]/Ig' \
    > "$output"
}

factory_recover_semantic_verdict() {
  local runtime_model="$1" workspace="$2" timeout_seconds="$3" recovery_log="$4"
  local status=0
  set +e
  timeout --signal=TERM --kill-after=15s "${timeout_seconds}s" \
    opencode run --continue -m "$runtime_model" --agent build --auto --dir "$workspace" \
    --title 'ComicPile semantic verdict recovery' \
    'Your semantic review is complete but its terminal machine verdict was missing. Do not inspect files, run commands, or redo the review. Return exactly one bare line and nothing else: FACTORY_GATE_READY if your completed review found no semantic blocker, otherwise FACTORY_GATE_BLOCKED.' \
    2>&1 | tee "$recovery_log"
  status=${PIPESTATUS[0]}
  set -e
  return "$status"
}
