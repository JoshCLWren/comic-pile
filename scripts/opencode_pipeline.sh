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
#   ./scripts/opencode_pipeline.sh ci_check   # checks CI + CodeRabbit, posts AC to issue
#   ./scripts/opencode_pipeline.sh arbiter    # watchdog: resets stalemates
#   ./scripts/opencode_pipeline.sh status     # show state of all issues
#   ./scripts/opencode_pipeline.sh timesheet  # show model usage log
#
# Run multiple workers of the same role by opening more terminals — the mkdir
# lock ensures only one worker handles each issue at a time.
#
# State machine:
#   pending → implementing → implemented → reviewing → reviewed → fixing → fixed
#     → pr_open → pr_opened → ci_checking → done
#                                        ↘ ci_failing → fixing (loops back)
#
# Env overrides:
#   STALE_MINUTES=30    staleness threshold before arbiter resets a stage
#   POLL_SECONDS=20     how often workers poll for new work
#   IMPLEMENT_MODEL=... override first model for implementer
#   REVIEW_MODEL=...    override first model for reviewer
#   FIX_MODEL=...       override first model for fixer
#   PR_MODEL=...        override first model for PR opener
#   CI_CHECK_MODEL=...  override first model for CI checker

set -uo pipefail

# ── Config ────────────────────────────────────────────────────────────────────

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$REPO_ROOT/.opencode_logs"
WORKTREE_BASE="$HOME/.opencode-worktrees/comic-pile"
TIMESHEET="$LOG_DIR/timesheet.jsonl"
STALE_MINUTES="${STALE_MINUTES:-30}"
POLL_SECONDS="${POLL_SECONDS:-20}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-3}"      # max model attempts per run_with_fallback call
BACKOFF_SECONDS="${BACKOFF_SECONDS:-300}"  # cooldown after all models fail for an issue
_ISSUES_CACHE_TTL=600  # refresh issue list from GitHub every 10 minutes

# Dynamic issue list — populated by _load_issues, shuffled each call
ISSUES=()
_load_issues() {
    local cache="$LOG_DIR/.issues_cache"
    mkdir -p "$LOG_DIR"
    local now age=99999
    now=$(date +%s)
    if [[ -f "$cache" ]]; then
        local mtime
        mtime=$(stat -c %Y "$cache" 2>/dev/null || echo 0)
        age=$(( now - mtime ))
    fi
    if [[ $age -ge $_ISSUES_CACHE_TTL ]] || [[ ! -s "$cache" ]]; then
        gh issue list --state open --json number --jq '.[].number' 2>/dev/null > "$cache" || true
    fi
    if [[ -s "$cache" ]]; then
        mapfile -t ISSUES < <(shuf "$cache")
    fi
}

# Load all confirmed working models from test results (shuffled for load distribution)
_MODEL_POOL=()
if [[ -f "$LOG_DIR/model_test_results.txt" ]]; then
    while IFS= read -r model; do
        _MODEL_POOL+=("$model")
    done < <(grep "^OK" "$LOG_DIR/model_test_results.txt" | awk '{print $2}' | shuf)
fi
# Fallback hardcoded list if test results not available
if [[ ${#_MODEL_POOL[@]} -eq 0 ]]; then
    _MODEL_POOL=(
        "mistral/devstral-2512"
        "mistral/codestral-latest"
        "cerebras/qwen-3-235b-a22b-instruct-2507"
        "opencode/nemotron-3-super-free"
        "opencode/big-pickle"
    )
fi

IMPLEMENT_MODELS=(  "${IMPLEMENT_MODEL:-}"  "${_MODEL_POOL[@]}" )
REVIEW_MODELS=(     "${REVIEW_MODEL:-}"     "${_MODEL_POOL[@]}" )
FIX_MODELS=(        "${FIX_MODEL:-}"        "${_MODEL_POOL[@]}" )
PR_MODELS=(         "${PR_MODEL:-}"         "${_MODEL_POOL[@]}" )
CI_CHECK_MODELS=(   "${CI_CHECK_MODEL:-}"   "${_MODEL_POOL[@]}" )

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
    # Never overwrite 'done' — zombie processes finishing late must not reset terminal state
    [[ "$(get_state "$issue")" == "done" && "$new_state" != "done" ]] && return 0
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
_CIRCUIT_COOLDOWN=300   # 5 minutes
_INSTANT_FAIL_THRESHOLD=10  # seconds — faster than this = auth/availability error
_MODEL_BACKOFF_DIR="$LOG_DIR/.model_backoff"
_MODEL_BACKOFF_BASE=15   # seconds for first failure; doubles each time, no cap

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

# Per-model exponential backoff — replaces permanent blacklist
# Backoff file: $_MODEL_BACKOFF_DIR/<sanitized_model>  →  "<fail_count>\n<last_fail_ts>"
# Backoff duration: min(BASE * 2^(fail_count-1), MAX)  →  15s 30s 60s … 1hr
# Reset to zero on any success.

_model_backoff_file() {
    local safe
    safe=$(echo "$1" | tr '/:' '__')
    echo "$_MODEL_BACKOFF_DIR/$safe"
}

model_in_backoff() {
    local f
    f=$(_model_backoff_file "$1")
    [[ ! -f "$f" ]] && return 1
    local fail_count last_fail now backoff_s
    fail_count=$(sed -n '1p' "$f")
    last_fail=$(sed -n '2p' "$f")
    now=$(date +%s)
    # backoff = BASE * 2^(fail_count-1), capped at MAX
    backoff_s=$(( _MODEL_BACKOFF_BASE * (1 << (fail_count - 1)) ))
    [[ $(( now - last_fail )) -lt $backoff_s ]]
}

record_model_fail() {
    local model=$1 duration=$2
    local f
    f=$(_model_backoff_file "$model")
    mkdir -p "$_MODEL_BACKOFF_DIR"
    local fail_count=0
    [[ -f "$f" ]] && fail_count=$(sed -n '1p' "$f")
    fail_count=$(( fail_count + 1 ))
    printf '%s\n%s\n' "$fail_count" "$(date +%s)" > "$f"
    local backoff_s=$(( _MODEL_BACKOFF_BASE * (1 << (fail_count - 1)) ))
    log_warn "Model backoff #${fail_count} for $model — retry in ${backoff_s}s (duration was ${duration}s)"
}

record_model_success() {
    local f
    f=$(_model_backoff_file "$1")
    rm -f "$f"
}

# Per-issue backoff — after all models fail, cool off before retrying
_fail_ts_file() { echo "$LOG_DIR/issue_$1/.fail_ts"; }

issue_in_backoff() {
    local f
    f=$(_fail_ts_file "$1")
    [[ ! -f "$f" ]] && return 1
    local ts now age
    ts=$(cat "$f")
    now=$(date +%s)
    age=$(( now - ts ))
    [[ $age -lt $BACKOFF_SECONDS ]]
}

record_issue_fail() {
    date +%s > "$(_fail_ts_file "$1")"
    log_warn "#$1 — entered backoff for ${BACKOFF_SECONDS}s"
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
    # Shuffle per-call so concurrent workers don't all hammer the same model
    local models=()
    while IFS= read -r m; do models+=("$m"); done < <(printf '%s\n' "$@" | shuf)
    local wt
    wt=$(worktree_dir "$issue")

    local attempts=0
    for model in "${models[@]}"; do
        [[ -z "$model" ]] && continue
        model_in_backoff "$model" && continue
        [[ $attempts -ge $MAX_ATTEMPTS ]] && { log_warn "#$issue — hit MAX_ATTEMPTS ($MAX_ATTEMPTS), stopping"; break; }
        attempts=$(( attempts + 1 ))

        log_info "#$issue — trying model: $model (attempt $attempts/$MAX_ATTEMPTS)"
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
            record_model_success "$model"
            timesheet_entry "$issue" "$role" "$model" "$start" "$end" "$outcome"
            gh_comment "$issue" "✅ **[$role_title done]** · model: \`$model\` · duration: ${duration}s"
            return 0
        elif [[ $exit_code -eq 124 ]]; then
            outcome="timeout"
            log_warn "#$issue — $model timed out after ${duration}s, trying next"
            # Timeouts still count as failures for backoff — model may be overloaded
            record_model_fail "$model" "$duration"
        else
            outcome="failed"
            log_warn "#$issue — $model failed (exit $exit_code, ${duration}s), trying next"
            record_model_fail "$model" "$duration"
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

    # Kill any lingering opencode/pipeline processes from previous sessions
    # Exclude current PID and parent so init doesn't kill itself
    pgrep -f "opencode_pipeline.sh" | grep -v "^$$\$\|^$PPID\$" | xargs kill 2>/dev/null || true
    pkill -f "opencode run" 2>/dev/null || true
    sleep 2

    # Clear all stale locks (scan existing dirs — ISSUES not loaded yet)
    for _lock in "$LOG_DIR"/issue_*/lock; do
        [[ -d "$_lock" ]] || continue
        local _pid
        _pid=$(cat "$_lock/pid" 2>/dev/null)
        if ! kill -0 "$_pid" 2>/dev/null; then
            rm -rf "$_lock"
        fi
    done

    # Reset session state: circuit breakers, model backoffs, and per-issue backoffs
    rm -f "$_GH_BREAKER"
    rm -rf "$_MODEL_BACKOFF_DIR"
    rm -f "$LOG_DIR"/issue_*/.fail_ts

    # Load issue list from GitHub
    _load_issues
    log_info "Loaded ${#ISSUES[@]} open issues from GitHub"

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
    _load_issues
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
    log_info "Implementer online — ${#IMPLEMENT_MODELS[@]} models in pool"
    while true; do
        _load_issues  # refresh list from GitHub and shuffle
        local claimed=0
        for issue in "${ISSUES[@]}"; do
            [[ "$(get_state "$issue")" != "pending" ]] && continue
            issue_in_backoff "$issue" && { log_skip "#$issue — in backoff"; continue; }
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
5. Run: make pytest — aim for ≥96% coverage; commit even if tests are not fully passing yet
6. Commit your changes: git add -A && git -c core.hooksPath=/dev/null commit -m 'fix: <description> (closes #${issue})'
7. Write a brief summary of every file you changed and why

STANDARDS:
- No Any types (ruff ANN401)
- Mobile-first, touch targets ≥44px for UI changes
- Update docs/changelog.md
- Do NOT open a PR — stop after committing
- IMPORTANT: Always use 'git -c core.hooksPath=/dev/null commit' to bypass pre-commit hooks

Start immediately. Do not ask questions."

            if run_with_fallback "$issue" "implement" "$prompt" "$log" "${IMPLEMENT_MODELS[@]}"; then
                set_state "$issue" "implemented"
                log_ok "#$issue — implemented, ready for review"
            else
                set_state "$issue" "pending"
                record_issue_fail "$issue"
                log_error "#$issue — all models failed, reset to pending (backoff ${BACKOFF_SECONDS}s)"
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
    log_info "Reviewer online — ${#REVIEW_MODELS[@]} models in pool"
    while true; do
        _load_issues  # refresh and shuffle
        local claimed=0
        for issue in "${ISSUES[@]}"; do
            [[ "$(get_state "$issue")" != "implemented" ]] && continue
            acquire_lock "$issue" || continue

            set_state "$issue" "reviewing"
            log_info "#$issue — reviewing"

            local wt log
            wt=$(worktree_dir "$issue")
            log="$(state_dir "$issue")/review.log"

            local critique_file
            critique_file="$(state_dir "$issue")/review_critique.md"

            local prompt
            prompt="You are a HARSH code reviewer for GitHub issue #${issue} in the comic-pile repo.
The implementation is already in your working directory on branch $(branch_name "$issue").

1. Read the issue requirements in full: gh issue view ${issue}
2. Examine every change made: git diff main
3. Run make lint — report any failures
4. Run make pytest — report any failures or coverage below 96%
5. Check EVERY acceptance criterion — mark each one PASS or FAIL
6. Look hard for: missing edge cases, wrong behaviour, type errors, mobile/a11y issues, missing tests

IMPORTANT: When you are done with your review, write your findings to this exact file path:
${critique_file}

Use this exact format in that file:
- If everything passes: write only the single word: APPROVED
- If there are problems: write a numbered list, one problem per line

Example of approved: just write APPROVED
Example of rejected: write lines like:
1. Missing test for edge case X
2. Lint error in file Y

Do not write anything else to that file. Be thorough. Do NOT write APPROVED if any criterion is unmet."

            if run_with_fallback "$issue" "review" "$prompt" "$log" "${REVIEW_MODELS[@]}"; then
                if grep -qiE "^APPROVED$|^APPROVED\b" "$critique_file" 2>/dev/null; then
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
    log_info "Fixer online — ${#FIX_MODELS[@]} models in pool"
    while true; do
        _load_issues  # refresh and shuffle
        local claimed=0
        for issue in "${ISSUES[@]}"; do
            local cur_state
            cur_state=$(get_state "$issue")
            [[ "$cur_state" != "reviewed" && "$cur_state" != "ci_failing" ]] && continue
            acquire_lock "$issue" || continue

            set_state "$issue" "fixing"

            local wt fix_log critique_file review_summary
            wt=$(worktree_dir "$issue")
            fix_log="$(state_dir "$issue")/fix.log"

            # ci_failing uses ci_critique.md; reviewed uses review_critique.md
            if [[ "$cur_state" == "ci_failing" ]]; then
                log_info "#$issue — addressing CI failures"
                critique_file="$(state_dir "$issue")/ci_critique.md"
            else
                log_info "#$issue — addressing review critique"
                critique_file="$(state_dir "$issue")/review_critique.md"
            fi

            # Prefer clean critique file (state dir or worktree); fall back to stripped log
            local wt_critique
            wt_critique="$(worktree_dir "$issue")/$(basename "$critique_file")"
            if [[ -s "$critique_file" ]]; then
                review_summary=$(grep -v "^$" "$critique_file" | head -80)
            elif [[ -s "$wt_critique" ]]; then
                review_summary=$(grep -v "^$" "$wt_critique" | head -80)
                cp "$wt_critique" "$critique_file"
            elif [[ "$cur_state" == "ci_failing" ]]; then
                review_summary=$(sed 's/\x1b\[[0-9;]*m//g' "$(state_dir "$issue")/ci_check.log" 2>/dev/null | grep -v "^>" | grep -v "^\s*$" | tail -80 || echo "No CI critique found")
            else
                review_summary=$(sed 's/\x1b\[[0-9;]*m//g' "$(state_dir "$issue")/review.log" 2>/dev/null | grep -v "^>" | grep -v "^\s*$" | tail -80 || echo "No review found")
            fi

            local fix_context
            if [[ "$cur_state" == "ci_failing" ]]; then
                fix_context="CI checks and CodeRabbit review found these problems on the open PR"
            else
                fix_context="The code reviewer found these problems"
            fi

            local prompt
            prompt="You are fixing issues for GitHub issue #${issue} in the comic-pile repo.
The code is already in your working directory on branch $(branch_name "$issue").

${fix_context}:
---
${review_summary}
---

Your tasks:
1. Address EVERY numbered problem listed above
2. Run make lint — must pass
3. Run make pytest — aim for ≥96% coverage; commit even if not fully passing yet
4. Commit your changes: git add -A && git -c core.hooksPath=/dev/null commit -m 'fix: address CI/review feedback for #${issue}'
5. Push the branch: git push -u origin HEAD
6. Write a brief summary of what you changed for each item

IMPORTANT: Always use 'git -c core.hooksPath=/dev/null commit' to bypass pre-commit hooks.
Do not skip any item. Do not open a new PR. Do not ask questions."

            local reset_state
            [[ "$cur_state" == "ci_failing" ]] && reset_state="ci_failing" || reset_state="reviewed"

            if run_with_fallback "$issue" "fix" "$prompt" "$fix_log" "${FIX_MODELS[@]}"; then
                set_state "$issue" "fixed"
                log_ok "#$issue — fixes applied, ready for PR"
            else
                set_state "$issue" "$reset_state"
                log_error "#$issue — all fixers failed, reset to $reset_state"
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
    log_info "PR opener online — ${#PR_MODELS[@]} models in pool"
    while true; do
        _load_issues  # refresh and shuffle
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
                set_state "$issue" "pr_opened"
                local pr_url
                pr_url=$(grep -o 'https://github.com[^ ]*pull[^ ]*' "$log" | tail -1 || echo "")
                log_ok "#$issue — PR opened${pr_url:+ → $pr_url}, queued for CI check"
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

# ── Role: ci_check ────────────────────────────────────────────────────────────

cmd_ci_check() {
    log_info "CI checker online — ${#CI_CHECK_MODELS[@]} models in pool"
    while true; do
        _load_issues
        local claimed=0
        for issue in "${ISSUES[@]}"; do
            [[ "$(get_state "$issue")" != "pr_opened" ]] && continue
            acquire_lock "$issue" || continue

            set_state "$issue" "ci_checking"
            log_info "#$issue — locating open PR"

            # Find the PR number for this issue
            local pr_number
            refresh_pr_cache
            pr_number=$(gh pr list --state open --json number,body \
                --jq ".[] | select(.body | test(\"#${issue}[^0-9]\"; \"g\")) | .number" \
                2>/dev/null | head -1)

            if [[ -z "$pr_number" ]]; then
                log_warn "#$issue — no open PR found, marking done"
                set_state "$issue" "done"
                release_lock "$issue"
                continue
            fi

            log_info "#$issue — PR #$pr_number found, checking CI status"

            # Check CI — collect failing checks (exclude CodeRabbit which is advisory)
            local failing_checks
            failing_checks=$(gh pr checks "$pr_number" 2>/dev/null \
                | grep -v -iE "pass|skip|pending|neutral|CodeRabbit" \
                | grep -v "^$" || true)

            if [[ -z "$failing_checks" ]]; then
                log_ok "#$issue — PR #$pr_number all CI green → done"
                set_state "$issue" "done"
                remove_worktree "$issue"
                release_lock "$issue"
                claimed=$(( claimed + 1 ))
                break
            fi

            log_warn "#$issue — CI failures on PR #$pr_number, running analysis agent"

            local ci_critique log
            ci_critique="$(state_dir "$issue")/ci_critique.md"
            log="$(state_dir "$issue")/ci_check.log"

            local prompt
            prompt="You are a CI triage agent for GitHub issue #${issue} in the comic-pile repo.
PR #${pr_number} has failing CI checks. Your job is to analyze the failures and document
what needs to be fixed.

Steps:
1. Get the failing checks: gh pr checks ${pr_number}
2. For each failing check, find its run ID and fetch the logs:
   gh run list --branch pipeline/issue-${issue} --limit 5
   gh run view <run_id> --log-failed
3. Read any CodeRabbit review: gh pr view ${pr_number} --comments
4. Identify the root cause of each failure — is it a real bug, a flaky test, or a missing feature?

Then do TWO things:

A. Write a structured report to this exact file: ${ci_critique}
   Use this format:
   ## Failing CI Checks
   - <check name>: <root cause — real bug / flaky / missing feature>

   ## Acceptance Criteria to Fix
   1. <specific testable fix — e.g. 'Add test for X', 'Fix selector Y in component Z'>
   2. ...

   ## CodeRabbit Issues (if any)
   - <severity> <file>:<line> — <description>

   If a check is clearly flaky (test passed in other shards, no code change could affect it),
   note it as FLAKY and do NOT list it in Acceptance Criteria.

B. Post the report as a comment on the issue:
   gh issue comment ${issue} --body \"\$(cat ${ci_critique})\"

Do NOT make any code changes. Do NOT open a new PR. Analyze and report only."

            if run_with_fallback "$issue" "ci_check" "$prompt" "$log" "${CI_CHECK_MODELS[@]}"; then
                log_warn "#$issue — CI failures documented in ${ci_critique}, queued for fixing"
                set_state "$issue" "ci_failing"
            else
                log_error "#$issue — CI check agent failed, reset to pr_opened"
                set_state "$issue" "pr_opened"
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
        _load_issues  # refresh issue list each cycle
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
                ci_checking)  reset_to="pr_opened" ;;
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
    ci_check)   cmd_ci_check ;;
    arbiter)    cmd_arbiter ;;
    timesheet)  cmd_timesheet ;;
    *)
        echo "Usage: $0 {init|status|implement|review|fix|pr|ci_check|arbiter|timesheet}"
        echo ""
        echo "Workflow:"
        echo "  1. $0 init           — seed state files + clean stale worktrees"
        echo "  2. Open terminals:"
        echo "       $0 implement    — creates worktree per issue, implements"
        echo "       $0 review       — reviews in the issue's worktree"
        echo "       $0 fix          — fixes critique or CI failures"
        echo "       $0 pr           — opens PR"
        echo "       $0 ci_check     — checks CI + CodeRabbit, posts AC, routes failures back"
        echo "       $0 arbiter      — watchdog: resets stalemates every 5m"
        echo "  3. $0 status         — see all issue states + active worktrees"
        echo "  4. $0 timesheet      — see model usage log"
        echo ""
        echo "State machine:"
        echo "  pending → implementing → implemented → reviewing → reviewed"
        echo "    → fixing → fixed → pr_open → pr_opened → ci_checking → done"
        echo "                                          ↘ ci_failing → fixing (loops)"
        echo ""
        echo "Scale up: open multiple terminals with the same role — they compete via locks."
        echo "Worktrees: $WORKTREE_BASE"
        exit 1
        ;;
esac
