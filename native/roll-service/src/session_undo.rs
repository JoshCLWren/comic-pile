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
use serde_json::{json, Value};
use std::sync::Arc;

/// One restore snapshot in reverse chronological order.
#[derive(Debug, utoipa::ToSchema)]
pub struct UndoSnapshotItem {
    pub id: i32,
    pub session_id: i32,
    pub created_at: String,
    pub description: Option<String>,
    pub event_id: Option<i32>,
}

/// Wire shape of Python `SnapshotsListResponse` for the undo snapshot list.
#[derive(Debug, utoipa::ToSchema)]
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
) -> Result<Json<Value>, ApiError> {
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
    let snapshots: Value = serde_json::from_str(row.get(0)).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        ApiError::Internal("Internal Server Error".to_string())
    })?;
    Ok(Json(
        json!({"session_id": session_id, "snapshots": snapshots}),
    ))
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
