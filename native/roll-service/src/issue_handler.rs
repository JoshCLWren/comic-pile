//! Issue read/rate endpoint handler.

use crate::{
    auth::{authenticate, AuthenticatedUser},
    config::Config,
    db::DbPool,
    error::ServiceError,
    issue_service::{IssueReadRateRequest, IssueReadRateResponse, IssueService},
    AppState,
};
use axum::{
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
    response::Json,
};
use serde::Deserialize;
use std::sync::Arc;

/// Request body for issue read/rate operation.
#[derive(Debug, Deserialize)]
pub struct IssueReadRateRequestWrapper {
    pub status: Option<String>,
    pub rating: Option<f64>,
}

/// Handle PATCH /api/v2/issues/{issue_id} for direct issue reading and rating.
///
/// This endpoint implements:
/// - Real, authenticated, owner-scoped, idempotent direct-issue reading command
/// - Takes exact owned issue ID and rating (0.5-5, step 0.5, default 3.5 when user leaves slider unchanged)
/// - Validates identity, not Option E eligibility
/// - Atomically persists issue read status + rating/activity event/history
/// - Updates thread's earliest genuinely unread frontier/remaining/complete status
/// - Returns reconciled issue/thread/rating data for the UI
/// - Never silently mark preceding issues read or satisfy uncompleted prerequisites
/// - Same issue read again avoids duplicate read events, allows rating correction
/// - Rating correction is not an unread operation
pub async fn read_rate_issue(
    State(state): State<Arc<AppState>>,
    Path(issue_id): Path<i32>,
    headers: HeaderMap,
    Json(request): Json<IssueReadRateRequestWrapper>,
) -> Result<Json<IssueReadRateResponse>, ServiceError> {
    // Extract authorization header and authenticate user
    let auth_header = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .ok_or_else(|| ServiceError::Unauthorized("Missing authorization header"))?;

    let token = auth_header
        .split_once(' ')
        .and_then(|(scheme, token)| {
            if scheme.eq_ignore_ascii_case("bearer") {
                Some(token)
            } else {
                None
            }
        })
        .ok_or_else(|| ServiceError::Unauthorized("Invalid authorization header format"))?;

    let authenticated_user = authenticate(&state, token).await?;

    // Create the issue service
    let issue_service = IssueService::new(state.pool.clone(), Arc::new(Config::from_vercel_env()?));

    // Convert the request to the internal format
    let internal_request = IssueReadRateRequest {
        status: request.status,
        rating: request.rating,
    };

    // Process the read/rate operation
    let response = issue_service
        .read_rate_issue(authenticated_user, issue_id, internal_request)
        .await?;

    Ok(Json(response))
}
