//! Bulk queue exclusion and restore for reading containers (issue #5435).
//!
//! "Remove all series from Queue" / "Restore all to Queue" operate on a set of
//! thread IDs in one set-based write, recording which list/plan/crossover caused
//! a bulk removal so the Queue's excluded section can group and restore it as a
//! unit. Exclusion is non-destructive: it only moves active threads off the
//! queue (status `excluded`, queue_position 0) exactly like the per-thread
//! exclude path.

use crate::{auth::AuthenticatedUser, db, queue, ApiError, AppState};
use axum::{
    extract::{Path, State},
    Json,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

/// Maximum thread IDs accepted in one bulk queue exclusion/restore request.
const MAX_BULK_THREAD_IDS: usize = 1000;

/// Source container that produced a bulk queue exclusion.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct QueueExclusionSource {
    /// `reading_list`, `reading_plan`, or `crossover`.
    pub kind: String,
    pub id: i32,
    pub name: String,
}

/// Bulk exclusion request for a set of series (threads).
#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct BulkQueueExclusionRequest {
    /// Owned thread IDs to remove from the active queue.
    pub thread_ids: Vec<i32>,
    /// Container the removal was initiated from.
    pub source: QueueExclusionSource,
}

/// Persisted exclusion group returned after a bulk removal.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct QueueExclusionGroup {
    pub id: i32,
    pub source_kind: String,
    pub source_id: i32,
    pub source_name: String,
    pub created_at: String,
}

/// Bulk exclusion response.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct BulkQueueExclusionResponse {
    /// Created provenance group when at least one thread was excluded.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group: Option<QueueExclusionGroup>,
    pub excluded_thread_ids: Vec<i32>,
}

/// Bulk restore request for an explicit set of threads.
#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct BulkQueueRestoreRequest {
    pub thread_ids: Vec<i32>,
}

/// Bulk restore response.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct BulkQueueRestoreResponse {
    pub restored_thread_ids: Vec<i32>,
}

/// Scoped excluded-status check for a set of threads.
#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ExcludedStatusCheckRequest {
    pub thread_ids: Vec<i32>,
}

/// Scoped excluded-status check response.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ExcludedStatusCheckResponse {
    /// Requested thread IDs currently excluded for the reader.
    pub excluded_thread_ids: Vec<i32>,
    /// Requested thread IDs currently active in the queue for the reader.
    ///
    /// Used by container bulk actions to exclude completed/inactive series from
    /// removable selections without per-thread lookups.
    pub active_thread_ids: Vec<i32>,
}

fn bad_request(detail: &str) -> ApiError {
    ApiError::BadRequest(detail.to_string())
}

fn validate_source(source: &QueueExclusionSource) -> Result<(), ApiError> {
    if !matches!(
        source.kind.as_str(),
        "reading_list" | "reading_plan" | "crossover"
    ) {
        return Err(bad_request(
            "source.kind must be reading_list, reading_plan, or crossover",
        ));
    }
    if source.id <= 0 {
        return Err(bad_request("source.id must be positive"));
    }
    if source.name.trim().is_empty() {
        return Err(bad_request("source.name must not be empty"));
    }
    if source.name.chars().count() > 500 {
        return Err(bad_request("source.name must be at most 500 characters"));
    }
    Ok(())
}

fn validate_thread_id_count(count: usize) -> Result<(), ApiError> {
    if count == 0 {
        return Err(bad_request("thread_ids must contain at least one id"));
    }
    if count > MAX_BULK_THREAD_IDS {
        return Err(bad_request(&format!(
            "thread_ids must contain at most {MAX_BULK_THREAD_IDS} ids"
        )));
    }
    Ok(())
}

/// Normalize a requested thread-id set: drop non-positive ids and de-duplicate
/// in ascending order (stable, bounded, no per-row SQL).
fn normalize_thread_ids(ids: Vec<i32>) -> Vec<i32> {
    let mut ids: Vec<i32> = ids.into_iter().filter(|id| *id > 0).collect();
    ids.sort_unstable();
    ids.dedup();
    ids
}

async fn renormalize_active_queue(
    transaction: &deadpool_postgres::Transaction<'_>,
    user_id: i32,
) -> Result<(), ApiError> {
    transaction
        .execute(
            "WITH ranked AS ( \
                 SELECT id, row_number() OVER (ORDER BY queue_position, id)::int AS pos \
                 FROM threads \
                 WHERE user_id = $1 AND status = 'active' AND queue_position >= 1 \
             ) \
             UPDATE threads t SET queue_position = ranked.pos \
             FROM ranked WHERE t.id = ranked.id AND t.queue_position <> ranked.pos",
            &[&user_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(())
}

/// Recompute issue counters for the given excluded thread IDs and restore them
/// to active/completed in one set-based write. Caller must hold the per-reader
/// queue advisory lock and have locked the candidate rows.
async fn restore_locked_excluded_ids(
    transaction: &deadpool_postgres::Transaction<'_>,
    user_id: i32,
    excluded_ids: &[i32],
) -> Result<Vec<i32>, ApiError> {
    if excluded_ids.is_empty() {
        return Ok(Vec::new());
    }

    // Recompute counters for issue-tracked threads, mirroring per-thread restore.
    transaction
        .execute(
            "WITH issue_threads AS ( \
                 SELECT id FROM threads \
                 WHERE user_id = $1 AND id = ANY($2::int[]) AND status = 'excluded' \
                   AND total_issues IS NOT NULL \
             ), stats AS ( \
                 SELECT i.thread_id, \
                        count(*)::int AS total, \
                        count(*) FILTER (WHERE i.status = 'unread')::int AS remaining, \
                        (array_agg(i.id ORDER BY i.position, i.id) \
                          FILTER (WHERE i.status = 'unread'))[1] AS next_unread \
                 FROM issues i JOIN issue_threads it ON it.id = i.thread_id \
                 GROUP BY i.thread_id \
             ) \
             UPDATE threads t SET \
                 total_issues = COALESCE(s.total, 0), \
                 issues_remaining = COALESCE(s.remaining, 0), \
                 next_unread_issue_id = s.next_unread, \
                 reading_progress = CASE \
                     WHEN COALESCE(s.remaining, 0) = 0 THEN 'completed' \
                     WHEN COALESCE(s.remaining, 0) = COALESCE(s.total, 0) THEN 'not_started' \
                     ELSE 'in_progress' END, \
                 is_blocked = CASE WHEN COALESCE(s.remaining, 0) = 0 THEN false ELSE t.is_blocked END \
             FROM stats s WHERE t.id = s.thread_id",
            &[&user_id, &excluded_ids],
        )
        .await
        .map_err(db::query_error)?;

    // Issue-tracked threads with no issue rows.
    transaction
        .execute(
            "UPDATE threads t SET \
                 total_issues = 0, issues_remaining = 0, next_unread_issue_id = NULL, \
                 reading_progress = 'completed', is_blocked = false \
             WHERE t.user_id = $1 AND t.id = ANY($2::int[]) AND t.status = 'excluded' \
               AND t.total_issues IS NOT NULL \
               AND NOT EXISTS (SELECT 1 FROM issues i WHERE i.thread_id = t.id)",
            &[&user_id, &excluded_ids],
        )
        .await
        .map_err(db::query_error)?;

    // Restore: active threads (remaining > 0) go to the back of the queue in a
    // stable order; fully-read threads return to the completed shelf.
    let max_pos: i32 = transaction
        .query_one(
            "SELECT COALESCE(MAX(queue_position), 0)::int FROM threads \
             WHERE user_id = $1 AND status = 'active'",
            &[&user_id],
        )
        .await
        .map_err(db::query_error)?
        .get(0);

    let restored_rows = transaction
        .query(
            "WITH candidates AS ( \
                 SELECT t.id, \
                        CASE WHEN t.issues_remaining > 0 THEN 'active' ELSE 'completed' END AS new_status, \
                        row_number() OVER (ORDER BY t.id)::int AS ord \
                 FROM threads t \
                 WHERE t.user_id = $1 AND t.id = ANY($2::int[]) AND t.status = 'excluded' \
             ) \
             UPDATE threads t SET \
                 status = c.new_status, \
                 queue_position = CASE WHEN c.new_status = 'active' THEN $3 + c.ord ELSE 0 END, \
                 queue_position_is_manual = false, \
                 queue_exclusion_group_id = NULL \
             FROM candidates c \
             WHERE t.id = c.id \
             RETURNING t.id, t.status",
            &[&user_id, &excluded_ids, &max_pos],
        )
        .await
        .map_err(db::query_error)?;

    let restored_thread_ids: Vec<i32> = restored_rows.iter().map(|row| row.get(0)).collect();
    renormalize_active_queue(transaction, user_id).await?;
    Ok(restored_thread_ids)
}

/// Bulk-exclude active threads from the queue in one set-based write.
///
/// Only owned threads currently in `active` queue status are excluded; ids that
/// are missing, foreign, already excluded, or not active are ignored so the
/// operation is tolerant of stale selections. When no active threads remain to
/// exclude, no group is created and an empty result is returned.
pub async fn bulk_exclude(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<BulkQueueExclusionRequest>,
) -> Result<Json<BulkQueueExclusionResponse>, ApiError> {
    validate_source(&request.source)?;
    validate_thread_id_count(request.thread_ids.len())?;
    let thread_ids = normalize_thread_ids(request.thread_ids);
    if thread_ids.is_empty() {
        return Err(bad_request(
            "thread_ids must contain at least one positive id",
        ));
    }

    let mut connection = db::checkout(&state).await?;
    let transaction = connection.transaction().await.map_err(db::query_error)?;
    queue::lock_queue(&transaction, user.id()).await?;

    // Lock the owned active candidates so concurrent writers serialize on the
    // same rows after the per-reader queue advisory lock.
    let rows = transaction
        .query(
            "SELECT id FROM threads \
             WHERE user_id = $1 AND id = ANY($2::int[]) AND status = 'active' \
             ORDER BY id FOR UPDATE",
            &[&user.id(), &thread_ids],
        )
        .await
        .map_err(db::query_error)?;
    let excluded_thread_ids: Vec<i32> = rows.iter().map(|row| row.get(0)).collect();

    if excluded_thread_ids.is_empty() {
        transaction.commit().await.map_err(db::query_error)?;
        return Ok(Json(BulkQueueExclusionResponse {
            group: None,
            excluded_thread_ids,
        }));
    }

    let group_row = transaction
        .query_one(
            "INSERT INTO queue_exclusion_groups (user_id, source_kind, source_id, source_name) \
             VALUES ($1, $2, $3, $4) \
             RETURNING id, source_kind, source_id, source_name, \
                       to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')",
            &[
                &user.id(),
                &request.source.kind,
                &request.source.id,
                &request.source.name.trim(),
            ],
        )
        .await
        .map_err(db::query_error)?;

    transaction
        .execute(
            "UPDATE threads SET status = 'excluded', queue_position = 0, \
                    queue_position_is_manual = false, queue_exclusion_group_id = $3 \
             WHERE user_id = $1 AND id = ANY($2::int[]) AND status = 'active'",
            &[
                &user.id(),
                &excluded_thread_ids,
                &group_row.get::<_, i32>(0),
            ],
        )
        .await
        .map_err(db::query_error)?;

    renormalize_active_queue(&transaction, user.id()).await?;
    transaction.commit().await.map_err(db::query_error)?;

    Ok(Json(BulkQueueExclusionResponse {
        group: Some(QueueExclusionGroup {
            id: group_row.get(0),
            source_kind: group_row.get(1),
            source_id: group_row.get(2),
            source_name: group_row.get(3),
            created_at: group_row.get(4),
        }),
        excluded_thread_ids,
    }))
}

/// Restore a set of excluded threads to the queue in one set-based write.
async fn restore_ids(
    state: &AppState,
    user_id: i32,
    thread_ids: Vec<i32>,
) -> Result<Vec<i32>, ApiError> {
    let thread_ids = normalize_thread_ids(thread_ids);
    if thread_ids.is_empty() {
        return Ok(Vec::new());
    }

    let mut connection = db::checkout(state).await?;
    let transaction = connection.transaction().await.map_err(db::query_error)?;
    queue::lock_queue(&transaction, user_id).await?;

    let rows = transaction
        .query(
            "SELECT id FROM threads \
             WHERE user_id = $1 AND id = ANY($2::int[]) AND status = 'excluded' \
             ORDER BY id FOR UPDATE",
            &[&user_id, &thread_ids],
        )
        .await
        .map_err(db::query_error)?;
    let excluded_ids: Vec<i32> = rows.iter().map(|row| row.get(0)).collect();
    if excluded_ids.is_empty() {
        transaction.commit().await.map_err(db::query_error)?;
        return Ok(Vec::new());
    }

    let restored = restore_locked_excluded_ids(&transaction, user_id, &excluded_ids).await?;
    transaction.commit().await.map_err(db::query_error)?;
    Ok(restored)
}

/// `POST /api/v2/queue-exclusions/restore` — restore an explicit set of threads.
pub async fn bulk_restore(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<BulkQueueRestoreRequest>,
) -> Result<Json<BulkQueueRestoreResponse>, ApiError> {
    validate_thread_id_count(request.thread_ids.len())?;
    let restored_thread_ids = restore_ids(&state, user.id(), request.thread_ids).await?;
    Ok(Json(BulkQueueRestoreResponse {
        restored_thread_ids,
    }))
}

/// `POST /api/v2/queue-exclusions/status:check` — scoped excluded-status lookup.
///
/// Returns which of the requested thread IDs are currently excluded for the
/// reader. Read-only and owner-scoped; used by container bulk actions instead of
/// scanning the excluded library.
pub async fn check_excluded_status(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<ExcludedStatusCheckRequest>,
) -> Result<Json<ExcludedStatusCheckResponse>, ApiError> {
    validate_thread_id_count(request.thread_ids.len())?;
    let thread_ids = normalize_thread_ids(request.thread_ids);
    if thread_ids.is_empty() {
        return Err(bad_request(
            "thread_ids must contain at least one positive id",
        ));
    }

    let connection = db::checkout(&state).await?;
    let rows = connection
        .query(
            "SELECT id, status FROM threads \
             WHERE user_id = $1 AND id = ANY($2::int[]) AND status IN ('excluded', 'active') \
             ORDER BY id",
            &[&user.id(), &thread_ids],
        )
        .await
        .map_err(db::query_error)?;
    let mut excluded_thread_ids = Vec::new();
    let mut active_thread_ids = Vec::new();
    for row in &rows {
        let id: i32 = row.get(0);
        let status: &str = row.get(1);
        match status {
            "excluded" => excluded_thread_ids.push(id),
            "active" => active_thread_ids.push(id),
            _ => {}
        }
    }
    Ok(Json(ExcludedStatusCheckResponse {
        excluded_thread_ids,
        active_thread_ids,
    }))
}

/// `POST /api/v2/queue-exclusion-groups/{group_id}/restore` — restore a whole group.
///
/// Member selection and restore run in one locked transaction with the group
/// constraint enforced on selection/write to avoid restoring threads re-excluded
/// into a different group between selection and restore.
pub async fn restore_group(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(group_id): Path<i32>,
) -> Result<Json<BulkQueueRestoreResponse>, ApiError> {
    if group_id <= 0 {
        return Err(bad_request("group_id must be positive"));
    }

    let mut connection = db::checkout(&state).await?;
    let transaction = connection.transaction().await.map_err(db::query_error)?;
    queue::lock_queue(&transaction, user.id()).await?;

    let rows = transaction
        .query(
            "SELECT t.id FROM threads t \
             JOIN queue_exclusion_groups g ON g.id = t.queue_exclusion_group_id \
             WHERE g.id = $1 AND g.user_id = $2 AND t.user_id = $2 \
               AND t.status = 'excluded' AND t.queue_exclusion_group_id = $1 \
             ORDER BY t.id FOR UPDATE OF t",
            &[&group_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let thread_ids: Vec<i32> = rows.iter().map(|row| row.get(0)).collect();
    if thread_ids.is_empty() {
        transaction.commit().await.map_err(db::query_error)?;
        return Ok(Json(BulkQueueRestoreResponse {
            restored_thread_ids: Vec::new(),
        }));
    }

    let restored_thread_ids =
        restore_locked_excluded_ids(&transaction, user.id(), &thread_ids).await?;
    transaction.commit().await.map_err(db::query_error)?;
    Ok(Json(BulkQueueRestoreResponse {
        restored_thread_ids,
    }))
}

/// Documentation-only operations for queue exclusion v2 resources.
/// Generated from the handlers above using utoipa to produce the OpenAPI contract.

/// Documentation-only operation for bulk queue exclusion.
#[utoipa::path(
    post,
    path = "/api/v2/queue-exclusions",
    tag = "queue-exclusions",
    request_body = BulkQueueExclusionRequest,
    responses(
        (status = 200, description = "Bulk queue exclusion completed", body = BulkQueueExclusionResponse),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Invalid request body")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn bulk_exclude_documentation() {}

/// Documentation-only operation for bulk queue exclusion restore.
#[utoipa::path(
    post,
    path = "/api/v2/queue-exclusions/restore",
    tag = "queue-exclusions",
    request_body = BulkQueueRestoreRequest,
    responses(
        (status = 200, description = "Bulk queue exclusion restore completed", body = BulkQueueRestoreResponse),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Invalid request body")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn bulk_restore_documentation() {}

/// Documentation-only operation for excluded status check.
#[utoipa::path(
    post,
    path = "/api/v2/queue-exclusions/status:check",
    tag = "queue-exclusions",
    request_body = ExcludedStatusCheckRequest,
    responses(
        (status = 200, description = "Excluded status check completed", body = ExcludedStatusCheckResponse),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Invalid request body")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn check_excluded_status_documentation() {}

/// Documentation-only operation for queue exclusion group restore.
#[utoipa::path(
    post,
    path = "/api/v2/queue-exclusion-groups/{group_id}/restore",
    tag = "queue-exclusions",
    params(("group_id" = i32, Path, description = "Queue exclusion group identifier")),
    responses(
        (status = 200, description = "Queue exclusion group restore completed", body = BulkQueueRestoreResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Queue exclusion group not found")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn restore_group_documentation() {}
