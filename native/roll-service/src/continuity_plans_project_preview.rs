//! Same-path Rust cutover of
//! `POST /api/v1/continuity-plans/{plan_id}/reading-orders/project-preview`.
//!
//! Port of `app/services/reading_order_projection.py::build_projection_plan`
//! plus `preview_to_response`. The preview is recomputed from persisted plan
//! JSON on every call and never mutates the plan or reading order.

use crate::{
    auth::AuthenticatedUser,
    db,
    preview_validation::{parse_body_object, parse_path_int, required_int, validation_failed},
    ApiError, AppState,
};
use axum::{
    body::Bytes,
    extract::{rejection::PathRejection, Path, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{collections::HashMap, sync::Arc};
use utoipa::ToSchema;

/// Small response error used instead of returning a large Axum `Response` from
/// helpers (see `clippy::result_large_err`).
#[derive(Debug)]
pub enum PreviewError {
    Api(ApiError),
    Json(StatusCode, Value),
}

impl PreviewError {
    #[cfg(test)]
    fn status(&self) -> StatusCode {
        match self {
            Self::Api(error) => error.status(),
            Self::Json(status, _) => *status,
        }
    }
}

impl From<ApiError> for PreviewError {
    fn from(error: ApiError) -> Self {
        Self::Api(error)
    }
}

impl IntoResponse for PreviewError {
    fn into_response(self) -> Response {
        match self {
            Self::Api(error) => error.into_response(),
            Self::Json(status, body) => (status, Json(body)).into_response(),
        }
    }
}

#[derive(Debug, Deserialize, ToSchema)]
pub struct ReadingOrderProjectPreviewRequest {
    pub reading_order_id: i64,
}

/// Parse the body like `ReadingOrderProjectPreviewRequest` (`reading_order_id: int > 0`).
/// Any rejection is the production `{"detail": "Validation failed"}` 422.
fn parse_request(body: &[u8]) -> Result<ReadingOrderProjectPreviewRequest, ApiError> {
    let map = parse_body_object(body)?;
    let reading_order_id = required_int(&map, "reading_order_id")?;
    if reading_order_id < 1 {
        return Err(validation_failed());
    }
    Ok(ReadingOrderProjectPreviewRequest { reading_order_id })
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingOrderProjectPreviewResponse {
    pub plan_id: i64,
    pub plan_name: String,
    pub plan_ordering_mode: String,
    pub reading_order_id: i64,
    pub reading_order_name: String,
    pub entries: Vec<ReadingOrderProjectPreviewEntry>,
    pub conflicts: Vec<ReadingOrderProjectPreviewConflict>,
    pub total_positions: i64,
    pub dropped_node_ids: Vec<String>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingOrderProjectPreviewEntry {
    pub thread_id: i64,
    pub thread_title: Option<String>,
    pub position: i64,
    pub source: String,
    pub source_node_id: Option<String>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingOrderProjectPreviewConflict {
    pub code: String,
    pub message: String,
    pub node_id: String,
    pub thread_id: Option<i64>,
    pub existing_positions: Vec<i64>,
}

#[derive(Debug, Clone)]
struct Node {
    id: String,
    node_type: String,
    ref_id: i64,
    lane_id: String,
    position: i64,
}

fn not_found(detail: String) -> PreviewError {
    PreviewError::Api(ApiError::NotFound(detail))
}

fn conflict_detail(detail: Value) -> PreviewError {
    PreviewError::Json(
        StatusCode::CONFLICT,
        serde_json::json!({ "detail": detail }),
    )
}

/// Parse persisted nodes with the Pydantic field constraints used by Python.
fn parse_nodes(nodes: &Value, plan_id: i64) -> Result<Vec<Node>, PreviewError> {
    let malformed = |reason: &str| {
        conflict_detail(serde_json::json!({
            "code": "malformed_plan", "plan_id": plan_id, "reason": reason
        }))
    };
    let Some(items) = nodes.as_array() else {
        return Err(malformed("nodes_json is not an array"));
    };
    let mut parsed = Vec::with_capacity(items.len());
    for item in items {
        let (Some(id), Some(node_type), Some(ref_id), Some(lane_id), Some(position)) = (
            item.get("id").and_then(Value::as_str),
            item.get("node_type").and_then(Value::as_str),
            item.get("ref_id").and_then(Value::as_i64),
            item.get("lane_id").and_then(Value::as_str),
            item.get("position").and_then(Value::as_i64),
        ) else {
            return Err(malformed("node failed ContinuityPlanNode validation"));
        };
        // Python `ContinuityPlanNode` (and `ContinuityPlanWrite::validate_structure`)
        // constrain these fields by characters, not UTF-8 bytes.
        if id.is_empty()
            || id.chars().count() > 80
            || node_type.is_empty()
            || ref_id < 1
            || lane_id.is_empty()
            || lane_id.chars().count() > 80
            || position < 0
        {
            return Err(malformed("node failed ContinuityPlanNode validation"));
        }
        parsed.push(Node {
            id: id.to_string(),
            node_type: node_type.to_string(),
            ref_id,
            lane_id: lane_id.to_string(),
            position,
        });
    }
    Ok(parsed)
}

/// Apply Python's deterministic flattening policy.
fn flatten(
    nodes: Vec<Node>,
    ordering_mode: &str,
    lanes: &Value,
    plan_id: i64,
) -> Result<(Vec<Node>, Vec<String>), PreviewError> {
    let lane_ids: Vec<String> = lanes
        .as_array()
        .map(|items| {
            items
                .iter()
                .filter_map(|lane| lane.get("id").and_then(Value::as_str).map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    let lane_orders: HashMap<String, i64> = lanes
        .as_array()
        .map(|items| {
            items
                .iter()
                .filter_map(|lane| {
                    let id = lane.get("id").and_then(Value::as_str)?;
                    let order = lane
                        .get("order")
                        .and_then(Value::as_i64)
                        .unwrap_or_default();
                    Some((id.to_string(), order))
                })
                .collect()
        })
        .unwrap_or_default();
    let mut ordered = nodes;
    if ordering_mode == "strict_sequential" {
        // The empty plan (0 lanes, 0 steps) is a valid strict plan (#5614);
        // it projects as an empty sequence, so only more than one lane is
        // malformed.
        if lane_ids.len() > 1 {
            return Err(conflict_detail(serde_json::json!({
                "code": "malformed_plan", "plan_id": plan_id,
                "reason": "strict sequential plans must use exactly one lane"
            })));
        }
        if let Some(lane) = lane_ids.first() {
            if ordered.iter().any(|node| &node.lane_id != lane) {
                return Err(conflict_detail(serde_json::json!({
                    "code": "malformed_plan", "plan_id": plan_id,
                    "reason": "strict sequential plans must have all nodes in single lane"
                })));
            }
            let mut positions: Vec<i64> = ordered.iter().map(|node| node.position).collect();
            positions.sort_unstable();
            if positions != (0..positions.len() as i64).collect::<Vec<_>>() {
                return Err(conflict_detail(serde_json::json!({
                    "code": "malformed_plan", "plan_id": plan_id,
                    "reason": "strict sequential positions must be contiguous starting at zero"
                })));
            }
            ordered.sort_by_key(|node| node.position);
        }
    } else {
        ordered.sort_by(|a, b| {
            lane_orders
                .get(&a.lane_id)
                .copied()
                .unwrap_or_default()
                .cmp(&lane_orders.get(&b.lane_id).copied().unwrap_or_default())
                .then(a.position.cmp(&b.position))
                .then(a.id.cmp(&b.id))
        });
    }
    let dropped = ordered
        .iter()
        .filter(|node| !lane_ids.contains(&node.lane_id))
        .map(|node| node.id.clone())
        .collect();
    Ok((ordered, dropped))
}

#[utoipa::path(
    post,
    path = "/api/v1/continuity-plans/{plan_id}/reading-orders/project-preview",
    operation_id = "preview_plan_projection_api_v1_continuity_plans__plan_id__reading_orders_project_preview_post",
    request_body = ReadingOrderProjectPreviewRequest,
    params(("plan_id" = i64, Path, description = "Continuity plan id")),
    responses(
        (status = 200, description = "Deterministic projection preview", body = ReadingOrderProjectPreviewResponse),
        (status = 401, description = "Unauthorized"),
        (status = 404, description = "Plan or reading order not found"),
        (status = 409, description = "Malformed plan"),
        (status = 422, description = "Validation failed"),
    ),
    security(("HTTPBearer" = []))
)]
pub fn documentation() {}

/// Mounted handler for `POST .../reading-orders/project-preview`.
pub async fn preview_plan_projection_handler(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    plan_id: Result<Path<String>, PathRejection>,
    body: Bytes,
) -> Result<Json<ReadingOrderProjectPreviewResponse>, PreviewError> {
    let plan_id = parse_path_int(plan_id)?;
    let request = parse_request(&body)?;
    let connection = db::checkout(&state).await?;

    // `continuity_plans.id` and `reading_orders.id` are `integer` columns, so the
    // i64 wire ids must be narrowed before binding. Values outside i32 cannot
    // match any persisted row, so they are the same owner-scoped 404 as a miss.
    let plan_key = i32::try_from(plan_id)
        .map_err(|_| not_found(format!("Continuity plan {plan_id} not found")))?;
    let reading_order_key = i32::try_from(request.reading_order_id).map_err(|_| {
        not_found(format!(
            "Reading order {} not found",
            request.reading_order_id
        ))
    })?;

    let plan_row = connection
        .query_opt(
            "SELECT name, ordering_mode, nodes_json, lanes_json FROM continuity_plans \
             WHERE id = $1 AND user_id = $2",
            &[&plan_key, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| not_found(format!("Continuity plan {plan_id} not found")))?;
    let plan_name: String = plan_row.get(0);
    let ordering_mode: String = plan_row.get(1);
    let nodes_json: Value = plan_row.get(2);
    let lanes_json: Value = plan_row.get(3);

    let order_row = connection
        .query_opt(
            "SELECT name FROM reading_orders WHERE id = $1 AND user_id = $2",
            &[&reading_order_key, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| {
            not_found(format!(
                "Reading order {} not found",
                request.reading_order_id
            ))
        })?;
    let reading_order_name: String = order_row.get(0);

    let parsed = parse_nodes(&nodes_json, plan_id)?;
    let (ordered_nodes, dropped_node_ids) = flatten(parsed, &ordering_mode, &lanes_json, plan_id)?;

    let thread_ids: Vec<i64> = ordered_nodes
        .iter()
        .filter(|node| node.node_type == "thread")
        .map(|node| node.ref_id)
        .collect();
    let mut thread_titles: HashMap<i64, Option<String>> = HashMap::new();
    if !thread_ids.is_empty() {
        let rows = connection
            .query(
                "SELECT id, title FROM threads WHERE user_id = $1 AND id = ANY($2::int8[])",
                &[&user.id(), &thread_ids],
            )
            .await
            .map_err(db::query_error)?;
        for row in rows {
            thread_titles.insert(i64::from(row.get::<_, i32>(0)), row.get(1));
        }
    }

    let existing_rows = connection
        .query(
            "SELECT thread_id, position FROM reading_order_items WHERE reading_order_id = $1",
            &[&reading_order_key],
        )
        .await
        .map_err(db::query_error)?;
    let mut existing_positions: HashMap<i64, i64> = HashMap::new();
    for row in &existing_rows {
        existing_positions.insert(
            i64::from(row.get::<_, i32>(0)),
            i64::from(row.get::<_, i32>(1)),
        );
    }

    let mut conflicts = Vec::new();
    let mut seen: std::collections::HashSet<i64> = std::collections::HashSet::new();
    let mut thread_positions: HashMap<i64, Vec<i64>> = HashMap::new();
    for node in &ordered_nodes {
        if node.node_type != "thread" {
            conflicts.push(ReadingOrderProjectPreviewConflict {
                code: "non_thread_node".to_string(),
                message: format!(
                    "Reading order projection only supports thread nodes; {} node {:?} cannot be projected.",
                    node.node_type, node.id
                ),
                node_id: node.id.clone(),
                thread_id: Some(node.ref_id),
                existing_positions: Vec::new(),
            });
            continue;
        }
        if thread_titles.contains_key(&node.ref_id) {
            thread_positions
                .entry(node.ref_id)
                .or_default()
                .push(node.position);
            if !seen.insert(node.ref_id) {
                let mut positions = thread_positions[&node.ref_id].clone();
                positions.sort_unstable();
                conflicts.push(ReadingOrderProjectPreviewConflict {
                    code: "duplicate_thread".to_string(),
                    message: format!(
                        "Thread {} appears multiple times in the plan; deduplicate node positions before projection.",
                        node.ref_id
                    ),
                    node_id: node.id.clone(),
                    thread_id: Some(node.ref_id),
                    existing_positions: positions,
                });
            }
        } else {
            conflicts.push(ReadingOrderProjectPreviewConflict {
                code: "missing_thread".to_string(),
                message: format!(
                    "Thread {} from node {:?} is not owned by the user.",
                    node.ref_id, node.id
                ),
                node_id: node.id.clone(),
                thread_id: Some(node.ref_id),
                existing_positions: Vec::new(),
            });
        }
    }

    let (entries, total_positions) = if conflicts.is_empty() {
        let mut entries = Vec::new();
        let mut position = 1i64;
        for node in &ordered_nodes {
            if node.node_type != "thread" || !thread_titles.contains_key(&node.ref_id) {
                continue;
            }
            let source = match existing_positions.get(&node.ref_id) {
                None => "added",
                Some(prior) if *prior != position => "updated",
                Some(_) => "existing",
            };
            entries.push(ReadingOrderProjectPreviewEntry {
                thread_id: node.ref_id,
                thread_title: thread_titles.get(&node.ref_id).and_then(Clone::clone),
                position,
                source: source.to_string(),
                source_node_id: Some(node.id.clone()),
            });
            position += 1;
        }
        let total = entries.len().max(existing_rows.len()) as i64;
        (entries, total)
    } else {
        (Vec::new(), existing_rows.len() as i64)
    };

    Ok(Json(ReadingOrderProjectPreviewResponse {
        plan_id,
        plan_name,
        plan_ordering_mode: ordering_mode,
        reading_order_id: request.reading_order_id,
        reading_order_name,
        entries,
        conflicts,
        total_positions,
        dropped_node_ids,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// `continuity_plans` registers `ReadingOrderProjectionRequest` with
    /// `deny_unknown_fields` and i32 ids. Reusing those names would publish that
    /// incompatible schema for this preview instead of this handler's i64,
    /// extra-field-tolerant Python-parity contract (#5342 review).
    #[test]
    fn published_preview_schema_uses_distinct_names_and_wire_types() {
        let document =
            serde_json::to_value(crate::same_path_openapi::same_path_openapi()).expect("OpenAPI");
        let operation = &document["paths"]
            ["/api/v1/continuity-plans/{plan_id}/reading-orders/project-preview"]["post"];
        assert_eq!(
            operation["requestBody"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/ReadingOrderProjectPreviewRequest"
        );
        assert_eq!(
            operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/ReadingOrderProjectPreviewResponse"
        );
        let request = &document["components"]["schemas"]["ReadingOrderProjectPreviewRequest"];
        assert_eq!(request["properties"]["reading_order_id"]["format"], "int64");
        assert!(request.get("additionalProperties").is_none());
        // The commit endpoint keeps its own, incompatible schema.
        assert!(document["components"]["schemas"]
            .get("ReadingOrderProjectionRequest")
            .is_some());
    }

    #[test]
    fn request_requires_positive_reading_order_id() {
        assert_eq!(
            parse_request(br#"{"reading_order_id": 3}"#)
                .expect("valid")
                .reading_order_id,
            3
        );
        for body in [
            &br#"{"reading_order_id": 0}"#[..],
            br#"{}"#,
            br#"{"reading_order_id": "x"}"#,
            b"[]",
            b"",
        ] {
            let error = parse_request(body).expect_err("invalid");
            assert_eq!(error.detail(), "Validation failed");
        }
    }

    /// Pydantic's `max_length=80` counts characters, not UTF-8 bytes; a plan
    /// with 30 Chinese characters is valid and must not 409 in this preview.
    #[test]
    fn multibyte_node_and_lane_ids_are_measured_in_characters() {
        let wide = "节".repeat(30);
        assert!(wide.len() > 80 && wide.chars().count() == 30);
        let nodes = serde_json::json!([
            {"id": wide, "node_type": "thread", "ref_id": 10, "lane_id": wide, "position": 0}
        ]);
        let parsed = parse_nodes(&nodes, 5).expect("30-character ids are valid");
        assert_eq!(parsed[0].id, wide);

        let too_long = "节".repeat(81);
        let nodes = serde_json::json!([
            {"id": too_long, "node_type": "thread", "ref_id": 10, "lane_id": "a", "position": 0}
        ]);
        assert!(parse_nodes(&nodes, 5).is_err());
    }

    #[test]
    fn parses_and_flattens_informational_lane_order() {
        let nodes = serde_json::json!([
            {"id":"n1","node_type":"thread","ref_id":10,"lane_id":"b","position":0},
            {"id":"n2","node_type":"thread","ref_id":11,"lane_id":"a","position":1},
            {"id":"n3","node_type":"series","ref_id":12,"lane_id":"a","position":0}
        ]);
        let lanes = serde_json::json!([
            {"id":"a","order":0},{"id":"b","order":1}
        ]);
        let parsed = parse_nodes(&nodes, 5).expect("nodes");
        let (ordered, dropped) = flatten(parsed, "informational", &lanes, 5).expect("flatten");
        assert_eq!(
            ordered.iter().map(|n| n.id.as_str()).collect::<Vec<_>>(),
            vec!["n3", "n2", "n1"]
        );
        assert!(dropped.is_empty());
    }

    #[test]
    fn drops_nodes_from_unknown_lanes() {
        let nodes = serde_json::json!([
            {"id":"n1","node_type":"thread","ref_id":10,"lane_id":"ghost","position":0}
        ]);
        let parsed = parse_nodes(&nodes, 5).expect("nodes");
        let (_, dropped) =
            flatten(parsed, "informational", &serde_json::json!([]), 5).expect("flatten");
        assert_eq!(dropped, vec!["n1"]);
    }

    /// Database-backed exercise of the mounted read-only preview. A missing
    /// plan must return the owner-scoped 404 without touching any row.
    #[tokio::test]
    async fn preview_plan_projection_read_only_handler_reaches_the_database() {
        let state = crate::test_support::test_state(1)
            .await
            .expect("disposable PostgreSQL required");
        let _guard = crate::test_support::reset_for_test(&state).await;
        let error = preview_plan_projection_handler(
            State(state),
            crate::auth::AuthenticatedUser::for_test(9_001),
            Ok(Path("9001001".to_string())),
            Bytes::from_static(br#"{"reading_order_id": 9001001}"#),
        )
        .await
        .expect_err("missing plan is a 404");
        assert_eq!(error.status(), StatusCode::NOT_FOUND);
    }

    /// An i64 path/body id beyond the int4 primary-key domain cannot match a
    /// row. It must narrow to the same 404 as a missing plan instead of binding
    /// an i64 to an integer column and surfacing a 500 (WrongType).
    #[tokio::test]
    async fn out_of_range_ids_are_not_found_not_internal_errors() {
        let state = crate::test_support::test_state(1)
            .await
            .expect("disposable PostgreSQL required");
        let _guard = crate::test_support::reset_for_test(&state).await;
        let beyond_int4 = i64::from(i32::MAX) + 1;
        let error = preview_plan_projection_handler(
            State(state.clone()),
            crate::auth::AuthenticatedUser::for_test(9_001),
            Ok(Path(beyond_int4.to_string())),
            Bytes::from(format!(r#"{{"reading_order_id": {beyond_int4}}}"#)),
        )
        .await
        .expect_err("out-of-range plan is a 404");
        assert_eq!(error.status(), StatusCode::NOT_FOUND);

        // A valid plan id with an out-of-range reading order id also narrows
        // cleanly instead of failing to bind the reading-order integer column.
        let error = preview_plan_projection_handler(
            State(state),
            crate::auth::AuthenticatedUser::for_test(9_001),
            Ok(Path("9001001".to_string())),
            Bytes::from(format!(r#"{{"reading_order_id": {beyond_int4}}}"#)),
        )
        .await
        .expect_err("out-of-range reading order is a 404");
        assert_eq!(error.status(), StatusCode::NOT_FOUND);
    }

    #[test]
    fn strict_sequential_rejects_non_contiguous_positions() {
        let nodes = serde_json::json!([
            {"id":"n1","node_type":"thread","ref_id":10,"lane_id":"a","position":0},
            {"id":"n2","node_type":"thread","ref_id":11,"lane_id":"a","position":2}
        ]);
        let parsed = parse_nodes(&nodes, 5).expect("nodes");
        let lanes = serde_json::json!([{"id":"a","order":0}]);
        let result = flatten(parsed, "strict_sequential", &lanes, 5);
        assert_eq!(
            result.expect_err("non-contiguous").status(),
            StatusCode::CONFLICT
        );
    }
}
