# Manager Daemon

The manager daemon (`agents/manager_daemon.py`) is an automated background process that handles task reviewing, merging, and monitoring for the manager agent.

## How It Works

The daemon runs continuously once started and performs the following operations:

### 1. Reviewing and Merging In-Review Tasks

- Queries `/api/tasks/reviewable` for tasks ready for review
- For each in_review task:
  - Runs `pytest` to verify all tests pass
  - Runs `make lint` to verify code quality
  - If both pass: merges the task branch to main
  - If either fails: marks the task `blocked` with test/lint output

### 2. Detecting Stale Workers

- Monitors worker heartbeats via the Task API
- Detects workers with no heartbeat for 20+ minutes
- Reports stale workers for manager intervention

### 3. Monitoring Task Availability

- Checks if there are pending/ready tasks
- Tracks when all tasks are complete and no workers are active

### 4. Automatic Shutdown

- Stops when all tasks are done and no active workers remain
- Writes summary logs of work completed

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

### What the Daemon Does (Automated)

- Reviewing in_review tasks
- Running tests and linting
- Merging approved tasks
- Detecting stale workers

### What the Manager Still Must Do

- **Handle blocked tasks** - Daemon marks tasks blocked, manager resolves them
- **Recover abandoned work** - Unclaim stale tasks, reassign
- **Resolve merge conflicts** - When daemon can't auto-merge
- **Launch and coordinate workers** - Manual or via Worker Pool Manager
- **Monitor for issues** - Workers reporting problems, API failures
- **Create new tasks** - When work needs to be done

### What the Manager Does NOT Do

- ❌ Never click "Auto-Merge All In-Review Tasks" button - daemon handles it
- ❌ Never manually merge tasks - daemon handles it
- ❌ Never run tests/linting on in_review tasks - daemon handles it

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
