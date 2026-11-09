//! Canonical owner-scoped issue-dependency authoring.
//!
//! The Dependency Builder previously wrote reader prerequisites through the
//! Python `/api/v1/dependencies/` surface, which only checked for cycles made
//! of dependency edges alone. A dependency whose endpoints are also ordered
//! by a strict Reading List or by natural series order could therefore be
//! committed and only surface later as a global `ReadingCycleError` outage
//! (#4684, #4656). These canonical Rust `/api/v2` resources validate the
//! complete projected Option E graph — series order, strict/loose list order,
//! gates, prerequisites and cross-list dependencies — inside the write
//! transaction, before commit, so a cyclic edge can never be persisted.
//!
//! A rejected write rolls back with nothing changed and names the offending
//! series/issues and edge provenance. Successful writes store the same
//! reader-authored provenance as the Python surface (`origin='reader'`,
//! reviewed classification, explicit provenance) and refresh the denormalized
//! `threads.is_blocked` flags in the same transaction. Deletes are
//! owner-scoped and never touch issues, read state, ratings or history.

use crate::{
    auth::AuthenticatedUser, db, issue_service, option_inputs,
    reading_constraints::ValidatedReadingInputs, ApiError, AppState,
};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::sync::Arc;
use tokio_postgres::Transaction;

const QUEUE_LOCK_NAMESPACE: i32 = 699001;
const READER_AUTHORED_PROVENANCE: &str = "Reader-authored through the Dependency Builder";

/// Flat wire request mirroring the Python `DependencyCreate` payload so the
/// Dependency Builder migrates without changing its semantics.
#[derive(Debug, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct DependencyCreateRequest {
    pub source_type: String,
    pub source_id: i32,
    pub target_type: String,
    pub target_id: i32,
}

/// Issue-level dependency response mirroring the Python `DependencyResponse`
/// fields the Dependency Builder consumes (`warning`, labels, thread ids).
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct DependencyResponse {
    pub id: i32,
    pub source_issue_id: Option<i32>,
    pub target_issue_id: Option<i32>,
    pub source_thread_id: Option<i32>,
    pub target_thread_id: Option<i32>,
    pub is_issue_level: bool,
    pub created_at: String,
    pub note: Option<String>,
    pub source_label: Option<String>,
    pub target_label: Option<String>,
    pub source_issue_thread_id: Option<i32>,
    pub target_issue_thread_id: Option<i32>,
    pub warning: Option<String>,
}

/// Wire parity with Python `ThreadDependenciesResponse`
/// (`app/schemas/dependency.py`): the `blocking` list holds edges where this
/// thread's issues block others, `blocked_by` holds edges where this thread's
/// issues are blocked. Each entry is the enriched `DependencyResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ThreadDependenciesResponse {
    pub blocking: Vec<DependencyResponse>,
    pub blocked_by: Vec<DependencyResponse>,
}

const THREAD_OWNED_SQL: &str = "SELECT t.id FROM threads t WHERE t.id = $1 AND t.user_id = $2";

const THREAD_BLOCKING_SQL: &str = "SELECT d.id, d.source_issue_id, d.target_issue_id, d.created_at::text, d.note, si.thread_id, ti.thread_id, st.title, si.issue_number, tt.title, ti.issue_number FROM dependencies d JOIN issues si ON si.id = d.source_issue_id JOIN threads st ON st.id = si.thread_id JOIN issues ti ON ti.id = d.target_issue_id JOIN threads tt ON tt.id = ti.thread_id WHERE si.thread_id = $1 AND st.user_id = $2 AND tt.user_id = $2 ORDER BY d.id";

const THREAD_BLOCKED_BY_SQL: &str = "SELECT d.id, d.source_issue_id, d.target_issue_id, d.created_at::text, d.note, si.thread_id, ti.thread_id, st.title, si.issue_number, tt.title, ti.issue_number FROM dependencies d JOIN issues si ON si.id = d.source_issue_id JOIN threads st ON st.id = si.thread_id JOIN issues ti ON ti.id = d.target_issue_id JOIN threads tt ON tt.id = ti.thread_id WHERE ti.thread_id = $1 AND st.user_id = $2 AND tt.user_id = $2 ORDER BY d.id";

fn thread_row_to_response(row: &tokio_postgres::Row) -> DependencyResponse {
    let source_thread_id: i32 = row.get(5);
    let target_thread_id: i32 = row.get(6);
    let source_thread_title: String = row.get(7);
    let source_issue_number: String = row.get(8);
    let target_thread_title: String = row.get(9);
    let target_issue_number: String = row.get(10);
    DependencyResponse {
        id: row.get(0),
        source_issue_id: Some(row.get(1)),
        target_issue_id: Some(row.get(2)),
        source_thread_id: Some(source_thread_id),
        target_thread_id: Some(target_thread_id),
        is_issue_level: true,
        created_at: row.get(3),
        note: row.get(4),
        source_label: Some(issue_label(&source_thread_title, &source_issue_number)),
        target_label: Some(issue_label(&target_thread_title, &target_issue_number)),
        source_issue_thread_id: Some(source_thread_id),
        target_issue_thread_id: Some(target_thread_id),
        warning: None,
    }
}

fn bad_request(detail: &str) -> ApiError {
    ApiError(StatusCode::BAD_REQUEST, detail.to_string())
}

fn not_found(detail: &str) -> ApiError {
    ApiError(StatusCode::NOT_FOUND, detail.to_string())
}

fn validate_create_request(request: &DependencyCreateRequest) -> Result<(i32, i32), ApiError> {
    if request.source_type == "thread" || request.target_type == "thread" {
        if request.source_type != request.target_type {
            return Err(bad_request(
                "Mixed thread/issue dependencies are not supported",
            ));
        }
        return Err(bad_request(
            "Thread-level dependencies are no longer supported. \
             Create an issue-level dependency instead: use the last issue \
             of the source thread and the first issue of the target thread.",
        ));
    }
    if request.source_type != "issue" || request.target_type != "issue" {
        return Err(bad_request("source_type and target_type must be 'issue'"));
    }
    if request.source_id == request.target_id {
        return Err(bad_request("Cannot create dependency on self"));
    }
    Ok((request.source_id, request.target_id))
}

fn issue_label(thread_title: &str, issue_number: &str) -> String {
    format!("{thread_title} #{issue_number}")
}

fn ahead_warning(
    target_issue_number: &str,
    target_position: i32,
    next_issue_number: &str,
    next_position: i32,
) -> Option<String> {
    if target_position <= next_position {
        return None;
    }
    let issues_ahead = target_position - next_position;
    let issue_word = if issues_ahead == 1 { "issue" } else { "issues" };
    Some(format!(
        "Target issue #{target_issue_number} is not yet the next unread \
         (current next unread: #{next_issue_number}). This dependency will \
         block when the target thread reaches it in {issues_ahead} {issue_word}."
    ))
}

struct OwnedIssue {
    thread_id: i32,
    thread_title: String,
    issue_number: String,
    position: i32,
}

async fn owned_issue(
    tx: &Transaction<'_>,
    user_id: i32,
    issue_id: i32,
) -> Result<Option<OwnedIssue>, ApiError> {
    let row = tx
        .query_opt(
            "SELECT t.id, t.title, i.issue_number, i.position
             FROM issues i JOIN threads t ON t.id = i.thread_id
             WHERE i.id = $1 AND t.user_id = $2",
            &[&issue_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(row.map(|row| OwnedIssue {
        thread_id: row.get(0),
        thread_title: row.get(1),
        issue_number: row.get(2),
        position: row.get(3),
    }))
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

/// Combined-graph preflight: the projected graph after this write must be
/// acyclic, or the transaction rolls back and nothing is changed.
async fn graph_preflight(tx: &Transaction<'_>, user: AuthenticatedUser) -> Result<(), ApiError> {
    let inputs = option_inputs::load_inputs_in_transaction(tx, user).await?;
    let names: BTreeMap<i32, String> = inputs
        .lists
        .iter()
        .map(|list| (list.list_id, list.name.clone()))
        .collect();
    ValidatedReadingInputs::new(inputs.clone(), &names)
        .map_err(|error| crate::reading_graph::cycle_conflict(error, &inputs))?;
    Ok(())
}

/// `POST /api/v2/dependencies/`
pub async fn create_dependency(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<DependencyCreateRequest>,
) -> Result<(StatusCode, Json<DependencyResponse>), ApiError> {
    let (source_issue_id, target_issue_id) = validate_create_request(&request)?;
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    lock_reader(&tx, user.id()).await?;

    let Some(source) = owned_issue(&tx, user.id(), source_issue_id).await? else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(not_found("Issue not found"));
    };
    let Some(target) = owned_issue(&tx, user.id(), target_issue_id).await? else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(not_found("Issue not found"));
    };

    let existing = tx
        .query_opt(
            "SELECT id FROM dependencies
             WHERE source_issue_id = $1 AND target_issue_id = $2",
            &[&source_issue_id, &target_issue_id],
        )
        .await
        .map_err(db::query_error)?;
    if existing.is_some() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("Dependency already exists"));
    }

    let next_unread = tx
        .query_opt(
            "SELECT i.issue_number, i.position FROM threads t
             JOIN issues i ON i.id = t.next_unread_issue_id
             WHERE t.id = $1",
            &[&target.thread_id],
        )
        .await
        .map_err(db::query_error)?;
    let mut warning: Option<String> = None;
    if let Some(row) = next_unread {
        let next_number: String = row.get(0);
        let next_position: i32 = row.get(1);
        if target.position < next_position {
            tx.rollback().await.map_err(db::query_error)?;
            return Err(bad_request(&format!(
                "Target issue #{} has already been read in {} (current next unread: #{}). \
                 This dependency would never activate. Did you mean to target issue #{}?",
                target.issue_number, target.thread_title, next_number, next_number
            )));
        }
        warning = ahead_warning(
            &target.issue_number,
            target.position,
            &next_number,
            next_position,
        );
    }

    let row = tx
        .query_one(
            "INSERT INTO dependencies
               (source_issue_id, target_issue_id, origin, classification, provenance, created_at)
             VALUES ($1,$2,'reader','A',$3,NOW())
             RETURNING id, created_at::text",
            &[
                &source_issue_id,
                &target_issue_id,
                &READER_AUTHORED_PROVENANCE,
            ],
        )
        .await
        .map_err(db::query_error)?;
    let dependency_id: i32 = row.get(0);
    let created_at: String = row.get(1);

    issue_service::refresh_blocked_threads(&tx, user.id()).await?;
    graph_preflight(&tx, user).await?;

    let response = DependencyResponse {
        id: dependency_id,
        source_issue_id: Some(source_issue_id),
        target_issue_id: Some(target_issue_id),
        source_thread_id: Some(source.thread_id),
        target_thread_id: Some(target.thread_id),
        is_issue_level: true,
        created_at,
        note: None,
        source_label: Some(issue_label(&source.thread_title, &source.issue_number)),
        target_label: Some(issue_label(&target.thread_title, &target.issue_number)),
        source_issue_thread_id: Some(source.thread_id),
        target_issue_thread_id: Some(target.thread_id),
        warning,
    };
    tx.commit().await.map_err(db::query_error)?;
    Ok((StatusCode::CREATED, Json(response)))
}

/// `DELETE /api/v2/dependencies/{dependency_id}`
///
/// Owner-scoped: another reader's edge is indistinguishable from a missing
/// one (404), and only the constraint row is removed.
pub async fn delete_dependency(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(dependency_id): Path<i32>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    lock_reader(&tx, user.id()).await?;
    let removed = tx
        .execute(
            "DELETE FROM dependencies d
             USING issues si, threads st, issues ti, threads tt
             WHERE d.id = $1
               AND d.source_issue_id = si.id AND si.thread_id = st.id AND st.user_id = $2
               AND d.target_issue_id = ti.id AND ti.thread_id = tt.id AND tt.user_id = $2",
            &[&dependency_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    if removed == 0 {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(not_found("Dependency not found"));
    }
    issue_service::refresh_blocked_threads(&tx, user.id()).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(serde_json::json!({"message": "Dependency deleted"})))
}

/// `GET /api/v1/threads/{thread_id}/dependencies`
///
/// Lists dependencies where this thread blocks others (`blocking`) and where
/// it is blocked (`blocked_by`). Owner-scoped: a missing or foreign thread is
/// a 404 with the Python detail text. Each direction is one bounded JOIN
/// ordered by dependency id; labels mirror Python `enrich_dependencies`
/// (`"{title} #{issue_number}"`, `is_issue_level=true`).
pub async fn get_thread_dependencies(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(thread_id): Path<i32>,
) -> Result<Json<ThreadDependenciesResponse>, ApiError> {
    let connection = db::checkout(&state).await?;
    let owned = connection
        .query_opt(THREAD_OWNED_SQL, &[&thread_id, &user.id()])
        .await
        .map_err(db::query_error)?;
    if owned.is_none() {
        return Err(ApiError(
            StatusCode::NOT_FOUND,
            format!("Thread {thread_id} not found"),
        ));
    }
    let blocking_rows = connection
        .query(THREAD_BLOCKING_SQL, &[&thread_id, &user.id()])
        .await
        .map_err(db::query_error)?;
    let blocking = blocking_rows.iter().map(thread_row_to_response).collect();
    let blocked_by_rows = connection
        .query(THREAD_BLOCKED_BY_SQL, &[&thread_id, &user.id()])
        .await
        .map_err(db::query_error)?;
    let blocked_by = blocked_by_rows.iter().map(thread_row_to_response).collect();
    Ok(Json(ThreadDependenciesResponse {
        blocking,
        blocked_by,
    }))
}

/// Documentation-only operation for the mounted dependency create.
#[utoipa::path(
    post,
    path = "/api/v2/dependencies/",
    tag = "dependencies",
    description = "Create one owner-scoped issue-level reader dependency after combined reading-graph preflight. The complete projected Option E graph is validated inside the write transaction before commit; a cyclic edge is rejected with the named series/issues and nothing is changed.",
    request_body = DependencyCreateRequest,
    responses(
        (status = 201, description = "Created dependency", body = DependencyResponse),
        (status = 400, description = "Invalid or duplicate dependency"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Issue not found"),
        (status = 409, description = "Reading constraint cycle: nothing was changed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn create_dependency_documentation() {}

/// Documentation-only operation for the mounted dependency delete.
#[utoipa::path(
    delete,
    path = "/api/v2/dependencies/{dependency_id}",
    tag = "dependencies",
    description = "Delete one owner-scoped dependency and refresh denormalized blocked flags. Issues, read state, ratings and history are preserved.",
    params(
        ("dependency_id" = i32, Path, description = "Dependency id")
    ),
    responses(
        (status = 200, description = "Deleted"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Dependency not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn delete_dependency_documentation() {}

/// Documentation-only operation for the mounted thread-dependencies read.
#[utoipa::path(
    get,
    path = "/api/v1/threads/{thread_id}/dependencies",
    tag = "dependencies",
    description = "List owner-scoped dependency edges where one thread blocks others and where it is blocked. Wire parity with Python GET /api/v1/threads/{thread_id}/dependencies: {blocking, blocked_by} of enriched DependencyResponse entries ordered by dependency id.",
    params(
        ("thread_id" = i32, Path, description = "Owned thread identifier")
    ),
    responses(
        (status = 200, description = "Thread dependencies", body = ThreadDependenciesResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_thread_dependencies_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;

    fn request(
        source_type: &str,
        source_id: i32,
        target_type: &str,
        target_id: i32,
    ) -> DependencyCreateRequest {
        DependencyCreateRequest {
            source_type: source_type.into(),
            source_id,
            target_type: target_type.into(),
            target_id,
        }
    }

    #[test]
    fn create_validation_mirrors_python_semantics() {
        assert_eq!(
            validate_create_request(&request("issue", 10, "issue", 20)).unwrap(),
            (10, 20)
        );
        let mixed = validate_create_request(&request("issue", 10, "thread", 20)).unwrap_err();
        assert_eq!(mixed.0, StatusCode::BAD_REQUEST);
        assert!(mixed.1.contains("Mixed thread/issue"));
        let thread = validate_create_request(&request("thread", 1, "thread", 2)).unwrap_err();
        assert_eq!(thread.0, StatusCode::BAD_REQUEST);
        assert!(thread.1.contains("no longer supported"));
        let self_edge = validate_create_request(&request("issue", 10, "issue", 10)).unwrap_err();
        assert_eq!(self_edge.0, StatusCode::BAD_REQUEST);
        assert_eq!(self_edge.1, "Cannot create dependency on self");
        let unknown = validate_create_request(&request("volume", 10, "issue", 20)).unwrap_err();
        assert_eq!(unknown.0, StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn create_dependency_persists_reader_edge_through_handler() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _db_guard = crate::test_support::reset_for_test(&state).await;
        let conn = state
            .pool
            .get()
            .await
            .expect("disposable Postgres connection");
        conn.batch_execute(
            "INSERT INTO users (id, username) VALUES (1,'dependency-handler-owner');
             INSERT INTO threads (id,title,format,issues_remaining,queue_position,status,user_id,created_at)
             VALUES (11,'Alpha','comic',0,1,'active',1,NOW()),(12,'Beta','comic',0,2,'active',1,NOW());
             INSERT INTO issues (id,thread_id,issue_number,status,created_at,position)
             VALUES (101,11,'1','unread',NOW(),1),(102,11,'2','unread',NOW(),2),
                    (201,12,'1','unread',NOW(),1),(202,12,'2','unread',NOW(),2);",
        )
        .await
        .expect("canonical dependency fixtures");
        drop(conn);
        let user = crate::auth::AuthenticatedUser::for_test(1);
        let (status, created) = create_dependency(
            State(state.clone()),
            user,
            Json(request("issue", 101, "issue", 201)),
        )
        .await
        .expect("benign dependency creates");
        assert_eq!(status, StatusCode::CREATED);
        assert_eq!(created.0.source_label.as_deref(), Some("Alpha #1"));
        assert_eq!(created.0.target_label.as_deref(), Some("Beta #1"));
        let conn = state.pool.get().await.unwrap();
        let origin: Option<String> = conn
            .query_one(
                "SELECT origin FROM dependencies WHERE id=$1",
                &[&created.0.id],
            )
            .await
            .unwrap()
            .get(0);
        assert_eq!(origin.as_deref(), Some("reader"));
        drop(conn);
        let deleted = delete_dependency(
            State(state.clone()),
            user,
            axum::extract::Path(created.0.id),
        )
        .await
        .expect("owner delete succeeds");
        assert_eq!(deleted.0["message"], "Dependency deleted");
    }

    #[test]
    fn labels_and_ahead_warning_name_actual_issues() {
        assert_eq!(issue_label("B.P.R.D.", "142"), "B.P.R.D. #142");
        assert!(ahead_warning("140", 5, "139", 4).unwrap().contains("#140"));
        assert!(ahead_warning("140", 5, "139", 4)
            .unwrap()
            .contains("1 issue"));
        assert!(ahead_warning("141", 6, "139", 4)
            .unwrap()
            .contains("2 issues"));
        assert!(ahead_warning("139", 4, "139", 4).is_none());
        assert!(ahead_warning("138", 3, "139", 4).is_none());
    }

    #[test]
    fn thread_dependencies_wire_matches_python_shape() {
        let entry = DependencyResponse {
            id: 11,
            source_issue_id: Some(101),
            target_issue_id: Some(201),
            source_thread_id: Some(11),
            target_thread_id: Some(12),
            is_issue_level: true,
            created_at: "2026-11-08 20:19:24.123456".into(),
            note: Some("Note visible in list".into()),
            source_label: Some("Alpha #1".into()),
            target_label: Some("Beta #1".into()),
            source_issue_thread_id: Some(11),
            target_issue_thread_id: Some(12),
            warning: None,
        };
        let value = serde_json::to_value(ThreadDependenciesResponse {
            blocking: vec![entry.clone()],
            blocked_by: vec![],
        })
        .expect("serializable thread dependencies");
        assert!(value["blocking"].is_array());
        assert!(value["blocked_by"].is_array());
        assert_eq!(value["blocking"][0]["source_label"], "Alpha #1");
        assert_eq!(value["blocking"][0]["note"], "Note visible in list");
        assert_eq!(value["blocking"][0]["is_issue_level"], true);
        assert_eq!(value["blocked_by"].as_array().expect("array").len(), 0);
    }

    #[test]
    fn thread_dependencies_sql_preserves_python_parity() {
        assert!(THREAD_OWNED_SQL.contains("t.user_id = $2"));
        for sql in [THREAD_BLOCKING_SQL, THREAD_BLOCKED_BY_SQL] {
            assert!(sql.contains("ORDER BY d.id"), "bounded ordering");
            assert!(sql.contains("st.user_id = $2"), "source owner scope");
            assert!(sql.contains("tt.user_id = $2"), "target owner scope");
            assert!(sql.contains("JOIN issues si"), "source joins");
            assert!(sql.contains("JOIN threads st"), "source thread join");
        }
        assert!(THREAD_BLOCKING_SQL.contains("si.thread_id = $1"));
        assert!(THREAD_BLOCKED_BY_SQL.contains("ti.thread_id = $1"));
        assert!(!THREAD_BLOCKING_SQL.contains(';'));
        assert!(!THREAD_BLOCKED_BY_SQL.contains(';'));
    }

    #[tokio::test]
    async fn thread_dependencies_handler_separates_blocking_and_blocked_by() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _db_guard = crate::test_support::reset_for_test(&state).await;
        let conn = state
            .pool
            .get()
            .await
            .expect("disposable Postgres connection");
        conn.batch_execute(
            "INSERT INTO users (id, username) VALUES (1,'thread-deps-owner');
             INSERT INTO threads (id,title,format,issues_remaining,queue_position,status,user_id,created_at)
             VALUES (21,'Alpha','comic',0,1,'active',1,NOW()),(22,'Beta','comic',0,2,'active',1,NOW());
             INSERT INTO issues (id,thread_id,issue_number,status,created_at,position)
             VALUES (301,21,'1','unread',NOW(),1),(401,22,'1','unread',NOW(),1);
             INSERT INTO dependencies (source_issue_id,target_issue_id,origin,classification,note,created_at)
             VALUES (301,401,'reader','A',NULL,NOW());",
        )
        .await
        .expect("thread dependency fixtures");
        drop(conn);
        let user = crate::auth::AuthenticatedUser::for_test(1);
        let alpha = get_thread_dependencies(State(state.clone()), user, axum::extract::Path(21))
            .await
            .expect("alpha thread dependencies");
        assert_eq!(alpha.0.blocking.len(), 1);
        assert_eq!(alpha.0.blocked_by.len(), 0);
        assert_eq!(alpha.0.blocking[0].target_label.as_deref(), Some("Beta #1"));
        let beta = get_thread_dependencies(State(state.clone()), user, axum::extract::Path(22))
            .await
            .expect("beta thread dependencies");
        assert_eq!(beta.0.blocking.len(), 0);
        assert_eq!(beta.0.blocked_by.len(), 1);
        assert_eq!(
            beta.0.blocked_by[0].source_label.as_deref(),
            Some("Alpha #1")
        );
        let missing = get_thread_dependencies(State(state.clone()), user, axum::extract::Path(999))
            .await
            .expect_err("missing thread is 404");
        assert_eq!(missing.0, StatusCode::NOT_FOUND);
        assert_eq!(missing.1, "Thread 999 not found");
    }
}
