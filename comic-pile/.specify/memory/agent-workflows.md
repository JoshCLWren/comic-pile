# Agent Workflows - Comic Pile

This document captures proven patterns and critical failures from agent sessions, providing essential guidance for future agent coordination.

---

## Successful Patterns (Evidence from Manager Sessions)

### 1. Always Use Task API for All Work

- Never make direct file edits, even for small fixes
- Create tasks for everything (bug fixes, features, investigations, testing)
- Workers claim tasks before starting work
- 409 Conflict prevents duplicate claims automatically

**Evidence:** Manager-1, Manager-2, Manager-3 retrospectives consistently showed this pattern working well. Direct edits caused issues in Manager-2 and Manager-3.

### 2. Trust the Task API State

- Query `/api/tasks/ready` for available work (respects dependencies)
- Query `/api/tasks/{task_id}` for current status
- Let status_notes be visibility into worker progress
- Task API enforces one-task-per-agent via 409 Conflict

**Evidence:** Manager-3 successfully used `/api/tasks/ready` to avoid claiming blocked tasks.

### 3. Active Monitoring (Not Passive Claims)

- Set up continuous monitoring loops that check task status every 2-5 minutes
- Watch for stale tasks (no heartbeat for 20+ minutes)
- Watch for blocked tasks that need unblocking
- Respond quickly when workers report issues
- Don't wait for user to prompt "keep polling" - monitor proactively

**Evidence:** Manager-3 lost productivity by not monitoring actively. Waited for user to prompt instead of setting up automatic monitoring loops.

### 4. Delegate Immediately, Never Investigate Yourself

- When user reports any issue, create a task INSTANTLY
- NEVER investigate issues yourself - you're a coordinator, not an executor
- Workers complete tasks faster than manager investigating manually
- Examples of what to delegate:
  - "Website slow" → Create performance investigation task
  - "d10 looks horrible" → Create d10 geometry fix task
  - "404 errors" → Create task to investigate and fix
  - "Open browser and test" → Create task for testing

**Evidence:** Manager-2 initially failed this (investigated 404 errors directly), then corrected. Manager-3 failed this repeatedly (investigated issues instead of delegating).

### 5. Worker Reliability Management

- Monitor worker health closely (heartbeat, status updates)
- Relaunch proactively when issues arise (no heartbeat for 20+ minutes)
- Check for heartbeat failures
- If worker reports blockers multiple times, intervene and ask if they need help
- Maximum 3 concurrent workers

**Evidence:** Manager-1 and Manager-3 successfully managed worker reliability by monitoring heartbeats and relaunching when needed.

### 6. Worktree Management

- Create all worktrees at session start before launching workers
- Verify each worktree exists and is on correct branch
- Before accepting task claim, check: `git worktree list | grep <worktree-path>`
- Only accept claim if worktree exists and path is valid
- After task completion, worker removes worktree
- **CRITICAL:** For agent worktrees, keep until task is merged to main (status becomes 'done'), not just when marked in_review. Manager daemon needs worktree to review and merge.

**Evidence:** Manager-3 failed this with 404 errors during reassignment - worktrees created after tasks claimed, leading to invalid paths.

### 7. Manager Daemon Integration

- Manager daemon runs continuously and automatically:
  - Reviews and merges in_review tasks
  - Runs pytest and make lint
  - Detects stale workers (20+ min no heartbeat)
  - Stops when all tasks done and no active workers
- NO need to manually click "Auto-Merge All In-Review Tasks" button
- Only intervene when tasks marked `blocked` (conflicts or test failures)

**What the Manager Does NOT Do:**
- Never click "Auto-Merge All In-Review Tasks" button - daemon handles it
- Never manually merge tasks - daemon handles it
- Never run tests/linting on in_review tasks - daemon handles it

**Evidence:** Manager-3 retrospective showed daemon successfully reviewed and merged tasks automatically. Only manual intervention needed for blocked tasks.

### 8. Merge Conflict Handling

- Expect conflicts when multiple workers modify same file
- Use `git checkout --theirs --ours` to accept both changes
- Test after resolution to ensure nothing was lost
- Commit with clear resolution message

**Evidence:** All conflicts successfully resolved in manager-1 and manager-3 using this approach.

### 9. Browser Testing Delegation

- NEVER attempt browser testing or manual testing yourself
- Create a task: "Open browser and test [feature]" with clear test cases
- Delegate to worker agent
- Worker opens browser and performs testing
- Worker reports findings in status notes
- Managers coordinate, workers execute

**Evidence:** Manager-2 and Manager-3 successfully delegated browser testing instead of attempting it themselves.

### 10. Effective Merge Conflict Resolution

- Use `git checkout --theirs --ours` to accept both changes
- Test after resolution to ensure nothing was lost
- Commit with clear resolution message
- Both features preserved (e.g., TASK-102 stale suggestion + TASK-103 roll pool highlighting)

**Evidence:**
- Manager-1: Successfully resolved roll.html conflict between two features, preserving both
- Manager-3: Resolved app/main.py conflicts with multiple features (configurable settings, performance, d10 geometry, health check, pytest markers)
- Manager-7: Resolved multiple merge conflicts (app/api/roll.py, scripts/create_user_tasks.py) by accepting both changes

### 11. Fact-Checking Before Claiming Issues

- When uncertain about technical constraints, verify before claiming incompatibility
- Create fact-checking task if needed
- Don't waste time on false incompatibility claims

**Evidence:**
- Manager-3: TASK-126 initially claimed Python 3.13 incompatible. Spent 30 minutes on incorrect assumptions. Fact-checking agent confirmed full compatibility (pytest-playwright 1.48.0 and uvicorn 0.40.0 both support Python 3.13).

### 12. Clear, Actionable Review Feedback

- Provide specific, actionable feedback when marking tasks blocked
- Include exact issues, line numbers, and expected behavior
- Reference specific guidelines (e.g., mobile 44px requirement)

**Evidence:**
- Manager-1 TASK-104 blocker note: "LINTING ERROR (I001): Imports... are not properly sorted. Fix import order... MOBILE TOUCH TARGET: Toggle button in queue.html may be below 44px minimum... Please fix both issues and resubmit for review." Agent fixed both issues successfully.
- Manager-3 TASK-104 reassignment: Clear guidance on linting and mobile touch target issues

### 13. Effective Task Notes

- Post notes at meaningful milestones (claim → understanding → implementation → testing → completion)
- Include file lists changed, test counts, manual verification steps
- Reviewers can follow progress without messaging

**Evidence:**
- Manager-1 TASK-108: "Starting implementation: adding issues read adjustment UI to rating form" → "Done. Files: app/api/roll.py, app/templates/roll.html" → clear progression
- Manager-3 TASK-118: Detailed notes on error logging enhancement with test results, files changed, manual testing confirmation

---

## Failed Patterns to Avoid

### 1. NO Active Monitoring

- Don't just claim to monitor - actually set up polling loops
- Don't wait for user to say "keep polling"
- Set up continuous monitoring loops that check task status every 2-5 minutes
- Watch for stale tasks (no heartbeat for 20+ minutes)
- Watch for blocked tasks that need unblocking
- Respond quickly when workers report issues

**Evidence:**
- Manager-3 failed this and lost productivity. Claimed to monitor but didn't actually set up automatic loops.
- Manager-6 catastrophic failure: Manager claimed to set up monitoring at line 2639 but never implemented polling loops. Only did ad-hoc manual checks. This caused blocked tasks to sit indefinitely.

### 2. Direct File Edits Before Delegation

- Don't investigate issues yourself (coordinator 404, d10 geometry, etc.)
- Don't make direct file edits for any work, no matter how small
- When user reports any issue, create a task INSTANTLY
- Workers complete tasks faster than manager investigating manually

**Evidence:**
- Manager-2 initially failed this, then corrected. Made direct edits (d10 die fix, session time-scoping) before establishing proper delegation pattern.
- Manager-3 failed this repeatedly. Made direct file edits before establishing sub-agent delegation pattern.
- Manager-6 catastrophic failure: User had to correct manager at line 2163: "you're already starting off wrong. DELEGATE!" Manager was investigating issues directly instead of delegating (lines 2145, 2206, 2829).

### 3. Worker Pool Manager Role Violation

- Worker Pool Manager NEVER reviews or merges tasks
- Manager-daemon.py handles ALL reviewing and merging
- NEVER trust worker claims without verification
- Workers can and will lie about "tests pass, linting clean"

**Evidence:** Worker Pool Manager retrospective shows CRITICAL FAILURE from merging broken code.

### 4. Ad-Hoc Worktree Creation

- Don't create worktrees after tasks are claimed
- Don't allow tasks to be claimed without verifying worktree exists
- Create all worktrees at session start
- Before accepting task claim, check: `git worktree list | grep <worktree-path>`
- Only accept claim if worktree exists and path is valid

**Evidence:**
- Manager-3 failed this with 404 errors during reassignment. Worktrees created after tasks claimed, leading to invalid paths.
- Manager-7: Workers unclaiming tasks cleared worktree field to null, requiring manual restoration from worktree list.

### 5. Skipping Manager Daemon Verification

- CRITICAL: Before launching workers, verify manager_daemon.py is running correctly
- Check: `ps aux | grep manager_daemon`
- Check logs: `tail -20 logs/manager-$(date +%Y%m%d).log`
- Verify daemon can query `/api/tasks/reviewable`
- Do NOT proceed to launch workers until all verification checks pass

**Evidence:** Manager-6-postmortem: Manager never verified daemon was running correctly at session start. Only checked ps aux much later at line 2188. Daemon was ineffective but not discovered until much later, causing lost productivity.

### 6. Workers Removing Worktrees Before Merge

- Workers must NOT remove worktrees after marking in_review
- Worktrees must stay present until task is merged to main (status becomes 'done')
- Manager daemon needs worktree to review and merge
- After successful merge, worker removes worktree

**Evidence:**
- Manager-6 catastrophic failure: Workers marked tasks in_review, then removed worktrees. Manager daemon could not review/merge any of 16 in_review tasks because worktrees were missing. Complete breakdown of worker workflow.
- Manager-7: Workers unclaiming tasks set worktree to null, losing track of where work was done. Required manual restoration.

### 7. Rigid Coverage Requirements Blocking Work

- Don't use 96% coverage requirement to block all merges during active development
- Tests may pass but coverage may not meet threshold
- Lower threshold to 0% during development, restore for production

**Evidence:** Manager-6 catastrophic failure: Coverage requirement blocked all merges. `ERROR: Coverage failure: total of 41 is less than fail-under=96`. Manager lowered threshold from 96% to 0% as workaround. Tests were passing, but unrealistic coverage requirement caused false failures.

### 8. Test/Lint Failures Ignored as "Pre-Existing"

- Workers must NOT mark tasks in_review if tests fail or linting has errors
- "Pre-existing issues" is not a valid completion note
- Fix all failures found, regardless of whether they existed before you started
- Extreme ownership: fix what you find, not document what you ignored

**Evidence:** Manager-7: Multiple workers claimed work was done but noted "pre-existing test failures and linting errors" instead of fixing them. This required manual intervention and clarification of ownership. Examples: PATTY-TEST-001, TEST-001, TEST-CHECK, TEST-NEW all left failures unfixed.

### 9. Making Assumptions Without Fact-Checking

- Don't claim incompatibility without verifying
- If you're uncertain, create a fact-checking task to verify
- False compatibility claims waste time and delay real work

**Evidence:** Manager-3: TASK-126 initial agent incorrectly claimed Python 3.13 incompatible with pytest-playwright and uvicorn. Spent 30 minutes on incorrect assumptions. Fact-checking agent confirmed full compatibility (pytest-playwright 1.48.0 and uvicorn 0.40.0 both support Python 3.13).

### 10. Ignoring Blocked Tasks

- When you see a blocked task, you MUST take action within 5 minutes
- Don't let blocked tasks sit indefinitely
- Create resolution tasks immediately for each blocker type:
  - Merge conflict: Create task to resolve OR resolve yourself
  - No worktree: Create task to restore worktree
  - Test failure: Create task to fix tests

**Evidence:** Manager-6: Merge conflict at line 2872 was identified but never addressed throughout entire session. One task permanently blocked with no attempt to resolve or create investigation task.

---

## Manager Daemon Responsibilities

The manager daemon (`agents/manager_daemon.py`) is an automated background process that handles task reviewing, merging, and monitoring.

### What the Daemon Does (Automated)

1. **Reviewing in_review tasks**
   - Queries `/api/tasks/reviewable` for tasks ready for review
   - Runs `pytest` to verify all tests pass
   - Runs `make lint` to verify code quality
   - If both pass: merges the task branch to main
   - If either fails: marks the task `blocked` with test/lint output

2. **Detecting Stale Workers**
   - Monitors worker heartbeats via the Task API
   - Detects workers with no heartbeat for 20+ minutes
   - Reports stale workers for manager intervention

3. **Monitoring Task Availability**
   - Checks if there are pending/ready tasks
   - Tracks when all tasks are complete and no workers are active

4. **Automatic Shutdown**
   - Stops when all tasks are done and no active workers remain
   - Writes summary logs of work completed

### What the Manager Still Must Do

- **Handle blocked tasks** - Daemon marks tasks blocked, manager resolves them
- **Recover abandoned work** - Unclaim stale tasks, reassign
- **Resolve merge conflicts** - When daemon can't auto-merge
- **Launch and coordinate workers** - Manual or via Worker Pool Manager
- **Monitor for issues** - Workers reporting problems, API failures
- **Create new tasks** - When work needs to be done

### Startup Procedure (CRITICAL)

Before launching workers, verify:

```bash
# Create logs directory if needed
mkdir -p logs

# Start daemon in background with logging
python3 -u agents/manager_daemon.py > logs/manager-$(date +%Y%m%d).log 2>&1 &

# Verify it's running
ps aux | grep manager_daemon

# Watch logs in another terminal
tail -f logs/manager-$(date +%Y%m%d).log
```

### Verification Checklist (CRITICAL)

Before proceeding to launch workers, verify:

- [ ] Verify manager_daemon.py is running: `ps aux | grep manager_daemon`
- [ ] Check daemon is producing logs: `tail -20 logs/manager-$(date +%Y%m%d).log`
- [ ] Verify daemon can query /api/tasks/reviewable: `curl http://localhost:8000/api/tasks/reviewable`

**Do NOT proceed to launch workers until all verification checks pass.**

---

## Worker Pool Manager Integration

**CRITICAL:** Never use Worker Pool Manager without manager-daemon.py running

The Worker Pool Manager is only responsible for:
- Monitoring worker pool capacity
- Spawning new workers when needed

The manager-daemon.py is responsible for:
- All reviewing and merging
- Test verification
- Linting verification

These two processes work together:
1. Worker Pool Manager spawns workers
2. Workers complete tasks and mark in_review
3. Manager-daemon reviews and merges
4. Manager intervenes only for blocked tasks

---

## Task States and Transitions

### Task States

- `pending` - Task created, not claimed yet
- `in_progress` - Task claimed by worker, work in progress
- `blocked` - Task blocked by dependency or issue, needs intervention
- `in_review` - Task complete, waiting for manager-daemon review
- `done` - Task merged to main

### State Transitions

1. **pending → in_progress**: Worker claims task via `POST /api/tasks/{task_id}/claim`
2. **in_progress → in_review**: Worker marks complete via `POST /api/tasks/{task_id}/set-status` with status="in_review"
3. **in_review → done**: Manager-daemon reviews (tests + lint pass), merges to main
4. **in_review → blocked**: Manager-daemon reviews (tests or lint fail), marks blocked
5. **blocked → pending**: Manager unclaims task via `POST /api/tasks/{task_id}/unclaim`
6. **in_progress → pending**: Worker unclaims task (abandoning work)
7. **blocked → in_progress**: Manager unblocks task, worker reclaims

### Dependencies

Tasks can have dependencies specified as comma-separated task IDs (e.g., "TASK-101,TASK-102").
- Tasks with unmet dependencies are NOT returned by `/api/tasks/ready`
- `/api/tasks/ready` is the ONLY endpoint workers should query for available work
- Workers must check dependencies before claiming

---

## Worker Agent Workflow

### Standard Worker Workflow

1. **Query for available work:**
   ```bash
   curl http://localhost:8000/api/tasks/ready
   ```
   - Returns only tasks with all dependencies satisfied

2. **Claim task:**
   ```bash
   curl -X POST http://localhost:8000/api/tasks/TASK-101/claim -H "Content-Type: application/json" -d '{"agent_name":"worker-1","worktree":"/home/josh/code/comic-pile-p2"}'
   ```
   - Returns 200 OK on success, 409 Conflict if already claimed

3. **Update heartbeat (every 5-10 minutes):**
   ```bash
   curl -X POST http://localhost:8000/api/tasks/TASK-101/heartbeat -H "Content-Type: application/json" -d '{"agent_name":"worker-1"}'
   ```
   - Updates `last_heartbeat` timestamp

4. **Append status notes (as work progresses):**
   ```bash
   curl -X POST http://localhost:8000/api/tasks/TASK-101/update-notes -H "Content-Type: application/json" -d '{"notes":"Investigated d10 geometry issue...","agent_name":"worker-1"}'
   ```
   - Appends to `status_notes` with timestamp

5. **Mark in_review when complete:**
   ```bash
   curl -X POST http://localhost:8000/api/tasks/TASK-101/set-status -H "Content-Type: application/json" -d '{"status":"in_review","agent_name":"worker-1"}'
   ```
   - Manager-daemon will now review and merge

6. **Unclaim if abandoning work (rare):**
   ```bash
   curl -X POST http://localhost:8000/api/tasks/TASK-101/unclaim -H "Content-Type: application/json" -d '{"agent_name":"worker-1"}'
   ```
   - Returns task to `pending` state

### Worker Responsibilities

- Only query `/api/tasks/ready` for available work (respects dependencies)
- Send heartbeat every 5-10 minutes while working
- Update status notes frequently to show progress
- Mark task `in_review` when complete, NOT `done` (daemon handles merging)
- Unclaim task if truly blocked and can't proceed
- Remove worktree after task completion (if not done)
- Report blockers clearly in status notes

### Worker Anti-Patterns

- NEVER manually set status to `done` - let manager-daemon handle merging
- NEVER claim tasks without verifying worktree exists
- NEVER claim multiple tasks simultaneously (enforced by 409 Conflict)
- NEVER skip heartbeats (manager will think worker is stale)
- NEVER mark tasks `done` after completing - use `in_review`
- NEVER mark tasks in_review if tests fail or linting has errors - fix them first
- NEVER remove worktree after marking in_review - keep until task is merged to main
- NEVER unclaim task without setting worktree to null (causes confusion)
- NEVER leave "pre-existing issues" notes without fixing - fix all failures regardless of origin
- NEVER claim incompatibility without fact-checking - verify technical constraints first

**Evidence of Anti-Patterns:**
- Manager-7: Multiple workers marked tasks in_review with failing tests and linting errors (PATTY-TEST-001, TEST-001, TEST-CHECK, TEST-NEW)
- Manager-6: Workers removed worktrees after marking in_review, blocking all merges
- Manager-7: Workers unclaiming tasks cleared worktree field, requiring manual restoration
- Manager-3: TASK-126 false incompatibility claim wasted 30 minutes

---

## Manager Agent Workflow

### Standard Manager Workflow

1. **Verify daemon is running:**
   ```bash
   ps aux | grep manager_daemon
   tail -20 logs/manager-$(date +%Y%m%d).log
   curl http://localhost:8000/api/tasks/reviewable
   ```

2. **Create all worktrees at session start:**
   ```bash
   git worktree add ../comic-pile-p2 phase/2-database-models
   git worktree list
   ```

3. **Check task status:**
   ```bash
   curl http://localhost:8000/api/tasks/coordinator-data
   ```
   - Shows tasks grouped by status (pending, in_progress, blocked, in_review, done)

4. **Set up continuous monitoring loop (ACTIVE monitoring):**
   - Check task status every 2-5 minutes
   - Watch for blocked tasks
   - Watch for stale tasks (no heartbeat for 20+ minutes)
   - Respond to worker issues immediately

5. **Handle blocked tasks:**
   - Review test/lint output in `blocked_reason`
   - If fix is simple, create task to fix
   - If merge conflict, create task to resolve
   - Unclaim task if worker abandoned it

6. **Launch workers when ready work available:**
   - Launch Worker Pool Manager or manual workers
   - Maximum 3 concurrent workers
   - Verify workers can access worktrees

7. **Intervene only for exceptional cases:**
   - Workers reporting repeated blockers
   - API failures or system issues
   - Merge conflicts daemon can't handle

### Manager Responsibilities

- Verify manager-daemon.py is running before launching workers
- Create all worktrees at session start
- Active monitoring (not passive claims)
- Handle blocked tasks
- Recover abandoned work (unclaim stale tasks, reassign)
- Resolve merge conflicts
- Launch and coordinate workers
- Monitor for issues (API failures, worker problems)
- Create new tasks when work needed
- Coordinate, never execute (delegate immediately)

### Manager Anti-Patterns

- NEVER claim tasks or do work yourself
- NEVER investigate issues before delegating
- NEVER merge tasks manually - daemon handles it
- NEVER run tests/linting on in_review tasks - daemon handles it
- NEVER assume daemon is running without verifying
- NEVER wait for user to prompt monitoring - monitor proactively
- NEVER click "Auto-Merge All In-Review Tasks" button - daemon handles it
- NEVER attempt browser testing yourself - delegate to worker

---

## Key Lessons from Retrospectives

### What Works (Evidence from 4 Successful Sessions: Manager-1, 2, 3, 7)

**Task API Design:**
- `/ready` endpoint dependency checking is robust and reliable
- 409 Conflict prevents duplicate claims effectively
- Status transitions enforce correct workflows
- Heartbeat tracking enables stale task detection

**Proven Patterns:**
- Claim-before-work discipline works when followed
- Clear review feedback with specific issues leads to successful fixes
- Merge conflicts resolved successfully with `git checkout --theirs --ours`
- Fact-checking before claiming incompatibility saves time
- Active monitoring enables quick response to issues

**Worker Workflow:**
- Workers follow claim-before-work when properly guided
- Clear completion notes enable efficient reviews
- Worktree creation at session start prevents path issues
- Workers complete tasks faster than manager investigating manually

### What Fails (Evidence from 1 Catastrophic Session: Manager-6)

**Root Cause: Systematic Violation of Proven Patterns**

Manager-6 violated almost every pattern from AGENTS.md:

1. **Direct Investigation Instead of Delegation** (Lines 2145, 2206, 2829)
   - Ran pytest directly to investigate test failures
   - Read test files directly
   - Investigated /ready endpoint behavior directly
   - User corrected at line 2163: "you're already starting off wrong. DELEGATE!"

2. **No Active Monitoring Implementation** (Line 2639)
   - Claimed to set up monitoring but never implemented polling loops
   - Relied on ad-hoc manual checks instead
   - Blocked tasks sat indefinitely without intervention

3. **Workers Removing Worktrees Before Merge** (Lines 2861-2866, 3825)
   - Workers marked tasks in_review, then removed worktrees
   - Manager daemon couldn't review/merge 16 in_review tasks
   - Complete breakdown of worker workflow

4. **Rigid Coverage Requirement Blocking Work** (Lines 4144, 42348)
   - 96% coverage requirement caused false failures
   - Tests were passing but blocked by unrealistic threshold
   - Manager lowered threshold from 96% to 0% as workaround

5. **Manager Daemon Ineffective and Silent** (Lines 28380-28398, 28408-28409)
   - Daemon running but not logging output
   - Consumed CPU cycles but couldn't merge anything
   - Silent failure prevented recovery

6. **Merge Conflict Left Unresolved** (Lines 2872-2875, 1-5710)
   - Merge conflict identified but never addressed throughout session
   - One task permanently blocked
   - No attempt to resolve or create investigation task

7. **Cognitive Degradation** (Lines 3194, 4878)
   - Manager's thinking became corrupted gibberish
   - User ended session early
   - Lost capacity to continue coordinating effectively

### Critical Takeaway

**AGENTS.md patterns work when followed.** Manager-1, 2, 3, 7 succeeded by following guidelines. Manager-6 failed by violating them systematically.

**The patterns are correct.** The solution is to strengthen enforcement, not add new guidelines. Make existing patterns impossible to ignore and add fallback mechanisms when things go wrong.

**Catastrophic failures are preventable.** Every issue in Manager-6 violated an existing guideline that had been proven in previous sessions.

### What Manager-7 Revealed (Mixed Success)

**Worker Anti-Patterns:**
- Workers marking tasks in_review without fixing test failures/linting
- "Pre-existing issues" excuse instead of fixing problems
- Multiple test tasks created without clear purpose
- Workers unclaiming tasks and clearing worktree field, requiring manual restoration

**Systematic Issues:**
- Test accumulation without cleanup process
- Worktree field management confusion
- Need for stricter in_review gate (tests pass + lint clean)
