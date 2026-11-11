//! Native same-path current session read (#4839, parent #4335).
//!
//! Migrates the current-session subset of `app/api/session.py` to the native
//! Rust router with identical method/path and wire contract:
//!
//! * `GET /api/sessions/current/`
//! * `GET /api/v1/sessions/current/`
//!
//! Wire parity with Python `get_current_session` (`app/api/session.py`):
//!
//! * Ownership: session scoped to `user_id` with `ended_at IS NULL` — a foreign
//!   or missing session returns a newly created session (matching Python
//!   `get_or_create` behavior with timezone from `X-Browser-Timezone` header).
//! * `ladder_path`: `build_ladder_path` — `start_die` followed by every
//!   `die_after` from `rate`/`snooze`/`undo` events in timestamp/id order,
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
//! * `snoozed_thread_ids` / `snoozed_threads` populated from session state.
//! * `pending_thread_id` returned from session.
//! * Timestamps are emitted as UTC `...Z` strings.
//!
//! Bounded reads only: one session row (create or fetch), one snapshot count,
//! two die-event reads, one latest-action read, and at most one active thread
//! with one unread count, one next-issue read, one tag read and one ranked
//! queue read. No per-row fan-out. Python handlers remain; deployed ingress in
//! `vercel.json` shadows them after this cutover.

#![forbid(unsafe_code)]

use crate::{
    auth::AuthenticatedUser, db, reading_session::automatic_die_after, ApiError, AppState,
};
use axum::{
    extract::{Path, Query, State},
    http::{HeaderMap, StatusCode},
    Json,
};
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

/// Snoozed thread info matching Python `SnoozedThreadInfo`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SnoozedThreadInfo {
    pub id: i32,
    pub title: String,
}

/// Wire shape of Python `SessionResponse` for `get_current_session`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
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
    pub snoozed_threads: Vec<SnoozedThreadInfo>,
    pub pending_thread_id: Option<i32>,
    pub timezone: Option<String>,
    pub reading_bandwidth: Option<String>,
    pub reading_intent: Option<String>,
    pub reading_mode_source: Option<String>,
    pub reading_mode_suggested: bool,
    pub bandwidth: Option<SessionBandwidthState>,
    pub intent: Option<SessionIntentState>,
    pub correction: Option<Value>,
}

#[derive(Debug, Deserialize)]
pub struct TimezoneQuery {
    pub timezone: Option<String>,
}

const SESSION_CURRENT_SQL: &str = "SELECT id, to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(ended_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), start_die, manual_die, user_id, pending_thread_id, snoozed_thread_ids, timezone, reading_bandwidth, reading_intent, reading_mode_source, reading_mode_suggested, predicted_bandwidth, active_bandwidth, bandwidth_confidence, bandwidth_source, bandwidth_version, predicted_intent, active_intent, intent_confidence, intent_source, intent_version FROM sessions WHERE user_id = $1 AND ended_at IS NULL ORDER BY started_at DESC, id DESC LIMIT 1";
const SNAPSHOT_COUNT_SQL: &str = "SELECT count(*)::int FROM snapshots WHERE session_id = $1";
const LADDER_SQL: &str = "SELECT die_after FROM events WHERE session_id = $1 AND type IN ('rate','snooze','undo') AND die_after IS NOT NULL ORDER BY timestamp ASC, id ASC";
const CURRENT_DIE_SQL: &str = "SELECT die_after, context::text FROM events WHERE session_id = $1 AND type IN ('rate','snooze','undo') AND die_after IS NOT NULL ORDER BY timestamp DESC, id DESC LIMIT 1";
const LATEST_ACTION_SQL: &str = "SELECT type, selected_thread_id, result FROM events WHERE session_id = $1 AND type IN ('roll','rate','snooze','rolled_but_skipped') ORDER BY timestamp DESC, id DESC LIMIT 1";
const PENDING_THREAD_SQL: &str = "SELECT id, title, format, issues_remaining, total_issues, reading_progress, next_unread_issue_id, user_id FROM threads WHERE id = $1 AND user_id = $2";
const ROLLED_THREAD_SQL: &str = "SELECT id, title, format, issues_remaining, total_issues, reading_progress, next_unread_issue_id, user_id FROM threads WHERE id = $1";
const UNREAD_COUNT_SQL: &str =
    "SELECT count(*)::int FROM issues WHERE thread_id = $1 AND status = 'unread'";
const NEXT_ISSUE_SQL: &str = "SELECT id, issue_number FROM issues WHERE id = $1";
const TAGS_SQL: &str = "SELECT tag.id, tag.name, tag.normalized_name, tag.scope, tag.owner_user_id, tag.color, to_char(tag.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(tag.updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') FROM tag_assignments assignment JOIN tags tag ON tag.id = assignment.tag_id WHERE assignment.target_type = 'Thread' AND assignment.target_id = $1 AND (tag.scope = 'global' OR tag.owner_user_id = $2) ORDER BY tag.scope DESC, tag.normalized_name ASC";
const QUEUE_POSITION_SQL: &str = "SELECT seq::int FROM (SELECT id, row_number() OVER (ORDER BY is_blocked ASC, queue_position ASC, id ASC) AS seq FROM threads WHERE user_id = $1 AND status = 'active' AND queue_position >= 1) ranked WHERE id = $2";
const SNOOZED_THREADS_SQL: &str = "SELECT id, title FROM threads WHERE id = ANY($1)";

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
///
/// Event-derived die wins (#4352): the manual_die column is a legacy
/// fallback only when the session has no die-changing events.
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

/// `GET /api/sessions/current/` and `GET /api/v1/sessions/current/`.
pub async fn get_current_session(
    headers: HeaderMap,
    Query(query): Query<TimezoneQuery>,
    user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
) -> Result<Json<SessionCurrentResponse>, ApiError> {
    let connection = db::checkout(&state).await?;

    // Try to find existing active session
    let session_row = connection
        .query_opt(SESSION_CURRENT_SQL, &[&user.id()])
        .await
        .map_err(db::query_error)?;

    let session_row = match session_row {
        Some(row) => row,
        None => {
            // Create new session (Python get_or_create behavior)
            let timezone = headers
                .get("x-browser-timezone")
                .and_then(|v| v.to_str().ok())
                .or(query.timezone.as_deref());

            let now = chrono::Utc::now();
            let timezone_str = timezone.unwrap_or("UTC");

            // Validate timezone like Python does
            let valid_timezone = crate::reading_session::browser_timezone(timezone_str);

            let session_id: i32 = connection
                .query_one(
                    "INSERT INTO sessions (user_id, started_at, start_die, reading_mode_suggested, timezone) VALUES ($1, $2, 6, false, $3) RETURNING id",
                    &[&user.id(), &now, &valid_timezone],
                )
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

            connection
                .query_opt(
                    "SELECT id, to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(ended_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), start_die, manual_die, user_id, pending_thread_id, snoozed_thread_ids, timezone, reading_bandwidth, reading_intent, reading_mode_source, reading_mode_suggested, predicted_bandwidth, active_bandwidth, bandwidth_confidence, bandwidth_source, bandwidth_version, predicted_intent, active_intent, intent_confidence, intent_source, intent_version FROM sessions WHERE id = $1",
                    &[&session_id],
                )
                .await
                .map_err(db::query_error)?
                .ok_or_else(internal)?
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
    let snoozed_thread_ids: Option<Vec<i32>> = session_row.try_get(7).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let timezone: Option<String> = session_row.try_get(8).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let reading_bandwidth: Option<String> = session_row.try_get(9).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let reading_intent: Option<String> = session_row.try_get(10).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let reading_mode_source: Option<String> = session_row.try_get(11).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let reading_mode_suggested: Option<bool> = session_row.try_get(12).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let predicted_bandwidth: Option<String> = session_row.try_get(13).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let active_bandwidth: Option<String> = session_row.try_get(14).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let bandwidth_confidence: Option<f64> = session_row.try_get(15).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let bandwidth_source: Option<String> = session_row.try_get(16).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let bandwidth_version: Option<String> = session_row.try_get(17).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let predicted_intent: Option<String> = session_row.try_get(18).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let active_intent: Option<String> = session_row.try_get(19).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let intent_confidence: Option<f64> = session_row.try_get(20).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let intent_source: Option<String> = session_row.try_get(21).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let intent_version: Option<String> = session_row.try_get(22).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;

    // Fetch snapshot count
    let snapshot_count: i32 = connection
        .query_one(SNAPSHOT_COUNT_SQL, &[&session_id])
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

    // Fetch snoozed threads
    let snoozed_thread_ids_vec = snoozed_thread_ids.unwrap_or_default();
    let snoozed_threads = if !snoozed_thread_ids_vec.is_empty() {
        let rows = connection
            .query(SNOOZED_THREADS_SQL, &[&snoozed_thread_ids_vec])
            .await
            .map_err(db::query_error)?;
        rows.iter()
            .map(|row| SnoozedThreadInfo {
                id: row.try_get(0).map_err(|e| {
                    tracing::debug!(
                        error_kind = crate::error_kind(&e),
                        "preserved underlying error before mapping"
                    );
                    internal()
                })?,
                title: row.try_get(1).map_err(|e| {
                    tracing::debug!(
                        error_kind = crate::error_kind(&e),
                        "preserved underlying error before mapping"
                    );
                    internal()
                })?,
            })
            .collect::<Result<_, ApiError>>()?
    } else {
        Vec::new()
    };

    // Ladder path
    let ladder_rows = connection
        .query(LADDER_SQL, &[&session_id])
        .await
        .map_err(db::query_error)?;
    let ladder_values: Vec<i32> = ladder_rows
        .iter()
        .map(|row| {
            row.try_get::<_, i32>(0).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })
        })
        .collect::<Result<_, ApiError>>()?;
    let ladder = ladder_path(start_die, &ladder_values);

    // Current die
    let die_row = connection
        .query_opt(CURRENT_DIE_SQL, &[&session_id])
        .await
        .map_err(db::query_error)?;
    let latest_die = match die_row {
        Some(row) => {
            let die_after: i32 = row.try_get(0).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?;
            let context_text: Option<String> = row.try_get(1).map_err(|e| {
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
            Some((die_after, owned))
        }
        None => None,
    };
    let resolved_die = match &latest_die {
        Some((die_after, context)) => {
            current_die(manual_die, Some((*die_after, context)), start_die)
        }
        None => current_die(manual_die, None, start_die),
    };

    // Latest action
    let action_row = connection
        .query_opt(LATEST_ACTION_SQL, &[&session_id])
        .await
        .map_err(db::query_error)?;
    let (action_type, selected_thread_id, roll_result) = match action_row {
        Some(row) => (
            row.try_get::<_, String>(0).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?,
            row.try_get::<_, Option<i32>>(1).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?,
            row.try_get::<_, Option<i32>>(2).map_err(|e| {
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
                                        Some(issue_row.try_get::<_, i32>(0).map_err(|e| {
                                            tracing::debug!(
                                                error_kind = crate::error_kind(&e),
                                                "preserved underlying error before mapping"
                                            );
                                            internal()
                                        })?),
                                        issue_row.try_get::<_, Option<String>>(1).map_err(|e| {
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
                }
            }
        }
    };

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
        snoozed_thread_ids: snoozed_thread_ids_vec,
        snoozed_threads,
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
        correction: None,
    }))
}

/// Documentation-only operation for the unversioned mounted read.
#[utoipa::path(
    get,
    path = "/api/sessions/current/",
    tag = "sessions",
    params(
        ("timezone" = Option<String>, Query, description = "Browser timezone")
    ),
    responses(
        (status = 200, description = "Current session", body = SessionCurrentResponse),
        (status = 401, description = "Not authenticated"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_current_session_documentation() {}

/// Documentation-only operation for the versioned mounted read.
#[utoipa::path(
    get,
    path = "/api/v1/sessions/current/",
    tag = "sessions",
    params(
        ("timezone" = Option<String>, Query, description = "Browser timezone")
    ),
    responses(
        (status = 200, description = "Current session", body = SessionCurrentResponse),
        (status = 401, description = "Not authenticated"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_current_session_v1_documentation() {}

/// OpenAPI document for the current-session same-path surface.
#[derive(utoipa::OpenApi)]
#[openapi(
    paths(get_current_session_documentation, get_current_session_v1_documentation),
    components(schemas(
        SessionTag,
        SessionActiveThread,
        SessionBandwidthState,
        SessionIntentState,
        SnoozedThreadInfo,
        SessionCurrentResponse
    )),
    modifiers(&SessionCurrentSecurityAddon)
)]
pub struct SessionCurrentApi;

struct SessionCurrentSecurityAddon;

impl utoipa::Modify for SessionCurrentSecurityAddon {
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
    fn session_current_sql_is_owner_scoped_and_bounded() {
        assert!(SESSION_CURRENT_SQL.contains("WHERE user_id = $1 AND ended_at IS NULL"));
        assert!(SESSION_CURRENT_SQL.contains("ORDER BY started_at DESC, id DESC LIMIT 1"));
        assert!(SNAPSHOT_COUNT_SQL.contains("WHERE session_id = $1"));
        assert!(LADDER_SQL.contains("type IN ('rate','snooze','undo')"));
        assert!(CURRENT_DIE_SQL.contains("ORDER BY timestamp DESC, id DESC LIMIT 1"));
        assert!(LATEST_ACTION_SQL.contains("rolled_but_skipped"));
        assert!(PENDING_THREAD_SQL.contains("WHERE id = $1 AND user_id = $2"));
        assert!(QUEUE_POSITION_SQL.contains("row_number()"));
        assert!(QUEUE_POSITION_SQL.contains("status = 'active'"));
    }

    #[test]
    fn session_current_openapi_covers_both_same_paths() {
        let document = serde_json::to_value(SessionCurrentApi::openapi()).expect("openapi");
        let paths = document["paths"].as_object().expect("paths");
        assert!(paths.contains_key("/api/sessions/current/"));
        assert!(paths.contains_key("/api/v1/sessions/current/"));
        for path in ["/api/sessions/current/", "/api/v1/sessions/current/"] {
            let operation = &document["paths"][path]["get"];
            assert!(operation["operationId"].is_string());
            assert!(operation["responses"]["200"].as_object().is_some());
            assert!(operation["security"].is_array());
        }
        assert!(document["components"]["schemas"]["SessionCurrentResponse"].is_object());
        assert!(document["components"]["schemas"]["SessionActiveThread"].is_object());
    }

    #[test]
    fn session_current_response_defaults_match_python_unset_fields() {
        let value = serde_json::to_value(SessionCurrentResponse {
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
            snoozed_thread_ids: Vec::new(),
            snoozed_threads: Vec::new(),
            pending_thread_id: None,
            timezone: None,
            reading_bandwidth: None,
            reading_intent: None,
            reading_mode_source: None,
            reading_mode_suggested: false,
            bandwidth: None,
            intent: None,
            correction: None,
        })
        .expect("serializable session");
        assert_eq!(value["snoozed_thread_ids"], json!([]));
        assert_eq!(value["snoozed_threads"], json!([]));
        assert_eq!(value["correction"], Value::Null);
        assert_eq!(value["reading_mode_suggested"], json!(false));
    }
}