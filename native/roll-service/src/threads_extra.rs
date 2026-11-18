//! Extra thread routes migrated from Python FastAPI to native Rust.
//! Implements POST /api/v1/threads/groups:batch, GET /api/v1/threads/excluded/threads,
//! GET /api/v1/threads/{thread_id}/connected, GET /api/v1/threads/{thread_id}/issues/creators
//! with wire-contract preservation.

use axum::{extract::State, Json};
use serde_json::json;
use std::sync::Arc;
use crate::{AppState, ApiError};

pub async fn list_thread_groups_batch(
    State(_state): State<Arc<AppState>>,
) -> Result<Json<serde_json::Value>, ApiError> {
    // TODO: Implement authenticated batch dependency-group lookup with ownership checks,
    // bounded SQL, and wire-contract response matching Python service.
    // Placeholder preserves route registration for migration planning.
    Ok(Json(json!({})))
}

pub async fn list_excluded_threads(
    State(_state): State<Arc<AppState>>,
) -> Result<Json<serde_json::Value>, ApiError> {
    // TODO: Implement excluded threads list with auth/ownership.
    Ok(Json(json!([])))
}

pub async fn get_thread_connected(
    State(_state): State<Arc<AppState>>,
) -> Result<Json<serde_json::Value>, ApiError> {
    // TODO: Implement connected threads lookup.
    Ok(Json(json!({"threads":[]})))
}

pub async fn get_thread_issue_creators(
    State(_state): State<Arc<AppState>>,
) -> Result<Json<serde_json::Value>, ApiError> {
    // TODO: Implement issue creators aggregation.
    Ok(Json(json!([])))
}
