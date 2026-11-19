//! Native cutover of the Thread lifecycle writers that kept their original
//! `/api/v1/threads` URLs (#4832 part A):
//!
//! * `POST /api/v1/threads/` (create)
//! * `PUT` / `DELETE /api/v1/threads/{thread_id}`
//! * `POST /api/v1/threads/{thread_id}/exclude`, `/restore`, `/set-pending`
//! * `POST /api/v1/threads/reactivate`
//! * `GET /api/v1/threads/stale`
//! * `POST /api/v1/threads/check-duplicates`
//! * `POST /api/v1/threads/groups:batch`
//! * `GET /api/v1/threads/excluded/threads`
//! * `PUT /api/v1/threads/{thread_id}/test-backdate` (TEST_ENVIRONMENT-only)
//!
//! The Python handlers (`app/api/thread.py`, `app/api/dependency_group_batch.py`
//! and `app/services/thread_service.py`) are the behavioral oracle. Status
//! codes, error details, response field order, transactions, the per-reader
//! queue advisory lock and ownership scoping mirror them.
//!
//! Scope notes:
//! * Production runs legacy execution (`OPTION_E_ENABLED` unset). The Option E
//!   preview is honored for the dense Queue ordinal in lifecycle responses;
//!   `stale` and `set-pending` fail closed with 503 while the preview is
//!   active because their candidate pool is then the evaluated graph.
//! * `test-backdate` is only available when `TEST_ENVIRONMENT` is set, matching
//!   the Python test helper's guard.
//! * Python's in-process `slowapi` limits (30-120 requests per minute) are
//!   per-instance memory and are not ported.
#![forbid(unsafe_code)]
use crate::{
    auth::{AuthenticatedUser, VerifiedAccessClaims},
    continuity_plans::ContinuityPlanNode,
    db,
    dice_api::Pending,
    option_inputs, queue,
    reading_session::{self, SessionPolicy},
    roll_exclusions,
    roll_override::RollResponse,
    thread_validation::{
        coerce_bool, int_field, parse_body, path_int, query_pairs, query_value, require_object,
        str_field, Bounds, Check, IntOutcome, LifecycleError, StrRules,
    },
    threads, ApiError, AppState,
};
use axum::{
    body::Bytes,
    extract::{Path, RawQuery, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::{ser::SerializeMap, Serialize, Serializer};
use serde_json::{json, Value};
use std::{
    collections::{BTreeMap, HashMap, HashSet},
    sync::Arc,
    time::Duration,
};
use tokio_postgres::{IsolationLevel, Transaction};
use unicode_casefold::UnicodeCaseFold;

type HandlerResult = Result<Response, LifecycleError>;

/// Maximum threads one `groups:batch` request may name.
const MAX_BATCH_THREADS: usize = 200;
/// Maximum possible-existing-volume matches one advisory check returns.
const MAX_POTENTIAL_DUPLICATE_MATCHES: usize = 5;
/// Minimum title resemblance that still counts as a possible existing volume.
const MIN_TITLE_SIMILARITY: f64 = 0.5;
const MAX_MANUAL_CREATOR_CREDITS: usize = 50;
const MAX_CREATOR_NAME_LENGTH: usize = 200;
const MAX_MANUAL_ROLES_PER_CREDIT: usize = 12;
const MAX_MANUAL_ROLE_LENGTH: usize = 60;
/// Coordinator-approved hardening for `POST /api/v1/threads/reactivate`: Python
/// accepts any positive count, but the native set-based insert must never let a
/// single request scale an unbounded insert. Counts above this are HTTP 422.
const MAX_ISSUES_TO_ADD: i64 = 10_000;

// ---------------------------------------------------------------------------
// Wire types
// ---------------------------------------------------------------------------

/// The Python `ThreadResponse` projection every lifecycle writer returns.
#[derive(Debug, Serialize, utoipa::ToSchema)]
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
    pub manual_creator_credits: Value,
}

/// Body of `POST /api/v1/threads/`.
#[derive(Debug, serde::Deserialize, utoipa::ToSchema)]
pub struct ThreadCreateRequest {
    pub title: String,
    pub format: String,
    pub issues_remaining: i32,
    pub total_issues: Option<i32>,
    pub notes: Option<String>,
    #[serde(default)]
    pub manual_creator_credits: Vec<Value>,
    #[serde(default)]
    pub is_test: bool,
}

/// Body of `PUT /api/v1/threads/{thread_id}`.
#[derive(Debug, serde::Deserialize, utoipa::ToSchema)]
pub struct ThreadUpdateRequest {
    pub title: Option<String>,
    pub format: Option<String>,
    pub issues_remaining: Option<i32>,
    pub notes: Option<String>,
    pub manual_creator_credits: Option<Vec<Value>>,
    pub is_test: Option<bool>,
}

/// Body of `POST /api/v1/threads/reactivate`.
#[derive(Debug, serde::Deserialize, utoipa::ToSchema)]
pub struct ReactivateRequest {
    pub thread_id: i32,
    pub issues_to_add: i32,
}

/// Optional body of `POST /api/v1/threads/{thread_id}/set-pending`.
#[derive(Debug, serde::Deserialize, utoipa::ToSchema)]
pub struct SetPendingRequest {
    pub expected_issue_id: Option<i32>,
}

/// Body of `POST /api/v1/threads/check-duplicates`.
#[derive(Debug, serde::Deserialize, utoipa::ToSchema)]
pub struct CheckDuplicatesRequest {
    pub title: String,
    pub format: String,
    pub comicvine_volume_id: Option<i32>,
    pub exclude_thread_id: Option<i32>,
}

/// Body of `POST /api/v1/threads/groups:batch`.
#[derive(Debug, serde::Deserialize, utoipa::ToSchema)]
pub struct GroupsBatchRequest {
    pub thread_ids: Vec<i32>,
}

/// One possible existing volume.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct PotentialDuplicateMatch {
    pub thread_id: i32,
    pub title: String,
    pub format: String,
    pub status: String,
    pub issues_remaining: i32,
    pub total_issues: Option<i32>,
    pub comicvine_volume_id: Option<i64>,
    pub start_year: Option<i32>,
    pub match_type: String,
}

/// Response of `POST /api/v1/threads/check-duplicates`.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct CheckDuplicatesResponse {
    pub matches: Vec<PotentialDuplicateMatch>,
}

/// Compact crossover group metadata.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct DependencyGroupSummary {
    pub id: i32,
    pub name: String,
}

/// Insertion-ordered `{thread_id: [groups]}` map (Python dict order).
pub struct GroupsByThread(Vec<(i32, Vec<DependencyGroupSummary>)>);

impl Serialize for GroupsByThread {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut map = serializer.serialize_map(Some(self.0.len()))?;
        for (thread_id, groups) in &self.0 {
            map.serialize_entry(&thread_id.to_string(), groups)?;
        }
        map.end()
    }
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

fn not_found(thread_id: i64) -> ApiError {
    ApiError::NotFound(format!("Thread {thread_id} not found"))
}

fn json_response(status: StatusCode, body: impl Serialize) -> Response {
    (status, Json(body)).into_response()
}

/// Mirror `app.models.thread.normalize_format_value`.
fn normalize_format_value(value: &str) -> String {
    let stripped = value.trim();
    match stripped.to_lowercase().as_str() {
        "comic" | "comics" => "Comic".to_string(),
        "digital" => "Digital".to_string(),
        _ => stripped.to_string(),
    }
}

/// Mirror `app.models.thread.normalize_notes_value`.
fn normalize_notes_value(notes: Option<&str>) -> Option<String> {
    notes.and_then(|text| {
        if text.trim().is_empty() {
            None
        } else {
            Some(text.to_string())
        }
    })
}

fn collapse_whitespace(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Mirror `normalize_manual_creator_credits`.
fn normalize_manual_creator_credits(raw: &[Value]) -> Value {
    let mut normalized = Vec::new();
    for item in raw {
        if normalized.len() >= MAX_MANUAL_CREATOR_CREDITS {
            break;
        }
        let Some(object) = item.as_object() else {
            continue;
        };
        let Some(name) = object.get("name").and_then(Value::as_str) else {
            continue;
        };
        let clean_name: String = collapse_whitespace(name)
            .chars()
            .take(MAX_CREATOR_NAME_LENGTH)
            .collect();
        if clean_name.is_empty() {
            continue;
        }
        let mut roles: Vec<String> = Vec::new();
        if let Some(raw_roles) = object.get("roles").and_then(Value::as_array) {
            for role in raw_roles {
                let Some(role) = role.as_str() else {
                    continue;
                };
                let clean_role: String = collapse_whitespace(role)
                    .chars()
                    .take(MAX_MANUAL_ROLE_LENGTH)
                    .collect();
                if !clean_role.is_empty() && !roles.contains(&clean_role) {
                    roles.push(clean_role);
                }
                if roles.len() >= MAX_MANUAL_ROLES_PER_CREDIT {
                    break;
                }
            }
        }
        normalized.push(json!({"name": clean_name, "roles": roles}));
    }
    Value::Array(normalized)
}

fn iso(column: &str) -> String {
    format!(
        "CASE WHEN {column} IS NULL THEN NULL \
         WHEN date_trunc('second', {column}) = {column} \
         THEN to_char({column} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
         ELSE to_char({column} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') END"
    )
}

/// Thread ids evaluated as eligible while the Option E preview is active.
async fn option_e_eligible(
    state: &AppState,
    user: AuthenticatedUser,
) -> Result<Option<HashSet<i32>>, ApiError> {
    if !state.option_e {
        return Ok(None);
    }
    let validated = option_inputs::load_option_inputs_contained(state, user).await?;
    Ok(Some(queue::evaluated_eligible_ids(&validated)?))
}

/// Option E changes the candidate pool of `stale`/`set-pending`; fail closed.
fn reject_option_e_preview(state: &AppState) -> Result<(), ApiError> {
    if state.option_e {
        return Err(ApiError::ServiceUnavailable(
            "Option E execution is not supported by this operation".to_string(),
        ));
    }
    Ok(())
}

/// Load `ThreadResponse` projections for owned threads, in `ids` order.
///
/// Mirrors `thread_to_response`: unread counts for issue-tracked threads, the
/// stored counter otherwise, the dense Queue ordinal (blocked rows last), and
/// the number of the stored next-unread issue.
async fn load_views(
    client: &impl tokio_postgres::GenericClient,
    user_id: i32,
    ids: &[i32],
    eligible: Option<&HashSet<i32>>,
) -> Result<Vec<ThreadResponse>, ApiError> {
    let sql = format!(
        "WITH ranked AS (
             SELECT id,
                    row_number() OVER (
                        ORDER BY CASE WHEN $2::boolean THEN NOT (id = ANY($3::int[]))
                                      ELSE is_blocked END,
                                 queue_position, id)::int AS pos
             FROM threads
             WHERE user_id = $1 AND status = 'active' AND queue_position >= 1
         )
         SELECT t.id, t.title, t.format,
                CASE WHEN t.total_issues IS NOT NULL
                     THEN (SELECT count(*)::int FROM issues i
                           WHERE i.thread_id = t.id AND i.status = 'unread')
                     ELSE t.issues_remaining END,
                COALESCE(r.pos, 0), t.status, t.last_rating,
                {last_activity}, t.notes, t.is_test, t.is_blocked,
                {created}, t.total_issues, t.reading_progress,
                t.next_unread_issue_id,
                (SELECT i.issue_number FROM issues i WHERE i.id = t.next_unread_issue_id),
                t.manual_creator_credits
         FROM unnest($4::int[]) WITH ORDINALITY AS wanted(id, ord)
         JOIN threads t ON t.id = wanted.id AND t.user_id = $1
         LEFT JOIN ranked r ON r.id = t.id
         ORDER BY wanted.ord",
        last_activity = iso("t.last_activity_at"),
        created = iso("t.created_at"),
    );
    let eligible_ids: Vec<i32> = eligible
        .map(|set| set.iter().copied().collect())
        .unwrap_or_default();
    let ids_vec: Vec<i32> = ids.to_vec();
    let rows = client
        .query(
            &sql,
            &[&user_id, &eligible.is_some(), &eligible_ids, &ids_vec],
        )
        .await
        .map_err(db::query_error)?;
    rows.iter()
        .map(|row| -> Result<ThreadResponse, ApiError> {
            let credits: Value = row.try_get(16).map_err(db::query_error)?;
            Ok(ThreadResponse {
                id: row.try_get(0).map_err(db::query_error)?,
                title: row.try_get(1).map_err(db::query_error)?,
                format: normalize_format_value(
                    &row.try_get::<_, String>(2).map_err(db::query_error)?,
                ),
                issues_remaining: row.try_get(3).map_err(db::query_error)?,
                queue_position: row.try_get(4).map_err(db::query_error)?,
                status: row.try_get(5).map_err(db::query_error)?,
                last_rating: row.try_get(6).map_err(db::query_error)?,
                last_activity_at: row.try_get(7).map_err(db::query_error)?,
                notes: row.try_get(8).map_err(db::query_error)?,
                is_test: row.try_get(9).map_err(db::query_error)?,
                is_blocked: row.try_get(10).map_err(db::query_error)?,
                blocking_reasons: Vec::new(),
                created_at: row.try_get(11).map_err(db::query_error)?,
                total_issues: row.try_get(12).map_err(db::query_error)?,
                reading_progress: row.try_get(13).map_err(db::query_error)?,
                next_unread_issue_id: row.try_get(14).map_err(db::query_error)?,
                next_unread_issue_number: row.try_get(15).map_err(db::query_error)?,
                manual_creator_credits: if credits.is_array() {
                    credits
                } else {
                    Value::Array(Vec::new())
                },
            })
        })
        .collect()
}

/// Read one committed thread back as the Python `ThreadResponse`.
async fn respond_thread(
    state: &AppState,
    user: AuthenticatedUser,
    thread_id: i32,
    status: StatusCode,
) -> HandlerResult {
    let eligible = option_e_eligible(state, user).await?;
    let connection = db::checkout(state).await?;
    let mut views = load_views(&**connection, user.id(), &[thread_id], eligible.as_ref()).await?;
    let view = views.pop().ok_or_else(|| not_found(thread_id.into()))?;
    Ok(json_response(status, view))
}

/// Take the transaction-scoped per-reader queue lock (`acquire_queue_lock`).
async fn acquire_queue_lock(tx: &Transaction<'_>, user_id: i32) -> Result<(), ApiError> {
    queue::lock_queue(tx, user_id).await
}

/// Rewrite the active queue as a dense `1..N` sequence (`renormalize_queue_positions`).
async fn renormalize(tx: &Transaction<'_>, user_id: i32) -> Result<(), ApiError> {
    acquire_queue_lock(tx, user_id).await?;
    tx.execute(
        "UPDATE threads t SET queue_position = r.seq
         FROM (SELECT id, row_number() OVER (ORDER BY queue_position, id)::int AS seq
               FROM threads
               WHERE user_id = $1 AND status = 'active' AND queue_position >= 1) r
         WHERE t.id = r.id AND t.queue_position <> r.seq",
        &[&user_id],
    )
    .await
    .map_err(db::tx_error)?;
    Ok(())
}

async fn max_queue_position(tx: &Transaction<'_>, user_id: i32) -> Result<i32, ApiError> {
    let row = tx
        .query_one(
            "SELECT COALESCE(MAX(queue_position), 0)::int FROM threads
             WHERE user_id = $1 AND status = 'active' AND queue_position >= 1",
            &[&user_id],
        )
        .await
        .map_err(db::tx_error)?;
    Ok(row.get(0))
}

async fn begin<'a>(
    pending: &'a mut Pending,
) -> Result<deadpool_postgres::Transaction<'a>, ApiError> {
    pending
        .connection()
        .build_transaction()
        .isolation_level(IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::tx_error)
}

/// Run `$body` inside one read-committed transaction on a pooled connection.
///
/// A successful body commits (commit failures map through `$commit_error`); a
/// failed body rolls back and returns the connection to the pool only when the
/// rollback completed, so a cancelled or broken command never recycles a busy
/// socket.
macro_rules! with_tx {
    ($state:expr, $tx:ident, $commit_error:path, $body:block) => {{
        let mut pending = Pending::new(db::checkout($state).await?);
        let $tx = begin(&mut pending).await?;
        let result: Result<_, LifecycleError> = async $body.await;
        match result {
            Ok(value) => {
                $tx.commit().await.map_err($commit_error)?;
                pending.release();
                Ok(value)
            }
            Err(error) => {
                if $tx.rollback().await.is_ok() {
                    pending.release();
                }
                Err(error)
            }
        }
    }};
}

/// The stored fields lifecycle transitions read from an owned thread.
struct OwnedThread {
    id: i32,
    title: String,
    format: String,
    issues_remaining: i32,
    total_issues: Option<i32>,
    reading_progress: Option<String>,
    next_unread_issue_id: Option<i32>,
    status: String,
    is_blocked: bool,
    queue_position: i32,
}

async fn find_owned(
    tx: &Transaction<'_>,
    user_id: i32,
    thread_id: i64,
    for_update: bool,
) -> Result<OwnedThread, ApiError> {
    let id = i32::try_from(thread_id).map_err(|_| not_found(thread_id))?;
    let sql = format!(
        "SELECT id, title, format, issues_remaining, total_issues, reading_progress,
                next_unread_issue_id, status, is_blocked, queue_position
         FROM threads WHERE id = $1 AND user_id = $2{}",
        if for_update { " FOR UPDATE" } else { "" }
    );
    let row = tx
        .query_opt(&sql, &[&id, &user_id])
        .await
        .map_err(db::tx_error)?
        .ok_or_else(|| not_found(thread_id))?;
    Ok(OwnedThread {
        id: row.get(0),
        title: row.get(1),
        format: row.get(2),
        issues_remaining: row.get(3),
        total_issues: row.get(4),
        reading_progress: row.get(5),
        next_unread_issue_id: row.get(6),
        status: row.get(7),
        is_blocked: row.get(8),
        queue_position: row.get(9),
    })
}

/// Run `body` and retry a bounded number of times on deadlock victims.
macro_rules! retry_deadlock {
    ($attempts:expr, $delay_ms:expr, $body:expr) => {{
        let mut attempt = 0u32;
        loop {
            match $body.await {
                Err(LifecycleError::Api(ApiError::DeadlockDetected)) if attempt + 1 < $attempts => {
                    tokio::time::sleep(Duration::from_millis($delay_ms << attempt)).await;
                    attempt += 1;
                }
                other => break other,
            }
        }
    }};
}

// ---------------------------------------------------------------------------
// POST /api/v1/threads/
// ---------------------------------------------------------------------------

struct CreateInput {
    title: String,
    format: String,
    issues_remaining: i32,
    total_issues: Option<i32>,
    notes: Option<String>,
    credits: Value,
    is_test: bool,
}

fn validate_title(check: &mut Check, loc: &[&str], title: &Option<String>) {
    if let Some(title) = title {
        if title.trim().is_empty() {
            check.push(
                loc,
                "value_error",
                "Value error, Title cannot be empty or whitespace only",
            );
        }
    }
}

fn credits_field(check: &mut Check, value: Option<&Value>, nullable: bool) -> Option<Vec<Value>> {
    let loc = ["body", "manual_creator_credits"];
    let value = value?;
    if value.is_null() {
        if !nullable {
            check.push(&loc, "list_type", "Input should be a valid list");
        }
        return None;
    }
    let Some(items) = value.as_array() else {
        check.push(&loc, "list_type", "Input should be a valid list");
        return None;
    };
    let mut clean = true;
    for (index, item) in items.iter().enumerate() {
        if !item.is_object() {
            check.push_indexed(
                &loc,
                index,
                "dict_type",
                "Input should be a valid dictionary",
            );
            clean = false;
        }
    }
    clean.then(|| items.clone())
}

fn to_i32(check: &mut Check, loc: &[&str], value: Option<i64>) -> Option<i32> {
    value.and_then(|int| match i32::try_from(int) {
        Ok(value) => Some(value),
        Err(_) => {
            check.push(loc, "int_parsing", "Input should be a valid 32-bit integer");
            None
        }
    })
}

fn parse_create(body: Option<Value>) -> Result<CreateInput, LifecycleError> {
    let map = require_object(body)?;
    let raw_body = Value::Object(map.clone());
    let mut check = Check::default();
    let title = str_field(
        &mut check,
        &["body", "title"],
        map.get("title"),
        StrRules {
            min: Some(1),
            max: Some(200),
        },
        false,
        true,
    );
    validate_title(&mut check, &["body", "title"], &title);
    let format = str_field(
        &mut check,
        &["body", "format"],
        map.get("format"),
        StrRules {
            min: Some(1),
            max: None,
        },
        false,
        true,
    );
    let issues_remaining = int_field(
        &mut check,
        &["body", "issues_remaining"],
        map.get("issues_remaining"),
        Bounds {
            ge: Some(0),
            ..Bounds::default()
        },
        false,
        true,
    );
    let issues_remaining = to_i32(&mut check, &["body", "issues_remaining"], issues_remaining);
    let total_issues = int_field(
        &mut check,
        &["body", "total_issues"],
        map.get("total_issues"),
        Bounds {
            ge: Some(1),
            ..Bounds::default()
        },
        true,
        false,
    );
    let total_issues = to_i32(&mut check, &["body", "total_issues"], total_issues);
    let notes = str_field(
        &mut check,
        &["body", "notes"],
        map.get("notes"),
        StrRules::default(),
        true,
        false,
    );
    let credits = credits_field(&mut check, map.get("manual_creator_credits"), false);
    let is_test = match map.get("is_test") {
        None => false,
        Some(value) => match coerce_bool(value) {
            Some(flag) => flag,
            None => {
                check.push(
                    &["body", "is_test"],
                    "bool_parsing",
                    "Input should be a valid boolean, unable to interpret input",
                );
                false
            }
        },
    };
    check.finish(raw_body)?;
    Ok(CreateInput {
        title: title.unwrap_or_default(),
        format: format.unwrap_or_default(),
        issues_remaining: issues_remaining.unwrap_or_default(),
        total_issues,
        notes,
        credits: normalize_manual_creator_credits(&credits.unwrap_or_default()),
        is_test,
    })
}

async fn create_once(
    state: &AppState,
    user: AuthenticatedUser,
    input: &CreateInput,
) -> Result<i32, LifecycleError> {
    with_tx!(state, tx, db::tx_error, {
        let format_value = normalize_format_value(&input.format);
        // #3466: a double-clicked "Create Series" merges into the first create.
        let existing = tx
            .query_opt(
                "SELECT id FROM threads
             WHERE user_id = $1 AND lower(title) = $2 AND format = $3
               AND issues_remaining = $4
               AND created_at >= NOW() - interval '5 seconds'
             ORDER BY created_at DESC, id DESC LIMIT 1",
                &[
                    &user.id(),
                    &input.title.to_lowercase(),
                    &format_value,
                    &input.issues_remaining,
                ],
            )
            .await
            .map_err(db::tx_error)?;
        if let Some(row) = existing {
            let id: i32 = row.get(0);
            return Ok(id);
        }
        let max_position = max_queue_position(&tx, user.id()).await?;
        let notes = normalize_notes_value(input.notes.as_deref());
        let row = tx
            .query_one(
                "INSERT INTO threads
               (title, format, issues_remaining, total_issues, queue_position, user_id,
                notes, manual_creator_credits, is_test, status, is_blocked,
                queue_position_is_manual, created_at)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'active', false, false, NOW())
             RETURNING id",
                &[
                    &input.title,
                    &format_value,
                    &input.issues_remaining,
                    &input.total_issues,
                    &(max_position + 1),
                    &user.id(),
                    &notes,
                    &input.credits,
                    &input.is_test,
                ],
            )
            .await
            .map_err(db::tx_error)?;
        let id: i32 = row.get(0);
        Ok(id)
    })
}

/// `POST /api/v1/threads/`
pub async fn create_thread(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    body: Bytes,
) -> HandlerResult {
    let input = parse_create(parse_body(&body)?)?;
    let id = retry_deadlock!(3, 100u64, create_once(&state, user, &input))?;
    respond_thread(&state, user, id, StatusCode::CREATED).await
}

// ---------------------------------------------------------------------------
// PUT /api/v1/threads/{thread_id}
// ---------------------------------------------------------------------------

struct UpdateInput {
    title: Option<String>,
    format: Option<String>,
    issues_remaining: Option<i32>,
    notes_present: bool,
    notes: Option<String>,
    credits: Option<Value>,
    is_test: Option<bool>,
}

fn parse_update(
    check: &mut Check,
    body: Option<Value>,
) -> Result<(UpdateInput, Value), LifecycleError> {
    let map = match require_object(body) {
        Ok(map) => map,
        Err(LifecycleError::Validation { errors, body }) => {
            // Surface path errors collected so far together with the body error.
            let mut combined = check_errors(check);
            combined.extend(errors);
            return Err(LifecycleError::Validation {
                errors: combined,
                body,
            });
        }
        Err(other) => return Err(other),
    };
    let raw_body = Value::Object(map.clone());
    let title = str_field(
        check,
        &["body", "title"],
        map.get("title"),
        StrRules {
            min: Some(1),
            max: Some(200),
        },
        true,
        false,
    );
    validate_title(check, &["body", "title"], &title);
    let format = str_field(
        check,
        &["body", "format"],
        map.get("format"),
        StrRules {
            min: Some(1),
            max: None,
        },
        true,
        false,
    );
    let issues_remaining = int_field(
        check,
        &["body", "issues_remaining"],
        map.get("issues_remaining"),
        Bounds {
            ge: Some(0),
            ..Bounds::default()
        },
        true,
        false,
    );
    let issues_remaining = to_i32(check, &["body", "issues_remaining"], issues_remaining);
    let notes = str_field(
        check,
        &["body", "notes"],
        map.get("notes"),
        StrRules::default(),
        true,
        false,
    );
    let credits = credits_field(check, map.get("manual_creator_credits"), true);
    let is_test = match map.get("is_test") {
        None | Some(Value::Null) => None,
        Some(value) => match coerce_bool(value) {
            Some(flag) => Some(flag),
            None => {
                check.push(
                    &["body", "is_test"],
                    "bool_parsing",
                    "Input should be a valid boolean, unable to interpret input",
                );
                None
            }
        },
    };
    Ok((
        UpdateInput {
            title,
            format,
            issues_remaining,
            notes_present: map.contains_key("notes"),
            notes,
            credits: credits.map(|items| normalize_manual_creator_credits(&items)),
            is_test,
        },
        raw_body,
    ))
}

fn check_errors(check: &Check) -> Vec<Value> {
    check.errors_snapshot()
}

async fn update_once(
    state: &AppState,
    user: AuthenticatedUser,
    thread_id: i64,
    input: &UpdateInput,
) -> Result<(), LifecycleError> {
    with_tx!(state, tx, db::tx_error, {
        // Take the queue lock before the row lock when this update can mutate the
        // active queue, matching every other queue writer (exclude/restore/delete/
        // reactivate/renormalize) so concurrent operations cannot deadlock.
        if input.issues_remaining.is_some() {
            acquire_queue_lock(&tx, user.id()).await?;
        }
        // Lock the owned row so a concurrent writer cannot change fields that this
        // partial PUT does not supply while we decide/apply queue transitions.
        let thread = find_owned(&tx, user.id(), thread_id, true).await?;

        // Python applies the legacy issues_remaining transition in-place (and may
        // flush status before computing an append position) instead of rewriting the
        // whole row from a stale snapshot.
        if let Some(remaining) = input.issues_remaining {
            if thread.total_issues.is_none() {
                let mut status = thread.status.clone();
                let mut queue_position = thread.queue_position;
                let mut manual_cleared = false;
                let mut renormalize_after = false;
                let excluded = status == "excluded";
                if remaining == 0 {
                    if !excluded {
                        status = "completed".to_string();
                        manual_cleared = true;
                        queue_position = 0;
                        renormalize_after = true;
                    }
                } else if !excluded {
                    status = "active".to_string();
                    if queue_position < 1 {
                        // Flush the status first so the max excludes this thread.
                        tx.execute(
                            "UPDATE threads SET status = $2 WHERE id = $1",
                            &[&thread.id, &status],
                        )
                        .await
                        .map_err(db::tx_error)?;
                        queue_position = max_queue_position(&tx, user.id()).await? + 1;
                        renormalize_after = true;
                    }
                }
                tx.execute(
                    "UPDATE threads SET issues_remaining = $2, status = $3, queue_position = $4,
                        queue_position_is_manual = CASE WHEN $5 THEN false ELSE queue_position_is_manual END
                     WHERE id = $1",
                    &[
                        &thread.id,
                        &remaining,
                        &status,
                        &queue_position,
                        &manual_cleared,
                    ],
                )
                .await
                .map_err(db::tx_error)?;
                if renormalize_after {
                    renormalize(&tx, user.id()).await?;
                }
            }
        }

        if let Some(title) = &input.title {
            tx.execute(
                "UPDATE threads SET title = $2 WHERE id = $1",
                &[&thread.id, title],
            )
            .await
            .map_err(db::tx_error)?;
        }
        if let Some(format) = &input.format {
            let format_value = normalize_format_value(format);
            tx.execute(
                "UPDATE threads SET format = $2 WHERE id = $1",
                &[&thread.id, &format_value],
            )
            .await
            .map_err(db::tx_error)?;
        }
        if input.notes_present {
            let notes = normalize_notes_value(input.notes.as_deref());
            tx.execute(
                "UPDATE threads SET notes = $2 WHERE id = $1",
                &[&thread.id, &notes],
            )
            .await
            .map_err(db::tx_error)?;
        }
        if let Some(credits) = &input.credits {
            tx.execute(
                "UPDATE threads SET manual_creator_credits = $2 WHERE id = $1",
                &[&thread.id, credits],
            )
            .await
            .map_err(db::tx_error)?;
        }
        if let Some(is_test) = input.is_test {
            tx.execute(
                "UPDATE threads SET is_test = $2 WHERE id = $1",
                &[&thread.id, &is_test],
            )
            .await
            .map_err(db::tx_error)?;
        }
        Ok(())
    })
}

/// `PUT /api/v1/threads/{thread_id}`
pub async fn update_thread(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(raw_id): Path<String>,
    body: Bytes,
) -> HandlerResult {
    let mut check = Check::default();
    let thread_id = path_int(&mut check, "thread_id", &raw_id);
    let parsed_body = parse_body(&body)?;
    let (input, raw_body) = parse_update(&mut check, parsed_body)?;
    check.finish(raw_body)?;
    let thread_id = thread_id.unwrap_or_default();
    update_once(&state, user, thread_id, &input).await?;
    respond_thread(&state, user, thread_id as i32, StatusCode::OK).await
}

// ---------------------------------------------------------------------------
// DELETE /api/v1/threads/{thread_id}
// ---------------------------------------------------------------------------

/// Python `int(value)` for the plan node fields it tolerates.
fn python_int(value: Option<&Value>) -> Option<i64> {
    match value? {
        Value::Number(number) => number
            .as_i64()
            .or_else(|| number.as_f64().map(|float| float.trunc() as i64)),
        Value::String(text) => text.trim().parse::<i64>().ok(),
        Value::Bool(flag) => Some(i64::from(*flag)),
        _ => None,
    }
}

/// Prune plan nodes that reference a deleted thread or its issues and
/// renumber each lane contiguously (lane order = first appearance).
fn prune_plan_nodes(
    nodes: &[Value],
    thread_id: i64,
    deleted_issue_ids: &HashSet<i64>,
) -> Option<Vec<Value>> {
    let mut pruned: Vec<Value> = Vec::new();
    let mut changed = false;
    for node in nodes {
        let node_type = node
            .get("node_type")
            .map(|value| match value {
                Value::String(text) => text.clone(),
                other => other.to_string(),
            })
            .unwrap_or_default();
        let reference = match node.get("ref_id") {
            None => Some(0),
            some => python_int(some),
        };
        let Some(reference) = reference else {
            pruned.push(node.clone());
            continue;
        };
        if node_type == "thread" && reference == thread_id {
            changed = true;
            continue;
        }
        if node_type == "issue" && deleted_issue_ids.contains(&reference) {
            changed = true;
            continue;
        }
        pruned.push(node.clone());
    }
    if !changed {
        return None;
    }
    let mut lane_order: Vec<String> = Vec::new();
    let mut by_lane: HashMap<String, Vec<Value>> = HashMap::new();
    for node in &pruned {
        let lane = match node.get("lane_id") {
            None => String::new(),
            Some(Value::String(text)) => text.clone(),
            Some(other) => other.to_string(),
        };
        if !by_lane.contains_key(&lane) {
            lane_order.push(lane.clone());
        }
        by_lane.entry(lane).or_default().push(node.clone());
    }
    let mut normalized: Vec<Value> = Vec::new();
    for lane in lane_order {
        let mut lane_nodes = by_lane.remove(&lane).unwrap_or_default();
        lane_nodes.sort_by_key(|node| python_int(node.get("position")).unwrap_or(0));
        for (index, mut node) in lane_nodes.into_iter().enumerate() {
            if let Some(object) = node.as_object_mut() {
                object.insert("position".to_string(), json!(index as i64));
            }
            normalized.push(node);
        }
    }
    Some(normalized)
}

fn refused(error: &tokio_postgres::Error) -> ApiError {
    let message = error
        .as_db_error()
        .map(|db_error| db_error.message().to_string())
        .unwrap_or_else(|| error.to_string());
    ApiError::BadRequest(format!("Cannot delete thread: {message}"))
}

/// Integrity failures (class 23) become Python's "Cannot delete thread" 400.
fn delete_error(error: tokio_postgres::Error) -> ApiError {
    let integrity = error
        .code()
        .is_some_and(|code| code.code().starts_with("23"));
    if integrity {
        refused(&error)
    } else {
        db::tx_error(error)
    }
}

async fn delete_once(
    state: &AppState,
    user: AuthenticatedUser,
    thread_id: i64,
) -> Result<(), LifecycleError> {
    let user_id = user.id();
    with_tx!(state, tx, delete_error, {
        // Take the queue lock first to prevent deadlocks with concurrent shuffles.
        acquire_queue_lock(&tx, user_id).await?;
        let thread = find_owned(&tx, user_id, thread_id, false).await?;
        let id = thread.id;

        tx.execute(
            "UPDATE sessions SET pending_thread_id = NULL WHERE pending_thread_id = $1",
            &[&id],
        )
        .await
        .map_err(db::tx_error)?;

        let deleted_issue_ids: Vec<i32> = tx
            .query("SELECT id FROM issues WHERE thread_id = $1", &[&id])
            .await
            .map_err(db::tx_error)?
            .iter()
            .map(|row| row.get(0))
            .collect();
        let issue_set: HashSet<i64> = deleted_issue_ids.iter().map(|id| i64::from(*id)).collect();

        // Tag assignments carry polymorphic target ids with no foreign key.
        tx.execute(
            "DELETE FROM tag_assignments WHERE target_type = 'Thread' AND target_id = $1",
            &[&id],
        )
        .await
        .map_err(db::tx_error)?;
        if !deleted_issue_ids.is_empty() {
            tx.execute(
            "DELETE FROM tag_assignments WHERE target_type = 'Issue' AND target_id = ANY($1::int[])",
            &[&deleted_issue_ids],
        )
        .await
        .map_err(db::tx_error)?;
        }

        tx.execute(
            "DELETE FROM reading_order_items WHERE thread_id = $1",
            &[&id],
        )
        .await
        .map_err(db::tx_error)?;

        if !deleted_issue_ids.is_empty() {
            tx.execute(
                "DELETE FROM continuity_rules
                 WHERE user_id = $1 AND checkpoint_issue_id = ANY($2::int[])",
                &[&user_id, &deleted_issue_ids],
            )
            .await
            .map_err(delete_error)?;
        }

        // Remove the thread's existing events before recording the delete action
        // so deletion succeeds even when events.thread_id lacks ON DELETE CASCADE.
        tx.execute("DELETE FROM events WHERE thread_id = $1", &[&id])
            .await
            .map_err(delete_error)?;

        tx.execute(
        "INSERT INTO events (type, timestamp, user_id, thread_id) VALUES ('delete', NOW(), $1, NULL)",
        &[&user_id],
    )
    .await
    .map_err(db::tx_error)?;

        let plans = tx
            .query(
                "SELECT id, nodes_json FROM continuity_plans WHERE user_id = $1 ORDER BY id",
                &[&user_id],
            )
            .await
            .map_err(delete_error)?;
        for plan in plans {
            let plan_id: i32 = plan.get(0);
            let nodes_json: Option<Value> = plan.get(1);
            let original: Vec<Value> = match nodes_json {
                Some(Value::Array(items)) => items,
                _ => Vec::new(),
            };
            let Some(normalized) = prune_plan_nodes(&original, i64::from(id), &issue_set) else {
                continue;
            };
            let nodes_value = Value::Array(normalized.clone());
            tx.execute(
                "UPDATE continuity_plans SET nodes_json = $2 WHERE id = $1",
                &[&plan_id, &nodes_value],
            )
            .await
            .map_err(delete_error)?;
            let typed: Vec<ContinuityPlanNode> = normalized
                .iter()
                .map(|node| serde_json::from_value(node.clone()))
                .collect::<Result<_, _>>()
                .map_err(|error| ApiError::BadRequest(format!("Cannot delete thread: {error}")))?;
            crate::continuity_plans::rebuild_plan_membership(&tx, plan_id, &typed)
                .await
                .map_err(|error| match error {
                    ApiError::StructuredDetail { detail, .. } => {
                        ApiError::BadRequest(format!("Cannot delete thread: {detail}"))
                    }
                    other => other,
                })?;
            let marker = format!("continuity-plan:{plan_id}");
            if !deleted_issue_ids.is_empty() {
                tx.execute(
                    "DELETE FROM continuity_rules
                     WHERE user_id = $1 AND note = $2
                       AND ((source_type = 'issue' AND source_id = ANY($3::int[]))
                         OR (target_type = 'issue' AND target_id = ANY($3::int[])))",
                    &[&user_id, &marker, &deleted_issue_ids],
                )
                .await
                .map_err(delete_error)?;
            }
            if normalized.len() < 2 {
                tx.execute(
                    "DELETE FROM continuity_rules WHERE user_id = $1 AND note = $2",
                    &[&user_id, &marker],
                )
                .await
                .map_err(delete_error)?;
            }
        }
        if !deleted_issue_ids.is_empty() {
            tx.execute(
                "DELETE FROM continuity_rules
                 WHERE user_id = $1
                   AND ((source_type = 'issue' AND source_id = ANY($2::int[]))
                     OR (target_type = 'issue' AND target_id = ANY($2::int[])))",
                &[&user_id, &deleted_issue_ids],
            )
            .await
            .map_err(delete_error)?;
        }
        // Canonical blocked state comes only from Thread frontiers plus
        // canonical Dependency rows; refreshed before the thread disappears,
        // exactly like the Python writer.
        crate::issue_service::refresh_blocked_threads(&tx, user_id).await?;
        tx.execute("DELETE FROM threads WHERE id = $1", &[&id])
            .await
            .map_err(delete_error)?;
        renormalize(&tx, user_id).await?;
        Ok(())
    })
}

/// `DELETE /api/v1/threads/{thread_id}`
pub async fn delete_thread(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(raw_id): Path<String>,
) -> HandlerResult {
    let mut check = Check::default();
    let thread_id = path_int(&mut check, "thread_id", &raw_id);
    check.finish(Value::Null)?;
    delete_once(&state, user, thread_id.unwrap_or_default()).await?;
    Ok(StatusCode::NO_CONTENT.into_response())
}

// ---------------------------------------------------------------------------
// exclude / restore / reactivate
// ---------------------------------------------------------------------------

async fn exclude_once(
    state: &AppState,
    user: AuthenticatedUser,
    thread_id: i64,
) -> Result<i32, LifecycleError> {
    let user_id = user.id();
    with_tx!(state, tx, db::tx_error, {
        acquire_queue_lock(&tx, user_id).await?;
        let thread = find_owned(&tx, user_id, thread_id, true).await?;
        if thread.status == "excluded" {
            // Idempotent: removing an already-excluded series is a no-op.
            return Ok(thread.id);
        }
        if thread.status != "active" {
            return Err(ApiError::BadRequest(format!(
                "Thread {thread_id} is not active and cannot be excluded"
            ))
            .into());
        }
        tx.execute(
            "UPDATE threads SET status = 'excluded', queue_position = 0,
                queue_position_is_manual = false, queue_exclusion_group_id = NULL
         WHERE id = $1",
            &[&thread.id],
        )
        .await
        .map_err(db::tx_error)?;
        renormalize(&tx, user_id).await?;
        Ok(thread.id)
    })
}

/// `POST /api/v1/threads/{thread_id}/exclude`
pub async fn exclude_thread(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(raw_id): Path<String>,
) -> HandlerResult {
    let mut check = Check::default();
    let thread_id = path_int(&mut check, "thread_id", &raw_id);
    check.finish(Value::Null)?;
    let id = exclude_once(&state, user, thread_id.unwrap_or_default()).await?;
    respond_thread(&state, user, id, StatusCode::OK).await
}

async fn restore_once(
    state: &AppState,
    user: AuthenticatedUser,
    thread_id: i64,
) -> Result<i32, LifecycleError> {
    let user_id = user.id();
    with_tx!(state, tx, db::tx_error, {
        acquire_queue_lock(&tx, user_id).await?;
        let thread = find_owned(&tx, user_id, thread_id, true).await?;
        if thread.status != "excluded" {
            return Err(ApiError::BadRequest(format!("Thread {thread_id} is not excluded")).into());
        }
        let issues_remaining = if thread.total_issues.is_some() {
            // Re-derive the denormalized counters from the issue rows.
            let issues = tx
                .query(
                    "SELECT id, status FROM issues WHERE thread_id = $1 ORDER BY position, id",
                    &[&thread.id],
                )
                .await
                .map_err(db::tx_error)?;
            let total = issues.len() as i32;
            let unread: Vec<i32> = issues
                .iter()
                .filter(|row| row.get::<_, String>(1) == "unread")
                .map(|row| row.get(0))
                .collect();
            let remaining = unread.len() as i32;
            let progress = if remaining == 0 {
                "completed"
            } else if remaining == total {
                "not_started"
            } else {
                "in_progress"
            };
            let next_unread = unread.first().copied();
            tx.execute(
                "UPDATE threads SET total_issues = $2, issues_remaining = $3,
                    next_unread_issue_id = $4, reading_progress = $5,
                    is_blocked = CASE WHEN $3 = 0 THEN false ELSE is_blocked END
             WHERE id = $1",
                &[&thread.id, &total, &remaining, &next_unread, &progress],
            )
            .await
            .map_err(db::tx_error)?;
            remaining
        } else {
            thread.issues_remaining
        };
        let (status, position) = if issues_remaining > 0 {
            (
                "active",
                max_queue_position(&tx, user_id).await?.saturating_add(1),
            )
        } else {
            ("completed", 0)
        };
        tx.execute(
            "UPDATE threads SET status = $2, queue_position = $3,
                queue_position_is_manual = false, queue_exclusion_group_id = NULL
         WHERE id = $1",
            &[&thread.id, &status, &position],
        )
        .await
        .map_err(db::tx_error)?;
        if status == "active" {
            renormalize(&tx, user_id).await?;
        }
        Ok(thread.id)
    })
}

/// `POST /api/v1/threads/{thread_id}/restore`
pub async fn restore_thread(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(raw_id): Path<String>,
) -> HandlerResult {
    let mut check = Check::default();
    let thread_id = path_int(&mut check, "thread_id", &raw_id);
    check.finish(Value::Null)?;
    let id = restore_once(&state, user, thread_id.unwrap_or_default()).await?;
    respond_thread(&state, user, id, StatusCode::OK).await
}

async fn reactivate_once(
    state: &AppState,
    user: AuthenticatedUser,
    thread_id: i32,
    issues_to_add: i32,
) -> Result<i32, LifecycleError> {
    let user_id = user.id();
    with_tx!(state, tx, db::tx_error, {
        acquire_queue_lock(&tx, user_id).await?;
        let thread = find_owned(&tx, user_id, i64::from(thread_id), false).await?;
        if thread.status != "completed" {
            return Err(
                ApiError::BadRequest(format!("Thread {thread_id} is not completed")).into(),
            );
        }
        if issues_to_add <= 0 {
            return Err(ApiError::BadRequest("Must add at least 1 issue".to_string()).into());
        }
        tx.execute(
            "UPDATE threads SET queue_position = queue_position + 1
         WHERE user_id = $1 AND status = 'active'",
            &[&user_id],
        )
        .await
        .map_err(db::tx_error)?;
        if thread.total_issues.is_some() {
            let rows = tx
                .query(
                    "SELECT issue_number, position FROM issues WHERE thread_id = $1
                 ORDER BY position FOR UPDATE",
                    &[&thread.id],
                )
                .await
                .map_err(db::tx_error)?;
            let existing_total = rows.len() as i32;
            let max_position = rows
                .iter()
                .map(|row| row.get::<_, i32>(1))
                .max()
                .unwrap_or(0);
            let max_numeric = rows
                .iter()
                .filter_map(|row| {
                    let number: String = row.get(0);
                    (!number.is_empty() && number.chars().all(|c| c.is_ascii_digit()))
                        .then(|| number.parse::<i64>().ok())
                        .flatten()
                })
                .max()
                .unwrap_or(0);
            // Derive the new issue numbers and ordinals in SQL. No app-side
            // collection scales with `issues_to_add` (Greptile P1 security).
            let first_new: Option<i32> = tx
                .query_opt(
                    "WITH inserted AS (
                         INSERT INTO issues (thread_id, issue_number, status, position, created_at)
                         SELECT $1, ($3::bigint + s)::text, 'unread', ($4::bigint + s)::int, NOW()
                         FROM generate_series(1, $2::bigint) AS s
                         RETURNING id, position
                     )
                     SELECT id FROM inserted ORDER BY position LIMIT 1",
                    &[
                        &thread.id,
                        &i64::from(issues_to_add),
                        &max_numeric,
                        &i64::from(max_position),
                    ],
                )
                .await
                .map_err(db::tx_error)?
                .map(|row| row.get(0));
            let total = existing_total + issues_to_add;
            tx.execute(
                "UPDATE threads SET total_issues = $2, reading_progress = 'in_progress',
                    issues_remaining = $3,
                    next_unread_issue_id = COALESCE($4, next_unread_issue_id)
             WHERE id = $1",
                &[&thread.id, &total, &issues_to_add, &first_new],
            )
            .await
            .map_err(db::tx_error)?;
        } else {
            tx.execute(
                "UPDATE threads SET issues_remaining = $2 WHERE id = $1",
                &[&thread.id, &issues_to_add],
            )
            .await
            .map_err(db::tx_error)?;
        }
        tx.execute(
            "UPDATE threads SET status = 'active', queue_position = 1,
                queue_position_is_manual = false
         WHERE id = $1",
            &[&thread.id],
        )
        .await
        .map_err(db::tx_error)?;
        renormalize(&tx, user_id).await?;
        Ok(thread.id)
    })
}

/// `POST /api/v1/threads/reactivate`
pub async fn reactivate_thread(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    body: Bytes,
) -> HandlerResult {
    let map = require_object(parse_body(&body)?)?;
    let raw_body = Value::Object(map.clone());
    let mut check = Check::default();
    let thread_id = int_field(
        &mut check,
        &["body", "thread_id"],
        map.get("thread_id"),
        Bounds::default(),
        false,
        true,
    );
    let thread_id = to_i32(&mut check, &["body", "thread_id"], thread_id);
    let issues_to_add = int_field(
        &mut check,
        &["body", "issues_to_add"],
        map.get("issues_to_add"),
        Bounds {
            gt: Some(0),                 // Python's gt=0 check is mirrored for counts <= 0.
            le: Some(MAX_ISSUES_TO_ADD), // Coordinator-approved hardening cap.
            ..Bounds::default()
        },
        false,
        true,
    );
    let issues_to_add = to_i32(&mut check, &["body", "issues_to_add"], issues_to_add);
    check.finish(raw_body)?;
    let id = reactivate_once(
        &state,
        user,
        thread_id.unwrap_or_default(),
        issues_to_add.unwrap_or_default(),
    )
    .await?;
    respond_thread(&state, user, id, StatusCode::OK).await
}

// ---------------------------------------------------------------------------
// POST /api/v1/threads/{thread_id}/set-pending
// ---------------------------------------------------------------------------

fn parse_set_pending(body: Option<Value>) -> Result<Option<i32>, LifecycleError> {
    let Some(body) = body else {
        return Ok(None);
    };
    if body.is_null() {
        return Ok(None);
    }
    let Value::Object(map) = &body else {
        return Err(LifecycleError::Validation {
            errors: vec![json!({
                "field": "body",
                "message": "Input should be a valid dictionary or object to extract fields from",
                "type": "model_attributes_type",
            })],
            body,
        });
    };
    let mut check = Check::default();
    let value = int_field(
        &mut check,
        &["body", "expected_issue_id"],
        map.get("expected_issue_id"),
        Bounds {
            gt: Some(0),
            ..Bounds::default()
        },
        true,
        false,
    );
    let value = to_i32(&mut check, &["body", "expected_issue_id"], value);
    check.finish(body.clone())?;
    Ok(value)
}

struct SetPendingSelection {
    thread_id: i32,
    title: String,
    format: String,
    issues_remaining: i32,
    total_issues: Option<i32>,
    reading_progress: Option<String>,
    queue_position: i32,
    issue_id: Option<i32>,
    issue_number: Option<String>,
}

async fn validate_set_pending_selection(
    tx: &Transaction<'_>,
    user_id: i32,
    thread_id: i64,
    expected_issue_id: Option<i32>,
) -> Result<SetPendingSelection, LifecycleError> {
    let thread = find_owned(tx, user_id, thread_id, true).await?;
    if thread.status != "active" {
        return Err(ApiError::BadRequest(format!("Thread {thread_id} is not active")).into());
    }
    if thread.is_blocked {
        let reason = tx
            .query_opt(
                "SELECT DISTINCT st.id, st.title, si.id, si.issue_number
                 FROM threads tt
                 JOIN issues nu ON nu.id = tt.next_unread_issue_id
                 JOIN dependencies d ON d.target_issue_id = nu.id
                 JOIN issues si ON si.id = d.source_issue_id
                 JOIN threads st ON st.id = si.thread_id
                 WHERE tt.id = $1 AND tt.user_id = $2 AND st.user_id = $2
                   AND si.status <> 'read' AND nu.status <> 'read'
                   AND tt.next_unread_issue_id IS NOT NULL
                   AND (d.note IS NULL OR d.note NOT LIKE 'cbl-order:%')
                 ORDER BY st.id, st.title, si.id, si.issue_number
                 LIMIT 1",
                &[&thread.id, &user_id],
            )
            .await
            .map_err(db::tx_error)?
            .map(|row| {
                let title: String = row.get(1);
                let number: String = row.get(3);
                format!(": Blocked by {title}: #{number}")
            })
            .unwrap_or_default();
        return Err(ApiError::BadRequest(format!(
            "Thread {thread_id} is blocked by a dependency{reason}"
        ))
        .into());
    }
    let position_row = tx
        .query_opt(
            "SELECT pos FROM (
                 SELECT id, row_number() OVER (ORDER BY is_blocked, queue_position, id)::int AS pos
                 FROM threads
                 WHERE user_id = $1 AND status = 'active' AND queue_position >= 1) ranked
             WHERE id = $2",
            &[&user_id, &thread.id],
        )
        .await
        .map_err(db::tx_error)?;
    let queue_position: i32 = position_row.map(|row| row.get(0)).unwrap_or(0);

    let mut issue_id: Option<i32> = None;
    let mut issue_number: Option<String> = None;
    if thread.total_issues.is_some() {
        if let Some(next_id) = thread.next_unread_issue_id {
            if let Some(row) = tx
                .query_opt(
                    "SELECT id, issue_number FROM issues WHERE id = $1",
                    &[&next_id],
                )
                .await
                .map_err(db::tx_error)?
            {
                issue_id = Some(row.get(0));
                issue_number = Some(row.get(1));
            }
        }
    }
    if thread.issues_remaining <= 0 {
        return Err(
            ApiError::BadRequest(format!("Thread {thread_id} has no issues remaining")).into(),
        );
    }
    // A Reading Plan offers one exact Issue; never select its successor.
    if expected_issue_id.is_some() && issue_id != expected_issue_id {
        return Err(ApiError::Conflict(
            "This issue is no longer next and available. Refresh the reading plan and try again."
                .to_string(),
        )
        .into());
    }
    Ok(SetPendingSelection {
        thread_id: thread.id,
        title: thread.title.clone(),
        format: normalize_format_value(&thread.format),
        issues_remaining: thread.issues_remaining,
        total_issues: thread.total_issues,
        reading_progress: thread.reading_progress.clone(),
        queue_position,
        issue_id,
        issue_number,
    })
}

async fn set_pending_once(
    state: &AppState,
    user: AuthenticatedUser,
    thread_id: i64,
    expected_issue_id: Option<i32>,
) -> Result<RollResponse, LifecycleError> {
    let user_id = user.id();

    // Validate the offered selection before initializing the reading session so a
    // rejected request (notably a stale expected_issue_id 409) does not commit a
    // session-start undo checkpoint like Python's pre-get_or_create checks.
    with_tx!(state, tx, db::tx_error, {
        validate_set_pending_selection(&tx, user_id, thread_id, expected_issue_id).await?;
        Ok::<_, LifecycleError>(())
    })?;

    let active = reading_session::initialize(state, user, None, SessionPolicy::default()).await?;

    with_tx!(state, tx, db::tx_error, {
        let selection =
            validate_set_pending_selection(&tx, user_id, thread_id, expected_issue_id).await?;

        let session = tx
            .query_opt(
                "SELECT snoozed_thread_ids::text FROM sessions
             WHERE id = $1 AND user_id = $2 FOR UPDATE",
                &[&active.session.id, &user_id],
            )
            .await
            .map_err(db::tx_error)?
            .ok_or_else(|| ApiError::Conflict("Reading session changed; try again".to_string()))?;
        let snoozed_raw: Option<String> = session.get(0);
        let mut snoozed_ids = reading_session::decode_thread_ids(snoozed_raw)?.unwrap_or_default();
        if snoozed_ids.contains(&selection.thread_id) {
            // Manual selection clears a current-session snooze; record the
            // unsnooze so historical replay sees the boundary (#4209).
            tx.execute(
                "INSERT INTO events (type, timestamp, user_id, session_id, thread_id)
             VALUES ('unsnooze', NOW(), $1, $2, $3)",
                &[&user_id, &active.session.id, &selection.thread_id],
            )
            .await
            .map_err(db::tx_error)?;
        }
        let mut offset = snoozed_ids.len() as i32;
        let mut snoozed_count = offset;
        tx.execute(
            "INSERT INTO events (type, timestamp, user_id, session_id, selected_thread_id, die,
                             result, selection_method, issue_id, issue_number)
         VALUES ('roll', NOW(), $1, $2, $3, $4, 0, 'manual', $5, $6)",
            &[
                &user_id,
                &active.session.id,
                &selection.thread_id,
                &active.current_die,
                &selection.issue_id,
                &selection.issue_number,
            ],
        )
        .await
        .map_err(db::tx_error)?;
        // A manual selection retargets the pending pair: an issue pinned to a
        // different thread is superseded, never carried over (#3225).
        tx.execute(
            "UPDATE sessions SET pending_thread_id = $1, pending_thread_updated_at = NOW(),
                pending_issue_id = CASE
                    WHEN pending_issue_id IS NULL THEN NULL
                    WHEN EXISTS (SELECT 1 FROM issues i
                                 WHERE i.id = sessions.pending_issue_id AND i.thread_id = $1)
                        THEN pending_issue_id
                    ELSE NULL END
         WHERE id = $2 AND user_id = $3",
            &[&selection.thread_id, &active.session.id, &user_id],
        )
        .await
        .map_err(db::tx_error)?;
        if let Some(index) = snoozed_ids.iter().position(|id| *id == selection.thread_id) {
            snoozed_ids.remove(index);
            let encoded = serde_json::to_string(&snoozed_ids)
                .map_err(|_| ApiError::Internal("Internal Server Error".to_string()))?;
            tx.execute(
            "UPDATE sessions SET snoozed_thread_ids = $1::text::json WHERE id = $2 AND user_id = $3",
            &[&encoded, &active.session.id, &user_id],
        )
        .await
        .map_err(db::tx_error)?;
            offset = snoozed_ids.len() as i32;
            snoozed_count = offset;
        }
        Ok(RollResponse {
            thread_id: selection.thread_id,
            title: selection.title,
            format: selection.format,
            issues_remaining: selection.issues_remaining,
            queue_position: selection.queue_position,
            die_size: active.current_die,
            result: 0,
            offset,
            snoozed_count,
            issue_id: selection.issue_id,
            issue_number: selection.issue_number.clone(),
            next_issue_id: selection.issue_id,
            next_issue_number: selection.issue_number,
            total_issues: selection.total_issues,
            reading_progress: selection.reading_progress,
            explanation: None,
        })
    })
}

/// `POST /api/v1/threads/{thread_id}/set-pending`
pub async fn set_pending_thread(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(raw_id): Path<String>,
    body: Bytes,
) -> HandlerResult {
    let mut check = Check::default();
    let thread_id = path_int(&mut check, "thread_id", &raw_id);
    let parsed = parse_body(&body)?;
    let expected = match parse_set_pending(parsed) {
        Ok(value) => value,
        Err(LifecycleError::Validation { errors, body }) => {
            let mut combined = check_errors(&check);
            combined.extend(errors);
            return Err(LifecycleError::Validation {
                errors: combined,
                body,
            });
        }
        Err(other) => return Err(other),
    };
    check.finish(Value::Null)?;
    reject_option_e_preview(&state)?;
    let response = set_pending_once(&state, user, thread_id.unwrap_or_default(), expected).await?;
    Ok(json_response(StatusCode::OK, response))
}

// ---------------------------------------------------------------------------
// PUT /api/v1/threads/{thread_id}/test-backdate
// ---------------------------------------------------------------------------

fn test_environment_enabled() -> bool {
    std::env::var_os("TEST_ENVIRONMENT").is_some_and(|value| !value.is_empty())
}

/// `PUT /api/v1/threads/{thread_id}/test-backdate`
pub async fn backdate_thread_for_testing(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(raw_id): Path<String>,
    RawQuery(raw): RawQuery,
) -> HandlerResult {
    let mut check = Check::default();
    let thread_id = path_int(&mut check, "thread_id", &raw_id);
    let pairs = query_pairs(raw.as_deref());
    let days_param = query_value(&pairs, "days_ago");
    let days_param_value = days_param.map(Value::String);
    let days_ago = int_field(
        &mut check,
        &["query", "days_ago"],
        days_param_value.as_ref(),
        Bounds {
            ge: Some(1),
            le: Some(3650),
            ..Bounds::default()
        },
        false,
        true,
    );
    check.finish(Value::Null)?;

    if !test_environment_enabled() {
        return Err(LifecycleError::Api(ApiError::Forbidden(
            "This endpoint is only available in test environment".to_string(),
        )));
    }

    let user_id = user.id();
    let thread_id = thread_id.unwrap_or_default();
    let days_ago = days_ago.unwrap_or_default();
    let updated_id = with_tx!(&state, tx, db::tx_error, {
        // Match every sibling lifecycle writer: take the per-reader queue
        // advisory lock before the thread row lock (`find_owned(.., true)`),
        // never the reverse (#5398/#5419 lock-order rule).
        acquire_queue_lock(&tx, user_id).await?;
        let thread = find_owned(&tx, user_id, thread_id, true).await?;
        tx.execute(
            "UPDATE threads SET last_activity_at = NOW() - ($2::bigint * INTERVAL '1 day')
             WHERE id = $1",
            &[&thread.id, &days_ago],
        )
        .await
        .map_err(db::tx_error)?;
        Ok(thread.id)
    })?;
    respond_thread(&state, user, updated_id, StatusCode::OK).await
}

// ---------------------------------------------------------------------------
// GET /api/v1/threads/stale
// ---------------------------------------------------------------------------

/// `GET /api/v1/threads/stale`
pub async fn list_stale_threads(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    RawQuery(raw): RawQuery,
) -> HandlerResult {
    let pairs = query_pairs(raw.as_deref());
    let mut check = Check::default();
    let days = match query_value(&pairs, "days") {
        None => Some(30),
        Some(text) => {
            let value = Value::String(text);
            match crate::thread_validation::coerce_int(&value) {
                IntOutcome::Value(days) => Some(days),
                IntOutcome::Invalid(kind, message) => {
                    check.push(&["query", "days"], kind, message);
                    None
                }
            }
        }
    };
    let page_size = match query_value(&pairs, "page_size") {
        None => Some(200),
        Some(text) => int_field(
            &mut check,
            &["query", "page_size"],
            Some(&Value::String(text)),
            Bounds {
                ge: Some(1),
                le: Some(200),
                ..Bounds::default()
            },
            false,
            false,
        ),
    };
    check.finish(Value::Null)?;
    reject_option_e_preview(&state)?;
    let days = days.unwrap_or(30);
    let page_size = page_size.unwrap_or(200);
    let user_id = user.id();
    let views = with_tx!(&state, tx, db::tx_error, {
        let session = tx
            .query_opt(
                "SELECT snoozed_thread_ids::text FROM sessions
             WHERE user_id = $1 AND ended_at IS NULL
             ORDER BY started_at DESC, id DESC LIMIT 1",
                &[&user_id],
            )
            .await
            .map_err(db::tx_error)?;
        let current: Vec<i32> = match session {
            Some(row) => reading_session::decode_thread_ids(row.get::<_, Option<String>>(0))?
                .unwrap_or_default(),
            None => Vec::new(),
        };
        let derived = roll_exclusions::durable_snoozed(&tx, user_id).await?;
        let mut snoozed: Vec<i32> = current.into_iter().chain(derived).collect();
        snoozed.sort_unstable();
        snoozed.dedup();
        let ids: Vec<i32> = tx
            .query(
                "SELECT id FROM threads
             WHERE user_id = $1 AND status = 'active' AND is_blocked = false
               AND (last_activity_at < NOW() - make_interval(days => $2::int)
                    OR last_activity_at IS NULL)
               AND NOT (id = ANY($3::int[]))
             ORDER BY last_activity_at ASC NULLS FIRST, id
             LIMIT $4",
                &[&user_id, &(days as i32), &snoozed, &page_size],
            )
            .await
            .map_err(db::tx_error)?
            .iter()
            .map(|row| row.get(0))
            .collect();
        Ok(load_views(&*tx, user_id, &ids, None).await?)
    })?;
    Ok(json_response(StatusCode::OK, views))
}

// ---------------------------------------------------------------------------
// GET /api/v1/threads/excluded/threads
// ---------------------------------------------------------------------------

/// `GET /api/v1/threads/excluded/threads`
pub async fn list_excluded_threads(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
    RawQuery(raw): RawQuery,
) -> HandlerResult {
    let pairs = query_pairs(raw.as_deref());
    let mut check = Check::default();
    let search = str_field(
        &mut check,
        &["query", "search"],
        query_value(&pairs, "search").map(Value::String).as_ref(),
        StrRules {
            min: Some(1),
            max: None,
        },
        true,
        false,
    );
    let sort = query_value(&pairs, "sort").unwrap_or_else(|| "created".to_string());
    let page_size = match query_value(&pairs, "page_size") {
        None => Some(50),
        Some(text) => int_field(
            &mut check,
            &["query", "page_size"],
            Some(&Value::String(text)),
            Bounds {
                ge: Some(1),
                le: Some(200),
                ..Bounds::default()
            },
            false,
            false,
        ),
    };
    let page_token = query_value(&pairs, "page_token");
    check.finish(Value::Null)?;
    if !matches!(sort.as_str(), "position" | "title" | "created") {
        return Err(ApiError::BadRequest(
            "sort must be one of: position, title, created".to_string(),
        )
        .into());
    }
    let response = threads::list_excluded_page(
        &state,
        &claims,
        search.as_deref(),
        &sort,
        page_size.unwrap_or(50),
        page_token.as_deref(),
    )
    .await?;
    Ok(response.into_response())
}

// ---------------------------------------------------------------------------
// POST /api/v1/threads/check-duplicates
// ---------------------------------------------------------------------------

/// Mirror `normalize_title`: casefolded alphanumeric tokens, single spaced.
fn normalize_title(title: &str) -> String {
    let folded: String = title.case_fold().collect();
    let cleaned: String = folded
        .chars()
        .map(|c| if c.is_alphanumeric() { c } else { ' ' })
        .collect();
    cleaned.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Mirror `significant_title_tokens`.
fn significant_title_tokens(normalized: &str) -> Vec<String> {
    let mut tokens: Vec<String> = Vec::new();
    for token in normalized.split_whitespace() {
        if !tokens.iter().any(|existing| existing == token) {
            tokens.push(token.to_string());
        }
    }
    let significant: Vec<String> = tokens
        .iter()
        .filter(|token| token.chars().count() >= 3)
        .cloned()
        .collect();
    if significant.is_empty() {
        return tokens.into_iter().take(6).collect();
    }
    let mut ordered = significant;
    // Python `sorted(..., key=len, reverse=True)` is stable.
    ordered.sort_by_key(|token| std::cmp::Reverse(token.chars().count()));
    ordered.into_iter().take(6).collect()
}

/// Mirror `title_similarity`.
fn title_similarity(proposed: &str, existing: &str) -> f64 {
    let proposed_normalized = normalize_title(proposed);
    let existing_normalized = normalize_title(existing);
    if proposed_normalized.is_empty() || existing_normalized.is_empty() {
        return 0.0;
    }
    if proposed_normalized == existing_normalized {
        return 1.0;
    }
    if format!(" {existing_normalized} ").contains(&format!(" {proposed_normalized} "))
        || format!(" {proposed_normalized} ").contains(&format!(" {existing_normalized} "))
    {
        return 0.8;
    }
    let proposed_tokens: HashSet<&str> = proposed_normalized.split_whitespace().collect();
    let existing_tokens: HashSet<&str> = existing_normalized.split_whitespace().collect();
    let union = proposed_tokens.union(&existing_tokens).count();
    if union == 0 {
        return 0.0;
    }
    proposed_tokens.intersection(&existing_tokens).count() as f64 / union as f64
}

fn coerce_publication_year(value: Option<&Value>) -> Option<i32> {
    let year = match value? {
        Value::Bool(_) => return None,
        Value::Number(number) => number.as_i64()?,
        Value::String(text) => {
            let trimmed = text.trim();
            if trimmed.len() == 4 && trimmed.chars().all(|c| c.is_ascii_digit()) {
                trimmed.parse::<i64>().ok()?
            } else {
                return None;
            }
        }
        _ => return None,
    };
    (1000..=9999).contains(&year).then_some(year as i32)
}

/// Mirror `publication_year_from_metadata` (`(19|20)\d{2}` in cover/store date).
fn publication_year_from_metadata(metadata: &serde_json::Map<String, Value>) -> Option<i32> {
    for field in ["cover_date", "store_date"] {
        let Some(text) = metadata.get(field).and_then(Value::as_str) else {
            continue;
        };
        let chars: Vec<char> = text.chars().collect();
        for window in chars.windows(4) {
            if window.iter().all(char::is_ascii_digit) {
                let candidate: String = window.iter().collect();
                if candidate.starts_with("19") || candidate.starts_with("20") {
                    return candidate.parse().ok();
                }
            }
        }
    }
    None
}

struct Candidate {
    id: i32,
    title: String,
    format: String,
    status: String,
    issues_remaining: i32,
    total_issues: Option<i32>,
}

fn candidate(row: &tokio_postgres::Row) -> Candidate {
    Candidate {
        id: row.get(0),
        title: row.get(1),
        format: row.get(2),
        status: row.get(3),
        issues_remaining: row.get(4),
        total_issues: row.get(5),
    }
}

const CANDIDATE_COLUMNS: &str =
    "t.id, t.title, t.format, t.status, t.issues_remaining, t.total_issues";

/// `POST /api/v1/threads/check-duplicates`
pub async fn check_potential_duplicates(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    body: Bytes,
) -> HandlerResult {
    let map = require_object(parse_body(&body)?)?;
    let raw_body = Value::Object(map.clone());
    let mut check = Check::default();
    let title = str_field(
        &mut check,
        &["body", "title"],
        map.get("title"),
        StrRules {
            min: Some(1),
            max: Some(200),
        },
        false,
        true,
    );
    let format_value = str_field(
        &mut check,
        &["body", "format"],
        map.get("format"),
        StrRules {
            min: Some(1),
            max: Some(50),
        },
        false,
        true,
    );
    let volume = int_field(
        &mut check,
        &["body", "comicvine_volume_id"],
        map.get("comicvine_volume_id"),
        Bounds {
            gt: Some(0),
            ..Bounds::default()
        },
        true,
        false,
    );
    let exclude = int_field(
        &mut check,
        &["body", "exclude_thread_id"],
        map.get("exclude_thread_id"),
        Bounds {
            gt: Some(0),
            ..Bounds::default()
        },
        true,
        false,
    );
    let exclude = to_i32(&mut check, &["body", "exclude_thread_id"], exclude);
    check.finish(raw_body)?;
    let title = title.unwrap_or_default();
    let format_value = format_value.unwrap_or_default();
    let user_id = user.id();

    let connection = db::checkout(&state).await?;
    let mut strong: Vec<Candidate> = Vec::new();
    if let Some(volume_id) = volume {
        let rows = connection
            .query(
                &format!(
                    "SELECT {CANDIDATE_COLUMNS}
                     FROM threads t
                     JOIN thread_external_series_mappings m ON t.id = m.thread_id
                     JOIN external_identities e ON e.id = m.external_identity_id
                     WHERE t.user_id = $1 AND m.status = 'confirmed'
                       AND e.provider = 'comicvine' AND e.entity_type = 'series'
                       AND e.external_id = $2
                       AND ($3::int IS NULL OR t.id <> $3)
                     ORDER BY t.id"
                ),
                &[&user_id, &volume_id.to_string(), &exclude],
            )
            .await
            .map_err(db::query_error)?;
        strong = rows.iter().map(candidate).collect();
    }

    let normalized_format = normalize_format_value(&format_value);
    let strong_ids: HashSet<i32> = strong.iter().map(|thread| thread.id).collect();
    let normalized_title = normalize_title(&title);
    let mut similar: Vec<Candidate> = Vec::new();
    if !normalized_title.is_empty() {
        let tokens = significant_title_tokens(&normalized_title);
        let terms: Vec<String> = if tokens.is_empty() {
            vec![normalized_title.clone()]
        } else {
            tokens
        };
        // `lower(title)` contains each token literally (SQLAlchemy
        // `contains(..., autoescape=True)`), so use `strpos`, which has no
        // wildcard syntax to escape.
        let complete = connection
            .query(
                &format!(
                    "SELECT {CANDIDATE_COLUMNS} FROM threads t
                     WHERE t.user_id = $1 AND ($2::int IS NULL OR t.id <> $2)
                       AND NOT EXISTS (SELECT 1 FROM unnest($3::text[]) AS term
                                       WHERE strpos(lower(t.title), term) = 0)
                     ORDER BY t.id"
                ),
                &[&user_id, &exclude, &terms],
            )
            .await
            .map_err(db::query_error)?;
        let complete: Vec<Candidate> = complete.iter().map(candidate).collect();
        let complete_ids: Vec<i32> = complete.iter().map(|thread| thread.id).collect();
        let fuzzy = connection
            .query(
                &format!(
                    "SELECT {CANDIDATE_COLUMNS} FROM threads t
                     WHERE t.user_id = $1 AND ($2::int IS NULL OR t.id <> $2)
                       AND EXISTS (SELECT 1 FROM unnest($3::text[]) AS term
                                   WHERE strpos(lower(t.title), term) > 0)
                       AND NOT (t.id = ANY($4::int[]))
                     ORDER BY t.id LIMIT 25"
                ),
                &[&user_id, &exclude, &terms, &complete_ids],
            )
            .await
            .map_err(db::query_error)?;
        similar.extend(complete);
        similar.extend(fuzzy.iter().map(candidate));
    }
    let mut considered: Vec<(f64, bool, Candidate)> = similar
        .into_iter()
        .filter(|thread| !strong_ids.contains(&thread.id))
        .filter_map(|thread| {
            let similarity = title_similarity(&title, &thread.title);
            (similarity >= MIN_TITLE_SIMILARITY).then(|| {
                let same_format = normalize_format_value(&thread.format) == normalized_format;
                (similarity, same_format, thread)
            })
        })
        .collect();
    considered.sort_by(|left, right| {
        right
            .0
            .partial_cmp(&left.0)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| (!left.1).cmp(&(!right.1)))
            .then_with(|| left.2.id.cmp(&right.2.id))
    });
    let remaining_slots = MAX_POTENTIAL_DUPLICATE_MATCHES.saturating_sub(strong.len());
    let mut candidates: Vec<(Candidate, &'static str)> = strong
        .into_iter()
        .map(|thread| (thread, "same_comicvine_volume"))
        .collect();
    candidates.extend(
        considered
            .into_iter()
            .take(remaining_slots)
            .map(|(_, _, thread)| (thread, "similar_title")),
    );

    let ids: Vec<i32> = candidates.iter().map(|(thread, _)| thread.id).collect();
    let mut series: HashMap<i32, (Option<i64>, Value)> = HashMap::new();
    let mut unread: HashMap<i32, i32> = HashMap::new();
    if !ids.is_empty() {
        let rows = connection
            .query(
                "SELECT m.thread_id, e.external_id, e.metadata_json
                 FROM thread_external_series_mappings m
                 JOIN external_identities e ON e.id = m.external_identity_id
                 JOIN threads t ON t.id = m.thread_id
                 WHERE t.user_id = $1 AND t.id = ANY($2::int[])
                   AND m.status = 'confirmed'
                   AND e.provider = 'comicvine' AND e.entity_type = 'series'
                 ORDER BY m.thread_id, m.id",
                &[&user_id, &ids],
            )
            .await
            .map_err(db::query_error)?;
        for row in rows {
            let thread_id: i32 = row.get(0);
            if series.contains_key(&thread_id) {
                continue;
            }
            let external_id: String = row.get(1);
            let volume_id = (!external_id.is_empty()
                && external_id.chars().all(|c| c.is_ascii_digit()))
            .then(|| external_id.parse::<i64>().ok())
            .flatten();
            let metadata: Option<Value> = row.get(2);
            series.insert(thread_id, (volume_id, metadata.unwrap_or(Value::Null)));
        }
        let tracked: Vec<i32> = candidates
            .iter()
            .filter(|(thread, _)| thread.total_issues.is_some())
            .map(|(thread, _)| thread.id)
            .collect();
        if !tracked.is_empty() {
            let rows = connection
                .query(
                    "SELECT thread_id, count(*)::int FROM issues
                     WHERE thread_id = ANY($1::int[]) AND status = 'unread'
                     GROUP BY thread_id",
                    &[&tracked],
                )
                .await
                .map_err(db::query_error)?;
            unread = rows.iter().map(|row| (row.get(0), row.get(1))).collect();
        }
    }
    drop(connection);

    let matches = candidates
        .into_iter()
        .map(|(thread, match_type)| {
            let (volume_id, metadata) = series
                .get(&thread.id)
                .cloned()
                .unwrap_or((None, Value::Null));
            let empty = serde_json::Map::new();
            let metadata = metadata.as_object().unwrap_or(&empty);
            let start_year = coerce_publication_year(metadata.get("start_year"))
                .or_else(|| publication_year_from_metadata(metadata));
            PotentialDuplicateMatch {
                thread_id: thread.id,
                title: thread.title.clone(),
                format: normalize_format_value(&thread.format),
                status: thread.status.clone(),
                issues_remaining: if thread.total_issues.is_some() {
                    unread.get(&thread.id).copied().unwrap_or(0)
                } else {
                    thread.issues_remaining
                },
                total_issues: thread.total_issues,
                comicvine_volume_id: volume_id,
                start_year,
                match_type: match_type.to_string(),
            }
        })
        .collect();
    Ok(json_response(
        StatusCode::OK,
        CheckDuplicatesResponse { matches },
    ))
}

// ---------------------------------------------------------------------------
// POST /api/v1/threads/groups:batch
// ---------------------------------------------------------------------------

/// `POST /api/v1/threads/groups:batch`
pub async fn list_thread_groups_batch(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    body: Bytes,
) -> HandlerResult {
    let map = require_object(parse_body(&body)?)?;
    let raw_body = Value::Object(map.clone());
    let mut check = Check::default();
    let mut thread_ids: Vec<i32> = Vec::new();
    match map.get("thread_ids") {
        None => check.push(&["body", "thread_ids"], "missing", "Field required"),
        Some(Value::Array(items)) => {
            if items.is_empty() {
                check.push(
                    &["body", "thread_ids"],
                    "too_short",
                    "List should have at least 1 item after validation, not 0",
                );
            } else if items.len() > MAX_BATCH_THREADS {
                check.push(
                    &["body", "thread_ids"],
                    "too_long",
                    format!(
                        "List should have at most {MAX_BATCH_THREADS} items after validation, not {}",
                        items.len()
                    ),
                );
            }
            for (index, item) in items.iter().enumerate() {
                match crate::thread_validation::coerce_int(item) {
                    IntOutcome::Value(value) => match i32::try_from(value) {
                        Ok(value) => thread_ids.push(value),
                        Err(_) => check.push_indexed(
                            &["body", "thread_ids"],
                            index,
                            "int_parsing",
                            "Input should be a valid 32-bit integer",
                        ),
                    },
                    IntOutcome::Invalid(kind, message) => {
                        check.push_indexed(&["body", "thread_ids"], index, kind, &message)
                    }
                }
            }
        }
        Some(_) => check.push(
            &["body", "thread_ids"],
            "list_type",
            "Input should be a valid list",
        ),
    }
    check.finish(raw_body)?;

    let mut ordered: Vec<i32> = Vec::new();
    for id in thread_ids {
        if !ordered.contains(&id) {
            ordered.push(id);
        }
    }
    let user_id = user.id();
    let connection = db::checkout(&state).await?;
    let owned: HashSet<i32> = connection
        .query(
            "SELECT id FROM threads WHERE id = ANY($1::int[]) AND user_id = $2",
            &[&ordered, &user_id],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| row.get(0))
        .collect();
    if let Some(missing) = ordered.iter().find(|id| !owned.contains(id)) {
        return Err(not_found(i64::from(*missing)).into());
    }
    let rows = connection
        .query(
            "SELECT DISTINCT g.id, g.name, x.thread_id
             FROM (
                 SELECT group_id, thread_id FROM dependency_group_memberships
                 WHERE thread_id = ANY($1::int[])
                 UNION ALL
                 SELECT m.group_id, i.thread_id FROM dependency_group_memberships m
                 JOIN issues i ON i.id = m.issue_id
                 WHERE i.thread_id = ANY($1::int[])
             ) x
             JOIN dependency_groups g ON g.id = x.group_id
             WHERE g.user_id = $2
             ORDER BY g.name, g.id",
            &[&ordered, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    drop(connection);
    let mut grouped: BTreeMap<i32, Vec<DependencyGroupSummary>> = BTreeMap::new();
    let mut seen: HashSet<(i32, i32)> = HashSet::new();
    for row in rows {
        let group_id: i32 = row.get(0);
        let thread_id: i32 = row.get(2);
        if !seen.insert((thread_id, group_id)) {
            continue;
        }
        grouped
            .entry(thread_id)
            .or_default()
            .push(DependencyGroupSummary {
                id: group_id,
                name: row.get(1),
            });
    }
    let payload = GroupsByThread(
        ordered
            .into_iter()
            .map(|id| (id, grouped.remove(&id).unwrap_or_default()))
            .collect(),
    );
    Ok(json_response(StatusCode::OK, payload))
}

// ---------------------------------------------------------------------------
// OpenAPI documentation-only operations
// ---------------------------------------------------------------------------

#[utoipa::path(
    post,
    path = "/api/v1/threads/",
    tag = "threads",
    description = "Create a thread at the end of the reader's queue.",
    request_body = ThreadCreateRequest,
    responses(
        (status = 201, description = "Created (or the duplicate created seconds earlier)", body = ThreadResponse),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn create_thread_documentation() {}

#[utoipa::path(
    put,
    path = "/api/v1/threads/{thread_id}",
    tag = "threads",
    description = "Update an owned thread.",
    params(("thread_id" = i32, Path, description = "Owned thread identifier")),
    request_body = ThreadUpdateRequest,
    responses(
        (status = 200, description = "Updated thread", body = ThreadResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn update_thread_documentation() {}

#[utoipa::path(
    delete,
    path = "/api/v1/threads/{thread_id}",
    tag = "threads",
    description = "Delete a thread and prune dependent session and continuity state.",
    params(("thread_id" = i32, Path, description = "Owned thread identifier")),
    responses(
        (status = 204, description = "Deleted"),
        (status = 400, description = "The database refused the deletion"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn delete_thread_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/threads/{thread_id}/exclude",
    tag = "threads",
    description = "Remove an active thread from the queue without deleting data.",
    params(("thread_id" = i32, Path, description = "Owned thread identifier")),
    responses(
        (status = 200, description = "Excluded thread", body = ThreadResponse),
        (status = 400, description = "Thread is not active"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn exclude_thread_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/threads/{thread_id}/restore",
    tag = "threads",
    description = "Restore an excluded thread to the queue (or the finished shelf).",
    params(("thread_id" = i32, Path, description = "Owned thread identifier")),
    responses(
        (status = 200, description = "Restored thread", body = ThreadResponse),
        (status = 400, description = "Thread is not excluded"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn restore_thread_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/threads/reactivate",
    tag = "threads",
    description = "Reactivate a completed thread by adding more issues.",
    request_body = ReactivateRequest,
    responses(
        (status = 200, description = "Reactivated thread", body = ThreadResponse),
        (status = 400, description = "Thread is not completed"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn reactivate_thread_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/threads/{thread_id}/set-pending",
    tag = "threads",
    description = "Manually select a thread as the pending roll.",
    params(("thread_id" = i32, Path, description = "Owned thread identifier")),
    request_body(content = Option<SetPendingRequest>, description = "Optional exact-issue guard"),
    responses(
        (status = 200, description = "Selected thread", body = RollResponse),
        (status = 400, description = "Thread is inactive, blocked or out of issues"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 409, description = "The offered issue is no longer next"),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn set_pending_thread_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v1/threads/stale",
    tag = "threads",
    description = "List active threads not read in `days` days.",
    params(
        ("days" = Option<i32>, Query, description = "Staleness threshold in days (default 30)"),
        ("page_size" = Option<i32>, Query, description = "Maximum results (1-200, default 200)")
    ),
    responses(
        (status = 200, description = "Stale threads, oldest activity first", body = [ThreadResponse]),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_stale_threads_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v1/threads/excluded/threads",
    tag = "threads",
    description = "List the reader's excluded threads with cursor pagination.",
    params(
        ("search" = Option<String>, Query, description = "Case-insensitive title filter"),
        ("sort" = Option<String>, Query, description = "position, title or created (default created)"),
        ("page_size" = Option<i32>, Query, description = "Page size (1-200, default 50)"),
        ("page_token" = Option<String>, Query, description = "Opaque continuation cursor")
    ),
    responses(
        (status = 200, description = "Excluded thread page", body = threads::ThreadListResponse),
        (status = 400, description = "Unsupported sort or stale page token"),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_excluded_threads_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/threads/check-duplicates",
    tag = "threads",
    description = "Advisory check for existing volumes that may be the proposed series.",
    request_body = CheckDuplicatesRequest,
    responses(
        (status = 200, description = "Possible existing volumes", body = CheckDuplicatesResponse),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn check_potential_duplicates_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/threads/groups:batch",
    tag = "threads",
    description = "List crossover groups for several owned threads in one request.",
    request_body = GroupsBatchRequest,
    responses(
        (status = 200, description = "Map of thread id to crossover groups", body = HashMap<String, Vec<DependencyGroupSummary>>),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "A requested thread is not owned by the reader"),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_thread_groups_batch_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn title_similarity_matches_python_ladder() {
        assert_eq!(title_similarity("Spider-Man", "spider man"), 1.0);
        assert_eq!(title_similarity("Batman", "The Batman Adventures"), 0.8);
        assert_eq!(title_similarity("", "x"), 0.0);
        let jaccard = title_similarity("alpha beta gamma", "alpha beta delta");
        assert!((jaccard - 0.5).abs() < f64::EPSILON);
    }

    #[test]
    fn significant_tokens_prefer_long_unique_tokens() {
        assert_eq!(
            significant_title_tokens("x men x the uncanny"),
            vec!["uncanny", "men", "the"]
        );
        assert_eq!(significant_title_tokens("x y"), vec!["x", "y"]);
    }

    #[test]
    fn creator_credits_are_bounded_and_deduplicated() {
        let raw = vec![
            json!({"name": "  Jane   Doe ", "roles": ["Writer", "Writer", " Artist ", 3]}),
            json!({"name": "   "}),
            json!("nope"),
            json!({"name": 5}),
        ];
        assert_eq!(
            normalize_manual_creator_credits(&raw),
            json!([{"name": "Jane Doe", "roles": ["Writer", "Artist"]}])
        );
    }

    #[test]
    fn notes_normalize_blank_to_none_and_keep_whitespace_inside() {
        assert_eq!(normalize_notes_value(Some("   ")), None);
        assert_eq!(normalize_notes_value(None), None);
        assert_eq!(
            normalize_notes_value(Some(" a \n b ")).as_deref(),
            Some(" a \n b ")
        );
    }

    #[test]
    fn format_normalization_mirrors_python() {
        assert_eq!(normalize_format_value(" comics "), "Comic");
        assert_eq!(normalize_format_value("DIGITAL"), "Digital");
        assert_eq!(normalize_format_value(" Trade "), "Trade");
    }

    #[test]
    fn publication_year_prefers_start_year_then_dates() {
        assert_eq!(coerce_publication_year(Some(&json!("1999"))), Some(1999));
        assert_eq!(coerce_publication_year(Some(&json!(true))), None);
        assert_eq!(coerce_publication_year(Some(&json!(999))), None);
        let metadata = json!({"cover_date": "x 2011-05-01", "store_date": "1990"});
        assert_eq!(
            publication_year_from_metadata(metadata.as_object().unwrap()),
            Some(2011)
        );
    }

    #[test]
    fn plan_pruning_renumbers_lanes_and_reports_changes() {
        let nodes = vec![
            json!({"id": "a", "node_type": "thread", "ref_id": 7, "lane_id": "L", "position": 0}),
            json!({"id": "b", "node_type": "issue", "ref_id": 11, "lane_id": "L", "position": 1}),
            json!({"id": "c", "node_type": "issue", "ref_id": 12, "lane_id": "L", "position": 2}),
            json!({"id": "d", "node_type": "issue", "ref_id": "bad", "lane_id": "M", "position": 5}),
        ];
        let issues: HashSet<i64> = [11].into_iter().collect();
        let pruned = prune_plan_nodes(&nodes, 7, &issues).unwrap();
        let ids: Vec<&str> = pruned.iter().map(|n| n["id"].as_str().unwrap()).collect();
        assert_eq!(ids, vec!["c", "d"]);
        assert_eq!(pruned[0]["position"], 0);
        assert_eq!(pruned[1]["position"], 0);
        assert!(prune_plan_nodes(&nodes, 99, &HashSet::new()).is_none());
    }
}
