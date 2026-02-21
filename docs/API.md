# Comic Pile API Documentation

## Overview

The Comic Pile API is a RESTful API for tracking comic reading using a dice-driven selection system. All endpoints use JSON for request and response bodies.

- **Base URL**: `http://localhost:8000`
- **Content Type**: `application/json`
- **Authentication**: JWT Bearer token required (see `/api/auth/login`)

### Interactive Documentation

FastAPI automatically generates interactive API documentation:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

---

## Threads

Thread CRUD operations and queue management.

### GET /threads/

List all threads ordered by queue position.

**Response**: `200 OK`

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

### POST /threads/

Create a new thread at the end of the queue.

**Request Body**:

```json
{
  "title": "Amazing Spider-Man #50",
  "format": "Issue",
  "issues_remaining": 1
}
```

**Response**: `201 Created`

```json
{
  "id": 2,
  "title": "Amazing Spider-Man #50",
  "format": "Issue",
  "issues_remaining": 1,
  "position": 2,
  "status": "active",
  "last_rating": null,
  "last_activity_at": null,
  "created_at": "2025-12-30T10:35:00"
}
```

### GET /threads/{id}

Get a single thread by ID.

**Response**: `200 OK`

```json
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
```

**Response**: `404 Not Found`

```json
{
  "detail": "Thread 999 not found"
}
```

### PUT /threads/{id}

Update a thread. All fields are optional.

**Request Body**:

```json
{
  "title": "Batman Vol. 1 (Updated)",
  "format": "TPB",
  "issues_remaining": 5
}
```

**Response**: `200 OK`

```json
{
  "id": 1,
  "title": "Batman Vol. 1 (Updated)",
  "format": "TPB",
  "issues_remaining": 5,
  "position": 1,
  "status": "active",
  "last_rating": 4.5,
  "last_activity_at": "2025-12-30T10:30:00",
  "created_at": "2025-12-30T08:00:00"
}
```

### DELETE /threads/{id}

Delete a thread.

**Response**: `204 No Content`

### POST /threads/reactivate

Reactivate a completed thread by adding more issues. Moves thread to position 1.

**Request Body**:

```json
{
  "thread_id": 5,
  "issues_to_add": 6
}
```

**Response**: `200 OK`

```json
{
  "id": 5,
  "title": "Saga Volume 1",
  "format": "Graphic Novel",
  "issues_remaining": 6,
  "position": 1,
  "status": "active",
  "last_rating": 4.0,
  "last_activity_at": "2025-12-29T15:00:00",
  "created_at": "2025-12-28T10:00:00"
}
```

**Response**: `400 Bad Request`

```json
{
  "detail": "Thread 5 is not completed"
}
```

---

## Queue

Queue management for thread positioning.

### PUT /queue/threads/{thread_id}/position/

Move thread to a specific position.

**Request Body**:

```json
{
  "new_position": 3
}
```

**Response**: `200 OK`

```json
{
  "id": 1,
  "title": "Batman Vol. 1",
  "format": "TPB",
  "issues_remaining": 6,
  "position": 3,
  "status": "active",
  "last_rating": 4.5,
  "last_activity_at": "2025-12-30T10:30:00",
  "created_at": "2025-12-30T08:00:00"
}
```

### PUT /queue/threads/{thread_id}/front/

Move thread to the front of the queue (position 1).

**Response**: `200 OK`

```json
{
  "id": 5,
  "title": "Saga Volume 1",
  "format": "Graphic Novel",
  "issues_remaining": 6,
  "position": 1,
  "status": "active",
  "last_rating": 4.0,
  "last_activity_at": "2025-12-29T15:00:00",
  "created_at": "2025-12-28T10:00:00"
}
```

### PUT /queue/threads/{thread_id}/back/

Move thread to the back of the queue.

**Response**: `200 OK`

```json
{
  "id": 1,
  "title": "Batman Vol. 1",
  "format": "TPB",
  "issues_remaining": 6,
  "position": 10,
  "status": "active",
  "last_rating": 4.5,
  "last_activity_at": "2025-12-30T10:30:00",
  "created_at": "2025-12-30T08:00:00"
}
```

---

## Roll

Dice roll for thread selection.

### POST /roll/

Roll the dice to select a thread from the roll pool. The roll pool includes threads at positions 1 through the current die size.

**Response**: `200 OK`

```json
{
  "thread_id": 3,
  "title": "The Walking Dead Vol. 1",
  "die_size": 6,
  "result": 2
}
```

**Response**: `400 Bad Request`

```json
{
  "detail": "No active threads available to roll"
}
```

### POST /roll/override

Manually select a thread instead of rolling.

**Request Body**:

```json
{
  "thread_id": 3
}
```

**Response**: `200 OK`

```json
{
  "thread_id": 3,
  "title": "The Walking Dead Vol. 1",
  "die_size": 6,
  "result": 0
}
```

---

## Rate

Rate the current reading session.

### POST /rate/

Rate the current reading and update thread status, issues remaining, and dice ladder position.

**Request Body**:

```json
{
  "rating": 4.5,
  "issues_read": 1
}
```

**Response**: `200 OK`

```json
{
  "id": 3,
  "title": "The Walking Dead Vol. 1",
  "format": "TPB",
  "issues_remaining": 5,
  "position": 10,
  "status": "active",
  "last_rating": 4.5,
  "last_activity_at": "2025-12-30T11:00:00",
  "created_at": "2025-12-28T10:00:00"
}
```

**Dice Ladder Logic**:
- Rating >= 3.5: Step up the dice ladder (e.g., d6 → d8)
- Rating < 3.5: Step down the dice ladder (e.g., d6 → d4)

**Response**: `400 Bad Request` (no active session)

```json
{
  "detail": "No active session. Please roll the dice first."
}
```

---

## Session

Session tracking and history.

### GET /sessions/current/

Get the currently active session.

**Response**: `200 OK`

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

**Response**: `404 Not Found`

```json
{
  "detail": "No active session found"
}
```

### GET /sessions/

List all sessions with pagination.

**Query Parameters**:
- `limit`: Number of sessions to return (default: 10, max: 100)
- `offset`: Number of sessions to skip (default: 0)

**Response**: `200 OK`

```json
[
  {
    "id": 2,
    "started_at": "2025-12-29T18:00:00",
    "ended_at": "2025-12-29T19:30:00",
    "start_die": 6,
    "user_id": 1,
    "ladder_path": "6 → 8",
    "active_thread": {
      "id": 5,
      "title": "Saga Volume 1",
      "format": "Graphic Novel",
      "issues_remaining": 0,
      "position": 10
    }
  },
  {
    "id": 1,
    "started_at": "2025-12-29T10:00:00",
    "ended_at": "2025-12-29T11:30:00",
    "start_die": 4,
    "user_id": 1,
    "ladder_path": "4 → 6 → 8",
    "active_thread": {
      "id": 1,
      "title": "Batman Vol. 1",
      "format": "TPB",
      "issues_remaining": 4,
      "position": 5
    }
  }
]
```

### GET /sessions/{id}

Get a single session by ID.

**Response**: `200 OK`

```json
{
  "id": 1,
  "started_at": "2025-12-30T10:00:00",
  "ended_at": "2025-12-30T11:30:00",
  "start_die": 6,
  "user_id": 1,
  "ladder_path": "6 → 8 → 10",
  "active_thread": {
    "id": 3,
    "title": "The Walking Dead Vol. 1",
    "format": "TPB",
    "issues_remaining": 0,
    "position": 10
  }
}
```

### GET /sessions/{id}/details

Get detailed session information with all events (HTML response).

**Response**: `200 OK` (HTML)

Returns rendered HTML template with full event log including rolls and ratings.

---

## Admin

Data import/export operations.

### POST /admin/import/csv/

Import threads from a CSV file. Compatible with Google Sheets exports.

**Request**: `multipart/form-data` with file field

**CSV Format**:
- Headers: `title`, `format`, `issues_remaining`
- Format values: `TPB`, `Issue`, `Graphic Novel`, `OGN`, or custom
- `issues_remaining`: Positive integer (≥ 0)

**Example CSV**:

```csv
title,format,issues_remaining
"Batman Vol. 1",TPB,6
"Amazing Spider-Man #50",Issue,1
"Saga Volume 1",Graphic Novel,6
"Sandman: Preludes & Nocturnes",OGN,8
```

**Response**: `200 OK`

```json
{
  "imported": 4,
  "errors": []
}
```

**Response**: `400 Bad Request`

```json
{
  "imported": 2,
  "errors": [
    "Row 3: Missing title",
    "Row 5: issues_remaining must be an integer"
  ]
}
```

### GET /admin/export/csv/

Export active threads as a CSV file. Compatible with Google Sheets.

**Response**: `200 OK` (text/csv)

Content-Disposition: `attachment; filename=threads_export.csv`

```csv
title,format,issues_remaining
"Batman Vol. 1",TPB,5
"The Walking Dead Vol. 1",TPB,4
"Saga Volume 1",Graphic Novel,6
```

### GET /admin/export/json/

Export full database as JSON for backups.

**Response**: `200 OK` (application/json)

Content-Disposition: `attachment; filename=database_backup.json`

```json
{
  "users": [
    {
      "id": 1,
      "username": "admin",
      "created_at": "2025-12-28T08:00:00"
    }
  ],
  "threads": [
    {
      "id": 1,
      "title": "Batman Vol. 1",
      "format": "TPB",
      "issues_remaining": 5,
      "queue_position": 1,
      "status": "active",
      "last_rating": 4.5,
      "last_activity_at": "2025-12-30T10:30:00",
      "review_url": null,
      "created_at": "2025-12-30T08:00:00",
      "user_id": 1
    }
  ],
  "sessions": [
    {
      "id": 1,
      "started_at": "2025-12-30T10:00:00",
      "ended_at": null,
      "start_die": 6,
      "user_id": 1
    }
  ],
  "events": [
    {
      "id": 1,
      "type": "roll",
      "timestamp": "2025-12-30T10:05:00",
      "die": 6,
      "result": 1,
      "selected_thread_id": 1,
      "selection_method": "roll",
      "rating": null,
      "issues_read": null,
      "queue_move": null,
      "die_after": null,
      "notes": null,
      "session_id": 1,
      "thread_id": null
    }
  ]
}
```

---

## CSV Format

The CSV format is used for importing and exporting thread data. This format is compatible with Google Sheets and other spreadsheet applications.

### Headers

| Header | Type | Required | Description |
|--------|------|----------|-------------|
| `title` | string | Yes | Thread title (e.g., "Batman Vol. 1") |
| `format` | string | Yes | Publication format (e.g., "TPB", "Issue") |
| `issues_remaining` | integer | Yes | Number of issues remaining (≥ 0) |

### Format Values

Common format values:
- `TPB` - Trade Paperback
- `Issue` - Single comic issue
- `Graphic Novel` - Graphic Novel
- `OGN` - Original Graphic Novel
- Custom values are also supported

### Example CSV File

```csv
title,format,issues_remaining
"Batman Vol. 1",TPB,6
"Amazing Spider-Man #50",Issue,1
"Saga Volume 1",Graphic Novel,6
"Sandman: Preludes & Nocturnes",OGN,8
"Watchmen",Graphic Novel,12
"Transmetropolitan Vol. 1",TPB,10
```

### CSV Import Rules

1. **Required Fields**: All three headers must be present
2. **Validation**:
   - Title must not be empty
   - Format must not be empty
   - `issues_remaining` must be a valid integer ≥ 0
3. **Import Order**: New threads are inserted at position 1 (front of queue)
4. **Error Handling**: Invalid rows are skipped and listed in the error response
5. **Duplicate Titles**: Duplicate titles are allowed

### CSV Export Rules

1. **Active Threads Only**: Only threads with `status = "active"` and `issues_remaining > 0` are exported
2. **Order**: Threads are exported in queue position order
3. **Fields**: Only title, format, and issues_remaining are included

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

## Data Models

### ThreadResponse

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique thread identifier |
| `title` | string | Thread title |
| `format` | string | Publication format |
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
| `result` | integer | Roll result (0 for override) |

### SessionResponse

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique session identifier |
| `started_at` | datetime | Session start time |
| `ended_at` | datetime | Session end time, null if active |
| `start_die` | integer | Starting die size for session |
| `user_id` | integer | User ID |
| `ladder_path` | string | Narrative summary of dice ladder path |
| `active_thread` | object | Last read thread in session, null if none |

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

- **Single User**: The API is designed for single-user applications (user_id is always 1)
- **Session Timeout**: Sessions are considered inactive after 6 hours of inactivity
- **Dice Ladder**: The dice ladder follows the pattern: d4 → d6 → d8 → d10 → d12 → d20
- **Caching**: Thread and session data is cached for performance (30s and 10s TTL respectively)
- **CORS**: All origins are allowed for local network access during development
