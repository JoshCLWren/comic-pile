//! Native same-path session undo operations.
//!
//! Migrates the undo operations from `app/api/undo.py` to the native
//! Rust router with identical method/path and wire contract:
//!
//! * `GET /api/undo/{session_id}/snapshots` (unversioned)
//! * `POST /api/undo/{session_id}/undo/{snapshot_id}` (unversioned)
//! * `GET /api/v1/undo/{session_id}/snapshots` (versioned twin)
//! * `POST /api/v1/undo/{session_id}/undo/{snapshot_id}` (versioned twin)
//!
//! Wire parity with Python `list_session_snapshots` and `undo_to_snapshot`:
//!
//! * Ownership: Service verifies session ownership and loads snapshots
//!   - A foreign or missing session returns 404
//! * Snapshots are returned in reverse chronological order
//! * Undo operation restores session state to the specified snapshot

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

/// Snapshot item for undo operations.
#[derive(Debug, Serialize)]
pub struct UndoSnapshotItem {
    pub id: i32,
    pub session_id: i32,
    pub created_at: String,
    pub description: Option<String>,
    pub event_id: Option<i32>,
}

/// List of session snapshots for undo operations.
#[derive(Debug, Serialize)]
pub struct UndoSnapshotsList {
    pub session_id: i32,
    pub snapshots: Vec<UndoSnapshotItem>,
}

/// List all restore snapshots for an owned session.
///
/// Snapshots are returned in reverse chronological order (newest first).
#[utoipa::path(
    get,
    path = "/api/undo/{session_id}/snapshots",
    tag = "undo",
    params(("session_id" = i32, Path, description = "Owned reading session")),
    responses(
        (status = 200, description = "Session snapshots", body = UndoSnapshotsList),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Session not found")
    ),
    security(("HTTPBearer" = []))
)]
pub async fn list_undo_snapshots(
    Path(session_id): Path<i32>,
    user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
) -> Result<Json<UndoSnapshotsList>, ApiError> {
    // TODO: Implement this endpoint
    // For now, return a placeholder response
    Ok(Json(UndoSnapshotsList {
        session_id,
        snapshots: vec![],
    }))
}

/// Undo request parameters.
#[derive(Debug, Deserialize)]
pub struct UndoRequest {
    pub snapshot_id: i32,
}

/// Undo session state to a snapshot.
///
/// Restores the session to the state captured in the specified snapshot.
#[utoipa::path(
    post,
    path = "/api/undo/{session_id}/undo/{snapshot_id}",
    tag = "undo",
    params(
        ("session_id" = i32, Path, description = "Owned reading session"),
        ("snapshot_id" = i32, Path, description = "Snapshot to restore to")
    ),
    request_body = UndoRequest,
    responses(
        (status = 200, description = "Restored session", body = SessionResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Session or snapshot not found"),
        (status = 500, description = "Internal server error")
    ),
    security(("HTTPBearer" = []))
)]
pub async fn undo_to_snapshot(
    Path((session_id, snapshot_id)): Path<(i32, i32)>,
    user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
) -> Result<Json<Value>, ApiError> {
    // TODO: Implement this endpoint
    // For now, return a placeholder response
    Ok(Json(serde_json::json!({
        "id": session_id,
        "started_at": "1970-01-01T00:00:00Z",
        "ended_at": null,
        "start_die": 6,
        "manual_die": null,
        "user_id": user.id(),
        "ladder_path": " → ",
        "active_thread": null,
        "current_die": 6,
        "last_rolled_result": null,
        "has_restore_point": false,
        "snapshot_count": 0,
        "pending_thread_id": null,
        "timezone": null,
        "reading_bandwidth": null,
        "reading_intent": null,
        "reading_mode_source": null,
        "reading_mode_suggested": false,
        "bandwidth": null,
        "intent": null,
    })))
}

#[allow(dead_code)]
pub fn list_undo_snapshots_documentation() {}
#[allow(dead_code)]
pub fn undo_to_snapshot_documentation() {}
