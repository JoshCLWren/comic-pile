/// Rate endpoint handler for POST /api/v1/rate/ and POST /api/rate/.
///
/// Mirrors the business logic of `app.services.rate_service.rate_thread` but
/// executes equivalent raw SQL against the shared PostgreSQL database via the
/// native roll-service connection pool. The request/response contract is
/// identical to the Python FastAPI endpoint: RateRequest → RateResponse with
/// roll_reconciliation.
use crate::{auth::AuthenticatedUser, config::get_rating_settings, ApiError, AppState};
use crate::db::{execute_in_transaction, query_error, SessionQuery, ThreadQuery};
use axum::{
    extract::State,
    http::StatusCode,
    response::IntoResponse,
    Json,
};
use axum::routing::post;
use chrono::{DateTime, Utc};
use deadpool_postgres::Object;
use serde::Deserialize;
use serde_json::Value;
use std::sync::Arc;
use tokio_postgres::IsolationLevel;

const DICE_LADDER: [i32; 9] = [4, 6, 8, 10, 12, 20, 30, 50, 100];

/// Rate request body, matching `app.schemas.rate.RateRequest`.
#[derive(Deserialize)]
pub struct RateRequest {
    pub rating: f64,
    pub finish_session: bool,
    pub issue_number: Option<String>,
    pub thread_id: Option<i32>,
    pub direct: bool,
}

/// Rate response body, matching `app.schemas.roll_v2.RateResponse`.
#[derive(serde::Serialize)]
pub struct RateResponse {
    pub id: i32,
    pub title: String,
    pub format: String,
    pub issues_remaining: i32,
    pub queue_position: i32,
    pub status: String,
    pub last_rating: f64,
    pub last_activity_at: String,
    pub notes: Option<String>,
    pub is_test: bool,
    pub is_blocked: bool,
    pub blocking_reasons: Vec<String>,
    pub created_at: String,
    pub total_issues: Option<i32>,
    pub reading_progress: Option<String>,
    pub next_unread_issue_id: Option<i32>,
    pub next_unread_issue_number: Option<String>,
    pub manual_creator_credits: Option<Value>,
    pub roll_reconciliation: Option<RollReconciliation>,
}

/// Roll reconciliation last-read record.
#[derive(serde::Serialize)]
pub struct RollReconciliation {
    pub last_read: RollLastRead,
}

/// Roll last-read record.
#[derive(serde::Serialize)]
pub struct RollLastRead {
    pub issue_id: Option<i32>,
    pub issue_number: Option<String>,
    pub thread_id: i32,
    pub thread_title: String,
    pub read_at: String,
}

impl IntoResponse for RateResponse {
    fn into_response(self) -> axum::response::Response {
        (
            StatusCode::OK,
            [("Content-Type", "application/json")],
            serde_json::to_string(&self).unwrap(),
        )
            .into_response()
    }
}

/// Execute the full rate pipeline using raw SQL equivalent to the Python
/// rate_thread function. This preserves the exact database operations,
/// transaction boundaries, and side effects of the Python handler.
async fn execute_rate_pipeline(
    state: &Arc<AppState>,
    user: AuthenticatedUser,
    rate_data: &RateRequest,
    db: &mut Object,
) -> Result<RateResponse, ApiError> {
    let (rating_min, rating_max, rating_threshold) = get_rating_settings();

    if rate_data.rating < rating_min || rate_data.rating > rating_max {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "Rating must be between 0.5 and 5.0",
        ));
    }

    let user_id = user.id();

    // Step 1: Determine the thread being rated.
    let thread_id = determine_thread_id(state, user_id, rate_data, db).await?;

    // Step 2: Validate thread has issues remaining.
    if !thread_has_issues_remaining(db, thread_id).await? {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "Thread has no issues remaining",
        ));
    }

    // Resolve session id and current die before the transaction so the rate
    // event can be created inside it.
    let session_id = session_id_opt(user_id, db).await?;
    let current_die = current_die_for_thread(user_id, db).await?;

    // Step 3: Determine the issue to rate and compute die_after.
    let (issue_id, issues_read, die_after) =
        determine_issue_and_die(db, thread_id, rate_data, current_die, rating_threshold).await?;

    // Pre-fetch issue number for event creation to avoid borrowing tx inside async block.
    let issue_number = issue_number_opt(db, thread_id, rate_data).await?;

    // Steps 4-6: Mark issue read, update thread, create rate event — all in one
    // transaction, matching Python's single commit boundary.
    let (new_issues_remaining, next_unread_issue_id) = execute_in_transaction(db, |tx| async move {
            // Mark the issue as read.
            tx.execute(
                "UPDATE issues SET status = 'read', read_at = to_timestamp(extract(epoch from current_timestamp)) WHERE id = $1",
                &[&issue_id],
            )
            .await
            .map_err(query_error)?;

            // Update thread state: decrement issues_remaining, update last_rating/last_activity_at.
            let current_issues: i32 = tx.query_opt(
                "SELECT issues_remaining FROM threads WHERE id = $1",
                &[&thread_id],
            )
            .await
            .map_err(query_error)?
            .map(|r| r.get::<_, i32>(0))
            .unwrap_or(0);
            let new_issues_remaining = current_issues.saturating_sub(1);
            tx.execute(
                "UPDATE threads SET issues_remaining = $1, last_rating = $2, last_activity_at = to_timestamp(extract(epoch from current_timestamp)) WHERE id = $3",
                &[&new_issues_remaining, &rate_data.rating, &thread_id],
            )
            .await
            .map_err(query_error)?;

            // Find the next unread issue for this thread.
            let next_unread: Option<i32> = tx.query_opt(
                "SELECT id FROM issues WHERE thread_id = $1 AND status = 'unread' ORDER BY position LIMIT 1",
                &[&thread_id],
            )
            .await
            .map_err(query_error)?
            .map(|r| r.get::<_, i32>(0));

            // Create the rate event and return its id.
            let event_id: i32 = tx.query_opt(
                "INSERT INTO events (type, session_id, thread_id, rating, issues_read, die, die_after, issue_id, issue_number, context)
                 VALUES ('rate', $1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                 RETURNING id",
                &[
                    &session_id,
                    &thread_id,
                    &rate_data.rating,
                    &issues_read,
                    &current_die,
                    &die_after,
                    &issue_id,
                    &issue_number,
                    &Value::Null,
                ],
            )
            .await
            .map_err(query_error)?
            .map(|r| r.get::<_, i32>(0))
            .ok_or_else(|| ApiError(StatusCode::INTERNAL_SERVER_ERROR, "Failed to create rate event"))?;

            let _ = event_id;
            Ok((new_issues_remaining, next_unread))
        })
    }).await?;

    let _ = next_unread_issue_id;

    // Step 7: Handle queue position changes (after commit, uses committed state).
    handle_queue_placement(db, thread_id, user_id, rate_data.rating, rating_threshold).await?;

    // Step 8: Create snapshot keyed by the real session id.
    create_rate_snapshot(state, db, user_id, thread_id).await?;

    // Step 9: Refresh blocked status.
    refresh_blocked_status_user(user_id, db).await?;

    // Step 10: If finish_session, end the user's session only.
    if rate_data.finish_session {
        end_session_db(user_id, db).await?;
    }

    // Step 11: Re-read the thread for the response.
    let response_thread = re_read_thread(state, user_id, thread_id, db).await?;

    // Step 12: Build the roll reconciliation from the committed event.
    let roll_reconciliation = build_roll_reconciliation_db(db, issue_id, thread_id).await?;

    // Step 13: Build and return the RateResponse.
    Ok(build_rate_response(
        &response_thread,
        roll_reconciliation,
    ))
}

/// Determine which thread is being rated.
async fn determine_thread_id(
    state: &Arc<AppState>,
    user_id: i32,
    rate_data: &RateRequest,
    db: &mut Object,
) -> Result<i32, ApiError> {
    if rate_data.direct {
        if rate_data.thread_id.is_none() {
            return Err(ApiError(
                StatusCode::BAD_REQUEST,
                "thread_id is required for a direct Thread rating".into(),
            ));
        }
        let tid = rate_data.thread_id.unwrap();
        let owned = find_owned_thread_raw(state, user_id, tid, db).await?;
        if owned.is_none() {
            return Err(ApiError(
                StatusCode::NOT_FOUND,
                "Thread not found",
            ));
        }
        Ok(tid)
    } else {
        // Session-driven: find the active session.
        let session = fetch_active_session_raw(user_id, db).await?;
        if session.is_none() {
            return Err(ApiError(
                StatusCode::BAD_REQUEST,
                "No active session. Please roll the dice first.".into(),
            ));
        }
        let sess = session.unwrap();

        if sess.pending_thread_id.is_some() {
            let tid = sess.pending_thread_id.unwrap();
            let owned = find_owned_thread_raw(state, user_id, tid, db).await?;
            if owned.is_none() {
                return Err(ApiError(
                    StatusCode::NOT_FOUND,
                    "Thread not found",
                ));
            }
            Ok(tid)
        } else {
            // No pending thread - find thread from roll history.
            let thread = find_any_owned_thread_with_issues_raw(user_id, db).await?;
            if thread.is_none() {
                return Err(ApiError(
                    StatusCode::BAD_REQUEST,
                    "No active thread. Please roll the dice first.",
                ));
            }
            let (tid, _) = thread.unwrap();
            Ok(tid)
        }
    }
}

/// Check if a thread has issues remaining.
async fn thread_has_issues_remaining(db: &mut Object, thread_id: i32) -> Result<bool, ApiError> {
    let row = db.query_opt(
        "SELECT issues_remaining FROM threads WHERE id = $1",
        &[&thread_id],
    )
    .await
    .map_err(query_error)?;

    Ok(row.map(|r| r.get::<_, i32>(0) > 0).unwrap_or(false))
}

/// Find an owned thread by ID using raw query.
async fn find_owned_thread_raw(
    _state: &Arc<AppState>,
    user_id: i32,
    thread_id: i32,
    db: &mut Object,
) -> Result<Option<ThreadQuery>, ApiError> {
    let row = db.query_opt(
        "SELECT id, title, format, issues_remaining, queue_position, status, last_rating, last_activity_at, notes, is_test, created_at, total_issues, next_unread_issue_id, reading_progress, is_blocked, manual_creator_credits FROM threads WHERE id = $1 AND user_id = $2",
        &[&thread_id, &user_id],
    )
    .await
    .map_err(query_error)?;

    Ok(row.map(|r| ThreadQuery {
        id: r.get(0),
        title: r.get(1),
        format: r.get(2),
        issues_remaining: r.get(3),
        queue_position: r.get(4),
        status: r.get(5),
        last_rating: r.get(6),
        last_activity_at: format_ts(r.get::<_, DateTime<Utc>>(7)),
        notes: r.get(8),
        is_test: r.get(9),
        created_at: format_ts(r.get::<_, DateTime<Utc>>(10)),
        total_issues: r.get(11),
        next_unread_issue_id: r.get(12),
        reading_progress: r.get::<_, Option<String>>(13).or_else(|| Some("in_progress".to_string())),
        is_blocked: r.get(14),
        manual_creator_credits: r.get(15),
    }))
}

/// Fetch the active session for a user.
async fn fetch_active_session_raw(
    user_id: i32,
    db: &mut Object,
) -> Result<Option<SessionQuery>, ApiError> {
    let row = db.query_opt(
        "SELECT id, user_id, start_die, manual_die, pending_thread_id, pending_thread_updated_at, ended_at, started_at, snoozed_thread_ids, skipped_thread_ids FROM sessions WHERE user_id = $1 AND ended_at IS NULL",
        &[&user_id],
    )
    .await
    .map_err(query_error)?;

    Ok(row.map(|r| SessionQuery {
        id: r.get(0),
        user_id: r.get(1),
        start_die: r.get(2),
        manual_die: r.get(3),
        pending_thread_id: r.get(4),
        pending_thread_updated_at: format_ts_opt(r.get::<_, Option<DateTime<Utc>>>(5)),
        ended_at: format_ts_opt(r.get::<_, Option<DateTime<Utc>>>(6)),
        started_at: format_ts(r.get::<_, DateTime<Utc>>(7)),
        snoozed_thread_ids: r.get::<_, Vec<i32>>(8),
        skipped_thread_ids: r.get::<_, Vec<i32>>(9),
    }))
}

/// Find any owned thread with issues remaining for a user.
async fn find_any_owned_thread_with_issues_raw(
    user_id: i32,
    db: &mut Object,
) -> Result<Option<(i32, ThreadQuery)>, ApiError> {
    let rows = db.query(
        "SELECT id, title, format, issues_remaining, queue_position, status, last_rating, last_activity_at, notes, is_test, created_at, total_issues, next_unread_issue_id, reading_progress, is_blocked, manual_creator_credits FROM threads WHERE user_id = $1 AND issues_remaining > 0 LIMIT 1",
        &[&user_id],
    )
    .await
    .map_err(query_error)?;

    if rows.is_empty() {
        return Ok(None);
    }

    let r = &rows[0];
    let thread = ThreadQuery {
        id: r.get(0),
        title: r.get(1),
        format: r.get(2),
        issues_remaining: r.get(3),
        queue_position: r.get(4),
        status: r.get(5),
        last_rating: r.get(6),
        last_activity_at: format_ts(r.get::<_, DateTime<Utc>>(7)),
        notes: r.get(8),
        is_test: r.get(9),
        created_at: format_ts(r.get::<_, DateTime<Utc>>(10)),
        total_issues: r.get(11),
        next_unread_issue_id: r.get(12),
        reading_progress: r.get::<_, Option<String>>(13).or_else(|| Some("in_progress".to_string())),
        is_blocked: r.get(14),
        manual_creator_credits: r.get(15),
    };
    Ok(Some((r.get::<_, i32>(0), thread)))
}

/// Resolve the active session id for the user, or None when there is none.
async fn session_id_opt(user_id: i32, db: &mut Object) -> Result<Option<i32>, ApiError> {
    let row = db.query_opt(
        "SELECT id FROM sessions WHERE user_id = $1 AND ended_at IS NULL LIMIT 1",
        &[&user_id],
    )
    .await
    .map_err(query_error)?;
    Ok(row.map(|r| r.get::<_, i32>(0)))
}

/// Resolve the current die for the user's active session (or start die if none).
async fn current_die_for_thread(user_id: i32, db: &mut Object) -> Result<i32, ApiError> {
    let row = db.query_opt(
        "SELECT COALESCE(manual_die, start_die) FROM sessions WHERE user_id = $1 AND ended_at IS NULL LIMIT 1",
        &[&user_id],
    )
    .await
    .map_err(query_error)?;
    Ok(row.map(|r| r.get::<_, i32>(0)).unwrap_or(6))
}

/// Resolve the issue number for the rated issue (direct rates name it by number).
async fn issue_number_opt(
    db: &mut Object,
    thread_id: i32,
    rate_data: &RateRequest,
) -> Result<Option<String>, ApiError> {
    if let Some(ref num) = rate_data.issue_number {
        let row = db.query_opt(
            "SELECT issue_number FROM issues WHERE thread_id = $1 AND issue_number = $2",
            &[&thread_id, num],
        )
        .await
        .map_err(query_error)?;
        return Ok(row.map(|r| r.get::<_, String>(0)));
    }
    Ok(None)
}

/// Same as `issue_number_opt` but runs inside an active transaction.
async fn issue_number_tx(
    tx: &mut tokio_postgres::Transaction<'_>,
    thread_id: i32,
    rate_data: &RateRequest,
) -> Result<Option<String>, ApiError> {
    if let Some(ref num) = rate_data.issue_number {
        let row = tx.query_opt(
            "SELECT issue_number FROM issues WHERE thread_id = $1 AND issue_number = $2",
            &[&thread_id, num],
        )
        .await
        .map_err(query_error)?;
        return Ok(row.map(|r| r.get::<_, String>(0)));
    }
    Ok(None)
}

/// Format a DateTime<Utc> as an RFC-3339 string.
fn format_ts(ts: DateTime<Utc>) -> Option<String> {
    Some(ts.to_rfc3339())
}

/// Format an optional DateTime<Utc> as an Option<String>.
fn format_ts_opt(ts: Option<DateTime<Utc>>) -> Option<String> {
    ts.map(|t| t.to_rfc3339())
}

/// Determine which issue to rate and compute the die_after value.
async fn determine_issue_and_die(
    db: &mut Object,
    thread_id: i32,
    rate_data: &RateRequest,
    current_die: i32,
    rating_threshold: f64,
) -> Result<(i32, i32, Option<i32>), ApiError> {
    // For direct ratings with issue number specified, find that issue.
    if let Some(issue_num) = &rate_data.issue_number {
        let issue = db.query_opt(
            "SELECT id FROM issues WHERE thread_id = $1 AND issue_number = $2 AND status = 'unread'",
            &[&thread_id, issue_num],
        )
        .await
        .map_err(query_error)?;

        if let Some(r) = issue {
            let issue_id = r.get(0);
            let die_after = compute_die_after(rate_data.rating, rating_threshold, current_die);
            return Ok((issue_id, 1, die_after));
        }
    }

    // Find first unread issue in the thread.
    let issue = db.query_opt(
        "SELECT id FROM issues WHERE thread_id = $1 AND status = 'unread' ORDER BY position LIMIT 1",
        &[&thread_id],
    )
    .await
    .map_err(query_error)?;

    if let Some(r) = issue {
        let issue_id = r.get(0);
        let die_after = compute_die_after(rate_data.rating, rating_threshold, current_die);
        return Ok((issue_id, 1, die_after));
    }

    Err(ApiError(
        StatusCode::BAD_REQUEST,
        "Thread has no unread issues",
    ))
}

/// Compute die_after based on rating vs threshold using the dice ladder.
fn compute_die_after(rating: f64, rating_threshold: f64, current_die: i32) -> Option<i32> {
    let idx = DICE_LADDER.iter().position(|&d| d == current_die)?;
    if current_die_is_good_rating_threshold(rating, rating_threshold) {
        // Step down: higher rating -> smaller die.
        if idx > 0 {
            Some(DICE_LADDER[idx - 1])
        } else {
            None
        }
    } else {
        // Step up: lower rating -> larger die.
        if idx < DICE_LADDER.len() - 1 {
            Some(DICE_LADDER[idx + 1])
        } else {
            None
        }
    }
}

/// Whether a rating at the threshold steps the die down. The actual rating
/// comparison happens at the call site; this helper selects the ladder
/// direction for the threshold boundary.
fn current_die_is_good_rating_threshold(rating: f64, rating_threshold: f64) -> bool {
    // High rating (>= threshold) steps down to smaller die
    rating >= rating_threshold
}

/// Advance the die based on the rating against the threshold.
fn advance_die_based_on_rating(rating: f64, rating_threshold: f64, current_die: i32) -> Option<i32> {
    compute_die_after(rating, rating_threshold, current_die)
}

/// Handle queue position changes based on the rating.
async fn handle_queue_placement(
    db: &mut Object,
    thread_id: i32,
    user_id: i32,
    rating: f64,
    rating_threshold: f64,
) -> Result<(), ApiError> {
    if rating >= rating_threshold {
        // High rating - move to front (position 1).
        db.execute(
            "WITH ranked AS (
                SELECT id, queue_position AS old_position,
                       row_number() OVER (ORDER BY queue_position, id) AS seq
                FROM threads
                WHERE user_id = $1 AND status = 'active' AND queue_position >= 1
            ),
            target AS (
                SELECT seq FROM ranked WHERE id = $2
            )
            UPDATE threads AS t
            SET queue_position = CASE
                WHEN t.id = $2 THEN 1
                WHEN ranked.seq > target.seq THEN ranked.seq - 1
                ELSE ranked.seq
                ELSE
                    CASE WHEN ranked.seq >= 1 AND ranked.seq < target.seq
                         THEN ranked.seq + 1 ELSE ranked.seq END
            END
            FROM ranked, target
            WHERE t.id = ranked.id",
            &[&user_id, &thread_id],
        )
        .await
        .map_err(query_error)?;
    } else {
        // Low rating - move to safe position just beyond the die range.
        let current_die = current_die_for_thread(user_id, db).await?;
        db.execute(
            "WITH ranked AS (
                SELECT id, queue_position AS old_position,
                       row_number() OVER (ORDER BY queue_position, id) AS seq
                FROM threads
                WHERE user_id = $1 AND status = 'active' AND queue_position >= 1
            ),
            target AS (
                SELECT seq FROM ranked WHERE id = $2
            )
            UPDATE threads AS t
            SET queue_position = CASE
                WHEN t.id = $2 THEN $3 + 1
                WHEN ranked.seq > target.seq THEN ranked.seq - 1
                ELSE ranked.seq
            END
            FROM ranked, target
            WHERE t.id = ranked.id",
            &[&user_id, &thread_id, &(current_die as i64)],
        )
        .await
        .map_err(query_error)?;
    }

    Ok(())
}

/// Create a rate snapshot (v2 delta mode) keyed by the real session id.
async fn create_rate_snapshot(
    _state: &Arc<AppState>,
    db: &mut Object,
    user_id: i32,
    thread_id: i32,
) -> Result<(), ApiError> {
    let session_id = session_id_opt(user_id, db).await?
        .ok_or_else(|| ApiError(StatusCode::BAD_REQUEST, "No active session for snapshot"))?;

    db.execute(
        "INSERT INTO snapshots (session_id, event_id, thread_states, snapshot_kind, schema_version, description)
         VALUES ($1, NULL, $2::jsonb, 'delta', 2, 'After rating')",
        &[&session_id, &serde_json::json!({thread_id.to_string(): {"rated": true}})],
    )
    .await
    .map_err(query_error)?;

    Ok(())
}

/// Refresh the user's blocked status from canonical dependency edges.
async fn refresh_blocked_status_user(user_id: i32, db: &mut Object) -> Result<(), ApiError> {
    // Set blocked=true for threads whose next unread issue has an unread
    // prerequisite through a canonical dependency edge.
    db.execute(
        "WITH blocked AS (
            SELECT DISTINCT target_thread.id AS thread_id
            FROM threads AS target_thread
            JOIN issues AS next_unread ON next_unread.id = target_thread.next_unread_issue_id
            JOIN dependencies ON dependencies.target_issue_id = next_unread.id
            JOIN issues AS source_issue ON dependencies.source_issue_id = source_issue.id
            JOIN threads AS source_thread ON source_issue.thread_id = source_thread.id
            WHERE target_thread.user_id = $1
              AND source_thread.user_id = $1
              AND source_issue.status <> 'read'
              AND next_unread.status <> 'read'
              AND target_thread.next_unread_issue_id IS NOT NULL
              AND (dependencies.note IS NULL OR dependencies.note NOT LIKE 'cbl-order:%')
        )
        UPDATE threads AS t
        SET is_blocked = TRUE
        FROM blocked
        WHERE t.id = blocked.thread_id
          AND t.user_id = $1",
        &[&user_id],
    )
    .await
    .map_err(query_error)?;

    // Clear blocked=false for threads no longer blocked.
    db.execute(
        "UPDATE threads AS t
        SET is_blocked = FALSE
        WHERE t.user_id = $1
          AND t.is_blocked = TRUE
          AND t.next_unread_issue_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1
            FROM issues AS next_unread
            JOIN dependencies ON dependencies.target_issue_id = next_unread.id
            JOIN issues AS source_issue ON dependencies.source_issue_id = source_issue.id
            JOIN threads AS source_thread ON source_issue.thread_id = source_thread.id
            WHERE next_unread.id = t.next_unread_issue_id
              AND source_thread.user_id = $1
              AND source_issue.status <> 'read'
              AND next_unread.status <> 'read'
              AND (dependencies.note IS NULL OR dependencies.note NOT LIKE 'cbl-order:%')
          )",
        &[&user_id],
    )
    .await
    .map_err(query_error)?;

    Ok(())
}

/// End the user's active reading session, scoped to that user only.
async fn end_session_db(user_id: i32, db: &mut Object) -> Result<(), ApiError> {
    db.execute(
        "UPDATE sessions SET ended_at = to_timestamp(extract(epoch from current_timestamp)) WHERE user_id = $1 AND ended_at IS NULL",
        &[&user_id],
    )
    .await
    .map_err(query_error)?;

    Ok(())
}

/// Re-read the thread state from the database.
async fn re_read_thread(
    state: &Arc<AppState>,
    user_id: i32,
    thread_id: i32,
    db: &mut Object,
) -> Result<ThreadQuery, ApiError> {
    find_owned_thread_raw(state, user_id, thread_id, db).await?
        .ok_or_else(|| ApiError(StatusCode::NOT_FOUND, "Thread not found"))
}

/// Build the roll reconciliation from the committed rate event.
async fn build_roll_reconciliation_db(
    db: &mut Object,
    issue_id: i32,
    thread_id: i32,
) -> Result<Option<RollReconciliation>, ApiError> {
    let row = db.query_opt(
        "SELECT e.issue_id, e.issue_number, e.thread_id, t.title, e.timestamp FROM events e JOIN threads t ON t.id = e.thread_id WHERE e.issue_id = $1 AND e.thread_id = $2 AND e.type = 'rate' ORDER BY e.timestamp DESC, e.id DESC LIMIT 1",
        &[&issue_id, &thread_id],
    )
    .await
    .map_err(query_error)?;

    Ok(row.map(|r| RollReconciliation {
        last_read: RollLastRead {
            issue_id: r.get(0),
            issue_number: r.get::<_, Option<String>>(1),
            thread_id: r.get(2),
            thread_title: r.get(3),
            read_at: format_ts(r.get::<_, DateTime<Utc>>(4)).unwrap_or_default(),
        },
    }))
}

/// Build the RateResponse from the thread state and reconciliation.
fn build_rate_response(
    thread: &ThreadQuery,
    roll_reconciliation: Option<RollReconciliation>,
) -> RateResponse {
    RateResponse {
        id: thread.id,
        title: thread.title.clone(),
        format: thread.format.clone(),
        issues_remaining: thread.issues_remaining,
        queue_position: thread.queue_position,
        status: thread.status.clone(),
        last_rating: thread.last_rating.unwrap_or(0.0),
        last_activity_at: thread.last_activity_at.clone().unwrap_or_default(),
        notes: thread.notes.clone(),
        is_test: thread.is_test,
        is_blocked: thread.is_blocked,
        blocking_reasons: vec![],
        created_at: thread.created_at.clone().unwrap_or_default(),
        total_issues: thread.total_issues,
        reading_progress: thread.reading_progress.clone(),
        next_unread_issue_id: thread.next_unread_issue_id,
        next_unread_issue_number: None,
        manual_creator_credits: thread.manual_creator_credits.clone(),
        roll_reconciliation,
    }
}

/// POST /api/v1/rate/ and POST /api/rate/ handler.
pub async fn post_rate(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(rate_data): Json<RateRequest>,
) -> Result<impl IntoResponse, ApiError> {
    let _user_id = user.id();

    // Get a database connection from the pool.
    let mut db = state.pool.get().await.map_err(|_| {
        ApiError(StatusCode::SERVICE_UNAVAILABLE, "Database unavailable")
    })?;

    // Execute the rate pipeline.
    let response = execute_rate_pipeline(&state, user, &rate_data, &mut db).await?;

    Ok(response.into_response())
}

/// Register the rate routes in the router.
pub fn rate_router(state: Arc<AppState>) -> axum::Router {
    axum::Router::new()
        .route("/api/v1/rate", post(post_rate))
        .route("/api/rate", post(post_rate))
        .with_state(state)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dice_ladder_step_down_and_up() {
        // Step down: high rating -> smaller die.
        assert_eq!(compute_die_after(4.0, 4.0, 20), Some(10));
        assert_eq!(compute_die_after(4.0, 4.0, 10), Some(6));
        assert_eq!(compute_die_after(4.0, 4.0, 6), Some(4));
        assert_eq!(compute_die_after(4.0, 4.0, 4), None);
        // Step up: low rating -> larger die.
        assert_eq!(compute_die_after(3.0, 4.0, 4), Some(6));
        assert_eq!(compute_die_after(3.0, 4.0, 6), Some(8));
        assert_eq!(compute_die_after(3.0, 4.0, 100), None);
        // Unknown die size returns None.
        assert_eq!(compute_die_after(4.0, 4.0, 7), None);
    }

    #[test]
    fn advance_die_based_on_rating_threshold() {
        assert_eq!(
            advance_die_based_on_rating(5.0, 4.0, 20),
            Some(10)
        );
        assert_eq!(
            advance_die_based_on_rating(3.0, 4.0, 6),
            Some(8)
        );
        // At minimum die, stays.
        assert_eq!(advance_die_based_on_rating(5.0, 4.0, 4), None);
        // At maximum die, stays.
        assert_eq!(advance_die_based_on_rating(3.0, 4.0, 100), None);
    }

    #[test]
    fn rating_validation_bounds() {
        let (min, max, threshold) = get_rating_settings();
        assert_eq!(min, 0.5);
        assert_eq!(max, 5.0);
        assert_eq!(threshold, 4.0);
    }
}
