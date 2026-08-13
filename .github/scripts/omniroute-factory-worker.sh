#!/usr/bin/env bash
set -Eeuo pipefail

MODEL="${1:?routed model required}"
WORKER="16"
WORKER_ID="opencode-omniroute-factory-16"
OWNER="factory:16"
LANE_LABEL="omniroute-experiment"
BUDGET_SECONDS="${FACTORY_BUDGET_SECONDS:-6000}"
STARTED="$(date +%s)"
DEADLINE=$((STARTED + BUDGET_SECONDS))

log() { printf '[factory:16] %s\n' "$*"; }
remaining() { echo $((DEADLINE - $(date +%s))); }

replace_labels() {
  local number="$1" stage="$2" labels target
  labels="$(gh api "repos/${GITHUB_REPOSITORY}/issues/${number}/labels?per_page=100" --jq '[.[].name]')"
  target="$(jq -c --arg owner "$OWNER" --arg stage "$stage" '
    map(select((test("^factory:(unowned|local|([1-9]|1[0-6]))$")|not) and (test("^factory:(building|review|changes-requested|ci|ready|blocked)$")|not) and . != "factory"))
    + ["factory", $owner, $stage] | unique' <<< "$labels")"
  gh api --method PUT "repos/${GITHUB_REPOSITORY}/issues/${number}/labels" --input - <<< "{\"labels\":${target}}" >/dev/null
}

choose_issue() {
  gh issue list --state open --limit 100 --label "$LANE_LABEL" --label "$OWNER" \
    --json number,createdAt | jq -r 'sort_by(.createdAt) | reverse | .[].number'
}

existing_pr_for_issue() {
  local issue="$1"
  gh pr list --state open --limit 100 --json number,headRefName | jq -r --arg prefix "factory/16-${issue}-" '
    [.[] | select(.headRefName | startswith($prefix))][0].number // empty'
}

checkout_issue_branch() {
  local issue="$1" branch="factory/16-${issue}-omniroute"
  git fetch --prune origin
  if git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then
    git fetch origin "$branch:$branch" --force
    git switch "$branch"
    git reset --hard "origin/$branch"
  else
    git switch -C "$branch" origin/main
  fi
  printf '%s' "$branch"
}

run_agent() {
  local issue="$1" timeout_seconds="$2" prompt
  prompt="You are OpenCode OmniRoute Factory 16 · Multiple Man for JoshCLWren/comic-pile. Durable worker ID: ${WORKER_ID}. Assigned issue: #${issue}. Read AGENTS.md, docs/ISSUE_EXECUTION_PROTOCOL.md, docs/AUTONOMOUS_FACTORY_POLICY.md, docs/CHATGPT_FACTORY_PROMPT.md, and docs/FACTORY_GITHUB_VISIBILITY.md first. Implement the closure-critical acceptance contract for this issue with code and focused tests. Work only on issue #${issue}. Edit the checked-out branch and validate your changes. Do not commit, push, merge, alter labels, touch production databases, or change automation schedules; the wrapper handles persistence."
  timeout --signal=TERM --kill-after=30s "${timeout_seconds}s" \
    opencode run -m "omniroute/${MODEL}" --agent build --auto --dir "$GITHUB_WORKSPACE" \
    --title "ComicPile OmniRoute Factory 16 issue ${issue}" "$prompt" \
    2>&1 | tee /tmp/opencode-factory-16.log
}

persist() {
  local issue="$1" branch="$2" pr title
  [[ -n "$(git status --porcelain)" ]] || return 1
  git add -A
  git commit -m "factory: advance #${issue} with OmniRoute"
  git push --set-upstream origin "$branch"
  pr="$(gh pr list --state open --head "$branch" --json number --jq '.[0].number // empty')"
  if [[ -z "$pr" ]]; then
    title="$(gh issue view "$issue" --json title --jq .title)"
    gh pr create --base main --head "$branch" --title "$title" \
      --body "Closes #${issue}.\n\nProduced by Factory 16 · Multiple Man through OmniRoute. Normal ComicPile review and exact-head merge gates apply."
    pr="$(gh pr list --state open --head "$branch" --json number --jq '.[0].number')"
  fi
  replace_labels "$issue" 'factory:review'
  replace_labels "$pr" 'factory:review'
  log "opened/updated PR #${pr} for issue #${issue}"
}

log "starting isolated OmniRoute experiment lane with routed model ${MODEL}"

while (( $(remaining) > 480 )); do
  issue="$(choose_issue | head -n1)"
  if [[ -z "$issue" ]]; then
    log "no open ${LANE_LABEL} issue owned by Factory 16; ending cleanly"
    break
  fi

  if pr="$(existing_pr_for_issue "$issue")" && [[ -n "$pr" ]]; then
    log "issue #${issue} already has open PR #${pr}; leaving it to normal review/merge gates"
    replace_labels "$issue" 'factory:review'
    replace_labels "$pr" 'factory:review'
    break
  fi

  replace_labels "$issue" 'factory:building'
  branch="$(checkout_issue_branch "$issue")"
  available="$(remaining)"
  timeout_seconds=$((available - 240))
  (( timeout_seconds > 3000 )) && timeout_seconds=3000
  (( timeout_seconds >= 300 )) || break

  set +e
  run_agent "$issue" "$timeout_seconds"
  status=$?
  set -e

  if persist "$issue" "$branch"; then
    continue
  fi

  if (( status != 0 )); then
    log "agent exited ${status} without persisted edits; returning issue #${issue} to building for the next run"
    replace_labels "$issue" 'factory:building'
  else
    log "agent produced no changes for issue #${issue}; marking the experiment lane item blocked"
    replace_labels "$issue" 'factory:blocked'
  fi
  break
done

log "session complete; remaining budget $(remaining)s"
