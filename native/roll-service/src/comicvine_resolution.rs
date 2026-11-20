//! Native same-path reads for the first ComicVine resolution slice (#4835).
//!
//! The Python handler remains mounted as the fallback until production proves
//! the native path. This slice migrates only the browser-called import-status
//! read; the remaining ComicVine search, identity, correction, and import
//! operations stay on Python for subsequent slices.

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    Json,
};
use serde::Serialize;
use std::sync::Arc;

/// Wire parity with Python `SeriesImportStatusResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SeriesImportStatusResponse {
    pub comicvine_volume_id: i32,
    pub imported: bool,
    pub thread_id: Option<i32>,
    pub series_name: Option<String>,
    pub issue_count: Option<i32>,
}

const STATUS_SQL: &str = "SELECT t.id, t.title, t.total_issues FROM threads t JOIN thread_external_series_mappings m ON m.thread_id = t.id JOIN external_identities e ON e.id = m.external_identity_id WHERE t.user_id = $1 AND m.status = 'confirmed' AND e.entity_type = 'series' AND e.provider = 'comicvine' AND e.external_id = $2 ORDER BY m.id LIMIT 1";

/// `GET /api/v1/comicvine/series/{comicvine_volume_id}/import-status`.
///
/// The owner predicate is part of the single query, matching the Python
/// repository's no-leakage contract for retry recovery.
pub async fn series_import_status(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(comicvine_volume_id): Path<i32>,
) -> Result<Json<SeriesImportStatusResponse>, ApiError> {
    let connection = db::checkout(&state).await?;
    let volume_id = comicvine_volume_id.to_string();
    let row = connection
        .query_opt(STATUS_SQL, &[&user.id(), &volume_id])
        .await
        .map_err(db::query_error)?;

    let response = match row {
        Some(row) => SeriesImportStatusResponse {
            comicvine_volume_id,
            imported: true,
            thread_id: Some(row.get(0)),
            series_name: Some(row.get(1)),
            issue_count: row.get(2),
        },
        None => SeriesImportStatusResponse {
            comicvine_volume_id,
            imported: false,
            thread_id: None,
            series_name: None,
            issue_count: None,
        },
    };
    Ok(Json(response))
}

/// OpenAPI documentation for the migrated same-path operation.
#[utoipa::path(
    get,
    path = "/api/v1/comicvine/series/{comicvine_volume_id}/import-status",
    params(("comicvine_volume_id" = i32, Path, description = "ComicVine volume ID")),
    tag = "comicvine-resolution",
    responses(
        (status = 200, description = "Owned import status", body = SeriesImportStatusResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn series_import_status_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn query_is_owner_scoped_and_uses_one_bounded_lookup() {
        assert!(STATUS_SQL.contains("t.user_id = $1"));
        assert!(STATUS_SQL.contains("e.external_id = $2"));
        assert!(STATUS_SQL.contains("ORDER BY m.id LIMIT 1"));
        assert!(!STATUS_SQL.contains("FOR UPDATE"));
    }
}
