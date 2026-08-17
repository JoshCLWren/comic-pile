#!/usr/bin/env bash
set -Eeuo pipefail

# Preserve the worker's public fail-fast contract before loading shared
# primitives. Guard tests intentionally exercise these checks in isolation.
: "${FACTORY_WORKER:?FACTORY_WORKER is required}"
: "${FACTORY_SOURCE:?FACTORY_SOURCE is required}"
: "${FACTORY_MODEL:?FACTORY_MODEL is required}"
: "${FACTORY_RUNTIME_MODEL:?FACTORY_RUNTIME_MODEL is required}"

# Factory selection and lease handoff must keep working even when GitHub's
# GraphQL installation bucket is exhausted. Route the small set of gh list/view
# reads used by the wrapper through REST while forwarding every other gh command
# to the real CLI unchanged.
install_factory_rest_gh() {
  local real_gh shim_dir
  real_gh="$(command -v gh)"
  shim_dir="$(mktemp -d /tmp/comic-pile-factory-gh.XXXXXX)"
  cp .github/scripts/factory-gh-rest-shim.sh "$shim_dir/gh"
  chmod +x "$shim_dir/gh"
  export FACTORY_REAL_GH="$real_gh"
  export PATH="$shim_dir:$PATH"
}
install_factory_rest_gh

# These four tiny bridges preserve the existing regression harness, which
# extracts named helper functions directly from this file. In the real worker
# they are immediately replaced when the tracked primitives are sourced below.
stage_trusted_guard() {
  local primitives definition
  primitives="$(dirname "${WORKER:-${BASH_SOURCE[0]}}")/free-model-factory-worker-primitives.sh"
  [[ -f "$primitives" ]] || primitives="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/free-model-factory-worker-primitives.sh"
  definition="$(sed -n '/^stage_trusted_guard() {/,/^}/p' "$primitives")"
  unset -f stage_trusted_guard
  eval "$definition"
  stage_trusted_guard "$@"
}

conflict_markers_present() {
  local primitives definition
  primitives="$(dirname "${WORKER:-${BASH_SOURCE[0]}}")/free-model-factory-worker-primitives.sh"
  [[ -f "$primitives" ]] || primitives="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/free-model-factory-worker-primitives.sh"
  definition="$(sed -n '/^conflict_markers_present() {/,/^}/p' "$primitives")"
  unset -f conflict_markers_present
  eval "$definition"
  conflict_markers_present "$@"
}

branch_folded_main_commits() {
  local primitives definition
  primitives="$(dirname "${WORKER:-${BASH_SOURCE[0]}}")/free-model-factory-worker-primitives.sh"
  [[ -f "$primitives" ]] || primitives="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/free-model-factory-worker-primitives.sh"
  definition="$(sed -n '/^branch_folded_main_commits() {/,/^}/p' "$primitives")"
  unset -f branch_folded_main_commits
  eval "$definition"
  branch_folded_main_commits "$@"
}

unclean_git_state_json() {
  local primitives definition
  primitives="$(dirname "${WORKER:-${BASH_SOURCE[0]}}")/free-model-factory-worker-primitives.sh"
  [[ -f "$primitives" ]] || primitives="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/free-model-factory-worker-primitives.sh"
  definition="$(sed -n '/^unclean_git_state_json() {/,/^}/p' "$primitives")"
  unset -f unclean_git_state_json
  eval "$definition"
  unclean_git_state_json "$@"
}

# Reuse the proven persistence/guard/provider/lease primitives as a tracked
# repository file, stopping before its legacy main loop.
source <(sed '/^ensure_owner_label$/,$d' .github/scripts/free-model-factory-worker-primitives.sh)

# A PR branch may predate the Kilo integration entirely. Stage the backend
# runner from trusted main before any checkout so cross-worker takeover never
# executes a missing or stale branch copy, mirroring the trusted guard model.
stage_trusted_kilo_helper() {
  [[ "$SOURCE" == 'kilo-auto' ]] || return 0
  TRUSTED_KILO_HELPER="${TRUSTED_KILO_HELPER:-}"
  if [[ -z "$TRUSTED_KILO_HELPER" ]]; then
    TRUSTED_KILO_HELPER="$(mktemp /tmp/comic-pile-kilo-auto-run.XXXXXX.sh)"
  fi
  cp .github/scripts/kilo-auto-factory-run.sh "$TRUSTED_KILO_HELPER"
  chmod +x "$TRUSTED_KILO_HELPER"
}

# Semantic state transitions are more privileged than the reviewed branch.
# Copy the controller and its pure policy module from trusted main before any
# checkout_target switch so a stale or contaminated PR cannot replace the
# authority code that interprets its model verdict.
stage_trusted_review_controller() {
  local trusted_dir
  trusted_dir="$(mktemp -d /tmp/comic-pile-review-controller.XXXXXX)"
  cp .github/scripts/factory-review-controller.py "$trusted_dir/factory-review-controller.py"
  cp .github/scripts/factory_review_policy.py "$trusted_dir/factory_review_policy.py"
  chmod +x "$trusted_dir/factory-review-controller.py"
  TRUSTED_REVIEW_CONTROLLER="$trusted_dir/factory-review-controller.py"
  export TRUSTED_REVIEW_CONTROLLER
}

# Keep the established OpenCode/NVIDIA implementation untouched. Kilo needs a
# small override only so it invokes the trusted helper staged from main.
eval "$(declare -f run_agent | sed '1s/^run_agent /legacy_run_agent /')"
run_agent() {
  local mode="$1" number="$2" timeout_seconds="$3"
  local target mission prompt status=0
  if [[ "$SOURCE" != 'kilo-auto' ]]; then
    legacy_run_agent "$@"
    return $?
  fi

  if [[ "$mode" == 'pr' ]]; then
    target="pull request #${number}"
    mission="Resume this PR. Inspect the exact current head, required CI, review submissions, and every inline review thread. Fix closure-critical defects and resolve or concretely rebut actionable threads. If no edits are required, decide whether the PR fully completes its declared scope and is safe to merge. End your final response with FACTORY_GATE_READY only for semantic approval, FACTORY_GATE_REJECT only when the PR is clearly unsalvageable, contaminated, obsolete, duplicate, or fundamentally incomplete, otherwise end with FACTORY_GATE_NOT_READY."
  else
    target="issue #${number}"
    mission="Implement the full closure-critical acceptance contract for this issue with code and focused tests. Do not stop at planning or optional polish."
  fi

  prompt="You are external-model Factory ${WORKER} for JoshCLWren/comic-pile. Durable worker ID: ${WORKER_ID}. Source: ${SOURCE}. Requested model or route: ${MODEL}. Runtime selector: ${RUNTIME_MODEL}. Assigned target: ${target}. Read AGENTS.md, docs/ISSUE_EXECUTION_PROTOCOL.md, docs/AUTONOMOUS_FACTORY_POLICY.md, docs/CHATGPT_FACTORY_PROMPT.md, and docs/FACTORY_GITHUB_VISIBILITY.md first. Follow the canonical product-first factory policy. ${mission} Work only on the assigned target during this agent invocation. Edit the checked-out branch, run focused validation, and use gh/GitHub when needed for review context. Do not commit or push; the wrapper persists changes. Do not switch models, providers, or routes. A provider failure is a result for this lane, not permission to fall back to another paid or unrequested route. Do not enable auto-merge, push main, touch production databases, or alter automation schedules."

  set +e
  bash "$TRUSTED_KILO_HELPER" \
    "$timeout_seconds" \
    "ComicPile Factory ${WORKER} · ${DISPLAY}" \
    "$prompt" \
    "/tmp/opencode-factory-${WORKER}.log"
  status=$?
  set -e
  return "$status"
}

select_controller_assignment() {
  local -a prs=() issues=()
  local pr_json issue_json pr_numbers issue_numbers
  local pr branch linked_issue issue

  if ! pr_json="$(gh pr list --state open --limit 200 --label "$OWNER" --json number,labels)"; then
    log "unable to query controller-leased PRs for ${OWNER}"
    return 3
  fi
  if ! pr_numbers="$(jq -r '.[] | select(([.labels[].name] | index("factory:ready")) == null) | .number' <<< "$pr_json")"; then
    log "unable to parse controller-leased PRs for ${OWNER}"
    return 3
  fi
  mapfile -t prs < <(printf '%s' "$pr_numbers")

  if (( ${#prs[@]} > 1 )); then
    log "controller invariant failed: ${OWNER} owns multiple open PRs (${prs[*]})"
    return 2
  fi

  if ! issue_json="$(gh issue list --state open --limit 300 --label "$OWNER" --json number)"; then
    log "unable to query controller-leased issues for ${OWNER}"
    return 3
  fi
  if ! issue_numbers="$(jq -r '.[].number' <<< "$issue_json")"; then
    log "unable to parse controller-leased issues for ${OWNER}"
    return 3
  fi
  mapfile -t issues < <(printf '%s' "$issue_numbers")

  if (( ${#prs[@]} == 1 )); then
    pr="${prs[0]}"
    if ! branch="$(gh pr view "$pr" --json headRefName --jq .headRefName)"; then
      log "unable to resolve branch for controller-leased PR #${pr}"
      return 3
    fi
    if [[ -z "$branch" ]]; then
      log "controller-leased PR #${pr} returned an empty branch"
      return 3
    fi
    linked_issue="$(linked_issue_from_branch "$branch")"

    for issue in "${issues[@]:-}"; do
      [[ -n "$issue" ]] || continue
      if [[ -z "$linked_issue" || "$issue" != "$linked_issue" ]]; then
        log "controller invariant failed: ${OWNER} owns PR #${pr} plus unrelated issue #${issue}"
        return 2
      fi
    done

    MODE='pr'
    NUMBER="$pr"
    BRANCH="$branch"
    return 0
  fi

  if (( ${#issues[@]} == 1 )); then
    MODE='issue'
    NUMBER="${issues[0]}"
    BRANCH="factory/${WORKER}-${NUMBER}-${BRANCH_SUFFIX}"
    return 0
  fi

  if (( ${#issues[@]} > 1 )); then
    log "controller invariant failed: ${OWNER} owns multiple open issues (${issues[*]})"
    return 2
  fi

  return 1
}

ensure_owner_label
stage_trusted_guard
stage_trusted_kilo_helper
stage_trusted_review_controller
trap 'release_owned_targets session-end-handoff || true' EXIT

MODE=''
NUMBER=''
BRANCH=''

set +e
select_controller_assignment
assignment_status=$?
set -e

if (( assignment_status == 1 )); then
  log 'no control-plane assignment is leased to this worker; exiting without repo-wide selection'
  exit 0
fi

if (( assignment_status != 0 )); then
  release_owned_targets 'controller-assignment-read-failed' || true
  exit "$assignment_status"
fi

log "executing control-plane assignment: ${MODE} #${NUMBER}; runtime ${RUNTIME_MODEL}; budget ${BUDGET_SECONDS}s"
checkout_target "$MODE" "$NUMBER" "$BRANCH"

available="$(remaining)"
agent_timeout=$((available - 240))
(( agent_timeout > 3000 )) && agent_timeout=3000
if (( agent_timeout < 300 )); then
  log 'insufficient remaining budget for assigned work'
  exit 1
fi

agent_attempt=1
agent_status=0
transient_failure=0
while :; do
  set +e
  run_agent "$MODE" "$NUMBER" "$agent_timeout"
  agent_status=$?
  set -e
  log "agent exit status ${agent_status} for ${MODE} #${NUMBER}"

  if (( agent_status == 0 )); then
    transient_failure=0
    break
  fi
  if ! is_transient_agent_failure "$agent_status"; then
    transient_failure=0
    break
  fi

  transient_failure=1
  log 'transient provider/runtime interruption on the pinned model; refusing to switch models'
  [[ -z "$(git status --porcelain)" ]] || break
  (( agent_attempt < MAX_AGENT_ATTEMPTS )) || break
  (( $(remaining) > 600 )) || break

  sleep_for="$TRANSIENT_BACKOFF_SECONDS"
  max_sleep=$(( $(remaining) - 540 ))
  (( sleep_for > max_sleep )) && sleep_for="$max_sleep"
  (( sleep_for > 0 )) && sleep "$sleep_for"
  agent_attempt=$((agent_attempt + 1))
  available="$(remaining)"
  agent_timeout=$((available - 240))
  (( agent_timeout > 3000 )) && agent_timeout=3000
  (( agent_timeout >= 300 )) || break
done

if [[ "$MODE" == 'issue' ]]; then
  if pr="$(persist_issue_pr "$NUMBER" "$BRANCH")"; then
    log "opened/updated PR #${pr} for issue #${NUMBER}"
    release_target "$NUMBER" 'factory:review' 'pr-opened-handoff' 'issue'
    release_target "$pr" 'factory:review' 'pr-opened-handoff' 'pr'
  elif (( transient_failure == 1 )); then
    log "issue #${NUMBER} produced no changes because the model was interrupted; releasing the lease"
    release_target "$NUMBER" 'factory:building' 'transient-model-interruption' 'issue'
  else
    log "issue #${NUMBER} produced no persisted change; releasing the lease for another worker/model attempt"
    release_target "$NUMBER" 'factory:building' 'no-persisted-change-handoff' 'issue'
  fi
  log "assignment complete; remaining budget $(remaining)s"
  exit 0
fi

if persist_pr_changes "$NUMBER" "$BRANCH"; then
  log "pushed repairs to PR #${NUMBER}; releasing for exact-head review"
  release_pr_and_issue "$NUMBER" "$BRANCH" 'factory:review' 'repairs-pushed-handoff'
  log "assignment complete; remaining budget $(remaining)s"
  exit 0
fi

if (( transient_failure == 1 )); then
  release_pr_and_issue "$NUMBER" "$BRANCH" 'factory:review' 'transient-model-interruption'
  log "assignment complete; remaining budget $(remaining)s"
  exit 0
fi

if (( agent_status != 0 )); then
  release_pr_and_issue "$NUMBER" "$BRANCH" 'factory:review' 'review-agent-failed'
  log "assignment complete; remaining budget $(remaining)s"
  exit 0
fi

review_log="/tmp/opencode-factory-${WORKER}.log"
verdict=''
if grep -Eq '^FACTORY_GATE_READY[[:space:]]*$' "$review_log"; then
  verdict='approve'
elif grep -Eq '^FACTORY_GATE_REJECT[[:space:]]*$' "$review_log"; then
  verdict='reject'
elif grep -Eq '^FACTORY_GATE_NOT_READY[[:space:]]*$' "$review_log"; then
  verdict='repair'
fi

if [[ -z "$verdict" ]]; then
  log "review model did not emit a recognized terminal verdict for PR #${NUMBER}; leaving it in review"
  release_pr_and_issue "$NUMBER" "$BRANCH" 'factory:review' 'missing-semantic-verdict'
  log "assignment complete; remaining budget $(remaining)s"
  exit 0
fi

log "submitting ${verdict} semantic verdict for PR #${NUMBER} at reviewed head ${EXPECTED_HEAD} to the trusted review controller"
python3 "$TRUSTED_REVIEW_CONTROLLER" review \
  --worker "$WORKER" \
  --pr "$NUMBER" \
  --reviewed-head "$EXPECTED_HEAD" \
  --verdict "$verdict" \
  --review-log "$review_log"

log "assignment complete; remaining budget $(remaining)s"
