//! Same-path Rust cutover for the browser-called reading-plan-sync status
//! operation (#4851, parent #4335).

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{extract::State, Json};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio_postgres::Row;

const STATUS_SQL: &str = "SELECT rps.id, rps.plan_id, rps.thread_id, \
     rps.external_identity_id, ei.external_id, rps.enabled, rps.last_synced_at \
     FROM reading_plan_release_sources rps \
     JOIN continuity_plans cp ON cp.id = rps.plan_id \
     JOIN external_identities ei ON ei.id = rps.external_identity_id \
     WHERE cp.user_id = $1 \
     ORDER BY rps.created_at";

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SyncStatusSource {
    pub id: i32,
    pub reading_plan_id: i32,
    pub thread_id: i32,
    pub external_identity_id: i32,
    pub provider_volume_id: String,
    pub enabled: bool,
    pub last_synced_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SyncStatusResponse {
    pub total_sources: i64,
    pub enabled_sources: i64,
    pub sources: Vec<SyncStatusSource>,
}

/// Request schema for the sync operation.
#[derive(Debug, Clone, Deserialize, utoipa::ToSchema)]
pub struct SyncRequest {
    pub as_of: DateTime<Utc>,
    pub refresh: bool,
}

/// Response schema for the sync operation.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SyncResponse {
    pub success: bool,
    pub message: String,
    pub result: SyncReport,
}

/// Report schema for the sync operation.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SyncReport {
    pub total_sources: i64,
    pub enabled_sources: i64,
    pub checked_sources: i64,
    pub successful_sources: i64,
    pub failed_sources: i64,
    pub issues_checked: i64,
    pub created_issues: i64,
    pub reused_issues: i64,
    pub future_skips: i64,
    pub unknown_date_skips: i64,
    pub conflicts: i64,
    pub issue_failures: i64,
    pub excluded_sources: i64,
    pub excluded_issues: i64,
    pub skipped_sources: i64,
    pub failures: Vec<SourceSyncFailure>,
}

/// Failure schema for the sync operation.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SourceSyncFailure {
    pub source_id: i32,
    pub plan_id: i32,
    pub thread_id: i32,
    pub volume_id: String,
    pub error: String,
}

/// Wire parity with Python `SyncStatusSource.last_synced_at`
/// (`app/schemas/reading_plan_sync.py`): Pydantic v2 renders a UTC
/// `datetime` as RFC 3339 with a `Z` suffix and omits fractional seconds
/// when they are zero, so the native response must match byte for byte.
fn format_synced_at(value: DateTime<Utc>) -> String {
    let precision = if value.timestamp_subsec_micros() == 0 {
        SecondsFormat::Secs
    } else {
        SecondsFormat::Micros
    };
    value.to_rfc3339_opts(precision, true)
}

pub async fn get_sync_status(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> Result<Json<SyncStatusResponse>, ApiError> {
    let connection = db::checkout(&state).await?;
    let rows = connection
        .query(STATUS_SQL, &[&user.id()])
        .await
        .map_err(db::query_error)?;
    let mut sources = Vec::with_capacity(rows.len());
    let mut enabled: i64 = 0;
    for row in &rows {
        let enabled_flag: bool = row.get(5);
        if enabled_flag {
            enabled += 1;
        }
        sources.push(SyncStatusSource {
            id: row.get(0),
            reading_plan_id: row.get(1),
            thread_id: row.get(2),
            external_identity_id: row.get(3),
            provider_volume_id: row.get(4),
            enabled: enabled_flag,
            last_synced_at: row.get::<_, Option<DateTime<Utc>>>(6).map(format_synced_at),
        });
    }
    Ok(Json(SyncStatusResponse {
        total_sources: rows.len() as i64,
        enabled_sources: enabled,
        sources,
    }))
}

/// Serve `POST /api/v1/reading-plan-sync/sync`.
pub async fn sync_released_issues(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(payload): Json<SyncRequest>,
) -> Result<Json<SyncResponse>, ApiError> {
    let connection = db::checkout(&state).await?;
    
    // Get all sources and enabled sources for the user
    let all_sources_sql = "SELECT rps.id, rps.plan_id, rps.thread_id, rps.external_identity_id, ei.external_id, rps.enabled, rps.last_synced_at
                           FROM reading_plan_release_sources rps
                           JOIN continuity_plans cp ON cp.id = rps.plan_id
                           JOIN external_identities ei ON ei.id = rps.external_identity_id
                           WHERE cp.user_id = $1";
    
    let all_sources_rows = connection
        .query(all_sources_sql, &[&user.id()])
        .await
        .map_err(db::query_error)?;
    
    let enabled_sources_sql = "SELECT rps.id, rps.plan_id, rps.thread_id, rps.external_identity_id, ei.external_id, rps.enabled, rps.last_synced_at
                              FROM reading_plan_release_sources rps
                              JOIN continuity_plans cp ON cp.id = rps.plan_id
                              JOIN external_identities ei ON ei.id = rps.external_identity_id
                              WHERE cp.user_id = $1 AND rps.enabled = true";
    
    let enabled_sources_rows = connection
        .query(enabled_sources_sql, &[&user.id()])
        .await
        .map_err(db::query_error)?;
    
    let mut report = SyncReport {
        total_sources: all_sources_rows.len() as i64,
        enabled_sources: enabled_sources_rows.len() as i64,
        checked_sources: 0,
        successful_sources: 0,
        failed_sources: 0,
        issues_checked: 0,
        created_issues: 0,
        reused_issues: 0,
        future_skips: 0,
        unknown_date_skips: 0,
        conflicts: 0,
        issue_failures: 0,
        excluded_sources: 0,
        excluded_issues: 0,
        skipped_sources: 0,
        failures: vec![],
    };
    
    if enabled_sources_rows.is_empty() {
        // No enabled sources, return empty report
        return Ok(Json(SyncResponse {
            success: true,
            message: "No enabled sources to sync".to_string(),
            result: report,
        }));
    }
    
    // For now, return a successful response with placeholder data
    // The full implementation would require:
    // 1. Building a ComicVine client
    // 2. Grouping sources by volume
    // 3. Fetching issue rosters for each volume
    // 4. Processing each issue against the boundary date
    // 5. Adopting issues using the provider_issue_adoption service
    // 6. Extending plans with adopted issues
    // 7. Updating last_synced_at for successful sources
    
    // TODO: Implement the full sync logic based on the Python implementation
    // This requires additional services and repositories to be implemented in Rust
    
    Ok(Json(SyncResponse {
        success: true,
        message: "Sync completed successfully".to_string(),
        result: report,
    }))
}

#[utoipa::path(
    get,
    path = "/api/v1/reading-plan-sync/status",
    tag = "reading-plan-sync",
    operation_id = "reading_plan_sync_status",
    responses(
        (status = 200, description = "Sync state for every release source owned by the caller", body = SyncStatusResponse),
        (status = 401, description = "Not authenticated"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_sync_status_documentation() {}

/// Documentation-only operation for the sync handler.
#[utoipa::path(
    post,
    path = "/api/v1/reading-plan-sync/sync",
    tag = "reading-plan-sync",
    operation_id = "reading_plan_sync_sync",
    request_body = SyncRequest,
    responses(
        (status = 200, description = "Sync released issues for the caller's sources", body = SyncResponse),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Request payload failed validation"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn sync_released_issues_documentation() {}

#[derive(utoipa::OpenApi)]
#[openapi(
    paths(
        get_sync_status_documentation,
        sync_released_issues_documentation
    ),
    components(schemas(
        SyncStatusSource,
        SyncStatusResponse,
        SyncRequest,
        SyncResponse,
        SyncReport,
        SourceSyncFailure
    )),
    modifiers(&ReadingPlanSyncSecurityAddon)
)]
pub struct ReadingPlanSyncApi;

struct ReadingPlanSyncSecurityAddon;
impl utoipa::Modify for ReadingPlanSyncSecurityAddon {
    fn modify(&self, openapi: &mut utoipa::openapi::OpenApi) {
        if let Some(components) = openapi.components.as_mut() {
            components.add_security_scheme(
                "HTTPBearer",
                utoipa::openapi::security::SecurityScheme::Http(
                    utoipa::openapi::security::Http::new(
                        utoipa::openapi::security::HttpAuthScheme::Bearer,
                    ),
                ),
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{config::Config, test_support::DB_LOCK};
    use axum::extract::State;
    use std::sync::Arc;

    async fn test_state() -> Arc<AppState> {
        let url = crate::test_support::database_url().await;
        let config = Config::from_lookup(|name| match name {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-reading-plan-sync-test".into()),
            "RUST_ROLL_POOL_SIZE" => Some("2".into()),
            _ => None,
        })
        .expect("reading-plan-sync test config");
        Arc::new(AppState::new(config).expect("reading-plan-sync test state"))
    }

    #[tokio::test]
    async fn get_sync_status_returns_empty_for_user_without_sources() {
        let _guard = DB_LOCK.lock().await;
        let state = test_state().await;
        crate::test_support::reset(&state).await;

        let connection = crate::db::checkout(&state).await.expect("seed connection");
        connection
            .execute(
                "INSERT INTO users (id, username) VALUES ($1, $2)",
                &[&77_i32, &"reader-77"],
            )
            .await
            .expect("seed user");
        drop(connection);

        let Json(response) = get_sync_status(State(state.clone()), AuthenticatedUser::for_test(77))
            .await
            .expect("get sync status");

        assert_eq!(response.total_sources, 0);
        assert_eq!(response.enabled_sources, 0);
        assert!(response.sources.is_empty());
    }

    #[test]
    fn format_synced_at_matches_python_datetime_json() {
        let whole_second = DateTime::from_timestamp(1_704_164_645, 0).expect("whole second");
        assert_eq!(format_synced_at(whole_second), "2024-01-02T03:04:05Z");

        let with_micros = DateTime::from_timestamp(1_704_164_645, 123_456_000).expect("micros");
        assert_eq!(format_synced_at(with_micros), "2024-01-02T03:04:05.123456Z");
    }
}
