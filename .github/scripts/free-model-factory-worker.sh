#!/usr/bin/env bash
set -Eeuo pipefail

WORKER="${FACTORY_WORKER:?FACTORY_WORKER is required}"
SOURCE="${FACTORY_SOURCE:?FACTORY_SOURCE is required}"
MODEL="${FACTORY_MODEL:?FACTORY_MODEL is required}"
RUNTIME_MODEL="${FACTORY_RUNTIME_MODEL:?FACTORY_RUNTIME_MODEL is required}"
DISPLAY="${FACTORY_DISPLAY:-$MODEL}"
BRANCH_SUFFIX="${FACTORY_BRANCH_SUFFIX:-free-model}"
OWNER="factory:${WORKER}"
WORKER_ID="opencode-free-model-factory-${WORKER}"
BUDGET_SECONDS="${FACTORY_BUDGET_SECONDS:-6000}"
MAX_AGENT_ATTEMPTS="${FREE_MODEL_AGENT_MAX_ATTEMPTS:-2}"
TRANSIENT_BACKOFF_SECONDS="${FREE_MODEL_TRANSIENT_BACKOFF_SECONDS:-20}"
STARTED="$(date +%s)"
DEADLINE=$((STARTED + BUDGET_SECONDS))
OWNER_RE='^factory:(unowned|local|[1-9][0-9]*)$'
STAGE_RE='^factory:(building|review|changes-requested|ci|ready|blocked)$'
SKIP_PRS=()

log() { printf '[factory:%s][source:%s][model:%s] %s\n' "$WORKER" "$SOURCE" "$MODEL" "$*"; }
remaining() { echo $((DEADLINE - $(date +%s))); }
contains_skip_pr() {
  local needle="$1" item
  for item in "${SKIP_PRS[@]:-}"; do
    [[ "$item" == "$needle" ]] && return 0
  done
  return 1
}

replace_labels() {
  local number="$1" owner="$2" stage="$3"
  local labels target
  labels="$(gh api "repos/${GITHUB_REPOSITORY}/issues/${number}/labels?per_page=100" --jq '[.[].name]')"
  target="$(jq -c --arg owner "$owner" --arg stage "$stage" --arg owner_re "$OWNER_RE" --arg stage_re "$STAGE_RE" '
    map(select((test($owner_re)|not) and (test($stage_re)|not) and . != "factory"))
    + ["factory", $owner, $stage] | unique' <<< "$labels")"
  gh api --method PUT "repos/${GITHUB_REPOSITORY}/issues/${number}/labels" \
    --input - <<< "{\"labels\":${target}}" >/dev/null
}

current_stage() {
  local number="$1" fallback="$2" labels stage
  labels="$(gh api "repos/${GITHUB_REPOSITORY}/issues/${number}/labels?per_page=100" --jq '[.[].name]')"
  stage="$(jq -r --arg stage_re "$STAGE_RE" '[.[] | select(test($stage_re))][0] // empty' <<< "$labels")"
  if [[ -n "$stage" ]]; then printf '%s\n' "$stage"; else printf '%s\n' "$fallback"; fi
}

release_target() {
  local number="$1" fallback_stage="$2" reason="$3" target_kind="${4:-target}"
  local stage epoch marker
  stage="$(current_stage "$number" "$fallback_stage")"
  replace_labels "$number" 'factory:unowned' "$stage"
  epoch="$(date +%s)"
  marker="<!-- comic-pile-factory-claim-released-v3:${target_kind}-${number}:${WORKER_ID}:${epoch}:${reason} -->"
  gh issue comment "$number" --body "$marker" >/dev/null 2>&1 || true
  log "released ${target_kind} #${number} to factory:unowned at ${stage} (${reason})"
}

release_owned_targets() {
  local reason="$1" number stage
  while IFS= read -r number; do
    [[ -n "$number" ]] || continue
    stage="$(current_stage "$number" 'factory:building')"
    release_target "$number" "$stage" "$reason" 'issue'
  done < <(gh issue list --state open --limit 300 --label "$OWNER" --json number --jq '.[].number')

  while IFS= read -r number; do
    [[ -n "$number" ]] || continue
    stage="$(current_stage "$number" 'factory:review')"
    release_target "$number" "$stage" "$reason" 'pr'
  done < <(gh pr list --state open --limit 200 --label "$OWNER" --json number --jq '.[].number')
}

linked_issue_from_branch() {
  sed -nE 's#^factory/[0-9]+-([0-9]+)-.*$#\1#p' <<< "$1"
}

release_pr_and_issue() {
  local pr="$1" branch="$2" stage="$3" reason="$4" issue
  release_target "$pr" "$stage" "$reason" 'pr'
  issue="$(linked_issue_from_branch "$branch")"
  if [[ -n "$issue" ]]; then
    state="$(gh issue view "$issue" --json state --jq .state 2>/dev/null || true)"
    if [[ "$state" == 'OPEN' ]]; then
      release_target "$issue" "$stage" "$reason" 'issue'
    fi
  fi
}

ensure_owner_label() {
  if ! gh api "repos/${GITHUB_REPOSITORY}/labels/factory%3A${WORKER}" >/dev/null 2>&1; then
    gh api --method POST "repos/${GITHUB_REPOSITORY}/labels" \
      -f name="$OWNER" \
      -f color='5319e7' \
      -f description="Owned by fixed-model Factory ${WORKER}: ${DISPLAY}" >/dev/null
    log "created ${OWNER}"
  fi
}

choose_existing_pr() {
  gh pr list --state open --limit 200 --json number,labels,updatedAt | jq -r \
    --arg owner "$OWNER" '
      map(select(([.labels[].name] | index($owner)) != null))
      | sort_by(.updatedAt)
      | .[].number'
}

choose_unowned_pr() {
  gh pr list --state open --limit 200 --label 'factory:unowned' --json number,isDraft,updatedAt | jq -r '
    map(select(.isDraft == false)) | sort_by(.updatedAt) | .[].number'
}

choose_issue() {
  local labels=("$@")
  local args=(issue list --state open --limit 300 --json number,labels,createdAt)
  local label
  for label in "${labels[@]}"; do args+=(--label "$label"); done
  gh "${args[@]}" | jq -r --arg owner_re "$OWNER_RE" '
    map(select(.number != 679 and .number != 1093 and .number != 1109))
    | map(select((([.labels[].name | select(test($owner_re) and . != "factory:unowned")] | length) == 0)))
    | sort_by(.createdAt) | reverse | .[].number'
}

choose_backlog_zero_child() {
  gh api --paginate "repos/${GITHUB_REPOSITORY}/issues/679/sub_issues?per_page=100" 2>/dev/null \
    | jq -s -r --arg owner_re "$OWNER_RE" '
      add
      | map(select(.state == "open"))
      | map(select((([.labels[].name | select(test($owner_re) and . != "factory:unowned")] | length) == 0)))
      | sort_by(.number)
      | .[].number' || true
}

claim_issue() {
  local number="$1" labels target epoch marker
  labels="$(gh api "repos/${GITHUB_REPOSITORY}/issues/${number}/labels?per_page=100" --jq '[.[].name]')"
  if jq -e --arg owner_re "$OWNER_RE" \
    '[.[] | select(test($owner_re) and . != "factory:unowned")] | length > 0' \
    >/dev/null <<< "$labels"; then
    return 1
  fi
  target="$(jq -c --arg owner "$OWNER" --arg owner_re "$OWNER_RE" --arg stage_re "$STAGE_RE" '
    map(select((test($owner_re)|not) and (test($stage_re)|not) and . != "factory"))
    + ["factory", $owner, "factory:building"] | unique' <<< "$labels")"
  gh api --method PUT "repos/${GITHUB_REPOSITORY}/issues/${number}/labels" \
    --input - <<< "{\"labels\":${target}}" >/dev/null
  epoch="$(date +%s)"
  marker="<!-- comic-pile-factory-implement-claim-v3:issue-${number}:${WORKER_ID}:${epoch}:attempt-1 -->"
  gh issue comment "$number" --body "$marker" >/dev/null 2>&1 || true
}

claim_unowned_pr() {
  local number="$1" labels owner_count
  labels="$(gh api "repos/${GITHUB_REPOSITORY}/issues/${number}/labels?per_page=100" --jq '[.[].name]')"
  jq -e 'index("factory:unowned") != null' >/dev/null <<< "$labels" || return 1
  owner_count="$(jq -r --arg owner_re "$OWNER_RE" \
    '[.[] | select(test($owner_re) and . != "factory:unowned")] | length' <<< "$labels")"
  [[ "$owner_count" == "0" ]] || return 1

  replace_labels "$number" "$OWNER" 'factory:review'
  labels="$(gh api "repos/${GITHUB_REPOSITORY}/issues/${number}/labels?per_page=100" --jq '[.[].name]')"
  jq -e --arg owner "$OWNER" 'index($owner) != null' >/dev/null <<< "$labels" || return 1

  gh issue comment "$number" --body "$(printf '<!-- free-model-factory-owner:%s -->\nFactory %s adopted this unowned PR with fixed model %s via %s.\n' \
    "$WORKER" "$WORKER" "$MODEL" "$SOURCE")" >/dev/null
}

checkout_target() {
  local mode="$1" number="$2" branch="$3"
  git fetch --prune origin
  git switch --detach origin/main >/dev/null 2>&1 || true
  git reset --hard origin/main >/dev/null
  git clean -fd >/dev/null
  if git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then
    git fetch origin "$branch:$branch" --force
    git switch "$branch"
    git reset --hard "origin/$branch" >/dev/null
  else
    git switch -C "$branch" origin/main
  fi
  log "checked out ${mode} #${number} on ${branch}"
}

current_head_review_blockers() {
  local pr="$1" head="$2"
  local changes unresolved
  changes="$(gh api --paginate "repos/${GITHUB_REPOSITORY}/pulls/${pr}/reviews?per_page=100" \
    | jq -s --arg head "$head" '[.[][] | select(.state == "CHANGES_REQUESTED" and .commit_id == $head)] | length')"
  [[ "$changes" == "0" ]] || return 1
  unresolved="$(gh api graphql -F owner='JoshCLWren' -F name='comic-pile' -F number="$pr" \
    -f query='query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){pullRequest(number:$number){reviewThreads(first:100){nodes{isResolved}}}}}' \
    --jq '[.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)] | length')"
  [[ "$unresolved" == "0" ]]
}

machine_merge_gates_pass() {
  local pr="$1" expected_head="$2" info head
  info="$(gh pr view "$pr" --json state,isDraft,mergeable,headRefOid)"
  [[ "$(jq -r .state <<< "$info")" == "OPEN" ]] || return 1
  [[ "$(jq -r .isDraft <<< "$info")" == "false" ]] || return 1
  [[ "$(jq -r .mergeable <<< "$info")" == "MERGEABLE" ]] || return 1
  head="$(jq -r .headRefOid <<< "$info")"
  [[ "$head" == "$expected_head" ]] || return 1
  gh pr checks "$pr" --required >/tmp/factory-required-checks 2>&1 || return 1
  current_head_review_blockers "$pr" "$head" || return 1
}

is_transient_agent_failure() {
  local status="$1"
  [[ "$status" == "124" ]] && return 0
  grep -Eiq '429|Too Many Requests|rate.?limit|overloaded|temporar(il)?y unavailable|bad gateway|gateway timeout|service unavailable|HTTP[^0-9]*(502|503|504)|ECONNRESET|ETIMEDOUT|connection reset' \
    "/tmp/opencode-factory-${WORKER}.log"
}

run_agent() {
  local mode="$1" number="$2" timeout_seconds="$3"
  local target mission prompt status=0
  if [[ "$mode" == "pr" ]]; then
    target="pull request #${number}"
    mission="Resume this PR. Inspect the exact current head, required CI, review submissions, and every inline review thread. Fix closure-critical defects and resolve or concretely rebut actionable threads. If no edits are required, decide whether the PR fully completes its declared scope and is safe to merge. End your final response with FACTORY_GATE_READY only when no semantic blocker remains; otherwise end with FACTORY_GATE_NOT_READY."
  else
    target="issue #${number}"
    mission="Implement the full closure-critical acceptance contract for this issue with code and focused tests. Do not stop at planning or optional polish."
  fi

  prompt="You are fixed-model OpenCode Factory ${WORKER} for JoshCLWren/comic-pile. Durable worker ID: ${WORKER_ID}. Source: ${SOURCE}. Pinned model: ${MODEL}. Runtime model: ${RUNTIME_MODEL}. Assigned target: ${target}. Read AGENTS.md, docs/ISSUE_EXECUTION_PROTOCOL.md, docs/AUTONOMOUS_FACTORY_POLICY.md, docs/CHATGPT_FACTORY_PROMPT.md, and docs/FACTORY_GITHUB_VISIBILITY.md first. Follow the canonical product-first factory policy. ${mission} Work only on the assigned target during this agent invocation. Edit the checked-out branch, run focused validation, and use gh/GitHub when needed for review context. Do not commit or push; the wrapper persists changes. Do not switch models, providers, or routes. A provider failure is a result for this model lane, not permission to fall back to another model. Do not enable auto-merge, push main, touch production databases, or alter automation schedules."

  timeout --signal=TERM --kill-after=30s "${timeout_seconds}s" \
    opencode run -m "$RUNTIME_MODEL" --agent build --auto --dir "$GITHUB_WORKSPACE" \
    --title "ComicPile Factory ${WORKER} · ${DISPLAY}" "$prompt" \
    2>&1 | tee "/tmp/opencode-factory-${WORKER}.log"
  status=${PIPESTATUS[0]}
  return "$status"
}

persist_issue_pr() {
  local number="$1" branch="$2" pr title body
  [[ -n "$(git status --porcelain)" ]] || return 1
  git add -A
  git commit -m "factory: advance #${number} with ${DISPLAY}"
  git push --set-upstream origin "$branch"
  pr="$(gh pr list --state open --head "$branch" --json number --jq '.[0].number // empty')"
  if [[ -z "$pr" ]]; then
    title="$(gh issue view "$number" --json title --jq .title)"
    body="$(printf 'Closes #%s.\n\nModel: %s\nSource: %s\nWorker: %s\n\nProduced by fixed-model Factory %s (%s). Normal ComicPile exact-head factory merge gates apply.\n' \
      "$number" "$MODEL" "$SOURCE" "$WORKER_ID" "$WORKER" "$DISPLAY")"
    gh pr create --base main --head "$branch" --title "$title" --body "$body" >/tmp/factory-pr-url
    pr="$(gh pr list --state open --head "$branch" --json number --jq '.[0].number')"
  fi
  replace_labels "$pr" "$OWNER" 'factory:review'
  echo "$pr"
}

persist_pr_changes() {
  local pr="$1" branch="$2"
  [[ -n "$(git status --porcelain)" ]] || return 1
  git add -A
  git commit -m "factory: advance PR #${pr} with ${DISPLAY}"
  git push origin "$branch"
  replace_labels "$pr" "$OWNER" 'factory:review'
}

ensure_owner_label
release_owned_targets 'previous-run-stale-lease'
trap 'release_owned_targets session-end-handoff || true' EXIT
log "starting fixed-model session with runtime ${RUNTIME_MODEL}; budget ${BUDGET_SECONDS}s"

while (( $(remaining) > 480 )); do
  MODE=''
  NUMBER=''
  BRANCH=''

  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] || continue
    contains_skip_pr "$candidate" && continue
    NUMBER="$candidate"
    MODE='pr'
    BRANCH="$(gh pr view "$NUMBER" --json headRefName --jq .headRefName)"
    break
  done < <(choose_existing_pr)

  if [[ -z "$NUMBER" ]]; then
    for selector in 'user-reported bug' 'bug' 'ralph-task'; do
      read -r -a labels <<< "$selector"
      while IFS= read -r candidate; do
        [[ -n "$candidate" ]] || continue
        if claim_issue "$candidate"; then
          NUMBER="$candidate"
          MODE='issue'
          BRANCH="factory/${WORKER}-${NUMBER}-${BRANCH_SUFFIX}"
          break 2
        fi
      done < <(choose_issue "${labels[@]}")
    done
  fi

  if [[ -z "$NUMBER" ]]; then
    while IFS= read -r candidate; do
      [[ -n "$candidate" ]] || continue
      contains_skip_pr "$candidate" && continue
      if claim_unowned_pr "$candidate"; then
        NUMBER="$candidate"
        MODE='pr'
        BRANCH="$(gh pr view "$NUMBER" --json headRefName --jq .headRefName)"
        log "adopted unowned PR #${NUMBER} on ${BRANCH}"
        break
      fi
    done < <(choose_unowned_pr)
  fi

  if [[ -z "$NUMBER" ]]; then
    while IFS= read -r candidate; do
      [[ -n "$candidate" ]] || continue
      if claim_issue "$candidate"; then
        NUMBER="$candidate"
        MODE='issue'
        BRANCH="factory/${WORKER}-${NUMBER}-${BRANCH_SUFFIX}"
        log "ordinary executable backlog unavailable; entering required #679 child #${NUMBER}"
        break
      fi
    done < <(choose_backlog_zero_child)
  fi

  if [[ -z "$NUMBER" ]]; then
    log 'no selectable ordinary target or unowned #679 child is currently available; refusing to report this as productive work'
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
      log "issue #${NUMBER} produced no changes because the pinned model was interrupted; releasing without marking the issue blocked"
      release_target "$NUMBER" 'factory:building' 'transient-model-interruption' 'issue'
    else
      log "issue #${NUMBER} produced no changes; releasing as blocked/unowned"
      release_target "$NUMBER" 'factory:blocked' 'no-persisted-change' 'issue'
    fi
    continue
  fi

  if persist_pr_changes "$NUMBER" "$BRANCH"; then
    log "pushed repairs to PR #${NUMBER}; review/CI must refresh"
    release_pr_and_issue "$NUMBER" "$BRANCH" 'factory:review' 'repairs-pushed-handoff'
    SKIP_PRS+=("$NUMBER")
    continue
  fi

  current="$(git rev-parse HEAD)"
  if grep -q 'FACTORY_GATE_READY' "/tmp/opencode-factory-${WORKER}.log" && \
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
    log "PR #${NUMBER} was interrupted transiently with no persisted edits; releasing the lease and selecting other work"
    release_pr_and_issue "$NUMBER" "$BRANCH" 'factory:review' 'transient-model-interruption'
  else
    log "PR #${NUMBER} is not merge-eligible now; releasing the lease for cross-worker takeover"
    release_pr_and_issue "$NUMBER" "$BRANCH" 'factory:review' 'not-merge-eligible-handoff'
  fi
  SKIP_PRS+=("$NUMBER")
done

log "session complete; remaining budget $(remaining)s"
