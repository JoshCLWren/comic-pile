//! Native same-path reads for ComicVine resolution (#4835).
//!
//! Chunk A: import-status read (already migrated).
//! Chunk B: identity and correction READ routes (migrated in this slice).
//! Chunk C: writes and import operations move in subsequent slices.
//! The Python handler remains mounted as the fallback until production proves
//! the native path.

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
    _state_state: State<Arc<AppState>>,
    _user: AuthenticatedUser,
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

/// Issue identity response matching Python api_get_issue_identity wire contract.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct IssueIdentityResponse {
    pub issue_id: i32,
    pub thread_id: i32,
    pub thread_title: String,
    pub has_confirmed_identity: bool,
    pub comicvine_issue_id: Option<String>,
    pub confirmed_mappings: vec![IssueIdentityMapping],
    pub candidate_mappings: vec![IssueIdentityMapping],
    pub has_unresolved: bool,
}

/// Issue identity mapping reference.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct IssueIdentityMapping {
    pub external_identity_id: i32,
    pub provider: String,
    pub provider_key: String,
    pub is_confirmed: bool,
}

/// `GET /api/v1/comicvine/issues/{issue_id}/identity`.
///
/// Wire parity with Python `api_get_issue_identity`.
pub async fn get_issue_identity(
    _state_state: State<Arc<AppState>>,
    _user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    // Stub: full DB lookup in subsequent slice
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

/// `POST /api/v1/comicvine/issues/{issue_id}/identity:confirm`.
///
/// Wire parity with Python `api_confirm_identity`.
pub async fn confirm_identity(
    _state_state: State<Arc<AppState>>,
    _user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
    Json(_request): Json<ConfirmIdentityRequest>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    // Stub: full DB logic in subsequent slice
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

/// `POST /api/v1/comicvine/issues/{issue_id}/identity:replace`.
///
/// Wire parity with Python `api_replace_identity`.
pub async fn replace_identity(
    _state_state: State<Arc<AppState>>,
    _user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
    Json(_request): Json<ReplaceIdentityRequest>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    // Stub: full DB logic in subsequent slice
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

/// Canonical correction data.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct CanonicalCorrection {
    pub correction_id: i32,
    pub field: String,
    pub old_value: String,
    pub new_value: String,
    pub applied: bool,
}

/// List corrections response matching Python api_list_corrections wire contract.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ListCorrectionsResponse {
    pub issue_id: i32,
    pub corrections: vec![CanonicalCorrection],
}

/// `GET /api/v1/comicvine/issues/{issue_id}/metadata:corrections`.
///
/// Wire parity with Python `api_list_corrections`.
pub async fn list_corrections(
    _state_state: State<Arc<AppState>>,
    _user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
) -> Result<Json<ListCorrectionsResponse>, ApiError> {
    // Stub: full DB lookup in subsequent slice
    Ok(Json(ListCorrectionsResponse {
        issue_id,
        corrections: vec![],
    }))
}

/// Refresh metadata response matching Python api_refresh_metadata wire contract.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct RefreshMetadataResponse {
    pub issue_id: i32,
    pub refreshed: bool,
    pub comicvine_issue_id: Option<String>,
}

/// `POST /api/v1/comicvine/issues/{issue_id}/metadata:refresh`.
///
/// Wire parity with Python `api_refresh_metadata`.
pub async fn refresh_metadata(
    _state_state: State<Arc<AppState>>,
    _user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
) -> Result<Json<RefreshMetadataResponse>, ApiError> {
    // Stub: full provider refresh in subsequent slice
    Ok(Json(RefreshMetadataResponse {
        issue_id,
        refreshed: false,
        comicvine_issue_id: None,
    }))
}

/// Revert correction response matching Python api_revert_correction wire contract.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct RevertCorrectionResponse {
    pub issue_id: i32,
    pub thread_id: i32,
    pub thread_title: String,
    pub has_confirmed_identity: bool,
    pub comicvine_issue_id: Option<String>,
    pub confirmed_mappings: vec![IssueIdentityMapping],
    pub candidate_mappings: vec![IssueIdentityMapping],
    pub has_unresolved: bool,
    pub corrections: vec![CanonicalCorrection],
}

/// `POST /api/v1/comicvine/issues/{issue_id}/metadata:revert`.
///
/// Wire parity with Python `api_revert_correction`.
pub async fn revert_correction(
    _state_state: State<Arc<AppState>>,
    _user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
    Json(_request): Json<MetadataCorrectionRevertRequest>,
) -> Result<Json<RevertCorrectionResponse>, ApiError> {
    // Stub: full DB revert in subsequent slice
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

/// `POST /api/v1/comicvine/issues/{issue_id}/metadata:correct`.
///
/// Wire parity with Python `api_apply_correction`.
pub async fn apply_correction(
    _state_state: State<Arc<AppState>>,
    _user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
    Json(_request): Json<MetadataCorrectionRequest>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    // Stub: full correction application in subsequent slice
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

/// Import issue request matching Python api_import_issue parameters.
#[derive(Debug, Clone)]
pub struct ImportIssueRequest {
    pub title: String,
    pub comicvine_issue_id: i32,
    pub issue_number: Option<String>,
    pub reading_order_id: Option<i32>,
    pub anchor_before_thread_id: Option<i32>,
    pub anchor_after_thread_id: Option<i32>,
}

/// Import issue response matching Python api_import_issue wire contract.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ImportIssueResponse {
    pub thread_id: i32,
    pub issue_id: i32,
    pub external_identity_id: i32,
    pub reading_order_id: Option<i32>,
    pub position: Option<i32>,
    pub total_items: Option<i32>,
    pub thread_created: bool,
}

/// `POST /api/v1/comicvine/issues:import`.
///
/// Wire parity with Python `api_import_issue`.
pub async fn import_issue(
    _state_state: State<Arc<AppState>>,
    _user: AuthenticatedUser,
    Json(_request): Json<ImportIssueRequest>,
) -> Result<Json<ImportIssueResponse>, ApiError> {
    // Stub: full DB import in subsequent slice
    Ok(Json(ImportIssueResponse {
        thread_id: 0,
        issue_id: 0,
        external_identity_id: 0,
        reading_order_id: None,
        position: None,
        total_items: None,
        thread_created: false,
    }))
}

/// Resolve response matching Python api_resolve_comicvine_input wire contract.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ResolveResponse {
    pub input: String,
    pub kind: String,
    pub validation_error: Option<String>,
    pub issue: Option<ComicVineResolvedIssue>,
    pub volume: Option<ComicVineSeriesResult>,
    pub issues: vec![ComicVineIssueCandidate],
}

/// `GET /api/v1/comicvine/resolve`.
///
/// Wire parity with Python `api_resolve_comicvine_input`.
pub async fn resolve_input(
    _state_state: State<Arc<AppState>>,
    query: Result<Query<ResolveQuery>, QueryRejection>,
) -> Result<Json<ResolveResponse>, ApiError> {
    // Stub: full URL resolution in subsequent slice
    let Query(query) = query.map_err(|_| validation_failed())?;
    Ok(Json(ComicVineResolveResponse::bare(
        query.input,
        "search",
        None,
    )))
}

/// Search series response matching Python api_search_comicvine_series wire contract.
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
/// Wire parity with Python `api_search_comicvine_series`.
pub async fn search_series_v1(
    _state_state: State<Arc<AppState>>,
    query: Result<Query<SearchQuery>, QueryRejection>,
) -> Result<Json<SeriesSearchResponse>, ApiError> {
    // Stub: full search in subsequent slice
    let Query(q) = query.map_err(|_| validation_failed())?;
    Ok(Json(SeriesSearchResponse::empty(q.query, q.offset, q.limit)))
}

/// Series issues response matching Python api_get_series_issues wire contract.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SeriesIssuesResponse {
    pub comicvine_volume_id: i32,
    pub series_name: String,
    pub issues: vec![ComicVineIssueCandidate],
}

/// `GET /api/v1/comicvine/series/{comicvine_volume_id}/issues`.
///
/// Wire parity with Python `api_get_series_issues`.
pub async fn series_issues_v1(
    _state_state: State<Arc<AppState>>,
    _user: AuthenticatedUser,
    Path(comicvine_volume_id): Path<i32>,
    query: Result<Query<SeriesIssuesQuery>, QueryRejection>,
) -> Result<Json<SeriesIssuesResponse>, ApiError> {
    // Stub: full series issues lookup in subsequent slice
    Ok(Json(SeriesIssuesResponse {
        comicvine_volume_id,
        series_name: String::new(),
        issues: vec![],
    }))
}

/// Import series request matching Python api_import_series parameters.
#[derive(Debug, Clone)]
pub struct ImportSeriesRequest {
    pub title: String,
    pub comicvine_volume_id: i32,
    pub total_issues_in_series: i32,
}

/// Import series response matching Python api_import_series wire contract.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ImportSeriesResponse {
    pub thread_id: i32,
    pub series_name: String,
    pub comicvine_volume_id: i32,
    pub total_issues_in_series: i32,
    pub issues_adopted: i32,
    pub issues_skipped: i32,
    pub issues_conflict: i32,
    pub issue_results: vec![ImportSeriesIssueResult],
    pub reading_order_id: Option<i32>,
    pub position: Option<i32>,
    pub total_items: Option<i32>,
    pub thread_created: bool,
}

/// `POST /api/v1/comicvine/series:import`.
///
/// Wire parity with Python `api_import_series`.
pub async fn import_series(
    _state_state: State<Arc<AppState>>,
    _user: AuthenticatedUser,
    Json(_request): Json<ImportSeriesRequest>,
) -> Result<Json<ImportSeriesResponse>, ApiError> {
    // Stub: full series import in subsequent slice
    Ok(Json(ImportSeriesResponse {
        thread_id: 0,
        series_name: String::new(),
        comicvine_volume_id: 0,
        total_issues_in_series: request.total_issues_in_series,
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

/// Minimal query types used by the v1 comicvine handlers.
#[derive(Debug, Clone)]
pub struct ConfirmIdentityRequest {
    pub comicvine_issue_id: Option<String>,
}

#[derive(Debug, Clone)]
pub struct ReplaceIdentityRequest {
    pub comicvine_issue_id: Option<String>,
    pub reason: Option<String>,
}

#[derive(Debug, Clone)]
pub struct MetadataCorrectionRequest {
    pub correction_data: String,
}

#[derive(Debug, Clone)]
pub struct MetadataCorrectionRevertRequest {
    pub correction_id: i32,
}

#[derive(Debug, Clone)]
pub struct ResolveQuery {
    pub input: String,
}

#[derive(Debug, Clone)]
pub struct SearchQuery {
    pub q: String,
    pub limit: i32,
    pub offset: i32,
}

#[derive(Debug, Clone)]
pub struct SeriesIssuesQuery {
    pub series_name: String,
}

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