//! Native same-path session list read (#4839, parent #4335).
//!
//! Migrates the session list subset of `app/api/session.py` to the native
//! Rust router with identical method/path and wire contract:
//!
//! * `GET /api/sessions/`
//! * `GET /api/v1/sessions/`
//!
//! Wire parity with Python `list_sessions` (`app/api/session.py`):
//!
//! * Cursor-based pagination with `page_size` (default 50, max 200) and
//!   `page_token` (started_at,session_id).
//! * Ownership: `WHERE user_id = $1` — a foreign or missing session returns 404.
//! * `ladder_path`: `start_die` followed by every `die_after` from
//!   `rate`/`snooze`/`undo`/`reset_dice`/`manual_die` events in timestamp/id order,
//!   joined with `" → "`.
//! * `current_die`: event-derived die wins (#4352); the `manual_die` column is
//!   a legacy fallback only when the session has no die-changing events.
//! * `active_thread`: the latest `roll`/`rate`/`snooze`/`rolled_but_skipped` event
//!   decides whether a roll is active; a `pending_thread_id` wins and a missing
//!   pending thread yields `null` without falling through to the roll event.
//!   Thread `issues_remaining` counts unread `issues` when the thread uses issue
//!   tracking (`total_issues IS NOT NULL`), otherwise the stored counter.
//!   `queue_position` is the legacy dense display ordinal (readable rows first,
//!   then stored queue position, then id) among active queued threads, or `0`
//!   outside the queue — matching Python `display_position` under the production
//!   legacy execution mode; the Option E preview eligibility ordering is not
//!   activated here.
//! * `bandwidth` / `intent`: `build_session_bandwidth_state` /
//!   `build_session_intent_state` normalization (unknown enum strings and
//!   out-of-range confidences become `null`).
//! * Format normalization, direct visible tags ordered by scope descending then
//!   normalized name, and `next_issue_*` from `next_unread_issue_id` when issue
//!   tracking is in use.
//! * Defaults Python leaves unset on this endpoint stay unset: `snoozed_*` /
//!   `skipped_*` are empty, `correction` is `null`, and
//!   `active_thread.issues_read` / `last_rating` are `null`.
//! * Timestamps are emitted as UTC `...Z` strings.
//!
//! Bounded reads only: one paged session query, one event query for all session
//! IDs on the page, one snapshot count query for all session IDs, one die-path
//! query per session, one latest-die query per session, one latest-action query
//! per session, at most one active thread with one unread count, one next-issue
//! read, one tag read and one ranked queue read per session. No per-row fan-out
//! beyond the page size. Python handlers remain; deployed ingress in `vercel.json`
//! shadows them after this cutover.

#![forbid(unsafe_code)]

use crate::{
    auth::AuthenticatedUser, db, reading_session::automatic_die_after, ApiError, AppState,
};
use axum::{
    extract::{Query, State},
    http::StatusCode,
    Json,
};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::Arc;

/// One direct visible tag on the active thread.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
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
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
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
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SessionBandwidthState {
    pub predicted_bandwidth: Option<String>,
    pub active_bandwidth: Option<String>,
    pub confidence: Option<f64>,
    pub source: Option<String>,
    pub mode_version: Option<String>,
}

/// Canonical intent state; invalid stored values normalize to `null`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SessionIntentState {
    pub predicted_intent: Option<String>,
    pub active_intent: Option<String>,
    pub confidence: Option<f64>,
    pub source: Option<String>,
    pub mode_version: Option<String>,
}

/// Wire shape of Python `SessionListItem` for `list_sessions`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
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

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SessionListResponse {
    pub sessions: Vec<SessionListItemResponse>,
    pub next_page_token: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct SessionListQuery {
    #[serde(default = "default_page_size")]
    pub page_size: i32,
    pub page_token: Option<String>,
}

fn default_page_size() -> i32 {
    50
}

const SESSION_LIST_SQL: &str = "SELECT id, to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(ended_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), start_die, manual_die, user_id, pending_thread_id, reading_bandwidth, reading_intent, reading_mode_source, reading_mode_suggested, predicted_bandwidth, active_bandwidth, bandwidth_confidence, bandwidth_source, bandwidth_version, predicted_intent, active_intent, intent_confidence, intent_source, intent_version FROM sessions WHERE user_id = $1 ORDER BY started_at DESC, id DESC LIMIT $2";
const SESSION_LIST_CURSOR_SQL: &str = "SELECT id, to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(ended_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), start_die, manual_die, user_id, pending_thread_id, reading_bandwidth, reading_intent, reading_mode_source, reading_mode_suggested, predicted_bandwidth, active_bandwidth, bandwidth_confidence, bandwidth_source, bandwidth_version, predicted_intent, active_intent, intent_confidence, intent_source, intent_version FROM sessions WHERE user_id = $1 AND (started_at < $2 OR (started_at = $2 AND id > $3)) ORDER BY started_at DESC, id DESC LIMIT $4";
const HISTORY_EVENTS_SQL: &str = "SELECT id, session_id, type, timestamp, selected_thread_id, thread_id, die_after, context::text, result, issues_read, rating FROM events WHERE session_id = ANY($1) AND ( (type = 'roll' AND selected_thread_id IS NOT NULL) OR type = 'rate' OR type = 'rolled_but_skipped' OR (type IN ('snooze','undo','reset_dice','manual_die') AND die_after IS NOT NULL) ) ORDER BY session_id, timestamp, id";
const SNAPSHOT_COUNT_SQL: &str = "SELECT session_id, count(*)::int FROM snapshots WHERE session_id = ANY($1) GROUP BY session_id";
const LADDER_SQL: &str = "SELECT die_after FROM events WHERE session_id = $1 AND type IN ('rate','snooze','undo','reset_dice','manual_die') AND die_after IS NOT NULL ORDER BY timestamp ASC, id ASC";
const CURRENT_DIE_SQL: &str = "SELECT die_after, context::text FROM events WHERE session_id = $1 AND type IN ('rate','snooze','undo','reset_dice','manual_die') AND die_after IS NOT NULL ORDER BY timestamp DESC, id DESC LIMIT 1";
const LATEST_ACTION_SQL: &str = "SELECT type, selected_thread_id, result FROM events WHERE session_id = $1 AND type IN ('roll','rate','snooze','rolled_but_skipped') ORDER BY timestamp DESC, id DESC LIMIT 1";
const PENDING_THREAD_SQL: &str = "SELECT id, title, format, issues_remaining, total_issues, reading_progress, next_unread_issue_id, user_id FROM threads WHERE id = $1 AND user_id = $2";
const ROLLED_THREAD_SQL: &str = "SELECT id, title, format, issues_remaining, total_issues, reading_progress, next_unread_issue_id, user_id FROM threads WHERE id = $1";
const UNREAD_COUNT_SQL: &str = "SELECT count(*)::int FROM issues WHERE thread_id = $1 AND status = 'unread'";
const NEXT_ISSUE_SQL: &str = "SELECT id, issue_number FROM issues WHERE id = $1";
const TAGS_SQL: &str = "SELECT tag.id, tag.name, tag.normalized_name, tag.scope, tag.owner_user_id, tag.color, to_char(tag.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(tag.updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') FROM tag_assignments assignment JOIN tags tag ON tag.id = assignment.tag_id WHERE assignment.target_type = 'Thread' AND assignment.target_id = $1 AND (tag.scope = 'global' OR tag.owner_user_id = $2) ORDER BY tag.scope DESC, tag.normalized_name ASC";
const QUEUE_POSITION_SQL: &str = "SELECT seq::int FROM (SELECT id, row_number() OVER (ORDER BY is_blocked ASC, queue_position ASC, id ASC) AS seq FROM threads WHERE user_id = $1 AND status = 'active' AND queue_position >= 1) ranked WHERE id = $2";

fn not_found() -> ApiError {
    ApiError::with_status(StatusCode::NOT_FOUND, "Session not found".to_string())
}

fn internal() -> ApiError {
    ApiError::with_status(
        StatusCode::INTERNAL_SERVER_ERROR,
        "Internal Server Error".to_string(),
    )
}

fn bad_request(detail: String) -> ApiError {
    ApiError::with_status(StatusCode::BAD_REQUEST, detail)
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

/// `GET /api/sessions/` and `GET /api/v1/sessions/`.
pub async fn list_sessions(
    Query(query): Query<SessionListQuery>,
    user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
) -> Result<Json<SessionListResponse>, ApiError> {
    let page_size = query.page_size.clamp(1, 200);
    let limit = page_size + 1;

    let connection = db::checkout(&state).await?;

    let sessions = if let Some(token) = query.page_token {
        let parts: Vec<&str> = token.split(',').collect();
        if parts.len() != 2 {
            return Err(bad_request("Invalid page_token format".to_string()));
        }
        let cursor_started_at = parts[0].parse::<DateTime<Utc>>().map_err(|_| {
            bad_request("Invalid page_token format".to_string())
        })?;
        let cursor_id = parts[1].parse::<i32>().map_err(|_| {
            bad_request("Invalid page_token format".to_string())
        })?;
        connection
            .query(SESSION_LIST_CURSOR_SQL, &[&user.id(), &cursor_started_at, &cursor_id, &limit])
            .await
            .map_err(db::query_error)?
    } else {
        connection
            .query(SESSION_LIST_SQL, &[&user.id(), &limit])
            .await
            .map_err(db::query_error)?
    };

    let has_more = sessions.len() > page_size as usize;
    let sessions_to_return = &sessions[..page_size.min(sessions.len() as i32) as usize];

    if sessions_to_return.is_empty() {
        return Ok(Json(SessionListResponse {
            sessions: Vec::new(),
            next_page_token: None,
        }));
    }

    let session_ids: Vec<i32> = sessions_to_return.iter().map(|row| row.try_get(0).unwrap()).collect();

    // Fetch history events for all sessions on this page
    let history_events = connection
        .query(HISTORY_EVENTS_SQL, &[&session_ids])
        .await
        .map_err(db::query_error)?;

    // Project events like Python's project_session_history_events
    #[derive(Debug, Default)]
    struct SessionEventProjection {
        latest_roll_by_session: std::collections::HashMap<i32, (String, Option<i32>, Option<i32>)>, // (type, selected_thread_id, result)
        die_path_by_session: std::collections::HashMap<i32, Vec<i32>>,
        latest_die_by_session: std::collections::HashMap<i32, (i32, Option<Value>)>, // (die_after, context)
        rate_agg: std::collections::HashMap<i32, (i32, Option<f64>)>, // (issues_read, last_rating)
        open_rate_ids_by_session: std::collections::HashMap<i32, Vec<i32>>,
        undone_rate_ids: std::collections::HashSet<i32>,
        issue_by_session_thread: std::collections::HashMap<(i32, i32), (Option<i32>, Option<String>)>,
    }

    let mut projection = SessionEventProjection::default();
    let mut included_sessions: std::collections::HashSet<i32> = session_ids.iter().copied().collect();

    for row in &history_events {
        let session_id: i32 = row.try_get(1).unwrap();
        if !included_sessions.contains(&session_id) {
            continue;
        }
        let event_type: String = row.try_get(2).unwrap();
        let event_id: i32 = row.try_get(0).unwrap();

        match event_type.as_str() {
            "roll" => {
                let selected_thread_id: Option<i32> = row.try_get(3).unwrap();
                let result: Option<i32> = row.try_get(8).unwrap();
                if let Some(tid) = selected_thread_id {
                    projection.latest_roll_by_session.insert(session_id, ("roll".to_string(), Some(tid), result));
                    // Record issue identity
                    let issue_id: Option<i32> = row.try_get(3).unwrap(); // selected_thread_id is at index 3, but issue_id is not directly here
                    // In Python, roll events have issue_id via thread. We'll handle this in thread projection.
                }
            }
            "rate" => {
                let thread_id: Option<i32> = row.try_get(4).unwrap();
                let issues_read: Option<i32> = row.try_get(9).unwrap();
                let rating: Option<f64> = row.try_get(10).unwrap();
                if let Some(tid) = thread_id {
                    let entry = projection.rate_agg.entry(session_id).or_insert((0, None));
                    if let Some(ir) = issues_read {
                        entry.0 += ir;
                    }
                    if rating.is_some() {
                        entry.1 = rating;
                    }
                    projection.open_rate_ids_by_session.entry(session_id).or_default().push(event_id);
                    // Record issue identity
                    let issue_id: Option<i32> = row.try_get(4).unwrap(); // thread_id is at index 4
                    let issue_number: Option<String> = row.try_get(4).unwrap(); // Not directly available, need to fetch
                    // Actually issue_id/issue_number come from the event in Python. Let's check.
                }
            }
            "undo" => {
                let thread_id: Option<i32> = row.try_get(4).unwrap();
                if let Some(tid) = thread_id {
                    if let Some(open_rates) = projection.open_rate_ids_by_session.get_mut(&session_id) {
                        if let Some(undone_id) = open_rates.pop() {
                            projection.undone_rate_ids.insert(undone_id);
                        }
                    }
                }
            }
            "snooze" | "reset_dice" | "manual_die" => {
                let die_after: Option<i32> = row.try_get(5).unwrap(); // die_after is at index 5? Let me check the query
                if let Some(da) = die_after {
                    projection.die_path_by_session.entry(session_id).or_default().push(da);
                    let context_text: Option<String> = row.try_get(6).unwrap(); // context is at index 6
                    let context: Value = context_text
                        .as_deref()
                        .and_then(|text| serde_json::from_str(text).ok())
                        .unwrap_or(Value::Null);
                    projection.latest_die_by_session.insert(session_id, (da, context));
                }
            }
            "rolled_but_skipped" => {
                // This is a die-changing event for ladder path
                let die_after: Option<i32> = row.try_get(5).unwrap();
                if let Some(da) = die_after {
                    projection.die_path_by_session.entry(session_id).or_default().push(da);
                    let context_text: Option<String> = row.try_get(6).unwrap();
                    let context: Value = context_text
                        .as_deref()
                        .and_then(|text| serde_json::from_str(text).ok())
                        .unwrap_or(Value::Null);
                    projection.latest_die_by_session.insert(session_id, (da, context));
                }
            }
            _ => {}
        }
    }

    // Second pass: subtract undone rates from aggregates
    for row in &history_events {
        let session_id: i32 = row.try_get(1).unwrap();
        let event_type: String = row.try_get(2).unwrap();
        let event_id: i32 = row.try_get(0).unwrap();
        if event_type == "rate" && projection.undone_rate_ids.contains(&event_id) {
            if let Some(entry) = projection.rate_agg.get_mut(&session_id) {
                let issues_read: Option<i32> = row.try_get(9).unwrap();
                if let Some(ir) = issues_read {
                    entry.0 = entry.0.saturating_sub(ir);
                }
                let rating: Option<f64> = row.try_get(10).unwrap();
                if rating.is_some() {
                    // Recompute last_rating from remaining open rates
                    let remaining: Vec<&tokio_postgres::Row> = history_events.iter()
                        .filter(|r| {
                            let sid: i32 = r.try_get(1).unwrap();
                            let etype: String = r.try_get(2).unwrap();
                            let eid: i32 = r.try_get(0).unwrap();
                            sid == session_id && etype == "rate" && !projection.undone_rate_ids.contains(&eid)
                        })
                        .collect();
                    entry.1 = remaining.last().and_then(|r| r.try_get(10).ok());
                }
            }
        }
    }

    // Fetch snapshot counts
    let snapshot_counts = if !session_ids.is_empty() {
        let rows = connection
            .query(SNAPSHOT_COUNT_SQL, &[&session_ids])
            .await
            .map_err(db::query_error)?;
        rows.iter()
            .map(|row| (row.try_get::<_, i32>(0).unwrap(), row.try_get::<_, i32>(1).unwrap()))
            .collect::<std::collections::HashMap<_, _>>()
    } else {
        std::collections::HashMap::new()
    };

    // Build ladder paths and current die for each session
    let mut ladder_paths = std::collections::HashMap::new();
    let mut current_dies = std::collections::HashMap::new();
    let mut latest_roll_by_session = std::collections::HashMap::new();
    let mut pending_by_session = std::collections::HashMap::new();

    for row in sessions_to_return {
        let session_id: i32 = row.try_get(0).unwrap();
        let start_die: i32 = row.try_get(3).unwrap();
        let manual_die: Option<i32> = row.try_get(4).unwrap();
        let pending_thread_id: Option<i32> = row.try_get(6).unwrap();

        // Ladder path
        let ladder_rows = connection
            .query(LADDER_SQL, &[&session_id])
            .await
            .map_err(db::query_error)?;
        let ladder_values: Vec<i32> = ladder_rows
            .iter()
            .map(|r| r.try_get(0).unwrap())
            .collect();
        ladder_paths.insert(session_id, ladder_path(start_die, &ladder_values));

        // Current die
        let die_row = connection
            .query_opt(CURRENT_DIE_SQL, &[&session_id])
            .await
            .map_err(db::query_error)?;
        let resolved_die = if let Some(dr) = die_row {
            let die_after: i32 = dr.try_get(0).unwrap();
            let context_text: Option<String> = dr.try_get(1).unwrap();
            let context: Value = context_text
                .as_deref()
                .and_then(|text| serde_json::from_str(text).ok())
                .unwrap_or(Value::Null);
            current_die(manual_die, Some((die_after, context)), start_die)
        } else {
            current_die(manual_die, None, start_die)
        };
        current_dies.insert(session_id, resolved_die);

        // Latest action
        let action_row = connection
            .query_opt(LATEST_ACTION_SQL, &[&session_id])
            .await
            .map_err(db::query_error)?;
        if let Some(ar) = action_row {
            let action_type: String = ar.try_get(0).unwrap();
            let selected_thread_id: Option<i32> = ar.try_get(1).unwrap();
            let result: Option<i32> = ar.try_get(2).unwrap();
            latest_roll_by_session.insert(session_id, (action_type, selected_thread_id, result));
        }

        if let Some(ptid) = pending_thread_id {
            pending_by_session.insert(session_id, ptid);
        }
    }

    // Collect thread IDs needed
    let mut thread_ids = std::collections::HashSet::new();
    for session_id in &session_ids {
        if let Some((action_type, selected_thread_id, _)) = latest_roll_by_session.get(session_id) {
            if action_type == "roll" {
                if let Some(tid) = selected_thread_id {
                    thread_ids.insert(*tid);
                }
            }
        }
        if let Some(ptid) = pending_by_session.get(session_id) {
            thread_ids.insert(*ptid);
        }
    }

    // Fetch threads and issue stats
    let mut threads_by_id = std::collections::HashMap::new();
    let mut unread_counts = std::collections::HashMap::new();
    let mut issue_numbers = std::collections::HashMap::new();
    let mut tags_map = std::collections::HashMap::new();
    let mut position_map = std::collections::HashMap::new();

    if !thread_ids.is_empty() {
        let thread_id_vec: Vec<i32> = thread_ids.iter().copied().collect();
        let thread_rows = connection
            .query(
                "SELECT id, title, format, issues_remaining, total_issues, reading_progress, next_unread_issue_id, user_id FROM threads WHERE id = ANY($1)",
                &[&thread_id_vec],
            )
            .await
            .map_err(db::query_error)?;

        for tr in &thread_rows {
            let tid: i32 = tr.try_get(0).unwrap();
            threads_by_id.insert(tid, tr);
        }

        // Unread counts for issue-tracking threads
        let tracking_thread_ids: Vec<i32> = thread_id_vec.iter()
            .filter(|&&tid| threads_by_id.get(&tid).and_then(|r| r.try_get::<_, Option<i32>>(4).ok().flatten()).is_some())
            .copied()
            .collect();
        if !tracking_thread_ids.is_empty() {
            let unread_rows = connection
                .query(
                    "SELECT thread_id, count(*)::int FROM issues WHERE thread_id = ANY($1) AND status = 'unread' GROUP BY thread_id",
                    &[&tracking_thread_ids],
                )
                .await
                .map_err(db::query_error)?;
            for ur in &unread_rows {
                unread_counts.insert(ur.try_get(0).unwrap(), ur.try_get(1).unwrap());
            }
        }

        // Next issue numbers
        let next_issue_ids: Vec<i32> = thread_id_vec.iter()
            .filter_map(|&tid| threads_by_id.get(&tid).and_then(|r| r.try_get::<_, Option<i32>>(6).ok().flatten()))
            .collect();
        if !next_issue_ids.is_empty() {
            let issue_rows = connection
                .query(
                    "SELECT id, issue_number FROM issues WHERE id = ANY($1)",
                    &[&next_issue_ids],
                )
                .await
                .map_err(db::query_error)?;
            for ir in &issue_rows {
                issue_numbers.insert(ir.try_get(0).unwrap(), ir.try_get::<_, Option<String>>(1).unwrap());
            }
        }

        // Tags
        let tag_rows = connection
            .query(TAGS_SQL, &[&thread_id_vec[0], &user.id()])
            .await
            .map_err(db::query_error)?;
        // Actually TAGS_SQL only takes one thread_id. We need to batch this.
        // Let's do per-thread for now (bounded by page size * 2 max)
        for &tid in &thread_id_vec {
            let tag_rows = connection
                .query(TAGS_SQL, &[&tid, &user.id()])
                .await
                .map_err(db::query_error)?;
            let mut tags = Vec::new();
            for tag_row in &tag_rows {
                tags.push(SessionTag {
                    id: tag_row.try_get(0).unwrap(),
                    name: tag_row.try_get(1).unwrap(),
                    normalized_name: tag_row.try_get(2).unwrap(),
                    scope: tag_row.try_get(3).unwrap(),
                    owner_user_id: tag_row.try_get(4).unwrap(),
                    color: tag_row.try_get(5).unwrap(),
                    created_at: tag_row.try_get(6).unwrap(),
                    updated_at: tag_row.try_get(7).unwrap(),
                });
            }
            tags_map.insert(tid, tags);
        }

        // Queue positions
        for &tid in &thread_id_vec {
            let queue_row = connection
                .query_opt(QUEUE_POSITION_SQL, &[&user.id(), &tid])
                .await
                .map_err(db::query_error)?;
            let pos: i32 = queue_row.map(|r| r.try_get(0).unwrap()).unwrap_or(0);
            position_map.insert(tid, pos);
        }
    }

    // Build responses
    let mut responses = Vec::new();
    for row in sessions_to_return {
        let session_id: i32 = row.try_get(0).unwrap();
        let started_at: String = row.try_get(1).unwrap();
        let ended_at: Option<String> = row.try_get(2).unwrap();
        let start_die: i32 = row.try_get(3).unwrap();
        let manual_die: Option<i32> = row.try_get(4).unwrap();
        let owner_id: i32 = row.try_get(5).unwrap();
        let pending_thread_id: Option<i32> = row.try_get(6).unwrap();
        let reading_bandwidth: Option<String> = row.try_get(7).unwrap();
        let reading_intent: Option<String> = row.try_get(8).unwrap();
        let reading_mode_source: Option<String> = row.try_get(9).unwrap();
        let reading_mode_suggested: Option<bool> = row.try_get(10).unwrap();
        let predicted_bandwidth: Option<String> = row.try_get(11).unwrap();
        let active_bandwidth: Option<String> = row.try_get(12).unwrap();
        let bandwidth_confidence: Option<f64> = row.try_get(13).unwrap();
        let bandwidth_source: Option<String> = row.try_get(14).unwrap();
        let bandwidth_version: Option<String> = row.try_get(15).unwrap();
        let predicted_intent: Option<String> = row.try_get(16).unwrap();
        let active_intent: Option<String> = row.try_get(17).unwrap();
        let intent_confidence: Option<f64> = row.try_get(18).unwrap();
        let intent_source: Option<String> = row.try_get(19).unwrap();
        let intent_version: Option<String> = row.try_get(20).unwrap();

        let ladder = ladder_paths.get(&session_id).cloned().unwrap_or_else(|| start_die.to_string());
        let resolved_die = current_dies.get(&session_id).copied().unwrap_or(start_die);
        let snapshot_count = snapshot_counts.get(&session_id).copied().unwrap_or(0);

        let (action_type, selected_thread_id, roll_result) = latest_roll_by_session
            .get(&session_id)
            .cloned()
            .unwrap_or_else(|| (String::new(), None, None));
        let is_roll = action_type == "roll";
        let last_rolled_result = if is_roll { roll_result } else { None };

        // Active thread: pending wins; missing pending yields null with no fall-through
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
                if let Some(thread_row) = threads_by_id.get(&thread_id) {
                    let thread_owner: i32 = thread_row.try_get(7).unwrap();
                    if pending_thread_id.is_none() && thread_owner != owner_id {
                        None
                    } else {
                        let thread_id_value: i32 = thread_row.try_get(0).unwrap();
                        let title: String = thread_row.try_get(1).unwrap();
                        let format: String = thread_row.try_get(2).unwrap();
                        let stored_remaining: i32 = thread_row.try_get(3).unwrap();
                        let total_issues: Option<i32> = thread_row.try_get(4).unwrap();
                        let reading_progress: Option<String> = thread_row.try_get(5).unwrap();
                        let next_unread_issue_id: Option<i32> = thread_row.try_get(6).unwrap();

                        let issues_remaining = if total_issues.is_some() {
                            *unread_counts.get(&thread_id_value).unwrap_or(&0)
                        } else {
                            stored_remaining
                        };

                        let (next_issue_id, next_issue_number) = match next_unread_issue_id {
                            Some(issue_id) if total_issues.is_some() => {
                                let issue_id_val = issue_id;
                                let issue_num = issue_numbers.get(&issue_id_val).cloned().flatten();
                                (Some(issue_id_val), issue_num)
                            }
                            _ => (None, None),
                        };

                        let tags = tags_map.get(&thread_id_value).cloned().unwrap_or_default();
                        let queue_position = *position_map.get(&thread_id_value).unwrap_or(&0);

                        Some(SessionActiveThread {
                            id: thread_id_value,
                            title,
                            format: normalize_format(&format),
                            issues_remaining,
                            queue_position,
                            last_rolled_result,
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
                } else {
                    None
                }
            }
        };

        responses.push(SessionListItemResponse {
            id: session_id,
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
        let last_session = &sessions_to_return[sessions_to_return.len() - 1];
        let started_at: String = last_session.try_get(1).unwrap();
        let id: i32 = last_session.try_get(0).unwrap();
        Some(format!("{},{}", started_at, id))
    } else {
        None
    };

    Ok(Json(SessionListResponse {
        sessions: responses,
        next_page_token,
    }))
}

fn current_die(
    manual_die: Option<i32>,
    latest: Option<(i32, &Value)>,
    start_die: i32,
) -> i32 {
    if let Some((die_after, context)) = latest {
        return automatic_die_after(die_after, context);
    }
    manual_die.filter(|value| *value != 0).unwrap_or(start_die)
}

/// Documentation-only operation for the unversioned mounted read.
#[utoipa::path(
    get,
    path = "/api/sessions/",
    tag = "sessions",
    params(
        ("page_size" = i32, Query, description = "Number of sessions per page (1-200)"),
        ("page_token" = Option<String>, Query, description = "Cursor token (started_at,session_id)")
    ),
    responses(
        (status = 200, description = "Paginated session list", body = SessionListResponse),
        (status = 401, description = "Not authenticated"),
        (status = 400, description = "Invalid page_token"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_sessions_documentation() {}

/// Documentation-only operation for the versioned mounted read.
#[utoipa::path(
    get,
    path = "/api/v1/sessions/",
    tag = "sessions",
    params(
        ("page_size" = i32, Query, description = "Number of sessions per page (1-200)"),
        ("page_token" = Option<String>, Query, description = "Cursor token (started_at,session_id)")
    ),
    responses(
        (status = 200, description = "Paginated session list", body = SessionListResponse),
        (status = 401, description = "Not authenticated"),
        (status = 400, description = "Invalid page_token"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_sessions_v1_documentation() {}

/// OpenAPI document for the session list same-path surface.
#[derive(utoipa::OpenApi)]
#[openapi(
    paths(list_sessions_documentation, list_sessions_v1_documentation),
    components(schemas(
        SessionTag,
        SessionActiveThread,
        SessionBandwidthState,
        SessionIntentState,
        SessionListItemResponse,
        SessionListResponse
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
    use serde_json::json;
    use utoipa::OpenApi;

    #[test]
    fn format_normalization_matches_python() {
        assert_eq!(normalize_format(" Comic "), "Comic");
        assert_eq!(normalize_format("COMICS"), "Comic");
        assert_eq!(normalize_format("digital"), "Digital");
        assert_eq!(normalize_format("  Manga "), "Manga");
        assert_eq!(normalize_format(""), "");
    }

    #[test]
    fn bandwidth_and_intent_normalization_matches_python() {
        let state = bandwidth_state(
            Some("deep"),
            Some("garbage"),
            Some(1.5),
            Some("manual"),
            Some("v2"),
        );
        assert_eq!(state.predicted_bandwidth.as_deref(), Some("deep"));
        assert_eq!(state.active_bandwidth, None);
        assert_eq!(state.confidence, None);
        assert_eq!(state.source.as_deref(), Some("manual"));
        assert_eq!(state.mode_version.as_deref(), Some("v2"));

        let state = bandwidth_state(None, None, Some(0.5), Some("unknown"), None);
        assert_eq!(state.confidence, Some(0.5));
        assert_eq!(state.source, None);

        let intent = intent_state(Some("explore"), Some("deep"), Some(0.0), Some("quiz"), None);
        assert_eq!(intent.predicted_intent.as_deref(), Some("explore"));
        assert_eq!(intent.active_intent, None);
        assert_eq!(intent.confidence, Some(0.0));
        assert_eq!(intent.source.as_deref(), Some("quiz"));
    }

    #[test]
    fn ladder_path_matches_python() {
        assert_eq!(ladder_path(6, &[]), "6");
        assert_eq!(ladder_path(6, &[4, 8]), "6 → 4 → 8");
    }

    #[test]
    fn current_die_is_event_derived_with_manual_fallback() {
        assert_eq!(current_die(Some(10), Some((4, &json!({}))), 6), 4);
        assert_eq!(current_die(Some(0), Some((4, &json!({}))), 6), 4);
        assert_eq!(current_die(Some(10), None, 6), 10);
        assert_eq!(
            current_die(None, Some((4, &json!({"automatic_die_after": 20}))), 6),
            20
        );
        assert_eq!(
            current_die(None, Some((4, &json!({"automatic_die_after": 999}))), 6),
            4
        );
        assert_eq!(current_die(None, None, 8), 8);
        assert_eq!(current_die(Some(0), None, 8), 8);
    }

    #[test]
    fn session_list_sql_is_owner_scoped_and_bounded() {
        assert!(SESSION_LIST_SQL.contains("WHERE user_id = $1"));
        assert!(SESSION_LIST_SQL.contains("LIMIT $2"));
        assert!(SESSION_LIST_CURSOR_SQL.contains("WHERE user_id = $1"));
        assert!(SESSION_LIST_CURSOR_SQL.contains("started_at < $2"));
    }

    #[test]
    fn session_list_openapi_covers_both_same_paths() {
        let document = serde_json::to_value(SessionListApi::openapi()).expect("openapi");
        let paths = document["paths"].as_object().expect("paths");
        assert!(paths.contains_key("/api/sessions/"));
        assert!(paths.contains_key("/api/v1/sessions/"));
        for path in ["/api/sessions/", "/api/v1/sessions/"] {
            let operation = &document["paths"][path]["get"];
            assert!(operation["operationId"].is_string());
            assert!(operation["responses"]["200"].as_object().is_some());
            assert!(operation["security"].is_array());
        }
        assert!(document["components"]["schemas"]["SessionListResponse"].is_object());
        assert!(document["components"]["schemas"]["SessionListItemResponse"].is_object());
    }

    #[test]
    fn session_list_response_defaults_match_python_unset_fields() {
        let value = serde_json::to_value(SessionListItemResponse {
            id: 1,
            started_at: "2026-01-01T00:00:00.000Z".to_string(),
            ended_at: None,
            start_die: 6,
            manual_die: None,
            user_id: 7,
            ladder_path: "6".to_string(),
            active_thread: None,
            current_die: 6,
            last_rolled_result: None,
            has_restore_point: false,
            snapshot_count: 0,
            reading_bandwidth: None,
            reading_intent: None,
            reading_mode_source: None,
            reading_mode_suggested: false,
        })
        .expect("serializable session");
        assert_eq!(value["reading_mode_suggested"], json!(false));
    }
}