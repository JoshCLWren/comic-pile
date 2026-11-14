//! Continuity Plan CRUD operations and management.

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    Json,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ContinuityPlanListItem {
    pub id: i32,
    pub name: String,
    pub ordering_mode: String,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ContinuityPlanResponse {
    pub id: i32,
    pub name: String,
    pub ordering_mode: String,
    pub nodes_json: Vec<serde_json::Value>,
    pub lanes_json: Option<Vec<serde_json::Value>>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ContinuityPlanWrite {
    pub name: String,
    pub ordering_mode: String,
    pub nodes: Vec<serde_json::Value>,
    pub lanes: Vec<serde_json::Value>,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ReadingPlanDependencyLink {
    pub dependency_id: i32,
    pub source_issue_id: i32,
    pub target_issue_id: i32,
    pub explanation: String,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ReadingPlanDependencyLinkRequest {
    pub explanation: Option<String>,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ReadingPlanMembershipResponse {
    pub plan_id: i32,
    pub total_issues: usize,
    pub read_issues: usize,
    pub issues: Vec<serde_json::Value>,
    pub dependencies: Vec<serde_json::Value>,
}

/// `GET /api/v2/continuity-plans/`
pub async fn list_continuity_plans(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> Result<Json<Vec<ContinuityPlanListItem>>, ApiError> {
    let conn = db::checkout(&state).await?;
    let rows = conn
        .query(
            "SELECT id, name, ordering_mode, created_at::text, updated_at::text
             FROM continuity_plans 
             WHERE user_id=$1 
             ORDER BY updated_at DESC",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;
    
    let plans: Vec<ContinuityPlanListItem> = rows
        .into_iter()
        .map(|row| ContinuityPlanListItem {
            id: row.get(0),
            name: row.get(1),
            ordering_mode: row.get(2),
            created_at: row.get(3),
            updated_at: row.get(4),
        })
        .collect();
    
    Ok(Json(plans))
}

/// `POST /api/v2/continuity-plans/`
pub async fn create_continuity_plan(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(payload): Json<ContinuityPlanWrite>,
) -> Result<Json<ContinuityPlanResponse>, ApiError> {
    let conn = db::checkout(&state).await?;
    
    // Check if any node references issues not owned by the user
    for node in &payload.nodes {
        if let Some(issue_id) = node.get("issue_id").and_then(|v| v.as_i64()) {
            let exists: bool = conn
                .query_opt(
                    "SELECT 1 FROM issues i JOIN threads t ON t.id=i.thread_id WHERE i.id=$1 AND t.user_id=$2",
                    &[&issue_id, &user.id()],
                )
                .await
                .map_err(db::query_error)?
                .is_some();
            if !exists {
                return Err(ApiError::BadRequest(
                    format!("Issue {} not found or not owned by user", issue_id)
                ));
            }
        }
    }
    
    let result = conn
        .query(
            "INSERT INTO continuity_plans (user_id, name, ordering_mode, nodes_json, lanes_json, created_at, updated_at)
             VALUES ($1, $2, $3, $4, $5, NOW(), NOW())
             RETURNING id, name, ordering_mode, nodes_json, lanes_json, created_at::text, updated_at::text",
            &[
                &user.id(),
                &payload.name,
                &payload.ordering_mode,
                &serde_json::to_value(&payload.nodes).map_err(|e| ApiError::Internal(format!("Failed to serialize nodes: {}", e)))?,
                &serde_json::to_value(&payload.lanes).map_err(|e| ApiError::Internal(format!("Failed to serialize lanes: {}", e)))?,
            ],
        )
        .await
        .map_err(db::query_error)?;
    
    let row = result.into_iter().next().ok_or_else(|| ApiError::Internal("Failed to create continuity plan".to_string()))?;
    let plan = ContinuityPlanResponse {
        id: row.get(0),
        name: row.get(1),
        ordering_mode: row.get(2),
        nodes_json: row.get(3),
        lanes_json: row.get(4),
        created_at: row.get(5),
        updated_at: row.get(6),
    };
    
    Ok(Json(plan))
}

/// `GET /api/v2/continuity-plans/{plan_id}`
pub async fn get_continuity_plan(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
) -> Result<Json<ContinuityPlanResponse>, ApiError> {
    let conn = db::checkout(&state).await?;
    let row = conn
        .query_opt(
            "SELECT id, name, ordering_mode, nodes_json, lanes_json, created_at::text, updated_at::text
             FROM continuity_plans 
             WHERE id=$1 AND user_id=$2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound("Continuity plan not found".to_string()))?;
    
    let plan = ContinuityPlanResponse {
        id: row.get(0),
        name: row.get(1),
        ordering_mode: row.get(2),
        nodes_json: row.get(3),
        lanes_json: row.get(4),
        created_at: row.get(5),
        updated_at: row.get(6),
    };
    
    Ok(Json(plan))
}

/// `PUT /api/v2/continuity-plans/{plan_id}`
pub async fn update_continuity_plan(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
    Json(payload): Json<ContinuityPlanWrite>,
) -> Result<Json<ContinuityPlanResponse>, ApiError> {
    let conn = db::checkout(&state).await?;
    
    // Verify plan ownership
    let exists: bool = conn
        .query_opt(
            "SELECT 1 FROM continuity_plans WHERE id=$1 AND user_id=$2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .is_some();
    
    if !exists {
        return Err(ApiError::NotFound("Continuity plan not found".to_string()));
    }
    
    // Check if any node references issues not owned by the user
    for node in &payload.nodes {
        if let Some(issue_id) = node.get("issue_id").and_then(|v| v.as_i64()) {
            let issue_exists: bool = conn
                .query_opt(
                    "SELECT 1 FROM issues i JOIN threads t ON t.id=i.thread_id WHERE i.id=$1 AND t.user_id=$2",
                    &[&issue_id, &user.id()],
                )
                .await
                .map_err(db::query_error)?
                .is_some();
            if !issue_exists {
                return Err(ApiError::BadRequest(
                    format!("Issue {} not found or not owned by user", issue_id)
                ));
            }
        }
    }
    
    let result = conn
        .query(
            "UPDATE continuity_plans 
             SET name=$1, ordering_mode=$2, nodes_json=$3, lanes_json=$4, updated_at=NOW()
             WHERE id=$5 AND user_id=$6
             RETURNING id, name, ordering_mode, nodes_json, lanes_json, created_at::text, updated_at::text",
            &[
                &payload.name,
                &payload.ordering_mode,
                &serde_json::to_value(&payload.nodes).map_err(|e| ApiError::Internal(format!("Failed to serialize nodes: {}", e)))?,
                &serde_json::to_value(&payload.lanes).map_err(|e| ApiError::Internal(format!("Failed to serialize lanes: {}", e)))?,
                &plan_id,
                &user.id(),
            ],
        )
        .await
        .map_err(db::query_error)?;
    
    let row = result.into_iter().next().ok_or_else(|| ApiError::Internal("Failed to create continuity plan".to_string()))?;
    let plan = ContinuityPlanResponse {
        id: row.get(0),
        name: row.get(1),
        ordering_mode: row.get(2),
        nodes_json: row.get(3),
        lanes_json: row.get(4),
        created_at: row.get(5),
        updated_at: row.get(6),
    };
    
    Ok(Json(plan))
}

/// `DELETE /api/v2/continuity-plans/{plan_id}`
pub async fn delete_continuity_plan(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
) -> Result<(), ApiError> {
    let conn = db::checkout(&state).await?;
    
    // Verify plan ownership and delete
    let result = conn
        .execute(
            "DELETE FROM continuity_plans WHERE id=$1 AND user_id=$2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    
    if result == 0 {
        return Err(ApiError::NotFound("Continuity plan not found".to_string()));
    }
    
    Ok(())
}

/// `GET /api/v2/continuity-plans/{plan_id}/membership`
pub async fn get_continuity_plan_membership(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
) -> Result<Json<ReadingPlanMembershipResponse>, ApiError> {
    let conn = db::checkout(&state).await?;
    
    // Verify plan ownership
    let plan_exists: bool = conn
        .query_opt(
            "SELECT 1 FROM continuity_plans WHERE id=$1 AND user_id=$2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .is_some();
    
    if !plan_exists {
        return Err(ApiError::NotFound("Continuity plan not found".to_string()));
    }
    
    // Get plan issues
    let issue_rows = conn
        .query(
            "SELECT r.issue_id, r.display_position, r.occurrence_id,
                    i.issue_number, t.title, i.status, r.is_checkpoint
             FROM reading_plan_issues r
             JOIN issues i ON i.id=r.issue_id
             JOIN threads t ON t.id=i.thread_id AND t.user_id=$2
             WHERE r.plan_id=$1
             ORDER BY r.display_position, r.occurrence_id",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    
    let issues: Vec<serde_json::Value> = issue_rows
        .into_iter()
        .map(|row| {
            serde_json::json!({
                "issue_id": row.get(0),
                "display_position": row.get(1),
                "occurrence_id": row.get(2),
                "issue_number": row.get(3),
                "thread_title": row.get(4),
                "status": row.get(5),
                "is_checkpoint": row.get(6),
            })
        })
        .collect();
    
    // Get plan dependencies
    let dependency_rows = conn
        .query(
            "SELECT d.id, d.source_issue_id, d.target_issue_id, pd.explanation
             FROM reading_plan_dependencies pd
             JOIN dependencies d ON d.id=pd.dependency_id
             WHERE pd.plan_id=$1",
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;
    
    let dependencies: Vec<serde_json::Value> = dependency_rows
        .into_iter()
        .map(|row| {
            serde_json::json!({
                "dependency_id": row.get(0),
                "source_issue_id": row.get(1),
                "target_issue_id": row.get(2),
                "explanation": row.get(3),
            })
        })
        .collect();
    
    let total_issues = issues.len();
    let read_issues = issues.iter().filter(|issue| {
        issue.get("status").and_then(|s| s.as_str()) == Some("read")
    }).count();
    
    Ok(Json(ReadingPlanMembershipResponse {
        plan_id,
        total_issues,
        read_issues,
        issues,
        dependencies,
    }))
}

/// `POST /api/v2/continuity-plans/{plan_id}/dependencies/{dependency_id}`
pub async fn link_plan_dependency_edge(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path((plan_id, dependency_id)): Path<(i32, i32)>,
    Json(payload): Json<ReadingPlanDependencyLinkRequest>,
) -> Result<Json<ReadingPlanDependencyLink>, ApiError> {
    let conn = db::checkout(&state).await?;
    
    // Verify plan ownership
    let plan_exists: bool = conn
        .query_opt(
            "SELECT 1 FROM continuity_plans WHERE id=$1 AND user_id=$2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .is_some();
    
    if !plan_exists {
        return Err(ApiError::NotFound("Continuity plan not found".to_string()));
    }
    
    // Verify dependency exists and get source/target info
    let dep_row = conn
        .query_opt(
            "SELECT source_issue_id, target_issue_id FROM dependencies WHERE id=$1",
            &[&dependency_id],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound("Dependency not found".to_string()))?;
    
    let source_id: i32 = dep_row.get(0);
    let target_id: i32 = dep_row.get(1);
    
    // Check if dependency is already linked to this plan
    let exists: bool = conn
        .query_opt(
            "SELECT 1 FROM reading_plan_dependencies WHERE plan_id=$1 AND dependency_id=$2",
            &[&plan_id, &dependency_id],
        )
        .await
        .map_err(db::query_error)?
        .is_some();
    
    if exists {
        return Err(ApiError::Conflict(
            "Dependency already linked to this plan".to_string()
        ));
    }
    
    // Link the dependency
    conn.execute(
        "INSERT INTO reading_plan_dependencies (plan_id, dependency_id) VALUES ($1, $2)",
        &[&plan_id, &dependency_id],
    ).await.map_err(db::query_error)?;
    
    Ok(Json(ReadingPlanDependencyLink {
        dependency_id,
        source_issue_id: source_id,
        target_issue_id: target_id,
        explanation: payload.explanation.unwrap_or_default(),
    }))
}

/// `DELETE /api/v2/continuity-plans/{plan_id}/dependencies/{dependency_id}`
pub async fn unlink_plan_dependency_edge(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path((plan_id, dependency_id)): Path<(i32, i32)>,
) -> Result<(), ApiError> {
    let conn = db::checkout(&state).await?;
    
    // Verify plan ownership
    let plan_exists: bool = conn
        .query_opt(
            "SELECT 1 FROM continuity_plans WHERE id=$1 AND user_id=$2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .is_some();
    
    if !plan_exists {
        return Err(ApiError::NotFound("Continuity plan not found".to_string()));
    }
    
    // Remove the dependency link
    let result = conn
        .execute(
            "DELETE FROM reading_plan_dependencies WHERE plan_id=$1 AND dependency_id=$2",
            &[&plan_id, &dependency_id],
        )
        .await
        .map_err(db::query_error)?;
    
    if result == 0 {
        return Err(ApiError::NotFound(
            "Dependency not linked to this plan".to_string()
        ));
    }
    
    Ok(())
}

/// `POST /api/v2/continuity-plans/from-reading-order`
pub async fn adopt_reading_order(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(payload): Json<serde_json::Value>,
) -> Result<Json<ContinuityPlanResponse>, ApiError> {
    let conn = db::checkout(&state).await?;
    
    // Extract reading order ID from payload
    let reading_order_id = payload.get("reading_order_id")
        .and_then(|v| v.as_i64())
        .ok_or_else(|| ApiError::BadRequest("reading_order_id is required".to_string()))? as i32;
    
    let plan_name = payload.get("plan_name")
        .and_then(|v| v.as_str())
        .ok_or_else(|| ApiError::BadRequest("plan_name is required".to_string()))?;
    
    let lane_id = payload.get("lane_id")
        .and_then(|v| v.as_i64())
        .map(|v| v as i32);
    
    let lane_name = payload.get("lane_name")
        .and_then(|v| v.as_str());
    
    // Verify reading order ownership
    let order_exists: bool = conn
        .query_opt(
            "SELECT 1 FROM custom_cbl_lists WHERE id=$1 AND user_id=$2",
            &[&reading_order_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .is_some();
    
    if !order_exists {
        return Err(ApiError::NotFound("Reading order not found".to_string()));
    }
    
    // Get reading order entries
    let order_entries = conn
        .query(
            "SELECT issue_id FROM custom_cbl_entries WHERE list_id=$1 ORDER BY position",
            &[&reading_order_id],
        )
        .await
        .map_err(db::query_error)?;
    
    let issue_ids: Vec<i32> = order_entries.into_iter().map(|row| row.get(0)).collect();
    
    // Verify all issues are owned by the user
    for issue_id in &issue_ids {
        let owned: bool = conn
            .query_opt(
                "SELECT 1 FROM issues i JOIN threads t ON t.id=i.thread_id WHERE i.id=$1 AND t.user_id=$2",
                &[issue_id, &user.id()],
            )
            .await
            .map_err(db::query_error)?
            .is_some();
        
        if !owned {
            return Err(ApiError::BadRequest(
                format!("Issue {} not found or not owned by user", issue_id)
            ));
        }
    }
    
    // Create nodes from reading order
    let mut nodes = Vec::new();
    for (position, &issue_id) in issue_ids.iter().enumerate() {
        nodes.push(serde_json::json!({
            "issue_id": issue_id,
            "position": position + 1,
            "occurrence_id": format!("reading_order:{}", reading_order_id),
        }));
    }
    
    // Create lanes if provided
    let lanes = if let Some(lane_name) = lane_name {
        vec![serde_json::json!({
            "name": lane_name,
            "position": 1,
        })]
    } else {
        Vec::new()
    };
    
    // Create the continuity plan
    let result = conn
        .query(
            "INSERT INTO continuity_plans (user_id, name, ordering_mode, nodes_json, lanes_json, created_at, updated_at)
             VALUES ($1, $2, $3, $4, $5, NOW(), NOW())
             RETURNING id, name, ordering_mode, nodes_json, lanes_json, created_at::text, updated_at::text",
            &[
                &user.id(),
                &plan_name,
                &"reading-order".to_string(), // Use a specific ordering mode for adopted plans
                &serde_json::to_value(&nodes).map_err(|e| ApiError::Internal(format!("Failed to serialize nodes: {}", e)))?,
                &serde_json::to_value(&lanes).map_err(|e| ApiError::Internal(format!("Failed to serialize lanes: {}", e)))?,
            ],
        )
        .await
        .map_err(db::query_error)?;
    
    let row = result.into_iter().next().ok_or_else(|| ApiError::Internal("Failed to create continuity plan".to_string()))?;
    let plan = ContinuityPlanResponse {
        id: row.get(0),
        name: row.get(1),
        ordering_mode: row.get(2),
        nodes_json: row.get(3),
        lanes_json: row.get(4),
        created_at: row.get(5),
        updated_at: row.get(6),
    };
    
    Ok(Json(plan))
}

#[utoipa::path(
    get,
    path = "/api/v2/continuity-plans/",
    tag = "continuity-plans",
    responses(
        (status = 200, description = "List of continuity plans", body = Vec<ContinuityPlanListItem>),
        (status = 401, description = "Not authenticated")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_continuity_plans_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/continuity-plans/",
    tag = "continuity-plans",
    request_body = ContinuityPlanWrite,
    responses(
        (status = 201, description = "Created continuity plan", body = ContinuityPlanResponse),
        (status = 400, description = "Invalid request"),
        (status = 401, description = "Not authenticated"),
        (status = 409, description = "Plan validation conflict")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn create_continuity_plan_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v2/continuity-plans/{plan_id}",
    tag = "continuity-plans",
    params(("plan_id" = i32, Path, description = "Continuity plan identifier")),
    responses(
        (status = 200, description = "Continuity plan details", body = ContinuityPlanResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan not found")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_continuity_plan_documentation() {}

#[utoipa::path(
    put,
    path = "/api/v2/continuity-plans/{plan_id}",
    tag = "continuity-plans",
    params(("plan_id" = i32, Path, description = "Continuity plan identifier")),
    request_body = ContinuityPlanWrite,
    responses(
        (status = 200, description = "Updated continuity plan", body = ContinuityPlanResponse),
        (status = 400, description = "Invalid request"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan not found"),
        (status = 409, description = "Plan validation conflict")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn update_continuity_plan_documentation() {}

#[utoipa::path(
    delete,
    path = "/api/v2/continuity-plans/{plan_id}",
    tag = "continuity-plans",
    params(("plan_id" = i32, Path, description = "Continuity plan identifier")),
    responses(
        (status = 204, description = "Plan deleted"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan not found")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn delete_continuity_plan_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v2/continuity-plans/{plan_id}/membership",
    tag = "continuity-plans",
    params(("plan_id" = i32, Path, description = "Continuity plan identifier")),
    responses(
        (status = 200, description = "Plan membership details", body = ReadingPlanMembershipResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan not found")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_continuity_plan_membership_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/continuity-plans/{plan_id}/dependencies/{dependency_id}",
    tag = "continuity-plans",
    params(("plan_id" = i32, Path, description = "Continuity plan identifier"), 
            ("dependency_id" = i32, Path, description = "Dependency identifier")),
    request_body = ReadingPlanDependencyLinkRequest,
    responses(
        (status = 201, description = "Dependency linked", body = ReadingPlanDependencyLink),
        (status = 400, description = "Invalid request"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan or dependency not found"),
        (status = 409, description = "Dependency already linked")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn link_plan_dependency_edge_documentation() {}

#[utoipa::path(
    delete,
    path = "/api/v2/continuity-plans/{plan_id}/dependencies/{dependency_id}",
    tag = "continuity-plans",
    params(("plan_id" = i32, Path, description = "Continuity plan identifier"), 
            ("dependency_id" = i32, Path, description = "Dependency identifier")),
    responses(
        (status = 204, description = "Dependency unlinked"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan not found or dependency not linked")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn unlink_plan_dependency_edge_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/continuity-plans/from-reading-order",
    tag = "continuity-plans",
    request_body = serde_json::Value,
    responses(
        (status = 201, description = "Plan created from reading order", body = ContinuityPlanResponse),
        (status = 400, description = "Invalid request"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Reading order not found"),
        (status = 409, description = "Order validation conflict")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn adopt_reading_order_documentation() {}