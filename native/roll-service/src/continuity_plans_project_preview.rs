//! Same-path Rust cutover for continuity-plans project-preview operation.
//
// Moved from `app/api/reading_order_projection.py` `preview_plan_projection` to native Roll
//! (`/api/native_roll.rs` via vercel.json) while preserving HTTP method,
//! exact path, and wire contract. No frontend URL changes.
//
// Parity notes (Python oracle is `app/services/reading_order_projection.py`):
// - Projection is recomputed from the persisted plan JSON on every call so
//   callers always see the current state, even after concurrent edits.
// - Duplicate thread references, missing owned threads, and non-thread
//   nodes are reported as conflicts before any mutation is permitted.
// - The confirm endpoint (`project`) is a separate operation; only the
//   preview is migrated here.

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

/// Request contract matching `app/schemas/reading_order.py` `ReadingOrderProjectionRequest`.
#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ReadingOrderProjectionRequest {
    /// The reading order ID to project into.
    pub reading_order_id: i32,
}

/// Response contract matching `app/schemas/reading_order.py` `ReadingOrderProjectionPreview`.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ReadingOrderProjectionPreview {
    /// Plan ID.
    pub plan_id: i32,
    /// Plan name.
    pub plan_name: String,
    /// Plan ordering mode.
    pub plan_ordering_mode: String,
    /// Reading order ID.
    pub reading_order_id: i32,
    /// Reading order name.
    pub reading_order_name: String,
    /// Projected entries.
    pub entries: Vec<ReadingOrderProjectionEntry>,
    /// Conflicts detected.
    pub conflicts: Vec<ReadingOrderProjectionConflict>,
    /// Total positions.
    pub total_positions: i32,
    /// Dropped node IDs.
    pub dropped_node_ids: Vec<String>,
}

/// One entry in the projected reading order.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ReadingOrderProjectionEntry {
    /// Thread ID.
    pub thread_id: i32,
    /// Thread title, preserved as null when missing.
    pub thread_title: Option<String>,
    /// Position in the reading order.
    pub position: i32,
    /// Source: "existing", "added", or "updated".
    pub source: String,
    /// Source node ID, when applicable.
    pub source_node_id: Option<String>,
}

/// A conflict blocking projection.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ReadingOrderProjectionConflict {
    /// Conflict code: "duplicate_thread", "missing_thread", "non_thread_node".
    pub code: String,
    /// Human-readable message.
    pub message: String,
    /// Node ID involved.
    pub node_id: String,
    /// Thread ID, when applicable.
    pub thread_id: Option<i32>,
    /// Existing positions, when applicable.
    pub existing_positions: Vec<i32>,
}

fn unprocessable(detail: String) -> ApiError {
    ApiError(StatusCode::UNPROCESSABLE_ENTITY, detail)
}

#[axum::async_handler]
pub async fn preview_plan_projection(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
    Json(req): Json<ReadingOrderProjectionRequest>,
) -> Result<Json<ReadingOrderProjectionPreview>, ApiError> {
    let conn = db::checkout(&state)
        .await
        .map_err(|e| unprocessable(format!("DB unavailable: {e}")))?;

    // Load the owned continuity plan. plan_id comes from the path, user_id
    // from auth; both are bound as distinct parameters.
    let rows = conn
        .query(
            "SELECT p.id, p.name, p.ordering_mode FROM continuity_plans p WHERE p.id = $1 AND p.user_id = $2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(|e| unprocessable(format!("Plan load error: {e}")))?;
    let plan_row = rows
        .into_iter()
        .next()
        .ok_or_else(|| unprocessable(format!("Plan {plan_id} not found")))?;
    let plan_name: String = plan_row.get("name");
    let plan_ordering_mode: String = plan_row.get("ordering_mode");

    // Build the projection plan from the plan JSON
    // This mirrors `app/services/reading_order_projection.build_projection_plan`
    let projection = build_projection_plan(&conn, user.id(), plan_id, req.reading_order_id)
        .await
        .map_err(|e| unprocessable(format!("Projection build error: {e}")))?;

    // Convert to response format
    let entries = projection
        .entries
        .into_iter()
        .map(|entry| ReadingOrderProjectionEntry {
            thread_id: entry.thread_id,
            thread_title: entry.thread_title,
            position: entry.position,
            source: entry.source,
            source_node_id: entry.source_node_id,
        })
        .collect();

    let conflicts = projection
        .conflicts
        .into_iter()
        .map(|conflict| ReadingOrderProjectionConflict {
            code: conflict.code,
            message: conflict.message,
            node_id: conflict.node_id.unwrap_or_default(),
            thread_id: conflict.thread_id,
            existing_positions: conflict.existing_positions.unwrap_or_default(),
        })
        .collect();

    let response = ReadingOrderProjectionPreview {
        plan_id,
        plan_name: projection.plan_name,
        plan_ordering_mode: projection.plan_ordering_mode,
        reading_order_id: req.reading_order_id,
        reading_order_name: projection.reading_order_name,
        entries,
        conflicts,
        total_positions: projection.total_positions,
        dropped_node_ids: projection.dropped_node_ids,
    };

    Ok(Json(response))
}

async fn build_projection_plan(
    conn: &deadpool_postgres::Object,
    user_id: i32,
    plan_id: i32,
    reading_order_id: i32,
) -> anyhow::Result<ProjectionPlan> {
    // Port from `app/services/reading_order_projection.build_projection_plan`
    // This is a deterministic projection without mutating any resource.

    // 1. Load owned continuity plan
    let plan_rows = conn
        .query(
            "SELECT p.id, p.name, p.ordering_mode, p.nodes_json, p.lanes_json FROM continuity_plans p WHERE p.id = $1 AND p.user_id = $2",
            &[&plan_id, &user_id],
        )
        .await?;
    let plan_row = plan_rows
        .into_iter()
        .next()
        .ok_or_else(|| anyhow::anyhow!("Plan {plan_id} not found"))?;
    let plan_id: i32 = plan_row.get("id");
    let plan_name: String = plan_row.get("name");
    let plan_ordering_mode: String = plan_row.get("ordering_mode");
    let nodes_json: serde_json::Value = plan_row.get("nodes_json");
    let lanes_json: serde_json::Value = plan_row.get("lanes_json");

    // 2. Load owned reading order
    let order_rows = conn
        .query(
            "SELECT o.id, o.name FROM reading_orders o WHERE o.id = $1 AND o.user_id = $2",
            &[&reading_order_id, &user_id],
        )
        .await?;
    let order_row = order_rows
        .into_iter()
        .next()
        .ok_or_else(|| anyhow::anyhow!("Reading order {reading_order_id} not found"))?;
    let reading_order_id: i32 = order_row.get("id");
    let reading_order_name: String = order_row.get("name");

    // 3. Parse and flatten plan nodes
    let nodes: Vec<ContinuityPlanNode> = serde_json::from_value(nodes_json)
        .map_err(|e| anyhow::anyhow!("Malformed plan nodes: {e}"))?;
    
    let lanes: Vec<serde_json::Value> = serde_json::from_value(lanes_json)
        .map_err(|e| anyhow::anyhow!("Malformed plan lanes: {e}"))?;
    let lane_orders: std::collections::HashMap<String, i32> = lanes
        .iter()
        .filter_map(|l| {
            let id = l.get("id")?.as_str()?.to_string();
            let order = l.get("order")?.as_i64()? as i32;
            Some((id, order))
        })
        .collect();

    let mut sorted_nodes = nodes.clone();
    let dropped_node_ids: Vec<String> = nodes
        .iter()
        .filter(|n| !lane_orders.contains_key(&n.lane_id))
        .map(|n| n.id.clone())
        .collect();

    if plan_ordering_mode == "strict_sequential" {
        if lanes.len() != 1 {
            return Err(anyhow::anyhow!("strict sequential plans must use exactly one lane"));
        }
        let single_lane_id = lanes[0].get("id").and_then(|v| v.as_str()).unwrap_or_default();
        let nodes_in_lane: Vec<_> = sorted_nodes.iter().filter(|n| n.lane_id == single_lane_id).collect();
        if nodes_in_lane.len() != nodes.len() {
            return Err(anyhow::anyhow!("strict sequential plans must have all nodes in single lane"));
        }
        sorted_nodes.sort_by_key(|n| n.position);
    } else {
        sorted_nodes.sort_by(|a, b| {
            let a_lane_order = lane_orders.get(&a.lane_id).unwrap_or(&0);
            let b_lane_order = lane_orders.get(&b.lane_id).unwrap_or(&0);
            a_lane_order.cmp(b_lane_order)
                .then(a.position.cmp(&b.position))
                .then(a.id.cmp(&b.id))
        });
    }

    // 4. Resolve thread titles
    let thread_ids: Vec<i32> = sorted_nodes
        .iter()
        .filter(|n| n.node_type == "thread")
        .map(|n| n.ref_id)
        .collect();
    
    let mut thread_titles = std::collections::HashMap::new();
    if !thread_ids.is_empty() {
        let title_rows = conn
            .query(
                "SELECT id, title FROM threads WHERE id = ANY($1) AND user_id = $2",
                &[&thread_ids, &user_id],
            )
            .await?;
        for row in title_rows {
            let id: i32 = row.get("id");
            let title: Option<String> = row.get("title");
            thread_titles.insert(id, title);
        }
    }

    // 5. Compute projection and conflicts
    let mut conflicts = Vec::new();
    let mut seen_thread_ids = std::collections::HashSet::new();
    let mut thread_positions: std::collections::HashMap<i32, Vec<i32>> = std::collections::HashMap::new();
    let mut preview_entries = Vec::new();

    for node in &sorted_nodes {
        if node.node_type != "thread" {
            conflicts.push(ProjectionConflict {
                code: "non_thread_node".to_string(),
                message: format!("Reading order projection only supports thread nodes; {node.node_type} node {node.id} cannot be projected."),
                node_id: Some(node.id.clone()),
                thread_id: Some(node.ref_id),
                existing_positions: vec![],
            });
            continue;
        }
        let thread_id = node.ref_id;
        if thread_titles.contains_key(&thread_id) {
            thread_positions.entry(thread_id).or_default().push(node.position);
            if seen_thread_ids.contains(&thread_id) {
                conflicts.push(ProjectionConflict {
                    code: "duplicate_thread".to_string(),
                    message: format!("Thread {thread_id} appears multiple times in the plan; deduplicate node positions before projection."),
                    node_id: Some(node.id.clone()),
                    thread_id: Some(thread_id),
                    existing_positions: thread_positions[&thread_id].clone(),
                });
                continue;
            }
            seen_thread_ids.insert(thread_id);
        } else {
            conflicts.push(ProjectionConflict {
                code: "missing_thread".to_string(),
                message: format!("Thread {thread_id} from node {node.id} is not owned by the user."),
                node_id: Some(node.id.clone()),
                thread_id: Some(thread_id),
                existing_positions: vec![],
            });
            continue;
        }
    }

    let mut total_positions = 0;
    if conflicts.is_empty() {
        let existing_rows = conn
            .query("SELECT thread_id, position FROM reading_order_items WHERE reading_order_id = $1", &[&reading_order_id])
            .await?;
        let mut existing_positions = std::collections::HashMap::new();
        for row in existing_rows {
            let tid: i32 = row.get("thread_id");
            let pos: i32 = row.get("position");
            existing_positions.insert(tid, pos);
        }

        let mut current_pos = 1;
        for node in &sorted_nodes {
            let thread_id = node.ref_id;
            let prior_pos = existing_positions.get(&thread_id);
            let source = if prior_pos.is_none() {
                "added".to_string()
            } else if *prior_pos.unwrap() != current_pos {
                "updated".to_string()
            } else {
                "existing".to_string()
            };
            preview_entries.push(ProjectionEntry {
                thread_id,
                thread_title: thread_titles.get(&thread_id).cloned().flatten(),
                position: current_pos,
                source,
                source_node_id: Some(node.id.clone()),
            });
            current_pos += 1;
        }
        total_positions = std::cmp::max(preview_entries.len() as i32, existing_positions.len() as i32);
    } else {
        let existing_rows = conn
            .query("SELECT 1 FROM reading_order_items WHERE reading_order_id = $1", &[&reading_order_id])
            .await?;
        total_positions = existing_rows.len() as i32;
    }

    Ok(ProjectionPlan {
        plan_id,
        plan_name,
        plan_ordering_mode,
        reading_order_id,
        reading_order_name,
        entries: preview_entries,
        conflicts,
        total_positions,
        dropped_node_ids,
    })
}

/// Internal projection plan structure.
#[derive(Debug, Clone)]
struct ProjectionPlan {
    entries: Vec<ProjectionEntry>,
    conflicts: Vec<ProjectionConflict>,
    total_positions: i32,
    dropped_node_ids: Vec<String>,
}

#[derive(Debug, Clone)]
struct ProjectionEntry {
    thread_id: i32,
    thread_title: Option<String>,
    position: i32,
    source: String,
    source_node_id: Option<String>,
}

#[derive(Debug, Clone)]
struct ProjectionConflict {
    code: String,
    message: String,
    node_id: Option<String>,
    thread_id: Option<i32>,
    existing_positions: Vec<i32>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn request_schema_validates() {
        let _req: ReadingOrderProjectionRequest = serde_json::from_value(
            serde_json::json!({
                "reading_order_id": 1,
            })
        )
        .unwrap();
    }

    #[test]
    fn response_schema_validates() {
        let _resp: ReadingOrderProjectionPreview = serde_json::from_value(
            serde_json::json!({
                "plan_id": 1,
                "plan_name": "My Plan",
                "plan_ordering_mode": "strict",
                "reading_order_id": 1,
                "reading_order_name": "My Reading Order",
                "entries": [
                    {
                        "thread_id": 1,
                        "thread_title": "Thread 1",
                        "position": 1,
                        "source": "existing",
                        "source_node_id": None,
                    }
                ],
                "conflicts": [],
                "total_positions": 1,
                "dropped_node_ids": [],
            })
        )
        .unwrap();
    }
}
