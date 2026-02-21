# Technical Debt - Comic Pile

**Last Updated:** 2026-02-21
**Project Status:** Production Ready (Phase 10+ - Auth, Snooze, Undo features shipped)
**Current Coverage:** 96% (configured in pyproject.toml)

---

## Resolved Since Last Review (January 2026)

### ~~1. d10 Die Rendering Visibility Problem~~ ✅ RESOLVED
**Fixed:** January 2026. Replaced geometry with proper pentagonal trapezohedron.

### ~~2. Hardcoded Task Data in tasks.py~~ ✅ RESOLVED
**Fixed:** Tasks module and database table dropped entirely via migration `b0e386559bcb_drop_tasks_and_agent_metrics_tables.py`.

### ~~5. Missing Review Timestamp Import Implementation~~ ✅ RESOLVED
**Fixed:** `POST /admin/import/reviews/` endpoint merged and functional in `app/api/admin.py`. The `last_review_at` field on Thread model is populated via CSV import.

### ~~6. Missing Narrative Summary Export Implementation~~ ✅ RESOLVED
**Fixed:** `GET /export/summary/` endpoint merged and functional in `app/api/admin.py`. Exports markdown-formatted session summaries via `StreamingResponse`.

### ~~9. CORS Configuration Allows All Origins~~ ✅ RESOLVED
**Fixed:** CORS origins now loaded from `app/config.py` via Pydantic Settings. Production requires explicit `CORS_ORIGINS` env var or validation fails. `["*"]` only allowed in non-production environments.

### ~~10. Session Detection Logic Duplication~~ ✅ RESOLVED
**Fixed:** Session gap hours extracted to `DEFAULT_SESSION_GAP_HOURS = 6` constant in `app/constants.py`. Session functions use `get_session_settings().session_gap_hours` from centralized config.

### ~~13. Dice Ladder Step Functions Don't Enforce Bounds~~ ✅ RESOLVED
**Fixed:** `step_up()` and `step_down()` in `comic_pile/dice_ladder.py` now validate die size and raise `ValueError` for invalid inputs.

### ~~15. No Rate Limiting on API Endpoints~~ ✅ RESOLVED
**Fixed:** Rate limiting implemented via `slowapi` in `app/middleware/rate_limit.py`. Per-endpoint limits configured (e.g., `30/minute` for queue, `100/minute` for threads). Documentation at `docs/rate_limiting.md`.

### ~~16. No Authentication/Authorization System~~ ✅ RESOLVED
**Fixed:** Full JWT auth system implemented:
- `app/auth.py`: Password hashing (bcrypt), JWT creation/verification, token revocation via JTI blacklist
- `app/api/auth.py`: Register, login, refresh, logout, me endpoints
- `app/models/user.py`, `app/models/revoked_token.py`: Database models
- All API endpoints use `Depends(get_current_user)` for auth
- Plan documented in `docs/AUTH_USERS_MULTITENANT_PLAN.md`

### ~~23. No Configuration Management~~ ✅ RESOLVED
**Fixed:** Centralized Pydantic Settings in `app/config.py` with specialized settings classes for database, auth, app, session, and ratings. Environment variables loaded with sensible defaults.

### ~~25. No Health Check Endpoint~~ ✅ RESOLVED
**Fixed:** `GET /health` endpoint in `app/main.py` verifies database connectivity. Returns 200 with `{"status": "healthy"}` or 503 with error details.

---

## High Priority (Impacting Reliability or Scalability)

### 1. Dead Cache References Throughout API Modules
**Location:** 7 files:
- `app/api/queue.py:25`
- `app/api/snooze.py:29`
- `app/api/session.py:29-30`
- `app/api/roll.py:24`
- `app/api/thread.py:80-81`
- `app/api/rate.py:81`
- `app/api/undo.py:20`
**Description:** All API modules set `clear_cache = None` (and sometimes `get_threads_cached = None`, `get_current_session_cached = None`) at module level. The actual cache implementation was removed from `app/main.py`, but these dead references and conditional guards (`if clear_cache:`) remain.
**Why It's Debt:**
- Dead code that serves no purpose — the cache no longer exists
- `if clear_cache:` guards will never execute, creating misleading code paths
- `snooze.py` explicitly disables `get_current_session_cached` in test mode for a cache that doesn't exist
- New modules (undo.py) copied this pattern, spreading the dead code
**Suggested Approach:**
- Remove all `clear_cache = None` lines and `if clear_cache:` blocks
- Remove all `get_threads_cached = None` and `get_current_session_cached = None` references
- Remove the cache-disabling logic in `snooze.py:31-34`
- If caching is re-added later, use a proper library with dependency injection
**Estimated Effort:** 1-2 hours

### 2. No Transaction Management for Complex Operations
**Location:** Various locations:
- `comic_pile/queue.py:14-45` (move_to_front)
- `comic_pile/queue.py:47-91` (move_to_back)
- `comic_pile/queue.py:93-202` (move_to_position)
- `app/api/admin.py` (CSV import, review import)
**Description:** Multiple database operations for single logical actions without explicit transaction boundaries. Functions use `commit: bool = True` flags but no `db.begin()` context manager.
**Why It's Debt:**
- Queue repositioning updates multiple threads — partial failure leaves inconsistent state
- CSV import adds threads then adjusts positions — could be inconsistent on failure
- No rollback mechanism for partial failures
- Violates ACID principles for multi-step operations
**Suggested Approach:**
- Use `async with db.begin():` context manager for multi-step operations
- Wrap critical sections (queue moves, imports) in transactions
- Test rollback scenarios explicitly
**Estimated Effort:** 3-4 hours

### 3. Remaining Hardcoded user_id=1 in Admin Endpoints
**Location:**
- `app/api/admin.py:91` (`recreate_default_user` endpoint)
- `app/api/admin.py:280` (`get_all_sessions` query)
**Description:** While core API endpoints now use `current_user.id` from auth, admin endpoints still hardcode `user_id=1`.
**Why It's Debt:**
- Inconsistent with the rest of the codebase which uses auth
- Admin endpoints won't work correctly for non-default users
- Blocks full multi-tenant support
**Suggested Approach:**
- Replace `user_id=1` with `current_user.id` from `get_current_user` dependency
- Add admin role check if these should be restricted
**Estimated Effort:** 1 hour

---

## Medium Priority (Code Quality, Maintainability)

### 4. `Any` Type Import in app/main.py
**Location:** `app/main.py:12` (`from typing import Any, cast`)
**Description:** `Any` is imported and used in the rate limit exception handler cast. Ruff ANN401 prohibits `Any` usage.
**Why It's Debt:**
- Inconsistent with project rule of no `Any` types
- Currently passes linting only because it's used in a `cast()` call, not an annotation
- Sets a bad precedent for other modules
**Suggested Approach:**
- Replace `cast(Callable[[Request, Any], Awaitable[Response]], ...)` with a properly typed wrapper or protocol
**Estimated Effort:** 30 minutes

### 5. Error-Only Request Logging
**Location:** `app/main.py:176-228` (`log_errors_middleware`)
**Description:** Request logging middleware only logs requests with status ≥ 400. Successful requests are not logged.
**Why It's Debt:**
- No audit trail of successful API calls
- Can't monitor usage patterns or performance trends
- Difficult to debug issues that don't produce errors
**Suggested Approach:**
- Add optional success request logging (configurable via env var to avoid noise)
- Log: timestamp, method, path, status code, duration for all requests
- Keep error logging verbose, success logging minimal
**Estimated Effort:** 1-2 hours

### 6. Queue Position Updates Not Atomic
**Location:** `comic_pile/queue.py:93-202`
**Description:** Queue repositioning loops through threads and updates positions one by one with individual UPDATE statements.
**Why It's Debt:**
- Multiple UPDATE statements for single move operation
- Performance degrades with large queues
- No bulk update optimization
**Suggested Approach:**
- Use `bulk_update_mappings()` or a single UPDATE with CASE expression
- Combine with transaction management (Item #2)
**Estimated Effort:** 2-3 hours

### 7. Manual SQL in Some Places
**Location:** `app/api/thread.py` (SQLAlchemy update statements)
**Description:** Mix of ORM and raw SQLAlchemy update statements
**Why It's Debt:**
- Inconsistent data access patterns
- Harder to test raw SQL paths
- Bypasses some ORM features
**Suggested Approach:**
- Use ORM methods consistently
- For bulk operations, use `bulk_update_mappings()`
- Only use raw SQL for performance-critical sections (document why)
**Estimated Effort:** 1-2 hours

### 8. Incomplete Error Messages in Some Endpoints
**Location:** Various API endpoints:
- `app/api/roll.py` ("No active threads available to roll")
- `app/api/rate.py` ("No active session. Please roll the dice first.")
**Description:** Some errors lack context or actionable guidance
**Why It's Debt:**
- Generic error messages don't help users resolve issues
- May lead to repeated failed attempts
**Suggested Approach:**
- Add context to error messages with actionable next steps
- Use HTTP status codes appropriately (400 vs 404 vs 422)
**Estimated Effort:** 2-3 hours

---

## Low Priority (Nice-to-Have Improvements)

### 9. No API Versioning Strategy
**Location:** All routes at `/api/` level (no version prefix)
**Description:** No versioning (e.g., `/api/v1/`) on API routes
**Why It's Debt:**
- Breaking changes affect all clients
- Can't maintain multiple API versions
**Suggested Approach:**
- Add version prefix to all API routes: `/api/v1/threads/`
- Document versioning strategy
**Estimated Effort:** 3-4 hours

### 10. No Pagination on Most List Endpoints
**Location:** Only `/sessions/` has pagination
**Description:** `/threads/` and other list endpoints return all records without pagination
**Why It's Debt:**
- Performance issue with large datasets
- Not scalable
**Suggested Approach:**
- Add `limit` and `offset` query parameters to `/threads/`, `/events/`
- Add `total_count` to responses
**Estimated Effort:** 3-4 hours

### 11. No Database Migration Downgrade Testing
**Location:** `alembic/versions/`
**Description:** Downgrade scripts are implemented but not tested in CI
**Why It's Debt:**
- Risk if need to rollback migration in production
- Downgrade scripts may have issues not caught until needed
**Suggested Approach:**
- Add CI step to test upgrade/downgrade cycles for recent migrations
- Document rollback procedure
**Estimated Effort:** 2-3 hours

### 12. No Background Job Queue for Long Operations
**Location:** `app/api/admin.py` (CSV import, JSON export, review import all blocking)
**Description:** All operations run synchronously in request handlers
**Why It's Debt:**
- Large CSV imports block the request
- JSON export of large database may time out
- No progress feedback for long operations
**Suggested Approach:**
- Use FastAPI `BackgroundTasks` for import/export operations
- Add job status endpoint for progress tracking
**Estimated Effort:** 6-10 hours

### 13. No API Documentation for Custom Endpoints
**Location:** Some endpoints lack detailed OpenAPI documentation
**Description:** FastAPI auto-generates docs but some details missing
**Why It's Debt:**
- Missing examples in request/response schemas
- Error responses not documented
**Suggested Approach:**
- Add `description` parameter to all route decorators
- Add `examples` to Pydantic schemas
- Document all possible error responses
**Estimated Effort:** 3-4 hours

---

## Technical Debt Summary

**Total Items:** 13 (active) + 11 resolved
- Resolved: 11
- High: 3
- Medium: 4
- Low: 5

**Total Estimated Effort (active items):** 25-40 hours

---

## Prioritized Recommendations

### Immediate (Next Sprint)
1. **Remove dead cache references** (High - dead code in 7 files)
2. **Fix admin hardcoded user_id=1** (High - inconsistent with auth system)

### Short Term (Next 2-3 Sprints)
3. **Add transaction management** (High - data integrity)
4. **Fix `Any` type usage** (Medium - code quality)
5. **Make queue updates atomic** (Medium - performance + integrity)

### Medium Term (Next Quarter)
6. **Add success request logging** (Medium - observability)
7. **Add pagination to list endpoints** (Low - scalability)
8. **Add background tasks for imports** (Low - user experience)

### Long Term (Future)
9. **Add API versioning** (if breaking changes needed)
10. **Test migration downgrades in CI** (operational safety)

---

## Debt Tracking

This document should be reviewed and updated:
- After each major feature release
- When new dependencies are added
- When architectural decisions are made
- During quarterly planning meetings

To resolve a debt item:
1. Create a branch: `git checkout -b fix/debt-item-description`
2. Implement the fix
3. Run `make lint` and `make pytest` before committing
4. Update this document when complete
