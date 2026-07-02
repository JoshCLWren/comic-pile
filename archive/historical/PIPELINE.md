# opencode Pipeline Documentation

## Overview and Philosophy

The opencode pipeline is an autonomous software development orchestration system that processes GitHub issues through a multi-stage workflow. The system uses git worktrees to isolate each issue's work, allowing multiple issues to be processed in parallel without conflicts. It implements a complete software development lifecycle from issue implementation to code review to pull request creation to CI validation.

## Full State Machine

```
pending → implementing → implemented → reviewing → reviewed → fixing → fixed
  → pr_open → pr_opened → ci_checking → done
                        ↘ ci_failing → fixing (loops back)
```

The pipeline consists of multiple autonomous agents that work in parallel:
- **Implementer**: Reads GitHub issues and implements code changes
- **Reviewer**: Reviews implemented code for quality and correctness
- **Fixer**: Addresses code review feedback or CI failures
- **PR Opener**: Creates GitHub pull requests for fixed implementations
- **CI Checker**: Validates PRs against CI systems and CodeRabbit reviews
- **Arbiter**: Monitors stalled work and resets deadlocked processes
- **Merger**: Automatically merges clean pipeline PRs and keeps all branches in sync

## Roles

### implement
- **What it does**: Processes pending GitHub issues by implementing the requested features/fixes
- **States handled**: `pending` → `implementing` → `implemented`
- **How to run**: `./scripts/opencode_pipeline.sh implement`
- **Key env vars**: `IMPLEMENT_MODEL`, `REVIEW_MODEL`, `FIX_MODEL`, `PR_MODEL`, `CI_CHECK_MODEL`

### review
- **What it does**: Code reviews implementations for quality and correctness
- **States handled**: `implemented` → `reviewing` → `reviewed`
- **How to run**: `./scripts/opencode_pipeline.sh review`
- **Key env vars**: Same as implement role

### fix
- **What it does**: Fixes implementation based on review feedback or CI failures
- **States handled**: `reviewed` → `fixing` → `fixed`, `ci_failing` → `fixing` → `fixed`
- **How to run**: `bash scripts/opencode_pipeline.sh fix`
- **Key env vars**: `FIX_MODEL`, `FIX_POLL`, `FIX_TIMEOUT`
- **Logic**: Picks `reviewed` or `ci_failing` issues, applies fixes via opencode, marks `fixed`

### pr
- **What it does**: Creates GitHub pull requests for fixed implementations
- **States handled**: `fixed` → `pr_open` → `pr_opened`
- **How to run**: `bash scripts/opencode_pipeline.sh pr`
- **Key env vars**: `PR_MODEL`, `PR_POLL`
- **Logic**: Reads fixed issue, creates PR via `gh pr create`, extracts PR number, transitions to `pr_opened`

### ci_check
- **What it does**: Polls GitHub CI and transitions issues based on results
- **States handled**: `pr_opened` → `ci_checking` → `done` (or `ci_failing` → back to fixing)
- **How to run**: `bash scripts/opencode_pipeline.sh ci_check`
- **Key env vars**: `CI_CHECK_POLL`
- **Logic**: Polls PR status with `gh pr checks`, routes to `done` if green, `ci_failing` if red

### arbiter
- **What it does**: Monitors the pipeline for stalled work and resets deadlocked states
- **States handled**: All (clears orphaned locks, resets stuck states)
- **How to run**: `bash scripts/opencode_pipeline.sh arbiter`
- **Key env vars**: `ARBITER_POLL`
- **Logic**: Scans issue state files for dead PIDs, clears stale locks, resets orphaned `implementing/reviewing/fixing` states to predecessor

### merger
- **What it does**: Automatically merges fully-green pipeline PRs into main, rebases other branches
- **States handled**: Reads `done` issues, merges their PRs, keeps all open branches in sync
- **How to run**: `bash scripts/opencode_pipeline.sh merger`
- **Key env vars**: `MERGER_POLL` (default 120s), `MERGER_STRATEGY` (default squash)
- **Logic**: Polls for `CLEAN/MERGEABLE` pipeline/* PRs with all CI passing, merges one per cycle, rebases remaining branches

### qa
- **What it does**: QA agent using Playwright MCP to test the live app end-to-end
- **How to run**: `bash scripts/opencode_pipeline.sh qa`
- **Key env vars**: `QA_MODEL` (default `nvidia/z-ai/glm4.7`), `QA_POLL` (default 3600s), `QA_BASE_URL`, `QA_BACKEND_URL`, `QA_SERVER_WAIT`
- **Logic**: Starts `make dev-all` on QA ports if needed, runs comprehensive Playwright tests, files `gh issue` for bugs, shuts down servers

### main_fixer
- **What it does**: Auto-fixes main-branch CI regressions
- **How to run**: `bash scripts/opencode_pipeline.sh main_fixer`
- **Key env vars**: `MAIN_FIXER_POLL` (default 600s), `MAIN_FIXER_MODEL`
- **Logic**: Surveys CI across all open PRs, when same job fails 3+ times runs opencode on main, verifies HEAD + lint, pushes main, propagates to all PR branches

### model_manager
- **What it does**: Manages the model pool — tests models, updates backoff state, evicts failed models
- **How to run**: `bash scripts/opencode_pipeline.sh model_manager`
- **Key env vars**: `MODEL_MANAGER_POLL` (default 3600s)
- **Logic**: Periodically runs `tool_test` to discover working models (Tier 1), clears expired backoff files

### tool_test
- **What it does**: One-time test: runs all candidate models, writes TOOL_OK results to pool file
- **How to run**: `bash scripts/opencode_pipeline.sh tool_test`
- **Output**: `.opencode_logs/model_tool_test_results.txt` (Tier 1 pool)
- **Use case**: Manual pool refresh or used by model_manager

## Model Pool System

**Two-tier design:**
- **Tier 1** (`.opencode_logs/model_tool_test_results.txt`): TOOL_OK — models with proven tool-use capability. Used by implement/review/fix.
- **Tier 2** (`.opencode_logs/model_test_results.txt`): All OK models. Used by pr/ci_check (lower-complexity tasks).

**Model discovery:**
```bash
_candidate_models() {
    opencode models | grep -E "^(nvidia|mistral|zai-coding-plan|opencode|cerebras)/"
    opencode models | grep -E "^openrouter/.*(:free$|-free$)"
}
```
Single source of truth: `opencode models`. Never hardcoded.

**Backoff formula:**
- Exponential: `15 * 2^(fail_count-1)` seconds, capped at 21600s (6h)
- Rate-limit: flat 3h backoff (detected by error regex)
- Files: `.opencode_logs/.model_backoff/<model>.txt` with first line = fail count or `ratelimit`, second line = unix timestamp

**Eviction:**
When a model hits the 6h cap, it's removed from pool files and re-tested by model_manager.

**Cleanup:**
`model_in_backoff()` auto-deletes expired files before checking — fixes stale backoff bugs.

## Git Worktrees

Each issue gets an isolated git worktree to enable parallel work without conflicts.

- **Location**: `~/.opencode-worktrees/comic-pile/issue_N`
- **Branch**: `pipeline/issue-N` (created from main)
- **Lifecycle**: Created on first claim, shared across all roles, cleaned up when issue reaches `done`
- **Design benefit**: Multiple workers can work on different issues in parallel without file system conflicts

## Quick Start

**Initialization:**
```bash
bash scripts/opencode_pipeline.sh init  # Creates log dirs, initializes state
```

**Start workers (recommended counts):**
```bash
# Health monitor (singleton)
bash scripts/opencode_pipeline.sh arbiter &

# Model manager (singleton)
bash scripts/opencode_pipeline.sh model_manager &

# Issue processing workers
for i in {1..16}; do bash scripts/opencode_pipeline.sh implement &; done
for i in {1..4}; do bash scripts/opencode_pipeline.sh review &; done
for i in {1..4}; do bash scripts/opencode_pipeline.sh fix &; done
for i in {1..5}; do bash scripts/opencode_pipeline.sh pr &; done
for i in {1..8}; do bash scripts/opencode_pipeline.sh ci_check &; done

# Traffic roles (singletons)
bash scripts/opencode_pipeline.sh merger &
bash scripts/opencode_pipeline.sh qa &
bash scripts/opencode_pipeline.sh main_fixer &

# Monitor
bash scripts/opencode_pipeline.sh status
```

**Scale factors:**
- **CPU-bound roles** (implement, review, fix): Scale with model availability and CPU
- **I/O-bound roles** (pr, ci_check, merger, qa): Can run many in parallel (GitHub API rate-limited)

## Monitoring

### Status command
```bash
bash scripts/opencode_pipeline.sh status
```
Reports: issue state counts, worker counts, lock health, model pool health, time since last success, slowest issues.

### Timesheet
```bash
bash scripts/opencode_pipeline.sh timesheet
```
Per-model stats: success count, failure count, timeout count, success rate, average duration.

### Key metrics
- **Healthy**: 90%+ success rate, steady issue throughput, no backlog of > 50 pending issues
- **Stalled**: 0% success for > 5 min, all models in backoff, workers dead but states not reset
- **Red flag**: `(git -C repo) is dirty` errors (uncommitted files blocking workdir), lock files not clearing, same issue stuck >10 min in one state

### Log files
- `.opencode_logs/issue_N/state` — current state
- `.opencode_logs/issue_N/<role>.log` — opencode output for that role
- `.opencode_logs/merger.log`, `.opencode_logs/qa.log`, `.opencode_logs/main_fixer.log` — traffic roles
- `.opencode_logs/timesheet.jsonl` — per-run outcomes (ts, issue, role, model, duration_s, outcome)
- `.opencode_logs/.model_backoff/<model>.txt` — backoff state (fail_count\ntimestamp)

## Troubleshooting

### Pipeline at 0% success rate
**Check**:
1. Are workers alive? `pgrep -fa opencode_pipeline | grep -v grep | wc -l`
2. How many models in backoff? `ls .opencode_logs/.model_backoff/ | wc -l` (if >30, that's the issue)
3. Do any models work? `opencode run -m "nvidia/z-ai/glm4.7" --dir . "say hello"` (should complete in <30s)

**Fix**:
```bash
# Clear all backoffs
rm -rf .opencode_logs/.model_backoff/ && mkdir .opencode_logs/.model_backoff

# Restart workers
pkill -f "opencode_pipeline.*(implement|review|fix|pr|ci_check)"
for i in {1..16}; do bash scripts/opencode_pipeline.sh implement &; done
```

### Issue stuck for >10 minutes
**Check**: `cat .opencode_logs/issue_N/state` (what state is it in?)

**Fix**:
```bash
# Is the lock dead?
PID=$(cat .opencode_logs/issue_N/lock/pid 2>/dev/null)
kill -0 $PID 2>/dev/null || rm -rf .opencode_logs/issue_N/lock/

# Run arbiter to reset stale states
bash scripts/opencode_pipeline.sh arbiter
```

### Merger can't merge a PR
**Check**:
```bash
gh pr checks <number>  # Verify CI actually passed
git status  # Check repo isn't dirty
```

### node_modules committed to a PR branch
**Prevention**: Pre-commit hook blocks it, `.gitignore` has it.

**Fix**:
```bash
git -C ~/.opencode-worktrees/comic-pile/issue_N rm -r --cached node_modules
git -C ~/.opencode-worktrees/comic-pile/issue_N commit -m "chore: remove node_modules from tracking"
git -C ~/.opencode-worktrees/comic-pile/issue_N push origin pipeline/issue-N
```

## Architecture Philosophy

- **Parallelism**: Git worktrees + state files enable stateless workers to work on different issues concurrently
- **Resilience**: Exponential backoff prevents broken models from blocking the pipeline; arbiter clears stale locks
- **Transparency**: State files are the source of truth; any agent can inspect the pipeline without special knowledge
- **Autonomy**: Workers pick up work autonomously; no central scheduler beyond polling
- **Feedback**: Timesheet provides real-time visibility into model performance; main_fixer keeps main green
