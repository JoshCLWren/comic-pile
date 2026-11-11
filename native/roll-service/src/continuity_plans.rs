//! Native same-path handlers for the browser-called continuity-plans API.
//!
//! The Python implementation remains mounted until production execution is
//! proven. This module mirrors the owner checks, validation, wire shapes,
//! membership rebuild, strict-rule compilation, and transaction semantics of
//! `app/api/continuity_plan.py`, `app/api/reading_plan_release_source.py`,
//! and `app/api/reading_order_projection.py`.

use crate::{
    auth::AuthenticatedUser,
    db,
    issue_service::refresh_blocked_threads,
    ApiError, AppState,
};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::Response,
    Json,
};
use chrono::{DateTime, TimeZone, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;
use std::sync::Arc;
use tokio_postgres::{Row, Transaction};
use utoipa::ToSchema;

const PLAN_RULE_MARKER_PREFIX: &str = "continuity-plan";
const RULE_NOTE_PREFIX: &str = "canonical:rule:";
const BACKFILL_NOTE_PREFIX: &str = "canonical:rule-backfill:";
const CBL_ORDER_NOTE_PREFIX: &str = "cbl-order:";

fn plan_rule_marker(plan_id: i32) -> String {
    format!("{PLAN_RULE_MARKER_PREFIX}:{plan_id}")
}

/// Python-compatible ISO 8601 serialization (`T` separator, `+00:00` offset,
/// fractional seconds only when non-zero), matching `datetime.isoformat()`.
fn python_isoformat(value: &DateTime<Utc>) -> String {
    let nanos = value.timestamp_subsec_nanos();
    let micros = nanos / 1_000;
    if micros == 0 {
        value.format("%Y-%m-%dT%H:%M:%S+00:00").to_string()
    } else {
        format!("{}.{:06}+00:00", value.format("%Y-%m-%dT%H:%M:%S"), micros)
    }
}

/// Parse a persisted or incoming timestamp, accepting both Python's
/// `T`-separated ISO form and PostgreSQL `::text` casts (` ` separator,
/// short `+00` offset). Naive inputs are treated as UTC, matching Python.
fn parse_python_datetime(raw: &str) -> Option<DateTime<Utc>> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return None;
    }
    let normalized = normalize_datetime_text(trimmed);
    DateTime::parse_from_rfc3339(&normalized)
        .map(|value| value.with_timezone(&Utc))
        .ok()
}

fn normalize_datetime_text(trimmed: &str) -> String {
    let value = trimmed.replace(' ', "T");
    let Some((date, time)) = value.split_once('T') else {
        return value;
    };
    let upper = time.to_ascii_uppercase();
    let (clock, offset) = if let Some(clock) = upper.strip_suffix('Z') {
        (clock.to_string(), "+00:00".to_string())
    } else if let Some(index) = upper.rfind(['+', '-']) {
        (
            upper[..index].to_string(),
            normalize_offset(&upper[index..]),
        )
    } else {
        // No offset: treat as UTC (Python assumes naive == UTC).
        (upper, "+00:00".to_string())
    };
    format!("{date}T{clock}{offset}")
}

fn normalize_offset(raw: &str) -> String {
    let sign = if raw.starts_with('-') { '-' } else { '+' };
    let digits = &raw[1..];
    match digits.len() {
        2 => format!("{sign}{digits}:00"),
        4 if !digits.contains(':') => format!("{sign}{}:{}", &digits[..2], &digits[2..]),
        _ => format!("{sign}{digits}"),
    }
}

fn json_datetime(value: &Value) -> Option<DateTime<Utc>> {
    value.as_str().and_then(parse_python_datetime)
}

/// PostgreSQL emits timestamps for chrono; re-render them Python-style.
fn row_datetime(row: &Row, index: usize) -> DateTime<Utc> {
    row.get::<_, DateTime<Utc>>(index)
}

// ---------------------------------------------------------------------------
// Wire types
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema, PartialEq)]
pub struct ContinuityPlanLane {
    pub id: String,
    pub name: String,
    pub order: i64,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub inferred_gate_kind: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub migration_contract: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema, PartialEq)]
pub struct ConvergenceGateTarget {
    pub node_type: String,
    pub node_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema, PartialEq)]
pub struct CBLPlacement {
    pub source_path: String,
    pub position: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema, PartialEq)]
pub struct ContinuityPlanNode {
    pub id: String,
    pub node_type: String,
    pub ref_id: i64,
    pub lane_id: String,
    pub position: i64,
    #[serde(default)]
    pub label: Option<String>,
    #[serde(default)]
    pub source_role: Option<String>,
    #[serde(default)]
    pub source_confidence: Option<String>,
    #[serde(default)]
    pub source_explanation: Option<String>,
    #[serde(default)]
    pub source_paths: Option<Vec<String>>,
    #[serde(default)]
    pub source_cbl_placements: Option<Vec<CBLPlacement>>,
    #[serde(default)]
    pub source_story_arc_ids: Option<Vec<String>>,
    #[serde(default)]
    pub source_target_story_arc_id: Option<String>,
    #[serde(default)]
    pub reader_role: Option<String>,
    #[serde(default)]
    pub reader_optional: Option<bool>,
    #[serde(default)]
    pub is_checkpoint: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub checkpoint_target_ref_id: Option<i64>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub checkpoint_target_ref_ids: Vec<i64>,
    #[serde(default)]
    pub convergence_gate: Vec<ConvergenceGateTarget>,
}

impl ContinuityPlanNode {
    /// Membership-authoritative editor nodes compare equal by identity.
    fn identity_key(&self) -> Value {
        let gates: Vec<Value> = self
            .convergence_gate
            .iter()
            .map(|target| json!([target.node_type, target.node_id]))
            .collect();
        let mut targets = self.checkpoint_target_ref_ids.clone();
        targets.sort_unstable();
        json!([
            self.id,
            self.node_type,
            self.ref_id,
            self.lane_id,
            self.position,
            self.is_checkpoint,
            self.checkpoint_target_ref_id,
            targets,
            gates,
        ])
    }
}

/// Write payloads keep Pydantic's bool rejection for integer ids.
#[derive(Debug, Deserialize)]
pub struct ContinuityPlanWrite {
    pub name: String,
    #[serde(default = "default_ordering_mode")]
    pub ordering_mode: String,
    pub lanes: Vec<ContinuityPlanLane>,
    #[serde(default)]
    pub nodes: Vec<Value>,
    #[serde(default)]
    pub expected_updated_at: Option<Value>,
}

fn default_ordering_mode() -> String {
    "informational".to_string()
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ContinuityPlanResponse {
    pub id: i32,
    pub user_id: i32,
    pub name: String,
    pub ordering_mode: String,
    pub lanes: Vec<Value>,
    pub nodes: Vec<Value>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ContinuityPlanListItem {
    pub id: i32,
    pub name: String,
    pub ordering_mode: String,
    pub lane_count: i64,
    pub step_count: i64,
    pub source_paths: Vec<String>,
    pub source_names: Map<String, Value>,
    pub updated_at: String,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingPlanMemberIssue {
    pub occurrence_id: String,
    pub issue_id: i32,
    pub lane_id: String,
    pub display_position: i32,
    pub label: Option<String>,
    pub reader_role: Option<String>,
    pub reader_optional: Option<bool>,
    pub is_checkpoint: bool,
    pub source_metadata: Option<Value>,
}

#[derive(Debug, Serialize, Deserialize, ToSchema, PartialEq)]
pub struct ReadingPlanDependencyLink {
    pub dependency_id: i32,
    pub source_issue_id: i32,
    pub target_issue_id: i32,
    pub explanation: Option<String>,
}

#[derive(Debug, Serialize, ToSchema)]
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

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingPlanSourcePlacementView {
    pub id: i32,
    pub occurrence_id: String,
    pub plan_source_id: i32,
    pub source_position: Option<i32>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingPlanProgress {
    pub total_issues: i64,
    pub read_issues: i64,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingPlanMembershipResponse {
    pub plan_id: i32,
    pub issues: Vec<ReadingPlanMemberIssue>,
    pub dependencies: Vec<ReadingPlanDependencyLink>,
    pub sources: Vec<ReadingPlanSourceSnapshot>,
    pub placements: Vec<ReadingPlanSourcePlacementView>,
    pub progress: ReadingPlanProgress,
}

#[derive(Debug, Deserialize, ToSchema)]
pub struct ReadingPlanDependencyLinkRequest {
    #[serde(default)]
    pub explanation: Option<String>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReleaseSourceResponse {
    pub id: i32,
    pub plan_id: i32,
    pub thread_id: i32,
    pub external_identity_id: i32,
    pub provider: String,
    pub provider_volume_id: String,
    pub provider_title: Option<String>,
    pub enabled: bool,
    pub last_synced_at: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingPlanReleaseSourceStatus {
    pub source_id: i32,
    pub thread_id: i32,
    pub external_identity_id: i32,
    pub provider_volume_id: String,
    pub provider_title: Option<String>,
    pub provider_publisher: Option<String>,
    pub provider_start_year: Option<i64>,
    pub provider_issue_count: Option<i64>,
    pub enabled: bool,
    pub last_synced_at: Option<String>,
}

#[derive(Debug, Deserialize, ToSchema)]
pub struct ReleaseSourceCreate {
    pub plan_id: i64,
    pub thread_id: i64,
    pub external_identity_id: i64,
}

#[derive(Debug, Deserialize, ToSchema)]
pub struct ReleaseSourceUpdate {
    pub enabled: bool,
}

#[derive(Debug, Deserialize, ToSchema)]
pub struct ReadingOrderAdoptRequest {
    pub reading_order_id: i64,
    #[serde(default)]
    pub plan_name: Option<String>,
    #[serde(default = "default_lane_id")]
    pub lane_id: String,
    #[serde(default = "default_lane_name")]
    pub lane_name: String,
}

fn default_lane_id() -> String {
    "adopted".to_string()
}

fn default_lane_name() -> String {
    "Adopted".to_string()
}

#[derive(Debug, Deserialize, ToSchema)]
pub struct ReadingOrderProjectionRequest {
    pub reading_order_id: i64,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingOrderProjectionEntry {
    pub thread_id: i32,
    pub thread_title: Option<String>,
    pub position: i64,
    pub source: String,
    pub source_node_id: Option<String>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingOrderProjectionConflict {
    pub code: String,
    pub message: String,
    pub node_id: String,
    pub thread_id: Option<i32>,
    pub existing_positions: Vec<i64>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingOrderProjectionResult {
    pub plan_id: i32,
    pub reading_order_id: i32,
    pub added_count: i64,
    pub updated_count: i64,
    pub kept_count: i64,
    pub total_positions: i64,
}

// ---------------------------------------------------------------------------
// Write-payload validation (port of ContinuityPlanWrite.validate_structure)
// ---------------------------------------------------------------------------

fn validation_error(message: impl Into<String>) -> ApiError {
    ApiError::with_status(StatusCode::UNPROCESSABLE_ENTITY, message.into())
}

fn structured_error(status: StatusCode, detail: Value) -> ApiError {
    ApiError::Structured { status, detail }
}

const NODE_TYPES: [&str; 3] = ["issue", "crossover", "thread"];
const SOURCE_ROLES: [&str; 4] = ["core", "context/prelude", "epilogue", "unknown"];
const SOURCE_CONFIDENCES: [&str; 3] = ["high", "medium", "low"];
const READER_ROLES: [&str; 6] = [
    "required/core",
    "recommended",
    "optional",
    "context/prelude",
    "aftermath/epilogue",
    "skipped/excluded",
];
const INFERRED_GATE_KINDS: [&str; 2] = ["thread_entry", "reading_order"];

fn validate_string_field(
    value: &str,
    field: &str,
    min: usize,
    max: usize,
) -> Result<(), ApiError> {
    let length = value.chars().count();
    if length < min {
        return Err(validation_error(format!(
            "{field} must have at least {min} characters"
        )));
    }
    if length > max {
        return Err(validation_error(format!(
            "{field} must have at most {max} characters"
        )));
    }
    Ok(())
}

fn validate_write(write: &ContinuityPlanWrite, nodes: &[ContinuityPlanNode]) -> Result<(), ApiError> {
    validate_string_field(&write.name, "name", 1, 200)?;
    if write.ordering_mode != "informational" && write.ordering_mode != "strict_sequential" {
        return Err(validation_error(
            "ordering_mode must be 'informational' or 'strict_sequential'",
        ));
    }
    if write.lanes.len() > 100 {
        return Err(validation_error("lanes must have at most 100 entries"));
    }
    if nodes.len() > 1000 {
        return Err(validation_error("nodes must have at most 1000 entries"));
    }

    let mut lane_ids = BTreeSet::new();
    let mut lane_orders = BTreeSet::new();
    for lane in &write.lanes {
        validate_string_field(&lane.id, "lane id", 1, 80)?;
        validate_string_field(&lane.name, "lane name", 1, 120)?;
        if lane.order < 0 {
            return Err(validation_error("lane order must be greater than or equal to 0"));
        }
        if !lane_ids.insert(lane.id.as_str()) {
            return Err(validation_error("lane ids must be unique"));
        }
        if !lane_orders.insert(lane.order) {
            return Err(validation_error("lane order values must be unique"));
        }
        if let Some(kind) = lane.inferred_gate_kind.as_deref() {
            if !INFERRED_GATE_KINDS.contains(&kind) {
                return Err(validation_error(format!(
                    "inferred_gate_kind must be one of: {}",
                    INFERRED_GATE_KINDS.join(", ")
                )));
            }
        }
    }

    let mut node_ids = BTreeSet::new();
    for node in nodes {
        validate_string_field(&node.id, "node id", 1, 80)?;
        if !NODE_TYPES.contains(&node.node_type.as_str()) {
            return Err(validation_error(
                "node_type must be 'issue', 'crossover', or 'thread'",
            ));
        }
        if node.ref_id <= 0 {
            return Err(validation_error("ref_id must be greater than 0"));
        }
        validate_string_field(&node.lane_id, "node lane_id", 1, 80)?;
        if node.position < 0 {
            return Err(validation_error("position must be greater than or equal to 0"));
        }
        if let Some(label) = node.label.as_deref() {
            validate_string_field(label, "label", 0, 200)?;
        }
        if let Some(role) = node.source_role.as_deref() {
            if !SOURCE_ROLES.contains(&role) {
                return Err(validation_error("source_role is not a supported value"));
            }
        }
        if let Some(confidence) = node.source_confidence.as_deref() {
            if !SOURCE_CONFIDENCES.contains(&confidence) {
                return Err(validation_error("source_confidence is not a supported value"));
            }
        }
        if let Some(role) = node.reader_role.as_deref() {
            if !READER_ROLES.contains(&role) {
                return Err(validation_error("reader_role is not a supported value"));
            }
        }
        if node.checkpoint_target_ref_id.is_some_and(|id| id <= 0) {
            return Err(validation_error(
                "checkpoint_target_ref_id must be greater than 0",
            ));
        }
        if node.checkpoint_target_ref_ids.len() > 1000 {
            return Err(validation_error(
                "checkpoint_target_ref_ids must have at most 1000 entries",
            ));
        }
        if node.checkpoint_target_ref_ids.iter().any(|id| *id <= 0) {
            return Err(validation_error(
                "checkpoint_target_ref_ids must contain positive integers",
            ));
        }
        for target in &node.convergence_gate {
            validate_string_field(&target.node_id, "convergence gate node_id", 1, 80)?;
            if !NODE_TYPES.contains(&target.node_type.as_str()) {
                return Err(validation_error(
                    "convergence gate node_type must be 'issue', 'crossover', or 'thread'",
                ));
            }
        }
        if !node_ids.insert(node.id.as_str()) {
            return Err(validation_error("node ids must be unique"));
        }
    }

    let issue_refs: Vec<i64> = nodes
        .iter()
        .filter(|node| node.node_type == "issue")
        .map(|node| node.ref_id)
        .collect();
    let unique_refs: BTreeSet<i64> = issue_refs.iter().copied().collect();
    if unique_refs.len() != issue_refs.len() {
        return Err(validation_error("an issue may appear at most once in a plan"));
    }

    let known_lanes: BTreeSet<&str> = write.lanes.iter().map(|lane| lane.id.as_str()).collect();
    if nodes.iter().any(|node| !known_lanes.contains(node.lane_id.as_str())) {
        return Err(validation_error("every node must reference an existing lane"));
    }

    let mut positions_by_lane: std::collections::HashMap<&str, BTreeSet<i64>> =
        std::collections::HashMap::new();
    for node in nodes {
        if !positions_by_lane
            .entry(node.lane_id.as_str())
            .or_default()
            .insert(node.position)
        {
            return Err(validation_error(
                "node positions must be unique within each lane",
            ));
        }
    }

    if write.ordering_mode == "strict_sequential" {
        if write.lanes.len() != 1 {
            return Err(validation_error(
                "strict sequential plans must use exactly one lane",
            ));
        }
        if nodes.iter().any(|node| node.node_type == "thread") {
            return Err(validation_error(
                "strict sequential plans may contain only issue/crossover nodes",
            ));
        }
        let positions: Vec<i64> = nodes.iter().map(|node| node.position).collect();
        let mut sorted = positions.clone();
        sorted.sort_unstable();
        if sorted != (0..sorted.len() as i64).collect::<Vec<i64>>() {
            return Err(validation_error(
                "strict sequential positions must be contiguous starting at zero",
            ));
        }
    }

    for node in nodes {
        if node.is_checkpoint && node.node_type != "issue" {
            return Err(validation_error(format!(
                "checkpoint on node '{}' is only allowed on issue nodes",
                node.id
            )));
        }
        if (node.checkpoint_target_ref_id.is_some() || !node.checkpoint_target_ref_ids.is_empty())
            && !node.is_checkpoint
        {
            return Err(validation_error(format!(
                "checkpoint target on node '{}' requires is_checkpoint",
                node.id
            )));
        }
        let target_set: BTreeSet<i64> = node.checkpoint_target_ref_ids.iter().copied().collect();
        if target_set.len() != node.checkpoint_target_ref_ids.len() {
            return Err(validation_error(format!(
                "checkpoint on node '{}' contains duplicate targets",
                node.id
            )));
        }
    }

    let known_node_ids: BTreeSet<&str> = nodes.iter().map(|node| node.id.as_str()).collect();
    let nodes_by_id: std::collections::HashMap<&str, &ContinuityPlanNode> =
        nodes.iter().map(|node| (node.id.as_str(), node)).collect();
    for node in nodes {
        if node.convergence_gate.is_empty() {
            continue;
        }
        if node.node_type != "issue" && node.node_type != "crossover" {
            return Err(validation_error(format!(
                "convergence gate on node '{}' is only allowed on issue/crossover nodes",
                node.id
            )));
        }
        let gate_ids: Vec<&str> = node
            .convergence_gate
            .iter()
            .map(|target| target.node_id.as_str())
            .collect();
        let unique: BTreeSet<&str> = gate_ids.iter().copied().collect();
        if unique.len() != gate_ids.len() {
            return Err(validation_error(format!(
                "convergence gate on node '{}' contains duplicate targets",
                node.id
            )));
        }
        for target in &node.convergence_gate {
            if target.node_id == node.id {
                return Err(validation_error(format!(
                    "convergence gate on node '{}' cannot wait for itself",
                    node.id
                )));
            }
            if !known_node_ids.contains(target.node_id.as_str()) {
                return Err(validation_error(format!(
                    "convergence gate on node '{}' references unknown node '{}'",
                    node.id, target.node_id
                )));
            }
            if let Some(target_node) = nodes_by_id.get(target.node_id.as_str()) {
                if target_node.node_type != "issue" && target_node.node_type != "crossover" {
                    return Err(validation_error(format!(
                        "convergence gate on node '{}' references node '{}' of type '{}'; convergence targets must be issue/crossover nodes",
                        node.id, target.node_id, target_node.node_type
                    )));
                }
            }
        }
    }

    Ok(())
}

/// Parse the raw `nodes` array, returning typed nodes plus a parallel vector
/// that records whether each node explicitly carried checkpoint target fields
/// (used to preserve server-owned checkpoint targets on ordinary saves).
fn parse_write_nodes(raw: &[Value]) -> Result<(Vec<ContinuityPlanNode>, Vec<bool>), ApiError> {
    let mut nodes = Vec::with_capacity(raw.len());
    let mut fields_set = Vec::with_capacity(raw.len());
    for value in raw {
        let object = value
            .as_object()
            .ok_or_else(|| validation_error("each node must be a JSON object"))?;
        let has_targets = object.contains_key("checkpoint_target_ref_id")
            || object.contains_key("checkpoint_target_ref_ids");
        let node: ContinuityPlanNode = serde_json::from_value(value.clone())
            .map_err(|error| validation_error(format!("invalid node payload: {error}")))?;
        nodes.push(node);
        fields_set.push(has_targets);
    }
    Ok((nodes, fields_set))
}

fn parse_expected_updated_at(value: &Option<Value>) -> Result<Option<DateTime<Utc>>, ApiError> {
    let Some(raw) = value else { return Ok(None) };
    let Some(text) = raw.as_str() else {
        return Err(validation_error(
            "expected_updated_at must be an ISO 8601 datetime string",
        ));
    };
    parse_python_datetime(text)
        .map(Some)
        .ok_or_else(|| validation_error("expected_updated_at must be an ISO 8601 datetime string"))
}

/// Serialize nodes for storage, matching Pydantic's `exclude_if` behavior:
/// `checkpoint_target_ref_id` is dropped when null and
/// `checkpoint_target_ref_ids` when empty. All other keys are kept.
fn dump_node(node: &ContinuityPlanNode) -> Value {
    let mut object = serde_json::Map::new();
    object.insert("id".to_string(), json!(node.id));
    object.insert("node_type".to_string(), json!(node.node_type));
    object.insert("ref_id".to_string(), json!(node.ref_id));
    object.insert("lane_id".to_string(), json!(node.lane_id));
    object.insert("position".to_string(), json!(node.position));
    object.insert("label".to_string(), json!(node.label));
    object.insert("source_role".to_string(), json!(node.source_role));
    object.insert("source_confidence".to_string(), json!(node.source_confidence));
    object.insert("source_explanation".to_string(), json!(node.source_explanation));
    object.insert("source_paths".to_string(), json!(node.source_paths));
    object.insert(
        "source_cbl_placements".to_string(),
        json!(node.source_cbl_placements),
    );
    object.insert(
        "source_story_arc_ids".to_string(),
        json!(node.source_story_arc_ids),
    );
    object.insert(
        "source_target_story_arc_id".to_string(),
        json!(node.source_target_story_arc_id),
    );
    object.insert("reader_role".to_string(), json!(node.reader_role));
    object.insert("reader_optional".to_string(), json!(node.reader_optional));
    object.insert("is_checkpoint".to_string(), json!(node.is_checkpoint));
    if let Some(target) = node.checkpoint_target_ref_id {
        object.insert("checkpoint_target_ref_id".to_string(), json!(target));
    }
    if !node.checkpoint_target_ref_ids.is_empty() {
        object.insert(
            "checkpoint_target_ref_ids".to_string(),
            json!(node.checkpoint_target_ref_ids),
        );
    }
    object.insert("convergence_gate".to_string(), json!(node.convergence_gate));
    Value::Object(object)
}

/// Serialize lanes for storage, dropping client-authored migration proof.
fn dump_lane(lane: &ContinuityPlanLane) -> Value {
    let mut object = serde_json::Map::new();
    object.insert("id".to_string(), json!(lane.id));
    object.insert("name".to_string(), json!(lane.name));
    object.insert("order".to_string(), json!(lane.order));
    if let Some(kind) = &lane.inferred_gate_kind {
        object.insert("inferred_gate_kind".to_string(), json!(kind));
    }
    Value::Object(object)
}

fn lane_response_value(lane: &ContinuityPlanLane) -> Value {
    let mut object = serde_json::Map::new();
    object.insert("id".to_string(), json!(lane.id));
    object.insert("name".to_string(), json!(lane.name));
    object.insert("order".to_string(), json!(lane.order));
    if let Some(kind) = &lane.inferred_gate_kind {
        object.insert("inferred_gate_kind".to_string(), json!(kind));
    }
    if let Some(contract) = &lane.migration_contract {
        object.insert("migration_contract".to_string(), contract.clone());
    }
    Value::Object(object)
}

struct PlanRow {
    id: i32,
    user_id: i32,
    name: String,
    ordering_mode: String,
    nodes_json_text: String,
    lanes_json_text: String,
    created_at: DateTime<Utc>,
    updated_at: DateTime<Utc>,
}

impl PlanRow {
    fn nodes_json(&self) -> Value {
        serde_json::from_str(&self.nodes_json_text).unwrap_or(Value::Array(Vec::new()))
    }

    fn lanes_json(&self) -> Value {
        serde_json::from_str(&self.lanes_json_text).unwrap_or(Value::Array(Vec::new()))
    }

    fn typed_nodes(&self) -> Vec<ContinuityPlanNode> {
        parse_stored_nodes(&self.nodes_json())
    }

    fn typed_lanes(&self) -> Vec<ContinuityPlanLane> {
        let value = self.lanes_json();
        value
            .as_array()
            .map(|items| {
                items
                    .iter()
                    .filter_map(|item| serde_json::from_value::<ContinuityPlanLane>(item.clone()).ok())
                    .collect()
            })
            .unwrap_or_default()
    }
}

/// Parse stored `nodes_json`, dropping entries that no longer validate.
fn parse_stored_nodes(value: &Value) -> Vec<ContinuityPlanNode> {
    value
        .as_array()
        .map(|items| {
            items
                .iter()
                .filter_map(|item| serde_json::from_value::<ContinuityPlanNode>(item.clone()).ok())
                .collect()
        })
        .unwrap_or_default()
}

const PLAN_SELECT: &str = "SELECT id, user_id, name, ordering_mode, nodes_json::text, lanes_json::text, created_at, updated_at FROM continuity_plans";

fn plan_row(row: &Row) -> PlanRow {
    PlanRow {
        id: row.get(0),
        user_id: row.get(1),
        name: row.get(2),
        ordering_mode: row.get(3),
        nodes_json_text: row.get(4),
        lanes_json_text: row.get(5),
        created_at: row_datetime(row, 6),
        updated_at: row_datetime(row, 7),
    }
}

async fn fetch_plan(
    tx: &Transaction<'_>,
    user_id: i32,
    plan_id: i32,
) -> Result<Option<PlanRow>, ApiError> {
    let row = tx
        .query_opt(
            &format!("{PLAN_SELECT} WHERE id = $1 AND user_id = $2"),
            &[&plan_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(row.map(|row| plan_row(&row)))
}

async fn fetch_plan_conn(
    state: &AppState,
    user_id: i32,
    plan_id: i32,
) -> Result<Option<PlanRow>, ApiError> {
    let connection = db::checkout(state).await?;
    let row = connection
        .query_opt(
            &format!("{PLAN_SELECT} WHERE id = $1 AND user_id = $2"),
            &[&plan_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(row.map(|row| plan_row(&row)))
}

fn plan_not_found(plan_id: i32) -> ApiError {
    ApiError::NotFound(format!("Continuity plan {plan_id} not found"))
}

async fn owned_plan(
    tx: &Transaction<'_>,
    user_id: i32,
    plan_id: i32,
) -> Result<PlanRow, ApiError> {
    fetch_plan(tx, user_id, plan_id)
        .await?
        .ok_or_else(|| plan_not_found(plan_id))
}

// ---------------------------------------------------------------------------
// Membership loading and editor-node overlay
// ---------------------------------------------------------------------------

struct MemberRow {
    occurrence_id: String,
    issue_id: i32,
    lane_id: String,
    display_position: i32,
    label: Option<String>,
    reader_role: Option<String>,
    reader_optional: Option<bool>,
    is_checkpoint: bool,
    source_metadata_text: Option<String>,
}

const MEMBER_SELECT: &str = "SELECT occurrence_id, issue_id, lane_id, display_position, label, reader_role, reader_optional, is_checkpoint, source_metadata_json::text FROM reading_plan_issues WHERE plan_id = $1 ORDER BY lane_id, display_position";

fn member_row(row: &Row) -> MemberRow {
    MemberRow {
        occurrence_id: row.get(0),
        issue_id: row.get(1),
        lane_id: row.get(2),
        display_position: row.get(3),
        label: row.get(4),
        reader_role: row.get(5),
        reader_optional: row.get(6),
        is_checkpoint: row.get(7),
        source_metadata_text: row.get(8),
    }
}

async fn list_plan_members(
    tx: &Transaction<'_>,
    plan_id: i32,
) -> Result<Vec<MemberRow>, ApiError> {
    let rows = tx
        .query(MEMBER_SELECT, &[&plan_id])
        .await
        .map_err(db::query_error)?;
    Ok(rows.iter().map(member_row).collect())
}

fn member_metadata(member: &MemberRow) -> Option<Value> {
    member
        .source_metadata_text
        .as_deref()
        .and_then(|text| serde_json::from_str::<Value>(text).ok())
        .filter(Value::is_object)
}

/// Membership-authoritative editor nodes (port of `overlay_membership_editor_nodes`).
fn overlay_membership_editor_nodes(
    members: &[MemberRow],
    nodes_json: &Value,
) -> Vec<ContinuityPlanNode> {
    let mut json_by_id: std::collections::HashMap<String, Value> = std::collections::HashMap::new();
    let mut extra_non_issue: Vec<Value> = Vec::new();
    if let Some(items) = nodes_json.as_array() {
        for raw in items {
            let Some(object) = raw.as_object() else { continue };
            let node_id = object.get("id").and_then(Value::as_str).map(str::to_string);
            match object.get("node_type").and_then(Value::as_str) {
                Some("issue") => {
                    if let Some(node_id) = node_id.filter(|id| !id.is_empty()) {
                        json_by_id.insert(node_id, raw.clone());
                    }
                }
                Some(kind @ ("crossover" | "thread")) => {
                    let _ = kind;
                    extra_non_issue.push(raw.clone());
                }
                _ => {}
            }
        }
    }

    let mut nodes: Vec<ContinuityPlanNode> = Vec::with_capacity(members.len() + extra_non_issue.len());
    for member in members {
        let mut overlay = json_by_id
            .get(&member.occurrence_id)
            .cloned()
            .and_then(|value| value.as_object().cloned())
            .unwrap_or_default();
        overlay.insert("id".to_string(), json!(member.occurrence_id));
        overlay.insert("node_type".to_string(), json!("issue"));
        overlay.insert("ref_id".to_string(), json!(member.issue_id));
        overlay.insert("lane_id".to_string(), json!(member.lane_id));
        overlay.insert("position".to_string(), json!(member.display_position));
        overlay.insert("is_checkpoint".to_string(), json!(member.is_checkpoint));
        if let Some(label) = &member.label {
            overlay.insert("label".to_string(), json!(label));
        }
        if let Some(role) = &member.reader_role {
            overlay.insert("reader_role".to_string(), json!(role));
        }
        if let Some(optional) = member.reader_optional {
            overlay.insert("reader_optional".to_string(), json!(optional));
        }
        if let Some(metadata) = member_metadata(member).and_then(|value| value.as_object().cloned()) {
            for (key, value) in metadata {
                if overlay.get(&key).is_none() || overlay.get(&key) == Some(&Value::Null) {
                    overlay.insert(key, value);
                }
            }
        }
        match serde_json::from_value::<ContinuityPlanNode>(Value::Object(overlay)) {
            Ok(node) => nodes.push(node),
            Err(_) => nodes.push(ContinuityPlanNode {
                id: member.occurrence_id.clone(),
                node_type: "issue".to_string(),
                ref_id: i64::from(member.issue_id),
                lane_id: member.lane_id.clone(),
                position: i64::from(member.display_position),
                label: member.label.clone(),
                source_role: None,
                source_confidence: None,
                source_explanation: None,
                source_paths: None,
                source_cbl_placements: None,
                source_story_arc_ids: None,
                source_target_story_arc_id: None,
                reader_role: member.reader_role.clone(),
                reader_optional: member.reader_optional,
                is_checkpoint: member.is_checkpoint,
                checkpoint_target_ref_id: None,
                checkpoint_target_ref_ids: Vec::new(),
                convergence_gate: Vec::new(),
            }),
        }
    }
    for raw in extra_non_issue {
        if let Ok(node) = serde_json::from_value::<ContinuityPlanNode>(raw) {
            nodes.push(node);
        }
    }
    nodes.sort_by(|left, right| {
        left.position
            .cmp(&right.position)
            .then_with(|| left.lane_id.cmp(&right.lane_id))
            .then_with(|| left.id.cmp(&right.id))
    });
    nodes
}

/// Editor nodes: membership-authoritative, falling back to stored JSON.
async fn editor_nodes_for_plan(
    tx: &Transaction<'_>,
    plan: &PlanRow,
) -> Result<Vec<ContinuityPlanNode>, ApiError> {
    let members = list_plan_members(tx, plan.id).await?;
    if members.is_empty() {
        return Ok(plan.typed_nodes());
    }
    Ok(overlay_membership_editor_nodes(&members, &plan.nodes_json()))
}

/// Fill missing issue labels from owned issues (read-time enrichment).
async fn labeled_plan_nodes(
    tx: &Transaction<'_>,
    nodes: Vec<ContinuityPlanNode>,
) -> Result<Vec<ContinuityPlanNode>, ApiError> {
    let missing: Vec<i32> = nodes
        .iter()
        .filter(|node| {
            node.node_type == "issue"
                && node.ref_id > 0
                && node.ref_id <= i64::from(i32::MAX)
                && node.label.as_deref().map(str::trim).unwrap_or("").is_empty()
        })
        .map(|node| node.ref_id as i32)
        .collect();
    if missing.is_empty() {
        return Ok(nodes);
    }
    let rows = tx
        .query(
            "SELECT i.id, i.issue_number, t.title FROM issues i JOIN threads t ON t.id = i.thread_id WHERE i.id = ANY($1::int[])",
            &[&missing],
        )
        .await
        .map_err(db::query_error)?;
    let mut labels: std::collections::HashMap<i32, String> = std::collections::HashMap::new();
    for row in rows {
        let issue_id: i32 = row.get(0);
        let issue_number: String = row.get(1);
        let thread_title: String = row.get(2);
        let number = issue_number.trim_start_matches('#').trim();
        let series = thread_title.trim();
        let label = match (series.is_empty(), number.is_empty()) {
            (false, false) => format!("{series} #{number}"),
            (false, true) => series.to_string(),
            (true, false) => number.to_string(),
            (true, true) => String::new(),
        };
        labels.insert(issue_id, label);
    }
    Ok(nodes
        .into_iter()
        .map(|mut node| {
            if node.node_type == "issue"
                && node.label.as_deref().map(str::trim).unwrap_or("").is_empty()
            {
                if let Some(label) = labels.get(&(node.ref_id as i32)) {
                    node.label = Some(label.clone());
                }
            }
            node
        })
        .collect())
}

fn plan_response(plan: &PlanRow, nodes: Vec<ContinuityPlanNode>) -> ContinuityPlanResponse {
    ContinuityPlanResponse {
        id: plan.id,
        user_id: plan.user_id,
        name: plan.name.clone(),
        ordering_mode: plan.ordering_mode.clone(),
        lanes: plan.typed_lanes().iter().map(lane_response_value).collect(),
        nodes: nodes.iter().map(dump_node).collect(),
        created_at: python_isoformat(&plan.created_at),
        updated_at: python_isoformat(&plan.updated_at),
    }
}

async fn editor_plan_response(
    tx: &Transaction<'_>,
    plan: &PlanRow,
) -> Result<ContinuityPlanResponse, ApiError> {
    let nodes = editor_nodes_for_plan(tx, plan).await?;
    let nodes = labeled_plan_nodes(tx, nodes).await?;
    Ok(plan_response(plan, nodes))
}

// ---------------------------------------------------------------------------
// Shared plan-graph facts
// ---------------------------------------------------------------------------

fn payload_issue_ids(nodes: &[ContinuityPlanNode]) -> BTreeSet<i64> {
    nodes
        .iter()
        .filter(|node| node.node_type == "issue")
        .map(|node| node.ref_id)
        .collect()
}

async fn distinct_plan_issue_ids(
    tx: &Transaction<'_>,
    plan_id: i32,
) -> Result<BTreeSet<i64>, ApiError> {
    let rows = tx
        .query(
            "SELECT DISTINCT issue_id FROM reading_plan_issues WHERE plan_id = $1",
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(rows.iter().map(|row| i64::from(row.get::<_, i32>(0))).collect())
}

/// `issue_ids` referenced by stored nodes_json (boolean-safe).
fn json_issue_ids(nodes_json: &Value) -> BTreeSet<i64> {
    let mut ids = BTreeSet::new();
    if let Some(items) = nodes_json.as_array() {
        for raw in items {
            let Some(object) = raw.as_object() else { continue };
            if object.get("node_type").and_then(Value::as_str) != Some("issue") {
                continue;
            }
            match object.get("ref_id") {
                Some(value) if value.is_boolean() => {}
                Some(value) => {
                    if let Some(id) = value.as_i64() {
                        if id > 0 {
                            ids.insert(id);
                        }
                    }
                }
                None => {}
            }
        }
    }
    ids
}

fn plan_source_paths(nodes_json: &Value) -> Vec<String> {
    let mut paths: Vec<String> = Vec::new();
    let mut push = |path: &str| {
        if !paths.iter().any(|existing| existing == path) {
            paths.push(path.to_string());
        }
    };
    let Some(items) = nodes_json.as_array() else { return paths };
    for node in items {
        let Some(object) = node.as_object() else { continue };
        if let Some(placements) = object.get("source_cbl_placements").and_then(Value::as_array) {
            for placement in placements {
                if let Some(path) = placement.get("source_path").and_then(Value::as_str) {
                    push(path);
                }
            }
        }
        if let Some(source_paths) = object.get("source_paths").and_then(Value::as_array) {
            for path in source_paths {
                if let Some(path) = path.as_str() {
                    push(path);
                }
            }
        }
    }
    paths
}

async fn load_source_names(
    connection: &tokio_postgres::Client,
    user_id: i32,
    source_paths: &[String],
) -> Result<std::collections::HashMap<String, String>, ApiError> {
    let references: std::collections::HashMap<String, i32> = source_paths
        .iter()
        .filter_map(|path| parse_custom_cbl_reference(path).map(|id| (path.clone(), id)))
        .collect();
    if references.is_empty() {
        return Ok(std::collections::HashMap::new());
    }
    let list_ids: Vec<i32> = references.values().copied().collect::<BTreeSet<_>>().into_iter().collect();
    let rows = connection
        .query(
            "SELECT id, name FROM custom_cbl_lists WHERE user_id = $1 AND id = ANY($2::int[])",
            &[&user_id, &list_ids],
        )
        .await
        .map_err(db::query_error)?;
    let names: std::collections::HashMap<i32, String> = rows
        .iter()
        .map(|row| (row.get::<_, i32>(0), row.get::<_, String>(1)))
        .collect();
    Ok(references
        .into_iter()
        .filter_map(|(path, id)| names.get(&id).map(|name| (path, name.clone())))
        .collect())
}

fn public_cbl_source_path(source_path: &str) -> String {
    const MIRROR: &str = "CBL-ReadingLists";
    let normalized = source_path.trim().replace('\\', "/");
    if !normalized.is_empty() {
        let marker = format!("{MIRROR}/");
        if let Some(index) = normalized.find(&marker) {
            let remainder = &normalized[index + marker.len()..];
            return if remainder.is_empty() {
                MIRROR.to_string()
            } else {
                remainder.to_string()
            };
        }
        if is_filesystem_location(&normalized) {
            return normalized
                .rsplit('/', 1)
                .next()
                .filter(|name| !name.is_empty())
                .map(str::to_string)
                .unwrap_or_else(|| "CBL source".to_string());
        }
    }
    source_path.to_string()
}

fn public_cbl_repository(repository: &str) -> String {
    const MIRROR: &str = "CBL-ReadingLists";
    const PUBLIC: &str = "JoshCLWren/CBL-ReadingLists";
    let normalized = repository.trim().replace('\\', "/");
    if !is_filesystem_location(&normalized) {
        return repository.to_string();
    }
    if normalized.trim_end_matches('/').ends_with(MIRROR)
        || normalized.contains(&format!("/{MIRROR}"))
    {
        return PUBLIC.to_string();
    }
    "CBL source".to_string()
}

fn is_filesystem_location(value: &str) -> bool {
    value.starts_with('/') || value.starts_with("file:") || value.starts_with("mnt/")
}

fn option_e_enabled() -> bool {
    std::env::var("OPTION_E_ENABLED")
        .map(|value| matches!(value.trim().to_ascii_lowercase().as_str(), "1" | "true" | "yes" | "on"))
        .unwrap_or(false)
}

// ---------------------------------------------------------------------------
// GET /api/v1/continuity-plans/
// ---------------------------------------------------------------------------

pub async fn list_continuity_plans(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> Result<Json<Vec<ContinuityPlanListItem>>, ApiError> {
    let connection = db::checkout(&state).await?;
    let rows = connection
        .query(
            &format!("{PLAN_SELECT} WHERE user_id = $1"),
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let mut plans: Vec<PlanRow> = rows.iter().map(plan_row).collect();
    // Python sorts by updated_at descending, stable for ties.
    plans.sort_by(|left, right| right.updated_at.cmp(&left.updated_at));

    let all_paths: Vec<String> = plans
        .iter()
        .flat_map(|plan| plan_source_paths(&plan.nodes_json()))
        .collect();
    let source_names = load_source_names(&connection, user.id(), &all_paths).await?;

    let mut summaries: Vec<ContinuityPlanListItem> = if option_e_enabled() && !plans.is_empty() {
        list_items_option_e(&connection, user.id(), &plans, &source_names).await?
    } else {
        list_items_legacy(&connection, &plans, &source_names).await?
    };
    summaries.sort_by(|left, right| {
        parse_python_datetime(&right.updated_at)
            .cmp(&parse_python_datetime(&left.updated_at))
    });
    Ok(Json(summaries))
}

async fn list_items_option_e(
    connection: &tokio_postgres::Client,
    user_id: i32,
    plans: &[PlanRow],
    source_names: &std::collections::HashMap<String, String>,
) -> Result<Vec<ContinuityPlanListItem>, ApiError> {
    let plan_ids: Vec<i32> = plans.iter().map(|plan| plan.id).collect();
    let rows = connection
        .query(
            "SELECT s.plan_id, l.id, l.mode, l.updated_at, l.user_id
             FROM reading_plan_sources s
             JOIN custom_cbl_lists l ON s.custom_cbl_list_id = l.id
             JOIN continuity_plans cp ON s.plan_id = cp.id
             WHERE s.plan_id = ANY($1::int[]) AND cp.user_id = $2",
            &[&plan_ids, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    let mut authorities: std::collections::HashMap<i32, (i32, String, DateTime<Utc>)> =
        std::collections::HashMap::new();
    for row in rows {
        let plan_id: i32 = row.get(0);
        let list_id: i32 = row.get(1);
        let mode: String = row.get(2);
        let list_updated_at: DateTime<Utc> = row_datetime(&row, 3);
        let list_owner: i32 = row.get(4);
        if list_owner != user_id {
            return Err(ApiError::Conflict(
                "Reading Plan links to an unowned Reading List".to_string(),
            ));
        }
        if let Some(existing) = authorities.get(&plan_id) {
            if existing.0 != list_id {
                return Err(ApiError::Conflict(
                    "Ambiguous Reading List association".to_string(),
                ));
            }
        }
        authorities.insert(plan_id, (list_id, mode, list_updated_at));
    }

    let list_ids: Vec<i32> = authorities.values().map(|authority| authority.0).collect::<BTreeSet<_>>().into_iter().collect();
    let mut list_counts: std::collections::HashMap<i32, i64> = std::collections::HashMap::new();
    if !list_ids.is_empty() {
        let rows = connection
            .query(
                "SELECT e.list_id, count(*)::bigint
                 FROM custom_cbl_entries e
                 JOIN custom_cbl_lists l ON e.list_id = l.id
                 WHERE e.list_id = ANY($1::int[]) AND l.user_id = $2
                 GROUP BY e.list_id",
                &[&list_ids, &user_id],
            )
            .await
            .map_err(db::query_error)?;
        for row in rows {
            list_counts.insert(row.get::<_, i32>(0), row.get::<_, i64>(1));
        }
    }

    Ok(plans
        .iter()
        .map(|plan| {
            let mut paths = plan_source_paths(&plan.nodes_json());
            let authority = authorities.get(&plan.id);
            if let Some((list_id, _, _)) = authority {
                let source_path = format!("custom-cbl:{list_id}");
                paths.retain(|path| path != &source_path);
                paths.insert(0, source_path);
            }
            let selected: Map<String, Value> = paths
                .iter()
                .filter_map(|path| source_names.get(path).map(|name| (path.clone(), json!(name))))
                .collect();
            match authority {
                Some((list_id, mode, list_updated_at)) => ContinuityPlanListItem {
                    id: plan.id,
                    name: plan.name.clone(),
                    ordering_mode: if mode == "strict" {
                        "strict_sequential".to_string()
                    } else {
                        "informational".to_string()
                    },
                    lane_count: 1,
                    step_count: list_counts.get(list_id).copied().unwrap_or(0),
                    source_paths: paths,
                    source_names: selected,
                    updated_at: python_isoformat(list_updated_at),
                },
                None => ContinuityPlanListItem {
                    id: plan.id,
                    name: plan.name.clone(),
                    ordering_mode: plan.ordering_mode.clone(),
                    lane_count: (plan.typed_lanes().len()).max(1) as i64,
                    step_count: plan
                        .nodes_json()
                        .as_array()
                        .map(|items| items.len() as i64)
                        .unwrap_or(0),
                    source_paths: paths,
                    source_names: selected,
                    updated_at: python_isoformat(&plan.updated_at),
                },
            }
        })
        .collect())
}

async fn list_items_legacy(
    connection: &tokio_postgres::Client,
    plans: &[PlanRow],
    source_names: &std::collections::HashMap<String, String>,
) -> Result<Vec<ContinuityPlanListItem>, ApiError> {
    let plan_ids: Vec<i32> = plans.iter().map(|plan| plan.id).collect();
    let mut membership_counts: std::collections::HashMap<i32, i64> = std::collections::HashMap::new();
    if !plan_ids.is_empty() {
        let rows = connection
            .query(
                "SELECT plan_id, count(*)::bigint FROM reading_plan_issues WHERE plan_id = ANY($1::int[]) GROUP BY plan_id",
                &[&plan_ids],
            )
            .await
            .map_err(db::query_error)?;
        for row in rows {
            membership_counts.insert(row.get::<_, i32>(0), row.get::<_, i64>(1));
        }
    }
    Ok(plans
        .iter()
        .map(|plan| {
            let paths = plan_source_paths(&plan.nodes_json());
            let selected: Map<String, Value> = paths
                .iter()
                .filter_map(|path| source_names.get(path).map(|name| (path.clone(), json!(name))))
                .collect();
            let lane_count = plan
                .lanes_json()
                .as_array()
                .map(|items| items.len() as i64)
                .unwrap_or(0);
            let step_count = membership_counts.get(&plan.id).copied().unwrap_or_else(|| {
                plan.nodes_json()
                    .as_array()
                    .map(|items| items.len() as i64)
                    .unwrap_or(0)
            });
            ContinuityPlanListItem {
                id: plan.id,
                name: plan.name.clone(),
                ordering_mode: plan.ordering_mode.clone(),
                lane_count,
                step_count,
                source_paths: paths,
                source_names: selected,
                updated_at: python_isoformat(&plan.updated_at),
            }
        })
        .collect())
}

// ---------------------------------------------------------------------------
// GET /api/v1/continuity-plans/{plan_id}
// ---------------------------------------------------------------------------

pub async fn get_continuity_plan(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
) -> Result<Json<ContinuityPlanResponse>, ApiError> {
    let mut connection = db::checkout(&state).await?;
    let tx = connection
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    let plan = owned_plan(&tx, user.id(), plan_id).await?;
    let response = editor_plan_response(&tx, &plan).await?;
    tx.rollback().await.map_err(db::query_error)?;
    Ok(Json(response))
}

// ---------------------------------------------------------------------------
// GET /api/v1/continuity-plans/{plan_id}/membership
// ---------------------------------------------------------------------------

pub async fn get_continuity_plan_membership(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
) -> Result<Json<ReadingPlanMembershipResponse>, ApiError> {
    let mut connection = db::checkout(&state).await?;
    let tx = connection
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    let plan = owned_plan(&tx, user.id(), plan_id).await?;

    let members = list_plan_members(&tx, plan.id).await?;

    let edge_rows = tx
        .query(
            "SELECT d.id, d.source_issue_id, d.target_issue_id
             FROM dependencies d
             JOIN reading_plan_dependencies rpd ON rpd.dependency_id = d.id
             WHERE rpd.plan_id = $1
             ORDER BY d.id",
            &[&plan.id],
        )
        .await
        .map_err(db::query_error)?;
    let link_rows = tx
        .query(
            "SELECT dependency_id, explanation FROM reading_plan_dependencies WHERE plan_id = $1 ORDER BY dependency_id",
            &[&plan.id],
        )
        .await
        .map_err(db::query_error)?;
    let explanations: std::collections::HashMap<i32, Option<String>> = link_rows
        .iter()
        .map(|row| (row.get::<_, i32>(0), row.get::<_, Option<String>>(1)))
        .collect();

    let source_rows = tx
        .query(
            "SELECT id, raw_source_path, repository, source_path, revision_sha, content_hash, adopted_at, recorded_at
             FROM reading_plan_sources WHERE plan_id = $1 ORDER BY id",
            &[&plan.id],
        )
        .await
        .map_err(db::query_error)?;
    let source_paths: Vec<String> = source_rows
        .iter()
        .map(|row| row.get::<_, String>(1))
        .collect();
    let source_names = load_source_names_for_tx(&tx, user.id(), &source_paths).await?;

    let placement_rows = tx
        .query(
            "SELECT id, occurrence_id, plan_source_id, source_position FROM reading_plan_source_placements WHERE plan_id = $1 ORDER BY id",
            &[&plan.id],
        )
        .await
        .map_err(db::query_error)?;

    let progress_row = tx
        .query_one(
            "SELECT count(DISTINCT issue_id)::bigint FROM reading_plan_issues WHERE plan_id = $1",
            &[&plan.id],
        )
        .await
        .map_err(db::query_error)?;
    let total_issues: i64 = progress_row.get(0);
    let read_row = tx
        .query_one(
            "SELECT count(DISTINCT rpi.issue_id)::bigint
             FROM reading_plan_issues rpi
             JOIN issues i ON i.id = rpi.issue_id
             WHERE rpi.plan_id = $1 AND i.status = 'read'",
            &[&plan.id],
        )
        .await
        .map_err(db::query_error)?;
    let read_issues: i64 = read_row.get(0);

    let issues = members
        .iter()
        .map(|member| ReadingPlanMemberIssue {
            occurrence_id: member.occurrence_id.clone(),
            issue_id: member.issue_id,
            lane_id: member.lane_id.clone(),
            display_position: member.display_position,
            label: member.label.clone(),
            reader_role: member.reader_role.clone(),
            reader_optional: member.reader_optional,
            is_checkpoint: member.is_checkpoint,
            source_metadata: member_metadata(member),
        })
        .collect();

    let dependencies = edge_rows
        .iter()
        .map(|row| {
            let dependency_id: i32 = row.get(0);
            ReadingPlanDependencyLink {
                dependency_id,
                source_issue_id: row.get(1),
                target_issue_id: row.get(2),
                explanation: explanations.get(&dependency_id).cloned().flatten(),
            }
        })
        .collect();

    let sources = source_rows
        .iter()
        .map(|row| {
            let raw_source_path: String = row.get(1);
            let repository: Option<String> = row.get(2);
            let source_path: Option<String> = row.get(3);
            let adopted_at: Option<DateTime<Utc>> = row.get(6);
            let recorded_at: DateTime<Utc> = row_datetime(row, 7);
            ReadingPlanSourceSnapshot {
                id: row.get(0),
                display_name: source_names.get(&raw_source_path).cloned(),
                raw_source_path: public_cbl_source_path(&raw_source_path),
                repository: repository
                    .as_deref()
                    .filter(|value| !value.is_empty())
                    .map(public_cbl_repository),
                source_path: source_path
                    .as_deref()
                    .filter(|value| !value.is_empty())
                    .map(public_cbl_source_path),
                revision_sha: row.get(4),
                content_hash: row.get(5),
                adopted_at: adopted_at.map(|value| python_isoformat(&value)),
                recorded_at: python_isoformat(&recorded_at),
            }
        })
        .collect();

    let placements = placement_rows
        .iter()
        .map(|row| ReadingPlanSourcePlacementView {
            id: row.get(0),
            occurrence_id: row.get(1),
            plan_source_id: row.get(2),
            source_position: row.get(3),
        })
        .collect();

    let response = ReadingPlanMembershipResponse {
        plan_id: plan.id,
        issues,
        dependencies,
        sources,
        placements,
        progress: ReadingPlanProgress {
            total_issues,
            read_issues,
        },
    };
    tx.rollback().await.map_err(db::query_error)?;
    Ok(Json(response))
}

async fn load_source_names_for_tx(
    tx: &Transaction<'_>,
    user_id: i32,
    source_paths: &[String],
) -> Result<std::collections::HashMap<String, String>, ApiError> {
    let references: std::collections::HashMap<String, i32> = source_paths
        .iter()
        .filter_map(|path| parse_custom_cbl_reference(path).map(|id| (path.clone(), id)))
        .collect();
    if references.is_empty() {
        return Ok(std::collections::HashMap::new());
    }
    let list_ids: Vec<i32> = references
        .values()
        .copied()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let rows = tx
        .query(
            "SELECT id, name FROM custom_cbl_lists WHERE user_id = $1 AND id = ANY($2::int[])",
            &[&user_id, &list_ids],
        )
        .await
        .map_err(db::query_error)?;
    let names: std::collections::HashMap<i32, String> = rows
        .iter()
        .map(|row| (row.get::<_, i32>(0), row.get::<_, String>(1)))
        .collect();
    Ok(references
        .into_iter()
        .filter_map(|(path, id)| names.get(&id).map(|name| (path, name.clone())))
        .collect())
}

fn parse_custom_cbl_reference(path: &str) -> Option<i32> {
    let digits = path.trim().strip_prefix("custom-cbl:")?;
    if digits.is_empty()
        || digits.len() > 10
        || !digits.chars().all(|c| c.is_ascii_digit())
    {
        return None;
    }
    digits.parse::<i64>().ok().and_then(|id| {
        if (1..=i64::from(i32::MAX)).contains(&id) {
            Some(id as i32)
        } else {
            None
        }
    })
}

// ---------------------------------------------------------------------------
// POST/DELETE /api/v1/continuity-plans/{plan_id}/dependencies/{dependency_id}
// ---------------------------------------------------------------------------

pub async fn link_plan_dependency_edge(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path((plan_id, dependency_id)): Path<(i32, i32)>,
    Json(payload): Json<ReadingPlanDependencyLinkRequest>,
) -> Result<(StatusCode, Json<ReadingPlanDependencyLink>), ApiError> {
    if payload
        .explanation
        .as_ref()
        .is_some_and(|value| value.chars().count() > 500)
    {
        return Err(validation_error(
            "explanation must have at most 500 characters",
        ));
    }
    let mut connection = db::checkout(&state).await?;
    let tx = connection
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;

    let plan = match owned_plan(&tx, user.id(), plan_id).await {
        Ok(plan) => plan,
        Err(error) => {
            let _ = tx.rollback().await;
            return Err(error);
        }
    };

    let dependency = tx
        .query_opt(
            "SELECT id, source_issue_id, target_issue_id FROM dependencies WHERE id = $1",
            &[&dependency_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(dependency) = dependency else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(ApiError::NotFound(format!(
            "Dependency {dependency_id} not found"
        )));
    };
    let source_issue_id: i32 = dependency.get(1);
    let target_issue_id: i32 = dependency.get(2);

    let owned = tx
        .query(
            "SELECT i.id FROM issues i JOIN threads t ON t.id = i.thread_id
             WHERE i.id = ANY($1::int[]) AND t.user_id = $2",
            &[&vec![source_issue_id, target_issue_id], &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let owned_ids: BTreeSet<i32> = owned.iter().map(|row| row.get(0)).collect();
    if !owned_ids.contains(&source_issue_id) || !owned_ids.contains(&target_issue_id) {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(structured_error(
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({"code": "dangling_plan_reference", "dependency_id": dependency_id}),
        ));
    }

    let existing = tx
        .query_opt(
            "SELECT explanation FROM reading_plan_dependencies WHERE plan_id = $1 AND dependency_id = $2",
            &[&plan.id, &dependency_id],
        )
        .await
        .map_err(db::query_error)?;
    let link = match existing {
        Some(row) => ReadingPlanDependencyLink {
            dependency_id,
            source_issue_id,
            target_issue_id,
            explanation: row.get(0),
        },
        None => {
            tx.execute(
                "INSERT INTO reading_plan_dependencies (plan_id, dependency_id, explanation)
                 VALUES ($1, $2, $3)
                 ON CONFLICT (plan_id, dependency_id) DO NOTHING",
                &[&plan.id, &dependency_id, &payload.explanation],
            )
            .await
            .map_err(db::query_error)?;
            ReadingPlanDependencyLink {
                dependency_id,
                source_issue_id,
                target_issue_id,
                explanation: payload.explanation.clone(),
            }
        }
    };

    tx.commit().await.map_err(db::query_error)?;
    Ok((StatusCode::CREATED, Json(link)))
}

pub async fn unlink_plan_dependency_edge(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path((plan_id, dependency_id)): Path<(i32, i32)>,
) -> Result<StatusCode, ApiError> {
    let mut connection = db::checkout(&state).await?;
    let tx = connection
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    let plan = match owned_plan(&tx, user.id(), plan_id).await {
        Ok(plan) => plan,
        Err(error) => {
            let _ = tx.rollback().await;
            return Err(error);
        }
    };
    let removed = tx
        .execute(
            "DELETE FROM reading_plan_dependencies WHERE plan_id = $1 AND dependency_id = $2",
            &[&plan.id, &dependency_id],
        )
        .await
        .map_err(db::query_error)?;
    if removed == 0 {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(ApiError::NotFound(format!(
            "Dependency {dependency_id} is not referenced by plan {plan_id}"
        )));
    }
    tx.commit().await.map_err(db::query_error)?;
    Ok(StatusCode::NO_CONTENT)
}

// ---------------------------------------------------------------------------
// Release sources
// ---------------------------------------------------------------------------

fn provider_display_from_metadata(metadata: &Value) -> Map<String, Value> {
    let mut display = Map::new();
    let object = metadata.as_object();
    let get = |key: &str| object.and_then(|map| map.get(key));

    let title = get("name").or_else(|| get("title")).and_then(|v| v.as_str()).map(str::trim).filter(|s| !s.is_empty());
    if let Some(title) = title {
        display.insert("title".to_string(), json!(title));
    }
    match get("publisher") {
        Some(Value::String(publisher)) => {
            let publisher = publisher.trim();
            if !publisher.is_empty() {
                display.insert("publisher".to_string(), json!(publisher));
            }
        }
        Some(Value::Object(map)) => {
            if let Some(name) = map.get("name").and_then(Value::as_str).map(str::trim).filter(|s| !s.is_empty()) {
                display.insert("publisher".to_string(), json!(name));
            }
        }
        _ => {}
    }
    let start_year = match get("start_year") {
        Some(Value::Number(number)) => number.as_i64(),
        Some(Value::String(text)) => text.trim().parse::<i64>().ok(),
        _ => None,
    };
    if let Some(year) = start_year {
        display.insert("start_year".to_string(), json!(year));
    }
    let count = match get("count_of_issues").or_else(|| get("issue_count")) {
        Some(Value::Number(number)) => number.as_i64(),
        Some(Value::String(text)) => text.trim().parse::<i64>().ok(),
        _ => None,
    };
    if let Some(count) = count {
        display.insert("issue_count".to_string(), json!(count));
    }
    display
}


fn display_title(metadata: &Value) -> Option<String> {
    provider_display_from_metadata(metadata)
        .get("title")
        .and_then(Value::as_str)
        .map(str::to_string)
}

fn status_from_row(row: &Row) -> ReadingPlanReleaseSourceStatus {
    let metadata_text: Option<String> = row.get(4);
    let metadata: Value = metadata_text
        .as_deref()
        .and_then(|text| serde_json::from_str(text).ok())
        .unwrap_or(Value::Null);
    let display = provider_display_from_metadata(&metadata);
    let last_synced_at: Option<DateTime<Utc>> = row.get(6);
    ReadingPlanReleaseSourceStatus {
        source_id: row.get(0),
        thread_id: row.get(1),
        external_identity_id: row.get(2),
        provider_volume_id: row.get(3),
        provider_title: display.get("title").and_then(Value::as_str).map(str::to_string),
        provider_publisher: display.get("publisher").and_then(Value::as_str).map(str::to_string),
        provider_start_year: display.get("start_year").and_then(Value::as_i64),
        provider_issue_count: display.get("issue_count").and_then(Value::as_i64),
        enabled: row.get(5),
        last_synced_at: last_synced_at.map(|value| python_isoformat(&value)),
    }
}

fn source_response_from_row(row: &Row) -> ReleaseSourceResponse {
    let metadata_text: Option<String> = row.get(5);
    let metadata: Value = metadata_text
        .as_deref()
        .and_then(|text| serde_json::from_str(text).ok())
        .unwrap_or(Value::Null);
    let last_synced_at: Option<DateTime<Utc>> = row.get(8);
    let created_at: DateTime<Utc> = row_datetime(row, 9);
    let updated_at: DateTime<Utc> = row_datetime(row, 10);
    ReleaseSourceResponse {
        id: row.get(0),
        plan_id: row.get(1),
        thread_id: row.get(2),
        external_identity_id: row.get(3),
        provider: row.get(4),
        provider_volume_id: row.get(6),
        provider_title: display_title(&metadata),
        enabled: row.get(7),
        last_synced_at: last_synced_at.map(|value| python_isoformat(&value)),
        created_at: python_isoformat(&created_at),
        updated_at: python_isoformat(&updated_at),
    }
}

const SOURCE_RESPONSE_SELECT: &str = "SELECT s.id, s.plan_id, s.thread_id, s.external_identity_id, ei.provider, ei.metadata_json::text, ei.external_id, s.enabled, s.last_synced_at, s.created_at, s.updated_at FROM reading_plan_release_sources s JOIN external_identities ei ON ei.id = s.external_identity_id";

const STATUS_SELECT: &str = "SELECT s.id, s.thread_id, s.external_identity_id, ei.external_id, ei.metadata_json::text, s.enabled, s.last_synced_at FROM reading_plan_release_sources s JOIN external_identities ei ON ei.id = s.external_identity_id";

async fn owned_plan_for_release_source(
    tx: &Transaction<'_>,
    user_id: i32,
    plan_id: i32,
) -> Result<i32, ApiError> {
    let row = tx
        .query_opt(
            "SELECT id FROM continuity_plans WHERE id = $1 AND user_id = $2",
            &[&plan_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    row.map(|row| row.get::<_, i32>(0))
        .ok_or_else(|| ApiError::NotFound(format!("Plan {plan_id} not found")))
}

async fn require_confirmed_mapping(
    tx: &Transaction<'_>,
    thread_id: i32,
    external_identity_id: i32,
) -> Result<(), ApiError> {
    let mapping = tx
        .query_opt(
            "SELECT 1 FROM thread_external_series_mappings
             WHERE thread_id = $1 AND external_identity_id = $2 AND status = 'confirmed'",
            &[&thread_id, &external_identity_id],
        )
        .await
        .map_err(db::query_error)?;
    if mapping.is_none() {
        return Err(ApiError::with_status(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Provider volume must be a confirmed mapping for the thread".to_string(),
        ));
    }
    let identity = tx
        .query_opt(
            "SELECT provider, entity_type FROM external_identities WHERE id = $1",
            &[&external_identity_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(identity) = identity else {
        return Err(ApiError::NotFound("Provider identity not found".to_string()));
    };
    let provider: String = identity.get(0);
    let entity_type: String = identity.get(1);
    if provider != "comicvine" || entity_type != "series" {
        return Err(ApiError::with_status(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Release source must reference a confirmed ComicVine series volume".to_string(),
        ));
    }
    Ok(())
}

pub async fn create_release_source(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(payload): Json<ReleaseSourceCreate>,
) -> Result<(StatusCode, Json<ReleaseSourceResponse>), ApiError> {
    if payload.plan_id <= 0 || payload.thread_id <= 0 || payload.external_identity_id <= 0 {
        return Err(validation_error(
            "plan_id, thread_id and external_identity_id must be positive integers",
        ));
    }
    let plan_id = payload.plan_id as i32;
    let thread_id = payload.thread_id as i32;
    let external_identity_id = payload.external_identity_id as i32;

    let mut connection = db::checkout(&state).await?;
    let tx = connection
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;

    if let Err(error) = owned_plan_for_release_source(&tx, user.id(), plan_id).await {
        let _ = tx.rollback().await;
        return Err(error);
    }
    let thread = tx
        .query_opt(
            "SELECT id FROM threads WHERE id = $1 AND user_id = $2",
            &[&thread_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    if thread.is_none() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(ApiError::NotFound(format!("Thread {thread_id} not found")));
    }
    if let Err(error) = require_confirmed_mapping(&tx, thread_id, external_identity_id).await {
        let _ = tx.rollback().await;
        return Err(error);
    }

    // Retry-safe: return the existing row on duplicate create.
    let existing = tx
        .query_opt(
            &format!("{SOURCE_RESPONSE_SELECT} WHERE s.plan_id = $1 AND s.thread_id = $2 AND s.external_identity_id = $3"),
            &[&plan_id, &thread_id, &external_identity_id],
        )
        .await
        .map_err(db::query_error)?;
    if let Some(row) = existing {
        let response = source_response_from_row(&row);
        tx.commit().await.map_err(db::query_error)?;
        return Ok((StatusCode::CREATED, Json(response)));
    }

    tx.execute(
        "INSERT INTO reading_plan_release_sources (plan_id, thread_id, external_identity_id, enabled, created_at, updated_at)
         VALUES ($1, $2, $3, TRUE, NOW(), NOW())
         ON CONFLICT ON CONSTRAINT uq_release_source_once_per_plan_thread_volume DO NOTHING",
        &[&plan_id, &thread_id, &external_identity_id],
    )
    .await
    .map_err(db::query_error)?;
    let response_row = tx
        .query_one(
            &format!("{SOURCE_RESPONSE_SELECT} WHERE s.plan_id = $1 AND s.thread_id = $2 AND s.external_identity_id = $3"),
            &[&plan_id, &thread_id, &external_identity_id],
        )
        .await
        .map_err(db::query_error)?;
    let response = source_response_from_row(&response_row);
    tx.commit().await.map_err(db::query_error)?;
    Ok((StatusCode::CREATED, Json(response)))
}

pub async fn list_release_sources(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
) -> Result<Json<Vec<ReleaseSourceResponse>>, ApiError> {
    let connection = db::checkout(&state).await?;
    let plan = connection
        .query_opt(
            "SELECT id FROM continuity_plans WHERE id = $1 AND user_id = $2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    if plan.is_none() {
        return Err(ApiError::NotFound(format!("Plan {plan_id} not found")));
    }
    let rows = connection
        .query(
            &format!("{SOURCE_RESPONSE_SELECT} WHERE s.plan_id = $1 AND s.plan_id IN (SELECT id FROM continuity_plans WHERE user_id = $2) ORDER BY s.created_at"),
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    Ok(Json(rows.iter().map(source_response_from_row).collect()))
}

pub async fn list_release_sources_for_reader(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
) -> Result<Json<Vec<ReadingPlanReleaseSourceStatus>>, ApiError> {
    let connection = db::checkout(&state).await?;
    let plan = connection
        .query_opt(
            "SELECT id FROM continuity_plans WHERE id = $1 AND user_id = $2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    if plan.is_none() {
        return Err(ApiError::NotFound(format!("Plan {plan_id} not found")));
    }
    let rows = connection
        .query(
            &format!("{STATUS_SELECT} WHERE s.plan_id = $1 AND s.plan_id IN (SELECT id FROM continuity_plans WHERE user_id = $2) ORDER BY s.created_at"),
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    Ok(Json(rows.iter().map(status_from_row).collect()))
}

pub async fn update_release_source(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(source_id): Path<i32>,
    Json(payload): Json<ReleaseSourceUpdate>,
) -> Result<Json<ReleaseSourceResponse>, ApiError> {
    let mut connection = db::checkout(&state).await?;
    let tx = connection
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;

    let existing = tx
        .query_opt(
            "SELECT s.id FROM reading_plan_release_sources s
             JOIN continuity_plans cp ON cp.id = s.plan_id
             WHERE s.id = $1 AND cp.user_id = $2",
            &[&source_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    if existing.is_none() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(ApiError::NotFound("Release source not found".to_string()));
    }
    if payload.enabled {
        let row = tx
            .query_one(
                "SELECT thread_id, external_identity_id FROM reading_plan_release_sources WHERE id = $1",
                &[&source_id],
            )
            .await
            .map_err(db::query_error)?;
        let thread_id: i32 = row.get(0);
        let external_identity_id: i32 = row.get(1);
        require_confirmed_mapping(&tx, thread_id, external_identity_id).await?;
    }
    tx.execute(
        "UPDATE reading_plan_release_sources SET enabled = $2, updated_at = NOW() WHERE id = $1",
        &[&source_id, &payload.enabled],
    )
    .await
    .map_err(db::query_error)?;
    let row = tx
        .query_one(
            &format!("{SOURCE_RESPONSE_SELECT} WHERE s.id = $1"),
            &[&source_id],
        )
        .await
        .map_err(db::query_error)?;
    let response = source_response_from_row(&row);
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

pub async fn delete_release_source(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(source_id): Path<i32>,
) -> Result<StatusCode, ApiError> {
    let mut connection = db::checkout(&state).await?;
    let tx = connection
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    let removed = tx
        .execute(
            "DELETE FROM reading_plan_release_sources s
             USING continuity_plans cp
             WHERE s.id = $1 AND cp.id = s.plan_id AND cp.user_id = $2",
            &[&source_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    if removed == 0 {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(ApiError::NotFound("Release source not found".to_string()));
    }
    tx.commit().await.map_err(db::query_error)?;
    Ok(StatusCode::NO_CONTENT)
}
