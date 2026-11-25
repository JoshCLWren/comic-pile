# Reading Session Naming Convention

## Rule

The durable reading-history model is the Rust `ReadingSession` resource, backed by the `sessions` table. In application code, never shorten it to ambiguous `Session`, `sessions`, or `SessionModel` when authentication state could be confused with reading history.

Auth state uses precise names: access token, refresh token, `password_changed_at` credential epoch, `revoked_tokens`, and `password_reset_tokens`. There is no auth-session persistence model. A password reset must preserve populated reading history.

## Current native implementation

| Concept | Current symbol/path | Notes |
| --- | --- | --- |
| Durable reading history | `ReadingSession` in `native/roll-service/src/reading_session.rs` | Owner-scoped history and initialization state |
| Reading-session SQL/persistence | `native/roll-service/src/reading_session.rs`, `session_details.rs`, `session_history.rs`, `undo_apply.rs` | Qualified by the reading-history domain |
| Auth identity | `native/roll-service/src/auth/` | Access/refresh credentials and credential epoch only |
| Password reset | `native/roll-service/src/auth/services.rs` | Reset-token and user credential state; must not read/write reading history |
| Public wire table name | `sessions` | Storage compatibility name; not a code-level domain noun |

The auth module must not import or call reading-history persistence. Revoke credentials through auth state; reading history is not a credential.

## Current HTTP resources

- `POST /api/v2/reading-sessions` explicitly initializes or reuses durable reading history.
- `GET /api/v2/reading-sessions/{session_id}/details` returns one owned history detail.
- `GET /api/v2/reading-sessions/{session_id}/snapshots` returns owned snapshots.
- Undo snapshot list/restore uses `/api/v2/undo/{session_id}/snapshots...`.

The v1 session list/get operations and their unversioned aliases are retired. `GET /api/v2/roll/bootstrap` reads an already initialized session and never creates one.

**Compatibility discrepancy:** [#4405](https://github.com/JoshCLWren/comic-pile/issues/4405) establishes sessionless Roll with browser-owned pending state, while the current native service still creates six-hour server sessions and stores pending selection in PostgreSQL. The qualified `ReadingSession` name remains necessary for durable history, but the server-session Roll lifecycle is not the intended final product boundary.

Storage/API edges may retain familiar wire names such as `sessions`, `session_id`, `SessionListItem`, or `SessionDetail`. Ambiguity is resolved in code, not by renaming an established wire contract.

## Historical incident and rationale

The #2996 password-reset incident came from conflating authentication state with reading history. The corrective rule is architectural: auth code operates only on auth state, while reading-history code uses the qualified `ReadingSession` name. The former Python model/repository/service paths and Python naming-guard tests are historical and no longer exist.

## Verification boundary

Current Rust modules and DB-backed HTTP tests are the implementation witnesses. A dedicated native regression proving that password reset preserves a populated reading-history library is not claimed by this document; that remains a focused auth-test gap to record and repair in the owning work rather than assuming the old Python test still runs.
