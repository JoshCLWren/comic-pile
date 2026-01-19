# Users + Auth + Multi-Tenant + React Modernization Plan

Last updated: 2026-01-19

## Goals

- Add real users and authentication so multiple people can use the app concurrently.
- Preserve existing production data currently owned by `user_id=1` by letting the first registration “claim” that user.
- Persist sessions and resume current progress per user (threads, sessions, events, undo/snapshots, settings).
- Reduce product surface area to a single, well-tested UI (React SPA), and quarantine or remove legacy HTML/HTMX endpoints.
- Improve security posture (CORS, logging redaction, disable dangerous endpoints by default) without boiling the ocean.

## Explicit Decisions

- Auth mechanism: JWT bearer tokens.
- Identity: email + password.
- Token lifetime: 30 days for access tokens.
- App access model: require login for all product pages; only `/health` remains unauthenticated.
- Migration strategy: keep existing data attached to `users.id == 1` by claiming that row on first registration.
- Deployment environment: Railway.

## Non-Goals (for this phase)

- Full OAuth / SSO.
- Multi-tenant “organizations”; tenancy is per-user ownership.
- A complete rewrite of the Task API / manager-worker system (we will quarantine it).
- Perfect frontend redesign; modernization is primarily about correctness, single UI surface, and testability.

## Current State Summary (Why This Work Is Non-Trivial)

The codebase has partial multi-user structure (many tables include `user_id`) but the runtime behavior is still effectively single-user:

- Hardcoded `user_id=1` in multiple endpoints.
- Many DB queries are global (no `where(Model.user_id == ...)`).
- Queue reorder helpers (`comic_pile/queue.py`) update positions across all threads.
- Session selection (`comic_pile/session.py#get_or_create`) can select an active session without scoping by user.
- Snapshots/undo/restore logic can read/mutate all threads.

Additionally, the UI surface is mixed:

- React SPA is served at `/`.
- Several API routes return HTML (legacy/experimental HTMX/inline JS).

## Security/Operations Constraints

- No credential/token leakage in logs or GitHub issue reports.
- Production must not expose dangerous internal endpoints (admin export/import, task subprocess execution, debug triggers).
- Production schema changes must be Alembic-driven (avoid `create_all()` drift).

## Environment and Config

### Railway domain

- Railway public domain (current): `https://app-production-72b9.up.railway.app`
- If a custom domain is added later, it must be included in `CORS_ORIGINS`.

### Proposed new/updated env vars

- `JWT_SECRET` (required in production)
- `JWT_EXPIRES_DAYS` (default `30`)
- `CORS_ORIGINS` (required in production; comma-separated)
- `ENVIRONMENT` (`development`/`production`)
- `ENABLE_DEBUG_ROUTES` (default false in production)
- `ENABLE_INTERNAL_OPS_ROUTES` (default false in production)

## Testing Strategy (Guardrails)

We treat tests as the primary mechanism to modernize without breaking features.

### Layers

- **Backend API regression tests (pytest + httpx.AsyncClient)**
  - Lock in core business behavior (roll/rate/queue/session/undo) before refactors.
  - Add auth tests and multi-user isolation tests as features land.

- **Browser E2E smoke tests (Playwright)**
  - Validate the “real user” workflow from the UI.
  - Keep these few, stable, and fast.

### Minimum critical flows to cover

- Roll -> Rate -> returns to Roll (and session persists across reload).
- Queue reorder operations.
- Sessions/history loads.
- Undo/restore works and is user-scoped.
- Login/logout gating.

### Go/No-Go definition

We do not enable “auth required” for all endpoints until:

- Core regression tests pass.
- Login flow + 1-2 happy-path Playwright flows pass.
- Multi-user isolation tests prove no cross-user access/mutation.

## Pre-Work (Must-Do Before Auth Enforcement)

These are “blockers” because they can cause security incidents or production drift.

1) Quarantine dangerous endpoints

- `app/api/tasks.py` (subprocess execution, worktree management)
- `app/api/admin.py` (export/import/delete)
- `app/main.py` debug endpoints

Plan:

- Add environment gating (disabled by default in production).
- Add admin-only authz for any remaining “ops” endpoints.

2) Disable schema auto-creation in production

- `app/main.py` calls `Base.metadata.create_all(bind=engine)`.

Plan:

- Production startup should only check DB connectivity.
- Alembic migrations become the authoritative path for schema changes.

3) Logging redaction

- `app/api/error_handler.py` captures full request headers in GitHub issue creation.
- `app/main.py` request body logging redacts only a small set of keys.

Plan:

- Redact `Authorization`, `Cookie`, `Set-Cookie`.
- Redact common sensitive keys: `password`, `secret`, `token`, `access_token`, `refresh_token`, `api_key`.
- Prefer logging body size/type rather than body content for auth-related routes.

4) CORS tightening

- `app/main.py` defaults to wildcard origins.

Plan:

- Require `CORS_ORIGINS` in production.
- For JWT bearer headers, set `allow_credentials=False`.

## Implementation Phases (With Dependencies and Parallelism)

This section describes what can be done in parallel and what depends on what. “Parallel” means independent workstreams that can be developed concurrently, then merged in a safe order.

### Current Phase Status Summary (Last Updated: 2026-01-19)

| Phase | Name | Status | Next Action |
|-------|------|--------|-------------|
| Phase 1 | Inventory + Baseline Tests | ✅ COMPLETE | Move to Phase 2 |
| Phase 2 | Security and Ops Hardening | ✅ COMPLETE | Move to Phase 3 |
| Phase 3 | Database Migrations for Auth | ✅ COMPLETE | Move to Phase 4 |
| Phase 4 | Auth Backend (JWT + Email/Pass) | ✅ COMPLETE | Ready for Phase 5 merge |
| Phase 5 | Frontend Auth + Gating | ⏸️ NOT MERGED | Awaiting PR merge to auth-refactor-feature-branch |
| Phase 6 | Tenant Isolation | ⏸️ NOT STARTED | Depends on Phase 4 |
| Phase 7 | React-Only Modernization | ⏸️ NOT STARTED | Depends on Phase 1 + Phase 5 |
| Phase 8 | Rollout Checklist | ⏸️ NOT STARTED | Depends on all previous phases |

**Current Branch:** `auth-refactor-feature-branch`
**Recent Merge:** `phase/3-auth-db-migrations` (Jan 19, 2026)
**Next Recommended Phase:** Phase 4 - Auth Backend

**Phase 2 Completion Details:**
- Branch: `phase/2-security-hardening`
- Commits: 9 (security hardening, fixes, CI improvements, git hooks)
- Tests: 365 passing, 97.70% coverage
- CI: Configured with lint and test jobs (runs on PR)
- Git Hooks: Pre-commit (linting) and pre-push (tests with coverage)
- Deferred Issues: 14 documented in `docs/PHASE_2_DEFERRED_ISSUES.md`

### Phase 1: Inventory + Baseline Tests

Purpose: get a complete surface map and establish regression protection.

- Inventory (deterministic from repo)
  - React routes: `frontend/src/App.jsx`
  - API routers: `app/main.py` + `app/api/*.py`
  - Client API calls: `frontend/src/services/api.js`
  [STATUS: COMPLETE - Inventory items identified]

- Tests
  - Add/expand pytest coverage for current roll/rate/queue/session/undo behavior.
    [STATUS: COMPLETE]
    - Backend tests: 28 test files including test_roll_api.py, test_rate_api.py, test_queue_api.py, test_session.py (includes undo tests)
    - Coverage: Tests exist for roll, rate, queue, session, undo, error handlers
  - Add minimal Playwright smoke for the primary workflow.
    [STATUS: COMPLETE]
    - E2E tests: tests_e2e/test_browser_ui.py exists
    - Tests cover: root URL rendering, roll navigation, rating UI, queue management UI
    - Test count: Multiple integration tests marked with @pytest.mark.integration

Dependencies:

- None.

Parallelizable:

- Backend tests and Playwright tests can be developed concurrently.

Go/No-Go gate:

- Baseline tests pass on current main branch.
  [STATUS: PASSED - Tests exist and run on auth-refactor-feature-branch]
  - 28 test files with extensive API coverage
  - Playwright integration tests for primary workflows
  - Tests can be run with: `pytest` or `make pytest`

### Phase 2: Security and Ops Hardening (Pre-Auth)

Purpose: avoid leaking credentials/tokens and avoid accidentally exposing internal power tools.

Work items:

- Gate internal endpoints (tasks/admin/debug) by env flag and admin auth.
  [STATUS: ✅ COMPLETE]
  - Created `app/dependencies.py` with `require_debug_routes()` and `require_internal_ops_routes()`
  - Applied gating to `/api/tasks/*` routes (router level)
  - Applied gating to `/api/admin/*` routes (router level)
  - Applied gating to `/debug/*` routes (route level)
  - Debug routes were removed; SPA handler now blocks `/debug/*` paths permanently
  - Required env vars: `ENABLE_DEBUG_ROUTES` (default false), `ENABLE_INTERNAL_OPS_ROUTES` (default false)

- Implement logging redaction for headers and sensitive JSON keys.
  [STATUS: ✅ COMPLETE]
  - Added `redact_headers()` function for Authorization, Cookie, Set-Cookie headers
  - Added `contains_sensitive_keys()` for password, secret, token, access_token, refresh_token, api_key
  - Added `is_auth_route()` to detect auth routes
  - Created `_safe_get_request_body()` helper to avoid 75 lines of duplication
  - Applied redaction in log_errors_middleware, global_exception_handler, http_exception_handler

- Tighten CORS config behavior for production.
  [STATUS: ✅ COMPLETE]
  - ENVIRONMENT check requires `CORS_ORIGINS` in production (raises RuntimeError if missing)
  - Set `allow_credentials=False` for JWT bearer headers
  - Development mode defaults to wildcard "*"

- Remove/disable `create_all()` in production startup path.
  [STATUS: ✅ COMPLETE]
  - Conditional logic in `startup_event()` skips `create_all()` in production mode
  - Production mode logs "Production mode: Skipping table creation (migrations required)"
  - Development mode calls `create_all()` and logs "Database tables created successfully"

Dependencies:

- Phase 1 recommended (so tests exist), but can start immediately.

Parallelizable:

- CORS + logging redaction + endpoint gating can be developed independently.

Go/No-Go gate:

- Unauthenticated requests cannot reach `/api/admin/*`, `/api/tasks/*`, `/debug/*` in production mode.
  [STATUS: ✅ MET]
  - All three endpoint groups gated by env flags and return 404 when disabled
  - Tests verify 404 responses when flags are false
  - Tests verify 200 responses when flags are true

- Headers are redacted in error handler output.
  [STATUS: ✅ MET]
  - Authorization, Cookie, Set-Cookie headers redacted
  - Sensitive keys redacted: password, secret, token, access_token, refresh_token, api_key
  - Auth routes log only size/type, not content

- App starts cleanly without relying on `create_all()` (migrations required).
  [STATUS: ✅ MET]
  - Production mode skips `create_all()` and logs appropriate message
  - Development mode calls `create_all()` and logs success message

- App starts cleanly without relying on wildcard CORS origins in production mode.
  [STATUS: ✅ MET]
  - Production mode requires `CORS_ORIGINS` to be set (raises RuntimeError if missing)
  - Development mode defaults to wildcard "*"

### Phase 3: Database Migrations for Auth

Purpose: introduce the minimum schema needed for email/pass auth and token revocation.

Work items:

- Extend `users`:
  - `email` (unique, nullable initially)
  - `password_hash` (nullable)
  - `is_admin` (default false)

- Add `revoked_tokens` table:
  - `user_id`, `jti` (unique), `revoked_at`, `expires_at`

Dependencies:

- Phase 2 (schema discipline) strongly recommended before shipping migrations.

Parallelizable:

- User table changes and revoked token table changes can be designed together.

Go/No-Go gate:

- Alembic upgrade works on a fresh DB and a prod-like dump.

### Phase 4: Auth Backend (JWT + Email/Pass)

Purpose: create a stable identity boundary for all later multi-tenant fixes.

Work items:

- Auth primitives (stdlib-only): password hashing (PBKDF2), JWT HS256 signing/verifying.
- Endpoints:
  - `POST /api/auth/register`
    - If `users.id=1` exists and has `email IS NULL`, the first register claims it.
  - `POST /api/auth/login`
  - `POST /api/auth/logout` (revokes current token by jti)
  - `GET /api/auth/me`
- `get_current_user` dependency: parses Authorization bearer token, validates, checks revocation table.

Dependencies:

- Phase 3 migrations.

Parallelizable:

- Backend auth endpoints and frontend auth UI can be developed in parallel.

Go/No-Go gate:

- API tests for auth flows pass (register/login/me/logout, revoked token rejected).

### Phase 5: Frontend Auth + Gating

Purpose: ensure the user experience matches “gate all pages” while preserving core flows.

Work items:

- Add login/register screens.
- Store JWT token (localStorage or another chosen store).
- Add axios interceptor to attach `Authorization: Bearer <token>`.
- Route guard: unauthenticated users cannot access product routes.

Dependencies:

- Phase 4 backend auth endpoints.

Parallelizable:

- Can be built alongside Phase 4.

Go/No-Go gate:

- Playwright flow: login -> roll -> rate works.

### Phase 6: Tenant Isolation (Core Correctness)

Purpose: enforce that all state is per-user and no cross-user mutation is possible.

Work items (ordered by risk/impact):

1) Session scoping

- Fix `comic_pile/session.py#get_or_create` to filter by `Session.user_id`.
- Fix “current session” queries in session endpoints.

2) Thread CRUD scoping

- Every thread query/update must include `Thread.user_id == current_user.id`.

3) Queue scoping

- `comic_pile/queue.py` updates must be scoped by user.
- Roll pool selection must be per-user.

4) Snapshot/undo/restore scoping

- Snapshot only current user’s threads.
- Undo/restore must never delete or mutate other user’s records.

Dependencies:

- Phase 4 (need current_user).

Parallelizable:

- Different modules can be refactored in parallel, but merges should follow the order above.

Go/No-Go gate:

- Two-user tests prove:
  - user A cannot view/mutate user B threads/sessions/events/snapshots.
  - undo/restore cannot delete user B threads.

### Phase 7: React-Only Modernization / Legacy Endpoint Quarantine

Purpose: reduce auth surface area and remove duplicate UI systems.

Work items:

- Inventory all non-JSON endpoints under `/api/*` that return HTML.
- Decide per endpoint: redirect to SPA route, return 404/410, or keep but fully protected.
- Remove broken HTMX template branches or restore the missing templates (short-term only).

Dependencies:

- Phase 1 tests, plus Phase 5 UI gating.

Parallelizable:

- Endpoint cleanup and frontend completion can be worked on concurrently.

Go/No-Go gate:

- No HTML endpoints are reachable unauthenticated in production mode.
- SPA routes work on refresh/direct navigation.

### Phase 8: Rollout Checklist

Purpose: ship safely to production.

- Set Railway env:
  - `JWT_SECRET`
  - `CORS_ORIGINS=https://app-production-72b9.up.railway.app`
  - `ENABLE_INTERNAL_OPS_ROUTES=false`
  - `ENABLE_DEBUG_ROUTES=false`
- Apply Alembic migrations.
- Deploy backend + frontend.
- First registration claims `users.id=1`.
- Verify:
  - Existing threads show up for your account.
  - Existing session resume behavior still works.
  - New users see isolated data.

## Parallel Workstreams (Recommended Implementation Approach)

- Workstream A: Tests
  - Phase 1 tests (pytest + Playwright) and keep expanding as invariants are added.

- Workstream B: Security hardening
  - Phase 2 gating + logging redaction + CORS tightening + disable create_all in prod.

- Workstream C: Auth backend
  - Phase 3/4 migrations + auth endpoints + get_current_user.

- Workstream D: Auth frontend
  - Phase 5 login/register + axios auth header + route gating.

- Workstream E: Tenant isolation
  - Phase 6 scoped queries and safe undo/restore.

## Scope Limits (to avoid endless cleanup)

- We will not fully rewrite the task system; we will disable/quarantine it for production.
- We will not restructure the repo or change the build artifact strategy in this phase.
- We will not add OAuth in this phase.

## Appendix: Known Hotspots (Files)

- Startup schema creation + CORS + debug routes: `app/main.py`
- Error/issue handler: `app/api/error_handler.py`
- Queue reorder helpers: `comic_pile/queue.py`
- Session creation/selection: `comic_pile/session.py`
- Undo/restore: `app/api/undo.py`, `app/api/session.py`
- Legacy HTML endpoints: `app/api/rate.py`, `app/api/roll.py`, `app/api/thread.py`, `app/api/tasks.py`
- React routes: `frontend/src/App.jsx`
- Frontend API client: `frontend/src/services/api.js`
