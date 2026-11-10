//! Canonical Rust issue mutations used by the Edit Series surface.
//!
//! These replace the Python `/v1/threads/{thread_id}/issues`,
//! `/v1/issues/{issue_id}` and `/v1/threads/{thread_id}/issues:reorder`
//! handlers. Every mutation validates the complete projected Option E graph
//! before commit, and a destructive edit that would leave a Reading List,
//! prerequisite or plan dangling is refused with the owning names.

use crate::{
    auth::AuthenticatedUser, db, option_inputs, reading_constraints::ValidatedReadingInputs,
    ApiError, AppState,
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

async fn lock_reader(tx: &Transaction<'_>, user_id: i32) -> Result<(), ApiError> {
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
             total_issues = (SELECT count(*)::int FROM issues i WHERE i.thread_id=t.id),
             issues_remaining = (SELECT count(*)::int FROM issues i
                                 WHERE i.thread_id=t.id AND i.status <> 'read'),
             next_unread_issue_id = (SELECT i.id FROM issues i
                                     WHERE i.thread_id=t.id AND i.status <> 'read'
                                     ORDER BY i.position, i.id LIMIT 1),
             status = CASE
                 WHEN EXISTS (SELECT 1 FROM issues i
                              WHERE i.thread_id=t.id AND i.status <> 'read')
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

async fn reseat_positions(
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
    let append = request.append_to_end
        || (request.insert_after_issue_id.is_none() && {
            // Natural placement is only safe when persisted numeric order is already
            // monotonic. A non-monotonic series is reader-authored; appending must not
            // silently re-sort it into a different strict-list relationship.
            let numbered: Option<Vec<i64>> = existing
                .iter()
                .map(|(_, number, _)| ordinary(number))
                .collect();
            numbered.is_none_or(|values| values.windows(2).any(|pair| pair[0] >= pair[1]))
        });

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
            "SELECT count(*)::int FROM issues WHERE thread_id=$1",
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
}
