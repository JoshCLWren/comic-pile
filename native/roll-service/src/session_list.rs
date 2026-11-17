//! Native same-path session list and current-session reads (#4839, parent #4335).
//!
//! Migrates the remaining browser-called session operations to the native
//! Rust router with identical method/path and wire contract:
//!
//! * `GET /api/sessions/` and `GET /api/v1/sessions/` - paginated session history
//! * `GET /api/sessions/current/` and `GET /api/v1/sessions/current/` - current active session
//!
//! Wire parity with Python `list_sessions` and `get_current_session` (`app/api/session.py`):
//!
//! * Ownership: all queries scoped to `user_id = $1`
//! * Pagination: cursor-based on `(started_at DESC, id DESC)` with `page_size` (1..200, default 50) and `page_token` ("started_at,id")
//! * `ladder_path`: `build_ladder_path` — `start_die` followed by every `die_after` from `rate`/`snooze`/`undo` events in timestamp/id order, joined with `" → "`.
//! * `current_die`: event-derived die wins (#4352); non-zero `manual_die` fallback, otherwise `start_die`.
//! * `active_thread`: latest `roll`/`rate`/`snooze`/`rolled_but_skipped` event; pending thread wins; missing pending yields `null` without fall-through. `issues_remaining` counts unread `issues` when thread uses issue tracking, otherwise stored counter. `queue_position` is legacy dense display ordinal.
//! * `bandwidth` / `intent`: normalization (unknown enum strings and out-of-range confidences become `null`).
//! * `format` normalization, direct visible tags ordered by scope descending then normalized name, and `next_issue_*` from `next_unread_issue_id` when issue tracking is in use.
//! * List view (`SessionListItem`) omits `snoozed_*` / `skipped_*` / `pending_thread_id` / `timezone` / `bandwidth` / `intent` / `correction` to reduce payload.
//! * Timestamps emitted as UTC `...Z` strings (matching session-detail Rust slice).
//!
//! Bounded reads only: one session page, one snapshot count per session, two die-event reads per session, one latest-action read per session, and at most one active thread per session with one unread count, one next-issue read, one tag read and one ranked queue read. No per-row fan-out across the page.

#![forbid(unsafe_code)]

use crate::{
    auth::AuthenticatedUser,
    db,
    reading_session::{self, automatic_die_after, SessionPolicy},
    ApiError, AppState,
};
use axum::{
    extract::{Query, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::Arc;
use utoipa::ToSchema;

/// Query parameters for session history pagination.
#[derive(Debug, Deserialize, ToSchema, utoipa::IntoParams)]
pub struct SessionListParams {
    #[schema(default = 50, minimum = 1, maximum = 200)]
    pub page_size: Option<i32>,
    pub page_token: Option<String>,
}

/// One direct visible tag on the active thread.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct SessionTag {
    pub id: i32,
    pub name: String,
    pub normalized_name: String,
    pub scope: String,
    pub owner_user_id: Option<i32>,
    pub color: String,
    pub created_at: String,
    pub updated_at: String,
}

/// Active (pending or freshly rolled) thread projection for one session.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct SessionActiveThread {
    pub id: i32,
    pub title: String,
    pub format: String,
    pub issues_remaining: i32,
    pub queue_position: i32,
    pub last_rolled_result: Option<i32>,
    pub total_issues: Option<i32>,
    pub reading_progress: Option<String>,
    pub issues_read: Option<i32>,
    pub last_rating: Option<f64>,
    pub tags: Vec<SessionTag>,
    pub issue_id: Option<i32>,
    pub issue_number: Option<String>,
    pub next_issue_id: Option<i32>,
    pub next_issue_number: Option<String>,
}

/// Canonical bandwidth state; invalid stored values normalize to `null`.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct SessionBandwidthState {
    pub predicted_bandwidth: Option<String>,
    pub active_bandwidth: Option<String>,
    pub confidence: Option<f64>,
    pub source: Option<String>,
    pub mode_version: Option<String>,
}

/// Canonical intent state; invalid stored values normalize to `null`.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct SessionIntentState {
    pub predicted_intent: Option<String>,
    pub active_intent: Option<String>,
    pub confidence: Option<f64>,
    pub source: Option<String>,
    pub mode_version: Option<String>,
}

/// Compact thread summary used for the snoozed and skipped lists.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct SessionThreadSummary {
    pub id: i32,
    pub title: String,
}

/// Full session response (current-session endpoint).
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct SessionCurrentResponse {
    pub id: i32,
    pub started_at: String,
    pub ended_at: Option<String>,
    pub start_die: i32,
    pub manual_die: Option<i32>,
    pub user_id: i32,
    pub ladder_path: String,
    pub active_thread: Option<SessionActiveThread>,
    pub current_die: i32,
    pub last_rolled_result: Option<i32>,
    pub has_restore_point: bool,
    pub snapshot_count: i32,
    pub snoozed_thread_ids: Vec<i32>,
    pub snoozed_threads: Vec<SessionThreadSummary>,
    pub skipped_thread_ids: Vec<i32>,
    pub skipped_threads: Vec<SessionThreadSummary>,
    pub pending_thread_id: Option<i32>,
    pub timezone: Option<String>,
    pub reading_bandwidth: Option<String>,
    pub reading_intent: Option<String>,
    pub reading_mode_source: Option<String>,
    pub reading_mode_suggested: bool,
    pub bandwidth: Option<SessionBandwidthState>,
    pub intent: Option<SessionIntentState>,
}

/// List-item session response (history list endpoint).
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct SessionListItemResponse {
    pub id: i32,
    pub started_at: String,
    pub ended_at: Option<String>,
    pub start_die: i32,
    pub manual_die: Option<i32>,
    pub user_id: i32,
    pub ladder_path: String,
    pub active_thread: Option<SessionActiveThread>,
    pub current_die: i32,
    pub last_rolled_result: Option<i32>,
    pub has_restore_point: bool,
    pub snapshot_count: i32,
    pub reading_bandwidth: Option<String>,
    pub reading_intent: Option<String>,
    pub reading_mode_source: Option<String>,
    pub reading_mode_suggested: bool,
}

/// Paginated session history list response.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct SessionHistoryListResponse {
    pub sessions: Vec<SessionListItemResponse>,
    pub next_page_token: Option<String>,
}

const SESSION_PAGE_SQL: &str = "SELECT id, to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(ended_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), start_die, manual_die, user_id, pending_thread_id, timezone, reading_bandwidth, reading_intent, reading_mode_source, reading_mode_suggested FROM sessions WHERE user_id = $1 ORDER BY started_at DESC, id DESC LIMIT $2";
const SESSION_PAGE_WITH_CURSOR_SQL: &str = "SELECT id, to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(ended_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), start_die, manual_die, user_id, pending_thread_id, timezone, reading_bandwidth, reading_intent, reading_mode_source, reading_mode_suggested FROM sessions WHERE user_id = $1 AND (started_at < $2 OR (started_at = $2 AND id < $3)) ORDER BY started_at DESC, id DESC LIMIT $4";
const SNAPSHOT_COUNT_SQL: &str = "SELECT session_id, count(*)::int FROM snapshots WHERE session_id = ANY($1) GROUP BY session_id";
const SNAPSHOT_COUNT_ONE_SQL: &str = "SELECT count(*)::int FROM snapshots WHERE session_id = $1";
const LADDER_SQL: &str = "SELECT session_id, die_after FROM events WHERE session_id = ANY($1) AND type IN ('rate','snooze','undo','reset_dice','manual_die') AND die_after IS NOT NULL ORDER BY session_id, timestamp ASC, id ASC";
const CURRENT_DIE_SQL: &str = "SELECT session_id, die_after, context::text FROM events WHERE session_id = ANY($1) AND type IN ('rate','snooze','undo','reset_dice','manual_die') AND die_after IS NOT NULL ORDER BY session_id, timestamp DESC, id DESC";
const LATEST_ROLL_SQL: &str = "SELECT session_id, selected_thread_id, result FROM events WHERE session_id = ANY($1) AND type = 'roll' ORDER BY session_id, timestamp DESC, id DESC";
const RATES_UNDO_SQL: &str = "SELECT session_id, type, issues_read, rating FROM events WHERE session_id = ANY($1) AND type IN ('rate','undo') ORDER BY session_id, timestamp ASC, id ASC";
const LATEST_ACTION_SQL: &str = "SELECT session_id, type, selected_thread_id, result FROM events WHERE session_id = ANY($1) AND type IN ('roll','rate','snooze','rolled_but_skipped') ORDER BY session_id, timestamp DESC, id DESC";
const PENDING_THREAD_SQL: &str = "SELECT id, title, format, issues_remaining, total_issues, reading_progress, next_unread_issue_id, user_id FROM threads WHERE id = $1 AND user_id = $2";
const ROLLED_THREAD_SQL: &str = "SELECT id, title, format, issues_remaining, total_issues, reading_progress, next_unread_issue_id, user_id FROM threads WHERE id = $1";
const UNREAD_COUNT_SQL: &str =
    "SELECT count(*)::int FROM issues WHERE thread_id = $1 AND status = 'unread'";
const NEXT_ISSUE_SQL: &str = "SELECT id, issue_number FROM issues WHERE id = $1";
const TAGS_SQL: &str = "SELECT tag.id, tag.name, tag.normalized_name, tag.scope, tag.owner_user_id, tag.color, to_char(tag.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(tag.updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') FROM tag_assignments assignment JOIN tags tag ON tag.id = assignment.tag_id WHERE assignment.target_type = 'Thread' AND assignment.target_id = $1 AND (tag.scope = 'global' OR tag.owner_user_id = $2) ORDER BY tag.scope DESC, tag.normalized_name ASC";
const TAGS_ANY_SQL: &str = "SELECT tag.id, tag.name, tag.normalized_name, tag.scope, tag.owner_user_id, tag.color, to_char(tag.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(tag.updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), assignment.target_id FROM tag_assignments assignment JOIN tags tag ON tag.id = assignment.tag_id WHERE assignment.target_type = 'Thread' AND assignment.target_id = ANY($1) AND (tag.scope = 'global' OR tag.owner_user_id = $2) ORDER BY tag.scope DESC, tag.normalized_name ASC";
const QUEUE_POSITION_SQL: &str = "SELECT seq::int FROM (SELECT id, row_number() OVER (ORDER BY is_blocked ASC, queue_position ASC, id ASC) AS seq FROM threads WHERE user_id = $1 AND status = 'active' AND queue_position >= 1) ranked WHERE id = $2";
const QUEUE_POSITION_ANY_SQL: &str = "SELECT id, seq::int FROM (SELECT id, row_number() OVER (ORDER BY is_blocked ASC, queue_position ASC, id ASC) AS seq FROM threads WHERE user_id = $1 AND status = 'active' AND queue_position >= 1) ranked WHERE id = ANY($2)";

// Windowed current-session resolution matching Python `get_or_create`: an
// unended session with a pending reading context wins; otherwise the session
// with the most recent activity (start, pending refresh, or event) within the
// six-hour default gap window wins. When no active session survives the gap
// window, `get_current_session` calls the transactional get-or-create so that
// this same-path GET matches Python's `get_or_create` read behavior (a fresh
// session is created rather than answering 404).
const CURRENT_SESSION_SQL: &str = "SELECT id, to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(ended_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), start_die, manual_die, user_id, pending_thread_id, timezone, reading_bandwidth, reading_intent, reading_mode_source, reading_mode_suggested, predicted_bandwidth, active_bandwidth, bandwidth_confidence, bandwidth_source, bandwidth_version, predicted_intent, active_intent, intent_confidence, intent_source, intent_version, snoozed_thread_ids, skipped_thread_ids, recent.pending_issue_id FROM (SELECT s.id, s.started_at, s.ended_at, s.start_die, s.manual_die, s.user_id, s.pending_thread_id, s.pending_issue_id, s.timezone, s.reading_bandwidth, s.reading_intent, s.reading_mode_source, s.reading_mode_suggested, s.predicted_bandwidth, s.active_bandwidth, s.bandwidth_confidence, s.bandwidth_source, s.bandwidth_version, s.predicted_intent, s.active_intent, s.intent_confidence, s.intent_source, s.intent_version, s.snoozed_thread_ids, s.skipped_thread_ids, GREATEST(s.started_at, CASE WHEN s.pending_thread_id IS NOT NULL OR s.pending_issue_id IS NOT NULL THEN COALESCE(s.pending_thread_updated_at, s.started_at) ELSE s.started_at END, COALESCE((SELECT max(e.timestamp) FROM events e WHERE e.session_id = s.id), s.started_at)) AS activity_at FROM sessions s WHERE s.user_id = $1 AND s.ended_at IS NULL) recent WHERE recent.activity_at >= to_timestamp($2) ORDER BY (recent.pending_thread_id IS NOT NULL OR recent.pending_issue_id IS NOT NULL) DESC, recent.activity_at DESC, recent.started_at DESC, recent.id DESC LIMIT 1";

/// Parse a nullable json thread-id array (Python `snoozed_thread_ids` /
/// `skipped_thread_ids` columns) into a bounded vector of valid ids.
pub(crate) fn json_id_list(value: Option<Value>) -> Vec<i32> {
    value
        .and_then(|v| v.as_array().cloned())
        .unwrap_or_default()
        .into_iter()
        .filter_map(|item| item.as_i64())
        .filter_map(|id| i32::try_from(id).ok())
        .collect()
}

fn not_found() -> ApiError {
    ApiError::with_status(StatusCode::NOT_FOUND, "Session not found".to_string())
}

fn internal() -> ApiError {
    ApiError::with_status(
        StatusCode::INTERNAL_SERVER_ERROR,
        "Internal Server Error".to_string(),
    )
}

/// Python `normalize_format_value`: trim, then map known variants.
pub(crate) fn normalize_format(value: &str) -> String {
    let stripped = value.trim();
    match stripped.to_ascii_lowercase().as_str() {
        "comic" | "comics" => "Comic".to_string(),
        "digital" => "Digital".to_string(),
        _ => stripped.to_string(),
    }
}

fn normalize_bandwidth_level(value: Option<&str>) -> Option<String> {
    match value {
        Some("light" | "balanced" | "deep") => value.map(str::to_owned),
        _ => None,
    }
}

fn normalize_intent_level(value: Option<&str>) -> Option<String> {
    match value {
        Some("balanced" | "momentum" | "familiar" | "explore" | "random") => {
            value.map(str::to_owned)
        }
        _ => None,
    }
}

fn normalize_source(value: Option<&str>) -> Option<String> {
    match value {
        Some("inferred" | "manual" | "snooze" | "quiz") => value.map(str::to_owned),
        _ => None,
    }
}

fn normalize_confidence(value: Option<f64>) -> Option<f64> {
    value.filter(|confidence| (0.0..=1.0).contains(confidence))
}

fn bandwidth_state(
    predicted: Option<&str>,
    active: Option<&str>,
    confidence: Option<f64>,
    source: Option<&str>,
    version: Option<&str>,
) -> SessionBandwidthState {
    SessionBandwidthState {
        predicted_bandwidth: normalize_bandwidth_level(predicted),
        active_bandwidth: normalize_bandwidth_level(active),
        confidence: normalize_confidence(confidence),
        source: normalize_source(source),
        mode_version: version.map(str::to_owned),
    }
}

fn intent_state(
    predicted: Option<&str>,
    active: Option<&str>,
    confidence: Option<f64>,
    source: Option<&str>,
    version: Option<&str>,
) -> SessionIntentState {
    SessionIntentState {
        predicted_intent: normalize_intent_level(predicted),
        active_intent: normalize_intent_level(active),
        confidence: normalize_confidence(confidence),
        source: normalize_source(source),
        mode_version: version.map(str::to_owned),
    }
}

/// Python `build_ladder_path`: start die plus chronological die-after values.
pub(crate) fn ladder_path(start_die: i32, die_after: &[i32]) -> String {
    let mut parts = vec![start_die.to_string()];
    parts.extend(die_after.iter().map(i32::to_string));
    parts.join(" → ")
}

/// Python `get_current_die` resolution for one already-loaded session.
pub(crate) fn current_die(
    manual_die: Option<i32>,
    latest: Option<(i32, &Value)>,
    start_die: i32,
) -> i32 {
    if let Some((die_after, context)) = latest {
        return automatic_die_after(die_after, context);
    }
    manual_die.filter(|value| *value != 0).unwrap_or(start_die)
}

/// `GET /api/sessions/` and `GET /api/v1/sessions/` - paginated session history.
pub async fn list_sessions(
    Query(params): Query<SessionListParams>,
    user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
) -> Result<Json<SessionHistoryListResponse>, ApiError> {
    let page_size = params.page_size.unwrap_or(50).clamp(1, 200);
    let connection = db::checkout(&state).await?;

    // Fetch session page
    let session_rows = if let Some(token) = params.page_token {
        let parts: Vec<&str> = token.split(',').collect();
        if parts.len() != 2 {
            return Err(ApiError::with_status(
                StatusCode::BAD_REQUEST,
                "Invalid page_token format".to_string(),
            ));
        }
        let cursor_started_at = chrono::DateTime::parse_from_rfc3339(parts[0]).map_err(|_| {
            ApiError::with_status(
                StatusCode::BAD_REQUEST,
                "Invalid page_token format".to_string(),
            )
        })?;
        let cursor_id = parts[1].parse::<i32>().map_err(|_| {
            ApiError::with_status(
                StatusCode::BAD_REQUEST,
                "Invalid page_token format".to_string(),
            )
        })?;
        connection
            .query(
                SESSION_PAGE_WITH_CURSOR_SQL,
                &[
                    &user.id(),
                    &cursor_started_at,
                    &cursor_id,
                    &((page_size + 1) as i64),
                ],
            )
            .await
            .map_err(db::query_error)?
    } else {
        connection
            .query(SESSION_PAGE_SQL, &[&user.id(), &((page_size + 1) as i64)])
            .await
            .map_err(db::query_error)?
    };

    let has_more = session_rows.len() > page_size as usize;
    let sessions_to_return = if has_more {
        &session_rows[..page_size as usize]
    } else {
        &session_rows
    };

    if sessions_to_return.is_empty() {
        return Ok(Json(SessionHistoryListResponse {
            sessions: Vec::new(),
            next_page_token: None,
        }));
    }

    let session_ids: Vec<i32> = sessions_to_return
        .iter()
        .map(|row| {
            row.try_get(0).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })
        })
        .collect::<Result<_, ApiError>>()?;

    // Snapshot counts for all sessions on this page
    let snapshot_count_rows = connection
        .query(SNAPSHOT_COUNT_SQL, &[&session_ids])
        .await
        .map_err(db::query_error)?;
    let snapshot_counts: std::collections::HashMap<i32, i32> = snapshot_count_rows
        .iter()
        .map(|row| {
            let sid: i32 = row.try_get(0).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?;
            let count: i32 = row.try_get(1).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?;
            Ok((sid, count))
        })
        .collect::<Result<_, ApiError>>()?;

    // Ladder path die-after values per session
    let ladder_rows = connection
        .query(LADDER_SQL, &[&session_ids])
        .await
        .map_err(db::query_error)?;
    let mut ladder_values: std::collections::HashMap<i32, Vec<i32>> =
        std::collections::HashMap::new();
    for row in ladder_rows {
        let sid: i32 = row.try_get(0).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let die_after: i32 = row.try_get(1).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        ladder_values.entry(sid).or_default().push(die_after);
    }

    // Current die per session (latest die-changing event)
    let die_rows = connection
        .query(CURRENT_DIE_SQL, &[&session_ids])
        .await
        .map_err(db::query_error)?;
    let mut latest_die_per_session: std::collections::HashMap<i32, (i32, Value)> =
        std::collections::HashMap::new();
    for row in die_rows {
        let sid: i32 = row.try_get(0).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        if latest_die_per_session.contains_key(&sid) {
            continue; // Already have the latest (ordered by timestamp DESC)
        }
        let die_after: i32 = row.try_get(1).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let context_text: Option<String> = row.try_get(2).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let context: Value = context_text
            .as_deref()
            .and_then(|text| serde_json::from_str(text).ok())
            .unwrap_or(Value::Null);
        latest_die_per_session.insert(sid, (die_after, context));
    }

    // Latest roll event per session (Python projects the latest roll only)
    let action_rows = connection
        .query(LATEST_ROLL_SQL, &[&session_ids])
        .await
        .map_err(db::query_error)?;
    let mut latest_roll_per_session: std::collections::HashMap<i32, (Option<i32>, Option<i32>)> =
        std::collections::HashMap::new();
    for row in &action_rows {
        let sid: i32 = row.try_get(0).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        if latest_roll_per_session.contains_key(&sid) {
            continue; // Already have the latest
        }
        let selected_thread_id: Option<i32> = row.try_get(1).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let result: Option<i32> = row.try_get(2).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        latest_roll_per_session.insert(sid, (selected_thread_id, result));
    }

    // Net rate aggregates per session (issues_read sum, last remaining rating).
    let rate_rows = connection
        .query(RATES_UNDO_SQL, &[&session_ids])
        .await
        .map_err(db::query_error)?;
    let mut open_rates: std::collections::HashMap<i32, Vec<(i32, Option<f64>)>> =
        std::collections::HashMap::new();
    for row in &rate_rows {
        let sid: i32 = row.try_get(0).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let event_type: String = row.try_get(1).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let stack = open_rates.entry(sid).or_default();
        if event_type == "undo" {
            stack.pop();
        } else {
            let issues_read: i32 = row.try_get(2).ok().flatten().unwrap_or(0);
            let rating: Option<f64> = row.try_get(3).ok().flatten();
            stack.push((issues_read, rating));
        }
    }
    let rate_agg: std::collections::HashMap<i32, (i32, Option<f64>)> = open_rates
        .into_iter()
        .map(|(sid, stack)| {
            let issues_read = stack.iter().map(|(count, _)| *count).sum::<i32>().max(0);
            let last_rating = stack.last().and_then(|(_, rating)| *rating);
            (sid, (issues_read, last_rating))
        })
        .collect();

    // Collect thread IDs for active threads
    let mut thread_ids = std::collections::HashSet::new();
    let mut pending_by_session: std::collections::HashMap<i32, i32> =
        std::collections::HashMap::new();
    for row in sessions_to_return {
        let sid: i32 = row.try_get(0).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let pending_thread_id: Option<i32> = row.try_get(6).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        if let Some(ptid) = pending_thread_id {
            thread_ids.insert(ptid);
            pending_by_session.insert(sid, ptid);
        }
    }
    for (selected_thread_id, _) in latest_roll_per_session.values() {
        if let Some(tid) = selected_thread_id {
            thread_ids.insert(*tid);
        }
    }

    // Load threads and build active thread info
    let mut active_threads: std::collections::HashMap<i32, Option<SessionActiveThread>> =
        std::collections::HashMap::new();

    if !thread_ids.is_empty() {
        let thread_id_list: Vec<i32> = thread_ids.into_iter().collect();
        let thread_rows = connection
            .query(
                "SELECT id, title, format, issues_remaining, total_issues, reading_progress, next_unread_issue_id, user_id FROM threads WHERE id = ANY($1)",
                &[&thread_id_list],
            )
            .await
            .map_err(db::query_error)?;
        let mut threads_by_id: std::collections::HashMap<i32, tokio_postgres::Row> =
            std::collections::HashMap::new();
        for row in thread_rows {
            let tid: i32 = row.try_get(0).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?;
            threads_by_id.insert(tid, row);
        }

        // Unread counts for issue-tracking threads
        let issue_tracking_thread_ids: Vec<i32> = threads_by_id
            .values()
            .filter_map(|row| {
                let total_issues: Option<i32> = row.try_get(4).ok();
                total_issues.map(|_| {
                    row.try_get::<_, i32>(0).map_err(|e| {
                        tracing::debug!(
                            error_kind = crate::error_kind(&e),
                            "preserved underlying error before mapping"
                        );
                        internal()
                    })
                })
            })
            .collect::<Result<_, ApiError>>()?;
        let mut unread_counts: std::collections::HashMap<i32, i32> =
            std::collections::HashMap::new();
        if !issue_tracking_thread_ids.is_empty() {
            let unread_rows = connection
                .query(
                    "SELECT thread_id, count(*)::int FROM issues WHERE thread_id = ANY($1) AND status = 'unread' GROUP BY thread_id",
                    &[&issue_tracking_thread_ids],
                )
                .await
                .map_err(db::query_error)?;
            for row in unread_rows {
                let tid: i32 = row.try_get(0).map_err(|e| {
                    tracing::debug!(
                        error_kind = crate::error_kind(&e),
                        "preserved underlying error before mapping"
                    );
                    internal()
                })?;
                let count: i32 = row.try_get(1).map_err(|e| {
                    tracing::debug!(
                        error_kind = crate::error_kind(&e),
                        "preserved underlying error before mapping"
                    );
                    internal()
                })?;
                unread_counts.insert(tid, count);
            }
        }

        // Next issue reads
        let next_issue_ids: Vec<i32> = threads_by_id
            .values()
            .filter_map(|row| {
                let next_unread_issue_id: Option<i32> = row.try_get(6).ok();
                next_unread_issue_id
            })
            .collect();
        let mut next_issue_map: std::collections::HashMap<i32, (i32, Option<String>)> =
            std::collections::HashMap::new();
        if !next_issue_ids.is_empty() {
            let issue_rows = connection
                .query(
                    "SELECT id, issue_number FROM issues WHERE id = ANY($1)",
                    &[&next_issue_ids],
                )
                .await
                .map_err(db::query_error)?;
            for row in issue_rows {
                let iid: i32 = row.try_get(0).map_err(|e| {
                    tracing::debug!(
                        error_kind = crate::error_kind(&e),
                        "preserved underlying error before mapping"
                    );
                    internal()
                })?;
                let inum: Option<String> = row.try_get(1).map_err(|e| {
                    tracing::debug!(
                        error_kind = crate::error_kind(&e),
                        "preserved underlying error before mapping"
                    );
                    internal()
                })?;
                next_issue_map.insert(iid, (iid, inum));
            }
        }

        // Tags for all thread IDs (one batched read, not one query per thread)
        let mut tags_map: std::collections::HashMap<i32, Vec<SessionTag>> =
            std::collections::HashMap::new();
        if !thread_id_list.is_empty() {
            let tag_rows = connection
                .query(TAGS_ANY_SQL, &[&thread_id_list, &user.id()])
                .await
                .map_err(db::query_error)?;
            for tag_row in &tag_rows {
                let target_id: i32 = tag_row.try_get(8).map_err(|e| {
                    tracing::debug!(
                        error_kind = crate::error_kind(&e),
                        "preserved underlying error before mapping"
                    );
                    internal()
                })?;
                let tag = SessionTag {
                    id: tag_row.try_get(0).map_err(|e| {
                        tracing::debug!(
                            error_kind = crate::error_kind(&e),
                            "preserved underlying error before mapping"
                        );
                        internal()
                    })?,
                    name: tag_row.try_get(1).map_err(|e| {
                        tracing::debug!(
                            error_kind = crate::error_kind(&e),
                            "preserved underlying error before mapping"
                        );
                        internal()
                    })?,
                    normalized_name: tag_row.try_get(2).map_err(|e| {
                        tracing::debug!(
                            error_kind = crate::error_kind(&e),
                            "preserved underlying error before mapping"
                        );
                        internal()
                    })?,
                    scope: tag_row.try_get(3).map_err(|e| {
                        tracing::debug!(
                            error_kind = crate::error_kind(&e),
                            "preserved underlying error before mapping"
                        );
                        internal()
                    })?,
                    owner_user_id: tag_row.try_get(4).map_err(|e| {
                        tracing::debug!(
                            error_kind = crate::error_kind(&e),
                            "preserved underlying error before mapping"
                        );
                        internal()
                    })?,
                    color: tag_row.try_get(5).map_err(|e| {
                        tracing::debug!(
                            error_kind = crate::error_kind(&e),
                            "preserved underlying error before mapping"
                        );
                        internal()
                    })?,
                    created_at: tag_row.try_get(6).map_err(|e| {
                        tracing::debug!(
                            error_kind = crate::error_kind(&e),
                            "preserved underlying error before mapping"
                        );
                        internal()
                    })?,
                    updated_at: tag_row.try_get(7).map_err(|e| {
                        tracing::debug!(
                            error_kind = crate::error_kind(&e),
                            "preserved underlying error before mapping"
                        );
                        internal()
                    })?,
                };
                tags_map.entry(target_id).or_default().push(tag);
            }
        }

        // Queue positions (one batched read over the whole queue)
        let mut position_map: std::collections::HashMap<i32, i32> =
            std::collections::HashMap::new();
        if !thread_id_list.is_empty() {
            let queue_rows = connection
                .query(QUEUE_POSITION_ANY_SQL, &[&user.id(), &thread_id_list])
                .await
                .map_err(db::query_error)?;
            for row in queue_rows {
                let id: i32 = row.try_get(0).map_err(|e| {
                    tracing::debug!(
                        error_kind = crate::error_kind(&e),
                        "preserved underlying error before mapping"
                    );
                    internal()
                })?;
                let seq: i32 = row.try_get(1).map_err(|e| {
                    tracing::debug!(
                        error_kind = crate::error_kind(&e),
                        "preserved underlying error before mapping"
                    );
                    internal()
                })?;
                position_map.insert(id, seq);
            }
        }

        // Build active thread for each session
        for row in sessions_to_return {
            let sid: i32 = row.try_get(0).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?;
            // Python's projection prefers the session's latest roll event over
            // the pending thread pointer; a roll without a selected thread is inert.
            let roll = latest_roll_per_session.get(&sid);
            let selected_thread_id = roll.and_then(|(tid, _)| *tid);
            let roll_result = roll.and_then(|(_, r)| *r);
            let rate = rate_agg.get(&sid);
            let issues_read = rate.map(|(count, _)| *count).filter(|count| *count > 0);
            let last_rating = rate.and_then(|(_, rating)| *rating);

            let active_candidate: Option<i32> =
                selected_thread_id.or_else(|| pending_by_session.get(&sid).copied());

            let active_thread = match active_candidate {
                None => None,
                Some(thread_id) => {
                    let thread_row = threads_by_id.get(&thread_id);
                    match thread_row {
                        None => None,
                        Some(thread_row) => {
                            let thread_owner: i32 = thread_row.try_get(7).map_err(|e| {
                                tracing::debug!(
                                    error_kind = crate::error_kind(&e),
                                    "preserved underlying error before mapping"
                                );
                                internal()
                            })?;
                            if pending_by_session.contains_key(&sid) {
                                // Pending thread: ownership already verified by query
                            } else if thread_owner != user.id() {
                                active_threads.insert(sid, None);
                                continue;
                            }

                            let thread_id_value: i32 = thread_row.try_get(0).map_err(|e| {
                                tracing::debug!(
                                    error_kind = crate::error_kind(&e),
                                    "preserved underlying error before mapping"
                                );
                                internal()
                            })?;
                            let title: String = thread_row.try_get(1).map_err(|e| {
                                tracing::debug!(
                                    error_kind = crate::error_kind(&e),
                                    "preserved underlying error before mapping"
                                );
                                internal()
                            })?;
                            let format: String = thread_row.try_get(2).map_err(|e| {
                                tracing::debug!(
                                    error_kind = crate::error_kind(&e),
                                    "preserved underlying error before mapping"
                                );
                                internal()
                            })?;
                            let stored_remaining: i32 = thread_row.try_get(3).map_err(|e| {
                                tracing::debug!(
                                    error_kind = crate::error_kind(&e),
                                    "preserved underlying error before mapping"
                                );
                                internal()
                            })?;
                            let total_issues: Option<i32> = thread_row.try_get(4).map_err(|e| {
                                tracing::debug!(
                                    error_kind = crate::error_kind(&e),
                                    "preserved underlying error before mapping"
                                );
                                internal()
                            })?;
                            let reading_progress: Option<String> =
                                thread_row.try_get(5).map_err(|e| {
                                    tracing::debug!(
                                        error_kind = crate::error_kind(&e),
                                        "preserved underlying error before mapping"
                                    );
                                    internal()
                                })?;
                            let next_unread_issue_id: Option<i32> =
                                thread_row.try_get(6).map_err(|e| {
                                    tracing::debug!(
                                        error_kind = crate::error_kind(&e),
                                        "preserved underlying error before mapping"
                                    );
                                    internal()
                                })?;

                            let issues_remaining = if total_issues.is_some() {
                                unread_counts.get(&thread_id_value).copied().unwrap_or(0)
                            } else {
                                stored_remaining
                            };

                            let (next_issue_id, next_issue_number) = match next_unread_issue_id {
                                Some(issue_id) if total_issues.is_some() => next_issue_map
                                    .get(&issue_id)
                                    .map(|(id, num)| (Some(*id), num.clone()))
                                    .unwrap_or((None, None)),
                                _ => (None, None),
                            };

                            let tags = tags_map.get(&thread_id_value).cloned().unwrap_or_default();
                            let queue_position =
                                position_map.get(&thread_id_value).copied().unwrap_or(0);
                            let safe_result = roll_result.filter(|r| *r > 0);

                            Some(SessionActiveThread {
                                id: thread_id_value,
                                title,
                                format: normalize_format(&format),
                                issues_remaining,
                                queue_position,
                                last_rolled_result: safe_result,
                                total_issues,
                                reading_progress,
                                issues_read,
                                last_rating,
                                tags,
                                issue_id: next_issue_id,
                                issue_number: next_issue_number.clone(),
                                next_issue_id,
                                next_issue_number,
                            })
                        }
                    }
                }
            };
            active_threads.insert(sid, active_thread);
        }
    } else {
        for sid in &session_ids {
            active_threads.insert(*sid, None);
        }
    }

    // Build responses
    let mut responses = Vec::with_capacity(sessions_to_return.len());
    for row in sessions_to_return {
        let sid: i32 = row.try_get(0).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let started_at: String = row.try_get(1).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let ended_at: Option<String> = row.try_get(2).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let start_die: i32 = row.try_get(3).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let manual_die: Option<i32> = row.try_get(4).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let owner_id: i32 = row.try_get(5).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let reading_bandwidth: Option<String> = row.try_get(8).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let reading_intent: Option<String> = row.try_get(9).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let reading_mode_source: Option<String> = row.try_get(10).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let reading_mode_suggested: Option<bool> = row.try_get(11).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;

        let snapshot_count = snapshot_counts.get(&sid).copied().unwrap_or(0);
        let ladder = ladder_path(
            start_die,
            ladder_values.get(&sid).map(|v| v.as_slice()).unwrap_or(&[]),
        );
        let resolved_die = match latest_die_per_session.get(&sid) {
            Some((die_after, context)) => {
                current_die(manual_die, Some((*die_after, context)), start_die)
            }
            None => current_die(manual_die, None, start_die),
        };
        let active_thread = active_threads.get(&sid).and_then(|v| v.clone());
        let last_rolled_result = active_thread
            .as_ref()
            .and_then(|t| t.last_rolled_result)
            .or_else(|| {
                action_rows.iter().find_map(|r| {
                    let action_sid: i32 = r.try_get(0).ok()?;
                    if action_sid == sid {
                        let action_type: String = r.try_get(1).ok()?;
                        if action_type == "roll" {
                            return r.try_get(3).ok().flatten();
                        }
                    }
                    None
                })
            });

        responses.push(SessionListItemResponse {
            id: sid,
            started_at,
            ended_at,
            start_die,
            manual_die,
            user_id: owner_id,
            ladder_path: ladder,
            active_thread,
            current_die: resolved_die,
            last_rolled_result,
            has_restore_point: snapshot_count > 0,
            snapshot_count,
            reading_bandwidth,
            reading_intent,
            reading_mode_source,
            reading_mode_suggested: reading_mode_suggested.unwrap_or(false),
        });
    }

    let next_page_token = if has_more && !sessions_to_return.is_empty() {
        let last_row = &sessions_to_return[sessions_to_return.len() - 1];
        let last_started_at: String = last_row.try_get(1).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let last_id: i32 = last_row.try_get(0).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        Some(format!("{},{}", last_started_at, last_id))
    } else {
        None
    };

    Ok(Json(SessionHistoryListResponse {
        sessions: responses,
        next_page_token,
    }))
}

/// `GET /api/sessions/current/` and `GET /api/v1/sessions/current/` - current active session.
pub async fn get_current_session(
    user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
) -> Result<Json<SessionCurrentResponse>, ApiError> {
    let connection = db::checkout(&state).await?;

    // Get or create current session (same logic as Python). Python's
    // GET /sessions/current/ resolves through `get_or_create`, so a new account
    // gets a session created on the read. Preserve that same-path behavior here
    // instead of answering 404: initialize() is the transactional get-or-create
    // with the same 6h gap policy and session-start snapshot as Python.
    let gap_cutoff = chrono::Utc::now().timestamp() as f64 - 6.0 * 3600.0;
    let active_row = connection
        .query_opt(CURRENT_SESSION_SQL, &[&user.id(), &gap_cutoff])
        .await
        .map_err(db::query_error)?;
    let session_row = match active_row {
        Some(row) => row,
        None => {
            reading_session::initialize(&state, user, None, SessionPolicy::default()).await?;
            connection
                .query_opt(CURRENT_SESSION_SQL, &[&user.id(), &gap_cutoff])
                .await
                .map_err(db::query_error)?
                .ok_or_else(not_found)?
        }
    };

    let session_id: i32 = session_row.try_get(0).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let started_at: String = session_row.try_get(1).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let ended_at: Option<String> = session_row.try_get(2).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let start_die: i32 = session_row.try_get(3).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let manual_die: Option<i32> = session_row.try_get(4).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let owner_id: i32 = session_row.try_get(5).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let pending_thread_id: Option<i32> = session_row.try_get(6).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let timezone: Option<String> = session_row.try_get(7).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let reading_bandwidth: Option<String> = session_row.try_get(8).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let reading_intent: Option<String> = session_row.try_get(9).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let reading_mode_source: Option<String> = session_row.try_get(10).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let reading_mode_suggested: Option<bool> = session_row.try_get(11).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let predicted_bandwidth: Option<String> = session_row.try_get(12).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let active_bandwidth: Option<String> = session_row.try_get(13).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let bandwidth_confidence: Option<f64> = session_row.try_get(14).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let bandwidth_source: Option<String> = session_row.try_get(15).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let bandwidth_version: Option<String> = session_row.try_get(16).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let predicted_intent: Option<String> = session_row.try_get(17).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let active_intent: Option<String> = session_row.try_get(18).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let intent_confidence: Option<f64> = session_row.try_get(19).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let intent_source: Option<String> = session_row.try_get(20).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let intent_version: Option<String> = session_row.try_get(21).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;

    // Snapshot count
    let snapshot_count: i32 = connection
        .query_one(SNAPSHOT_COUNT_ONE_SQL, &[&session_id])
        .await
        .map_err(db::query_error)?
        .try_get(0)
        .map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;

    // Ladder path
    let ladder_sql = LADDER_SQL.replace("session_id = ANY($1)", "session_id = $1");
    let ladder_rows = connection
        .query(&ladder_sql, &[&session_id])
        .await
        .map_err(db::query_error)?;
    let ladder_values: Vec<i32> = ladder_rows
        .iter()
        .map(|row| {
            row.try_get(1).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })
        })
        .collect::<Result<_, ApiError>>()?;
    let ladder = ladder_path(start_die, &ladder_values);

    // Current die (Python resolves die across the reader's events, not just
    // this session: Rust commands write sessionless die events)
    let current_die_sql =
        "SELECT session_id, die_after, context::text FROM events WHERE (user_id = $1 OR session_id = $2) AND type IN ('rate','snooze','undo','reset_dice','manual_die') AND die_after IS NOT NULL ORDER BY timestamp DESC, id DESC LIMIT 1";
    let die_row = connection
        .query_opt(current_die_sql, &[&user.id(), &session_id])
        .await
        .map_err(db::query_error)?;
    let resolved_die = match die_row {
        Some(row) => {
            let die_after: i32 = row.try_get(1).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?;
            let context_text: Option<String> = row.try_get(2).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?;
            let context: Value = context_text
                .as_deref()
                .and_then(|text| serde_json::from_str(text).ok())
                .unwrap_or(Value::Null);
            let owned = context;
            current_die(manual_die, Some((die_after, &owned)), start_die)
        }
        None => current_die(manual_die, None, start_die),
    };

    // Latest action event
    let latest_action_sql =
        LATEST_ACTION_SQL.replace("session_id = ANY($1)", "session_id = $1") + " LIMIT 1";
    let action_row = connection
        .query_opt(&latest_action_sql, &[&session_id])
        .await
        .map_err(db::query_error)?;
    let (action_type, selected_thread_id, roll_result) = match action_row {
        Some(row) => (
            row.try_get(1).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?,
            row.try_get(2).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?,
            row.try_get(3).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?,
        ),
        None => (String::new(), None, None),
    };
    let is_roll = action_type == "roll";

    // Active thread
    let active_candidate: Option<i32> = if pending_thread_id.is_some() {
        pending_thread_id
    } else if is_roll {
        selected_thread_id
    } else {
        None
    };
    let active_thread = match active_candidate {
        None => None,
        Some(thread_id) => {
            let thread_row = if pending_thread_id.is_some() {
                connection
                    .query_opt(PENDING_THREAD_SQL, &[&thread_id, &user.id()])
                    .await
                    .map_err(db::query_error)?
            } else {
                connection
                    .query_opt(ROLLED_THREAD_SQL, &[&thread_id])
                    .await
                    .map_err(db::query_error)?
            };
            match thread_row {
                None => None,
                Some(thread_row) => {
                    let thread_owner: i32 = thread_row.try_get(7).map_err(|e| {
                        tracing::debug!(
                            error_kind = crate::error_kind(&e),
                            "preserved underlying error before mapping"
                        );
                        internal()
                    })?;
                    if pending_thread_id.is_none() && thread_owner != owner_id {
                        None
                    } else {
                        let thread_id_value: i32 = thread_row.try_get(0).map_err(|e| {
                            tracing::debug!(
                                error_kind = crate::error_kind(&e),
                                "preserved underlying error before mapping"
                            );
                            internal()
                        })?;
                        let title: String = thread_row.try_get(1).map_err(|e| {
                            tracing::debug!(
                                error_kind = crate::error_kind(&e),
                                "preserved underlying error before mapping"
                            );
                            internal()
                        })?;
                        let format: String = thread_row.try_get(2).map_err(|e| {
                            tracing::debug!(
                                error_kind = crate::error_kind(&e),
                                "preserved underlying error before mapping"
                            );
                            internal()
                        })?;
                        let stored_remaining: i32 = thread_row.try_get(3).map_err(|e| {
                            tracing::debug!(
                                error_kind = crate::error_kind(&e),
                                "preserved underlying error before mapping"
                            );
                            internal()
                        })?;
                        let total_issues: Option<i32> = thread_row.try_get(4).map_err(|e| {
                            tracing::debug!(
                                error_kind = crate::error_kind(&e),
                                "preserved underlying error before mapping"
                            );
                            internal()
                        })?;
                        let reading_progress: Option<String> =
                            thread_row.try_get(5).map_err(|e| {
                                tracing::debug!(
                                    error_kind = crate::error_kind(&e),
                                    "preserved underlying error before mapping"
                                );
                                internal()
                            })?;
                        let next_unread_issue_id: Option<i32> =
                            thread_row.try_get(6).map_err(|e| {
                                tracing::debug!(
                                    error_kind = crate::error_kind(&e),
                                    "preserved underlying error before mapping"
                                );
                                internal()
                            })?;

                        let issues_remaining = if total_issues.is_some() {
                            connection
                                .query_one(UNREAD_COUNT_SQL, &[&thread_id_value])
                                .await
                                .map_err(db::query_error)?
                                .try_get(0)
                                .map_err(|e| {
                                    tracing::debug!(
                                        error_kind = crate::error_kind(&e),
                                        "preserved underlying error before mapping"
                                    );
                                    internal()
                                })?
                        } else {
                            stored_remaining
                        };

                        let (next_issue_id, next_issue_number) = match next_unread_issue_id {
                            Some(issue_id) if total_issues.is_some() => {
                                let issue_row = connection
                                    .query_opt(NEXT_ISSUE_SQL, &[&issue_id])
                                    .await
                                    .map_err(db::query_error)?;
                                match issue_row {
                                    Some(issue_row) => (
                                        Some(issue_row.try_get(0).map_err(|e| {
                                            tracing::debug!(
                                                error_kind = crate::error_kind(&e),
                                                "preserved underlying error before mapping"
                                            );
                                            internal()
                                        })?),
                                        issue_row.try_get(1).map_err(|e| {
                                            tracing::debug!(
                                                error_kind = crate::error_kind(&e),
                                                "preserved underlying error before mapping"
                                            );
                                            internal()
                                        })?,
                                    ),
                                    None => (None, None),
                                }
                            }
                            _ => (None, None),
                        };

                        let tag_rows = connection
                            .query(TAGS_SQL, &[&thread_id_value, &user.id()])
                            .await
                            .map_err(db::query_error)?;
                        let mut tags = Vec::with_capacity(tag_rows.len());
                        for tag_row in &tag_rows {
                            tags.push(SessionTag {
                                id: tag_row.try_get(0).map_err(|e| {
                                    tracing::debug!(
                                        error_kind = crate::error_kind(&e),
                                        "preserved underlying error before mapping"
                                    );
                                    internal()
                                })?,
                                name: tag_row.try_get(1).map_err(|e| {
                                    tracing::debug!(
                                        error_kind = crate::error_kind(&e),
                                        "preserved underlying error before mapping"
                                    );
                                    internal()
                                })?,
                                normalized_name: tag_row.try_get(2).map_err(|e| {
                                    tracing::debug!(
                                        error_kind = crate::error_kind(&e),
                                        "preserved underlying error before mapping"
                                    );
                                    internal()
                                })?,
                                scope: tag_row.try_get(3).map_err(|e| {
                                    tracing::debug!(
                                        error_kind = crate::error_kind(&e),
                                        "preserved underlying error before mapping"
                                    );
                                    internal()
                                })?,
                                owner_user_id: tag_row.try_get(4).map_err(|e| {
                                    tracing::debug!(
                                        error_kind = crate::error_kind(&e),
                                        "preserved underlying error before mapping"
                                    );
                                    internal()
                                })?,
                                color: tag_row.try_get(5).map_err(|e| {
                                    tracing::debug!(
                                        error_kind = crate::error_kind(&e),
                                        "preserved underlying error before mapping"
                                    );
                                    internal()
                                })?,
                                created_at: tag_row.try_get(6).map_err(|e| {
                                    tracing::debug!(
                                        error_kind = crate::error_kind(&e),
                                        "preserved underlying error before mapping"
                                    );
                                    internal()
                                })?,
                                updated_at: tag_row.try_get(7).map_err(|e| {
                                    tracing::debug!(
                                        error_kind = crate::error_kind(&e),
                                        "preserved underlying error before mapping"
                                    );
                                    internal()
                                })?,
                            });
                        }

                        let queue_row = connection
                            .query_opt(QUEUE_POSITION_SQL, &[&user.id(), &thread_id_value])
                            .await
                            .map_err(db::query_error)?;
                        let queue_position: i32 = match queue_row {
                            Some(row) => row.try_get(0).map_err(|e| {
                                tracing::debug!(
                                    error_kind = crate::error_kind(&e),
                                    "preserved underlying error before mapping"
                                );
                                internal()
                            })?,
                            None => 0,
                        };
                        let safe_result = roll_result.filter(|r| *r > 0);

                        Some(SessionActiveThread {
                            id: thread_id_value,
                            title,
                            format: normalize_format(&format),
                            issues_remaining,
                            queue_position,
                            last_rolled_result: safe_result,
                            total_issues,
                            reading_progress,
                            issues_read: None,
                            last_rating: None,
                            tags,
                            issue_id: next_issue_id,
                            issue_number: next_issue_number.clone(),
                            next_issue_id,
                            next_issue_number,
                        })
                    }
                }
            }
        }
    };

    // Snoozed and skipped threads (json id arrays on the session row)
    let snoozed_ids = json_id_list(session_row.try_get::<_, Option<Value>>(22).ok().flatten());
    let skipped_ids = json_id_list(session_row.try_get::<_, Option<Value>>(23).ok().flatten());
    let all_thread_ids = {
        let mut ids = snoozed_ids.clone();
        ids.extend(skipped_ids.iter().copied());
        ids.sort_unstable();
        ids.dedup();
        ids
    };
    let mut threads_title_by_id: std::collections::HashMap<i32, String> =
        std::collections::HashMap::new();
    if !all_thread_ids.is_empty() {
        let rows = connection
            .query(
                "SELECT id, title FROM threads WHERE id = ANY($1)",
                &[&all_thread_ids],
            )
            .await
            .map_err(db::query_error)?;
        for row in &rows {
            let id: i32 = row.try_get(0).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?;
            let title: String = row.try_get(1).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?;
            threads_title_by_id.insert(id, title);
        }
    }
    let snoozed_threads = snoozed_ids
        .iter()
        .filter_map(|id| {
            threads_title_by_id
                .get(id)
                .map(|title| SessionThreadSummary {
                    id: *id,
                    title: title.clone(),
                })
        })
        .collect();
    let skipped_threads = skipped_ids
        .iter()
        .filter_map(|id| {
            threads_title_by_id
                .get(id)
                .map(|title| SessionThreadSummary {
                    id: *id,
                    title: title.clone(),
                })
        })
        .collect();

    Ok(Json(SessionCurrentResponse {
        id: session_id,
        started_at,
        ended_at,
        start_die,
        manual_die,
        user_id: owner_id,
        ladder_path: ladder,
        active_thread: active_thread.clone(),
        current_die: resolved_die,
        last_rolled_result: active_thread
            .as_ref()
            .and_then(|thread| thread.last_rolled_result),
        has_restore_point: snapshot_count > 0,
        snapshot_count,
        snoozed_thread_ids: snoozed_ids,
        snoozed_threads,
        skipped_thread_ids: skipped_ids,
        skipped_threads,
        pending_thread_id,
        timezone,
        reading_bandwidth,
        reading_intent,
        reading_mode_source,
        reading_mode_suggested: reading_mode_suggested.unwrap_or(false),
        bandwidth: Some(bandwidth_state(
            predicted_bandwidth.as_deref(),
            active_bandwidth.as_deref(),
            bandwidth_confidence,
            bandwidth_source.as_deref(),
            bandwidth_version.as_deref(),
        )),
        intent: Some(intent_state(
            predicted_intent.as_deref(),
            active_intent.as_deref(),
            intent_confidence,
            intent_source.as_deref(),
            intent_version.as_deref(),
        )),
    }))
}

/// Documentation-only operation for the unversioned list.
#[utoipa::path(
    get,
    path = "/api/sessions/",
    tag = "sessions",
    params(SessionListParams),
    responses(
        (status = 200, description = "Paginated session history", body = SessionHistoryListResponse),
        (status = 401, description = "Not authenticated"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_sessions_documentation() {}

/// Documentation-only operation for the versioned list.
#[utoipa::path(
    get,
    path = "/api/v1/sessions/",
    tag = "sessions",
    params(SessionListParams),
    responses(
        (status = 200, description = "Paginated session history", body = SessionHistoryListResponse),
        (status = 401, description = "Not authenticated"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_sessions_v1_documentation() {}

/// Documentation-only operation for the unversioned current session.
#[utoipa::path(
    get,
    path = "/api/sessions/current/",
    tag = "sessions",
    responses(
        (status = 200, description = "Current active session", body = SessionCurrentResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Session not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_current_session_documentation() {}

/// Documentation-only operation for the versioned current session.
#[utoipa::path(
    get,
    path = "/api/v1/sessions/current/",
    tag = "sessions",
    responses(
        (status = 200, description = "Current active session", body = SessionCurrentResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Session not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_current_session_v1_documentation() {}

/// OpenAPI document for the session list/current same-path surface.
#[derive(utoipa::OpenApi)]
#[openapi(
    paths(
        list_sessions_documentation,
        list_sessions_v1_documentation,
        get_current_session_documentation,
        get_current_session_v1_documentation
    ),
    components(schemas(
        SessionListParams,
        SessionTag,
        SessionActiveThread,
        SessionBandwidthState,
        SessionIntentState,
        SessionThreadSummary,
        SessionListItemResponse,
        SessionHistoryListResponse,
        SessionCurrentResponse
    )),
    modifiers(&SessionListSecurityAddon)
)]
pub struct SessionListApi;

struct SessionListSecurityAddon;

impl utoipa::Modify for SessionListSecurityAddon {
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
    use crate::{db, test_support};
    use utoipa::OpenApi;

    #[test]
    fn session_list_params_serialize() {
        let params = SessionListParams {
            page_size: None,
            page_token: None,
        };
        assert_eq!(params.page_size, None);
        assert_eq!(params.page_token.as_deref(), None);
        let params = SessionListParams {
            page_size: Some(250),
            page_token: Some("2026-11-01T00:00:00Z,7".to_string()),
        };
        assert_eq!(params.page_size, Some(250));
        assert_eq!(params.page_token.as_deref(), Some("2026-11-01T00:00:00Z,7"));
    }

    #[test]
    fn session_list_openapi_covers_both_same_paths() {
        let document = serde_json::to_value(SessionListApi::openapi()).expect("openapi");
        let paths = document["paths"].as_object().expect("paths");
        assert!(paths.contains_key("/api/sessions/"));
        assert!(paths.contains_key("/api/v1/sessions/"));
        assert!(paths.contains_key("/api/sessions/current/"));
        assert!(paths.contains_key("/api/v1/sessions/current/"));
        for path in [
            "/api/sessions/",
            "/api/v1/sessions/",
            "/api/sessions/current/",
            "/api/v1/sessions/current/",
        ] {
            let operation = &document["paths"][path]["get"];
            assert!(operation["operationId"].is_string());
            assert!(operation["responses"]["200"].as_object().is_some());
            assert!(operation["security"].is_array());
        }
        assert!(document["components"]["schemas"]["SessionHistoryListResponse"].is_object());
        assert!(document["components"]["schemas"]["SessionCurrentResponse"].is_object());
        assert!(document["components"]["schemas"]["SessionListItemResponse"].is_object());
    }

    async fn database_fixture() -> (
        Arc<AppState>,
        AuthenticatedUser,
        tokio::sync::MutexGuard<'static, ()>,
    ) {
        let state = test_support::test_state(2)
            .await
            .expect("RUST_ROLL_TEST_DATABASE_URL is required");
        let guard = test_support::reset_for_test(&state).await;
        let connection = db::checkout(&state).await.expect("fixture connection");
        connection
            .batch_execute(
                "INSERT INTO users (id, username) VALUES (9101, 'session-list-test'), (9102, 'session-list-other');
                 INSERT INTO threads (id, user_id, title, format, issues_remaining, total_issues, reading_progress, queue_position, status, is_blocked) VALUES (9201, 9101, 'Owned Comic', 'comics', 3, NULL, NULL, 1, 'active', false), (9202, 9102, 'Foreign Comic', 'Comic', 2, NULL, NULL, 1, 'active', false);
                 INSERT INTO sessions (id, user_id, started_at, ended_at, start_die, manual_die, pending_thread_id, reading_mode_suggested) VALUES (9301, 9101, NOW(), NULL, 6, NULL, 9201, false), (9302, 9102, NOW(), NULL, 6, NULL, 9202, false), (9303, 9101, NOW(), NULL, 6, NULL, NULL, false);
                 INSERT INTO events (session_id, type, timestamp, selected_thread_id, thread_id, die, die_after, result) VALUES (9301, 'roll', NOW(), 9201, NULL, 6, NULL, 4), (9301, 'rate', NOW() + interval '1 minute', NULL, 9201, 6, 4, NULL), (9303, 'roll', NOW(), 9201, NULL, 6, NULL, 2);",
            )
            .await
            .expect("seed session list fixture");
        drop(connection);
        (state, AuthenticatedUser::for_test(9101), guard)
    }

    #[tokio::test]
    async fn list_sessions_returns_owned_sessions_to_disposable_postgres() {
        let (state, user, _guard) = database_fixture().await;
        let Json(response) = list_sessions(
            Query(SessionListParams {
                page_size: Some(50),
                page_token: None,
            }),
            user,
            State(state.clone()),
        )
        .await
        .expect("list sessions");
        assert_eq!(response.sessions.len(), 2);
        // Both sessions share the fixture's statement timestamp, so the
        // started_at DESC, id DESC tie-break puts the higher id first.
        assert_eq!(response.sessions[0].id, 9303);
        assert_eq!(response.sessions[0].user_id, 9101);
        assert_eq!(response.sessions[0].start_die, 6);
        assert_eq!(response.sessions[1].id, 9301);
        assert!(response.next_page_token.is_none());
    }

    #[tokio::test]
    async fn list_sessions_page_token_round_trip_returns_next_page() {
        let (state, user, _guard) = database_fixture().await;
        let Json(first) = list_sessions(
            Query(SessionListParams {
                page_size: Some(1),
                page_token: None,
            }),
            user,
            State(state.clone()),
        )
        .await
        .expect("first page");
        assert_eq!(first.sessions.len(), 1);
        let token = first.next_page_token.expect("a page-2 token");
        let Json(second) = list_sessions(
            Query(SessionListParams {
                page_size: Some(1),
                page_token: Some(token),
            }),
            user,
            State(state.clone()),
        )
        .await
        .expect("page_token must round-trip");
        assert_eq!(second.sessions.len(), 1);
        assert_ne!(second.sessions[0].id, first.sessions[0].id);
    }

    #[tokio::test]
    async fn list_sessions_page_token_rejects_garbage() {
        let (state, user, _guard) = database_fixture().await;
        let error = list_sessions(
            Query(SessionListParams {
                page_size: Some(1),
                page_token: Some("not-a-cursor".to_string()),
            }),
            user,
            State(state.clone()),
        )
        .await
        .expect_err("garbage token must 400");
        assert_eq!(error.status(), StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn list_sessions_rejects_foreign_sessions() {
        let (state, user, _guard) = database_fixture().await;
        let Json(response) = list_sessions(
            Query(SessionListParams {
                page_size: Some(50),
                page_token: None,
            }),
            user,
            State(state.clone()),
        )
        .await
        .expect("list sessions");
        // Should only return sessions for user 9101
        for session in &response.sessions {
            assert_eq!(session.user_id, 9101);
        }
    }

    #[tokio::test]
    async fn get_current_session_returns_owned_projection_to_disposable_postgres() {
        let (state, user, _guard) = database_fixture().await;
        let Json(response) = get_current_session(user, State(state.clone()))
            .await
            .expect("current session");
        assert_eq!(response.id, 9301);
        assert_eq!(response.user_id, 9101);
        assert_eq!(response.start_die, 6);
        assert_eq!(response.current_die, 4);
        assert_eq!(response.ladder_path, "6 → 4");
        assert_eq!(response.snapshot_count, 0);
        assert!(!response.has_restore_point);
        let active = response.active_thread.expect("pending active thread");
        assert_eq!(active.id, 9201);
        assert_eq!(active.title, "Owned Comic");
        assert_eq!(active.format, "Comic");
        assert_eq!(active.issues_remaining, 3);
        assert_eq!(active.queue_position, 1);
        assert_eq!(active.last_rolled_result, None);
        assert_eq!(active.issues_read, None);
        assert_eq!(active.last_rating, None);
    }

    #[tokio::test]
    async fn get_current_session_creates_session_for_account_with_no_session() {
        let (state, _user, _guard) = database_fixture().await;
        let connection = db::checkout(&state).await.expect("fixture connection");
        connection
            .execute(
                "INSERT INTO users (id, username) VALUES (9103, 'new-account-parity')",
                &[],
            )
            .await
            .expect("seed new account without a session");
        drop(connection);

        // Python's GET /sessions/current/ uses get_or_create, so a new account
        // gets a session created on the read instead of a 404.
        let Json(response) =
            get_current_session(AuthenticatedUser::for_test(9103), State(state.clone()))
                .await
                .expect("current session created on read");
        assert_eq!(response.user_id, 9103);

        let connection = db::checkout(&state).await.expect("fixture connection");
        let count: i64 = connection
            .query_one(
                "SELECT count(*)::bigint FROM sessions WHERE user_id = 9103",
                &[],
            )
            .await
            .expect("count created sessions")
            .get(0);
        assert_eq!(
            count, 1,
            "exactly one session should be created on the read"
        );
    }
}
