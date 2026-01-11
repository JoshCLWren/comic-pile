# Technical Debt - Comic Pile

**Last Updated:** 2026-01-01
**Project Status:** Production Ready (Phase 10 - PRD Alignment in progress)
**Current Coverage:** 96% (configured in pyproject.toml)

---

## Critical Priority (Blocking Issues)

### ~~1. d10 Die Rendering Visibility Problem~~ ~~RESOLVED~~
**Location:** `frontend/src/components/Dice3D.jsx:220` (`createD10Geometry`)
**Status:** Fixed in January 2026
**What Was Wrong:**
- Original implementation used 5 ring vertices instead of 10 (pentagonal trapezohedron needs zigzag belt)
- Incorrect triangulation created "collapsed funnel" appearance
- UV mapping shared vertices instead of per-face unique vertices
**What Was Fixed:**
- Replaced geometry with proper pentagonal trapezohedron: 12 vertices (2 poles + 10 belt)
- 10 kite faces, each split into 2 triangles (20 triangles total)
- Per-face vertex duplication for proper UV mapping
- Classic d10 silhouette with congruent kite faces
**Evidence:** PR to close GitHub issue #121

---

## High Priority (Impacting Reliability or Scalability)

### 2. Hardcoded Task Data in tasks.py
**Location:** `app/api/tasks.py:26-124` (TASK_DATA dictionary)
**Description:** 12 PRD tasks hardcoded as dict instead of loaded from database
**Why It's Debt:**
- Server restart required to add/modify tasks
- Database initialization endpoint `/tasks/initialize` reads from this dict
- Violates database-first design principle
- Causes 404 errors when referencing non-existent tasks
- Source of confusion: dashboard auto-refreshes but shows errors
**Suggested Approach:**
- Remove TASK_DATA dictionary entirely
- Keep only `POST /api/tasks/` and `POST /api/tasks/bulk` endpoints for task creation
- Document that tasks should be created via API or direct database insertion
- Consider removing `/tasks/initialize` endpoint or making it load from seed data file
**Estimated Effort:** 2-3 hours

### 3. ImportError Try/Except Pattern Throughout Codebase
**Location:** Multiple files:
- `app/api/session.py:21-25`
- `app/api/roll.py:20-23`
- `app/api/queue.py:14-17`
- `app/api/thread.py:36-40`
- `app/api/rate.py:18-21`
**Description:** All API modules import `clear_cache` and sometimes `get_current_session_cached` from app.main with try/except
**Why It's Debt:**
- Circular import concern causing defensive programming
- `clear_cache` is imported but may be None, requiring None checks before use
- Creates fragile code paths that silently degrade
- Makes testing harder (imports may or may not work)
**Suggested Approach:**
- Extract cache functions to separate module (e.g., `app/cache.py`)
- Import from cache module directly without try/except
- Remove all `if clear_cache:` checks
- Cleaner dependency injection through FastAPI dependencies
**Estimated Effort:** 2-3 hours

### 4. No Transaction Management for Complex Operations
**Location:** Various locations:
- `comic_pile/queue.py:29` (move_to_front)
- `comic_pile/queue.py:53` (move_to_back)
- `comic_pile/queue.py:95` (move_to_position)
- `app/api/admin.py:84-90` (CSV import)
**Description:** Multiple database commits for single logical operation without transaction boundary
**Why It's Debt:**
- Queue repositioning updates multiple threads - if one update fails, others may commit
- CSV import: threads added, then positions adjusted - could be inconsistent if position update fails
- No rollback mechanism for partial failures
- Violates ACID principles for multi-step operations
**Suggested Approach:**
- Use `with db.begin():` context manager for multi-step operations
- Wrap critical sections (queue moves, imports) in transactions
- Test rollback scenarios explicitly
- Consider SQLAlchemy `bulk_update_mappings()` for better performance with atomicity
**Estimated Effort:** 3-4 hours

### 5. Missing Review Timestamp Import Implementation
**Location:** TASK-111 status (in_review)
**Description:** API endpoint to import review timestamps from League of Comic Geeks is in review but not merged
**Why It's Debt:**
- PRD Section 9 requires importing scraped review timestamps
- `last_review_at` field exists in Thread model (TASK-110 completed)
- Without this feature, staleness awareness (TASK-102) lacks data source
- Blocks PRD alignment completion
**Suggested Approach:**
- Review TASK-111 implementation in worktree `../comic-pile-work-agent10`
- Verify endpoint `POST /admin/import/reviews/` works correctly
- Test CSV parsing: thread_id, review_url, review_timestamp
- Update thread's `last_review_at` field and commit
- Add integration tests for import endpoint
- Merge if approved
**Estimated Effort:** 1-2 hours (review and merge)

### 6. Missing Narrative Summary Export Implementation
**Location:** TASK-112 status (in_review)
**Description:** Export endpoint for narrative session summaries is in review but not merged
**Why It's Debt:**
- PRD Section 11 requires narrative session summaries in export format
- `build_narrative_summary()` function implemented (TASK-101 completed)
- Without export, users can only view summaries in UI, not download
- Blocks PRD alignment completion
**Suggested Approach:**
- Review TASK-112 implementation in worktree (if exists)
- Create endpoint `GET /admin/export/summary/`
- Generate markdown-formatted summaries for all sessions
- Return as StreamingResponse for download
- Add export button in history.html
- Test with sample data
- Merge if approved
**Estimated Effort:** 1-2 hours (review and merge)

---

## Medium Priority (Code Quality, Maintainability)

### 7. Module-Level Caching Without Invalidation Strategy
**Location:** `app/main.py:22-83`
**Description:** Simple dict-based cache with TTL, no invalidation strategy beyond clearing all
**Why It's Debt:**
- Only invalidation is `clear_cache()` which clears entire cache
- Thread data cached for 30s, session data for 10s
- No selective invalidation (e.g., invalidate specific thread)
- Stale data served until TTL expires or cache cleared
- `get_threads_cached()` and `get_current_session_cached()` manually clear cache via function calls
**Suggested Approach:**
- Switch to proper caching library (e.g., cachetools, FastAPI Cache)
- Implement cache keys based on query parameters and entity IDs
- Add selective invalidation: invalidate thread when updated
- Consider Redis for multi-instance deployments
- Document cache invalidation strategy
**Estimated Effort:** 4-6 hours

### 8. Hardcoded user_id=1 Throughout Codebase
**Location:** Multiple locations:
- `app/api/roll.py:29,157,196`
- `app/api/rate.py:27`
- `app/api/thread.py:115`
- `app/api/admin.py:19`
**Description:** User ID hardcoded to 1 in all operations
**Why It's Debt:**
- Multi-user support impossible without code changes
- Every user operation affects the same user
- No way to test multi-user scenarios
- PRD documents single-user but hardcoding limits future flexibility
**Suggested Approach:**
- Add authentication (JWT or session-based) if multi-user needed
- Or, accept single-user as design choice and document clearly
- Create user context dependency in FastAPI:
  ```python
  async def get_current_user() -> User:
      return user  # Single-user mode
  ```
- Replace all `user_id=1` with `user.id` from dependency
- Add tests for context extraction
**Estimated Effort:** 2-3 hours (document single-user) or 6-8 hours (add auth)

### 9. CORS Configuration Allows All Origins
**Location:** `app/main.py:95-101`
**Description:** CORS configured with `allow_origins=["*"]` for all requests
**Why It's Debt:**
- Security risk: any origin can access API
- Documented as "for local network access during development"
- Not safe for production deployment
- May expose user data to unauthorized origins
**Suggested Approach:**
- Move CORS origins to environment variable: `CORS_ORIGINS`
- Parse comma-separated list: `localhost:3000,https://app.example.com`
- Default to specific origins for production, keep "*" for development
- Document CORS configuration in README
- Add tests to verify CORS headers
**Estimated Effort:** 1-2 hours

### 10. Session Detection Logic Duplication
**Location:** `comic_pile/session.py:12-15, 36-46`
**Description:** `is_active()` and `get_or_create()` both check 6-hour threshold independently
**Why It's Debt:**
- Magic number `6 hours` duplicated (should be constant)
- Logic is tightly coupled but separated into two functions
- Changing session timeout requires updating multiple places
- `should_start_new()` also has similar 6-hour check
**Suggested Approach:**
- Define constant: `SESSION_TIMEOUT_HOURS = 6`
- Extract threshold calculation to helper function: `is_session_active(session)`
- Use helper in both `is_active()` and `get_or_create()`
- Consider caching recent session queries to reduce database hits
- Add tests for session timeout edge cases
**Estimated Effort:** 1-2 hours

### 11. Missing Type Hints in Some Functions
**Location:** Various locations identified by ruff ANN401:
- `app/main.py` (multiple functions)
- `app/api/session.py:88-115` (get_active_thread)
- Some utility functions
**Description:** Not all functions have complete type annotations
**Why It's Debt:**
- Ruff ANN401 rule enabled (no Any type allowed)
- Reduces type safety and IDE assistance
- Makes refactoring harder
- May mask bugs passed as Any
**Suggested Approach:**
- Run `ruff check --select ANN401` to find all missing types
- Add precise type hints to all function signatures
- Use typing imports: `from typing import Any` only when truly necessary
- Consider pydantic models for complex return types
- Run pyright to verify types are correct
**Estimated Effort:** 2-3 hours

### 12. Incomplete Error Messages in Some Endpoints
**Location:** Various API endpoints:
- `app/api/roll.py:152-155` ("No active threads available to roll")
- `app/api/rate.py:38-41` ("No active session. Please roll the dice first.")
**Description:** Some errors lack context or guidance
**Why It's Debt:**
- Generic error messages don't help users resolve issues
- No information about what data is missing or invalid
- May lead to repeated failed attempts
**Suggested Approach:**
- Add context to error messages: "No active threads. Create a thread first."
- Include validation details: "Thread X not found. Check thread ID."
- Use HTTP status codes appropriately (400 vs 404 vs 422)
- Consider structured error responses with field-level validation
- Add tests for error scenarios
**Estimated Effort:** 2-3 hours

### 13. Dice Ladder Step Functions Don't Enforce Bounds
**Location:** `comic_pile/dice_ladder.py:6-39`
**Description:** `step_up()` and `step_down()` don't validate die is in ladder
**Why It's Debt:**
- If invalid die passed, returns same die (fallback behavior unclear)
- No logging when invalid die encountered
- May cause issues if die gets corrupted in database
**Suggested Approach:**
- Add validation: raise ValueError if die not in DICE_LADDER
- Add logging when edge cases hit
- Or, document fallback behavior clearly
- Add tests for invalid die sizes
**Estimated Effort:** 1 hour

### 14. Queue Position Updates Not Atomic
**Location:** `comic_pile/queue.py:11-29, 32-53, 56-95`
**Description:** Queue repositioning loops through threads and updates positions one by one
**Why It's Debt:**
- Multiple UPDATE statements for single move operation
- Race condition risk if concurrent updates
- Performance concern for large queues
**Suggested Approach:**
- Use single SQL UPDATE with CASE statement
- Example: `UPDATE threads SET queue_position = CASE id WHEN ... END`
- Or, use SQLAlchemy bulk operations
- Add tests for concurrent queue updates
**Estimated Effort:** 3-4 hours

### 15. No Rate Limiting on API Endpoints
**Location:** All API routes (none have rate limiting)
**Description:** No rate limiting implemented on any endpoint
**Why It's Debt:**
- Vulnerable to abuse (e.g., repeated roll attempts)
- No protection against DoS attacks
- Could impact database performance
- Documented as single-user app but still a concern
**Suggested Approach:**
- Add rate limiting middleware (e.g., slowapi)
- Configure limits per endpoint:
  - Roll endpoint: 10 requests per minute
  - Rate endpoint: 5 requests per minute
  - Other endpoints: 60 requests per minute
- Document rate limits in API docs
- Add tests for rate limiting
**Estimated Effort:** 4-6 hours

---

## Low Priority (Nice-to-Have Improvements)

### 16. No Authentication/Authorization System
**Location:** Entire application (no auth middleware)
**Description:** All endpoints are public, no user authentication
**Why It's Debt:**
- Documented as single-user application
- Still, no authentication limits deployment scenarios
- API docs show "Authentication: Not required (single-user application)"
**Suggested Approach:**
- Accept single-user as design decision (document clearly)
- Or, add minimal auth if multi-user needed:
  - Simple password-based auth via FastAPI Security
  - Or OAuth integration (complex)
- Add API key authentication for external access
**Estimated Effort:** 0 hours (document) or 8-12 hours (implement auth)

### 17. No Request Logging Middleware
**Location:** `app/main.py` (no logging middleware configured)
**Description:** No structured logging of API requests
**Why It's Debt:**
- Difficult to debug production issues without request logs
- No audit trail of API calls
- Can't monitor usage patterns
**Suggested Approach:**
- Add request logging middleware (FastAPI has built-in support)
- Log: timestamp, method, path, status code, duration
- Add request ID for traceability
- Configure log levels appropriately
- Document log format and retention
**Estimated Effort:** 2-3 hours

### 18. Test Coverage May Not Be at 96%
**Location:** `tests/` directory (need to verify)
**Description:** Coverage configured for 96% but not verified if actual coverage meets threshold
**Why It's Debt:**
- May have gaps in test coverage
- CI runs `make pytest` but coverage may not be checked
- Risk of untested code paths
**Suggested Approach:**
- Run `pytest --cov=comic_pile --cov-report=term-missing`
- Review uncovered lines
- Add tests for missing coverage:
  - Edge cases in dice ladder
  - Error paths in API endpoints
  - Queue position edge cases
  - Session timeout edge cases
- Update coverage threshold if reasonable
**Estimated Effort:** 4-6 hours

### 19. No Database Migration Downgrade Scripts
**Location:** `alembic/versions/` (only upgrade scripts tested)
**Description:** Alembic migrations created but downgrade paths not tested
**Why It's Debt:**
- Risk if need to rollback migration
- Downgrade scripts auto-generated but not verified
- Could cause data loss or corruption
**Suggested Approach:**
- Test downgrade paths for recent migrations
- Document rollback procedure
- Consider backup strategy before migrations
- Add tests for upgrade/downgrade cycles
**Estimated Effort:** 2-3 hours

### 20. No Background Job Queue for Long Operations
**Location:** Synchronous operations only (no async task queue)
**Description:** All operations run synchronously in request handlers
**Why It's Debt:**
- CSV import of large files blocks request
- JSON export of large database times out
- No progress feedback for long operations
**Suggested Approach:**
- Add background task queue (e.g., Celery, RQ, or FastAPI BackgroundTasks)
- For simple use case: FastAPI `BackgroundTasks` sufficient
- For complex use case: separate task queue service
- Add job status endpoint for progress tracking
**Estimated Effort:** 6-10 hours (BackgroundTasks) or 12-16 hours (Celery)

### 21. No API Versioning Strategy
**Location:** All routes at root level (no version prefix)
**Description:** No versioning (e.g., /v1/, /v2/) on API routes
**Why It's Debt:**
- Breaking changes affect all clients
- Can't maintain multiple API versions
- Makes evolution of API difficult
**Suggested Approach:**
- Add version prefix to all API routes: `/api/v1/threads/`
- Document versioning strategy in API docs
- Use header-based versioning if needed (e.g., `Accept: application/vnd.api+json; version=1`)
- Add deprecation warnings when endpoints change
**Estimated Effort:** 3-4 hours

### 22. No Pagination on List Endpoints
**Location:** Only `/sessions/` has pagination, others don't
**Description:** List endpoints return all records without pagination
**Why It's Debt:**
- Performance issue with large datasets
- Could cause memory issues
- Not scalable
**Suggested Approach:**
- Add pagination to `/threads/`, `/sessions/`, `/events/`
- Use `limit` and `offset` query parameters consistently
- Add `total_count` header or field
- Document pagination in API docs
**Estimated Effort:** 3-4 hours

### 23. No Configuration Management
**Location:** Hardcoded values throughout (session timeout, cache TTL, etc.)
**Description:** Configuration values scattered in code
**Why It's Debt:**
- Difficult to change settings
- No environment-specific configs (dev, staging, prod)
- Secrets may be hardcoded
**Suggested Approach:**
- Use Pydantic Settings for configuration
- Create `.env.example` file
- Load from environment variables with sensible defaults
- Document all configuration options
**Estimated Effort:** 2-3 hours

### 24. Manual SQL in Some Places
**Location:** `app/api/thread.py:229-231` (SQLAlchemy update statement)
**Description:** Raw SQLAlchemy update used instead of ORM
**Why It's Debt:**
- Mix of ORM and raw SQL inconsistent
- Harder to test
- Bypasses some ORM features (e.g., relationship loading)
**Suggested Approach:**
- Use ORM methods consistently
- For bulk operations, use `bulk_update_mappings()`
- Only use raw SQL for performance-critical sections (document why)
- Add tests for raw SQL paths
**Estimated Effort:** 1-2 hours

### 25. No Health Check Endpoint
**Location:** No `/health` or `/status` endpoint
**Description:** No endpoint to check application health
**Why It's Debt:**
- Can't monitor application uptime
- No way for load balancers to check health
- Difficult to debug deployment issues
**Suggested Approach:**
- Add `/health` endpoint
- Check: database connection, cache status
- Return 200 OK if healthy, 503 if not
- Document in operations docs
**Estimated Effort:** 1 hour

### 26. No API Documentation for Custom Endpoints
**Location:** Some endpoints lack detailed OpenAPI documentation
**Description:** FastAPI auto-generates docs but some details missing
**Why It's Debt:**
- Missing examples in request/response schemas
- No detailed descriptions for some endpoints
- Error responses not documented
**Suggested Approach:**
- Add `description` parameter to all route decorators
- Add `examples` to Pydantic schemas
- Document all possible error responses
- Update API.md with missing details
**Estimated Effort:** 3-4 hours

---

## In-Review Tasks (Awaiting Merge)

### TASK-111: Review Timestamp Import API
**Status:** in_review
**Worktree:** `../comic-pile-work-agent10`
**Action Needed:** Review and merge implementation
**Description:** Import review timestamps from League of Comic Geeks via CSV
**Estimated Effort to Complete:** 1-2 hours (review)

### TASK-112: Narrative Summary Export
**Status:** in_review
**Worktree:** Not specified in HANDOFF.md
**Action Needed:** Review and merge implementation
**Description:** Export narrative session summaries as downloadable markdown
**Estimated Effort to Complete:** 1-2 hours (review)

---

## Technical Debt Summary

**Total Items:** 26
- Critical: 1
- High: 6
- Medium: 10
- Low: 9

**Total Estimated Effort:** 60-100 hours (depending on priorities chosen)

---

## Prioritized Recommendations

### Immediate (Next Sprint)
1. **Fix d10 die rendering** (Critical - blocking feature)
2. **Merge TASK-111 and TASK-112** (High - complete PRD alignment)
3. **Remove hardcoded TASK_DATA** (High - architectural improvement)

### Short Term (Next 2-3 Sprints)
4. **Fix ImportError pattern** (High - code quality)
5. **Add transaction management** (High - data integrity)
6. **Extract cache module** (Medium - remove circular imports)

### Medium Term (Next Quarter)
7. **Add CORS configuration** (Medium - security)
8. **Add configuration management** (Low - maintainability)
9. **Add health check endpoint** (Low - operations)
10. **Improve test coverage** (Low - quality assurance)

### Long Term (Future)
11. **Consider multi-user support** (if needed)
12. **Add rate limiting** (if deploying to public)
13. **Add background job queue** (if handling large imports)

---

## Debt Tracking

This document should be reviewed and updated:
- After each major feature release
- When new dependencies are added
- When architectural decisions are made
- During quarterly planning meetings

To resolve a debt item:
1. Create a task in Task API: `POST /api/tasks/`
2. Set status to `pending`
3. Include description and estimated effort
4. Claim and implement following standard workflow
5. Update this document when complete
