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
//!
//! Intentional, documented differences from the Python oracle:
//! - A request `reading_order_id` below 1 is rejected with Python's production
//!   422 body (`{"detail": "Validation failed"}`) before any pooled connection
//!   is checked out. Python's `Field(gt=0)` does not bound the value to `i32`,
//!   so an ID outside `i32` is not a validation error; the request reaches the
//!   owner-scoped query. Rust answers that case with the normal owner-scoped
//!   `404 {"detail": "Reading order <id> not found"}` instead of reproducing a
//!   driver-level integer-overflow failure.
//! - Python reads `lanes_json` as raw dictionaries and never applies the
//!   write-time `ContinuityPlanLane` limits during preview. Lane `id` values are
//!   therefore accepted at any length (including empty), and lane `order` may be
//!   negative. A lane missing `order` makes Python raise `KeyError` and return a
//!   500; Rust reports a structured `409 malformed_plan` instead. A non-string
//!   lane `id`/`order` is likewise a Python 500 and a Rust 409.
//! - Persisted node fields are validated against `ContinuityPlanNode` (label
//!   length, source/reader metadata, checkpoint targets, convergence targets).
//!   Pydantic's lax coercion of numeric strings/floats into integers is not
//!   reproduced; Rust treats such values as malformed. The `reason` string is a
//!   stable Rust explanation, not Pydantic's multi-line `str(exc)`; the browser
//!   client depends only on `code`.
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

/// One projected reading-order row.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingOrderProjectionEntry {
    /// Owned thread the row points at.
    pub thread_id: i32,
    /// Thread title when the thread is still owned by the reader.
    pub thread_title: Option<String>,
    /// One-based projected position.
    pub position: i32,
    /// `existing`, `added`, or `updated`.
    pub source: String,
    /// Plan node that produced the row.
    pub source_node_id: Option<String>,
}

/// One conflict that blocks a projection.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingOrderProjectionConflict {
    /// `duplicate_thread`, `missing_thread`, or `non_thread_node`.
    pub code: String,
    /// Human-readable explanation.
    pub message: String,
    /// Plan node that produced the conflict.
    pub node_id: String,
    /// Thread referenced by the node, when the node has one.
    pub thread_id: Option<i32>,
    /// Existing reading-order positions already used by the thread.
    pub existing_positions: Vec<i32>,
}

/// Preview response shared with the Python endpoint.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingOrderProjectionPreview {
    /// Continuity plan identifier.
    pub plan_id: i32,
    /// Continuity plan name.
    pub plan_name: String,
    /// Continuity plan ordering mode.
    pub plan_ordering_mode: String,
    /// Target reading order identifier.
    pub reading_order_id: i32,
    /// Target reading order name.
    pub reading_order_name: String,
    /// Projected rows, empty when any conflict exists.
    pub entries: Vec<ReadingOrderProjectionEntry>,
    /// Blocking conflicts.
    pub conflicts: Vec<ReadingOrderProjectionConflict>,
    /// Number of positions the order would have after confirmation.
    pub total_positions: i32,
    /// Plan node ids whose lane is absent from the persisted lanes.
    pub dropped_node_ids: Vec<String>,
}

/// A validated persisted plan node used only for preview flattening.
#[derive(Debug, Clone)]
struct PlanNode {
    /// Stable node identifier.
    id: String,
    /// `issue`, `crossover`, or `thread`.
    node_type: String,
    /// Referenced issue/crossover/thread identifier.
    ref_id: i32,
    /// Lane that owns the node.
    lane_id: String,
    /// Zero-based position inside the lane.
    position: i32,
}

/// One raw plan lane. Python reads these dictionaries directly during preview,
/// so only `id` and `order` are required; no write-time length limit applies.
#[derive(Debug, Clone)]
struct PlanLane {
    /// Lane identifier, accepted at any length.
    id: String,
    /// Lane ordering key, accepted at any integer value.
    order: i32,
}

/// The validated slice of a persisted plan needed by the preview.
#[derive(Debug, Clone)]
struct PlanDocument {
    /// Persisted ordering mode.
    ordering_mode: String,
    /// Validated nodes.
    nodes: Vec<PlanNode>,
    /// Raw lanes.
    lanes: Vec<PlanLane>,
}

/// Owner-scoped plan columns read for one preview.
struct OwnedPlan {
    /// Plan identifier.
    id: i32,
    /// Plan name.
    name: String,
    /// Persisted ordering mode.
    ordering_mode: String,
    /// Raw `nodes_json` text.
    nodes_json: String,
    /// Raw `lanes_json` text.
    lanes_json: String,
}

/// Owner-scoped reading order columns read for one preview.
struct OwnedOrder {
    /// Reading order identifier.
    id: i32,
    /// Reading order name.
    name: String,
}

/// Build the Python-compatible `404 {"detail": ...}` response.
fn not_found(detail: String) -> Response {
    ApiError::NotFound(detail).into_response()
}

/// Reject request bodies that Python's `Field(gt=0)` validation rejects.
///
/// The production Python body for any request-validation failure is
/// `{"detail": "Validation failed"}`. Checking this before `db::checkout`
/// keeps invalid requests from consuming a pooled connection.
fn validate_reading_order_id(reading_order_id: i64) -> Result<(), Response> {
    if reading_order_id < 1 {
        return Err(ApiError::Unprocessable("Validation failed".to_string()).into_response());
    }
    Ok(())
}

/// Build a `409 {"detail": ...}` response with a structured body.
fn structured_conflict(body: Value) -> Response {
    (
        axum::http::StatusCode::CONFLICT,
        Json(serde_json::json!({ "detail": body })),
    )
        .into_response()
}

/// Build the Python-compatible malformed-plan conflict envelope.
fn malformed_plan(plan_id: i32, reason: impl Into<String>) -> Response {
    structured_conflict(serde_json::json!({
        "code": "malformed_plan",
        "plan_id": plan_id,
        "reason": reason.into(),
    }))
}

/// Parse one persisted JSON column that Python stores as a list of dictionaries.
fn parse_json_array(raw: &str, what: &str) -> Result<Vec<Value>, String> {
    let value: Value =
        serde_json::from_str(raw).map_err(|_| format!("{what} must be a JSON array"))?;
    match value {
        Value::Array(values) => Ok(values),
        _ => Err(format!("{what} must be a JSON array")),
    }
}

/// Return an optional field, treating an explicit JSON `null` as absent.
fn optional_field<'a>(value: &'a Value, field: &str) -> Option<&'a Value> {
    value.get(field).filter(|item| !item.is_null())
}

/// Require a string field with Pydantic's inclusive character-length bounds.
fn require_bounded_str<'a>(
    value: &'a Value,
    field: &str,
    min: usize,
    max: usize,
) -> Result<&'a str, String> {
    let text = value
        .get(field)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("{field} must be a string"))?;
    let length = text.chars().count();
    if length < min || length > max {
        return Err(format!(
            "{field} must contain between {min} and {max} characters"
        ));
    }
    Ok(text)
}

/// Require an integer field that fits `i32` and satisfies `predicate`.
fn require_i32(
    value: &Value,
    field: &str,
    expectation: &str,
    predicate: impl Fn(i32) -> bool,
) -> Result<i32, String> {
    value
        .get(field)
        .and_then(Value::as_i64)
        .and_then(|number| i32::try_from(number).ok())
        .filter(|number| predicate(*number))
        .ok_or_else(|| format!("{field} must be {expectation}"))
}

/// Require a string field drawn from a fixed set of values.
fn require_enum<'a>(value: &'a Value, field: &str, allowed: &[&str]) -> Result<&'a str, String> {
    let text = value
        .get(field)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("{field} must be a string"))?;
    if !allowed.contains(&text) {
        return Err(format!("{field} must be one of {}", allowed.join(", ")));
    }
    Ok(text)
}

/// Validate an optional string field.
fn validate_optional_str(value: &Value, field: &str) -> Result<(), String> {
    if let Some(item) = optional_field(value, field) {
        if !item.is_string() {
            return Err(format!("{field} must be a string"));
        }
    }
    Ok(())
}

/// Validate an optional string field drawn from a fixed set of values.
fn validate_optional_enum(value: &Value, field: &str, allowed: &[&str]) -> Result<(), String> {
    if let Some(item) = optional_field(value, field) {
        let text = item
            .as_str()
            .ok_or_else(|| format!("{field} must be a string"))?;
        if !allowed.contains(&text) {
            return Err(format!("{field} must be one of {}", allowed.join(", ")));
        }
    }
    Ok(())
}

/// Validate an optional array whose entries are all strings.
fn validate_optional_str_array(value: &Value, field: &str) -> Result<(), String> {
    if let Some(item) = optional_field(value, field) {
        let array = item
            .as_array()
            .ok_or_else(|| format!("{field} must be an array"))?;
        if array.iter().any(|entry| !entry.is_string()) {
            return Err(format!("{field} must contain only strings"));
        }
    }
    Ok(())
}

/// Validate an optional array of `CBLPlacement` objects.
fn validate_optional_cbl_placements(value: &Value, field: &str) -> Result<(), String> {
    if let Some(item) = optional_field(value, field) {
        let array = item
            .as_array()
            .ok_or_else(|| format!("{field} must be an array"))?;
        for placement in array {
            let valid = placement.is_object()
                && placement.get("source_path").is_some_and(Value::is_string)
                && placement.get("position").is_some_and(Value::is_i64);
            if !valid {
                return Err(format!(
                    "{field} entries need a string source_path and integer position"
                ));
            }
        }
    }
    Ok(())
}

/// Validate an optional boolean field.
fn validate_optional_bool(value: &Value, field: &str) -> Result<(), String> {
    if let Some(item) = optional_field(value, field) {
        if !item.is_boolean() {
            return Err(format!("{field} must be a boolean"));
        }
    }
    Ok(())
}

/// Validate the `label` character bound that Pydantic enforces.
fn validate_label(value: &Value) -> Result<(), String> {
    if let Some(item) = optional_field(value, "label") {
        let text = item
            .as_str()
            .ok_or_else(|| "label must be a string".to_string())?;
        if text.chars().count() > 200 {
            return Err("label must contain at most 200 characters".to_string());
        }
    }
    Ok(())
}

/// Validate the defaulted `is_checkpoint` flag.
fn validate_checkpoint_flag(value: &Value) -> Result<(), String> {
    match value.get("is_checkpoint") {
        None => Ok(()),
        Some(item) if item.is_boolean() => Ok(()),
        Some(_) => Err("is_checkpoint must be a boolean".to_string()),
    }
}

/// Validate an optional positive `i32` field such as `checkpoint_target_ref_id`.
fn validate_optional_positive_i32(value: &Value, field: &str) -> Result<(), String> {
    if let Some(item) = optional_field(value, field) {
        let valid = item
            .as_i64()
            .and_then(|number| i32::try_from(number).ok())
            .is_some_and(|number| number > 0);
        if !valid {
            return Err(format!("{field} must be a positive integer"));
        }
    }
    Ok(())
}

/// Validate the bounded `checkpoint_target_ref_ids` list.
fn validate_checkpoint_targets(value: &Value) -> Result<(), String> {
    let Some(item) = optional_field(value, "checkpoint_target_ref_ids") else {
        return Ok(());
    };
    let array = item
        .as_array()
        .ok_or_else(|| "checkpoint_target_ref_ids must be an array".to_string())?;
    if array.len() > 1000 {
        return Err("checkpoint_target_ref_ids must contain at most 1000 items".to_string());
    }
    for target in array {
        let valid = target
            .as_i64()
            .and_then(|number| i32::try_from(number).ok())
            .is_some_and(|number| number > 0);
        if !valid {
            return Err("checkpoint_target_ref_ids must contain positive integers".to_string());
        }
    }
    Ok(())
}

/// Validate the `convergence_gate` target objects.
fn validate_convergence_gate(value: &Value) -> Result<(), String> {
    let Some(item) = value.get("convergence_gate") else {
        return Ok(());
    };
    if item.is_null() {
        return Ok(());
    }
    let array = item
        .as_array()
        .ok_or_else(|| "convergence_gate must be an array".to_string())?;
    for target in array {
        target
            .get("node_type")
            .and_then(Value::as_str)
            .filter(|kind| matches!(*kind, "issue" | "crossover" | "thread"))
            .ok_or_else(|| {
                "convergence_gate node_type must be issue, crossover, or thread".to_string()
            })?;
        target
            .get("node_id")
            .and_then(Value::as_str)
            .filter(|id| {
                let length = id.chars().count();
                (1..=80).contains(&length)
            })
            .ok_or_else(|| {
                "convergence_gate node_id must be a non-empty string of at most 80 characters"
                    .to_string()
            })?;
    }
    Ok(())
}

/// Validate one persisted node against the `ContinuityPlanNode` read contract.
fn validate_plan_node(value: &Value) -> Result<PlanNode, String> {
    let id = require_bounded_str(value, "id", 1, 80)?.to_string();
    let node_type =
        require_enum(value, "node_type", &["issue", "crossover", "thread"])?.to_string();
    let ref_id = require_i32(value, "ref_id", "a positive integer", |number| number > 0)?;
    let lane_id = require_bounded_str(value, "lane_id", 1, 80)?.to_string();
    let position = require_i32(value, "position", "a non-negative integer", |number| {
        number >= 0
    })?;

    validate_label(value)?;
    validate_optional_enum(
        value,
        "source_role",
        &["core", "context/prelude", "epilogue", "unknown"],
    )?;
    validate_optional_enum(value, "source_confidence", &["high", "medium", "low"])?;
    validate_optional_str(value, "source_explanation")?;
    validate_optional_str_array(value, "source_paths")?;
    validate_optional_cbl_placements(value, "source_cbl_placements")?;
    validate_optional_str_array(value, "source_story_arc_ids")?;
    validate_optional_str(value, "source_target_story_arc_id")?;
    validate_optional_enum(
        value,
        "reader_role",
        &[
            "required/core",
            "recommended",
            "optional",
            "context/prelude",
            "aftermath/epilogue",
            "skipped/excluded",
        ],
    )?;
    validate_optional_bool(value, "reader_optional")?;
    validate_checkpoint_flag(value)?;
    validate_optional_positive_i32(value, "checkpoint_target_ref_id")?;
    validate_checkpoint_targets(value)?;
    validate_convergence_gate(value)?;

    Ok(PlanNode {
        id,
        node_type,
        ref_id,
        lane_id,
        position,
    })
}

/// Validate and decode the persisted plan JSON into the flattening model.
///
/// Python validates every node first and only then reads lane dictionaries, so
/// node errors take precedence when both columns are malformed.
fn parse_plan(plan: &OwnedPlan) -> Result<PlanDocument, String> {
    let nodes_raw = parse_json_array(&plan.nodes_json, "nodes_json")?;
    let lanes_raw = parse_json_array(&plan.lanes_json, "lanes_json")?;

    let mut nodes = Vec::with_capacity(nodes_raw.len());
    for value in &nodes_raw {
        nodes.push(validate_plan_node(value)?);
    }

    let mut lanes = Vec::with_capacity(lanes_raw.len());
    for value in lanes_raw {
        // Python reads lane dictionaries directly and never re-runs the
        // write-time lane limits during preview, so ids are not length-bounded
        // and orders may be negative. A missing/non-integer order is a Python
        // 500 (`KeyError`/`TypeError`); Rust fails closed with a 409 instead.
        let id = value
            .get("id")
            .and_then(Value::as_str)
            .ok_or_else(|| "lane id must be a string".to_string())?
            .to_string();
        let order = value
            .get("order")
            .and_then(Value::as_i64)
            .and_then(|order| i32::try_from(order).ok())
            .ok_or_else(|| "lane order must be an integer".to_string())?;
        lanes.push(PlanLane { id, order });
    }

    Ok(PlanDocument {
        ordering_mode: plan.ordering_mode.clone(),
        nodes,
        lanes,
    })
}

/// Apply the documented deterministic flattening policy.
fn flatten_plan(plan: &PlanDocument) -> Result<(Vec<PlanNode>, Vec<String>), String> {
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
        let lane_orders: BTreeMap<&str, i32> = plan
            .lanes
            .iter()
            .map(|lane| (lane.id.as_str(), lane.order))
            .collect();
        ordered.sort_by(|left, right| {
            let left_lane = lane_orders.get(left.lane_id.as_str()).copied().unwrap_or(0);
            let right_lane = lane_orders
                .get(right.lane_id.as_str())
                .copied()
                .unwrap_or(0);
            left_lane
                .cmp(&right_lane)
                .then(left.position.cmp(&right.position))
                .then_with(|| left.id.cmp(&right.id))
        });
    }

    Ok((ordered, dropped))
}

/// Classify one projected entry against the current reading-order rows.
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
    Path(plan_id): Path<i64>,
    Json(payload): Json<ReadingOrderProjectionRequest>,
) -> Response {
    if let Err(response) = validate_reading_order_id(payload.reading_order_id) {
        return response;
    }
    match build_preview(&state, user.id(), plan_id, payload.reading_order_id).await {
        Ok(preview) => Json(preview).into_response(),
        Err(response) => response,
    }
}

/// Load the owned plan and order, then compute the preview.
///
/// The plan lookup runs before the reading-order lookup so a request naming a
/// missing plan and a missing order reports the plan, exactly like Python.
async fn build_preview(
    state: &AppState,
    user_id: i32,
    plan_id: i64,
    reading_order_id: i64,
) -> Result<ReadingOrderProjectionPreview, Response> {
    let connection = db::checkout(state)
        .await
        .map_err(IntoResponse::into_response)?;

    let plan_row = match i32::try_from(plan_id) {
        Ok(owned_plan_id) => connection
            .query_opt(
                "SELECT id, name, ordering_mode, COALESCE(nodes_json::text, '[]'), \
                        COALESCE(lanes_json::text, '[]') \
                 FROM continuity_plans WHERE id=$1 AND user_id=$2",
                &[&owned_plan_id, &user_id],
            )
            .await
            .map_err(db::query_error)
            .map_err(IntoResponse::into_response)?,
        Err(_) => None,
    };
    let plan_row =
        plan_row.ok_or_else(|| not_found(format!("Continuity plan {plan_id} not found")))?;

    let plan = OwnedPlan {
        id: plan_row.get(0),
        name: plan_row.get(1),
        ordering_mode: plan_row.get(2),
        nodes_json: plan_row.get(3),
        lanes_json: plan_row.get(4),
    };

    let order_row = match i32::try_from(reading_order_id) {
        Ok(owned_order_id) => connection
            .query_opt(
                "SELECT id, name FROM reading_orders WHERE id=$1 AND user_id=$2",
                &[&owned_order_id, &user_id],
            )
            .await
            .map_err(db::query_error)
            .map_err(IntoResponse::into_response)?,
        Err(_) => None,
    };
    let order_row = order_row
        .ok_or_else(|| not_found(format!("Reading order {reading_order_id} not found")))?;

    let order = OwnedOrder {
        id: order_row.get(0),
        name: order_row.get(1),
    };

    let document = parse_plan(&plan).map_err(|reason| malformed_plan(plan.id, reason))?;
    let (ordered_nodes, dropped_node_ids) =
        flatten_plan(&document).map_err(|reason| malformed_plan(plan.id, reason))?;

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
                    "Reading order projection only supports thread nodes; \
                     {} node '{}' cannot be projected.",
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
                        "Thread {thread_id} appears multiple times in the plan; \
                         deduplicate node positions before projection."
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
                    "Thread {thread_id} from node '{}' is not owned by the user.",
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
    operation_id = "preview_plan_projection",
    params(("plan_id" = i32, Path, description = "Continuity plan ID")),
    request_body = ReadingOrderProjectionRequest,
    responses(
        (status = 200, description = "Deterministic projection preview with conflicts", body = ReadingOrderProjectionPreview),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Continuity plan or reading order not found"),
        (status = 409, description = "Malformed persisted plan"),
        (status = 422, description = "Invalid reading order id"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub fn preview_plan_projection_documentation() {}

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

    /// Build one plan node for flattening tests.
    fn node(id: &str, kind: &str, ref_id: i32, lane: &str, position: i32) -> PlanNode {
        PlanNode {
            id: id.to_string(),
            node_type: kind.to_string(),
            ref_id,
            lane_id: lane.to_string(),
            position,
        }
    }

    /// Build one plan lane for flattening tests.
    fn lane(id: &str, order: i32) -> PlanLane {
        PlanLane {
            id: id.to_string(),
            order,
        }
    }

    /// Build an owned plan with raw JSON columns for parser tests.
    fn owned_plan(nodes_json: &str, lanes_json: &str, mode: &str) -> OwnedPlan {
        OwnedPlan {
            id: 7,
            name: "Plan".to_string(),
            ordering_mode: mode.to_string(),
            nodes_json: nodes_json.to_string(),
            lanes_json: lanes_json.to_string(),
        }
    }

    /// Minimal valid persisted node used by parser tests.
    fn valid_node(id: &str, lane: &str, position: i32) -> Value {
        serde_json::json!({
            "id": id,
            "node_type": "thread",
            "ref_id": 1,
            "lane_id": lane,
            "position": position,
        })
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

    #[tokio::test]
    async fn reading_order_id_below_one_is_a_python_shaped_422() {
        let response = validate_reading_order_id(0).expect_err("zero must be rejected");
        assert_eq!(
            response.status(),
            axum::http::StatusCode::UNPROCESSABLE_ENTITY
        );
        let body = axum::body::to_bytes(response.into_body(), 1024)
            .await
            .expect("body bytes");
        let value: Value = serde_json::from_slice(&body).expect("json body");
        assert_eq!(value, serde_json::json!({"detail": "Validation failed"}));
        assert!(validate_reading_order_id(1).is_ok());
    }

    #[test]
    fn lane_ids_are_not_length_bounded_and_orders_may_be_negative() {
        let long_lane = "x".repeat(200);
        let plan = owned_plan(
            &serde_json::json!([valid_node("node", &long_lane, 0)]).to_string(),
            &serde_json::json!([{"id": long_lane, "order": -3}]).to_string(),
            "informational",
        );
        let document = parse_plan(&plan).expect("Python accepts long lane ids");
        assert_eq!(document.lanes[0].id, long_lane);
        assert_eq!(document.lanes[0].order, -3);
        assert!(flatten_plan(&document).is_ok());
    }

    #[test]
    fn missing_lane_order_is_a_structured_conflict_instead_of_a_500() {
        let plan = owned_plan(
            &serde_json::json!([valid_node("node", "main", 0)]).to_string(),
            &serde_json::json!([{"id": "main"}]).to_string(),
            "informational",
        );
        assert_eq!(
            parse_plan(&plan).expect_err("missing order is malformed"),
            "lane order must be an integer"
        );
    }

    #[test]
    fn invalid_reader_role_is_rejected_like_python() {
        let mut value = valid_node("node", "main", 0);
        value["reader_role"] = Value::String("not-a-role".to_string());
        let plan = owned_plan(
            &serde_json::json!([value]).to_string(),
            &serde_json::json!([{"id": "main", "order": 0}]).to_string(),
            "informational",
        );
        assert!(parse_plan(&plan).is_err());
    }

    #[test]
    fn valid_node_metadata_is_accepted() {
        let mut value = valid_node("node", "main", 0);
        value["label"] = Value::String("Chapter one".to_string());
        value["source_role"] = Value::String("core".to_string());
        value["source_confidence"] = Value::String("high".to_string());
        value["source_explanation"] = Value::String("from CBL".to_string());
        value["source_paths"] = serde_json::json!(["a.cbl"]);
        value["source_cbl_placements"] =
            serde_json::json!([{"source_path": "a.cbl", "position": 1}]);
        value["source_story_arc_ids"] = serde_json::json!(["arc-1"]);
        value["source_target_story_arc_id"] = Value::String("arc-1".to_string());
        value["reader_role"] = Value::String("required/core".to_string());
        value["reader_optional"] = Value::Bool(false);
        value["is_checkpoint"] = Value::Bool(true);
        value["checkpoint_target_ref_id"] = serde_json::json!(9);
        value["checkpoint_target_ref_ids"] = serde_json::json!([9, 10]);
        value["convergence_gate"] = serde_json::json!([
            {"node_type": "issue", "node_id": "gate-1"},
            {"node_type": "crossover", "node_id": "gate-2"},
        ]);
        let plan = owned_plan(
            &serde_json::json!([value]).to_string(),
            &serde_json::json!([{"id": "main", "order": 0}]).to_string(),
            "informational",
        );
        let document = parse_plan(&plan).expect("valid metadata");
        assert_eq!(document.nodes[0].id, "node");
    }

    #[test]
    fn node_errors_take_precedence_over_lane_errors() {
        let plan = owned_plan(
            &serde_json::json!([{"id": "broken", "node_type": "issue"}]).to_string(),
            &serde_json::json!([{"id": "main"}]).to_string(),
            "informational",
        );
        assert_eq!(
            parse_plan(&plan).expect_err("node error wins"),
            "ref_id must be a positive integer"
        );
    }
}
