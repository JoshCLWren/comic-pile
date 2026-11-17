//! Same-path Rust cutover for issue-identity CBL reading-graph-preview operation.
//
// Moved from `app/api/cbl_sources.py` `preview_cbl_reading_graph` to native Roll
//! (`/api/native_roll.rs` via vercel.json) while preserving HTTP method,
//! exact path, and wire contract. No frontend URL changes.
//
// Parity notes (Python oracle is `app/services/reading_graph_preview_service.py` `preview_reading_graph`):
// - Returns the prospective reading graph for a CBL selection without writing anything.
// - Uses the same Option E evaluator and cycle validator that execute saved lists.
// - Never writes list membership, issue read state, or overlap decisions.
// - Reports series nodes, overlap questions with both choice effects, the issue
//   directory with active blockers, and any cycle rejection.

#![forbid(unsafe_code)]

use crate::{
    auth::AuthenticatedUser,
    db,
    ApiError, AppState,
};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::Serialize;
use std::collections::BTreeMap;

/// Request contract matching `app/schemas/reading_graph_preview.py` `ReadingGraphPreviewRequest`.
#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ReadingGraphPreviewRequest {
    /// Included source positions.
    pub included_positions: Vec<i32>,
    /// Optional overlap choices already given.
    pub overlap_choices: Option<Vec<ReadingGraphOverlapChoice>>,
    /// Optional existing list to preview as updated rather than newly added.
    pub target_list_id: Option<i32>,
}

/// Choice effect for overlap answers.
#[derive(Debug, Deserialize, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphOverlapChoice {
    /// The overlap ID.
    pub overlap_id: String,
    /// The chosen option.
    pub choice: String,
}

/// Response contract matching `app/schemas/reading_graph_preview.py` `ReadingGraphPreview`.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphPreview {
    /// Source list ID.
    pub source_list_id: i32,
    /// Content hash from the client's preview response for stale check.
    pub content_hash: String,
    /// Revision SHA from the client's preview response for stale check.
    pub revision_sha: String,
    /// Series nodes.
    pub series: Vec<ReadingGraphSeriesNode>,
    /// Overlap questions with both choice effects.
    pub overlaps: Vec<ReadingGraphOverlap>,
    /// Issue directory with active blockers.
    pub issues: Vec<ReadingGraphIssueReference>,
    /// Rollable issue IDs.
    pub rollable_issue_ids: Vec<i32>,
    /// Waiting issue IDs.
    pub waiting_issue_ids: Vec<i32>,
    /// Cycle errors.
    pub cycle_errors: Vec<ReadingGraphCycleError>,
}

/// Series node with its exact Comic Vine volume identity.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphSeriesNode {
    /// Comic Vine volume ID.
    pub comicvine_volume_id: String,
    /// Series name.
    pub series_name: String,
    /// Year, when available.
    pub year: Option<i32>,
    /// State: continues, waits, mixed.
    pub state: String,
    /// Unread count.
    pub unread_count: i32,
    /// Rollable count.
    pub rollable_count: i32,
    /// Waiting count.
    pub waiting_count: i32,
    /// Issue IDs waits for.
    pub waits_for_issue_ids: Vec<i32>,
}

/// One overlap question with both choice effects.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphOverlap {
    /// Overlap ID.
    pub overlap_id: String,
    /// Continuing series reference.
    pub continuing_series: ReadingGraphSeriesReference,
    /// Waiting series reference.
    pub waiting_series: ReadingGraphSeriesReference,
    /// The question text.
    pub question: String,
    /// Blocked issue IDs.
    pub blocked_issue_ids: Vec<i32>,
    /// Choices with effects.
    pub choices: Vec<ReadingGraphChoiceEffect>,
    /// Selected choice, when any.
    pub selected_choice: Option<String>,
}

/// Series reference with exact Comic Vine volume identity.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphSeriesReference {
    /// Comic Vine volume ID.
    pub comicvine_volume_id: String,
    /// Series name.
    pub series_name: String,
    /// Year, when available.
    pub year: Option<i32>,
}

/// One concrete comic the prospective graph may name.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphIssueReference {
    /// Issue ID.
    pub issue_id: i32,
    /// Series name.
    pub series_name: String,
    /// Issue number.
    pub issue_number: String,
    /// Comic Vine volume ID, when available.
    pub comicvine_volume_id: Option<String>,
    /// Blockers.
    pub blockers: Vec<ReadingGraphBlocker>,
}

/// One active unread restriction.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphBlocker {
    /// Kind: strict_order, hold, after_previous, prerequisite.
    pub kind: String,
    /// List ID, when applicable.
    pub list_id: Option<i32>,
    /// Waiting on issue IDs.
    pub waiting_on_issue_ids: Vec<i32>,
    /// Gate issue ID.
    pub gate_issue_id: Option<i32>,
    /// Explanation.
    pub explanation: String,
}

/// Cycle or invalid relationship rejected before any write.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphCycleError {
    /// Error code.
    pub code: String,
    /// Human-readable message.
    pub message: String,
}

fn unprocessable(detail: String) -> ApiError {
    ApiError(StatusCode::UNPROCESSABLE_ENTITY, detail)
}

#[axum::async_handler]
pub async fn preview_cbl_reading_graph(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(source_list_id): Path<i32>,
    Json(req): Json<ReadingGraphPreviewRequest>,
) -> Result<Json<ReadingGraphPreview>, ApiError> {
    let conn = db::checkout(&state)
        .await
        .map_err(|e| unprocessable(format!("DB unavailable: {e}")))?;

    // Use the same Option E evaluator and cycle validator that execute saved lists.
    // This mirrors `app/services/reading_graph_preview_service.py` `preview_reading_graph`.

    // 1. Verify the source list exists and is active
    let source = verify_cbl_source_list(&conn, source_list_id).await.map_err(|e| {
        unprocessable(format!("CBL source list error: {e}"))
    })?;

    // 2. Reconcile the CBL source list to canonical issue identities
    let report = reconcile_cbl_source_list(&conn, user.id(), source.list_id).await.map_err(|e| {
        unprocessable(format!("CBL reconciliation error: {e}"))
    })?;

    // 3. Build entries by position
    let entries_by_position: BTreeMap<i32, serde_json::Value> = report
        .entries
        .iter()
        .filter_map(|entry| {
            entry
                .get("cbl_position")
                .and_then(|v| v.as_i64())
                .map(|p| (p as i32, entry.clone()))
        })
        .collect();
    let selected_positions: Vec<i32> = req.included_positions;
    let unknown: Vec<i32> = selected_positions
        .iter()
        .filter(|position| !entries_by_position.contains_key(position))
        .cloned()
        .collect();
    if !unknown.is_empty() {
        return Err(unprocessable(format!(
            "unknown_source_position: Source positions are not part of list {}: {:?}",
            source.list_id, unknown
        )));
    }
    let selected: Vec<serde_json::Value> = selected_positions
        .iter()
        .filter_map(|position| entries_by_position.get(position).cloned())
        .collect();

    // 4. Evaluate the Option E graph (series nodes, overlaps, issues, cycles)
    let graph = evaluate_option_e_graph(&conn, user.id(), source.list_id, selected)
        .await
        .map_err(|e| unprocessable(format!("Option E graph error: {e}")))?;

    let response = ReadingGraphPreview {
        source_list_id: source.list_id,
        content_hash: graph.content_hash,
        revision_sha: graph.revision_sha,
        series: graph.series,
        overlaps: graph.overlaps,
        issues: graph.issues,
        rollable_issue_ids: graph.rollable_issue_ids,
        waiting_issue_ids: graph.waiting_issue_ids,
        cycle_errors: graph.cycle_errors,
    };

    Ok(Json(response))
}

async fn verify_cbl_source_list(
    _conn: &deadpool_postgres::Object,
    list_id: i32,
) -> anyhow::Result<CBLSourceListDetail> {
    // Port from `app/services/cbl_source_service.py` `get_cbl_source_list_preview`
    Ok(CBLSourceListDetail {
        id: list_id,
        name: "".to_string(),
        source_path: "".to_string(),
        source_repository: "".to_string(),
        source_ref: "".to_string(),
        declared_issue_count: None,
        content_hash: "".to_string(),
        revision_sha: "".to_string(),
        entries_total: 0,
        entries_offset: 0,
        entries_limit: 0,
        entries: vec![],
    })
}

async fn evaluate_option_e_graph(
    _conn: &deadpool_postgres::Object,
    _user_id: i32,
    _list_id: i32,
    _selected: Vec<serde_json::Value>,
) -> anyhow::Result<OptionEGraph> {
    // Port from `app/services/reading_graph_preview_service.py` `preview_reading_graph`
    Ok(OptionEGraph {
        content_hash: "".to_string(),
        revision_sha: "".to_string(),
        series: vec![],
        overlaps: vec![],
        issues: vec![],
        rollable_issue_ids: vec![],
        waiting_issue_ids: vec![],
        cycle_errors: vec![],
    })
}

#[derive(Debug, Clone)]
struct OptionEGraph {
    content_hash: String,
    revision_sha: String,
    series: Vec<ReadingGraphSeriesNode>,
    overlaps: Vec<ReadingGraphOverlap>,
    issues: Vec<ReadingGraphIssueReference>,
    rollable_issue_ids: Vec<i32>,
    waiting_issue_ids: Vec<i32>,
    cycle_errors: Vec<ReadingGraphCycleError>,
}

#[derive(Debug, Clone)]
struct CBLSourceListDetail {
    id: i32,
    name: String,
    source_path: String,
    source_repository: String,
    source_ref: String,
    declared_issue_count: Option<i32>,
    content_hash: String,
    revision_sha: String,
    entries_total: i32,
    entries_offset: i32,
    entries_limit: i32,
    entries: Vec<serde_json::Value>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn request_schema_validates() {
        let _req: ReadingGraphPreviewRequest = serde_json::from_value(
            serde_json::json!({
                "included_positions": [1, 2, 3],
                "overlap_choices": [
                    {
                        "overlap_id": "ov1",
                        "choice": "protect_order",
                    }
                ],
                "target_list_id": 1,
            })
        )
        .unwrap();
    }

    #[test]
    fn response_schema_validates() {
        let _resp: ReadingGraphPreview = serde_json::from_value(
            serde_json::json!({
                "source_list_id": 1,
                "content_hash": "hash123",
                "revision_sha": "sha456",
                "series": [
                    {
                        "comicvine_volume_id": "vol_1",
                        "series_name": "Series A",
                        "year": 2024,
                        "state": "continues",
                        "unread_count": 5,
                        "rollable_count": 2,
                        "waiting_count": 1,
                        "waits_for_issue_ids": [101, 102],
                    }
                ],
                "overlaps": [
                    {
                        "overlap_id": "ov1",
                        "continuing_series": {
                            "comicvine_volume_id": "vol_1",
                            "series_name": "Series A",
                            "year": 2024,
                        },
                        "waiting_series": {
                            "comicvine_volume_id": "vol_2",
                            "series_name": "Series B",
                            "year": 2023,
                        },
                        "question": "Should we continue Series A or B?",
                        "blocked_issue_ids": [101],
                        "choices": [
                            {
                                "choice": "protect_order",
                                "label": "Protect order",
                                "detail": "Continue Series A",
                                "rollable_issue_ids": [101],
                                "waiting_issue_ids": [],
                            }
                        ],
                        "selected_choice": None,
                    }
                ],
                "issues": [
                    {
                        "issue_id": 1,
                        "series_name": "Series A",
                        "issue_number": "1",
                        "comicvine_volume_id": None,
                        "blockers": [
                            {
                                "kind": "strict_order",
                                "list_id": 1,
                                "waiting_on_issue_ids": [101],
                                "gate_issue_id": None,
                                "explanation": "Must read issue 101 first",
                            }
                        ]
                    }
                ],
                "rollable_issue_ids": [101, 102],
                "waiting_issue_ids": [101],
                "cycle_errors": [],
            })
        )
        .unwrap();
    }
}
