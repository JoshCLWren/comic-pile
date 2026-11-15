#!/usr/bin/env bash
# Trusted factory-only recovery writer. Never checks out a different branch,
# edits the agent's index, or pushes into a production/review PR branch.
set -Eeuo pipefail

[[ "$#" -eq 4 ]] || { echo 'usage: factory-work-checkpoint.sh MODE NUMBER WORKER RUN_ID' >&2; exit 2; }
mode="$1" number="$2" worker="$3" run_id="$4"
[[ "$mode" == issue || "$mode" == pr ]] || exit 2
[[ "$number" =~ ^[1-9][0-9]*$ && "$worker" =~ ^[1-9][0-9]*$ && "$run_id" =~ ^[1-9][0-9]*$ ]] || exit 2

interval="${FACTORY_CHECKPOINT_INTERVAL_SECONDS:-45}"
[[ "$interval" =~ ^[1-9][0-9]*$ ]] || exit 2
base_sha="$(git rev-parse --verify HEAD)"
base_tree="$(git rev-parse --verify "${base_sha}^{tree}")"
source_branch="$(git symbolic-ref --quiet --short HEAD)" || exit 2
ref="refs/heads/factory/work-checkpoints/${run_id}"
state_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/factory-checkpoint.XXXXXXXX")"
trap 'rm -rf "$state_dir"' EXIT
index="$state_dir/index"
last_tree="$base_tree"
last_commit="$base_sha"
stop_requested=0
trap 'stop_requested=1' USR1 TERM INT

checkpoint_once() {
  local current_tree commit
  # The agent can inspect refs, but this writer only snapshots the exact
  # checked-out target branch. Never follow its arbitrary branch switches.
  [[ "$(git symbolic-ref --quiet --short HEAD 2>/dev/null || :)" == "$source_branch" ]] || return 0
  GIT_INDEX_FILE="$index" git read-tree "$base_sha" || return 1
  # A private index captures tracked and non-ignored new files without
  # touching the agent's index or HEAD. Git's ignore rules remain effective.
  GIT_INDEX_FILE="$index" git add -A -- . || return 1
  current_tree="$(GIT_INDEX_FILE="$index" git write-tree)" || return 1
  [[ "$current_tree" != "$last_tree" ]] || return 0
  commit="$(printf 'checkpoint(factory): worker %s run %s %s #%s (unreviewed recovery only)\n' \
    "$worker" "$run_id" "$mode" "$number" | git commit-tree "$current_tree" -p "$last_commit")" || return 1
  # Every attempt owns a unique ref. The parent chain makes each update
  # fast-forward-only; neither main nor the assigned PR branch is touched.
  if GIT_TERMINAL_PROMPT=0 git push --quiet origin "$commit:$ref"; then
    last_tree="$current_tree"
    last_commit="$commit"
    printf '[factory-checkpoint] saved %s #%s: %s (%s)\n' "$mode" "$number" "$ref" "$commit"
  else
    echo '::warning::Factory checkpoint push failed; retrying on next interval' >&2
    return 1
  fi
}

# A signal from the trusted wrapper performs one final snapshot and exits.
# Periodic pushes preserve earlier edits even if Actions force-kills the job
# before EXIT or TERM handlers can run.
while :; do
  sleep "$interval" &
  sleep_pid=$!
  wait "$sleep_pid" || true
  kill "$sleep_pid" 2>/dev/null || true
  checkpoint_once || echo '::warning::Factory checkpoint attempt failed' >&2
  (( stop_requested == 0 )) || break
done
