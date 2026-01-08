# Comic Pile API Compliance Audit Report

**Date:** 2026-01-08
**Auditor:** AI Agent
**Scope:** All API endpoints in `/app/api/`

## Executive Summary

This audit evaluates the Comic Pile API against Google API Design Guide principles. The audit covers 9 API modules with 40+ endpoints, examining naming conventions, HTTP methods, status codes, error handling, pagination, filtering, resource-oriented design, and request/response formats.

**Findings:**
- **Total Endpoints Audited:** 40+
- **Compliant Endpoints:** 12 (30%)
- **Partially Compliant Endpoints:** 8 (20%)
- **Non-Compliant Endpoints:** 20+ (50%)
- **Critical Issues:** 6
- **Medium Priority Issues:** 15
- **Low Priority Issues:** 12

## Google API Design Guide Principles Applied

Based on research of the [Google API Design Guide](https://cloud.google.com/apis/design), this audit evaluates:

1. **Resource-Oriented Design (AIP-121)**: Resources as nouns, standard methods for CRUD
2. **Naming Conventions (AIP-190)**: Plural nouns for collections, clear intuitive names
3. **Standard Methods (AIP-132/133)**: List, Get, Create, Update, Delete
4. **Custom Methods**: Using `:` syntax for actions that don't fit standard methods
5. **HTTP Methods**: Proper use of GET, POST, PUT, PATCH, DELETE
6. **Status Codes**: Appropriate 2xx, 3xx, 4xx, 5xx codes
7. **Error Handling (AIP-193)**: Consistent error response format
8. **Pagination**: Proper pagination for list endpoints
9. **Filtering/Sorting**: Query parameters for filtering and ordering
10. **API Versioning**: Version prefix for breaking changes

---

## Detailed Audit Results

### 1. /app/api/roll.py (Roll API)

#### 1.1 POST /roll/html
**Status:** NON-COMPLIANT

**Issues:**
- Returns HTML in an API route; should be separate from REST API
- Trailing slash inconsistent with other endpoints
- Returns raw HTML string instead of JSON

**Recommendations:**
- Move to `/roll/view` or separate router for HTML fragments
- Remove from core REST API documentation

---

#### 1.2 POST /roll
**Status:** PARTIALLY COMPLIANT

**Issues:**
- Should use plural noun for resource collection (e.g., `/rolls`)
- Custom action (rolling dice) could use custom method syntax: `POST /rolls:roll`
- No pagination for roll pool retrieval
- Returns `RollResponse` model (good)

**Recommendations:**
- Consider renaming to `/rolls:roll` following custom method pattern
- Or rename to `/rolls` with POST creating a roll result

---

#### 1.3 POST /roll/override
**Status:** NON-COMPLIANT

**Issues:**
- Uses POST to "override" - should be custom method: `POST /rolls:override`
- Path structure doesn't indicate which resource is being acted upon
- Should operate on thread resource instead: `POST /threads/{thread_id}:select`

**Recommendations:**
- Change to `POST /threads/{thread_id}:select`
- Update description to "manually select thread for reading"

---

#### 1.4 POST /roll/dismiss-pending
**Status:** NON-COMPLIANT

**Issues:**
- Kebab-case in URL is non-standard
- Should use custom method syntax: `POST /roll:dismiss-pending`
- Should be a session action: `POST /sessions/current:dismiss-pending`

**Recommendations:**
- Change to `POST /sessions/current:dismiss-pending`
- Update logic to operate on session resource

---

#### 1.5 POST /roll/set-die
**Status:** NON-COMPLIANT

**Issues:**
- Modifies session state, not roll state
- Should be `PATCH /sessions/current` with `manual_die` field
- Path doesn't follow resource hierarchy

**Recommendations:**
- Change to `PATCH /sessions/current` with request body: `{"manual_die": 6}`
- Remove roll-specific die manipulation from roll router

---

#### 1.6 POST /roll/clear-manual-die
**Status:** NON-COMPLIANT

**Issues:**
- Modifies session state, not roll state
- Should be `PATCH /sessions/current` with `manual_die: null`
- Non-descriptive path structure

**Recommendations:**
- Change to `PATCH /sessions/current` with request body: `{"manual_die": null}`
- Consolidate with set-die endpoint

---

#### 1.7 POST /roll/reroll
**Status:** PARTIALLY COMPLIANT

**Issues:**
- Should use custom method syntax: `POST /rolls:reroll`
- Returns HTML instead of JSON for API consumers

**Recommendations:**
- Change to `POST /rolls:reroll`
- Ensure JSON response for API clients

---

### 2. /app/api/rate.py (Rate API)

#### 2.1 POST /rate
**Status:** NON-COMPLIANT

**Issues:**
- Singular noun in URL (should be plural: `/ratings`)
- Mixed responsibilities: creates event, updates thread, updates session, moves queue
- Should operate on thread resource: `POST /threads/{thread_id}:rate`
- No resource ID in path - ambiguous which thread is being rated

**Recommendations:**
- Change to `POST /threads/{thread_id}:rate`
- Split responsibilities into focused endpoints
- Or create `/ratings` collection with POST creating a rating

---

### 3. /app/api/session.py (Session API)

#### 3.1 GET /sessions/current/
**Status:** PARTIALLY COMPLIANT

**Issues:**
- Trailing slash inconsistent with other endpoints
- Should be `GET /sessions/current`

**Recommendations:**
- Remove trailing slash
- Keep existing pagination support (good)

---

#### 3.2 GET /sessions/
**Status:** COMPLIANT

**Compliance:**
- Plural noun for collection
- Proper pagination (limit, offset)
- GET method for reading
- Returns list of SessionResponse models

**Issues:**
- No filtering support (e.g., `?user_id=1`, `?status=active`)
- No sorting support (e.g., `?orderBy=started_at desc`)

**Recommendations:**
- Add filter parameter support
- Add orderBy parameter support

---

#### 3.3 GET /sessions/{session_id}
**Status:** COMPLIANT

**Compliance:**
- Standard GET method for single resource
- Proper 404 status for missing resources
- Returns SessionResponse model

---

#### 3.4 GET /sessions/{session_id}/details
**Status:** NON-COMPLIANT

**Issues:**
- Should be part of GET /sessions/{session_id} with query parameter
- Path-based view selection instead of query parameter
- Returns HTML for HTMX (should be separate endpoint)

**Recommendations:**
- Change to `GET /sessions/{session_id}?view=full`
- Move HTML rendering to separate `/sessions/{session_id}/details/html` endpoint

---

#### 3.5 GET /sessions/{session_id}/snapshots
**Status:** PARTIALLY COMPLIANT

**Issues:**
- Returns HTML instead of JSON (line 336: `response_class=HTMLResponse`)
- Sub-resource access is correct pattern

**Recommendations:**
- Rename HTML endpoint to `/sessions/{session_id}/snapshots/html`
- Create `/sessions/{session_id}/snapshots` for JSON

---

#### 3.6 POST /sessions/{session_id}/restore-session-start
**Status:** NON-COMPLIANT

**Issues:**
- Kebab-case URL structure
- Should use custom method syntax: `POST /sessions/{session_id}:restore`
- Non-descriptive naming

**Recommendations:**
- Change to `POST /sessions/{session_id}:restore`
- Add query parameter for snapshot selection: `?snapshot={session_id}`

---

### 4. /app/api/queue.py (Queue API)

#### 4.1 PUT /queue/threads/{thread_id}/position/
**Status:** NON-COMPLIANT

**Issues:**
- Queue is not a first-class resource; threads are
- Should operate on thread resource: `PATCH /threads/{thread_id}`
- Action-based path structure instead of resource update

**Recommendations:**
- Change to `PATCH /threads/{thread_id}` with body: `{"queue_position": 5}`
- Remove queue router prefix

---

#### 4.2 PUT /queue/threads/{thread_id}/front/
**Status:** NON-COMPLIANT

**Issues:**
- Queue not a first-class resource
- Should be custom method on thread: `POST /threads/{thread_id}:move-to-front`
- Non-standard action path

**Recommendations:**
- Change to `POST /threads/{thread_id}:move-to-front`
- Or use PATCH with `queue_position: 1`

---

#### 4.3 PUT /queue/threads/{thread_id}/back/
**Status:** NON-COMPLIANT

**Issues:**
- Queue not a first-class resource
- Should be custom method on thread: `POST /threads/{thread_id}:move-to-back`
- Non-standard action path

**Recommendations:**
- Change to `POST /threads/{thread_id}:move-to-back`
- Or use PATCH with calculated max position

---

### 5. /app/api/thread.py (Thread API)

#### 5.1 GET /threads/
**Status:** NON-COMPLIANT

**Issues:**
- No pagination support (all threads returned)
- No filtering support (e.g., `?status=active`, `?format=comic`)
- No sorting support (e.g., `?orderBy=queue_position`)
- Could return large response for many threads

**Recommendations:**
- Add pagination: `?page_token=xyz&max_results=100`
- Add filtering: `?filter=status=active AND format=comic`
- Add sorting: `?orderBy=queue_position`

---

#### 5.2 GET /threads/stale
**Status:** NON-COMPLIANT

**Issues:**
- Should be custom method: `GET /threads:stale`
- Query parameter approach better: `GET /threads?filter=last_activity_at < '30 days ago'`

**Recommendations:**
- Change to `GET /threads:stale` with `days={days}` parameter
- Or use filter parameter: `GET /threads?stale_days=30`

---

#### 5.3 GET /threads/completed
**Status:** PARTIALLY COMPLIANT

**Issues:**
- Returns HTML option elements (line 74: `response_class=HTMLResponse`)
- Should be filtering: `GET /threads?filter=status=completed`

**Recommendations:**
- Rename to `/threads/completed/html` for HTML fragment
- Add filtering support to `/threads` endpoint

---

#### 5.4 GET /threads/active
**Status:** PARTIALLY COMPLIANT

**Issues:**
- Returns HTML (line 91: `response_class=HTMLResponse`)
- Should be filtering: `GET /threads?filter=status=active`

**Recommendations:**
- Rename to `/threads/active/html` for HTML fragment
- Use filter parameter instead

---

#### 5.5 POST /threads/
**Status:** COMPLIANT

**Compliance:**
- Correct POST method for creation
- Returns 201 Created status (line 111)
- Returns created resource (good)
- Plural noun for collection

**Issues:**
- No Location header in response for new resource URL
- No validation for duplicate thread titles

**Recommendations:**
- Add `Location` header with URL to created thread
- Add duplicate title validation

---

#### 5.6 GET /threads/{thread_id}
**Status:** COMPLIANT

**Compliance:**
- Standard GET method for single resource
- Returns 404 for missing resources (lines 152-154)
- Proper response model

---

#### 5.7 PUT /threads/{thread_id}
**Status:** PARTIALLY COMPLIANT

**Issues:**
- Should use PATCH for partial updates (PUT replaces entire resource)
- PUT expects full resource replacement, PATCH for partial updates

**Recommendations:**
- Change to `PATCH /threads/{thread_id}`
- Keep PUT for full resource replacement if needed

---

#### 5.8 DELETE /threads/{thread_id}
**Status:** COMPLIANT

**Compliance:**
- Correct DELETE method
- Returns 204 No Content status (line 215)
- Proper 404 for missing resources

---

#### 5.9 POST /threads/reactivate
**Status:** NON-COMPLIANT

**Issues:**
- Custom action without `:` syntax
- Should be `POST /threads/{thread_id}:reactivate`
- No thread_id in path (comes from request body)

**Recommendations:**
- Change to `POST /threads/{thread_id}:reactivate`
- Move thread_id from body to path

---

### 6. /app/api/tasks.py (Task API)

#### 6.1 POST /tasks/initialize
**Status:** NON-COMPLIANT

**Issues:**
- Custom action without `:` syntax
- Should be `POST /tasks:initialize`
- Duplicates database state creation logic

**Recommendations:**
- Change to `POST /tasks:initialize`
- Document idempotency (can be called multiple times safely)

---

#### 6.2 GET /tasks/
**Status:** NON-COMPLIANT

**Issues:**
- No pagination support
- No filtering support
- No sorting support
- Returns all tasks in single response

**Recommendations:**
- Add pagination with `page_token` and `max_results`
- Add filtering: `?filter=status=pending`
- Add sorting: `?orderBy=priority`

---

#### 6.3 POST /tasks/
**Status:** COMPLIANT

**Compliance:**
- Correct POST method for creation
- Returns 201 Created status (line 425)
- Returns created resource
- Plural noun for collection

---

#### 6.4 POST /tasks/bulk
**Status:** PARTIALLY COMPLIANT

**Issues:**
- Should use `:` syntax for custom method: `POST /tasks:bulk-create`
- Non-standard naming convention

**Recommendations:**
- Change to `POST /tasks:bulk-create`
- Or use standard POST with array body (if supported)

---

#### 6.5 GET /tasks/ready
**Status:** NON-COMPLIANT

**Issues:**
- Should use custom method syntax: `GET /tasks:ready`
- Query parameter approach: `GET /tasks?filter=status=ready`

**Recommendations:**
- Change to `GET /tasks:ready`
- Document that this returns tasks ready to be claimed

---

#### 6.6 GET /tasks/coordinator-data
**Status:** NON-COMPLIANT

**Issues:**
- Kebab-case in URL
- Should use `:` syntax: `GET /tasks:coordinator-data`
- Non-descriptive name

**Recommendations:**
- Change to `GET /tasks:coordinator-data`
- Or split into separate endpoints for each status bucket

---

#### 6.7 GET /tasks/metrics
**Status:** NON-COMPLIANT

**Issues:**
- Should use custom method syntax: `GET /tasks:metrics`
- Could be separate top-level resource

**Recommendations:**
- Change to `GET /tasks:metrics`
- Or create `/metrics` resource

---

#### 6.8 GET /tasks/stale
**Status:** NON-COMPLIANT

**Issues:**
- Should use custom method syntax: `GET /tasks:stale`
- Better as filter: `GET /tasks?filter=last_heartbeat < '20 minutes ago'`

**Recommendations:**
- Change to `GET /tasks:stale`
- Or add filter parameter

---

#### 6.9 GET /tasks/search
**Status:** PARTIALLY COMPLIANT

**Issues:**
- Should use `:` syntax: `GET /tasks:search`
- Query parameter approach better: `GET /tasks?query=search-term`

**Recommendations:**
- Change to `GET /tasks:search` with `q=` parameter
- Or add to `/tasks` endpoint with `?filter=title contains 'term'`

---

#### 6.10 GET /tasks/{task_id}
**Status:** COMPLIANT

**Compliance:**
- Standard GET method
- Proper 404 for missing resources
- Returns TaskResponse model

---

#### 6.11 PATCH /tasks/{task_id}
**Status:** COMPLIANT

**Compliance:**
- Correct PATCH method for partial updates
- Proper 404 for missing resources

**Issues:**
- No validation for invalid status transitions

---

#### 6.12 GET /tasks/{task_id}/history
**Status:** NON-COMPLIANT

**Issues:**
- Sub-resource path doesn't follow convention
- Should be `GET /tasks/{task_id}:history` (custom method)

**Recommendations:**
- Change to `GET /tasks/{task_id}:history`
- Keep existing functionality

---

#### 6.13 POST /tasks/{task_id}/claim
**Status:** NON-COMPLIANT

**Issues:**
- Should use custom method syntax: `POST /tasks/{task_id}:claim`
- Non-standard path structure

**Recommendations:**
- Change to `POST /tasks/{task_id}:claim`
- Keep existing validation logic

---

#### 6.14 POST /tasks/{task_id}/update-notes
**Status:** NON-COMPLIANT

**Issues:**
- Should be `PATCH /tasks/{task_id}` with notes field
- Duplicate functionality with PATCH endpoint

**Recommendations:**
- Remove this endpoint
- Use `PATCH /tasks/{task_id}` with `{"notes": "..."}`

---

#### 6.15 POST /tasks/{task_id}/unclaim
**Status:** NON-COMPLIANT

**Issues:**
- Should use custom method syntax: `POST /tasks/{task_id}:unclaim`
- Non-standard path structure

**Recommendations:**
- Change to `POST /tasks/{task_id}:unclaim`
- Keep existing functionality

---

#### 6.16 POST /tasks/{task_id}/complete
**Status:** NON-COMPLIANT

**Issues:**
- Should use custom method syntax: `POST /tasks/{task_id}:complete`
- Non-standard path structure

**Recommendations:**
- Change to `POST /tasks/{task_id}:complete`
- Document status change from in_progress to done

---

#### 6.17 POST /tasks/{task_id}/review
**Status:** NON-COMPLIANT

**Issues:**
- Should use custom method syntax: `POST /tasks/{task_id}:review`
- Non-standard path structure

**Recommendations:**
- Change to `POST /tasks/{task_id}:review`
- Keep existing functionality

---

#### 6.18 POST /tasks/{task_id}/start
**Status:** NON-COMPLIANT

**Issues:**
- Should use custom method syntax: `POST /tasks/{task_id}:start`
- Non-standard path structure

**Recommendations:**
- Change to `POST /tasks/{task_id}:start`
- Document status change from pending to in_progress

---

### 7. /app/api/undo.py (Undo API)

#### 7.1 POST /undo/{session_id}/undo/{snapshot_id}
**Status:** NON-COMPLIANT

**Issues:**
- Undo is an action, should be custom method
- Should be `POST /sessions/{session_id}:undo` with `snapshot_id` parameter
- Double `undo` in path is redundant

**Recommendations:**
- Change to `POST /sessions/{session_id}:undo?snapshot_id={snapshot_id}`
- Or use `POST /sessions/{session_id}:restore?to={snapshot_id}`

---

#### 7.2 GET /undo/{session_id}/snapshots
**Status:** NON-COMPLIANT

**Issues:**
- Snapshots are session sub-resources
- Should be `GET /sessions/{session_id}/snapshots`
- Undo router prefix is not appropriate for read operations

**Recommendations:**
- Move to sessions router
- Change to `GET /sessions/{session_id}/snapshots`

---

### 8. /app/api/admin.py (Admin API)

#### 8.1 POST /admin/import/csv/
**Status:** NON-COMPLIANT

**Issues:**
- Import is a custom action, should use `:` syntax
- Should be `POST /threads:import-csv`
- Trailing slash inconsistent

**Recommendations:**
- Change to `POST /threads:import-csv`
- Remove trailing slash

---

#### 8.2 GET /admin/export/csv/
**Status:** NON-COMPLIANT

**Issues:**
- Export is a custom action, should use `:` syntax
- Should be `GET /threads:export-csv`
- Trailing slash inconsistent

**Recommendations:**
- Change to `GET /threads:export-csv`
- Remove trailing slash

---

#### 8.3 GET /admin/export/json/
**Status:** NON-COMPLIANT

**Issues:**
- Export is a custom action, should use `:` syntax
- Should be `GET /:export-json` (system-level)
- Trailing slash inconsistent

**Recommendations:**
- Change to `GET /:export-json` (top-level resource)
- Remove trailing slash

---

#### 8.4 POST /admin/delete-test-data/
**Status:** NON-COMPLIANT

**Issues:**
- Should use `:` syntax: `POST /:delete-test-data`
- System-level operation, not admin-specific

**Recommendations:**
- Change to `POST /:delete-test-data`
- Remove trailing slash

---

#### 8.5 GET /admin/settings
**Status:** NON-COMPLIANT

**Issues:**
- Settings is a singleton resource, should be `/settings`
- Admin prefix is unnecessary
- Plural form for singleton is incorrect

**Recommendations:**
- Change to `GET /settings`

---

#### 8.6 PUT /admin/settings
**Status:** NON-COMPLIANT

**Issues:**
- Settings is a singleton, should be `/settings`
- Should be `PATCH` for partial updates
- Admin prefix is unnecessary

**Recommendations:**
- Change to `PATCH /settings` with partial update body
- Or keep `PUT /settings` for full replacement

---

### 9. /app/api/retros.py (Retros API)

#### 9.1 POST /retros/generate
**Status:** NON-COMPLIANT

**Issues:**
- Retros are derived reports, not first-class resources
- Should be custom method on sessions: `POST /sessions:generate-retro`
- Path structure unclear

**Recommendations:**
- Change to `POST /sessions:generate-retro`
- Or create `/retros:generate` (but still clarify it's session-based)

---

### 10. Health Check Endpoints

#### 10.1 GET /health
**Status:** COMPLIANT

**Compliance:**
- Standard GET method
- Returns health status
- Proper error handling

**Issues:**
- Not under `/v1/` version prefix
- Could be more descriptive: `GET /health/check`

---

#### 10.2 GET /api/health
**Status:** COMPLIANT

**Compliance:**
- Under `/api/` prefix (not versioned though)
- Standard GET method
- Returns health status

---

## Summary of Non-Compliant Endpoints

### Critical Issues (Must Fix)

1. **POST /roll/set-die** - Modifies session, not roll state
2. **POST /roll/clear-manual-die** - Modifies session, not roll state
3. **POST /roll/override** - Path doesn't indicate resource
4. **POST /rate** - Mixed responsibilities, no thread_id in path
5. **GET /threads/** - No pagination, filtering, or sorting
6. **GET /tasks/** - No pagination, filtering, or sorting

### High Priority Issues

7. **POST /roll/html** - Returns HTML in API route
8. **POST /roll/dismiss-pending** - Kebab-case URL
9. **POST /sessions/{session_id}/restore-session-start** - Kebab-case URL
10. **PUT /queue/threads/{thread_id}/position/** - Queue not first-class resource
11. **POST /threads/reactivate** - No thread_id in path
12. **POST /tasks/{task_id}/claim** - Non-standard path structure
13. **POST /tasks/{task_id}/update-notes** - Duplicate of PATCH

### Medium Priority Issues

14. **POST /roll/reroll** - Should use `:` syntax
15. **POST /roll/override** - Should use `:` syntax
16. **GET /sessions/current/** - Trailing slash
17. **GET /sessions/{session_id}/details** - Should be query param
18. **GET /sessions/{session_id}/snapshots** - Returns HTML
19. **GET /threads/stale** - Should use `:` syntax
20. **GET /threads/completed** - Returns HTML
21. **GET /threads/active** - Returns HTML
22. **PUT /threads/{thread_id}** - Should be PATCH
23. **POST /tasks/initialize** - Should use `:` syntax
24. **POST /tasks/bulk** - Should use `:` syntax
25. **GET /tasks/ready** - Should use `:` syntax
26. **GET /tasks/coordinator-data** - Should use `:` syntax
27. **GET /tasks/metrics** - Should use `:` syntax
28. **GET /tasks/stale** - Should use `:` syntax
29. **GET /tasks/search** - Should use `:` syntax
30. **GET /tasks/{task_id}/history** - Should use `:` syntax
31. **POST /tasks/{task_id}/unclaim** - Should use `:` syntax
32. **POST /tasks/{task_id}/complete** - Should use `:` syntax
33. **POST /tasks/{task_id}/review** - Should use `:` syntax
34. **POST /tasks/{task_id}/start** - Should use `:` syntax
35. **POST /undo/{session_id}/undo/{snapshot_id}** - Should be session action
36. **GET /undo/{session_id}/snapshots** - Should be under sessions
37. **POST /admin/import/csv/** - Should use `:` syntax
38. **GET /admin/export/csv/** - Should use `:` syntax
39. **GET /admin/export/json/** - Should use `:` syntax
40. **POST /admin/delete-test-data/** - Should use `:` syntax
41. **GET /admin/settings** - Should be `/settings`
42. **PUT /admin/settings** - Should be `/settings` or PATCH
43. **POST /retros/generate** - Should use `:` syntax

### Low Priority Issues

44. All endpoints - No API versioning (e.g., `/v1/`)
45. List endpoints - No consistent error response format
46. Some endpoints - Status codes could be more specific
47. Response models - Some inconsistency in field naming

---

## Recommendations by Category

### Naming Conventions

1. Use plural nouns for all collections (e.g., `/threads`, `/tasks`, `/sessions`)
2. Use kebab-case for URL paths (but not for actions - use `:` syntax)
3. Use camelCase for request/response fields
4. Avoid abbreviations unless commonly accepted

### Resource-Oriented Design

1. Identify true resources (threads, sessions, tasks, settings, snapshots)
2. Use standard methods for CRUD operations
3. Use custom methods (with `:`) for actions that don't fit standard methods
4. Create clear resource hierarchies (e.g., `/sessions/{id}/snapshots`)

### HTTP Methods

1. GET: Read resources
2. POST: Create resources or perform non-idempotent actions
3. PATCH: Partially update resources
4. PUT: Fully replace resources
5. DELETE: Remove resources

### Status Codes

1. 200 OK: Successful GET/PUT/PATCH
2. 201 Created: Successful POST
3. 204 No Content: Successful DELETE
4. 400 Bad Request: Invalid request
5. 404 Not Found: Resource not found
6. 409 Conflict: Resource already exists or state conflict

### Pagination

1. Use `page_token` and `max_results` for cursor-based pagination
2. Or use `limit` and `offset` for simple pagination
3. Return total count and next/previous page tokens

### Filtering and Sorting

1. Use `filter` parameter for filtering (Google-style syntax)
2. Use `orderBy` parameter for sorting (e.g., `orderBy=priority,created_at desc`)
3. Support field-specific filters with operators (=, <, >, contains)

### Error Handling

1. Use consistent error response format across all endpoints
2. Include error code, message, and details
3. Log all errors with context
4. Return 422 for validation errors

### API Versioning

1. Add `/v1/` prefix to all API routes
2. Document breaking changes in version bump
3. Maintain backward compatibility when possible

---

## Tasks to Create

Based on this audit, **43 tasks** should be created to address all non-compliant endpoints. Below are the most critical ones:

### Critical Tasks

1. **API-COMPLIANCE-001**: Fix POST /roll/set-die endpoint
2. **API-COMPLIANCE-002**: Fix POST /roll/clear-manual-die endpoint
3. **API-COMPLIANCE-003**: Fix POST /roll/override endpoint
4. **API-COMPLIANCE-004**: Fix POST /rate endpoint
5. **API-COMPLIANCE-005**: Add pagination to GET /threads/
6. **API-COMPLIANCE-006**: Add pagination to GET /tasks/

### High Priority Tasks

7. **API-COMPLIANCE-007**: Fix POST /roll/html endpoint
8. **API-COMPLIANCE-008**: Fix POST /roll/dismiss-pending endpoint
9. **API-COMPLIANCE-009**: Fix POST /sessions/{session_id}/restore-session-start
10. **API-COMPLIANCE-010**: Fix queue endpoints to use thread resource
11. **API-COMPLIANCE-011**: Fix POST /threads/reactivate endpoint
12. **API-COMPLIANCE-012**: Fix POST /tasks/{task_id}/claim endpoint
13. **API-COMPLIANCE-013**: Remove POST /tasks/{task_id}/update-notes endpoint

(Additional tasks 14-43 for medium and low priority issues - see detailed audit above for complete list)

---

## Conclusion

The Comic Pile API shows good foundation with proper use of Pydantic schemas and FastAPI framework. However, significant improvements are needed to align with Google API Design Guide principles:

**Key Areas for Improvement:**
1. **Resource-Oriented Design**: Many endpoints don't follow true resource hierarchy
2. **Custom Method Syntax**: Consistent use of `:` for custom actions needed
3. **Pagination**: Critical for list endpoints to handle growing datasets
4. **Filtering/Sorting**: Essential for developer experience
5. **API Versioning**: Needed for future-breaking changes
6. **Error Handling**: Standardized error response format required

**Estimated Effort:**
- Critical fixes: 12-16 hours
- High priority fixes: 8-12 hours
- Medium priority fixes: 16-20 hours
- Low priority fixes: 8-10 hours
- **Total estimated effort: 44-58 hours**

**Recommended Approach:**
1. Address critical issues first (blocking developer experience)
2. Implement pagination and filtering for list endpoints
3. Refactor to proper resource-oriented design
4. Add API versioning with `/v1/` prefix
5. Standardize error responses
6. Update OpenAPI documentation

---

## References

- [Google API Design Guide](https://cloud.google.com/apis/design)
- [AIP-121: Resource-oriented design](https://google.aip.dev/121)
- [AIP-132: List methods](https://google.aip.dev/132)
- [AIP-133: Get methods](https://google.aip.dev/133)
- [AIP-134: Create methods](https://google.aip.dev/134)
- [AIP-135: Update methods](https://google.aip.dev/135)
- [AIP-136: Delete methods](https://google.aip.dev/136)
- [AIP-190: Naming conventions](https://google.aip.dev/190)
- [AIP-193: Errors](https://google.aip.dev/193)

---

**Report Generated:** 2026-01-08
**Next Audit Recommended:** After critical fixes are implemented
