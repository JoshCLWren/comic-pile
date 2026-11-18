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
//! preview and Roll/Queue writes stay wire-compatible. Overlap detection and
//! choice-effect computation are intentionally deferred to a follow-up PR; the
//! preview returns the evaluated series/issue structure with empty overlaps.

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
use std::collections::BTreeSet;
use std::sync::Arc;
use tracing::instrument;

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
#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ReadingGraphPreviewRequest {
    #[serde(default)]
    pub included_positions: Vec<i32>,
    #[serde(default)]
    pub overlap_choices: Vec<ReadingGraphOverlapChoice>,
    #[serde(default)]
    pub target_list_id: Option<i32>,
}

/// Python `ReadingGraphPreview`.
#[derive(Debug, Serialize, utoipa::ToSchema)]
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
    error_type: String,
    loc: Vec<String>,
    msg: String,
    input: Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    ctx: Option<Value>,
}

#[derive(Debug, Serialize)]
struct ValidationErrorResponse {
    detail: Vec<ValidationErrorItem>,
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

fn validation_error(msg: String, field: &str, input: Value) -> PreviewError {
    PreviewError::Validation(vec![ValidationErrorItem {
        error_type: "value_error".to_string(),
        loc: vec!["body".to_string(), field.to_string()],
        msg,
        input,
        ctx: Some(serde_json::json!({"error": {}})),
    }])
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
    // Load the CBL source list (404 if missing or inactive).
    let conn = db::checkout(&state).await?;
    let source = conn
        .query_opt(
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
    let content_hash: String = source.get(4);
    let revision_sha: String = source.get(5);

    // Load source entries for position validation.
    let entries = conn
        .query(
            "SELECT position FROM cbl_source_entries WHERE list_id = $1 ORDER BY position ASC",
            &[&list_id],
        )
        .await
        .map_err(|e| {
            tracing::error!(error_kind = crate::error_kind(&e), "load cbl entries failed");
            ApiError::Internal("CBL entries load failed".to_string())
        })?;
    let entry_positions: BTreeSet<i32> = entries
        .iter()
        .filter_map(|row| row.get::<_, Option<i32>>(0))
        .collect()
        .collect();

    // Validate selected positions.
    let selected_positions: BTreeSet<i32> = payload.included_positions.iter().cloned().collect();
    let unknown: Vec<i32> = selected_positions
        .iter()
        .filter(|p| !entry_positions.contains(p))
        .cloned()
        .collect();
    if !unknown.is_empty() {
        return Err(validation_error(
            format!("Source positions are not part of list {list_id}: {unknown:?}"),
            "included_positions",
            serde_json::to_value(&payload.included_positions).unwrap_or_default(),
        ));
    }

    // Load validated reading inputs (threads, issues, lists, prerequisites, exclusions).
    let validated =
        option_inputs::load_option_inputs(&state, auth).await.map_err(|e| {
            tracing::error!(error_kind = crate::error_kind(&e), "option inputs load failed");
            ApiError::Internal("reading inputs load failed".to_string())
        })?;

    let eligibility = reading_eligibility::evaluate(&validated).map_err(|e| {
        tracing::error!(error_kind = crate::error_kind(&e), "evaluation failed");
        ApiError::Internal("reading evaluation failed".to_string())
    })?;

    // Build series nodes, issue references, rollable/waiting IDs from the
    // evaluated eligibility. Overlap detection and choice effects are deferred
    // to a follow-up PR (#4842 tracking).
    let inputs = validated.inputs();
    let series = build_series_nodes(inputs, &eligibility);
    let issues = build_issue_references(inputs, &eligibility);
    let (rollable, waiting) = build_rollable_waiting(inputs, &eligibility);

    Ok(Json(ReadingGraphPreview {
        source_list_id,
        content_hash,
        revision_sha,
        series,
        overlaps: Vec::new(),
        issues,
        rollable_issue_ids: rollable,
        waiting_issue_ids: waiting,
        cycle_errors: Vec::new(),
    }))
}

fn build_series_nodes(
    inputs: &option_inputs::OptionInputs,
    eligibility: &std::collections::HashMap<i32, reading_constraints::ThreadEligibility>,
) -> Vec<ReadingGraphSeriesNode> {
    let mut nodes: Vec<ReadingGraphSeriesNode> = Vec::new();
    for thread in &inputs.core.threads {
        let volume_id = inputs
            .thread_volumes
            .get(&thread.id)
            .cloned()
            .unwrap_or_default();
        let state = eligibility
            .get(&thread.id)
            .map(|e| {
                if e.eligible {
                    "continues"
                } else {
                    "waits"
                }
            })
            .unwrap_or("waits");
        nodes.push(ReadingGraphSeriesNode {
            comicvine_volume_id: volume_id,
            series_name: thread.title.clone(),
            year: None,
            state: state.to_string(),
            unread_count: 0,
            rollable_count: 0,
            waiting_count: 0,
            waits_for_issue_ids: Vec::new(),
        });
    }
    nodes
}

fn build_issue_references(
    inputs: &option_inputs::OptionInputs,
    eligibility: &std::collections::HashMap<i32, reading_constraints::ThreadEligibility>,
) -> Vec<ReadingGraphIssueReference> {
    let mut refs: Vec<ReadingGraphIssueReference> = Vec::new();
    for issue in &inputs.core.issues {
        let volume_id = inputs
            .thread_volumes
            .get(&issue.thread_id)
            .cloned();
        let state = eligibility.get(&issue.thread_id);
        let blockers = state
            .map(|e| {
                e.blockers
                    .iter()
                    .map(|b| ReadingGraphBlocker {
                        kind: b.kind.clone(),
                        list_id: b.list_id,
                        waiting_on_issue_ids: b.waiting_on_issue_ids.clone(),
                        gate_issue_id: b.gate_issue_id,
                        explanation: format!("{} gate", b.kind),
                    })
                    .collect()
            })
            .unwrap_or_default();
        refs.push(ReadingGraphIssueReference {
            issue_id: issue.id,
            series_name: inputs
                .thread_volumes
                .get(&issue.thread_id)
                .cloned()
                .unwrap_or_default(),
            issue_number: issue.issue_number.clone(),
            comicvine_volume_id: volume_id,
            blockers,
        });
    }
    refs
}

fn build_rollable_waiting(
    inputs: &option_inputs::OptionInputs,
    eligibility: &std::collections::HashMap<i32, reading_constraints::ThreadEligibility>,
) -> (Vec<i32>, Vec<i32>) {
    let mut rollable: Vec<i32> = Vec::new();
    let mut waiting: Vec<i32> = Vec::new();
    for (thread_id, state) in eligibility {
        if state.eligible {
            if let Some(next) = state.next_issue_id {
                rollable.push(next);
            }
        } else {
            for issue in &inputs.core.issues {
                if issue.thread_id == *thread_id && issue.status != "read" {
                    waiting.push(issue.id);
                }
            }
        }
    }
    rollable.sort_unstable();
    waiting.sort_unstable();
    (rollable, waiting)
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
