//! Read-only prospective reading-graph preview for CBL adoption (native Rust).
//!
//! Mirrors Python's `app/services/reading_graph_preview_service.py`:
//! `preview_reading_graph`. It projects the same canonical Option E evaluator
//! onto a prospective CBL source selection, then surfaces overlap questions,
//! choice effects, the issue directory, and any cycle rejection.
//!
//! Nothing here persists list membership, issue read state, or an overlap
//! decision. It never writes; it only evaluates inside a read-only snapshot.

use crate::{
    auth::AuthenticatedUser, db, option_inputs, reading_constraints, reading_inputs, ApiError,
    AppState,
};
use axum::{
    extract::{Path, State},
    Json,
};
use serde::Deserialize;
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::sync::Arc;
use utoipa::ToSchema;
use tracing::instrument;

// ---------------------------------------------------------------------------
// Wire schemas (mirror app/schemas/reading_graph_preview.py)
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize, ToSchema)]
pub struct ReadingGraphOverlapChoice {
    pub overlap_id: String,
    pub choice: String,
}

#[derive(Debug, Deserialize, ToSchema)]
pub struct ReadingGraphPreviewRequest {
    #[serde(default)]
    pub included_positions: Vec<i32>,
    #[serde(default)]
    pub overlap_choices: Vec<ReadingGraphOverlapChoice>,
    #[serde(default)]
    pub target_list_id: Option<i32>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphSeriesReference {
    pub comicvine_volume_id: String,
    pub series_name: String,
    pub year: Option<i32>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphBlocker {
    pub kind: String,
    pub list_id: Option<i32>,
    pub waiting_on_issue_ids: Vec<i32>,
    pub gate_issue_id: Option<i32>,
    pub explanation: String,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphIssueReference {
    pub issue_id: i32,
    pub series_name: String,
    pub issue_number: String,
    pub comicvine_volume_id: Option<String>,
    pub blockers: Vec<ReadingGraphBlocker>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphSeriesNode {
    pub comicvine_volume_id: String,
    pub series_name: String,
    pub year: Option<i32>,
    pub state: String,
    pub unread_count: i32,
    pub rollable_count: i32,
    pub waiting_count: i32,
    pub waits_for_issue_ids: Vec<i32>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphChoiceEffect {
    pub choice: String,
    pub label: String,
    pub detail: String,
    pub rollable_issue_ids: Vec<i32>,
    pub waiting_issue_ids: Vec<i32>,
    pub series: Vec<ReadingGraphSeriesNode>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphOverlap {
    pub overlap_id: String,
    pub continuing_series: ReadingGraphSeriesReference,
    pub waiting_series: ReadingGraphSeriesReference,
    pub question: String,
    pub blocked_issue_ids: Vec<i32>,
    pub choices: Vec<ReadingGraphChoiceEffect>,
    pub selected_choice: Option<String>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphCycleError {
    pub code: String,
    pub message: String,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphPreview {
    pub source_list_id: i32,
    pub content_hash: String,
    pub revision_sha: String,
    pub series: Vec<ReadingGraphSeriesNode>,
    pub overlaps: Vec<ReadingGraphOverlap>,
    pub issues: Vec<ReadingGraphIssueReference>,
    pub rollable_issue_ids: Vec<i32>,
    pub waiting_issue_ids: Vec<i32>,
    pub cycle_errors: Vec<ReadingGraphCycleError>,
}

// ---------------------------------------------------------------------------
// Handler
// ---------------------------------------------------------------------------

/// `POST /api/v1/issue-identity/cbl/{list_id}/reading-graph-preview`
#[instrument(skip(state, _auth, payload))]
pub async fn preview_reading_graph(
    State(state): State<Arc<AppState>>,
    _auth: AuthenticatedUser,
    Path(list_id): Path<i32>,
    Json(payload): Json<ReadingGraphPreviewRequest>,
) -> Result<Json<ReadingGraphPreview>, ApiError> {
    let _ = (state, _auth, list_id, payload);
    Err(ApiError::Internal("not yet implemented".to_string()))
}

/// OpenAPI documentation for the reading-graph-preview endpoint.
#[utoipa::path(
    post,
    path = "/api/v1/issue-identity/cbl/{list_id}/reading-graph-preview",
    tag = "issue-identity",
    operation_id = "issue_identity_reading_graph_preview",
    params(("list_id" = i32, Path)),
    request_body = ReadingGraphPreviewRequest,
    responses(
        (status = 200, description = "Prospective reading graph preview", body = ReadingGraphPreview),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "CBL source list not found"),
        (status = 422, description = "Unknown source position or overlap choice"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub fn preview_reading_graph_documentation() {}
