//! Native same-path session-history list read (#4839, parent #4335).
//!
//! Migrates the session-history list subset of `app/api/session.py` to the
//! native Rust router with identical method/path and wire contract:
//!
//! * `GET /api/sessions/`
//! * `GET /api/v1/sessions/`
//!
//! Wire parity with Python `list_sessions` (`app/api/session.py`):
//!
//! * Ownership: `WHERE user_id = $1` — a foreign session is never returned.
//! * Cursor pagination: `page_size` (default 50, rejected outside 1..=200) and
//!   `page_token` (`started_at,session_id`). A malformed token is a 400 with the
//!   exact detail `"Invalid page_token format"`.
//! * `ladder_path`: `start_die` followed by every `die_after` from the
//!   `rate`/`snooze`/`undo`/`reset_dice`/`manual_die` events of the session in
//!   timestamp/id order, joined with `" → "`. The same page-wide event read
//!   feeds the ladder, so a page never issues one ladder query per row.
//! * `current_die`: event-derived die wins (#4352); the `manual_die` column is
//!   a legacy fallback only when the session has no die-changing events.
//! * `active_thread`: the session's latest `roll` event decides the rolled
//!   series and only a session without one falls back to `pending_thread_id`.
//!   Thread `issues_remaining` counts unread `issues` when the thread uses
//!   issue tracking (`total_issues IS NOT NULL`), otherwise the stored counter.
//!   `queue_position` is the legacy dense display ordinal (readable rows
//!   first, then stored queue position, then id) among active queued threads,
//!   or `0` outside the queue — matching Python `display_position` under the
//!   production legacy execution mode; the Option E preview eligibility
//!   ordering is not activated here.
//! * `issues_read` / `last_rating`: the session's rating aggregate, with an
//!   undone rating subtracted again.
//! * `issue_id` / `issue_number`: the issue identity the session recorded for
//!   that series, so a card never borrows another series' issue number
//!   (#3763). Only a thread without a recorded identity falls back to its
//!   current next-unread issue.
//! * Reading-mode fields stay unset: Python's `_to_session_list_item` drops
//!   `reading_bandwidth`, `reading_intent`, `reading_mode_source` and
//!   `reading_mode_suggested`, so the list never reports them.
//!
//! Bounded reads only: one paged session query, one event query for the whole
//! page, one snapshot-count query, one thread read, one unread-count read, one
//! next-issue read, one tag read and one whole-queue position read. No
//! per-row fan-out beyond the page size. Python handlers remain; deployed
//! ingress in `vercel.json` shadows them after this cutover.

#![forbid(unsafe_code)]

use crate::{
    auth::AuthenticatedUser,
    db,
    session_detail::{current_die, ladder_path, normalize_format, SessionActiveThread, SessionTag},
    ApiError, AppState,
};
use axum::{
    extract::{Query, State},
    http::StatusCode,
    Json,
};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use tokio_postgres::types::FromSqlOwned;

/// Python `SessionListItem`: the deliberate subset of `SessionResponse` the
/// history list view returns.
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

/// Python `SessionHistoryListResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SessionHistoryListResponse {
    pub sessions: Vec<SessionListItemResponse>,
    pub next_page_token: Option<String>,
}

/// Query parameters of Python `list_sessions`.
#[derive(Debug, Deserialize)]
pub struct SessionListQuery {
    #[serde(default = "default_page_size")]
    pub page_size: i32,
    pub page_token: Option<String>,
}

const DEFAULT_PAGE_SIZE: i32 = 50;
const MAX_PAGE_SIZE: i32 = 200;

fn default_page_size() -> i32 {
    DEFAULT_PAGE_SIZE
}

const SESSION_LIST_SQL: &str = "SELECT id, to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(ended_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), start_die, manual_die, user_id, pending_thread_id FROM sessions WHERE user_id = $1 ORDER BY started_at DESC, id DESC LIMIT $2";
const SESSION_LIST_CURSOR_SQL: &str = "SELECT id, to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(ended_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), start_die, manual_die, user_id, pending_thread_id FROM sessions WHERE user_id = $1 AND (started_at < $2 OR (started_at = $2 AND id > $3)) ORDER BY started_at DESC, id DESC LIMIT $4";
const HISTORY_EVENTS_SQL: &str = "SELECT id, session_id, type, thread_id, selected_thread_id, die_after, context::text, result, issues_read, rating, issue_id, issue_number FROM events WHERE session_id = ANY($1) AND ((type = 'roll' AND selected_thread_id IS NOT NULL) OR type = 'rate' OR type = 'rolled_but_skipped' OR (type IN ('snooze','unsnooze','undo','restore','manual_die','reset_dice') AND die_after IS NOT NULL)) ORDER BY session_id, timestamp, id";
const SNAPSHOT_COUNT_SQL: &str =
    "SELECT session_id, count(*)::int FROM snapshots WHERE session_id = ANY($1) GROUP BY session_id";
const THREADS_SQL: &str = "SELECT id, title, format, issues_remaining, total_issues, reading_progress, next_unread_issue_id FROM threads WHERE id = ANY($1)";
const UNREAD_COUNT_SQL: &str = "SELECT thread_id, count(*)::int FROM issues WHERE thread_id = ANY($1) AND status = 'unread' GROUP BY thread_id";
const NEXT_ISSUE_SQL: &str = "SELECT id, issue_number FROM issues WHERE id = ANY($1)";
const TAGS_SQL: &str = "SELECT assignment.target_id, tag.id, tag.name, tag.normalized_name, tag.scope, tag.owner_user_id, tag.color, to_char(tag.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(tag.updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') FROM tag_assignments assignment JOIN tags tag ON tag.id = assignment.tag_id WHERE assignment.target_type = 'Thread' AND assignment.target_id = ANY($1) AND (tag.scope = 'global' OR tag.owner_user_id = $2) ORDER BY tag.scope DESC, tag.normalized_name ASC";
const QUEUE_POSITIONS_SQL: &str = "SELECT id, row_number() OVER (ORDER BY is_blocked ASC, queue_position ASC, id ASC)::int FROM threads WHERE user_id = $1 AND status = 'active' AND queue_position >= 1";

fn internal() -> ApiError {
    ApiError::with_status(
        StatusCode::INTERNAL_SERVER_ERROR,
        "Internal Server Error".to_string(),
    )
}

fn bad_request(detail: String) -> ApiError {
    ApiError::with_status(StatusCode::BAD_REQUEST, detail)
}

fn unprocessable(detail: String) -> ApiError {
    ApiError::with_status(StatusCode::UNPROCESSABLE_ENTITY, detail)
}

/// Read one typed column, mapping a decode failure to the standard 500 body.
fn column<T: FromSqlOwned>(row: &tokio_postgres::Row, index: usize) -> Result<T, ApiError> {
    row.try_get(index).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })
}

/// Python `build_ladder_path`: start die plus chronological die-after values.
fn ladder_for(start_die: i32, die_after: &[i32]) -> String {
    ladder_path(start_die, die_after)
}

/// Aggregated rating state for one session history row.
#[derive(Debug, Default, Clone, Copy)]
struct RateAggregate {
    issues_read: i32,
    last_rating: Option<f64>,
}

/// The rolled series recorded by a session's latest roll event.
#[derive(Debug, Clone, Copy)]
struct RollEvent {
    selected_thread_id: i32,
    result: Option<i32>,
}

/// `GET /api/sessions/` and `GET /api/v1/sessions/`.
pub async fn list_sessions(
    Query(query): Query<SessionListQuery>,
    user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
) -> Result<Json<SessionHistoryListResponse>, ApiError> {
    let page_size = query.page_size;
    if !(1..=MAX_PAGE_SIZE).contains(&page_size) {
        return Err(unprocessable(format!(
            "page_size must be between 1 and {MAX_PAGE_SIZE}"
        )));
    }
    let limit = page_size + 1;

    let connection = db::checkout(&state).await?;

    let rows = if let Some(token) = query.page_token.as_deref() {
        let (cursor_started_at, cursor_id) = parse_page_token(token)?;
        connection
            .query(
                SESSION_LIST_CURSOR_SQL,
                &[&user.id(), &cursor_started_at, &cursor_id, &limit],
            )
            .await
            .map_err(db::query_error)?
    } else {
        connection
            .query(SESSION_LIST_SQL, &[&user.id(), &limit])
            .await
            .map_err(db::query_error)?
    };

    let has_more = rows.len() > page_size as usize;
    let page = &rows[..page_size.min(rows.len() as i32) as usize];
    if page.is_empty() {
        return Ok(Json(SessionHistoryListResponse {
            sessions: Vec::new(),
            next_page_token: None,
        }));
    }

    let session_ids: Vec<i32> = page.iter().map(|row| column::<i32>(row, 0)).collect::<Result<_, _>>()?;

    let events = connection
        .query(HISTORY_EVENTS_SQL, &[&session_ids])
        .await
        .map_err(db::query_error)?;

    // Python `project_session_history_events` plus the rating aggregate that
    // undoes subtract again. Events arrive ordered by (session, timestamp, id),
    // so later events overwrite earlier latest-event values.
    let mut rate_agg: HashMap<i32, RateAggregate> = HashMap::new();
    let mut open_rate_ids: HashMap<i32, Vec<i64>> = HashMap::new();
    let mut undone_rate_ids: HashSet<i64> = HashSet::new();
    let mut latest_roll: HashMap<i32, RollEvent> = HashMap::new();
    let mut die_path: HashMap<i32, Vec<i32>> = HashMap::new();
    let mut latest_die: HashMap<i32, (i32, Value)> = HashMap::new();
    let mut issue_identity: HashMap<(i32, i32), (Option<i32>, Option<String>)> = HashMap::new();

    for row in &events {
        let event_id: i64 = column(row, 0)?;
        let session_id: i32 = column(row, 1)?;
        if !session_ids.contains(&session_id) {
            continue;
        }
        let event_type: String = column(row, 2)?;
        let thread_id: Option<i32> = column(row, 3)?;
        let selected_thread_id: Option<i32> = column(row, 4)?;
        let die_after: Option<i32> = column(row, 5)?;
        let context_text: Option<String> = column(row, 6)?;
        let result: Option<i32> = column(row, 7)?;
        let issues_read: Option<i32> = column(row, 8)?;
        let rating: Option<f64> = column(row, 9)?;
        let issue_id: Option<i32> = column(row, 10)?;
        let issue_number: Option<String> = column(row, 11)?;

        if event_type == "roll" {
            if let Some(selected) = selected_thread_id {
                latest_roll.insert(
                    session_id,
                    RollEvent {
                        selected_thread_id: selected,
                        result,
                    },
                );
                record_issue_identity(
                    &mut issue_identity,
                    session_id,
                    selected,
                    issue_id,
                    issue_number,
                    true,
                );
            }
        } else if event_type == "rate" {
            if let Some(thread) = thread_id {
                record_issue_identity(
                    &mut issue_identity,
                    session_id,
                    thread,
                    issue_id,
                    issue_number,
                    false,
                );
            }
            let entry = rate_agg.entry(session_id).or_default();
            if let Some(read) = issues_read {
                entry.issues_read += read;
            }
            if rating.is_some() {
                entry.last_rating = rating;
            }
            open_rate_ids.entry(session_id).or_default().push(event_id);
        } else if event_type == "undo" {
            if let Some(open) = open_rate_ids.get_mut(&session_id) {
                if let Some(undone) = open.pop() {
                    undone_rate_ids.insert(undone);
                }
            }
        }

        if is_die_event(&event_type) {
            if let Some(after) = die_after {
                die_path.entry(session_id).or_default().push(after);
                let context = context_text
                    .as_deref()
                    .and_then(|text| serde_json::from_str(text).ok())
                    .unwrap_or(Value::Null);
                latest_die.insert(session_id, (after, context));
            }
        }
    }

    // An undone rating is subtracted from the aggregate again, and the last
    // remaining rating replaces the aggregate's rating.
    for row in &events {
        let event_id: i64 = column(row, 0)?;
        if !undone_rate_ids.contains(&event_id) {
            continue;
        }
        let session_id: i32 = column(row, 1)?;
        let event_type: String = column(row, 2)?;
        if event_type != "rate" {
            continue;
        }
        let issues_read: Option<i32> = column(row, 8)?;
        let rating: Option<f64> = column(row, 9)?;
        if let Some(entry) = rate_agg.get_mut(&session_id) {
            if let Some(read) = issues_read {
                entry.issues_read = entry.issues_read.saturating_sub(read);
            }
            if rating.is_some() {
                entry.last_rating = None;
                for candidate in &events {
                    let candidate_id: i64 = column(candidate, 0)?;
                    if undone_rate_ids.contains(&candidate_id) {
                        continue;
                    }
                    let candidate_session: i32 = column(candidate, 1)?;
                    let candidate_type: String = column(candidate, 2)?;
                    if candidate_session == session_id && candidate_type == "rate" {
                        entry.last_rating = column::<Option<f64>>(candidate, 9)?;
                    }
                }
            }
        }
    }

    let snapshot_counts: HashMap<i32, i32> = {
        let rows = connection
            .query(SNAPSHOT_COUNT_SQL, &[&session_ids])
            .await
            .map_err(db::query_error)?;
        rows.iter()
            .map(|row| Ok((column::<i32>(row, 0)?, column::<i32>(row, 1)?)))
            .collect::<Result<HashMap<i32, i32>, ApiError>>()?
    };

    // Threads named by the page's rolls and pending selections.
    let mut thread_ids: HashSet<i32> = HashSet::new();
    for session_id in &session_ids {
        if let Some(roll) = latest_roll.get(session_id) {
            thread_ids.insert(roll.selected_thread_id);
        }
        if let Some(pending) = pending_thread_id(row_for(page, *session_id))? {
            thread_ids.insert(pending);
        }
    }
    let thread_ids: Vec<i32> = thread_ids.into_iter().collect();

    let mut threads: HashMap<i32, ThreadRow> = HashMap::new();
    let mut unread_counts: HashMap<i32, i32> = HashMap::new();
    let mut issue_numbers: HashMap<i32, Option<String>> = HashMap::new();
    let mut tags: HashMap<i32, Vec<SessionTag>> = HashMap::new();
    let mut positions: HashMap<i32, i32> = HashMap::new();

    if !thread_ids.is_empty() {
        let rows = connection
            .query(THREADS_SQL, &[&thread_ids])
            .await
            .map_err(db::query_error)?;
        for row in &rows {
            let thread = ThreadRow {
                id: column(row, 0)?,
                title: column(row, 1)?,
                format: column(row, 2)?,
                issues_remaining: column(row, 3)?,
                total_issues: column(row, 4)?,
                reading_progress: column(row, 5)?,
                next_unread_issue_id: column(row, 6)?,
            };
            threads.insert(thread.id, thread);
        }

        let tracking_ids: Vec<i32> = thread_ids
            .iter()
            .copied()
            .filter(|id| {
                threads
                    .get(id)
                    .and_then(|thread| thread.total_issues)
                    .is_some()
            })
            .collect();
        if !tracking_ids.is_empty() {
            let rows = connection
                .query(UNREAD_COUNT_SQL, &[&tracking_ids])
                .await
                .map_err(db::query_error)?;
            for row in &rows {
                unread_counts.insert(column::<i32>(row, 0)?, column::<i32>(row, 1)?);
            }
        }

        let next_issue_ids: Vec<i32> = thread_ids
            .iter()
            .copied()
            .filter_map(|id| {
                threads
                    .get(&id)
                    .and_then(|thread| thread.next_unread_issue_id)
            })
            .collect();
        if !next_issue_ids.is_empty() {
            let rows = connection
                .query(NEXT_ISSUE_SQL, &[&next_issue_ids])
                .await
                .map_err(db::query_error)?;
            for row in &rows {
                issue_numbers.insert(column::<i32>(row, 0)?, column::<Option<String>>(row, 1)?);
            }
        }

        let rows = connection
            .query(TAGS_SQL, &[&thread_ids, &user.id()])
            .await
            .map_err(db::query_error)?;
        for row in &rows {
            let target_id: i32 = column(row, 0)?;
            let tag = SessionTag {
                id: column(row, 1)?,
                name: column(row, 2)?,
                normalized_name: column(row, 3)?,
                scope: column(row, 4)?,
                owner_user_id: column(row, 5)?,
                color: column(row, 6)?,
                created_at: column(row, 7)?,
                updated_at: column(row, 8)?,
            };
            tags.entry(target_id).or_default().push(tag);
        }
    }

    // One whole-queue read resolves every position on the page.
    {
        let rows = connection
            .query(QUEUE_POSITIONS_SQL, &[&user.id()])
            .await
            .map_err(db::query_error)?;
        for row in &rows {
            positions.insert(column::<i32>(row, 0)?, column::<i32>(row, 1)?);
        }
    }

    let mut sessions: Vec<SessionListItemResponse> = Vec::with_capacity(page.len());
    for row in page {
        let session_id: i32 = column(row, 0)?;
        let started_at: String = column(row, 1)?;
        let ended_at: Option<String> = column(row, 2)?;
        let start_die: i32 = column(row, 3)?;
        let manual_die: Option<i32> = column(row, 4)?;
        let owner_id: i32 = column(row, 5)?;
        let pending_thread_id: Option<i32> = column(row, 6)?;

        let ladder = ladder_for(
            start_die,
            die_path.get(&session_id).map(Vec::as_slice).unwrap_or(&[]),
        );
        let resolved_die = match latest_die.get(&session_id) {
            Some((after, context)) => current_die(manual_die, Some((*after, context)), start_die),
            None => current_die(manual_die, None, start_die),
        };
        let snapshot_count = snapshot_counts.get(&session_id).copied().unwrap_or(0);
        let aggregate = rate_agg.get(&session_id).copied().unwrap_or_default();

        // The session's latest roll decides the active series; a session
        // without one falls back to its pending selection.
        let active_thread = match latest_roll.get(&session_id) {
            Some(roll) => threads.get(&roll.selected_thread_id).map(|thread| {
                let result = roll.result.filter(|value| *value > 0);
                build_active_thread(
                    thread,
                    result,
                    aggregate,
                    &issue_identity,
                    &unread_counts,
                    &issue_numbers,
                    &positions,
                    &tags,
                    Some((session_id, roll.selected_thread_id)),
                )
            }),
            None => pending_thread_id
                .and_then(|pending| threads.get(&pending))
                .map(|thread| {
                    build_active_thread(
                        thread,
                        None,
                        aggregate,
                        &issue_identity,
                        &unread_counts,
                        &issue_numbers,
                        &positions,
                        &tags,
                        Some((session_id, thread.id)),
                    )
                }),
        };

        sessions.push(SessionListItemResponse {
            id: session_id,
            started_at,
            ended_at,
            start_die,
            manual_die,
            user_id: owner_id,
            ladder_path: ladder,
            last_rolled_result: active_thread
                .as_ref()
                .and_then(|thread| thread.last_rolled_result),
            active_thread,
            current_die: resolved_die,
            has_restore_point: snapshot_count > 0,
            snapshot_count,
            // Python's `_to_session_list_item` drops the reading-mode fields,
            // so the list never reports them.
            reading_bandwidth: None,
            reading_intent: None,
            reading_mode_source: None,
            reading_mode_suggested: false,
        });
    }

    let next_page_token = if has_more {
        let last = page
            .last()
            .ok_or_else(|| ApiError::Internal("Internal Server Error".to_string()))?;
        let started_at: String = column(last, 1)?;
        let id: i32 = column(last, 0)?;
        Some(format!("{started_at}+00:00,{id}"))
    } else {
        None
    };

    Ok(Json(SessionHistoryListResponse {
        sessions,
        next_page_token,
    }))
}

/// The columns of one page row.
struct ThreadRow {
    id: i32,
    title: String,
    format: String,
    issues_remaining: i32,
    total_issues: Option<i32>,
    reading_progress: Option<String>,
    next_unread_issue_id: Option<i32>,
}

/// Python's die-moving event types (`_DIE_EVENT_TYPES`).
fn is_die_event(event_type: &str) -> bool {
    matches!(
        event_type,
        "rate" | "snooze" | "undo" | "reset_dice" | "manual_die"
    )
}

/// Remember the issue identity an event recorded for one thread.
///
/// A roll always establishes the identity; a rating only contributes when no
/// roll for that thread already established it (#3708).
fn record_issue_identity(
    identity: &mut HashMap<(i32, i32), (Option<i32>, Option<String>)>,
    session_id: i32,
    thread_id: i32,
    issue_id: Option<i32>,
    issue_number: Option<String>,
    overwrite: bool,
) {
    if issue_id.is_none() && issue_number.is_none() {
        return;
    }
    let key = (session_id, thread_id);
    if overwrite || !identity.contains_key(&key) {
        identity.insert(key, (issue_id, issue_number));
    }
}

/// Build the active-thread projection for one history row.
#[allow(clippy::too_many_arguments)]
fn build_active_thread(
    thread: &ThreadRow,
    last_rolled_result: Option<i32>,
    aggregate: RateAggregate,
    issue_identity: &HashMap<(i32, i32), (Option<i32>, Option<String>)>,
    unread_counts: &HashMap<i32, i32>,
    issue_numbers: &HashMap<i32, Option<String>>,
    positions: &HashMap<i32, i32>,
    tags: &HashMap<i32, Vec<SessionTag>>,
    identity_key: Option<(i32, i32)>,
) -> SessionActiveThread {
    let uses_issue_tracking = thread.total_issues.is_some();
    let issues_remaining = if uses_issue_tracking {
        unread_counts.get(&thread.id).copied().unwrap_or(0)
    } else {
        thread.issues_remaining
    };

    let (issue_id, issue_number) = match identity_key
        .and_then(|key| issue_identity.get(&key))
        .cloned()
    {
        Some(identity) => identity,
        None => match thread.next_unread_issue_id {
            Some(next) if uses_issue_tracking => match issue_numbers.get(&next) {
                Some(Some(number)) => (Some(next), Some(number.clone())),
                _ => (None, None),
            },
            _ => (None, None),
        },
    };

    SessionActiveThread {
        id: thread.id,
        title: thread.title.clone(),
        format: normalize_format(&thread.format),
        issues_remaining,
        queue_position: positions.get(&thread.id).copied().unwrap_or(0),
        last_rolled_result,
        total_issues: thread.total_issues,
        reading_progress: thread.reading_progress.clone(),
        issues_read: if aggregate.issues_read > 0 {
            Some(aggregate.issues_read)
        } else {
            None
        },
        last_rating: aggregate.last_rating,
        tags: tags.get(&thread.id).cloned().unwrap_or_default(),
        issue_id,
        issue_number: issue_number.clone(),
        next_issue_id: issue_id,
        next_issue_number: issue_number,
    }
}

/// Find the page row of one session.
fn row_for<'a>(
    page: &'a [tokio_postgres::Row],
    session_id: i32,
) -> Result<&'a tokio_postgres::Row, ApiError> {
    page.iter()
        .find(|row| {
            row.try_get::<_, i32>(0)
                .map(|id| id == session_id)
                .unwrap_or(false)
        })
        .ok_or_else(|| internal())
}

/// Parse Python's `started_at,session_id` cursor.
fn parse_page_token(token: &str) -> Result<(DateTime<Utc>, i32), ApiError> {
    let parts: Vec<&str> = token.split(',').collect();
    if parts.len() != 2 {
        return Err(bad_request("Invalid page_token format".to_string()));
    }
    let started_at = DateTime::parse_from_rfc3339(parts[0])
        .map_err(|_| bad_request("Invalid page_token format".to_string()))?
        .with_timezone(&Utc);
    let session_id = parts[1]
        .parse::<i32>()
        .map_err(|_| bad_request("Invalid page_token format".to_string()))?;
    Ok((started_at, session_id))
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
        (status = 200, description = "Paginated session history", body = SessionHistoryListResponse),
        (status = 400, description = "Invalid page_token"),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Invalid page_size"),
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
        (status = 200, description = "Paginated session history", body = SessionHistoryListResponse),
        (status = 400, description = "Invalid page_token"),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Invalid page_size"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_sessions_v1_documentation() {}

/// OpenAPI document for the session-history list same-path surface.
#[derive(utoipa::OpenApi)]
#[openapi(
    paths(list_sessions_documentation, list_sessions_v1_documentation),
    components(schemas(
        SessionTag,
        SessionActiveThread,
        SessionListItemResponse,
        SessionHistoryListResponse
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
    fn die_event_types_match_python() {
        assert!(is_die_event("rate"));
        assert!(is_die_event("snooze"));
        assert!(is_die_event("undo"));
        assert!(is_die_event("reset_dice"));
        assert!(is_die_event("manual_die"));
        assert!(!is_die_event("rolled_but_skipped"));
        assert!(!is_die_event("restore"));
        assert!(!is_die_event("unsnooze"));
        assert!(!is_die_event("dismiss"));
    }

    #[test]
    fn page_token_round_trips_through_the_cursor_format() {
        let (started_at, session_id) =
            parse_page_token("2026-01-01T00:00:00.123456+00:00,42").expect("token");
        assert_eq!(started_at.to_rfc3339(), "2026-01-01T00:00:00.123456+00:00");
        assert_eq!(session_id, 42);
    }

    #[test]
    fn malformed_page_token_is_a_bad_request() {
        for token in ["", "2026-01-01T00:00:00+00:00", "a,b,c", "not-a-date,1", "2026-01-01T00:00:00+00:00,x"]
        {
            let error = parse_page_token(token).expect_err("token must be rejected");
            assert_eq!(error.status(), StatusCode::BAD_REQUEST);
            assert_eq!(error.detail(), "Invalid page_token format");
        }
    }

    #[test]
    fn issue_identity_prefers_the_rolled_issue_over_a_later_rating() {
        let mut identity: HashMap<(i32, i32), (Option<i32>, Option<String>)> = HashMap::new();
        record_issue_identity(&mut identity, 7, 11, Some(3), Some("5".to_string()), true);
        record_issue_identity(&mut identity, 7, 11, Some(9), Some("9".to_string()), false);
        assert_eq!(
            identity.get(&(7, 11)),
            Some(&(Some(3), Some("5".to_string())))
        );
    }

    #[test]
    fn session_list_sql_is_owner_scoped_and_bounded() {
        assert!(SESSION_LIST_SQL.contains("WHERE user_id = $1"));
        assert!(SESSION_LIST_SQL.contains("LIMIT $2"));
        assert!(SESSION_LIST_CURSOR_SQL.contains("WHERE user_id = $1"));
        assert!(SESSION_LIST_CURSOR_SQL.contains("started_at < $2"));
        assert!(!SESSION_LIST_SQL.contains(';'));
        assert!(HISTORY_EVENTS_SQL.contains("session_id = ANY($1)"));
        assert!(SNAPSHOT_COUNT_SQL.contains("session_id = ANY($1)"));
        assert!(UNREAD_COUNT_SQL.contains("thread_id = ANY($1)"));
        assert!(TAGS_SQL.contains("assignment.target_id = ANY($1)"));
        assert!(QUEUE_POSITIONS_SQL.contains("row_number()"));
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
            assert!(operation["responses"]["422"].as_object().is_some());
            assert!(operation["security"].is_array());
        }
        assert!(document["components"]["schemas"]["SessionHistoryListResponse"].is_object());
        assert!(document["components"]["schemas"]["SessionListItemResponse"].is_object());
    }

    #[test]
    fn session_list_item_keeps_python_unset_reading_mode_fields() {
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
        assert_eq!(value["reading_bandwidth"], Value::Null);
        assert_eq!(value["reading_mode_suggested"], json!(false));
        assert_eq!(value["next_page_token"], Value::Null);
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
                "INSERT INTO users (id, username) VALUES (9401, 'session-list-test'), (9402, 'session-list-other');
                 INSERT INTO threads (id, user_id, title, format, issues_remaining, total_issues, reading_progress, queue_position, status, is_blocked) VALUES (9401, 9401, 'Owned Comic', 'comics', 3, NULL, NULL, 1, 'active', false), (9402, 9402, 'Foreign Comic', 'Comic', 2, NULL, NULL, 1, 'active', false);
                 INSERT INTO sessions (id, user_id, started_at, ended_at, start_die, manual_die, pending_thread_id, reading_mode_suggested) VALUES (9501, 9401, NOW(), NULL, 6, NULL, NULL, false), (9502, 9402, NOW(), NULL, 6, NULL, NULL, false);
                 INSERT INTO events (session_id, type, timestamp, selected_thread_id, thread_id, die, die_after, result, issues_read, rating) VALUES (9501, 'roll', NOW(), 9401, NULL, 6, NULL, 4, NULL, NULL), (9501, 'rate', NOW() + interval '1 minute', NULL, 9401, 6, 4, NULL, 2, 4.5);",
            )
            .await
            .expect("seed session list fixture");
        drop(connection);
        (state, AuthenticatedUser::for_test(9401), guard)
    }

    #[tokio::test]
    async fn list_sessions_returns_only_owned_sessions_with_the_rolled_thread() {
        let (state, user, _guard) = database_fixture().await;
        let Json(response) = list_sessions(
            Query(SessionListQuery {
                page_size: DEFAULT_PAGE_SIZE,
                page_token: None,
            }),
            user,
            State(state.clone()),
        )
        .await
        .expect("owned list");
        assert_eq!(response.sessions.len(), 1);
        let session = &response.sessions[0];
        assert_eq!(session.id, 9501);
        assert_eq!(session.user_id, 9401);
        assert_eq!(session.ladder_path, "6 → 4");
        assert_eq!(session.current_die, 4);
        assert_eq!(session.reading_bandwidth, None);
        assert_eq!(session.reading_mode_suggested, false);
        let active = session.active_thread.as_ref().expect("rolled thread");
        assert_eq!(active.id, 9401);
        assert_eq!(active.title, "Owned Comic");
        assert_eq!(active.format, "Comic");
        assert_eq!(active.issues_remaining, 3);
        assert_eq!(active.queue_position, 1);
        assert_eq!(active.last_rolled_result, Some(4));
        assert_eq!(active.issues_read, Some(2));
        assert_eq!(active.last_rating, Some(4.5));
    }

    #[tokio::test]
    async fn list_sessions_rejects_an_out_of_range_page_size() {
        let (state, user, _guard) = database_fixture().await;
        let error = list_sessions(
            Query(SessionListQuery {
                page_size: 0,
                page_token: None,
            }),
            user,
            State(state.clone()),
        )
        .await
        .expect_err("page_size must be rejected");
        assert_eq!(error.status(), StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[tokio::test]
    async fn list_sessions_requires_auth_through_service_router() {
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
        for uri in ["/api/sessions/", "/api/v1/sessions/"] {
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
