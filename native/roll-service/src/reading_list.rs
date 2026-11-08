//! Canonical owner-scoped Reading List resources.
//!
//! These replace the read/list/create/delete half of the Python custom-CBL
//! surface. Authoring still runs through the one shared Option E graph
//! validator, inside the write transaction, before commit. The reader projects
//! availability from the same canonical Rust eligibility snapshot Roll and
//! Queue use, so a persisted cycle cannot make this page fail globally.

use crate::{
    auth::AuthenticatedUser, db, option_inputs, reading_blocker_projection,
    reading_constraints::ValidatedReadingInputs, reading_eligibility, ApiError, AppState,
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

#[derive(Debug, Clone, Deserialize, Serialize, utoipa::ToSchema)]
pub struct ReadingListEntryIntent {
    pub gate: String,
    #[serde(default)]
    pub skipped: bool,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingListEntry {
    pub id: i32,
    pub position: i32,
    pub issue_id: i32,
    pub thread_id: i32,
    pub series_name: String,
    pub issue_number: String,
    pub status: String,
    pub is_checkpoint: bool,
    pub gate: String,
    pub skipped: bool,
    pub checkpoint_target_issue_ids: Vec<i32>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingListSummary {
    pub id: i32,
    pub name: String,
    pub description: Option<String>,
    pub mode: String,
    pub issue_count: i32,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingList {
    pub id: i32,
    pub user_id: i32,
    pub name: String,
    pub description: Option<String>,
    pub mode: String,
    pub issue_count: i32,
    pub created_at: String,
    pub updated_at: String,
    pub entries: Vec<ReadingListEntry>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingListDependency {
    pub thread_id: i32,
    pub thread_title: String,
    pub issue_number: String,
    pub label: String,
    pub issue_id: Option<i32>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingListBlockerExplanation {
    pub is_blocked: bool,
    pub blocking_reasons: Vec<String>,
    pub blocking_dependencies: Vec<ReadingListDependency>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingListReaderEntry {
    pub id: i32,
    pub position: i32,
    pub issue_id: i32,
    pub thread_id: i32,
    pub series_name: String,
    pub issue_number: String,
    pub status: String,
    pub is_checkpoint: bool,
    pub gate: String,
    pub skipped: bool,
    pub checkpoint_target_issue_ids: Vec<i32>,
    pub availability: String,
    pub explanation: Option<ReadingListBlockerExplanation>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingListReader {
    pub list_id: i32,
    pub name: String,
    pub mode: String,
    pub execution_mode: String,
    pub entries: Vec<ReadingListReaderEntry>,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ReadingListWrite {
    pub name: String,
    pub description: Option<String>,
    pub mode: Option<String>,
    pub issue_ids: Vec<i32>,
    #[serde(default)]
    pub entry_intents: Option<BTreeMap<i32, ReadingListEntryIntent>>,
    #[serde(default)]
    pub checkpoint_issue_ids: Option<Vec<i32>>,
    #[serde(default)]
    pub checkpoint_targets: Option<BTreeMap<i32, Vec<i32>>>,
    /// Creation has no predecessor changes to confirm; only update accepts
    /// them. A present value is rejected exactly like the Python create path.
    #[serde(default)]
    pub confirmed_predecessor_changes: Option<serde_json::Value>,
}

/// Documentation-only operation for the Reading List collection.
#[utoipa::path(
    get,
    path = "/api/v2/reading-lists",
    tag = "reading-lists",
    description = "Owner-scoped compact Reading List rows ordered by name.",
    responses(
        (status = 200, description = "Owned Reading Lists", body = Vec<ReadingListSummary>),
        (status = 401, description = "Not authenticated"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_reading_lists_documentation() {}

/// Documentation-only operation for one Reading List.
#[utoipa::path(
    get,
    path = "/api/v2/reading-lists/{list_id}",
    tag = "reading-lists",
    params(("list_id" = i32, Path, description = "Owned Reading List identifier")),
    responses(
        (status = 200, description = "Reading List with ordered entries", body = ReadingList),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Reading List not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_reading_list_documentation() {}

/// Documentation-only operation for Reading List creation.
#[utoipa::path(
    post,
    path = "/api/v2/reading-lists",
    tag = "reading-lists",
    request_body = ReadingListWrite,
    responses(
        (status = 201, description = "Created Reading List", body = ReadingList),
        (status = 400, description = "Invalid list metadata or membership"),
        (status = 401, description = "Not authenticated"),
        (status = 409, description = "Projected reading graph would cycle; nothing was changed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn create_reading_list_documentation() {}

/// Documentation-only operation for Reading List deletion.
#[utoipa::path(
    delete,
    path = "/api/v2/reading-lists/{list_id}",
    tag = "reading-lists",
    params(("list_id" = i32, Path, description = "Owned Reading List identifier")),
    responses(
        (status = 204, description = "Reading List deleted; entries cascade"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Reading List not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn delete_reading_list_documentation() {}

/// Documentation-only operation for the live Reading List reader.
#[utoipa::path(
    get,
    path = "/api/v2/reading-lists/{list_id}/reader",
    tag = "reading-lists",
    params(("list_id" = i32, Path, description = "Owned Reading List identifier")),
    responses(
        (status = 200, description = "Reader with canonical availability", body = ReadingListReader),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Reading List not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn read_reading_list_documentation() {}

async fn lock_reader(tx: &Transaction<'_>, user_id: i32) -> Result<(), ApiError> {
    tx.execute(
        "SELECT pg_advisory_xact_lock($1,$2)",
        &[&QUEUE_LOCK_NAMESPACE, &user_id],
    )
    .await
    .map_err(db::query_error)?;
    Ok(())
}

fn validate_name(name: &str) -> Result<String, ApiError> {
    let name = name.trim();
    if name.is_empty() || name.chars().count() > 200 {
        return Err(ApiError::BadRequest(
            "Reading List name must be between 1 and 200 characters".to_string(),
        ));
    }
    Ok(name.to_string())
}

fn validate_mode(mode: Option<&str>) -> Result<String, ApiError> {
    match mode.unwrap_or("loose") {
        "strict" => Ok("strict".to_string()),
        "loose" => Ok("loose".to_string()),
        _ => Err(ApiError::BadRequest(
            "mode must be strict or loose".to_string(),
        )),
    }
}

async fn owned_issue_ids(
    tx: &Transaction<'_>,
    user_id: i32,
    issue_ids: &[i32],
) -> Result<BTreeSet<i32>, ApiError> {
    let rows = tx
        .query(
            "SELECT i.id FROM issues i JOIN threads t ON t.id=i.thread_id
             WHERE t.user_id=$1 AND i.id=ANY($2::int[])",
            &[&user_id, &issue_ids.to_vec()],
        )
        .await
        .map_err(db::query_error)?;
    Ok(rows.iter().map(|row| row.get(0)).collect())
}

async fn load_entries(
    tx: &Transaction<'_>,
    list_id: i32,
) -> Result<Vec<ReadingListEntry>, ApiError> {
    let rows = tx
        .query(
            "SELECT e.id, e.position, e.issue_id, i.thread_id, t.title, i.issue_number,
                    i.status, e.is_checkpoint, e.gate, e.skipped,
                    e.checkpoint_target_issue_ids::text
             FROM custom_cbl_entries e
             JOIN issues i ON i.id=e.issue_id
             JOIN threads t ON t.id=i.thread_id
             WHERE e.list_id=$1
             ORDER BY e.position, e.id",
            &[&list_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(rows
        .iter()
        .map(|row| ReadingListEntry {
            id: row.get(0),
            position: row.get(1),
            issue_id: row.get(2),
            thread_id: row.get(3),
            series_name: row.get(4),
            issue_number: row.get(5),
            status: row.get(6),
            is_checkpoint: row.get(7),
            gate: row.get(8),
            skipped: row.get(9),
            checkpoint_target_issue_ids: serde_json::from_str::<Vec<i32>>(
                &row.get::<_, String>(10),
            )
            .unwrap_or_default(),
        })
        .collect())
}

async fn load_list(
    conn: &deadpool_postgres::Object,
    list_id: i32,
    user_id: i32,
) -> Result<Option<(i32, String, Option<String>, String, String, String, i32)>, ApiError> {
    let row = conn
        .query_opt(
            "SELECT l.id, l.name, l.description, l.mode, l.created_at::text, l.updated_at::text,
                    l.user_id, count(e.id)::int
             FROM custom_cbl_lists l
             LEFT JOIN custom_cbl_entries e ON e.list_id=l.id
             WHERE l.id=$1 AND l.user_id=$2
             GROUP BY l.id",
            &[&list_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(row.map(|row| {
        (
            row.get(0),
            row.get(1),
            row.get(2),
            row.get(3),
            row.get(4),
            row.get(5),
            row.get(7),
        )
    }))
}

fn list_from_row(
    row: (i32, String, Option<String>, String, String, String, i32),
    user_id: i32,
    entries: Vec<ReadingListEntry>,
) -> ReadingList {
    ReadingList {
        id: row.0,
        user_id,
        name: row.1,
        description: row.2,
        mode: row.3,
        created_at: row.4,
        updated_at: row.5,
        issue_count: row.6,
        entries,
    }
}

/// `GET /api/v2/reading-lists`
pub async fn list_reading_lists(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> Result<Json<Vec<ReadingListSummary>>, ApiError> {
    let conn = db::checkout(&state).await?;
    let rows = conn
        .query(
            "SELECT l.id, l.name, l.description, l.mode, l.updated_at::text,
                    (SELECT count(*)::int FROM custom_cbl_entries e WHERE e.list_id=l.id)
             FROM custom_cbl_lists l
             WHERE l.user_id=$1
             ORDER BY lower(l.name), l.id",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;
    Ok(Json(
        rows.iter()
            .map(|row| ReadingListSummary {
                id: row.get(0),
                name: row.get(1),
                description: row.get(2),
                mode: row.get(3),
                updated_at: row.get(4),
                issue_count: row.get(5),
            })
            .collect(),
    ))
}

/// `GET /api/v2/reading-lists/{list_id}`
pub async fn get_reading_list(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i32>,
) -> Result<Json<ReadingList>, ApiError> {
    let conn = db::checkout(&state).await?;
    let Some(row) = load_list(&conn, list_id, user.id()).await? else {
        return Err(ApiError::NotFound("Reading List not found".to_string()));
    };
    let entries = load_entries_conn(&conn, list_id).await?;
    Ok(Json(list_from_row(row, user.id(), entries)))
}

/// `POST /api/v2/reading-lists`
pub async fn create_reading_list(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<ReadingListWrite>,
) -> Result<(StatusCode, Json<ReadingList>), ApiError> {
    if request.confirmed_predecessor_changes.is_some() {
        return Err(ApiError::Unprocessable(
            "reading_list_confirmation_put_only".to_string(),
        ));
    }
    let name = validate_name(&request.name)?;
    let mode = validate_mode(request.mode.as_deref())?;
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    lock_reader(&tx, user.id()).await?;

    let unique: BTreeSet<i32> = request.issue_ids.iter().copied().collect();
    if unique.len() != request.issue_ids.len() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(ApiError::BadRequest("issue_ids must be unique".to_string()));
    }
    let owned = owned_issue_ids(&tx, user.id(), &request.issue_ids).await?;
    if owned.len() != request.issue_ids.len() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(ApiError::NotFound("Issue not found".to_string()));
    }

    let row = tx
        .query_one(
            "INSERT INTO custom_cbl_lists (user_id, name, description, mode, created_at, updated_at)
             VALUES ($1,$2,$3,$4,NOW(),NOW())
             RETURNING id, created_at::text, updated_at::text",
            &[
                &user.id(),
                &name,
                &request.description,
                &mode,
            ],
        )
        .await
        .map_err(db::query_error)?;
    let list_id: i32 = row.get(0);
    let checkpoints: BTreeSet<i32> = request
        .checkpoint_issue_ids
        .clone()
        .unwrap_or_default()
        .into_iter()
        .collect();
    for (position, issue_id) in request.issue_ids.iter().enumerate() {
        let intent = request
            .entry_intents
            .as_ref()
            .and_then(|intents| intents.get(issue_id));
        let gate = intent.map(|value| value.gate.as_str()).unwrap_or("none");
        if !matches!(gate, "none" | "hold" | "after_previous") {
            tx.rollback().await.map_err(db::query_error)?;
            return Err(ApiError::BadRequest("Invalid gate".to_string()));
        }
        let skipped = intent.is_some_and(|value| value.skipped);
        let targets = request
            .checkpoint_targets
            .as_ref()
            .and_then(|targets| targets.get(issue_id))
            .cloned()
            .unwrap_or_default();
        tx.execute(
            "INSERT INTO custom_cbl_entries
               (list_id, issue_id, position, created_at, is_checkpoint,
                checkpoint_target_issue_ids, gate, skipped)
             VALUES ($1,$2,$3,NOW(),$4,$5::text::json,$6,$7)",
            &[
                &list_id,
                issue_id,
                &(position as i32),
                &checkpoints.contains(issue_id),
                &serde_json::to_string(&targets).map_err(|e| {
                    tracing::debug!(error = ?e, "preserved underlying error before mapping");
                    ApiError::Internal("Invalid checkpoint".to_string())
                })?,
                &gate,
                &skipped,
            ],
        )
        .await
        .map_err(db::query_error)?;
    }

    graph_preflight(&tx, user).await?;
    let entries = load_entries(&tx, list_id).await?;
    let list = list_from_row(
        (
            list_id,
            name,
            request.description,
            mode,
            row.get(1),
            row.get(2),
            entries.len() as i32,
        ),
        user.id(),
        entries,
    );
    tx.commit().await.map_err(db::query_error)?;
    Ok((StatusCode::CREATED, Json(list)))
}

async fn graph_preflight(tx: &Transaction<'_>, user: AuthenticatedUser) -> Result<(), ApiError> {
    let inputs = option_inputs::load_inputs_in_transaction(tx, user).await?;
    let names = inputs
        .lists
        .iter()
        .map(|list| (list.list_id, list.name.clone()))
        .collect();
    ValidatedReadingInputs::new(inputs.clone(), &names)
        .map_err(|error| crate::reading_graph::cycle_conflict(error, &inputs))?;
    Ok(())
}

/// An authoritative Reading List must not be removed while an owned Plan
/// still points to its immutable identity. A same-name replacement is not a
/// substitute: this would otherwise strand a Plan with HTTP 409 forever.
/// Reuse this preflight in graph repairs, not just the normal DELETE route.
pub(crate) async fn ensure_list_unlinked(
    tx: &Transaction<'_>,
    user_id: i32,
    list_id: i32,
) -> Result<(), ApiError> {
    let raw_source_path = format!("custom-cbl:{list_id}");
    let linked_plan = tx
        .query_opt(
            "SELECT p.id, p.name FROM reading_plan_sources s
         JOIN continuity_plans p ON p.id=s.plan_id
         WHERE p.user_id=$1 AND (s.custom_cbl_list_id=$2 OR s.raw_source_path=$3)
         ORDER BY p.id LIMIT 1",
            &[&user_id, &list_id, &raw_source_path],
        )
        .await
        .map_err(db::query_error)?;
    if let Some(row) = linked_plan {
        let plan_id: i32 = row.get(0);
        let plan_name: String = row.get(1);
        return Err(ApiError::Conflict(format!(
                "Reading List is authoritative for Reading Plan \"{plan_name}\" (#{plan_id}). Relink that plan before deleting the list; nothing was changed."
            )));
    }
    Ok(())
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ReadingListPredecessorChange {
    pub issue_id: i32,
    pub issue_name: String,
    pub before_issue_ids: Vec<i32>,
    pub before_issue_names: Vec<String>,
    pub after_issue_ids: Vec<i32>,
    pub after_issue_names: Vec<String>,
}

fn stored_requirements(mode: &str, entries: &[ReadingListEntry]) -> BTreeMap<i32, Vec<i32>> {
    let mut results = BTreeMap::new();
    let mut earlier = Vec::<i32>::new();
    let mut hold = BTreeSet::<i32>::new();
    for entry in entries {
        if entry.skipped {
            continue;
        }
        let mut sources = hold.clone();
        if mode == "strict" || entry.gate == "hold" {
            sources.extend(&earlier);
        }
        if entry.gate == "after_previous" {
            if let Some(last) = earlier.last() {
                sources.insert(*last);
            }
        }
        results.insert(
            entry.issue_id,
            earlier
                .iter()
                .copied()
                .filter(|id| sources.contains(id))
                .collect(),
        );
        earlier.push(entry.issue_id);
        if entry.gate == "hold" {
            hold.extend(&earlier);
        }
    }
    results
}

fn predecessor_changes(
    before: &BTreeMap<i32, Vec<i32>>,
    after: &BTreeMap<i32, Vec<i32>>,
    labels: &BTreeMap<i32, String>,
) -> Vec<ReadingListPredecessorChange> {
    let ids: BTreeSet<i32> = before.keys().chain(after.keys()).copied().collect();
    ids.into_iter()
        .filter_map(|issue_id| {
            let old = before.get(&issue_id).cloned().unwrap_or_default();
            let new = after.get(&issue_id).cloned().unwrap_or_default();
            if old == new {
                return None;
            }
            let name = |id: &i32| {
                labels
                    .get(id)
                    .cloned()
                    .unwrap_or_else(|| format!("Issue #{id}"))
            };
            Some(ReadingListPredecessorChange {
                issue_id,
                issue_name: name(&issue_id),
                before_issue_names: old.iter().map(&name).collect(),
                after_issue_names: new.iter().map(&name).collect(),
                before_issue_ids: old,
                after_issue_ids: new,
            })
        })
        .collect()
}

fn confirmed_changes_match(
    actual: &[ReadingListPredecessorChange],
    confirmed: &[ReadingListPredecessorChange],
) -> bool {
    let key = |row: &ReadingListPredecessorChange| {
        let mut before = row.before_issue_ids.clone();
        let mut after = row.after_issue_ids.clone();
        before.sort();
        after.sort();
        (row.issue_id, before, after)
    };
    let mut left: Vec<_> = actual.iter().map(&key).collect();
    let mut right: Vec<_> = confirmed.iter().map(&key).collect();
    left.sort();
    right.sort();
    left == right
}

/// PUT /api/v2/reading-lists/{list_id}
///
/// Replaces only this owner's list. Requires an exact structured acknowledgment
/// when the persistent predecessor constraints change. A cycle/invalid-target
/// error leaves all rows as they were because the transaction never commits.
pub async fn update_reading_list(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i32>,
    Json(request): Json<ReadingListWrite>,
) -> Result<axum::response::Response, ApiError> {
    use axum::response::IntoResponse;

    let name = validate_name(&request.name)?;
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
            "SELECT name,description,mode,created_at::text FROM custom_cbl_lists
         WHERE id=$1 AND user_id=$2 FOR UPDATE",
            &[&list_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound("Reading List not found".to_string()))?;
    let current_mode: String = row.get(2);
    let mode = validate_mode(request.mode.as_deref().or(Some(&current_mode)))?;
    let old_entries = load_entries(&tx, list_id).await?;
    let old_requirements = stored_requirements(&current_mode, &old_entries);
    let old_by_issue: BTreeMap<i32, ReadingListEntry> = old_entries
        .iter()
        .cloned()
        .map(|entry| (entry.issue_id, entry))
        .collect();

    let unique: BTreeSet<i32> = request.issue_ids.iter().copied().collect();
    if unique.len() != request.issue_ids.len() {
        return Err(ApiError::BadRequest("issue_ids must be unique".into()));
    }
    let owned = owned_issue_ids(&tx, user.id(), &request.issue_ids).await?;
    if owned != unique {
        return Err(ApiError::NotFound("Issue not found".into()));
    }
    let checkpoints: BTreeSet<i32> = request
        .checkpoint_issue_ids
        .as_ref()
        .map(|ids| ids.iter().copied().collect())
        .unwrap_or_else(|| {
            old_entries
                .iter()
                .filter(|entry| entry.is_checkpoint)
                .map(|entry| entry.issue_id)
                .collect()
        });
    if !checkpoints.is_subset(&unique) {
        return Err(ApiError::Unprocessable(
            "custom_cbl_invalid_checkpoint_targets".to_string(),
        ));
    }
    tx.execute(
        "UPDATE custom_cbl_lists
         SET name=$3,description=$4,mode=$5,updated_at=NOW()
         WHERE id=$1 AND user_id=$2",
        &[&list_id, &user.id(), &name, &request.description, &mode],
    )
    .await
    .map_err(db::query_error)?;
    tx.execute(
        "DELETE FROM custom_cbl_entries WHERE list_id=$1",
        &[&list_id],
    )
    .await
    .map_err(db::query_error)?;

    for (position, issue_id) in request.issue_ids.iter().enumerate() {
        let old = old_by_issue.get(issue_id);
        let intent = request
            .entry_intents
            .as_ref()
            .and_then(|intents| intents.get(issue_id));
        let gate = intent
            .map(|entry| entry.gate.as_str())
            .or_else(|| old.map(|entry| entry.gate.as_str()))
            .unwrap_or("none");
        if !matches!(gate, "none" | "hold" | "after_previous") {
            return Err(ApiError::BadRequest("Invalid gate".into()));
        }
        let skipped = intent
            .map(|entry| entry.skipped)
            .or_else(|| old.map(|entry| entry.skipped))
            .unwrap_or(false);
        let targets: Vec<i32> = match request.checkpoint_targets.as_ref() {
            Some(requested) => requested.get(issue_id).cloned().unwrap_or_default(),
            None => {
                if checkpoints.contains(issue_id) {
                    old.map(|entry| {
                        entry
                            .checkpoint_target_issue_ids
                            .iter()
                            .copied()
                            .filter(|target| unique.contains(target))
                            .collect()
                    })
                    .unwrap_or_else(|| {
                        request
                            .issue_ids
                            .get(position + 1)
                            .copied()
                            .into_iter()
                            .collect()
                    })
                } else {
                    vec![]
                }
            }
        };
        let valid: BTreeSet<i32> = targets.iter().copied().collect();
        if targets.len() != valid.len()
            || !valid.is_subset(&unique)
            || valid.contains(issue_id)
            || (!checkpoints.contains(issue_id) && !targets.is_empty())
        {
            return Err(ApiError::Unprocessable(
                "custom_cbl_invalid_checkpoint_targets".to_string(),
            ));
        }
        let targets_json = serde_json::to_string(&targets).map_err(|e| {
            tracing::debug!(error = ?e, "preserved underlying error before mapping");
            ApiError::Internal("Invalid checkpoint".into())
        })?;
        tx.execute(
            "INSERT INTO custom_cbl_entries
             (list_id,issue_id,position,created_at,is_checkpoint,checkpoint_target_issue_ids,gate,skipped)
             VALUES ($1,$2,$3,NOW(),$4,$5::text::json,$6,$7)",
            &[&list_id, issue_id, &(position as i32), &(!targets.is_empty()),
              &targets_json, &gate, &skipped],
        ).await.map_err(db::query_error)?;
    }

    graph_preflight(&tx, user).await?;
    let entries = load_entries(&tx, list_id).await?;
    let new_requirements = stored_requirements(&mode, &entries);
    let labels: BTreeMap<i32, String> = old_entries
        .iter()
        .chain(entries.iter())
        .map(|entry| {
            (
                entry.issue_id,
                format!("{} #{}", entry.series_name, entry.issue_number),
            )
        })
        .collect();
    let changes = predecessor_changes(&old_requirements, &new_requirements, &labels);
    let confirmation: Vec<ReadingListPredecessorChange> = request
        .confirmed_predecessor_changes
        .as_ref()
        .map_or(Ok(Vec::new()), |value| {
            serde_json::from_value(value.clone()).map_err(|e| {
                tracing::debug!(error = ?e, "preserved underlying error before mapping");
                ApiError::Unprocessable("Invalid predecessor confirmation".into())
            })
        })?;
    if !changes.is_empty() && !confirmed_changes_match(&changes, &confirmation) {
        return Ok((
            StatusCode::CONFLICT,
            Json(serde_json::json!({
                "detail": {
                    "code": "reading_list_predecessor_confirmation_required",
                    "predecessor_changes": changes
                }
            })),
        )
            .into_response());
    }

    let list = list_from_row(
        (
            list_id,
            name,
            request.description,
            mode,
            row.get(3),
            String::new(),
            entries.len() as i32,
        ),
        user.id(),
        entries,
    );
    let mut json = serde_json::to_value(&list).map_err(|e| {
        tracing::debug!(error = ?e, "preserved underlying error before mapping");
        ApiError::Internal("Reading List serialization failed".into())
    })?;
    json["predecessor_changes"] = serde_json::to_value(&changes).unwrap_or_default();
    json["warnings"] = serde_json::json!([]);
    tx.commit().await.map_err(db::query_error)?;
    // The metadata timestamp is selected after commit so clients get the
    // actual persisted optimistic token rather than a manufactured clock.
    let conn = db::checkout(&state).await?;
    if let Some(row) = load_list(&conn, list_id, user.id()).await? {
        json["updated_at"] = serde_json::json!(row.5);
    }
    Ok((StatusCode::OK, Json(json)).into_response())
}

#[utoipa::path(
    put,
    path = "/api/v2/reading-lists/{list_id}",
    tag = "reading-lists",
    params(("list_id" = i32, Path, description = "Owned Reading List identifier")),
    request_body = ReadingListWrite,
    responses(
        (status = 200, description = "Updated owner-scoped Reading List", body = ReadingList),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Reading List not found"),
        (status = 409, description = "Predecessor changes must be acknowledged"),
        (status = 422, description = "Invalid Issue or checkpoint")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn update_reading_list_documentation() {}

/// `DELETE /api/v2/reading-lists/{list_id}`
pub async fn delete_reading_list(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i32>,
) -> Result<StatusCode, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    lock_reader(&tx, user.id()).await?;
    ensure_list_unlinked(&tx, user.id(), list_id).await?;
    let deleted = tx
        .execute(
            "DELETE FROM custom_cbl_lists WHERE id=$1 AND user_id=$2",
            &[&list_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    if deleted == 0 {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(ApiError::NotFound("Reading List not found".to_string()));
    }
    tx.commit().await.map_err(db::query_error)?;
    Ok(StatusCode::NO_CONTENT)
}

/// `GET /api/v2/reading-lists/{list_id}/reader`
pub async fn read_reading_list(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i32>,
) -> Result<Json<ReadingListReader>, ApiError> {
    let conn = db::checkout(&state).await?;
    let Some(row) = load_list(&conn, list_id, user.id()).await? else {
        return Err(ApiError::NotFound("Reading List not found".to_string()));
    };
    let entries = load_entries_conn(&conn, list_id).await?;
    drop(conn);

    let validated = option_inputs::load_option_inputs_contained(&state, user).await?;
    let evaluated = reading_eligibility::evaluate(&validated)?;
    let inputs = validated.inputs();
    let titles: BTreeMap<i32, String> = inputs
        .core
        .threads
        .iter()
        .map(|thread| (thread.id, thread.title.clone()))
        .collect();
    let numbers: BTreeMap<i32, String> = inputs
        .core
        .issues
        .iter()
        .map(|issue| (issue.id, issue.issue_number.clone()))
        .collect();
    let thread_of: BTreeMap<i32, i32> = inputs
        .core
        .issues
        .iter()
        .map(|issue| (issue.id, issue.thread_id))
        .collect();
    let list_names: BTreeMap<i32, String> = inputs
        .lists
        .iter()
        .map(|list| (list.list_id, list.name.clone()))
        .collect();
    let excluded = &inputs.excluded_issue_ids;

    let mut projected = vec![];
    for entry in entries {
        let availability;
        let mut explanation = None;
        if entry.status == "read" {
            availability = "read".into();
        } else if excluded.contains(&entry.issue_id) {
            availability = "excluded".into();
        } else if let Some(state) = evaluated.get(&entry.thread_id) {
            if entry.issue_id != state.next_issue_id.unwrap_or_default() {
                availability = "later".into();
            } else {
                availability = if state.eligible {
                    "available"
                } else {
                    "blocked"
                }
                .into();
                let mut reasons = vec![];
                let mut dependencies = vec![];
                for gate in
                    reading_blocker_projection::describe_blocker_gates(state.blockers.clone())
                {
                    let origin = match gate.blocker.kind.as_str() {
                        "prerequisite" => {
                            if gate.blocker.origin.as_deref() == Some("reader") {
                                "Reader prerequisite".to_string()
                            } else {
                                "Converted prerequisite".to_string()
                            }
                        }
                        kind => {
                            let label = match kind {
                                "strict_order" => "Strict order",
                                "hold" => "Hold",
                                "after_previous" => "Wait for previous",
                                "reading_cycle" => "Reading constraint cycle",
                                other => other,
                            };
                            let list = gate
                                .blocker
                                .list_id
                                .and_then(|id| list_names.get(&id))
                                .map(String::as_str)
                                .unwrap_or("Reading List");
                            format!("{label} in {list}")
                        }
                    };
                    for issue_id in gate.described_issue_ids {
                        let series = thread_of
                            .get(&issue_id)
                            .and_then(|id| titles.get(id))
                            .cloned()
                            .unwrap_or_else(|| "Required series".to_string());
                        let number = numbers.get(&issue_id).cloned().unwrap_or_default();
                        let label = format!("{origin}: waiting on {series} #{number}");
                        reasons.push(label.clone());
                        dependencies.push(ReadingListDependency {
                            thread_id: *thread_of.get(&issue_id).unwrap_or(&0),
                            thread_title: series,
                            issue_number: number,
                            label,
                            issue_id: Some(issue_id),
                        });
                    }
                }
                if state.next_issue_id.is_none() {
                    reasons.push("No available unread issue".to_string());
                }
                explanation = Some(ReadingListBlockerExplanation {
                    is_blocked: !state.eligible,
                    blocking_reasons: reasons,
                    blocking_dependencies: dependencies,
                });
            }
        } else {
            availability = "inactive".into();
        }
        projected.push(ReadingListReaderEntry {
            id: entry.id,
            position: entry.position,
            issue_id: entry.issue_id,
            thread_id: entry.thread_id,
            series_name: entry.series_name,
            issue_number: entry.issue_number,
            status: entry.status,
            is_checkpoint: entry.is_checkpoint,
            gate: entry.gate,
            skipped: entry.skipped,
            checkpoint_target_issue_ids: entry.checkpoint_target_issue_ids,
            availability,
            explanation,
        });
    }
    Ok(Json(ReadingListReader {
        list_id: row.0,
        name: row.1,
        mode: row.3,
        execution_mode: "option_e".to_string(),
        entries: projected,
    }))
}

async fn load_entries_conn(
    conn: &deadpool_postgres::Object,
    list_id: i32,
) -> Result<Vec<ReadingListEntry>, ApiError> {
    let rows = conn
        .query(
            "SELECT e.id, e.position, e.issue_id, i.thread_id, t.title, i.issue_number,
                    i.status, e.is_checkpoint, e.gate, e.skipped,
                    e.checkpoint_target_issue_ids::text
             FROM custom_cbl_entries e
             JOIN issues i ON i.id=e.issue_id
             JOIN threads t ON t.id=i.thread_id
             WHERE e.list_id=$1
             ORDER BY e.position, e.id",
            &[&list_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(rows
        .iter()
        .map(|row| ReadingListEntry {
            id: row.get(0),
            position: row.get(1),
            issue_id: row.get(2),
            thread_id: row.get(3),
            series_name: row.get(4),
            issue_number: row.get(5),
            status: row.get(6),
            is_checkpoint: row.get(7),
            gate: row.get(8),
            skipped: row.get(9),
            checkpoint_target_issue_ids: serde_json::from_str::<Vec<i32>>(
                &row.get::<_, String>(10),
            )
            .unwrap_or_default(),
        })
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn metadata_validation_rejects_empty_names_and_unknown_modes() {
        assert!(validate_name("   ").is_err());
        assert_eq!(validate_name(" Julix ").unwrap(), "Julix");
        assert!(validate_mode(Some("nonsense")).is_err());
        assert_eq!(validate_mode(None).unwrap(), "loose");
        assert_eq!(validate_mode(Some("strict")).unwrap(), "strict");
    }
}
