//! Native same-path undo snapshots read (#4839, parent #4335).
//!
//! Migrates `GET /api/undo/{session_id}/snapshots` and
//! `GET /api/v1/undo/{session_id}/snapshots` to the native Rust router with
//! identical method/path and wire contract.
//!
//! Wire parity with Python `list_session_snapshots` (`app/api/undo.py`):
//!
//! * Ownership: session must belong to the authenticated user (404 if not found or foreign).
//! * Returns snapshots in reverse chronological order (newest first).
//! * Timestamps emitted as UTC `...Z` strings.
//!
//! Bounded reads: one session ownership check + one aggregated snapshots query.

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::Serialize;
use std::sync::Arc;
use utoipa::ToSchema;

/// Snapshot item in the list response.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct UndoSnapshotItem {
    pub id: i32,
    pub session_id: i32,
    pub created_at: String,
    pub description: Option<String>,
    pub event_id: Option<i32>,
}

/// Undo snapshots list response.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct UndoSnapshotsResponse {
    pub session_id: i32,
    pub snapshots: Vec<UndoSnapshotItem>,
}

const SESSION_OWNERSHIP_SQL: &str = "SELECT 1 FROM sessions WHERE id = $1 AND user_id = $2";
const SNAPSHOTS_SQL: &str = "SELECT id, session_id, to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), description, event_id FROM snapshots WHERE session_id = $1 ORDER BY created_at DESC, id DESC";

fn not_found() -> ApiError {
    ApiError::with_status(StatusCode::NOT_FOUND, "Session not found".to_string())
}

fn internal() -> ApiError {
    ApiError::with_status(
        StatusCode::INTERNAL_SERVER_ERROR,
        "Internal Server Error".to_string(),
    )
}

/// `GET /api/undo/{session_id}/snapshots` and `GET /api/v1/undo/{session_id}/snapshots`.
pub async fn list_undo_snapshots(
    Path(session_id): Path<i32>,
    user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
) -> Result<Json<UndoSnapshotsResponse>, ApiError> {
    let connection = db::checkout(&state).await?;

    // Verify session ownership
    let owned = connection
        .query_opt(SESSION_OWNERSHIP_SQL, &[&session_id, &user.id()])
        .await
        .map_err(db::query_error)?
        .is_some();

    if !owned {
        return Err(not_found());
    }

    // Fetch snapshots
    let snapshot_rows = connection
        .query(SNAPSHOTS_SQL, &[&session_id])
        .await
        .map_err(db::query_error)?;

    let mut snapshots = Vec::with_capacity(snapshot_rows.len());
    for row in snapshot_rows {
        let id: i32 = row.try_get(0).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let session_id: i32 = row.try_get(1).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let created_at: String = row.try_get(2).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let description: Option<String> = row.try_get(3).ok();
        let event_id: Option<i32> = row.try_get(4).ok();

        snapshots.push(UndoSnapshotItem {
            id,
            session_id,
            created_at,
            description,
            event_id,
        });
    }

    Ok(Json(UndoSnapshotsResponse {
        session_id,
        snapshots,
    }))
}

/// Documentation-only operation for the undo snapshots list.
#[utoipa::path(
    get,
    path = "/api/v2/undo/{session_id}/snapshots",
    tag = "undo",
    params(("session_id" = i32, Path, description = "Owned reading session")),
    responses(
        (status = 200, description = "Session restore snapshots", body = UndoSnapshotsResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Session not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_undo_snapshots_documentation() {}

/// OpenAPI document for the undo snapshots surface.
#[derive(utoipa::OpenApi)]
#[openapi(
    paths(list_undo_snapshots_documentation),
    components(schemas(
        UndoSnapshotItem,
        UndoSnapshotsResponse
    )),
    modifiers(&UndoSnapshotsSecurityAddon)
)]
pub struct UndoSnapshotsApi;

struct UndoSnapshotsSecurityAddon;

impl utoipa::Modify for UndoSnapshotsSecurityAddon {
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{db, test_support};
    use utoipa::OpenApi;

    #[test]
    fn undo_snapshots_openapi_covers_v2_path() {
        let document = serde_json::to_value(UndoSnapshotsApi::openapi()).expect("openapi");
        let paths = document["paths"].as_object().expect("paths");
        let path = "/api/v2/undo/{session_id}/snapshots";
        assert!(paths.contains_key(path));
        assert!(!paths.contains_key("/api/undo/{session_id}/snapshots"));
        assert!(!paths.contains_key("/api/v1/undo/{session_id}/snapshots"));
        let operation = &document["paths"][path]["get"];
        assert!(operation["operationId"].is_string());
        assert!(operation["responses"]["200"].as_object().is_some());
        assert!(operation["responses"]["404"].as_object().is_some());
        assert!(operation["security"].is_array());
        assert!(document["components"]["schemas"]["UndoSnapshotsResponse"].is_object());
        assert!(document["components"]["schemas"]["UndoSnapshotItem"].is_object());
    }

    async fn database_fixture() -> (
        Arc<AppState>,
        AuthenticatedUser,
        tokio::sync::MutexGuard<'static, ()>,
    ) {
        let state = test_support::test_state(2)
            .await
            .expect("RUST_ROLL_TEST_DATABASE_URL is required");
        let guard = test_support::reset_for_test(&state).await;
        let connection = db::checkout(&state).await.expect("fixture connection");
        connection
            .batch_execute(
                "INSERT INTO users (id, username) VALUES (9101, 'undo-snapshots-test'), (9102, 'undo-snapshots-other');
                 INSERT INTO sessions (id, user_id, started_at, ended_at, start_die, manual_die) VALUES (9301, 9101, NOW(), NULL, 6, NULL), (9302, 9102, NOW(), NULL, 6, NULL);
                 INSERT INTO snapshots (session_id, created_at, description, event_id, thread_states) VALUES (9301, NOW(), 'Session start', NULL, '{}'::json), (9301, NOW() + interval '1 minute', 'Before rating', NULL, '{}'::json), (9302, NOW(), 'Other session', NULL, '{}'::json);",
            )
            .await
            .expect("seed undo snapshots fixture");
        drop(connection);
        (state, AuthenticatedUser::for_test(9101), guard)
    }

    #[tokio::test]
    async fn list_undo_snapshots_returns_owned_snapshots_to_disposable_postgres() {
        let (state, user, _guard) = database_fixture().await;
        let Json(response) = list_undo_snapshots(Path(9301), user, State(state.clone()))
            .await
            .expect("list snapshots");
        assert_eq!(response.session_id, 9301);
        assert_eq!(response.snapshots.len(), 2);
        // Should be in reverse chronological order
        assert!(response.snapshots[0].created_at >= response.snapshots[1].created_at);
        assert_eq!(
            response.snapshots[0].description,
            Some("Before rating".to_string())
        );
        assert_eq!(
            response.snapshots[1].description,
            Some("Session start".to_string())
        );
    }

    #[tokio::test]
    async fn list_undo_snapshots_rejects_foreign_session() {
        let (state, user, _guard) = database_fixture().await;
        let missing = list_undo_snapshots(Path(9999), user, State(state.clone()))
            .await
            .expect_err("missing must 404");
        assert_eq!(missing.status(), StatusCode::NOT_FOUND);
        assert_eq!(missing.detail(), "Session not found");

        let foreign = list_undo_snapshots(Path(9302), user, State(state.clone()))
            .await
            .expect_err("foreign must 404");
        assert_eq!(foreign.status(), StatusCode::NOT_FOUND);
        assert_eq!(foreign.detail(), "Session not found");
    }
}
