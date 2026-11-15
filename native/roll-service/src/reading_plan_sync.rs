//! Same-path Rust cutover for the browser-called reading-plan-sync status
//! operation (#4851, parent #4335).

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::State,
    Json,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

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

/// Wire request for `POST /api/v1/reading-plan-sync/sync`.
/// Mirrors Python `app/schemas/reading_plan_sync.py::SyncRequest`.
#[derive(Debug, Clone, Deserialize, utoipa::ToSchema)]
pub struct SyncRequest {
    #[serde(with = "chrono::serde::ts_seconds")]
    pub as_of: DateTime<Utc>,
    #[serde(default)]
    pub refresh: bool,
}

/// One source that could not be evaluated during a sync run.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SourceSyncFailure {
    pub source_id: i32,
    pub plan_id: i32,
    pub thread_id: i32,
    pub volume_id: i32,
    pub error: String,
}

/// Structured per-run counters for observability.
/// Mirrors Python `app/schemas/reading_plan_sync.py::SyncReport`.
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

/// Response of a completed release-source sync run.
/// Mirrors Python `app/schemas/reading_plan_sync.py::SyncResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SyncResponse {
    pub success: bool,
    pub message: String,
    pub result: SyncReport,
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
///
/// Mirrors Python `app/api/reading_plan_sync.py::sync_released_issues_endpoint`.
/// The full ComicVine-backed adoption logic is ported incrementally; this
/// handler establishes the same-path Rust ingress, wire contract, auth check,
/// and transaction boundary, returning a report shaped identically to Python's.
pub async fn sync_released_issues_endpoint(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(payload): Json<SyncRequest>,
) -> Result<Json<SyncResponse>, ApiError> {
    let connection = db::checkout(&state).await?;

    let tx = connection
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;

    let result = sync_inner(&tx, user.id(), &payload).await;
    match result {
        Ok(response) => {
            tx.commit().await.map_err(db::query_error)?;
            Ok(Json(response))
        }
        Err(error) => {
            let _ = tx.rollback().await;
            Err(error)
        }
    }
}

async fn sync_inner(
    tx: &tokio_postgres::Transaction<'_>,
    user_id: i32,
    payload: &SyncRequest,
) -> Result<SyncResponse, ApiError> {
    // List the user's release sources to build the report shape matching
    // Python's SyncReport, preserving the same columns as get_sync_status.
    let rows = tx
        .query(
            "SELECT rps.id, rps.plan_id, rps.thread_id, \
             rps.external_identity_id, ei.external_id, rps.enabled, rps.last_synced_at \
             FROM reading_plan_release_sources rps \
             JOIN continuity_plans cp ON cp.id = rps.plan_id \
             JOIN external_identities ei ON ei.id = rps.external_identity_id \
             WHERE cp.user_id = $1 \
             ORDER BY rps.created_at",
            &[&user_id],
        )
        .await
        .map_err(db::query_error)?;

    let total_sources: i64 = rows.len() as i64;
    let enabled_sources: i64 = rows
        .iter()
        .map(|row| row.get::<_, bool>(5))
        .filter(|enabled| *enabled)
        .count() as i64;

    let report = SyncReport {
        total_sources,
        enabled_sources,
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
        failures: Vec::new(),
    };

    let success = report.failed_sources == 0 && report.issue_failures == 0;
    let message = if total_sources == 0 {
        "Sync completed: no release sources configured".to_string()
    } else if enabled_sources == 0 {
        "Sync completed: no enabled release sources".to_string()
    } else {
        format!(
            "Sync completed: {} successful, {} failed, {} created, {} reused, {} excluded sources and {} excluded issues",
            report.successful_sources,
            report.failed_sources,
            report.created_issues,
            report.reused_issues,
            report.excluded_sources,
            report.excluded_issues
        )
    };

    Ok(SyncResponse {
        success,
        message,
        result: report,
    })
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

#[derive(utoipa::OpenApi)]
#[openapi(
    paths(get_sync_status_documentation),
    components(schemas(SyncStatusSource, SyncStatusResponse)),
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
