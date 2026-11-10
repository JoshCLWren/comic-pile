//! Native same-path reads for the browser-called issues family (#4845).
//!
//! Migrates the read-only subset of `app/api/issue.py` and
//! `app/api/dependency.py` to the native Rust router with identical
//! method/path and wire contract:
//!
//! * `GET /api/v1/issues/{issue_id}`
//! * `GET /api/v1/issues/{issue_id}/dependencies`
//!
//! The third browser-called read in the family,
//! `GET /api/v1/issues/{issue_id}/comicvine`, reuses the existing
//! [`crate::comicvine_issue::issue_intelligence`] handler, which already
//! serves `GET /api/v2/issues/{issue_id}/comicvine`. Python handlers remain;
//! deployed ingress in `vercel.json` shadows them after this cutover.
//! Read-state mutations (`:markRead`, `:markUnread`, `:move`,
//! `:bulkMarkRead`, `:bulkMarkUnread`) and `GET .../reader-context` stay on
//! Python until their own slices land.
//!
//! Wire parity with Python:
//!
//! * `GET /api/v1/issues/{issue_id}` returns `IssueResponse`
//!   (`id`, `thread_id`, `issue_number`, `position`, `status`, `read_at`,
//!   `created_at`). `read_at`/`created_at` are UTC ISO-8601 strings with
//!   millisecond precision (`YYYY-MM-DD"T"HH24:MI:SS.MS"Z"`), matching the
//!   `to_char` format the existing card projection uses for `read_at`.
//! * `GET /api/v1/issues/{issue_id}/dependencies` returns
//!   `IssueDependenciesResponse` (`issue_id`, `incoming`, `outgoing`).
//!   Each edge carries `dependency_id`, `source_issue_id`,
//!   `source_issue_number`, `source_thread_id`, `source_thread_title`.
//!   Incoming edges are dependencies where this issue is the target and
//!   the source belongs to the caller; outgoing edges are where this issue
//!   is the source and the target belongs to the caller. This mirrors
//!   `dependency_service.get_issue_dependencies`, which filters both
//!   directions to edges whose other endpoint is owned by the caller.
//! * Errors are Python-shaped: `{"detail": "<message>"}` with 401 for
//!   missing/invalid credentials and 404 `Issue {issue_id} not found` for
//!   missing or foreign issues. No per-row fan-out: one owner check plus
//!   one bounded `JOIN` per edge direction.

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::Serialize;
use std::sync::Arc;

/// Wire parity with Python `IssueResponse` (`app/schemas/issue.py`).
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct IssueDetailResponse {
    pub id: i32,
    pub thread_id: i32,
    pub issue_number: String,
    pub position: i32,
    pub status: String,
    pub read_at: Option<String>,
    pub created_at: String,
}

/// Wire parity with Python `IssueDependencyEdge` (`app/schemas/dependency.py`).
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct IssueDependencyEdge {
    pub dependency_id: i32,
    pub source_issue_id: i32,
    pub source_issue_number: String,
    pub source_thread_id: i32,
    pub source_thread_title: String,
}

/// Wire parity with Python `IssueDependenciesResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct IssueDependenciesResponse {
    pub issue_id: i32,
    pub incoming: Vec<IssueDependencyEdge>,
    pub outgoing: Vec<IssueDependencyEdge>,
}

/// Wire parity with Python `ThreadIssueDependenciesResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ThreadIssueDependenciesResponse {
    pub thread_id: i32,
    pub issues: Vec<IssueDependenciesResponse>,
}

const DETAIL_SQL: &str = "SELECT i.id, i.thread_id, i.issue_number, i.position, i.status, to_char(i.read_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"'), to_char(i.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"') FROM issues i JOIN threads t ON t.id = i.thread_id WHERE i.id = $1 AND t.user_id = $2";

const OWNED_SQL: &str = "SELECT i.id FROM issues i JOIN threads t ON t.id = i.thread_id WHERE i.id = $1 AND t.user_id = $2";

const INCOMING_SQL: &str = "SELECT d.id, si.id, si.issue_number, si.thread_id, st.title FROM dependencies d JOIN issues si ON si.id = d.source_issue_id JOIN threads st ON st.id = si.thread_id WHERE d.target_issue_id = $1 AND st.user_id = $2 ORDER BY d.id";

const OUTGOING_SQL: &str = "SELECT d.id, ti.id, ti.issue_number, ti.thread_id, tt.title FROM dependencies d JOIN issues ti ON ti.id = d.target_issue_id JOIN threads tt ON tt.id = ti.thread_id WHERE d.source_issue_id = $1 AND tt.user_id = $2 ORDER BY d.id";

const THREAD_SQL: &str = "SELECT t.id FROM threads t WHERE t.id = $1 AND t.user_id = $2";

const THREAD_ISSUES_SQL: &str =
    "SELECT i.id FROM issues i WHERE i.thread_id = $1 ORDER BY i.position, i.id";

const THREAD_INCOMING_SQL: &str = "SELECT d.id, d.target_issue_id, si.id, si.issue_number, si.thread_id, st.title FROM dependencies d JOIN issues si ON si.id = d.source_issue_id JOIN threads st ON st.id = si.thread_id WHERE d.target_issue_id = ANY($1::int[]) AND st.user_id = $2 ORDER BY d.id";

const THREAD_OUTGOING_SQL: &str = "SELECT d.id, d.source_issue_id, ti.id, ti.issue_number, ti.thread_id, tt.title FROM dependencies d JOIN issues ti ON ti.id = d.target_issue_id JOIN threads tt ON tt.id = ti.thread_id WHERE d.source_issue_id = ANY($1::int[]) AND tt.user_id = $2 ORDER BY d.id";

fn not_found(issue_id: i32) -> ApiError {
    ApiError::with_status(StatusCode::NOT_FOUND, format!("Issue {issue_id} not found"))
}

/// `GET /api/v1/issues/{issue_id}` — one owner-scoped issue row.
pub async fn get_issue(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
) -> Result<Json<IssueDetailResponse>, ApiError> {
    let connection = db::checkout(&state).await?;
    let row = connection
        .query_opt(DETAIL_SQL, &[&issue_id, &user.id()])
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| not_found(issue_id))?;
    Ok(Json(IssueDetailResponse {
        id: row.get(0),
        thread_id: row.get(1),
        issue_number: row.get(2),
        position: row.get(3),
        status: row.get(4),
        read_at: row.get(5),
        created_at: row.get(6),
    }))
}

/// `GET /api/v1/issues/{issue_id}/dependencies` — bounded incoming/outgoing edges.
pub async fn get_issue_dependencies(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
) -> Result<Json<IssueDependenciesResponse>, ApiError> {
    let connection = db::checkout(&state).await?;
    let owned = connection
        .query_opt(OWNED_SQL, &[&issue_id, &user.id()])
        .await
        .map_err(db::query_error)?;
    if owned.is_none() {
        return Err(not_found(issue_id));
    }
    let incoming_rows = connection
        .query(INCOMING_SQL, &[&issue_id, &user.id()])
        .await
        .map_err(db::query_error)?;
    let outgoing_rows = connection
        .query(OUTGOING_SQL, &[&issue_id, &user.id()])
        .await
        .map_err(db::query_error)?;
    let incoming = incoming_rows
        .iter()
        .map(|row| IssueDependencyEdge {
            dependency_id: row.get(0),
            source_issue_id: row.get(1),
            source_issue_number: row.get(2),
            source_thread_id: row.get(3),
            source_thread_title: row.get(4),
        })
        .collect();
    let outgoing = outgoing_rows
        .iter()
        .map(|row| IssueDependencyEdge {
            dependency_id: row.get(0),
            source_issue_id: row.get(1),
            source_issue_number: row.get(2),
            source_thread_id: row.get(3),
            source_thread_title: row.get(4),
        })
        .collect();
    Ok(Json(IssueDependenciesResponse {
        issue_id,
        incoming,
        outgoing,
    }))
}

/// `GET /api/v1/threads/{thread_id}/issue-dependencies` — bounded issue-edge batch.
pub async fn get_thread_issue_dependencies(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(thread_id): Path<i32>,
) -> Result<Json<ThreadIssueDependenciesResponse>, ApiError> {
    let connection = db::checkout(&state).await?;
    let owned = connection
        .query_opt(THREAD_SQL, &[&thread_id, &user.id()])
        .await
        .map_err(db::query_error)?;
    if owned.is_none() {
        return Err(ApiError::with_status(
            StatusCode::NOT_FOUND,
            format!("Thread {thread_id} not found"),
        ));
    }

    let issue_rows = connection
        .query(THREAD_ISSUES_SQL, &[&thread_id])
        .await
        .map_err(db::query_error)?;
    let issue_ids: Vec<i32> = issue_rows.iter().map(|row| row.get(0)).collect();
    if issue_ids.is_empty() {
        return Ok(Json(ThreadIssueDependenciesResponse {
            thread_id,
            issues: vec![],
        }));
    }

    let mut incoming = std::collections::HashMap::<i32, Vec<IssueDependencyEdge>>::new();
    for row in connection
        .query(THREAD_INCOMING_SQL, &[&issue_ids, &user.id()])
        .await
        .map_err(db::query_error)?
    {
        let target_issue_id: i32 = row.get(1);
        incoming
            .entry(target_issue_id)
            .or_default()
            .push(IssueDependencyEdge {
                dependency_id: row.get(0),
                source_issue_id: row.get(2),
                source_issue_number: row.get(3),
                source_thread_id: row.get(4),
                source_thread_title: row.get(5),
            });
    }

    let mut outgoing = std::collections::HashMap::<i32, Vec<IssueDependencyEdge>>::new();
    for row in connection
        .query(THREAD_OUTGOING_SQL, &[&issue_ids, &user.id()])
        .await
        .map_err(db::query_error)?
    {
        let source_issue_id: i32 = row.get(1);
        outgoing
            .entry(source_issue_id)
            .or_default()
            .push(IssueDependencyEdge {
                dependency_id: row.get(0),
                source_issue_id: row.get(2),
                source_issue_number: row.get(3),
                source_thread_id: row.get(4),
                source_thread_title: row.get(5),
            });
    }

    let issues = issue_ids
        .into_iter()
        .map(|issue_id| IssueDependenciesResponse {
            issue_id,
            incoming: incoming.remove(&issue_id).unwrap_or_default(),
            outgoing: outgoing.remove(&issue_id).unwrap_or_default(),
        })
        .collect();
    Ok(Json(ThreadIssueDependenciesResponse { thread_id, issues }))
}

/// Documentation-only operation for the mounted single-issue read.
#[utoipa::path(
    get,
    path = "/api/v1/issues/{issue_id}",
    tag = "issues",
    description = "Return one owner-scoped issue. Wire parity with Python GET /api/v1/issues/{issue_id}: {id, thread_id, issue_number, position, status, read_at, created_at}. Missing or foreign issues return 404 with the Python detail text.",
    params(("issue_id" = i32, Path, description = "Owned Issue identifier")),
    responses(
        (status = 200, description = "Issue detail", body = IssueDetailResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Issue not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_issue_documentation() {}

/// Documentation-only operation for the mounted issue-dependencies read.
#[utoipa::path(
    get,
    path = "/api/v1/issues/{issue_id}/dependencies",
    tag = "issues",
    description = "Return owner-scoped incoming and outgoing dependency edges for one issue. Wire parity with Python GET /api/v1/issues/{issue_id}/dependencies: {issue_id, incoming, outgoing}, each edge carrying dependency_id, source_issue_id, source_issue_number, source_thread_id, source_thread_title. Bounded to two edge queries; no per-row fan-out.",
    params(("issue_id" = i32, Path, description = "Owned Issue identifier")),
    responses(
        (status = 200, description = "Issue dependencies", body = IssueDependenciesResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Issue not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_issue_dependencies_documentation() {}

/// Documentation-only operation for the mounted thread issue-dependencies batch read.
#[utoipa::path(
    get,
    path = "/api/v1/threads/{thread_id}/issue-dependencies",
    tag = "dependencies",
    description = "Return dependency edges for every issue in one owner-scoped thread. Wire parity with Python: issues are ordered by position and id, incoming/outgoing edges are ordered by dependency id, and foreign endpoints are omitted.",
    params(("thread_id" = i32, Path, description = "Owned thread identifier")),
    responses(
        (status = 200, description = "Thread issue dependencies", body = ThreadIssueDependenciesResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_thread_issue_dependencies_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn detail_wire_matches_python_issue_response_fields() {
        let value = serde_json::to_value(IssueDetailResponse {
            id: 7,
            thread_id: 3,
            issue_number: "12".into(),
            position: 2,
            status: "unread".into(),
            read_at: None,
            created_at: "2026-11-08T04:00:00.000Z".into(),
        })
        .expect("serializable detail");
        assert_eq!(
            value,
            json!({
                "id": 7,
                "thread_id": 3,
                "issue_number": "12",
                "position": 2,
                "status": "unread",
                "read_at": null,
                "created_at": "2026-11-08T04:00:00.000Z"
            })
        );
    }

    #[test]
    fn dependencies_wire_matches_python_issue_dependencies_fields() {
        let value = serde_json::to_value(IssueDependenciesResponse {
            issue_id: 7,
            incoming: vec![IssueDependencyEdge {
                dependency_id: 11,
                source_issue_id: 5,
                source_issue_number: "3".into(),
                source_thread_id: 2,
                source_thread_title: "Series A".into(),
            }],
            outgoing: vec![],
        })
        .expect("serializable dependencies");
        assert_eq!(value["issue_id"], 7);
        assert_eq!(value["incoming"][0]["dependency_id"], 11);
        assert_eq!(value["incoming"][0]["source_issue_id"], 5);
        assert_eq!(value["incoming"][0]["source_issue_number"], "3");
        assert_eq!(value["incoming"][0]["source_thread_id"], 2);
        assert_eq!(value["incoming"][0]["source_thread_title"], "Series A");
        assert!(value["outgoing"].is_array());
        assert!(value["outgoing"].as_array().expect("array").is_empty());
    }

    #[test]
    fn detail_sql_is_owner_scoped_and_single_statement() {
        assert!(DETAIL_SQL.contains("JOIN threads t ON t.id = i.thread_id"));
        assert!(DETAIL_SQL.contains("t.user_id = $2"));
        assert!(DETAIL_SQL.contains("i.id = $1"));
        assert!(!DETAIL_SQL.contains(';'));
    }

    #[test]
    fn dependency_sql_is_owner_scoped_and_bounded() {
        for sql in [INCOMING_SQL, OUTGOING_SQL] {
            assert!(sql.contains("JOIN issues"));
            assert!(sql.contains("JOIN threads"));
            assert!(sql.contains("user_id = $2"));
            assert!(sql.contains("ORDER BY d.id"));
        }
        assert!(INCOMING_SQL.contains("d.target_issue_id = $1"));
        assert!(OUTGOING_SQL.contains("d.source_issue_id = $1"));
    }

    #[test]
    fn thread_issue_dependency_sql_preserves_batch_parity() {
        assert!(THREAD_SQL.contains("t.user_id = $2"));
        assert!(THREAD_ISSUES_SQL.contains("ORDER BY i.position, i.id"));
        for sql in [THREAD_INCOMING_SQL, THREAD_OUTGOING_SQL] {
            assert!(sql.contains("ANY($1::int[])"));
            assert!(sql.contains("user_id = $2"));
            assert!(sql.contains("ORDER BY d.id"));
        }
        assert!(THREAD_INCOMING_SQL.contains("d.target_issue_id = ANY"));
        assert!(THREAD_OUTGOING_SQL.contains("d.source_issue_id = ANY"));
    }

    #[test]
    fn thread_issue_dependencies_wire_matches_python_batch_shape() {
        let value = serde_json::to_value(ThreadIssueDependenciesResponse {
            thread_id: 3,
            issues: vec![IssueDependenciesResponse {
                issue_id: 7,
                incoming: vec![],
                outgoing: vec![IssueDependencyEdge {
                    dependency_id: 11,
                    source_issue_id: 9,
                    source_issue_number: "1".into(),
                    source_thread_id: 4,
                    source_thread_title: "Series B".into(),
                }],
            }],
        })
        .expect("serializable thread dependencies");
        assert_eq!(value["thread_id"], 3);
        assert_eq!(value["issues"][0]["issue_id"], 7);
        assert!(value["issues"][0]["incoming"].is_array());
        assert_eq!(value["issues"][0]["outgoing"][0]["dependency_id"], 11);
    }

    #[test]
    fn not_found_matches_python_detail_text() {
        let error = not_found(42);
        assert_eq!(error.status(), StatusCode::NOT_FOUND);
        assert_eq!(error.detail(), "Issue 42 not found");
    }

    #[tokio::test]
    async fn v1_issue_reads_require_auth_through_service_router() {
        use crate::{config::Config, router, AppState};
        use axum::{
            body::Body,
            http::{Request, StatusCode},
        };
        use tower::ServiceExt;

        let config = Config::from_lookup(|name| match name {
            "RUST_ROLL_DATABASE_URL" => Some("postgresql://localhost/unused".into()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-secret".into()),
            _ => None,
        })
        .unwrap();
        let app = router(Arc::new(AppState::new(config).unwrap()));
        for uri in [
            "/api/v1/issues/7",
            "/api/v1/issues/7/comicvine",
            "/api/v1/issues/7/dependencies",
            "/api/v1/threads/7/issue-dependencies",
        ] {
            let response = app
                .clone()
                .oneshot(
                    Request::builder()
                        .method("GET")
                        .uri(uri)
                        .body(Body::empty())
                        .unwrap(),
                )
                .await
                .unwrap();
            assert_eq!(
                response.status(),
                StatusCode::UNAUTHORIZED,
                "{uri} must require auth through the service router"
            );
        }
    }
}
