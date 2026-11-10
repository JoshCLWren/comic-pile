//! Same-path Rust cutover for the browser-called reading-order projection preview (#4842).
//!
//! Preserves the Python `app/api/reading_order_projection.py` +
//! `app/services/reading_order_projection.py` wire contract at
//! `POST /api/v1/continuity-plans/{plan_id}/reading-orders/project-preview`.
//! Only the read-only preview moves in this slice; the confirm operation and its
//! Python implementation stay mounted until their own cutover.
//!
//! Parity notes (Python oracle):
//! - The owned plan and owned reading order are loaded with the owner predicate
//!   in the query; a foreign identifier is a 404 with the Python detail text.
//! - Persisted plan nodes are revalidated on every call. Malformed JSON is a
//!   `409 {detail: {code: "malformed_plan", ...}}`, never a 500.
//! - Informational plans flatten by (lane order, node position, node id);
//!   nodes whose lane is absent are reported in `dropped_node_ids`.
//! - Strict sequential plans must have exactly one lane, every node in that
//!   lane, and positions contiguous from zero; otherwise the plan is malformed.
//! - Conflicts are computed before any entry: non-thread nodes, duplicate owned
//!   threads, and unowned threads. Any conflict empties `entries` and sets
//!   `total_positions` to the existing order size.
//! - With no conflicts, entries are sequentially positioned from 1 and tagged
//!   `added`, `updated`, or `existing` against the current reading-order rows.
#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    response::{IntoResponse, Response},
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    cmp::Ordering,
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};

/// Request contract shared with the Python preview endpoint.
#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ReadingOrderProjectionRequest {
    #[schema(value_type = i32, minimum = 1)]
    pub reading_order_id: i64,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingOrderProjectionEntry {
    pub thread_id: i32,
    pub thread_title: Option<String>,
    pub position: i32,
    pub source: String,
    pub source_node_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingOrderProjectionConflict {
    pub code: String,
    pub message: String,
    pub node_id: String,
    pub thread_id: Option<i32>,
    pub existing_positions: Vec<i32>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingOrderProjectionPreview {
    pub plan_id: i32,
    pub plan_name: String,
    pub plan_ordering_mode: String,
    pub reading_order_id: i32,
    pub reading_order_name: String,
    pub entries: Vec<ReadingOrderProjectionEntry>,
    pub conflicts: Vec<ReadingOrderProjectionConflict>,
    pub total_positions: i32,
    pub dropped_node_ids: Vec<String>,
}

#[derive(Debug, Clone, Deserialize)]
struct PlanNode {
    id: String,
    node_type: String,
    ref_id: i32,
    lane_id: String,
    position: i32,
}

#[derive(Debug, Clone, Deserialize)]
struct PlanLane {
    id: String,
    #[serde(default)]
    order: i32,
}

#[derive(Debug, Clone, Deserialize)]
struct PlanDocument {
    ordering_mode: String,
    nodes: Vec<PlanNode>,
    lanes: Vec<PlanLane>,
}

struct OwnedPlan {
    id: i32,
    name: String,
    ordering_mode: String,
    nodes_json: String,
    lanes_json: String,
}

struct OwnedOrder {
    id: i32,
    name: String,
}

fn not_found(detail: String) -> Response {
    ApiError::NotFound(detail).into_response()
}

fn structured_conflict(body: Value) -> Response {
    (
        axum::http::StatusCode::CONFLICT,
        Json(serde_json::json!({ "detail": body })),
    )
        .into_response()
}

fn malformed_plan(plan_id: i32, reason: impl Into<String>) -> Response {
    structured_conflict(serde_json::json!({
        "code": "malformed_plan",
        "plan_id": plan_id,
        "reason": reason.into(),
    }))
}

fn parse_json_array(raw: &str, what: &str) -> Result<Vec<Value>, String> {
    let value: Value =
        serde_json::from_str(raw).map_err(|_| format!("{what} must be a JSON array"))?;
    match value {
        Value::Array(values) => Ok(values),
        _ => Err(format!("{what} must be a JSON array")),
    }
}

fn parse_plan(plan: &OwnedPlan) -> Result<PlanDocument, String> {
    let lanes_raw = parse_json_array(&plan.lanes_json, "lanes_json")?;
    let nodes_raw = parse_json_array(&plan.nodes_json, "nodes_json")?;

    let mut lanes = Vec::with_capacity(lanes_raw.len());
    for value in lanes_raw {
        let id = value
            .get("id")
            .and_then(Value::as_str)
            .filter(|id| !id.is_empty() && id.len() <= 80)
            .ok_or_else(|| "lane id must be a non-empty string".to_string())?
            .to_string();
        let order = value
            .get("order")
            .and_then(Value::as_i64)
            .and_then(|order| i32::try_from(order).ok())
            .filter(|order| *order >= 0)
            .ok_or_else(|| "lane order must be a non-negative integer".to_string())?;
        lanes.push(PlanLane { id, order });
    }

    let mut nodes = Vec::with_capacity(nodes_raw.len());
    for value in nodes_raw {
        let id = value
            .get("id")
            .and_then(Value::as_str)
            .filter(|id| !id.is_empty() && id.len() <= 80)
            .ok_or_else(|| "node id must be a non-empty string".to_string())?
            .to_string();
        let node_type = value
            .get("node_type")
            .and_then(Value::as_str)
            .filter(|kind| matches!(*kind, "issue" | "crossover" | "thread"))
            .ok_or_else(|| "node_type must be issue, crossover, or thread".to_string())?
            .to_string();
        let ref_id = value
            .get("ref_id")
            .and_then(Value::as_i64)
            .and_then(|id| i32::try_from(id).ok())
            .filter(|id| *id > 0)
            .ok_or_else(|| "ref_id must be a positive integer".to_string())?;
        let lane_id = value
            .get("lane_id")
            .and_then(Value::as_str)
            .filter(|lane| !lane.is_empty() && lane.len() <= 80)
            .ok_or_else(|| "lane_id must be a non-empty string".to_string())?
            .to_string();
        let position = value
            .get("position")
            .and_then(Value::as_i64)
            .and_then(|position| i32::try_from(position).ok())
            .filter(|position| *position >= 0)
            .ok_or_else(|| "position must be a non-negative integer".to_string())?;
        nodes.push(PlanNode {
            id,
            node_type,
            ref_id,
            lane_id,
            position,
        });
    }

    Ok(PlanDocument {
        ordering_mode: plan.ordering_mode.clone(),
        nodes,
        lanes,
    })
}

fn flatten_plan(
    plan: &PlanDocument,
) -> Result<(Vec<PlanNode>, Vec<String>), String> {
    let lane_ids: BTreeSet<&str> = plan.lanes.iter().map(|lane| lane.id.as_str()).collect();
    let dropped: Vec<String> = plan
        .nodes
        .iter()
        .filter(|node| !lane_ids.contains(node.lane_id.as_str()))
        .map(|node| node.id.clone())
        .collect();

    let mut ordered = plan.nodes.clone();
    if plan.ordering_mode == "strict_sequential" {
        if plan.lanes.len() != 1 {
            return Err("strict sequential plans must use exactly one lane".to_string());
        }
        let single_lane_id = &plan.lanes[0].id;
        let nodes_in_lane: Vec<&PlanNode> = ordered
            .iter()
            .filter(|node| &node.lane_id == single_lane_id)
            .collect();
        if nodes_in_lane.len() != ordered.len() {
            return Err("strict sequential plans must have all nodes in single lane".to_string());
        }
        let mut positions: Vec<i32> = nodes_in_lane.iter().map(|node| node.position).collect();
        positions.sort_unstable();
        let expected: Vec<i32> = (0..positions.len() as i32).collect();
        if positions != expected {
            return Err(
                "strict sequential positions must be contiguous starting at zero".to_string(),
            );
        }
        ordered.sort_by_key(|node| node.position);
    } else {
        let lane_orders: BTreeMap<&str, i32> =
            plan.lanes.iter().map(|lane| (lane.id.as_str(), lane.order)).collect();
        ordered.sort_by(|left, right| {
            let left_lane = lane_orders.get(left.lane_id.as_str()).copied().unwrap_or(0);
            let right_lane = lane_orders.get(right.lane_id.as_str()).copied().unwrap_or(0);
            left_lane
                .cmp(&right_lane)
                .then(left.position.cmp(&right.position))
                .then_with(|| left.id.cmp(&right.id))
        });
    }

    Ok((ordered, dropped))
}

fn entry_source(prior: Option<i32>, position: i32) -> &'static str {
    match prior {
        None => "added",
        Some(prior) if prior != position => "updated",
        Some(_) => "existing",
    }
}

/// `POST /api/v1/continuity-plans/{plan_id}/reading-orders/project-preview`.
pub async fn preview_plan_projection(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
    Json(payload): Json<ReadingOrderProjectionRequest>,
) -> Response {
    match build_preview(&state, user.id(), plan_id, payload.reading_order_id).await {
        Ok(preview) => Json(preview).into_response(),
        Err(response) => response,
    }
}

async fn build_preview(
    state: &AppState,
    user_id: i32,
    plan_id: i32,
    reading_order_id: i64,
) -> Result<ReadingOrderProjectionPreview, Response> {
    let connection = db::checkout(state)
        .await
        .map_err(IntoResponse::into_response)?;

    let reading_order_id = i32::try_from(reading_order_id)
        .map_err(|_| not_found("Reading order not found".to_string()))?;

    let plan_row = connection
        .query_opt(
            "SELECT id, name, ordering_mode, COALESCE(nodes_json::text, '[]'), \
                    COALESCE(lanes_json::text, '[]') \
             FROM continuity_plans WHERE id=$1 AND user_id=$2",
            &[&plan_id, &user_id],
        )
        .await
        .map_err(db::query_error)
        .map_err(IntoResponse::into_response)?
        .ok_or_else(|| not_found(format!("Continuity plan {plan_id} not found")))?;

    let plan = OwnedPlan {
        id: plan_row.get(0),
        name: plan_row.get(1),
        ordering_mode: plan_row.get(2),
        nodes_json: plan_row.get(3),
        lanes_json: plan_row.get(4),
    };

    let order_row = connection
        .query_opt(
            "SELECT id, name FROM reading_orders WHERE id=$1 AND user_id=$2",
            &[&reading_order_id, &user_id],
        )
        .await
        .map_err(db::query_error)
        .map_err(IntoResponse::into_response)?
        .ok_or_else(|| not_found(format!("Reading order {reading_order_id} not found")))?;

    let order = OwnedOrder {
        id: order_row.get(0),
        name: order_row.get(1),
    };

    let document = parse_plan(&plan).map_err(|reason| malformed_plan(plan.id, reason))?;
    let (ordered_nodes, dropped_node_ids) = flatten_plan(&document)
        .map_err(|reason| malformed_plan(plan.id, reason))?;

    let thread_ids: Vec<i32> = ordered_nodes
        .iter()
        .filter(|node| node.node_type == "thread")
        .map(|node| node.ref_id)
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let mut thread_titles: BTreeMap<i32, String> = BTreeMap::new();
    if !thread_ids.is_empty() {
        let rows = connection
            .query(
                "SELECT id, title FROM threads WHERE id = ANY($1) AND user_id=$2",
                &[&thread_ids, &user_id],
            )
            .await
            .map_err(db::query_error)
            .map_err(IntoResponse::into_response)?;
        for row in rows {
            thread_titles.insert(row.get(0), row.get(1));
        }
    }

    let existing_rows = connection
        .query(
            "SELECT thread_id, position FROM reading_order_items WHERE reading_order_id=$1",
            &[&order.id],
        )
        .await
        .map_err(db::query_error)
        .map_err(IntoResponse::into_response)?;
    let mut existing_positions: BTreeMap<i32, i32> = BTreeMap::new();
    for row in &existing_rows {
        existing_positions.insert(row.get(0), row.get(1));
    }
    let existing_len = existing_rows.len();

    let mut conflicts: Vec<ReadingOrderProjectionConflict> = Vec::new();
    let mut seen_thread_ids: BTreeSet<i32> = BTreeSet::new();
    let mut thread_positions: BTreeMap<i32, Vec<i32>> = BTreeMap::new();

    for node in &ordered_nodes {
        if node.node_type != "thread" {
            conflicts.push(ReadingOrderProjectionConflict {
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
        let thread_id = node.ref_id;
        if thread_titles.contains_key(&thread_id) {
            thread_positions
                .entry(thread_id)
                .or_default()
                .push(node.position);
            if !seen_thread_ids.insert(thread_id) {
                let mut positions = thread_positions.get(&thread_id).cloned().unwrap_or_default();
                positions.sort_unstable();
                conflicts.push(ReadingOrderProjectionConflict {
                    code: "duplicate_thread".to_string(),
                    message: format!(
                        "Thread {thread_id} appears multiple times in the plan; deduplicate node positions before projection."
                    ),
                    node_id: node.id.clone(),
                    thread_id: Some(thread_id),
                    existing_positions: positions,
                });
                continue;
            }
        } else {
            conflicts.push(ReadingOrderProjectionConflict {
                code: "missing_thread".to_string(),
                message: format!(
                    "Thread {thread_id} from node {:?} is not owned by the user.",
                    node.id
                ),
                node_id: node.id.clone(),
                thread_id: Some(thread_id),
                existing_positions: Vec::new(),
            });
            continue;
        }
    }

    let mut entries: Vec<ReadingOrderProjectionEntry> = Vec::new();
    let total_positions;
    if conflicts.is_empty() {
        let mut position: i32 = 1;
        for node in &ordered_nodes {
            if node.node_type != "thread" || !thread_titles.contains_key(&node.ref_id) {
                continue;
            }
            let thread_id = node.ref_id;
            entries.push(ReadingOrderProjectionEntry {
                thread_id,
                thread_title: thread_titles.get(&thread_id).cloned(),
                position,
                source: entry_source(existing_positions.get(&thread_id).copied(), position)
                    .to_string(),
                source_node_id: Some(node.id.clone()),
            });
            position += 1;
        }
        total_positions = entries.len().max(existing_len) as i32;
    } else {
        entries.clear();
        total_positions = existing_len as i32;
    }

    Ok(ReadingOrderProjectionPreview {
        plan_id: plan.id,
        plan_name: plan.name,
        plan_ordering_mode: plan.ordering_mode,
        reading_order_id: order.id,
        reading_order_name: order.name,
        entries,
        conflicts,
        total_positions,
        dropped_node_ids,
    })
}

/// OpenAPI documentation for the migrated same-path operation.
#[utoipa::path(
    post,
    path = "/api/v1/continuity-plans/{plan_id}/reading-orders/project-preview",
    tag = "reading-orders",
    params(("plan_id" = i32, Path, description = "Continuity plan ID")),
    request_body = ReadingOrderProjectionRequest,
    responses(
        (status = 200, description = "Deterministic projection preview with conflicts", body = ReadingOrderProjectionPreview),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Continuity plan or reading order not found"),
        (status = 409, description = "Malformed persisted plan"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
fn preview_plan_projection_documentation() {}

/// Sort helper exposed for deterministic tests of the flattening policy.
#[cfg(test)]
fn ordered_node_ids(document: &PlanDocument) -> Vec<String> {
    flatten_plan(document)
        .map(|(nodes, _)| nodes.into_iter().map(|node| node.id).collect())
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn node(id: &str, kind: &str, ref_id: i32, lane: &str, position: i32) -> PlanNode {
        PlanNode {
            id: id.to_string(),
            node_type: kind.to_string(),
            ref_id,
            lane_id: lane.to_string(),
            position,
        }
    }

    fn lane(id: &str, order: i32) -> PlanLane {
        PlanLane {
            id: id.to_string(),
            order,
        }
    }

    #[test]
    fn informational_flattening_is_lane_then_position_then_id() {
        let document = PlanDocument {
            ordering_mode: "informational".to_string(),
            lanes: vec![lane("beta", 1), lane("alpha", 0)],
            nodes: vec![
                node("b-first", "thread", 1, "beta", 0),
                node("a-second", "thread", 2, "alpha", 1),
                node("a-first", "thread", 3, "alpha", 0),
                node("a-tie-b", "thread", 4, "alpha", 1),
                node("a-tie-a", "thread", 5, "alpha", 1),
            ],
        };
        assert_eq!(
            ordered_node_ids(&document),
            vec!["a-first", "a-second", "a-tie-a", "a-tie-b", "b-first"]
        );
    }

    #[test]
    fn nodes_in_unknown_lanes_are_dropped_but_preserved_in_order() {
        let document = PlanDocument {
            ordering_mode: "informational".to_string(),
            lanes: vec![lane("main", 0)],
            nodes: vec![
                node("kept", "thread", 1, "main", 0),
                node("dropped", "thread", 2, "ghost", 0),
            ],
        };
        let (ordered, dropped) = flatten_plan(&document).expect("informational plan");
        assert_eq!(ordered.len(), 2);
        assert_eq!(dropped, vec!["dropped"]);
    }

    #[test]
    fn strict_sequential_requires_one_lane_and_contiguous_positions() {
        let good = PlanDocument {
            ordering_mode: "strict_sequential".to_string(),
            lanes: vec![lane("main", 0)],
            nodes: vec![
                node("second", "thread", 2, "main", 1),
                node("first", "thread", 1, "main", 0),
            ],
        };
        assert_eq!(ordered_node_ids(&good), vec!["first", "second"]);

        let two_lanes = PlanDocument {
            ordering_mode: "strict_sequential".to_string(),
            lanes: vec![lane("main", 0), lane("other", 1)],
            nodes: vec![node("first", "thread", 1, "main", 0)],
        };
        assert!(flatten_plan(&two_lanes).is_err());

        let gap = PlanDocument {
            ordering_mode: "strict_sequential".to_string(),
            lanes: vec![lane("main", 0)],
            nodes: vec![node("first", "thread", 1, "main", 1)],
        };
        assert!(flatten_plan(&gap).is_err());
    }

    #[test]
    fn entries_are_tagged_against_current_positions() {
        assert_eq!(entry_source(None, 1), "added");
        assert_eq!(entry_source(Some(4), 1), "updated");
        assert_eq!(entry_source(Some(1), 1), "existing");
    }

    #[test]
    fn malformed_plan_has_structured_conflict_detail() {
        let response = malformed_plan(7, "broken");
        assert_eq!(response.status(), axum::http::StatusCode::CONFLICT);
    }
}
