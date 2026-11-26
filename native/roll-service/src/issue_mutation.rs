//! Canonical Rust issue mutations used by the Edit Series surface.
//!
//! These replace the Python `/v1/threads/{thread_id}/issues`,
//! `/v1/issues/{issue_id}` and `/v1/threads/{thread_id}/issues:reorder`
//! handlers. Every mutation validates the complete projected Option E graph
//! before commit, and a destructive edit that would leave a Reading List,
//! prerequisite or plan dangling is refused with the owning names.

use crate::{
    auth::AuthenticatedUser, db, option_inputs, reading_constraints::ValidatedReadingInputs,
    thread_issues::natural_issue_order, ApiError, AppState,
};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
use tokio_postgres::Transaction;

const QUEUE_LOCK_NAMESPACE: i32 = 699001;
const MAX_ISSUES_PER_REQUEST: i64 = 1000;

#[derive(Debug, Clone, Copy, Default, Deserialize, Serialize, PartialEq, Eq, utoipa::ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum IssuePlacementStrategy {
    /// Preserve existing relative issue order. Non-monotonic numeric series
    /// append new numbers instead of silently re-sorting persisted issues.
    #[default]
    SafeDefault,
    /// Explicitly re-seat all ordinary numeric issues in numeric order.
    /// This is a deliberate action and must be previewed before commit.
    NumericResort,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct CreateIssuesRequest {
    /// Reader-facing range, e.g. `1-3, 5` or `Annual 1`.
    pub issue_range: String,
    /// Explicit anchor. Omit for natural placement.
    pub insert_after_issue_id: Option<i32>,
    /// Explicit "At the end" choice. Distinct from an omitted anchor.
    #[serde(default)]
    pub append_to_end: bool,
    /// Placement strategy. Defaults to safe_default.
    #[serde(default)]
    pub strategy: IssuePlacementStrategy,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct IssueMutationItem {
    pub id: i32,
    pub thread_id: i32,
    pub issue_number: String,
    pub status: String,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct IssueListResponse {
    pub issues: Vec<IssueMutationItem>,
    pub total_count: i32,
    pub page_size: i64,
    pub next_page_token: Option<String>,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct IssueOrderRequest {
    pub issue_ids: Vec<i32>,
}

/// Documentation-only operation for the mounted issue-create resource.
#[utoipa::path(
    post,
    path = "/api/v2/threads/{thread_id}/issues",
    tag = "issues",
    description = "Create issue labels atomically. Natural numeric placement never re-sorts previously persisted issues; a non-monotonic series appends without changing existing relative order. The complete reading graph is validated before commit.",
    params(("thread_id" = i32, Path, description = "Owned Thread identifier")),
    request_body = CreateIssuesRequest,
    responses(
        (status = 201, description = "Created issues", body = IssueListResponse),
        (status = 400, description = "Invalid issue range or no new issues"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 409, description = "Projected reading graph would cycle; nothing was changed"),
        (status = 422, description = "Invalid reading snapshot"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn create_issues_documentation() {}

/// Documentation-only operation for the mounted issue delete resource.
#[utoipa::path(
    delete,
    path = "/api/v2/issues/{issue_id}",
    tag = "issues",
    description = "Delete one owned Issue only when no Reading List, prerequisite, plan or reading-history row references it. A referenced Issue is refused before any write with the owning names.",
    params(("issue_id" = i32, Path, description = "Owned Issue identifier")),
    responses(
        (status = 204, description = "Issue deleted and positions compacted"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Issue not found"),
        (status = 409, description = "Issue is referenced; nothing was changed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn delete_issue_documentation() {}

/// Documentation-only operation for the mounted issue-order resource.
#[utoipa::path(
    put,
    path = "/api/v2/threads/{thread_id}/issue-order",
    tag = "issues",
    description = "Replace the complete issue order atomically. The projected Option E graph is validated before commit, so a manual reorder cannot introduce a strict-list/series-order cycle.",
    params(("thread_id" = i32, Path, description = "Owned Thread identifier")),
    request_body = IssueOrderRequest,
    responses(
        (status = 204, description = "Issue order replaced"),
        (status = 400, description = "issue_ids must contain every thread issue exactly once"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 409, description = "Projected reading graph would cycle; nothing was changed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn issue_order_documentation() {}

/// Documentation-only operation for the mounted issue-create preview resource.
#[utoipa::path(
    post,
    path = "/api/v2/threads/{thread_id}/issues/preview",
    tag = "issues",
    description = "Preview an issue-create edit before commit. Returns the safe default outcome and, when relevant, a numeric-resort outcome with exact before/after order and graph validation.",
    params(("thread_id" = i32, Path, description = "Owned Thread identifier")),
    request_body = PreviewIssuesRequest,
    responses(
        (status = 200, description = "Preview outcomes", body = IssueEditPreviewResponse),
        (status = 400, description = "Invalid issue range or no new issues"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn preview_issue_create_documentation() {}

fn names(inputs: &option_inputs::OptionInputs) -> BTreeMap<i32, String> {
    inputs
        .lists
        .iter()
        .map(|list| (list.list_id, list.name.clone()))
        .collect()
}

async fn graph_preflight(tx: &Transaction<'_>, user: AuthenticatedUser) -> Result<(), ApiError> {
    let inputs = option_inputs::load_inputs_in_transaction(tx, user).await?;
    let names = names(&inputs);
    ValidatedReadingInputs::new(inputs.clone(), &names)
        .map_err(|error| crate::reading_graph::cycle_conflict(error, &inputs))?;
    Ok(())
}

pub(crate) async fn lock_reader(tx: &Transaction<'_>, user_id: i32) -> Result<(), ApiError> {
    tx.execute(
        "SELECT pg_advisory_xact_lock($1,$2)",
        &[&QUEUE_LOCK_NAMESPACE, &user_id],
    )
    .await
    .map_err(db::query_error)?;
    Ok(())
}

async fn lock_thread(tx: &Transaction<'_>, thread_id: i32, user_id: i32) -> Result<(), ApiError> {
    let row = tx
        .query_opt(
            "SELECT id FROM threads WHERE id=$1 AND user_id=$2 FOR UPDATE",
            &[&thread_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    row.ok_or_else(|| ApiError::NotFound("Thread not found".to_string()))?;
    Ok(())
}

fn ordinary(value: &str) -> Option<i64> {
    if value.is_empty()
        || value.starts_with('0')
        || !value.bytes().all(|byte| byte.is_ascii_digit())
    {
        return None;
    }
    value.parse().ok()
}

fn parse_issue_numbers(raw: &str) -> Result<Vec<String>, ApiError> {
    let mut numbers = vec![];
    let mut seen = BTreeSet::new();
    for part in raw.split(',') {
        let part = part.trim();
        if part.is_empty() {
            continue;
        }
        if let Some((start, end)) = part.split_once('-') {
            let (start, end) = (start.trim(), end.trim());
            if let (Some(start), Some(end)) = (ordinary(start), ordinary(end)) {
                if end < start || end - start >= MAX_ISSUES_PER_REQUEST {
                    return Err(ApiError::BadRequest(format!("Invalid issue range: {part}")));
                }
                for value in start..=end {
                    let label = value.to_string();
                    if seen.insert(label.clone()) {
                        numbers.push(label);
                    }
                }
                continue;
            }
        }
        if seen.insert(part.to_string()) {
            numbers.push(part.to_string());
        }
    }
    if numbers.is_empty() {
        return Err(ApiError::BadRequest(
            "Issue range cannot be empty".to_string(),
        ));
    }
    if numbers.len() as i64 > MAX_ISSUES_PER_REQUEST {
        return Err(ApiError::BadRequest("Issue range is too large".to_string()));
    }
    Ok(numbers)
}

async fn recreate_tracking_state(
    tx: &Transaction<'_>,
    thread_id: i32,
    user_id: i32,
) -> Result<(), ApiError> {
    tx.execute(
        "UPDATE threads t SET
             total_issues = (SELECT count(*)::int FROM issues i
                             WHERE i.thread_id=t.id AND i.merged_into_issue_id IS NULL),
             issues_remaining = (SELECT count(*)::int FROM issues i
                                 WHERE i.thread_id=t.id AND i.status <> 'read'
                                   AND i.merged_into_issue_id IS NULL),
             next_unread_issue_id = (SELECT i.id FROM issues i
                                     WHERE i.thread_id=t.id AND i.status <> 'read'
                                       AND i.merged_into_issue_id IS NULL
                                     ORDER BY i.position, i.id LIMIT 1),
             status = CASE
                 WHEN EXISTS (SELECT 1 FROM issues i
                              WHERE i.thread_id=t.id AND i.status <> 'read'
                                AND i.merged_into_issue_id IS NULL)
                 THEN 'active' ELSE 'completed' END
         WHERE t.id=$1 AND t.user_id=$2",
        &[&thread_id, &user_id],
    )
    .await
    .map_err(db::query_error)?;
    Ok(())
}

async fn insert_issue(
    tx: &Transaction<'_>,
    thread_id: i32,
    issue_number: &str,
    position: i32,
) -> Result<IssueMutationItem, ApiError> {
    let row = tx
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, status, created_at, position)
             VALUES ($1,$2,'unread',NOW(),$3)
             RETURNING id, thread_id, issue_number, status",
            &[&thread_id, &issue_number, &position],
        )
        .await
        .map_err(db::query_error)?;
    Ok(IssueMutationItem {
        id: row.get(0),
        thread_id: row.get(1),
        issue_number: row.get(2),
        status: row.get(3),
    })
}

pub(crate) async fn reseat_positions(
    tx: &Transaction<'_>,
    thread_id: i32,
    positions: &[(i32, i32)],
) -> Result<(), ApiError> {
    if positions.is_empty() {
        return Ok(());
    }
    let ids: Vec<i32> = positions.iter().map(|(id, _)| *id).collect();
    let values: Vec<i32> = positions.iter().map(|(_, position)| *position).collect();
    tx.execute(
        "UPDATE issues i SET position=v.position
         FROM (SELECT unnest($2::int[]) AS id, unnest($3::int[]) AS position) v
         WHERE i.id=v.id AND i.thread_id=$1",
        &[&thread_id, &ids, &values],
    )
    .await
    .map_err(db::query_error)?;
    Ok(())
}

/// `POST /api/v2/threads/{thread_id}/issues`
pub async fn create_issues(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(thread_id): Path<i32>,
    Json(request): Json<CreateIssuesRequest>,
) -> Result<(StatusCode, Json<IssueListResponse>), ApiError> {
    let requested = parse_issue_numbers(&request.issue_range)?;
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    lock_reader(&tx, user.id()).await?;
    lock_thread(&tx, thread_id, user.id()).await?;

    let rows = tx
        .query(
            "SELECT id, issue_number, position FROM issues
             WHERE thread_id=$1 ORDER BY position, id",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    let existing: Vec<(i32, String, i32)> = rows
        .iter()
        .map(|row| (row.get(0), row.get(1), row.get(2)))
        .collect();
    let existing_numbers: BTreeSet<String> = existing
        .iter()
        .map(|(_, number, _)| number.clone())
        .collect();
    let new_numbers: Vec<String> = requested
        .into_iter()
        .filter(|number| !existing_numbers.contains(number))
        .collect();
    if new_numbers.is_empty() {
        return Err(ApiError::BadRequest(
            "All issues in range already exist".to_string(),
        ));
    }

    tx.execute("SET CONSTRAINTS uq_issue_thread_position DEFERRED", &[])
        .await
        .map_err(db::query_error)?;

    let mut created = vec![];
    // Natural placement is only safe when persisted numeric order is already
    // monotonic. A non-monotonic series is reader-authored; appending must not
    // silently re-sort it into a different strict-list relationship. An explicit
    // NumericResort is a deliberate action that may re-seat ordinary numbers.
    let numbered: Option<Vec<i64>> = existing
        .iter()
        .map(|(_, number, _)| ordinary(number))
        .collect();
    let monotonic = numbered
        .as_ref()
        .is_some_and(|values| values.windows(2).all(|pair| pair[0] < pair[1]));
    let mixed_natural_order = if matches!(request.strategy, IssuePlacementStrategy::SafeDefault)
        && !request.append_to_end
        && request.insert_after_issue_id.is_none()
        && numbered.is_none()
    {
        let existing_labels: Vec<String> = existing
            .iter()
            .map(|(_, number, _)| number.clone())
            .collect();
        natural_issue_order(&existing_labels, &new_numbers)
    } else {
        None
    };
    let append = matches!(request.strategy, IssuePlacementStrategy::SafeDefault)
        && (request.append_to_end
            || (request.insert_after_issue_id.is_none()
                && !monotonic
                && mixed_natural_order.is_none()));

    if let Some(anchor) = request.insert_after_issue_id {
        let anchor_position = existing
            .iter()
            .find(|(id, _, _)| *id == anchor)
            .map(|(_, _, position)| *position)
            .ok_or_else(|| ApiError::NotFound(format!("Issue {anchor} not found")))?;
        let count = new_numbers.len() as i32;
        tx.execute(
            "UPDATE issues SET position=position+$1
             WHERE thread_id=$2 AND position>$3",
            &[&count, &thread_id, &anchor_position],
        )
        .await
        .map_err(db::query_error)?;
        for (offset, number) in new_numbers.iter().enumerate() {
            created.push(
                insert_issue(&tx, thread_id, number, anchor_position + offset as i32 + 1).await?,
            );
        }
    } else if let Some(order) = mixed_natural_order {
        let target: BTreeMap<&str, i32> = order
            .iter()
            .enumerate()
            .map(|(index, number)| (number.as_str(), index as i32 + 1))
            .collect();
        let positions: Vec<(i32, i32)> = existing
            .iter()
            .filter_map(|(id, number, position)| {
                target
                    .get(number.as_str())
                    .filter(|wanted| **wanted != *position)
                    .map(|wanted| (*id, *wanted))
            })
            .collect();
        reseat_positions(&tx, thread_id, &positions).await?;
        let mut creations: Vec<(&String, i32)> = new_numbers
            .iter()
            .map(|number| (number, target[number.as_str()]))
            .collect();
        creations.sort_by_key(|(_, position)| *position);
        for (number, position) in creations {
            created.push(insert_issue(&tx, thread_id, number, position).await?);
        }
    } else if append {
        let next = existing
            .iter()
            .map(|(_, _, position)| *position)
            .max()
            .unwrap_or(0);
        for (offset, number) in new_numbers.iter().enumerate() {
            created.push(insert_issue(&tx, thread_id, number, next + offset as i32 + 1).await?);
        }
    } else {
        // Monotonic numeric placement or explicit NumericResort.
        let mut merged = existing.clone();
        for number in &new_numbers {
            merged.push((0, number.clone(), 0));
        }
        merged.sort_by(|left, right| {
            let left_value = ordinary(&left.1).unwrap_or(i64::MAX);
            let right_value = ordinary(&right.1).unwrap_or(i64::MAX);
            (left_value, &left.1).cmp(&(right_value, &right.1))
        });
        let mut positions = vec![];
        for (next_position, (id, _number, _)) in (1..).zip(merged.iter()) {
            if *id != 0 {
                positions.push((*id, next_position));
            }
        }
        reseat_positions(&tx, thread_id, &positions).await?;
        for (position, (id, number, _)) in (1..).zip(merged.iter()) {
            if *id == 0 {
                created.push(insert_issue(&tx, thread_id, number, position).await?);
            }
        }
    }

    recreate_tracking_state(&tx, thread_id, user.id()).await?;
    graph_preflight(&tx, user).await?;
    tx.execute(
        "INSERT INTO events (type, user_id, thread_id, timestamp)
         VALUES ('issues_created',$1,$2,NOW())",
        &[&user.id(), &thread_id],
    )
    .await
    .map_err(db::query_error)?;
    let total: i32 = tx
        .query_one(
            "SELECT count(*)::int FROM issues WHERE thread_id=$1 AND merged_into_issue_id IS NULL",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?
        .get(0);
    tx.commit().await.map_err(db::query_error)?;
    let page_size = created.len() as i64;
    Ok((
        StatusCode::CREATED,
        Json(IssueListResponse {
            issues: created,
            total_count: total,
            page_size,
            next_page_token: None,
        }),
    ))
}

async fn reference_names(
    tx: &Transaction<'_>,
    issue_id: i32,
    user_id: i32,
) -> Result<Vec<String>, ApiError> {
    let lists = tx
        .query(
            "SELECT DISTINCT l.name FROM custom_cbl_entries e
             JOIN custom_cbl_lists l ON l.id=e.list_id
             WHERE e.issue_id=$1 AND l.user_id=$2 ORDER BY l.name",
            &[&issue_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    let plans = tx
        .query(
            "SELECT DISTINCT p.name FROM reading_plan_issues r
             JOIN continuity_plans p ON p.id=r.plan_id
             WHERE r.issue_id=$1 AND p.user_id=$2 ORDER BY p.name",
            &[&issue_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    let node_plans = tx
        .query(
            "SELECT DISTINCT p.name FROM continuity_plans p
             WHERE p.user_id=$1
               AND json_typeof(p.nodes_json) = 'array'
               AND EXISTS (
                   SELECT 1 FROM json_array_elements(p.nodes_json) node
                   WHERE (node->>'ref_id') ~ '^[0-9]+$'
                     AND (node->>'ref_id')::int=$2
               )
             ORDER BY p.name",
            &[&user_id, &issue_id],
        )
        .await
        .map_err(db::query_error)?;
    let dependencies: i64 = tx
        .query_one(
            "SELECT count(*) FROM dependencies WHERE source_issue_id=$1 OR target_issue_id=$1",
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?
        .get(0);
    let events: i64 = tx
        .query_one(
            "SELECT count(*) FROM events WHERE issue_id=$1 AND user_id=$2",
            &[&issue_id, &user_id],
        )
        .await
        .map_err(db::query_error)?
        .get(0);
    let mut names: Vec<String> = lists
        .iter()
        .chain(plans.iter())
        .chain(node_plans.iter())
        .map(|row| row.get(0))
        .collect();
    names.sort();
    names.dedup();
    if dependencies > 0 {
        names.push(format!("{dependencies} prerequisite edge(s)"));
    }
    if events > 0 {
        names.push(format!("{events} reading-history event(s)"));
    }
    Ok(names)
}

/// `DELETE /api/v2/issues/{issue_id}`
pub async fn delete_issue(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
) -> Result<StatusCode, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    lock_reader(&tx, user.id()).await?;
    let row = tx
        .query_opt(
            "SELECT i.thread_id, i.issue_number, i.position
             FROM issues i JOIN threads t ON t.id=i.thread_id
             WHERE i.id=$1 AND t.user_id=$2",
            &[&issue_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let Some(row) = row else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(ApiError::NotFound(format!("Issue {issue_id} not found")));
    };
    let thread_id: i32 = row.get(0);
    let issue_number: String = row.get(1);
    let position: i32 = row.get(2);
    lock_thread(&tx, thread_id, user.id()).await?;

    let references = reference_names(&tx, issue_id, user.id()).await?;
    if !references.is_empty() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(ApiError::Conflict(format!(
                "Issue {issue_number} is referenced by {}. Remove those references first; nothing was changed.",
                references.join(", ")
            )));
    }

    tx.execute("DELETE FROM issues WHERE id=$1", &[&issue_id])
        .await
        .map_err(db::query_error)?;
    tx.execute(
        "UPDATE issues SET position=position-1
         WHERE thread_id=$1 AND position>$2",
        &[&thread_id, &position],
    )
    .await
    .map_err(db::query_error)?;
    recreate_tracking_state(&tx, thread_id, user.id()).await?;
    graph_preflight(&tx, user).await?;
    tx.execute(
        "INSERT INTO events (type, user_id, thread_id, issue_number, timestamp)
         VALUES ('issue_deleted',$1,$2,$3,NOW())",
        &[&user.id(), &thread_id, &issue_number],
    )
    .await
    .map_err(db::query_error)?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(StatusCode::NO_CONTENT)
}

/// `PUT /api/v2/threads/{thread_id}/issue-order`
pub async fn reorder_issues(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(thread_id): Path<i32>,
    Json(request): Json<IssueOrderRequest>,
) -> Result<StatusCode, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    lock_reader(&tx, user.id()).await?;
    lock_thread(&tx, thread_id, user.id()).await?;
    let rows = tx
        .query(
            "SELECT id FROM issues WHERE thread_id=$1 ORDER BY position, id",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    let existing: Vec<i32> = rows.iter().map(|row| row.get(0)).collect();
    let requested: BTreeSet<i32> = request.issue_ids.iter().copied().collect();
    let available: BTreeSet<i32> = existing.iter().copied().collect();
    if requested.len() != request.issue_ids.len() || requested != available {
        return Err(ApiError::BadRequest(
            "issue_ids must contain every issue in the thread exactly once".to_string(),
        ));
    }
    tx.execute("SET CONSTRAINTS uq_issue_thread_position DEFERRED", &[])
        .await
        .map_err(db::query_error)?;
    let positions: Vec<(i32, i32)> = request
        .issue_ids
        .iter()
        .enumerate()
        .map(|(index, id)| (*id, index as i32 + 1))
        .collect();
    reseat_positions(&tx, thread_id, &positions).await?;
    recreate_tracking_state(&tx, thread_id, user.id()).await?;
    graph_preflight(&tx, user).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(StatusCode::NO_CONTENT)
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct PreviewIssuesRequest {
    /// Reader-facing range, e.g. `1-3, 5` or `Annual 1`.
    pub issue_range: String,
    /// Explicit anchor. Omit for natural placement.
    pub insert_after_issue_id: Option<i32>,
    /// Explicit "At the end" choice. Distinct from an omitted anchor.
    #[serde(default)]
    pub append_to_end: bool,
    /// Requested placement strategy. Defaults to safe_default.
    #[serde(default)]
    pub strategy: IssuePlacementStrategy,
}

/// Per-issue human-readable context carried in the preview payload so the
/// Before/After rows can identify a specific series, its list memberships,
/// identity/rating/read state and the Queue/Roll frontier it affects (#4654).
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct PreviewIssueItem {
    pub issue_id: Option<i32>,
    pub issue_number: String,
    pub position: i32,
    pub is_new: bool,
    /// Title of the series (thread) this issue belongs to.
    pub series_title: String,
    /// Names of every custom reading list the issue is a member of.
    pub source_lists: Vec<String>,
    /// Whether the issue has already been read.
    pub is_read: bool,
    /// Whether the issue has a confirmed external identity/catalog mapping.
    pub is_mapped: bool,
    /// Whether rating history exists for this issue.
    pub has_rating: bool,
    /// Human label for the Queue/Roll frontier affected by this issue, if any.
    pub frontier_label: Option<String>,
    /// Human-readable description of the order effect on this issue.
    pub effect: String,
    /// Whether a second physical issue with the same number exists in the series.
    pub is_duplicate: bool,
}

/// Set-based metadata gathered once per previewed thread (never per row) and
/// keyed by issue id. `new` issues have no entry and use neutral defaults.
#[derive(Debug, Clone, Default)]
struct PreviewIssueMetadata {
    source_lists: Vec<String>,
    is_read: bool,
    is_mapped: bool,
    has_rating: bool,
    is_frontier: bool,
    is_duplicate: bool,
}

/// Load all preview context for a thread in a single grouped query. This keeps
/// the preview free of N+1 round trips and is safe inside the preview savepoint.
async fn load_preview_metadata(
    tx: &Transaction<'_>,
    thread_id: i32,
) -> Result<(String, BTreeMap<i32, PreviewIssueMetadata>), ApiError> {
    let rows = tx
        .query(
            "SELECT i.id,
                    i.status = 'read' AS is_read,
                    (i.catalog_issue_id IS NOT NULL OR EXISTS (
                        SELECT 1 FROM issue_external_identity_mappings m
                        WHERE m.issue_id = i.id AND m.status = 'confirmed'
                    )) AS is_mapped,
                    EXISTS (
                        SELECT 1 FROM events e
                        WHERE e.issue_id = i.id AND e.rating IS NOT NULL
                    ) AS has_rating,
                    COALESCE((
                        SELECT array_agg(DISTINCT l.name ORDER BY l.name)::text[]
                        FROM custom_cbl_entries ce
                        JOIN custom_cbl_lists l ON l.id = ce.list_id
                        WHERE ce.issue_id = i.id
                    ), '{}'::text[]) AS source_lists,
                    EXISTS (
                        SELECT 1 FROM issues dup
                        WHERE dup.thread_id = i.thread_id
                          AND dup.issue_number = i.issue_number
                          AND dup.id <> i.id
                    ) AS is_duplicate,
                    COALESCE(t.next_unread_issue_id = i.id, false) AS is_frontier,
                    t.title
             FROM issues i
             JOIN threads t ON t.id = i.thread_id
             WHERE i.thread_id = $1",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;

    let mut series_title = String::new();
    let mut by_id = BTreeMap::new();
    for row in &rows {
        let id: i32 = row.get(0);
        let title: String = row.get(7);
        if series_title.is_empty() {
            series_title = title;
        }
        by_id.insert(
            id,
            PreviewIssueMetadata {
                source_lists: row.get(4),
                is_read: row.get(1),
                is_mapped: row.get(2),
                has_rating: row.get(3),
                is_frontier: row.get(6),
                is_duplicate: row.get(5),
            },
        );
    }
    Ok((series_title, by_id))
}

fn describe_effect(
    number: &str,
    is_new: bool,
    before_position: Option<i32>,
    after_position: i32,
    is_duplicate: bool,
) -> String {
    if is_new {
        return format!("new issue #{number} inserted at position {after_position}");
    }
    let order = match before_position {
        Some(before) if before == after_position => {
            format!("kept #{number} at position {after_position}")
        }
        Some(before) => format!("moved #{number} from position {before} to {after_position}"),
        None => format!("repositioned #{number} to position {after_position}"),
    };
    if is_duplicate {
        format!("{order}; possible physical duplicate of #{number}")
    } else {
        order
    }
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct IssueEditPreviewOutcome {
    pub strategy: IssuePlacementStrategy,
    pub can_commit: bool,
    pub preserves_existing_relative_order: bool,
    pub before: Vec<PreviewIssueItem>,
    pub after: Vec<PreviewIssueItem>,
    pub added_issue_numbers: Vec<String>,
    pub graph: crate::reading_graph::ReadingGraphResponse,
    pub conflict_message: Option<String>,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct IssueEditPreviewResponse {
    pub thread_id: i32,
    pub thread_title: String,
    pub requested_strategy: IssuePlacementStrategy,
    pub default_outcome: IssueEditPreviewOutcome,
    pub numeric_resort_outcome: Option<IssueEditPreviewOutcome>,
}

fn build_after_items(
    existing: &[(i32, String, i32)],
    merged: &[(i32, String)],
    series_title: &str,
    metadata: &BTreeMap<i32, PreviewIssueMetadata>,
) -> (Vec<PreviewIssueItem>, Vec<PreviewIssueItem>) {
    let before = existing
        .iter()
        .map(|(id, number, position)| {
            let meta = metadata.get(id);
            PreviewIssueItem {
                issue_id: Some(*id),
                issue_number: number.clone(),
                position: *position,
                is_new: false,
                series_title: series_title.to_string(),
                source_lists: meta.map(|m| m.source_lists.clone()).unwrap_or_default(),
                is_read: meta.is_some_and(|m| m.is_read),
                is_mapped: meta.is_some_and(|m| m.is_mapped),
                has_rating: meta.is_some_and(|m| m.has_rating),
                frontier_label: meta
                    .filter(|m| m.is_frontier)
                    .map(|_| "current unread (Queue/Roll frontier)".to_string()),
                effect: describe_effect(
                    number,
                    false,
                    Some(*position),
                    *position,
                    meta.is_some_and(|m| m.is_duplicate),
                ),
                is_duplicate: meta.is_some_and(|m| m.is_duplicate),
            }
        })
        .collect();
    let existing_positions: BTreeMap<i32, i32> = existing
        .iter()
        .map(|(id, _, position)| (*id, *position))
        .collect();
    let after = merged
        .iter()
        .enumerate()
        .map(|(index, (id, number))| {
            let is_new = *id == 0;
            let meta = if is_new { None } else { metadata.get(id) };
            let after_position = index as i32 + 1;
            let before_position = if is_new {
                None
            } else {
                existing_positions.get(id).copied()
            };
            PreviewIssueItem {
                issue_id: (*id != 0).then_some(*id),
                issue_number: number.clone(),
                position: after_position,
                is_new,
                series_title: series_title.to_string(),
                source_lists: meta.map(|m| m.source_lists.clone()).unwrap_or_default(),
                is_read: meta.is_some_and(|m| m.is_read),
                is_mapped: meta.is_some_and(|m| m.is_mapped),
                has_rating: meta.is_some_and(|m| m.has_rating),
                frontier_label: meta
                    .filter(|m| m.is_frontier)
                    .map(|_| "current unread (Queue/Roll frontier)".to_string()),
                effect: describe_effect(
                    number,
                    is_new,
                    before_position,
                    after_position,
                    meta.is_some_and(|m| m.is_duplicate),
                ),
                is_duplicate: meta.is_some_and(|m| m.is_duplicate),
            }
        })
        .collect();
    (before, after)
}

fn planned_merge(
    existing: &[(i32, String, i32)],
    new_numbers: &[String],
    request: &PreviewIssuesRequest,
    strategy: IssuePlacementStrategy,
) -> Result<(Vec<(i32, String)>, bool), ApiError> {
    let numbered: Option<Vec<i64>> = existing
        .iter()
        .map(|(_, number, _)| ordinary(number))
        .collect();
    let monotonic = numbered
        .as_ref()
        .is_some_and(|values| values.windows(2).all(|pair| pair[0] < pair[1]));
    let mixed_natural_order = if matches!(strategy, IssuePlacementStrategy::SafeDefault)
        && !request.append_to_end
        && request.insert_after_issue_id.is_none()
        && numbered.is_none()
    {
        let existing_labels: Vec<String> = existing.iter().map(|(_, n, _)| n.clone()).collect();
        natural_issue_order(&existing_labels, new_numbers)
    } else {
        None
    };

    let append = matches!(strategy, IssuePlacementStrategy::SafeDefault)
        && (request.append_to_end
            || (request.insert_after_issue_id.is_none()
                && !monotonic
                && mixed_natural_order.is_none()));

    if let Some(anchor) = request.insert_after_issue_id {
        let anchor_index = existing
            .iter()
            .position(|(id, _, _)| *id == anchor)
            .ok_or_else(|| ApiError::NotFound(format!("Issue {anchor} not found")))?;
        let mut merged: Vec<(i32, String)> = existing
            .iter()
            .map(|(id, number, _)| (*id, number.clone()))
            .collect();
        for (offset, number) in new_numbers.iter().enumerate() {
            merged.insert(anchor_index + 1 + offset, (0, number.clone()));
        }
        return Ok((merged, true));
    }

    if let Some(order) = mixed_natural_order {
        let mut merged: Vec<(i32, String)> = vec![];
        for number in order {
            if let Some((id, _, _)) = existing.iter().find(|(_, n, _)| n == &number) {
                merged.push((*id, number));
            } else {
                merged.push((0, number));
            }
        }
        return Ok((merged, true));
    }

    if append {
        let mut merged: Vec<(i32, String)> = existing
            .iter()
            .map(|(id, number, _)| (*id, number.clone()))
            .collect();
        for number in new_numbers {
            merged.push((0, number.clone()));
        }
        return Ok((merged, true));
    }

    if matches!(strategy, IssuePlacementStrategy::NumericResort) {
        let mut merged: Vec<(i32, String)> = existing
            .iter()
            .map(|(id, number, _)| (*id, number.clone()))
            .collect();
        for number in new_numbers {
            merged.push((0, number.clone()));
        }
        merged.sort_by(|left, right| {
            let left_value = ordinary(&left.1).unwrap_or(i64::MAX);
            let right_value = ordinary(&right.1).unwrap_or(i64::MAX);
            (left_value, &left.1, left.0).cmp(&(right_value, &right.1, right.0))
        });
        let preserves = existing
            .iter()
            .zip(merged.iter().filter(|(id, _)| *id != 0))
            .all(|(e, m)| e.0 == m.0);
        return Ok((merged, preserves));
    }

    // Safe default, monotonic numeric series: numeric placement.
    let mut merged: Vec<(i32, String)> = existing
        .iter()
        .map(|(id, number, _)| (*id, number.clone()))
        .collect();
    for number in new_numbers {
        merged.push((0, number.clone()));
    }
    merged.sort_by(|left, right| {
        let left_value = ordinary(&left.1).unwrap_or(i64::MAX);
        let right_value = ordinary(&right.1).unwrap_or(i64::MAX);
        (left_value, &left.1, left.0).cmp(&(right_value, &right.1, right.0))
    });
    let preserves = existing
        .iter()
        .zip(merged.iter().filter(|(id, _)| *id != 0))
        .all(|(e, m)| e.0 == m.0);
    Ok((merged, preserves))
}

async fn preview_outcome(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
    thread_id: i32,
    existing: &[(i32, String, i32)],
    new_numbers: &[String],
    request: &PreviewIssuesRequest,
    strategy: IssuePlacementStrategy,
) -> Result<IssueEditPreviewOutcome, ApiError> {
    let (merged, preserves) = planned_merge(existing, new_numbers, request, strategy)?;
    let (series_title, metadata) = load_preview_metadata(tx, thread_id).await?;
    let (before, after) = build_after_items(existing, &merged, &series_title, &metadata);

    let savepoint = format!(
        "sp_preview_{}",
        match strategy {
            IssuePlacementStrategy::SafeDefault => "safe",
            IssuePlacementStrategy::NumericResort => "resort",
        }
    );
    tx.execute(&format!("SAVEPOINT {savepoint}"), &[])
        .await
        .map_err(db::query_error)?;
    tx.execute("SET CONSTRAINTS uq_issue_thread_position DEFERRED", &[])
        .await
        .map_err(db::query_error)?;

    let positions: Vec<(i32, i32)> = merged
        .iter()
        .enumerate()
        .filter_map(|(index, (id, _))| (*id != 0).then_some((*id, index as i32 + 1)))
        .collect();
    reseat_positions(tx, thread_id, &positions).await?;
    for (index, (id, number)) in merged.iter().enumerate() {
        if *id == 0 {
            insert_issue(tx, thread_id, number, index as i32 + 1).await?;
        }
    }
    recreate_tracking_state(tx, thread_id, user.id()).await?;

    let inputs = option_inputs::load_inputs_in_transaction(tx, user).await?;
    let validated = option_inputs::validated_contained(inputs.clone())?;
    let graph = crate::reading_graph::project(&inputs, &validated, None);
    let can_commit = graph.status == "ok";
    let conflict_message = if can_commit {
        None
    } else {
        graph.cycles.first().map(|c| c.message.clone())
    };

    tx.execute(&format!("ROLLBACK TO SAVEPOINT {savepoint}"), &[])
        .await
        .map_err(db::query_error)?;
    tx.execute(&format!("RELEASE SAVEPOINT {savepoint}"), &[])
        .await
        .map_err(db::query_error)?;

    Ok(IssueEditPreviewOutcome {
        strategy,
        can_commit,
        preserves_existing_relative_order: preserves,
        before,
        after,
        added_issue_numbers: new_numbers.to_vec(),
        graph,
        conflict_message,
    })
}

/// `POST /api/v2/threads/{thread_id}/issues:preview`
pub async fn preview_issue_create(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(thread_id): Path<i32>,
    Json(request): Json<PreviewIssuesRequest>,
) -> Result<Json<IssueEditPreviewResponse>, ApiError> {
    let requested = parse_issue_numbers(&request.issue_range)?;
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    lock_reader(&tx, user.id()).await?;
    lock_thread(&tx, thread_id, user.id()).await?;

    let thread_row = tx
        .query_one(
            "SELECT title FROM threads WHERE id=$1 AND user_id=$2",
            &[&thread_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let thread_title: String = thread_row.get(0);

    let rows = tx
        .query(
            "SELECT id, issue_number, position FROM issues
             WHERE thread_id=$1 ORDER BY position, id",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    let existing: Vec<(i32, String, i32)> = rows
        .iter()
        .map(|row| (row.get(0), row.get(1), row.get(2)))
        .collect();
    let existing_numbers: BTreeSet<String> = existing.iter().map(|(_, n, _)| n.clone()).collect();
    let new_numbers: Vec<String> = requested
        .into_iter()
        .filter(|n| !existing_numbers.contains(n))
        .collect();
    if new_numbers.is_empty() {
        return Err(ApiError::BadRequest(
            "All issues in range already exist".to_string(),
        ));
    }

    let default_outcome = preview_outcome(
        &tx,
        user,
        thread_id,
        &existing,
        &new_numbers,
        &request,
        IssuePlacementStrategy::SafeDefault,
    )
    .await?;

    let numeric_resort_outcome =
        if request.insert_after_issue_id.is_none() && !request.append_to_end {
            let resort = preview_outcome(
                &tx,
                user,
                thread_id,
                &existing,
                &new_numbers,
                &request,
                IssuePlacementStrategy::NumericResort,
            )
            .await?;
            if resort.preserves_existing_relative_order
                && default_outcome.preserves_existing_relative_order
            {
                // Same effective result; no need to show a separate resort option.
                None
            } else {
                Some(resort)
            }
        } else {
            None
        };

    tx.rollback().await.map_err(db::query_error)?;
    Ok(Json(IssueEditPreviewResponse {
        thread_id,
        thread_title,
        requested_strategy: request.strategy,
        default_outcome,
        numeric_resort_outcome,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_ranges_and_specials_without_inventing_numbers() {
        assert_eq!(
            parse_issue_numbers("1-3, 5, Annual 1").unwrap(),
            vec!["1", "2", "3", "5", "Annual 1"]
        );
        assert_eq!(parse_issue_numbers("1-3, 2").unwrap(), vec!["1", "2", "3"]);
        assert!(parse_issue_numbers("").is_err());
        assert!(parse_issue_numbers("3-1").is_err());
    }

    #[test]
    fn ordinary_numbers_reject_leading_zero_and_decimals() {
        assert_eq!(ordinary("101"), Some(101));
        assert_eq!(ordinary("0101"), None);
        assert_eq!(ordinary("1.5"), None);
        assert_eq!(ordinary("Annual 1"), None);
    }

    #[test]
    fn unrelated_cycle_edges_are_not_silently_ordered_by_issue_label() {
        // Guard the exact failure: an ascending label list is not proof that the
        // reader-authored persisted order is ascending.
        let persisted = ["129", "140", "141", "142", "130"];
        let values: Vec<i64> = persisted
            .iter()
            .filter_map(|value| ordinary(value))
            .collect();
        assert!(values.windows(2).any(|pair| pair[0] >= pair[1]));
    }

    #[test]
    fn preview_effect_labels_are_human_readable() {
        assert_eq!(
            describe_effect("101", true, None, 3, false),
            "new issue #101 inserted at position 3"
        );
        assert_eq!(
            describe_effect("140", false, Some(2), 2, false),
            "kept #140 at position 2"
        );
        assert_eq!(
            describe_effect("130", false, Some(5), 9, false),
            "moved #130 from position 5 to 9"
        );
        assert!(
            describe_effect("130", false, Some(5), 9, true).contains("possible physical duplicate")
        );
    }

    #[test]
    fn preview_rows_carry_series_lists_frontier_and_effects() {
        let existing = vec![(7, "129".to_string(), 1), (8, "140".to_string(), 2)];
        let merged = vec![
            (7, "129".to_string()),
            (0, "101".to_string()),
            (8, "140".to_string()),
        ];
        let mut metadata = BTreeMap::new();
        metadata.insert(
            7,
            PreviewIssueMetadata {
                source_lists: vec!["Julix".to_string()],
                is_read: true,
                is_mapped: true,
                has_rating: true,
                is_frontier: true,
                is_duplicate: false,
            },
        );
        let (before, after) =
            build_after_items(&existing, &merged, "B.P.R.D.: Hell on Earth", &metadata);

        assert_eq!(before[0].series_title, "B.P.R.D.: Hell on Earth");
        assert_eq!(before[0].source_lists, vec!["Julix".to_string()]);
        assert!(before[0].is_read);
        assert!(before[0].is_mapped);
        assert!(before[0].has_rating);
        assert!(before[0]
            .frontier_label
            .as_deref()
            .is_some_and(|label| label.contains("Queue/Roll")));

        assert!(after[1].is_new);
        assert_eq!(after[1].effect, "new issue #101 inserted at position 2");
        assert_eq!(after[2].effect, "moved #140 from position 2 to 3");
        assert!(after[0].source_lists.contains(&"Julix".to_string()));
    }
}
