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
issue="${FACTORY_CHECKPOINT_ISSUE:-}"
[[ "$mode" != issue ]] || issue="$number"
[[ -z "$issue" || "$issue" =~ ^[1-9][0-9]*$ ]] || exit 2
model="${FACTORY_CHECKPOINT_MODEL:-${FACTORY_MODEL:-unknown-model}}"
runtime_model="${FACTORY_CHECKPOINT_RUNTIME_MODEL:-${FACTORY_RUNTIME_MODEL:-$model}}"
[[ "$model" != *$'\n'* && "$model" != *$'\r'* && "$runtime_model" != *$'\n'* && "$runtime_model" != *$'\r'* ]] || exit 2
model_slug="$(printf '%s' "$model" | LC_ALL=C tr '[:upper:]' '[:lower:]' | LC_ALL=C sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' | cut -c1-80)"
[[ -n "$model_slug" ]] || model_slug=unknown-model
target_slug="issue-${issue:-unknown-pr-${number}}"
ref="refs/heads/factory/work-checkpoints/${target_slug}/${model_slug}/${run_id}"
state_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/factory-checkpoint.XXXXXXXX")"
trap 'rm -rf "$state_dir"' EXIT
index="$state_dir/index"
last_tree="$base_tree"
last_commit="$base_sha"
stop_requested=0
trap 'stop_requested=1' USR1 TERM INT
# Flush after a model exits without stopping periodic protection during the
# wrapper's optional same-lease correction attempt.
trap ':' USR2

publish_checkpoint() {
  [[ -n "${TRUSTED_CHECKPOINT_HANDOFF:-}" && -n "${GITHUB_REPOSITORY:-}" ]] || return 0
  python3 "$TRUSTED_CHECKPOINT_HANDOFF" --repo "$GITHUB_REPOSITORY" --run-id "$run_id" || {
    echo '::warning::Checkpoint saved; draft publication will retry on the next interval' >&2
    return 1
  }
}

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
  if [[ "$current_tree" == "$last_tree" ]]; then
    # A successful git push does not prove GitHub accepted the draft API call.
    [[ "$last_commit" == "$base_sha" ]] || publish_checkpoint
    return 0
  fi
  commit="$(printf 'checkpoint(factory): worker %s run %s %s #%s (unreviewed recovery only)\n\nIssue: %s\nModel: %s\nRuntime-model: %s\nSource-branch: %s\nBase-commit: %s\n' \
    "$worker" "$run_id" "$mode" "$number" "${issue:-unknown}" "$model" "$runtime_model" "$source_branch" "$base_sha" | git commit-tree "$current_tree" -p "$last_commit")" || return 1
  # Every attempt owns a unique ref. The parent chain makes each update
  # fast-forward-only; neither main nor the assigned PR branch is touched.
  if GIT_TERMINAL_PROMPT=0 git push --quiet origin "$commit:$ref"; then
    last_tree="$current_tree"
    last_commit="$commit"
    printf '[factory-checkpoint] saved %s #%s: %s (%s)\n' "$mode" "$number" "$ref" "$commit"
    publish_checkpoint
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
  if (( stop_requested != 0 )); then
    # TERM/USR1 can arrive while git or the draft API call is running. Capture
    # again after that operation so a final correction cannot miss the flush.
    checkpoint_once || echo '::warning::Final factory checkpoint attempt failed' >&2
    break
  fi
done
