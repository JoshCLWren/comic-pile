//! Native same-path undo snapshot reads.
//!
//! Migrates the undo snapshot *read* from `app/api/undo.py` to the native Rust
//! router with identical method/path and wire contract:
//!
//! * `GET /api/undo/{session_id}/snapshots` (unversioned)
//! * `GET /api/v1/undo/{session_id}/snapshots` (versioned twin)
//!
//! Wire parity with Python `list_session_snapshots` (`app/api/undo.py`,
//! `UndoSnapshotService.list_session_snapshots`):
//!
//! * Ownership: the service loads the session through
//!   `UndoSnapshotRepository.get_user_session` (`WHERE id = $1 AND user_id =
//!   $2`); a foreign or missing session returns 404 with the exact detail
//!   `"Session {session_id} not found"` — note this detail differs from the
//!   sessions-family `"Session not found"` boundary, so the two families must
//!   never share one handler.
//! * Snapshots are returned in reverse chronological order
//!   (`created_at DESC, id DESC`), newest first.
//! * The response is `SnapshotsListResponse`: `session_id` echoes the request
//!   path parameter and `snapshots` is a (possibly empty) list of
//!   `SnapshotResponse` items (`id`, `session_id`, `created_at`, `description`,
//!   `event_id`).
//! * Timestamps are emitted as UTC `...Z` strings, matching the earlier
//!   session-snapshots Rust slice (PR #4888); the frontend parses both the
//!   Python `+00:00` and Rust `Z` forms as dates.
//!
//! The undo *write* (`POST /api/undo/{session_id}/undo/{snapshot_id}`) is not
//! part of this slice: it applies delta/full snapshots through a multi-table
//! transaction and stays on Python until its own cutover.
//!
//! Bounded reads only: one ownership-checked statement that aggregates the
//! session's snapshots server-side. No per-row fan-out. Python handlers remain;
//! deployed ingress in `vercel.json` shadows them after this cutover.

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    Json,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

/// One restore snapshot in reverse chronological order.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct UndoSnapshotItem {
    pub id: i32,
    pub session_id: i32,
    pub created_at: String,
    pub description: Option<String>,
    pub event_id: Option<i32>,
}

/// Wire shape of Python `SnapshotsListResponse` for the undo snapshot list.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct UndoSnapshotsList {
    pub session_id: i32,
    pub snapshots: Vec<UndoSnapshotItem>,
}

/// List restore snapshots for an owned reading session (undo boundary).
///
/// The ownership predicate and projection are one bounded SQL statement. A
/// foreign or missing session is intentionally indistinguishable, matching
/// Python's `get_user_session` boundary and its `Session {id} not found`
/// detail.
pub async fn list_undo_snapshots(
    Path(session_id): Path<i32>,
    user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
) -> Result<Json<UndoSnapshotsList>, ApiError> {
    let connection = db::checkout(&state).await?;
    let row = db::query_one_optional(
        &state,
        connection,
        "SELECT COALESCE((
             SELECT json_agg(json_build_object(
                 'id', s.id,
                 'session_id', s.session_id,
                 'created_at', to_char(s.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'),
                 'description', s.description,
                 'event_id', s.event_id
             ) ORDER BY s.created_at DESC, s.id DESC)
             FROM snapshots s WHERE s.session_id = rs.id
         ), '[]'::json)::text
         FROM sessions rs
         WHERE rs.id = $1 AND rs.user_id = $2",
        &[&session_id, &user.id()],
    )
    .await?
    .ok_or_else(|| {
        ApiError::NotFound(format!("Session {session_id} not found"))
    })?;
    let snapshots: Vec<UndoSnapshotItem> = serde_json::from_str(row.get(0)).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        ApiError::Internal("Internal Server Error".to_string())
    })?;
    Ok(Json(UndoSnapshotsList {
        session_id,
        snapshots,
    }))
}

/// OpenAPI declaration for both legacy and versioned same-path aliases.
#[utoipa::path(
    get,
    path = "/api/v1/undo/{session_id}/snapshots",
    tag = "undo",
    params(("session_id" = i32, Path, description = "Owned reading session")),
    responses(
        (status = 200, description = "Session snapshots", body = UndoSnapshotsList),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Session not found")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_undo_snapshots_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{db, test_support};
    use axum::http::StatusCode;
    use std::sync::Arc;

    async fn database_fixture() -> (
        Arc<AppState>,
        AuthenticatedUser,
        tokio::sync::MutexGuard<'static, ()>,
    ) {
        let state = test_support::test_state(2)
            .await
            .expect("RUST_ROLL_TEST_DATABASE_URL is required");
        let guard = test_support::reset_for_test(&state).await;
        let connection = db::checkout(&state).await.expect("fixture connection");
        connection
            .batch_execute(
                "INSERT INTO users (id, username) VALUES (9101, 'undo-owner'), (9102, 'undo-other');
                 INSERT INTO sessions (id, user_id, started_at, start_die, reading_mode_suggested)
                   VALUES (9301, 9101, NOW(), 6, false), (9302, 9102, NOW(), 6, false);
                 INSERT INTO events (id, session_id, type, timestamp)
                   VALUES (9501, 9301, 'roll', '2026-01-01T00:00:00Z');
                 INSERT INTO snapshots (id, session_id, thread_states, created_at, description, event_id)
                   VALUES (9401, 9301, '{}'::json, '2026-01-02T00:00:00Z', 'first snapshot', NULL),
                          (9402, 9301, '{}'::json, '2026-01-03T00:00:00Z', 'second snapshot', 9501),
                          (9403, 9302, '{}'::json, '2026-01-04T00:00:00Z', 'foreign snapshot', NULL);",
            )
            .await
            .expect("seed undo snapshots fixture");
        drop(connection);
        (state, AuthenticatedUser::for_test(9101), guard)
    }

    #[tokio::test]
    async fn list_undo_snapshots_returns_owned_newest_first() {
        let (state, user, _guard) = database_fixture().await;
        let Json(response) = list_undo_snapshots(Path(9301), user, State(state.clone()))
            .await
            .expect("owned session snapshots");
        assert_eq!(response.session_id, 9301);
        let ids: Vec<i32> = response.snapshots.iter().map(|item| item.id).collect();
        assert_eq!(
            ids,
            vec![9402, 9401],
            "snapshots must be reverse chronological"
        );
        assert_eq!(
            response.snapshots[0].description.as_deref(),
            Some("second snapshot")
        );
        assert_eq!(response.snapshots[0].event_id, Some(9501));
        assert_eq!(
            response.snapshots[1].description.as_deref(),
            Some("first snapshot")
        );
        assert_eq!(response.snapshots[1].event_id, None);
        assert!(
            response.snapshots[0].created_at.ends_with('Z'),
            "created_at must be a UTC Z-suffix timestamp, got {}",
            response.snapshots[0].created_at
        );
    }

    #[tokio::test]
    async fn list_undo_snapshots_rejects_missing_and_foreign_sessions() {
        let (state, user, _guard) = database_fixture().await;
        let missing = list_undo_snapshots(Path(9999), user, State(state.clone()))
            .await
            .expect_err("missing session must 404");
        assert_eq!(missing.status(), StatusCode::NOT_FOUND);
        assert_eq!(missing.detail(), "Session 9999 not found");

        let foreign = list_undo_snapshots(Path(9302), user, State(state.clone()))
            .await
            .expect_err("foreign session must 404");
        assert_eq!(foreign.status(), StatusCode::NOT_FOUND);
        assert_eq!(foreign.detail(), "Session 9302 not found");
    }

    #[tokio::test]
    async fn list_undo_snapshots_empty_for_session_without_snapshots() {
        let (state, user, _guard) = database_fixture().await;
        let connection = db::checkout(&state).await.expect("fixture connection");
        connection
            .batch_execute(
                "INSERT INTO sessions (id, user_id, started_at, start_die, reading_mode_suggested)
                   VALUES (9303, 9101, NOW(), 6, false);",
            )
            .await
            .expect("seed snapshotless session");
        drop(connection);
        let Json(response) = list_undo_snapshots(Path(9303), user, State(state.clone()))
            .await
            .expect("snapshotless session must be an empty list, not an error");
        assert_eq!(response.session_id, 9303);
        assert!(response.snapshots.is_empty());
    }
}
