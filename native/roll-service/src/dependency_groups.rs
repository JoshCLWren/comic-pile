//! Same-path Rust cutover for the browser-called dependency-group routes
//! (#4841, parent #4335).
//!
//! Preserves the Python `app/api/dependency_group.py` wire contract at the same
//! HTTP methods and exact paths:
//!
//! * `GET /api/v1/reading-order-groups/`
//! * `POST /api/v1/reading-order-groups/`
//! * `GET /api/v1/reading-order-groups/threads/{thread_id}/groups`
//! * `GET /api/v1/reading-order-groups/{group_id}`
//! * `GET /api/v1/reading-order-groups/{group_id}/detail`
//! * `PATCH /api/v1/reading-order-groups/{group_id}`
//! * `DELETE /api/v1/reading-order-groups/{group_id}`
//! * `POST /api/v1/reading-order-groups/{group_id}/issue-ranges`
//! * `POST /api/v1/reading-order-groups/{group_id}/members`
//! * `DELETE /api/v1/reading-order-groups/{group_id}/members/{member_id}`
//! * `PUT /api/v1/reading-order-groups/{group_id}/order`
//! * `GET /api/v1/reading-order-groups/{group_id}/plans`
//!
//! Wire parity with Python (`app/api/dependency_group.py` +
//! `app/services/dependency_group_service.py` + `app/repositories/dependency_group_repository.py`):
//!
//! * Group lists are one owner-scoped statement plus one batched membership
//!   query, then batched thread-title, unread-count and issue queries, so the
//!   statement count stays flat as the number of groups grows (no per-group
//!   membership fan-out).
//! * `sequence_order` is the authoritative crossover reading order and is never
//!   re-derived from membership ids or per-series issue positions.
//! * Business errors map like Python: 404 `Group {id} not found` /
//!   `Thread {id} not found`, 422 `Group name must not be blank`, 409
//!   `A group with this name already exists`, 422 range/order conflicts.
//! * Mutating handlers run one ReadCommitted transaction with commit/rollback
//!   and refresh the denormalized blocked-state flags in the same transaction.

use crate::{
    auth::AuthenticatedUser, db, issue_read::IssueDetailResponse, issue_service, queue,
    threads::ThreadDetailResponse, ApiError, AppState,
};
use axum::{
    extract::{
        rejection::{JsonRejection, PathRejection},
        Path, State,
    },
    http::StatusCode,
    Json,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
use tokio_postgres::{GenericClient, Transaction};

const MAX_GROUP_NAME_CHARS: usize = 120;
const MAX_RANGE_SIZE: i32 = 250;
const MAX_ORDER_ITEMS: usize = 1000;

const LIST_GROUPS_SQL: &str =
    "SELECT id, name, created_at FROM dependency_groups WHERE user_id = $1 ORDER BY name, id";
const LIST_GROUP_MEMBERS_SQL: &str = "SELECT id, group_id, thread_id, issue_id, sequence_order \
     FROM dependency_group_memberships WHERE group_id = ANY($1::int[]) ORDER BY group_id, id";
const OWNED_GROUP_SQL: &str =
    "SELECT id, name, created_at FROM dependency_groups WHERE id = $1 AND user_id = $2";
const OWNED_THREAD_SQL: &str = "SELECT id FROM threads WHERE id = $1 AND user_id = $2";
const OWNED_ISSUE_SQL: &str = "SELECT i.id, i.thread_id FROM issues i \
     JOIN threads t ON t.id = i.thread_id WHERE i.id = $1 AND t.user_id = $2";
const THREAD_GROUP_SUMMARIES_SQL: &str = "SELECT DISTINCT g.id, g.name FROM dependency_groups g \
     JOIN dependency_group_memberships m ON m.group_id = g.id \
     WHERE g.user_id = $1 AND (m.thread_id = $2 OR m.issue_id IN \
     (SELECT i.id FROM issues i WHERE i.thread_id = $2)) ORDER BY g.name, g.id";
const THREAD_TITLES_SQL: &str = "SELECT id, title FROM threads WHERE id = ANY($1::int[])";
const ISSUE_METADATA_SQL: &str = "SELECT i.id, i.issue_number, t.title FROM issues i \
     JOIN threads t ON t.id = i.thread_id WHERE i.id = ANY($1::int[])";
const THREAD_TOTALS_SQL: &str = "SELECT id, total_issues FROM threads WHERE id = ANY($1::int[])";
const UNREAD_COUNTS_SQL: &str = "SELECT i.thread_id, COUNT(*) FROM issues i \
     WHERE i.status = 'unread' AND i.thread_id = ANY($1::int[]) GROUP BY i.thread_id";
const ISSUE_PROGRESS_SQL: &str = "SELECT i.id, i.thread_id, i.status FROM issues i \
     WHERE i.id = ANY($1::int[])";
const THREADS_DETAIL_SQL: &str = "SELECT t.id, t.title, t.format, t.issues_remaining, \
     t.queue_position, t.status, t.last_rating, \
     to_char(t.last_activity_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') AS last_activity_at, \
     t.notes, t.is_test, t.is_blocked, \
     to_char(t.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') AS created_at, \
     t.total_issues, t.reading_progress, t.next_unread_issue_id, \
     (SELECT i.issue_number FROM issues i WHERE i.id = t.next_unread_issue_id) \
     AS next_unread_issue_number, t.manual_creator_credits::text AS manual_creator_credits \
     FROM threads t WHERE t.id = ANY($1::int[])";
const ISSUES_DETAIL_SQL: &str = "SELECT i.id, i.thread_id, i.issue_number, i.position, i.status, \
     to_char(i.read_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"') AS read_at, \
     to_char(i.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"') AS created_at \
     FROM issues i WHERE i.id = ANY($1::int[])";
const OTHER_COUPLERS_SQL: &str =
    "SELECT DISTINCT m.group_id, g.name, COALESCE(m.thread_id, i.thread_id) \
     AS thread_id FROM dependency_group_memberships m \
     JOIN dependency_groups g ON g.id = m.group_id AND g.user_id = $1 AND g.id <> $2 \
     LEFT JOIN issues i ON i.id = m.issue_id \
     WHERE m.group_id <> $2 AND (m.thread_id = ANY($3::int[]) OR i.thread_id = ANY($3::int[])) \
     ORDER BY g.name";
const LINKED_PLANS_SQL: &str = "SELECT id, name FROM continuity_plans \
     WHERE user_id = $1 AND nodes_json::jsonb @> $2::jsonb ORDER BY name, id";
const DELETE_GROUP_SQL: &str = "DELETE FROM dependency_groups WHERE id = $1 AND user_id = $2";
const SEQUENCE_OCCUPIED_SQL: &str = "SELECT id FROM dependency_group_memberships \
     WHERE group_id = $1 AND sequence_order = $2 LIMIT 1";
const ISSUE_MEMBERSHIPS_SQL: &str =
    "SELECT id, issue_id, sequence_order FROM dependency_group_memberships \
     WHERE group_id = $1 AND issue_id IS NOT NULL";
const OWNED_ISSUES_SQL: &str = "SELECT i.id, i.thread_id FROM issues i \
     JOIN threads t ON t.id = i.thread_id WHERE i.id = ANY($1::int[]) AND t.user_id = $2";
const INSERT_MEMBERSHIP_SQL: &str = "INSERT INTO dependency_group_memberships \
     (group_id, thread_id, issue_id, sequence_order) \
     VALUES ($1, $2, $3, $4) RETURNING id, group_id, thread_id, issue_id, sequence_order";
const INSERT_ISSUE_MEMBERSHIPS_SQL: &str = "INSERT INTO dependency_group_memberships (group_id, issue_id) \
     SELECT $1, issue_id FROM unnest($2::int[]) AS issue_ids(issue_id) ON CONFLICT DO NOTHING RETURNING issue_id";
const INSERT_GROUP_SQL: &str = "INSERT INTO dependency_groups (user_id, name, created_at) \
     VALUES ($1, $2, now()) RETURNING id, name, created_at";

/// Wire request mirroring the Python `DependencyGroupCreate` payload.
#[derive(Debug, Clone, Deserialize, Serialize, utoipa::ToSchema)]
pub struct DependencyGroupCreateRequest {
    pub name: String,
}

/// Wire request mirroring the Python `DependencyGroupUpdate` payload.
#[derive(Debug, Clone, Deserialize, Serialize, utoipa::ToSchema)]
pub struct DependencyGroupUpdateRequest {
    pub name: String,
}

/// Wire request mirroring the Python `DependencyGroupMemberCreate` payload.
#[derive(Debug, Clone, Deserialize, Serialize, utoipa::ToSchema)]
pub struct DependencyGroupMemberCreateRequest {
    pub thread_id: Option<i32>,
    pub issue_id: Option<i32>,
    pub sequence_order: Option<i32>,
}

/// Wire request mirroring the Python `DependencyGroupIssueRangeCreate` payload.
#[derive(Debug, Clone, Deserialize, Serialize, utoipa::ToSchema)]
pub struct DependencyGroupIssueRangeCreateRequest {
    pub thread_id: i32,
    pub start_position: i32,
    pub end_position: i32,
}

/// Wire request mirroring the Python `DependencyGroupOrderUpdate` payload.
#[derive(Debug, Clone, Deserialize, Serialize, utoipa::ToSchema)]
pub struct DependencyGroupOrderUpdateRequest {
    pub items: Vec<DependencyGroupOrderItem>,
}

/// Wire request item mirroring the Python `DependencyGroupOrderItem` payload.
#[derive(Debug, Clone, Deserialize, Serialize, utoipa::ToSchema)]
pub struct DependencyGroupOrderItem {
    pub issue_id: i32,
    pub sequence_order: i32,
}

fn validate_group_name_schema(name: &str) -> Result<(), ApiError> {
    let len = name.chars().count();
    if len == 0 || len > MAX_GROUP_NAME_CHARS {
        return Err(validation_failed());
    }
    Ok(())
}

fn validate_member_create_request(
    request: &DependencyGroupMemberCreateRequest,
) -> Result<(), ApiError> {
    if (request.thread_id.is_none()) == (request.issue_id.is_none()) {
        return Err(validation_failed());
    }
    if request.thread_id.is_some_and(|id| id <= 0) {
        return Err(validation_failed());
    }
    if request.issue_id.is_some_and(|id| id <= 0) {
        return Err(validation_failed());
    }
    if request.sequence_order.is_some_and(|order| order < 1) {
        return Err(validation_failed());
    }
    Ok(())
}

fn validate_issue_range_request(
    request: &DependencyGroupIssueRangeCreateRequest,
) -> Result<(), ApiError> {
    if request.thread_id <= 0 || request.start_position <= 0 || request.end_position <= 0 {
        return Err(validation_failed());
    }
    if request.end_position < request.start_position {
        // Python schema model_validator rejects this as a validation error.
        return Err(validation_failed());
    }
    Ok(())
}

fn validate_order_request(request: &DependencyGroupOrderUpdateRequest) -> Result<(), ApiError> {
    if request.items.is_empty() || request.items.len() > MAX_ORDER_ITEMS {
        return Err(validation_failed());
    }
    for item in &request.items {
        if item.issue_id <= 0 || item.sequence_order <= 0 {
            return Err(validation_failed());
        }
    }
    Ok(())
}

/// Wire response mirroring the Python `DependencyGroupIssueRangeResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct DependencyGroupIssueRangeResponse {
    pub thread_id: i32,
    pub start_position: i32,
    pub end_position: i32,
    pub added_issue_ids: Vec<i32>,
    pub already_present_issue_ids: Vec<i32>,
}

/// Wire response mirroring the Python `DependencyGroupMemberResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct DependencyGroupMemberResponse {
    pub id: i32,
    pub thread_id: Option<i32>,
    pub issue_id: Option<i32>,
    pub series_title: Option<String>,
    pub issue_number: Option<String>,
    pub sequence_order: Option<i32>,
}

/// Wire response mirroring the Python `DependencyGroupResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct DependencyGroupResponse {
    pub id: i32,
    pub name: String,
    pub created_at: String,
    pub memberships: Vec<DependencyGroupMemberResponse>,
    pub read_issues: i32,
    pub total_issues: i64,
    pub reading_progress: String,
}

/// Wire response mirroring the Python `DependencyGroupSummary`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct DependencyGroupSummary {
    pub id: i32,
    pub name: String,
}

/// Wire response member mirroring the Python `DependencyGroupDetailMemberResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct DependencyGroupDetailMemberResponse {
    pub membership: DependencyGroupMemberResponse,
    pub thread: Option<ThreadDetailResponse>,
    pub issue: Option<IssueDetailResponse>,
    pub other_crossovers: Vec<String>,
}

/// Wire response mirroring the Python `DependencyGroupDetailResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct DependencyGroupDetailResponse {
    pub id: i32,
    pub name: String,
    pub created_at: String,
    pub memberships: Vec<DependencyGroupDetailMemberResponse>,
    pub linked_plans: Vec<DependencyGroupSummary>,
}

/// Persisted group membership as the service resolves it.
#[derive(Debug, Clone)]
struct GroupMemberInput {
    id: i32,
    group_id: i32,
    thread_id: Option<i32>,
    issue_id: Option<i32>,
    sequence_order: Option<i32>,
}

/// Owned group row with its name and creation timestamp.
struct GroupRecord {
    id: i32,
    name: String,
    created_at: DateTime<Utc>,
}

fn format_created_at(created_at: DateTime<Utc>) -> String {
    let precision = if created_at.timestamp_subsec_micros() == 0 {
        SecondsFormat::Secs
    } else {
        SecondsFormat::Micros
    };
    created_at.to_rfc3339_opts(precision, true)
}

fn normalize_thread_format(format: &str) -> String {
    let trimmed = format.trim();
    match trimmed.to_ascii_lowercase().as_str() {
        "comic" | "comics" => "Comic".to_string(),
        "digital" => "Digital".to_string(),
        _ => trimmed.to_string(),
    }
}

fn unprocessable(detail: impl Into<String>) -> ApiError {
    ApiError::Unprocessable(detail.into())
}

fn conflict(detail: impl Into<String>) -> ApiError {
    ApiError::Conflict(detail.into())
}

/// Production `RequestValidationError` body: `{"detail": "Validation failed"}`.
fn validation_failed() -> ApiError {
    ApiError::Unprocessable("Validation failed".into())
}

fn parse_path_i32(raw: Result<Path<String>, PathRejection>) -> Result<i32, ApiError> {
    let Path(value) = raw.map_err(|_| validation_failed())?;
    value.trim().parse::<i32>().map_err(|_| validation_failed())
}

fn parse_path_i32_pair(
    raw: Result<Path<(String, String)>, PathRejection>,
) -> Result<(i32, i32), ApiError> {
    let Path((left, right)) = raw.map_err(|_| validation_failed())?;
    let left = left
        .trim()
        .parse::<i32>()
        .map_err(|_| validation_failed())?;
    let right = right
        .trim()
        .parse::<i32>()
        .map_err(|_| validation_failed())?;
    Ok((left, right))
}

fn parse_json<T>(raw: Result<Json<T>, JsonRejection>) -> Result<T, ApiError> {
    raw.map(|Json(value)| value)
        .map_err(|_| validation_failed())
}

/// Inclusive range length computed in `i64` so request-supplied `i32` bounds
/// cannot overflow the size guard (Python uses unbounded integers here).
fn inclusive_range_size(start: i32, end: i32) -> i64 {
    i64::from(end) - i64::from(start) + 1
}

/// Strip and validate a group name (Python `app/services/dependency_group_service.py::_normalize_name`).
fn normalize_group_name(name: &str) -> Result<String, ApiError> {
    let normalized = name.trim();
    if normalized.is_empty() {
        return Err(unprocessable("Group name must not be blank"));
    }
    if normalized.chars().count() > MAX_GROUP_NAME_CHARS {
        return Err(unprocessable(format!(
            "Group name must be at most {MAX_GROUP_NAME_CHARS} characters"
        )));
    }
    Ok(normalized.to_string())
}

fn member_response(
    id: i32,
    thread_id: Option<i32>,
    issue_id: Option<i32>,
    sequence_order: Option<i32>,
    thread_titles: &BTreeMap<i32, String>,
    issue_metadata: &BTreeMap<i32, (Option<String>, Option<String>)>,
) -> DependencyGroupMemberResponse {
    let (series_title, issue_number) = if let Some(thread_id) = thread_id {
        (thread_titles.get(&thread_id).cloned(), None)
    } else {
        let issue_id = issue_id.unwrap_or_default();
        let metadata = issue_metadata.get(&issue_id);
        (
            metadata.and_then(|meta| meta.1.clone()),
            metadata.and_then(|meta| meta.0.clone()),
        )
    };
    DependencyGroupMemberResponse {
        id,
        thread_id,
        issue_id,
        series_title,
        issue_number,
        sequence_order,
    }
}

/// Port of the Python member-response builder; pure so focused tests cover it.
fn build_member_responses(
    memberships: &[GroupMemberInput],
    thread_titles: &BTreeMap<i32, String>,
    issue_metadata: &BTreeMap<i32, (Option<String>, Option<String>)>,
) -> Vec<DependencyGroupMemberResponse> {
    memberships
        .iter()
        .map(|member| {
            member_response(
                member.id,
                member.thread_id,
                member.issue_id,
                member.sequence_order,
                thread_titles,
                issue_metadata,
            )
        })
        .collect()
}

/// Port of `app/services/dependency_group_service.py::_crossover_progress`.
fn crossover_progress(
    memberships: &[GroupMemberInput],
    threads: &BTreeMap<i32, Option<i32>>,
    issues: &BTreeMap<i32, (i32, String)>,
    unread_counts: &BTreeMap<i32, i64>,
) -> (i32, i64, String) {
    let mut thread_ids: BTreeSet<i32> = BTreeSet::new();
    for member in memberships {
        if let Some(thread_id) = member.thread_id {
            thread_ids.insert(thread_id);
        }
    }
    let mut read_issues: i64 = 0;
    let mut total_issues: i64 = 0;
    for thread_id in &thread_ids {
        let Some(Some(total)) = threads.get(thread_id) else {
            continue;
        };
        if *total <= 0 {
            continue;
        }
        let remaining = unread_counts.get(thread_id).copied().unwrap_or(0);
        total_issues += i64::from(*total);
        read_issues += (i64::from(*total) - remaining).max(0);
    }
    for member in memberships {
        let Some(issue_id) = member.issue_id else {
            continue;
        };
        let Some((thread_id, status)) = issues.get(&issue_id) else {
            continue;
        };
        if thread_ids.contains(thread_id) {
            continue;
        }
        total_issues += 1;
        if status != "unread" {
            read_issues += 1;
        }
    }
    let progress = if total_issues == 0 {
        "0%".to_string()
    } else {
        format!("{}%", read_issues * 100 / total_issues)
    };
    (read_issues as i32, total_issues, progress)
}

// ---------------------------------------------------------------------------
// Read-side batched loaders. Handlers run against one checked-out connection.
// ---------------------------------------------------------------------------

async fn load_thread_titles(
    connection: &deadpool_postgres::Object,
    thread_ids: &BTreeSet<i32>,
) -> Result<BTreeMap<i32, String>, ApiError> {
    if thread_ids.is_empty() {
        return Ok(BTreeMap::new());
    }
    let ids: Vec<i32> = thread_ids.iter().copied().collect();
    let rows = connection
        .query(THREAD_TITLES_SQL, &[&ids])
        .await
        .map_err(db::query_error)?;
    let mut titles = BTreeMap::new();
    for row in rows {
        titles.insert(row.get(0), row.get(1));
    }
    Ok(titles)
}

async fn load_issue_metadata(
    connection: &deadpool_postgres::Object,
    issue_ids: &BTreeSet<i32>,
) -> Result<BTreeMap<i32, (Option<String>, Option<String>)>, ApiError> {
    if issue_ids.is_empty() {
        return Ok(BTreeMap::new());
    }
    let ids: Vec<i32> = issue_ids.iter().copied().collect();
    let rows = connection
        .query(ISSUE_METADATA_SQL, &[&ids])
        .await
        .map_err(db::query_error)?;
    let mut metadata = BTreeMap::new();
    for row in rows {
        metadata.insert(row.get(0), (row.get(1), row.get(2)));
    }
    Ok(metadata)
}

async fn load_thread_totals(
    connection: &deadpool_postgres::Object,
    thread_ids: &BTreeSet<i32>,
) -> Result<BTreeMap<i32, Option<i32>>, ApiError> {
    if thread_ids.is_empty() {
        return Ok(BTreeMap::new());
    }
    let ids: Vec<i32> = thread_ids.iter().copied().collect();
    let rows = connection
        .query(THREAD_TOTALS_SQL, &[&ids])
        .await
        .map_err(db::query_error)?;
    let mut totals = BTreeMap::new();
    for row in rows {
        totals.insert(row.get(0), row.get(1));
    }
    Ok(totals)
}

async fn load_unread_counts(
    connection: &deadpool_postgres::Object,
    thread_ids: &BTreeSet<i32>,
) -> Result<BTreeMap<i32, i64>, ApiError> {
    if thread_ids.is_empty() {
        return Ok(BTreeMap::new());
    }
    let ids: Vec<i32> = thread_ids.iter().copied().collect();
    let rows = connection
        .query(UNREAD_COUNTS_SQL, &[&ids])
        .await
        .map_err(db::query_error)?;
    let mut counts = BTreeMap::new();
    for row in rows {
        counts.insert(row.get(0), row.get(1));
    }
    Ok(counts)
}

async fn load_issue_progress(
    connection: &deadpool_postgres::Object,
    issue_ids: &BTreeSet<i32>,
) -> Result<BTreeMap<i32, (i32, String)>, ApiError> {
    if issue_ids.is_empty() {
        return Ok(BTreeMap::new());
    }
    let ids: Vec<i32> = issue_ids.iter().copied().collect();
    let rows = connection
        .query(ISSUE_PROGRESS_SQL, &[&ids])
        .await
        .map_err(db::query_error)?;
    let mut issues = BTreeMap::new();
    for row in rows {
        issues.insert(row.get(0), (row.get(1), row.get(2)));
    }
    Ok(issues)
}

async fn owned_group<T: GenericClient>(
    connection: &T,
    group_id: i32,
    user_id: i32,
) -> Result<Option<GroupRecord>, ApiError> {
    let row = connection
        .query_opt(OWNED_GROUP_SQL, &[&group_id, &user_id])
        .await
        .map_err(db::query_error)?;
    Ok(row.map(|row| GroupRecord {
        id: row.get(0),
        name: row.get(1),
        created_at: row.get(2),
    }))
}

async fn owned_thread_id<T: GenericClient>(
    connection: &T,
    thread_id: i32,
    user_id: i32,
) -> Result<Option<i32>, ApiError> {
    let row = connection
        .query_opt(OWNED_THREAD_SQL, &[&thread_id, &user_id])
        .await
        .map_err(db::query_error)?;
    Ok(row.map(|row| row.get(0)))
}

async fn owned_issue_thread_id<T: GenericClient>(
    connection: &T,
    issue_id: i32,
    user_id: i32,
) -> Result<Option<i32>, ApiError> {
    let row = connection
        .query_opt(OWNED_ISSUE_SQL, &[&issue_id, &user_id])
        .await
        .map_err(db::query_error)?;
    Ok(row.map(|row| row.get(1)))
}

async fn memberships(
    connection: &deadpool_postgres::Object,
    group_id: i32,
) -> Result<Vec<GroupMemberInput>, ApiError> {
    let rows = connection
        .query(
            "SELECT id, group_id, thread_id, issue_id, sequence_order FROM dependency_group_memberships \
             WHERE group_id = $1 ORDER BY id",
            &[&group_id],
        )
        .await
        .map_err(db::query_error)?;
    let mut result = Vec::with_capacity(rows.len());
    for row in rows {
        result.push(GroupMemberInput {
            id: row.get(0),
            group_id: row.get(1),
            thread_id: row.get(2),
            issue_id: row.get(3),
            sequence_order: row.get(4),
        });
    }
    Ok(result)
}

async fn threads_by_ids(
    connection: &deadpool_postgres::Object,
    thread_ids: &BTreeSet<i32>,
) -> Result<BTreeMap<i32, Option<ThreadDetailResponse>>, ApiError> {
    let mut result = BTreeMap::new();
    if thread_ids.is_empty() {
        return Ok(result);
    }
    let ids: Vec<i32> = thread_ids.iter().copied().collect();
    let rows = connection
        .query(THREADS_DETAIL_SQL, &[&ids])
        .await
        .map_err(db::query_error)?;
    for row in rows {
        let manual_creator_credits = row
            .get::<_, Option<String>>(16)
            .and_then(|value| serde_json::from_str(&value).ok())
            .unwrap_or_else(|| serde_json::Value::Array(Vec::new()));
        result.insert(
            row.get(0),
            Some(ThreadDetailResponse {
                id: row.get(0),
                title: row.get(1),
                format: normalize_thread_format(row.get::<_, String>(2).as_str()),
                issues_remaining: row.get(3),
                queue_position: row.get(4),
                status: row.get(5),
                last_rating: row.get(6),
                last_activity_at: row.get(7),
                notes: row.get(8),
                is_test: row.get(9),
                is_blocked: row.get(10),
                blocking_reasons: Vec::new(),
                created_at: row.get(11),
                total_issues: row.get(12),
                reading_progress: row.get(13),
                next_unread_issue_id: row.get(14),
                next_unread_issue_number: row.get(15),
                manual_creator_credits,
            }),
        );
    }
    Ok(result)
}

async fn issues_by_ids(
    connection: &deadpool_postgres::Object,
    issue_ids: &BTreeSet<i32>,
) -> Result<BTreeMap<i32, Option<IssueDetailResponse>>, ApiError> {
    let mut result = BTreeMap::new();
    if issue_ids.is_empty() {
        return Ok(result);
    }
    let ids: Vec<i32> = issue_ids.iter().copied().collect();
    let rows = connection
        .query(ISSUES_DETAIL_SQL, &[&ids])
        .await
        .map_err(db::query_error)?;
    for row in rows {
        result.insert(
            row.get(0),
            Some(IssueDetailResponse {
                id: row.get(0),
                thread_id: row.get(1),
                issue_number: row.get(2),
                position: row.get(3),
                status: row.get(4),
                read_at: row.get(5),
                created_at: row.get(6),
            }),
        );
    }
    Ok(result)
}

async fn other_crossovers(
    connection: &deadpool_postgres::Object,
    group_id: i32,
    user_id: i32,
    thread_ids: &BTreeSet<i32>,
) -> Result<BTreeMap<i32, Vec<String>>, ApiError> {
    let mut result: BTreeMap<i32, Vec<String>> = BTreeMap::new();
    if thread_ids.is_empty() {
        return Ok(result);
    }
    let ids: Vec<i32> = thread_ids.iter().copied().collect();
    let rows = connection
        .query(OTHER_COUPLERS_SQL, &[&user_id, &group_id, &ids])
        .await
        .map_err(db::query_error)?;
    for row in rows {
        let thread_id: i32 = row.get(2);
        let name: String = row.get(1);
        result.entry(thread_id).or_default().push(name);
    }
    Ok(result)
}

async fn linked_plans(
    connection: &deadpool_postgres::Object,
    group_id: i32,
    user_id: i32,
) -> Result<Vec<DependencyGroupSummary>, ApiError> {
    let rows = connection
        .query(
            LINKED_PLANS_SQL,
            &[
                &user_id,
                &serde_json::json!([{ "node_type": "crossover", "ref_id": group_id }]),
            ],
        )
        .await
        .map_err(db::query_error)?;
    let mut plans = Vec::new();
    for row in rows {
        plans.push(DependencyGroupSummary {
            id: row.get(0),
            name: row.get(1),
        });
    }
    Ok(plans)
}

async fn issue_parent_threads(
    connection: &deadpool_postgres::Object,
    issue_ids: &BTreeSet<i32>,
) -> Result<BTreeMap<i32, i32>, ApiError> {
    let mut result = BTreeMap::new();
    if issue_ids.is_empty() {
        return Ok(result);
    }
    let ids: Vec<i32> = issue_ids.iter().copied().collect();
    let rows = connection
        .query(
            "SELECT id, thread_id FROM issues WHERE id = ANY($1)",
            &[&ids],
        )
        .await
        .map_err(db::query_error)?;
    for row in rows {
        result.insert(row.get(0), row.get(1));
    }
    Ok(result)
}

async fn group_response(
    connection: &deadpool_postgres::Object,
    group: &GroupRecord,
    memberships: &[GroupMemberInput],
) -> Result<DependencyGroupResponse, ApiError> {
    let mut thread_ids: BTreeSet<i32> = BTreeSet::new();
    let mut issue_ids: BTreeSet<i32> = BTreeSet::new();
    for member in memberships {
        if let Some(thread_id) = member.thread_id {
            thread_ids.insert(thread_id);
        }
        if let Some(issue_id) = member.issue_id {
            issue_ids.insert(issue_id);
        }
    }
    let thread_titles = load_thread_titles(connection, &thread_ids).await?;
    let issue_metadata = load_issue_metadata(connection, &issue_ids).await?;
    let threads = load_thread_totals(connection, &thread_ids).await?;
    let unread_counts = load_unread_counts(connection, &thread_ids).await?;
    let issues = load_issue_progress(connection, &issue_ids).await?;
    let (read_issues, total_issues, progress) =
        crossover_progress(memberships, &threads, &issues, &unread_counts);
    Ok(DependencyGroupResponse {
        id: group.id,
        name: group.name.clone(),
        created_at: format_created_at(group.created_at),
        memberships: build_member_responses(memberships, &thread_titles, &issue_metadata),
        read_issues,
        total_issues,
        reading_progress: progress,
    })
}

// ---------------------------------------------------------------------------
// Handlers: reads.
// ---------------------------------------------------------------------------

/// `GET /api/v1/reading-order-groups/`
pub async fn list_groups(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> Result<Json<Vec<DependencyGroupResponse>>, ApiError> {
    let connection = db::checkout(&state).await?;
    let group_rows = connection
        .query(LIST_GROUPS_SQL, &[&user.id()])
        .await
        .map_err(db::query_error)?;
    let groups: Vec<GroupRecord> = group_rows
        .iter()
        .map(|row| GroupRecord {
            id: row.get(0),
            name: row.get(1),
            created_at: row.get(2),
        })
        .collect();
    if groups.is_empty() {
        return Ok(Json(Vec::new()));
    }
    let group_ids: Vec<i32> = groups.iter().map(|group| group.id).collect();
    let membership_rows = connection
        .query(LIST_GROUP_MEMBERS_SQL, &[&group_ids])
        .await
        .map_err(db::query_error)?;
    let mut memberships_by_group: BTreeMap<i32, Vec<GroupMemberInput>> = BTreeMap::new();
    for row in membership_rows {
        let member = GroupMemberInput {
            id: row.get(0),
            group_id: row.get(1),
            thread_id: row.get(2),
            issue_id: row.get(3),
            sequence_order: row.get(4),
        };
        memberships_by_group
            .entry(member.group_id)
            .or_default()
            .push(member);
    }
    let mut thread_ids: BTreeSet<i32> = BTreeSet::new();
    let mut issue_ids: BTreeSet<i32> = BTreeSet::new();
    for members in memberships_by_group.values() {
        for member in members {
            if let Some(thread_id) = member.thread_id {
                thread_ids.insert(thread_id);
            }
            if let Some(issue_id) = member.issue_id {
                issue_ids.insert(issue_id);
            }
        }
    }
    let thread_titles = load_thread_titles(&connection, &thread_ids).await?;
    let issue_metadata = load_issue_metadata(&connection, &issue_ids).await?;
    let threads = load_thread_totals(&connection, &thread_ids).await?;
    let unread_counts = load_unread_counts(&connection, &thread_ids).await?;
    let issues = load_issue_progress(&connection, &issue_ids).await?;
    let mut responses = Vec::with_capacity(groups.len());
    for group in groups {
        let memberships = memberships_by_group
            .get(&group.id)
            .cloned()
            .unwrap_or_default();
        let (read_issues, total_issues, progress) =
            crossover_progress(&memberships, &threads, &issues, &unread_counts);
        responses.push(DependencyGroupResponse {
            id: group.id,
            name: group.name,
            created_at: format_created_at(group.created_at),
            memberships: build_member_responses(&memberships, &thread_titles, &issue_metadata),
            read_issues,
            total_issues,
            reading_progress: progress,
        });
    }
    Ok(Json(responses))
}

/// `POST /api/v1/reading-order-groups/`
pub async fn create_group(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    request: Result<Json<DependencyGroupCreateRequest>, JsonRejection>,
) -> Result<(StatusCode, Json<DependencyGroupResponse>), ApiError> {
    let request = parse_json(request)?;
    validate_group_name_schema(&request.name)?;
    let name = normalize_group_name(&request.name)?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    let result = create_group_tx(&tx, user.id(), &name).await;
    match result {
        Ok(group) => {
            tx.commit().await.map_err(db::query_error)?;
            let memberships = memberships(&connection, group.id).await?;
            let response = group_response(&connection, &group, &memberships).await?;
            Ok((StatusCode::CREATED, Json(response)))
        }
        Err(error) => {
            let _ = tx.rollback().await;
            Err(error)
        }
    }
}

async fn create_group_tx(
    tx: &Transaction<'_>,
    user_id: i32,
    name: &str,
) -> Result<GroupRecord, ApiError> {
    let row = tx
        .query_one(INSERT_GROUP_SQL, &[&user_id, &name])
        .await
        .map_err(|error| {
            if error
                .as_db_error()
                .is_some_and(|e| e.code().code() == "23505")
            {
                return conflict("A group with this name already exists");
            }
            db::query_error(error)
        })?;
    Ok(GroupRecord {
        id: row.get(0),
        name: row.get(1),
        created_at: row.get(2),
    })
}

/// `GET /api/v1/reading-order-groups/threads/{thread_id}/groups`
pub async fn list_thread_groups(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    thread_id: Result<Path<String>, PathRejection>,
) -> Result<Json<Vec<DependencyGroupSummary>>, ApiError> {
    let thread_id = parse_path_i32(thread_id)?;
    let connection = db::checkout(&state).await?;
    let owned = connection
        .query_opt(OWNED_THREAD_SQL, &[&thread_id, &user.id()])
        .await
        .map_err(db::query_error)?;
    if owned.is_none() {
        return Err(ApiError::NotFound(format!("Thread {thread_id} not found")));
    }
    let rows = connection
        .query(THREAD_GROUP_SUMMARIES_SQL, &[&user.id(), &thread_id])
        .await
        .map_err(db::query_error)?;
    let groups = rows
        .iter()
        .map(|row| DependencyGroupSummary {
            id: row.get(0),
            name: row.get(1),
        })
        .collect();
    Ok(Json(groups))
}

/// `GET /api/v1/reading-order-groups/{group_id}`
pub async fn get_group(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    group_id: Result<Path<String>, PathRejection>,
) -> Result<Json<DependencyGroupResponse>, ApiError> {
    let group_id = parse_path_i32(group_id)?;
    let connection = db::checkout(&state).await?;
    let group = owned_group(&**connection, group_id, user.id())
        .await?
        .ok_or_else(|| ApiError::NotFound(format!("Group {group_id} not found")))?;
    let memberships = memberships(&connection, group_id).await?;
    let response = group_response(&connection, &group, &memberships).await?;
    Ok(Json(response))
}

/// `GET /api/v1/reading-order-groups/{group_id}/detail`
pub async fn get_group_detail(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    group_id: Result<Path<String>, PathRejection>,
) -> Result<Json<DependencyGroupDetailResponse>, ApiError> {
    let group_id = parse_path_i32(group_id)?;
    let connection = db::checkout(&state).await?;
    let group = owned_group(&**connection, group_id, user.id())
        .await?
        .ok_or_else(|| ApiError::NotFound(format!("Group {group_id} not found")))?;
    let memberships = memberships(&connection, group_id).await?;
    let mut thread_ids: BTreeSet<i32> = BTreeSet::new();
    let mut issue_ids: BTreeSet<i32> = BTreeSet::new();
    let mut member_threads: BTreeMap<i32, Option<i32>> = BTreeMap::new();
    for member in &memberships {
        member_threads.insert(member.id, member.thread_id);
        if let Some(thread_id) = member.thread_id {
            thread_ids.insert(thread_id);
        }
        if let Some(issue_id) = member.issue_id {
            issue_ids.insert(issue_id);
        }
    }
    let issue_to_thread = issue_parent_threads(&connection, &issue_ids).await?;
    thread_ids.extend(issue_to_thread.values().copied());
    let threads = threads_by_ids(&connection, &thread_ids).await?;
    let issues = issues_by_ids(&connection, &issue_ids).await?;
    let other_crossovers = other_crossovers(&connection, group_id, user.id(), &thread_ids).await?;
    let linked_plans = linked_plans(&connection, group_id, user.id()).await?;
    let mut enriched = Vec::with_capacity(memberships.len());
    for member in &memberships {
        let mut thread = None;
        let mut issue = None;
        let mut other: Vec<String> = Vec::new();
        let (series_title, issue_number) = if let Some(thread_id) = member.thread_id {
            thread = threads.get(&thread_id).and_then(|opt| opt.clone());
            let title = thread.as_ref().map(|t| t.title.clone());
            other = other_crossovers
                .get(&thread_id)
                .cloned()
                .unwrap_or_default();
            (title, None)
        } else if let Some(issue_id) = member.issue_id {
            issue = issues.get(&issue_id).and_then(|opt| opt.clone());
            let thread_id = issue.as_ref().map(|i| i.thread_id).unwrap_or_default();
            thread = threads.get(&thread_id).and_then(|opt| opt.clone());
            let title = thread.as_ref().map(|t| t.title.clone());
            let number = issue.as_ref().map(|i| i.issue_number.clone());
            other = other_crossovers
                .get(&thread_id)
                .cloned()
                .unwrap_or_default();
            (title, number)
        } else {
            (None, None)
        };
        enriched.push(DependencyGroupDetailMemberResponse {
            membership: DependencyGroupMemberResponse {
                id: member.id,
                thread_id: member.thread_id,
                issue_id: member.issue_id,
                series_title,
                issue_number,
                sequence_order: member.sequence_order,
            },
            thread,
            issue,
            other_crossovers: other,
        });
    }
    Ok(Json(DependencyGroupDetailResponse {
        id: group.id,
        name: group.name,
        created_at: format_created_at(group.created_at),
        memberships: enriched,
        linked_plans,
    }))
}

/// `PATCH /api/v1/reading-order-groups/{group_id}`
pub async fn update_group(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    group_id: Result<Path<String>, PathRejection>,
    request: Result<Json<DependencyGroupUpdateRequest>, JsonRejection>,
) -> Result<(StatusCode, Json<DependencyGroupResponse>), ApiError> {
    let group_id = parse_path_i32(group_id)?;
    let request = parse_json(request)?;
    validate_group_name_schema(&request.name)?;
    let name = normalize_group_name(&request.name)?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    let result = update_group_tx(&tx, group_id, user.id(), &name).await;
    match result {
        Ok(group) => {
            tx.commit().await.map_err(db::query_error)?;
            let memberships = memberships(&connection, group_id).await?;
            let response = group_response(&connection, &group, &memberships).await?;
            Ok((StatusCode::OK, Json(response)))
        }
        Err(error) => {
            let _ = tx.rollback().await;
            Err(error)
        }
    }
}

async fn update_group_tx(
    tx: &Transaction<'_>,
    group_id: i32,
    user_id: i32,
    name: &str,
) -> Result<GroupRecord, ApiError> {
    if owned_group(tx, group_id, user_id).await?.is_none() {
        return Err(ApiError::NotFound(format!("Group {group_id} not found")));
    }
    let updated = tx
        .execute(
            "UPDATE dependency_groups SET name = $2 WHERE id = $1 AND user_id = $3",
            &[&group_id, &name, &user_id],
        )
        .await
        .map_err(|error| {
            if error
                .as_db_error()
                .is_some_and(|e| e.code().code() == "23505")
            {
                return conflict("A group with this name already exists");
            }
            db::query_error(error)
        })?;
    if updated == 0 {
        return Err(ApiError::NotFound(format!("Group {group_id} not found")));
    }
    let row = tx
        .query_one(
            "SELECT id, name, created_at FROM dependency_groups WHERE id = $1 AND user_id = $2",
            &[&group_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(GroupRecord {
        id: row.get(0),
        name: row.get(1),
        created_at: row.get(2),
    })
}

/// `DELETE /api/v1/reading-order-groups/{group_id}`
pub async fn delete_group(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    group_id: Result<Path<String>, PathRejection>,
) -> Result<StatusCode, ApiError> {
    let group_id = parse_path_i32(group_id)?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    let result = delete_group_tx(&tx, group_id, user.id()).await;
    match result {
        Ok(()) => {
            tx.commit().await.map_err(db::query_error)?;
            Ok(StatusCode::NO_CONTENT)
        }
        Err(error) => {
            let _ = tx.rollback().await;
            Err(error)
        }
    }
}

async fn delete_group_tx(
    tx: &Transaction<'_>,
    group_id: i32,
    user_id: i32,
) -> Result<(), ApiError> {
    queue::lock_queue(tx, user_id).await?;
    if owned_group(tx, group_id, user_id).await?.is_none() {
        return Err(ApiError::NotFound(format!("Group {group_id} not found")));
    }
    let deleted = tx
        .execute(DELETE_GROUP_SQL, &[&group_id, &user_id])
        .await
        .map_err(db::query_error)?;
    if deleted == 0 {
        return Err(ApiError::NotFound(format!("Group {group_id} not found")));
    }
    issue_service::refresh_blocked_threads(tx, user_id).await?;
    Ok(())
}

/// `POST /api/v1/reading-order-groups/{group_id}/issue-ranges`
pub async fn add_issue_range(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    group_id: Result<Path<String>, PathRejection>,
    request: Result<Json<DependencyGroupIssueRangeCreateRequest>, JsonRejection>,
) -> Result<(StatusCode, Json<DependencyGroupIssueRangeResponse>), ApiError> {
    let group_id = parse_path_i32(group_id)?;
    let request = parse_json(request)?;
    validate_issue_range_request(&request)?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    let result = add_issue_range_tx(&tx, group_id, user.id(), &request).await;
    match result {
        Ok(response) => {
            tx.commit().await.map_err(db::query_error)?;
            Ok((StatusCode::OK, Json(response)))
        }
        Err(error) => {
            let _ = tx.rollback().await;
            Err(error)
        }
    }
}

async fn add_issue_range_tx(
    tx: &Transaction<'_>,
    group_id: i32,
    user_id: i32,
    request: &DependencyGroupIssueRangeCreateRequest,
) -> Result<DependencyGroupIssueRangeResponse, ApiError> {
    queue::lock_queue(tx, user_id).await?;
    if request.end_position < request.start_position {
        return Err(unprocessable(
            "end_position must be greater than or equal to start_position",
        ));
    }
    if inclusive_range_size(request.start_position, request.end_position)
        > i64::from(MAX_RANGE_SIZE)
    {
        return Err(unprocessable(format!(
            "Issue range cannot contain more than {MAX_RANGE_SIZE} positions"
        )));
    }
    if owned_group(tx, group_id, user_id).await?.is_none() {
        return Err(ApiError::NotFound(format!("Group {group_id} not found")));
    }
    if owned_thread_id(tx, request.thread_id, user_id)
        .await?
        .is_none()
    {
        return Err(ApiError::NotFound(format!(
            "Thread {} not found",
            request.thread_id
        )));
    }
    let rows = tx
        .query(
            "SELECT i.id, i.position FROM issues i WHERE i.thread_id = $1 AND i.position >= $2 \
             AND i.position <= $3 ORDER BY i.position",
            &[
                &request.thread_id,
                &request.start_position,
                &request.end_position,
            ],
        )
        .await
        .map_err(db::query_error)?;
    let mut actual_positions: Vec<i32> = Vec::with_capacity(rows.len());
    let mut issue_ids: Vec<i32> = Vec::with_capacity(rows.len());
    for row in rows {
        actual_positions.push(row.get(1));
        issue_ids.push(row.get(0));
    }
    let expected_positions: Vec<i32> = (request.start_position..=request.end_position).collect();
    if actual_positions != expected_positions {
        let actual_set: BTreeSet<i32> = actual_positions.iter().copied().collect();
        let missing: Vec<i32> = expected_positions
            .iter()
            .copied()
            .filter(|position| !actual_set.contains(position))
            .collect();
        return Err(unprocessable(format!(
            "Issue range contains missing positions: {}",
            missing
                .iter()
                .map(|n| n.to_string())
                .collect::<Vec<_>>()
                .join(", ")
        )));
    }
    let added_rows = tx
        .query(INSERT_ISSUE_MEMBERSHIPS_SQL, &[&group_id, &issue_ids])
        .await
        .map_err(db::query_error)?;
    let added_set: BTreeSet<i32> = added_rows.iter().map(|row| row.get::<_, i32>(0)).collect();
    let added_issue_ids: Vec<i32> = issue_ids
        .iter()
        .copied()
        .filter(|id| added_set.contains(id))
        .collect();
    let already_present_issue_ids: Vec<i32> = issue_ids
        .iter()
        .copied()
        .filter(|id| !added_set.contains(id))
        .collect();
    issue_service::refresh_blocked_threads(tx, user_id).await?;
    Ok(DependencyGroupIssueRangeResponse {
        thread_id: request.thread_id,
        start_position: request.start_position,
        end_position: request.end_position,
        added_issue_ids,
        already_present_issue_ids,
    })
}

/// `POST /api/v1/reading-order-groups/{group_id}/members`
pub async fn add_member(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    group_id: Result<Path<String>, PathRejection>,
    request: Result<Json<DependencyGroupMemberCreateRequest>, JsonRejection>,
) -> Result<(StatusCode, Json<DependencyGroupMemberResponse>), ApiError> {
    let group_id = parse_path_i32(group_id)?;
    let request = parse_json(request)?;
    validate_member_create_request(&request)?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    let result = add_member_tx(&tx, group_id, user.id(), &request).await;
    match result {
        Ok((member, thread_id, issue_id, _sequence_order)) => {
            tx.commit().await.map_err(db::query_error)?;
            let thread_ids: BTreeSet<i32> = thread_id.into_iter().collect();
            let issue_ids: BTreeSet<i32> = issue_id.into_iter().collect();
            let thread_titles = load_thread_titles(&connection, &thread_ids).await?;
            let issue_metadata = load_issue_metadata(&connection, &issue_ids).await?;
            let response = member_response(
                member.id,
                member.thread_id,
                member.issue_id,
                member.sequence_order,
                &thread_titles,
                &issue_metadata,
            );
            Ok((StatusCode::CREATED, Json(response)))
        }
        Err(error) => {
            let _ = tx.rollback().await;
            Err(error)
        }
    }
}

async fn add_member_tx(
    tx: &Transaction<'_>,
    group_id: i32,
    user_id: i32,
    request: &DependencyGroupMemberCreateRequest,
) -> Result<(GroupMemberInput, Option<i32>, Option<i32>, Option<i32>), ApiError> {
    queue::lock_queue(tx, user_id).await?;
    if owned_group(tx, group_id, user_id).await?.is_none() {
        return Err(ApiError::NotFound(format!("Group {group_id} not found")));
    }
    if request.thread_id.is_none() == request.issue_id.is_none() {
        return Err(unprocessable(
            "Exactly one of thread_id or issue_id is required",
        ));
    }
    let (thread_id, issue_id) = if let Some(thread_id) = request.thread_id {
        if owned_thread_id(tx, thread_id, user_id).await?.is_none() {
            return Err(ApiError::NotFound(format!("Thread {thread_id} not found")));
        }
        (Some(thread_id), None)
    } else {
        let issue_id = request.issue_id.unwrap_or_default();
        if owned_issue_thread_id(tx, issue_id, user_id)
            .await?
            .is_none()
        {
            return Err(ApiError::NotFound(format!("Issue {issue_id} not found")));
        }
        (None, Some(issue_id))
    };
    let sequence_order = if issue_id.is_some() {
        request.sequence_order
    } else {
        None
    };
    if let Some(sequence_order) = sequence_order {
        let occupied = tx
            .query_opt(SEQUENCE_OCCUPIED_SQL, &[&group_id, &sequence_order])
            .await
            .map_err(db::query_error)?;
        if occupied.is_some() {
            return Err(unprocessable(
                "Each sequence_order position may appear at most once in the crossover",
            ));
        }
    }
    let row = tx
        .query_one(
            INSERT_MEMBERSHIP_SQL,
            &[&group_id, &thread_id, &issue_id, &sequence_order],
        )
        .await
        .map_err(|error| {
            if error
                .as_db_error()
                .is_some_and(|e| e.code().code() == "23505")
            {
                return conflict("This member is already in the group");
            }
            db::query_error(error)
        })?;
    issue_service::refresh_blocked_threads(tx, user_id).await?;
    Ok((
        GroupMemberInput {
            id: row.get(0),
            group_id,
            thread_id,
            issue_id,
            sequence_order,
        },
        thread_id,
        issue_id,
        sequence_order,
    ))
}

/// `DELETE /api/v1/reading-order-groups/{group_id}/members/{member_id}`
pub async fn remove_member(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    path: Result<Path<(String, String)>, PathRejection>,
) -> Result<StatusCode, ApiError> {
    let (group_id, member_id) = parse_path_i32_pair(path)?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    let result = remove_member_tx(&tx, group_id, member_id, user.id()).await;
    match result {
        Ok(()) => {
            tx.commit().await.map_err(db::query_error)?;
            Ok(StatusCode::NO_CONTENT)
        }
        Err(error) => {
            let _ = tx.rollback().await;
            Err(error)
        }
    }
}

async fn remove_member_tx(
    tx: &Transaction<'_>,
    group_id: i32,
    member_id: i32,
    user_id: i32,
) -> Result<(), ApiError> {
    queue::lock_queue(tx, user_id).await?;
    if owned_group(tx, group_id, user_id).await?.is_none() {
        return Err(ApiError::NotFound(format!("Group {group_id} not found")));
    }
    let member = tx
        .query_opt(
            "SELECT id, group_id FROM dependency_group_memberships WHERE id = $1",
            &[&member_id],
        )
        .await
        .map_err(db::query_error)?;
    let member =
        member.ok_or_else(|| ApiError::NotFound(format!("Member {member_id} not found")))?;
    let member_group_id: i32 = member.get(1);
    if member_group_id != group_id {
        return Err(ApiError::NotFound(format!("Member {member_id} not found")));
    }
    let deleted = tx
        .execute(
            "DELETE FROM dependency_group_memberships WHERE id = $1 AND group_id = $2",
            &[&member_id, &group_id],
        )
        .await
        .map_err(db::query_error)?;
    if deleted == 0 {
        return Err(ApiError::NotFound(format!("Member {member_id} not found")));
    }
    issue_service::refresh_blocked_threads(tx, user_id).await?;
    Ok(())
}

/// `PUT /api/v1/reading-order-groups/{group_id}/order`
pub async fn set_group_order(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    group_id: Result<Path<String>, PathRejection>,
    request: Result<Json<DependencyGroupOrderUpdateRequest>, JsonRejection>,
) -> Result<(StatusCode, Json<DependencyGroupResponse>), ApiError> {
    let group_id = parse_path_i32(group_id)?;
    let request = parse_json(request)?;
    validate_order_request(&request)?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    let result = set_group_order_tx(&tx, group_id, user.id(), &request).await;
    match result {
        Ok(group) => {
            tx.commit().await.map_err(db::query_error)?;
            let memberships = memberships(&connection, group_id).await?;
            let response = group_response(&connection, &group, &memberships).await?;
            Ok((StatusCode::OK, Json(response)))
        }
        Err(error) => {
            let _ = tx.rollback().await;
            Err(error)
        }
    }
}

async fn set_group_order_tx(
    tx: &Transaction<'_>,
    group_id: i32,
    user_id: i32,
    request: &DependencyGroupOrderUpdateRequest,
) -> Result<GroupRecord, ApiError> {
    queue::lock_queue(tx, user_id).await?;
    if request.items.is_empty() || request.items.len() > MAX_ORDER_ITEMS {
        return Err(unprocessable(format!(
            "The crossover order must contain between 1 and {MAX_ORDER_ITEMS} items"
        )));
    }
    let mut seen_issues: BTreeSet<i32> = BTreeSet::new();
    let mut seen_positions: BTreeSet<i32> = BTreeSet::new();
    let mut ordered_issue_ids: BTreeSet<i32> = BTreeSet::new();
    for item in &request.items {
        if !seen_issues.insert(item.issue_id) {
            return Err(unprocessable(
                "Each crossover issue may appear at most once in the order",
            ));
        }
        if !seen_positions.insert(item.sequence_order) {
            return Err(unprocessable(
                "Each sequence_order position may appear at most once in the order",
            ));
        }
        ordered_issue_ids.insert(item.issue_id);
    }
    if owned_group(tx, group_id, user_id).await?.is_none() {
        return Err(ApiError::NotFound(format!("Group {group_id} not found")));
    }
    let member_rows = tx
        .query(ISSUE_MEMBERSHIPS_SQL, &[&group_id])
        .await
        .map_err(db::query_error)?;
    let mut member_by_issue: BTreeMap<i32, i32> = BTreeMap::new();
    for row in member_rows {
        let membership_id: i32 = row.get(0);
        let issue_id: i32 = row.get(1);
        member_by_issue.insert(issue_id, membership_id);
    }
    let ordered_ids_vec: Vec<i32> = ordered_issue_ids.iter().copied().collect();
    let owned_rows = tx
        .query(OWNED_ISSUES_SQL, &[&ordered_ids_vec, &user_id])
        .await
        .map_err(db::query_error)?;
    let mut owned_issues: BTreeSet<i32> = BTreeSet::new();
    for row in owned_rows {
        owned_issues.insert(row.get(0));
    }
    for issue_id in &ordered_issue_ids {
        if !owned_issues.contains(issue_id) {
            return Err(ApiError::NotFound(format!("Issue {issue_id} not found")));
        }
        if !member_by_issue.contains_key(issue_id) {
            return Err(ApiError::NotFound(format!(
                "Issue {issue_id} is not a member of this crossover"
            )));
        }
    }
    // One set-based statement rewrites every issue-level membership's order:
    // listed issues receive their requested position, unlisted ones are cleared
    // to NULL, and thread-level memberships are untouched. This mirrors
    // Python's `membership.sequence_order = ordered_positions.get(issue_id)`
    // without a per-row round trip (AGENTS.md no-SQL-in-loops rule).
    let order_issue_ids: Vec<i32> = request.items.iter().map(|item| item.issue_id).collect();
    let order_positions: Vec<i32> = request
        .items
        .iter()
        .map(|item| item.sequence_order)
        .collect();
    tx.execute(
        "UPDATE dependency_group_memberships AS m
         SET sequence_order = requested.sequence_order
         FROM (
             SELECT mi.id AS membership_id, positions.sequence_order
             FROM dependency_group_memberships mi
             LEFT JOIN unnest($1::int[], $2::int[]) AS positions(issue_id, sequence_order)
               ON positions.issue_id = mi.issue_id
             WHERE mi.group_id = $3 AND mi.issue_id IS NOT NULL
         ) AS requested
         WHERE m.id = requested.membership_id",
        &[&order_issue_ids, &order_positions, &group_id],
    )
    .await
    .map_err(db::query_error)?;
    issue_service::refresh_blocked_threads(tx, user_id).await?;
    let row = tx
        .query_one(
            "SELECT id, name, created_at FROM dependency_groups WHERE id = $1 AND user_id = $2",
            &[&group_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(GroupRecord {
        id: row.get(0),
        name: row.get(1),
        created_at: row.get(2),
    })
}

/// `GET /api/v1/reading-order-groups/{group_id}/plans`
pub async fn list_crossover_plans(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    group_id: Result<Path<String>, PathRejection>,
) -> Result<Json<Vec<DependencyGroupSummary>>, ApiError> {
    let group_id = parse_path_i32(group_id)?;
    let connection = db::checkout(&state).await?;
    let group = owned_group(&**connection, group_id, user.id())
        .await?
        .ok_or_else(|| ApiError::NotFound(format!("Group {group_id} not found")))?;
    let _ = group;
    let plans = linked_plans(&connection, group_id, user.id()).await?;
    Ok(Json(plans))
}

// ---------------------------------------------------------------------------
// OpenAPI documentation
// ---------------------------------------------------------------------------

/// Documentation-only operation for listing reading-order groups.
#[utoipa::path(
    get,
    path = "/api/v1/reading-order-groups/",
    tag = "reading-order-groups",
    operation_id = "dependency_groups_list",
    responses(
        (status = 200, description = "Owned groups with memberships", body = Vec<DependencyGroupResponse>),
        (status = 401, description = "Not authenticated"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_groups_documentation() {}

/// Documentation-only operation for creating a reading-order group.
#[utoipa::path(
    post,
    path = "/api/v1/reading-order-groups/",
    tag = "reading-order-groups",
    operation_id = "dependency_groups_create",
    request_body = DependencyGroupCreateRequest,
    responses(
        (status = 201, description = "Created group", body = DependencyGroupResponse),
        (status = 401, description = "Not authenticated"),
        (status = 409, description = "A group with this name already exists"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn create_group_documentation() {}

/// Documentation-only operation for listing groups for a thread.
#[utoipa::path(
    get,
    path = "/api/v1/reading-order-groups/threads/{thread_id}/groups",
    tag = "reading-order-groups",
    operation_id = "dependency_groups_list_thread_groups",
    params(("thread_id" = i32, Path, description = "Owned thread identifier")),
    responses(
        (status = 200, description = "Groups containing the thread or its issues", body = Vec<DependencyGroupSummary>),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_thread_groups_documentation() {}

/// Documentation-only operation for fetching one group.
#[utoipa::path(
    get,
    path = "/api/v1/reading-order-groups/{group_id}",
    tag = "reading-order-groups",
    operation_id = "dependency_groups_get",
    params(("group_id" = i32, Path, description = "Owned group identifier")),
    responses(
        (status = 200, description = "Owned group", body = DependencyGroupResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Group not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_group_documentation() {}

/// Documentation-only operation for renaming one group.
#[utoipa::path(
    patch,
    path = "/api/v1/reading-order-groups/{group_id}",
    tag = "reading-order-groups",
    operation_id = "dependency_groups_update",
    params(("group_id" = i32, Path, description = "Owned group identifier")),
    request_body = DependencyGroupUpdateRequest,
    responses(
        (status = 200, description = "Renamed group", body = DependencyGroupResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Group not found"),
        (status = 409, description = "A group with this name already exists"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn update_group_documentation() {}

/// Documentation-only operation for deleting one group.
#[utoipa::path(
    delete,
    path = "/api/v1/reading-order-groups/{group_id}",
    tag = "reading-order-groups",
    operation_id = "dependency_groups_delete",
    params(("group_id" = i32, Path, description = "Owned group identifier")),
    responses(
        (status = 204, description = "Group deleted"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Group not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn delete_group_documentation() {}

/// Documentation-only operation for fetching enriched group detail.
#[utoipa::path(
    get,
    path = "/api/v1/reading-order-groups/{group_id}/detail",
    tag = "reading-order-groups",
    operation_id = "dependency_groups_get_detail",
    params(("group_id" = i32, Path, description = "Owned group identifier")),
    responses(
        (status = 200, description = "Owned group detail", body = DependencyGroupDetailResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Group not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_group_detail_documentation() {}

/// Documentation-only operation for adding an issue-position range.
#[utoipa::path(
    post,
    path = "/api/v1/reading-order-groups/{group_id}/issue-ranges",
    tag = "reading-order-groups",
    operation_id = "dependency_groups_add_issue_range",
    params(("group_id" = i32, Path, description = "Owned group identifier")),
    request_body = DependencyGroupIssueRangeCreateRequest,
    responses(
        (status = 200, description = "Range membership result", body = DependencyGroupIssueRangeResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Group or thread not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn add_issue_range_documentation() {}

/// Documentation-only operation for adding a group member.
#[utoipa::path(
    post,
    path = "/api/v1/reading-order-groups/{group_id}/members",
    tag = "reading-order-groups",
    operation_id = "dependency_groups_add_member",
    params(("group_id" = i32, Path, description = "Owned group identifier")),
    request_body = DependencyGroupMemberCreateRequest,
    responses(
        (status = 201, description = "Created membership", body = DependencyGroupMemberResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Group, thread, or issue not found"),
        (status = 409, description = "This member is already in the group"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn add_member_documentation() {}

/// Documentation-only operation for removing a group member.
#[utoipa::path(
    delete,
    path = "/api/v1/reading-order-groups/{group_id}/members/{member_id}",
    tag = "reading-order-groups",
    operation_id = "dependency_groups_remove_member",
    params(
        ("group_id" = i32, Path, description = "Owned group identifier"),
        ("member_id" = i32, Path, description = "Membership identifier")
    ),
    responses(
        (status = 204, description = "Membership removed"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Group or member not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn remove_member_documentation() {}

/// Documentation-only operation for setting crossover order.
#[utoipa::path(
    put,
    path = "/api/v1/reading-order-groups/{group_id}/order",
    tag = "reading-order-groups",
    operation_id = "dependency_groups_set_order",
    params(("group_id" = i32, Path, description = "Owned group identifier")),
    request_body = DependencyGroupOrderUpdateRequest,
    responses(
        (status = 200, description = "Updated group with reordered memberships", body = DependencyGroupResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Group, issue, or membership not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn set_group_order_documentation() {}

/// Documentation-only operation for listing linked continuity plans.
#[utoipa::path(
    get,
    path = "/api/v1/reading-order-groups/{group_id}/plans",
    tag = "reading-order-groups",
    operation_id = "dependency_groups_list_plans",
    params(("group_id" = i32, Path, description = "Owned group identifier")),
    responses(
        (status = 200, description = "Linked continuity plans", body = Vec<DependencyGroupSummary>),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Group not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_crossover_plans_documentation() {}

/// OpenAPI document for the native same-path reading-order-group surface.
#[derive(utoipa::OpenApi)]
#[openapi(
    info(
        title = "ComicPile native same-path reading-order-groups API",
        version = "1.0.0",
        description = "Generated contract for the native reading-order-group handlers that retain their original method and path."
    ),
    paths(
        list_groups_documentation,
        create_group_documentation,
        list_thread_groups_documentation,
        get_group_documentation,
        update_group_documentation,
        delete_group_documentation,
        get_group_detail_documentation,
        add_issue_range_documentation,
        add_member_documentation,
        remove_member_documentation,
        set_group_order_documentation,
        list_crossover_plans_documentation
    ),
    components(schemas(
        DependencyGroupCreateRequest,
        DependencyGroupUpdateRequest,
        DependencyGroupMemberCreateRequest,
        DependencyGroupIssueRangeCreateRequest,
        DependencyGroupOrderUpdateRequest,
        DependencyGroupOrderItem,
        DependencyGroupIssueRangeResponse,
        DependencyGroupMemberResponse,
        DependencyGroupResponse,
        DependencyGroupSummary,
        DependencyGroupDetailMemberResponse,
        DependencyGroupDetailResponse
    )),
    modifiers(&DependencyGroupsSecurityAddon)
)]
pub struct DependencyGroupsApi;

struct DependencyGroupsSecurityAddon;
impl utoipa::Modify for DependencyGroupsSecurityAddon {
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

/// Emit the same-path native reading-order-groups contract.
pub fn dependency_groups_openapi() -> utoipa::openapi::OpenApi {
    use utoipa::OpenApi;
    DependencyGroupsApi::openapi()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{config::Config, test_support::DB_LOCK};
    use axum::extract::{Path, State};
    use chrono::TimeZone;

    async fn test_state() -> Arc<AppState> {
        let url = crate::test_support::database_url().await;
        let config = Config::from_lookup(|name| match name {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-dependency-groups-test".into()),
            "RUST_ROLL_POOL_SIZE" => Some("2".into()),
            _ => None,
        })
        .expect("dependency-groups test config");
        Arc::new(AppState::new(config).expect("dependency-groups test state"))
    }

    #[test]
    fn normalize_group_name_trims_and_rejects_blank_and_overlong() {
        assert_eq!(
            normalize_group_name("  crossover  ").expect("valid name"),
            "crossover"
        );
        assert!(matches!(
            normalize_group_name("   \t  "),
            Err(ApiError::Unprocessable(detail)) if detail == "Group name must not be blank"
        ));
        let overlong = "x".repeat(MAX_GROUP_NAME_CHARS + 1);
        assert!(matches!(
            normalize_group_name(&overlong),
            Err(ApiError::Unprocessable(_))
        ));
    }

    #[test]
    fn error_helpers_keep_python_status_mapping() {
        assert_eq!(
            ApiError::status(&unprocessable("bad")),
            StatusCode::UNPROCESSABLE_ENTITY
        );
        assert_eq!(ApiError::status(&conflict("dup")), StatusCode::CONFLICT);
    }

    #[test]
    fn crossover_progress_matches_python_math() {
        let member = |id: i32, thread_id: Option<i32>, issue_id: Option<i32>| GroupMemberInput {
            id,
            group_id: 1,
            thread_id,
            issue_id,
            sequence_order: None,
        };
        let memberships = vec![member(1, Some(10), None), member(2, None, Some(20))];
        let threads: BTreeMap<i32, Option<i32>> = BTreeMap::from([(10, Some(4))]);
        let issues: BTreeMap<i32, (i32, String)> = BTreeMap::from([(20, (99, "read".to_string()))]);
        let unread: BTreeMap<i32, i64> = BTreeMap::from([(10, 1_i64)]);
        // Thread 10: 4 total, 1 unread -> 3 read. Loose issue 20 -> 1 total/read.
        assert_eq!(
            crossover_progress(&memberships, &threads, &issues, &unread),
            (4, 5, "80%".to_string())
        );
        let empty_threads: BTreeMap<i32, Option<i32>> = BTreeMap::new();
        let empty_issues: BTreeMap<i32, (i32, String)> = BTreeMap::new();
        let empty_unread: BTreeMap<i32, i64> = BTreeMap::new();
        assert_eq!(
            crossover_progress(&[], &empty_threads, &empty_issues, &empty_unread),
            (0, 0, "0%".to_string())
        );
        // Python floors read progress at zero when another writer has added
        // unread issues since the thread total was read.
        let skew_threads: BTreeMap<i32, Option<i32>> = BTreeMap::from([(10, Some(3))]);
        let skew_unread: BTreeMap<i32, i64> = BTreeMap::from([(10, 4_i64)]);
        assert_eq!(
            crossover_progress(
                &[member(1, Some(10), None)],
                &skew_threads,
                &empty_issues,
                &skew_unread
            ),
            (0, 3, "0%".to_string())
        );
    }

    #[test]
    fn format_created_at_matches_python_rfc3339_utc() {
        let whole = Utc.with_ymd_and_hms(2026, 11, 17, 12, 34, 56).unwrap();
        assert_eq!(format_created_at(whole), "2026-11-17T12:34:56Z");
    }

    #[tokio::test]
    async fn remove_member_deletes_only_the_requested_owned_member() {
        let _guard = DB_LOCK.lock().await;
        let state = test_state().await;
        crate::test_support::reset(&state).await;

        let connection = crate::db::checkout(&state).await.expect("seed connection");
        for user_id in [7_i32, 8_i32] {
            connection
                .execute(
                    "INSERT INTO users (id, username) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    &[&user_id, &format!("reader-{user_id}")],
                )
                .await
                .expect("seed user");
        }
        for (group_id, user_id) in [(101_i32, 7_i32), (102, 7), (103, 8)] {
            connection
                .execute(
                    "INSERT INTO dependency_groups (id, user_id, name, created_at) \
                     VALUES ($1, $2, $3, now())",
                    &[&group_id, &user_id, &format!("group-{group_id}")],
                )
                .await
                .expect("seed group");
        }
        for (thread_id, user_id) in [(11_i32, 7_i32), (12, 7), (13, 8)] {
            connection
                .execute(
                    "INSERT INTO threads (id, user_id, title, format, issues_remaining, status, queue_position, is_blocked) \
                     VALUES ($1, $2, $3, 'Comic', 1, 'active', 1, false)",
                    &[&thread_id, &user_id, &format!("Thread {thread_id}")],
                )
                .await
                .expect("seed thread");
        }
        for (member_id, group_id, thread_id) in
            [(201_i32, 101_i32, 11), (202, 102, 12), (203, 103, 13)]
        {
            connection
                .execute(
                    "INSERT INTO dependency_group_memberships (id, group_id, thread_id) \
                     VALUES ($1, $2, $3)",
                    &[&member_id, &group_id, &thread_id],
                )
                .await
                .expect("seed membership");
        }
        drop(connection);

        // Both path captures must be honoured: member 201 in group 101 is removed,
        // and a sibling group's member plus another user's group are untouched.
        let status = remove_member(
            State(state.clone()),
            AuthenticatedUser::for_test(7),
            Ok(Path(("101".to_string(), "201".to_string()))),
        )
        .await
        .expect("remove member");
        assert_eq!(status, StatusCode::NO_CONTENT);

        let connection = crate::db::checkout(&state)
            .await
            .expect("verify connection");
        let remaining: Vec<i32> = connection
            .query(
                "SELECT id FROM dependency_group_memberships ORDER BY id",
                &[],
            )
            .await
            .expect("remaining memberships")
            .iter()
            .map(|row| row.get(0))
            .collect();
        assert_eq!(remaining, vec![202, 203]);
        drop(connection);

        // Ownership: another user cannot delete a member inside group 102.
        let error = remove_member(
            State(state.clone()),
            AuthenticatedUser::for_test(8),
            Ok(Path(("102".to_string(), "202".to_string()))),
        )
        .await
        .expect_err("foreign group must be hidden");
        assert_eq!(ApiError::status(&error), StatusCode::NOT_FOUND);
    }

    #[test]
    fn inclusive_range_size_does_not_overflow_i32_bounds() {
        assert_eq!(inclusive_range_size(1, 250), 250);
        // The old `end - start + 1` i32 expression overflowed here; Python's
        // unbounded ints reject this as an oversized range instead of allocating.
        assert_eq!(inclusive_range_size(i32::MIN, i32::MAX), 4_294_967_296);
    }

    #[tokio::test]
    async fn set_group_order_rewrites_every_issue_membership() {
        let _guard = DB_LOCK.lock().await;
        let state = test_state().await;
        crate::test_support::reset(&state).await;

        let connection = crate::db::checkout(&state).await.expect("seed connection");
        for user_id in [7_i32, 8_i32] {
            connection
                .execute(
                    "INSERT INTO users (id, username) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    &[&user_id, &format!("reader-{user_id}")],
                )
                .await
                .expect("seed user");
        }
        connection
            .execute(
                "INSERT INTO threads (id, user_id, title, format, issues_remaining, status, queue_position, is_blocked) \
                 VALUES (11, 7, 'Thread 11', 'Comic', 4, 'active', 1, false)",
                &[],
            )
            .await
            .expect("seed thread");
        for (issue_id, position) in [(21_i32, 1_i32), (22, 2), (23, 3), (24, 4)] {
            connection
                .execute(
                    "INSERT INTO issues (id, thread_id, issue_number, position, status, created_at) \
                     VALUES ($1, 11, $2, $3, 'unread', now())",
                    &[&issue_id, &position.to_string(), &position],
                )
                .await
                .expect("seed issue");
        }
        connection
            .execute(
                "INSERT INTO dependency_groups (id, user_id, name, created_at) \
                 VALUES (101, 7, 'group-101', now())",
                &[],
            )
            .await
            .expect("seed group");
        for (membership_id, issue_id, order) in [
            (201_i32, 21_i32, Some(9_i32)),
            (202, 22, Some(8)),
            (203, 23, Some(7)),
            (204, 24, None),
        ] {
            connection
                .execute(
                    "INSERT INTO dependency_group_memberships (id, group_id, issue_id, sequence_order) \
                     VALUES ($1, 101, $2, $3)",
                    &[&membership_id, &issue_id, &order],
                )
                .await
                .expect("seed issue membership");
        }
        // Thread-level memberships are never sequence entries.
        connection
            .execute(
                "INSERT INTO dependency_group_memberships (id, group_id, thread_id) \
                 VALUES (205, 101, 11)",
                &[],
            )
            .await
            .expect("seed thread membership");
        drop(connection);

        let response = set_group_order(
            State(state.clone()),
            AuthenticatedUser::for_test(7),
            Ok(Path("101".to_string())),
            Ok(Json(DependencyGroupOrderUpdateRequest {
                items: vec![
                    DependencyGroupOrderItem {
                        issue_id: 21,
                        sequence_order: 1,
                    },
                    DependencyGroupOrderItem {
                        issue_id: 23,
                        sequence_order: 2,
                    },
                ],
            })),
        )
        .await
        .expect("set group order");
        assert_eq!(response.0, StatusCode::OK);

        let connection = crate::db::checkout(&state)
            .await
            .expect("verify connection");
        let rows = connection
            .query(
                "SELECT id, sequence_order FROM dependency_group_memberships \
                 WHERE group_id = 101 ORDER BY id",
                &[],
            )
            .await
            .expect("verify memberships");
        let orders: BTreeMap<i32, Option<i32>> = rows
            .iter()
            .map(|row| (row.get::<_, i32>(0), row.get::<_, Option<i32>>(1)))
            .collect();
        assert_eq!(orders.get(&201).copied().flatten(), Some(1));
        assert_eq!(orders.get(&202).copied().flatten(), None); // unlisted issue cleared
        assert_eq!(orders.get(&203).copied().flatten(), Some(2));
        assert_eq!(orders.get(&204).copied().flatten(), None); // already unordered stays NULL
        assert_eq!(orders.get(&205).copied().flatten(), None); // thread membership untouched
        drop(connection);

        // Ownership: a foreign user cannot rewrite the order.
        let error = set_group_order(
            State(state.clone()),
            AuthenticatedUser::for_test(8),
            Ok(Path("101".to_string())),
            Ok(Json(DependencyGroupOrderUpdateRequest {
                items: vec![DependencyGroupOrderItem {
                    issue_id: 21,
                    sequence_order: 1,
                }],
            })),
        )
        .await
        .expect_err("foreign group must be hidden");
        assert_eq!(ApiError::status(&error), StatusCode::NOT_FOUND);
    }

    #[test]
    fn contract_documents_every_operation_and_stays_current() {
        let document = serde_json::to_value(dependency_groups_openapi()).unwrap();
        for path in [
            "/api/v1/reading-order-groups/",
            "/api/v1/reading-order-groups/threads/{thread_id}/groups",
            "/api/v1/reading-order-groups/{group_id}",
            "/api/v1/reading-order-groups/{group_id}/detail",
            "/api/v1/reading-order-groups/{group_id}/issue-ranges",
            "/api/v1/reading-order-groups/{group_id}/members",
            "/api/v1/reading-order-groups/{group_id}/members/{member_id}",
            "/api/v1/reading-order-groups/{group_id}/order",
            "/api/v1/reading-order-groups/{group_id}/plans",
        ] {
            assert!(document["paths"].get(path).is_some(), "{path}");
        }
    }
}
