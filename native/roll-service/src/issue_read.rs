//! Native same-path reads for the browser-called issues family (#4845).
//!
//! Migrates the read-only subset of `app/api/issue.py` and
//! `app/api/dependency.py` to the native Rust router with identical
//! method/path and wire contract:
//!
//! * `GET /api/v1/issues/{issue_id}`
//! * `GET /api/v1/issues/{issue_id}/dependencies`
//! * `GET /api/v1/threads/{thread_id}/issues` — the production Fluid CPU hot
//!   path from issue #4832 (browser bursts across many thread IDs), plus
//! * `GET /api/v1/threads/{thread_id}/issue-dependencies`
//!
//! The remaining browser-called reads in the family,
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
//! * `GET /api/v1/threads/{thread_id}/issues` returns `IssueListResponse`
//!   (`issues`, `total_count`, `page_size`, `next_page_token`) where each
//!   issue carries the same fields as `IssueResponse`. Python
//!   `issue_service.list_issues` behavior is mirrored exactly: one
//!   owner-thread check (404 `Thread {id} not found`), an optional exact
//!   `status` filter (`unread`/`read`, 422 otherwise), `page_size` clamped
//!   by FastAPI to 1..=100 with default 50 (422 otherwise), a
//!   `{position},{id}` cursor `page_token` (400 `Invalid page_token format`
//!   when malformed, empty token treated as page one), one page query with
//!   `limit page_size + 1`, and one count query. `next_page_token` is the
//!   canonical `last.position,last.id` of the returned page when more rows
//!   exist. `created_at`/`read_at` serialize the way FastAPI/Pydantic v2
//!   renders aware UTC datetimes: no fractional seconds on whole seconds,
//!   otherwise six-digit microseconds with a `Z` suffix (the shared
//!   `threads::iso_timestamp` projection).
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

use crate::{auth::AuthenticatedUser, db, threads::iso_timestamp, ApiError, AppState};
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use std::sync::{Arc, LazyLock};

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

/// Wire parity with Python `IssueListResponse` (`app/schemas/issue.py`).
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ThreadIssueListResponse {
    /// One page of the thread's issues in canonical `position` order.
    pub issues: Vec<IssueDetailResponse>,
    /// Total issues in the thread, optionally filtered by `status`.
    pub total_count: i64,
    /// Echo of the requested page size (50 when omitted).
    pub page_size: i64,
    /// `{position},{id}` cursor when another page exists.
    pub next_page_token: Option<String>,
}

/// Python `Query` parameters of `GET /api/v1/threads/{thread_id}/issues`.
#[derive(Debug, Deserialize)]
pub struct ThreadIssueListQuery {
    /// Optional exact status filter; Python pattern `^(unread|read)$`.
    pub status: Option<String>,
    /// Page size; Python `Query(50, ge=1, le=100)`.
    pub page_size: Option<i32>,
    /// `{position},{id}` continuation cursor.
    pub page_token: Option<String>,
}

/// One page of a thread's issues, in canonical order, with the same
/// `to_char` datetime projection as the mounted single-issue read.
static ISSUE_PAGE_SQL: LazyLock<String> = LazyLock::new(|| {
    format!(
        "SELECT i.id, i.thread_id, i.issue_number, i.position, i.status, {}, {} \
         FROM issues i WHERE i.thread_id = $1 \
         AND ($2::text IS NULL OR i.status = $2) \
         AND ($3::int IS NULL OR i.position > $3 OR (i.position = $3 AND i.id > $4::int)) \
         ORDER BY i.position LIMIT $5::int",
        iso_timestamp("i.read_at"),
        iso_timestamp("i.created_at"),
    )
});

/// Count of a thread's issues, optionally filtered by `status`.
static ISSUE_COUNT_SQL: LazyLock<String> = LazyLock::new(|| {
    "SELECT count(*) FROM issues i WHERE i.thread_id = $1 \
     AND ($2::text IS NULL OR i.status = $2)"
        .to_string()
});

/// Decode Python's `{position},{id}` cursor. A malformed token is a 400, an
/// empty token is page one (Python's falsy-string check).
fn parse_issue_page_token(token: &str) -> Result<(i32, i32), ApiError> {
    let mut parts = token.split(',');
    let position = parts
        .next()
        .and_then(|part| part.parse::<i32>().ok())
        .ok_or_else(|| {
            ApiError::with_status(
                StatusCode::BAD_REQUEST,
                "Invalid page_token format".to_string(),
            )
        })?;
    let id = parts
        .next()
        .and_then(|part| part.parse::<i32>().ok())
        .filter(|_| parts.next().is_none())
        .ok_or_else(|| {
            ApiError::with_status(
                StatusCode::BAD_REQUEST,
                "Invalid page_token format".to_string(),
            )
        })?;
    Ok((position, id))
}

/// `GET /api/v1/threads/{thread_id}/issues` — the browser hot-path issue
/// listing (issue #4832). Same method/path as Python `list_issues` with one
/// owner check, one bounded page query, and one count query: no N+1 and no
/// per-row fan-out.
pub async fn list_thread_issues(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(thread_id): Path<i32>,
    Query(query): Query<ThreadIssueListQuery>,
) -> Result<Json<ThreadIssueListResponse>, ApiError> {
    if let Some(status_filter) = query.status.as_deref() {
        if status_filter != "unread" && status_filter != "read" {
            return Err(ApiError::Unprocessable(
                "status must be 'unread' or 'read'".to_string(),
            ));
        }
    }
    let page_size = i64::from(query.page_size.unwrap_or(50));
    if !(1..=100).contains(&page_size) {
        return Err(ApiError::Unprocessable(
            "page_size must be between 1 and 100".to_string(),
        ));
    }
    let cursor = query
        .page_token
        .as_deref()
        .filter(|token| !token.is_empty())
        .map(parse_issue_page_token)
        .transpose()?;

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

    let (cursor_position, cursor_id) =
        cursor.map_or((None, None), |(position, id)| (Some(position), Some(id)));
    let rows = connection
        .query(
            &*ISSUE_PAGE_SQL,
            &[
                &thread_id,
                &query.status,
                &cursor_position,
                &cursor_id,
                &(page_size + 1),
            ],
        )
        .await
        .map_err(db::query_error)?;
    let total_count: i64 = connection
        .query_one(&*ISSUE_COUNT_SQL, &[&thread_id, &query.status])
        .await
        .map_err(db::query_error)?
        .get(0);

    let has_more = rows.len() as i64 > page_size;
    let issues: Vec<IssueDetailResponse> = rows
        .into_iter()
        .take(page_size as usize)
        .map(|row| IssueDetailResponse {
            id: row.get(0),
            thread_id: row.get(1),
            issue_number: row.get(2),
            position: row.get(3),
            status: row.get(4),
            read_at: row.get(5),
            created_at: row.get(6),
        })
        .collect();
    let next_page_token = if has_more {
        issues
            .last()
            .map(|last| format!("{},{}", last.position, last.id))
    } else {
        None
    };
    Ok(Json(ThreadIssueListResponse {
        issues,
        total_count,
        page_size,
        next_page_token,
    }))
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

/// Documentation-only operation for the mounted thread issue list read.
#[utoipa::path(
    get,
    path = "/api/v1/threads/{thread_id}/issues",
    tag = "issues",
    description = "List one owner-scoped thread's issues with optional unread/read filter and {position},{id} cursor pagination. Wire parity with Python IssueListResponse: issues ordered by position, total_count reflects the filter, page_size echoes the request (default 50), next_page_token appears only when more pages exist.",
    params(
        ("thread_id" = i32, Path, description = "Owned thread identifier"),
        ("status" = Option<String>, Query, description = "Optional exact status filter: unread or read"),
        ("page_size" = Option<i32>, Query, description = "Page size, 1-100 (default 50)"),
        ("page_token" = Option<String>, Query, description = "position,id continuation cursor")
    ),
    responses(
        (status = 200, description = "Paginated issue list", body = ThreadIssueListResponse),
        (status = 400, description = "Invalid page_token format"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 422, description = "Invalid status or page_size"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_thread_issues_documentation() {}

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
    fn issue_list_wire_matches_python_fields() {
        let value = serde_json::to_value(ThreadIssueListResponse {
            issues: vec![IssueDetailResponse {
                id: 9,
                thread_id: 3,
                issue_number: "1".into(),
                position: 1,
                status: "read".into(),
                read_at: Some("2026-11-08T04:00:00.000123Z".into()),
                created_at: "2026-11-08T04:00:00Z".into(),
            }],
            total_count: 12,
            page_size: 50,
            next_page_token: Some("1,9".into()),
        })
        .expect("serializable issue list");
        assert_eq!(value["total_count"], 12);
        assert_eq!(value["page_size"], 50);
        assert_eq!(value["next_page_token"], "1,9");
        let issue = &value["issues"][0];
        assert_eq!(issue["id"], 9);
        assert_eq!(issue["thread_id"], 3);
        assert_eq!(issue["issue_number"], "1");
        assert_eq!(issue["position"], 1);
        assert_eq!(issue["status"], "read");
        assert_eq!(issue["read_at"], "2026-11-08T04:00:00.000123Z");
        assert_eq!(issue["created_at"], "2026-11-08T04:00:00Z");
    }

    #[test]
    fn page_sql_is_owner_scoped_and_bounded() {
        let sql = ISSUE_PAGE_SQL.clone();
        assert!(sql.contains("i.thread_id = $1"));
        assert!(sql.contains("i.status = $2"));
        assert!(sql.contains("ORDER BY i.position"));
        assert!(sql.contains("LIMIT $5"));
        assert!(sql.contains("date_trunc('second', i.read_at) = i.read_at"));
        assert!(sql.contains(".US\"Z\""));
        assert!(!sql.contains(';'));
        assert!(ISSUE_COUNT_SQL.clone().contains("count(*)"));
    }

    #[test]
    fn page_tokens_round_trip_python_cursor_semantics() {
        assert_eq!(
            parse_issue_page_token("12,34").expect("valid token"),
            (12, 34)
        );
        for bad in [
            "", "12", "12,", "12,34,", "12,34,56", "a,b", "1,b", "-,2", "1.5,2",
        ] {
            let error = parse_issue_page_token(bad).expect_err(bad);
            assert_eq!(error.status(), StatusCode::BAD_REQUEST, "{bad}");
            assert!(
                error.to_string().contains("Invalid page_token format"),
                "{bad} -> {error}"
            );
        }
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
