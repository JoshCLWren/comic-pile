# Agent Workflow Patterns (Proven to Work)

Based on manager-1, manager-2, manager-3 retrospectives:

## Successful Patterns

### 1. Always Use Task API for All Work

- Never make direct file edits, even for small fixes
- Create tasks for everything (bug fixes, features, investigations, testing)
- Workers claim tasks before starting work
- 409 Conflict prevents duplicate claims automatically

### 2. Trust the Task API State

- Query `/api/tasks/ready` for available work (respects dependencies)
- Query `/api/tasks/{task_id}` for current status
- Let status_notes be visibility into worker progress
- Task API enforces one-task-per-agent via 409 Conflict

### 3. Active Monitoring (Not Passive Claims)

- Set up continuous monitoring loops that check task status every 2-5 minutes
- Watch for stale tasks (no heartbeat for 20+ minutes)
- Watch for blocked tasks that need unblocking
- Respond quickly when workers report issues
- Don't wait for user to prompt "keep polling" - monitor proactively

### 4. Delegate Immediately, Never Investigate Yourself

- When user reports any issue, create a task INSTANTLY
- NEVER investigate issues yourself - you're a coordinator, not an executor
- Workers complete tasks faster than manager investigating manually
- Examples of what to delegate:
  - "Website slow" → Create performance investigation task
  - "d10 looks horrible" → Create d10 geometry fix task
  - "404 errors" → Create task to investigate and fix
  - "Open browser and test" → Create task for testing

### 5. Worker Reliability Management

- Monitor worker health closely (heartbeat, status updates)
- Relaunch proactively when issues arise (no heartbeat for 20+ minutes)
- Check for heartbeat failures
- If worker reports blockers multiple times, intervene and ask if they need help
- Maximum 3 concurrent workers

### 6. Worktree Management

- Create all worktrees at session start before launching workers
- Verify each worktree exists and is on correct branch
- Before accepting task claim, check: `git worktree list | grep <worktree-path>`
- Only accept claim if worktree exists and path is valid
- After task completion, worker removes worktree

### 7. Manager Daemon Integration

- Manager daemon runs continuously and automatically:
  - Reviews and merges in_review tasks
  - Runs pytest and make lint
  - Detects stale workers (20+ min no heartbeat)
  - Stops when all tasks done and no active workers
- NO need to manually click "Auto-Merge All In-Review Tasks" button
- Only intervene when tasks marked `blocked` (conflicts or test failures)

### 8. Merge Conflict Handling

- Expect conflicts when multiple workers modify same file
- Use `git checkout --theirs --ours` to accept both changes
- Test after resolution to ensure nothing was lost
- Commit with clear resolution message
- All conflicts successfully resolved in manager-1 and manager-3

### 9. Browser Testing Delegation

- NEVER attempt browser testing or manual testing yourself
- Create a task: "Open browser and test [feature]" with clear test cases
- Delegate to worker agent
- Worker opens browser and performs testing
- Worker reports findings in status notes
- Managers coordinate, workers execute

## Failed Patterns to Avoid

### 1. NO Active Monitoring

- Don't just claim to monitor - actually set up polling loops
- Don't wait for user to say "keep polling"
- Manager-3 failed this and lost productivity

### 2. Direct File Edits Before Delegation

- Don't investigate issues yourself (coordinator 404, d10 geometry, etc.)
- Don't make direct file edits for any work, no matter how small
- Manager-2 initially failed this, then corrected
- Manager-3 failed this repeatedly

### 3. Worker Pool Manager Role Violation

- Worker Pool Manager NEVER reviews or merges tasks
- Manager-daemon.py handles ALL reviewing and merging
- NEVER trust worker claims without verification
- Workers can and will lie about "tests pass, linting clean"
- Worker Pool Manager retrospective shows CRITICAL FAILURE from merging broken code

### 4. Ad-Hoc Worktree Creation

- Don't create worktrees after tasks are claimed
- Don't allow tasks to be claimed without verifying worktree exists
- Create all worktrees at session start
- Manager-3 failed this with 404 errors during reassignment
