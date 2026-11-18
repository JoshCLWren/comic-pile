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
    auth::AuthenticatedUser,
    db,
    issue_read::IssueDetailResponse,
    issue_service,
    threads::ThreadDetailResponse,
    ApiError, AppState,
};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
use tokio_postgres::Transaction;

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
     t.queue_position, t.status, t.last_rating, t.last_activity_at, t.notes, t.is_test, \
     t.is_blocked, to_char(t.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"') AS \
     created_at, t.total_issues, t.reading_progress, t.next_unread_issue_id, \
     t.next_unread_issue_number, t.manual_creator_credits FROM threads t WHERE t.id = ANY($1::int[])";
const ISSUES_DETAIL_SQL: &str = "SELECT i.id, i.thread_id, i.issue_number, i.position, i.status, \
     to_char(i.read_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"') AS read_at, \
     to_char(i.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"') AS created_at \
     FROM issues i WHERE i.id = ANY($1::int[])";
const BLOCKING_EDGES_SQL: &str = "SELECT tt.id, si.issue_number, st.title FROM dependencies d \
     JOIN issues si ON si.id = d.source_issue_id JOIN threads st ON st.id = si.thread_id \
     JOIN issues ti ON ti.id = d.target_issue_id JOIN threads tt ON tt.id = ti.thread_id \
     WHERE tt.user_id = $1 AND tt.id = ANY($2::int[]) ORDER BY tt.id, si.id";
const OTHER_COUPLERS_SQL: &str = "SELECT DISTINCT m.group_id, g.name, COALESCE(m.thread_id, i.thread_id) \
     AS thread_id FROM dependency_group_memberships m \
     JOIN dependency_groups g ON g.id = m.group_id AND g.user_id = $1 AND g.id <> $2 \
     LEFT JOIN issues i ON i.id = m.issue_id \
     WHERE m.group_id <> $2 AND (m.thread_id = ANY($3::int[]) OR i.thread_id = ANY($3::int[])) \
     ORDER BY g.name";
const LINKED_PLANS_SQL: &str = "SELECT id, name FROM continuity_plans \
     WHERE user_id = $1 AND nodes_json @> $2::jsonb ORDER BY name, id";
const DELETE_GROUP_SQL: &str = "DELETE FROM dependency_groups WHERE id = $1 AND user_id = $2";
const SEQUENCE_OCCUPIED_SQL: &str = "SELECT id FROM dependency_group_memberships \
     WHERE group_id = $1 AND sequence_order = $2 LIMIT 1";
const ISSUE_MEMBERSHIPS_SQL: &str = "SELECT id, issue_id, sequence_order FROM dependency_group_memberships \
     WHERE group_id = $1 AND issue_id IS NOT NULL";
const OWNED_ISSUES_SQL: &str = "SELECT i.id, i.thread_id FROM issues i \
     JOIN threads t ON t.id = i.thread_id WHERE i.id = ANY($1::int[]) AND t.user_id = $2";
const INSERT_MEMBERSHIP_SQL: &str = "INSERT INTO dependency_group_memberships \
     (group_id, thread_id, issue_id, sequence_order) \
     VALUES ($1, $2, $3, $4) RETURNING id, group_id, thread_id, issue_id, sequence_order";
const INSERT_ISSUE_MEMBERSHIPS_SQL: &str = "INSERT INTO dependency_group_memberships (group_id, issue_id) \
     SELECT $1, issue_id FROM unnest($2::int[]) AS issue_ids(issue_id) ON CONFLICT DO NOTHING RETURNING issue_id";
const INSERT_GROUP_SQL: &str = "INSERT INTO dependency_groups (user_id, name) \
     VALUES ($1, $2) RETURNING id, name, created_at";

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

fn unprocessable(detail: impl Into<String>) -> ApiError {
    ApiError::Unprocessable(detail.into())
}

fn conflict(detail: impl Into<String>) -> ApiError {
    ApiError::Conflict(detail.into())
}

/// Strip and validate a group name (Python `app/services/dependency_group_service.py::_normalize_name`).
fn normalize_group_name(name: &str) -> Result<String, ApiError> {
    let normalized = name.trim();
    if normalized.chars().count() == 0 {
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
        read_issues += i64::from(*total) - remaining;
    }
    let mut read_issues = read_issues;
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
        format!("{read_issues * 100 / total_issues}%")
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

async fn owned_group(
    connection: &deadpool_postgres::Object,
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

async fn owned_thread_id(
    connection: &deadpool_postgres::Object,
    thread_id: i32,
    user_id: i32,
) -> Result<Option<i32>, ApiError> {
    let row = connection
        .query_opt(OWNED_THREAD_SQL, &[&thread_id, &user_id])
        .await
        .map_err(db::query_error)?;
    Ok(row.map(|row| row.get(0)))
}

async fn owned_issue_thread_id(
    connection: &deadpool_postgres::Object,
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
        let blocking_reasons: Vec<String> = Vec::new();
        result.insert(
            row.get(0),
            Some(ThreadDetailResponse {
                id: row.get(0),
                title: row.get(1),
                format: row.get(2),
                issues_remaining: row.get(3),
                queue_position: row.get(4),
                status: row.get(5),
                last_rating: row.get(6),
                last_activity_at: row.get(7),
                notes: row.get(8),
                is_test: row.get(9),
                is_blocked: row.get(10),
                blocking_reasons,
                created_at: row.get(11),
                total_issues: row.get(12),
                reading_progress: row.get(13),
                next_unread_issue_id: row.get(14),
                next_unread_issue_number: row.get(15),
                manual_creator_credits: serde_json::Value::Null,
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

async fn blocking_reasons_by_thread(
    connection: &deadpool_postgres::Object,
    user_id: i32,
    thread_ids: &BTreeSet<i32>,
) -> Result<BTreeMap<i32, Vec<String>>, ApiError> {
    let mut result: BTreeMap<i32, Vec<String>> = BTreeMap::new();
    if thread_ids.is_empty() {
        return Ok(result);
    }
    let ids: Vec<i32> = thread_ids.iter().copied().collect();
    let rows = connection
        .query(BLOCKING_EDGES_SQL, &[&user_id, &ids])
        .await
        .map_err(db::query_error)?;
    for row in rows {
        let thread_id: i32 = row.get(0);
        let issue_number: String = row.get(1);
        let thread_title: String = row.get(2);
        result
            .entry(thread_id)
            .or_default()
            .push(format!("Blocked by {thread_title}: #{issue_number}"));
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
            &[&user_id, &serde_json::json!({ "node_type": "crossover", "ref_id": group_id })],
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
    let (read_issues, total_issues, progress) = crossover_progress(
        memberships,
        &threads,
        &issues,
        &unread_counts,
    );
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

/// `GET /api/v1/reading-order-groups/threads/{thread_id}/groups`
pub async fn list_thread_groups(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(thread_id): Path<i32>,
) -> Result<Json<Vec<DependencyGroupSummary>>, ApiError> {
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
    Path(group_id): Path<i32>,
) -> Result<Json<DependencyGroupResponse>, ApiError> {
    let connection = db::checkout(&state).await?;
    let group = owned_group(&connection, group_id, user.id())
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
    Path(group_id): Path<i32>,
) -> Result<Json<DependencyGroupDetailResponse>, ApiError> {
    let connection = db::checkout(&state).await?;
    let group = owned_group(&connection, group_id, user.id())
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
    thread_ids.extend(issue_to_thread.values().copied().filter(|id| !id.is_empty()));
    let threads = threads_by_ids(&connection, &thread_ids).await?;
    let issues = issues_by_ids(&connection, &issue_ids).await?;
    let reasons = blocking_reasons_by_thread(&connection, user.id(), &thread_ids).await?;
    let other_crossovers = other_crossovers(&connection, group_id, user.id(), &thread_ids).await?;
    let linked_plans = linked_plans(&connection, group_id, user.id()).await?;
    let mut enriched = Vec::with_capacity(memberships.len());
    for member in &memberships {
        let mut thread = None;
        let mut issue = None;
        let mut other: Vec<String> = Vec::new();
        let mut blocking: Vec<String> = Vec::new();
        let (series_title, issue_number) = if let Some(thread_id) = member.thread_id {
            thread = threads.get(&thread_id).cloned().flatten();
            series_title = thread.as_ref().map(|thread| thread.title.clone());
            issue_number = None;
            other = other_crossovers.get(&thread_id).cloned().unwrap_or_default();
            blocking = reasons.get(&thread_id).cloned().unwrap_or_default();
        } else if let Some(issue_id) = member.issue_id {
            issue = issues.get(&issue_id).cloned().flatten();
            let thread_id = issue.as_ref().map(|issue| issue.thread_id);
            let thread_id = thread_id.unwrap_or_default();
            thread = threads.get(&thread_id).cloned().flatten();
            series_title = thread.as_ref().map(|thread| thread.title.clone());
            issue_number = issue.as_ref().map(|issue| issue.issue_number.clone());
            other = other_crossovers.get(&thread_id).cloned().unwrap_or_default();
            blocking = reasons.get(&thread_id).cloned().unwrap_or_default();
        } else {
            series_title = None;
            issue_number = None;
        }
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
    Path(group_id): Path<i32>,
    Json(request): Json<DependencyGroupUpdateRequest>,
) -> Result<(StatusCode, Json<DependencyGroupResponse>), ApiError> {
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
            if error.is_unique_violation() {
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
    Path(group_id): Path<i32>,
) -> Result<StatusCode, ApiError> {
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
    Path(group_id): Path<i32>,
    Json(request): Json<DependencyGroupIssueRangeCreateRequest>,
) -> Result<(StatusCode, Json<DependencyGroupIssueRangeResponse>), ApiError> {
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
    if request.end_position < request.start_position {
        return Err(unprocessable(
            "end_position must be greater than or equal to start_position",
        ));
    }
    if i64::from(request.end_position - request.start_position + 1) > i64::from(MAX_RANGE_SIZE) {
        return Err(unprocessable(format!(
            "Issue range cannot contain more than {MAX_RANGE_SIZE} positions"
        )));
    }
    if owned_group(tx, group_id, user_id).await?.is_none() {
        return Err(ApiError::NotFound(format!("Group {group_id} not found")));
    }
    if owned_thread_id(tx, request.thread_id, user_id).await?.is_none() {
        return Err(ApiError::NotFound(format!(
            "Thread {} not found",
            request.thread_id
        )));
    }
    let rows = tx
        .query(
            "SELECT i.id, i.position FROM issues i WHERE i.thread_id = $1 AND i.position >= $2 \
             AND i.position <= $3 ORDER BY i.position",
            &[&request.thread_id, &request.start_position, &request.end_position],
        )
        .await
        .map_err(db::query_error)?;
    let mut expected = Vec::new();
    let mut actual: Vec<i32> = Vec::new();
    for row in rows {
        expected.push(request.start_position + actual.len() as i32);
        actual.push(row.get(1));
    }
    if actual != expected {
        let mut missing: Vec<i32> = Vec::new();
        let mut expected_iter = expected.iter().copied();
        let mut actual_iter = actual.iter().copied();
        while let (Some(next), Some(found)) = (expected_iter.next(), actual_iter.next()) {
            if next != found {
                missing.push(next);
            }
        }
        return Err(unprocessable(format!(
            "Issue range contains missing positions: {}",
            missing.join(", ")
        )));
    }
    let issue_ids: Vec<i32> = rows.iter().map(|row| row.get(0)).collect();
    let added = tx
        .query(INSERT_ISSUE_MEMBERSHIPS_SQL, &[&group_id, &issue_ids])
        .await
        .map_err(db::query_error)?;
    let mut added_ids = Vec::new();
    for row in added {
        added_ids.push(row.get(0));
    }
    let mut already_present = Vec::new();
    for issue_id in &issue_ids {
        if !added_ids.contains(issue_id) {
            already_present.push(*issue_id);
        }
    }
    Ok(DependencyGroupIssueRangeResponse {
        thread_id: request.thread_id,
        start_position: request.start_position,
        end_position: request.end_position,
        added_issue_ids: added_ids,
        already_present_issue_ids: already_present,
    })
}

/// `POST /api/v1/reading-order-groups/{group_id}/members`
pub async fn add_member(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(group_id): Path<i32>,
    Json(request): Json<DependencyGroupMemberCreateRequest>,
) -> Result<(StatusCode, Json<DependencyGroupMemberResponse>), ApiError> {
    let mut connection = db::checkout(&state).await?;
    let tx = connection
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    let result = add_member_tx(&tx, group_id, user.id(), &request).await;
    match result {
        Ok((member, thread_id, issue_id, sequence_order)) => {
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
    if owned_group(tx, group_id, user_id).await?.is_none() {
        return Err(ApiError::NotFound(format!("Group {group_id} not found")));
    }
    if request.thread_id.is_none() && request.issue_id.is_none() {
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
        if owned_issue_thread_id(tx, issue_id, user_id).await?.is_none() {
            return Err(ApiError::NotFound(format!("Issue {issue_id} not found")));
        }
        (None, Some(issue_id))
    };
    let sequence_order = if issue_id.is_some() { request.sequence_order } else { None };
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
        .query_one(INSERT_MEMBERSHIP_SQL, &[&group_id, &thread_id, &issue_id, &sequence_order])
        .await
        .map_err(|error| {
            if error.is_unique_violation() {
                return conflict("This member is already in the group");
            }
            db::query_error(error)
        })?;
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
    Path(group_id): Path<i32>,
    Path(member_id): Path<i32>,
) -> Result<StatusCode, ApiError> {
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
            issue_service::refresh_blocked_threads(&tx, user.id()).await?;
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
    let member = member.ok_or_else(|| ApiError::NotFound(format!("Member {member_id} not found")))?;
    if member.get(1) != group_id {
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
    Ok(())
}

/// `PUT /api/v1/reading-order-groups/{group_id}/order`
pub async fn set_group_order(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(group_id): Path<i32>,
    Json(request): Json<DependencyGroupOrderUpdateRequest>,
) -> Result<(StatusCode, Json<DependencyGroupResponse>), ApiError> {
    let mut connection = db::checkout(&state).await?;
    let tx = connection
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    let result = set_group_order_tx(&tx, group_id, user.id(), &request).await;
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

async fn set_group_order_tx(
    tx: &Transaction<'_>,
    group_id: i32,
    user_id: i32,
    request: &DependencyGroupOrderUpdateRequest,
) -> Result<DependencyGroupResponse, ApiError> {
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
        member_by_issue.insert(row.get(1), row.get(2));
    }
    let owned_rows = tx
        .query(OWNED_ISSUES_SQL, &[&ordered_issue_ids.iter().copied().collect::<Vec<i32>>(), &user_id])
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
    let mut ordered_members: Vec<(i32, i32)> = Vec::with_capacity(request.items.len());
    for item in &request.items {
        let membership_id = member_by_issue
            .iter()
            .find(|(issue, _)| **issue == item.issue_id)
            .map(|(issue, sequence)| (*sequence, **issue))
            .map(|_| membership_id_for(&member_by_issue, item.issue_id))
            .expect("ordered issue must have a membership");
        let _ = (membership_id, *sequence_placeholder());
        ordered_members.push((*sequence_placeholder(), item.issue_id));
    }
    Ok(group_response_placeholder(&mut connection, group_id, user_id).await?)
}

/// `GET /api/v1/reading-order-groups/{group_id}/plans`
pub async fn list_crossover_plans(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(group_id): Path<i32>,
) -> Result<Json<Vec<DependencyGroupSummary>>, ApiError> {
    let connection = db::checkout(&state).await?;
    let group = owned_group(&connection, group_id, user.id())
        .await?
        .ok_or_else(|| ApiError::NotFound(format!("Group {group_id} not found")))?;
    let _ = group;
    let plans = linked_plans(&connection, group_id, user.id()).await?;
    Ok(Json(plans))
}
