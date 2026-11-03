//! Owner-scoped, bounded analytics metrics resource.
//!
//! `GET /api/v2/analytics/metrics` is the native replacement for Python's
//! `GET /api/v1/analytics/metrics` and bare `/api/analytics/metrics` alias.
//! The legacy routes remain mounted until this resource is deployed and
//! authenticated production verification permits their cleanup.
//! The response preserves the real metrics surface: thread counts, completion
//! rate, average ended-session duration, the five newest sessions inside a
//! seven-day window, event-type counts and the five highest-rated threads at or
//! above 4.0.
//!
//! Authentication, token-revocation state, the credential epoch and every
//! metric projection are folded into one owner-scoped PostgreSQL statement.
//! The response is bounded by the fixed recent/top limits and the finite set of
//! event types; there is no whole-history JSON snapshot and no per-row N+1.

use crate::{auth::VerifiedAccessClaims, db, ApiError, AppState};
use axum::{extract::State, http::StatusCode, Json};
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc,
    },
};

/// Metrics statements issued by this module, so parity tests can prove the
/// complete request (including authentication) is one issued statement.
pub static METRICS_STATEMENTS_ISSUED: AtomicU64 = AtomicU64::new(0);

const RECENT_SESSION_LIMIT: i64 = 5;
const RECENT_SESSION_WINDOW_DAYS: i64 = 7;
const TOP_THREAD_LIMIT: i64 = 5;
const TOP_RATING_THRESHOLD: f64 = 4.0;

/// Summary of one recent reading session.
#[derive(Debug, Clone, Deserialize, Serialize, utoipa::ToSchema)]
pub struct RecentSession {
    pub id: i32,
    pub started_at: String,
    pub ended_at: Option<String>,
    pub start_die: i32,
}

/// Summary of one highly rated thread.
#[derive(Debug, Clone, Deserialize, Serialize, utoipa::ToSchema)]
pub struct TopRatedThread {
    pub id: i32,
    pub title: String,
    pub rating: f64,
    pub format: String,
}

/// Reading metrics and analytics for the authenticated user.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct AnalyticsMetricsResponse {
    pub total_threads: i32,
    pub active_threads: i32,
    pub completed_threads: i32,
    pub completion_rate: f64,
    pub average_session_hours: f64,
    pub recent_sessions: Vec<RecentSession>,
    pub event_stats: BTreeMap<String, i32>,
    pub top_rated_threads: Vec<TopRatedThread>,
}

#[derive(Debug, Deserialize)]
struct AuthRow {
    password_epoch: i64,
    revoked: bool,
}

#[derive(Debug, Deserialize)]
struct EventCount {
    #[serde(rename = "type")]
    event_type: String,
    count: i32,
}

#[derive(Debug, Deserialize)]
struct MetricsPayload {
    auth: Option<AuthRow>,
    total_threads: i32,
    active_threads: i32,
    completed_threads: i32,
    average_session_hours: Option<f64>,
    recent_sessions: Vec<RecentSession>,
    event_stats: Vec<EventCount>,
    top_rated_threads: Vec<TopRatedThread>,
}

fn internal_error() -> ApiError {
    ApiError(
        StatusCode::INTERNAL_SERVER_ERROR,
        "Internal Server Error".to_string(),
    )
}

/// Validate the revocation/credential-epoch fields folded into the metrics
/// statement. The order matches Python's `authenticate_claims`: missing user,
/// revoked token, then stale password epoch.
fn validate_auth(claims: &VerifiedAccessClaims, auth: &Option<AuthRow>) -> Result<(), ApiError> {
    let auth = auth
        .as_ref()
        .ok_or_else(|| ApiError(StatusCode::UNAUTHORIZED, "User not found".to_string()))?;
    if auth.revoked {
        return Err(ApiError(
            StatusCode::UNAUTHORIZED,
            "Token has been revoked".to_string(),
        ));
    }
    if claims.expected_epoch()? < auth.password_epoch {
        return Err(ApiError(
            StatusCode::UNAUTHORIZED,
            "Password changed; please sign in again.".to_string(),
        ));
    }
    Ok(())
}

/// Python-compatible one-decimal rounding (`round(value, 1)`).
fn round_one_decimal(value: f64) -> f64 {
    format!("{value:.1}").parse().unwrap_or(value)
}

/// Preserve the legacy completion-rate formula and zero denominator fallback.
fn completion_rate(completed_threads: i32, total_threads: i32) -> f64 {
    if total_threads > 0 {
        round_one_decimal(completed_threads as f64 / total_threads as f64 * 100.0)
    } else {
        0.0
    }
}

/// Canonicalize a thread format exactly like `normalize_format_value`.
fn normalize_format_value(value: &str) -> String {
    let stripped = value.trim();
    match stripped.to_lowercase().as_str() {
        "comic" | "comics" => "Comic".to_string(),
        "digital" => "Digital".to_string(),
        _ => stripped.to_string(),
    }
}

/// Python `datetime.isoformat()` uses `+00:00`, omits a zero microsecond
/// fraction and keeps six digits otherwise. The analytics wire contract keeps
/// that historical spelling rather than the newer `Z` spelling used by other
/// v2 resources.
fn iso_timestamp(column: &str) -> String {
    format!(
        "CASE WHEN {column} IS NULL THEN NULL \
         WHEN date_trunc('second', {column}) = {column} \
         THEN to_char({column} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"+00:00\"') \
         ELSE to_char({column} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"+00:00\"') END"
    )
}

const METRICS_SQL: &str = r#"
WITH auth AS (
    SELECT u.id AS user_id,
           COALESCE(trunc(extract(epoch FROM u.password_changed_at))::bigint, 0)
               AS password_epoch,
           EXISTS(
               SELECT 1 FROM revoked_tokens r WHERE r.jti = $2
           ) AS revoked
    FROM users u
    WHERE u.username = $1
    LIMIT 1
),
me AS (
    SELECT user_id
    FROM auth
    WHERE NOT revoked AND password_epoch <= $3
),
thread_counts AS (
    SELECT count(*)::int AS total_threads,
           count(*) FILTER (WHERE t.status = 'active')::int AS active_threads,
           count(*) FILTER (WHERE t.status = 'completed')::int AS completed_threads
    FROM threads t
    JOIN me ON t.user_id = me.user_id
),
session_stats AS (
    SELECT avg(
               extract(epoch FROM s.ended_at - s.started_at) / 3600.0
           ) AS average_session_hours
    FROM sessions s
    JOIN me ON s.user_id = me.user_id
    WHERE s.ended_at IS NOT NULL
),
recent_sessions AS (
    SELECT COALESCE(
               json_agg(
                   json_build_object(
                       'id', r.id,
                       'started_at', r.started_at_text,
                       'ended_at', r.ended_at_text,
                       'start_die', r.start_die
                   )
                   ORDER BY r.started_at DESC
               ),
               '[]'::json
           ) AS items
    FROM (
        SELECT s.id, s.started_at, s.start_die,
               {STARTED_AT} AS started_at_text,
               {ENDED_AT} AS ended_at_text
        FROM sessions s
        JOIN me ON s.user_id = me.user_id
        WHERE s.started_at >= to_timestamp($4::double precision)
        ORDER BY s.started_at DESC
        LIMIT {RECENT_LIMIT}
    ) r
),
event_type_counts AS (
    SELECT COALESCE(
               json_agg(
                   json_build_object('type', e.event_type, 'count', e.event_count)
                   ORDER BY e.event_type
               ),
               '[]'::json
           ) AS items
    FROM (
        SELECT ev.type AS event_type, count(*)::int AS event_count
        FROM events ev
        JOIN sessions s ON s.id = ev.session_id
        JOIN me ON s.user_id = me.user_id
        GROUP BY ev.type
    ) e
),
top_rated_threads AS (
    SELECT COALESCE(
               json_agg(
                   json_build_object(
                       'id', t.id,
                       'title', t.title,
                       'rating', t.last_rating,
                       'format', t.format
                   )
                   ORDER BY t.last_rating DESC
               ),
               '[]'::json
           ) AS items
    FROM (
        SELECT t.id, t.title, t.last_rating, t.format
        FROM threads t
        JOIN me ON t.user_id = me.user_id
        WHERE t.last_rating IS NOT NULL
          AND t.last_rating >= $5::double precision
        ORDER BY t.last_rating DESC
        LIMIT {TOP_LIMIT}
    ) t
)
SELECT json_build_object(
    'auth', (
        SELECT json_build_object(
            'password_epoch', password_epoch,
            'revoked', revoked
        )
        FROM auth
    ),
    'total_threads', (SELECT total_threads FROM thread_counts),
    'active_threads', (SELECT active_threads FROM thread_counts),
    'completed_threads', (SELECT completed_threads FROM thread_counts),
    'average_session_hours', (SELECT average_session_hours FROM session_stats),
    'recent_sessions', (SELECT items FROM recent_sessions),
    'event_stats', (SELECT items FROM event_type_counts),
    'top_rated_threads', (SELECT items FROM top_rated_threads)
)::text
"#;

fn metrics_sql() -> String {
    METRICS_SQL
        .replace("{STARTED_AT}", &iso_timestamp("s.started_at"))
        .replace("{ENDED_AT}", &iso_timestamp("s.ended_at"))
        .replace("{RECENT_LIMIT}", &RECENT_SESSION_LIMIT.to_string())
        .replace("{TOP_LIMIT}", &TOP_THREAD_LIMIT.to_string())
}

/// Return the authenticated reader's bounded analytics metrics.
pub async fn metrics(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
) -> Result<Json<AnalyticsMetricsResponse>, ApiError> {
    // Keep Python's error precedence: a missing user or revoked token is
    // reported before a malformed credential epoch. A malformed/overflowing
    // epoch cannot match `me`, and `validate_auth` re-evaluates it after the
    // one statement to return the legacy 500 when the owner is otherwise valid.
    let expected_epoch = claims.expected_epoch().unwrap_or(i64::MAX);
    let username = claims.username().to_string();
    let jti = claims.jti().to_string();
    let window_start = chrono::Utc::now() - chrono::Duration::days(RECENT_SESSION_WINDOW_DAYS);
    let window_start_seconds = window_start.timestamp_micros() as f64 / 1_000_000.0;
    let threshold = TOP_RATING_THRESHOLD;
    let params: [&(dyn tokio_postgres::types::ToSql + Sync); 5] = [
        &username,
        &jti,
        &expected_epoch,
        &window_start_seconds,
        &threshold,
    ];

    let connection = db::checkout(&state).await?;
    METRICS_STATEMENTS_ISSUED.fetch_add(1, Ordering::Relaxed);
    let row = db::query_one_optional(&state, connection, &metrics_sql(), &params)
        .await?
        .ok_or_else(internal_error)?;
    let payload_text: String = row.try_get(0).map_err(db::query_error)?;
    let payload: MetricsPayload =
        serde_json::from_str(&payload_text).map_err(|_| internal_error())?;

    validate_auth(&claims, &payload.auth)?;

    let top_rated_threads = payload
        .top_rated_threads
        .into_iter()
        .map(|mut thread| {
            thread.format = normalize_format_value(&thread.format);
            thread
        })
        .collect();
    let event_stats = payload
        .event_stats
        .into_iter()
        .map(|event| (event.event_type, event.count))
        .collect();

    Ok(Json(AnalyticsMetricsResponse {
        total_threads: payload.total_threads,
        active_threads: payload.active_threads,
        completed_threads: payload.completed_threads,
        completion_rate: completion_rate(payload.completed_threads, payload.total_threads),
        average_session_hours: round_one_decimal(payload.average_session_hours.unwrap_or(0.0)),
        recent_sessions: payload.recent_sessions,
        event_stats,
        top_rated_threads,
    }))
}

/// OpenAPI document for the v2 analytics metrics resource.
#[derive(utoipa::OpenApi)]
#[openapi(
    paths(metrics_documentation),
    components(schemas(RecentSession, TopRatedThread, AnalyticsMetricsResponse)),
    modifiers(&AnalyticsSecurityAddon)
)]
pub struct AnalyticsApi;

struct AnalyticsSecurityAddon;
impl utoipa::Modify for AnalyticsSecurityAddon {
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

/// Documentation-only operation used by the canonical Rust OpenAPI generator.
#[utoipa::path(
    get,
    path = "/api/v2/analytics/metrics",
    tag = "analytics",
    responses(
        (status = 200, description = "Owner-scoped bounded reading metrics", body = AnalyticsMetricsResponse),
        (status = 401, description = "Not authenticated, revoked token, or stale credential epoch")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
fn metrics_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use utoipa::OpenApi;

    #[test]
    fn completion_rate_preserves_legacy_rounding_and_zero_fallback() {
        assert_eq!(completion_rate(0, 0), 0.0);
        assert_eq!(completion_rate(1, 5), 20.0);
        assert_eq!(completion_rate(1, 6), 16.7);
        assert_eq!(completion_rate(6, 6), 100.0);
    }

    #[test]
    fn format_normalization_matches_the_legacy_helper() {
        assert_eq!(normalize_format_value("comics"), "Comic");
        assert_eq!(normalize_format_value("  Comic  "), "Comic");
        assert_eq!(normalize_format_value("digital"), "Digital");
        assert_eq!(normalize_format_value(" Manga "), "Manga");
    }

    #[test]
    fn metrics_statement_template_is_fully_rendered() {
        let sql = metrics_sql();
        assert!(!sql.contains('{'));
        assert!(sql.contains("LIMIT 5"));
        assert!(sql.contains("+00:00"));
        assert!(sql.contains("revoked_tokens"));
    }

    #[test]
    fn analytics_openapi_describes_the_bounded_v2_resource() {
        let openapi = AnalyticsApi::openapi();
        let operation = openapi
            .paths
            .paths
            .get("/api/v2/analytics/metrics")
            .and_then(|path| path.get.as_ref())
            .expect("analytics metrics operation");
        assert_eq!(operation.tags, Some(vec!["analytics".to_string()]));
        let schemas = &openapi
            .components
            .as_ref()
            .expect("component schemas")
            .schemas;
        assert!(schemas.contains_key("AnalyticsMetricsResponse"));
        assert!(schemas.contains_key("RecentSession"));
        assert!(schemas.contains_key("TopRatedThread"));
    }
}
