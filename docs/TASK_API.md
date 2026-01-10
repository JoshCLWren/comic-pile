# Task API Reference

This document provides reference for the Task API endpoints used by the agent system.

**For complete worker agent workflow, see WORKER_WORKFLOW.md.**

## API Endpoints

All task operations are performed via REST API endpoints at `/api/tasks/`:

### Initialize Tasks
```bash
POST /api/tasks/initialize
```
Initializes all 12 PRD tasks in the database. Idempotent - can be run multiple times safely.

Example:
```bash
curl -X POST http://localhost:8000/api/tasks/initialize
```

### List All Tasks
```bash
GET /api/tasks/
```
Returns all tasks with current state.

Example:
```bash
curl http://localhost:8000/api/tasks/
```

### Get Single Task
```bash
GET /api/tasks/{task_id}
```
Get details for a specific task.

Example:
```bash
curl http://localhost:8000/api/tasks/TASK-101
```

### Claim a Task
```bash
POST /api/tasks/{task_id}/claim
```
Claims a task for an agent. Sets status to "in_progress" and records agent name and worktree.

Request body:
```json
{
  "agent_name": "agent-1",
  "worktree": "comic-pile-task-101"
}
```

Example:
```bash
curl -X POST http://localhost:8000/api/tasks/TASK-101/claim \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "agent-1", "worktree": "comic-pile-task-101"}'
```

### Update Status Notes
```bash
POST /api/tasks/{task_id}/update-notes
```
Appends a note to the task's status_notes field. Notes are timestamped and preserved.

Request body:
```json
{
  "notes": "Started implementing narrative summary function"
}
```

Example:
```bash
curl -X POST http://localhost:8000/api/tasks/TASK-101/update-notes \
  -H "Content-Type: application/json" \
  -d '{"notes": "Started implementing narrative summary function"}'
```

### Set Task Status
```bash
POST /api/tasks/{task_id}/set-status
```
Changes the task status. Valid statuses: `pending`, `in_progress`, `blocked`, `in_review`, `done`.

Request body:
```json
{
  "status": "in_review"
}
```

Example:
```bash
curl -X POST http://localhost:8000/api/tasks/TASK-101/set-status \
  -H "Content-Type: application/json" \
  -d '{"status": "in_review"}'
```

### Filter Tasks by Status
```bash
GET /api/tasks/by-status/{status}
```
Get all tasks with a specific status.

Example:
```bash
curl http://localhost:8000/api/tasks/by-status/pending
curl http://localhost:8000/api/tasks/by-status/in_progress
```

### Get Tasks by Agent
```bash
GET /api/tasks/by-agent/{agent_name}
```
Get all tasks assigned to a specific agent.

Example:
```bash
curl http://localhost:8000/api/tasks/by-agent/agent-1
```

### Get Ready Tasks
```bash
GET /api/tasks/ready
```
Get tasks that are ready for claiming. Returns tasks that are:
- status = "pending" (not claimed)
- blocked_reason = NULL (not blocked)
- All dependencies are "done" (check dependencies)
- Ordered by priority (HIGH first, then MEDIUM, then LOW)

Example:
```bash
curl http://localhost:8000/api/tasks/ready
```

### Task Heartbeat
```bash
POST /api/tasks/{task_id}/heartbeat
```
Update task heartbeat to show active work. Only allowed by the assigned agent.

Request body:
```json
{
  "agent_name": "agent-1"
}
```

Example:
```bash
curl -X POST http://localhost:8000/api/tasks/TASK-101/heartbeat \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "agent-1"}'
```

Returns 403 if not assigned to the requesting agent.

### Unclaim Task
```bash
POST /api/tasks/{task_id}/unclaim
```
Unclaim a task - resets to pending status and clears assignment. Only allowed by the assigned agent (or admin).

Request body:
```json
{
  "agent_name": "agent-1"
}
```

Example:
```bash
curl -X POST http://localhost:8000/api/tasks/TASK-101/unclaim \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "agent-1"}'
```

Returns 403 if not assigned to the requesting agent.

### Coordinator Data
```bash
GET /api/tasks/coordinator-data
```
Get all tasks grouped by status for coordinator dashboard.

Example:
```bash
curl http://localhost:8000/api/tasks/coordinator-data
```

Returns:
```json
{
  "pending": [...],
  "in_progress": [...],
  "blocked": [...],
  "in_review": [...],
  "done": [...]
}
```

## Why Database Instead of File-Based Tracking?

- **No git conflicts**: Multiple agents can update task state simultaneously
- **Real-time status**: Always see current task assignments and progress
- **History tracking**: Status notes preserve complete history
- **Programmatic access**: Easy to build dashboards and reporting tools

## Status Legend

- 🟢 **pending**: Not started
- 🟡 **in_progress**: Agent working on it
- 🟣 **review**: Agent finished, awaiting review
- 🔴 **blocked**: Waiting on dependency
- ✅ **completed**: Done and tested
- ❌ **failed**: Failed, needs retry
