# Worker Agent Workflow

## RALPH_MODE Detection

**Check environment variable before reading this document:**

```bash
if [ "$RALPH_MODE" = "true" ]; then
    echo "🔄 RALPH_MODE=true - Read docs/RALPH_MODE.md instead"
    # Exit and follow Ralph mode instructions
else
    echo "📋 RALPH_MODE=false - Following worker workflow"
fi
```

**If RALPH_MODE=true:**
- Stop reading this document
- Read `docs/RALPH_MODE.md` instead
- Follow autonomous iteration instructions

**If RALPH_MODE=false or unset:**
- Continue reading this document
- Follow the Task API worker workflow below

---

This document provides the complete end-to-end workflow for worker agents using the Task API system.

## Quick Reference

| Step | Action | API Call | Next Step |
|------|--------|----------|-----------|
| 1 | Claim a task | `POST /api/tasks/{task_id}/claim` | 2 |
| 2 | Create worktree | `git worktree add ../worktree-name branch` | 3 |
| 3 | Work on task | Make changes, test, commit | 4 |
| 4 | Mark in_review | `POST /api/tasks/{task_id}/set-status {"status": "in_review"}` | 5 |
| 5 | Unclaim task | `POST /api/tasks/{task_id}/unclaim` | 6 |
| 6 | Wait for merge | Manager daemon handles this | 7 |
| 7 | Remove worktree | `git worktree remove ../worktree-name` | Claim next task |

## Detailed Workflow

### 1. Claim a Task

Query for available tasks and claim one:

```bash
# Get ready tasks (respects dependencies, ordered by priority)
curl http://localhost:8000/api/tasks/ready | jq -r '.[].task_id' | head -1

# Claim a task
curl -X POST http://localhost:8000/api/tasks/TASK-101/claim \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "Alice",
    "worktree": "comic-pile-task-101"
  }'
```

**Important:**
- Returns 409 Conflict if already claimed by another agent
- Worktree path must exist (or set `SKIP_WORKTREE_CHECK=true`)
- Status changes to `in_progress`
- Set `AUTO_CREATE_WORKTREE=true` to automatically create worktrees on claim (git branch and worktree created automatically)

### 2. Create Worktree (if not exists)

Create a git worktree for isolated development:

```bash
# From main repo
cd /home/josh/code/comic-pile

# Create worktree on the phase branch
git worktree add ../comic-pile-task-101 phase/10-prd-alignment

# Or create a feature branch first
git checkout -b feature/TASK-101
git worktree add ../comic-pile-task-101 feature/TASK-101
```

**Naming convention:**
- Use task ID or descriptive name
- Example: `comic-pile-task-101`, `comic-pile-narrative-summaries`

### 3. Work on Task

Complete the task in your worktree:

```bash
# Change to worktree directory
cd ../comic-pile-task-101

# Make your changes

# Run tests
pytest

# Run linting
make lint

# Commit changes
git add .
git commit -m "feat(TASK-101): implement narrative session summaries"
```

**Send heartbeats every 5-10 minutes:**
```bash
curl -X POST http://localhost:8000/api/tasks/TASK-101/heartbeat \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "Alice"}'
```

**Update status notes at milestones:**
```bash
curl -X POST http://localhost:8000/api/tasks/TASK-101/update-notes \
  -H "Content-Type: application/json" \
  -d '{"notes": "Created narrative summary function, testing now"}'
```

### 4. Mark Task as in_review

When complete, tested, and ready for review:

```bash
curl -X POST http://localhost:8000/api/tasks/TASK-101/set-status \
  -H "Content-Type: application/json" \
  -d '{"status": "in_review"}'
```

**Requirements before marking in_review:**
- All tests pass (`pytest`)
- Linting passes (`make lint`)
- Work committed with conventional commit format
- Worktree exists and has valid changes

**What happens next:**
- Manager daemon will automatically review your worktree
- Daemon runs `pytest` and `make lint` to verify
- Daemon merges to main if tests pass
- Task status changes to `blocked` if tests fail or merge conflict
- Task status changes to `done` after successful merge

### 5. Unclaim Task

After marking in_review, unclaim to release the task:

```bash
curl -X POST http://localhost:8000/api/tasks/TASK-101/unclaim \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "Alice"}'
```

**IMPORTANT: Keep your worktree alive!**
- DO NOT remove the worktree after unclaiming
- Manager daemon needs the worktree to review and merge
- Worktree must exist until task status becomes `done`

### 6. Wait for Manager Daemon

Manager daemon (running in background) will:

1. Detect task is `in_review`
2. Change to worktree directory
3. `git fetch origin && git rebase origin/main`
4. Run `pytest`
5. Run `make lint`
6. Merge to main via `/api/tasks/{task_id}/merge-to-main`
7. Set task status to `done` on success
8. Set task status to `blocked` on failure

**Monitor task status:**
```bash
# Check task status
curl http://localhost:8000/api/tasks/TASK-101 | jq '.status'
```

**If task becomes blocked:**
- Check `blocked_reason` field
- Fix the issue in worktree
- Update status notes
- Daemon will retry automatically

### 7. Remove Worktree

Only after task status becomes `done`:

```bash
cd /home/josh/code/comic-pile

# Verify task is done
curl http://localhost:8000/api/tasks/TASK-101 | jq '.status'
# Should return "done"

# Remove worktree
git worktree remove ../comic-pile-task-101
```

## Task Status Flow

```
pending (unclaimed)
  ↓
  claim()
in_progress (you're working)
  ↓
  set-status("in_review") + unclaim()
in_review (daemon reviewing)
  ↓
  daemon merges to main
done (merged) ← Remove worktree here
```

Alternative flows:
```
in_progress → blocked (you hit dependency or confusion)
blocked → in_progress (manager unblocks)
in_review → blocked (tests fail or merge conflict)
blocked → in_review (you fix and mark again)
```

## Common Scenarios

### Scenario: Task Becomes Blocked After in_review

**Symptom:** Daemon marks task `blocked` after you set it to `in_review`

**Causes:**
- Tests failing (see `blocked_reason` for test output)
- Linting failing
- Merge conflict with main

**Resolution:**
```bash
# Check why blocked
curl http://localhost:8000/api/tasks/TASK-101 | jq '.blocked_reason'

# Fix in worktree
cd ../comic-pile-task-101

# Rebase to latest main
git fetch origin
git rebase origin/main

# Run tests and fix failures
pytest

# Run linting and fix failures
make lint

# Commit fixes
git add .
git commit -m "fix(TASK-101): resolve test failures"

# Mark in_review again
curl -X POST http://localhost:8000/api/tasks/TASK-101/set-status \
  -H "Content-Type: application/json" \
  -d '{"status": "in_review"}'
```

### Scenario: Stuck on Dependency

**Symptom:** Task can't proceed because another task needs to complete first

**Resolution:**
```bash
# Mark task as blocked
curl -X POST http://localhost:8000/api/tasks/TASK-101/set-status \
  -H "Content-Type: application/json" \
  -d '{
    "status": "blocked",
    "blocked_reason": "Waiting for TASK-102",
    "blocked_by": "TASK-102"
  }'
```

Manager will:
- Keep task blocked
- You can claim other tasks
- Unclaim this task
- When TASK-102 is done, `/api/tasks/ready` will include TASK-101

### Scenario: Merge Conflict

**Symptom:** Daemon marks task `blocked` with "Merge conflict detected"

**Resolution:**
```bash
cd ../comic-pile-task-101

git fetch origin
git rebase origin/main

# Resolve conflicts manually
git status  # See conflicted files

# For each conflicted file, choose which changes to keep
# Example: keep both changes
git checkout --theirs --ours path/to/file.py

# Test that merge works
pytest
make lint

# Commit resolution
git add .
git commit -m "resolve(TASK-101): merge conflict with main"

# Mark in_review again
curl -X POST http://localhost:8000/api/tasks/TASK-101/set-status \
  -H "Content-Type: application/json" \
  -d '{"status": "in_review"}'
```

## What Workers NEVER Do

❌ Never call `/api/tasks/{task_id}/merge-to-main` yourself
- Manager daemon handles all merging

❌ Never set status to `done` yourself
- Daemon sets status to `done` after successful merge

❌ Never remove worktree before task is `done`
- Daemon needs worktree to review and merge
- Only remove after `status == "done"`

❌ Never merge to main manually
- Use daemon auto-merge or ask manager to intervene

❌ Never mark tasks as `in_review` without testing
- Ensure `pytest` passes
- Ensure `make lint` passes

❌ Never work on tasks you haven't claimed
- Always claim first via `/api/tasks/{task_id}/claim`

## Agent Identity

Always use your agent name consistently:
- In claim requests: `agent_name`
- In heartbeat requests: `agent_name`
- In unclaim requests: `agent_name`
- In status notes (optional): "Alice: Started implementing..."

## Monitoring Your Tasks

### Check task status
```bash
curl http://localhost:8000/api/tasks/TASK-101 | jq '{status, assigned_agent, worktree, blocked_reason}'
```

### Check your active tasks
```bash
curl http://localhost:8000/api/tasks/by-agent/Alice | jq '.[].task_id'
```

### Check coordinator dashboard
Open: http://localhost:8000/tasks/coordinator

## Troubleshooting

### 409 Conflict when claiming
Another agent already claimed this task. Choose a different task.

### 403 Forbidden on heartbeat/unclaim
You're not the assigned agent. Use the correct `agent_name`.

### Worktree not found error
Create worktree first with `git worktree add` or set `SKIP_WORKTREE_CHECK=true`.

### Can't set status to in_review
Ensure worktree field is set and worktree exists.

### Task stuck in in_review
Check daemon logs: `tail -f logs/manager-*.log`
Task may be blocked (check `blocked_reason`).

## Port Allocation

Each agent uses a unique port for their dev server:
- Main repo (Task API): 8000
- Agent worktree 1: 8001
- Agent worktree 2: 8002
- Agent worktree 3: 8003

Start your dev server:
```bash
cd ../comic-pile-task-101
PORT=8001 make dev
```

Always connect to Task API on port 8000 for task operations.
