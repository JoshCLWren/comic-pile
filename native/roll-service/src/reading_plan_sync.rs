//! Same-path Rust cutover for browser-called reading-plan-sync operations
//! (#4851, parent #4335).
//!
//! Preserves the Python `app/api/reading_plan_sync.py` wire contract at the
//! same HTTP method and exact path:
//!
//! * `GET /api/v1/reading-plan-sync/status`
//! * `POST /api/v1/reading-plan-sync/sync` (in progress; not yet routed to
//!   native until parity is complete)
//!
//! Status is a direct read of persisted release-source state. The sync POST
//! must mirror the user-triggered `sync_released_issues` behavior: evaluate
//! only the authenticated user's enabled sources, adopt released ComicVine
//! issues, and preserve Python wire/auth/ownership/SQL/transaction semantics.

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{extract::State, Json};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::Arc;

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct SyncRequest {
    #[schema(value_type = String, format = "date-time")]
    pub as_of: String,
    #[serde(default = "default_refresh")]
    pub refresh: bool,
}

fn default_refresh() -> bool {
    true
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SourceSyncFailure {
    pub source_id: i32,
    pub plan_id: i32,
    pub thread_id: i32,
    pub volume_id: i32,
    pub error: String,
}

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
    #[serde(default)]
    pub excluded_sources: i64,
    #[serde(default)]
    pub excluded_issues: i64,
    #[serde(default)]
    pub skipped_sources: i64,
    pub failures: Vec<SourceSyncFailure>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SyncResponse {
    pub success: bool,
    pub message: String,
    pub result: SyncReport,
}

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

fn report_message(report: &SyncReport) -> String {
    format!(
        "Sync completed: {} successful, {} failed, {} created, {} reused, {} sources and {} issues excluded",
        report.successful_sources,
        report.failed_sources,
        report.created_issues,
        report.reused_issues,
        report.excluded_sources,
        report.excluded_issues
    )
}

fn parse_as_of(value: &str) -> Result<DateTime<Utc>, ApiError> {
    if let Ok(dt) = DateTime::parse_from_rfc3339(value) {
        return Ok(dt.with_timezone(&Utc));
    }
    if let Ok(naive) = chrono::NaiveDateTime::parse_from_str(value, "%Y-%m-%dT%H:%M:%S%.f") {
        return Ok(DateTime::<Utc>::from_naive_utc_and_offset(naive, Utc));
    }
    if let Ok(naive) = chrono::NaiveDateTime::parse_from_str(value, "%Y-%m-%dT%H:%M:%S") {
        return Ok(DateTime::<Utc>::from_naive_utc_and_offset(naive, Utc));
    }
    if let Ok(naive) = chrono::NaiveDateTime::parse_from_str(value, "%Y-%m-%d %H:%M:%S%.f") {
        return Ok(DateTime::<Utc>::from_naive_utc_and_offset(naive, Utc));
    }
    if let Ok(naive) = chrono::NaiveDateTime::parse_from_str(value, "%Y-%m-%d %H:%M:%S") {
        return Ok(DateTime::<Utc>::from_naive_utc_and_offset(naive, Utc));
    }
    Err(ApiError::Unprocessable(
        "as_of must be a valid datetime".to_string(),
    ))
}

#[allow(dead_code)]
fn parse_store_date(value: Option<&Value>) -> Option<DateTime<Utc>> {
    let value = value?;
    if value.is_null() {
        return None;
    }
    let text = value.as_str()?.trim();
    if text.is_empty() {
        return None;
    }
    let normalized = if text.ends_with(['Z', 'z']) {
        format!("{}+00:00", &text[..text.len() - 1])
    } else {
        text.to_string()
    };
    if let Ok(dt) = DateTime::parse_from_rfc3339(&normalized) {
        return Some(dt.with_timezone(&Utc));
    }
    if normalized.len() == 10
        && normalized.chars().nth(4) == Some('-')
        && normalized.chars().nth(7) == Some('-')
    {
        if let Ok(date) = chrono::NaiveDate::parse_from_str(&normalized, "%Y-%m-%d") {
            return date
                .and_hms_opt(0, 0, 0)
                .map(|naive| DateTime::<Utc>::from_naive_utc_and_offset(naive, Utc));
        }
    }
    None
}

#[derive(Debug, Clone)]
#[allow(dead_code)]
struct EnabledSourceRow {
    source_id: i32,
    plan_id: i32,
    thread_id: i32,
    external_identity_id: i32,
    provider_volume_id: String,
}

fn parse_volume_id(raw: &str, source_id: i32) -> Result<i32, String> {
    let trimmed = raw.trim();
    let numeric = if trimmed.chars().all(|c| c.is_ascii_digit()) {
        trimmed
    } else if trimmed.contains('-') && trimmed.rsplit('-').next().is_some_and(|s| !s.is_empty()) {
        trimmed.rsplit('-').next().unwrap_or(trimmed)
    } else {
        trimmed
    };
    numeric.parse::<i32>().map_err(|_| {
        format!("Release source {source_id} has a non-numeric ComicVine volume id: {raw:?}")
    })
}

pub async fn sync_released_issues_endpoint(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(payload): Json<SyncRequest>,
) -> Result<Json<SyncResponse>, ApiError> {
    let as_of = parse_as_of(&payload.as_of)?;
    let _refresh = payload.refresh;
    let connection = db::checkout(&state).await?;

    let all_rows = connection
        .query(
            "SELECT rps.id, rps.plan_id, rps.thread_id, rps.external_identity_id, ei.external_id, rps.enabled \
             FROM reading_plan_release_sources rps \
             JOIN continuity_plans cp ON cp.id = rps.plan_id \
             JOIN external_identities ei ON ei.id = rps.external_identity_id \
             WHERE cp.user_id = $1 \
             ORDER BY rps.created_at",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let total_sources = all_rows.len() as i64;

    let mut enabled_rows = Vec::new();
    for row in &all_rows {
        let enabled: bool = row.get(5);
        if enabled {
            enabled_rows.push(EnabledSourceRow {
                source_id: row.get(0),
                plan_id: row.get(1),
                thread_id: row.get(2),
                external_identity_id: row.get(3),
                provider_volume_id: row.get(4),
            });
        }
    }
    let enabled_sources = enabled_rows.len() as i64;

    if enabled_sources == 0 {
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
        return Ok(Json(SyncResponse {
            success: report.failed_sources == 0 && report.issue_failures == 0,
            message: report_message(&report),
            result: report,
        }));
    }

    // Match Python: missing API key fails all enabled sources with the
    // client-construction error message.
    let api_key = std::env::var("COMICVINE_API_KEY")
        .ok()
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty());
    if api_key.is_none() {
        let error = "COMICVINE_API_KEY is required".to_string();
        let mut failures = Vec::with_capacity(enabled_rows.len());
        for source in &enabled_rows {
            let volume_id = parse_volume_id(&source.provider_volume_id, source.source_id)
                .unwrap_or(-1);
            failures.push(SourceSyncFailure {
                source_id: source.source_id,
                plan_id: source.plan_id,
                thread_id: source.thread_id,
                volume_id,
                error: error.clone(),
            });
        }
        let report = SyncReport {
            total_sources,
            enabled_sources,
            checked_sources: 0,
            successful_sources: 0,
            failed_sources: enabled_sources,
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
            failures,
        };
        return Ok(Json(SyncResponse {
            success: false,
            message: report_message(&report),
            result: report,
        }));
    }

    let _ = as_of;
    Err(ApiError::ServiceUnavailable(
        "reading-plan-sync POST native implementation in progress".to_string(),
    ))
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
