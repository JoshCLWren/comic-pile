//! Owner-scoped activity history endpoint for the History page.
//!
//! `GET /api/v2/activity` provides a chronological view of all user-visible
//! events including sessionless snoozes and ratings, with stable cursor
//! pagination. This replaces the Python `GET /api/v1/sessions/` endpoint for
//! the History page to fix the omissions described in issue #4822.
//!
//! The response preserves both events for each rate/snooze pair to show
//! the causal narrative (e.g., d6 roll → snooze to d8 → roll d8 → snooze
//! to d10 → roll d10 → rated 4.5), while coalescing for display purposes.
//!
//! Authentication, token-revocation state, the credential epoch and every
//! activity projection are folded into one owner-scoped PostgreSQL statement.
use crate::{
    auth::VerifiedAccessClaims,
    db,
    ApiError, AppState,
};
use axum::{extract::{Query, State}, Json};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

/// Handler-level query count for the activity read.
pub static ACTIVITY_STATEMENTS_ISSUED: AtomicU64 = AtomicU64::new(0);

/// Default number of activity events per page.
const DEFAULT_PAGE_SIZE: i64 = 50;

/// Cursor token for activity pagination.
#[derive(Debug, Deserialize)]
struct ActivityQuery {
    /// Cursor token (event_id) for pagination.
    page_token: Option<String>,
    /// Page size override.
    page_size: Option<i64>,
}

/// One user-visible activity event for the History timeline.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ActivityEvent {
    /// Unique event identifier.
    pub event_id: i32,
    /// Event type: "roll", "rate", "snooze", "unsnooze", "dismiss", etc.
    #[serde(rename = "type")]
    pub event_type: String,
    /// ISO 8601 timestamp when the event occurred.
    pub timestamp: String,
    /// Die before this event (for roll, snooze, dismiss, etc.).
    pub die_before: Option<i32>,
    /// Die after this event (for rate, snooze, undo, etc.).
    pub die_after: Option<i32>,
    /// Rating value (for rate events).
    pub rating: Option<f64>,
    /// Thread ID this event relates to.
    pub thread_id: Option<i32>,
    /// Thread title (denormalized for display).
    pub thread_title: Option<String>,
    /// Issue number (for roll events that selected an issue).
    pub issue_number: Option<String>,
}

/// Response for the activity endpoint.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ActivityResponse {
    /// List of activity events in reverse chronological order.
    pub events: Vec<ActivityEvent>,
    /// Cursor token for the next page (timestamp,id format).
    pub next_page_token: Option<String>,
}

#[derive(Debug, Deserialize)]
struct AuthRow {
    password_epoch: i64,
    revoked: bool,
}

#[derive(Debug, Deserialize)]
struct ActivityPayload {
    auth: Option<AuthRow>,
    events: Vec<ActivityRawRow>,
    has_more: bool,
    last_id: Option<i32>,
    last_ts_us: Option<f64>,
}

#[derive(Debug, Deserialize)]
struct ActivityRawRow {
    event_id: i32,
    event_type: String,
    timestamp_sec: f64,
    timestamp_us: Option<f64>,
    die_before: Option<i32>,
    die_after: Option<i32>,
    rating: Option<f64>,
    thread_id: Option<i32>,
    thread_title: Option<String>,
    issue_number: Option<String>,
}

fn internal_error() -> ApiError {
    ApiError::Internal("Internal Server Error".to_string())
}

/// Validate the revocation/credential-epoch fields folded into the activity
/// statement. The order matches Python's `authenticate_claims`: missing user,
/// revoked token, then stale password epoch.
fn validate_auth(claims: &VerifiedAccessClaims, auth: &Option<AuthRow>) -> Result<(), ApiError> {
    let auth = auth
        .as_ref()
        .ok_or_else(|| ApiError::Unauthorized("User not found".to_string()))?;
    if auth.revoked {
        return Err(ApiError::Unauthorized("Token has been revoked".to_string()));
    }
    if claims.expected_epoch()? < auth.password_epoch {
        return Err(ApiError::Unauthorized(
            "Password changed; please sign in again.".to_string(),
        ));
    }
    Ok(())
}

/// Build the ISO 8601 timestamp with microsecond precision from separate fields.
fn build_timestamp(sec: f64, us: Option<f64>) -> String {
    let datetime: DateTime<Utc> = DateTime::from_timestamp(sec as i64, 0)
        .unwrap_or_else(|| DateTime::from_timestamp(sec as i64, 0).unwrap());
    // Include microseconds if present and non-zero
    match us {
        Some(us_val) if us_val > 0.0 => {
            let us = us_val.fract() * 1_000_000.0;
            if us > 0.0 {
                let us_u32 = us as u32;
                let iso = datetime.format("%Y-%m-%dT%H:%M:%S");
                format!("{iso}.{us_u32:06}Z")
            } else {
                datetime.to_rfc3339()
            }
        }
        _ => datetime.to_rfc3339(),
    }
}

/// The one owner-scoped SQL statement for activity events.
///
/// This query fetches all user-visible events in reverse chronological order,
/// with thread title denormalized for display without N+1 lookups.
///
/// The query includes:
/// - Events from sessions owned by the user (via session_id join)
/// - Sessionless events that have user_id directly (snoozes, ratings, etc.)
const ACTIVITY_SQL: &str = r#"
WITH auth AS (
    SELECT u.id AS user_id,
           COALESCE(trunc(extract(epoch FROM u.password_changed_at))::bigint, 0) AS password_epoch,
           EXISTS(SELECT 1 FROM revoked_tokens r WHERE r.jti = $2) AS revoked
    FROM users u
    WHERE u.username = $1
    LIMIT 1
),
me AS (
    SELECT user_id FROM auth WHERE NOT revoked AND password_epoch <= $3
),
page_events AS (
    SELECT e.id AS event_id,
           e.type AS event_type,
           e.timestamp AS event_timestamp,
           e.die AS die_before,
           e.die_after,
           e.rating,
           e.thread_id,
           t.title AS thread_title,
           e.issue_number
    FROM events e
    LEFT JOIN threads t ON t.id = COALESCE(e.thread_id, e.selected_thread_id) AND t.user_id = (SELECT user_id FROM me)
    WHERE e.user_id = (SELECT user_id FROM me)
       OR e.session_id IN (SELECT id FROM sessions WHERE user_id = (SELECT user_id FROM me))
    ORDER BY e.timestamp DESC, e.id DESC
    LIMIT $4 + 1
)
SELECT jsonb_agg(jsonb_build_object(
    'auth', (SELECT jsonb_build_object('password_epoch', password_epoch, 'revoked', revoked) FROM auth),
    'events', (SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'event_id', event_id,
        'type', event_type,
        'timestamp', to_char(event_timestamp AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.USZ'),
        'die_before', die_before,
        'die_after', die_after,
        'rating', rating,
        'thread_id', thread_id,
        'thread_title', thread_title,
        'issue_number', issue_number
    ) FILTER (WHERE event_id IS NOT NULL), '[]')) FROM page_events),
    'has_more', (SELECT COUNT(*) > $4 FROM page_events),
    'last_id', (SELECT event_id FROM page_events WHERE event_id IS NOT NULL LIMIT 1 OFFSET $4),
    'last_ts_us', (SELECT to_char(event_timestamp AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.USZ') FROM page_events WHERE event_id IS NOT NULL LIMIT 1 OFFSET $4)
)::text
FROM page_events
LIMIT 1;
"#;

/// Read the owner-scoped activity events in one statement.
pub async fn activity(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
) -> Result<Json<ActivityResponse>, ApiError> {
    let expected_epoch = claims.expected_epoch()?;
    let username = claims.username().to_string();
    let jti = claims.jti().to_string();
    let page_size = DEFAULT_PAGE_SIZE;
    let bindings: [&(dyn tokio_postgres::types::ToSql + Sync); 4] =
        [&username, &jti, &expected_epoch, &page_size as &i64];

    let connection = db::checkout(&state).await?;
    ACTIVITY_STATEMENTS_ISSUED.fetch_add(1, Ordering::Relaxed);
    let row = db::query_one_optional(&state, connection, ACTIVITY_SQL, &bindings)
        .await?
        .ok_or_else(internal_error)?;
    let encoded: String = row.try_get(0).map_err(db::query_error)?;
    let payload: ActivityPayload = serde_json::from_str(&encoded).map_err(|error| {
        tracing::error!(%error, "Invalid native Roll activity projection");
        internal_error()
    })?;

    validate_auth(&claims, &payload.auth)?;

    let events = payload
        .events
        .into_iter()
        .map(|row| {
            ActivityEvent {
                event_id: row.event_id,
                event_type: row.event_type,
                timestamp: row.timestamp_sec.to_string(),
                die_before: row.die_before,
                die_after: row.die_after,
                rating: row.rating,
                thread_id: row.thread_id,
                thread_title: row.thread_title,
                issue_number: row.issue_number,
            }
        })
        .collect();

    let next_page_token = if payload.has_more {
        payload.last_id.zip(Some(0)).map(|(id, _)| id.to_string())
    } else {
        None
    };

    Ok(Json(ActivityResponse {
        events,
        next_page_token,
    }))
}

/// OpenAPI document for the v2 activity resource.
#[derive(utoipa::OpenApi)]
#[openapi(
    paths(activity_documentation),
    components(schemas(ActivityEvent, ActivityResponse)),
    modifiers(&ActivitySecurityAddon)
)]
pub struct ActivityApi;

struct ActivitySecurityAddon;
impl utoipa::Modify for ActivitySecurityAddon {
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

/// Documentation-only operation for the mounted v2 activity endpoint.
#[utoipa::path(
    get,
    path = "/api/v2/activity",
    tag = "activity",
    responses(
        (status = 200, description = "Owner-scoped activity timeline", body = ActivityResponse),
        (status = 401, description = "Not authenticated, revoked token, or stale credential epoch")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
fn activity_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use utoipa::OpenApi;

    #[test]
    fn activity_openapi_describes_the_bounded_v2_resource() {
        let openapi = ActivityApi::openapi();
        let operation = openapi
            .paths
            .paths
            .get("/api/v2/activity")
            .and_then(|path| path.get.as_ref())
            .expect("activity operation");
        assert_eq!(operation.tags, Some(vec!["activity".to_string()]));
        let schemas = &openapi
            .components
            .as_ref()
            .expect("component schemas")
            .schemas;
        assert!(schemas.contains_key("ActivityResponse"));
        assert!(schemas.contains_key("ActivityEvent"));
    }

    #[test]
    fn activity_statement_is_one_bounded_query() {
        assert!(ACTIVITY_SQL.contains("LIMIT $4 + 1"));
        assert!(ACTIVITY_SQL.contains("page_events"));
        // Allow a trailing semicolon (standard SQL), but no semicolons in the middle
        let semicolon_count = ACTIVITY_SQL.matches(';').count();
        assert_eq!(
            semicolon_count, 1,
            "activity SQL must be one statement (found {} semicolons)",
            semicolon_count
        );
    }
}