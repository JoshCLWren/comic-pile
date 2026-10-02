# Reading Session Naming Convention

This document explains the domain naming convention for ComicPile's durable reading-history records
and records which ambiguous-looking names are intentionally retained.

## Problem

ComicPile historically used the bare name `Session` for the durable reading-history model (table `sessions`). This created a semantic collision with authentication concepts:

- **Reading session**: A durable record of a user's reading activity (started/ended, dice state, threads, snapshots)
- **Auth session**: A user's login state (JWT tokens, refresh tokens, password change revocation)

The collision contributed directly to the password-reset incident fixed in #2996: auth recovery code called `delete_all_sessions_for_user()`, but the helper operated on reading sessions rather than authentication state.

## Solution

**Internal code uses explicit domain names:**

| Concept | Internal Name | Table/Storage |
|---------|---------------|---------------|
| Durable reading history | `ReadingSession` in `app/models/reading_session.py` | `sessions` (unchanged) |
| Reading-history persistence | functions in `app/repositories/reading_session_repository.py` | — |
| Reading-history orchestration | `ReadingSessionService` in `app/services/reading_session_service.py` | — |
| Core reading-session helpers | `comic_pile/reading_session.py` | — |
| API endpoints | `/api/session/` (unchanged) | — |
| API schemas | `SessionListItem`, `SessionDetail` (unchanged) | — |

`app/models/session.py`, `app/repositories/session_repository.py`, `app/services/session_service.py`, and
`comic_pile/session.py` no longer exist. `delete_all_sessions_for_user()` was deleted outright rather than
renamed, because nothing legitimately bulk-deletes a user's reading history.

**Authentication code uses precise names:**

- Access token, refresh token
- Credential epoch (`password_changed_at`)
- Revoked token (`revoked_tokens` table)
- Password reset token (`password_reset_tokens` table)

**No new auth-session persistence model is introduced.** The current password revocation mechanism based on `password_changed_at` remains.

## Migration Strategy

The database table name `sessions` is deliberately unchanged. Renaming the stored table would require:
- A database migration
- API/client coordination
- Potential downtime

This is out of scope for the domain rename. The internal model class is `ReadingSession` with `__tablename__ = "sessions"`, and `User.reading_sessions` is the only relationship that reaches it.

## Enforcement

1. **Architecture guard** (`tests/test_reading_session_naming_guard.py`, static AST analysis, no database):
   - `test_auth_code_does_not_touch_reading_session_domain` — auth and password-reset modules may not
     import the `ReadingSession` model, the reading-session repository/service, or call their helpers.
     A justified cross-domain interaction belongs in a service that owns both sides, never inside an auth
     module; there is no blanket allowlist to widen.
   - `test_reading_session_repository_exposes_no_destructive_helper` — the reading-session repository may
     not expose a public `delete_*` helper or issue a bulk `DELETE` against reading sessions, so
     `delete_all_sessions_for_user()` cannot reappear.
   - `test_reading_session_is_not_exposed_under_a_bare_session_name` — `app/models/session.py` must stay
     deleted, `app.models` must export `ReadingSession` and not `Session`, and `User` must expose
     `reading_sessions` and not `sessions`.

2. **Regression test** (`tests/test_password_reset.py::test_reset_preserves_reading_sessions`): completes a
   real `POST /api/auth/reset-password` for a user with populated reading history and proves every reading
   session, thread, issue, event, and snapshot survives unchanged.

3. **Documentation in code**: key modules state the boundary explicitly:
   - `app/models/reading_session.py`: names the rationale and the auth state that lives elsewhere.
   - `app/repositories/reading_session_repository.py`: "nothing in this module revokes credentials or touches authentication state".
   - `app/services/password_reset_service.py`: "The reading-history table is never touched here; reading sessions survive every password change/reset".
   Two guard assertions keep those statements from drifting away.

4. **Agent guidance**: `AGENTS.md` → "Domain Nouns With Multiple Meanings (House Standard)" makes the
   qualified-name rule mandatory for every agent, so this document is reached without knowing its path.

## Retained Ambiguity Inventory

These names intentionally still read as `session`. They are retained because clients, migrations, or the
HTTP surface depend on them, and none of them is reachable from application code as a bare model name.

| Retained name | Where | Why retained |
|---|---|---|
| `sessions` table | `ReadingSession.__tablename__` | Renaming requires a migration plus API/client coordination |
| `/api/session/...` endpoints | `app/api/session.py`, `app/api/undo.py` | Public HTTP contract |
| `SessionListItem`, `SessionDetail`, `SessionResponse`, `SessionHistoryPage` | `app/schemas/session.py` | Public response schema names |
| `session_id` parameters, fields, and prose | throughout `app/`, `comic_pile/`, `tests/` | Unambiguous in context and pervasive on the wire |
| `comic_pile/reading_session.py` | re-exports in `comic_pile/__init__.py` | Qualified module path is the disambiguation |
| `app/services/session_response.py`, `session_history_projection.py` | service modules | Response/history projections over reading sessions; module name is qualified |
| `X-Session-Read-*` response headers | `app/middleware/security_headers.py` | Diagnostics header contract, unrelated to either session concept |

## Guidelines for Future Work

- **Autocomplete safety**: an auth change should see `reading_session_repository` and
  `ReadingSessionService` at the call site and immediately recognize reading history, not login revocation.
- **Code review**: flag any auth module that imports `ReadingSession` or a reading-session repository/service.
- **New domain concepts**: any new domain noun with more than one plausible meaning (for example "session",
  "thread", "issue", or "snapshot") must use a qualified name at every boundary, not just a docstring.
- **Public API**: external contracts (OpenAPI schemas, endpoint paths) may retain familiar names because
  they are unambiguous to the caller.

## Files Changed in #2998

The domain rename touched ~100 files across:
- `app/models/` — model definition and relationships
- `app/repositories/` — repository module and helpers with explicit `reading_session_` prefixes
- `app/services/` — service module, class, and dependency provider with explicit naming
- `comic_pile/` — core business logic modules
- `tests/` — all test files updated to use `ReadingSession`, plus the guard and reset regression test
- `scripts/` — utility scripts updated
- `docs/` — this document, plus the `AGENTS.md` house-standard rule
