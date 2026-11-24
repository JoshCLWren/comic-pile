# Reading Session Naming Convention

This document explains the domain naming convention for ComicPile's durable
reading-history records and which ambiguous-looking wire names are intentionally
retained.

## Problem

The durable reading-history model was historically exposed as bare `Session`.
That collided with authentication concepts:

- **Reading session**: a durable record of reading activity, dice state and
  snapshots in the `sessions` table.
- **Auth state**: access tokens, refresh tokens, token revocation and the
  `password_changed_at` credential epoch. ComicPile does not persist an
  auth-session model.

The collision contributed to the password-reset incident fixed in #2996:
credential recovery called a helper that deleted reading history instead of
revoking authentication state.

## Current Rust convention

Internal code uses qualified domain names:

| Concept | Current Rust name / location | Storage or wire boundary |
| --- | --- | --- |
| Durable reading history | `reading_session::ReadingSession` in `native/roll-service/src/reading_session.rs` | `sessions` table |
| Owned reading-session lookup | `db::require_owned_reading_session` in `native/roll-service/src/db.rs` | Owner-scoped SQL |
| Reading-history details | `native/roll-service/src/session_details.rs` | `GET /api/v2/reading-sessions/{session_id}/details` |
| Reading-history snapshots | `native/roll-service/src/session_history.rs` | `GET /api/v2/reading-sessions/{session_id}/snapshots` |
| Restore snapshots | `native/roll-service/src/undo_snapshots.rs` and `undo_apply.rs` | `/api/v2/undo/{session_id}/snapshots` |

Do not introduce a bare `Session`, `sessions` or `SessionModel` type for reading
history. The table and familiar HTTP names remain because clients and migrations
depend on them.

Authentication code uses precise names: access token, refresh token,
`password_changed_at`, `revoked_tokens` and `password_reset_tokens`.
`auth::services::AuthService::complete_reset` updates the user's password and
credential epoch and consumes the reset token; it does not call reading-history
persistence. A password reset must preserve populated reading history.

## Enforcement

- `AGENTS.md` makes the qualified-name rule mandatory for every agent.
- The native auth module must not import or call reading-history persistence.
  Credential revocation belongs to auth state, not to reading history.
- Reading-history helpers must not grow a bulk-delete operation that recreates
  `delete_all_sessions_for_user()`.
- Existing reset-flow tests live with the native auth handlers. Any change to
  reset or auth-state cleanup must include a database-backed regression proving
  that sessions, snapshots, threads, issues and events survive unchanged.

The former Python AST guard and `app/models/`, `app/repositories/` and
`app/services/` paths were retired with the Python runtime. They are not current
test or source locations.

## Retained ambiguity inventory

| Retained name | Where | Why retained |
| --- | --- | --- |
| `sessions` table | Native reading-history SQL | Renaming requires a migration and client coordination |
| Retired `/api/v1/sessions/` and `/api/v1/sessions/{id}` | No current native registration | `frontend/src/services/api-sessions.ts` still references them; caller drift is a separate repair |
| `/api/v2/reading-sessions/{id}/details` and `/snapshots` | Native session detail/history modules | Canonical resource-shaped reads |
| `SessionDetailsResponse`, `SessionSnapshotsResponse` | Rust response DTOs | Existing generated wire schema names |
| `SessionListItem`, `SessionSummary` and related frontend types | `frontend/src/types.ts` and `frontend/src/services/api-sessions.ts` | Existing client projections |
| `session_id` parameters, fields and prose | Public HTTP/JSON and SQL | Unambiguous in context and pervasive on the wire |

## Historical provenance

Issue #2998 introduced the qualified reading-history name across the retired
Python implementation. The convention survives the Rust cutover; references
below to Python model/repository paths describe that historical change only and
must not be restored as active architecture.
