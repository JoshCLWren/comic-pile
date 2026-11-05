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

## API Versioning

The API uses a **partial versioning** strategy with two surfaces:

- **`/api/*`** — the legacy surface, used by original resources. Most maintained client resources have migrated to the versioned surface.
- **`/api/v1/*`** — the canonical versioned surface. All new client resources must be added here.

Legacy paths (e.g., `/api/threads/*`, `/api/roll/*`, `/api/sessions/*`, `/api/rate/*`, `/api/snooze/*`, `/api/undo/*`) are retained as explicit, tested backwards-compatibility aliases. Maintained first-party consumers should use the `/api/v1/*` equivalents.

**Convention for new endpoints:** add new client resources under `/api/v1/*`;
do not introduce new bare `/api/*` routes. Non-production tooling routes
(`debug`, `test`) are mounted under bare `/api/*` but only in non-production or
test environments — they are intentional exceptions, not client APIs.

The exact canonical families and the allowed legacy aliases are maintained in
[`docs/API_V1_CANONICAL.md`](API_V1_CANONICAL.md) and enforced by
`tests/test_api_v1_canonical_contract.py`.

### API version is not implementation language

The version segment identifies the HTTP contract, not the runtime. Native Rust
currently serves every deployed `/api/v2` operation listed in
[`docs/api/v2-route-inventory.json`](api/v2-route-inventory.json), while
`GET /api/v2/reading-boundaries/{thread_id}` remains a Python/FastAPI operation
behind the same v2 contract version. Never infer "v1 means Python" or "v2 means
Rust" from a path.

### Generated authoritative contract

The checked-in client contract
(`frontend/src/generated/openapi.json` and `openapi.ts`) is assembled from two
generated sources:

- `app.openapi()` for the Python/FastAPI routes, and
- `native/contracts/v2-runtime.openapi.json` for the deployed native Rust v2
  operations, generated from the Rust DTOs by `cargo run --example v2_openapi`.

`scripts/export_openapi_schema.py` merges them: a native operation replaces the
same `(path, method)` because ingress routes that request to Rust, and a native
component schema that differs from a same-named Python schema is published as
`Native<Name>` with its internal references rewritten. The same canonical
generator emits `frontend/src/generated/nativeV2Client.ts`, a thin typed request
client whose methods delegate to the existing frontend `HttpClient`; it does not
replace the authentication, CSRF, retry or error pipeline. The two live
transitional native responses, `GET /api/v2/roll/bootstrap` and
`POST /api/v2/reading-sessions`, are typed from their actual Rust handler DTOs,
so their known session/mode/bandwidth/rollable/recovery/read/snooze/skip fields
remain in the generated client contract until their owning retirements; stored
tag rows are typed for their stable columns with an explicit additional-property
boundary, while recovery nodes and mode-guidance JSON remain explicit extension
boundaries. The inventory, the native contract, the generated schema,
`vercel.json` ingress and the declared frontend service callers are kept in sync
by `tests/test_api_v2_contract_inventory.py`.

---

## Threads

Thread CRUD operations and queue management.

### GET /api/v2/threads

Read the authenticated reader's active queue as a bounded, cursor-paginated
collection. This is the native Rust resource that replaced the retired Python
`GET /api/v1/threads/` (the `POST /threads/` creation route is unchanged).

Query parameters: `search`, `sort` (`position`, `title`, `created`),
`page_size` (1-200, default 50) and the opaque `page_token` continuation.

**Response**: `200 OK`

```json
{
  "threads": [
    {
      "id": 1,
      "title": "Batman Vol. 1",
      "format": "Comic",
      "issues_remaining": 6,
      "queue_position": 1,
      "status": "active",
      "last_activity_at": "2025-12-30T10:30:00Z",
      "is_blocked": false,
      "blocking_reasons": [],
      "total_issues": 12,
      "next_unread_issue_number": "7",
      "notes": null,
      "created_at": "2025-12-30T08:00:00Z",
      "comicvine_mapping": null,
      "manual_creator_credits": [],
      "tags": []
    }
  ],
  "next_page_token": null,
  "active_count": 1
}
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

## Analytics

The authenticated reader's bounded reading metrics. `GET /api/v2/analytics/metrics`
is the new native Rust resource used by the real frontend service. The legacy
Python `GET /api/v1/analytics/metrics` and `GET /api/analytics/metrics` handlers
remain temporarily available until the replacement has authenticated production
proof; they are removed in the post-proof cleanup (#4348).

### GET /api/v2/analytics/metrics

Return owner-scoped thread counts, completion rate, average ended-session
duration, the five newest sessions from the last seven days, event-type counts,
and the five highest-rated threads at or above 4.0. Authentication, ownership,
token revocation and the credential epoch are validated in the same single
database statement as the metrics.

**Response**: `200 OK`

```json
{
  "total_threads": 5,
  "active_threads": 4,
  "completed_threads": 1,
  "completion_rate": 20.0,
  "average_session_hours": 2.0,
  "recent_sessions": [
    {
      "id": 12,
      "started_at": "2025-12-30T10:30:00+00:00",
      "ended_at": null,
      "start_die": 6
    }
  ],
  "event_stats": {"rate": 1, "roll": 4},
  "top_rated_threads": [
    {"id": 3, "title": "Saga", "rating": 4.5, "format": "Comic"}
  ]
}
```

`401 Unauthorized` is returned for a missing/invalid token, a revoked token, or
a password change that predates the token's credential epoch.

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

### PATCH /api/v2/queue-entries/{thread_id}

Move an owned thread to the front with `{"position": 1}`. This resource is
implemented in native Rust and replaces both legacy move-to-front PUT aliases.
The response contains `thread_id`, `position`, and `ordering_version`, rather
than a full thread projection. Queue/Thread clients already use this resource.

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

### POST /roll/ (retired)

`POST /api/v1/roll/` and its unversioned `POST /api/roll/` alias were retired in
#4336. The public Roll mutation is now the sessionless native
`POST /api/v2/roll/offer`, which is not served by the Python FastAPI app; both
retired Python paths return `404`. The retained Python Roll operations are
`override`, `dismiss-pending`, and the recommendation-explanation read.

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

### Manual die selection

`POST /api/v2/roll/dice-command` is the only way to choose a die. The command
body carries `kind: "manual_select"`, the requested `die`, and an
`idempotency_key`:

```json
{
  "kind": "manual_select",
  "die": 20,
  "idempotency_key": "roll-0123456789abcdef0123456789abcdef"
}
```

The selection is one event, not a pinned mode: the die is projected from the
owner's newest die-changing event, so it survives navigation and applies to
every later roll. `POST /api/v2/roll/reset` returns the die to d6 and clears
the browser's temporary snoozes and the pending roll.

The v1 `POST /api/v1/roll/set-die` and `POST /api/v1/roll/clear-manual-die`
routes were retired (#4352, #4353): nothing pins a manual die any more, so
there is no automatic ladder to resume.

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

## Demo

Bounded guest demo surface (issue #2757). It is read-only and identity-free: the
logged-out landing page links to `/demo`, where a visitor can see exactly one
seeded sample Roll moment before signing up.

This family is intentionally unauthenticated and versioned-only (no bare `/api/*`
twin). It serves fabricated fixtures rather than database reads, so a demo
interaction cannot create library, queue, rating, or reading-history rows, and
nothing here is imported into a real account.

### GET /v1/demo/roll

Return the single deterministic seeded sample roll.

**Auth**: none required
**Response**: `200 OK`

```json
{
  "thread_id": 999,
  "title": "Sample: The Dark Knight Returns (Demo)",
  "format": "comic",
  "issues_remaining": 3,
  "queue_position": 1,
  "die_size": 6,
  "result": 4,
  "offset": 0,
  "snoozed_count": 0,
  "issue_id": 1001,
  "issue_number": "#4",
  "next_issue_id": 1002,
  "next_issue_number": "#5",
  "total_issues": 12,
  "reading_progress": "Late in arc — the final act is building.",
  "explanation": "Demo roll: seeded sample data, no account state."
}
```

There is deliberately no demo write endpoint. Guest ratings stay in the browser
until the visitor explicitly signs up and separately chooses a save action.

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

## Dependencies

Manage hard-blocking dependencies between threads and issues.

### GET /api/v1/dependencies/blocked

List all thread IDs currently blocked by dependencies.

**Response**: `200 OK`

```json
[2, 5, 8]
```

### GET /api/v1/threads/{thread_id}/dependencies

Get all dependencies for a thread (both incoming and outgoing).

**Response**: `200 OK`

```json
{
  "blocking": [
    {
      "id": 1,
      "source_thread_id": 1,
      "target_thread_id": 2,
      "source_issue_id": null,
      "target_issue_id": null,
      "is_issue_level": false,
      "created_at": "2026-03-21T10:00:00",
      "source_label": "Batman Vol. 1",
      "target_label": "Batman Vol. 2"
    }
  ],
  "blocked_by": []
}
```

### GET /api/v1/issues/{issue_id}/dependencies

Get all incoming and outgoing dependency edges for a specific issue.

**Response**: `200 OK`

```json
{
  "issue_id": 101,
  "incoming": [
    {
      "dependency_id": 5,
      "source_issue_id": 88,
      "source_issue_number": "79",
      "source_thread_id": 3,
      "source_thread_title": "X-Men"
    }
  ],
  "outgoing": [
    {
      "dependency_id": 7,
      "source_issue_id": 115,
      "source_issue_number": "10",
      "source_thread_id": 4,
      "source_thread_title": "New Mutants"
    }
  ]
}
```

**Response**: `404 Not Found`

```json
{
  "detail": "Issue 99999 not found"
}
```

### POST /api/v1/dependencies/

Create a new dependency between two threads or two issues.

**Request Body**:

```json
{
  "source_type": "thread",
  "source_id": 1,
  "target_type": "thread",
  "target_id": 2
}
```

For issue-level dependencies:

```json
{
  "source_type": "issue",
  "source_id": 101,
  "target_type": "issue",
  "target_id": 205
}
```

**Response**: `201 Created`

Returns the created dependency with enriched labels.

### DELETE /api/v1/dependencies/{dependency_id}

Delete a dependency.

**Response**: `200 OK`

```json
{
  "message": "Dependency deleted"
}
```

**Response**: `404 Not Found`

```json
{
  "detail": "Dependency 999 not found"
}
```

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

- **CORS**: All origins are allowed for local network access during development

### Dependency Blocking Behavior

**Thread-Level Dependencies:**
- When thread A depends on thread B, thread A is blocked until all issues in thread B are read
- Blocked threads are excluded from roll pool and stale thread suggestions
- Blocking is recalculated whenever dependencies change or issues are marked as read

**Issue-Level Dependencies:**
- Specific issues can depend on other specific issues
- A thread is blocked if its `next_unread_issue` has an unread prerequisite
- Dependency indicators (🔗) appear on issues with incoming/outgoing dependencies
- Only visible for threads owned by the current user (authorization enforced)

**Unblocking:**
- Removing a dependency immediately recalculates blocked status
- Marking a prerequisite issue as read unblocks dependent issues
- Blocked threads show visual indicators in queue and roll views
