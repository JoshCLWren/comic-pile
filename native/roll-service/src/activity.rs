//! Owner-scoped activity history endpoint for the History page.
//!
//! `GET /api/v2/activity` provides a chronological view of all user-visible
//! events including sessionless snoozes and ratings, with stable cursor
//! pagination. This replaces the Python `GET /api/v1/sessions/` endpoint for
//! the History page to fix the omissions described in issue #4822.
//!
//! The response coalesces the two receipts of one rating action
//! (`issue_command_key` + `dice_command_key`) into a single display row while
//! both audit rows stay in the database, and it restores the causal narrative
//! for snooze/roll pairs whose insertion timestamps cross by milliseconds, so
//! the timeline reads d6 roll → snooze to d8 → roll d8 → snooze to d10 →
//! roll d10 → rated 4.5.
//!
//! Authentication, token-revocation state, the credential epoch and every
//! activity projection are folded into one owner-scoped PostgreSQL statement.
use crate::{auth::VerifiedAccessClaims, db, ApiError, AppState};
use axum::{
    extract::{Query, State},
    Json,
};
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
pub struct ActivityQuery {
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
    /// Exact owned issue id for actionable comic UI, when available.
    pub issue_id: Option<i32>,
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
}

#[derive(Debug, Deserialize)]
struct ActivityRawRow {
    event_id: i32,
    #[serde(rename = "type")]
    event_type: String,
    timestamp_sec: f64,
    timestamp_us: Option<f64>,
    die_before: Option<i32>,
    die_after: Option<i32>,
    rating: Option<f64>,
    thread_id: Option<i32>,
    thread_title: Option<String>,
    issue_number: Option<String>,
    issue_id: Option<i32>,
    dice_command_key: Option<String>,
    issue_command_key: Option<String>,
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
            let us_u32 = us_val as u32;
            if us_u32 > 0 {
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
///
/// Supports cursor-based pagination via $5 (cursor_event_id). When provided,
/// only events older than the cursor event are returned.
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
cursor_bounds AS (
    SELECT 
        COALESCE((SELECT timestamp FROM events WHERE id = $5), '9999-12-31 23:59:59+00'::timestamptz) AS cursor_timestamp,
        COALESCE($5, 2147483647) AS cursor_id
),
page_events AS (
    SELECT e.id AS event_id,
           e.type AS event_type,
           extract(epoch FROM e.timestamp) AS timestamp_sec,
           (extract(epoch FROM e.timestamp) - floor(extract(epoch FROM e.timestamp))) * 1000000 AS timestamp_us,
           e.die AS die_before,
           e.die_after,
           e.rating,
           e.thread_id,
           t.title AS thread_title,
           e.issue_number,
           e.issue_id,
           e.context->>'dice_command_key' AS dice_command_key,
           e.context->>'issue_command_key' AS issue_command_key
    FROM events e
    LEFT JOIN threads t ON t.id = COALESCE(e.thread_id, e.selected_thread_id) AND t.user_id = (SELECT user_id FROM me)
    CROSS JOIN cursor_bounds
    WHERE (e.user_id = (SELECT user_id FROM me)
        OR e.session_id IN (SELECT id FROM sessions WHERE user_id = (SELECT user_id FROM me)))
      AND (e.timestamp, e.id) < (cursor_bounds.cursor_timestamp, cursor_bounds.cursor_id)
    ORDER BY e.timestamp DESC, e.id DESC
    LIMIT $4 + 1
)
SELECT jsonb_agg(jsonb_build_object(
    'auth', (SELECT jsonb_build_object('password_epoch', password_epoch, 'revoked', revoked) FROM auth),
    'events', (SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'event_id', event_id,
        'type', event_type,
        'timestamp_sec', timestamp_sec,
        'timestamp_us', timestamp_us,
        'die_before', die_before,
        'die_after', die_after,
        'rating', rating,
        'thread_id', thread_id,
        'thread_title', thread_title,
        'issue_number', issue_number,
        'issue_id', issue_id,
        'dice_command_key', dice_command_key,
        'issue_command_key', issue_command_key
    ) FILTER (WHERE event_id IS NOT NULL), '[]')) FROM page_events),
    'has_more', (SELECT COUNT(*) > $4 FROM page_events),
    'last_id', (SELECT event_id FROM page_events WHERE event_id IS NOT NULL LIMIT 1 OFFSET $4)
)::text
FROM page_events
LIMIT 1;
"#;

/// Comparable (seconds, microseconds) sort key for one raw row.
fn timestamp_key(row: &ActivityRawRow) -> (i64, f64) {
    (row.timestamp_sec as i64, row.timestamp_us.unwrap_or(0.0))
}

/// True when two adjacent `rate` rows are the two receipts of one user action:
/// one carries an `issue_command_key` receipt and the other a `dice_command_key`
/// receipt for the same issue and the same rating.
///
/// The pair is never merged when both rows are issue receipts or both are dice
/// receipts, so unrelated repeated ratings stay distinct.
fn coalescible_rate_pair(first: &ActivityRawRow, second: &ActivityRawRow) -> bool {
    if first.event_type != "rate" || second.event_type != "rate" {
        return false;
    }
    let (issue_receipt, dice_receipt) = match (
        first.issue_command_key.is_some(),
        second.issue_command_key.is_some(),
    ) {
        (true, false) => (first, second),
        (false, true) => (second, first),
        _ => return false,
    };
    if dice_receipt.dice_command_key.is_none() {
        return false;
    }
    if issue_receipt.rating != dice_receipt.rating || issue_receipt.rating.is_none() {
        return false;
    }
    match (issue_receipt.issue_id, dice_receipt.issue_id) {
        (Some(left), Some(right)) => left == right,
        _ => {
            issue_receipt.thread_id == dice_receipt.thread_id
                && issue_receipt.thread_id.is_some()
                && issue_receipt.issue_number == dice_receipt.issue_number
        }
    }
}

/// Fold one coalesced rate pair into a single display row without erasing either
/// audit row. The issue receipt owns the display (it carries the new die and the
/// source roll link); the dice receipt contributes the previous die.
fn merge_rate_pair(first: ActivityRawRow, second: ActivityRawRow) -> ActivityRawRow {
    let (mut issue_receipt, dice_receipt) = if first.issue_command_key.is_some() {
        (first, second)
    } else {
        (second, first)
    };
    if issue_receipt.die_before.is_none() {
        issue_receipt.die_before = dice_receipt.die_before;
    }
    if issue_receipt.die_after.is_none() {
        issue_receipt.die_after = dice_receipt.die_after;
    }
    if issue_receipt.issue_id.is_none() {
        issue_receipt.issue_id = dice_receipt.issue_id;
    }
    if issue_receipt.thread_id.is_none() {
        issue_receipt.thread_id = dice_receipt.thread_id;
    }
    if issue_receipt.issue_number.is_none() {
        issue_receipt.issue_number = dice_receipt.issue_number;
    }
    if dice_receipt.event_id > issue_receipt.event_id {
        issue_receipt.event_id = dice_receipt.event_id;
    }
    if timestamp_key(&dice_receipt) > timestamp_key(&issue_receipt) {
        issue_receipt.timestamp_sec = dice_receipt.timestamp_sec;
        issue_receipt.timestamp_us = dice_receipt.timestamp_us;
    }
    issue_receipt
}

/// Collapse a related `issue_command_key`/`dice_command_key` rate pair into one
/// reader-visible rating while keeping both underlying audit rows intact in the
/// database. Rows are consumed newest-first, matching the SQL projection order.
fn coalesce_rate_pairs(rows: Vec<ActivityRawRow>) -> Vec<ActivityRawRow> {
    let mut output: Vec<ActivityRawRow> = Vec::with_capacity(rows.len());
    let mut pending = rows.into_iter().peekable();
    while let Some(row) = pending.next() {
        if row.event_type == "rate" {
            if let Some(next) = pending.peek() {
                if coalescible_rate_pair(&row, next) {
                    match pending.next() {
                        Some(other) => output.push(merge_rate_pair(row, other)),
                        None => output.push(row),
                    }
                    continue;
                }
            }
        }
        output.push(row);
    }
    output
}

/// Restore the causal narrative for reroll/snooze pairs whose insertion
/// timestamps cross by milliseconds.
///
/// A snooze that steps the die from `before` to `after` is the cause of the very
/// next roll made on `after`. When that roll's wall-clock timestamp is slightly
/// earlier than the snooze row (the production defect), naive `timestamp, id`
/// ordering shows the snooze before the roll it caused. The swap below is the
/// deterministic fallback for rows that carry no `roll_offer_key`/source link:
/// it never rewrites timestamps or audit rows, only the reader-visible order.
fn apply_causal_order(mut rows: Vec<ActivityRawRow>) -> Vec<ActivityRawRow> {
    let mut index = 0;
    while index + 1 < rows.len() {
        let inverted = {
            let snooze = &rows[index];
            let roll = &rows[index + 1];
            snooze.event_type == "snooze"
                && roll.event_type == "roll"
                && snooze.die_after.is_some()
                && snooze.die_after == roll.die_before
                && timestamp_key(snooze) > timestamp_key(roll)
        };
        if inverted {
            rows.swap(index, index + 1);
        }
        index += 1;
    }
    rows
}

/// Read the owner-scoped activity events in one statement.
pub async fn activity(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
    Query(query): Query<ActivityQuery>,
) -> Result<Json<ActivityResponse>, ApiError> {
    let expected_epoch = claims.expected_epoch()?;
    let username = claims.username().to_string();
    let jti = claims.jti().to_string();
    let page_size = query.page_size.unwrap_or(DEFAULT_PAGE_SIZE).clamp(1, 200);
    let cursor_event_id: Option<i32> = query.page_token.and_then(|t| t.parse().ok());

    let bindings: [&(dyn tokio_postgres::types::ToSql + Sync); 5] = [
        &username,
        &jti,
        &expected_epoch,
        &page_size as &i64,
        &cursor_event_id,
    ];

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

    let mut raw_events = apply_causal_order(coalesce_rate_pairs(payload.events));
    // Trim to page size; the extra row is used only for has_more detection
    let page_limit = page_size as usize;
    if raw_events.len() > page_limit {
        raw_events.truncate(page_limit);
    }
    let events_vec: Vec<ActivityEvent> = raw_events
        .into_iter()
        .map(|row| ActivityEvent {
            event_id: row.event_id,
            event_type: row.event_type,
            timestamp: build_timestamp(row.timestamp_sec, row.timestamp_us),
            die_before: row.die_before,
            die_after: row.die_after,
            rating: row.rating,
            thread_id: row.thread_id,
            thread_title: row.thread_title,
            issue_number: row.issue_number,
            issue_id: row.issue_id,
        })
        .collect();

    let next_page_token = if payload.has_more {
        // Use the last returned event id as cursor to avoid skipping
        events_vec.last().map(|e| e.event_id.to_string())
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

    /// Build a raw row for the reader-visible projection tests. Only the fields
    /// the coalescing/ordering logic reads are set; the rest stay at defaults.
    #[allow(clippy::too_many_arguments)]
    fn raw(
        event_id: i32,
        event_type: &str,
        timestamp_sec: f64,
        timestamp_us: Option<f64>,
        die_before: Option<i32>,
        die_after: Option<i32>,
        rating: Option<f64>,
        thread_id: Option<i32>,
        issue_number: Option<&str>,
        issue_id: Option<i32>,
        dice_command_key: Option<&str>,
        issue_command_key: Option<&str>,
    ) -> ActivityRawRow {
        ActivityRawRow {
            event_id,
            event_type: event_type.to_string(),
            timestamp_sec,
            timestamp_us,
            die_before,
            die_after,
            rating,
            thread_id,
            thread_title: None,
            issue_number: issue_number.map(str::to_string),
            issue_id,
            dice_command_key: dice_command_key.map(str::to_string),
            issue_command_key: issue_command_key.map(str::to_string),
        }
    }

    #[test]
    fn coalesce_rate_pairs_merges_issue_and_dice_receipts() {
        // One user action: an issue-command receipt and a dice-command receipt.
        let rows = vec![
            raw(
                1050517,
                "rate",
                10.0,
                Some(388000.0),
                None,
                Some(8),
                Some(4.5),
                Some(52329),
                Some("2"),
                Some(900),
                None,
                Some("issue-1"),
            ),
            raw(
                1050516,
                "rate",
                10.0,
                Some(440000.0),
                Some(10),
                Some(8),
                Some(4.5),
                Some(52329),
                Some("2"),
                Some(900),
                Some("dice-1"),
                None,
            ),
        ];
        let merged = coalesce_rate_pairs(rows);
        assert_eq!(
            merged.len(),
            1,
            "the rate pair collapses to one display row"
        );
        let row = &merged[0];
        assert_eq!(row.rating, Some(4.5));
        assert_eq!(row.die_before, Some(10));
        assert_eq!(row.die_after, Some(8));
        assert_eq!(row.issue_id, Some(900));
        // The newer event id/timestamp is retained for a stable display.
        assert_eq!(row.event_id, 1050517);
        assert_eq!(row.timestamp_us, Some(440000.0));
    }

    #[test]
    fn coalesce_rate_pairs_keeps_unrelated_repeated_ratings() {
        // Two separate rating actions on two different issues must stay distinct.
        let rows = vec![
            raw(
                3,
                "rate",
                30.0,
                None,
                None,
                Some(8),
                Some(4.0),
                Some(1),
                Some("1"),
                Some(11),
                None,
                Some("issue-a"),
            ),
            raw(
                2,
                "rate",
                20.0,
                None,
                None,
                Some(8),
                Some(4.0),
                Some(1),
                Some("1"),
                Some(11),
                Some("dice-a"),
                None,
            ),
            raw(
                1,
                "rate",
                10.0,
                None,
                None,
                Some(10),
                Some(4.0),
                Some(2),
                Some("2"),
                Some(22),
                Some("dice-b"),
                None,
            ),
        ];
        let merged = coalesce_rate_pairs(rows);
        assert_eq!(
            merged.len(),
            2,
            "the first pair merges, the unrelated row stays"
        );
    }

    #[test]
    fn apply_causal_order_swaps_inverted_snooze_roll() {
        // Production defect: the snooze row's timestamp is after the roll it
        // caused. Newest-first naive order is [snooze, roll]; causally the roll
        // happened after the snooze, so the roll must read first.
        let rows = vec![
            raw(
                1050512,
                "snooze",
                25.0,
                Some(515000.0),
                Some(6),
                Some(8),
                None,
                Some(3153),
                None,
                None,
                Some("dice-snooze"),
                None,
            ),
            raw(
                1050513,
                "roll",
                25.0,
                Some(467000.0),
                Some(8),
                None,
                None,
                None,
                None,
                Some(25301),
                None,
                None,
            ),
        ];
        let ordered = apply_causal_order(rows);
        assert_eq!(ordered[0].event_type, "roll");
        assert_eq!(ordered[1].event_type, "snooze");
    }

    #[test]
    fn activity_finalize_matches_production_sequence() {
        // The owner-reported 09:42 → 10:01 sequence, newest-first from the SQL
        // projection (note the inverted snooze/roll timestamps and the rate pair).
        let rows = vec![
            raw(
                1050516,
                "rate",
                50.0,
                Some(440000.0),
                Some(10),
                Some(8),
                Some(4.5),
                Some(52329),
                Some("2"),
                Some(900),
                Some("dice"),
                None,
            ),
            raw(
                1050517,
                "rate",
                50.0,
                Some(388000.0),
                None,
                Some(8),
                Some(4.5),
                Some(52329),
                Some("2"),
                Some(900),
                None,
                Some("issue"),
            ),
            raw(
                1050514,
                "snooze",
                34.0,
                Some(105000.0),
                Some(8),
                Some(10),
                None,
                Some(3469),
                None,
                None,
                Some("dice2"),
                None,
            ),
            raw(
                1050515,
                "roll",
                34.0,
                Some(66000.0),
                Some(10),
                None,
                None,
                None,
                None,
                Some(52329),
                None,
                None,
            ),
            raw(
                1050512,
                "snooze",
                25.0,
                Some(515000.0),
                Some(6),
                Some(8),
                None,
                Some(3153),
                None,
                None,
                Some("dice1"),
                None,
            ),
            raw(
                1050513,
                "roll",
                25.0,
                Some(467000.0),
                Some(8),
                None,
                None,
                None,
                None,
                Some(25301),
                None,
                None,
            ),
            raw(
                1050511,
                "roll",
                35.0,
                Some(28000.0),
                Some(6),
                None,
                None,
                None,
                None,
                Some(1121330),
                None,
                None,
            ),
        ];

        let ordered: Vec<ActivityRawRow> = apply_causal_order(coalesce_rate_pairs(rows));
        let summary: Vec<(&str, i32)> = ordered
            .iter()
            .map(|row| (row.event_type.as_str(), row.event_id))
            .collect();

        // Newest-first: the coalesced rating, then roll d10, snooze d8->d10,
        // roll d8, snooze d6->d8, roll d6. Reversed, this is the causal narrative.
        assert_eq!(
            summary,
            vec![
                ("rate", 1050517),
                ("roll", 1050515),
                ("snooze", 1050514),
                ("roll", 1050513),
                ("snooze", 1050512),
                ("roll", 1050511),
            ]
        );

        // Only one rating display row survives, and it carries the merged die
        // transition (d10 -> d8) from both receipts.
        let ratings: Vec<&ActivityRawRow> = ordered
            .iter()
            .filter(|row| row.event_type == "rate")
            .collect();
        assert_eq!(ratings.len(), 1);
        assert_eq!(ratings[0].die_before, Some(10));
        assert_eq!(ratings[0].die_after, Some(8));
        assert_eq!(ratings[0].rating, Some(4.5));
    }
}
