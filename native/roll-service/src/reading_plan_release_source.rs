//! Reading Plan release source management.

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReleaseSourceResponse {
    pub id: i32,
    pub plan_id: i32,
    pub thread_id: i32,
    pub external_identity_id: i32,
    pub provider_volume_id: String,
    pub provider_title: Option<String>,
    pub provider_publisher: Option<String>,
    pub provider_start_year: Option<i32>,
    pub provider_issue_count: Option<i32>,
    pub enabled: bool,
    pub last_synced_at: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ReleaseSourceCreate {
    pub plan_id: i32,
    pub thread_id: i32,
    pub external_identity_id: i32,
    pub provider_volume_id: String,
    pub provider_title: Option<String>,
    pub provider_publisher: Option<String>,
    pub provider_start_year: Option<i32>,
    pub provider_issue_count: Option<i32>,
    pub enabled: bool,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ReleaseSourceUpdate {
    pub enabled: bool,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingPlanReleaseSourceStatus {
    pub source_id: i32,
    pub thread_id: i32,
    pub external_identity_id: i32,
    pub provider_volume_id: String,
    pub provider_title: Option<String>,
    pub provider_publisher: Option<String>,
    pub provider_start_year: Option<i32>,
    pub provider_issue_count: Option<i32>,
    pub enabled: bool,
    pub last_synced_at: Option<String>,
}

/// `POST /api/v2/continuity-plans/release-sources/`
pub async fn create_release_source(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(payload): Json<ReleaseSourceCreate>,
) -> Result<(StatusCode, Json<ReleaseSourceResponse>), ApiError> {
    let conn = db::checkout(&state).await?;
    
    // Verify plan ownership
    let plan_exists: bool = conn
        .query_opt(
            "SELECT 1 FROM continuity_plans WHERE id=$1 AND user_id=$2",
            &[&payload.plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .is_some();

    if !plan_exists {
        return Err(ApiError::NotFound("Continuity plan not found".to_string()));
    }

    // Verify thread ownership
    let thread_exists: bool = conn
        .query_opt(
            "SELECT 1 FROM threads WHERE id=$1 AND user_id=$2",
            &[&payload.thread_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .is_some();

    if !thread_exists {
        return Err(ApiError::NotFound("Thread not found".to_string()));
    }

    // Verify external identity exists
    let identity_exists: bool = conn
        .query_opt(
            "SELECT 1 FROM external_identities WHERE id=$1",
            &[&payload.external_identity_id],
        )
        .await
        .map_err(db::query_error)?
        .is_some();

    if !identity_exists {
        return Err(ApiError::NotFound(
            "External identity not found".to_string(),
        ));
    }

    let result = conn
        .query(
            "INSERT INTO reading_plan_release_sources 
             (plan_id, thread_id, external_identity_id, provider_volume_id, provider_title, 
              provider_publisher, provider_start_year, provider_issue_count, enabled, created_at, updated_at)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), NOW())
             RETURNING id, plan_id, thread_id, external_identity_id, provider_volume_id, provider_title,
                       provider_publisher, provider_start_year, provider_issue_count, enabled,
                       last_synced_at::text, created_at::text, updated_at::text",
            &[
                &payload.plan_id,
                &payload.thread_id,
                &payload.external_identity_id,
                &payload.provider_volume_id,
                &payload.provider_title,
                &payload.provider_publisher,
                &payload.provider_start_year,
                &payload.provider_issue_count,
                &payload.enabled,
            ],
        )
        .await
        .map_err(db::query_error)?;

    let row = result
        .into_iter()
        .next()
        .ok_or_else(|| ApiError::Internal("Failed to create release source".to_string()))?;
    let source = ReleaseSourceResponse {
        id: row.get(0),
        plan_id: row.get(1),
        thread_id: row.get(2),
        external_identity_id: row.get(3),
        provider_volume_id: row.get(4),
        provider_title: row.get(5),
        provider_publisher: row.get(6),
        provider_start_year: row.get(7),
        provider_issue_count: row.get(8),
        enabled: row.get(9),
        last_synced_at: row.get(10),
        created_at: row.get(11),
        updated_at: row.get(12),
    };
    
    Ok((StatusCode::CREATED, Json(source)))
}

/// `GET /api/v2/continuity-plans/{plan_id}/release-sources/`
pub async fn list_release_sources(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
) -> Result<Json<Vec<ReleaseSourceResponse>>, ApiError> {
    let conn = db::checkout(&state).await?;

    // Verify plan ownership and fetch related release sources
    let rows = conn
        .query(
            "SELECT r.id, r.plan_id, r.thread_id, r.external_identity_id, r.provider_volume_id,
                     r.provider_title, r.provider_publisher, r.provider_start_year,
                     r.provider_issue_count, r.enabled, r.last_synced_at::text,
                     r.created_at::text, r.updated_at::text
              FROM reading_plan_release_sources r
              JOIN continuity_plans p ON p.id=r.plan_id
              WHERE r.plan_id=$1 AND p.user_id=$2
              ORDER BY r.created_at, r.id",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;

    let sources: Vec<ReleaseSourceResponse> = rows
        .into_iter()
        .map(|row| ReleaseSourceResponse {
            id: row.get(0),
            plan_id: row.get(1),
            thread_id: row.get(2),
            external_identity_id: row.get(3),
            provider: "comicvine".to_string(),
            provider_volume_id: row.get(4),
            provider_title: row.get(5),
            provider_publisher: row.get(6),
            provider_start_year: row.get(7),
            provider_issue_count: row.get(8),
            enabled: row.get(9),
            last_synced_at: row.get(10),
            created_at: row.get(11),
            updated_at: row.get(12),
        })
        .collect();

    Ok(Json(sources))
}

/// `GET /api/v2/continuity-plans/{plan_id}/release-sources/reader`
pub async fn list_release_sources_for_reader(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
) -> Result<Json<Vec<ReadingPlanReleaseSourceStatus>>, ApiError> {
    let conn = db::checkout(&state).await?;

    // Verify plan ownership and fetch related release sources
    let rows = conn
        .query(
            "SELECT r.id, r.thread_id, r.external_identity_id, r.provider_volume_id,
                     r.provider_title, r.provider_publisher, r.provider_start_year,
                     r.provider_issue_count, r.enabled, r.last_synced_at::text
              FROM reading_plan_release_sources r
              JOIN continuity_plans p ON p.id=r.plan_id
              WHERE r.plan_id=$1 AND p.user_id=$2
              ORDER BY r.created_at, r.id",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;

    let sources: Vec<ReadingPlanReleaseSourceStatus> = rows
        .into_iter()
        .map(|row| ReadingPlanReleaseSourceStatus {
            source_id: row.get(0),
            thread_id: row.get(1),
            external_identity_id: row.get(2),
            provider_volume_id: row.get(3),
            provider_title: row.get(4),
            provider_publisher: row.get(5),
            provider_start_year: row.get(6),
            provider_issue_count: row.get(7),
            enabled: row.get(8),
            last_synced_at: row.get(9),
        })
        .collect();

    Ok(Json(sources))
}

/// `PATCH /api/v2/continuity-plans/release-sources/{source_id}`
pub async fn update_release_source(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(source_id): Path<i32>,
    Json(payload): Json<ReleaseSourceUpdate>,
) -> Result<Json<ReleaseSourceResponse>, ApiError> {
    let conn = db::checkout(&state).await?;

    // Verify source exists and user owns the associated plan
    let row = conn
        .query_opt(
            "SELECT r.id, r.thread_id, r.external_identity_id, r.provider_volume_id,
                    r.provider_title, r.provider_publisher, r.provider_start_year,
                    r.provider_issue_count, r.enabled, r.last_synced_at::text,
                    r.created_at::text, r.updated_at::text, p.user_id
             FROM reading_plan_release_sources r
             JOIN reading_plan_issues pi ON pi.issue_id=r.thread_id
             JOIN continuity_plans p ON p.id=pi.plan_id
             WHERE r.id=$1 AND p.user_id=$2",
            &[&source_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound("Release source not found".to_string()))?;

    let result = conn
        .query(
            "UPDATE reading_plan_release_sources 
             SET enabled=$1, updated_at=NOW()
             WHERE id=$2
             RETURNING id, thread_id, external_identity_id, provider_volume_id,
                      provider_title, provider_publisher, provider_start_year,
                      provider_issue_count, enabled, last_synced_at::text,
                      created_at::text, updated_at::text",
            &[&payload.enabled, &source_id],
        )
        .await
        .map_err(db::query_error)?;

    let updated_row = result
        .into_iter()
        .next()
        .ok_or_else(|| ApiError::Internal("Failed to update release source".to_string()))?;
    let source = ReleaseSourceResponse {
        id: updated_row.get(0),
        thread_id: updated_row.get(1),
        external_identity_id: updated_row.get(2),
        provider_volume_id: updated_row.get(3),
        provider_title: updated_row.get(4),
        provider_publisher: updated_row.get(5),
        provider_start_year: updated_row.get(6),
        provider_issue_count: updated_row.get(7),
        enabled: updated_row.get(8),
        last_synced_at: updated_row.get(9),
        created_at: updated_row.get(10),
        updated_at: updated_row.get(11),
    };

    Ok(Json(source))
}

/// `DELETE /api/v2/continuity-plans/release-sources/{source_id}`
pub async fn delete_release_source(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(source_id): Path<i32>,
) -> Result<StatusCode, ApiError> {
    let conn = db::checkout(&state).await?;
    
    // Verify source exists and user owns the associated plan
    let result = conn
        .execute(
            "DELETE FROM reading_plan_release_sources r
             USING continuity_plans p
             WHERE r.id=$1 AND r.plan_id=p.id AND p.user_id=$2",
            &[&source_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;

    if result == 0 {
        return Err(ApiError::NotFound("Release source not found".to_string()));
    }
    
    Ok(StatusCode::NO_CONTENT)
}

#[utoipa::path(
    post,
    path = "/api/v2/continuity-plans/release-sources/",
    tag = "continuity-plans",
    request_body = ReleaseSourceCreate,
    responses(
        (status = 201, description = "Created release source", body = ReleaseSourceResponse),
        (status = 400, description = "Invalid request"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread or identity not found"),
        (status = 409, description = "Source validation conflict")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn create_release_source_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v2/continuity-plans/{plan_id}/release-sources/",
    tag = "continuity-plans",
    params(("plan_id" = i32, Path, description = "Continuity plan identifier")),
    responses(
        (status = 200, description = "List of release sources", body = Vec<ReleaseSourceResponse>),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan not found")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_release_sources_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v2/continuity-plans/{plan_id}/release-sources/reader",
    tag = "continuity-plans",
    params(("plan_id" = i32, Path, description = "Continuity plan identifier")),
    responses(
        (status = 200, description = "Reader-facing release source status", body = Vec<ReadingPlanReleaseSourceStatus>),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan not found")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_release_sources_for_reader_documentation() {}

#[utoipa::path(
    patch,
    path = "/api/v2/continuity-plans/release-sources/{source_id}",
    tag = "continuity-plans",
    params(("source_id" = i32, Path, description = "Release source identifier")),
    request_body = ReleaseSourceUpdate,
    responses(
        (status = 200, description = "Updated release source", body = ReleaseSourceResponse),
        (status = 400, description = "Invalid request"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Source not found")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn update_release_source_documentation() {}

#[utoipa::path(
    delete,
    path = "/api/v2/continuity-plans/release-sources/{source_id}",
    tag = "continuity-plans",
    params(("source_id" = i32, Path, description = "Release source identifier")),
    responses(
        (status = 204, description = "Release source deleted"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Source not found")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn delete_release_source_documentation() {}
