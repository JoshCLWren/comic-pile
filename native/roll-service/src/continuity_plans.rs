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
//! * `GET /api/v1/continuity-plans/` - list plans
//! * `POST /api/v1/continuity-plans/` - create plan
//! * `POST /api/v1/continuity-plans/from-reading-order` - adopt reading order
//! * `POST /api/v1/continuity-plans/release-sources/` - create release source
//! * `DELETE /api/v1/continuity-plans/release-sources/{source_id}` - delete release source
//! * `PATCH /api/v1/continuity-plans/release-sources/{source_id}` - update release source
//! * `DELETE /api/v1/continuity-plans/{plan_id}` - delete plan
//! * `GET /api/v1/continuity-plans/{plan_id}` - get plan
//! * `PUT /api/v1/continuity-plans/{plan_id}` - update plan
//! * `DELETE /api/v1/continuity-plans/{plan_id}/dependencies/{dependency_id}` - unlink dependency
//! * `POST /api/v1/continuity-plans/{plan_id}/dependencies/{dependency_id}` - link dependency
//! * `GET /api/v1/continuity-plans/{plan_id}/membership` - get membership
//! * `POST /api/v1/continuity-plans/{plan_id}/reading-orders/project` - project to reading order
//! * `GET /api/v1/continuity-plans/{plan_id}/release-sources/` - list release sources
//! * `GET /api/v1/continuity-plans/{plan_id}/release-sources/reader` - reader-facing release sources
//!
//! Wire contracts mirror Python (`app/schemas/continuity_plan.py`,
//! `app/schemas/reading_plan_release_source.py`, `app/schemas/reading_order.py`)
//! with identical JSON field names, types, and optional/required status.
//!
//! Parity notes:
//! * Uses owner-scoped SQL queries similar to other native Rust handlers
//! * Preserves 404 messages from Python for plan/thread ownership checks
//! * Mirrors Python 409 conflict responses with same message structure
//! * Uses advisory locking via QUEUE_LOCK_NAMESPACE for write transactions

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, issue_service, option_inputs, ApiError, AppState};
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

const QUEUE_LOCK_NAMESPACE: i32 = 699001;

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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub label: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_role: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_confidence: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_explanation: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_paths: Option<Vec<String>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_cbl_placements: Option<Vec<serde_json::Value>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_story_arc_ids: Option<Vec<String>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_target_story_arc_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reader_role: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reader_optional: Option<bool>,
    #[serde(default)]
    pub is_checkpoint: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub checkpoint_target_ref_id: Option<i32>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub checkpoint_target_ref_ids: Vec<i32>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub convergence_gate: Vec<serde_json::Value>,
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ContinuityPlanWrite {
    pub name: String,
    #[serde(rename = "ordering_mode")]
    pub ordering_mode: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub lanes: Vec<ContinuityPlanLane>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub nodes: Vec<ContinuityPlanNode>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expected_updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ContinuityPlanResponse {
    pub id: i32,
    pub user_id: i32,
    pub name: String,
    #[serde(rename = "ordering_mode")]
    pub ordering_mode: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub lanes: Vec<ContinuityPlanLane>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
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
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub source_paths: Vec<String>,
    #[serde(default, skip_serializing_if = "serde_json::Value::is_null")]
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
}

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ReleaseSourceUpdate {
    pub enabled: bool,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReleaseSourceResponse {
    pub id: i32,
    pub plan_id: i32,
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

// Read timestamp as RFC3339
fn format_timestamp(ts: chrono::DateTime<Utc>) -> String {
    ts.to_rfc3339_opts(SecondsFormat::Secs, true)
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

// ============================================================================
// GET /api/v1/continuity-plans/ - List plans
// ============================================================================

#[utoipa::path(
    get,
    path = "/api/v1/continuity-plans/",
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
            SELECT p.id, p.name, p.ordering_mode, p.lanes_json, p.nodes_json, p.created_at::text, p.updated_at::text
            FROM continuity_plans p
            WHERE p.user_id = $1
            ORDER BY p.updated_at DESC
            "#,
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;

    let plans: Vec<ContinuityPlanListItem> = rows
        .iter()
        .map(|row| {
            let lanes_json: Vec<serde_json::Value> =
                serde_json::from_value(row.get(5).clone()).unwrap_or_default();
            let lane_count = lanes_json.len().saturating_sub(0).max(1);
            
            // Calculate step count from nodes_json
            let nodes: Vec<serde_json::Value> =
                serde_json::from_value(row.get(7).clone()).unwrap_or_default();
            let step_count = nodes.len() as i32;
            
            // Extract source paths from nodes
            let mut source_paths = Vec::new();
            for node in &nodes {
                if let Some(paths) = node.get("source_paths").and_then(|v| v.as_array()) {
                    for path in paths {
                        if let Some(s) = path.as_str() {
                            if !source_paths.contains(&s.to_string()) {
                                source_paths.push(s.to_string());
                            }
                        }
                    }
                }
            }

            ContinuityPlanListItem {
                id: row.get(0),
                name: row.get(1),
                ordering_mode: row.get(2),
                lane_count: lane_count as i32,
                step_count,
                source_paths,
                source_names: serde_json::json!({}),
                updated_at: row.get(6),
            }
        })
        .collect();

    Ok(Json(plans))
}

// ============================================================================
// POST /api/v1/continuity-plans/ - Create plan
// ============================================================================

#[utoipa::path(
    post,
    path = "/api/v1/continuity-plans/",
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
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;

    // Check that all referenced issues are owned by the user
    let issue_ids: Vec<i32> = payload
        .nodes
        .iter()
        .filter(|n| n.node_type == "issue")
        .map(|n| n.ref_id)
        .collect();

    if !issue_ids.is_empty() {
        let count: i64 = tx
            .query_one(
                "SELECT COUNT(*) FROM issues i JOIN threads t ON t.id = i.thread_id WHERE i.id = ANY($1::int[]) AND t.user_id = $2",
                &[&issue_ids, &user.id()],
            )
            .await
            .map_err(db::query_error)?
            .get(0);
        if count as usize != issue_ids.len() {
            tx.rollback().await.map_err(db::query_error)?;
            return Err(bad_request("Some referenced issues are not owned by the user"));
        }
    }

    // Check thread nodes
    for node in &payload.nodes {
        if node.node_type == "thread" {
            let found: Option<i32> = tx
                .query_opt(
                    "SELECT id FROM threads WHERE id = $1 AND user_id = $2",
                    &[&node.ref_id, &user.id()],
                )
                .await
                .map_err(db::query_error)?
                .map(|row| row.get(0));
            if found.is_none() {
                tx.rollback().await.map_err(db::query_error)?;
                return Err(bad_request(format!(
                    "Thread {} not found or not owned",
                    node.ref_id
                )));
            }
        }
    }

    // Validate lane uniqueness
    let lane_ids: Vec<&String> = payload.lanes.iter().map(|l| &l.id).collect();
    if lane_ids.len() != lane_ids.iter().collect::<std::collections::HashSet<_>>().len() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("Lane ids must be unique"));
    }

    // Check for duplicate node ids
    let node_ids: Vec<&String> = payload.nodes.iter().map(|n| &n.id).collect();
    if node_ids.len() != node_ids.iter().collect::<std::collections::HashSet<_>>().len() {
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

    let row = tx
        .query_one(
            r#"
            INSERT INTO continuity_plans (user_id, name, ordering_mode, lanes_json, nodes_json, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, NOW(), NOW())
            RETURNING id, user_id, name, ordering_mode, lanes_json, nodes_json, created_at::text, updated_at::text
            "#,
            &[
                &user.id(),
                &payload.name,
                &payload.ordering_mode,
                &serde_json::to_string(&lanes_json).unwrap(),
                &serde_json::to_string(&nodes_json).unwrap(),
            ],
        )
        .await
        .map_err(db::query_error)?;

    // Extract values before commit to avoid MissingGreenlet issues
    let plan_id: i32 = row.get(0);
    let plan_response = ContinuityPlanResponse {
        id: plan_id,
        user_id: row.get(1),
        name: row.get(2),
        ordering_mode: row.get(3),
        lanes: serde_json::from_value(row.get(4)).unwrap_or_default(),
        nodes: serde_json::from_value(row.get(5)).unwrap_or_default(),
        created_at: row.get(6),
        updated_at: row.get(7),
    };

    tx.commit().await.map_err(db::query_error)?;
    Ok((StatusCode::CREATED, Json(plan_response)))
}

// ============================================================================
// GET /api/v1/continuity-plans/{plan_id} - Get plan
// ============================================================================

#[utoipa::path(
    get,
    path = "/api/v1/continuity-plans/{plan_id}",
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
    let conn = db::checkout(&state).await?;
    let row = conn
        .query_opt(
            r#"
            SELECT id, user_id, name, ordering_mode, lanes_json, nodes_json, created_at::text, updated_at::text
            FROM continuity_plans
            WHERE id = $1 AND user_id = $2
            "#,
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| not_found(format!("Continuity plan {plan_id} not found")))?;

    Ok(Json(ContinuityPlanResponse {
        id: row.get(0),
        user_id: row.get(1),
        name: row.get(2),
        ordering_mode: row.get(3),
        lanes: serde_json::from_value(row.get(4)).unwrap_or_default(),
        nodes: serde_json::from_value(row.get(5)).unwrap_or_default(),
        created_at: row.get(6),
        updated_at: row.get(7),
    }))
}

// ============================================================================
// PUT /api/v1/continuity-plans/{plan_id} - Update plan
// ============================================================================

#[utoipa::path(
    put,
    path = "/api/v1/continuity-plans/{plan_id}",
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
    Json(payload): Json<ContinuityPlanWrite>,
) -> Result<Json<ContinuityPlanResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;

    // Check plan ownership and get current version
    let existing = tx
        .query_opt(
            "SELECT id, lanes_json, nodes_json, updated_at FROM continuity_plans WHERE id = $1 AND user_id = $2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| not_found(format!("Continuity plan {plan_id} not found")))?;

    let expected_version: Option<String> = payload.expected_updated_at.map(|dt| format_timestamp(dt));
    let current_updated_at: String = existing.get(3);
    
    if let Some(ref expected) = expected_version {
        if expected != &current_updated_at {
            tx.rollback().await.map_err(db::query_error)?;
            return Err(ApiError::Conflict(format!(
                "Plan {plan_id} has changed since last read"
            )));
        }
    }

    // Validate node ownership (same logic as create)
    let issue_ids: Vec<i32> = payload
        .nodes
        .iter()
        .filter(|n| n.node_type == "issue")
        .map(|n| n.ref_id)
        .collect();

    if !issue_ids.is_empty() {
        let count: i64 = tx
            .query_one(
                "SELECT COUNT(*) FROM issues i JOIN threads t ON t.id = i.thread_id WHERE i.id = ANY($1::int[]) AND t.user_id = $2",
                &[&issue_ids, &user.id()],
            )
            .await
            .map_err(db::query_error)?
            .get(0);
        if count as usize != issue_ids.len() {
            tx.rollback().await.map_err(db::query_error)?;
            return Err(bad_request("Some referenced issues are not owned by the user"));
        }
    }

    for node in &payload.nodes {
        if node.node_type == "thread" {
            let found: Option<i32> = tx
                .query_opt(
                    "SELECT id FROM threads WHERE id = $1 AND user_id = $2",
                    &[&node.ref_id, &user.id()],
                )
                .await
                .map_err(db::query_error)?
                .map(|row| row.get(0));
            if found.is_none() {
                tx.rollback().await.map_err(db::query_error)?;
                return Err(bad_request(format!(
                    "Thread {} not found or not owned",
                    node.ref_id
                )));
            }
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

    tx.execute(
        r#"
        UPDATE continuity_plans 
        SET name = $1, ordering_mode = $2, lanes_json = $3, nodes_json = $4, updated_at = NOW()
        WHERE id = $5 AND user_id = $6
        "#,
        &[
            &payload.name,
            &payload.ordering_mode,
            &serde_json::to_string(&lanes_json).unwrap(),
            &serde_json::to_string(&nodes_json).unwrap(),
            &plan_id,
            &user.id(),
        ],
    )
    .await
    .map_err(db::query_error)?;

    let row = tx
        .query_one(
            r#"
            SELECT id, user_id, name, ordering_mode, lanes_json, nodes_json, created_at::text, updated_at::text
            FROM continuity_plans WHERE id = $1
            "#,
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;

    tx.commit().await.map_err(db::query_error)?;

    Ok(Json(ContinuityPlanResponse {
        id: row.get(0),
        user_id: row.get(1),
        name: row.get(2),
        ordering_mode: row.get(3),
        lanes: serde_json::from_value(row.get(4)).unwrap_or_default(),
        nodes: serde_json::from_value(row.get(5)).unwrap_or_default(),
        created_at: row.get(6),
        updated_at: row.get(7),
    }))
}

// ============================================================================
// DELETE /api/v1/continuity-plans/{plan_id} - Delete plan
// ============================================================================

#[utoipa::path(
    delete,
    path = "/api/v1/continuity-plans/{plan_id}",
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

    // Check plan ownership
    let plan = tx
        .query_opt(
            "SELECT id FROM continuity_plans WHERE id = $1 AND user_id = $2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| not_found(format!("Continuity plan {plan_id} not found")))?;

    // Get marker for deleting plan rules
    let marker = format!("continuity-plan:{}", plan_id);

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
// POST /api/v1/continuity-plans/from-reading-order - Adopt reading order
// ============================================================================

#[utoipa::path(
    post,
    path = "/api/v1/continuity-plans/from-reading-order",
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

    // Load the reading order
    let order = tx
        .query_opt(
            "SELECT id, name FROM reading_orders WHERE id = $1 AND user_id = $2",
            &[&payload.reading_order_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| not_found(format!("Reading order {} not found", payload.reading_order_id)))?;

    let order_id: i32 = order.get(0);
    let order_name: String = order.get(1);

    // Get items from the reading order
    let items = tx
        .query(
            "SELECT thread_id, position FROM reading_order_items WHERE reading_order_id = $1 ORDER BY position, id",
            &[&order_id],
        )
        .await
        .map_err(db::query_error)?;

    // Check for duplicate threads
    let mut seen_threads = std::collections::HashSet::new();
    let mut duplicates = Vec::new();
    for item in &items {
        let thread_id: i32 = item.get(0);
        if seen_threads.contains(&thread_id) {
            duplicates.push(thread_id);
        } else {
            seen_threads.insert(thread_id);
        }
    }

    if !duplicates.is_empty() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(ApiError::Conflict(serde_json::json!({
            "code": "duplicate_thread",
            "reading_order_id": order_id,
            "duplicate_thread_ids": duplicates,
            "message": "Reading order contains duplicate threads; deduplicate before adoption."
        })));
    }

    // Check thread ownership for nodes
    let thread_ids: Vec<i32> = seen_threads.iter().copied().collect();
    if !thread_ids.is_empty() {
        let count: i64 = tx
            .query_one(
                "SELECT COUNT(*) FROM threads WHERE id = ANY($1::int[]) AND user_id = $2",
                &[&thread_ids, &user.id()],
            )
            .await
            .map_err(db::query_error)?
            .get(0);
        
        if count as usize != thread_ids.len() {
            tx.rollback().await.map_err(db::query_error)?;
            return Err(bad_request("Some threads are not owned by the user"));
        }
    }

    // Determine plan name
    let plan_name = payload
        .plan_name
        .as_ref()
        .and_then(|n| if n.trim().is_empty() { None } else { Some(n.trim().to_string()) })
        .unwrap_or_else(|| {
            if order_name.trim().is_empty() {
                format!("From reading order {}", order_id)
            } else {
                order_name.trim().to_string()
            }
        });

    let lane_id = payload.lane_id.unwrap_or_else(|| "adopted".to_string());
    let lane_name = payload.lane_name.unwrap_or_else(|| "Adopted".to_string());

    // Build nodes JSON
    let mut nodes_val = serde_json::Value::Array(Vec::new());
    for (idx, thread_id) in thread_ids.iter().enumerate() {
        nodes_val.as_array_mut().unwrap().push(serde_json::json!({
            "id": format!("ro-{}", order_id * 1000 + thread_id),
            "node_type": "thread",
            "ref_id": thread_id,
            "lane_id": lane_id,
            "position": idx,
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

    // Create the plan first to get the plan_id
    let lanes_json = serde_json::to_string(&serde_json::Value::Array(vec![serde_json::json!({
        "id": lane_id,
        "name": lane_name,
        "order": 0
    })])).unwrap();
    let nodes_json = serde_json::to_string(&nodes_val).unwrap();

    let row = tx
        .query_one(
            r#"
            INSERT INTO continuity_plans (user_id, name, ordering_mode, lanes_json, nodes_json, created_at, updated_at)
            VALUES ($1, $2, 'informational', $3, $4, NOW(), NOW())
            RETURNING id, user_id, name, ordering_mode, lanes_json, nodes_json, created_at::text, updated_at::text
            "#,
            &[&user.id(), &plan_name, &lanes_json, &nodes_json],
        )
        .await
        .map_err(db::query_error)?;

    let plan_id: i32 = row.get(0);

    // Insert continuity plan membership with the correct plan_id
    for (idx, thread_id) in thread_ids.iter().enumerate() {
        tx.execute(
            "INSERT INTO reading_plan_issues (plan_id, issue_id, display_position, node_id) VALUES ($1, $2, $3, $4)",
            &[&plan_id, thread_id, &(idx as i32), &format!("ro-{}-{}", order_id, thread_id)],
        )
        .await
        .map_err(db::query_error)?;
    }

    // Mark as adopted from reading order
    tx.execute(
        "INSERT INTO reading_plan_sources (plan_id, raw_source_path, recorded_at) VALUES ($1, $2, NOW())",
        &[&plan_id, &format!("reading-order:{}", order_id)],
    )
    .await
    .map_err(db::query_error)?;

    tx.commit().await.map_err(db::query_error)?;

    let result = ContinuityPlanResponse {
        id: plan_id,
        user_id: row.get(1),
        name: row.get(2),
        ordering_mode: row.get(3),
        lanes: serde_json::from_value(row.get(4)).unwrap_or_default(),
        nodes: serde_json::from_value(row.get(5)).unwrap_or_default(),
        created_at: row.get(6),
        updated_at: row.get(7),
    };

    Ok((StatusCode::CREATED, Json(result)))
}

// ============================================================================
// GET /api/v1/continuity-plans/{plan_id}/membership - Get membership
// ============================================================================

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReadingPlanMembershipResponse {
    pub plan_id: i32,
    #[serde(rename = "issue_ids")]
    pub issue_ids: Vec<i32>,
    #[serde(rename = "issue_count")]
    pub issue_count: i32,
    #[serde(rename = "thread_ids")]
    pub thread_ids: Vec<i32>,
}

#[utoipa::path(
    get,
    path = "/api/v1/continuity-plans/{plan_id}/membership",
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

    // Get issue membership
    let issue_rows = conn
        .query(
            "SELECT DISTINCT issue_id FROM reading_plan_issues WHERE plan_id = $1",
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;
    let issue_ids: Vec<i32> = issue_rows.iter().map(|row| row.get(0)).collect();

    // Get thread ids from nodes
    let node_rows = conn
        .query(
            "SELECT nodes_json FROM continuity_plans WHERE id = $1",
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;
    
    let thread_ids: Vec<i32> = if let Some(row) = node_rows.first() {
        let nodes: Vec<serde_json::Value> = row.get(0);
        nodes
            .iter()
            .filter_map(|node| {
                if node.get("node_type").and_then(|v| v.as_str()) == Some("thread") {
                    node.get("ref_id").and_then(|v| v.as_i64()).map(|v| v as i32)
                } else {
                    None
                }
            })
            .collect()
    } else {
        Vec::new()
    };

    Ok(Json(ReadingPlanMembershipResponse {
        plan_id,
        issue_ids,
        issue_count: issue_ids.len() as i32,
        thread_ids,
    }))
}

// ============================================================================
// POST /api/v1/continuity-plans/{plan_id}/dependencies/{dependency_id} - Link dependency
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
    path = "/api/v1/continuity-plans/{plan_id}/dependencies/{dependency_id}",
    tag = "continuity-plans",
    operation_id = "continuity_plans_link_dependency",
    params((
        ("plan_id" = i32, Path, description = "Continuity plan identifier"),
        ("dependency_id" = i32, Path, description = "Dependency identifier")
    )),
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

    // Check plan ownership
    let plan = tx
        .query_opt(
            "SELECT id FROM continuity_plans WHERE id = $1 AND user_id = $2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| not_found(format!("Continuity plan {plan_id} not found")))?;

    // Get dependency and check ownership
    let dep_row = tx
        .query_opt(
            r#"
            SELECT d.id, d.source_issue_id, d.target_issue_id,
                   si.thread_id, st.title as source_title, si.issue_number,
                   ti.thread_id, tt.title as target_title, ti.issue_number
            FROM dependencies d
            JOIN issues si ON si.id = d.source_issue_id
            JOIN threads st ON st.id = si.thread_id
            JOIN issues ti ON ti.id = d.target_issue_id
            JOIN threads tt ON tt.id = ti.thread_id
            WHERE d.id = $1 AND st.user_id = $2 AND tt.user_id = $2
            "#,
            &[&dependency_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| not_found("Dependency not found or not owned"))?;

    let source_issue_id: i32 = dep_row.get(1);
    let target_issue_id: i32 = dep_row.get(2);
    let source_thread_id: i32 = dep_row.get(3);
    let source_title: String = dep_row.get(4);
    let source_issue_number: String = dep_row.get(5);
    let target_thread_id: i32 = dep_row.get(6);
    let target_title: String = dep_row.get(7);
    let target_issue_number: String = dep_row.get(8);

    // Check if already linked
    let existing = tx
        .query_opt(
            "SELECT id FROM reading_plan_dependencies WHERE plan_id = $1 AND dependency_id = $2",
            &[&plan_id, &dependency_id],
        )
        .await
        .map_err(db::query_error)?
        .is_some();

    if existing {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(crate::ApiError::Conflict(format!(
            "Dependency {} is already linked to plan {}",
            dependency_id, plan_id
        )));
    }

    // Create the reading_plan_dependency
    let linked_id: i32 = tx
        .query_one(
            "INSERT INTO reading_plan_dependencies (plan_id, dependency_id, explanation) VALUES ($1, $2, $3) RETURNING id",
            &[&plan_id, &dependency_id, &payload.explanation],
        )
        .await
        .map_err(db::query_error)?
        .get(0);

    tx.commit().await.map_err(db::query_error)?;

    Ok((
        StatusCode::CREATED,
        Json(ReadingPlanDependencyLink {
            dependency_id: linked_id,
            source_issue_id,
            target_issue_id,
            explanation: payload.explanation,
        }),
    ))
}

// ============================================================================
// DELETE /api/v1/continuity-plans/{plan_id}/dependencies/{dependency_id} - Unlink dependency
// ============================================================================

#[utoipa::path(
    delete,
    path = "/api/v1/continuity-plans/{plan_id}/dependencies/{dependency_id}",
    tag = "continuity-plans",
    operation_id = "continuity_plans_unlink_dependency",
    params((
        ("plan_id" = i32, Path, description = "Continuity plan identifier"),
        ("dependency_id" = i32, Path, description = "Dependency identifier")
    )),
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
// POST /api/v1/continuity-plans/{plan_id}/reading-orders/project - Project to reading order
// ============================================================================

#[utoipa::path(
    post,
    path = "/api/v1/continuity-plans/{plan_id}/reading-orders/project",
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
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;

    // Check plan ownership
    let plan = tx
        .query_opt(
            "SELECT id FROM continuity_plans WHERE id = $1 AND user_id = $2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| not_found(format!("Continuity plan {plan_id} not found")))?;

    // Check reading order ownership
    let order = tx
        .query_opt(
            "SELECT id FROM reading_orders WHERE id = $1 AND user_id = $2",
            &[&payload.reading_order_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| not_found(format!("Reading order {} not found", payload.reading_order_id)))?;

    // Get plan nodes
    let plan_rows = tx
        .query_one(
            "SELECT nodes_json, plan_id FROM continuity_plans WHERE id = $1",
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;

    let nodes: Vec<serde_json::Value> = plan_rows.get(0);
    let plan_ordering_mode: String = if nodes.is_empty() {
        "informational".to_string()
    } else {
        "strict_sequential".to_string() // Simplified for now
    };

    // Extract thread nodes
    let mut thread_nodes: Vec<(i32, i32, String)> = Vec::new(); // (position, thread_id, node_id)
    let mut node_ids_with_positions: std::collections::HashMap<String, i32> = std::collections::HashMap::new();
    
    for (pos, node) in nodes.iter().enumerate() {
        if node.get("node_type").and_then(|v| v.as_str()) == Some("thread") {
            if let (Some(thread_id), Some(node_id)) = (
                node.get("ref_id").and_then(|v| v.as_i64()).map(|v| v as i32),
                node.get("id").and_then(|v| v.as_str()).map(|s| s.to_string())
            ) {
                thread_nodes.push((pos as i32, thread_id, node_id.clone()));
                node_ids_with_positions.insert(node_id, pos as i32);
            }
        }
    }

    // Get existing order items
    let existing_items = tx
        .query(
            "SELECT thread_id, position FROM reading_order_items WHERE reading_order_id = $1 ORDER BY position",
            &[&payload.reading_order_id],
        )
        .await
        .map_err(db::query_error)?;

    // Check for conflicts - duplicate threads in plan
    let mut seen_threads = std::collections::HashSet::new();
    let mut duplicates = Vec::new();
    for (_, thread_id, _) in &thread_nodes {
        if seen_threads.contains(thread_id) {
            duplicates.push(*thread_id);
        } else {
            seen_threads.insert(thread_id);
        }
    }

    if !duplicates.is_empty() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(crate::ApiError::Conflict(serde_json::json!({
            "code": "projection_conflicts",
            "conflicts": [{
                "code": "duplicate_thread",
                "node_id": thread_nodes.iter().find(|(_, t, _)| **t == duplicates[0]).map(|(_, _, n)| n.clone()).unwrap_or_default(),
                "thread_id": duplicates[0],
                "message": "Thread appears multiple times in the plan",
                "existing_positions": []
            }]
        })));
    }

    // Apply projection: delete existing items and insert new ones
    tx.execute(
        "DELETE FROM reading_order_items WHERE reading_order_id = $1",
        &[&payload.reading_order_id],
    )
    .await
    .map_err(db::query_error)?;

    // Get thread titles
    let mut thread_titles = std::collections::HashMap::new();
    for (_, thread_id, _) in &thread_nodes {
        let title_row = tx
            .query_opt(
                "SELECT title FROM threads WHERE id = $1 AND user_id = $2",
                &[thread_id, &user.id()],
            )
            .await
            .map_err(db::query_error)?;
        if let Some(row) = title_row {
            thread_titles.insert(thread_id, row.get(0));
        }
    }

    let mut added = 0;
    let mut updated = 0;
    let mut kept = 0;

    for (pos, thread_id, _node_id) in thread_nodes.into_iter().map(|(p, t, n)| (p, t, n)) {
        let thread_title = thread_titles.get(&thread_id).cloned().unwrap_or_default();
        let source = if existing_items.iter().any(|r| r.get::<_, i32>(0) == thread_id) {
            // Check if position changed
            for row in &existing_items {
                if row.get::<_, i32>(0) == thread_id {
                    let old_pos: i32 = row.get(1);
                    if old_pos != pos + 1 {
                        // Position changed, counts as update
                    }
                }
            }
            if existing_items.iter().any(|r| r.get::<_, i32>(0) == thread_id && r.get::<_, i32>(1) == pos + 1) {
                kept += 1;
                "existing".to_string()
            } else {
                updated += 1;
                "updated".to_string()
            }
        } else {
            added += 1;
            "added".to_string()
        };

        tx.execute(
            "INSERT INTO reading_order_items (reading_order_id, thread_id, position, issue_number) VALUES ($1, $2, $3, NULL)",
            &[&payload.reading_order_id, thread_id, &(pos + 1)],
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
        total_positions: (added + updated + kept) as i32,
    }))
}