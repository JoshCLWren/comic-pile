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
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    let response = identity_state(&tx, user.id(), issue_id).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

/// `POST /api/v1/comicvine/issues/{issue_id}/identity:confirm`.
///
/// Wire parity with Python `api_confirm_identity`.
pub async fn confirm_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
    Json(request): Json<ConfirmIdentityRequest>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    let comicvine_issue_id = request.comicvine_issue_id;
    let identity = confirm_comicvine_identity(
        &state.db,
        user_id=user.id(),
        issue_id,
        comicvine_issue_id,
    ).await?;
    let state_response = get_issue_identity_state(
        &state.db,
        user_id=user.id(),
        issue_id,
    ).await?;
    Ok(Json(state_response))
}

/// `POST /api/v1/comicvine/issues/{issue_id}/identity:replace`.
///
/// Wire parity with Python `api_replace_identity`.
pub async fn replace_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
    Json(request): Json<ReplaceIdentityRequest>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    let comicvine_issue_id = request.comicvine_issue_id;
    let response = replace_comicvine_identity(
        &state.db,
        user_id=user.id(),
        issue_id,
        comicvine_issue_id,
        request.reason.as_deref(),
    ).await?;
    let state_response = get_issue_identity_state(
        &state.db,
        user_id=user.id(),
        issue_id,
    ).await?;
    Ok(Json(state_response))
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
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
) -> Result<Json<ListCorrectionsResponse>, ApiError> {
    let response = list_metadata_corrections(
        &state.db,
        user_id=user.id(),
        issue_id,
    ).await?;
    Ok(Json(response))
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
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
) -> Result<Json<RefreshMetadataResponse>, ApiError> {
    let refreshed = request_provider_refresh(
        &state.db,
        user_id=user.id(),
        issue_id,
    ).await?;
    Ok(Json(refreshed))
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
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
    Json(request): Json<MetadataCorrectionRevertRequest>,
) -> Result<Json<RevertCorrectionResponse>, ApiError> {
    revert_metadata_correction(
        &state.db,
        user_id=user.id(),
        issue_id,
        request.correction_id,
    ).await?;
    db::commit(&state).await.map_err(db::query_error)?;
    let corrections = list_metadata_corrections(
        &state.db,
        user_id=user.id(),
        issue_id,
    ).await?;
    let state_response = get_issue_identity_state(
        &state.db,
        user_id=user.id(),
        issue_id,
    ).await?;
    Ok(Json(state_response))
}

/// `POST /api/v1/comicvine/issues/{issue_id}/metadata:correct`.
///
/// Wire parity with Python `api_apply_correction`.
pub async fn apply_correction(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
    Json(request): Json<MetadataCorrectionRequest>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    await get_owned_issue_or_404(&state.db, user.id(), issue_id).await;
    let correction = apply_metadata_correction(
        &state.db,
        user_id=user.id(),
        issue_id=issue_id,
        request=request,
    ).await?;
    db::commit(&state).await.map_err(db::query_error)?;
    let state_response = get_issue_identity_state(
        &state.db,
        user_id=user.id(),
        issue_id,
    ).await?;
    Ok(Json(state_response))
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
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<ImportIssueRequest>,
) -> Result<Json<ImportIssueResponse>, ApiError> {
    let result = import_comicvine_issue(
        &state.db,
        user_id=user.id(),
        request=request,
    ).await?;
    Ok(Json(result))
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
    State(state): State<Arc<AppState>>,
    query: Result<Query<ResolveQuery>, QueryRejection>,
) -> Result<Json<ResolveResponse>, ApiError> {
    let Query(query) = query.map_err(|_| validation_failed())?;
    // Python `Query(min_length=1, max_length=1000)`.
    if query.input.is_empty() || query.input.chars().count() > 1000 {
        return Err(unprocessable("resolve input length out of range"));
    }
    let input = query.input;
    let trimmed = input.trim();
    if trimmed.is_empty() {
        return Ok(Json(ComicVineResolveResponse::bare(input, "search", None)));
    }
    let Some(parsed) = parse_comicvine_url(trimmed) else {
        let error = looks_like_url(trimmed).then_some(NOT_A_COMICVINE_URL);
        return Ok(Json(ComicVineResolveResponse::bare(input, "search", error)));
    };
    let Some(key) = provider_key() else {
        return Ok(Json(ComicVineResolveResponse::bare(
            input,
            parsed.kind(),
            Some(PROVIDER_NOT_CONFIGURED),
        )));
    };
    let mut response = ComicVineResolveResponse::bare(input, parsed.kind(), None);
    let resolved = match parsed {
        ParsedResource::Issue(id) => state
            .comicvine_limits
            .call(
                &state.outbound,
                &format!("issue/4000-{id}"),
                &format!("&field_list={}", crate::comicvine_repair::FIELDS),
                &key,
            )
            .await
            .ok()
            .and_then(|payload| resolved_issue(payload.get("results")?, id))
            .map(|issue| response.issue = Some(issue)),
        ParsedResource::Volume(id) => {
            // TODO: fetch volume and issues
            None
        }
    };
    if resolved.is_none() {
        tracing::warn!(kind = parsed.kind(), "comicvine resolve failed");
        response.validation_error = Some(RESOLVE_FAILED.to_owned());
    }
    Ok(Json(response))
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

/// `GET /api/v1/comicvine/search/series`.
///
/// Wire parity with Python `api_search_comicvine_series`.
pub async fn search_series_v1(
    State(state): State<Arc<AppState>>,
    query: Result<Query<SearchQuery>, QueryRejection>,
) -> Result<Json<SeriesSearchResponse>, ApiError> {
    let Query(query) = query.map_err(|_| validation_failed())?;
    // Python `Query(min_length=1, max_length=200)`, `limit` ge=1 le=50, `offset` ge=0.
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
    let page = i64::from(offset) / i64::from(limit) + 1;
    let key = provider_key();
    if key.is_none() || query.q.trim().is_empty() {
        return Ok(Json(SeriesSearchResponse::empty(query.q, offset, limit)));
    }
    let key = key.unwrap();
    let extra = format!(
        "&query={}&resources=volume&limit={limit}&page={page}\
         &field_list=id,name,publisher,start_year,count_of_issues,site_detail_url,image",
        encode_query(&query.q)
    );
    // Python lets provider errors escape to the global handler: a generic 500.
    let payload = state
        .comicvine_limits
        .call(&state.outbound, "search", &extra, &key)
        .await
        .map_err(|failure| {
            tracing::warn!(?failure, "comicvine series search failed");
            ApiError::Internal("Internal server error".to_owned())
        })?;
    let Some(rows) = payload.get("results").and_then(Value::as_array) else {
        return Ok(Json(SeriesSearchResponse::empty(query.q, offset, limit)));
    };
    let results: Vec<ComicVineSeriesResult> = rows.iter().filter_map(search_result).collect();
    // Widened arithmetic: `offset` may be `i32::MAX` (#4636390843).
    let total =
        coerce_provider_i64(payload.get("number_of_total_results")).unwrap_or(results.len() as i64);
    let loaded = i64::from(offset) + results.len() as i64;
    let has_more = loaded < total;
    Ok(Json(SeriesSearchResponse {
        query: query.q,
        results,
        total_available: Some(total),
        offset,
        limit,
        has_more,
        next_offset: has_more.then_some(loaded),
    }))
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
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(comicvine_volume_id): Path<i32>,
    query: Result<Query<SeriesIssuesQuery>, QueryRejection>,
) -> Result<Json<SeriesIssuesResponse>, ApiError> {
    let volume_id = comicvine_volume_id;
    let Query(query) = query.map_err(|_| validation_failed())?;
    let key = provider_key();
    Ok(Json(
        series_issues_response(&state, volume_id, query.series_name, key.as_deref()).await,
    ))
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
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<ImportSeriesRequest>,
) -> Result<Json<ImportSeriesResponse>, ApiError> {
    let result = import_comicvine_series(
        &state.db,
        user_id=user.id(),
        request=request,
    ).await?;
    Ok(Json(result))
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