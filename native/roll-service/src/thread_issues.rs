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
//! * `POST /api/v1/threads/{thread_id}:migrateToIssues`
//! * `POST /api/v1/threads/{thread_id}:migrateToIssuesSimple`
//! * `POST /api/v1/threads/{thread_id}:setCurrentIssue`
//!
//! The three `{thread_id}:action` operations are routed through the single
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
    db, option_inputs, queue, reading_eligibility,
    reading_session::{self, SessionPolicy},
    roll_exclusions, thread_ordering, ApiError, AppState,
};
use axum::{
    body::Bytes,
    extract::{rejection::PathRejection, Path, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::Serialize;
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

/// Python `SetCurrentIssueResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SetCurrentIssueResponse {
    pub thread_id: i32,
    pub title: String,
    pub format: String,
    pub issues_remaining: i32,
    pub queue_position: i32,
    pub issue_id: Option<i32>,
    pub issue_number: Option<String>,
    pub next_issue_id: Option<i32>,
    pub next_issue_number: Option<String>,
    pub total_issues: Option<i32>,
    pub reading_progress: Option<String>,
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

/// Request body of `POST /api/v1/threads/{thread_id}:migrateToIssues`.
#[derive(Debug, serde::Deserialize, utoipa::ToSchema)]
pub struct MigrateToIssuesRequest {
    pub last_issue_read: i32,
    pub total_issues: i32,
}

/// Request body of `POST /api/v1/threads/{thread_id}:migrateToIssuesSimple`.
#[derive(Debug, serde::Deserialize, utoipa::ToSchema)]
pub struct MigrateToIssuesSimpleRequest {
    pub issue_number: String,
}

/// Request body of `POST /api/v1/threads/{thread_id}:setCurrentIssue`.
#[derive(Debug, serde::Deserialize, utoipa::ToSchema)]
pub struct SetCurrentIssueRequest {
    pub issue_number: String,
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

fn parse_migrate_body(body: &[u8]) -> Result<(i32, i32), ApiError> {
    let map = json_object(body)?;
    let last = map
        .get("last_issue_read")
        .and_then(int_field)
        .ok_or_else(validation_failed)?;
    let total = map
        .get("total_issues")
        .and_then(int_field)
        .ok_or_else(validation_failed)?;
    if last < 0 || total < 1 {
        return Err(validation_failed());
    }
    // Bound the request-supplied count before it reaches generate_series:
    // an uncapped total would ask PostgreSQL to insert billions of rows.
    if total > MAX_ISSUES as i32 {
        return Err(validation_failed());
    }
    Ok((last, total))
}

fn parse_migrate_simple_body(body: &[u8]) -> Result<String, ApiError> {
    let map = json_object(body)?;
    let number = str_field(&map, "issue_number")?;
    let length = number.chars().count();
    if !(1..=50).contains(&length) {
        return Err(validation_failed());
    }
    Ok(number)
}

fn parse_set_current_body(body: &[u8]) -> Result<String, ApiError> {
    let map = json_object(body)?;
    // `extra="forbid"` rejects any key other than `issue_number`.
    if map.keys().any(|key| key != "issue_number") {
        return Err(validation_failed());
    }
    let number = str_field(&map, "issue_number")?;
    if number.is_empty() {
        return Err(validation_failed());
    }
    Ok(number)
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
            None => result.push(label.clone()),
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
                (SELECT count(*) FROM issues i WHERE i.thread_id = t.id AND i.status = 'unread') \
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
// :migrateToIssues
// ---------------------------------------------------------------------------

/// `POST /api/v1/threads/{thread_id}:migrateToIssues`
pub(crate) async fn migrate_to_issues(
    state: &Arc<AppState>,
    user: AuthenticatedUser,
    raw_id: &str,
    body: &[u8],
) -> Result<Response, ApiError> {
    let thread_id = thread_ordering::parse_int_text(raw_id).ok_or_else(validation_failed)?;
    let (last_read, total) = parse_migrate_body(body)?;

    let mut connection = db::checkout(state).await?;
    let tx = begin(&mut connection).await?;
    let thread = lock_owned_thread(&tx, user.id(), thread_id).await?;
    if thread.total_issues.is_some() {
        return Err(ApiError::BadRequest(format!(
            "Thread {thread_id} already uses issue tracking"
        )));
    }
    if last_read > total {
        return Err(ApiError::BadRequest(
            "last_issue_read cannot exceed total_issues".to_string(),
        ));
    }
    tx.execute(
        "INSERT INTO issues (thread_id, issue_number, status, read_at, created_at, position) \
         SELECT $1, n::text, CASE WHEN n <= $2 THEN 'read' ELSE 'unread' END, \
                CASE WHEN n <= $2 THEN NOW() END, NOW(), n \
         FROM generate_series(1, $3::int) AS n",
        &[&thread_id, &last_read, &total],
    )
    .await
    .map_err(insert_error)?;
    if last_read < total {
        // `total` is capped at MAX_ISSUES by parse_migrate_body and
        // last_read <= total, so both stay small; checked arithmetic keeps
        // that invariant explicit instead of relying on it.
        let next = last_read
            .checked_add(1)
            .and_then(|next| {
                total
                    .checked_sub(last_read)
                    .map(|remaining| (next, remaining))
            })
            .ok_or_else(|| ApiError::Internal("Internal Server Error".to_string()))?;
        let (next_read, remaining) = next;
        tx.execute(
            "UPDATE threads SET total_issues = $2, reading_progress = 'in_progress', \
             next_unread_issue_id = (SELECT id FROM issues WHERE thread_id = $1 AND issue_number = $3), \
             issues_remaining = $4 WHERE id = $1",
            &[&thread_id, &total, &next_read.to_string(), &remaining],
        )
        .await
        .map_err(db::query_error)?;
    } else {
        tx.execute(
            "UPDATE threads SET total_issues = $2, reading_progress = 'completed', \
             next_unread_issue_id = NULL, issues_remaining = 0, queue_position = 0, \
             status = CASE WHEN status = $3 THEN status ELSE 'completed' END, \
             queue_position_is_manual = CASE WHEN status = $3 THEN queue_position_is_manual ELSE false END \
             WHERE id = $1",
            &[&thread_id, &total, &EXCLUDED_STATUS],
        )
        .await
        .map_err(db::query_error)?;
    }
    let response = thread_response(&tx, user, thread_id, state.option_e).await?;
    tx.commit().await.map_err(db::tx_error)?;
    Ok(Json(response).into_response())
}

// ---------------------------------------------------------------------------
// :migrateToIssuesSimple
// ---------------------------------------------------------------------------

/// `POST /api/v1/threads/{thread_id}:migrateToIssuesSimple`
pub(crate) async fn migrate_to_issues_simple(
    state: &Arc<AppState>,
    user: AuthenticatedUser,
    raw_id: &str,
    body: &[u8],
) -> Result<Response, ApiError> {
    let thread_id = thread_ordering::parse_int_text(raw_id).ok_or_else(validation_failed)?;
    let issue_number = parse_migrate_simple_body(body)?;

    let mut connection = db::checkout(state).await?;
    let tx = begin(&mut connection).await?;
    let thread = lock_owned_thread(&tx, user.id(), thread_id).await?;
    if thread.total_issues.is_some() {
        return Err(ApiError::BadRequest(format!(
            "Thread {thread_id} already uses issue tracking"
        )));
    }

    let find = "SELECT id, position FROM issues WHERE thread_id = $1 AND issue_number = $2";
    let mut current = tx
        .query_opt(find, &[&thread_id, &issue_number])
        .await
        .map_err(db::query_error)?;
    if current.is_none() {
        let Some(number) = python_int(&issue_number) else {
            return Err(ApiError::BadRequest(format!(
                "Non-numeric issue '{issue_number}' not found in thread. \
                 Please add it via Edit Thread first."
            )));
        };
        // Checked arithmetic on the arbitrary-precision issue number, then a
        // practical cap before the total reaches generate_series.
        let total = number
            .checked_add(i128::from((thread.issues_remaining - 1).max(0)))
            .ok_or_else(|| ApiError::Internal("Internal Server Error".to_string()))?;
        if total > MAX_ISSUES as i128 {
            return Err(ApiError::BadRequest(format!(
                "Total issues would exceed maximum of {MAX_ISSUES}"
            )));
        }
        if total >= 1 {
            let total = i32::try_from(total)
                .map_err(|_| ApiError::Internal("Internal Server Error".to_string()))?;
            let read_below = i32::try_from(number)
                .map_err(|_| ApiError::Internal("Internal Server Error".to_string()))?;
            tx.execute(
                "INSERT INTO issues (thread_id, issue_number, status, read_at, created_at, position) \
                 SELECT $1, n::text, CASE WHEN n < $2 THEN 'read' ELSE 'unread' END, \
                        CASE WHEN n < $2 THEN NOW() END, NOW(), n \
                 FROM generate_series(1, $3::int) AS n",
                &[&thread_id, &read_below, &total],
            )
            .await
            .map_err(insert_error)?;
        }
        current = tx
            .query_opt(find, &[&thread_id, &issue_number])
            .await
            .map_err(db::query_error)?;
        if current.is_none() {
            return Err(ApiError::BadRequest(format!(
                "Failed to create issue '{issue_number}'. Please add it via Edit Thread first."
            )));
        }
    }
    let current = current.ok_or_else(|| ApiError::Internal("Internal Server Error".into()))?;
    let current_id: i32 = current.get(0);
    let current_position: i32 = current.get(1);

    tx.execute(
        "UPDATE issues SET status = 'read', read_at = NOW() \
         WHERE thread_id = $1 AND position < $2 AND status <> 'read'",
        &[&thread_id, &current_position],
    )
    .await
    .map_err(db::query_error)?;
    tx.execute(
        "UPDATE issues SET status = 'unread', read_at = NULL WHERE id = $1",
        &[&current_id],
    )
    .await
    .map_err(db::query_error)?;
    tx.execute(
        "UPDATE threads SET total_issues = (SELECT count(*) FROM issues WHERE thread_id = $1), \
         next_unread_issue_id = $2, reading_progress = 'in_progress' WHERE id = $1",
        &[&thread_id, &current_id],
    )
    .await
    .map_err(db::query_error)?;
    let response = thread_response(&tx, user, thread_id, state.option_e).await?;
    tx.commit().await.map_err(db::tx_error)?;
    Ok(Json(response).into_response())
}

// ---------------------------------------------------------------------------
// :setCurrentIssue
// ---------------------------------------------------------------------------

/// `POST /api/v1/threads/{thread_id}:setCurrentIssue`
pub(crate) async fn set_current_issue(
    state: &Arc<AppState>,
    user: AuthenticatedUser,
    raw_id: &str,
    body: &[u8],
) -> Result<Response, ApiError> {
    let thread_id = thread_ordering::parse_int_text(raw_id).ok_or_else(validation_failed)?;
    let requested = parse_set_current_body(body)?;
    let option_e = state.option_e;

    // Reject before any session side effect, exactly as Python orders it.
    {
        let connection = db::checkout(state).await?;
        let row = connection
            .query_opt(
                "SELECT status, total_issues FROM threads WHERE id = $1 AND user_id = $2",
                &[&thread_id, &user.id()],
            )
            .await
            .map_err(db::query_error)?
            .ok_or_else(|| thread_not_found(thread_id))?;
        let status: String = row.get(0);
        let total: Option<i32> = row.get(1);
        if status != "active" {
            return Err(ApiError::BadRequest(format!(
                "Thread {thread_id} is not active"
            )));
        }
        if !option_e && total.is_none() {
            return Err(ApiError::BadRequest(format!(
                "Thread {thread_id} does not use issue tracking"
            )));
        }
    }
    let active = reading_session::initialize(state, user, None, SessionPolicy::default()).await?;
    let session_id = active.session.id;

    let mut connection = db::checkout(state).await?;
    let tx = begin(&mut connection).await?;
    // One global lock order with every other writer (issue_service::persist):
    // queue advisory lock first, then the single-key dice lock, then row locks.
    // `lock_owned_thread` re-acquires the queue lock as a no-op.
    queue::lock_queue(&tx, user.id()).await?;
    tx.query_one(
        "SELECT pg_advisory_xact_lock($1::bigint)",
        &[&(user.id() as i64)],
    )
    .await
    .map_err(db::query_error)?;
    let thread = lock_owned_thread(&tx, user.id(), thread_id).await?;
    if thread.status != "active" {
        return Err(ApiError::BadRequest(format!(
            "Thread {thread_id} is not active"
        )));
    }
    if !option_e && thread.total_issues.is_none() {
        return Err(ApiError::BadRequest(format!(
            "Thread {thread_id} does not use issue tracking"
        )));
    }

    let target_number = requested.trim().to_string();
    let target = tx
        .query_opt(
            "SELECT id, position FROM issues WHERE thread_id = $1 AND issue_number = $2",
            &[&thread_id, &target_number],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| {
            ApiError::NotFound(format!(
                "Issue '{target_number}' not found in thread {thread_id}"
            ))
        })?;
    let target_id: i32 = target.get(0);
    let target_position: i32 = target.get(1);

    tx.execute(
        "UPDATE issues SET status = 'read', read_at = NOW() \
         WHERE thread_id = $1 AND position < $2 AND status <> 'read'",
        &[&thread_id, &target_position],
    )
    .await
    .map_err(db::query_error)?;
    tx.execute(
        "UPDATE issues SET status = 'unread', read_at = NULL WHERE id = $1 AND status <> 'unread'",
        &[&target_id],
    )
    .await
    .map_err(db::query_error)?;
    let counts = tx
        .query_one(
            "SELECT count(*), count(*) FILTER (WHERE status = 'unread') \
             FROM issues WHERE thread_id = $1",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    let total_issues = counts.get::<_, i64>(0) as i32;
    let issues_remaining = counts.get::<_, i64>(1) as i32;
    tx.execute(
        "UPDATE threads SET total_issues = $2, next_unread_issue_id = $3, \
         reading_progress = 'in_progress', issues_remaining = $4 WHERE id = $1",
        &[&thread_id, &total_issues, &target_id, &issues_remaining],
    )
    .await
    .map_err(db::query_error)?;
    tx.execute(
        "UPDATE sessions SET pending_thread_id = $2, pending_issue_id = $3, \
         pending_thread_updated_at = NOW() WHERE id = $1 AND user_id = $4",
        &[&session_id, &thread_id, &target_id, &user.id()],
    )
    .await
    .map_err(db::query_error)?;

    let queue_position = display_position(&tx, user, thread_id, option_e).await?;
    let meta = tx
        .query_one(
            "SELECT title, format FROM threads WHERE id = $1",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    let title: String = meta.get(0);
    let format = normalize_format_value(&meta.get::<_, String>(1));

    if option_e {
        select_manual_pick(
            &tx,
            user,
            thread_id,
            target_id,
            &target_number,
            session_id,
            active.current_die,
        )
        .await?;
    }
    tx.commit().await.map_err(db::tx_error)?;

    Ok(Json(SetCurrentIssueResponse {
        thread_id,
        title,
        format,
        issues_remaining,
        queue_position,
        issue_id: Some(target_id),
        issue_number: Some(target_number.clone()),
        next_issue_id: Some(target_id),
        next_issue_number: Some(target_number),
        total_issues: Some(total_issues),
        reading_progress: Some("in_progress".to_string()),
    })
    .into_response())
}

/// Option E tail of `set_current_issue`: verify the corrected frontier is the
/// thread's derived next issue, then perform the manual selection
/// (`thread_service.set_pending_thread`): unsnooze, manual roll event and the
/// session pending pair.
async fn select_manual_pick(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
    thread_id: i32,
    target_id: i32,
    target_number: &str,
    session_id: i32,
    die: i32,
) -> Result<(), ApiError> {
    let validated = option_inputs::load_validated_contained_in_transaction(tx, user).await?;
    let derived = reading_eligibility::evaluate(&validated)?;
    let next_issue_id = derived
        .get(&thread_id)
        .and_then(|state| state.next_issue_id);
    if next_issue_id != Some(target_id) {
        return Err(ApiError::BadRequest(
            "The corrected issue is not available in the reading order".to_string(),
        ));
    }
    let frontiers = validated
        .eligible_frontiers()
        .map_err(|_| ApiError::Internal("Invalid reading constraints".to_string()))?;
    if !frontiers
        .iter()
        .any(|frontier| frontier.thread_id == thread_id)
    {
        return Err(ApiError::BadRequest(format!(
            "Thread {thread_id} has no available issue"
        )));
    }
    let inputs = validated.inputs();
    let unread = inputs
        .core
        .issues
        .iter()
        .filter(|issue| issue.thread_id == thread_id)
        .filter(|issue| issue.status != "read")
        .filter(|issue| !inputs.excluded_issue_ids.contains(&issue.id))
        .count();
    if unread == 0 {
        return Err(ApiError::BadRequest(format!(
            "Thread {thread_id} has no issues remaining"
        )));
    }

    let session = tx
        .query_one(
            "SELECT snoozed_thread_ids::text, skipped_thread_ids::text \
             FROM sessions WHERE id = $1 AND user_id = $2 FOR UPDATE",
            &[&session_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let snoozed = reading_session::decode_thread_ids(session.get(0))?.unwrap_or_default();
    let skipped = reading_session::decode_thread_ids(session.get(1))?.unwrap_or_default();
    if snoozed.contains(&thread_id) {
        tx.execute(
            "INSERT INTO events (type, session_id, thread_id, timestamp) \
             VALUES ('unsnooze', $1, $2, NOW())",
            &[&session_id, &thread_id],
        )
        .await
        .map_err(db::query_error)?;
    }
    let mut excluded: HashSet<i32> = skipped.into_iter().collect();
    excluded.extend(roll_exclusions::durable_snoozed(tx, user.id()).await?);
    excluded.extend(roll_exclusions::excluded_status_ids(tx, user.id()).await?);
    if excluded.contains(&thread_id) {
        return Err(ApiError::BadRequest(format!(
            "Thread {thread_id} is excluded from this reading session"
        )));
    }

    tx.execute(
        "INSERT INTO events (type, session_id, selected_thread_id, die, result, selection_method, \
                             issue_id, issue_number, timestamp) \
         VALUES ('roll', $1, $2, $3, 0, 'manual', $4, $5, NOW())",
        &[&session_id, &thread_id, &die, &target_id, &target_number],
    )
    .await
    .map_err(db::query_error)?;
    let remaining_snoozed: Vec<i32> = snoozed
        .iter()
        .copied()
        .filter(|id| *id != thread_id)
        .collect();
    if remaining_snoozed.len() != snoozed.len() {
        let encoded = serde_json::to_string(&remaining_snoozed)
            .map_err(|_| ApiError::Internal("Internal Server Error".to_string()))?;
        tx.execute(
            "UPDATE sessions SET snoozed_thread_ids = $2::text::json WHERE id = $1",
            &[&session_id, &encoded],
        )
        .await
        .map_err(db::query_error)?;
    }
    Ok(())
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

/// Documentation-only operation for the explicit migration.
#[utoipa::path(
    post,
    path = "/api/v1/threads/{thread_id}:migrateToIssues",
    tag = "threads",
    operation_id = "thread_issues_migrate",
    params(("thread_id" = i32, Path, description = "Owned Thread identifier")),
    request_body = MigrateToIssuesRequest,
    responses(
        (status = 200, description = "Migrated thread", body = ThreadResponse),
        (status = 400, description = "Already migrated or inconsistent range"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn migrate_documentation() {}

/// Documentation-only operation for the simplified migration.
#[utoipa::path(
    post,
    path = "/api/v1/threads/{thread_id}:migrateToIssuesSimple",
    tag = "threads",
    operation_id = "thread_issues_migrate_simple",
    params(("thread_id" = i32, Path, description = "Owned Thread identifier")),
    request_body = MigrateToIssuesSimpleRequest,
    responses(
        (status = 200, description = "Migrated thread", body = ThreadResponse),
        (status = 400, description = "Already migrated or issue cannot be created"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn migrate_simple_documentation() {}

/// Documentation-only operation for correcting the current issue.
#[utoipa::path(
    post,
    path = "/api/v1/threads/{thread_id}:setCurrentIssue",
    tag = "threads",
    operation_id = "thread_issues_set_current",
    params(("thread_id" = i32, Path, description = "Owned Thread identifier")),
    request_body = SetCurrentIssueRequest,
    responses(
        (status = 200, description = "Corrected current issue", body = SetCurrentIssueResponse),
        (status = 400, description = "Thread inactive, untracked or issue unavailable"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread or issue not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn set_current_documentation() {}

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
        reorder_documentation,
        migrate_documentation,
        migrate_simple_documentation,
        set_current_documentation
    ),
    components(schemas(
        IssueResponse,
        ThreadIssueCreateListResponse,
        CreatorCredit,
        IssueCreatorsEntry,
        ThreadIssueCreatorsResponse,
        ThreadResponse,
        SetCurrentIssueResponse,
        IssueCreateRange,
        IssueReorderRequest,
        MigrateToIssuesRequest,
        MigrateToIssuesSimpleRequest,
        SetCurrentIssueRequest
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
        // All-numeric threads repair earlier out-of-order appends.
        assert_eq!(order(&["3", "1"], &["2"]), Some(strings(&["1", "2", "3"])));
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
        assert_eq!(
            parse_migrate_body(br#"{"last_issue_read":0,"total_issues":1}"#).unwrap(),
            (0, 1)
        );
        assert!(parse_migrate_body(br#"{"last_issue_read":-1,"total_issues":1}"#).is_err());
        assert!(parse_migrate_body(br#"{"last_issue_read":0,"total_issues":0}"#).is_err());
        assert!(parse_migrate_simple_body(br#"{"issue_number":""}"#).is_err());
        assert!(parse_migrate_simple_body(
            format!(r#"{{"issue_number":"{}"}}"#, "9".repeat(51)).as_bytes()
        )
        .is_err());
        assert!(parse_set_current_body(br#"{"issue_number":"5","extra":1}"#).is_err());
        assert_eq!(
            parse_set_current_body(br#"{"issue_number":" 5 "}"#).unwrap(),
            " 5 "
        );
    }

    #[test]
    fn contract_documents_every_operation_and_stays_current() {
        let document = serde_json::to_value(thread_issues_openapi()).unwrap();
        for path in [
            "/api/v1/threads/{thread_id}/issues",
            "/api/v1/threads/{thread_id}/issues/creators",
            "/api/v1/threads/{thread_id}/issues:reorder",
            "/api/v1/threads/{thread_id}:migrateToIssues",
            "/api/v1/threads/{thread_id}:migrateToIssuesSimple",
            "/api/v1/threads/{thread_id}:setCurrentIssue",
        ] {
            assert!(document["paths"].get(path).is_some(), "{path}");
        }
        let expected = include_str!("../../contracts/thread-issues-v1.openapi.json");
        let generated = thread_issues_openapi().to_pretty_json().unwrap();
        assert_eq!(expected.trim_end(), generated.trim_end());
    }
}
