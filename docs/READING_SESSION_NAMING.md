# Reading Session Naming Convention

This document explains the domain naming convention for ComicPile's durable reading-history records.

## Problem

ComicPile historically used the bare name `Session` for the durable reading-history model (table `sessions`). This created a semantic collision with authentication concepts:

- **Reading session**: A durable record of a user's reading activity (started/ended, dice state, threads, snapshots)
- **Auth session**: A user's login state (JWT tokens, refresh tokens, password change revocation)

The collision contributed directly to the password-reset incident fixed in #2996: auth recovery code called `delete_all_sessions_for_user()`, but the helper operated on reading sessions rather than authentication state.

## Solution

**Internal code uses explicit domain names:**

| Concept | Internal Name | Table/Storage |
|---------|---------------|---------------|
| Durable reading history | `ReadingSession` | `sessions` (unchanged) |
| Reading session repository | `ReadingSessionRepository` / `reading_session_repository.py` | — |
| Reading session service | `ReadingSessionService` / `reading_session_service.py` | — |
| API endpoints | `/api/session/` (unchanged) | — |
| API schemas | `SessionListItem`, `SessionDetail` (unchanged) | — |

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

This is out of scope for the domain rename. The internal model class is `ReadingSession` with `__tablename__ = "sessions"`.

## Enforcement

1. **Architecture test** (`tests/test_reading_session_naming_guard.py`): Prevents auth/password-reset code from importing reading-session repositories, services, or the model directly.

2. **Regression test** (`tests/test_password_reset.py::test_reset_preserves_reading_sessions`): Verifies that password reset preserves all populated reading history.

3. **Documentation in code**: Key modules include explicit boundary comments:
   - `app/models/reading_session.py`: Documents the naming rationale
   - `app/repositories/reading_session_repository.py`: States "nothing in this module revokes credentials or touches authentication state"
   - `app/services/password_reset_service.py`: States "The reading-history table is never touched here; reading sessions survive every password change/reset"

## Guidelines for Future Work

- **Autocomplete safety**: A future auth change should see `ReadingSessionRepository.delete_for_user(...)` and immediately recognize it as reading-history deletion, not login revocation.
- **Code review**: Reviewers should flag any auth code that imports `ReadingSession` or reading-session repositories.
- **New domain concepts**: Any new domain concept with multiple meanings (e.g., "session", "thread", "issue" in different contexts) must use qualified names at boundaries.
- **Public API**: External API contracts (OpenAPI schemas, endpoint paths) may retain familiar names (`/api/session/`, `SessionListItem`) since they are user-facing and unambiguous in context.

## Files Changed in #2998

The domain rename touched ~100 files across:
- `app/models/` — model definition and relationships
- `app/repositories/` — repository helpers with explicit `reading_session_` prefixes
- `app/services/` — service helpers with explicit naming
- `comic_pile/` — core business logic modules
- `tests/` — all test files updated to use `ReadingSession`
- `scripts/` — utility scripts updated