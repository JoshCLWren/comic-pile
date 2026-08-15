#!/usr/bin/env bash
set -Eeuo pipefail

# Reuse the battle-tested persistence, guard, lease, provider, and PR lifecycle
# functions from the current worker, but replace only its drifted selection loop.
# sed stops at the top-level invocation that begins the legacy main loop.
source <(sed '/^ensure_owner_label$/,$d' .github/scripts/free-model-factory-worker.sh)

priority_rank_jq='def priority_rank:
  ([.labels[].name] // []) as $labels
  | if ($labels | index("ralph-priority:critical")) then 4
    elif ($labels | index("ralph-priority:high")) then 3
    elif ($labels | index("ralph-priority:medium")) then 2
    elif ($labels | index("ralph-priority:low")) then 1
    else 0 end;'

issue_has_open_blocker() {
  local issue="$1" blockers
  # Native GitHub issue dependencies are authoritative when available. If the
  # endpoint is unavailable, do not manufacture a blocker from missing data.
  blockers="$(gh api --paginate "repos/${GITHUB_REPOSITORY}/issues/${issue}/dependencies/blocked_by?per_page=100" 2>/dev/null \
    | jq -s '[.[][]? | select(.state == "open")] | length' 2>/dev/null || true)"
  [[ "${blockers:-0}" != "0" ]]
}

issue_is_executable() {
  local issue="$1" metadata title
  metadata="$(gh issue view "$issue" --json title,labels --jq '{title,labels:[.labels[].name]}')" || return 1
  title="$(jq -r .title <<< "$metadata")"

  # Containers, policy/telemetry anchors, and explicitly blocked work are not
  # implementation tickets. Everything else remains eligible unless a native
  # dependency or active implementation PR proves otherwise.
  [[ "$issue" != "1093" && "$issue" != "1109" ]] || return 1
  [[ ! "$title" =~ ^(Epic:|PRD:) ]] || return 1
  jq -e '
    (.labels | index("factory:blocked") | not)
    and (.labels | index("ralph-status:blocked") | not)
  ' >/dev/null <<< "$metadata" || return 1
  issue_has_open_factory_pr "$issue" && return 1
  issue_has_open_blocker "$issue" && return 1
  return 0
}

choose_ranked_issues() {
  local mode="$1" candidate
  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] || continue
    issue_is_executable "$candidate" || continue
    printf '%s\n' "$candidate"
  done < <(
    gh issue list --state open --limit 300 --json number,title,labels,createdAt \
      | jq -r --arg mode "$mode" --arg owner_re "$OWNER_RE" "$priority_rank_jq
        map(select(.number != 1093 and .number != 1109))
        | map(select((([.labels[].name | select(test($owner_re) and . != \"factory:unowned\")] | length) == 0)))
        | map(select(
            if $mode == \"user-bug\" then
              ([.labels[].name] | index(\"user-reported\")) != null and
              ([.labels[].name] | index(\"bug\")) != null
            elif $mode == \"bug\" then
              ([.labels[].name] | index(\"bug\")) != null
            else true end
          ))
        | sort_by([priority_rank, .createdAt]) | reverse | .[].number"
  )
}

claim_from_pool() {
  local mode="$1" candidate
  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] || continue
    if claim_issue "$candidate"; then
      NUMBER="$candidate"
      MODE='issue'
      BRANCH="factory/${WORKER}-${NUMBER}-${BRANCH_SUFFIX}"
      log "leased executable ${mode} issue #${NUMBER} from the shared factory pool"
      return 0
    fi
  done < <(choose_ranked_issues "$mode")
  return 1
}

trigger_backlog_zero_discovery() {
  local token="${PR_REBASE_TOKEN:-${GH_TOKEN:-}}"
  log 'shared executable backlog is empty; triggering Chromium discovery directly'
  if GH_TOKEN="$token" gh workflow run chromium-discovery.yml --ref main >/dev/null 2>&1; then
    log 'Chromium backlog-zero discovery dispatched; no coordination issue is required'
    return 0
  fi
  log 'Chromium backlog-zero discovery could not be dispatched from this token; preserving this as an operational failure'
  return 1
}

ensure_owner_label
stage_trusted_guard
release_owned_targets 'previous-run-stale-lease'
trap 'release_owned_targets session-end-handoff || true' EXIT
log "starting shared-pool fixed-model session with runtime ${RUNTIME_MODEL}; budget ${BUDGET_SECONDS}s"

while (( $(remaining) > 480 )); do
  MODE=''
  NUMBER=''
  BRANCH=''

  # A lease held by this worker is resumable work, but branch provenance alone
  # never creates affinity. Previous sessions release their leases at handoff.
  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] || continue
    contains_skip_pr "$candidate" && continue
    NUMBER="$candidate"
    MODE='pr'
    BRANCH="$(gh pr view "$NUMBER" --json headRefName --jq .headRefName)"
    break
  done < <(choose_existing_pr)

  if [[ -z "$NUMBER" ]]; then claim_from_pool 'user-bug' || true; fi
  if [[ -z "$NUMBER" ]]; then claim_from_pool 'bug' || true; fi
  if [[ -z "$NUMBER" ]]; then claim_from_pool 'product' || true; fi

  # Existing unowned PRs are shared next-action work, but they do not outrank
  # fresh executable product issues merely because a branch already exists.
  if [[ -z "$NUMBER" ]]; then
    while IFS= read -r candidate; do
      [[ -n "$candidate" ]] || continue
      contains_skip_pr "$candidate" && continue
      if claim_unowned_pr "$candidate"; then
        NUMBER="$candidate"
        MODE='pr'
        BRANCH="$(gh pr view "$NUMBER" --json headRefName --jq .headRefName)"
        log "leased unowned PR #${NUMBER} on ${BRANCH} for cross-worker continuation"
        break
      fi
    done < <(choose_unowned_pr)
  fi

  if [[ -z "$NUMBER" ]]; then
    trigger_backlog_zero_discovery || exit 88
    break
  fi

  checkout_target "$MODE" "$NUMBER" "$BRANCH"
  available="$(remaining)"
  agent_timeout=$((available - 240))
  (( agent_timeout > 3000 )) && agent_timeout=3000
  (( agent_timeout < 300 )) && break

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
      SKIP_PRS+=("$pr")
    elif (( transient_failure == 1 )); then
      log "issue #${NUMBER} produced no changes because the model was interrupted; releasing the lease"
      release_target "$NUMBER" 'factory:building' 'transient-model-interruption' 'issue'
    else
      log "issue #${NUMBER} produced no persisted change; releasing the lease for another worker/model attempt"
      release_target "$NUMBER" 'factory:building' 'no-persisted-change-handoff' 'issue'
    fi
    continue
  fi

  if persist_pr_changes "$NUMBER" "$BRANCH"; then
    log "pushed repairs to PR #${NUMBER}; releasing for review/CI/cross-worker continuation"
    release_pr_and_issue "$NUMBER" "$BRANCH" 'factory:review' 'repairs-pushed-handoff'
    SKIP_PRS+=("$NUMBER")
    continue
  fi

  current="$(git rev-parse HEAD)"
  if [[ "$SOURCE" != 'kilo-auto' ]] && \
    grep -q 'FACTORY_GATE_READY' "/tmp/opencode-factory-${WORKER}.log" && \
    machine_merge_gates_pass "$NUMBER" "$current"; then
    log "all exact-head gates passed for PR #${NUMBER}; merging ${current}"
    gh pr merge "$NUMBER" --merge --match-head-commit "$current" --delete-branch
    issue_number="$(linked_issue_from_branch "$BRANCH")"
    if [[ -n "$issue_number" ]]; then
      state="$(gh issue view "$issue_number" --json state --jq .state 2>/dev/null || true)"
      if [[ "$state" == 'OPEN' ]]; then
        gh issue close "$issue_number" --reason completed \
          --comment "Closed after Factory ${WORKER} merged PR #${NUMBER} through the exact-head gates."
      fi
    fi
    continue
  fi

  if (( transient_failure == 1 )); then
    release_pr_and_issue "$NUMBER" "$BRANCH" 'factory:review' 'transient-model-interruption'
  else
    release_pr_and_issue "$NUMBER" "$BRANCH" 'factory:review' 'not-merge-eligible-handoff'
  fi
  SKIP_PRS+=("$NUMBER")
done

log "session complete; remaining budget $(remaining)s"