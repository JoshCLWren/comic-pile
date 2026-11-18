//! Same-path Rust cutover for the browser-called issue read-state routes
//! (#4832, part C).
//!
//! Replaces the frozen Python handlers in `app/api/issue.py` and
//! `app/services/issue.py` at the identical HTTP methods and paths:
//!
//! * `POST /api/v1/issues/{issue_id}:markRead`
//! * `POST /api/v1/issues/{issue_id}:markUnread`
//! * `POST /api/v1/issues/{issue_id}:move`
//! * `POST /api/v1/issues:bulkMarkRead`
//! * `POST /api/v1/issues:bulkMarkUnread`
//! * `GET  /api/v1/issues/{issue_id}/reader-context` (see [`crate::reader_context`])
//!
//! Every mutation runs in one transaction that takes the per-reader queue
//! advisory lock first (the global lock order every queue writer uses), then
//! row locks, and mirrors the Python side effects exactly: issue
//! `status`/`read_at`, the thread's `next_unread_issue_id`,
//! `issues_remaining`, `reading_progress`, derived lifecycle status (an
//! excluded series is never overwritten and completing a series ends its
//! manual queue claim), queue renumbering, the `issue_read`/`issue_unread`
//! history events and the denormalized `threads.is_blocked` refresh.
//!
//! Wire parity:
//!
//! * Success is `204 No Content`. Missing and foreign issues are the same
//!   `404 {"detail": "Issue {id} not found"}`. Re-marking an issue is
//!   `400 "Issue {id} is already marked as read|unread"`. A bulk request
//!   fails on the first invalid id in request order, with nothing changed.
//! * Validation failures use the production FastAPI 422 body
//!   (`{"detail": "Validation failed"}` from `app/exception_handlers.py`),
//!   matching every other native v1 cutover (`thread_ordering.rs`). FastAPI's
//!   list-shaped development body is not reproduced. Authentication runs before
//!   validation, as in FastAPI.
//! * A bulk list that repeats an id records one history event per list entry,
//!   exactly like the Python loop.
//! * axum cannot express a parameter followed by `:action`, so the whole
//!   `{issue_id}:action` segment is captured and dispatched on its suffix
//!   (the same technique the thread-action dispatcher uses). Any other
//!   `POST /api/v1/issues/{segment}` is a 405, as in Starlette where the
//!   path matches the `GET` route only.

#![forbid(unsafe_code)]

use crate::{
    auth::AuthenticatedUser, db, issue_mutation, issue_service, reader_context, ApiError, AppState,
};
use axum::{
    body::Bytes,
    extract::{rejection::PathRejection, Path, State},
    http::StatusCode,
};
use serde_json::Value;
use std::sync::Arc;
use tokio_postgres::Transaction;

const MAX_BULK_ISSUES: usize = 100;

/// Production `RequestValidationError` body: `{"detail": "Validation failed"}`.
fn validation_failed() -> ApiError {
    ApiError::Unprocessable("Validation failed".into())
}

fn issue_not_found(issue_id: impl std::fmt::Display) -> ApiError {
    ApiError::NotFound(format!("Issue {issue_id} not found"))
}

/// Pydantic lax integer text: optional sign then ASCII digits (surrounding
/// whitespace is ignored).
fn parse_int_text(raw: &str) -> Option<i64> {
    let trimmed = raw.trim();
    let digits = trimmed.strip_prefix(['+', '-']).unwrap_or(trimmed);
    if digits.is_empty() || !digits.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    trimmed.parse().ok()
}

fn path_int_error(_raw: &str) -> ApiError {
    validation_failed()
}

/// Resolve an `issue_id` path value. Integers outside PostgreSQL's `integer`
/// range can never name a row, so they are an ordinary missing issue.
fn resolve_issue_id(raw: &str) -> Result<i32, ApiError> {
    let value = parse_int_text(raw).ok_or_else(|| path_int_error(raw))?;
    i32::try_from(value).map_err(|_| issue_not_found(value))
}

/// Parse the `{issue_id}` path segment of a single-segment route.
pub(crate) fn parse_path_issue_id(
    raw: Result<Path<String>, PathRejection>,
) -> Result<i32, ApiError> {
    let Path(raw) = raw.map_err(|_| path_int_error(""))?;
    resolve_issue_id(&raw)
}

/// One pydantic lax integer element.
fn lax_int(value: &Value) -> Option<i64> {
    match value {
        Value::Number(number) => number.as_i64().or_else(|| {
            number
                .as_f64()
                .filter(|float| float.is_finite() && float.fract() == 0.0 && float.abs() < 9.0e15)
                .map(|float| float as i64)
        }),
        Value::String(text) => parse_int_text(text),
        Value::Bool(flag) => Some(i64::from(*flag)),
        _ => None,
    }
}

/// Parse the JSON request body into a top-level object, FastAPI style.
fn body_object(body: &[u8]) -> Result<serde_json::Map<String, Value>, ApiError> {
    if body.iter().all(u8::is_ascii_whitespace) {
        return Err(validation_failed());
    }
    let value: Value = serde_json::from_slice(body).map_err(|_| validation_failed())?;
    match value {
        Value::Object(map) => Ok(map),
        _ => Err(validation_failed()),
    }
}

/// `IssueMoveRequest`: required nullable `after_issue_id >= 1`.
fn parse_move_body(body: &[u8]) -> Result<Option<i64>, ApiError> {
    let object = body_object(body)?;
    let Some(value) = object.get("after_issue_id") else {
        return Err(validation_failed());
    };
    if value.is_null() {
        return Ok(None);
    }
    match lax_int(value) {
        Some(int) if int >= 1 => Ok(Some(int)),
        _ => Err(validation_failed()),
    }
}

/// `IssueBulkMarkReadRequest` / `IssueBulkMarkUnreadRequest`: 1..=100 integers.
fn parse_bulk_body(body: &[u8]) -> Result<Vec<i64>, ApiError> {
    let object = body_object(body)?;
    let Some(value) = object.get("issue_ids") else {
        return Err(validation_failed());
    };
    let Value::Array(items) = value else {
        return Err(validation_failed());
    };
    if items.is_empty() || items.len() > MAX_BULK_ISSUES {
        return Err(validation_failed());
    }
    items
        .iter()
        .map(|item| lax_int(item).ok_or_else(validation_failed))
        .collect()
}

#[derive(Clone)]
struct OwnedIssue {
    id: i32,
    thread_id: i32,
    issue_number: String,
    status: String,
    position: i32,
}

async fn owned_issue(
    tx: &Transaction<'_>,
    user_id: i32,
    issue_id: i32,
) -> Result<OwnedIssue, ApiError> {
    let row = tx
        .query_opt(
            "SELECT i.id, i.thread_id, i.issue_number, i.status, i.position
             FROM issues i JOIN threads t ON t.id = i.thread_id
             WHERE i.id = $1 AND t.user_id = $2",
            &[&issue_id, &user_id],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| issue_not_found(issue_id))?;
    Ok(OwnedIssue {
        id: row.get(0),
        thread_id: row.get(1),
        issue_number: row.get(2),
        status: row.get(3),
        position: row.get(4),
    })
}

struct ThreadState {
    status: String,
    total_issues: Option<i32>,
    issues_remaining: i32,
    next_unread_issue_id: Option<i32>,
    queue_position: i32,
}

async fn lock_owned_thread(
    tx: &Transaction<'_>,
    user_id: i32,
    thread_id: i32,
) -> Result<ThreadState, ApiError> {
    let row = tx
        .query_opt(
            "SELECT status, total_issues, issues_remaining, next_unread_issue_id, queue_position
             FROM threads WHERE id = $1 AND user_id = $2 FOR UPDATE",
            &[&thread_id, &user_id],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound(format!("Thread {thread_id} not found")))?;
    Ok(ThreadState {
        status: row.get(0),
        total_issues: row.get(1),
        issues_remaining: row.get(2),
        next_unread_issue_id: row.get(3),
        queue_position: row.get(4),
    })
}

async fn begin(
    conn: &mut deadpool_postgres::Object,
) -> Result<deadpool_postgres::Transaction<'_>, ApiError> {
    conn.build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)
}

/// `Thread.apply_derived_status`: an excluded series keeps its status. Returns
/// whether the status was written. Completing ends any manual queue claim.
async fn apply_derived_status(
    tx: &Transaction<'_>,
    thread_id: i32,
    status: &str,
) -> Result<bool, ApiError> {
    let written = tx
        .execute(
            "UPDATE threads SET status = $2::text,
                    queue_position_is_manual = CASE WHEN $2::text = 'completed'
                        THEN FALSE ELSE queue_position_is_manual END
             WHERE id = $1 AND status <> 'excluded'",
            &[&thread_id, &status],
        )
        .await
        .map_err(db::query_error)?;
    Ok(written > 0)
}

/// Seat a reactivated series at the end of the active queue when it has none.
async fn seat_at_queue_end(
    tx: &Transaction<'_>,
    user_id: i32,
    thread_id: i32,
) -> Result<(), ApiError> {
    tx.execute(
        "UPDATE threads SET queue_position = (
             SELECT COALESCE(MAX(other.queue_position), 0) + 1
             FROM threads other
             WHERE other.user_id = $1 AND other.status = 'active'
               AND other.queue_position >= 1 AND other.id <> $2
         )
         WHERE id = $2 AND queue_position < 1",
        &[&user_id, &thread_id],
    )
    .await
    .map_err(db::query_error)?;
    Ok(())
}

/// `thread_repository.renormalize_queue_positions`: dense `1..N` active queue.
async fn renormalize_queue_positions(tx: &Transaction<'_>, user_id: i32) -> Result<(), ApiError> {
    tx.execute(
        "UPDATE threads t SET queue_position = ranked.seq
         FROM (
             SELECT id, row_number() OVER (ORDER BY queue_position, id)::int AS seq
             FROM threads
             WHERE user_id = $1 AND status = 'active' AND queue_position >= 1
         ) ranked
         WHERE t.id = ranked.id AND t.queue_position IS DISTINCT FROM ranked.seq",
        &[&user_id],
    )
    .await
    .map_err(db::query_error)?;
    Ok(())
}

/// `apply_thread_issue_tracking_state`: re-derive the thread counters from its
/// issue rows. Returns the new `next_unread_issue_id`. Lifecycle `status` is
/// left to the caller; a thread with nothing unread cannot be blocked.
async fn apply_tracking_state(
    tx: &Transaction<'_>,
    thread_id: i32,
) -> Result<Option<i32>, ApiError> {
    let row = tx
        .query_one(
            "UPDATE threads t SET
                 total_issues = s.total,
                 issues_remaining = s.unread,
                 next_unread_issue_id = s.next_id,
                 reading_progress = CASE WHEN s.unread = 0 THEN 'completed'
                                         WHEN s.unread = s.total THEN 'not_started'
                                         ELSE 'in_progress' END,
                 is_blocked = CASE WHEN s.unread = 0 THEN FALSE ELSE t.is_blocked END
             FROM (
                 SELECT count(*)::int AS total,
                        (count(*) FILTER (WHERE status = 'unread'))::int AS unread,
                        (SELECT id FROM issues WHERE thread_id = $1 AND status = 'unread'
                         ORDER BY position, id LIMIT 1) AS next_id
                 FROM issues WHERE thread_id = $1
             ) s
             WHERE t.id = $1
             RETURNING t.next_unread_issue_id",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(row.get(0))
}

async fn insert_history_event(
    tx: &Transaction<'_>,
    event_type: &str,
    user_id: i32,
    thread_id: i32,
    issue_id: i32,
    issue_number: &str,
) -> Result<(), ApiError> {
    tx.execute(
        "INSERT INTO events (type, timestamp, user_id, thread_id, issue_id, issue_number)
         VALUES ($1, NOW(), $2, $3, $4, $5)",
        &[&event_type, &user_id, &thread_id, &issue_id, &issue_number],
    )
    .await
    .map_err(db::query_error)?;
    Ok(())
}

async fn count_unread(tx: &Transaction<'_>, thread_id: i32) -> Result<i32, ApiError> {
    Ok(tx
        .query_one(
            "SELECT count(*)::int FROM issues WHERE thread_id = $1 AND status = 'unread'",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?
        .get(0))
}

async fn mark_issue_read(
    state: &AppState,
    user: AuthenticatedUser,
    issue_id: i32,
) -> Result<StatusCode, ApiError> {
    let mut conn = db::checkout(state).await?;
    let tx = begin(&mut conn).await?;
    issue_mutation::lock_reader(&tx, user.id()).await?;
    let issue = owned_issue(&tx, user.id(), issue_id).await?;
    let thread = lock_owned_thread(&tx, user.id(), issue.thread_id).await?;
    if issue.status == "read" {
        return Err(ApiError::BadRequest(format!(
            "Issue {issue_id} is already marked as read"
        )));
    }
    tx.execute(
        "UPDATE issues SET status = 'read', read_at = NOW() WHERE id = $1",
        &[&issue_id],
    )
    .await
    .map_err(db::query_error)?;

    let next_unread: Option<i32> = tx
        .query_opt(
            "SELECT id FROM issues WHERE thread_id = $1 AND status = 'unread'
             ORDER BY position, id LIMIT 1",
            &[&issue.thread_id],
        )
        .await
        .map_err(db::query_error)?
        .map(|row| row.get(0));
    if let Some(next_id) = next_unread {
        // `Thread.get_issues_remaining`: counted only once issue tracking is on.
        let remaining = if thread.total_issues.is_some() {
            count_unread(&tx, issue.thread_id).await?
        } else {
            thread.issues_remaining
        };
        tx.execute(
            "UPDATE threads SET next_unread_issue_id = $2, reading_progress = 'in_progress',
                    issues_remaining = $3
             WHERE id = $1",
            &[&issue.thread_id, &next_id, &remaining],
        )
        .await
        .map_err(db::query_error)?;
    } else {
        tx.execute(
            "UPDATE threads SET next_unread_issue_id = NULL, reading_progress = 'completed',
                    issues_remaining = 0
             WHERE id = $1",
            &[&issue.thread_id],
        )
        .await
        .map_err(db::query_error)?;
        if apply_derived_status(&tx, issue.thread_id, "completed").await? {
            renormalize_queue_positions(&tx, user.id()).await?;
        }
    }
    insert_history_event(
        &tx,
        "issue_read",
        user.id(),
        issue.thread_id,
        issue_id,
        &issue.issue_number,
    )
    .await?;
    issue_service::refresh_blocked_threads(&tx, user.id()).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(StatusCode::NO_CONTENT)
}

async fn mark_issue_unread(
    state: &AppState,
    user: AuthenticatedUser,
    issue_id: i32,
) -> Result<StatusCode, ApiError> {
    let mut conn = db::checkout(state).await?;
    let tx = begin(&mut conn).await?;
    // The queue lock precedes every row lock so reactivation's renumbering
    // cannot deadlock against a concurrent move or shuffle.
    issue_mutation::lock_reader(&tx, user.id()).await?;
    let issue = owned_issue(&tx, user.id(), issue_id).await?;
    let thread = lock_owned_thread(&tx, user.id(), issue.thread_id).await?;
    if issue.status == "unread" {
        return Err(ApiError::BadRequest(format!(
            "Issue {issue_id} is already marked as unread"
        )));
    }
    let thread_was_completed = thread.status == "completed";
    tx.execute(
        "UPDATE issues SET status = 'unread', read_at = NULL WHERE id = $1",
        &[&issue_id],
    )
    .await
    .map_err(db::query_error)?;

    let current_next_position: Option<i32> = match thread.next_unread_issue_id {
        Some(next_id) => tx
            .query_opt("SELECT position FROM issues WHERE id = $1", &[&next_id])
            .await
            .map_err(db::query_error)?
            .map(|row| row.get(0)),
        None => None,
    };
    let next_unread_issue_id = match current_next_position {
        Some(position) if issue.position >= position => thread.next_unread_issue_id,
        _ => Some(issue_id),
    };
    let remaining = if thread.total_issues.is_some() {
        count_unread(&tx, issue.thread_id).await?
    } else {
        thread.issues_remaining
    };
    tx.execute(
        "UPDATE threads SET next_unread_issue_id = $2, reading_progress = 'in_progress',
                issues_remaining = $3
         WHERE id = $1",
        &[&issue.thread_id, &next_unread_issue_id, &remaining],
    )
    .await
    .map_err(db::query_error)?;

    if thread_was_completed && apply_derived_status(&tx, issue.thread_id, "active").await? {
        if thread.queue_position < 1 {
            seat_at_queue_end(&tx, user.id(), issue.thread_id).await?;
        }
        renormalize_queue_positions(&tx, user.id()).await?;
    }
    insert_history_event(
        &tx,
        "issue_unread",
        user.id(),
        issue.thread_id,
        issue_id,
        &issue.issue_number,
    )
    .await?;
    issue_service::refresh_blocked_threads(&tx, user.id()).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(StatusCode::NO_CONTENT)
}

async fn bulk_mark(
    state: &AppState,
    user: AuthenticatedUser,
    requested: &[i64],
    mark_read: bool,
) -> Result<StatusCode, ApiError> {
    let (target_status, refused_status, event_type) = if mark_read {
        ("read", "read", "issue_read")
    } else {
        ("unread", "unread", "issue_unread")
    };
    let mut conn = db::checkout(state).await?;
    let tx = begin(&mut conn).await?;
    // Queue lock first, then row locks — one global order with every queue writer.
    issue_mutation::lock_reader(&tx, user.id()).await?;

    // Ids outside the int4 range cannot exist; they are checked in request order below.
    let convertible: Vec<Option<i32>> = requested
        .iter()
        .map(|raw_id| i32::try_from(*raw_id).ok())
        .collect();

    let distinct_ids: Vec<i32> = convertible
        .iter()
        .flatten()
        .copied()
        .collect::<std::collections::BTreeSet<_>>()
        .into_iter()
        .collect();
    let rows = tx
        .query(
            "SELECT i.id, i.thread_id, i.issue_number, i.status, i.position
             FROM issues i JOIN threads t ON t.id = i.thread_id
             WHERE t.user_id = $1 AND i.id = ANY($2::int[])",
            &[&user.id(), &distinct_ids],
        )
        .await
        .map_err(db::query_error)?;
    let mut by_id = std::collections::HashMap::<i32, OwnedIssue>::with_capacity(rows.len());
    for row in rows {
        let issue = OwnedIssue {
            id: row.get(0),
            thread_id: row.get(1),
            issue_number: row.get(2),
            status: row.get(3),
            position: row.get(4),
        };
        by_id.insert(issue.id, issue);
    }

    // Validate in request order (including duplicates) against the pre-update
    // state, so the first failing entry decides the error exactly like Python.
    let mut issues: Vec<OwnedIssue> = Vec::with_capacity(requested.len());
    for (raw_id, converted) in requested.iter().zip(&convertible) {
        let issue = converted
            .and_then(|issue_id| by_id.get(&issue_id).cloned())
            .ok_or_else(|| issue_not_found(raw_id))?;
        if issue.status == refused_status {
            return Err(ApiError::BadRequest(format!(
                "Issue {} is already marked as {refused_status}",
                issue.id
            )));
        }
        issues.push(issue);
    }

    tx.execute(
        "UPDATE issues SET status = $2::text,
                read_at = CASE WHEN $2::text = 'read' THEN NOW() ELSE NULL END
         WHERE id = ANY($1::int[])",
        &[&distinct_ids, &target_status],
    )
    .await
    .map_err(db::query_error)?;

    let thread_ids: Vec<i32> = issues
        .iter()
        .map(|issue| issue.thread_id)
        .collect::<std::collections::BTreeSet<_>>()
        .into_iter()
        .collect();
    let mut queue_changed = false;
    if !thread_ids.is_empty() {
        // Lock every affected thread row before mutating counters/queue state.
        tx.query(
            "SELECT id FROM threads WHERE id = ANY($1::int[]) AND user_id = $2 ORDER BY id FOR UPDATE",
            &[&thread_ids, &user.id()],
        )
        .await
        .map_err(db::query_error)?;

        // Re-derive tracking counters for every affected thread in one statement.
        let tracked = tx
            .query(
                "UPDATE threads t SET
                     total_issues = s.total,
                     issues_remaining = s.unread,
                     next_unread_issue_id = s.next_id,
                     reading_progress = CASE WHEN s.unread = 0 THEN 'completed'
                                             WHEN s.unread = s.total THEN 'not_started'
                                             ELSE 'in_progress' END,
                     is_blocked = CASE WHEN s.unread = 0 THEN FALSE ELSE t.is_blocked END
                 FROM (
                     SELECT i.thread_id,
                            count(*)::int AS total,
                            (count(*) FILTER (WHERE i.status = 'unread'))::int AS unread,
                            (
                                SELECT i2.id FROM issues i2
                                WHERE i2.thread_id = i.thread_id AND i2.status = 'unread'
                                ORDER BY i2.position, i2.id LIMIT 1
                            ) AS next_id
                     FROM issues i
                     WHERE i.thread_id = ANY($1::int[])
                     GROUP BY i.thread_id
                 ) s
                 WHERE t.id = s.thread_id
                 RETURNING t.id,
                           t.status,
                           t.next_unread_issue_id IS NULL AS no_unread,
                           t.status = 'completed' AS was_completed",
                &[&thread_ids],
            )
            .await
            .map_err(db::query_error)?;

        let mut complete_ids: Vec<i32> = Vec::new();
        let mut reactivate_ids: Vec<i32> = Vec::new();
        for row in &tracked {
            let id: i32 = row.get(0);
            let status: String = row.get(1);
            let no_unread: bool = row.get(2);
            let was_completed: bool = row.get(3);
            if no_unread {
                complete_ids.push(id);
            } else if was_completed || status == "completed" {
                reactivate_ids.push(id);
            }
        }

        if !complete_ids.is_empty() {
            let written = tx
                .execute(
                    "UPDATE threads SET status = 'completed', queue_position_is_manual = FALSE
                     WHERE id = ANY($1::int[]) AND status <> 'excluded'",
                    &[&complete_ids],
                )
                .await
                .map_err(db::query_error)?;
            if written > 0 {
                queue_changed = true;
            }
        }
        if !reactivate_ids.is_empty() {
            let written = tx
                .execute(
                    "UPDATE threads SET status = 'active'
                     WHERE id = ANY($1::int[]) AND status <> 'excluded'",
                    &[&reactivate_ids],
                )
                .await
                .map_err(db::query_error)?;
            if written > 0 {
                // Reactivated series with no queue seat move after every seated active series,
                // including reactivated ones that kept a positive position.
                tx.execute(
                    "UPDATE threads t SET queue_position = base.max_pos + ranked.seq
                     FROM (
                         SELECT id, row_number() OVER (ORDER BY id)::int AS seq
                         FROM threads
                         WHERE id = ANY($1::int[]) AND status = 'active' AND queue_position < 1
                     ) ranked,
                     (
                         SELECT COALESCE(MAX(queue_position), 0) AS max_pos
                         FROM threads
                         WHERE user_id = $2 AND status = 'active' AND queue_position >= 1
                     ) base
                     WHERE t.id = ranked.id",
                    &[&reactivate_ids, &user.id()],
                )
                .await
                .map_err(db::query_error)?;
                queue_changed = true;
            }
        }
        if queue_changed {
            renormalize_queue_positions(&tx, user.id()).await?;
        }
    }

    // Preserve duplicate history entries in request order.
    if !issues.is_empty() {
        let event_types: Vec<&str> = vec![event_type; issues.len()];
        let user_ids: Vec<i32> = vec![user.id(); issues.len()];
        let thread_ids: Vec<i32> = issues.iter().map(|issue| issue.thread_id).collect();
        let issue_ids: Vec<i32> = issues.iter().map(|issue| issue.id).collect();
        let issue_numbers: Vec<String> = issues
            .iter()
            .map(|issue| issue.issue_number.clone())
            .collect();
        tx.execute(
            "INSERT INTO events (type, timestamp, user_id, thread_id, issue_id, issue_number)
             SELECT t.event_type, NOW(), t.user_id, t.thread_id, t.issue_id, t.issue_number
             FROM unnest($1::text[], $2::int[], $3::int[], $4::int[], $5::text[])
                  AS t(event_type, user_id, thread_id, issue_id, issue_number)",
            &[
                &event_types,
                &user_ids,
                &thread_ids,
                &issue_ids,
                &issue_numbers,
            ],
        )
        .await
        .map_err(db::query_error)?;
    }
    issue_service::refresh_blocked_threads(&tx, user.id()).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(StatusCode::NO_CONTENT)
}

async fn move_issue(
    state: &AppState,
    user: AuthenticatedUser,
    issue_id: i32,
    after_issue_id: Option<i64>,
) -> Result<StatusCode, ApiError> {
    let mut conn = db::checkout(state).await?;
    let tx = begin(&mut conn).await?;
    issue_mutation::lock_reader(&tx, user.id()).await?;
    let thread_id: i32 = tx
        .query_opt(
            "SELECT i.thread_id FROM issues i JOIN threads t ON t.id = i.thread_id
             WHERE i.id = $1 AND t.user_id = $2",
            &[&issue_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| issue_not_found(issue_id))?
        .get(0);
    lock_owned_thread(&tx, user.id(), thread_id).await?;
    let ids: Vec<i32> = tx
        .query(
            "SELECT id FROM issues WHERE thread_id = $1 ORDER BY position, id FOR UPDATE",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| row.get(0))
        .collect();
    if !ids.contains(&issue_id) {
        return Err(issue_not_found(issue_id));
    }

    if after_issue_id == Some(i64::from(issue_id)) {
        // Anchoring on itself keeps the order and only refreshes tracking state.
        apply_tracking_state(&tx, thread_id).await?;
        issue_service::refresh_blocked_threads(&tx, user.id()).await?;
        tx.commit().await.map_err(db::query_error)?;
        return Ok(StatusCode::NO_CONTENT);
    }

    let mut reordered: Vec<i32> = ids.iter().copied().filter(|id| *id != issue_id).collect();
    let insert_index = match after_issue_id {
        None => 0,
        Some(after) => reordered
            .iter()
            .position(|id| i64::from(*id) == after)
            .map(|index| index + 1)
            .ok_or_else(|| issue_not_found(after))?,
    };
    reordered.insert(insert_index, issue_id);

    tx.execute("SET CONSTRAINTS uq_issue_thread_position DEFERRED", &[])
        .await
        .map_err(db::query_error)?;
    let positions: Vec<(i32, i32)> = (1..)
        .zip(reordered.iter())
        .map(|(p, id)| (*id, p))
        .collect();
    issue_mutation::reseat_positions(&tx, thread_id, &positions).await?;
    apply_tracking_state(&tx, thread_id).await?;
    issue_service::refresh_blocked_threads(&tx, user.id()).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(StatusCode::NO_CONTENT)
}

/// Dispatch `POST /api/v1/issues/{issue_id}:{action}` operations.
///
/// The segment is split on its action suffix like Starlette's
/// `(?P<issue_id>[^/]+):action` pattern, so an id containing a colon is an
/// invalid integer rather than a different route. Any other segment matches
/// only the `GET` route in Python and is a 405.
pub async fn post_issue_action(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    segment: Result<Path<String>, PathRejection>,
    body: Bytes,
) -> Result<StatusCode, ApiError> {
    let Path(segment) = segment.map_err(|_| path_int_error(""))?;
    if let Some(raw_id) = segment.strip_suffix(":markRead") {
        let issue_id = resolve_issue_id(raw_id)?;
        return mark_issue_read(&state, user, issue_id).await;
    }
    if let Some(raw_id) = segment.strip_suffix(":markUnread") {
        let issue_id = resolve_issue_id(raw_id)?;
        return mark_issue_unread(&state, user, issue_id).await;
    }
    if let Some(raw_id) = segment.strip_suffix(":move") {
        // FastAPI reports path errors before body errors.
        let path_id = parse_int_text(raw_id).ok_or_else(|| path_int_error(raw_id))?;
        let after = parse_move_body(&body)?;
        let issue_id = i32::try_from(path_id).map_err(|_| issue_not_found(path_id))?;
        return move_issue(&state, user, issue_id, after).await;
    }
    Err(ApiError::MethodNotAllowed("Method Not Allowed".to_string()))
}

/// `POST /api/v1/issues:bulkMarkRead`
pub async fn bulk_mark_issues_read(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    body: Bytes,
) -> Result<StatusCode, ApiError> {
    let ids = parse_bulk_body(&body)?;
    bulk_mark(&state, user, &ids, true).await
}

/// `POST /api/v1/issues:bulkMarkUnread`
pub async fn bulk_mark_issues_unread(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    body: Bytes,
) -> Result<StatusCode, ApiError> {
    let ids = parse_bulk_body(&body)?;
    bulk_mark(&state, user, &ids, false).await
}

/// Request body for `POST /api/v1/issues/{issue_id}:move`.
#[derive(Debug, serde::Deserialize, utoipa::ToSchema)]
pub struct IssueMoveRequest {
    /// Move after this issue. `null` moves the issue to position 1.
    #[schema(required = true, minimum = 1, value_type = Option<i32>, nullable)]
    pub after_issue_id: Option<i32>,
}

/// Request body for the bulk read-state operations.
#[derive(Debug, serde::Deserialize, utoipa::ToSchema)]
pub struct IssueBulkRequest {
    #[schema(min_items = 1, max_items = 100)]
    pub issue_ids: Vec<i32>,
}

/// Documentation-only operation for `:markRead`.
#[utoipa::path(
    post,
    path = "/api/v1/issues/{issue_id}:markRead",
    tag = "issues",
    operation_id = "issue_read_state_mark_read",
    params(("issue_id" = i32, Path, description = "Owned Issue identifier")),
    responses(
        (status = 204, description = "Issue marked read and the thread counters refreshed"),
        (status = 400, description = "Issue is already marked as read"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Issue not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn mark_read_documentation() {}

/// Documentation-only operation for `:markUnread`.
#[utoipa::path(
    post,
    path = "/api/v1/issues/{issue_id}:markUnread",
    tag = "issues",
    operation_id = "issue_read_state_mark_unread",
    params(("issue_id" = i32, Path, description = "Owned Issue identifier")),
    responses(
        (status = 204, description = "Issue marked unread; a completed thread is reactivated"),
        (status = 400, description = "Issue is already marked as unread"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Issue not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn mark_unread_documentation() {}

/// Documentation-only operation for `:move`.
#[utoipa::path(
    post,
    path = "/api/v1/issues/{issue_id}:move",
    tag = "issues",
    operation_id = "issue_read_state_move",
    params(("issue_id" = i32, Path, description = "Owned Issue identifier")),
    request_body = IssueMoveRequest,
    responses(
        (status = 204, description = "Issue moved within its thread"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Issue or anchor issue not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn move_documentation() {}

/// Documentation-only operation for `:bulkMarkRead`.
#[utoipa::path(
    post,
    path = "/api/v1/issues:bulkMarkRead",
    tag = "issues",
    operation_id = "issue_read_state_bulk_mark_read",
    request_body = IssueBulkRequest,
    responses(
        (status = 204, description = "Every issue marked read atomically"),
        (status = 400, description = "An issue is already marked as read"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Issue not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn bulk_mark_read_documentation() {}

/// Documentation-only operation for `:bulkMarkUnread`.
#[utoipa::path(
    post,
    path = "/api/v1/issues:bulkMarkUnread",
    tag = "issues",
    operation_id = "issue_read_state_bulk_mark_unread",
    request_body = IssueBulkRequest,
    responses(
        (status = 204, description = "Every issue marked unread atomically"),
        (status = 400, description = "An issue is already marked as unread"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Issue not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn bulk_mark_unread_documentation() {}

/// Documentation-only operation for reader context.
#[utoipa::path(
    get,
    path = "/api/v1/issues/{issue_id}/reader-context",
    tag = "issues",
    operation_id = "issue_read_state_reader_context",
    params(("issue_id" = i32, Path, description = "Owned Issue identifier")),
    responses(
        (status = 200, description = "Bounded reader context", body = reader_context::ReaderContextResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Issue not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn reader_context_documentation() {}

/// OpenAPI document for the native same-path issue read-state surface.
#[derive(utoipa::OpenApi)]
#[openapi(
    info(
        title = "ComicPile native same-path issue read-state API",
        version = "1.0.0",
        description = "Generated contract for the native issue read-state, move and reader-context handlers that retain their original method and path."
    ),
    paths(
        mark_read_documentation,
        mark_unread_documentation,
        move_documentation,
        bulk_mark_read_documentation,
        bulk_mark_unread_documentation,
        reader_context_documentation
    ),
    components(schemas(
        IssueMoveRequest,
        IssueBulkRequest,
        reader_context::ReaderContextPreviousIssue,
        reader_context::ReaderContextRecentRating,
        reader_context::ReaderContextSeries,
        reader_context::ReaderContextCrossoverNextMember,
        reader_context::ReaderContextCrossover,
        reader_context::ReaderContextCrossoverMembership,
        reader_context::ReaderContextLocalIssue,
        reader_context::ReaderContextEdge,
        reader_context::ReaderContextLocalChain,
        reader_context::ReaderContextResponse
    )),
    modifiers(&IssueReadStateSecurityAddon)
)]
pub struct IssueReadStateApi;

struct IssueReadStateSecurityAddon;
impl utoipa::Modify for IssueReadStateSecurityAddon {
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

/// Emit the same-path native issue read-state contract.
pub fn issue_read_state_openapi() -> utoipa::openapi::OpenApi {
    use utoipa::OpenApi;
    IssueReadStateApi::openapi()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn assert_validation_failed(error: ApiError) {
        assert!(
            matches!(error, ApiError::Unprocessable(ref detail) if detail == "Validation failed"),
            "expected production 422 detail, got {error:?}"
        );
    }

    #[test]
    fn path_ids_follow_integer_path_semantics() {
        assert_eq!(parse_int_text("12"), Some(12));
        assert_eq!(parse_int_text(" +4 "), Some(4));
        assert_eq!(parse_int_text("-3"), Some(-3));
        assert_eq!(parse_int_text("1.5"), None);
        assert_eq!(parse_int_text("abc"), None);
        assert_eq!(parse_int_text(""), None);
        assert!(matches!(
            resolve_issue_id("99999999999"),
            Err(ApiError::NotFound(_))
        ));
        assert_validation_failed(resolve_issue_id("abc").unwrap_err());
    }

    #[test]
    fn move_body_uses_the_production_validation_detail() {
        assert_eq!(
            parse_move_body(br#"{"after_issue_id": null}"#).unwrap(),
            None
        );
        assert_eq!(
            parse_move_body(br#"{"after_issue_id": 7}"#).unwrap(),
            Some(7)
        );
        assert_eq!(
            parse_move_body(br#"{"after_issue_id": "7"}"#).unwrap(),
            Some(7)
        );
        assert_eq!(
            parse_move_body(br#"{"after_issue_id": 7.0}"#).unwrap(),
            Some(7)
        );
        for body in [
            b"{}".as_slice(),
            br#"{"after_issue_id": 0}"#,
            br#"{"after_issue_id": 1.5}"#,
            br#"{"after_issue_id": "x"}"#,
            br#"[1]"#,
            b"",
            b"{not json",
        ] {
            assert_validation_failed(parse_move_body(body).unwrap_err());
        }
    }

    #[test]
    fn bulk_body_uses_the_production_validation_detail() {
        assert_eq!(
            parse_bulk_body(br#"{"issue_ids": [3, "4", 3]}"#).unwrap(),
            vec![3, 4, 3]
        );
        let too_many = format!(
            "{{\"issue_ids\":[{}]}}",
            (1..=101)
                .map(|n| n.to_string())
                .collect::<Vec<_>>()
                .join(",")
        );
        for body in [
            b"{}".as_slice(),
            br#"{"issue_ids": []}"#,
            too_many.as_bytes(),
            br#"{"issue_ids": [1, "x", null]}"#,
            br#"{"issue_ids": 5}"#,
        ] {
            assert_validation_failed(parse_bulk_body(body).unwrap_err());
        }
    }

    #[test]
    fn contract_documents_every_operation_and_stays_current() {
        let document = serde_json::to_value(issue_read_state_openapi()).unwrap();
        for path in [
            "/api/v1/issues/{issue_id}:markRead",
            "/api/v1/issues/{issue_id}:markUnread",
            "/api/v1/issues/{issue_id}:move",
            "/api/v1/issues:bulkMarkRead",
            "/api/v1/issues:bulkMarkUnread",
            "/api/v1/issues/{issue_id}/reader-context",
        ] {
            assert!(document["paths"].get(path).is_some(), "{path}");
        }
        let expected = include_str!("../../contracts/issue-read-state-v1.openapi.json");
        let generated = issue_read_state_openapi().to_pretty_json().unwrap();
        assert_eq!(expected.trim_end(), generated.trim_end());
    }
}
