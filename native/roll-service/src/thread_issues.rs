//! Same-path Rust cutover for the browser-called thread issue-management
//! operations (#4832, part D).
//!
//! Preserves the frozen Python wire contract (the oracle is
//! `app/api/issue.py`, `app/api/thread.py`, `app/services/issue.py`,
//! `app/services/thread_service.py`, `app/services/issue_insertion.py`,
//! `app/services/comicvine_intelligence.py` and `app/utils/issue_parser.py`) at
//! the identical HTTP methods and paths:
//!
//! * `POST /api/v1/threads/{thread_id}/issues`
//! * `GET  /api/v1/threads/{thread_id}/issues/creators`
//! * `POST /api/v1/threads/{thread_id}/issues:reorder`
//!
//! The v1 `{thread_id}:getBlockingInfo` action remains on the same
//! `POST /api/v1/threads/{thread_id}` dispatcher in
//! [`crate::thread_ordering::post_thread_action`], which splits the segment on
//! the first colon.
//!
//! Parity notes:
//!
//! * Every write is owner-scoped (a foreign thread is indistinguishable from a
//!   missing one, 404) and runs in one transaction that rolls back on any error.
//! * Request validation follows the house Rust convention
//!   (`{"detail": "Validation failed"}` 422) that matches the Python
//!   production exception handler.
//! * Known gap: the Python create path best-effort auto-adopts ComicVine issue
//!   identities for new issues when the thread has a confirmed ComicVine series
//!   mapping and `COMICVINE_API_KEY` is configured. That provider round trip is
//!   not ported; new issues are created unmapped and picked up by the existing
//!   ComicVine reconciliation flows.

#![forbid(unsafe_code)]

use crate::{
    auth::AuthenticatedUser,
    db, option_inputs, queue, thread_ordering, ApiError, AppState,
};
use axum::{
    body::Bytes,
    extract::{rejection::PathRejection, Path, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::sync::Arc;
use tokio_postgres::Transaction;

const MAX_ISSUES: usize = 10_000;
const MAX_LITERAL_LENGTH: usize = 100;
const MAX_BULK_CREDITS_PER_ISSUE: usize = 25;
const EXCLUDED_STATUS: &str = "excluded";

// ---------------------------------------------------------------------------
// Wire types
// ---------------------------------------------------------------------------

/// One issue row (Python `IssueResponse`).
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct IssueResponse {
    pub id: i32,
    pub thread_id: i32,
    pub issue_number: String,
    pub position: i32,
    pub status: String,
    pub read_at: Option<String>,
    pub created_at: String,
}

/// Newly created issues (Python `IssueListResponse`). Named distinctly from the v2 `IssueListResponse` so merged contracts never collide.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ThreadIssueCreateListResponse {
    pub issues: Vec<IssueResponse>,
    pub total_count: i32,
    pub page_size: i32,
    pub next_page_token: Option<String>,
}

/// One credited creator (Python `ComicVineCreator`).
#[derive(Debug, Clone, PartialEq, Serialize, utoipa::ToSchema)]
pub struct CreatorCredit {
    pub creator_id: Option<i64>,
    pub name: String,
    pub roles: Vec<String>,
}

/// Stored creator credits for one issue (Python `IssueCreatorsEntry`).
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct IssueCreatorsEntry {
    pub issue_id: i32,
    pub creators: Vec<CreatorCredit>,
}

/// Bulk creator credits for one thread (Python `ThreadIssueCreatorsResponse`).
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ThreadIssueCreatorsResponse {
    pub thread_id: i32,
    pub issues: Vec<IssueCreatorsEntry>,
}

/// Bounded, paginated thread-scoped issue-credit projection for #5706.
///
/// Keeps the frozen per-issue `issue_id`/`creators` wire shape of the legacy
/// bulk creator read and adds standard page fields. The `issues` array omits
/// unmapped issues and issues without stored credits, exactly like the legacy
/// response, while `total_count` counts matching confirmed-mapping issue rows.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ThreadCreatorCreditsResponse {
    pub thread_id: i32,
    pub issues: Vec<IssueCreatorsEntry>,
    pub total_count: i64,
    pub page_size: i64,
    pub next_page_token: Option<String>,
}

/// Python `ThreadResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ThreadResponse {
    pub id: i32,
    pub title: String,
    pub format: String,
    pub issues_remaining: i32,
    pub queue_position: i32,
    pub status: String,
    pub last_rating: Option<f64>,
    pub last_activity_at: Option<String>,
    pub notes: Option<String>,
    pub is_test: bool,
    pub is_blocked: bool,
    pub blocking_reasons: Vec<String>,
    pub created_at: String,
    pub total_issues: Option<i32>,
    pub reading_progress: Option<String>,
    pub next_unread_issue_id: Option<i32>,
    pub next_unread_issue_number: Option<String>,
    #[schema(value_type = Vec<Object>)]
    pub manual_creator_credits: Value,
}

/// Request body of `POST /api/v1/threads/{thread_id}/issues`.
#[derive(Debug, serde::Deserialize, utoipa::ToSchema)]
pub struct IssueCreateRange {
    /// Range such as `1-25` or `1, 3, 5-7`.
    pub issue_range: String,
    /// Insert after this issue id; omit for natural placement, null to append.
    pub insert_after_issue_id: Option<i32>,
}

/// Request body of `POST /api/v1/threads/{thread_id}/issues:reorder`.
#[derive(Debug, serde::Deserialize, utoipa::ToSchema)]
pub struct IssueReorderRequest {
    pub issue_ids: Vec<i32>,
}

// ---------------------------------------------------------------------------
// Errors and request parsing
// ---------------------------------------------------------------------------

fn validation_failed() -> ApiError {
    ApiError::Unprocessable("Validation failed".into())
}

fn thread_not_found(thread_id: i32) -> ApiError {
    ApiError::NotFound(format!("Thread {thread_id} not found"))
}

/// Coerce one JSON value the way pydantic's lax `int` does.
fn coerce_json_int(value: &Value) -> Option<i64> {
    match value {
        Value::Number(number) => number.as_i64().or_else(|| {
            number
                .as_f64()
                .filter(|float| float.fract() == 0.0 && float.abs() < 9.0e15)
                .map(|float| float as i64)
        }),
        Value::String(text) => {
            let trimmed = text.trim();
            let digits = trimmed.strip_prefix(['+', '-']).unwrap_or(trimmed);
            if digits.is_empty() || !digits.bytes().all(|byte| byte.is_ascii_digit()) {
                return None;
            }
            trimmed.parse().ok()
        }
        Value::Bool(flag) => Some(i64::from(*flag)),
        _ => None,
    }
}

/// A pydantic `int` field that must also fit the integer column.
fn int_field(value: &Value) -> Option<i32> {
    coerce_json_int(value).and_then(|number| i32::try_from(number).ok())
}

fn json_object(body: &[u8]) -> Result<Map<String, Value>, ApiError> {
    match serde_json::from_slice::<Value>(body) {
        Ok(Value::Object(map)) => Ok(map),
        _ => Err(validation_failed()),
    }
}

/// A pydantic `str` field: only JSON strings are accepted.
fn str_field(map: &Map<String, Value>, key: &str) -> Result<String, ApiError> {
    match map.get(key) {
        Some(Value::String(text)) => Ok(text.clone()),
        _ => Err(validation_failed()),
    }
}

fn parse_create_body(body: &[u8]) -> Result<(String, Option<i32>, bool), ApiError> {
    let map = json_object(body)?;
    let issue_range = str_field(&map, "issue_range")?;
    if issue_range.is_empty() {
        return Err(validation_failed());
    }
    let (anchor, explicit_null) = match map.get("insert_after_issue_id") {
        None => (None, false),
        Some(Value::Null) => (None, true),
        Some(value) => {
            let id = int_field(value).ok_or_else(validation_failed)?;
            if id < 1 {
                return Err(validation_failed());
            }
            (Some(id), false)
        }
    };
    Ok((issue_range, anchor, explicit_null))
}

fn parse_reorder_body(body: &[u8]) -> Result<Vec<i32>, ApiError> {
    let map = json_object(body)?;
    let items = match map.get("issue_ids") {
        Some(Value::Array(items)) if !items.is_empty() => items,
        _ => return Err(validation_failed()),
    };
    items
        .iter()
        .map(|item| int_field(item).ok_or_else(validation_failed))
        .collect()
}

fn path_thread_id(raw: Result<Path<String>, PathRejection>) -> Result<i32, ApiError> {
    let Path(raw) = raw.map_err(|_| validation_failed())?;
    thread_ordering::parse_int_text(&raw).ok_or_else(validation_failed)
}

// ---------------------------------------------------------------------------
// Issue range parsing and natural ordering (pure)
// ---------------------------------------------------------------------------

/// Port of `app.utils.issue_parser.parse_issue_ranges`. Errors carry the exact
/// Python `ValueError` message, which the route returns as a 400 detail.
pub(crate) fn parse_issue_ranges(input: &str) -> Result<Vec<String>, String> {
    if input.trim().is_empty() {
        return Err("Issue range cannot be empty".to_string());
    }
    let mut result: Vec<String> = Vec::new();
    for part in input.split(',') {
        let part = part.trim();
        if part.is_empty() {
            continue;
        }
        if part.chars().count() > MAX_LITERAL_LENGTH {
            return Err(format!(
                "Issue identifier too long (max {MAX_LITERAL_LENGTH} chars)"
            ));
        }
        if let Some((left, right)) = part.split_once('-') {
            let (left, right) = (left.trim(), right.trim());
            let digits = |text: &str| !text.is_empty() && text.bytes().all(|b| b.is_ascii_digit());
            if !digits(left) || !digits(right) {
                result.push(part.to_string());
                continue;
            }
            // Python ints are arbitrary precision and each endpoint may be up
            // to MAX_LITERAL_LENGTH digits, so the span is measured on the
            // decimal strings themselves. `end - start + 1` must never wrap:
            // an overflowing span is always far above MAX_ISSUES and is
            // rejected before any expansion (release builds included).
            let start = normalize_decimal(left);
            let end = normalize_decimal(right);
            if cmp_decimal(&start, &end) == Ordering::Greater {
                return Err(format!("Range start ({start}) cannot exceed end ({end})"));
            }
            let size_text = add_one_decimal(&sub_decimal(&end, &start));
            let size: Option<usize> = size_text.parse().ok();
            let Some(size) = size.filter(|size| *size <= MAX_ISSUES) else {
                return Err(format!(
                    "Range too large: {size_text} issues (max {MAX_ISSUES})"
                ));
            };
            if result.len() + size > MAX_ISSUES {
                return Err(format!("Total issues would exceed maximum of {MAX_ISSUES}"));
            }
            let mut current = start;
            for _ in 0..size {
                result.push(current.clone());
                current = add_one_decimal(&current);
            }
        } else {
            result.push(part.to_string());
        }
    }
    let mut seen = HashSet::new();
    let unique: Vec<String> = result
        .into_iter()
        .filter(|issue| seen.insert(issue.clone()))
        .collect();
    if unique.len() > MAX_ISSUES {
        return Err(format!(
            "Cannot create more than {MAX_ISSUES} issues at once"
        ));
    }
    Ok(unique)
}

/// Python `str(int(text))` for a non-negative all-digit string: leading zeros
/// are dropped (`"007"` -> `"7"`, `"000"` -> `"0"`).
fn normalize_decimal(digits: &str) -> String {
    let trimmed = digits.trim_start_matches('0');
    if trimmed.is_empty() {
        "0".to_string()
    } else {
        trimmed.to_string()
    }
}

/// Compare two normalized non-negative decimal strings.
fn cmp_decimal(left: &str, right: &str) -> Ordering {
    left.len().cmp(&right.len()).then_with(|| left.cmp(right))
}

/// `bigger - smaller` for normalized decimals with `bigger >= smaller`,
/// returned normalized (schoolbook subtraction; no integer type involved).
fn sub_decimal(bigger: &str, smaller: &str) -> String {
    let big: Vec<u8> = bigger.bytes().map(|b| b - b'0').collect();
    let small: Vec<u8> = smaller.bytes().map(|b| b - b'0').collect();
    let offset = big.len() - small.len();
    let mut diff = vec![0u8; big.len()];
    let mut borrow = 0i16;
    for i in (0..big.len()).rev() {
        let subtrahend = if i >= offset { small[i - offset] } else { 0 };
        let mut digit = i16::from(big[i]) - i16::from(subtrahend) - borrow;
        if digit < 0 {
            digit += 10;
            borrow = 1;
        } else {
            borrow = 0;
        }
        diff[i] = digit as u8;
    }
    normalize_decimal(&diff.iter().map(|d| (b'0' + d) as char).collect::<String>())
}

/// `value + 1` on a normalized non-negative decimal string.
fn add_one_decimal(value: &str) -> String {
    let mut digits: Vec<u8> = value.bytes().collect();
    for i in (0..digits.len()).rev() {
        if digits[i] == b'9' {
            digits[i] = b'0';
        } else {
            digits[i] += 1;
            return digits.iter().map(|b| *b as char).collect();
        }
    }
    let mut out = String::with_capacity(digits.len() + 1);
    out.push('1');
    out.extend(digits.iter().map(|b| *b as char));
    out
}

/// Sort key of an ordinary issue number (`^[1-9][0-9]*$`): digit-string length
/// then lexical order equals integer order for canonical digit strings of any
/// length, so no integer overflow is possible.
fn ordinary_key(issue_number: &str) -> Option<(usize, &str)> {
    let mut bytes = issue_number.bytes();
    let first = bytes.next()?;
    if !(b'1'..=b'9').contains(&first) || !bytes.all(|b| b.is_ascii_digit()) {
        return None;
    }
    Some((issue_number.len(), issue_number))
}

/// Port of `app.utils.issue_natural_order.natural_issue_order`.
pub(crate) fn natural_issue_order(existing: &[String], incoming: &[String]) -> Option<Vec<String>> {
    let mut new_keyed: Vec<((usize, &str), &String)> = Vec::new();
    for number in incoming {
        new_keyed.push((ordinary_key(number)?, number));
    }
    let existing_keyed: Vec<((usize, &str), &String)> = existing
        .iter()
        .filter_map(|number| ordinary_key(number).map(|key| (key, number)))
        .collect();

    if existing_keyed.len() == existing.len() {
        // A saved all-numeric order that is not ascending is reader-authored
        // (or an intentionally nonmonotonic series), not a sorting defect to
        // silently repair while inserting another issue. #4654: fall back to
        // the caller's append/accepted-anchor path so every existing Issue ID
        // keeps its relative order. Numeric resort stays a previewed choice.
        if existing_keyed.windows(2).any(|pair| pair[0].0 >= pair[1].0) {
            return None;
        }
        let mut merged: Vec<((usize, &str), &String)> = existing_keyed;
        merged.extend(new_keyed);
        merged.sort_by(|left, right| left.0.cmp(&right.0));
        return Some(merged.into_iter().map(|(_, label)| label.clone()).collect());
    }

    if existing_keyed.is_empty() {
        return None;
    }
    let keys: Vec<(usize, &str)> = existing_keyed.iter().map(|(key, _)| *key).collect();
    if keys.windows(2).any(|pair| pair[0] > pair[1]) {
        return None;
    }

    let mut result: Vec<String> = existing.to_vec();
    new_keyed.sort_by(|left, right| left.0.cmp(&right.0));
    for (key, label) in new_keyed {
        let slot = result.iter().position(|current| {
            ordinary_key(current).is_some_and(|existing_key| existing_key > key)
        });
        match slot {
            Some(index) => result.insert(index, label.clone()),
            None => {
                // Beyond the maximum, anchor after the last ordinary number rather
                // than after any irregular labels saved at the tail.
                let last_numbered = result
                    .iter()
                    .rposition(|current| ordinary_key(current).is_some());
                if let Some(index) = last_numbered {
                    result.insert(index + 1, label.clone());
                } else {
                    result.push(label.clone());
                }
            }
        }
    }
    Some(result)
}

/// Python `int(str)` for the strings the migration route can receive.
fn python_int(text: &str) -> Option<i128> {
    let trimmed = text.trim();
    let (negative, digits) = match trimmed.as_bytes().first()? {
        b'-' => (true, &trimmed[1..]),
        b'+' => (false, &trimmed[1..]),
        _ => (false, trimmed),
    };
    if digits.is_empty()
        || digits.starts_with('_')
        || digits.ends_with('_')
        || digits.contains("__")
    {
        return None;
    }
    if !digits.bytes().all(|b| b.is_ascii_digit() || b == b'_') {
        return None;
    }
    let cleaned: String = digits.chars().filter(|c| *c != '_').collect();
    let value: i128 = cleaned.parse().ok()?;
    Some(if negative { -value } else { value })
}

// ---------------------------------------------------------------------------
// Shared SQL helpers
// ---------------------------------------------------------------------------

fn iso(column: &str) -> String {
    format!(
        "CASE WHEN {column} IS NULL THEN NULL \
         WHEN date_trunc('second', {column}) = {column} \
         THEN to_char({column} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
         ELSE to_char({column} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') END"
    )
}

async fn begin(
    connection: &mut deadpool_postgres::Object,
) -> Result<deadpool_postgres::Transaction<'_>, ApiError> {
    connection
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)
}

/// The locked thread columns the issue-management operations read.
struct LockedThread {
    status: String,
    queue_position: i32,
    total_issues: Option<i32>,
    issues_remaining: i32,
    next_unread_issue_id: Option<i32>,
}

async fn lock_owned_thread(
    tx: &Transaction<'_>,
    user_id: i32,
    thread_id: i32,
) -> Result<LockedThread, ApiError> {
    // Writer lock order: the per-reader queue advisory lock is always taken
    // BEFORE any thread/issue row lock, so sibling writers serialize on it
    // instead of deadlocking on row locks (rust-write-lock-order rule).
    // Re-acquiring it in the same transaction (e.g. after
    // `renormalize_queue_positions`) is a no-op.
    queue::lock_queue(tx, user_id).await?;
    let row = tx
        .query_opt(
            "SELECT status, queue_position, total_issues, issues_remaining, next_unread_issue_id \
             FROM threads WHERE id = $1 AND user_id = $2 FOR UPDATE",
            &[&thread_id, &user_id],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| thread_not_found(thread_id))?;
    Ok(LockedThread {
        status: row.get(0),
        queue_position: row.get(1),
        total_issues: row.get(2),
        issues_remaining: row.get(3),
        next_unread_issue_id: row.get(4),
    })
}

/// `thread_repository.renormalize_queue_positions`: take the per-reader queue
/// lock, then rewrite active queue positions as a dense `1..N` sequence.
async fn renormalize_queue_positions(tx: &Transaction<'_>, user_id: i32) -> Result<(), ApiError> {
    queue::lock_queue(tx, user_id).await?;
    tx.execute(
        "UPDATE threads t SET queue_position = ranked.seq \
         FROM (SELECT id, row_number() OVER (ORDER BY queue_position, id)::int AS seq \
               FROM threads WHERE user_id = $1 AND status = 'active' AND queue_position >= 1) ranked \
         WHERE t.id = ranked.id AND t.queue_position <> ranked.seq",
        &[&user_id],
    )
    .await
    .map_err(db::query_error)?;
    Ok(())
}

/// Counters derived from a thread's issue rows
/// (`issue_tracking.derive_thread_issue_tracking_state`).
struct TrackingState {
    total: i32,
    next_unread: Option<i32>,
}

/// Re-derive and persist the thread counters, then return them
/// (`issue_tracking.apply_thread_issue_tracking_state`).
async fn apply_tracking_state(
    tx: &Transaction<'_>,
    thread_id: i32,
) -> Result<TrackingState, ApiError> {
    let rows = tx
        .query(
            "SELECT id, status FROM issues WHERE thread_id = $1 ORDER BY position",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    let total = rows.len() as i32;
    let mut remaining = 0;
    let mut next_unread = None;
    for row in &rows {
        let status: String = row.get(1);
        if status == "unread" {
            remaining += 1;
            if next_unread.is_none() {
                next_unread = Some(row.get::<_, i32>(0));
            }
        }
    }
    let progress = if remaining == 0 {
        "completed"
    } else if remaining == total {
        "not_started"
    } else {
        "in_progress"
    };
    tx.execute(
        "UPDATE threads SET total_issues = $2, issues_remaining = $3, next_unread_issue_id = $4, \
         reading_progress = $5, is_blocked = CASE WHEN $3 = 0 THEN false ELSE is_blocked END \
         WHERE id = $1",
        &[&thread_id, &total, &remaining, &next_unread, &progress],
    )
    .await
    .map_err(db::query_error)?;
    Ok(TrackingState { total, next_unread })
}

fn normalize_format_value(value: &str) -> String {
    match value.trim().to_lowercase().as_str() {
        "comic" | "comics" => "Comic".to_string(),
        "digital" => "Digital".to_string(),
        _ => value.trim().to_string(),
    }
}

/// The reader's dense Queue ordinal for one thread
/// (`queue_display.display_position`), zero when outside the Queue.
async fn display_position(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
    thread_id: i32,
    option_e: bool,
) -> Result<i32, ApiError> {
    let rows = tx
        .query(
            "SELECT id, is_blocked, queue_position FROM threads \
             WHERE user_id = $1 AND status = 'active' AND queue_position >= 1 \
             ORDER BY queue_position, id",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let candidates: Option<HashSet<i32>> = if option_e {
        let validated = option_inputs::load_validated_contained_in_transaction(tx, user).await?;
        let frontiers = validated
            .eligible_frontiers()
            .map_err(|_| ApiError::Internal("Invalid reading constraints".to_string()))?;
        Some(
            frontiers
                .iter()
                .map(|frontier| frontier.thread_id)
                .collect(),
        )
    } else {
        None
    };
    let mut ordered: Vec<(bool, i32, i32)> = rows
        .iter()
        .map(|row| {
            let id: i32 = row.get(0);
            let blocked = match &candidates {
                Some(set) => !set.contains(&id),
                None => row.get(1),
            };
            (blocked, row.get::<_, i32>(2), id)
        })
        .collect();
    ordered.sort();
    Ok(ordered
        .iter()
        .position(|(_, _, id)| *id == thread_id)
        .map_or(0, |index| index as i32 + 1))
}

/// `thread_to_response`, read inside the writing transaction.
async fn thread_response(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
    thread_id: i32,
    option_e: bool,
) -> Result<ThreadResponse, ApiError> {
    let sql = format!(
        "SELECT t.title, t.format, t.issues_remaining, t.status, t.last_rating, {last_activity}, \
                t.notes, t.is_test, t.is_blocked, {created}, t.total_issues, t.reading_progress, \
                t.next_unread_issue_id, t.manual_creator_credits::text, \
                (SELECT i.issue_number FROM issues i WHERE i.id = t.next_unread_issue_id), \
                (SELECT count(*) FROM issues i WHERE i.thread_id = t.id AND i.status = 'unread' AND i.merged_into_issue_id IS NULL) \
         FROM threads t WHERE t.id = $1 AND t.user_id = $2",
        last_activity = iso("t.last_activity_at"),
        created = iso("t.created_at"),
    );
    let row = tx
        .query_opt(&sql, &[&thread_id, &user.id()])
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| thread_not_found(thread_id))?;
    let total_issues: Option<i32> = row.get(10);
    let unread: i64 = row.get(15);
    let issues_remaining = if total_issues.is_some() {
        unread as i32
    } else {
        row.get(2)
    };
    let queue_position = display_position(tx, user, thread_id, option_e).await?;
    let credits: Option<String> = row.get(13);
    Ok(ThreadResponse {
        id: thread_id,
        title: row.get(0),
        format: normalize_format_value(&row.get::<_, String>(1)),
        issues_remaining,
        queue_position,
        status: row.get(3),
        last_rating: row.get(4),
        last_activity_at: row.get(5),
        notes: row.get(6),
        is_test: row.get(7),
        is_blocked: row.get(8),
        blocking_reasons: Vec::new(),
        created_at: row.get(9),
        total_issues,
        reading_progress: row.get(11),
        next_unread_issue_id: row.get(12),
        next_unread_issue_number: row.get(14),
        manual_creator_credits: credits
            .and_then(|text| serde_json::from_str(&text).ok())
            .unwrap_or_else(|| Value::Array(Vec::new())),
    })
}

fn insert_error(error: tokio_postgres::Error) -> ApiError {
    if error.code() == Some(&tokio_postgres::error::SqlState::UNIQUE_VIOLATION) {
        let constraint = error
            .as_db_error()
            .and_then(|db_error| db_error.constraint())
            .unwrap_or_default();
        if constraint == "uq_issue_thread_number" {
            return ApiError::Conflict("Issue number already exists in this thread".to_string());
        }
        return ApiError::Internal("Internal error: Database constraint violation".to_string());
    }
    db::tx_error(error)
}

// ---------------------------------------------------------------------------
// POST /api/v1/threads/{thread_id}/issues
// ---------------------------------------------------------------------------

struct CreatedIssue {
    id: i32,
    number: String,
    position: i32,
    created_at: String,
}

/// Insert every new issue in one set-based statement (no SQL inside loops),
/// returning the created rows.
async fn insert_issues(
    tx: &Transaction<'_>,
    thread_id: i32,
    numbers: &[String],
    positions: &[i32],
) -> Result<Vec<CreatedIssue>, ApiError> {
    let sql = format!(
        "INSERT INTO issues (thread_id, issue_number, position, status, created_at) \
         SELECT $1, new.number, new.position, 'unread', NOW() \
         FROM unnest($2::text[], $3::int[]) AS new(number, position) \
         RETURNING id, issue_number, position, {}",
        iso("created_at")
    );
    let rows = tx
        .query(&sql, &[&thread_id, &numbers, &positions])
        .await
        .map_err(insert_error)?;
    Ok(rows
        .iter()
        .map(|row| CreatedIssue {
            id: row.get(0),
            number: row.get(1),
            position: row.get(2),
            created_at: row.get(3),
        })
        .collect())
}

/// `POST /api/v1/threads/{thread_id}/issues`
pub async fn create_thread_issues(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    thread_id: Result<Path<String>, PathRejection>,
    body: Bytes,
) -> Result<(StatusCode, Json<ThreadIssueCreateListResponse>), ApiError> {
    let thread_id = path_thread_id(thread_id)?;
    let (issue_range, insert_after, explicit_null) = parse_create_body(&body)?;
    let append_to_end = explicit_null;

    let mut connection = db::checkout(&state).await?;
    let tx = begin(&mut connection).await?;
    // Queue lock before the thread row lock, as Python does, so queue writers
    // keep a single lock order.
    renormalize_queue_positions(&tx, user.id()).await?;
    let thread = lock_owned_thread(&tx, user.id(), thread_id).await?;

    let numbers = parse_issue_ranges(&issue_range).map_err(ApiError::BadRequest)?;
    if numbers.is_empty() {
        return Err(ApiError::BadRequest(
            "Issue range cannot be empty".to_string(),
        ));
    }

    let rows = tx
        .query(
            "SELECT id, issue_number, position FROM issues WHERE thread_id = $1 \
             ORDER BY position FOR UPDATE",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    let existing: Vec<(i32, String, i32)> = rows
        .iter()
        .map(|row| (row.get(0), row.get(1), row.get(2)))
        .collect();
    let existing_numbers: HashSet<&str> = existing
        .iter()
        .map(|(_, number, _)| number.as_str())
        .collect();
    let max_position = existing.iter().map(|(_, _, p)| *p).max().unwrap_or(0);
    let mut insert_position = max_position;
    if let Some(anchor) = insert_after {
        let found = existing.iter().find(|(id, _, _)| *id == anchor);
        match found {
            Some((_, _, position)) => insert_position = *position,
            None => {
                return Err(ApiError::NotFound(format!("Issue {anchor} not found")));
            }
        }
    }

    let new_numbers: Vec<String> = numbers
        .iter()
        .filter(|number| !existing_numbers.contains(number.as_str()))
        .cloned()
        .collect();
    if new_numbers.is_empty() {
        return Err(ApiError::BadRequest(
            "All issues in range already exist".to_string(),
        ));
    }

    let mut created: Vec<CreatedIssue> = Vec::new();
    let mut placed = false;
    if insert_after.is_none() && !append_to_end {
        let existing_labels: Vec<String> = existing
            .iter()
            .map(|(_, number, _)| number.clone())
            .collect();
        if let Some(order) = natural_issue_order(&existing_labels, &new_numbers) {
            let target: BTreeMap<&str, i32> = order
                .iter()
                .enumerate()
                .map(|(index, number)| (number.as_str(), index as i32 + 1))
                .collect();
            let (ids, positions): (Vec<i32>, Vec<i32>) = existing
                .iter()
                .filter_map(|(id, number, position)| {
                    target
                        .get(number.as_str())
                        .filter(|wanted| **wanted != *position)
                        .map(|wanted| (*id, *wanted))
                })
                .unzip();
            if !ids.is_empty() {
                tx.execute("SET CONSTRAINTS uq_issue_thread_position DEFERRED", &[])
                    .await
                    .map_err(db::query_error)?;
                tx.execute(
                    "UPDATE issues SET position = moved.position \
                     FROM unnest($2::int[], $3::int[]) AS moved(id, position) \
                     WHERE issues.id = moved.id AND issues.thread_id = $1",
                    &[&thread_id, &ids, &positions],
                )
                .await
                .map_err(db::query_error)?;
            }
            let positions: Vec<i32> = new_numbers
                .iter()
                .map(|number| target[number.as_str()])
                .collect();
            created = insert_issues(&tx, thread_id, &new_numbers, &positions).await?;
            created.sort_by_key(|issue| issue.position);
            placed = true;
        }
    }
    if !placed {
        let count = new_numbers.len() as i32;
        if insert_after.is_some() {
            tx.execute("SET CONSTRAINTS uq_issue_thread_position DEFERRED", &[])
                .await
                .map_err(db::query_error)?;
            tx.execute(
                "UPDATE issues SET position = position + $3 \
                 WHERE thread_id = $1 AND position > $2",
                &[&thread_id, &insert_position, &count],
            )
            .await
            .map_err(db::query_error)?;
        }
        let positions: Vec<i32> = (insert_position + 1..=insert_position + count).collect();
        created = insert_issues(&tx, thread_id, &new_numbers, &positions).await?;
        created.sort_by_key(|issue| issue.position);
    }

    let was_unmigrated = thread.total_issues.is_none();
    let had_next_unread = thread.next_unread_issue_id.is_some();
    let tracking = apply_tracking_state(&tx, thread_id).await?;
    let mut status = thread.status.clone();
    let mut queue_position = thread.queue_position;

    if tracking.next_unread.is_none() {
        if status != EXCLUDED_STATUS {
            tx.execute(
                "UPDATE threads SET status = 'completed', queue_position_is_manual = false, \
                 queue_position = 0 WHERE id = $1",
                &[&thread_id],
            )
            .await
            .map_err(db::query_error)?;
            renormalize_queue_positions(&tx, user.id()).await?;
        }
    } else if was_unmigrated || !had_next_unread {
        if !was_unmigrated && status == "completed" {
            tx.execute(
                "UPDATE threads SET queue_position = queue_position + 1 \
                 WHERE user_id = $1 AND status = 'active'",
                &[&user.id()],
            )
            .await
            .map_err(db::query_error)?;
            queue_position = 1;
        }
        if status != EXCLUDED_STATUS {
            status = "active".to_string();
        }
        if queue_position < 1 {
            let max: Option<i32> = tx
                .query_one(
                    "SELECT max(queue_position) FROM threads \
                     WHERE user_id = $1 AND status = 'active' AND queue_position >= 1",
                    &[&user.id()],
                )
                .await
                .map_err(db::query_error)?
                .get(0);
            queue_position = max.unwrap_or(0) + 1;
        }
        tx.execute(
            "UPDATE threads SET status = $2, queue_position = $3 WHERE id = $1",
            &[&thread_id, &status, &queue_position],
        )
        .await
        .map_err(db::query_error)?;
        renormalize_queue_positions(&tx, user.id()).await?;
    }

    tx.execute(
        "INSERT INTO events (type, timestamp, thread_id) VALUES ('issues_created', NOW(), $1)",
        &[&thread_id],
    )
    .await
    .map_err(db::query_error)?;
    crate::issue_service::refresh_blocked_threads(&tx, user.id()).await?;
    tx.commit().await.map_err(db::tx_error)?;

    let issues: Vec<IssueResponse> = created
        .into_iter()
        .map(|issue| IssueResponse {
            id: issue.id,
            thread_id,
            issue_number: issue.number,
            position: issue.position,
            status: "unread".to_string(),
            read_at: None,
            created_at: issue.created_at,
        })
        .collect();
    Ok((
        StatusCode::CREATED,
        Json(ThreadIssueCreateListResponse {
            page_size: issues.len() as i32,
            total_count: tracking.total,
            issues,
            next_page_token: None,
        }),
    ))
}

// ---------------------------------------------------------------------------
// POST /api/v1/threads/{thread_id}/issues:reorder
// ---------------------------------------------------------------------------

/// `POST /api/v1/threads/{thread_id}/issues:reorder`
pub async fn reorder_thread_issues(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    thread_id: Result<Path<String>, PathRejection>,
    body: Bytes,
) -> Result<StatusCode, ApiError> {
    let thread_id = path_thread_id(thread_id)?;
    let requested = parse_reorder_body(&body)?;

    let mut connection = db::checkout(&state).await?;
    let tx = begin(&mut connection).await?;
    lock_owned_thread(&tx, user.id(), thread_id).await?;
    let rows = tx
        .query(
            "SELECT id FROM issues WHERE thread_id = $1 ORDER BY position, id FOR UPDATE",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    let existing: BTreeSet<i32> = rows.iter().map(|row| row.get(0)).collect();
    let unique: BTreeSet<i32> = requested.iter().copied().collect();
    if requested.len() != rows.len() || unique.len() != requested.len() || unique != existing {
        return Err(ApiError::BadRequest(
            "issue_ids must contain every issue in the thread exactly once".to_string(),
        ));
    }
    let positions: Vec<i32> = (1..=requested.len() as i32).collect();
    tx.execute("SET CONSTRAINTS uq_issue_thread_position DEFERRED", &[])
        .await
        .map_err(db::query_error)?;
    tx.execute(
        "UPDATE issues SET position = ordered.position \
         FROM unnest($2::int[], $3::int[]) AS ordered(id, position) \
         WHERE issues.id = ordered.id AND issues.thread_id = $1",
        &[&thread_id, &requested, &positions],
    )
    .await
    .map_err(db::query_error)?;
    apply_tracking_state(&tx, thread_id).await?;
    crate::issue_service::refresh_blocked_threads(&tx, user.id()).await?;
    tx.commit().await.map_err(db::tx_error)?;
    Ok(StatusCode::NO_CONTENT)
}

// ---------------------------------------------------------------------------
// GET /api/v1/threads/{thread_id}/issues/creators
// ---------------------------------------------------------------------------

/// Python `_string`: a non-blank string or integer rendered as text.
fn credit_string(value: &Value) -> Option<String> {
    let text = match value {
        Value::String(text) => text.clone(),
        Value::Number(number) if number.is_i64() || number.is_u64() => number.to_string(),
        Value::Bool(flag) => if *flag { "True" } else { "False" }.to_string(),
        _ => return None,
    };
    if text.trim().is_empty() {
        None
    } else {
        Some(text)
    }
}

/// Python `_integer`: an integer or an all-digit string.
fn credit_integer(value: &Value) -> Option<i64> {
    match value {
        Value::Number(number) => number.as_i64(),
        Value::Bool(flag) => Some(i64::from(*flag)),
        Value::String(text) if !text.is_empty() && text.chars().all(|c| c.is_ascii_digit()) => {
            text.parse().ok()
        }
        _ => None,
    }
}

/// Port of `comicvine_intelligence._creators` over the stored credit arrays.
pub(crate) fn merge_creators(
    person_credits: Option<&Value>,
    creator_credits: Option<&Value>,
) -> Vec<CreatorCredit> {
    let list = [person_credits, creator_credits]
        .into_iter()
        .flatten()
        .find_map(Value::as_array);
    let mut by_id: Vec<CreatorCredit> = Vec::new();
    let mut anonymous: Vec<CreatorCredit> = Vec::new();
    for credit in list.into_iter().flatten().filter(|item| item.is_object()) {
        let Some(name) = credit.get("name").and_then(credit_string) else {
            continue;
        };
        let creator_id = credit.get("id").and_then(credit_integer);
        let role_text = credit
            .get("role")
            .and_then(credit_string)
            .unwrap_or_default();
        let roles: Vec<String> = role_text
            .split(',')
            .map(str::trim)
            .filter(|role| !role.is_empty())
            .map(str::to_owned)
            .collect();
        match creator_id {
            None => anonymous.push(CreatorCredit {
                creator_id: None,
                name,
                roles,
            }),
            Some(id) => {
                if let Some(existing) = by_id.iter_mut().find(|entry| entry.creator_id == Some(id))
                {
                    for role in roles {
                        if !existing.roles.contains(&role) {
                            existing.roles.push(role);
                        }
                    }
                } else {
                    by_id.push(CreatorCredit {
                        creator_id: Some(id),
                        name,
                        roles,
                    });
                }
            }
        }
    }
    by_id.extend(anonymous);
    by_id
}

fn parse_credit_array(raw: Option<String>) -> Option<Value> {
    let value: Value = serde_json::from_str(&raw?).ok()?;
    if value.is_null() {
        None
    } else {
        Some(value)
    }
}

/// `GET /api/v1/threads/{thread_id}/issues/creators`
pub async fn list_thread_issue_creators(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    thread_id: Result<Path<String>, PathRejection>,
) -> Result<Json<ThreadIssueCreatorsResponse>, ApiError> {
    let thread_id = path_thread_id(thread_id)?;
    let connection = db::checkout(&state).await?;
    let owned = connection
        .query_opt(
            "SELECT 1 FROM threads WHERE id = $1 AND user_id = $2",
            &[&thread_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    if owned.is_none() {
        return Err(thread_not_found(thread_id));
    }
    let rows = connection
        .query(
            "SELECT DISTINCT ON (i.id) i.id, \
                    (ei.metadata_json::jsonb -> 'person_credits')::text, \
                    (ei.metadata_json::jsonb -> 'creator_credits')::text \
             FROM issues i \
             JOIN issue_external_identity_mappings iem ON iem.issue_id = i.id \
             JOIN external_identities ei ON ei.id = iem.external_identity_id \
             WHERE i.thread_id = $1 AND iem.status = 'confirmed' \
               AND ei.provider = 'comicvine' AND ei.entity_type = 'issue' \
             ORDER BY i.id, iem.confidence DESC NULLS LAST, ei.id",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    let mut issues = Vec::new();
    for row in rows {
        let person = parse_credit_array(row.get(1));
        let creator = parse_credit_array(row.get(2));
        let mut creators = merge_creators(person.as_ref(), creator.as_ref());
        creators.truncate(MAX_BULK_CREDITS_PER_ISSUE);
        if creators.is_empty() {
            continue;
        }
        issues.push(IssueCreatorsEntry {
            issue_id: row.get(0),
            creators,
        });
    }
    Ok(Json(ThreadIssueCreatorsResponse { thread_id, issues }))
}

// ---------------------------------------------------------------------------
// GET /api/v2/threads/{thread_id}/creatorCredits (#5706)
// ---------------------------------------------------------------------------

const DEFAULT_CREDIT_PAGE_SIZE: i64 = 100;
const MAX_CREDIT_PAGE_SIZE: i64 = 100;

/// One raw credit row from the set-based projection query.
#[derive(Debug, Deserialize)]
struct CreditRow {
    issue_id: i32,
    person_credits: Option<String>,
    creator_credits: Option<String>,
}

/// One bounded CTE over confirmed ComicVine issue identities: a total count and
/// the requested page of issue ids. No per-issue SQL or provider fan-out; the
/// owner check below is the only other statement.
const THREAD_CREATOR_CREDITS_SQL: &str = "
WITH matched AS (
    SELECT DISTINCT ON (i.id) i.id AS issue_id,
           (ei.metadata_json::jsonb -> 'person_credits')::text AS person_credits,
           (ei.metadata_json::jsonb -> 'creator_credits')::text AS creator_credits
    FROM issues i
    JOIN issue_external_identity_mappings iem ON iem.issue_id = i.id
    JOIN external_identities ei ON ei.id = iem.external_identity_id
    WHERE i.thread_id = $1 AND iem.status = 'confirmed'
      AND ei.provider = 'comicvine' AND ei.entity_type = 'issue'
    ORDER BY i.id, iem.confidence DESC NULLS LAST, ei.id
), totals AS (
    SELECT count(*)::bigint AS total_count FROM matched
), paged AS (
    SELECT m.issue_id, m.person_credits, m.creator_credits
    FROM matched m
    WHERE ($2::integer IS NULL OR m.issue_id > $2)
    ORDER BY m.issue_id
    LIMIT $3
)
SELECT totals.total_count,
       COALESCE((SELECT jsonb_agg(to_jsonb(p) ORDER BY p.issue_id)::text FROM paged p), '[]')
FROM totals
";

fn credit_validation_failed() -> ApiError {
    ApiError::Unprocessable("Validation failed".into())
}

fn decode_credit_cursor(token: &str) -> Result<i32, ApiError> {
    token
        .parse::<i32>()
        .map_err(|_| ApiError::BadRequest("Invalid page_token format".into()))
}

fn parse_credit_query(raw: Option<&str>) -> Result<(i64, Option<String>), ApiError> {
    let mut page_size = DEFAULT_CREDIT_PAGE_SIZE;
    let mut page_token: Option<String> = None;
    let mut seen_page_size = false;
    let mut seen_page_token = false;

    if let Some(raw) = raw {
        // RawQuery is not form-decoded; decode exactly as axum's Query would.
        for (key, value) in form_urlencoded::parse(raw.as_bytes()) {
            match key.as_ref() {
                "page_size" => {
                    if seen_page_size {
                        return Err(credit_validation_failed());
                    }
                    seen_page_size = true;
                    let parsed = value
                        .parse::<i64>()
                        .map_err(|_| credit_validation_failed())?;
                    if !(1..=MAX_CREDIT_PAGE_SIZE).contains(&parsed) {
                        return Err(credit_validation_failed());
                    }
                    page_size = parsed;
                }
                "page_token" => {
                    if seen_page_token {
                        return Err(credit_validation_failed());
                    }
                    seen_page_token = true;
                    page_token = Some(value.into_owned());
                }
                _ => {}
            }
        }
    }
    Ok((page_size, page_token))
}

/// `GET /api/v2/threads/{thread_id}/creatorCredits` — a bounded, paginated
/// issue-credit projection over the caller's own thread (#5706).
///
/// The response keeps the legacy `{thread_id, issues: [{issue_id, creators}]}`
/// shape, so expanding a thread's issue list still needs one bounded bulk
/// request instead of one provider-intelligence request per issue. Credits are
/// read only from stored ComicVine metadata: no refresh, no
/// reading-eligibility veto, and no unmapped-issue placeholder rows.
/// `total_count` counts confirmed-mapping issue rows before the empty-credit
/// filter, so a page token always advances even when a row has no credits.
pub async fn list_thread_creator_credits(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    thread_id: Result<Path<String>, PathRejection>,
    raw_query: axum::extract::RawQuery,
) -> Result<Json<ThreadCreatorCreditsResponse>, ApiError> {
    let Path(thread_id) = thread_id.map_err(|_| credit_validation_failed())?;
    let thread_id: i32 = thread_id.parse().map_err(|_| credit_validation_failed())?;
    let (page_size, page_token) = parse_credit_query(raw_query.0.as_deref())?;
    let cursor = page_token
        .as_deref()
        .filter(|token| !token.is_empty())
        .map(decode_credit_cursor)
        .transpose()?;

    let connection = db::checkout(&state).await?;
    let owned = connection
        .query_opt(
            "SELECT 1 FROM threads WHERE id = $1 AND user_id = $2",
            &[&thread_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    if owned.is_none() {
        return Err(thread_not_found(thread_id));
    }

    let row = connection
        .query_one(
            THREAD_CREATOR_CREDITS_SQL,
            &[&thread_id, &cursor, &(page_size + 1)],
        )
        .await
        .map_err(db::query_error)?;
    let total_count: i64 = row.get(0);
    let payload: String = row.get(1);
    let mut rows: Vec<CreditRow> = serde_json::from_str(&payload)
        .map_err(|_| ApiError::Internal("Internal Server Error".into()))?;
    let has_more = rows.len() > page_size as usize;
    rows.truncate(page_size as usize);
    let next_page_token = if has_more {
        rows.last().map(|row| row.issue_id.to_string())
    } else {
        None
    };

    let mut issues = Vec::new();
    for row in rows {
        let person = parse_credit_array(row.person_credits);
        let creator = parse_credit_array(row.creator_credits);
        let mut creators = merge_creators(person.as_ref(), creator.as_ref());
        creators.truncate(MAX_BULK_CREDITS_PER_ISSUE);
        if creators.is_empty() {
            continue;
        }
        issues.push(IssueCreatorsEntry {
            issue_id: row.issue_id,
            creators,
        });
    }
    Ok(Json(ThreadCreatorCreditsResponse {
        thread_id,
        issues,
        total_count,
        page_size,
        next_page_token,
    }))
}


// ---------------------------------------------------------------------------
// OpenAPI documentation
// ---------------------------------------------------------------------------

/// Documentation-only operation for issue creation.
#[utoipa::path(
    post,
    path = "/api/v1/threads/{thread_id}/issues",
    tag = "issues",
    operation_id = "thread_issues_create",
    params(("thread_id" = i32, Path, description = "Owned Thread identifier")),
    request_body = IssueCreateRange,
    responses(
        (status = 201, description = "Newly created issues", body = ThreadIssueCreateListResponse),
        (status = 400, description = "Invalid or fully duplicate range"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread or anchor issue not found"),
        (status = 409, description = "Issue number already exists"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn create_issues_documentation() {}

/// Documentation-only operation for the bulk creator read.
#[utoipa::path(
    get,
    path = "/api/v1/threads/{thread_id}/issues/creators",
    tag = "issues",
    operation_id = "thread_issues_creators",
    params(("thread_id" = i32, Path, description = "Owned Thread identifier")),
    responses(
        (status = 200, description = "Stored creator credits per mapped issue", body = ThreadIssueCreatorsResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn creators_documentation() {}

/// Documentation-only operation for the canonical v2 thread-scoped credit
/// projection (#5706). The v1 bulk creator URL stays on the legacy response;
/// this v2 operation adds bounded pagination around the same stored credits.
#[utoipa::path(
    get,
    path = "/api/v2/threads/{thread_id}/creatorCredits",
    tag = "issues",
    operation_id = "thread_creator_credits",
    params(
        ("thread_id" = i32, Path, description = "Owned Thread identifier"),
        ("page_size" = Option<i64>, Query, description = "1-100 credited issues (default 100)"),
        ("page_token" = Option<String>, Query, description = "issue_id continuation cursor")
    ),
    responses(
        (status = 200, description = "Paginated stored creator credits per mapped issue", body = ThreadCreatorCreditsResponse),
        (status = 400, description = "Invalid page token"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 422, description = "Validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn creator_credits_documentation() {}

/// Documentation-only operation for issue reordering.
#[utoipa::path(
    post,
    path = "/api/v1/threads/{thread_id}/issues:reorder",
    tag = "issues",
    operation_id = "thread_issues_reorder",
    params(("thread_id" = i32, Path, description = "Owned Thread identifier")),
    request_body = IssueReorderRequest,
    responses(
        (status = 204, description = "Order rewritten"),
        (status = 400, description = "issue_ids must name every issue exactly once"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn reorder_documentation() {}

/// OpenAPI document for the native same-path thread issue-management surface.
#[derive(utoipa::OpenApi)]
#[openapi(
    info(
        title = "ComicPile native same-path thread issue API",
        version = "1.0.0",
        description = "Generated contract for the native thread issue-management handlers that retain their original method and path."
    ),
    paths(
        create_issues_documentation,
        creators_documentation,
        reorder_documentation
    ),
    components(schemas(
        IssueResponse,
        ThreadIssueCreateListResponse,
        CreatorCredit,
        IssueCreatorsEntry,
        ThreadIssueCreatorsResponse,
        ThreadResponse,
        IssueCreateRange,
        IssueReorderRequest
    )),
    modifiers(&ThreadIssuesSecurityAddon)
)]
pub struct ThreadIssuesApi;

struct ThreadIssuesSecurityAddon;
impl utoipa::Modify for ThreadIssuesSecurityAddon {
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

/// Emit the same-path native thread issue-management contract.
pub fn thread_issues_openapi() -> utoipa::openapi::OpenApi {
    use utoipa::OpenApi;
    ThreadIssuesApi::openapi()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn strings(values: &[&str]) -> Vec<String> {
        values.iter().map(|v| (*v).to_string()).collect()
    }

    #[test]
    fn range_parser_matches_python() {
        assert_eq!(
            parse_issue_ranges("1-3").unwrap(),
            strings(&["1", "2", "3"])
        );
        assert_eq!(
            parse_issue_ranges("0, 1-2, Annual 1, 2").unwrap(),
            strings(&["0", "1", "2", "Annual 1"])
        );
        assert_eq!(
            parse_issue_ranges("1-Annual").unwrap(),
            strings(&["1-Annual"])
        );
        assert_eq!(
            parse_issue_ranges("5-3").unwrap_err(),
            "Range start (5) cannot exceed end (3)"
        );
        assert_eq!(
            parse_issue_ranges("1-10001").unwrap_err(),
            "Range too large: 10001 issues (max 10000)"
        );
        assert_eq!(
            parse_issue_ranges("  ").unwrap_err(),
            "Issue range cannot be empty"
        );
        assert!(parse_issue_ranges(",").unwrap().is_empty());
        assert_eq!(
            parse_issue_ranges(&"x".repeat(101)).unwrap_err(),
            "Issue identifier too long (max 100 chars)"
        );
        assert_eq!(
            parse_issue_ranges("1-9000, 9001-10001").unwrap_err(),
            "Total issues would exceed maximum of 10000"
        );
    }

    #[test]
    fn range_parser_rejects_huge_and_overflowing_ranges_like_python() {
        // u128::MAX endpoint: `end - start + 1` would wrap to 0 in release
        // builds; Python's arbitrary-precision int rejects the same input.
        assert_eq!(
            parse_issue_ranges("0-340282366920938463463374607431768211455").unwrap_err(),
            "Range too large: 340282366920938463463374607431768211456 issues (max 10000)"
        );
        // Endpoints beyond u128 stay exact on the decimal strings.
        assert_eq!(
            parse_issue_ranges(&format!("0-{}", "9".repeat(98))).unwrap_err(),
            format!(
                "Range too large: {} issues (max 10000)",
                add_one_decimal(&"9".repeat(98))
            )
        );
        assert_eq!(
            parse_issue_ranges(&format!("{}-{}", "9".repeat(50), "9".repeat(49))).unwrap_err(),
            format!(
                "Range start ({}) cannot exceed end ({})",
                "9".repeat(50),
                "9".repeat(49)
            )
        );
        // A huge but tiny-span range still expands exactly like Python.
        let big = "9".repeat(40);
        assert_eq!(
            parse_issue_ranges(&format!("{big}-{big}")).unwrap(),
            strings(&[&big])
        );
        let next = add_one_decimal(&big);
        assert_eq!(
            parse_issue_ranges(&format!("{big}-{next}")).unwrap(),
            strings(&[&big, &next])
        );
        // Leading zeros normalize the way Python `str(int(...))` does.
        assert_eq!(
            parse_issue_ranges("007-009").unwrap(),
            strings(&["7", "8", "9"])
        );
        assert_eq!(parse_issue_ranges("0-0").unwrap(), strings(&["0"]));
    }

    #[test]
    fn natural_order_matches_python() {
        let order = |existing: &[&str], new: &[&str]| {
            natural_issue_order(&strings(existing), &strings(new))
        };
        assert_eq!(
            order(&["33", "34", "35"], &["2"]),
            Some(strings(&["2", "33", "34", "35"]))
        );
        // Reader-authored non-monotonic numeric order is preserved: callers
        // must fall back to append instead of rewriting saved positions.
        assert_eq!(order(&["3", "1"], &["2"]), None);
        // Irregular incoming labels fall back to append.
        assert_eq!(order(&["1"], &["Annual 1"]), None);
        assert_eq!(order(&["1"], &["0"]), None);
        // Mixed threads keep the saved order and seat numbers by neighbours.
        assert_eq!(
            order(&["1", "Annual 1", "3"], &["2"]),
            Some(strings(&["1", "Annual 1", "2", "3"]))
        );
        assert_eq!(order(&["Annual 1"], &["2"]), None);
        assert_eq!(order(&["3", "Annual 1", "1"], &["2"]), None);
        // Magnitude comparison is numeric, not lexical.
        assert_eq!(order(&["9"], &["10"]), Some(strings(&["9", "10"])));
    }

    #[test]
    fn natural_order_seats_monotonic_runs_and_preserves_authored_order_3483_4654() {
        // #3483: adopting the Ultimate Universe CBL list into a thread that
        // already held #7-#24 appended the missing low issues after #24.
        // This routine is the single ordering authority for series:import,
        // CBL adoption materialization and reading-plan sync; the Queue and
        // thread-page dialogs are covered by the same #3029 ordering contract
        // through their shared create-issues handler.
        let high_run: Vec<String> = (7..=24).map(|n| n.to_string()).collect();
        let mut seated: Vec<String> = strings(&["1", "2"]);
        seated.extend(high_run.iter().cloned());

        // First adoption: the missing #1 and #2 must be seated in front of the
        // existing run, regardless of the CBL roster order.
        let ascending = natural_issue_order(&high_run, &strings(&["1", "2"]));
        let descending = natural_issue_order(&high_run, &strings(&["2", "1"]));
        assert_eq!(ascending, Some(seated.clone()));
        assert_eq!(descending, Some(seated));

        // #4654: a non-monotonic all-numeric series is reader intent, not a
        // defect to repair during a later adoption or plan sync. The helper
        // must refuse to reorder it so every existing Issue ID keeps its
        // relative order; only an explicit previewed numeric resort may move
        // existing issues.
        let mut appended = high_run;
        appended.extend(
            ["2", "3", "4", "5", "6", "1"]
                .iter()
                .map(|n| (*n).to_string()),
        );
        let before = appended.clone();
        assert_eq!(natural_issue_order(&appended, &strings(&["25"])), None);
        assert_eq!(appended, before, "the helper never mutates saved order");

        // The synthetic 129, 140-142, 130-139, 143 order is the same class of
        // reader-authored order and must never be numerically re-seated here.
        let julix = strings(&["129", "140", "141", "142", "130", "131", "143"]);
        assert_eq!(natural_issue_order(&julix, &strings(&["101"])), None);
    }

    #[test]
    fn python_int_parsing() {
        assert_eq!(python_int("5"), Some(5));
        assert_eq!(python_int(" 5 "), Some(5));
        assert_eq!(python_int("+5"), Some(5));
        assert_eq!(python_int("-5"), Some(-5));
        assert_eq!(python_int("1_000"), Some(1000));
        assert_eq!(python_int("1__0"), None);
        assert_eq!(python_int("_1"), None);
        assert_eq!(python_int("1.5"), None);
        assert_eq!(python_int("Annual 1"), None);
        assert_eq!(python_int(""), None);
    }

    #[test]
    fn natural_order_places_new_maximum_before_trailing_special() {
        let existing = strings(&["1", "2", "5", "7", "8", "Annual 1", "9", "10", "Special 0"]);
        let expected = strings(&[
            "1",
            "2",
            "5",
            "7",
            "8",
            "Annual 1",
            "9",
            "10",
            "11",
            "Special 0",
        ]);
        assert_eq!(
            natural_issue_order(&existing, &strings(&["11"])),
            Some(expected)
        );
    }

    #[test]
    fn creator_merge_matches_python() {
        let person: Value = serde_json::json!([
            {"id": 7, "name": "A", "role": "writer, penciler"},
            {"name": "NoId", "role": "cover"},
            {"id": "7", "name": "A2", "role": "writer,inker"},
            {"id": 9, "name": "  ", "role": "x"},
            "skipped",
            {"id": 3, "name": 42, "role": null}
        ]);
        let creators = merge_creators(Some(&person), None);
        assert_eq!(
            creators,
            vec![
                CreatorCredit {
                    creator_id: Some(7),
                    name: "A".into(),
                    roles: strings(&["writer", "penciler", "inker"]),
                },
                CreatorCredit {
                    creator_id: Some(3),
                    name: "42".into(),
                    roles: vec![],
                },
                CreatorCredit {
                    creator_id: None,
                    name: "NoId".into(),
                    roles: strings(&["cover"]),
                },
            ]
        );
        // A non-list `person_credits` falls through to `creator_credits`.
        let fallback: Value = serde_json::json!([{"id": 1, "name": "B", "role": ""}]);
        let text: Value = serde_json::json!("nope");
        assert_eq!(merge_creators(Some(&text), Some(&fallback)).len(), 1);
        assert!(merge_creators(None, None).is_empty());
    }

    #[test]
    fn body_validation_matches_pydantic() {
        assert!(parse_create_body(br#"{"issue_range":"1-3"}"#).is_ok());
        let (_, anchor, null) =
            parse_create_body(br#"{"issue_range":"1","insert_after_issue_id":null}"#).unwrap();
        assert_eq!((anchor, null), (None, true));
        let (_, anchor, null) =
            parse_create_body(br#"{"issue_range":"1","insert_after_issue_id":"4"}"#).unwrap();
        assert_eq!((anchor, null), (Some(4), false));
        for bad in [
            &br#"{"issue_range":""}"#[..],
            br#"{"issue_range":1}"#,
            br#"{"issue_range":"1","insert_after_issue_id":0}"#,
            br#"{}"#,
            b"[]",
            b"nope",
        ] {
            assert!(parse_create_body(bad).is_err());
        }
        assert!(parse_reorder_body(br#"{"issue_ids":[]}"#).is_err());
        assert_eq!(
            parse_reorder_body(br#"{"issue_ids":[2,"1"]}"#).unwrap(),
            vec![2, 1]
        );
    }

    #[test]
    fn contract_documents_every_operation_and_stays_current() {
        let document = serde_json::to_value(thread_issues_openapi()).unwrap();
        for path in [
            "/api/v1/threads/{thread_id}/issues",
            "/api/v1/threads/{thread_id}/issues/creators",
            "/api/v1/threads/{thread_id}/issues:reorder",
        ] {
            assert!(document["paths"].get(path).is_some(), "{path}");
        }
        let expected = include_str!("../../contracts/thread-issues-v1.openapi.json");
        let generated = thread_issues_openapi().to_pretty_json().unwrap();
        assert_eq!(expected.trim_end(), generated.trim_end());
    }

    #[test]
    fn credit_query_is_form_decoded_bounded_and_rejects_duplicates() {
        // RawQuery is not form-decoded: %35 is a 5 and %37 is a 7.
        assert_eq!(
            parse_credit_query(Some("page_size=2%35&page_token=%37")).unwrap(),
            (25, Some("7".into()))
        );
        assert_eq!(
            parse_credit_query(None).unwrap(),
            (DEFAULT_CREDIT_PAGE_SIZE, None)
        );
        for bad in [
            "page_size=0",
            "page_size=101",
            "page_size=x",
            "page_size=1&page_size=2",
            "page_token=1&page_token=2",
        ] {
            assert!(parse_credit_query(Some(bad)).is_err(), "{bad}");
        }
        assert_eq!(decode_credit_cursor("12").unwrap(), 12);
        assert!(decode_credit_cursor("1,2").is_err());
    }

    #[test]
    fn credit_projection_is_one_bounded_owner_scoped_statement() {
        assert_eq!(MAX_CREDIT_PAGE_SIZE, 100);
        for fragment in [
            "WITH matched AS",
            "count(*)::bigint",
            "i.thread_id = $1",
            "m.issue_id > $2",
            "LIMIT $3",
            "ORDER BY m.issue_id",
        ] {
            assert!(
                THREAD_CREATOR_CREDITS_SQL.contains(fragment),
                "missing {fragment}"
            );
        }
    }
}
