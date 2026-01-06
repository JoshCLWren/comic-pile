# Manager Daemon

The manager daemon (`agents/manager_daemon.py`) is an automated background process that handles task reviewing, merging, and monitoring for the manager agent.

## How It Works

The daemon runs continuously once started and performs the following operations:

### 1. Reviewing and Merging In-Review Tasks (PRIMARY FUNCTION)

- Queries `/api/tasks/` for tasks with status `in_review`
- For each in_review task:
  1. Checks if worktree exists (skips if missing)
  2. Changes to worktree directory
  3. Runs `git fetch origin && git rebase origin/main`
  4. Runs `pytest` to verify all tests pass
  5. Runs `make lint` to verify code quality
  6. Calls `/api/tasks/{task_id}/merge-to-main` if tests/lint pass
  7. Task status changes to `done` on successful merge
  8. Marks task `blocked` if tests fail, linting fails, or merge conflict

**CRITICAL:** Workers must keep worktrees alive until task status becomes `done`. The daemon needs the worktree to review and merge.

### 2. Detecting Stale Workers

- Monitors worker heartbeats via the Task API
- Detects workers with no heartbeat for 20+ minutes
- Reports stale workers in logs (no auto-action - manager must intervene)

### 3. Auto-Unblocking Agent Confusion Tasks

- Checks for tasks with status `blocked` and blocked_reason containing "agent" or "confused"
- Automatically unclaims these tasks to allow reassignment
- Does NOT resolve merge conflicts or test failures (requires manager intervention)

### 4. Monitoring Task Availability

- Checks `/api/tasks/ready` for available work
- Reports ready task count in logs
- Tracks when all tasks are complete and no workers are active

### 5. Automatic Shutdown

- Stops when: `ready_tasks == 0` and `active_workers == 0`
- Writes summary logs of work completed (every 10 minutes)

## Startup Procedure

### Required Before Launching Workers

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

### If Daemon Not Running Correctly

```bash
# Kill any existing daemon process
pkill -f manager_daemon.py

# Restart daemon
python3 -u agents/manager_daemon.py > logs/manager-$(date +%Y%m%d).log 2>&1 &

# Re-run verification checklist
```

**Do NOT proceed to launch workers until all verification checks pass.**

## Manager's Role With Daemon Running

With the daemon active, the manager agent's responsibilities are:

### What the Daemon Does (Fully Automated)

- ✅ Reviewing all `in_review` tasks (every 2 minutes)
- ✅ Running `pytest` and `make lint` in worktrees
- ✅ Merging tasks to main via `/api/tasks/{task_id}/merge-to-main`
- ✅ Setting task status to `done` on successful merge
- ✅ Setting task status to `blocked` on failures
- ✅ Auto-unblocking agent confusion tasks
- ✅ Detecting and reporting stale workers
- ✅ Monitoring ready tasks and active workers
- ✅ Shutting down when all work is done

### What the Manager Still Must Do

- **Handle merge conflicts** - Daemon can't resolve these, manager must intervene
- **Handle test failures** - Manager creates tasks or guides workers to fix
- **Handle lint failures** - Manager creates tasks or guides workers to fix
- **Recover abandoned work** - Unclaim stale tasks (20+ min no heartbeat), reassign
- **Create resolution tasks** - When daemon marks tasks blocked
- **Launch and coordinate workers** - Manual or via Worker Pool Manager
- **Monitor for API failures** - Task API 500 errors need manual intervention
- **Create new tasks** - When work needs to be done
- **Handle edge cases** - Anything daemon can't auto-resolve

### What the Manager Does NOT Do

- ❌ Never manually merge tasks - daemon handles it
- ❌ Never run tests/linting on in_review tasks - daemon handles it
- ❌ Never call `/api/tasks/{task_id}/merge-to-main` yourself - daemon handles it
- ❌ Never click "Auto-Merge All In-Review Tasks" button - daemon handles it automatically
- ❌ Never unclaim in_review tasks - let daemon review them first

## Integration with Worker Pool Manager

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

## Evidence from Previous Sessions

From manager-3 retrospective: Manager daemon successfully reviewed and merged tasks automatically. Only manual intervention needed for blocked tasks.

From manager-6-postmortem: Manager never verified daemon was running correctly at session start. Only checked ps aux much later at line 2188. Daemon was ineffective but not discovered until much later, causing lost productivity.
