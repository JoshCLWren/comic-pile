//! Native Rust implementation for issue-identity and CBL browser-called API operations.
//! 
//! This module implements the 12 API operations that are being migrated from Python
//! FastAPI to native Rust v2, specifically:
//! - Operations under `/api/v1/issue-identity/` prefix
//! - Operations under `/api/v1/cbl/` and `/api/v1/issue-identity/cbl/` prefixes
//! 
//! **Scope:** All 12 operations with wire contract compatibility matching Python,
//! SQL budget compliance, and authentication/authorization requirements.
//! 
//! **Migration:** This module replaces the Python implementation in
//! `app/api/issue_identity.py` and `app/api/cbl_sources.py`.

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{extract::{Path, State}, http::StatusCode, Json, Router};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio_postgres::Transaction;

pub mod models;
pub mod repository;
pub mod service;

/// Entry point for issue-identity API routes
pub fn router() -> Router<Arc<AppState>> {
    Router::new()
        .route("/api/v1/issue-identity/cbl-sources", axum::routing::get(discover_cbl_source_lists))
        .route("/api/v1/issue-identity/cbl-sources/browse", axum::routing::get(browse_cbl_catalog))
        .route("/api/v1/issue-identity/cbl-sources/by-comicvine-issue/{comicvine_issue_id}", axum::routing::get(search_cbl_sources_by_comicvine_issue))
        .route("/api/v1/issue-identity/cbl-sources/compare", axum::routing::post(compare_cbl_sources))
        .route("/api/v1/issue-identity/cbl-sources/folders", axum::routing::get(list_cbl_source_folders))
        .route("/api/v1/issue-identity/cbl-sources/{list_id}", axum::routing::get(get_cbl_source_list))
        .route("/api/v1/issue-identity/cbl/{list_id}/adoption-preview", axum::routing::get(api_cbl_adoption_preview))
        .route("/api/v1/issue-identity/cbl/{list_id}/adoption-plan", axum::routing::post(api_cbl_adoption_plan))
        .route("/api/v1/issue-identity/cbl/{list_id}/reading-graph-preview", axum::routing::post(api_cbl_reading_graph_preview))
        .route("/api/v1/issue-identity/reading-lists/{list_id}/cbl-candidates", axum::routing::get(get_cbl_candidates))
        .route("/api/v1/cbl/{list_id}/adoption-commit", axum::routing::post(commit_cbl_adoption))
        .route("/api/v1/cbl/{list_id}/reading-plans/{plan_id}/adoption-commit", axum::routing::post(commit_plan_adoption))
}

/// CBL source list discovery - GET /api/v1/issue-identity/cbl-sources
async fn discover_cbl_source_lists(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Query(params): axum::extract::Query<DiscoverQuery>,
) -> Result<Json<Vec<CBLSourceListDiscoveryItem>>, ApiError> {
    let conn = db::checkout(&state).await?;
    let summaries = service::list_cbl_source_previews(
        &conn,
        user.id(),
        params.q,
        params.limit,
    )
    .await
    .map_err(|e| ApiError::Internal(format!("Failed to list CBL source previews: {}", e)))?;

    let items = summaries
        .into_iter()
        .map(|summary| CBLSourceListDiscoveryItem {
            id: summary.id,
            name: summary.name,
            source_path: summary.source_path,
            source_repository: summary.source_repository,
            declared_issue_count: summary.declared_issue_count,
            content_hash: summary.content_hash,
            revision_sha: summary.revision_sha,
        })
        .collect();

    Ok(Json(items))
}

/// CBL catalog browse - GET /api/v1/issue-identity/cbl-sources/browse
async fn browse_cbl_catalog(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Query(params): axum::extract::Query<BrowseQuery>,
    Path(folder): Path<String>,
) -> Result<Json<CBLCatalogBrowsePage>, ApiError> {
    let conn = db::checkout(&state).await?;
    let browse_result = service::browse_cbl_catalog(
        &conn,
        user.id(),
        folder,
        params.q,
        params.page,
        params.page_size,
    )
    .await
    .map_err(|e| ApiError::Internal(format!("Failed to browse CBL catalog: {}", e)))?;

    Ok(Json(browse_result))
}

/// Search CBL sources by ComicVine issue - GET /api/v1/issue-identity/cbl-sources/by-comicvine-issue/{comicvine_issue_id}
async fn search_cbl_sources_by_comicvine_issue(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(comicvine_issue_id): Path<String>,
) -> Result<Json<Vec<CBLCatalogListItem>>, ApiError> {
    let conn = db::checkout(&state).await?;
    let items = service::search_cbl_sources_by_comicvine_issue(
        &conn,
        user.id(),
        comicvine_issue_id,
    )
    .await
    .map_err(|e| ApiError::Internal(format!("Failed to search CBL sources by ComicVine issue: {}", e)))?;

    Ok(Json(items))
}

/// Compare CBL sources - POST /api/v1/issue-identity/cbl-sources/compare
async fn compare_cbl_sources(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<CompareRequest>,
) -> Result<Json<CompareResult>, ApiError> {
    let conn = db::checkout(&state).await?;
    let comparison_result = service::compare_cbl_sources(
        &conn,
        user.id(),
        request.list_ids,
        request.source_path,
    )
    .await
    .map_err(|e| ApiError::Internal(format!("Failed to compare CBL sources: {}", e)))?;

    Ok(Json(comparison_result))
}

/// List CBL source folders - GET /api/v1/issue-identity/cbl-sources/folders
async fn list_cbl_source_folders(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Query(params): axum::extract::Query<FolderQuery>,
) -> Result<Json<CBLFolderListing>, ApiError> {
    let conn = db::checkout(&state).await?;
    let folder_listing = service::list_cbl_source_folders(
        &conn,
        user.id(),
        params.folder,
    )
    .await
    .map_err(|e| ApiError::Internal(format!("Failed to list CBL source folders: {}", e)))?;

    Ok(Json(folder_listing))
}

/// Get specific CBL source list - GET /api/v1/issue-identity/cbl-sources/{list_id}
async fn get_cbl_source_list(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i32>,
    Query(params): axum::extract::Query<ListDetailQuery>,
) -> Result<Json<CBLSourceListDetail>, ApiError> {
    let conn = db::checkout(&state).await?;
    let detail = service::get_cbl_source_list_detail(
        &conn,
        user.id(),
        list_id,
        params.offset,
        params.limit,
    )
    .await
    .map_err(|e| ApiError::Internal(format!("Failed to get CBL source list detail: {}", e)))?;

    if detail.is_none() {
        return Err(ApiError::NotFound("CBL source list not found".to_string()));
    }

    let preview = detail.unwrap();
    let detail_response = CBLSourceListDetail {
        id: preview.id,
        name: preview.name,
        source_path: preview.source_path,
        source_repository: preview.source_repository,
        source_ref: preview.source_ref,
        declared_issue_count: preview.declared_issue_count,
        content_hash: preview.content_hash,
        revision_sha: preview.revision_sha,
        entries_total: preview.entries_total,
        entries_offset: preview.entries_offset,
        entries_limit: preview.entries_limit,
        entries: preview.entries.into_iter().map(|entry| CBLSourceEntryDetail {
            position: entry.position,
            series_name: entry.series_name,
            issue_number: entry.issue_number,
            volume_year: entry.volume_year,
            publication_year: entry.publication_year,
            comicvine_issue_id: entry.comicvine_issue_id,
            comicvine_volume_id: entry.comicine_volume_id,
        }).collect(),
    };

    Ok(Json(detail_response))
}

/// CBL adoption preview - GET /api/v1/issue-identity/cbl/{list_id}/adoption-preview
async fn api_cbl_adoption_preview(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i32>,
) -> Result<Json<CBLAdoptionPreviewResponse>, ApiError> {
    let conn = db::checkout(&state).await?;
    let (report, plan) = service::preview_cbl_adoption(
        &conn,
        user.id(),
        list_id,
    )
    .await
    .map_err(|e| ApiError::Internal(format!("Failed to preview CBL adoption: {}", e)))?;

    let preview = service::build_cbl_adoption_preview(report, plan);
    Ok(Json(preview))
}

/// CBL adoption plan calculation - POST /api/v1/issue-identity/cbl/{list_id}/adoption-plan
async fn api_cbl_adoption_plan(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i32>,
    Json(request): Json<CBLAdoptionPlanRequest>,
) -> Result<Json<CBLAdoptionPreviewResponse>, ApiError> {
    let conn = db::checkout(&state).await?;
    let (report, plan) = service::preview_cbl_adoption(
        &conn,
        user.id(),
        list_id,
        Some(request.series_decisions),
        Some(request.entry_decisions),
    )
    .await
    .map_err(|e| ApiError::Internal(format!("Failed to calculate CBL adoption plan: {}", e)))?;

    let preview = service::build_cbl_adoption_preview(report, plan);
    Ok(Json(preview))
}

/// CBL reading graph preview - POST /api/v1/issue-identity/cbl/{list_id}/reading-graph-preview
async fn api_cbl_reading_graph_preview(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i32>,
    Json(request): Json<ReadingGraphPreviewRequest>,
) -> Result<Json<ReadingGraphPreview>, ApiError> {
    let conn = db::checkout(&state).await?;
    let graph_preview = service::preview_cbl_reading_graph(
        &conn,
        user.id(),
        list_id,
        request,
    )
    .await
    .map_err(|e| ApiError::Internal(format!("Failed to preview CBL reading graph: {}", e)))?;

    Ok(Json(graph_preview))
}

/// Get CBL candidates for reading list - GET /api/v1/issue-identity/reading-lists/{list_id}/cbl-candidates
async fn get_cbl_candidates(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i32>,
) -> Result<Json<Vec<CBLCandidate>>, ApiError> {
    let conn = db::checkout(&state).await?;
    let candidates = service::get_cbl_candidates(
        &conn,
        user.id(),
        list_id,
    )
    .await
    .map_err(|e| ApiError::Internal(format!("Failed to get CBL candidates: {}", e)))?;

    Ok(Json(candidates))
}

/// Commit CBL adoption - POST /api/v1/cbl/{list_id}/adoption-commit
async fn commit_cbl_adoption(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i32>,
    Json(request): Json<CommitAdoptionRequest>,
) -> Result<Json<AdoptionCommitResult>, ApiError> {
    let conn = db::checkout(&state).await?;
    let mut tx = conn
        .begin()
        .await
        .map_err(db::query_error)?;

    let adoption_result = service::commit_cbl_adoption(
        &mut tx,
        user.id(),
        list_id,
        request.plan_id,
        request.request_fingerprint,
    )
    .await
    .map_err(|e| ApiError::Internal(format!("Failed to commit CBL adoption: {}", e)))?;

    tx.commit().await.map_err(db::query_error)?;

    Ok(Json(adoption_result))
}

/// Commit plan adoption - POST /api/v1/cbl/{list_id}/reading-plans/{plan_id}/adoption-commit
async fn commit_plan_adoption(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path((list_id, plan_id)): Path<(i32, i32)>,
    Json(request): Json<CommitPlanAdoptionRequest>,
) -> Result<Json<PlanAdoptionCommitResult>, ApiError> {
    let conn = db::checkout(&state).await?;
    let mut tx = conn
        .begin()
        .await
        .map_err(db::query_error)?;

    let commit_result = service::commit_plan_adoption(
        &mut tx,
        user.id(),
        list_id,
        plan_id,
        request.request_fingerprint,
    )
    .await
    .map_err(|e| ApiError::Internal(format!("Failed to commit plan adoption: {}", e)))?;

    tx.commit().await.map_err(db::query_error)?;

    Ok(Json(commit_result))
}

// Query parameter structures
#[derive(Debug, Deserialize)]
struct DiscoverQuery {
    q: Option<String>,
    limit: i32,
}

#[derive(Debug, Deserialize)]
struct BrowseQuery {
    q: Option<String>,
    page: i32,
    page_size: i32,
}

#[derive(Debug, Deserialize)]
struct FolderQuery {
    folder: String,
}

#[derive(Debug, Deserialize)]
struct ListDetailQuery {
    offset: i32,
    limit: i32,
}

// Data model structures (simplified versions of Python models)
#[derive(Debug, Clone, Serialize, Deserialize)]
struct CBLSourceListDiscoveryItem {
    id: i32,
    name: String,
    source_path: String,
    source_repository: String,
    declared_issue_count: Option<i32>,
    content_hash: String,
    revision_sha: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CBLCatalogBrowsePage {
    scope: String,
    folder: String,
    query: Option<String>,
    breadcrumbs: Vec<CBLBreadcrumb>,
    folders: Vec<CBLSourceFolder>,
    items: Vec<CBLCatalogListItem>,
    page: i32,
    page_size: i堆,
    total: i32,
    total_pages: i32,
    has_next: bool,
    has_previous: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CBLBreadcrumb {
    name: String,
    path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CBLSourceFolder {
    name: String,
    path: String,
    direct_list_count: i32,
    total_list_count: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CBLCatalogListItem {
    id: i32,
    name: String,
    source_path: String,
    source_repository: String,
    declared_issue_count: Option<i32>,
    content_hash: String,
    revision_sha: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CBLFolderListing {
    folder: String,
    breadcrumbs: Vec<CBLBreadcrumb>,
    folders: Vec<CBLSourceFolder>,
    direct_list_count: i32,
    total_list_count: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CBLSourceEntryDetail {
    position: i32,
    series_name: String,
    issue_number: String,
    volume_year: Option<i32>,
    publication_year: Option<i32>,
    comicvine_issue_id: Option<String>,
    comicvine_volume_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CBLSourceListDetail {
    id: i32,
    name: String,
    source_path: String,
    source_repository: String,
    source_ref: String,
    declared_issue_count: Option<i32>,
    content_hash: String,
    revision_sha: String,
    entries_total: i32,
    entries_offset: i32,
    entries_limit: i32,
    entries: Vec<CBLSourceEntryDetail>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CBLAdoptionPreviewResponse {
    source: CBLSourceFingerprintResponse,
    total_positions: i32,
    entries: Vec<CBLAdoptionEntryResponse>,
    summary: CBLAdoptionSummaryResponse,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CBLSourceFingerprintResponse {
    source_list_id: i32,
    source_repository: String,
    source_path: String,
    content_hash: String,
    revision_sha: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CBLAdoptionEntryResponse {
    collection_excluded: bool,
    collection_exclusion_reason: Option<String>,
    collection_exclusion_ids: Vec<i32>,
    cbl_position: i32,
    cbl_entry_id: i32,
    series_name: String,
    issue_number: String,
    series_group_id: String,
    volume_year: Option<i32>,
    publication_year: Option<i32>,
    adoption_class: String,
    adoption_decision: String,
    adopted: bool,
    comicvine_issue_id: Option<String>,
    comicvine_series_id: Option<String>,
    series_provider: Option<String>,
    series_external_id: Option<String>,
    resolved_issue_id: Option<i32>,
    canonical_issue_id: Option<i32>,
    read_status: Option<String>,
    read_at: Option<String>,
    resolution_status: String,
    is_duplicate_identity: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CBLAdoptionSummaryResponse {
    reused_existing_count: i32,
    missing_would_create_count: i32,
    excluded_count: i32,
    unresolved_count: i32,
    awaiting_opt_in_count: i32,
    final_adopted_count: i32,
    final_adopted_order: Vec<i32>,
    reused_existing_positions: Vec<i32>,
    missing_would_create_positions: Vec<i32>,
    excluded_positions: Vec<i32>,
    unresolved_positions: Vec<i32>,
    awaiting_opt_in_positions: Vec<i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CBLCatalogListItem {
    id: i32,
    name: String,
    source_path: String,
    source_repository: String,
    declared_issue_count: Option<i32>,
    content_hash: String,
    revision_sha: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CBLCandidate {
    list_id: i32,
    name: String,
    mode: String,
    list_updated_at: String,
    steps: Vec<RecoveryStep>,
    added_steps: Vec<RecoveryStep>,
    removed_steps: Vec<RecoveryStep>,
    order_changed: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct RecoveryStep {
    issue_id: i32,
    label: String,
}

// Request parameter structures
#[derive(Debug, Deserialize)]
struct CompareRequest {
    list_ids: Vec<i32>,
    source_path: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ListDetailQuery {
    offset: i32,
    limit: i32,
}

#[derive(Debug, Deserialize)]
struct FolderQuery {
    folder: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CBLAdoptionPlanRequest {
    series_decisions: std::collections::HashMap<String, bool>,
    entry_decisions: std::collections::HashMap<String, bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CompareRequest {
    list_ids: Vec<i32>,
    source_path: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CompareResult {
    comparisons: Vec<ComparisonResult>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ComparisonResult {
    list_id: i32,
    name: String,
    source_path: String,
    similarity_score: f64,
    differences: Vec<Difference>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Difference {
    type: String,
    description: String,
    position: Option<i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ReadingGraphPreviewRequest {
    included_positions: Vec<i32>,
    prior_answers: std::collections::HashMap<String, String>,
    optional_list_to_preview: Option<i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CommitAdoptionRequest {
    plan_id: i32,
    request_fingerprint: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct AdoptionCommitResult {
    success: bool,
    message: String,
    receipt_id: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CommitPlanAdoptionRequest {
    request_fingerprint: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PlanAdoptionCommitResult {
    success: bool,
    message: String,
    receipt_id: i32,
    plan_id: i32,
    list_id: i32,
}