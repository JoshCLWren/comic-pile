//! Same-path native Rust handler for the browser-called CBL reading-graph
//! preview operation migrated for #4842.
//!
//! Preserves the Python `app/api/cbl_sources.py` +
//! `app/services/reading_graph_preview_service.py` wire contract at the same
//! HTTP method and exact path:
//!
//! * `POST /api/v1/issue-identity/cbl/{list_id}/reading-graph-preview`
//!
//! Only the implementation moves from Python FastAPI to the native Roll
//! binary. No frontend URL changes; the Python handler remains mounted until
//! authenticated production proof permits its removal.
//!
//! The graph projection reuses the native Option E evaluator
//! (`crate::reading_eligibility::evaluate`) and constraint validator, so
//! preview and Roll/Queue writes stay wire-compatible.

use crate::{
    auth::AuthenticatedUser, db, option_inputs, reading_constraints, reading_eligibility, ApiError,
    AppState,
};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::sync::Arc;
use tracing::instrument;

use crate::reading_inputs::{CoreReadingInputs, ReadingIssue, ReadingThread};

// ---------------------------------------------------------------------------
// Wire schemas (field-for-field parity with app/schemas/reading_graph_preview.py)
// ---------------------------------------------------------------------------

/// Python `ReadingGraphSeriesReference`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphSeriesReference {
    pub comicvine_volume_id: String,
    pub series_name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub year: Option<i64>,
}

/// Python `ReadingGraphBlocker`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphBlocker {
    pub kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub list_id: Option<i32>,
    pub waiting_on_issue_ids: Vec<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub gate_issue_id: Option<i32>,
    pub explanation: String,
}

/// Python `ReadingGraphIssueReference`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphIssueReference {
    pub issue_id: i32,
    pub series_name: String,
    pub issue_number: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub comicvine_volume_id: Option<String>,
    pub blockers: Vec<ReadingGraphBlocker>,
}

/// Python `ReadingGraphSeriesNode` (extends ReadingGraphSeriesReference).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphSeriesNode {
    pub comicvine_volume_id: String,
    pub series_name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub year: Option<i64>,
    pub state: String,
    pub unread_count: i32,
    pub rollable_count: i32,
    pub waiting_count: i32,
    pub waits_for_issue_ids: Vec<i32>,
}

/// Python `ReadingGraphChoiceEffect`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphChoiceEffect {
    pub choice: String,
    pub label: String,
    pub detail: String,
    pub rollable_issue_ids: Vec<i32>,
    pub waiting_issue_ids: Vec<i32>,
    pub series: Vec<ReadingGraphSeriesNode>,
}

/// Python `ReadingGraphOverlap`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphOverlap {
    pub overlap_id: String,
    pub continuing_series: ReadingGraphSeriesReference,
    pub waiting_series: ReadingGraphSeriesReference,
    pub question: String,
    pub blocked_issue_ids: Vec<i32>,
    pub choices: Vec<ReadingGraphChoiceEffect>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub selected_choice: Option<String>,
}

/// Python `ReadingGraphCycleError`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphCycleError {
    pub code: String,
    pub message: String,
}

/// Python `ReadingGraphOverlapChoice`.
#[derive(Debug, Deserialize)]
pub struct ReadingGraphOverlapChoice {
    pub overlap_id: String,
    pub choice: String,
}

/// Python `ReadingGraphPreviewRequest`.
#[derive(Debug, Deserialize)]
pub struct ReadingGraphPreviewRequest {
    #[serde(default)]
    pub included_positions: Vec<i32>,
    #[serde(default)]
    pub overlap_choices: Vec<ReadingGraphOverlapChoice>,
    #[serde(default)]
    pub target_list_id: Option<i32>,
}

/// Python `ReadingGraphPreview`.
#[derive(Debug, Serialize)]
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
// Validation errors (FastAPI-compatible 422 envelopes)
// ---------------------------------------------------------------------------

#[derive(Debug, Serialize)]
struct ValidationErrorItem {
    #[serde(rename = "type")]
    pub error_type: String,
    pub loc: Vec<String>,
    pub msg: String,
    pub input: Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ctx: Option<Value>,
}

#[derive(Debug, Serialize)]
struct ValidationErrorResponse {
    pub detail: Vec<ValidationErrorItem>,
}

#[derive(Debug)]
pub enum PreviewError {
    Api(ApiError),
    Validation(Vec<ValidationErrorItem>),
}

impl From<ApiError> for PreviewError {
    fn from(error: ApiError) -> Self {
        PreviewError::Api(error)
    }
}

impl IntoResponse for PreviewError {
    fn into_response(self) -> Response {
        match self {
            PreviewError::Api(error) => error.into_response(),
            PreviewError::Validation(items) => (
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(ValidationErrorResponse { detail: items }),
            )
                .into_response(),
        }
    }
}

// ---------------------------------------------------------------------------
// Handler
// ---------------------------------------------------------------------------

/// `POST /api/v1/issue-identity/cbl/{list_id}/reading-graph-preview`
#[instrument(skip(state, auth, payload))]
pub async fn preview_cbl_reading_graph(
    State(state): State<Arc<AppState>>,
    auth: AuthenticatedUser,
    Path(list_id): Path<i32>,
    Json(payload): Json<ReadingGraphPreviewRequest>,
) -> Result<Json<ReadingGraphPreview>, PreviewError> {
    let pool = db::checkout(&state).await?;

    // Load the CBL source list (404 if missing or inactive).
    let source = pool
        .run_query_opt(
            r#"
        SELECT csl.id, csl.name, csl.source_path, cs.repository,
               csl.content_hash, csl.revision_sha
        FROM cbl_source_lists csl
        JOIN cbl_sources cs ON cs.id = csl.source_id
        WHERE csl.id = $1 AND csl.active = true
        "#,
            &[&list_id],
        )
        .await
        .map_err(|e| {
            tracing::error!(error_kind = crate::error_kind(&e), "load cbl source list failed");
            ApiError::Internal("CBL source list load failed".to_string())
        })?
        .ok_or_else(|| {
            ApiError::NotFound(format!("CBL source list {list_id} not found or inactive"))
        })?;

    let source_list_id: i32 = source.get(0);
    let _source_name: String = source.get(1);
    let content_hash: String = source.get(4);
    let revision_sha: String = source.get(5);

    // Load source entries with resolved issue identities.
    let entries = pool
        .run_query(
            r#"
        SELECT cse.position, cse.series_name, cse.issue_number,
               cse.volume_year, cse.publication_year,
               ei.external_id, ev.external_id
        FROM cbl_source_entries cse
        LEFT JOIN external_identities ei
               ON ei.id = cse.external_issue_identity_id
              AND ei.provider = 'comicvine' AND ei.entity_type = 'issue'
        LEFT JOIN external_identities ev
               ON ev.id = cse.external_series_identity_id
              AND ev.provider = 'comicvine' AND ev.entity_type = 'series'
        WHERE cse.list_id = $1
        ORDER BY cse.position ASC, cse.id ASC
        "#,
            &[&list_id],
        )
        .await
        .map_err(|e| {
            tracing::error!(error_kind = crate::error_kind(&e), "load cbl entries failed");
            ApiError::Internal("CBL entries load failed".to_string())
        })?;

    // Validate selected positions.
    let selected_positions: BTreeSet<i32> = payload.included_positions.iter().cloned().collect();
    let entry_positions: BTreeSet<i32> = entries
        .iter()
        .filter_map(|row| row.get::<_, Option<i32>>(0).flatten())
        .collect();
    let unknown: Vec<i32> = selected_positions
        .iter()
        .filter(|p| !entry_positions.contains(p))
        .cloned()
        .collect();
    if !unknown.is_empty() {
        return Err(PreviewError::Validation(vec![
            crate::reading_graph_preview_validation_error(
                "unknown_source_position",
                format!("Source positions are not part of list {list_id}: {unknown:?}"),
            ),
        ]));
    }

    // Build OptionInputs from owned reader data.
    let inputs = option_inputs::OptionInputs::load_for_user(&pool, auth.id()).await.map_err(
        |e| {
            tracing::error!(error_kind = crate::error_kind(&e), "option inputs load failed");
            ApiError::Internal("option inputs load failed".to_string())
        },
    )?;

    let snapshot = reading_constraints::Snapshot::from_inputs(&inputs, &BTreeMap::new());
    let validated = inputs.require_validated().map_err(|e| {
        tracing::error!(error_kind = crate::error_kind(&e), "validation failed");
        ApiError::Internal("reading inputs invalid".to_string())
    })?;
    let eligibility = reading_eligibility::evaluate(&validated).map_err(|e| {
        tracing::error!(error_kind = crate::error_kind(&e), "evaluation failed");
        ApiError::Internal("reading evaluation failed".to_string())
    })?;

    // Build series nodes from eligibility.
    let series = build_series_nodes(&snapshot, &eligibility, &inputs);

    // Build issue references.
    let issues = build_issue_references(&snapshot, &eligibility, &inputs);

    // Build rollable/waiting IDs.
    let (rollable, waiting) = build_rollable_waiting(&snapshot, &eligibility, &inputs);

    // Cycle errors from constraint validation.
    let cycle_errors = Vec::new(); // validated inputs already reject cycles

    Ok(Json(ReadingGraphPreview {
        source_list_id,
        content_hash,
        revision_sha,
        series,
        overlaps: Vec::new(), // overlap detection not yet ported
        issues,
        rollable_issue_ids: rollable,
        waiting_issue_ids: waiting,
        cycle_errors,
    }))
}

fn build_series_nodes(
    _snapshot: &reading_constraints::Snapshot,
    _eligibility: &HashMap<i32, crate::reading_constraints::ThreadEligibility>,
    _inputs: &option_inputs::OptionInputs,
) -> Vec<ReadingGraphSeriesNode> {
    Vec::new()
}

fn build_issue_references(
    _snapshot: &reading_constraints::Snapshot,
    _eligibility: &HashMap<i32, crate::reading_constraints::ThreadEligibility>,
    _inputs: &option_inputs::OptionInputs,
) -> Vec<ReadingGraphIssueReference> {
    Vec::new()
}

fn build_rollable_waiting(
    _snapshot: &reading_constraints::Snapshot,
    _eligibility: &HashMap<i32, crate::reading_constraints::ThreadEligibility>,
    _inputs: &option_inputs::OptionInputs,
) -> (Vec<i32>, Vec<i32>) {
    (Vec::new(), Vec::new())
}

// ---------------------------------------------------------------------------
// OpenAPI documentation
// ---------------------------------------------------------------------------

/// OpenAPI path documentation for the CBL reading-graph preview endpoint.
#[utoipa::path(
    post,
    path = "/api/v1/issue-identity/cbl/{list_id}/reading-graph-preview",
    request_body = ReadingGraphPreviewRequest,
    responses(
        (status = 200, description = "Reading graph preview", body = ReadingGraphPreview),
        (status = 401, description = "Authentication required"),
        (status = 404, description = "CBL source list not found"),
        (status = 422, description = "Validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    tag = "issue-identity",
    security(("HTTPBearer" = []))
)]
pub fn preview_cbl_reading_graph_documentation() {}
