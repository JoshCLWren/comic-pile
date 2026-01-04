# API Contracts - Comic Pile

This document summarizes the key API endpoints and data contracts for Comic Pile, providing essential context for API development and testing.

---

## API Overview

**Base URL:** `http://localhost:8000`
**Content Type:** `application/json`
**Authentication:** Not required (single-user application)
**Interactive Documentation:**
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

---

## Core Endpoints

### Threads

#### GET /threads/
List all threads ordered by queue position.

**Response:** `200 OK`
```json
[
  {
    "id": 1,
    "title": "Batman Vol. 1",
    "format": "TPB",
    "issues_remaining": 6,
    "position": 1,
    "status": "active",
    "last_rating": 4.5,
    "last_activity_at": "2025-12-30T10:30:00",
    "created_at": "2025-12-30T08:00:00"
  }
]
```

#### POST /threads/
Create a new thread at the end of the queue.

**Request Body:**
```json
{
  "title": "Amazing Spider-Man #50",
  "format": "Issue",
  "issues_remaining": 1
}
```

**Response:** `201 Created` (returns created thread)

#### PUT /threads/{id}
Update a thread. All fields are optional.

**Request Body:**
```json
{
  "title": "Batman Vol. 1 (Updated)",
  "format": "TPB",
  "issues_remaining": 5
}
```

**Response:** `200 OK` (returns updated thread)

#### DELETE /threads/{id}
Delete a thread.

**Response:** `204 No Content`

#### POST /threads/reactivate
Reactivate a completed thread by adding more issues. Moves thread to position 1.

**Request Body:**
```json
{
  "thread_id": 5,
  "issues_to_add": 6
}
```

**Response:** `200 OK` (returns reactivated thread)

---

### Queue

#### PUT /queue/threads/{thread_id}/position/
Move thread to a specific position.

**Request Body:**
```json
{
  "new_position": 3
}
```

**Response:** `200 OK` (returns updated thread)

#### PUT /queue/threads/{thread_id}/front/
Move thread to the front of the queue (position 1).

**Response:** `200 OK` (returns updated thread)

#### PUT /queue/threads/{thread_id}/back/
Move thread to the back of the queue.

**Response:** `200 OK` (returns updated thread)

---

### Roll

#### POST /roll/
Roll the dice to select a thread from the roll pool. The roll pool includes threads at positions 1 through the current die size.

**Response:** `200 OK`
```json
{
  "thread_id": 3,
  "title": "The Walking Dead Vol. 1",
  "die_size": 6,
  "result": 2
}
```

**Response:** `400 Bad Request` (no active threads)
```json
{
  "detail": "No active threads available to roll"
}
```

#### POST /roll/override
Manually select a thread instead of rolling.

**Request Body:**
```json
{
  "thread_id": 3
}
```

**Response:** `200 OK`
```json
{
  "thread_id": 3,
  "title": "The Walking Dead Vol. 1",
  "die_size": 6,
  "result": 0
}
```

---

### Rate

#### POST /rate/
Rate the current reading and update thread status, issues remaining, and dice ladder position.

**Request Body:**
```json
{
  "rating": 4.5,
  "issues_read": 1
}
```

**Response:** `200 OK` (returns updated thread)

**Dice Ladder Logic:**
- Rating >= 4.0: Step up the dice ladder (e.g., d6 → d8)
- Rating < 4.0: Step down the dice ladder (e.g., d6 → d4)
- **Queue Movement:**
  - Rating >= 4.0 → move thread to **front**
  - Rating < 4.0 → move thread to **back**

**Response:** `400 Bad Request` (no active session)
```json
{
  "detail": "No active session. Please roll the dice first."
}
```

---

### Session

#### GET /sessions/current/
Get the currently active session.

**Response:** `200 OK`
```json
{
  "id": 1,
  "started_at": "2025-12-30T10:00:00",
  "ended_at": null,
  "start_die": 6,
  "user_id": 1,
  "ladder_path": "6 → 8 → 10",
  "active_thread": {
    "id": 3,
    "title": "The Walking Dead Vol. 1",
    "format": "TPB",
    "issues_remaining": 5,
    "position": 10
  }
}
```

**Response:** `404 Not Found` (no active session)
```json
{
  "detail": "No active session found"
}
```

#### GET /sessions/
List all sessions with pagination.

**Query Parameters:**
- `limit`: Number of sessions to return (default: 10, max: 100)
- `offset`: Number of sessions to skip (default: 0)

**Response:** `200 OK` (array of sessions)

#### GET /sessions/{id}
Get a single session by ID.

**Response:** `200 OK` (returns session)

#### GET /sessions/{id}/details
Get detailed session information with all events (HTML response).

**Response:** `200 OK` (HTML)

Returns rendered HTML template with full event log including rolls and ratings.

---

### Task API (Agent Coordination)

**Note:** These endpoints are used by AI agents for coordinating development work, not by end users.

#### GET /api/tasks/
List all tasks.

**Response:** `200 OK` (array of tasks)

#### GET /api/tasks/ready
Get tasks ready for claiming (respects dependencies).

**Response:** `200 OK` (array of pending tasks with all dependencies satisfied)

#### GET /api/tasks/coordinator-data
Get tasks grouped by status for coordinator dashboard.

**Response:** `200 OK`
```json
{
  "pending": [...],
  "in_progress": [...],
  "blocked": [...],
  "in_review": [...],
  "done": [...]
}
```

#### GET /api/tasks/{task_id}
Get a single task by ID.

**Response:** `200 OK` (returns task)

#### POST /api/tasks/{task_id}/claim
Claim task for agent.

**Request Body:**
```json
{
  "agent_name": "worker-1",
  "worktree": "/home/josh/code/comic-pile-p2"
}
```

**Response:** `200 OK` (returns updated task)
**Response:** `409 Conflict` (task already claimed)

#### POST /api/tasks/{task_id}/heartbeat
Update task heartbeat.

**Request Body:**
```json
{
  "agent_name": "worker-1"
}
```

**Response:** `200 OK` (returns updated task)

#### POST /api/tasks/{task_id}/update-notes
Append status notes.

**Request Body:**
```json
{
  "notes": "Investigated d10 geometry issue...",
  "agent_name": "worker-1"
}
```

**Response:** `200 OK` (returns updated task)

#### POST /api/tasks/{task_id}/set-status
Change task status.

**Request Body:**
```json
{
  "status": "in_review",
  "agent_name": "worker-1"
}
```

**Response:** `200 OK` (returns updated task)

#### POST /api/tasks/{task_id}/unclaim
Release task back to pending.

**Request Body:**
```json
{
  "agent_name": "worker-1"
}
```

**Response:** `200 OK` (returns updated task)

#### POST /api/tasks/initialize
Initialize tasks from hardcoded data.

**Response:** `200 OK` (returns number of tasks initialized)

---

### Admin

#### POST /admin/import/csv/
Import threads from a CSV file. Compatible with Google Sheets exports.

**Request:** `multipart/form-data` with file field

**CSV Format:**
- Headers: `title`, `format`, `issues_remaining`
- Format values: `TPB`, `Issue`, `Graphic Novel`, `OGN`, or custom
- `issues_remaining`: Positive integer (≥ 0)

**Example CSV:**
```csv
title,format,issues_remaining
"Batman Vol. 1",TPB,6
"Amazing Spider-Man #50",Issue,1
"Saga Volume 1",Graphic Novel,6
```

**Response:** `200 OK`
```json
{
  "imported": 4,
  "errors": []
}
```

**Response:** `400 Bad Request`
```json
{
  "imported": 2,
  "errors": [
    "Row 3: Missing title",
    "Row 5: issues_remaining must be an integer"
  ]
}
```

#### GET /admin/export/csv/
Export active threads as a CSV file. Compatible with Google Sheets.

**Response:** `200 OK` (text/csv)

Content-Disposition: `attachment; filename=threads_export.csv`

```csv
title,format,issues_remaining
"Batman Vol. 1",TPB,5
"The Walking Dead Vol. 1",TPB,4
"Saga Volume 1",Graphic Novel,6
```

#### GET /admin/export/json/
Export full database as JSON for backups.

**Response:** `200 OK` (application/json)

Content-Disposition: `attachment; filename=database_backup.json`

```json
{
  "users": [...],
  "threads": [...],
  "sessions": [...],
  "events": [...]
}
```

---

## Data Models

### ThreadResponse

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique thread identifier |
| `title` | string | Thread title |
| `format` | string | Publication format (TPB, Issue, Graphic Novel, OGN, etc.) |
| `issues_remaining` | integer | Number of issues remaining to read |
| `position` | integer | Current queue position |
| `status` | string | Thread status (`active` or `completed`) |
| `last_rating` | float | Last rating given (0.5 - 5.0), null if never rated |
| `last_activity_at` | datetime | Last activity timestamp, null if never active |
| `created_at` | datetime | Thread creation timestamp |

### RollResponse

| Field | Type | Description |
|-------|------|-------------|
| `thread_id` | integer | Selected thread ID |
| `title` | string | Selected thread title |
| `die_size` | integer | Die size used for roll |
| `result` | integer | Roll result (0 for override, 1-N for roll) |

### SessionResponse

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique session identifier |
| `started_at` | datetime | Session start time |
| `ended_at` | datetime | Session end time, null if active |
| `start_die` | integer | Starting die size for session |
| `user_id` | integer | User ID (always 1 for single-user app) |
| `ladder_path` | string | Narrative summary of dice ladder path (e.g., "6 → 8 → 10") |
| `active_thread` | object | Last read thread in session, null if none |

### TaskResponse

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique task identifier |
| `task_id` | string | Task ID (e.g., "TASK-101") |
| `title` | string | Task title |
| `priority` | string | Task priority (HIGH, MEDIUM, LOW) |
| `status` | string | Task status (pending, in_progress, blocked, in_review, done) |
| `dependencies` | string | Comma-separated task IDs |
| `assigned_agent` | string | Agent name assigned to task, null if unclaimed |
| `worktree` | string | Worktree path for task execution, null if not set |
| `status_notes` | text | Status notes with timestamps |
| `estimated_effort` | string | Estimated effort (e.g., "2-3 hours") |
| `completed` | bool | Whether task is completed |
| `blocked_reason` | text | Reason task is blocked, null if not blocked |
| `blocked_by` | string | Task ID blocking this task, null if not blocked |
| `last_heartbeat` | datetime | Last heartbeat timestamp, null if not set |
| `instructions` | text | Task instructions |
| `created_at` | datetime | Task creation timestamp |
| `updated_at` | datetime | Last update timestamp |

---

## Error Responses

All endpoints may return standard HTTP error responses:

### 400 Bad Request
Invalid request data or missing required fields.
```json
{
  "detail": "No active threads available to roll"
}
```

### 404 Not Found
Resource not found.
```json
{
  "detail": "Thread 999 not found"
}
```

### 409 Conflict
Resource conflict (e.g., task already claimed).
```json
{
  "detail": "Task TASK-101 is already claimed by worker-1"
}
```

### 422 Unprocessable Entity
Validation error for request body.
```json
{
  "detail": [
    {
      "loc": ["body", "issues_remaining"],
      "msg": "ensure this value is greater than or equal to 0",
      "type": "greater_than_equal"
    }
  ]
}
```

---

## Usage Examples

### Creating a New Thread
```bash
curl -X POST http://localhost:8000/threads/ \
  -H "Content-Type: application/json" \
  -d '{
    "title": "The Incredible Hulk Vol. 1",
    "format": "TPB",
    "issues_remaining": 6
  }'
```

### Rolling the Dice
```bash
curl -X POST http://localhost:8000/roll/
```

### Rating the Current Reading
```bash
curl -X POST http://localhost:8000/rate/ \
  -H "Content-Type: application/json" \
  -d '{
    "rating": 4.0,
    "issues_read": 1
  }'
```

### Importing from CSV
```bash
curl -X POST http://localhost:8000/admin/import/csv/ \
  -F "file=@threads.csv"
```

### Exporting to CSV
```bash
curl -O http://localhost:8000/admin/export/csv/
```

---

## Notes

- **Single User:** The API is designed for single-user applications (user_id is always 1)
- **Session Timeout:** Sessions are considered inactive after 6 hours of inactivity
- **Dice Ladder:** The dice ladder follows the pattern: d4 → d6 → d8 → d10 → d12 → d20
- **Caching:** Thread and session data is cached for performance (30s and 10s TTL respectively)
- **CORS:** All origins are allowed for local network access during development (`allow_origins=["*"]`)
- **Rate Limiting:** No rate limiting implemented (documented as technical debt)
- **API Versioning:** No version prefix on routes (documented as technical debt)

---

## Testing Notes

All API endpoints are tested with `httpx.AsyncClient` in the test suite:

```python
async def test_roll_dice(async_client: AsyncClient):
    response = await async_client.post("/roll/")
    assert response.status_code == 200
    data = response.json()
    assert "thread_id" in data
    assert "result" in data
```

See `tests/test_api_endpoints.py` for comprehensive API tests.
