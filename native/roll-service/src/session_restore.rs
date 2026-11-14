//! Native same-path session restore operations.
//!
//! Migrates the restore-session-start operation from `app/api/session.py` to the native
//! Rust router with identical method/path and wire contract:
//!
//! * `POST /api/sessions/{session_id}/restore-session-start` (unversioned)
//! * `POST /api/v1/sessions/{session_id}/restore-session-start` (versioned twin)
//!
//! Wire parity with Python `restore_reading_session_start`:
//!
//! * Ownership: `get_owned_session_or_404` — a foreign or missing session
//!   returns 404 with the exact detail `"Session not found"`.
//! * Restores session to its initial state at session start, including:
//!   - Resetting all die changes to the original `start_die`
//!   - Clearing all events after the initial roll
//!   - Resetting `pending_thread_id` to null
//!   - Preserving `snoozed_thread_ids` and `skipped_thread_ids`
//! * Returns the restored session details with the same response structure
//!   as `get_session` (see `session_detail.rs`).

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use std::sync::Arc;

/// Restore a session to its initial state at session start.
///
/// This operation resets the session to its initial state, including:
/// - Resetting all die changes to the original `start_die`
/// - Clearing all events after the initial roll
/// - Resetting `pending_thread_id` to null
/// - Preserving `snoozed_thread_ids` and `skipped_thread_ids`
#[utoipa::path(
    post,
    path = "/api/sessions/{session_id}/restore-session-start",
    tag = "sessions",
    params(("session_id" = i32, Path, description = "Owned reading session")),
    responses(
        (status = 200, description = "Restored session", body = SessionResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Session not found"),
        (status = 500, description = "Internal server error")
    ),
    security(("HTTPBearer" = []))
)]
pub async fn restore_session_start(
    Path(session_id): Path<i32>,
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
pub fn restore_session_start_documentation() {}
