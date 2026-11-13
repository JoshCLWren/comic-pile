//! Reading order projection for continuity plans.

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    Json,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingOrderProjectionPreview {
    pub plan_id: i32,
    pub reading_order_id: i32,
    pub total_issues: usize,
    pub added_issues: usize,
    pub removed_issues: usize,
    pub reordered_issues: bool,
    pub conflicts: Vec<serde_json::Value>,
    pub preview: Vec<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingOrderProjectionResult {
    pub plan_id: i32,
    pub reading_order_id: i32,
    pub total_issues: usize,
    pub added_issues: usize,
    pub removed_issues: usize,
    pub reordered_issues: bool,
    pub status: String,
    pub message: Option<String>,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ReadingOrderProjectionRequest {
    pub reading_order_id: i32,
}

/// `POST /api/v2/continuity-plans/{plan_id}/reading-orders/project-preview`
pub async fn preview_plan_projection(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
    Json(payload): Json<ReadingOrderProjectionRequest>,
) -> Result<Json<ReadingOrderProjectionPreview>, ApiError> {
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
    
    // Verify reading order ownership
    let order_exists: bool = conn
        .query_opt(
            "SELECT 1 FROM custom_cbl_lists WHERE id=$1 AND user_id=$2",
            &[&payload.reading_order_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .is_some();
    
    if !order_exists {
        return Err(ApiError::NotFound("Reading order not found".to_string()));
    }
    
    // Get plan issues
    let plan_issues = conn
        .query(
            "SELECT issue_id FROM reading_plan_issues WHERE plan_id=$1 ORDER BY display_position",
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;
    
    let plan_issue_ids: Vec<i32> = plan_issues.into_iter().map(|row| row.get(0)).collect();
    
    // Get reading order issues
    let order_issues = conn
        .query(
            "SELECT issue_id FROM custom_cbl_entries WHERE list_id=$1 ORDER BY position",
            &[&payload.reading_order_id],
        )
        .await
        .map_err(db::query_error)?;
    
    let order_issue_ids: Vec<i32> = order_issues.into_iter().map(|row| row.get(0)).collect();
    
    // Find differences
    let plan_set: std::collections::HashSet<i32> = plan_issue_ids.iter().cloned().collect();
    let order_set: std::collections::HashSet<i32> = order_issue_ids.iter().cloned().collect();
    
    let added_issues: Vec<i32> = order_set.difference(&plan_set).cloned().collect();
    let removed_issues: Vec<i32> = plan_set.difference(&order_set).cloned().collect();
    let reordered_issues = plan_issue_ids != order_issue_ids;
    
    // Check for conflicts (issues not owned by user)
    let mut conflicts = Vec::new();
    for issue_id in &added_issues {
        let owned: bool = conn
            .query_opt(
                "SELECT 1 FROM issues WHERE id=$1 AND user_id=$2",
                &[issue_id, &user.id()],
            )
            .await
            .map_err(db::query_error)?
            .is_some();
        
        if !owned {
            conflicts.push(serde_json::json!({
                "issue_id": issue_id,
                "type": "not_owned"
            }));
        }
    }
    
    // Build preview
    let mut preview = Vec::new();
    for (i, &issue_id) in order_issue_ids.iter().enumerate() {
        let thread_row = conn
            .query_opt(
                "SELECT t.title, i.issue_number FROM threads t JOIN issues i ON i.thread_id=t.id WHERE i.id=$1",
                &[&issue_id],
            )
            .await
            .map_err(db::query_error)?;
        
        if let Some(thread_row) = thread_row {
            let in_plan = plan_issue_ids.contains(&issue_id);
            let status = if in_plan { "in_plan" } else { "added" };
            
            preview.push(serde_json::json!({
                "position": i + 1,
                "issue_id": issue_id,
                "thread_title": thread_row.get(0),
                "issue_number": thread_row.get(1),
                "status": status
            }));
        }
    }
    
    Ok(Json(ReadingOrderProjectionPreview {
        plan_id,
        reading_order_id: payload.reading_order_id,
        total_issues: order_issue_ids.len(),
        added_issues: added_issues.len(),
        removed_issues: removed_issues.len(),
        reordered_issues,
        conflicts,
        preview,
    }))
}

/// `POST /api/v2/continuity-plans/{plan_id}/reading-orders/project`
pub async fn confirm_plan_projection(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
    Json(payload): Json<ReadingOrderProjectionRequest>,
) -> Result<Json<ReadingOrderProjectionResult>, ApiError> {
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
    
    // Verify reading order ownership
    let order_exists: bool = conn
        .query_opt(
            "SELECT 1 FROM custom_cbl_lists WHERE id=$1 AND user_id=$2",
            &[&payload.reading_order_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .is_some();
    
    if !order_exists {
        return Err(ApiError::NotFound("Reading order not found".to_string()));
    }
    
    // Get current plan issues
    let plan_issues = conn
        .query(
            "SELECT issue_id, display_position FROM reading_plan_issues WHERE plan_id=$1 ORDER BY display_position",
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;
    
    let plan_issue_ids: Vec<i32> = plan_issues.iter().map(|row| row.get(0)).collect();
    
    // Get reading order issues
    let order_issues = conn
        .query(
            "SELECT issue_id FROM custom_cbl_entries WHERE list_id=$1 ORDER BY position",
            &[&payload.reading_order_id],
        )
        .await
        .map_err(db::query_error)?;
    
    let order_issue_ids: Vec<i32> = order_issues.iter().map(|row| row.get(0)).collect();
    
    // Find differences
    let plan_set: std::collections::HashSet<i32> = plan_issue_ids.iter().cloned().collect();
    let order_set: std::collections::HashSet<i32> = order_issue_ids.iter().cloned().collect();
    
    let added_issues: Vec<i32> = order_set.difference(&plan_set).cloned().collect();
    let removed_issues: Vec<i32> = plan_set.difference(&order_set).cloned().collect();
    let reordered_issues = plan_issue_ids != order_issue_ids;
    
    // Check for conflicts
    for issue_id in &added_issues {
        let owned: bool = conn
            .query_opt(
                "SELECT 1 FROM issues WHERE id=$1 AND user_id=$2",
                &[issue_id, &user.id()],
            )
            .await
            .map_err(db::query_error)?
            .is_some();
        
        if !owned {
            return Err(ApiError::BadRequest(
                format!("Cannot add issue {} to plan: not owned by user", issue_id)
            ));
        }
    }
    
    // Perform the projection in a transaction
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    
    // Remove issues that are no longer in the reading order
    for issue_id in &removed_issues {
        tx.execute(
            "DELETE FROM reading_plan_issues WHERE plan_id=$1 AND issue_id=$2",
            &[&plan_id, issue_id],
        ).await.map_err(db::query_error)?;
    }
    
    // Add issues that are in the reading order but not in the plan
    for (position, &issue_id) in order_issue_ids.iter().enumerate() {
        if !plan_issue_ids.contains(&issue_id) {
            tx.execute(
                "INSERT INTO reading_plan_issues (plan_id, issue_id, display_position, occurrence_id)
                 VALUES ($1, $2, $3, $4)",
                &[
                    &plan_id,
                    &issue_id,
                    &(position as i32 + 1),
                    &format!("projection:{}", issue_id),
                ],
            ).await.map_err(db::query_error)?;
        }
    }
    
    // Update positions for reordered issues
    if reordered_issues {
        for (position, &issue_id) in order_issue_ids.iter().enumerate() {
            tx.execute(
                "UPDATE reading_plan_issues SET display_position=$1 WHERE plan_id=$2 AND issue_id=$3",
                &[
                    &(position as i32 + 1),
                    &plan_id,
                    &issue_id,
                ],
            ).await.map_err(db::query_error)?;
        }
    }
    
    tx.commit().await.map_err(db::query_error)?;
    
    Ok(Json(ReadingOrderProjectionResult {
        plan_id,
        reading_order_id: payload.reading_order_id,
        total_issues: order_issue_ids.len(),
        added_issues: added_issues.len(),
        removed_issues: removed_issues.len(),
        reordered_issues,
        status: "completed".to_string(),
        message: None,
    }))
}

#[utoipa::path(
    post,
    path = "/api/v2/continuity-plans/{plan_id}/reading-orders/project-preview",
    tag = "continuity-plans",
    params(("plan_id" = i32, Path, description = "Continuity plan identifier")),
    request_body = ReadingOrderProjectionRequest,
    responses(
        (status = 200, description = "Projection preview", body = ReadingOrderProjectionPreview),
        (status = 400, description = "Invalid request"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan or reading order not found")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn preview_plan_projection_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/continuity-plans/{plan_id}/reading-orders/project",
    tag = "continuity-plans",
    params(("plan_id" = i32, Path, description = "Continuity plan identifier")),
    request_body = ReadingOrderProjectionRequest,
    responses(
        (status = 200, description = "Projection completed", body = ReadingOrderProjectionResult),
        (status = 400, description = "Invalid request or conflicts"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan or reading order not found")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn confirm_plan_projection_documentation() {}