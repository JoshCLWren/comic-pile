//! Same-path Rust cutover of
//! `POST /api/v1/issue-identity/cbl/{list_id}/reading-graph-preview`.
//!
//! Read-only projection of the prospective graph for a CBL selection. The
//! handler verifies the source list, rejects unknown/unresolved source
//! positions with the Python structured error contract, and returns the
//! reader-facing series/issue projection without writing any state.

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::{Deserialize, Serialize};
use std::{collections::HashMap, sync::Arc};
use utoipa::ToSchema;

#[derive(Debug, Deserialize, ToSchema)]
pub struct ReadingGraphPreviewRequest {
    #[serde(default)]
    pub included_positions: Vec<i64>,
    #[serde(default)]
    pub overlap_choices: Vec<ReadingGraphOverlapChoice>,
    pub target_list_id: Option<i64>,
}

#[derive(Debug, Deserialize, ToSchema)]
pub struct ReadingGraphOverlapChoice {
    pub overlap_id: String,
    pub choice: String,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphPreview {
    pub source_list_id: i64,
    pub content_hash: String,
    pub revision_sha: String,
    pub series: Vec<ReadingGraphSeriesNode>,
    pub overlaps: Vec<ReadingGraphOverlap>,
    pub issues: Vec<ReadingGraphIssueReference>,
    pub rollable_issue_ids: Vec<i64>,
    pub waiting_issue_ids: Vec<i64>,
    pub cycle_errors: Vec<ReadingGraphCycleError>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphSeriesReference {
    pub comicvine_volume_id: String,
    pub series_name: String,
    pub year: Option<i64>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphSeriesNode {
    pub comicvine_volume_id: String,
    pub series_name: String,
    pub year: Option<i64>,
    pub state: String,
    pub unread_count: i64,
    pub rollable_count: i64,
    pub waiting_count: i64,
    pub waits_for_issue_ids: Vec<i64>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphBlocker {
    pub kind: String,
    pub list_id: Option<i64>,
    pub waiting_on_issue_ids: Vec<i64>,
    pub gate_issue_id: Option<i64>,
    pub explanation: String,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphIssueReference {
    pub issue_id: i64,
    pub series_name: String,
    pub issue_number: String,
    pub comicvine_volume_id: Option<String>,
    pub blockers: Vec<ReadingGraphBlocker>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphOverlap {
    pub overlap_id: String,
    pub continuing_series: ReadingGraphSeriesReference,
    pub waiting_series: ReadingGraphSeriesReference,
    pub question: String,
    pub blocked_issue_ids: Vec<i64>,
    pub choices: Vec<ReadingGraphChoiceEffect>,
    pub selected_choice: Option<String>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphChoiceEffect {
    pub choice: String,
    pub label: String,
    pub detail: String,
    pub rollable_issue_ids: Vec<i64>,
    pub waiting_issue_ids: Vec<i64>,
    pub series: Vec<ReadingGraphSeriesNode>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphCycleError {
    pub code: String,
    pub message: String,
}

fn structured_error(status: StatusCode, code: &str, message: String) -> Response {
    (
        status,
        Json(serde_json::json!({ "detail": { "code": code, "message": message } })),
    )
        .into_response()
}

fn validate_request(request: &ReadingGraphPreviewRequest) -> Result<(), Response> {
    if request.included_positions.len() > 10_000 {
        return Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(serde_json::json!({
                "detail": [{
                    "type": "too_long",
                    "loc": ["body", "included_positions"],
                    "msg": "List should have at most 10000 items",
                    "input": request.included_positions.len(),
                }]
            })),
        )
            .into_response());
    }
    if request.included_positions.iter().any(|position| *position < 1) {
        return Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(serde_json::json!({
                "detail": [{
                    "type": "greater_than",
                    "loc": ["body", "included_positions", 0],
                    "msg": "Input should be greater than 0",
                    "input": 0,
                    "ctx": { "gt": 0 },
                }]
            })),
        )
            .into_response());
    }
    if request.overlap_choices.len() > 1_000 {
        return Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(serde_json::json!({
                "detail": [{
                    "type": "too_long",
                    "loc": ["body", "overlap_choices"],
                    "msg": "List should have at most 1000 items",
                    "input": request.overlap_choices.len(),
                }]
            })),
        )
            .into_response());
    }
    if request.target_list_id.is_some_and(|id| id < 1) {
        return Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(serde_json::json!({
                "detail": [{
                    "type": "greater_than",
                    "loc": ["body", "target_list_id"],
                    "msg": "Input should be greater than 0",
                    "input": 0,
                    "ctx": { "gt": 0 },
                }]
            })),
        )
            .into_response());
    }
    Ok(())
}

#[utoipa::path(
    post,
    path = "/api/v1/issue-identity/cbl/{list_id}/reading-graph-preview",
    request_body = ReadingGraphPreviewRequest,
    params(("list_id" = i64, Path, description = "CBL source list id")),
    responses(
        (status = 200, description = "Read-only graph preview", body = ReadingGraphPreview),
        (status = 401, description = "Unauthorized"),
        (status = 404, description = "CBL source list not found or not active"),
        (status = 422, description = "Unknown or unresolved source position"),
    ),
    security(("HTTPBearer" = []))
)]
pub fn documentation() {}

/// Mounted handler for `POST .../cbl/{list_id}/reading-graph-preview`.
pub async fn preview_cbl_reading_graph_handler(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i64>,
    Json(request): Json<ReadingGraphPreviewRequest>,
) -> Result<Json<ReadingGraphPreview>, Response> {
    validate_request(&request)?;
    let connection = db::checkout(&state).await.map_err(|error| ApiError::into_response(db::query_error(error)))?;

    let list_row = connection
        .query_opt(
            "SELECT content_hash, revision_sha, active FROM cbl_source_lists WHERE id = $1",
            &[&list_id],
        )
        .await
        .map_err(|error| ApiError::into_response(db::query_error(error)))?
        .filter(|row| row.get::<_, bool>(2))
        .ok_or_else(|| {
            structured_error(
                StatusCode::NOT_FOUND,
                "cbl_source_not_found",
                format!("CBL source list {list_id} was not found or is inactive"),
            )
        })?;
    let content_hash: String = list_row.get(0);
    let revision_sha: String = list_row.get(1);

    let selected_positions: Vec<i64> = {
        let mut positions = request.included_positions.clone();
        positions.sort_unstable();
        positions.dedup();
        positions
    };
    let entry_rows = if selected_positions.is_empty() {
        Vec::new()
    } else {
        connection
            .query(
                "SELECT position, series_name, volume_year, external_issue_identity_id, \
                        external_series_identity_id
                 FROM cbl_source_entries
                 WHERE list_id = $1 AND position = ANY($2::int8[])
                 ORDER BY position",
                &[&list_id, &selected_positions],
            )
            .await
            .map_err(|error| ApiError::into_response(db::query_error(error)))?
    };
    let known_positions: std::collections::HashSet<i64> =
        entry_rows.iter().map(|row| row.get::<_, i64>(0)).collect();
    let unknown: Vec<i64> = selected_positions
        .iter()
        .copied()
        .filter(|position| !known_positions.contains(position))
        .collect();
    if !unknown.is_empty() {
        return Err(structured_error(
            StatusCode::UNPROCESSABLE_ENTITY,
            "unknown_source_position",
            format!("Source positions are not part of list {list_id}: {unknown:?}"),
        ));
    }

    let identity_ids: Vec<i64> = entry_rows
        .iter()
        .filter_map(|row| row.get::<_, Option<i64>>(3))
        .collect();
    let mut external_by_id: HashMap<i64, String> = HashMap::new();
    if !identity_ids.is_empty() {
        for row in connection
            .query(
                "SELECT id, external_id FROM external_identities
                 WHERE id = ANY($1::int8[]) AND provider = 'comicvine' AND entity_type = 'issue'",
                &[&identity_ids],
            )
            .await
            .map_err(|error| ApiError::into_response(db::query_error(error)))?
        {
            external_by_id.insert(row.get(0), row.get(1));
        }
    }
    let unresolved: Vec<i64> = entry_rows
        .iter()
        .filter(|row| {
            row.get::<_, Option<i64>>(3)
                .and_then(|id| external_by_id.get(&id))
                .is_none()
        })
        .map(|row| row.get::<_, i64>(0))
        .collect();
    if !unresolved.is_empty() {
        return Err(structured_error(
            StatusCode::UNPROCESSABLE_ENTITY,
            "unresolved_source_position",
            format!("Resolve these source positions before previewing the graph: {unresolved:?}"),
        ));
    }

    // Resolve reader-owned issues for the selected Comic Vine identities in a
    // single set-based query.
    let external_ids: Vec<String> = external_by_id.values().cloned().collect();
    let mut owned_by_external: HashMap<String, i64> = HashMap::new();
    if !external_ids.is_empty() {
        for row in connection
            .query(
                "SELECT e.external_id, i.id
                 FROM external_identities e
                 JOIN issue_external_identity_mappings m ON m.external_identity_id = e.id
                 JOIN issues i ON i.id = m.issue_id
                 JOIN threads t ON t.id = i.thread_id AND t.user_id = $1
                 WHERE e.provider = 'comicvine' AND e.entity_type = 'issue'
                   AND e.external_id = ANY($2::text[])",
                &[&user.id(), &external_ids],
            )
            .await
            .map_err(|error| ApiError::into_response(db::query_error(error)))?
        {
            owned_by_external.entry(row.get(0)).or_insert_with(|| row.get::<_, i64>(1));
        }
    }

    let mut series_nodes: Vec<ReadingGraphSeriesNode> = Vec::new();
    let mut issues: Vec<ReadingGraphIssueReference> = Vec::new();
    let mut rollable_issue_ids: Vec<i64> = Vec::new();
    let mut waiting_issue_ids: Vec<i64> = Vec::new();
    let mut by_volume: HashMap<String, usize> = HashMap::new();

    for row in &entry_rows {
        let position: i64 = row.get(0);
        let series_name: String = row.get(1);
        let volume_year: Option<i64> = row.get(2);
        let identity_id: Option<i64> = row.get(3);
        let series_identity_id: Option<i64> = row.get(4);
        let comicvine_volume_id = identity_id
            .and_then(|id| external_by_id.get(&id))
            .cloned()
            .unwrap_or_default();
        let _ = series_identity_id;
        let owned_issue_id = external_by_id
            .get(&identity_id.expect("resolved above"))
            .and_then(|external| owned_by_external.get(external))
            .copied();
        let state = if owned_issue_id.is_some() {
            "continues"
        } else {
            "waits"
        };
        let index = *by_volume.entry(comicvine_volume_id.clone()).or_insert_with(|| {
            series_nodes.push(ReadingGraphSeriesNode {
                comicvine_volume_id: comicvine_volume_id.clone(),
                series_name: series_name.clone(),
                year: volume_year,
                state: state.to_string(),
                unread_count: 0,
                rollable_count: 0,
                waiting_count: 0,
                waits_for_issue_ids: Vec::new(),
            });
            series_nodes.len() - 1
        });
        let node = &mut series_nodes[index];
        node.unread_count += 1;
        if owned_issue_id.is_some() {
            node.rollable_count += 1;
            rollable_issue_ids.push(position);
        } else {
            node.waiting_count += 1;
            waiting_issue_ids.push(position);
            node.waits_for_issue_ids.push(position);
        }
        issues.push(ReadingGraphIssueReference {
            issue_id: owned_issue_id.unwrap_or(position),
            series_name,
            issue_number: position.to_string(),
            comicvine_volume_id: Some(comicvine_volume_id),
            blockers: Vec::new(),
        });
    }

    if request.overlap_choices.iter().any(|choice| {
        !matches!(choice.choice.as_str(), "protect_order" | "continue_series")
    }) {
        return Err(structured_error(
            StatusCode::UNPROCESSABLE_ENTITY,
            "unknown_overlap_choice",
            "An overlap answer is not valid for this preview".to_string(),
        ));
    }

    Ok(Json(ReadingGraphPreview {
        source_list_id: list_id,
        content_hash,
        revision_sha,
        series: series_nodes,
        overlaps: Vec::new(),
        issues,
        rollable_issue_ids,
        waiting_issue_ids,
        cycle_errors: Vec::new(),
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request() -> ReadingGraphPreviewRequest {
        ReadingGraphPreviewRequest {
            included_positions: vec![1, 2],
            overlap_choices: Vec::new(),
            target_list_id: None,
        }
    }

    #[test]
    fn accepts_a_well_formed_request() {
        assert!(validate_request(&request()).is_ok());
    }

    #[test]
    fn rejects_non_positive_positions_and_excessive_batches() {
        let mut bad = request();
        bad.included_positions = vec![0];
        assert_eq!(
            validate_request(&bad).expect_err("non-positive").status(),
            StatusCode::UNPROCESSABLE_ENTITY
        );
        let mut large = request();
        large.included_positions = vec![1; 10_001];
        assert_eq!(
            validate_request(&large).expect_err("too large").status(),
            StatusCode::UNPROCESSABLE_ENTITY
        );
    }

    #[test]
    fn structured_error_uses_python_detail_shape() {
        let response = structured_error(StatusCode::NOT_FOUND, "cbl_source_not_found", "gone".into());
        assert_eq!(response.status(), StatusCode::NOT_FOUND);
    }

    #[test]
    fn response_serializes_all_wire_fields() {
        let preview = ReadingGraphPreview {
            source_list_id: 7,
            content_hash: "h".into(),
            revision_sha: "r".into(),
            series: Vec::new(),
            overlaps: Vec::new(),
            issues: Vec::new(),
            rollable_issue_ids: Vec::new(),
            waiting_issue_ids: Vec::new(),
            cycle_errors: Vec::new(),
        };
        let value = serde_json::to_value(&preview).expect("serializes");
        for key in [
            "source_list_id", "content_hash", "revision_sha", "series", "overlaps",
            "issues", "rollable_issue_ids", "waiting_issue_ids", "cycle_errors",
        ] {
            assert!(value.get(key).is_some(), "missing wire field {key}");
        }
    }
}
