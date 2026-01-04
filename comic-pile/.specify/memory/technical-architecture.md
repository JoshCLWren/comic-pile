# Technical Architecture - Comic Pile

This document captures key architectural decisions, tech debt, and technical context for Comic Pile.

---

## Architecture Overview

### Monolithic FastAPI Application

Comic Pile is a monolithic FastAPI application with a clear separation of concerns despite being in a single codebase.

```
┌─────────────────────────────────────────────────────────────┐
│                     Comic Pile FastAPI                      │
│                      (Monolithic)                           │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  API Layer (FastAPI Router)                         │  │
│  │  ├── threads.py  (Thread CRUD, queue, rating)       │  │
│  │  ├── roll.py     (Dice rolling, session flow)       │  │
│  │  ├── queue.py    (Queue operations)                  │  │
│  │  ├── session.py  (Session management)                │  │
│  │  ├── admin.py    (Admin operations)                  │  │
│  │  ├── rate.py     (Rating and dice ladder)           │  │
│  │  └── tasks.py    (Task management for agents)        │  │
│  └──────────────────────────────────────────────────────┘  │
│                           │                                  │
│                           ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Business Logic Layer (comic_pile package)          │  │
│  │  ├── dice_ladder.py  (Dice ladder step logic)       │  │
│  │  ├── queue.py        (Queue repositioning logic)     │  │
│  │  └── session.py      (Session detection logic)      │  │
│  └──────────────────────────────────────────────────────┘  │
│                           │                                  │
│                           ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Database Layer (SQLAlchemy ORM)                      │  │
│  │  ├── Thread, Session, Event, User models             │  │
│  │  └── Task model  ←─ Single database                     │  │
│  └──────────────────────────────────────────────────────┘  │
│                           │                                  │
│                           ▼                                  │
│                  SQLite Database                             │
└─────────────────────────────────────────────────────────────┘

External Consumers:
- AI Agents (via curl/httpx)
- Coordinator Dashboard (HTMX)
- Interactive Tests
```

### Key Design Decisions

1. **Monolithic Architecture:**
   - Single FastAPI application
   - All endpoints in one process
   - Clear module separation despite monolith
   - Simple deployment and testing

2. **SQLite Database:**
   - Single database for all data (threads, sessions, events, tasks)
   - SQLAlchemy ORM for database access
   - Alembic for migrations
   - ACID transactions for data integrity

3. **API-First Design:**
   - RESTful endpoints with JSON request/response
   - Pydantic schemas for validation
   - FastAPI auto-generates OpenAPI docs
   - HTMX frontend uses same API as potential native clients

4. **Task API for Agent Coordination:**
   - Embedded in monolith (not extracted to separate service)
   - Used by AI agents for coordinating development work
   - Separate bounded context within same codebase
   - See ARCHITECTURE_TASK_API.md for extraction analysis

---

## Technology Stack

### Backend

**Framework:**
- FastAPI (Python 3.13)
  - High-performance async framework
  - Automatic OpenAPI documentation
  - Pydantic integration
  - Dependency injection

**Database:**
- SQLite (development)
  - Embedded database, no server needed
  - Easy local development
  - Single file storage
- PostgreSQL (production option)
  - See DOCKER_MIGRATION.md for migration guide
  - Better concurrency for multi-user scenarios

**ORM:**
- SQLAlchemy 2.0
  - Async support
  - Type-safe queries
  - Migration support via Alembic

**Testing:**
- pytest with httpx.AsyncClient
  - Async HTTP client for API tests
  - Fixtures for shared setup
  - Coverage reporting (96% threshold)

**Code Quality:**
- ruff (linting)
  - Fast Python linter
  - Configured for PEP 8
  - 100-character line length
  - ANN401 rule: no Any type allowed
- pyright (type checking)
  - Static type analyzer
  - Microsoft's TypeScript-style type checker for Python

### Frontend

**Templates:**
- Jinja2 (server-side rendering)
  - Built into FastAPI
  - Template inheritance (base.html)
  - Dynamic content rendering

**Interactivity:**
- HTMX
  - AJAX requests without JavaScript
  - Server-side HTML responses
  - Declarative markup (hx-get, hx-post, etc.)

**Styling:**
- Tailwind CSS
  - Utility-first CSS
  - CDN for development
  - Mobile-first responsive design
  - Touch-friendly (≥44px targets)

**JavaScript:**
- Minimal custom JavaScript
  - dice3d.js for 3D dice rendering
  - app.js for client-side logic
  - No frameworks (React, Vue, etc.)

---

## Database Schema

### Core Tables

#### threads
```sql
id (PK, integer)
title (string)
format (string)
issues_remaining (integer)
queue_position (integer)
status (string) -- 'active' or 'completed'
last_rating (float, nullable)
last_activity_at (datetime, nullable)
review_url (string, nullable)
last_review_at (datetime, nullable)
created_at (datetime)
user_id (FK, integer)
```

#### sessions
```sql
id (PK, integer)
started_at (datetime)
ended_at (datetime, nullable)
start_die (integer)
user_id (FK, integer)
```

#### events
```sql
id (PK, integer)
type (string) -- 'roll', 'rate', 'override', etc.
timestamp (datetime)
die (integer, nullable)
result (integer, nullable)
selected_thread_id (FK, nullable)
selection_method (string, nullable) -- 'roll' or 'override'
rating (float, nullable)
issues_read (integer, nullable)
queue_move (string, nullable) -- 'front' or 'back'
die_after (integer, nullable)
notes (text, nullable)
session_id (FK, integer)
thread_id (FK, nullable)
```

#### users
```sql
id (PK, integer)
username (string)
created_at (datetime)
```

#### tasks (Agent Coordination)
```sql
id (PK, integer)
task_id (string, unique, indexed)
title (string)
priority (string) -- 'HIGH', 'MEDIUM', 'LOW'
status (string, indexed) -- 'pending', 'in_progress', 'blocked', 'in_review', 'done'
dependencies (string) -- comma-separated task IDs
assigned_agent (string, nullable)
worktree (string, nullable)
status_notes (text)
estimated_effort (string)
completed (bool)
blocked_reason (text, nullable)
blocked_by (string, nullable)
last_heartbeat (datetime, nullable)
instructions (text)
description (text)
created_at (datetime)
updated_at (datetime)
```

---

## Key Components

### Dice Ladder (comic_pile/dice_ladder.py)

**Purpose:** Implement dice ladder step logic for rating flow.

**Functions:**
- `step_up(die: int) -> int`: Step up one die (e.g., d6 → d8)
- `step_down(die: int) -> int`: Step down one die (e.g., d6 → d4)
- `DICE_LADDER = [4, 6, 8, 10, 12, 20]`: Ordered list of allowed dice

**Bounds:**
- d4 cannot step down (stays d4)
- d20 cannot step up (stays d20)

**Used by:** `/rate/` endpoint to update die size after rating.

### Queue Management (comic_pile/queue.py)

**Purpose:** Handle thread repositioning in queue.

**Functions:**
- `move_to_front(db, thread_id)`: Move thread to position 1, shift others down
- `move_to_back(db, thread_id)`: Move thread to last position
- `move_to_position(db, thread_id, new_position)`: Move thread to specific position

**Implementation:**
- Updates `queue_position` for all affected threads
- Uses UPDATE statements for performance
- Called from `/rate/` and queue endpoints

**Used by:** `/rate/`, `/queue/threads/{id}/front/`, `/queue/threads/{id}/back/`, `/queue/threads/{id}/position/`

### Session Detection (comic_pile/session.py)

**Purpose:** Detect and manage active reading sessions.

**Constants:**
- `SESSION_GAP_HOURS = 6`: Time threshold for new session

**Functions:**
- `is_active(session) -> bool`: Check if session ended < 6 hours ago
- `should_start_new(db, user_id) -> bool`: Check if new session needed
- `get_or_create(db, user_id) -> Session`: Return active session or create new one

**Logic:**
- 6-hour gap = new session
- Automatic resume if < 6 hours
- No manual session creation

**Used by:** `/roll/`, `/rate/`, session endpoints

### Caching (app/main.py)

**Purpose:** In-memory caching for performance.

**Implementation:**
- Simple dict-based cache with TTL
- Thread cache: 30s TTL
- Session cache: 10s TTL
- Functions: `clear_cache()`, `get_threads_cached()`, `get_current_session_cached()`

**Limitations:**
- No selective invalidation (clears entire cache)
- Single-process only (not multi-instance safe)
- No Redis for distributed caching

**Technical Debt:** See TECH_DEBT.md item #7.

---

## Proven Solutions

### Integration Test Database Isolation (RESOLVED)

**Problem:** Tests failed with "no such table: settings" errors during integration tests.
**Root Cause:** In-memory SQLite database not shared across test connections. Each test had isolated database.
**Solution:** Use `sqlite:///file::memory:?cache=shared` for shared access across test connections.
**Implementation:** `tests/integration/conftest.py` updated with shared database connection string.
**Result:** All integration tests now pass with proper database isolation.
**Evidence:** Manager-7 successfully fixed this issue.

### Uvicorn Version Pinning (RESOLVED)

**Problem:** SyntaxError in uvicorn/importer.py line 24 blocking all development.
**Root Cause:** uvicorn 0.40.0 had corrupted importer.py.
**Solution:** Pinned uvicorn to 0.39.0 in pyproject.toml.
**Implementation:** Updated dependency constraint in `pyproject.toml`.
**Result:** Development server starts without SyntaxError.
**Evidence:** Manager-2 successfully resolved this issue.

### Merge Conflict Resolution with `git checkout --theirs --ours`

**Problem:** Multiple workers modifying same files (app/main.py, roll.html, etc.) created merge conflicts.
**Solution:** Use `git checkout --theirs --ours` to accept both changes.
**Implementation:** Manual conflict resolution accepting both sides of merge.
**Result:** All features preserved (e.g., TASK-102 stale suggestion + TASK-103 roll pool highlighting).
**Evidence:**
- Manager-1: Successfully resolved roll.html conflict
- Manager-3: Successfully resolved app/main.py conflicts (TASK-200, 124, 125, 126)
- Manager-7: Successfully resolved app/api/roll.py and scripts/create_user_tasks.py conflicts

### Python 3.13 Compatibility Verification

**Problem:** False compatibility claims wasting time on incorrect assumptions.
**Solution:** Fact-check before claiming incompatibility.
**Implementation:** Create fact-checking agent to verify compatibility.
**Result:** Avoided wasted 30 minutes on incorrect assumptions about pytest-playwright and uvicorn.
**Evidence:** Manager-3 learned lesson after false claim, fact-checking confirmed full compatibility.

### Performance Optimization: O(n) to O(1) (RESOLVED)

**Problem:** Queue position updates had O(n) memory usage.
**Solution:** Use single SQL UPDATE with CASE statement instead of loop.
**Implementation:** `comic_pile/queue.py` updated with bulk update pattern.
**Result:** Queue operations now O(1) memory usage.
**Evidence:** Manager-3 completed TASK-124 performance optimization.

### Playwright Integration Testing (RESOLVED)

**Problem:** Need end-to-end integration tests with browser automation.
**Solution:** Add pytest-playwright for browser automation testing.
**Implementation:**
- Installed pytest-playwright (1.48.0 supports Python 3.13)
- Added pytest markers configuration to pyproject.toml
- Created integration tests in `tests/integration/test_workflows.py`
**Result:** End-to-end browser automation tests working.
**Evidence:** Manager-3 completed TASK-126 Playwright integration.

---

## Technical Debt

This section summarizes known technical debt items. See TECH_DEBT.md for full details.

### Critical Priority

1. **d10 Die Rendering Visibility Problem**
   - Location: `static/js/dice3d.js:13, 136-140`
   - Multiple fix attempts failed (TASK-121, TASK-123, TASK-125)
   - Manager-3 attempted fix: CylinderGeometry instead of Decahedron (wrong)
   - Manager-3 attempted fix: DecahedronGeometry (still invisible)
   - Root cause unknown: geometry may be correct, but die not visible (material, lighting, scene, camera)
   - Requires browser DevTools investigation or alternative 2D approach
   - Estimated effort: 4-8 hours (deep investigation) or 2-3 hours (alternative 2D approach)

### High Priority

2. **POST /tasks/ Endpoint Missing**
   - Location: `app/api/tasks.py`
   - Task creation endpoint removed in earlier work, causing database-only task creation
   - Required Python database insertion script to create tasks (TASK-114 through TASK-122)
   - Lost API consistency - tasks created outside of Task API
   - More cognitive load - had to manually verify database insertion
   - No audit trail for task creation
   - Estimated effort: 2-3 hours (restore endpoint or document workflow)

3. **Integration Test Database Isolation**
   - Location: `tests/integration/conftest.py`
   - Issue: In-memory SQLite database not shared across test connections
   - Tests failed with "no such table: settings" errors
   - Root cause: Each test connection had isolated in-memory database
   - Resolution: Use `sqlite:///file::memory:?cache=shared` for shared access
   - Estimated effort: 30 minutes (completed in Manager-7)
   - Status: RESOLVED

4. **Uvicorn Version Corruption (Manager-2)**
   - Location: Dependency (uvicorn)
   - Issue: uvicorn 0.40.0 had corrupted importer.py causing SyntaxError
   - Blocked all development work with SyntaxError
   - Resolution: Pinned uvicorn to 0.39.0
   - Estimated effort: 10 minutes
   - Status: RESOLVED

5. **Python 3.13 Compatibility False Claims (Manager-3)**
   - Location: TASK-126 task
   - Issue: Initial agent incorrectly claimed Python 3.13 incompatible with pytest-playwright and uvicorn
   - Wasted 30 minutes on incorrect assumptions
   - Reality: pytest-playwright 1.48.0 and uvicorn 0.40.0 both support Python 3.13
   - Required fact-checking agent to verify compatibility
   - Estimated effort: 30 minutes (wasted before verification)
   - Status: RESOLVED (lesson learned: fact-check before claiming incompatibility)

6. **Hardcoded Task Data in tasks.py**
   - Location: `app/api/tasks.py:26-124` (TASK_DATA dictionary)
   - 12 PRD tasks hardcoded as dict instead of loaded from database
   - Server restart required to add/modify tasks
   - Estimated effort: 2-3 hours

3. **ImportError Try/Except Pattern Throughout Codebase**
   - Location: Multiple files (session.py, roll.py, queue.py, thread.py, rate.py)
   - All API modules import `clear_cache` and `get_current_session_cached` from app.main with try/except
   - Circular import concern causing defensive programming
   - Estimated effort: 2-3 hours (extract to separate cache module)

4. **No Transaction Management for Complex Operations**
   - Location: Queue operations, CSV import
   - Multiple database commits for single logical operation without transaction boundary
   - Violates ACID principles for multi-step operations
   - Estimated effort: 3-4 hours

5. **Missing Review Timestamp Import Implementation**
   - Location: TASK-111 status (in_review)
   - API endpoint to import review timestamps from League of Comic Geeks
   - Without this feature, staleness awareness lacks data source
   - Estimated effort: 1-2 hours (review and merge)

6. **Missing Narrative Summary Export Implementation**
   - Location: TASK-112 status (in_review)
   - Export endpoint for narrative session summaries
   - Users can only view summaries in UI, not download
   - Estimated effort: 1-2 hours (review and merge)

### Medium Priority

7. **Module-Level Caching Without Invalidation Strategy**
   - Location: `app/main.py:22-83`
   - Only invalidation is `clear_cache()` which clears entire cache
   - No selective invalidation
   - Estimated effort: 4-6 hours

8. **Hardcoded user_id=1 Throughout Codebase**
   - Location: Multiple locations (roll.py, rate.py, thread.py, admin.py)
   - User ID hardcoded to 1 in all operations
   - Multi-user support impossible without code changes
   - Estimated effort: 2-3 hours (document) or 6-8 hours (add auth)

9. **CORS Configuration Allows All Origins**
   - Location: `app/main.py:95-101`
   - CORS configured with `allow_origins=["*"]` for all requests
   - Security risk: any origin can access API
   - Estimated effort: 1-2 hours

10. **Session Detection Logic Duplication**
    - Location: `comic_pile/session.py`
    - `is_active()` and `get_or_create()` both check 6-hour threshold independently
    - Magic number `6 hours` duplicated (should be constant)
    - Estimated effort: 1-2 hours

... (see TECH_DEBT.md for items 11-26)

**Total Items:** 26
**Critical:** 1
**High:** 6
**Medium:** 10
**Low:** 9

**Total Estimated Effort:** 60-100 hours (depending on priorities chosen)

---

## Known Issues

### d10 Die Rendering

**Problem:** Despite geometry fixes, d10 die may still have rendering issues (invisible or not displaying correctly).

**History:**
- TASK-121 attempted fix (geometry changes)
- TASK-123 attempted fix (additional geometry adjustments)
- Both attempts failed to resolve issue
- Geometry is correct (DecahedronGeometry), but die may not be visible

**Possible Causes:**
- Material properties (color, lighting)
- Scene addition not working
- Camera positioning incorrect
- Three.js version incompatibility
- Three.js-dice library bug

**Suggested Approaches:**
1. Use browser DevTools to inspect: mesh creation, scene addition, material properties, lighting, camera positioning
2. Compare d10 with working dice (d12, d20) for differences
3. Consider alternative: replace with 2D SVG dice if 3D proves too complex
4. May require refactoring entire dice3d.js library or switching to different three.js-dice implementation

**Estimated Effort:** 4-8 hours (deep investigation) or 2-3 hours (alternative 2D approach)

**Priority:** Critical (blocking dice rolling functionality for d10)

---

## Deployment

### Development

```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies
uv sync --all-extras

# Run migrations
make migrate

# Seed database (optional)
make seed

# Run development server
make dev
```

**Access:** http://localhost:8000

### Production Options

#### Option 1: SQLite (Single User)

- Keep SQLite database
- Use uvicorn directly
- Simple deployment
- No database server needed

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

#### Option 2: PostgreSQL (Multi-User/Production)

- Migrate to PostgreSQL
- See DOCKER_MIGRATION.md for detailed guide
- Better concurrency
- More robust for production

```bash
# Use docker-compose.prod.yml
docker-compose -f docker-compose.prod.yml up -d
```

**Key Differences:**
- PostgreSQL supports concurrent writes
- Better for multi-user scenarios
- Requires PostgreSQL server
- Slightly more complex deployment

---

## Performance

### Caching

- Thread data cached for 30s TTL
- Session data cached for 10s TTL
- Cache cleared on mutations
- No selective invalidation

### Database Queries

- Use SQLAlchemy ORM for queries
- Indexes on: tasks.task_id, tasks.status, threads.status
- No N+1 query issues detected
- Potential optimization: queue position updates (see TECH_DEBT.md item #14)

### Frontend Performance

- HTMX uses vanilla JavaScript (fast)
- Tailwind CSS via CDN (cached)
- Minimal custom JavaScript
- 3D dice rendering: Three.js with canvas

---

## Security Considerations

### Current Security Model

- No authentication/authorization (single-user app)
- CORS allows all origins (`allow_origins=["*"]`)
- No rate limiting
- No input validation beyond Pydantic schemas
- No HTTPS enforcement (local network access only)

### Security Recommendations

1. **CORS Configuration:**
   - Move origins to environment variable: `CORS_ORIGINS`
   - Parse comma-separated list: `localhost:3000,https://app.example.com`
   - Default to specific origins for production

2. **Rate Limiting:**
   - Add rate limiting middleware (e.g., slowapi)
   - Configure limits per endpoint:
     - Roll endpoint: 10 requests per minute
     - Rate endpoint: 5 requests per minute
     - Other endpoints: 60 requests per minute

3. **Input Validation:**
   - Pydantic schemas already validate input
   - No additional validation needed currently

4. **HTTPS Enforcement:**
   - Add TLS termination (nginx, reverse proxy)
   - Redirect HTTP to HTTPS
   - Use environment variables for SSL certificates

**Note:** Security improvements documented as technical debt (items #9, #15).

---

## Monitoring and Logging

### Current State

- No structured logging
- No request logging middleware
- No monitoring endpoints
- No alerting
- Logs output to stdout only

### Recommendations

1. **Add Request Logging Middleware:**
   - Log: timestamp, method, path, status code, duration
   - Add request ID for traceability
   - Configure log levels appropriately

2. **Add Health Check Endpoint:**
   - Check: database connection, cache status
   - Return 200 OK if healthy, 503 if not

3. **Structured Logging:**
   - Use JSON logging format
   - Add correlation IDs
   - Centralize logs (Loki, ELK, etc.)

**Note:** Monitoring improvements documented as technical debt (items #17, #25).

---

## Scalability Considerations

### Current Limitations

- Single SQLite database (not multi-writer safe)
- In-memory caching (not multi-instance safe)
- No horizontal scaling capability
- No load balancing support

### When to Scale Up

Consider these changes if:
- Multiple users need concurrent access
- Database performance becomes bottleneck
- Need high availability (99.9%+ uptime)
- Deploying to public internet (not just local network)

### Scaling Options

1. **Database:**
   - Migrate to PostgreSQL
   - Add connection pooling
   - Consider read replicas

2. **Caching:**
   - Switch to Redis
   - Shared cache across instances
   - Selective invalidation

3. **Application:**
   - Run multiple instances behind load balancer
   - Use Kubernetes for orchestration
   - Add health checks and auto-scaling

**Note:** See ARCHITECTURE_TASK_API.md for detailed analysis of extracting Task API to separate service.

---

## Architecture Decisions Rationale

### Why Monolithic Architecture?

**Pros:**
- Simple deployment (single process)
- Easy to test (single codebase)
- Fast development (no inter-service communication)
- Low operational complexity
- Good for single-user, hobbyist project

**Cons:**
- Can't scale components independently
- Technology choices apply to entire app
- Harder to evolve features independently

**Decision:** Monolithic is appropriate for current scale (single user, hobbyist project). Extract to microservices only if justified by actual requirements.

### Why SQLite?

**Pros:**
- No database server needed
- Embedded database (single file)
- Easy local development
- Fast for small datasets
- ACID compliant

**Cons:**
- Not multi-writer safe
- Limited concurrent connections
- Scales poorly for large datasets

**Decision:** SQLite is appropriate for single-user app. Migrate to PostgreSQL if multi-user support needed.

### Why HTMX?

**Pros:**
- No JavaScript framework needed
- Server-side rendering (simple)
- Declarative markup
- Fast development
- Good accessibility

**Cons:**
- Not suitable for complex UIs
- Limited client-side state
- Network latency for every interaction

**Decision:** HTMX is perfect for this app's simple UI. Good enough for dice rolling, rating, and queue management.

### Why Tailwind CSS?

**Pros:**
- Utility-first (fast development)
- No custom CSS needed
- Responsive by default
- Mobile-first design
- CDN for development

**Cons:**
- Large CSS file (if not optimized)
- Can get verbose in HTML
- Learning curve for utility classes

**Decision:** Tailwind is standard for modern web apps. Good tradeoff for fast development and consistent styling.

---

## Future Architecture Considerations

### Multi-User Support

If multi-user support is needed, consider:

1. **Authentication:**
   - Add JWT or session-based auth
   - Add user context dependency in FastAPI
   - Replace all `user_id=1` with `user.id`

2. **Authorization:**
   - Users can only access their own threads/sessions
   - Add row-level security in queries
   - Use SQLAlchemy filters for user isolation

3. **Database:**
   - Migrate to PostgreSQL for concurrency
   - Add foreign key constraints
   - Add indexes on user_id columns

4. **Caching:**
   - Switch to Redis for multi-instance support
   - Add user-specific cache keys
   - Implement cache invalidation per user

**Estimated Effort:** 20-40 hours

### Native Mobile App

If native mobile app is needed, API is already designed for it:

1. **API-First Design:**
   - All endpoints documented with OpenAPI
   - JSON request/response
   - No HTML responses for mobile

2. **Authentication:**
   - Add JWT for mobile client auth
   - Add refresh token rotation
   - Store tokens securely (Keychain, Keystore)

3. **Offline Support:**
   - Add sync endpoints (GET /threads/sync, POST /threads/sync)
   - Handle conflict resolution
   - Use SQLite for local cache

**Estimated Effort:** 40-80 hours (depending on platforms)

### Extract Task API to Separate Service

If Task API extraction is justified (see ARCHITECTURE_TASK_API.md):

1. **Strangler Fig Pattern:**
   - Incremental migration
   - Phase 1: Read-only endpoints (GET /tasks/, GET /tasks/{id})
   - Phase 2: Write endpoints (POST /tasks/{id}/claim, /heartbeat, /update-notes)
   - Phase 3: Status and unclaim endpoints

2. **Shared Database Initially:**
   - Both services access same SQLite
   - Maintain referential integrity
   - Separate databases later if needed

3. **Inter-Service Auth:**
   - Simple API key shared secret
   - Upgrade to JWT if needed

**Estimated Effort:** 2-4 weeks (19-22 days)

**Note:** ARCHITECTURE_TASK_API.md recommends keeping Task API in Comic Pile for now. Extract only if justified by actual requirements.
