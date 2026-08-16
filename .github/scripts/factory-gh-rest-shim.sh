#!/usr/bin/env bash
set -Eeuo pipefail

REAL_GH="${FACTORY_REAL_GH:-/usr/bin/gh}"
[[ -x "$REAL_GH" ]] || {
  echo "factory gh REST shim: real gh executable not found at ${REAL_GH}" >&2
  exit 127
}

original=("$@")
command_group="${1:-}"
command_name="${2:-}"

emit_with_optional_jq() {
  local payload="$1" jq_expr="${2:-}"
  if [[ -n "$jq_expr" ]]; then
    jq -r "$jq_expr" <<< "$payload"
  else
    printf '%s\n' "$payload"
  fi
}

parse_list_args() {
  local -n out_repo=$1 out_state=$2 out_limit=$3 out_jq=$4 out_labels=$5
  shift 5
  out_repo="${GITHUB_REPOSITORY:-}"
  out_state='open'
  out_limit=100
  out_jq=''
  out_labels=()
  while (( $# )); do
    case "$1" in
      --repo)
        out_repo="$2"; shift 2 ;;
      --state)
        out_state="$2"; shift 2 ;;
      --limit)
        out_limit="$2"; shift 2 ;;
      --label)
        out_labels+=("$2"); shift 2 ;;
      --json)
        shift 2 ;;
      --jq)
        out_jq="$2"; shift 2 ;;
      *)
        return 2 ;;
    esac
  done
  [[ -n "$out_repo" && "$out_limit" =~ ^[0-9]+$ ]] || return 2
}

if [[ "$command_group" == issue && "$command_name" == list ]]; then
  shift 2
  repo='' state='' limit='' jq_expr=''
  labels=()
  if ! parse_list_args repo state limit jq_expr labels "$@"; then
    exec "$REAL_GH" "${original[@]}"
  fi
  pages="$("$REAL_GH" api --paginate --slurp "repos/${repo}/issues?state=${state}&per_page=100")"
  labels_json="$(printf '%s\n' "${labels[@]:-}" | jq -Rsc 'split("\n") | map(select(length > 0))')"
  payload="$(jq -c --argjson labels "$labels_json" --argjson limit "$limit" '
    [
      .[][]
      | select(.pull_request == null)
      | select([.labels[]?.name] as $item_labels
          | all($labels[] as $wanted; ($item_labels | index($wanted)) != null))
      | {
          number,
          title,
          body,
          labels,
          createdAt: .created_at,
          updatedAt: .updated_at,
          state: (if .state == "open" then "OPEN" else "CLOSED" end)
        }
    ][: $limit]
  ' <<< "$pages")"
  emit_with_optional_jq "$payload" "$jq_expr"
  exit 0
fi

if [[ "$command_group" == pr && "$command_name" == list ]]; then
  shift 2
  repo='' state='' limit='' jq_expr=''
  labels=()
  if ! parse_list_args repo state limit jq_expr labels "$@"; then
    exec "$REAL_GH" "${original[@]}"
  fi
  pages="$("$REAL_GH" api --paginate --slurp "repos/${repo}/pulls?state=${state}&per_page=100")"
  labels_json="$(printf '%s\n' "${labels[@]:-}" | jq -Rsc 'split("\n") | map(select(length > 0))')"
  payload="$(jq -c --argjson labels "$labels_json" --argjson limit "$limit" '
    [
      .[][]
      | select([.labels[]?.name] as $item_labels
          | all($labels[] as $wanted; ($item_labels | index($wanted)) != null))
      | {
          number,
          title,
          body,
          labels,
          headRefName: .head.ref,
          headRefOid: .head.sha,
          createdAt: .created_at,
          updatedAt: .updated_at,
          isDraft: (.draft // false),
          state: (if .state == "open" then "OPEN" else "CLOSED" end)
        }
    ][: $limit]
  ' <<< "$pages")"
  emit_with_optional_jq "$payload" "$jq_expr"
  exit 0
fi

parse_view_args() {
  local -n out_number=$1 out_repo=$2 out_jq=$3
  shift 3
  out_number="${1:-}"
  shift || true
  out_repo="${GITHUB_REPOSITORY:-}"
  out_jq=''
  [[ "$out_number" =~ ^[0-9]+$ ]] || return 2
  while (( $# )); do
    case "$1" in
      --repo)
        out_repo="$2"; shift 2 ;;
      --json)
        shift 2 ;;
      --jq)
        out_jq="$2"; shift 2 ;;
      *)
        return 2 ;;
    esac
  done
  [[ -n "$out_repo" ]] || return 2
}

if [[ "$command_group" == pr && "$command_name" == view ]]; then
  shift 2
  number='' repo='' jq_expr=''
  if ! parse_view_args number repo jq_expr "$@"; then
    exec "$REAL_GH" "${original[@]}"
  fi
  raw="$("$REAL_GH" api "repos/${repo}/pulls/${number}")"
  payload="$(jq -c '
    {
      number,
      title,
      body,
      labels,
      state: (if .merged_at != null then "MERGED" elif .state == "open" then "OPEN" else "CLOSED" end),
      isDraft: (.draft // false),
      mergeable: (if .mergeable == true then "MERGEABLE" elif .mergeable == false then "CONFLICTING" else "UNKNOWN" end),
      headRefOid: .head.sha,
      headRefName: .head.ref
    }
  ' <<< "$raw")"
  emit_with_optional_jq "$payload" "$jq_expr"
  exit 0
fi

if [[ "$command_group" == issue && "$command_name" == view ]]; then
  shift 2
  number='' repo='' jq_expr=''
  if ! parse_view_args number repo jq_expr "$@"; then
    exec "$REAL_GH" "${original[@]}"
  fi
  raw="$("$REAL_GH" api "repos/${repo}/issues/${number}")"
  payload="$(jq -c '
    {
      number,
      title,
      body,
      labels,
      state: (if .state == "open" then "OPEN" else "CLOSED" end)
    }
  ' <<< "$raw")"
  emit_with_optional_jq "$payload" "$jq_expr"
  exit 0
fi

exec "$REAL_GH" "${original[@]}"
