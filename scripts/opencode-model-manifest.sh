#!/usr/bin/env bash
# OpenCode model manifest helper.
#
# Tracks probe results and usage for opencode models used by the ComicPile
# factory. Shared by the model scout and the factory runner.
#
# Manifest layout ($STATE_DIR/model_manifest.tsv):
#   model_id<TAB>status<TAB>tool_support<TAB>last_probed<TAB>use_count
#
# status:       untested | confirmed | failed
# tool_support: unknown | yes | no
#
# Usage:
#   opencode-model-manifest.sh init [STATE_DIR]
#   opencode-model-manifest.sh set MODEL STATUS TOOL [STATE_DIR]
#   opencode-model-manifest.sh record MODEL [STATE_DIR]
#   opencode-model-manifest.sh confirmed [STATE_DIR]
#   opencode-model-manifest.sh next DEFAULT_MODEL [STATE_DIR]
#   opencode-model-manifest.sh pending [STATE_DIR]
#   opencode-model-manifest.sh summary [STATE_DIR]

set -Eeuo pipefail

default_state_dir() {
  local source_repo="${COMIC_PILE_REPO:-}"
  if [[ -n "$source_repo" ]]; then
    printf '%s-factory-state\n' "${source_repo%/}"
  else
    printf '%s\n' "${COMIC_PILE_FACTORY_STATE_DIR:-/tmp/comic-pile-factory-state}"
  fi
}

state_dir_for() {
  if [[ $# -ge 1 && -n "$1" ]]; then
    printf '%s\n' "$1"
  else
    printf '%s\n' "${COMIC_PILE_FACTORY_STATE_DIR:-$(default_state_dir)}"
  fi
}

manifest_path() {
  printf '%s/model_manifest.tsv\n' "$1"
}

manifest_init() {
  local dir="$1"
  mkdir -p "$dir"
  local file
  file="$(manifest_path "$dir")"
  if [[ ! -f "$file" ]]; then
    printf 'model_id\tstatus\ttool_support\tlast_probed\tuse_count\n' >"$file"
  fi
}

manifest_lock() {
  local dir="$1"
  exec 9>"$dir/model_manifest.lock"
  flock -x 9
}

manifest_unlock() {
  flock -u 9 2>/dev/null || true
}

# set MODEL STATUS TOOL STATE_DIR
manifest_set() {
  local model="$1" status="$2" tool="$3" dir="$4"
  manifest_init "$dir"
  local file
  file="$(manifest_path "$dir")"
  manifest_lock "$dir"
  local tmp
  tmp="$(mktemp "$dir/.manifest.XXXXXX")"
  awk -F'\t' -v model="$model" -v status="$status" -v tool="$tool" -v now="$(date +%s)" \
    'BEGIN{OFS="\t"}
     NR==1{print; next}
     $1==model{print model, status, tool, now, ($5==""?0:$5); found=1; next}
     {print}
     END{if(!found) print model, status, tool, now, 0}' \
    "$file" >"$tmp"
  mv "$tmp" "$file"
  manifest_unlock
}

# record MODEL STATE_DIR  (bump use_count, mark confirmed)
manifest_record() {
  local model="$1" dir="$2"
  manifest_init "$dir"
  local file
  file="$(manifest_path "$dir")"
  manifest_lock "$dir"
  local tmp
  tmp="$(mktemp "$dir/.manifest.XXXXXX")"
  awk -F'\t' -v model="$model" -v now="$(date +%s)" \
    'BEGIN{OFS="\t"}
     NR==1{print; next}
     $1==model{print model, "confirmed", ($3==""?"unknown":$3), now, ($5==""?1:$5+1); found=1; next}
     {print}
     END{if(!found) print model, "confirmed", "unknown", now, 1}' \
    "$file" >"$tmp"
  mv "$tmp" "$file"
  manifest_unlock
}

# confirmed STATE_DIR  -> newline-separated confirmed model ids
manifest_confirmed() {
  local dir="$1"
  manifest_init "$dir"
  local file
  file="$(manifest_path "$dir")"
  [[ -f "$file" ]] || return 0
  awk -F'\t' 'NR>1 && $2=="confirmed" && $1!="" {print $1}' "$file"
}

# pending STATE_DIR  -> models that are untested or failed (candidates for re-probe)
manifest_pending() {
  local dir="$1"
  manifest_init "$dir"
  local file
  file="$(manifest_path "$dir")"
  [[ -f "$file" ]] || return 0
  awk -F'\t' 'NR>1 && ($2=="untested" || $2=="failed") && $1!="" {print $1}' "$file"
}

# next DEFAULT STATE_DIR -> round-robin confirmed model, or DEFAULT when none.
# Uses $dir/model_cursor for round-robin across confirmed models (least-used first).
manifest_next() {
  local default="$1" dir="$2"
  local models
  models="$(manifest_confirmed "$dir" | sort -t$'\t' -k5,5n)"
  [[ -n "$models" ]] || { printf '%s\n' "$default"; return 0; }
  local cursor_file="$dir/model_cursor"
  local cursor=0
  [[ -f "$cursor_file" ]] && cursor="$(cat "$cursor_file" 2>/dev/null || printf 0)"
  [[ "$cursor" =~ ^[0-9]+$ ]] || cursor=0
  local count n
  count="$(printf '%s\n' "$models" | sed '/^$/d' | wc -l | tr -d ' ')"
  ((count > 0)) || { printf '%s\n' "$default"; return 0; }
  n=$((cursor % count + 1))
  printf '%s\n' "$((cursor + 1))" >"$cursor_file"
  printf '%s\n' "$models" | sed -n "${n}p"
}

# summary STATE_DIR -> human-readable one-line-per-model summary
manifest_summary() {
  local dir="$1"
  manifest_init "$dir"
  local file
  file="$(manifest_path "$dir")"
  [[ -f "$file" ]] || return 0
  printf '%-45s %-10s %-8s %-12s %s\n' MODEL STATUS TOOLS PROBED USES
  tail -n +2 "$file" | column -t -s $'\t'
}

main() {
  local cmd="${1:-}"
  [[ -n "$cmd" ]] || { printf 'usage: %s <init|set|record|confirmed|next|pending|summary> [...]\n' "$0" >&2; exit 2; }
  shift
  case "$cmd" in
    init)
      manifest_init "$(state_dir_for "${1:-}")"
      ;;
    set)
      (($# >= 3)) || { printf 'usage: %s set MODEL STATUS TOOL [STATE_DIR]\n' "$0" >&2; exit 2; }
      local model="$1" status="$2" tool="$3" dir
      shift 3
      dir="$(state_dir_for "${1:-}")"
      manifest_set "$model" "$status" "$tool" "$dir"
      ;;
    record)
      (($# >= 1)) || { printf 'usage: %s record MODEL [STATE_DIR]\n' "$0" >&2; exit 2; }
      local model="$1" dir
      shift
      dir="$(state_dir_for "${1:-}")"
      manifest_record "$model" "$dir"
      ;;
    confirmed)
      manifest_confirmed "$(state_dir_for "${1:-}")"
      ;;
    pending)
      manifest_pending "$(state_dir_for "${1:-}")"
      ;;
    next)
      (($# >= 1)) || { printf 'usage: %s next DEFAULT_MODEL [STATE_DIR]\n' "$0" >&2; exit 2; }
      local default="$1" dir
      shift
      dir="$(state_dir_for "${1:-}")"
      manifest_next "$default" "$dir"
      ;;
    summary)
      manifest_summary "$(state_dir_for "${1:-}")"
      ;;
    *)
      printf 'unknown command: %s\n' "$cmd" >&2
      exit 2
      ;;
  esac
}

main "$@"
