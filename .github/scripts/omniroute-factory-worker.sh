#!/usr/bin/env bash
set -Eeuo pipefail

WORKER="16"
MODEL="${1:?model required}"
ROUTED_MODEL="omniroute/${MODEL}"
OWNER="factory:16"
WORKER_ID="opencode-omniroute-factory-16"
BUDGET_SECONDS="${FACTORY_BUDGET_SECONDS:-6000}"
STARTED="$(date +%s)"
DEADLINE=$((STARTED + BUDGET_SECONDS))
OWNER_RE='^factory:(unowned|local|([1-9]|1[0-6]))$'
STAGE_RE='^factory:(building|review|changes-requested|ci|ready|blocked)$'
SKIP_PRS=()

log() { printf '[factory:16] %s\n' "$*"; }
remaining() { echo $((DEADLINE - $(date +%s))); }
contains_skip_pr() {
  local needle="$1" item
  for item in "${SKIP_PRS[@]:-}"; do [[ "$item" == "$needle" ]] && return 0; done
  return 1
}

replace_labels() {
  local number="$1" owner="$2" stage="$3"
  local labels target
  labels="$(gh api "repos/${GITHUB_REPOSITORY}/issues/${number}/labels?per_page=100" --jq '[.[].name]')"
  target="$(jq -c --arg owner "$owner" --arg stage "$stage" --arg owner_re "$OWNER_RE" --arg stage_re "$STAGE_RE" '
    map(select((test($owner_re)|not) and (test($stage_re)|not) and . != "factory"))
    + ["factory", $owner, $stage] | unique' <<< "$labels")"
  gh api --method PUT "repos/${GITHUB_REPOSITORY}/issues/${number}/labels" --input - <<< "{\"labels\":${target}}" >/dev/null
}

choose_existing_pr() {
  gh pr list --state open --limit 200 --json number,headRefName,updatedAt | jq -r '
    map(select(.headRefName | startswith("factory/16-"))) | sort_by(.updatedAt) | .[].number'
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
    map(select(.number != 679 and .number != 1093 and .number != 1109 and .number != 1149))
    | map(select((([.labels[].name | select(test($owner_re) and . != "factory:unowned")] | length) == 0)))
    | sort_by(.createdAt) | reverse | .[].number'
}

claim_issue() {
  local number="$1" labels target
  labels="$(gh api "repos/${GITHUB_REPOSITORY}/issues/${number}/labels?per_page=100" --jq '[.[].name]')"
  if jq -e --arg owner_re "$OWNER_RE" '[.[] | select(test($owner_re) and . != "factory:unowned")] | length > 0' >/dev/null <<< "$labels"; then
    return 1
  fi
  target="$(jq -c --arg owner "$OWNER" --arg owner_re "$OWNER_RE" --arg stage_re "$STAGE_RE" '
    map(select((test($owner_re)|not) and (test($stage_re)|not) and . != "factory"))
    + ["factory", $owner, "factory:building"] | unique' <<< "$labels")"
  gh api --method PUT "repos/${GITHUB_REPOSITORY}/issues/${number}/labels" --input - <<< "{\"labels\":${target}}" >/dev/null
}

claim_unowned_pr() {
  local number="$1" labels owner_count
  labels="$(gh api "repos/${GITHUB_REPOSITORY}/issues/${number}/labels?per_page=100" --jq '[.[].name]')"
  jq -e 'index("factory:unowned") != null' >/dev/null <<< "$labels" || return 1
  owner_count="$(jq -r --arg owner_re "$OWNER_RE" '[.[] | select(test($owner_re) and . != "factory:unowned")] | length' <<< "$labels")"
  [[ "$owner_count" == "0" ]] || return 1
  replace_labels "$number" "$OWNER" 'factory:review'
  gh issue comment "$number" --body '<!-- omniroute-factory-owner:16 -->
Factory 16 adopted this previously unowned PR for the next actionable step.' >/dev/null
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
  local pr="$1" head="$2" changes unresolved
  changes="$(gh api --paginate "repos/${GITHUB_REPOSITORY}/pulls/${pr}/reviews?per_page=100" | jq -s --arg head "$head" '[.[][] | select(.state == "CHANGES_REQUESTED" and .commit_id == $head)] | length')"
  [[ "$changes" == "0" ]] || return 1
  unresolved="$(gh api graphql -F owner='JoshCLWren' -F name='comic-pile' -F number="$pr" -f query='query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){pullRequest(number:$number){reviewThreads(first:100){nodes{isResolved}}}}}' --jq '[.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)] | length')"
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
  current_head_review_blockers "$pr" "$head"
}

run_agent() {
  local mode="$1" number="$2" timeout_seconds="$3" target mission prompt status=0
  if [[ "$mode" == "pr" ]]; then
    target="pull request #${number}"
    mission="Resume this PR. Inspect the current head, required CI, reviews, and inline threads. Fix closure-critical defects. End with FACTORY_GATE_READY only when no semantic blocker remains; otherwise FACTORY_GATE_NOT_READY."
  else
    target="issue #${number}"
    mission="Implement the full closure-critical acceptance contract for this issue with code and focused tests. Do not stop at planning."
  fi
  prompt="You are OpenCode OmniRoute Factory 16 for JoshCLWren/comic-pile. Durable worker ID: ${WORKER_ID}. Routed model: ${MODEL}. Assigned target: ${target}. Read AGENTS.md, docs/ISSUE_EXECUTION_PROTOCOL.md, docs/AUTONOMOUS_FACTORY_POLICY.md, docs/CHATGPT_FACTORY_PROMPT.md, and docs/FACTORY_GITHUB_VISIBILITY.md first. User-reported product bugs outrank unrelated plumbing. ${mission} Work only on the assigned target during this invocation. Edit the checked-out branch, run focused validation, and use gh/GitHub when needed. Do not commit or push; the wrapper persists changes. Do not enable auto-merge, push main, touch production databases, or alter automation schedules."
  timeout --signal=TERM --kill-after=30s "${timeout_seconds}s" opencode run -m "$ROUTED_MODEL" --agent build --auto --dir "$GITHUB_WORKSPACE" --title "ComicPile OmniRoute Factory 16" "$prompt" 2>&1 | tee /tmp/opencode-factory-16.log
  status=${PIPESTATUS[0]}
  return "$status"
}

persist_issue_pr() {
  local number="$1" branch="$2" pr title
  [[ -n "$(git status --porcelain)" ]] || return 1
  git add -A
  git commit -m "factory: advance #${number} with OmniRoute OpenCode"
  git push --set-upstream origin "$branch"
  pr="$(gh pr list --state open --head "$branch" --json number --jq '.[0].number // empty')"
  if [[ -z "$pr" ]]; then
    title="$(gh issue view "$number" --json title --jq .title)"
    gh pr create --base main --head "$branch" --title "$title" --body "Closes #${number}.\n\nModel: ${MODEL}\nWorker: ${WORKER_ID}\nGateway: OmniRoute\n\nNormal factory merge gates apply." >/tmp/factory-pr-url
    pr="$(gh pr list --state open --head "$branch" --json number --jq '.[0].number')"
  fi
  replace_labels "$pr" "$OWNER" 'factory:review'
  echo "$pr"
}

persist_pr_changes() {
  local pr="$1" branch="$2"
  [[ -n "$(git status --porcelain)" ]] || return 1
  git add -A
  git commit -m "factory: advance PR #${pr} with OmniRoute OpenCode"
  git push origin "$branch"
  replace_labels "$pr" "$OWNER" 'factory:review'
}

log "starting through OmniRoute with ${MODEL}; budget ${BUDGET_SECONDS}s"
while (( $(remaining) > 480 )); do
  MODE=''; NUMBER=''; BRANCH=''

  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] || continue
    contains_skip_pr "$candidate" && continue
    NUMBER="$candidate"; MODE='pr'; BRANCH="$(gh pr view "$NUMBER" --json headRefName --jq .headRefName)"; break
  done < <(choose_existing_pr)

  if [[ -z "$NUMBER" ]]; then
    while IFS= read -r candidate; do
      [[ -n "$candidate" ]] || continue
      contains_skip_pr "$candidate" && continue
      if claim_unowned_pr "$candidate"; then
        NUMBER="$candidate"; MODE='pr'; BRANCH="$(gh pr view "$NUMBER" --json headRefName --jq .headRefName)"; break
      fi
    done < <(choose_unowned_pr)
  fi

  if [[ -z "$NUMBER" ]]; then
    for selector in 'user-reported bug' 'bug' 'ralph-task'; do
      read -r -a labels <<< "$selector"
      while IFS= read -r candidate; do
        [[ -n "$candidate" ]] || continue
        if claim_issue "$candidate"; then
          NUMBER="$candidate"; MODE='issue'; BRANCH="factory/16-${NUMBER}-omniroute"; break 2
        fi
      done < <(choose_issue "${labels[@]}")
    done
  fi

  [[ -n "$NUMBER" ]] || { log 'no unclaimed executable product work found'; break; }
  checkout_target "$MODE" "$NUMBER" "$BRANCH"
  available="$(remaining)"; agent_timeout=$((available - 240))
  (( agent_timeout > 3000 )) && agent_timeout=3000
  (( agent_timeout >= 300 )) || break

  set +e
  run_agent "$MODE" "$NUMBER" "$agent_timeout"
  agent_status=$?
  set -e
  log "agent exit status ${agent_status} for ${MODE} #${NUMBER}"

  if [[ "$MODE" == 'issue' ]]; then
    if pr="$(persist_issue_pr "$NUMBER" "$BRANCH")"; then
      log "opened/updated PR #${pr} for issue #${NUMBER}"; SKIP_PRS+=("$pr")
    elif (( agent_status != 0 )); then
      replace_labels "$NUMBER" 'factory:unowned' 'factory:building'
    else
      replace_labels "$NUMBER" 'factory:unowned' 'factory:blocked'
    fi
    continue
  fi

  if persist_pr_changes "$NUMBER" "$BRANCH"; then
    log "pushed repairs to PR #${NUMBER}"; SKIP_PRS+=("$NUMBER"); continue
  fi

  current="$(git rev-parse HEAD)"
  if grep -q 'FACTORY_GATE_READY' /tmp/opencode-factory-16.log && machine_merge_gates_pass "$NUMBER" "$current"; then
    gh pr merge "$NUMBER" --merge --match-head-commit "$current" --delete-branch
    issue_number="$(sed -nE 's#^factory/16-([0-9]+)-omniroute$#\1#p' <<< "$BRANCH")"
    if [[ -n "$issue_number" ]] && [[ "$(gh issue view "$issue_number" --json state --jq .state 2>/dev/null || true)" == 'OPEN' ]]; then
      gh issue close "$issue_number" --reason completed --comment "Closed after Factory 16 merged PR #${NUMBER} through the normal gates."
    fi
    continue
  fi

  SKIP_PRS+=("$NUMBER")
done

log "session complete; remaining budget $(remaining)s"
