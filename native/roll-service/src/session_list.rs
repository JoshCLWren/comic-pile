//! Native same-path session list reads (#4839, parent #4335).
//!
//! Migrates the remaining browser-called session operations to the native
//! Rust router with identical method/path and wire contract:
//!
//! * `GET /api/sessions/` and `GET /api/v1/sessions/` - paginated session history
//!
//! Wire parity with Python `list_sessions` (`app/api/session.py`):
//!
//! * Ownership: all queries scoped to `user_id = $1`
//! * Pagination: cursor-based on `(started_at DESC, id DESC)` with `page_size` (1..200, default 50) and `page_token` ("started_at,id")
//! * `ladder_path`: `build_ladder_path` — `start_die` followed by every `die_after` from `rate`/`snooze`/`undo` events in timestamp/id order, joined with `" → "`.
//! * `active_thread`: latest `roll`/`rate`/`snooze`/`rolled_but_skipped` event; pending thread wins; missing pending yields `null` without fall-through. `issues_remaining` counts unread `issues` when thread uses issue tracking, otherwise stored counter. `queue_position` is legacy dense display ordinal.
//! * `format` normalization, direct visible tags ordered by scope descending then normalized name, and `next_issue_*` from `next_unread_issue_id` when issue tracking is in use.
//! * List view (`SessionListItem`) omits `snoozed_*` / `skipped_*` / `pending_thread_id` / `timezone` / `bandwidth` / `intent` / `correction` to reduce payload.
//! * Timestamps emitted as UTC `...Z` strings (matching session-detail Rust slice).
//!
//! Bounded reads only: one session page, one snapshot count per session, two die-event reads per session, one latest-action read per session, and at most one active thread per session with one unread count, one next-issue read, one tag read and one ranked queue read. No per-row fan-out across the page.

#![forbid(unsafe_code)]

use crate::{
    auth::AuthenticatedUser, db, reading_session::automatic_die_after, ApiError, AppState,
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
// utoipa's `IntoParams` defaults to `path`; the Python contract and the frontend
// both send these as query parameters, so declare the correct wire location.
#[into_params(parameter_in = Query)]
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
const SESSION_PAGE_WITH_CURSOR_SQL: &str = "SELECT id, to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(ended_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), start_die, manual_die, user_id, pending_thread_id, timezone, reading_bandwidth, reading_intent, reading_mode_source, reading_mode_suggested FROM sessions WHERE user_id = $1 AND (started_at < $2 OR (started_at = $2 AND id > $3)) ORDER BY started_at DESC, id DESC LIMIT $4";
const SNAPSHOT_COUNT_SQL: &str = "SELECT session_id, count(*)::int FROM snapshots WHERE session_id = ANY($1) GROUP BY session_id";
const LADDER_SQL: &str = "SELECT session_id, die_after FROM events WHERE session_id = ANY($1) AND type IN ('rate','snooze','undo','reset_dice','manual_die') AND die_after IS NOT NULL ORDER BY session_id, timestamp ASC, id ASC";
const CURRENT_DIE_SQL: &str = "SELECT session_id, die_after, context::text FROM events WHERE session_id = ANY($1) AND type IN ('rate','snooze','undo','reset_dice','manual_die') AND die_after IS NOT NULL ORDER BY session_id, timestamp DESC, id DESC";
const LATEST_ROLL_SQL: &str = "SELECT session_id, selected_thread_id, result FROM events WHERE session_id = ANY($1) AND type = 'roll' ORDER BY session_id, timestamp DESC, id DESC";
// Python `project_session_history_events` records the issue identity an event
// established for a thread inside a session; it is the immutable source for a
// History card and wins over the thread's current `next_unread_issue_id`.
const ISSUE_IDENTITY_SQL: &str = "SELECT session_id, type, selected_thread_id, thread_id, issue_id, issue_number FROM events WHERE session_id = ANY($1) AND type IN ('roll','rate') AND (selected_thread_id IS NOT NULL OR thread_id IS NOT NULL) ORDER BY session_id, timestamp ASC, id ASC";
const RATES_UNDO_SQL: &str = "SELECT session_id, type, issues_read, rating FROM events WHERE session_id = ANY($1) AND type IN ('rate','undo') ORDER BY session_id, timestamp ASC, id ASC";
const TAGS_ANY_SQL: &str = "SELECT tag.id, tag.name, tag.normalized_name, tag.scope, tag.owner_user_id, tag.color, to_char(tag.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(tag.updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), assignment.target_id FROM tag_assignments assignment JOIN tags tag ON tag.id = assignment.tag_id WHERE assignment.target_type = 'Thread' AND assignment.target_id = ANY($1) AND (tag.scope = 'global' OR tag.owner_user_id = $2) ORDER BY tag.scope DESC, tag.normalized_name ASC";
const QUEUE_POSITION_ANY_SQL: &str = "SELECT id, seq::int FROM (SELECT id, row_number() OVER (ORDER BY is_blocked ASC, queue_position ASC, id ASC) AS seq FROM threads WHERE user_id = $1 AND status = 'active' AND queue_position >= 1) ranked WHERE id = ANY($2)";

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

    // Python `project_session_history_events` keyed issue identity by
    // (session_id, thread_id): a roll overwrites the recorded identity while a
    // rate only contributes when no roll has established one for that thread.
    let identity_rows = connection
        .query(ISSUE_IDENTITY_SQL, &[&session_ids])
        .await
        .map_err(db::query_error)?;
    let mut issue_by_session_thread: std::collections::HashMap<
        (i32, i32),
        (Option<i32>, Option<String>),
    > = std::collections::HashMap::new();
    for row in &identity_rows {
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
        let selected_thread_id: Option<i32> = row.try_get(2).ok();
        let thread_id: Option<i32> = row.try_get(3).ok();
        let issue_id: Option<i32> = row.try_get(4).ok();
        let issue_number: Option<String> = row.try_get(5).ok();
        if issue_id.is_none() && issue_number.is_none() {
            continue;
        }
        let key = if event_type == "roll" {
            selected_thread_id.map(|tid| (sid, tid))
        } else {
            thread_id.map(|tid| (sid, tid))
        };
        let Some(key) = key else { continue };
        if event_type == "roll" {
            issue_by_session_thread.insert(key, (issue_id, issue_number));
        } else {
            issue_by_session_thread
                .entry(key)
                .or_insert((issue_id, issue_number));
        }
    }

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

                            // Prefer the identity the session recorded for this
                            // thread over the thread's current next-unread issue,
                            // so History rows never borrow another series' number.
                            let (issue_id, issue_number) = if let Some(historical) =
                                issue_by_session_thread.get(&(sid, thread_id_value))
                            {
                                (historical.0, historical.1.clone())
                            } else {
                                match next_unread_issue_id {
                                    Some(current_id) if total_issues.is_some() => next_issue_map
                                        .get(&current_id)
                                        .map(|(id, num)| (Some(*id), num.clone()))
                                        .unwrap_or((None, None)),
                                    _ => (None, None),
                                }
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
                                issue_id,
                                issue_number: issue_number.clone(),
                                next_issue_id: issue_id,
                                next_issue_number: issue_number,
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
        // Python: `active_thread.last_rolled_result if active_thread else None`.
        // A session with no active thread has no result, even if it has roll
        // events in the action stream.
        let last_rolled_result = active_thread.as_ref().and_then(|t| t.last_rolled_result);

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

/// OpenAPI document for the session list same-path surface.
#[derive(utoipa::OpenApi)]
#[openapi(
    paths(
        list_sessions_documentation,
        list_sessions_v1_documentation
    ),
    components(schemas(
        SessionListParams,
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
        for path in ["/api/sessions/", "/api/v1/sessions/"] {
            let operation = &document["paths"][path]["get"];
            assert!(operation["operationId"].is_string());
            assert!(operation["responses"]["200"].as_object().is_some());
            assert!(operation["security"].is_array());
        }
        assert!(document["components"]["schemas"]["SessionHistoryListResponse"].is_object());
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
                 INSERT INTO threads (id, user_id, title, format, issues_remaining, total_issues, reading_progress, queue_position, status, is_blocked) VALUES (9201, 9101, 'Owned Comic', 'comics', 3, NULL, NULL, 1, 'active', false), (9202, 9102, 'Foreign Comic', 'Comic', 2, NULL, NULL, 1, 'active', false), (9204, 9101, 'Series A', 'Comic', 5, 5, NULL, 2, 'active', false);
                 INSERT INTO issues (id, thread_id, issue_number, status, created_at, position) VALUES (9401, 9204, '1', 'unread', NOW(), 1), (9402, 9204, '2', 'unread', NOW(), 2);
                 UPDATE threads SET next_unread_issue_id = 9402 WHERE id = 9204;
                 INSERT INTO sessions (id, user_id, started_at, ended_at, start_die, manual_die, pending_thread_id, reading_mode_suggested) VALUES (9301, 9101, NOW() - interval '1 minute', NULL, 6, NULL, 9201, false), (9302, 9102, NOW(), NULL, 6, NULL, 9202, false), (9303, 9101, NOW(), NULL, 6, NULL, NULL, false), (9304, 9101, NOW() - interval '2 minutes', NULL, 6, NULL, NULL, false), (9305, 9101, NOW() - interval '3 minutes', NULL, 6, NULL, NULL, false);
                 INSERT INTO events (session_id, type, timestamp, selected_thread_id, thread_id, die, die_after, result) VALUES (9301, 'roll', NOW() - interval '1 minute', 9201, NULL, 6, NULL, 4), (9301, 'rate', NOW(), NULL, 9201, 6, 4, NULL), (9303, 'roll', NOW(), 9201, NULL, 6, NULL, 2);
                 INSERT INTO events (session_id, type, timestamp, selected_thread_id, thread_id, issue_id, issue_number, die, die_after, result) VALUES (9304, 'roll', NOW() - interval '2 minutes', 9204, NULL, 9401, '1', 6, NULL, 3), (9305, 'roll', NOW() - interval '3 minutes', NULL, NULL, NULL, NULL, 6, NULL, 6);",
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
        assert_eq!(response.sessions.len(), 4);
        // started_at DESC puts the newest session first.
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

    #[test]
    fn session_list_openapi_params_are_query_location() {
        let document = serde_json::to_value(SessionListApi::openapi()).expect("openapi");
        for path in ["/api/sessions/", "/api/v1/sessions/"] {
            let params = document["paths"][path]["get"]["parameters"]
                .as_array()
                .expect("parameters");
            assert!(
                params
                    .iter()
                    .any(|param| param["name"] == "page_size" && param["in"] == "query"),
                "page_size must be a query parameter on {}",
                path
            );
            assert!(
                params
                    .iter()
                    .any(|param| param["name"] == "page_token" && param["in"] == "query"),
                "page_token must be a query parameter on {}",
                path
            );
        }
    }

    #[test]
    fn session_page_cursor_predicate_matches_python() {
        assert!(
            SESSION_PAGE_WITH_CURSOR_SQL
                .contains("started_at < $2 OR (started_at = $2 AND id > $3)"),
            "cursor must match Python's `started_at < cursor OR (started_at == cursor AND id > cursor_id)`"
        );
    }

    #[tokio::test]
    async fn list_sessions_uses_historical_issue_identity() {
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
        let session = response
            .sessions
            .iter()
            .find(|session| session.id == 9304)
            .expect("session 9304");
        let active = session.active_thread.as_ref().expect("active thread");
        // The roll recorded issue 9401 ('1') for this thread; the thread's
        // current next_unread_issue_id points at 9402 ('2') and must not win.
        assert_eq!(active.issue_id, Some(9401));
        assert_eq!(active.issue_number.as_deref(), Some("1"));
        assert_eq!(active.next_issue_id, Some(9401));
        assert_eq!(active.next_issue_number.as_deref(), Some("1"));
    }

    #[tokio::test]
    async fn list_sessions_last_rolled_result_has_no_event_fallback() {
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
        let session = response
            .sessions
            .iter()
            .find(|session| session.id == 9305)
            .expect("session 9305");
        assert!(
            session.active_thread.is_none(),
            "a roll without a selected thread has no active thread"
        );
        assert_eq!(
            session.last_rolled_result, None,
            "Python returns None when there is no active thread"
        );
    }
}
