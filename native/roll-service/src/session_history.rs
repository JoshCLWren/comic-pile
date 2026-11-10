//! Native same-path session-history reads.
//!
//! The snapshot list is deliberately isolated from the rest of the session
//! projection so this first browser-called slice can be deployed and reviewed
//! without changing the Python session implementation or its wire contract.

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    Json,
};
use serde_json::{json, Value};
use std::sync::Arc;
use utoipa::ToSchema;

#[derive(Debug, ToSchema)]
pub struct SessionSnapshotItem {
    pub id: i32,
    pub session_id: i32,
    pub created_at: String,
    pub description: Option<String>,
    pub event_id: Option<i32>,
}

#[derive(Debug, ToSchema)]
pub struct SessionSnapshotsResponse {
    pub session_id: i32,
    pub snapshots: Vec<SessionSnapshotItem>,
}

/// List restore snapshots for an owned reading session.
///
/// The ownership predicate and projection are one bounded SQL statement. A
/// foreign or missing session is intentionally indistinguishable, matching
/// Python's `get_owned_session_or_404` boundary.
pub async fn list_session_snapshots(
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
    .ok_or(ApiError::NotFound("Session not found".to_string()))?;
    let snapshots: Value = serde_json::from_str(row.get(0))
        .map_err(|_| ApiError::Internal("Internal Server Error".to_string()))?;
    Ok(Json(
        json!({"session_id": session_id, "snapshots": snapshots}),
    ))
}

/// OpenAPI declaration for both legacy and versioned same-path aliases.
#[utoipa::path(
    get,
    path = "/api/v1/sessions/{session_id}/snapshots",
    tag = "sessions",
    params(("session_id" = i32, Path, description = "Owned reading session")),
    responses(
        (status = 200, description = "Session restore snapshots", body = SessionSnapshotsResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Session not found")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_session_snapshots_documentation() {}
