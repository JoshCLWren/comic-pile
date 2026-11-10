//! Native same-path single-session read (#4839, parent #4335).
//!
//! Migrates the single-session subset of `app/api/session.py` to the native
//! Rust router with identical method/path and wire contract:
//!
//! * `GET /api/sessions/{session_id}`
//! * `GET /api/v1/sessions/{session_id}`
//!
//! Remaining browser-called sessions operations stay on Python in this slice:
//! list (`GET /api/sessions/` + v1 twin), current (`GET .../current/` + v1),
//! details (`GET .../{id}/details` + v1), restore-session-start
//! (`POST .../{id}/restore-session-start` + v1), correction-examples
//! (`GET /api/v1/sessions/correction-examples`), and snapshots
//! (`GET .../{id}/snapshots` + v1, covered by PR #4888). Undo operations
//! (`/api/undo/*`, `/api/v1/undo/*`) live outside the sessions route
//! fragment and are not claimed here.
//!
//! Wire parity with Python `get_session` (`app/api/session.py`):
//!
//! * Ownership: `get_owned_session_or_404` — a foreign or missing session
//!   returns 404 with the exact detail `"Session not found"`.
//! * `ladder_path`: `build_ladder_path` — `start_die` followed by every
//!   `die_after` from `rate`/`snooze`/`undo` events in timestamp/id order,
//!   joined with `" → "`.
//! * `current_die`: `comic_pile.reading_session.get_current_die` — a
//!   non-zero `manual_die` wins, otherwise the latest die-changing event's
//!   `automatic_die_after` (see [`crate::reading_session::automatic_die_after`]),
//!   otherwise `start_die`.
//! * `active_thread`: `get_session_with_thread_safe` — the latest
//!   `roll`/`rate`/`snooze`/`rolled_but_skipped` event decides whether a roll
//!   is active; a `pending_thread_id` wins and a missing pending thread
//!   yields `null` without falling through to the roll event. Thread
//!   `issues_remaining` counts unread `issues` when the thread uses issue
//!   tracking (`total_issues IS NOT NULL`), otherwise the stored counter.
//!   `queue_position` is the legacy dense display ordinal (readable rows
//!   first, then stored queue position, then id) among active queued
//!   threads, or `0` outside the queue — matching Python
//!   `display_position` under the production legacy execution mode; the
//!   Option E preview eligibility ordering is not activated here.
//! * `bandwidth` / `intent`: `build_session_bandwidth_state` /
//!   `build_session_intent_state` normalization (unknown enum strings and
//!   out-of-range confidences become `null`).
//! * `format` normalization, direct visible tags ordered by scope
//!   descending then normalized name, and `next_issue_*` from
//!   `next_unread_issue_id` when issue tracking is in use.
//! * Defaults Python leaves unset on this endpoint stay unset:
//!   `snoozed_*` / `skipped_*` are empty, `correction` is `null`, and
//!   `active_thread.issues_read` / `last_rating` are `null`.
//! * Timestamps are emitted as UTC `...Z` strings, matching the earlier
//!   session-snapshots Rust slice (PR #4888); the frontend parses both the
//!   Python `+00:00` and Rust `Z` forms as dates.
//!
//! Bounded reads only: one session row, one snapshot count, two die-event
//! reads, one latest-action read, and at most one active thread with one
//! unread count, one next-issue read, one tag read and one ranked queue
//! read. No per-row fan-out. Python handlers remain; deployed ingress in
//! `vercel.json` shadows them after this cutover, and the numeric-only
//! Vercel source (`[0-9]+`) keeps literal siblings such as
//! `correction-examples` and `current/` on Python.

#![forbid(unsafe_code)]

use crate::{
    auth::AuthenticatedUser, db, reading_session::automatic_die_after, ApiError, AppState,
};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::Serialize;
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

/// Wire shape of Python `SessionResponse` for `get_session`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SessionDetailResponse {
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
    pub correction: Option<Value>,
}

/// Compact thread summary used for the (empty on this endpoint) snoozed and
/// skipped lists, kept typed so the contract stays explicit.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SessionThreadSummary {
    pub id: i32,
    pub title: String,
}

const SESSION_SQL: &str = "SELECT id, to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(ended_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), start_die, manual_die, user_id, pending_thread_id, timezone, reading_bandwidth, reading_intent, reading_mode_source, reading_mode_suggested, predicted_bandwidth, active_bandwidth, bandwidth_confidence, bandwidth_source, bandwidth_version, predicted_intent, active_intent, intent_confidence, intent_source, intent_version FROM sessions WHERE id = $1 AND user_id = $2";
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

fn not_found() -> ApiError {
    ApiError(StatusCode::NOT_FOUND, "Session not found".to_string())
}

fn internal() -> ApiError {
    ApiError(
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

/// `GET /api/sessions/{session_id}` and `GET /api/v1/sessions/{session_id}`.
pub async fn get_session(
    Path(session_id): Path<i32>,
    user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
) -> Result<Json<SessionDetailResponse>, ApiError> {
    let connection = db::checkout(&state).await?;

    let session_row = connection
        .query_opt(SESSION_SQL, &[&session_id, &user.id()])
        .await
        .map_err(db::query_error)?
        .ok_or_else(not_found)?;

    let started_at: String = session_row.try_get(1).map_err(|_| internal())?;
    let ended_at: Option<String> = session_row.try_get(2).map_err(|_| internal())?;
    let start_die: i32 = session_row.try_get(3).map_err(|_| internal())?;
    let manual_die: Option<i32> = session_row.try_get(4).map_err(|_| internal())?;
    let owner_id: i32 = session_row.try_get(5).map_err(|_| internal())?;
    let pending_thread_id: Option<i32> = session_row.try_get(6).map_err(|_| internal())?;
    let timezone: Option<String> = session_row.try_get(7).map_err(|_| internal())?;
    let reading_bandwidth: Option<String> = session_row.try_get(8).map_err(|_| internal())?;
    let reading_intent: Option<String> = session_row.try_get(9).map_err(|_| internal())?;
    let reading_mode_source: Option<String> = session_row.try_get(10).map_err(|_| internal())?;
    let reading_mode_suggested: Option<bool> = session_row.try_get(11).map_err(|_| internal())?;
    let predicted_bandwidth: Option<String> = session_row.try_get(12).map_err(|_| internal())?;
    let active_bandwidth: Option<String> = session_row.try_get(13).map_err(|_| internal())?;
    let bandwidth_confidence: Option<f64> = session_row.try_get(14).map_err(|_| internal())?;
    let bandwidth_source: Option<String> = session_row.try_get(15).map_err(|_| internal())?;
    let bandwidth_version: Option<String> = session_row.try_get(16).map_err(|_| internal())?;
    let predicted_intent: Option<String> = session_row.try_get(17).map_err(|_| internal())?;
    let active_intent: Option<String> = session_row.try_get(18).map_err(|_| internal())?;
    let intent_confidence: Option<f64> = session_row.try_get(19).map_err(|_| internal())?;
    let intent_source: Option<String> = session_row.try_get(20).map_err(|_| internal())?;
    let intent_version: Option<String> = session_row.try_get(21).map_err(|_| internal())?;

    let snapshot_count: i32 = connection
        .query_one(SNAPSHOT_COUNT_SQL, &[&session_id])
        .await
        .map_err(db::query_error)?
        .try_get(0)
        .map_err(|_| internal())?;

    let ladder_rows = connection
        .query(LADDER_SQL, &[&session_id])
        .await
        .map_err(db::query_error)?;
    let ladder_values: Vec<i32> = ladder_rows
        .iter()
        .map(|row| row.try_get::<_, i32>(0).map_err(|_| internal()))
        .collect::<Result<_, ApiError>>()?;
    let ladder = ladder_path(start_die, &ladder_values);

    let die_row = connection
        .query_opt(CURRENT_DIE_SQL, &[&session_id])
        .await
        .map_err(db::query_error)?;
    let latest_die = match die_row {
        Some(row) => {
            let die_after: i32 = row.try_get(0).map_err(|_| internal())?;
            let context_text: Option<String> = row.try_get(1).map_err(|_| internal())?;
            let context: Value = context_text
                .as_deref()
                .and_then(|text| serde_json::from_str(text).ok())
                .unwrap_or(Value::Null);
            // Leak-free local: move the parsed context into an owned value
            // whose reference lives for the `current_die` call below.
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

    // Latest roll/rate/snooze/rolled_but_skipped event decides active roll.
    let action_row = connection
        .query_opt(LATEST_ACTION_SQL, &[&session_id])
        .await
        .map_err(db::query_error)?;
    let (action_type, selected_thread_id, roll_result) = match action_row {
        Some(row) => (
            row.try_get::<_, String>(0).map_err(|_| internal())?,
            row.try_get::<_, Option<i32>>(1).map_err(|_| internal())?,
            row.try_get::<_, Option<i32>>(2).map_err(|_| internal())?,
        ),
        None => (String::new(), None, None),
    };
    let is_roll = action_type == "roll";
    let last_rolled_result = if is_roll { roll_result } else { None };

    // Active thread: pending wins; missing pending yields null with no
    // fall-through, exactly like `get_session_with_thread_safe`.
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
                    // Rolled threads must still belong to the session owner.
                    let thread_owner: i32 = thread_row.try_get(7).map_err(|_| internal())?;
                    if pending_thread_id.is_none() && thread_owner != owner_id {
                        None
                    } else {
                        let thread_id_value: i32 = thread_row.try_get(0).map_err(|_| internal())?;
                        let title: String = thread_row.try_get(1).map_err(|_| internal())?;
                        let format: String = thread_row.try_get(2).map_err(|_| internal())?;
                        let stored_remaining: i32 =
                            thread_row.try_get(3).map_err(|_| internal())?;
                        let total_issues: Option<i32> =
                            thread_row.try_get(4).map_err(|_| internal())?;
                        let reading_progress: Option<String> =
                            thread_row.try_get(5).map_err(|_| internal())?;
                        let next_unread_issue_id: Option<i32> =
                            thread_row.try_get(6).map_err(|_| internal())?;

                        let issues_remaining = if total_issues.is_some() {
                            connection
                                .query_one(UNREAD_COUNT_SQL, &[&thread_id_value])
                                .await
                                .map_err(db::query_error)?
                                .try_get(0)
                                .map_err(|_| internal())?
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
                                        Some(
                                            issue_row
                                                .try_get::<_, i32>(0)
                                                .map_err(|_| internal())?,
                                        ),
                                        issue_row
                                            .try_get::<_, Option<String>>(1)
                                            .map_err(|_| internal())?,
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
                                id: tag_row.try_get(0).map_err(|_| internal())?,
                                name: tag_row.try_get(1).map_err(|_| internal())?,
                                normalized_name: tag_row.try_get(2).map_err(|_| internal())?,
                                scope: tag_row.try_get(3).map_err(|_| internal())?,
                                owner_user_id: tag_row.try_get(4).map_err(|_| internal())?,
                                color: tag_row.try_get(5).map_err(|_| internal())?,
                                created_at: tag_row.try_get(6).map_err(|_| internal())?,
                                updated_at: tag_row.try_get(7).map_err(|_| internal())?,
                            });
                        }

                        let queue_row = connection
                            .query_opt(QUEUE_POSITION_SQL, &[&user.id(), &thread_id_value])
                            .await
                            .map_err(db::query_error)?;
                        let queue_position: i32 = match queue_row {
                            Some(row) => row.try_get(0).map_err(|_| internal())?,
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

    Ok(Json(SessionDetailResponse {
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
        snoozed_thread_ids: Vec::new(),
        snoozed_threads: Vec::new(),
        skipped_thread_ids: Vec::new(),
        skipped_threads: Vec::new(),
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
    path = "/api/sessions/{session_id}",
    tag = "sessions",
    params(("session_id" = i32, Path, description = "Owned reading session")),
    responses(
        (status = 200, description = "Single session", body = SessionDetailResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Session not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_session_documentation() {}

/// Documentation-only operation for the versioned mounted read.
#[utoipa::path(
    get,
    path = "/api/v1/sessions/{session_id}",
    tag = "sessions",
    params(("session_id" = i32, Path, description = "Owned reading session")),
    responses(
        (status = 200, description = "Single session", body = SessionDetailResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Session not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_session_v1_documentation() {}

/// OpenAPI document for the single-session same-path surface.
#[derive(utoipa::OpenApi)]
#[openapi(
    paths(get_session_documentation, get_session_v1_documentation),
    components(schemas(
        SessionTag,
        SessionActiveThread,
        SessionBandwidthState,
        SessionIntentState,
        SessionThreadSummary,
        SessionDetailResponse
    )),
    modifiers(&SessionDetailSecurityAddon)
)]
pub struct SessionDetailApi;

struct SessionDetailSecurityAddon;

impl utoipa::Modify for SessionDetailSecurityAddon {
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
        // #4352: the newest die event wins over the legacy manual pin.
        assert_eq!(current_die(Some(10), Some((4, &json!({}))), 6), 4);
        assert_eq!(current_die(Some(0), Some((4, &json!({}))), 6), 4);
        // With no die events, the legacy manual column is the fallback.
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
    fn not_found_matches_python_detail_text() {
        let error = not_found();
        assert_eq!(error.0, StatusCode::NOT_FOUND);
        assert_eq!(error.1, "Session not found");
    }

    #[test]
    fn session_sql_is_owner_scoped_and_bounded() {
        assert!(SESSION_SQL.contains("WHERE id = $1 AND user_id = $2"));
        assert!(!SESSION_SQL.contains(';'));
        assert!(SNAPSHOT_COUNT_SQL.contains("WHERE session_id = $1"));
        assert!(LADDER_SQL.contains("type IN ('rate','snooze','undo')"));
        assert!(CURRENT_DIE_SQL.contains("ORDER BY timestamp DESC, id DESC LIMIT 1"));
        assert!(LATEST_ACTION_SQL.contains("rolled_but_skipped"));
        assert!(PENDING_THREAD_SQL.contains("WHERE id = $1 AND user_id = $2"));
        assert!(QUEUE_POSITION_SQL.contains("row_number()"));
        assert!(QUEUE_POSITION_SQL.contains("status = 'active'"));
    }

    #[test]
    fn session_detail_openapi_covers_both_same_paths() {
        let document = serde_json::to_value(SessionDetailApi::openapi()).expect("openapi");
        let paths = document["paths"].as_object().expect("paths");
        assert!(paths.contains_key("/api/sessions/{session_id}"));
        assert!(paths.contains_key("/api/v1/sessions/{session_id}"));
        for path in [
            "/api/sessions/{session_id}",
            "/api/v1/sessions/{session_id}",
        ] {
            let operation = &document["paths"][path]["get"];
            assert!(operation["operationId"].is_string());
            assert!(operation["responses"]["200"].as_object().is_some());
            assert!(operation["responses"]["404"].as_object().is_some());
            assert!(operation["security"].is_array());
        }
        assert!(document["components"]["schemas"]["SessionDetailResponse"].is_object());
        assert!(document["components"]["schemas"]["SessionActiveThread"].is_object());
    }

    #[test]
    fn session_detail_response_defaults_match_python_unset_fields() {
        let value = serde_json::to_value(SessionDetailResponse {
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
            skipped_thread_ids: Vec::new(),
            skipped_threads: Vec::new(),
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
        assert_eq!(value["skipped_threads"], json!([]));
        assert_eq!(value["correction"], Value::Null);
        assert_eq!(value["reading_mode_suggested"], json!(false));
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
                "INSERT INTO users (id, username) VALUES (9101, 'session-detail-test'), (9102, 'session-detail-other');
                 INSERT INTO threads (id, user_id, title, format, issues_remaining, total_issues, reading_progress, queue_position, status, is_blocked) VALUES (9201, 9101, 'Owned Comic', 'comics', 3, NULL, NULL, 1, 'active', false), (9202, 9102, 'Foreign Comic', 'Comic', 2, NULL, NULL, 1, 'active', false);
                 INSERT INTO sessions (id, user_id, started_at, ended_at, start_die, manual_die, pending_thread_id, reading_mode_suggested) VALUES (9301, 9101, NOW(), NULL, 6, NULL, 9201, false), (9302, 9102, NOW(), NULL, 6, NULL, 9202, false), (9303, 9101, NOW(), NULL, 6, NULL, NULL, false);
                 INSERT INTO events (session_id, type, timestamp, selected_thread_id, thread_id, die, die_after, result) VALUES (9301, 'roll', NOW(), 9201, NULL, 6, NULL, 4), (9301, 'rate', NOW() + interval '1 minute', NULL, 9201, 6, 4, NULL), (9303, 'roll', NOW(), 9201, NULL, 6, NULL, 2);",
            )
            .await
            .expect("seed session detail fixture");
        drop(connection);
        (state, AuthenticatedUser::for_test(9101), guard)
    }

    #[tokio::test]
    async fn get_session_returns_owned_projection_to_disposable_postgres() {
        let (state, user, _guard) = database_fixture().await;
        let Json(response) = get_session(Path(9301), user, State(state.clone()))
            .await
            .expect("owned session");
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
    async fn get_session_rejects_missing_and_foreign_without_leaking() {
        let (state, user, _guard) = database_fixture().await;
        let missing = get_session(Path(9999), user, State(state.clone()))
            .await
            .expect_err("missing must 404");
        assert_eq!(missing.0, StatusCode::NOT_FOUND);
        assert_eq!(missing.1, "Session not found");

        let foreign = get_session(Path(9302), user, State(state.clone()))
            .await
            .expect_err("foreign must 404");
        assert_eq!(foreign.0, StatusCode::NOT_FOUND);
        assert_eq!(foreign.1, "Session not found");
    }

    #[tokio::test]
    async fn get_session_rolled_thread_without_pending_is_active() {
        let (state, user, _guard) = database_fixture().await;
        let Json(response) = get_session(Path(9303), user, State(state.clone()))
            .await
            .expect("owned session without pending");
        // Latest action is a roll selecting the owned thread, so the rolled
        // thread is the active thread even without a pending id.
        let active = response.active_thread.expect("rolled active thread");
        assert_eq!(active.id, 9201);
        assert_eq!(active.last_rolled_result, Some(2));
        assert_eq!(response.last_rolled_result, Some(2));
    }

    #[tokio::test]
    async fn session_detail_requires_auth_through_service_router() {
        use crate::{config::Config, router, AppState};
        use axum::{
            body::Body,
            http::{Request, StatusCode},
        };
        use tower::ServiceExt;

        let config = Config::from_lookup(|name| match name {
            "RUST_ROLL_DATABASE_URL" => Some("postgresql://localhost/unused".into()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-secret".into()),
            _ => None,
        })
        .unwrap();
        let app = router(Arc::new(AppState::new(config).unwrap()));
        for uri in ["/api/sessions/7", "/api/v1/sessions/7"] {
            let response = app
                .clone()
                .oneshot(
                    Request::builder()
                        .method("GET")
                        .uri(uri)
                        .body(Body::empty())
                        .unwrap(),
                )
                .await
                .unwrap();
            assert_eq!(
                response.status(),
                StatusCode::UNAUTHORIZED,
                "{uri} must require auth through the service router"
            );
        }
    }
}
