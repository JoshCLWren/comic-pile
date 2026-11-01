//! Native, authenticated PATCH /api/v2/issues/{issue_id}.
//! Manual completion validates ownership, not Option E eligibility.
use crate::{
    auth::AuthenticatedUser,
    db,
    dice_api::Pending,
    issue_service::{self, IssueReadRateRequest, IssueReadRateResponse},
    ApiError, AppState,
};
use axum::{extract::{Path, State}, Json};
use std::sync::Arc;
use tokio_postgres::IsolationLevel;

/// Commit status, rating, history and frontier atomically.
pub async fn read_rate_issue(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
    Json(request): Json<IssueReadRateRequest>,
) -> Result<Json<IssueReadRateResponse>, ApiError> {
    issue_service::validate(&request)?;
    let mut pending = Pending::new(db::checkout(&state).await?);
    let result = {
        let tx = pending.connection()
            .build_transaction()
            .isolation_level(IsolationLevel::ReadCommitted)
            .start()
            .await
            .map_err(db::query_error)?;
        let receipt = issue_service::persist(&tx, user, issue_id, &request).await?;
        tx.commit().await.map_err(db::query_error)?;
        receipt
    };
    pending.release();
    Ok(Json(result))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{config::Config, router};
    use axum::{body::Body, http::{Request, StatusCode}};
    use tower::ServiceExt;

    #[tokio::test]
    async fn issue_patch_checks_authentication_without_database_config_access() {
        let config = Config::from_lookup(|name| match name {
            "RUST_ROLL_DATABASE_URL" => Some("postgresql://localhost/unused".into()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-secret".into()),
            _ => None,
        }).unwrap();
        let app = router(Arc::new(AppState::new(config).unwrap()));
        let response = app.oneshot(
            Request::builder()
                .method("PATCH")
                .uri("/api/v2/issues/42")
                .header("content-type", "application/json")
                .body(Body::from(r#"{"status":"read","idempotency_key":"test-issue-012345"}"#))
                .unwrap()
        ).await.unwrap();
        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    }
}
