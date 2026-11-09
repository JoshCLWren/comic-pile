//! Native same-path compatibility handlers for the browser dependency API.
//!
//! These routes intentionally keep the `/api/v1` wire surface while the Python
//! implementation remains available until production runtime proof is recorded.

use crate::{
    auth::AuthenticatedUser,
    db,
    dependencies::{self, DependencyCreateRequest, DependencyResponse},
    ApiError, AppState,
};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

#[derive(Debug, Deserialize, Serialize, utoipa::ToSchema)]
pub struct DependencyNoteUpdate {
    pub note: Option<String>,
}

fn not_found(dependency_id: i32) -> ApiError {
    ApiError(
        StatusCode::NOT_FOUND,
        format!("Dependency {dependency_id} not found"),
    )
}

async fn fetch_dependency(
    state: &AppState,
    dependency_id: i32,
    user_id: i32,
) -> Result<Option<DependencyResponse>, ApiError> {
    let connection = db::checkout(state).await?;
    let row = connection
        .query_opt(
            "SELECT d.id, d.source_issue_id, d.target_issue_id, d.created_at::text, d.note,
                    st.id, tt.id, st.title, si.issue_number, tt.title, ti.issue_number
             FROM dependencies d
             JOIN issues si ON si.id = d.source_issue_id
             JOIN threads st ON st.id = si.thread_id
             JOIN issues ti ON ti.id = d.target_issue_id
             JOIN threads tt ON tt.id = ti.thread_id
             WHERE d.id = $1 AND st.user_id = $2 AND tt.user_id = $2",
            &[&dependency_id, &user_id],
        )
        .await
        .map_err(|error| db::query_error_for("legacy_dependencies.fetch", error))?;

    Ok(row.map(|row| {
        let source_thread_id: i32 = row.get(5);
        let target_thread_id: i32 = row.get(6);
        let source_title: String = row.get(7);
        let source_number: String = row.get(8);
        let target_title: String = row.get(9);
        let target_number: String = row.get(10);
        DependencyResponse {
            id: row.get(0),
            source_issue_id: Some(row.get(1)),
            target_issue_id: Some(row.get(2)),
            source_thread_id: Some(source_thread_id),
            target_thread_id: Some(target_thread_id),
            is_issue_level: true,
            created_at: row.get(3),
            note: row.get(4),
            source_label: Some(format!("{source_title} #{source_number}")),
            target_label: Some(format!("{target_title} #{target_number}")),
            source_issue_thread_id: Some(source_thread_id),
            target_issue_thread_id: Some(target_thread_id),
            warning: None,
        }
    }))
}

/// `GET /api/v1/dependencies/blocked`.
pub async fn blocked(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> Result<Json<Vec<i32>>, ApiError> {
    let connection = db::checkout(&state).await?;
    let rows = connection
        .query(
            "SELECT DISTINCT target_thread.id
             FROM threads target_thread
             JOIN issues next_unread_issue ON next_unread_issue.id = target_thread.next_unread_issue_id
             JOIN dependencies d ON d.target_issue_id = next_unread_issue.id
             JOIN issues source_issue ON source_issue.id = d.source_issue_id
             JOIN threads source_thread ON source_thread.id = source_issue.thread_id
             WHERE target_thread.user_id = $1
               AND source_thread.user_id = $1
               AND source_issue.status <> 'read'
               AND next_unread_issue.status <> 'read'
               AND (d.note IS NULL OR d.note NOT LIKE 'cbl-order:%')
             ORDER BY target_thread.id",
            &[&user.id()],
        )
        .await
        .map_err(|error| db::query_error_for("legacy_dependencies.blocked", error))?;
    Ok(Json(rows.into_iter().map(|row| row.get(0)).collect()))
}

/// `POST /api/v1/dependencies/`.
pub async fn create(
    state: State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<DependencyCreateRequest>,
) -> Result<(StatusCode, Json<DependencyResponse>), ApiError> {
    dependencies::create_dependency(state, user, Json(request)).await
}

/// `GET /api/v1/dependencies/{dependency_id}`.
pub async fn get(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(dependency_id): Path<i32>,
) -> Result<Json<DependencyResponse>, ApiError> {
    fetch_dependency(&state, dependency_id, user.id())
        .await?
        .map(Json)
        .ok_or_else(|| not_found(dependency_id))
}

/// `PATCH /api/v1/dependencies/{dependency_id}`.
pub async fn update(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(dependency_id): Path<i32>,
    Json(request): Json<DependencyNoteUpdate>,
) -> Result<Json<DependencyResponse>, ApiError> {
    if request
        .note
        .as_ref()
        .is_some_and(|note| note.chars().count() > 255)
    {
        return Err(ApiError(
            StatusCode::UNPROCESSABLE_ENTITY,
            "String should have at most 255 characters".to_string(),
        ));
    }
    let connection = db::checkout(&state).await?;
    let updated = connection
        .execute(
            "UPDATE dependencies d
             SET note = $2
             FROM issues si, threads st, issues ti, threads tt
             WHERE d.id = $1
               AND d.source_issue_id = si.id AND si.thread_id = st.id AND st.user_id = $3
               AND d.target_issue_id = ti.id AND ti.thread_id = tt.id AND tt.user_id = $3",
            &[&dependency_id, &request.note, &user.id()],
        )
        .await
        .map_err(|error| db::query_error_for("legacy_dependencies.update", error))?;
    if updated == 0 {
        return Err(not_found(dependency_id));
    }
    fetch_dependency(&state, dependency_id, user.id())
        .await?
        .map(Json)
        .ok_or_else(|| not_found(dependency_id))
}

/// `DELETE /api/v1/dependencies/{dependency_id}`.
pub async fn delete(
    state: State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(dependency_id): Path<i32>,
) -> Result<Json<serde_json::Value>, ApiError> {
    dependencies::delete_dependency(state, user, Path(dependency_id)).await
}

#[utoipa::path(
    get,
    path = "/api/v1/dependencies/blocked",
    operation_id = "list_blocked_legacy_dependencies",
    tag = "dependencies",
    responses((status = 200, description = "Blocked thread ids", body = [i32]), (status = 401, description = "Not authenticated")),
    security(("HTTPBearer" = []))
)]
pub fn blocked_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/dependencies/",
    operation_id = "create_legacy_dependency",
    tag = "dependencies",
    request_body = DependencyCreateRequest,
    responses((status = 201, description = "Created dependency", body = DependencyResponse), (status = 400, description = "Invalid dependency"), (status = 401, description = "Not authenticated"), (status = 404, description = "Issue not found")),
    security(("HTTPBearer" = []))
)]
pub fn create_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v1/dependencies/{dependency_id}",
    operation_id = "get_legacy_dependency",
    tag = "dependencies",
    params(("dependency_id" = i32, Path, description = "Dependency id")),
    responses((status = 200, description = "Dependency", body = DependencyResponse), (status = 401, description = "Not authenticated"), (status = 404, description = "Dependency not found")),
    security(("HTTPBearer" = []))
)]
pub fn get_documentation() {}

#[utoipa::path(
    patch,
    path = "/api/v1/dependencies/{dependency_id}",
    operation_id = "update_legacy_dependency",
    tag = "dependencies",
    request_body = DependencyNoteUpdate,
    params(("dependency_id" = i32, Path, description = "Dependency id")),
    responses((status = 200, description = "Dependency", body = DependencyResponse), (status = 401, description = "Not authenticated"), (status = 404, description = "Dependency not found")),
    security(("HTTPBearer" = []))
)]
pub fn update_documentation() {}

#[utoipa::path(
    delete,
    path = "/api/v1/dependencies/{dependency_id}",
    operation_id = "delete_legacy_dependency",
    tag = "dependencies",
    params(("dependency_id" = i32, Path, description = "Dependency id")),
    responses((status = 200, description = "Deleted", body = serde_json::Value), (status = 401, description = "Not authenticated"), (status = 404, description = "Dependency not found")),
    security(("HTTPBearer" = []))
)]
pub fn delete_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn owner_mutations_persist_and_foreign_reader_cannot_change_edge() {
        let state = crate::test_support::test_state(2)
            .await
            .expect("disposable Postgres is required");
        let _guard = crate::test_support::reset_for_test(&state).await;
        let connection = state.pool.get().await.expect("fixture connection");
        connection.batch_execute(
            "INSERT INTO users (id,username) VALUES (1,'legacy-owner'),(2,'legacy-other');
             INSERT INTO threads (id,title,format,issues_remaining,queue_position,status,user_id,created_at)
             VALUES (11,'Source','comic',1,1,'active',1,NOW()),(12,'Target','comic',1,2,'active',1,NOW());
             INSERT INTO issues (id,thread_id,issue_number,status,created_at,position)
             VALUES (101,11,'1','unread',NOW(),1),(201,12,'1','unread',NOW(),1);"
        ).await.expect("dependency fixtures");
        drop(connection);
        let owner = AuthenticatedUser::for_test(1);
        let other = AuthenticatedUser::for_test(2);
        let (status, Json(created)) = create(
            State(state.clone()),
            owner,
            Json(DependencyCreateRequest {
                source_type: "issue".into(),
                source_id: 101,
                target_type: "issue".into(),
                target_id: 201,
            }),
        )
        .await
        .expect("create persists edge");
        assert_eq!(status, StatusCode::CREATED);
        let edge = created.id;
        let denied = update(
            State(state.clone()),
            other,
            Path(edge),
            Json(DependencyNoteUpdate {
                note: Some("foreign".into()),
            }),
        )
        .await
        .expect_err("foreign update denied");
        assert_eq!(denied.0, StatusCode::NOT_FOUND);
        let denied = delete(State(state.clone()), other, Path(edge))
            .await
            .expect_err("foreign delete denied");
        assert_eq!(denied.0, StatusCode::NOT_FOUND);
        let Json(updated) = update(
            State(state.clone()),
            owner,
            Path(edge),
            Json(DependencyNoteUpdate {
                note: Some("reader note".into()),
            }),
        )
        .await
        .expect("owner update persists");
        assert_eq!(updated.note.as_deref(), Some("reader note"));
        let connection = state.pool.get().await.expect("read persisted edge");
        let note: Option<String> = connection
            .query_one("SELECT note FROM dependencies WHERE id=$1", &[&edge])
            .await
            .expect("persisted note")
            .get(0);
        assert_eq!(note.as_deref(), Some("reader note"));
        drop(connection);
        let invalid = update(
            State(state.clone()),
            owner,
            Path(edge),
            Json(DependencyNoteUpdate {
                note: Some("x".repeat(256)),
            }),
        )
        .await
        .expect_err("oversized note denied");
        assert_eq!(invalid.0, StatusCode::UNPROCESSABLE_ENTITY);
        let Json(cleared) = update(
            State(state.clone()),
            owner,
            Path(edge),
            Json(DependencyNoteUpdate { note: None }),
        )
        .await
        .expect("owner clears note");
        assert_eq!(cleared.note, None);
        let Json(deleted) = delete(State(state.clone()), owner, Path(edge))
            .await
            .expect("owner deletes edge");
        assert_eq!(deleted["message"], "Dependency deleted");
        let connection = state.pool.get().await.expect("read deleted edge");
        let count: i64 = connection
            .query_one("SELECT count(*) FROM dependencies WHERE id=$1", &[&edge])
            .await
            .expect("deletion persisted")
            .get(0);
        assert_eq!(count, 0);
    }
}
