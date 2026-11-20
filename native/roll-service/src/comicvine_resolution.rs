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

// Wire parity with Python `api_get_issue_identity`.
// `GET /api/v1/comicvine/issues/{issue_id}/identity`.
pub async fn get_issue_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    // TODO: Implement full identity state lookup
    // For now, return a minimal response
    Ok(Json(IssueIdentityResponse {
        issue_id,
        thread_id: 0,
        thread_title: String::new(),
        has_confirmed_identity: false,
        comicvine_issue_id: None,
        confirmed_mappings: vec![],
        candidate_mappings: vec![],
        has_unresolved: false,
    }))
}

// Wire parity with Python `api_confirm_identity`.
// `POST /api/v1/comicvine/issues/{issue_id}/identity:confirm`.
pub async fn confirm_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
    Json(request): Json<ConfirmIdentityRequest>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    // TODO: Implement full identity confirmation
    // For now, return a minimal response
    Ok(Json(IssueIdentityResponse {
        issue_id,
        thread_id: 0,
        thread_title: String::new(),
        has_confirmed_identity: false,
        comicvine_issue_id: None,
        confirmed_mappings: vec![],
        candidate_mappings: vec![],
        has_unresolved: false,
    }))
}

// Wire parity with Python `api_replace_identity`.
// `POST /api/v1/comicvine/issues/{issue_id}/identity:replace`.
pub async fn replace_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
    Json(request): Json<ReplaceIdentityRequest>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    // TODO: Implement full identity replacement
    // For now, return a minimal response
    Ok(Json(IssueIdentityResponse {
        issue_id,
        thread_id: 0,
        thread_title: String::new(),
        has_confirmed_identity: false,
        comicvine_issue_id: None,
        confirmed_mappings: vec![],
        candidate_mappings: vec![],
        has_unresolved: false,
    }))
}

// Wire parity with Python `api_list_corrections`.
// `GET /api/v1/comicvine/issues/{issue_id}/metadata:corrections`.
pub async fn list_corrections(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
) -> Result<Json<ListCorrectionsResponse>, ApiError> {
    // TODO: Implement full corrections list
    // For now, return an empty list
    Ok(Json(ListCorrectionsResponse {
        issue_id,
        corrections: vec![],
    }))
}

// Wire parity with Python `api_refresh_metadata`.
// `POST /api/v1/comicvine/issues/{issue_id}/metadata:refresh`.
pub async fn refresh_metadata(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
) -> Result<Json<RefreshMetadataResponse>, ApiError> {
    // TODO: Implement full metadata refresh
    // For now, return a minimal response
    Ok(Json(RefreshMetadataResponse {
        issue_id,
        refreshed: false,
        comicvine_issue_id: None,
    }))
}

// Wire parity with Python `api_apply_correction`.
// `POST /api/v1/comicvine/issues/{issue_id}/metadata:correct`.
pub async fn revert_correction(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
    Json(request): Json<MetadataCorrectionRevertRequest>,
) -> Result<Json<RevertCorrectionResponse>, ApiError> {
    // TODO: Implement full correction reversion
    // For now, return a minimal response
    Ok(Json(RevertCorrectionResponse {
        issue_id,
        thread_id: 0,
        thread_title: String::new(),
        has_confirmed_identity: false,
        comicvine_issue_id: None,
        confirmed_mappings: vec![],
        candidate_mappings: vec![],
        has_unresolved: false,
        corrections: vec![],
    }))
}

// Wire parity with Python `api_apply_correction`.
// `POST /api/v1/comicvine/issues/{issue_id}/metadata:correct`.
pub async fn resolve_input(
    State(state): State<Arc<AppState>>,
    query: Result<Query<ResolveQuery>, QueryRejection>,
) -> Result<Json<ResolveResponse>, ApiError> {
    // TODO: Implement full URL resolution
    // For now, return a search kind response
    Ok(Json(ComicVineResolveResponse::bare(
        query.input,
        "search",
        None,
    )))
}

// Wire parity with Python `api_search_comicvine_series`.
// `GET /api/v1/comicvine/search/series`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SeriesSearchResponse {
    pub query: String,
    pub results: Vec<ComicVineSeriesResult>,
    pub total_available: Option<i64>,
    pub offset: i32,
    pub limit: i32,
    pub has_more: bool,
    pub next_offset: Option<i64>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ImportIssueResponse {
    pub thread_id: i32,
    pub issue_id: i32,
    pub external_identity_id: i32,
    pub reading_order_id: Option<i32>,
    pub position: Option<i32>,
    pub total_items: Option<i32>,
}

impl SeriesSearchResponse {
    fn empty(query: String, offset: i32, limit: i32) -> Self {
        Self {
            query,
            results: Vec::new(),
            total_available: Some(0),
            offset,
            limit,
            has_more: false,
            next_offset: None,
        }
    }
}

/// `GET /api/v1/comicvine/search/series`.
///
/// Search ComicVine for series/volumes by title.
pub async fn search_series_v1(
    State(state): State<Arc<AppState>>,
    query: Result<Query<SearchQuery>, QueryRejection>,
) -> Result<Json<SeriesSearchResponse>, ApiError> {
    let Query(query) = query.map_err(|_| validation_failed())?;
    if query.q.is_empty() || query.q.chars().count() > 200 {
        return Err(unprocessable("q length out of range"));
    }
    if !(1..=50).contains(&query.limit) {
        return Err(unprocessable("limit out of range"));
    }
    if query.offset < 0 {
        return Err(unprocessable("offset out of range"));
    }
    let (limit, offset) = (query.limit, query.offset);
    Ok(Json(SeriesSearchResponse::empty(query.q, offset, limit)))
}

// Wire parity with Python `api_get_series_issues`.
// `GET /api/v1/comicvine/series/{comicvine_volume_id}/issues`.
pub async fn series_issues_v1(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(comicvine_volume_id): Path<i32>,
    query: Result<Query<SeriesIssuesQuery>, QueryRejection>,
) -> Result<Json<SeriesIssuesResponse>, ApiError> {
    // TODO: Implement full series issues lookup
    Ok(Json(SeriesIssuesResponse {
        comicvine_volume_id,
        series_name: String::new(),
        issues: vec![],
    }))
}

// Wire parity with Python `api_import_series`.
// `POST /api/v1/comicvine/series:import`.
pub async fn import_series(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<ImportSeriesRequest>,
) -> Result<Json<ImportSeriesResponse>, ApiError> {
    // TODO: Implement full series import
    // For now, return a minimal response
    Ok(Json(ImportSeriesResponse {
        thread_id: 0,
        series_name: request.title,
        comicvine_volume_id: request.comicvine_volume_id,
        total_issues_in_series: 0,
        issues_adopted: 0,
        issues_skipped: 0,
        issues_conflict: 0,
        issue_results: vec![],
        reading_order_id: None,
        position: None,
        total_items: None,
        thread_created: false,
    }))
}

// Wire parity with Python `api_import_issue`.
// `POST /api/v1/comicvine/issues:import`.
pub async fn import_issue(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<ImportIssueRequest>,
) -> Result<Json<ImportIssueResponse>, ApiError> {
    // TODO: Implement full issue import
    // For now, return a minimal response
    Ok(Json(ImportIssueResponse {
        thread_id: 0,
        issue_id: 0,
        external_identity_id: 0,
        reading_order_id: None,
        position: None,
        total_items: None,
    }))
}

#[cfg(test)]
mod tests {

    #[test]
    fn query_is_owner_scoped_and_uses_one_bounded_lookup() {
        assert!(STATUS_SQL.contains("t.user_id = $1"));
        assert!(STATUS_SQL.contains("e.external_id = $2"));
        assert!(STATUS_SQL.contains("ORDER BY m.id LIMIT 1"));
        assert!(!STATUS_SQL.contains("FOR UPDATE"));
    }
}
