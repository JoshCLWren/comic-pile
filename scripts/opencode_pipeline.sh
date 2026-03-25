#!/usr/bin/env bash
# Multi-role pipeline for running opencode on GitHub issues.
# Each issue gets its own git worktree so workers never stomp on each other's branches.
#
# Usage (one terminal per role):
#   ./scripts/opencode_pipeline.sh init       # seed state files (run once)
#   ./scripts/opencode_pipeline.sh implement  # picks up pending issues
#   ./scripts/opencode_pipeline.sh review     # picks up implemented issues
#   ./scripts/opencode_pipeline.sh fix        # picks up reviewed issues
#   ./scripts/opencode_pipeline.sh pr         # opens PRs for fixed issues
#   ./scripts/opencode_pipeline.sh arbiter    # watchdog: resets stalemates
#   ./scripts/opencode_pipeline.sh status     # show state of all issues
#   ./scripts/opencode_pipeline.sh timesheet  # show model usage log
#
# Run multiple workers of the same role by opening more terminals — the mkdir
# lock ensures only one worker handles each issue at a time.
#
# State machine:
#   pending → implementing → implemented → reviewing → reviewed → fixing → fixed → pr_open → done
#
# Env overrides:
#   STALE_MINUTES=30    staleness threshold before arbiter resets a stage
#   POLL_SECONDS=20     how often workers poll for new work
#   IMPLEMENT_MODEL=... override first model for implementer
#   REVIEW_MODEL=...    override first model for reviewer
#   FIX_MODEL=...       override first model for fixer
#   PR_MODEL=...        override first model for PR opener

set -uo pipefail

# ── Config ────────────────────────────────────────────────────────────────────

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ISSUES=(357 361 362 358 366 367 368 370 373 379 359 360 363 365 369 371 372 376 377 378 364 380)
LOG_DIR="$REPO_ROOT/.opencode_logs"
WORKTREE_BASE="$HOME/.opencode-worktrees/comic-pile"
TIMESHEET="$LOG_DIR/timesheet.jsonl"
STALE_MINUTES="${STALE_MINUTES:-30}"
POLL_SECONDS="${POLL_SECONDS:-20}"

# Load all confirmed working models from test results (shuffled for load distribution)
# Filter out models that have error messages in their response
_MODEL_POOL=()
if [[ -f "$LOG_DIR/model_test_results.txt" ]]; then
    while IFS= read -r line; do
        model=$(echo "$line" | awk '{print $2}')
        # Skip models that have error responses (e.g., "[Error: ...]")
        if echo "$line" | grep -q "\[Error:"; then
            continue
        fi
        _MODEL_POOL+=("$model")
    done < <(grep "^OK" "$LOG_DIR/model_test_results.txt" | shuf)
fi
# Fallback hardcoded list if test results not available
if [[ ${#_MODEL_POOL[@]} -eq 0 ]]; then
    _MODEL_POOL=(
        "mistralai/mistral-medium-2505"
        "cerebras/qwen-3-235b-a22b-instruct-2507"
        "opencode/nemotron-3-super-free"
        "opencode/big-pickle"
    )
fi

IMPLEMENT_MODELS=( "${IMPLEMENT_MODEL:-}" "${_MODEL_POOL[@]}" )
REVIEW_MODELS=(    "${REVIEW_MODEL:-}"    "${_MODEL_POOL[@]}" )
FIX_MODELS=(       "${FIX_MODEL:-}"       "${_MODEL_POOL[@]}" )
PR_MODELS=(        "${PR_MODEL:-}"        "${_MODEL_POOL[@]}" )

# ── Helpers ───────────────────────────────────────────────────────────────────

state_dir()   { echo "$LOG_DIR/issue_$1"; }
state_file()  { echo "$LOG_DIR/issue_$1/state"; }
lock_dir()    { echo "$LOG_DIR/issue_$1/lock"; }
ts_file()     { echo "$LOG_DIR/issue_$1/last_updated"; }
model_file()  { echo "$LOG_DIR/issue_$1/last_model"; }
worktree_dir(){ echo "$WORKTREE_BASE/issue_$1"; }
branch_name() { echo "pipeline/issue-$1"; }

get_state() { cat "$(state_file "$1")" 2>/dev/null || echo "missing"; }

set_state() {
    local issue=$1 new_state=$2
    echo "$new_state" > "$(state_file "$issue")"
    date +%s > "$(ts_file "$issue")"
}

acquire_lock() {
    local issue=$1
    if mkdir "$(lock_dir "$issue")" 2>/dev/null; then
        echo $$ > "$(lock_dir "$issue")/pid"
        return 0
    fi
    local pid_file="$(lock_dir "$issue")/pid"
    if [[ -f "$pid_file" ]]; then
        local pid
        pid=$(cat "$pid_file")
        if ! kill -0 "$pid" 2>/dev/null; then
            rm -rf "$(lock_dir "$issue")"
            if mkdir "$(lock_dir "$issue")" 2>/dev/null; then
                echo $$ > "$(lock_dir "$issue")/pid"
                return 0
            fi
        fi
    fi
    return 1
}

release_lock() { rm -rf "$(lock_dir "$1")"; }

create_worktree() {
    local issue=$1
    local wt
    wt=$(worktree_dir "$issue")
    local branch
    branch=$(branch_name "$issue")

    mkdir -p "$WORKTREE_BASE"

    # Remove stale worktree if it exists but is broken
    if [[ -d "$wt" ]] && ! git -C "$wt" status &>/dev/null; then
        git -C "$REPO_ROOT" worktree remove "$wt" --force 2>/dev/null || rm -rf "$wt"
    fi

    if [[ ! -d "$wt" ]]; then
        # Create branch from main, add worktree
        git -C "$REPO_ROOT" worktree add "$wt" -b "$branch" main 2>/dev/null || \
        git -C "$REPO_ROOT" worktree add "$wt" "$branch" 2>/dev/null || return 1
    fi
    return 0
}

remove_worktree() {
    local issue=$1
    local wt
    wt=$(worktree_dir "$issue")
    git -C "$REPO_ROOT" worktree remove "$wt" --force 2>/dev/null || true
    git -C "$REPO_ROOT" branch -D "$(branch_name "$issue")" 2>/dev/null || true
}

timesheet_entry() {
    local issue=$1 role=$2 model=$3 start=$4 end=$5 outcome=$6
    local duration=$(( end - start ))
    printf '{"ts":"%s","issue":%s,"role":"%s","model":"%s","start":%s,"end":%s,"duration_s":%s,"outcome":"%s"}\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        "$issue" "$role" "$model" "$start" "$end" "$duration" "$outcome" \
        >> "$TIMESHEET"
}

# ── Circuit breakers ──────────────────────────────────────────────────────────

_GH_BREAKER="$LOG_DIR/.gh_circuit_breaker"
_MODEL_BLACKLIST="$LOG_DIR/.model_blacklist"
_CIRCUIT_COOLDOWN=300  # 5 minutes
_INSTANT_FAIL_THRESHOLD=10  # seconds — faster than this = auth/availability error

# GitHub circuit breaker — if gh fails, block calls for 5min then retry
gh_ok() {
    [[ ! -f "$_GH_BREAKER" ]] && return 0
    local tripped now age
    tripped=$(cat "$_GH_BREAKER" 2>/dev/null || echo 0)
    now=$(date +%s)
    age=$(( now - tripped ))
    [[ $age -ge $_CIRCUIT_COOLDOWN ]]
}

trip_gh_breaker() {
    date +%s > "$_GH_BREAKER"
    log_warn "GitHub circuit breaker TRIPPED — pausing gh calls for ${_CIRCUIT_COOLDOWN}s"
}

reset_gh_breaker() {
    rm -f "$_GH_BREAKER"
}

gh_comment() {
    local issue=$1 body=$2
    gh_ok || return 0
    if ! gh issue comment "$issue" --body "$body" 2>/dev/null; then
        trip_gh_breaker
    else
        reset_gh_breaker
    fi
}

# Model blacklist — instant failures mean auth/unavailable, skip forever this session
model_blacklisted() {
    grep -qxF "$1" "$_MODEL_BLACKLIST" 2>/dev/null
}

blacklist_model() {
    local model=$1
    echo "$model" >> "$_MODEL_BLACKLIST"
    log_warn "Blacklisted model (instant fail): $model"
}

# Cache file for open PR bodies — refreshed at most once per TTL
_PR_CACHE_FILE="$LOG_DIR/.pr_cache"
_PR_CACHE_TTL=120  # seconds

refresh_pr_cache() {
    gh_ok || return 0
    local now age=99999
    now=$(date +%s)
    if [[ -f "$_PR_CACHE_FILE" ]]; then
        local mtime
        mtime=$(stat -c %Y "$_PR_CACHE_FILE" 2>/dev/null || echo 0)
        age=$(( now - mtime ))
    fi
    if [[ $age -ge $_PR_CACHE_TTL ]]; then
        if ! gh pr list --state open --json body --jq '.[].body' 2>/dev/null > "$_PR_CACHE_FILE"; then
            trip_gh_breaker
        else
            reset_gh_breaker
        fi
    fi
}

issue_has_open_pr() {
    local issue=$1
    grep -qi "#${issue}" "$_PR_CACHE_FILE" 2>/dev/null
}

# Cache gh issue view title per issue (titles don't change)
gh_issue_title() {
    local issue=$1
    local cache="$LOG_DIR/issue_${issue}/.title_cache"
    if [[ -f "$cache" ]]; then
        cat "$cache"
        return
    fi
    gh_ok || { echo "unknown"; return; }
    local title
    title=$(gh issue view "$issue" --json title --jq '.title' 2>/dev/null || echo "unknown")
    echo "$title" > "$cache"
    echo "$title"
}

log_info()  { echo "[$(date '+%H:%M:%S')] [INFO]  $*"; }
log_ok()    { echo "[$(date '+%H:%M:%S')] [DONE]  $*"; }
log_skip()  { echo "[$(date '+%H:%M:%S')] [SKIP]  $*"; }
log_warn()  { echo "[$(date '+%H:%M:%S')] [WARN]  $*"; }
log_error() { echo "[$(date '+%H:%M:%S')] [ERROR] $*"; }

run_with_fallback() {
    local issue=$1 role=$2 prompt=$3 log=$4
    shift 4
    local models=("$@")
    local wt
    wt=$(worktree_dir "$issue")

    for model in "${models[@]}"; do
        [[ -z "$model" ]] && continue
        model_blacklisted "$model" && continue

        log_info "#$issue — trying model: $model"
        echo "$model" > "$(model_file "$issue")"

        local role_title
        role_title="$(tr '[:lower:]' '[:upper:]' <<< "${role:0:1}")${role:1}"

        local start exit_code=0
        start=$(date +%s)

        timeout 45m opencode run -m "$model" --dir "$wt" "$prompt" >> "$log" 2>&1 || exit_code=$?

        local end duration outcome
        end=$(date +%s)
        duration=$(( end - start ))

        # opencode exits 0 even on model-not-found — detect via log
        if [[ $exit_code -eq 0 ]] && grep -qiE "ProviderModelNotFoundError|Model not found|Insufficient balance" "$log" 2>/dev/null; then
            exit_code=1
        fi

        if [[ $exit_code -eq 0 ]]; then
            outcome="success"
            timesheet_entry "$issue" "$role" "$model" "$start" "$end" "$outcome"
            gh_comment "$issue" "✅ **[$role_title done]** · model: \`$model\` · duration: ${duration}s"
            return 0
        elif [[ $exit_code -eq 124 ]]; then
            outcome="timeout"
            log_warn "#$issue — $model timed out after ${duration}s, trying next"
        else
            outcome="failed"
            log_warn "#$issue — $model failed (exit $exit_code), trying next"
            # If provider reports model not found or insufficient balance, blacklist regardless of duration
            if grep -qiE "ProviderModelNotFoundError|Model not found|Insufficient balance" "$log" 2>/dev/null; then
                blacklist_model "$model"
            # Also blacklist on instant failures (auth/unavailable) to avoid repeated attempts
            elif [[ $duration -le $_INSTANT_FAIL_THRESHOLD ]]; then
                blacklist_model "$model"
            fi
        fi

        timesheet_entry "$issue" "$role" "$model" "$start" "$end" "$outcome"
    done

    log_error "#$issue — all models exhausted for role: $role"
    return 1
}

# ── Role: init ────────────────────────────────────────────────────────────────

cmd_init() {
    mkdir -p "$LOG_DIR" "$WORKTREE_BASE"

    # Clean up stale worktrees from previous runs
    git -C "$REPO_ROOT" worktree prune 2>/dev/null || true

    # Reset session state: circuit breakers and model blacklist
    rm -f "$_GH_BREAKER" "$_MODEL_BLACKLIST"

    local seeded=0 skipped=0

    for issue in "${ISSUES[@]}"; do
        mkdir -p "$(state_dir "$issue")"

        refresh_pr_cache
        if issue_has_open_pr "$issue"; then
            if [[ "$(get_state "$issue")" != "done" ]]; then
                set_state "$issue" "done"
                remove_worktree "$issue"
                log_skip "#$issue — PR already open, marking done"
            fi
            skipped=$(( skipped + 1 ))
            continue
        fi

        if [[ ! -f "$(state_file "$issue")" ]] || [[ "$(get_state "$issue")" == "missing" ]]; then
            set_state "$issue" "pending"
            log_info "#$issue — initialized as pending"
            seeded=$(( seeded + 1 ))
        else
            log_skip "#$issue — already has state: $(get_state "$issue")"
        fi
    done

    echo ""
    echo "Init complete. Seeded: $seeded  Skipped (PR exists): $skipped"
    echo "Worktrees will be created at: $WORKTREE_BASE"
}

# ── Role: status ──────────────────────────────────────────────────────────────

cmd_status() {
    printf "%-8s  %-16s  %-42s  %s\n" "ISSUE" "STATE" "LAST MODEL" "AGE"
    printf "%-8s  %-16s  %-42s  %s\n" "-----" "-----" "----------" "---"
    local now
    now=$(date +%s)

    for issue in "${ISSUES[@]}"; do
        local state age_str="" model_str=""
        state=$(get_state "$issue")
        local mf tsf
        mf=$(model_file "$issue")
        tsf=$(ts_file "$issue")
        [[ -f "$mf" ]] && model_str=$(cat "$mf")
        if [[ -f "$tsf" ]]; then
            local ts age
            ts=$(cat "$tsf")
            age=$(( (now - ts) / 60 ))
            age_str="${age}m ago"
        fi
        printf "%-8s  %-16s  %-42s  %s\n" "#$issue" "$state" "$model_str" "$age_str"
    done

    echo ""
    if [[ -f "$TIMESHEET" ]]; then
        echo "Sessions: $(wc -l < "$TIMESHEET")  Successes: $(grep -c '"outcome":"success"' "$TIMESHEET" || echo 0)  Failures: $(grep -c '"outcome":"failed"' "$TIMESHEET" || echo 0)  Timeouts: $(grep -c '"outcome":"timeout"' "$TIMESHEET" || echo 0)"
    fi

    echo ""
    echo "Active worktrees:"
    git -C "$REPO_ROOT" worktree list 2>/dev/null | grep "pipeline/issue" || echo "  none"
}

# ── Role: implement ───────────────────────────────────────────────────────────

cmd_implement() {
    log_info "Implementer online — models: ${IMPLEMENT_MODELS[*]}"
    while true; do
        local claimed=0
        for issue in "${ISSUES[@]}"; do
            [[ "$(get_state "$issue")" != "pending" ]] && continue
            acquire_lock "$issue" || continue

            set_state "$issue" "implementing"
            local title
            title=$(gh_issue_title "$issue")
            log_info "#$issue — creating worktree and implementing: $title"

            if ! create_worktree "$issue"; then
                log_error "#$issue — failed to create worktree, resetting to pending"
                set_state "$issue" "pending"
                release_lock "$issue"
                continue
            fi

            local wt log
            wt=$(worktree_dir "$issue")
            log="$(state_dir "$issue")/implement.log"

            gh_comment "$issue" "## 🚀 Pipeline: Implementation starting
**Branch:** \`$(branch_name "$issue")\`
**Worktree:** \`$wt\`"

            local prompt
            prompt="You are implementing a fix for GitHub issue #${issue} in the comic-pile repo.
The repo is already checked out in your working directory.

1. Read the issue in full: gh issue view ${issue}
2. Understand the existing code before changing anything — read relevant files first
3. Implement the fix following EVERY acceptance criterion in the issue
4. Run: make lint — must pass with zero errors
5. Run: make pytest — must pass with ≥96% coverage
6. Commit your changes: git add -A && git commit -m 'fix: <description> (closes #${issue})'
7. Write a brief summary of every file you changed and why

STANDARDS:
- No Any types (ruff ANN401)
- Mobile-first, touch targets ≥44px for UI changes
- Update docs/changelog.md
- Do NOT open a PR — stop after committing

Start immediately. Do not ask questions."

            if run_with_fallback "$issue" "implement" "$prompt" "$log" "${IMPLEMENT_MODELS[@]}"; then
                set_state "$issue" "implemented"
                log_ok "#$issue — implemented, ready for review"
            else
                set_state "$issue" "pending"
                log_error "#$issue — all models failed, reset to pending"
            fi

            release_lock "$issue"
            claimed=$(( claimed + 1 ))
            break
        done

        [[ $claimed -eq 0 ]] && sleep "$POLL_SECONDS"
    done
}

# ── Role: review ──────────────────────────────────────────────────────────────

cmd_review() {
    log_info "Reviewer online — models: ${REVIEW_MODELS[*]}"
    while true; do
        local claimed=0
        for issue in "${ISSUES[@]}"; do
            [[ "$(get_state "$issue")" != "implemented" ]] && continue
            acquire_lock "$issue" || continue

            set_state "$issue" "reviewing"
            log_info "#$issue — reviewing"

            local wt log
            wt=$(worktree_dir "$issue")
            log="$(state_dir "$issue")/review.log"

            local prompt
            prompt="You are a HARSH code reviewer for GitHub issue #${issue} in the comic-pile repo.
The implementation is already in your working directory on branch $(branch_name "$issue").

1. Read the issue requirements in full: gh issue view ${issue}
2. Examine every change made: git diff main
3. Run make lint — report any failures
4. Run make pytest — report any failures or coverage below 96%
5. Check EVERY acceptance criterion — mark each one PASS or FAIL
6. Look hard for: missing edge cases, wrong behaviour, type errors, mobile/a11y issues, missing tests

Be thorough and critical. List every problem clearly, numbered.
If the implementation is genuinely complete and all criteria pass, write APPROVED on its own line.
Do NOT write APPROVED if any criterion is unmet or any test fails."

            if run_with_fallback "$issue" "review" "$prompt" "$log" "${REVIEW_MODELS[@]}"; then
                if grep -qE "^APPROVED$|^APPROVED\." "$log"; then
                    set_state "$issue" "fixed"
                    log_ok "#$issue — approved by reviewer, skipping fix stage"
                    gh_comment "$issue" "✅ **[Reviewer approved]** — proceeding directly to PR"
                else
                    set_state "$issue" "reviewed"
                    log_info "#$issue — review complete with critique"
                fi
            else
                set_state "$issue" "implemented"
                log_error "#$issue — all reviewers failed, reset to implemented"
            fi

            release_lock "$issue"
            claimed=$(( claimed + 1 ))
            break
        done

        [[ $claimed -eq 0 ]] && sleep "$POLL_SECONDS"
    done
}

# ── Role: fix ─────────────────────────────────────────────────────────────────

cmd_fix() {
    log_info "Fixer online — models: ${FIX_MODELS[*]}"
    while true; do
        local claimed=0
        for issue in "${ISSUES[@]}"; do
            [[ "$(get_state "$issue")" != "reviewed" ]] && continue
            acquire_lock "$issue" || continue

            set_state "$issue" "fixing"
            log_info "#$issue — addressing review critique"

            local wt review_log fix_log review_summary
            wt=$(worktree_dir "$issue")
            review_log="$(state_dir "$issue")/review.log"
            fix_log="$(state_dir "$issue")/fix.log"
            review_summary=$(tail -100 "$review_log" 2>/dev/null || echo "No review log found")

            local prompt
            prompt="You are fixing code review feedback for GitHub issue #${issue} in the comic-pile repo.
The code is already in your working directory on branch $(branch_name "$issue").

The reviewer found these problems:
---
${review_summary}
---

Your tasks:
1. Address EVERY numbered problem the reviewer listed
2. Run make lint — must pass
3. Run make pytest — must pass with ≥96% coverage
4. Commit your changes: git add -A && git commit -m 'fix: address review feedback for #${issue}'
5. Write a brief summary of what you changed to address each critique point

Do not skip any critique item. Do not open a PR. Do not ask questions."

            if run_with_fallback "$issue" "fix" "$prompt" "$fix_log" "${FIX_MODELS[@]}"; then
                set_state "$issue" "fixed"
                log_ok "#$issue — fixes applied, ready for PR"
            else
                set_state "$issue" "reviewed"
                log_error "#$issue — all fixers failed, reset to reviewed"
            fi

            release_lock "$issue"
            claimed=$(( claimed + 1 ))
            break
        done

        [[ $claimed -eq 0 ]] && sleep "$POLL_SECONDS"
    done
}

# ── Role: pr ──────────────────────────────────────────────────────────────────

cmd_pr() {
    log_info "PR opener online — models: ${PR_MODELS[*]}"
    while true; do
        local claimed=0
        for issue in "${ISSUES[@]}"; do
            [[ "$(get_state "$issue")" != "fixed" ]] && continue
            acquire_lock "$issue" || continue

            set_state "$issue" "pr_open"
            local title wt log
            title=$(gh_issue_title "$issue")
            wt=$(worktree_dir "$issue")
            log="$(state_dir "$issue")/pr.log"
            log_info "#$issue — opening PR: $title"

            local prompt
            prompt="You are opening a pull request for GitHub issue #${issue} in the comic-pile repo.
The code is in your working directory on branch $(branch_name "$issue").

Steps:
1. Verify commits exist: git log main..HEAD --oneline
2. If there are uncommitted changes, commit them first
3. Push the branch: git push -u origin HEAD
4. Open the PR:
   gh pr create --title '<concise title>' --body 'Closes #${issue}

## Summary
<2-4 bullet points of what changed>

## Test plan
<what tests were added or updated>

🤖 Generated with opencode pipeline'

Do not ask questions. Open the PR now."

            if run_with_fallback "$issue" "pr" "$prompt" "$log" "${PR_MODELS[@]}"; then
                set_state "$issue" "done"
                local pr_url
                pr_url=$(grep -o 'https://github.com[^ ]*pull[^ ]*' "$log" | tail -1 || echo "")
                log_ok "#$issue — done${pr_url:+ → $pr_url}"
                # Clean up worktree now that PR is open
                remove_worktree "$issue"
            else
                set_state "$issue" "fixed"
                log_error "#$issue — PR opener failed, reset to fixed"
            fi

            release_lock "$issue"
            claimed=$(( claimed + 1 ))
            break
        done

        [[ $claimed -eq 0 ]] && sleep "$POLL_SECONDS"
    done
}

# ── Role: arbiter ─────────────────────────────────────────────────────────────

cmd_arbiter() {
    local stale_seconds=$(( STALE_MINUTES * 60 ))
    log_info "Arbiter online — stale threshold: ${STALE_MINUTES}m, checking every 5m"

    while true; do
        local now resets=0
        now=$(date +%s)

        for issue in "${ISSUES[@]}"; do
            local state
            state=$(get_state "$issue")

            local reset_to=""
            case "$state" in
                implementing) reset_to="pending" ;;
                reviewing)    reset_to="implemented" ;;
                fixing)       reset_to="reviewed" ;;
                pr_open)      reset_to="fixed" ;;
                *)            continue ;;
            esac

            local tsf
            tsf=$(ts_file "$issue")
            [[ ! -f "$tsf" ]] && continue

            local ts age
            ts=$(cat "$tsf")
            age=$(( now - ts ))

            if [[ $age -gt $stale_seconds ]]; then
                rm -rf "$(lock_dir "$issue")"
                set_state "$issue" "$reset_to"
                local age_min=$(( age / 60 ))
                log_warn "#$issue — STALEMATE: '$state' for ${age_min}m → reset to '$reset_to'"
                gh_comment "$issue" "🔄 **[Arbiter]** stuck in \`$state\` for ${age_min}m — reset to \`$reset_to\`"
                resets=$(( resets + 1 ))
            fi
        done

        [[ $resets -eq 0 ]] && log_info "All clear"
        sleep 300
    done
}

# ── Role: timesheet ───────────────────────────────────────────────────────────

cmd_timesheet() {
    if [[ ! -f "$TIMESHEET" ]]; then
        echo "No timesheet yet."
        return
    fi

    printf "%-6s  %-10s  %-8s  %-44s  %-8s  %s\n" "TIME" "ISSUE" "ROLE" "MODEL" "DURATION" "OUTCOME"
    printf "%-6s  %-10s  %-8s  %-44s  %-8s  %s\n" "----" "-----" "----" "-----" "--------" "-------"

    while IFS= read -r line; do
        python3 -c "
import json, sys
d = json.loads('$line'.replace(\"'\", \"'\"))
print('{ts}  #{issue:<8}  {role:<8}  {model:<44}  {dur:<8}  {outcome}'.format(
    ts=d['ts'][11:16], issue=d['issue'], role=d['role'],
    model=d['model'], dur=str(d['duration_s'])+'s', outcome=d['outcome']))
" 2>/dev/null || echo "$line"
    done < "$TIMESHEET"

    echo ""
    echo "Total: $(wc -l < "$TIMESHEET")  OK: $(grep -c '"outcome":"success"' "$TIMESHEET" || echo 0)  FAIL: $(grep -c '"outcome":"failed"' "$TIMESHEET" || echo 0)  TIMEOUT: $(grep -c '"outcome":"timeout"' "$TIMESHEET" || echo 0)"
}

# ── Dispatch ──────────────────────────────────────────────────────────────────

ROLE="${1:-}"

case "$ROLE" in
    init)       cmd_init ;;
    status)     cmd_status ;;
    implement)  cmd_implement ;;
    review)     cmd_review ;;
    fix)        cmd_fix ;;
    pr)         cmd_pr ;;
    arbiter)    cmd_arbiter ;;
    timesheet)  cmd_timesheet ;;
    *)
        echo "Usage: $0 {init|status|implement|review|fix|pr|arbiter|timesheet}"
        echo ""
        echo "Workflow:"
        echo "  1. $0 init           — seed state files + clean stale worktrees"
        echo "  2. Open terminals:"
        echo "       $0 implement    — creates worktree per issue, implements"
        echo "       $0 review       — reviews in the issue's worktree"
        echo "       $0 fix          — fixes critique in the issue's worktree"
        echo "       $0 pr           — opens PR, removes worktree"
        echo "       $0 arbiter      — watchdog: resets stalemates every 5m"
        echo "  3. $0 status         — see all issue states + active worktrees"
        echo "  4. $0 timesheet      — see model usage log"
        echo ""
        echo "Scale up: open multiple terminals with the same role — they compete via locks."
        echo "Worktrees: $WORKTREE_BASE"
        exit 1
        ;;
esac
