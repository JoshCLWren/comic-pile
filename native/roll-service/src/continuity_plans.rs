//! Same-path native Rust cutover for the browser-called continuity-plans operations.
//!
//! Preserves the Python `app/api/continuity_plan.py` +
//! `app/api/reading_plan_release_source.py` +
//! `app/api/reading_order_projection.py` wire contract at the same
//! HTTP methods and exact paths.
//!
//! Only the implementation moves from Python FastAPI to the native Roll
//! binary. No frontend URL changes.
//!
//! Routes cut over:
//! * `GET /api/v2/continuity-plans/` - list plans
//! * `POST /api/v2/continuity-plans/` - create plan
//! * `POST /api/v2/continuity-plans/from-reading-order` - adopt reading order
//! * `POST /api/v2/continuity-plans/release-sources/` - create release source
//! * `DELETE /api/v2/continuity-plans/release-sources/{source_id}` - delete release source
//! * `PATCH /api/v2/continuity-plans/release-sources/{source_id}` - update release source
//! * `DELETE /api/v2/continuity-plans/{plan_id}` - delete plan
//! * `GET /api/v2/continuity-plans/{plan_id}` - get plan
//! * `PUT /api/v2/continuity-plans/{plan_id}` - update plan
//! * `DELETE /api/v2/continuity-plans/{plan_id}/dependencies/{dependency_id}` - unlink dependency
//! * `POST /api/v2/continuity-plans/{plan_id}/dependencies/{dependency_id}` - link dependency
//! * `GET /api/v2/continuity-plans/{plan_id}/membership` - get membership
//! * `POST /api/v2/continuity-plans/{plan_id}/reading-orders/project` - project to reading order
//! * `GET /api/v2/continuity-plans/{plan_id}/release-sources/` - list release sources
//! * `GET /api/v2/continuity-plans/{plan_id}/release-sources/reader` - reader-facing release sources
//!
//! Wire contracts mirror Python (`app/schemas/continuity_plan.py`,
//! `app/schemas/reading_plan_release_source.py`, `app/schemas/reading_order.py`)
//! with identical JSON field names, types, and optional/required status.
//!
//! Parity notes:
//! * Uses owner-scoped SQL queries similar to other native Rust handlers
//! * Preserves 404 messages from Python for plan/thread ownership checks
//! * Mirrors Python 409 conflict responses with same message structure
//! * Serializes graph mutations with the same per-user advisory lock the Python
//!   writer uses (`pg_advisory_xact_lock(CONTINUITY_LOCK_NAMESPACE, user_id)`).

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio_postgres::Transaction;
use utoipa::ToSchema;

// ============================================================================
// Continuity Plan request/response schemas (mirrors app/schemas/continuity_plan.py)
// ============================================================================

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ContinuityPlanLane {
    pub id: String,
    pub name: String,
    pub order: i32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub inferred_gate_kind: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub migration_contract: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ContinuityPlanNode {
    pub id: String,
    #[serde(rename = "node_type")]
    pub node_type: String,
    #[serde(rename = "ref_id")]
    pub ref_id: i32,
    #[serde(rename = "lane_id")]
    pub lane_id: String,
    pub position: i32,
    #[serde(default)]
    #[schema(required)]
    pub label: Option<String>,
    #[serde(default)]
    #[schema(required)]
    pub source_role: Option<String>,
    #[serde(default)]
    #[schema(required)]
    pub source_confidence: Option<String>,
    #[serde(default)]
    #[schema(required)]
    pub source_explanation: Option<String>,
    #[serde(default)]
    #[schema(required)]
    pub source_paths: Option<Vec<String>>,
    #[serde(default)]
    #[schema(required)]
    pub source_cbl_placements: Option<Vec<serde_json::Value>>,
    #[serde(default)]
    #[schema(required)]
    pub source_story_arc_ids: Option<Vec<String>>,
    #[serde(default)]
    #[schema(required)]
    pub source_target_story_arc_id: Option<String>,
    #[serde(default)]
    #[schema(required)]
    pub reader_role: Option<String>,
    #[serde(default)]
    #[schema(required)]
    pub reader_optional: Option<bool>,
    #[serde(default)]
    pub is_checkpoint: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub checkpoint_target_ref_id: Option<i32>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub checkpoint_target_ref_ids: Vec<i32>,
    #[serde(default)]
    #[schema(required)]
    pub convergence_gate: Vec<serde_json::Value>,
}

fn default_ordering_mode() -> String {
    "informational".to_string()
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ContinuityPlanWrite {
    pub name: String,
    // The retired Python schema defaulted this field to "informational".
    // Keep that wire contract for the v2 Rust route so clients that omit it
    // keep working after the cutover (see #5528 CodeRabbit review).
    #[serde(rename = "ordering_mode", default = "default_ordering_mode")]
    pub ordering_mode: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub lanes: Vec<ContinuityPlanLane>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub nodes: Vec<ContinuityPlanNode>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expected_updated_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ContinuityPlanResponse {
    pub id: i32,
    pub user_id: i32,
    pub name: String,
    #[serde(rename = "ordering_mode")]
    pub ordering_mode: String,
    #[serde(default)]
    #[schema(required)]
    pub lanes: Vec<ContinuityPlanLane>,
    #[serde(default)]
    #[schema(required)]
    pub nodes: Vec<ContinuityPlanNode>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ContinuityPlanListItem {
    pub id: i32,
    pub name: String,
    #[serde(rename = "ordering_mode")]
    pub ordering_mode: String,
    #[serde(rename = "lane_count")]
    pub lane_count: i32,
    #[serde(rename = "step_count")]
    pub step_count: i32,
    #[schema(required)]
    pub source_paths: Vec<String>,
    #[schema(required)]
    pub source_names: serde_json::Value,
    pub updated_at: String,
}

// ============================================================================
// Reading Plan Release Source request/response schemas
// ============================================================================

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ReleaseSourceCreate {
    pub plan_id: i32,
    pub thread_id: i32,
    #[serde(rename = "external_identity_id")]
    pub external_identity_id: i32,
    #[serde(rename = "custom_cbl_list_id", default)]
    pub custom_cbl_list_id: Option<i32>,
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ReleaseSourceUpdate {
    pub enabled: bool,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
// Distinct schema name: the releases surface already owns `ReleaseSourceResponse`
// with a different `{exists, release}` shape. Keeping the continuity shape under
// its own name prevents a collision in the generated client contract.
#[schema(as = ContinuityReleaseSourceResponse)]
pub struct ReleaseSourceResponse {
    pub id: i32,
    pub plan_id: i32,
    #[serde(rename = "custom_cbl_list_id", default)]
    pub custom_cbl_list_id: Option<i32>,
    pub thread_id: i32,
    #[serde(rename = "external_identity_id")]
    pub external_identity_id: i32,
    pub provider: String,
    #[serde(rename = "provider_volume_id")]
    pub provider_volume_id: String,
    #[serde(rename = "provider_title")]
    pub provider_title: Option<String>,
    pub enabled: bool,
    #[serde(rename = "last_synced_at")]
    pub last_synced_at: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReadingPlanReleaseSourceStatus {
    #[serde(rename = "source_id")]
    pub source_id: i32,
    pub thread_id: i32,
    #[serde(rename = "external_identity_id")]
    pub external_identity_id: i32,
    #[serde(rename = "provider_volume_id")]
    pub provider_volume_id: String,
    #[serde(rename = "provider_title")]
    pub provider_title: Option<String>,
    #[serde(rename = "provider_publisher")]
    pub provider_publisher: Option<String>,
    #[serde(rename = "provider_start_year")]
    pub provider_start_year: Option<i32>,
    #[serde(rename = "provider_issue_count")]
    pub provider_issue_count: Option<i32>,
    pub enabled: bool,
    #[serde(rename = "last_synced_at")]
    pub last_synced_at: Option<String>,
}

// ============================================================================
// Reading Order Projection request/response schemas
// ============================================================================

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ReadingOrderProjectionRequest {
    #[serde(rename = "reading_order_id")]
    pub reading_order_id: i32,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReadingOrderProjectionEntry {
    pub thread_id: i32,
    #[serde(rename = "thread_title")]
    pub thread_title: Option<String>,
    pub position: i32,
    pub source: String,
    #[serde(rename = "source_node_id")]
    pub source_node_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReadingOrderProjectionConflict {
    pub code: String,
    pub message: String,
    #[serde(rename = "node_id")]
    pub node_id: String,
    #[serde(rename = "thread_id")]
    pub thread_id: Option<i32>,
    #[serde(rename = "existing_positions")]
    pub existing_positions: Vec<i32>,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReadingOrderProjectionPreview {
    #[serde(rename = "plan_id")]
    pub plan_id: i32,
    #[serde(rename = "plan_name")]
    pub plan_name: String,
    #[serde(rename = "plan_ordering_mode")]
    pub plan_ordering_mode: String,
    #[serde(rename = "reading_order_id")]
    pub reading_order_id: i32,
    #[serde(rename = "reading_order_name")]
    pub reading_order_name: String,
    pub entries: Vec<ReadingOrderProjectionEntry>,
    pub conflicts: Vec<ReadingOrderProjectionConflict>,
    #[serde(rename = "total_positions")]
    pub total_positions: i32,
    #[serde(rename = "dropped_node_ids")]
    pub dropped_node_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReadingOrderProjectionResult {
    #[serde(rename = "plan_id")]
    pub plan_id: i32,
    #[serde(rename = "reading_order_id")]
    pub reading_order_id: i32,
    #[serde(rename = "added_count")]
    pub added_count: i32,
    #[serde(rename = "updated_count")]
    pub updated_count: i32,
    #[serde(rename = "kept_count")]
    pub kept_count: i32,
    #[serde(rename = "total_positions")]
    pub total_positions: i32,
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ReadingOrderAdoptRequest {
    #[serde(rename = "reading_order_id")]
    pub reading_order_id: i32,
    #[serde(rename = "plan_name")]
    pub plan_name: Option<String>,
    #[serde(rename = "lane_id")]
    pub lane_id: Option<String>,
    #[serde(rename = "lane_name")]
    pub lane_name: Option<String>,
}

// ============================================================================
// Helper functions
// ============================================================================

fn bad_request(detail: impl Into<String>) -> ApiError {
    ApiError::BadRequest(detail.into())
}

fn not_found(detail: impl Into<String>) -> ApiError {
    ApiError::NotFound(detail.into())
}

/// Build a structured error whose wire body is `{"detail": <json object>}`.
///
/// Python/FastAPI domain errors carry a structured `detail` object. The scalar
/// `ApiError` variants stringify it, which would put a JSON *string* on the
/// wire and break the frontend's `detail.code` branching. This helper keeps
/// the exact object shape (review #4838 finding #6).
fn structured(status: StatusCode, detail: serde_json::Value) -> ApiError {
    ApiError::structured(status, detail)
}

/// Build a 422 envelope matching the Python Pydantic `model_validator` shape.
fn unprocessable(message: impl Into<String>) -> ApiError {
    structured(
        StatusCode::UNPROCESSABLE_ENTITY,
        serde_json::json!({"code": "validation_error", "message": message.into()}),
    )
}

/// 422 `dangling_plan_reference` envelope from Python `validate_node_ownership`.
fn dangling_node(node_id: &str) -> ApiError {
    structured(
        StatusCode::UNPROCESSABLE_ENTITY,
        serde_json::json!({"code": "dangling_plan_reference", "node_id": node_id}),
    )
}

/// 409 domain-conflict envelope (`detail.code`) used by plan writers.
fn domain_conflict(detail: serde_json::Value) -> ApiError {
    structured(StatusCode::CONFLICT, detail)
}

/// Per-user advisory-lock namespace shared with the Python continuity writer
/// (`app/repositories/continuity_repository.py::CONTINUITY_LOCK_NAMESPACE`).
const CONTINUITY_LOCK_NAMESPACE: i32 = 1_129_274_964;

/// Serialize continuity-graph mutations for one owner.
///
/// Mirrors Python `lock_continuity_graph`: the transaction-scoped advisory lock
/// is released on commit or rollback, so callers only need to take it once at
/// the start of a write transaction.
async fn lock_continuity_graph(tx: &Transaction<'_>, user_id: i32) -> Result<(), ApiError> {
    tx.execute(
        "SELECT pg_advisory_xact_lock($1, $2)",
        &[&CONTINUITY_LOCK_NAMESPACE, &user_id],
    )
    .await
    .map_err(db::query_error)?;
    Ok(())
}

/// Parse an optimistic-concurrency token into a timezone-aware UTC instant.
///
/// The frontend sends ISO-8601 tokens (`2026-08-12T00:00:00Z`); Python's
/// Pydantic parser accepts both `Z` and explicit offsets and normalizes naive
/// values to UTC. Compare instants, never raw text.
fn parse_aware_utc(value: &str) -> Option<DateTime<Utc>> {
    let value = value.trim();
    if let Ok(parsed) = DateTime::parse_from_rfc3339(value) {
        return Some(parsed.with_timezone(&Utc));
    }
    for format in [
        "%Y-%m-%dT%H:%M:%S%.f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S%.f",
        "%Y-%m-%d %H:%M:%S",
    ] {
        if let Ok(naive) = chrono::NaiveDateTime::parse_from_str(value, format) {
            return Some(DateTime::<Utc>::from_naive_utc_and_offset(naive, Utc));
        }
    }
    None
}

/// Render a UTC instant in the ISO-8601 wire shape Python emits for plan
/// timestamps (`datetime.isoformat()`), so GET-then-PUT round-trips.
fn iso_utc(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::AutoSi, true)
}

/// Port of Python `validate_node_ownership`: every referenced issue, thread and
/// crossover must be owned by the plan owner. Issues are bulk-checked through
/// the join-through-thread ownership guard; crossovers resolve to a
/// `DependencyGroup`. Any failure is a 422 `dangling_plan_reference` naming the
/// offending plan node id (review finding #6).
async fn validate_node_ownership(
    tx: &Transaction<'_>,
    user_id: i32,
    nodes: &[ContinuityPlanNode],
) -> Result<(), ApiError> {
    // Issue refs: bulk ownership check via the central join-through-thread guard.
    let issue_nodes: Vec<&ContinuityPlanNode> = nodes
        .iter()
        .filter(|node| node.node_type == "issue")
        .collect();
    if !issue_nodes.is_empty() {
        let issue_ids: Vec<i32> = issue_nodes.iter().map(|node| node.ref_id).collect();
        let owned_rows = tx
            .query(
                "SELECT i.id FROM issues i JOIN threads t ON t.id = i.thread_id \
                 WHERE i.id = ANY($1::int[]) AND t.user_id = $2",
                &[&issue_ids, &user_id],
            )
            .await
            .map_err(db::query_error)?;
        let owned: std::collections::HashSet<i32> =
            owned_rows.iter().map(|row| row.get::<_, i32>(0)).collect();
        for node in issue_nodes {
            if !owned.contains(&node.ref_id) {
                return Err(dangling_node(&node.id));
            }
        }
    }

    for node in nodes {
        match node.node_type.as_str() {
            "issue" => continue,
            "thread" => {
                let owned = tx
                    .query_opt(
                        "SELECT id FROM threads WHERE id = $1 AND user_id = $2",
                        &[&node.ref_id, &user_id],
                    )
                    .await
                    .map_err(db::query_error)?
                    .is_some();
                if !owned {
                    return Err(dangling_node(&node.id));
                }
            }
            "crossover" => {
                let owned = tx
                    .query_opt(
                        "SELECT id FROM dependency_groups WHERE id = $1 AND user_id = $2",
                        &[&node.ref_id, &user_id],
                    )
                    .await
                    .map_err(db::query_error)?
                    .is_some();
                if !owned {
                    return Err(dangling_node(&node.id));
                }
            }
            _ => return Err(dangling_node(&node.id)),
        }
    }
    Ok(())
}

impl ContinuityPlanWrite {
    /// Port of Python `ContinuityPlanWrite.validate_structure` (422 on failure).
    ///
    /// Enforces the cross-field invariants that keep downstream Option E
    /// compiled-rule semantics well defined. Field-level constraints that
    /// Pydantic enforces before this validator (lengths, enums, positive ids)
    /// are checked here as well so the native path cannot persist invalid plans.
    pub fn validate_structure(&self) -> Result<(), ApiError> {
        use std::collections::{HashMap, HashSet};

        if self.name.trim().is_empty() || self.name.chars().count() > 200 {
            return Err(unprocessable("name must be 1-200 characters"));
        }
        if self.ordering_mode != "informational" && self.ordering_mode != "strict_sequential" {
            return Err(unprocessable(
                "ordering_mode must be informational or strict_sequential",
            ));
        }
        if self.lanes.len() > 100 || self.nodes.len() > 1000 {
            return Err(unprocessable("plan exceeds lane/node limits"));
        }

        let lane_ids: Vec<&str> = self.lanes.iter().map(|lane| lane.id.as_str()).collect();
        if lane_ids.len() != lane_ids.iter().collect::<HashSet<_>>().len() {
            return Err(unprocessable("lane ids must be unique"));
        }
        let lane_orders: Vec<i32> = self.lanes.iter().map(|lane| lane.order).collect();
        if lane_orders.len() != lane_orders.iter().collect::<HashSet<_>>().len() {
            return Err(unprocessable("lane order values must be unique"));
        }
        for lane in &self.lanes {
            if lane.id.is_empty() || lane.id.chars().count() > 80 {
                return Err(unprocessable("lane id must be 1-80 characters"));
            }
            if lane.name.is_empty() || lane.name.chars().count() > 120 {
                return Err(unprocessable("lane name must be 1-120 characters"));
            }
            if lane.order < 0 {
                return Err(unprocessable("lane order must be non-negative"));
            }
        }

        let node_ids: Vec<&str> = self.nodes.iter().map(|node| node.id.as_str()).collect();
        if node_ids.len() != node_ids.iter().collect::<HashSet<_>>().len() {
            return Err(unprocessable("node ids must be unique"));
        }
        let issue_refs: Vec<i32> = self
            .nodes
            .iter()
            .filter(|node| node.node_type == "issue")
            .map(|node| node.ref_id)
            .collect();
        if issue_refs.len() != issue_refs.iter().collect::<HashSet<_>>().len() {
            return Err(unprocessable("an issue may appear at most once in a plan"));
        }

        let known_lanes: HashSet<&str> = lane_ids.iter().copied().collect();
        for node in &self.nodes {
            if node.id.is_empty() || node.id.chars().count() > 80 {
                return Err(unprocessable("node id must be 1-80 characters"));
            }
            if node.ref_id <= 0 {
                return Err(unprocessable("node ref_id must be positive"));
            }
            if node.position < 0 {
                return Err(unprocessable("node position must be non-negative"));
            }
            if !matches!(node.node_type.as_str(), "issue" | "crossover" | "thread") {
                return Err(unprocessable("invalid node_type"));
            }
            if !known_lanes.contains(node.lane_id.as_str()) {
                return Err(unprocessable("every node must reference an existing lane"));
            }
        }

        let mut positions_by_lane: HashMap<&str, Vec<i32>> = HashMap::new();
        for node in &self.nodes {
            positions_by_lane
                .entry(node.lane_id.as_str())
                .or_default()
                .push(node.position);
        }
        if positions_by_lane
            .values()
            .any(|values| values.len() != values.iter().collect::<HashSet<_>>().len())
        {
            return Err(unprocessable(
                "node positions must be unique within each lane",
            ));
        }

        if self.ordering_mode == "strict_sequential" {
            if self.lanes.len() != 1 {
                return Err(unprocessable(
                    "strict sequential plans must use exactly one lane",
                ));
            }
            if self.nodes.iter().any(|node| node.node_type == "thread") {
                return Err(unprocessable(
                    "strict sequential plans may contain only issue/crossover nodes",
                ));
            }
            let mut positions: Vec<i32> = self.nodes.iter().map(|node| node.position).collect();
            positions.sort_unstable();
            if positions != (0..positions.len() as i32).collect::<Vec<i32>>() {
                return Err(unprocessable(
                    "strict sequential positions must be contiguous starting at zero",
                ));
            }
        }

        for node in &self.nodes {
            if node.is_checkpoint && node.node_type != "issue" {
                return Err(unprocessable(format!(
                    "checkpoint on node '{}' is only allowed on issue nodes",
                    node.id
                )));
            }
            if (node.checkpoint_target_ref_id.is_some()
                || !node.checkpoint_target_ref_ids.is_empty())
                && !node.is_checkpoint
            {
                return Err(unprocessable(format!(
                    "checkpoint target on node '{}' requires is_checkpoint",
                    node.id
                )));
            }
            if node.checkpoint_target_ref_ids.len()
                != node
                    .checkpoint_target_ref_ids
                    .iter()
                    .collect::<HashSet<_>>()
                    .len()
            {
                return Err(unprocessable(format!(
                    "checkpoint on node '{}' contains duplicate targets",
                    node.id
                )));
            }
        }

        let nodes_by_id: HashMap<&str, &ContinuityPlanNode> = self
            .nodes
            .iter()
            .map(|node| (node.id.as_str(), node))
            .collect();
        for node in &self.nodes {
            if node.convergence_gate.is_empty() {
                continue;
            }
            if !matches!(node.node_type.as_str(), "issue" | "crossover") {
                return Err(unprocessable(format!(
                    "convergence gate on node '{}' is only allowed on issue/crossover nodes",
                    node.id
                )));
            }
            let gate_ids: Vec<&str> = node
                .convergence_gate
                .iter()
                .filter_map(|target| target.get("node_id").and_then(|v| v.as_str()))
                .collect();
            if gate_ids.len() != node.convergence_gate.len() {
                return Err(unprocessable("invalid convergence gate target"));
            }
            if gate_ids.len() != gate_ids.iter().collect::<HashSet<_>>().len() {
                return Err(unprocessable(format!(
                    "convergence gate on node '{}' contains duplicate targets",
                    node.id
                )));
            }
            for target_id in gate_ids {
                if target_id == node.id {
                    return Err(unprocessable(format!(
                        "convergence gate on node '{}' cannot wait for itself",
                        node.id
                    )));
                }
                let target_node = nodes_by_id.get(target_id).ok_or_else(|| {
                    unprocessable(format!(
                        "convergence gate on node '{}' references unknown node '{}'",
                        node.id, target_id
                    ))
                })?;
                if !matches!(target_node.node_type.as_str(), "issue" | "crossover") {
                    return Err(unprocessable(format!(
                        "convergence gate on node '{}' references node '{}' of type '{}'; \
                         convergence targets must be issue/crossover nodes",
                        node.id, target_id, target_node.node_type
                    )));
                }
            }
        }
        Ok(())
    }
}

/// Advisory source metadata from one node — mirrors `_source_metadata_for_node`.
fn source_metadata_for_node(node: &ContinuityPlanNode) -> Option<serde_json::Value> {
    let mut map = serde_json::Map::new();
    if let Some(value) = &node.source_role {
        map.insert(
            "source_role".into(),
            serde_json::Value::String(value.clone()),
        );
    }
    if let Some(value) = &node.source_confidence {
        map.insert(
            "source_confidence".into(),
            serde_json::Value::String(value.clone()),
        );
    }
    if let Some(value) = &node.source_explanation {
        map.insert(
            "source_explanation".into(),
            serde_json::Value::String(value.clone()),
        );
    }
    if let Some(value) = &node.source_story_arc_ids {
        map.insert(
            "source_story_arc_ids".into(),
            serde_json::to_value(value).unwrap_or(serde_json::Value::Null),
        );
    }
    if let Some(value) = &node.source_target_story_arc_id {
        map.insert(
            "source_target_story_arc_id".into(),
            serde_json::Value::String(value.clone()),
        );
    }
    if map.is_empty() {
        None
    } else {
        Some(serde_json::Value::Object(map))
    }
}

/// Rebuild normalized membership, source snapshots and placements for one plan.
/// Mirrors `rebuild_plan_membership` (issue rows only; non-issue nodes keep no
/// normalized membership until an explicit mapping exists).
pub(crate) async fn rebuild_plan_membership(
    tx: &Transaction<'_>,
    plan_id: i32,
    nodes: &[ContinuityPlanNode],
) -> Result<(), ApiError> {
    use std::collections::{BTreeMap, BTreeSet, HashSet};

    let mut seen_issues = HashSet::new();
    for node in nodes {
        if node.node_type == "issue" && !seen_issues.insert(node.ref_id) {
            return Err(domain_conflict(serde_json::json!({
                "code": "duplicate_plan_issue",
                "issue_id": node.ref_id,
            })));
        }
    }

    // Recovery relink records owned Reading List authority (`custom-cbl:<id>`)
    // independently of plan nodes. Preserve that provenance across authoring
    // saves: rebuilding only from node-carried paths would silently erase a
    // former authority and make an orphaned plan look never-linked.
    let authoritative_source =
        "raw_source_path LIKE 'custom-cbl:%' OR custom_cbl_list_id IS NOT NULL";
    // Placement rows are always rebuilt from the submitted nodes. Keeping any
    // old row would duplicate a still-present tuple or leave a removed one
    // behind, so clear all of them while preserving the source history itself.
    tx.execute(
        "DELETE FROM reading_plan_source_placements WHERE plan_id = $1",
        &[&plan_id],
    )
    .await
    .map_err(db::query_error)?;
    tx.execute(
        &format!(
            "DELETE FROM reading_plan_sources WHERE plan_id = $1
              AND NOT ({authoritative_source})"
        ),
        &[&plan_id],
    )
    .await
    .map_err(db::query_error)?;
    tx.execute(
        "DELETE FROM reading_plan_issues WHERE plan_id = $1",
        &[&plan_id],
    )
    .await
    .map_err(db::query_error)?;

    // Source snapshots, deduplicated by raw path, plus position observations.
    let mut source_paths: BTreeMap<String, Vec<Option<i32>>> = BTreeMap::new();
    for node in nodes {
        if let Some(placements) = &node.source_cbl_placements {
            for placement in placements {
                let path = placement
                    .get("source_path")
                    .or_else(|| placement.get("path"))
                    .and_then(|value| value.as_str());
                if let Some(path) = path {
                    let position = placement
                        .get("position")
                        .and_then(|value| value.as_i64())
                        .map(|value| value as i32);
                    source_paths
                        .entry(path.to_string())
                        .or_default()
                        .push(position);
                }
            }
        }
        if let Some(paths) = &node.source_paths {
            for path in paths {
                if !path.is_empty() {
                    source_paths.entry(path.clone()).or_default();
                }
            }
        }
    }

    // One set-based read of preserved authority sources; never a query per
    // node path (AGENTS.md: no SQL inside loops / no per-item round trips).
    let preserved_sources: BTreeMap<String, i32> = tx
        .query(
            &format!(
                "SELECT raw_source_path, id FROM reading_plan_sources
                  WHERE plan_id=$1 AND ({authoritative_source})"
            ),
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| (row.get(0), row.get(1)))
        .collect();
    let mut source_ids: BTreeMap<String, i32> = BTreeMap::new();
    for path in source_paths.keys() {
        // A preserved Reading List source already carries this path; reuse it
        // so its (possibly now-removed) List identity survives the save.
        if let Some(id) = preserved_sources.get(path) {
            source_ids.insert(path.clone(), *id);
            continue;
        }
        let row = tx
            .query_one(
                "INSERT INTO reading_plan_sources (plan_id, raw_source_path, recorded_at)
                 VALUES ($1, $2, NOW()) RETURNING id",
                &[&plan_id, path],
            )
            .await
            .map_err(db::query_error)?;
        source_ids.insert(path.clone(), row.get(0));
    }

    for node in nodes {
        if node.node_type != "issue" {
            continue;
        }
        let metadata = source_metadata_for_node(node);
        tx.execute(
            "INSERT INTO reading_plan_issues
             (plan_id, occurrence_id, issue_id, lane_id, display_position,
              label, reader_role, reader_optional, is_checkpoint, source_metadata_json)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
            &[
                &plan_id,
                &node.id,
                &node.ref_id,
                &node.lane_id,
                &node.position,
                &node.label,
                &node.reader_role,
                &node.reader_optional,
                &node.is_checkpoint,
                &metadata,
            ],
        )
        .await
        .map_err(db::query_error)?;

        // Position observations for this occurrence.
        let mut placements: Vec<(String, Option<i32>)> = Vec::new();
        if let Some(values) = &node.source_cbl_placements {
            for placement in values {
                let path = placement
                    .get("source_path")
                    .or_else(|| placement.get("path"))
                    .and_then(|value| value.as_str());
                if let Some(path) = path {
                    if let Some(id) = source_ids.get(path) {
                        let position = placement
                            .get("position")
                            .and_then(|value| value.as_i64())
                            .map(|value| value as i32);
                        placements.push((path.to_string(), position));
                        let _ = id;
                    }
                }
            }
        }
        if let Some(paths) = &node.source_paths {
            for path in paths {
                if !path.is_empty() && !placements.iter().any(|(p, _)| p == path) {
                    placements.push((path.clone(), None));
                }
            }
        }
        let mut unique: BTreeSet<(String, Option<i32>)> = BTreeSet::new();
        for placement in placements {
            unique.insert(placement);
        }
        for (path, position) in unique {
            if let Some(source_id) = source_ids.get(&path) {
                tx.execute(
                    "INSERT INTO reading_plan_source_placements
                     (plan_id, occurrence_id, plan_source_id, source_position)
                     VALUES ($1, $2, $3, $4)",
                    &[&plan_id, &node.id, source_id, &position],
                )
                .await
                .map_err(db::query_error)?;
            }
        }
    }
    Ok(())
}

/// Reconstruct editor nodes the way Python `editor_nodes_for_plan` +
/// `labeled_plan_nodes` do: normalized membership is authoritative for issue
/// nodes, non-issue nodes survive from the stored JSON, and blank labels are
/// filled from the owned issue/thread pair. Called by GET/create/update so the
/// wire response never returns raw, stale `nodes_json`.
async fn editor_nodes_for_plan(
    tx: &Transaction<'_>,
    plan_id: i32,
    stored_nodes: &serde_json::Value,
) -> Result<Vec<ContinuityPlanNode>, ApiError> {
    let member_rows = tx
        .query(
            "SELECT occurrence_id, issue_id, lane_id, display_position, label, \
             reader_role, reader_optional, is_checkpoint, source_metadata_json \
             FROM reading_plan_issues WHERE plan_id = $1",
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;
    if member_rows.is_empty() {
        return Ok(serde_json::from_value(stored_nodes.clone()).unwrap_or_default());
    }

    let mut json_by_id: std::collections::HashMap<String, serde_json::Value> =
        std::collections::HashMap::new();
    let mut extra_non_issue: Vec<serde_json::Value> = Vec::new();
    if let Some(nodes) = stored_nodes.as_array() {
        for raw in nodes {
            match raw.get("node_type").and_then(|value| value.as_str()) {
                Some("issue") => {
                    if let Some(id) = raw.get("id").and_then(|value| value.as_str()) {
                        if !id.is_empty() {
                            json_by_id.insert(id.to_string(), raw.clone());
                        }
                    }
                }
                Some("crossover") | Some("thread") => extra_non_issue.push(raw.clone()),
                _ => {}
            }
        }
    }

    let mut nodes: Vec<ContinuityPlanNode> = Vec::new();
    for row in &member_rows {
        let occurrence_id: String = row.get(0);
        let mut overlay = json_by_id
            .get(&occurrence_id)
            .cloned()
            .unwrap_or_else(|| serde_json::json!({}));
        if let Some(map) = overlay.as_object_mut() {
            map.insert(
                "id".into(),
                serde_json::Value::String(occurrence_id.clone()),
            );
            map.insert(
                "node_type".into(),
                serde_json::Value::String("issue".into()),
            );
            map.insert("ref_id".into(), serde_json::json!(row.get::<_, i32>(1)));
            map.insert("lane_id".into(), serde_json::json!(row.get::<_, String>(2)));
            map.insert("position".into(), serde_json::json!(row.get::<_, i32>(3)));
            map.insert(
                "is_checkpoint".into(),
                serde_json::json!(row.get::<_, bool>(7)),
            );
            if let Some(label) = row.get::<_, Option<String>>(4) {
                map.insert("label".into(), serde_json::Value::String(label));
            }
            if let Some(role) = row.get::<_, Option<String>>(5) {
                map.insert("reader_role".into(), serde_json::Value::String(role));
            }
            if let Some(optional) = row.get::<_, Option<bool>>(6) {
                map.insert("reader_optional".into(), serde_json::json!(optional));
            }
            if let Some(metadata) = row.get::<_, Option<serde_json::Value>>(8) {
                if let Some(metadata) = metadata.as_object() {
                    for (key, value) in metadata {
                        if map.get(key).is_none_or(|value| value.is_null()) {
                            map.insert(key.clone(), value.clone());
                        }
                    }
                }
            }
        }
        let node = serde_json::from_value::<ContinuityPlanNode>(overlay).unwrap_or_else(|_| {
            ContinuityPlanNode {
                id: occurrence_id.clone(),
                node_type: "issue".to_string(),
                ref_id: row.get(1),
                lane_id: row.get(2),
                position: row.get(3),
                label: row.get(4),
                source_role: None,
                source_confidence: None,
                source_explanation: None,
                source_paths: None,
                source_cbl_placements: None,
                source_story_arc_ids: None,
                source_target_story_arc_id: None,
                reader_role: row.get(5),
                reader_optional: row.get(6),
                is_checkpoint: row.get(7),
                checkpoint_target_ref_id: None,
                checkpoint_target_ref_ids: Vec::new(),
                convergence_gate: Vec::new(),
            }
        });
        nodes.push(node);
    }
    for raw in extra_non_issue {
        if let Ok(node) = serde_json::from_value::<ContinuityPlanNode>(raw) {
            nodes.push(node);
        }
    }
    nodes.sort_by(|a, b| (a.position, &a.lane_id, &a.id).cmp(&(b.position, &b.lane_id, &b.id)));

    let missing_ids: Vec<i32> = nodes
        .iter()
        .filter(|node| {
            node.node_type == "issue" && node.label.as_deref().unwrap_or_default().trim().is_empty()
        })
        .map(|node| node.ref_id)
        .collect();
    if !missing_ids.is_empty() {
        let label_rows = tx
            .query(
                "SELECT i.id, t.title, i.issue_number FROM issues i \
                 JOIN threads t ON t.id = i.thread_id WHERE i.id = ANY($1::int[])",
                &[&missing_ids],
            )
            .await
            .map_err(db::query_error)?;
        let mut labels: std::collections::HashMap<i32, String> = std::collections::HashMap::new();
        for row in &label_rows {
            let number = row
                .get::<_, String>(2)
                .trim_start_matches('#')
                .trim()
                .to_string();
            let title: String = row.get(1);
            let label = match (title.trim(), number.as_str()) {
                (series, n) if !series.is_empty() && !n.is_empty() => format!("{series} #{n}"),
                (series, _) if !series.is_empty() => series.to_string(),
                (_, n) => n.to_string(),
            };
            labels.insert(row.get::<_, i32>(0), label);
        }
        for node in &mut nodes {
            if node.node_type == "issue"
                && node.label.as_deref().unwrap_or_default().trim().is_empty()
            {
                if let Some(label) = labels.get(&node.ref_id) {
                    node.label = Some(label.clone());
                }
            }
        }
    }
    Ok(nodes)
}


// ============================================================================
// GET /api/v2/continuity-plans/ - List plans
// ============================================================================

#[utoipa::path(
    get,
    path = "/api/v2/continuity-plans/",
    tag = "continuity-plans",
    operation_id = "continuity_plans_list",
    responses(
        (status = 200, description = "List of continuity plans", body = Vec<ContinuityPlanListItem>),
        (status = 401, description = "Not authenticated"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub async fn list_continuity_plans(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> Result<Json<Vec<ContinuityPlanListItem>>, ApiError> {
    let conn = db::checkout(&state).await?;
    let rows = conn
        .query(
            r#"
            SELECT p.id, p.name, p.ordering_mode, p.lanes_json, p.nodes_json, p.updated_at
            FROM continuity_plans p
            WHERE p.user_id = $1
            ORDER BY p.updated_at DESC
            "#,
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;

    let mut plans = Vec::with_capacity(rows.len());
    for row in &rows {
        let lanes_json_val: serde_json::Value = row.get(3);
        let lanes_json: Vec<serde_json::Value> =
            serde_json::from_value(lanes_json_val).unwrap_or_default();
        let lane_count = lanes_json.len().max(1);

        let nodes_json_val: serde_json::Value = row.get(4);
        let nodes: Vec<serde_json::Value> =
            serde_json::from_value(nodes_json_val).unwrap_or_default();
        let step_count = nodes.len() as i32;

        // Python `plan_source_paths`: retain CBL placement paths first, then
        // explicit source paths, in source order and deduplicated.
        let mut source_paths: Vec<String> = Vec::new();
        for node in &nodes {
            if let Some(placements) = node.get("source_cbl_placements").and_then(|v| v.as_array()) {
                for placement in placements {
                    if let Some(path) = placement.get("source_path").and_then(|v| v.as_str()) {
                        if !source_paths.iter().any(|existing| existing == path) {
                            source_paths.push(path.to_string());
                        }
                    }
                }
            }
            if let Some(paths) = node.get("source_paths").and_then(|v| v.as_array()) {
                for path in paths.iter().filter_map(|value| value.as_str()) {
                    if !source_paths.iter().any(|existing| existing == path) {
                        source_paths.push(path.to_string());
                    }
                }
            }
        }

        // Python `load_reading_plan_source_names`: resolve `custom-cbl:<id>`
        // references to names of Reading Lists owned by this user only.
        let list_ids: Vec<i32> = source_paths
            .iter()
            .filter_map(|path| {
                path.strip_prefix("custom-cbl:")
                    .and_then(|rest| rest.parse::<i32>().ok())
            })
            .collect();
        let mut source_names = serde_json::Map::new();
        if !list_ids.is_empty() {
            let name_rows = conn
                .query(
                    "SELECT id, name FROM custom_cbl_lists \
                     WHERE user_id = $1 AND id = ANY($2::int[])",
                    &[&user.id(), &list_ids],
                )
                .await
                .map_err(db::query_error)?;
            for name_row in &name_rows {
                let path = format!("custom-cbl:{}", name_row.get::<_, i32>(0));
                source_names.insert(path, serde_json::json!(name_row.get::<_, String>(1)));
            }
        }

        plans.push(ContinuityPlanListItem {
            id: row.get(0),
            name: row.get(1),
            ordering_mode: row.get(2),
            lane_count: lane_count as i32,
            step_count,
            source_paths,
            source_names: serde_json::Value::Object(source_names),
            updated_at: iso_utc(row.get::<_, DateTime<Utc>>(5)),
        });
    }

    Ok(Json(plans))
}

// ============================================================================
// POST /api/v2/continuity-plans/ - Create plan
// ============================================================================

#[utoipa::path(
    post,
    path = "/api/v2/continuity-plans/",
    tag = "continuity-plans",
    operation_id = "continuity_plans_create",
    request_body = ContinuityPlanWrite,
    responses(
        (status = 201, description = "Created continuity plan", body = ContinuityPlanResponse),
        (status = 400, description = "Validation error"),
        (status = 409, description = "Conflict"),
        (status = 401, description = "Not authenticated"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub async fn create_continuity_plan(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(payload): Json<ContinuityPlanWrite>,
) -> Result<(StatusCode, Json<ContinuityPlanResponse>), ApiError> {
    payload.validate_structure()?;
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    lock_continuity_graph(&tx, user.id()).await?;

    // Ownership of every referenced node (issue/thread/crossover) must match
    // the Python `validate_node_ownership` guard, including the 422 envelope.
    if let Err(err) = validate_node_ownership(&tx, user.id(), &payload.nodes).await {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(err);
    }

    // Validate lane uniqueness
    let lane_ids: Vec<&String> = payload.lanes.iter().map(|l| &l.id).collect();
    if lane_ids.len()
        != lane_ids
            .iter()
            .collect::<std::collections::HashSet<_>>()
            .len()
    {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("Lane ids must be unique"));
    }

    // Check for duplicate node ids
    let node_ids: Vec<&String> = payload.nodes.iter().map(|n| &n.id).collect();
    if node_ids.len()
        != node_ids
            .iter()
            .collect::<std::collections::HashSet<_>>()
            .len()
    {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("Node ids must be unique"));
    }

    // Create the plan
    let lanes_json: Vec<serde_json::Value> = payload
        .lanes
        .iter()
        .map(|l| serde_json::to_value(l).unwrap_or_default())
        .collect();
    let nodes_json: Vec<serde_json::Value> = payload
        .nodes
        .iter()
        .map(|n| serde_json::to_value(n).unwrap_or_default())
        .collect();
    // tokio-postgres needs a `serde_json::Value` (not a String) for a `json`
    // parameter — a `::json` cast alone does not make a String encodable.
    let lanes_value = serde_json::Value::Array(lanes_json);
    let nodes_value = serde_json::Value::Array(nodes_json);

    let row = tx
        .query_one(
            r#"
            INSERT INTO continuity_plans (user_id, name, ordering_mode, lanes_json, nodes_json, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, NOW(), NOW())
            RETURNING id, user_id, name, ordering_mode, lanes_json, nodes_json, created_at, updated_at
            "#,
            &[
                &user.id(),
                &payload.name,
                &payload.ordering_mode,
                &lanes_value,
                &nodes_value,
            ],
        )
        .await
        .map_err(db::query_error)?;

    // Extract values before commit to avoid MissingGreenlet issues.
    let plan_id: i32 = row.get(0);
    let (user_id, name, ordering_mode) = (
        row.get::<_, i32>(1),
        row.get::<_, String>(2),
        row.get::<_, String>(3),
    );
    let lanes_out: serde_json::Value = row.get(4);
    let created_at = iso_utc(row.get::<_, DateTime<Utc>>(6));
    let updated_at = iso_utc(row.get::<_, DateTime<Utc>>(7));

    // Rebuild normalized membership in the same transaction. The Reading List
    // engine is the sole eligibility evaluator: saving a plan never compiles
    // continuity rules or canonical dependency edges.
    if let Err(error) = rebuild_plan_membership(&tx, plan_id, &payload.nodes).await {
        let _ = tx.rollback().await;
        return Err(error);
    }

    // Python `editor_plan_response`: membership-authoritative, labeled nodes.
    let nodes = editor_nodes_for_plan(&tx, plan_id, &nodes_value).await?;
    let plan_response = ContinuityPlanResponse {
        id: plan_id,
        user_id,
        name,
        ordering_mode,
        lanes: serde_json::from_value(lanes_out).unwrap_or_default(),
        nodes,
        created_at,
        updated_at,
    };

    tx.commit().await.map_err(db::query_error)?;
    Ok((StatusCode::CREATED, Json(plan_response)))
}

// ============================================================================
// GET /api/v2/continuity-plans/{plan_id} - Get plan
// ============================================================================

#[utoipa::path(
    get,
    path = "/api/v2/continuity-plans/{plan_id}",
    tag = "continuity-plans",
    operation_id = "continuity_plans_get",
    params(("plan_id" = i32, Path, description = "Continuity plan identifier")),
    responses(
        (status = 200, description = "Continuity plan", body = ContinuityPlanResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub async fn get_continuity_plan(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
) -> Result<Json<ContinuityPlanResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    let row = tx
        .query_opt(
            r#"
            SELECT id, user_id, name, ordering_mode, lanes_json, nodes_json, created_at, updated_at
            FROM continuity_plans
            WHERE id = $1 AND user_id = $2
            "#,
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| not_found(format!("Continuity plan {plan_id} not found")))?;

    let stored_nodes: serde_json::Value = row.get(5);
    let nodes = editor_nodes_for_plan(&tx, plan_id, &stored_nodes).await?;
    let response = ContinuityPlanResponse {
        id: row.get(0),
        user_id: row.get(1),
        name: row.get(2),
        ordering_mode: row.get(3),
        lanes: serde_json::from_value(row.get(4)).unwrap_or_default(),
        nodes,
        created_at: iso_utc(row.get::<_, DateTime<Utc>>(6)),
        updated_at: iso_utc(row.get::<_, DateTime<Utc>>(7)),
    };
    tx.commit().await.map_err(db::query_error)?;

    Ok(Json(response))
}

// ============================================================================
// PUT /api/v2/continuity-plans/{plan_id} - Update plan
// ============================================================================

#[utoipa::path(
    put,
    path = "/api/v2/continuity-plans/{plan_id}",
    tag = "continuity-plans",
    operation_id = "continuity_plans_update",
    params(("plan_id" = i32, Path, description = "Continuity plan identifier")),
    request_body = ContinuityPlanWrite,
    responses(
        (status = 200, description = "Updated continuity plan", body = ContinuityPlanResponse),
        (status = 400, description = "Validation error"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan not found"),
        (status = 409, description = "Conflict"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub async fn update_continuity_plan(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
    Json(mut payload): Json<ContinuityPlanWrite>,
) -> Result<Json<ContinuityPlanResponse>, ApiError> {
    payload.validate_structure()?;
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    lock_continuity_graph(&tx, user.id()).await?;

    // Check plan ownership and get the current version and ordering mode.
    let existing = tx
        .query_opt(
            "SELECT id, lanes_json, nodes_json, ordering_mode, updated_at
             FROM continuity_plans WHERE id = $1 AND user_id = $2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| not_found(format!("Continuity plan {plan_id} not found")))?;

    let expected_version: Option<String> = payload.expected_updated_at.clone();
    let current_updated_at: DateTime<Utc> = existing.get(4);
    let current_updated_at_iso = iso_utc(current_updated_at);
    let prior_lanes: serde_json::Value = existing.get(1);
    let prior_nodes: serde_json::Value = existing.get(2);

    // Python `guard_plan_write` compares timezone-aware UTC instants, so an
    // ISO token such as `2026-08-12T00:00:00Z` matches the stored instant even
    // though Postgres text differs. The 409 detail uses `isoformat()`.
    if let Some(ref expected) = expected_version {
        let matches = parse_aware_utc(expected).is_some_and(|value| value == current_updated_at);
        if !matches {
            tx.rollback().await.map_err(db::query_error)?;
            return Err(domain_conflict(serde_json::json!({
                "code": "plan_version_conflict",
                "expected_updated_at": current_updated_at_iso,
            })));
        }
    }

    // `guard_plan_write`: reject a GET-then-save of leftover nodes_json that
    // would resurrect issues no longer in normalized membership.
    let incoming_ids: std::collections::HashSet<i32> = payload
        .nodes
        .iter()
        .filter(|node| node.node_type == "issue")
        .map(|node| node.ref_id)
        .collect();
    let membership_ids: std::collections::HashSet<i32> = tx
        .query(
            "SELECT DISTINCT issue_id FROM reading_plan_issues WHERE plan_id = $1",
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| row.get::<_, i32>(0))
        .collect();
    let json_ids: std::collections::HashSet<i32> = prior_nodes
        .as_array()
        .map(|nodes| {
            nodes
                .iter()
                .filter(|node| {
                    node.get("node_type").and_then(|value| value.as_str()) == Some("issue")
                })
                .filter_map(|node| node.get("ref_id").and_then(|value| value.as_i64()))
                .map(|value| value as i32)
                .collect()
        })
        .unwrap_or_default();
    if !membership_ids.is_empty() && incoming_ids == json_ids && incoming_ids != membership_ids {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(domain_conflict(serde_json::json!({
            "code": "stale_plan_nodes",
            "membership_issue_count": membership_ids.len(),
            "payload_issue_count": incoming_ids.len(),
        })));
    }

    // Ownership of every referenced node (issue/thread/crossover) must match
    // the Python `validate_node_ownership` guard, including the 422 envelope.
    if let Err(err) = validate_node_ownership(&tx, user.id(), &payload.nodes).await {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(err);
    }

    // Preserve server-owned migration proof across ordinary lane replacement.
    let mut server_contracts: std::collections::HashMap<String, serde_json::Value> =
        std::collections::HashMap::new();
    if let Some(lanes) = prior_lanes.as_array() {
        for lane in lanes {
            if let (Some(id), Some(contract)) = (
                lane.get("id").and_then(|value| value.as_str()),
                lane.get("migration_contract"),
            ) {
                if !contract.is_null() {
                    server_contracts.insert(id.to_string(), contract.clone());
                }
            }
        }
    }
    for lane in &mut payload.lanes {
        if let Some(contract) = server_contracts.get(&lane.id) {
            lane.migration_contract = Some(contract.clone());
        }
    }

    let lanes_json: Vec<serde_json::Value> = payload
        .lanes
        .iter()
        .map(|l| serde_json::to_value(l).unwrap_or_default())
        .collect();
    let nodes_json: Vec<serde_json::Value> = payload
        .nodes
        .iter()
        .map(|n| serde_json::to_value(n).unwrap_or_default())
        .collect();
    let lanes_value = serde_json::Value::Array(lanes_json);
    let nodes_value = serde_json::Value::Array(nodes_json);

    tx.execute(
        r#"
        UPDATE continuity_plans
        SET name = $1, ordering_mode = $2, lanes_json = $3, nodes_json = $4, updated_at = NOW()
        WHERE id = $5 AND user_id = $6
        "#,
        &[
            &payload.name,
            &payload.ordering_mode,
            &lanes_value,
            &nodes_value,
            &plan_id,
            &user.id(),
        ],
    )
    .await
    .map_err(db::query_error)?;

    let row = tx
        .query_one(
            r#"
            SELECT id, user_id, name, ordering_mode, lanes_json, created_at, updated_at
            FROM continuity_plans WHERE id = $1
            "#,
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;

    if let Err(error) = rebuild_plan_membership(&tx, plan_id, &payload.nodes).await {
        let _ = tx.rollback().await;
        return Err(error);
    }

    // Python `editor_plan_response`: membership-authoritative, labeled nodes.
    let nodes = editor_nodes_for_plan(&tx, plan_id, &nodes_value).await?;
    let plan_response = ContinuityPlanResponse {
        id: row.get(0),
        user_id: row.get(1),
        name: row.get(2),
        ordering_mode: row.get(3),
        lanes: serde_json::from_value(row.get(4)).unwrap_or_default(),
        nodes,
        created_at: iso_utc(row.get::<_, DateTime<Utc>>(5)),
        updated_at: iso_utc(row.get::<_, DateTime<Utc>>(6)),
    };

    tx.commit().await.map_err(db::query_error)?;

    Ok(Json(plan_response))
}

// ============================================================================
// DELETE /api/v2/continuity-plans/{plan_id} - Delete plan
// ============================================================================

#[utoipa::path(
    delete,
    path = "/api/v2/continuity-plans/{plan_id}",
    tag = "continuity-plans",
    operation_id = "continuity_plans_delete",
    params(("plan_id" = i32, Path, description = "Continuity plan identifier")),
    responses(
        (status = 204, description = "Plan deleted"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub async fn delete_continuity_plan(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
) -> Result<StatusCode, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    lock_continuity_graph(&tx, user.id()).await?;

    // Check plan ownership
    tx.query_opt(
        "SELECT id FROM continuity_plans WHERE id = $1 AND user_id = $2",
        &[&plan_id, &user.id()],
    )
    .await
    .map_err(db::query_error)?
    .ok_or_else(|| not_found(format!("Continuity plan {plan_id} not found")))?;

    // Remove any legacy plan-owned rule rows left by earlier releases. The
    // Reading List engine compiled no new rules, so there are no edges to
    // retire here.
    let marker = format!("continuity-plan:{plan_id}");

    // Tag assignments point at polymorphic ids with no foreign key.
    tx.execute(
        "DELETE FROM tag_assignments WHERE target_type = 'continuity_plan' AND target_id = $1",
        &[&plan_id],
    )
    .await
    .map_err(db::query_error)?;

    // Delete plan-linked dependencies
    tx.execute(
        "DELETE FROM reading_plan_dependencies WHERE plan_id = $1",
        &[&plan_id],
    )
    .await
    .map_err(db::query_error)?;

    // Delete reading plan issues
    tx.execute(
        "DELETE FROM reading_plan_issues WHERE plan_id = $1",
        &[&plan_id],
    )
    .await
    .map_err(db::query_error)?;

    // Delete continuity rules owned by this plan
    tx.execute(
        "DELETE FROM continuity_rules WHERE note = $1 AND user_id = $2",
        &[&marker, &user.id()],
    )
    .await
    .map_err(db::query_error)?;

    // Delete plan sources
    tx.execute(
        "DELETE FROM reading_plan_sources WHERE plan_id = $1",
        &[&plan_id],
    )
    .await
    .map_err(db::query_error)?;

    // Delete the plan
    tx.execute("DELETE FROM continuity_plans WHERE id = $1", &[&plan_id])
        .await
        .map_err(db::query_error)?;

    tx.commit().await.map_err(db::query_error)?;
    Ok(StatusCode::NO_CONTENT)
}

// ============================================================================
// POST /api/v2/continuity-plans/from-reading-order - Adopt reading order
// ============================================================================

#[utoipa::path(
    post,
    path = "/api/v2/continuity-plans/from-reading-order",
    tag = "continuity-plans",
    operation_id = "continuity_plans_adopt_reading_order",
    request_body = ReadingOrderAdoptRequest,
    responses(
        (status = 201, description = "Created continuity plan from reading order", body = ContinuityPlanResponse),
        (status = 400, description = "Validation error"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Reading order not found"),
        (status = 409, description = "Conflict"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub async fn adopt_reading_order(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(payload): Json<ReadingOrderAdoptRequest>,
) -> Result<(StatusCode, Json<ContinuityPlanResponse>), ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    lock_continuity_graph(&tx, user.id()).await?;

    // Load the reading order (owned by the authenticated user).
    let order = tx
        .query_opt(
            "SELECT id, name FROM reading_orders WHERE id = $1 AND user_id = $2",
            &[&payload.reading_order_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| {
            not_found(format!(
                "Reading order {} not found",
                payload.reading_order_id
            ))
        })?;

    let order_id: i32 = order.get(0);
    let order_name: String = order.get(1);

    // Reading order items in canonical order (position, id), preserving item id
    // for node ids (Python: `ro-{item.id}`).
    let items = tx
        .query(
            "SELECT id, thread_id, position FROM reading_order_items \
             WHERE reading_order_id = $1 ORDER BY position, id",
            &[&order_id],
        )
        .await
        .map_err(db::query_error)?;

    // Reject duplicate threads before mutation (409 duplicate_thread).
    let mut seen_threads = std::collections::HashSet::new();
    let mut duplicates: Vec<i32> = Vec::new();
    for item in &items {
        let thread_id: i32 = item.get(1);
        if !seen_threads.insert(thread_id) && !duplicates.contains(&thread_id) {
            duplicates.push(thread_id);
        }
    }
    if !duplicates.is_empty() {
        tx.rollback().await.map_err(db::query_error)?;
        duplicates.sort_unstable();
        return Err(domain_conflict(serde_json::json!({
            "code": "duplicate_thread",
            "reading_order_id": order_id,
            "duplicate_thread_ids": duplicates,
            "message": "Reading order contains duplicate threads; deduplicate before adoption.",
        })));
    }

    // Dangling/non-owned thread references are rejected with 422
    // dangling_plan_reference naming the first offending node id (ro-{item.id}).
    if !items.is_empty() {
        let thread_ids: Vec<i32> = items.iter().map(|item| item.get(1)).collect();
        let owned_rows = tx
            .query(
                "SELECT id FROM threads WHERE id = ANY($1::int[]) AND user_id = $2",
                &[&thread_ids, &user.id()],
            )
            .await
            .map_err(db::query_error)?;
        let owned: std::collections::HashSet<i32> =
            owned_rows.iter().map(|row| row.get::<_, i32>(0)).collect();
        if let Some(first) = items
            .iter()
            .find(|item| !owned.contains(&item.get::<_, i32>(1)))
        {
            tx.rollback().await.map_err(db::query_error)?;
            let item_id: i32 = first.get(0);
            return Err(dangling_node(&format!("ro-{item_id}")));
        }
    }

    let resolved_name = payload
        .plan_name
        .as_deref()
        .map(str::trim)
        .filter(|name| !name.is_empty())
        .map(str::to_string)
        .unwrap_or_else(|| {
            let trimmed = order_name.trim();
            if trimmed.is_empty() {
                format!("From reading order {order_id}")
            } else {
                trimmed.to_string()
            }
        });

    let lane_id = payload.lane_id.as_deref().unwrap_or("adopted").to_string();
    let lane_name = payload
        .lane_name
        .as_deref()
        .unwrap_or("Adopted")
        .to_string();

    // Build thread nodes matching Python adoption (ro-{reading_order_item.id}).
    let mut nodes: Vec<serde_json::Value> = Vec::with_capacity(items.len());
    for (idx, item) in items.iter().enumerate() {
        let item_id: i32 = item.get(0);
        let thread_id: i32 = item.get(1);
        nodes.push(serde_json::json!({
            "id": format!("ro-{item_id}"),
            "node_type": "thread",
            "ref_id": thread_id,
            "lane_id": lane_id,
            "position": idx as i32,
            "label": null,
            "source_role": null,
            "source_confidence": null,
            "source_explanation": null,
            "source_paths": null,
            "source_cbl_placements": null,
            "source_story_arc_ids": null,
            "source_target_story_arc_id": null,
            "reader_role": null,
            "reader_optional": null,
            "is_checkpoint": false,
            "checkpoint_target_ref_id": null,
            "checkpoint_target_ref_ids": [],
            "convergence_gate": []
        }));
    }
    let lanes_value = serde_json::Value::Array(vec![serde_json::json!({
        "id": lane_id,
        "name": lane_name,
        "order": 0
    })]);
    let nodes_value = serde_json::Value::Array(nodes);

    let row = tx
        .query_one(
            r#"
            INSERT INTO continuity_plans (user_id, name, ordering_mode, lanes_json, nodes_json, created_at, updated_at)
            VALUES ($1, $2, 'informational', $3, $4, NOW(), NOW())
            RETURNING id, user_id, name, ordering_mode, lanes_json, nodes_json, created_at, updated_at
            "#,
            &[&user.id(), &resolved_name, &lanes_value, &nodes_value],
        )
        .await
        .map_err(db::query_error)?;

    tx.commit().await.map_err(db::query_error)?;

    let result = ContinuityPlanResponse {
        id: row.get(0),
        user_id: row.get(1),
        name: row.get(2),
        ordering_mode: row.get(3),
        lanes: serde_json::from_value(row.get(4)).unwrap_or_default(),
        nodes: serde_json::from_value(row.get(5)).unwrap_or_default(),
        created_at: iso_utc(row.get::<_, DateTime<Utc>>(6)),
        updated_at: iso_utc(row.get::<_, DateTime<Utc>>(7)),
    };

    Ok((StatusCode::CREATED, Json(result)))
}

// ============================================================================
// GET /api/v2/continuity-plans/{plan_id}/membership - Get membership
// ============================================================================

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReadingPlanMemberIssue {
    pub occurrence_id: String,
    pub issue_id: i32,
    pub lane_id: String,
    pub display_position: i32,
    pub label: Option<String>,
    pub reader_role: Option<String>,
    pub reader_optional: Option<bool>,
    pub is_checkpoint: bool,
    pub source_metadata: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReadingPlanSourceSnapshot {
    pub id: i32,
    pub raw_source_path: String,
    pub display_name: Option<String>,
    pub repository: Option<String>,
    pub source_path: Option<String>,
    pub revision_sha: Option<String>,
    pub content_hash: Option<String>,
    pub adopted_at: Option<String>,
    pub recorded_at: String,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReadingPlanSourcePlacementView {
    pub id: i32,
    pub occurrence_id: String,
    pub plan_source_id: i32,
    pub source_position: Option<i32>,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReadingPlanProgress {
    pub total_issues: i32,
    pub read_issues: i32,
}

/// Mirrors Python `app/schemas/reading_plan_membership.py::ReadingPlanMembershipResponse`.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReadingPlanMembershipResponse {
    pub plan_id: i32,
    pub issues: Vec<ReadingPlanMemberIssue>,
    pub dependencies: Vec<ReadingPlanDependencyLink>,
    pub sources: Vec<ReadingPlanSourceSnapshot>,
    pub placements: Vec<ReadingPlanSourcePlacementView>,
    pub progress: ReadingPlanProgress,
}

#[utoipa::path(
    get,
    path = "/api/v2/continuity-plans/{plan_id}/membership",
    tag = "continuity-plans",
    operation_id = "continuity_plans_membership",
    params(("plan_id" = i32, Path, description = "Continuity plan identifier")),
    responses(
        (status = 200, description = "Plan membership", body = ReadingPlanMembershipResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub async fn get_continuity_plan_membership(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
) -> Result<Json<ReadingPlanMembershipResponse>, ApiError> {
    let conn = db::checkout(&state).await?;

    // Check plan ownership
    let plan_owned: Option<i32> = conn
        .query_opt(
            "SELECT id FROM continuity_plans WHERE id = $1 AND user_id = $2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .map(|row| row.get(0));

    if plan_owned.is_none() {
        return Err(not_found(format!("Continuity plan {plan_id} not found")));
    }

    // Normalized membership rows owned by this plan (Python
    // `reading_plan_repository.list_plan_issues`).
    let issue_rows = conn
        .query(
            "SELECT occurrence_id, issue_id, lane_id, display_position, label, \
             reader_role, reader_optional, is_checkpoint, source_metadata_json \
             FROM reading_plan_issues WHERE plan_id = $1 \
             ORDER BY display_position, occurrence_id",
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;
    let issues: Vec<ReadingPlanMemberIssue> = issue_rows
        .iter()
        .map(|row| ReadingPlanMemberIssue {
            occurrence_id: row.get(0),
            issue_id: row.get(1),
            lane_id: row.get(2),
            display_position: row.get(3),
            label: row.get(4),
            reader_role: row.get(5),
            reader_optional: row.get(6),
            is_checkpoint: row.get(7),
            source_metadata: row.get(8),
        })
        .collect();

    // Dependency provenance: canonical edge endpoints plus this plan's link
    // explanation (Python `list_plan_dependency_edges` + `list_plan_dependencies`).
    let dep_rows = conn
        .query(
            "SELECT d.id, d.source_issue_id, d.target_issue_id, rpd.explanation \
             FROM reading_plan_dependencies rpd \
             JOIN dependencies d ON d.id = rpd.dependency_id \
             WHERE rpd.plan_id = $1 ORDER BY d.id",
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;
    let dependencies: Vec<ReadingPlanDependencyLink> = dep_rows
        .iter()
        .map(|row| ReadingPlanDependencyLink {
            dependency_id: row.get(0),
            source_issue_id: row.get(1),
            target_issue_id: row.get(2),
            explanation: row.get(3),
        })
        .collect();

    // Source snapshots (Python `list_plan_sources`). `display_name` is resolved
    // from external catalogs by the Python reader; no catalog-backed name is
    // available to the native process, so it is reported as null here.
    let source_rows = conn
        .query(
            "SELECT id, raw_source_path, repository, source_path, revision_sha, \
             content_hash, adopted_at::text, recorded_at::text \
             FROM reading_plan_sources WHERE plan_id = $1 ORDER BY id",
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;
    let sources: Vec<ReadingPlanSourceSnapshot> = source_rows
        .iter()
        .map(|row| ReadingPlanSourceSnapshot {
            id: row.get(0),
            raw_source_path: row.get(1),
            display_name: None,
            repository: row.get(2),
            source_path: row.get(3),
            revision_sha: row.get(4),
            content_hash: row.get(5),
            adopted_at: row.get(6),
            recorded_at: row.get(7),
        })
        .collect();

    // Source-position observations (Python `list_plan_source_placements`).
    let placement_rows = conn
        .query(
            "SELECT id, occurrence_id, plan_source_id, source_position \
             FROM reading_plan_source_placements WHERE plan_id = $1 ORDER BY id",
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;
    let placements: Vec<ReadingPlanSourcePlacementView> = placement_rows
        .iter()
        .map(|row| ReadingPlanSourcePlacementView {
            id: row.get(0),
            occurrence_id: row.get(1),
            plan_source_id: row.get(2),
            source_position: row.get(3),
        })
        .collect();

    // Progress derived from global Issue read state (Python `get_plan_progress`).
    let total_issues: i64 = conn
        .query_one(
            "SELECT COUNT(DISTINCT issue_id) FROM reading_plan_issues WHERE plan_id = $1",
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?
        .get(0);
    let read_issues: i64 = conn
        .query_one(
            "SELECT COUNT(DISTINCT rpi.issue_id) FROM reading_plan_issues rpi \
             JOIN issues i ON i.id = rpi.issue_id \
             WHERE rpi.plan_id = $1 AND i.status = 'read'",
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?
        .get(0);

    Ok(Json(ReadingPlanMembershipResponse {
        plan_id,
        issues,
        dependencies,
        sources,
        placements,
        progress: ReadingPlanProgress {
            total_issues: total_issues as i32,
            read_issues: read_issues as i32,
        },
    }))
}

// ============================================================================
// POST /api/v2/continuity-plans/{plan_id}/dependencies/{dependency_id} - Link dependency
// ============================================================================

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReadingPlanDependencyLink {
    #[serde(rename = "dependency_id")]
    pub dependency_id: i32,
    #[serde(rename = "source_issue_id")]
    pub source_issue_id: i32,
    #[serde(rename = "target_issue_id")]
    pub target_issue_id: i32,
    pub explanation: Option<String>,
}

#[derive(Debug, Clone, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ReadingPlanDependencyLinkRequest {
    pub explanation: Option<String>,
}

#[utoipa::path(
    post,
    path = "/api/v2/continuity-plans/{plan_id}/dependencies/{dependency_id}",
    tag = "continuity-plans",
    operation_id = "continuity_plans_link_dependency",
    params(
        ("plan_id" = i32, Path, description = "Continuity plan identifier"),
        ("dependency_id" = i32, Path, description = "Dependency identifier")
    ),
    request_body = ReadingPlanDependencyLinkRequest,
    responses(
        (status = 201, description = "Linked dependency", body = ReadingPlanDependencyLink),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan or dependency not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub async fn link_plan_dependency_edge(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path((plan_id, dependency_id)): Path<(i32, i32)>,
    Json(payload): Json<ReadingPlanDependencyLinkRequest>,
) -> Result<(StatusCode, Json<ReadingPlanDependencyLink>), ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    lock_continuity_graph(&tx, user.id()).await?;

    // Check plan ownership (Python `Continuity plan {id} not found`).
    tx.query_opt(
        "SELECT id FROM continuity_plans WHERE id = $1 AND user_id = $2",
        &[&plan_id, &user.id()],
    )
    .await
    .map_err(db::query_error)?
    .ok_or_else(|| not_found(format!("Continuity plan {plan_id} not found")))?;

    // Resolve the canonical dependency edge before the endpoint ownership guard.
    let dep_row = tx
        .query_opt(
            "SELECT source_issue_id, target_issue_id FROM dependencies WHERE id = $1",
            &[&dependency_id],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| not_found(format!("Dependency {dependency_id} not found")))?;
    let source_issue_id: i32 = dep_row.get(0);
    let target_issue_id: i32 = dep_row.get(1);

    // Python `require_dependency_endpoints_owned`: unowned endpoints yield a
    // structured 422 dangling_plan_reference, never a 404.
    let endpoints_owned: i64 = tx
        .query_one(
            "SELECT COUNT(*) FROM issues i \
             JOIN threads t ON t.id = i.thread_id \
             WHERE i.id = ANY($1::int[]) AND t.user_id = $2",
            &[&vec![source_issue_id, target_issue_id], &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .get(0);
    if endpoints_owned < 2 {
        return Err(structured(
            StatusCode::UNPROCESSABLE_ENTITY,
            serde_json::json!({
                "code": "dangling_plan_reference",
                "dependency_id": dependency_id,
            }),
        ));
    }

    // Python linking is idempotent: an existing link is returned unchanged
    // with 201, not rejected with 409.
    let existing = tx
        .query_opt(
            "SELECT explanation FROM reading_plan_dependencies \
             WHERE plan_id = $1 AND dependency_id = $2",
            &[&plan_id, &dependency_id],
        )
        .await
        .map_err(db::query_error)?;
    if let Some(row) = existing {
        let explanation: Option<String> = row.get(0);
        tx.commit().await.map_err(db::query_error)?;
        return Ok((
            StatusCode::CREATED,
            Json(ReadingPlanDependencyLink {
                dependency_id,
                source_issue_id,
                target_issue_id,
                explanation,
            }),
        ));
    }

    // Composite PK (plan_id, dependency_id): there is no `id` column to
    // RETURN. The response carries the canonical dependency id from the path.
    tx.execute(
        "INSERT INTO reading_plan_dependencies (plan_id, dependency_id, explanation) \
         VALUES ($1, $2, $3)",
        &[&plan_id, &dependency_id, &payload.explanation],
    )
    .await
    .map_err(db::query_error)?;

    tx.commit().await.map_err(db::query_error)?;

    Ok((
        StatusCode::CREATED,
        Json(ReadingPlanDependencyLink {
            dependency_id,
            source_issue_id,
            target_issue_id,
            explanation: payload.explanation,
        }),
    ))
}

// ============================================================================
// DELETE /api/v2/continuity-plans/{plan_id}/dependencies/{dependency_id} - Unlink dependency
// ============================================================================

#[utoipa::path(
    delete,
    path = "/api/v2/continuity-plans/{plan_id}/dependencies/{dependency_id}",
    tag = "continuity-plans",
    operation_id = "continuity_plans_unlink_dependency",
    params(
        ("plan_id" = i32, Path, description = "Continuity plan identifier"),
        ("dependency_id" = i32, Path, description = "Dependency identifier")
    ),
    responses(
        (status = 204, description = "Dependency unlinked"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan or dependency not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub async fn unlink_plan_dependency_edge(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path((plan_id, dependency_id)): Path<(i32, i32)>,
) -> Result<StatusCode, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    lock_continuity_graph(&tx, user.id()).await?;

    // Check plan ownership
    let plan_owned: Option<i32> = tx
        .query_opt(
            "SELECT id FROM continuity_plans WHERE id = $1 AND user_id = $2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .map(|row| row.get(0));

    if plan_owned.is_none() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(not_found(format!("Continuity plan {plan_id} not found")));
    }

    // Remove the plan-dependency link
    let removed = tx
        .execute(
            "DELETE FROM reading_plan_dependencies WHERE plan_id = $1 AND dependency_id = $2",
            &[&plan_id, &dependency_id],
        )
        .await
        .map_err(db::query_error)?;

    if removed == 0 {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(not_found(format!(
            "Dependency {} is not referenced by plan {}",
            dependency_id, plan_id
        )));
    }

    tx.commit().await.map_err(db::query_error)?;
    Ok(StatusCode::NO_CONTENT)
}

// ============================================================================
// POST /api/v2/continuity-plans/{plan_id}/reading-orders/project - Project to reading order
// ============================================================================

#[utoipa::path(
    post,
    path = "/api/v2/continuity-plans/{plan_id}/reading-orders/project",
    tag = "reading-orders",
    operation_id = "continuity_plans_project_to_reading_order",
    params(("plan_id" = i32, Path, description = "Continuity plan identifier")),
    request_body = ReadingOrderProjectionRequest,
    responses(
        (status = 200, description = "Projected reading order", body = ReadingOrderProjectionResult),
        (status = 400, description = "Validation error"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan or reading order not found"),
        (status = 409, description = "Conflict"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub async fn confirm_plan_projection(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
    Json(payload): Json<ReadingOrderProjectionRequest>,
) -> Result<Json<ReadingOrderProjectionResult>, ApiError> {
    use std::collections::{HashMap, HashSet};

    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    lock_continuity_graph(&tx, user.id()).await?;

    // Load the owned plan. `continuity_plans` is keyed by `id`; there is no
    // `plan_id` column (the #4838 review's original P1). Read ordering_mode
    // and lanes so flattening matches the canonical Python projection.
    let plan_row = tx
        .query_opt(
            "SELECT id, ordering_mode, lanes_json, nodes_json
             FROM continuity_plans WHERE id = $1 AND user_id = $2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| not_found(format!("Continuity plan {plan_id} not found")))?;
    let ordering_mode: String = plan_row.get(1);
    let lanes_json: serde_json::Value = plan_row.get(2);
    let nodes_json: serde_json::Value = plan_row.get(3);

    // Load the owned reading order.
    tx.query_opt(
        "SELECT id FROM reading_orders WHERE id = $1 AND user_id = $2",
        &[&payload.reading_order_id, &user.id()],
    )
    .await
    .map_err(db::query_error)?
    .ok_or_else(|| {
        not_found(format!(
            "Reading order {} not found",
            payload.reading_order_id
        ))
    })?;

    #[derive(Clone)]
    struct ProjectNode {
        id: String,
        node_type: String,
        ref_id: i32,
        lane_id: String,
        position: i32,
    }

    let nodes: Vec<ProjectNode> = nodes_json
        .as_array()
        .map(|values| {
            values
                .iter()
                .map(|value| ProjectNode {
                    id: value
                        .get("id")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    node_type: value
                        .get("node_type")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    ref_id: value.get("ref_id").and_then(|v| v.as_i64()).unwrap_or(0) as i32,
                    lane_id: value
                        .get("lane_id")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    position: value.get("position").and_then(|v| v.as_i64()).unwrap_or(0) as i32,
                })
                .collect()
        })
        .unwrap_or_default();

    // Flatten deterministically: strict sequential validates a single lane
    // with contiguous positions; informational flattens lane by lane.
    let lane_orders: HashMap<String, i32> = lanes_json
        .as_array()
        .map(|lanes| {
            lanes
                .iter()
                .filter_map(|lane| {
                    let id = lane.get("id")?.as_str()?.to_string();
                    let order = lane.get("order")?.as_i64()? as i32;
                    Some((id, order))
                })
                .collect()
        })
        .unwrap_or_default();

    let mut ordered = nodes.clone();
    if ordering_mode == "strict_sequential" {
        if lane_orders.len() != 1 {
            tx.rollback().await.map_err(db::query_error)?;
            return Err(domain_conflict(serde_json::json!({
                "code": "malformed_plan",
                "plan_id": plan_id,
                "reason": "strict sequential plans must use exactly one lane",
            })));
        }
        let lane_id = lane_orders.keys().next().cloned().unwrap_or_default();
        if nodes.iter().any(|node| node.lane_id != lane_id) {
            tx.rollback().await.map_err(db::query_error)?;
            return Err(domain_conflict(serde_json::json!({
                "code": "malformed_plan",
                "plan_id": plan_id,
                "reason": "strict sequential plans must have all nodes in single lane",
            })));
        }
        let mut positions: Vec<i32> = ordered.iter().map(|node| node.position).collect();
        positions.sort_unstable();
        if positions != (0..positions.len() as i32).collect::<Vec<i32>>() {
            tx.rollback().await.map_err(db::query_error)?;
            return Err(domain_conflict(serde_json::json!({
                "code": "malformed_plan",
                "plan_id": plan_id,
                "reason": "strict sequential positions must be contiguous starting at zero",
            })));
        }
        ordered.sort_by(|a, b| a.position.cmp(&b.position).then(a.id.cmp(&b.id)));
    } else {
        ordered.sort_by(|a, b| {
            lane_orders
                .get(&a.lane_id)
                .copied()
                .unwrap_or(0)
                .cmp(&lane_orders.get(&b.lane_id).copied().unwrap_or(0))
                .then(a.position.cmp(&b.position))
                .then(a.id.cmp(&b.id))
        });
    }

    let thread_ids: Vec<i32> = ordered
        .iter()
        .filter(|node| node.node_type == "thread")
        .map(|node| node.ref_id)
        .collect();
    let thread_titles: HashMap<i32, String> = if thread_ids.is_empty() {
        HashMap::new()
    } else {
        tx.query(
            "SELECT id, title FROM threads WHERE user_id = $1 AND id = ANY($2::int[])",
            &[&user.id(), &thread_ids],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| (row.get::<_, i32>(0), row.get::<_, String>(1)))
        .collect()
    };

    let existing_rows = tx
        .query(
            "SELECT thread_id, position FROM reading_order_items WHERE reading_order_id = $1",
            &[&payload.reading_order_id],
        )
        .await
        .map_err(db::query_error)?;
    let mut existing_positions: HashMap<i32, i32> = HashMap::new();
    for row in &existing_rows {
        existing_positions.insert(row.get(0), row.get(1));
    }

    let mut conflicts: Vec<serde_json::Value> = Vec::new();
    let mut seen_threads: HashSet<i32> = HashSet::new();
    let mut thread_positions: HashMap<i32, Vec<i32>> = HashMap::new();
    for node in &ordered {
        if node.node_type != "thread" {
            conflicts.push(serde_json::json!({
                "code": "non_thread_node",
                "message": format!(
                    "Reading order projection only supports thread nodes; {} node {} cannot be projected.",
                    node.node_type, node.id
                ),
                "node_id": node.id,
                "thread_id": node.ref_id,
                "existing_positions": [],
            }));
            continue;
        }
        if !thread_titles.contains_key(&node.ref_id) {
            conflicts.push(serde_json::json!({
                "code": "missing_thread",
                "message": format!(
                    "Thread {} from node {} is not owned by the user.",
                    node.ref_id, node.id
                ),
                "node_id": node.id,
                "thread_id": node.ref_id,
                "existing_positions": [],
            }));
            continue;
        }
        thread_positions
            .entry(node.ref_id)
            .or_default()
            .push(node.position);
        if seen_threads.contains(&node.ref_id) {
            let mut positions = thread_positions
                .get(&node.ref_id)
                .cloned()
                .unwrap_or_default();
            positions.sort_unstable();
            conflicts.push(serde_json::json!({
                "code": "duplicate_thread",
                "message": format!(
                    "Thread {} appears multiple times in the plan; deduplicate node positions before projection.",
                    node.ref_id
                ),
                "node_id": node.id,
                "thread_id": node.ref_id,
                "existing_positions": positions,
            }));
            continue;
        }
        seen_threads.insert(node.ref_id);
    }

    if !conflicts.is_empty() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(domain_conflict(serde_json::json!({
            "code": "projection_conflicts",
            "conflicts": conflicts,
        })));
    }

    #[derive(Clone, Copy)]
    enum EntrySource {
        Added,
        Updated,
        Existing,
    }
    let mut entries: Vec<(i32, EntrySource)> = Vec::new();
    let mut position = 1;
    for node in &ordered {
        if node.node_type != "thread" || !thread_titles.contains_key(&node.ref_id) {
            continue;
        }
        let source = match existing_positions.get(&node.ref_id) {
            None => EntrySource::Added,
            Some(old) if *old != position => EntrySource::Updated,
            Some(_) => EntrySource::Existing,
        };
        entries.push((node.ref_id, source));
        position += 1;
    }

    tx.execute(
        "DELETE FROM reading_order_items WHERE reading_order_id = $1",
        &[&payload.reading_order_id],
    )
    .await
    .map_err(db::query_error)?;

    let mut added: i32 = 0;
    let mut updated: i32 = 0;
    let mut kept: i32 = 0;
    for (index, (thread_id, source)) in entries.iter().enumerate() {
        match source {
            EntrySource::Added => added += 1,
            EntrySource::Updated => updated += 1,
            EntrySource::Existing => kept += 1,
        }
        let position = (index as i32) + 1;
        tx.execute(
            "INSERT INTO reading_order_items (reading_order_id, thread_id, position, issue_number) VALUES ($1, $2, $3, NULL)",
            &[&payload.reading_order_id, thread_id, &position],
        )
        .await
        .map_err(db::query_error)?;
    }

    tx.commit().await.map_err(db::query_error)?;

    Ok(Json(ReadingOrderProjectionResult {
        plan_id,
        reading_order_id: payload.reading_order_id,
        added_count: added,
        updated_count: updated,
        kept_count: kept,
        total_positions: entries.len() as i32,
    }))
}

// ============================================================================
// POST /api/v2/continuity-plans/release-sources/ - Create release source
// ============================================================================

#[utoipa::path(
    post,
    path = "/api/v2/continuity-plans/release-sources/",
    tag = "reading-plan-release-sources",
    operation_id = "release_sources_create",
    request_body = ReleaseSourceCreate,
    responses(
        (status = 201, description = "Created release source", body = ReleaseSourceResponse),
        (status = 400, description = "Validation error"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan, thread, or provider identity not found"),
        (status = 422, description = "Provider volume must be a confirmed mapping for the thread"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub async fn create_release_source(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(payload): Json<ReleaseSourceCreate>,
) -> Result<(StatusCode, Json<ReleaseSourceResponse>), ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    lock_continuity_graph(&tx, user.id()).await?;

    // Check plan ownership
    tx.query_opt(
        "SELECT id FROM continuity_plans WHERE id = $1 AND user_id = $2",
        &[&payload.plan_id, &user.id()],
    )
    .await
    .map_err(db::query_error)?
    .ok_or_else(|| not_found(format!("Plan {} not found", payload.plan_id)))?;

    // Check thread ownership
    tx.query_opt(
        "SELECT id FROM threads WHERE id = $1 AND user_id = $2",
        &[&payload.thread_id, &user.id()],
    )
    .await
    .map_err(db::query_error)?
    .ok_or_else(|| not_found(format!("Thread {} not found", payload.thread_id)))?;

    // Verify confirmed ComicVine series mapping
    let mapping = tx
        .query_opt(
            r#"
            SELECT ei.id, ei.provider, ei.entity_type, ei.external_id, ei.metadata_json
            FROM thread_external_series_mappings tesm
            JOIN external_identities ei ON ei.id = tesm.external_identity_id
            WHERE tesm.thread_id = $1
              AND tesm.external_identity_id = $2
              AND tesm.status = 'confirmed'
              AND ei.provider = 'comicvine'
              AND ei.entity_type = 'series'
            "#,
            &[&payload.thread_id, &payload.external_identity_id],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| {
            ApiError::Unprocessable(
                "Provider volume must be a confirmed mapping for the thread".into(),
            )
        })?;

    let provider: String = mapping.get(1);
    let provider_volume_id: String = mapping.get(3);
    let metadata_json: Option<serde_json::Value> = mapping.get(4);

    // Resolve authoritative custom CBL list association (non-destructive).
    // Explicit list wins after ownership validation; otherwise auto-associate
    // from unambiguous same-owner ReadingPlanSource provenance.
    let resolved_list_id: Option<i32> = if let Some(list_id) = payload.custom_cbl_list_id {
        tx.query_opt(
            "SELECT id FROM custom_cbl_lists WHERE id = $1 AND user_id = $2",
            &[&list_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| not_found(format!("Reading List {} not found", list_id)))?;
        Some(list_id)
    } else {
        let rows = tx
            .query(
                "SELECT DISTINCT src.custom_cbl_list_id \
                 FROM reading_plan_sources src \
                 JOIN custom_cbl_lists l ON l.id = src.custom_cbl_list_id AND l.user_id = $2 \
                 WHERE src.plan_id = $1 AND src.custom_cbl_list_id IS NOT NULL",
                &[&payload.plan_id, &user.id()],
            )
            .await
            .map_err(db::query_error)?;
        let ids: Vec<i32> = rows
            .iter()
            .filter_map(|r| r.get::<_, Option<i32>>(0))
            .collect();
        if ids.len() == 1 {
            Some(ids[0])
        } else {
            None
        }
    };

    // Check for existing release source (idempotent create)
    let existing = tx
        .query_opt(
            "SELECT id FROM reading_plan_release_sources WHERE plan_id = $1 AND thread_id = $2 AND external_identity_id = $3",
            &[&payload.plan_id, &payload.thread_id, &payload.external_identity_id],
        )
        .await
        .map_err(db::query_error)?;

    let source_id: i32;
    let created_at: String;
    let mut updated_at: String;
    let mut last_synced_at: Option<String> = None;
    let mut enabled = true;
    let mut final_list_id: Option<i32> = resolved_list_id;

    if let Some(row) = existing {
        source_id = row.get(0);
        // Fetch the existing source details
        let source_row = tx
            .query_one(
                "SELECT created_at::text, updated_at::text, last_synced_at::text, enabled, custom_cbl_list_id FROM reading_plan_release_sources WHERE id = $1",
                &[&source_id],
            )
            .await
            .map_err(db::query_error)?;
        created_at = source_row.get(0);
        updated_at = source_row.get(1);
        last_synced_at = source_row.get(2);
        enabled = source_row.get(3);
        let existing_list: Option<i32> = source_row.get(4);
        // Non-destructive association: fill list link if missing.
        if existing_list.is_none() && resolved_list_id.is_some() {
            let associated = tx
                .query_one(
                    "UPDATE reading_plan_release_sources SET custom_cbl_list_id = $1, updated_at = NOW() WHERE id = $2 RETURNING updated_at::text",
                    &[&resolved_list_id, &source_id],
                )
                .await
                .map_err(db::query_error)?;
            updated_at = associated.get(0);
            final_list_id = resolved_list_id;
        } else {
            final_list_id = existing_list.or(resolved_list_id);
        }
    } else {
        // Create new release source
        let row = tx
            .query_one(
                r#"
                INSERT INTO reading_plan_release_sources (plan_id, thread_id, external_identity_id, enabled, custom_cbl_list_id, created_at, updated_at)
                VALUES ($1, $2, $3, TRUE, $4, NOW(), NOW())
                RETURNING id, created_at::text, updated_at::text
                "#,
                &[&payload.plan_id, &payload.thread_id, &payload.external_identity_id, &resolved_list_id],
            )
            .await
            .map_err(db::query_error)?;
        source_id = row.get(0);
        created_at = row.get(1);
        updated_at = row.get(2);
    }

    tx.commit().await.map_err(db::query_error)?;

    // Extract provider title from metadata
    let provider_title = metadata_json.as_ref().and_then(|m| {
        let name_str = m.get("name").and_then(|v| v.as_str());
        let title_str = m.get("title").and_then(|v| v.as_str());
        name_str.or(title_str).map(|s| s.to_string())
    });

    let response = ReleaseSourceResponse {
        id: source_id,
        plan_id: payload.plan_id,
        custom_cbl_list_id: final_list_id,
        thread_id: payload.thread_id,
        external_identity_id: payload.external_identity_id,
        provider,
        provider_volume_id,
        provider_title,
        enabled,
        last_synced_at,
        created_at,
        updated_at,
    };

    Ok((StatusCode::CREATED, Json(response)))
}

// ============================================================================
// GET /api/v2/continuity-plans/{plan_id}/release-sources/ - List release sources
// ============================================================================

#[utoipa::path(
    get,
    path = "/api/v2/continuity-plans/{plan_id}/release-sources/",
    tag = "reading-plan-release-sources",
    operation_id = "release_sources_list",
    params(("plan_id" = i32, Path, description = "Continuity plan identifier")),
    responses(
        (status = 200, description = "List of release sources", body = Vec<ReleaseSourceResponse>),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub async fn list_release_sources(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
) -> Result<Json<Vec<ReleaseSourceResponse>>, ApiError> {
    let conn = db::checkout(&state).await?;

    // Check plan ownership
    let plan_owned = conn
        .query_opt(
            "SELECT id FROM continuity_plans WHERE id = $1 AND user_id = $2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .is_some();

    if !plan_owned {
        return Err(not_found(format!("Plan {plan_id} not found")));
    }

    // Get release sources with provider identity details
    let rows = conn
        .query(
            r#"
            SELECT rprs.id, rprs.plan_id, rprs.custom_cbl_list_id, rprs.thread_id, rprs.external_identity_id,
                   rprs.enabled, rprs.last_synced_at::text, rprs.created_at::text, rprs.updated_at::text,
                   ei.provider, ei.entity_type, ei.external_id, ei.metadata_json
            FROM reading_plan_release_sources rprs
            JOIN external_identities ei ON ei.id = rprs.external_identity_id
            JOIN continuity_plans cp ON cp.id = rprs.plan_id
            WHERE rprs.plan_id = $1 AND cp.user_id = $2
            ORDER BY rprs.created_at
            "#,
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;

    let sources: Vec<ReleaseSourceResponse> = rows
        .iter()
        .map(|row| {
            let metadata_json: Option<serde_json::Value> = row.get(12);
            let provider_title = metadata_json.as_ref().and_then(|m| {
                let name_str = m.get("name").and_then(|v| v.as_str());
                let title_str = m.get("title").and_then(|v| v.as_str());
                name_str.or(title_str).map(|s| s.to_string())
            });

            ReleaseSourceResponse {
                id: row.get(0),
                plan_id: row.get(1),
                custom_cbl_list_id: row.get(2),
                thread_id: row.get(3),
                external_identity_id: row.get(4),
                provider: row.get(9),
                provider_volume_id: row.get(11),
                provider_title,
                enabled: row.get(5),
                last_synced_at: row.get(6),
                created_at: row.get(7),
                updated_at: row.get(8),
            }
        })
        .collect();

    Ok(Json(sources))
}

// ============================================================================
// GET /api/v2/continuity-plans/{plan_id}/release-sources/reader - List reader-facing release sources
// ============================================================================

#[utoipa::path(
    get,
    path = "/api/v2/continuity-plans/{plan_id}/release-sources/reader",
    tag = "reading-plan-release-sources",
    operation_id = "release_sources_list_reader",
    params(("plan_id" = i32, Path, description = "Continuity plan identifier")),
    responses(
        (status = 200, description = "List of reader-facing release sources", body = Vec<ReadingPlanReleaseSourceStatus>),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub async fn list_release_sources_for_reader(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
) -> Result<Json<Vec<ReadingPlanReleaseSourceStatus>>, ApiError> {
    let conn = db::checkout(&state).await?;

    // Check plan ownership
    let plan_owned = conn
        .query_opt(
            "SELECT id FROM continuity_plans WHERE id = $1 AND user_id = $2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .is_some();

    if !plan_owned {
        return Err(not_found(format!("Plan {plan_id} not found")));
    }

    // Get release sources with provider identity details
    let rows = conn
        .query(
            r#"
            SELECT rprs.id, rprs.thread_id, rprs.external_identity_id,
                   rprs.enabled, rprs.last_synced_at::text,
                   ei.provider, ei.entity_type, ei.external_id, ei.metadata_json
            FROM reading_plan_release_sources rprs
            JOIN external_identities ei ON ei.id = rprs.external_identity_id
            JOIN continuity_plans cp ON cp.id = rprs.plan_id
            WHERE rprs.plan_id = $1 AND cp.user_id = $2
            ORDER BY rprs.created_at
            "#,
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;

    let sources: Vec<ReadingPlanReleaseSourceStatus> = rows
        .iter()
        .map(|row| {
            let metadata_json: Option<serde_json::Value> = row.get(8);
            let display = extract_provider_display(metadata_json);

            ReadingPlanReleaseSourceStatus {
                source_id: row.get(0),
                thread_id: row.get(1),
                external_identity_id: row.get(2),
                provider_volume_id: row.get(7),
                provider_title: display
                    .get("title")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string()),
                provider_publisher: display
                    .get("publisher")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string()),
                provider_start_year: display
                    .get("start_year")
                    .and_then(|v| v.as_i64())
                    .map(|v| v as i32),
                provider_issue_count: display
                    .get("issue_count")
                    .and_then(|v| v.as_i64())
                    .map(|v| v as i32),
                enabled: row.get(3),
                last_synced_at: row.get(4),
            }
        })
        .collect();

    Ok(Json(sources))
}

// ============================================================================
// PATCH /api/v2/continuity-plans/release-sources/{source_id} - Update release source
// ============================================================================

#[utoipa::path(
    patch,
    path = "/api/v2/continuity-plans/release-sources/{source_id}",
    tag = "reading-plan-release-sources",
    operation_id = "release_sources_update",
    params(("source_id" = i32, Path, description = "Release source identifier")),
    request_body = ReleaseSourceUpdate,
    responses(
        (status = 200, description = "Updated release source", body = ReleaseSourceResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Release source not found"),
        (status = 422, description = "Mapping no longer confirmed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub async fn update_release_source(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(source_id): Path<i32>,
    Json(payload): Json<ReleaseSourceUpdate>,
) -> Result<Json<ReleaseSourceResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    lock_continuity_graph(&tx, user.id()).await?;

    // Get the release source with ownership check
    let source_row = tx
        .query_opt(
            r#"
            SELECT rprs.id, rprs.plan_id, rprs.custom_cbl_list_id, rprs.thread_id, rprs.external_identity_id,
                   rprs.enabled, rprs.last_synced_at::text, rprs.created_at::text, rprs.updated_at::text,
                   ei.provider, ei.entity_type, ei.external_id, ei.metadata_json
            FROM reading_plan_release_sources rprs
            JOIN external_identities ei ON ei.id = rprs.external_identity_id
            JOIN continuity_plans cp ON cp.id = rprs.plan_id
            WHERE rprs.id = $1 AND cp.user_id = $2
            "#,
            &[&source_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| not_found(format!("Release source {source_id} not found")))?;

    let thread_id: i32 = source_row.get(3);
    let external_identity_id: i32 = source_row.get(4);
    let currently_enabled: bool = source_row.get(5);

    // If enabling, revalidate the mapping is still confirmed
    if payload.enabled && !currently_enabled {
        let mapping = tx
            .query_opt(
                r#"
                SELECT 1
                FROM thread_external_series_mappings tesm
                JOIN external_identities ei ON ei.id = tesm.external_identity_id
                WHERE tesm.thread_id = $1
                  AND tesm.external_identity_id = $2
                  AND tesm.status = 'confirmed'
                  AND ei.provider = 'comicvine'
                  AND ei.entity_type = 'series'
                "#,
                &[&thread_id, &external_identity_id],
            )
            .await
            .map_err(db::query_error)?;

        if mapping.is_none() {
            return Err(ApiError::Unprocessable(
                "Mapping no longer confirmed".into(),
            ));
        }
    }

    // Update the enabled status
    tx.execute(
        "UPDATE reading_plan_release_sources SET enabled = $1, updated_at = NOW() WHERE id = $2",
        &[&payload.enabled, &source_id],
    )
    .await
    .map_err(db::query_error)?;

    tx.commit().await.map_err(db::query_error)?;

    // Fetch updated row
    let conn = db::checkout(&state).await?;
    let updated_row = conn
        .query_one(
            r#"
            SELECT rprs.id, rprs.plan_id, rprs.custom_cbl_list_id, rprs.thread_id, rprs.external_identity_id,
                   rprs.enabled, rprs.last_synced_at::text, rprs.created_at::text, rprs.updated_at::text,
                   ei.provider, ei.entity_type, ei.external_id, ei.metadata_json
            FROM reading_plan_release_sources rprs
            JOIN external_identities ei ON ei.id = rprs.external_identity_id
            JOIN continuity_plans cp ON cp.id = rprs.plan_id
            WHERE rprs.id = $1 AND cp.user_id = $2
            "#,
            &[&source_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;

    let metadata_json: Option<serde_json::Value> = updated_row.get(12);
    let provider_title = metadata_json.as_ref().and_then(|m| {
        let name_str = m.get("name").and_then(|v| v.as_str());
        let title_str = m.get("title").and_then(|v| v.as_str());
        name_str.or(title_str).map(|s| s.to_string())
    });

    let response = ReleaseSourceResponse {
        id: updated_row.get(0),
        plan_id: updated_row.get(1),
        custom_cbl_list_id: updated_row.get(2),
        thread_id: updated_row.get(3),
        external_identity_id: updated_row.get(4),
        provider: updated_row.get(9),
        provider_volume_id: updated_row.get(11),
        provider_title,
        enabled: updated_row.get(5),
        last_synced_at: updated_row.get(6),
        created_at: updated_row.get(7),
        updated_at: updated_row.get(8),
    };

    Ok(Json(response))
}

// ============================================================================
// DELETE /api/v2/continuity-plans/release-sources/{source_id} - Delete release source
// ============================================================================

#[utoipa::path(
    delete,
    path = "/api/v2/continuity-plans/release-sources/{source_id}",
    tag = "reading-plan-release-sources",
    operation_id = "release_sources_delete",
    params(("source_id" = i32, Path, description = "Release source identifier")),
    responses(
        (status = 204, description = "Release source deleted"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Release source not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub async fn delete_release_source(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(source_id): Path<i32>,
) -> Result<StatusCode, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    lock_continuity_graph(&tx, user.id()).await?;

    // Check ownership and delete
    let deleted = tx
        .execute(
            r#"
            DELETE FROM reading_plan_release_sources rprs
            USING continuity_plans cp
            WHERE rprs.id = $1 AND rprs.plan_id = cp.id AND cp.user_id = $2
            "#,
            &[&source_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;

    if deleted == 0 {
        return Err(not_found(format!("Release source {source_id} not found")));
    }

    tx.commit().await.map_err(db::query_error)?;
    Ok(StatusCode::NO_CONTENT)
}

// Helper function to extract provider display metadata
fn extract_provider_display(metadata_json: Option<serde_json::Value>) -> serde_json::Value {
    let mut display = serde_json::Map::new();

    if let Some(m) = metadata_json {
        // Extract title - check both "name" and "title" keys
        let title_from_name = m
            .get("name")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        let title_from_title = m
            .get("title")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        let title_str = title_from_name.or(title_from_title);
        if let Some(s) = title_str {
            if !s.trim().is_empty() {
                display.insert(
                    "title".to_string(),
                    serde_json::Value::String(s.trim().to_string()),
                );
            }
        }

        // Extract publisher
        if let Some(publisher) = m.get("publisher") {
            if let Some(s) = publisher.as_str() {
                if !s.trim().is_empty() {
                    display.insert(
                        "publisher".to_string(),
                        serde_json::Value::String(s.trim().to_string()),
                    );
                }
            } else if let Some(obj) = publisher.as_object() {
                if let Some(name) = obj.get("name") {
                    if let Some(s) = name.as_str() {
                        if !s.trim().is_empty() {
                            display.insert(
                                "publisher".to_string(),
                                serde_json::Value::String(s.trim().to_string()),
                            );
                        }
                    }
                }
            }
        }

        // Extract start_year
        if let Some(start_year) = m.get("start_year") {
            if let Some(y) = start_year.as_i64() {
                display.insert(
                    "start_year".to_string(),
                    serde_json::Value::Number(y.into()),
                );
            } else if let Some(s) = start_year.as_str() {
                if let Ok(y) = s.trim().parse::<i64>() {
                    display.insert(
                        "start_year".to_string(),
                        serde_json::Value::Number(y.into()),
                    );
                }
            }
        }

        // Extract issue_count - check both "count_of_issues" and "issue_count" keys
        let count_of_issues_i64 = m.get("count_of_issues").and_then(|v| v.as_i64());
        let count_of_issues_str = m
            .get("count_of_issues")
            .and_then(|v| v.as_str())
            .and_then(|s| s.trim().parse::<i64>().ok());
        let issue_count_i64 = m.get("issue_count").and_then(|v| v.as_i64());
        let issue_count_str = m
            .get("issue_count")
            .and_then(|v| v.as_str())
            .and_then(|s| s.trim().parse::<i64>().ok());
        let issue_count = count_of_issues_i64
            .or(count_of_issues_str)
            .or(issue_count_i64)
            .or(issue_count_str);
        if let Some(c) = issue_count {
            display.insert(
                "issue_count".to_string(),
                serde_json::Value::Number(c.into()),
            );
        }
    }

    serde_json::Value::Object(display)
}

// ============================================================================
// Documentation-only declarations for the same-path v1 contract.
//
// The mounted handlers above carry their own `#[utoipa::path]` attributes.
// These empty shims register the identical operations in the generated native
// OpenAPI document so the client contract keeps the migrated v1 paths and
// schemas after the transitional Python handlers are deleted. This mirrors the
// established `continuity_rules` documentation pattern.
// ============================================================================

#[utoipa::path(get, path = "/api/v2/continuity-plans/", tag = "continuity-plans", operation_id = "continuity_plans_list", responses((status = 200, body = Vec<ContinuityPlanListItem>)), security(("HTTPBearer" = [])))]
pub fn list_documentation() {}
#[utoipa::path(post, path = "/api/v2/continuity-plans/", tag = "continuity-plans", operation_id = "continuity_plans_create", request_body = ContinuityPlanWrite, responses((status = 201, body = ContinuityPlanResponse)), security(("HTTPBearer" = [])))]
pub fn create_documentation() {}
#[utoipa::path(get, path = "/api/v2/continuity-plans/{plan_id}", tag = "continuity-plans", operation_id = "continuity_plans_get", params(("plan_id" = i32, Path)), responses((status = 200, body = ContinuityPlanResponse)), security(("HTTPBearer" = [])))]
pub fn get_documentation() {}
#[utoipa::path(put, path = "/api/v2/continuity-plans/{plan_id}", tag = "continuity-plans", operation_id = "continuity_plans_update", params(("plan_id" = i32, Path)), request_body = ContinuityPlanWrite, responses((status = 200, description = "Updated continuity plan", body = ContinuityPlanResponse), (status = 409, description = "Stale expected_updated_at: detail.code is plan_version_conflict and detail.expected_updated_at is the current version; reload before retrying")), security(("HTTPBearer" = [])))]
pub fn update_documentation() {}
#[utoipa::path(delete, path = "/api/v2/continuity-plans/{plan_id}", tag = "continuity-plans", operation_id = "continuity_plans_delete", params(("plan_id" = i32, Path)), responses((status = 204, description = "Plan deleted")), security(("HTTPBearer" = [])))]
pub fn delete_documentation() {}
#[utoipa::path(post, path = "/api/v2/continuity-plans/from-reading-order", tag = "continuity-plans", operation_id = "continuity_plans_adopt_reading_order", request_body = ReadingOrderAdoptRequest, responses((status = 201, body = ContinuityPlanResponse)), security(("HTTPBearer" = [])))]
pub fn adopt_reading_order_documentation() {}
#[utoipa::path(get, path = "/api/v2/continuity-plans/{plan_id}/membership", tag = "continuity-plans", operation_id = "continuity_plans_membership", params(("plan_id" = i32, Path)), responses((status = 200, body = ReadingPlanMembershipResponse)), security(("HTTPBearer" = [])))]
pub fn membership_documentation() {}
#[utoipa::path(post, path = "/api/v2/continuity-plans/{plan_id}/dependencies/{dependency_id}", tag = "continuity-plans", operation_id = "continuity_plans_link_dependency", params(("plan_id" = i32, Path), ("dependency_id" = i32, Path)), request_body = ReadingPlanDependencyLinkRequest, responses((status = 201, body = ReadingPlanDependencyLink)), security(("HTTPBearer" = [])))]
pub fn link_dependency_documentation() {}
#[utoipa::path(delete, path = "/api/v2/continuity-plans/{plan_id}/dependencies/{dependency_id}", tag = "continuity-plans", operation_id = "continuity_plans_unlink_dependency", params(("plan_id" = i32, Path), ("dependency_id" = i32, Path)), responses((status = 204, description = "Dependency unlinked")), security(("HTTPBearer" = [])))]
pub fn unlink_dependency_documentation() {}
#[utoipa::path(post, path = "/api/v2/continuity-plans/{plan_id}/reading-orders/project", tag = "reading-orders", operation_id = "continuity_plans_project_to_reading_order", params(("plan_id" = i32, Path)), request_body = ReadingOrderProjectionRequest, responses((status = 200, body = ReadingOrderProjectionResult)), security(("HTTPBearer" = [])))]
pub fn project_reading_order_documentation() {}
#[utoipa::path(post, path = "/api/v2/continuity-plans/release-sources/", tag = "continuity-plans", operation_id = "release_sources_create", request_body = ReleaseSourceCreate, responses((status = 201, body = ReleaseSourceResponse)), security(("HTTPBearer" = [])))]
pub fn release_source_create_documentation() {}
#[utoipa::path(get, path = "/api/v2/continuity-plans/{plan_id}/release-sources/", tag = "continuity-plans", operation_id = "release_sources_list", params(("plan_id" = i32, Path)), responses((status = 200, body = Vec<ReleaseSourceResponse>)), security(("HTTPBearer" = [])))]
pub fn release_source_list_documentation() {}
#[utoipa::path(get, path = "/api/v2/continuity-plans/{plan_id}/release-sources/reader", tag = "continuity-plans", operation_id = "release_sources_list_reader", params(("plan_id" = i32, Path)), responses((status = 200, body = Vec<ReadingPlanReleaseSourceStatus>)), security(("HTTPBearer" = [])))]
pub fn release_source_list_reader_documentation() {}
#[utoipa::path(patch, path = "/api/v2/continuity-plans/release-sources/{source_id}", tag = "continuity-plans", operation_id = "release_sources_update", params(("source_id" = i32, Path)), request_body = ReleaseSourceUpdate, responses((status = 200, body = ReleaseSourceResponse)), security(("HTTPBearer" = [])))]
pub fn release_source_update_documentation() {}
#[utoipa::path(delete, path = "/api/v2/continuity-plans/release-sources/{source_id}", tag = "continuity-plans", operation_id = "release_sources_delete", params(("source_id" = i32, Path)), responses((status = 204, description = "Release source deleted")), security(("HTTPBearer" = [])))]
pub fn release_source_delete_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;

    /// The retired Python schema defaulted `ordering_mode` to "informational";
    /// a v2 caller that still omits it must keep working after the cutover.
    #[test]
    fn plan_write_defaults_ordering_mode_to_informational() {
        let payload: ContinuityPlanWrite =
            serde_json::from_str(r#"{"name":"Plan","lanes":[],"nodes":[]}"#)
                .expect("omitted ordering_mode must deserialize");
        assert_eq!(payload.ordering_mode, "informational");
        payload
            .validate_structure()
            .expect("defaulted mode is valid");
    }

    fn lane(id: &str, order: i32) -> ContinuityPlanLane {
        ContinuityPlanLane {
            id: id.to_string(),
            name: format!("Lane {id}"),
            order,
            inferred_gate_kind: None,
            migration_contract: None,
        }
    }

    fn node(
        id: &str,
        node_type: &str,
        ref_id: i32,
        lane_id: &str,
        position: i32,
    ) -> ContinuityPlanNode {
        ContinuityPlanNode {
            id: id.to_string(),
            node_type: node_type.to_string(),
            ref_id,
            lane_id: lane_id.to_string(),
            position,
            label: None,
            source_role: None,
            source_confidence: None,
            source_explanation: None,
            source_paths: None,
            source_cbl_placements: None,
            source_story_arc_ids: None,
            source_target_story_arc_id: None,
            reader_role: None,
            reader_optional: None,
            is_checkpoint: false,
            checkpoint_target_ref_id: None,
            checkpoint_target_ref_ids: Vec::new(),
            convergence_gate: Vec::new(),
        }
    }

    fn payload(
        ordering_mode: &str,
        lanes: Vec<ContinuityPlanLane>,
        nodes: Vec<ContinuityPlanNode>,
    ) -> ContinuityPlanWrite {
        ContinuityPlanWrite {
            name: "Plan".to_string(),
            ordering_mode: ordering_mode.to_string(),
            lanes,
            nodes,
            expected_updated_at: None,
        }
    }

    #[test]
    fn validate_structure_accepts_valid_informational_plan() {
        let write = payload(
            "informational",
            vec![lane("l1", 0)],
            vec![node("n1", "issue", 1, "l1", 0)],
        );
        assert!(write.validate_structure().is_ok());
    }

    #[test]
    fn validate_structure_rejects_duplicate_issue_refs() {
        let write = payload(
            "informational",
            vec![lane("l1", 0)],
            vec![
                node("n1", "issue", 1, "l1", 0),
                node("n2", "issue", 1, "l1", 1),
            ],
        );
        let err = write
            .validate_structure()
            .expect_err("duplicate issue must fail");
        assert!(format!("{err:?}").contains("an issue may appear at most once"));
    }

    #[test]
    fn validate_structure_rejects_unknown_lane() {
        let write = payload(
            "informational",
            vec![lane("l1", 0)],
            vec![node("n1", "issue", 1, "missing", 0)],
        );
        assert!(write.validate_structure().is_err());
    }

    #[test]
    fn validate_structure_rejects_non_contiguous_strict_positions() {
        let write = payload(
            "strict_sequential",
            vec![lane("l1", 0)],
            vec![
                node("n1", "issue", 1, "l1", 0),
                node("n2", "issue", 2, "l1", 2),
            ],
        );
        let err = write.validate_structure().expect_err("gap must fail");
        assert!(format!("{err:?}").contains("contiguous starting at zero"));
    }

    #[test]
    fn validate_structure_rejects_checkpoint_on_thread() {
        let mut checkpoint = node("n1", "thread", 1, "l1", 0);
        checkpoint.is_checkpoint = true;
        let write = payload("informational", vec![lane("l1", 0)], vec![checkpoint]);
        let err = write
            .validate_structure()
            .expect_err("checkpoint must fail");
        assert!(format!("{err:?}").contains("only allowed on issue nodes"));
    }

    #[test]
    fn validate_structure_rejects_self_convergence_gate() {
        let mut gated = node("n1", "issue", 1, "l1", 0);
        gated.convergence_gate = vec![serde_json::json!({"node_type": "issue", "node_id": "n1"})];
        let write = payload("informational", vec![lane("l1", 0)], vec![gated]);
        let err = write.validate_structure().expect_err("self gate must fail");
        assert!(format!("{err:?}").contains("cannot wait for itself"));
    }

    #[test]
    fn dangling_node_uses_422_envelope() {
        let err = dangling_node("n7");
        assert_eq!(err.status(), StatusCode::UNPROCESSABLE_ENTITY);
        let detail = err.structured_detail().expect("structured detail");
        assert_eq!(detail["code"], "dangling_plan_reference");
        assert_eq!(detail["node_id"], "n7");
    }

    async fn plan_db_fixture() -> (
        std::sync::Arc<AppState>,
        AuthenticatedUser,
        tokio::sync::MutexGuard<'static, ()>,
    ) {
        let state = crate::test_support::test_state(2)
            .await
            .expect("RUST_ROLL_TEST_DATABASE_URL is required");
        let guard = crate::test_support::reset_for_test(&state).await;
        let connection = db::checkout(&state).await.expect("fixture connection");
        connection
            .batch_execute(
                "INSERT INTO users (id, username) VALUES (4838, 'plan-writer-test');
                 INSERT INTO threads (id, user_id, title, format, issues_remaining, queue_position, status)
                 VALUES (4838, 4838, 'Plan test', 'Comic', 2, 1, 'active');
                 INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
                 VALUES (483801, 4838, '1', 'unread', NOW(), 1),
                        (483802, 4838, '2', 'unread', NOW(), 2);",
            )
            .await
            .expect("seed plan writer fixture");
        drop(connection);
        (state, AuthenticatedUser::for_test(4838), guard)
    }

    #[tokio::test]
    async fn create_compiles_checkpoint_rule_and_delete_retires_edge() {
        let (state, user, _guard) = plan_db_fixture().await;
        let mut second = node("n2", "issue", 483802, "l1", 1);
        second.is_checkpoint = true;
        second.checkpoint_target_ref_id = Some(483801);
        let write = payload(
            "informational",
            vec![lane("l1", 0)],
            vec![node("n1", "issue", 483801, "l1", 0), second],
        );
        let (status, Json(created)) =
            create_continuity_plan(State(state.clone()), user, Json(write))
                .await
                .expect("create plan");
        assert_eq!(status, StatusCode::CREATED);

        let conn = db::checkout(&state).await.expect("verify connection");
        let rule_count: i64 = conn
            .query_one(
                "SELECT count(*) FROM continuity_rules WHERE note = $1 AND user_id = $2",
                &[&format!("continuity-plan:{}", created.id), &user.id()],
            )
            .await
            .expect("rule count")
            .get(0);
        assert_eq!(rule_count, 1);
        let membership: i64 = conn
            .query_one(
                "SELECT count(*) FROM reading_plan_issues WHERE plan_id = $1",
                &[&created.id],
            )
            .await
            .expect("membership count")
            .get(0);
        assert_eq!(membership, 2);
        let edge: Option<i32> = conn
            .query_opt(
                "SELECT id FROM dependencies
                 WHERE source_issue_id = 483802 AND target_issue_id = 483801
                   AND note LIKE 'canonical:rule:%'",
                &[],
            )
            .await
            .expect("compiled edge")
            .map(|row| row.get(0));
        assert!(edge.is_some(), "checkpoint must compile a canonical edge");
        drop(conn);

        let status =
            delete_continuity_plan(State(state.clone()), user, axum::extract::Path(created.id))
                .await
                .expect("delete plan");
        assert_eq!(status, StatusCode::NO_CONTENT);

        let conn = db::checkout(&state).await.expect("verify connection 2");
        let edge_after: Option<i32> = conn
            .query_opt(
                "SELECT id FROM dependencies
                 WHERE source_issue_id = 483802 AND target_issue_id = 483801
                   AND note LIKE 'canonical:rule:%'",
                &[],
            )
            .await
            .expect("edge after delete")
            .map(|row| row.get(0));
        assert!(edge_after.is_none(), "deleting a plan must retire its edge");
        let rule_after: i64 = conn
            .query_one(
                "SELECT count(*) FROM continuity_rules WHERE note = $1",
                &[&format!("continuity-plan:{}", created.id)],
            )
            .await
            .expect("rules after delete")
            .get(0);
        assert_eq!(rule_after, 0);
    }

    #[tokio::test]
    async fn create_with_convergence_cycle_returns_structured_409_and_rolls_back() {
        let (state, user, _guard) = plan_db_fixture().await;
        let mut first = node("n1", "issue", 483801, "l1", 0);
        first.convergence_gate = vec![serde_json::json!({"node_type": "issue", "node_id": "n2"})];
        let mut second = node("n2", "issue", 483802, "l1", 1);
        second.convergence_gate = vec![serde_json::json!({"node_type": "issue", "node_id": "n1"})];
        let write = payload("informational", vec![lane("l1", 0)], vec![first, second]);

        let error = create_continuity_plan(State(state.clone()), user, Json(write))
            .await
            .expect_err("a convergence cycle must be rejected");
        assert_eq!(error.status(), StatusCode::CONFLICT);
        assert_eq!(
            error.structured_detail().expect("structured detail")["code"],
            "plan_convergence_cycle"
        );

        let conn = db::checkout(&state).await.expect("verify connection");
        let plans: i64 = conn
            .query_one(
                "SELECT count(*) FROM continuity_plans WHERE user_id = $1",
                &[&user.id()],
            )
            .await
            .expect("plan count")
            .get(0);
        assert_eq!(plans, 0, "a failed write must leave no plan behind");
    }

    #[tokio::test]
    async fn update_with_stale_version_returns_structured_conflict() {
        let (state, user, _guard) = plan_db_fixture().await;
        let write = payload(
            "informational",
            vec![lane("l1", 0)],
            vec![node("n1", "issue", 483801, "l1", 0)],
        );
        let (_, Json(created)) = create_continuity_plan(State(state.clone()), user, Json(write))
            .await
            .expect("create plan");

        let mut update = payload(
            "informational",
            vec![lane("l1", 0)],
            vec![node("n1", "issue", 483801, "l1", 0)],
        );
        update.expected_updated_at = Some("2000-01-01 00:00:00+00".to_string());
        let error = update_continuity_plan(
            State(state.clone()),
            user,
            axum::extract::Path(created.id),
            Json(update),
        )
        .await
        .expect_err("a stale version must be rejected");
        assert_eq!(error.status(), StatusCode::CONFLICT);
        assert_eq!(
            error.structured_detail().expect("structured detail")["code"],
            "plan_version_conflict"
        );
    }

    #[test]
    fn list_item_always_serializes_empty_source_fields() {
        // The plans list page reads `plan.source_paths[0]` and
        // `plan.source_paths.map(...)`, and the TypeScript contract declares
        // `source_paths: string[]` as required. The retired Python handler
        // emitted both source fields even when empty (Pydantic
        // `default_factory`). A prior Rust cutover omitted them via
        // `skip_serializing_if`, which crashed the list page for any plan
        // without CBL sources. Regression for issue #5394.
        let item = ContinuityPlanListItem {
            id: 1,
            name: "Plan A".to_string(),
            ordering_mode: "informational".to_string(),
            lane_count: 1,
            step_count: 5,
            source_paths: Vec::new(),
            source_names: serde_json::json!({}),
            updated_at: "2026-11-17T00:00:00Z".to_string(),
        };
        let value = serde_json::to_value(&item).expect("serialize list item");
        let obj = value.as_object().expect("list item is an object");
        assert!(
            obj.contains_key("source_paths"),
            "source_paths must always be present, including when empty"
        );
        assert_eq!(
            value["source_paths"],
            serde_json::json!([]),
            "source_paths must serialize as [] when empty"
        );
        assert!(
            obj.contains_key("source_names"),
            "source_names must always be present, including when empty"
        );
        assert_eq!(
            value["source_names"],
            serde_json::json!({}),
            "source_names must serialize as {{}} when empty"
        );
    }

    #[test]
    fn continuity_plan_response_always_emits_empty_lanes_and_nodes() {
        // Python ContinuityPlanResponse always emits lanes/nodes as arrays.
        // The planner editor reads planData.lanes.length and [...planData.nodes]
        // on required TS types, so omitting empty arrays crashes GET/create/update
        // responses for plans with zero lanes or zero nodes.
        let response = ContinuityPlanResponse {
            id: 7,
            user_id: 42,
            name: "Empty Plan".to_string(),
            ordering_mode: "informational".to_string(),
            lanes: Vec::new(),
            nodes: Vec::new(),
            created_at: "2026-11-17T00:00:00Z".to_string(),
            updated_at: "2026-11-17T00:00:00Z".to_string(),
        };
        let value = serde_json::to_value(&response).expect("serialize plan response");
        let obj = value.as_object().expect("plan response is an object");
        assert!(
            obj.contains_key("lanes"),
            "lanes must always be present, including when empty"
        );
        assert_eq!(
            value["lanes"],
            serde_json::json!([]),
            "lanes must serialize as [] when empty"
        );
        assert!(
            obj.contains_key("nodes"),
            "nodes must always be present, including when empty"
        );
        assert_eq!(
            value["nodes"],
            serde_json::json!([]),
            "nodes must serialize as [] when empty"
        );
    }

    #[test]
    fn continuity_plan_node_emits_null_optional_fields_and_empty_convergence_gate() {
        // Python ContinuityPlanNode emits null for optional reader/source/label
        // fields when absent (no exclude_if) and always emits convergence_gate as
        // an array. Rust previously omitted these when None/empty, diverging from
        // the frozen Python wire contract.
        let plan_node = node("n1", "issue", 101, "l1", 0);
        let value = serde_json::to_value(&plan_node).expect("serialize node");
        let obj = value.as_object().expect("node is an object");

        for field in [
            "label",
            "source_role",
            "source_confidence",
            "source_explanation",
            "source_paths",
            "source_cbl_placements",
            "source_story_arc_ids",
            "source_target_story_arc_id",
            "reader_role",
            "reader_optional",
        ] {
            assert!(obj.contains_key(field), "{field} must be present when None");
            assert!(
                value[field].is_null(),
                "{field} must serialize as null when None"
            );
        }

        assert!(
            obj.contains_key("convergence_gate"),
            "convergence_gate must always be present"
        );
        assert_eq!(
            value["convergence_gate"],
            serde_json::json!([]),
            "convergence_gate must serialize as [] when empty"
        );

        // Fields Python intentionally excludes when absent must remain omitted.
        assert!(
            !obj.contains_key("checkpoint_target_ref_id"),
            "checkpoint_target_ref_id should be omitted when None (Python exclude_if)"
        );
        assert!(
            !obj.contains_key("checkpoint_target_ref_ids"),
            "checkpoint_target_ref_ids should be omitted when empty (Python exclude_if)"
        );
    }

    #[tokio::test]
    async fn release_source_list_association_is_owner_scoped_unambiguous_and_retry_safe() {
        let (state, user, _guard) = plan_db_fixture().await;
        let connection = db::checkout(&state).await.expect("fixture connection");
        connection
            .batch_execute(
                "INSERT INTO users (id, username) VALUES (4839, 'other-list-owner');
                 INSERT INTO continuity_plans
                   (id, user_id, name, ordering_mode, nodes_json, lanes_json, created_at, updated_at)
                 VALUES (483881, 4838, 'Ambiguous provenance', 'informational', '[]'::json, '[]'::json, NOW(), NOW()),
                        (483882, 4838, 'Single provenance', 'informational', '[]'::json, '[]'::json, NOW(), NOW()),
                        (483883, 4838, 'Explicit list', 'informational', '[]'::json, '[]'::json, NOW(), NOW());
                 INSERT INTO custom_cbl_lists
                   (id, user_id, name, description, mode, created_at, updated_at)
                 VALUES (483831, 4838, 'List A', NULL, 'loose', NOW(), NOW()),
                        (483832, 4838, 'List B', NULL, 'loose', NOW(), NOW()),
                        (483833, 4839, 'Foreign list', NULL, 'loose', NOW(), NOW());
                 INSERT INTO reading_plan_sources (plan_id, raw_source_path, custom_cbl_list_id, recorded_at)
                 VALUES (483881, 'custom-cbl:a', 483831, NOW()),
                        (483881, 'custom-cbl:b', 483832, NOW()),
                        (483882, 'custom-cbl:b', 483832, NOW()),
                         (483882, 'custom-cbl:foreign', 483833, NOW());
                 INSERT INTO external_identities
                   (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
                 VALUES (483810, 'comicvine', 'series', '4050-4838', '{}'::json, NOW(), NOW());
                 INSERT INTO thread_external_series_mappings
                   (thread_id, external_identity_id, status, created_at, updated_at)
                 VALUES (4838, 483810, 'confirmed', NOW(), NOW());",
            )
            .await
            .expect("seed release-source list fixtures");
        drop(connection);

        let payload = |plan_id, custom_cbl_list_id| ReleaseSourceCreate {
            plan_id,
            thread_id: 4838,
            external_identity_id: 483810,
            custom_cbl_list_id,
        };
        let (_, Json(ambiguous)) =
            create_release_source(State(state.clone()), user, Json(payload(483881, None)))
                .await
                .expect("ambiguous provenance remains unlinked");
        assert_eq!(ambiguous.custom_cbl_list_id, None);

        let connection = db::checkout(&state).await.expect("disable connection");
        connection
            .execute(
                "UPDATE reading_plan_release_sources \
                 SET enabled = FALSE, last_synced_at = '2024-01-02T03:04:05Z' WHERE id = $1",
                &[&ambiguous.id],
            )
            .await
            .expect("preserve existing subscription state");
        drop(connection);

        let (_, Json(associated)) = create_release_source(
            State(state.clone()),
            user,
            Json(payload(483881, Some(483831))),
        )
        .await
        .expect("explicit reassociation");
        assert_eq!(associated.id, ambiguous.id);
        assert_eq!(associated.custom_cbl_list_id, Some(483831));
        assert_eq!(associated.created_at, ambiguous.created_at);
        assert!(!associated.enabled, "retry must preserve disabled state");
        assert!(associated.last_synced_at.is_some());

        let (_, Json(retry)) = create_release_source(
            State(state.clone()),
            user,
            Json(payload(483881, Some(483832))),
        )
        .await
        .expect("retry keeps established association");
        assert_eq!(retry.id, ambiguous.id);
        assert_eq!(retry.custom_cbl_list_id, Some(483831));
        assert_eq!(retry.last_synced_at, associated.last_synced_at);
        assert!(!retry.enabled);

        let foreign = create_release_source(
            State(state.clone()),
            user,
            Json(payload(483881, Some(483833))),
        )
        .await
        .expect_err("another reader's list must not be associated");
        assert_eq!(foreign.status(), StatusCode::NOT_FOUND);

        let (_, Json(inferred)) =
            create_release_source(State(state.clone()), user, Json(payload(483882, None)))
                .await
                .expect("single same-owner provenance");
        assert_eq!(inferred.custom_cbl_list_id, Some(483832));
        let (_, Json(explicit)) = create_release_source(
            State(state.clone()),
            user,
            Json(payload(483883, Some(483831))),
        )
        .await
        .expect("explicit list-native creation");
        assert_eq!(explicit.custom_cbl_list_id, Some(483831));

        let connection = db::checkout(&state).await.expect("verify connection");
        let source_count: i64 = connection
            .query_one("SELECT count(*) FROM reading_plan_release_sources", &[])
            .await
            .expect("retry-safe source count")
            .get(0);
        assert_eq!(source_count, 3);
        let persisted_updated_at: String = connection
            .query_one(
                "SELECT updated_at::text FROM reading_plan_release_sources WHERE id = $1",
                &[&ambiguous.id],
            )
            .await
            .expect("association timestamp")
            .get(0);
        assert_eq!(associated.updated_at, persisted_updated_at);
        let preserved: bool = connection
            .query_one(
                "SELECT enabled = FALSE AND last_synced_at = '2024-01-02T03:04:05Z' \
                   AND custom_cbl_list_id = 483831 \
                 FROM reading_plan_release_sources WHERE id = $1",
                &[&ambiguous.id],
            )
            .await
            .expect("preserved subscription")
            .get(0);
        assert!(preserved);
    }

    #[tokio::test]
    async fn continuity_graph_advisory_lock_is_taken_in_a_transaction() {
        // Python `lock_continuity_graph` serializes plan writes with this
        // namespace; the native writer must take the identical transaction lock.
        assert_eq!(CONTINUITY_LOCK_NAMESPACE, 1_129_274_964);
        let (state, _user, _guard) = plan_db_fixture().await;
        let mut conn = db::checkout(&state).await.expect("lock connection");
        let tx = conn
            .build_transaction()
            .start()
            .await
            .expect("lock transaction");
        lock_continuity_graph(&tx, 4838)
            .await
            .expect("pg_advisory_xact_lock must execute");
        // Advisory locks are reentrant within one session/transaction.
        lock_continuity_graph(&tx, 4838)
            .await
            .expect("reentrant advisory lock");
        tx.commit().await.expect("commit lock transaction");
    }
}
