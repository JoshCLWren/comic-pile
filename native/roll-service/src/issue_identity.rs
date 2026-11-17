//! Issue Identity / CBL Adoption endpoints ported to native Rust.
//!
//! These endpoints provide read-only CBL catalog browsing, CBL source discovery,
//! reconciliation, adoption planning, and commit functionality.

use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use deadpool_postgres::Pool;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tracing::instrument;

use crate::{
    auth::middleware::AuthUser,
    db::checkout,
    ApiError, AppState,
};

/// Shared CBL source list discovery item
#[derive(Debug, Serialize, Deserialize)]
pub struct CblSourceListDiscoveryItem {
    pub id: i32,
    pub name: String,
    pub source_path: String,
    pub source_repository: String,
    pub declared_issue_count: Option<i32>,
    pub content_hash: String,
    pub revision_sha: String,
}

/// CBL source entry detail
#[derive(Debug, Serialize, Deserialize)]
pub struct CblSourceEntryDetail {
    pub position: i32,
    pub series_name: String,
    pub issue_number: String,
    pub volume_year: Option<i32>,
    pub publication_year: Option<i32>,
    pub comicvine_issue_id: Option<String>,
    pub comicvine_volume_id: Option<String>,
}

/// CBL source list detail with paginated entries
#[derive(Debug, Serialize, Deserialize)]
pub struct CblSourceListDetail {
    pub id: i32,
    pub name: String,
    pub source_path: String,
    pub source_repository: String,
    pub source_ref: String,
    pub declared_issue_count: Option<i32>,
    pub content_hash: String,
    pub revision_sha: String,
    pub entries_total: i32,
    pub entries_offset: i32,
    pub entries_limit: i32,
    pub entries: Vec<CblSourceEntryDetail>,
}

/// CBL catalog folder listing
#[derive(Debug, Serialize, Deserialize)]
pub struct CblSourceFolder {
    pub name: String,
    pub path: String,
    pub direct_list_count: i32,
    pub total_list_count: i32,
}

/// CBL breadcrumb
#[derive(Debug, Serialize, Deserialize)]
pub struct CblBreadcrumb {
    pub name: String,
    pub path: String,
}

/// CBL folder listing response
#[derive(Debug, Serialize, Deserialize)]
pub struct CblFolderListingResponse {
    pub folder: String,
    pub breadcrumbs: Vec<CblBreadcrumb>,
    pub folders: Vec<CblSourceFolder>,
    pub direct_list_count: i32,
    pub total_list_count: i32,
}

/// CBL catalog browse response
#[derive(Debug, Serialize, Deserialize)]
pub struct CblCatalogBrowseResponse {
    pub scope: String,
    pub folder: String,
    pub query: Option<String>,
    pub breadcrumbs: Vec<CblBreadcrumb>,
    pub folders: Vec<CblSourceFolder>,
    pub items: Vec<CblSourceListDiscoveryItem>,
    pub page: i32,
    pub page_size: i32,
    pub total: i32,
    pub total_pages: i32,
    pub has_next: bool,
    pub has_previous: bool,
}

/// Comic Vine occurrence in CBL sources
#[derive(Debug, Serialize, Deserialize)]
pub struct CblComicvineOccurrence {
    pub list_id: i32,
    pub list_name: String,
    pub source_path: String,
    pub source_repository: String,
    pub source_ref: String,
    pub revision_sha: String,
    pub position: i32,
    pub series_name: String,
    pub issue_number: String,
    pub volume_year: Option<i32>,
    pub publication_year: Option<i32>,
    pub comicvine_issue_id: String,
    pub comicvine_volume_id: Option<String>,
}

/// Page of Comic Vine occurrences
#[derive(Debug, Serialize, Deserialize)]
pub struct CblComicvineOccurrencePage {
    pub comicvine_issue_id: String,
    pub occurrences_total: i32,
    pub lists_total: i32,
    pub occurrences_offset: i32,
    pub occurrences_limit: i32,
    pub occurrences: Vec<CblComicvineOccurrence>,
}

/// CBL source comparison match
#[derive(Debug, Serialize, Deserialize)]
pub struct CblSourceComparisonMatch {
    pub list_id: i32,
    pub list_name: String,
    pub source_path: String,
    pub source_repository: String,
    pub source_ref: String,
    pub revision_sha: String,
    pub declared_issue_count: Option<i32>,
    pub entries_total: i32,
    pub distinct_source_issues: i32,
    pub matched_input_count: i32,
    pub input_total: i32,
    pub matched_occurrence_count: i32,
    pub duplicate_match_count: i32,
    pub source_only_issue_count: i32,
    pub input_coverage_percentage: i32,
    pub source_coverage_percentage: i32,
    pub order_status: String,
    pub order_pair_count: i32,
    pub order_disagreement_count: i32,
    pub matched_input_ids: Vec<String>,
    pub missing_input_ids: Vec<String>,
    pub score: i32,
}

/// CBL source comparison response
#[derive(Debug, Serialize, Deserialize)]
pub struct CblSourceComparisonResponse {
    pub comicvine_issue_ids: Vec<String>,
    pub input_total: i32,
    pub candidates_total: i32,
    pub candidates: Vec<CblSourceComparisonMatch>,
}

/// CBL adoption class
#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CblAdoptionClass {
    Existing,
    MissingImportable,
    AmbiguousUnresolved,
}

/// CBL adoption decision
#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CblAdoptionDecision {
    IncludedExisting,
    WouldCreateMissing,
    AwaitingOptIn,
    Excluded,
    Unresolved,
}

/// CBL adoption preview entry
#[derive(Debug, Serialize, Deserialize)]
pub struct CblAdoptionPreviewEntry {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub collection_excluded: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub collection_exclusion_reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub collection_exclusion_ids: Option<Vec<i32>>,
    pub cbl_position: i32,
    pub cbl_entry_id: i32,
    pub series_name: String,
    pub issue_number: String,
    pub series_group_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub volume_year: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub publication_year: Option<i32>,
    pub adoption_class: CblAdoptionClass,
    pub adoption_decision: CblAdoptionDecision,
    pub adopted: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub comicvine_issue_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub comicvine_series_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub series_provider: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub series_external_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub resolved_issue_id: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub canonical_issue_id: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub read_status: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub read_at: Option<String>,
    pub resolution_status: String,
    pub is_duplicate_identity: bool,
}

/// CBL adoption preview summary
#[derive(Debug, Serialize, Deserialize)]
pub struct CblAdoptionSummaryResponse {
    pub reused_existing_count: i32,
    pub missing_would_create_count: i32,
    pub excluded_count: i32,
    pub unresolved_count: i32,
    pub awaiting_opt_in_count: i32,
    pub final_adopted_count: i32,
    pub final_adopted_order: Vec<i32>,
    pub reused_existing_positions: Vec<i32>,
    pub missing_would_create_positions: Vec<i32>,
    pub excluded_positions: Vec<i32>,
    pub unresolved_positions: Vec<i32>,
    pub awaiting_opt_in_positions: Vec<i32>,
}

/// CBL adoption preview source
#[derive(Debug, Serialize, Deserialize)]
pub struct CblSourceFingerprintResponse {
    pub source_list_id: i32,
    pub source_repository: String,
    pub source_path: String,
    pub content_hash: String,
    pub revision_sha: String,
}

/// CBL adoption preview response
#[derive(Debug, Serialize, Deserialize)]
pub struct CblAdoptionPreviewResponse {
    pub source: CblSourceFingerprintResponse,
    pub total_positions: i32,
    pub entries: Vec<CblAdoptionPreviewEntry>,
    pub summary: CblAdoptionSummaryResponse,
}

/// CBL adoption plan request
#[derive(Debug, Serialize, Deserialize)]
pub struct CblAdoptionPlanRequest {
    #[serde(default)]
    pub series_decisions: std::collections::HashMap<String, bool>,
    #[serde(default)]
    pub entry_decisions: std::collections::HashMap<String, bool>,
}

/// CBL adoption commit request
#[derive(Debug, Serialize, Deserialize)]
pub struct CblAdoptionCommitRequest {
    pub entry_decisions: std::collections::HashMap<i32, String>,
    pub series_decisions: Vec<CblSeriesDecision>,
    pub series_overrides: Vec<CblSeriesOverride>,
    pub content_hash: String,
    pub revision_sha: String,
}

/// Series decision for commit
#[derive(Debug, Serialize, Deserialize)]
pub struct CblSeriesDecision {
    pub series_name: String,
    pub decision: String,
}

/// Series override for commit
#[derive(Debug, Serialize, Deserialize)]
pub struct CblSeriesOverride {
    pub cbl_position: i32,
    pub decision: String,
}

/// CBL adoption commit response
#[derive(Debug, Serialize, Deserialize)]
pub struct CblAdoptionCommitResponse {
    pub id: i32,
    pub user_id: i32,
    pub name: String,
    pub ordering_mode: String,
    pub lanes: Vec<serde_json::Value>,
    pub nodes: Vec<serde_json::Value>,
    pub created_at: String,
    pub updated_at: String,
    pub reused_positions: Vec<i32>,
    pub created_positions: Vec<i32>,
    pub excluded_positions: Vec<i32>,
    pub unresolved_positions: Vec<i32>,
}

/// CBL reading list candidate entry
#[derive(Debug, Serialize, Deserialize)]
pub struct CblReadingListInputEntry {
    pub position: i32,
    pub issue_id: i32,
    pub series_name: String,
    pub issue_number: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub comicvine_issue_id: Option<String>,
    pub comicvine_issue_ids: Vec<String>,
    pub identity_status: String,
}

/// CBL reading list candidates response
#[derive(Debug, Serialize, Deserialize)]
pub struct CblReadingListCandidatesResponse {
    pub list_id: i32,
    pub list_name: String,
    pub input_entry_count: i32,
    pub input_confirmed_total: i32,
    pub input_missing_count: i32,
    pub input_conflict_count: i32,
    pub input_ids: Vec<String>,
    pub entries: Vec<CblReadingListInputEntry>,
    pub candidates_total: i32,
    pub candidates: Vec<CblSourceComparisonMatch>,
}

/// Reading graph preview types
#[derive(Debug, Serialize, Deserialize)]
pub struct ReadingGraphSeriesReference {
    pub comicvine_volume_id: String,
    pub series_name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub year: Option<i32>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ReadingGraphSeriesNode {
    pub comicvine_volume_id: String,
    pub series_name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub year: Option<i32>,
    pub state: String,
    pub unread_count: i32,
    pub rollable_count: i32,
    pub waiting_count: i32,
    pub waits_for_issue_ids: Vec<i32>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ReadingGraphChoiceEffect {
    pub choice: String,
    pub label: String,
    pub detail: String,
    pub rollable_issue_ids: Vec<i32>,
    pub waiting_issue_ids: Vec<i32>,
    pub series: Vec<ReadingGraphSeriesNode>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ReadingGraphOverlap {
    pub overlap_id: String,
    pub continuing_series: ReadingGraphSeriesReference,
    pub waiting_series: ReadingGraphSeriesReference,
    pub question: String,
    pub blocked_issue_ids: Vec<i32>,
    pub choices: Vec<ReadingGraphChoiceEffect>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub selected_choice: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ReadingGraphCycleError {
    pub code: String,
    pub message: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ReadingGraphIssueReference {
    pub issue_id: i32,
    pub series_name: String,
    pub issue_number: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub comicvine_volume_id: Option<String>,
    pub blockers: Vec<ReadingGraphBlocker>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ReadingGraphBlocker {
    pub kind: String,
    pub list_id: i32,
    pub waiting_on_issue_ids: Vec<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub gate_issue_id: Option<i32>,
    pub explanation: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ReadingGraphPreview {
    pub source_list_id: i32,
    pub content_hash: String,
    pub revision_sha: String,
    pub series: Vec<ReadingGraphSeriesNode>,
    pub overlaps: Vec<ReadingGraphOverlap>,
    pub issues: Vec<ReadingGraphIssueReference>,
    pub rollable_issue_ids: Vec<i32>,
    pub waiting_issue_ids: Vec<i32>,
    pub cycle_errors: Vec<ReadingGraphCycleError>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ReadingGraphPreviewRequest {
    pub included_positions: Vec<i32>,
    pub overlap_choices: Vec<ReadingGraphOverlapChoice>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ReadingGraphOverlapChoice {
    pub overlap_id: String,
    pub choice: String,
}

// Query parameters
#[derive(Debug, Deserialize)]
pub struct DiscoverCblSourcesParams {
    #[serde(default)]
    pub q: Option<String>,
    #[serde(default = "default_limit_25")]
    pub limit: i32,
}

fn default_limit_25() -> i32 { 25 }

#[derive(Debug, Deserialize)]
pub struct GetCblSourceListParams {
    #[serde(default)]
    pub offset: i32,
    #[serde(default = "default_limit_1000")]
    pub limit: i32,
}

fn default_limit_1000() -> i32 { 1000 }

#[derive(Debug, Deserialize)]
pub struct BrowseCblCatalogParams {
    #[serde(default)]
    pub folder: String,
    #[serde(default)]
    pub q: Option<String>,
    #[serde(default = "default_page_1")]
    pub page: i32,
    #[serde(default = "default_page_size_50")]
    pub page_size: i32,
}

fn default_page_1() -> i32 { 1 }
fn default_page_size_50() -> i32 { 50 }

#[derive(Debug, Deserialize)]
pub struct CblOccurrenceParams {
    #[serde(default)]
    pub offset: i32,
    #[serde(default = "default_limit_50")]
    pub limit: i32,
}

fn default_limit_50() -> i32 { 50 }

#[derive(Debug, Deserialize)]
pub struct CompareCblSourcesParams {
    #[serde(default = "default_limit_50")]
    pub limit: i32,
}

#[derive(Debug, Deserialize)]
pub struct CblCandidatesParams {
    #[serde(default = "default_limit_50")]
    pub limit: i32,
}

/// POST /api/v1/issue-identity/cbl-sources/compare
#[instrument(skip(state, auth))]
pub async fn compare_cbl_sources(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
    Query(params): Query<CompareCblSourcesParams>,
    Json(payload): Json<CompareCblSourcesRequest>,
) -> Result<Json<CblSourceComparisonResponse>, ApiError> {
    let pool = checkout(&state.pool).await?;
    
    // This is a placeholder - full implementation requires the comparison logic
    // from cbl_comicvine_lookup_service.py
    let response = CblSourceComparisonResponse {
        comicvine_issue_ids: payload.comicvine_issue_ids,
        input_total: 0,
        candidates_total: 0,
        candidates: vec![],
    };
    
    Ok(Json(response))
}

#[derive(Debug, Deserialize)]
pub struct CompareCblSourcesRequest {
    pub comicvine_issue_ids: Vec<String>,
}

/// GET /api/v1/issue-identity/cbl-sources
#[instrument(skip(state, auth))]
pub async fn discover_cbl_source_lists(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
    Query(params): Query<DiscoverCblSourcesParams>,
) -> Result<Json<Vec<CblSourceListDiscoveryItem>>, ApiError> {
    let pool = checkout(&state.pool).await?;
    
    // Placeholder - needs full implementation from cbl_source_service.py
    let mut query = String::from(
        r#"
        SELECT 
            csl.id,
            csl.name,
            csl.source_path,
            cs.repository,
            csl.declared_issue_count,
            csl.content_hash,
            csl.revision_sha
        FROM cbl_source_lists csl
        JOIN cbl_sources cs ON csl.source_id = cs.id
        WHERE csl.active = true
        "#
    );
    
    let mut param_count = 0;
    let mut params_vec: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> = vec![];
    
    if let Some(ref q) = params.q {
        if !q.is_empty() {
            param_count += 1;
            query.push_str(&format!(" AND (csl.name ILIKE ${} OR csl.source_path ILIKE ${})", param_count, param_count));
            let pattern = format!("%{}%", q);
            params_vec.push(&pattern);
        }
    }
    
    query.push_str(" ORDER BY csl.name LIMIT $");
    param_count += 1;
    query.push_str(&param_count.to_string());
    params_vec.push(&params.limit);
    
    let rows = pool.query(&query, &params_vec).await.map_err(|e| {
        tracing::error!("discover_cbl_source_lists query failed: {}", e);
        ApiError::Internal("CBL source discovery failed".to_string())
    })?;
    
    let items = rows.into_iter().map(|row| CblSourceListDiscoveryItem {
        id: row.get(0),
        name: row.get(1),
        source_path: row.get(2),
        source_repository: row.get(3),
        declared_issue_count: row.get(4),
        content_hash: row.get(5),
        revision_sha: row.get(6),
    }).collect();
    
    Ok(Json(items))
}

/// GET /api/v1/issue-identity/cbl-sources/{list_id}
#[instrument(skip(state, auth))]
pub async fn get_cbl_source_list(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
    Path(list_id): Path<i32>,
    Query(params): Query<GetCblSourceListParams>,
) -> Result<Json<CblSourceListDetail>, ApiError> {
    let pool = checkout(&state.pool).await?;
    
    // Load source list
    let list_row = pool.query_opt(
        r#"
        SELECT csl.id, csl.name, csl.source_path, csl.source_repository, csl.declared_issue_count,
               csl.content_hash, csl.revision_sha, cs.repository, cs.source_path as source_path_ref
        FROM cbl_source_lists csl
        JOIN cbl_sources cs ON csl.source_id = cs.id
        WHERE csl.id = $1 AND csl.active = true
        "#,
        &[&list_id],
    ).await.map_err(|e| {
        tracing::error!("get_cbl_source_list query failed: {}", e);
        ApiError::Internal("CBL source list load failed".to_string())
    })?;
    
    let list_row = list_row.ok_or(ApiError::NotFound("CBL source list not found".to_string()))?;
    
    let id: i32 = list_row.get(0);
    let name: String = list_row.get(1);
    let source_path: String = list_row.get(2);
    let source_repository: String = list_row.get(3);
    let declared_issue_count: Option<i32> = list_row.get(4);
    let content_hash: String = list_row.get(5);
    let revision_sha: String = list_row.get(6);
    let repository: String = list_row.get(7);
    let source_ref: String = list_row.get(8);
    
    // Load entries with ComicVine IDs
    let entries_rows = pool.query(
        r#"
        SELECT 
            cse.position,
            cse.series_name,
            cse.issue_number,
            cse.volume_year,
            cse.publication_year,
            ei.external_id as comicvine_issue_id,
            ev.external_id as comicvine_volume_id
        FROM cbl_source_entries cse
        LEFT JOIN external_identities ei ON cse.external_issue_identity_id = ei.id
        LEFT JOIN external_identities ev ON cse.external_series_identity_id = ev.id
        WHERE cse.list_id = $1
        ORDER BY cse.position, cse.id
        LIMIT $2 OFFSET $3
        "#,
        &[&list_id, &params.limit, &params.offset],
    ).await.map_err(|e| {
        tracing::error!("get_cbl_source_list entries query failed: {}", e);
        ApiError::Internal("CBL source entries load failed".to_string())
    })?;
    
    let entries = entries_rows.into_iter().map(|row| CblSourceEntryDetail {
        position: row.get(0),
        series_name: row.get(1),
        issue_number: row.get(2),
        volume_year: row.get(3),
        publication_year: row.get(4),
        comicvine_issue_id: row.get(5),
        comicvine_volume_id: row.get(6),
    }).collect();
    
    // Get total count
    let total_count: i64 = pool.query_one(
        "SELECT COUNT(*) FROM cbl_source_entries WHERE list_id = $1",
        &[&list_id],
    ).await.map_err(|e| {
        tracing::error!("get_cbl_source_list count query failed: {}", e);
        ApiError::Internal("CBL source entries count failed".to_string())
    })?.get(0);
    
    let response = CblSourceListDetail {
        id,
        name,
        source_path,
        source_repository,
        source_ref,
        declared_issue_count,
        content_hash,
        revision_sha,
        entries_total: total_count as i32,
        entries_offset: params.offset,
        entries_limit: params.limit,
        entries,
    };
    
    Ok(Json(response))
}

/// GET /api/v1/issue-identity/cbl-sources/folders
#[instrument(skip(state, auth))]
pub async fn list_cbl_source_folders(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
    Query(params): Query<BrowseCblCatalogParams>,
) -> Result<Json<CblFolderListingResponse>, ApiError> {
    let pool = checkout(&state.pool).await?;
    
    // Validate folder path
    let folder = params.folder.trim();
    if folder.contains('\\') || folder.contains("..") || folder.contains("//") {
        return Err(ApiError::BadRequest("Invalid folder path".to_string()));
    }
    
    // Placeholder - needs full implementation from cbl_catalog.py
    let response = CblFolderListingResponse {
        folder: folder.to_string(),
        breadcrumbs: vec![CblBreadcrumb { name: "All CBLs".to_string(), path: "".to_string() }],
        folders: vec![],
        direct_list_count: 0,
        total_list_count: 0,
    };
    
    Ok(Json(response))
}

/// GET /api/v1/issue-identity/cbl-sources/browse
#[instrument(skip(state, auth))]
pub async fn browse_cbl_source_catalog(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
    Query(params): Query<BrowseCblCatalogParams>,
) -> Result<Json<CblCatalogBrowseResponse>, ApiError> {
    let pool = checkout(&state.pool).await?;
    
    // Placeholder - needs full implementation from cbl_catalog.py
    let response = CblCatalogBrowseResponse {
        scope: if params.q.is_some() && !params.q.as_ref().unwrap().is_empty() { "search".to_string() } else { "folder".to_string() },
        folder: params.folder,
        query: params.q,
        breadcrumbs: vec![CblBreadcrumb { name: "All CBLs".to_string(), path: "".to_string() }],
        folders: vec![],
        items: vec![],
        page: params.page,
        page_size: params.page_size,
        total: 0,
        total_pages: 0,
        has_next: false,
        has_previous: false,
    };
    
    Ok(Json(response))
}

/// GET /api/v1/issue-identity/cbl-sources/by-comicvine-issue/{comicvine_issue_id}
#[instrument(skip(state, auth))]
pub async fn find_cbl_sources_by_comicvine_issue(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
    Path(comicvine_issue_id): Path<String>,
    Query(params): Query<CblOccurrenceParams>,
) -> Result<Json<CblComicvineOccurrencePage>, ApiError> {
    let pool = checkout(&state.pool).await?;
    
    if comicvine_issue_id.trim().is_empty() {
        return Err(ApiError::BadRequest("Comic Vine issue ID must not be blank".to_string()));
    }
    
    // Load occurrences
    let rows = pool.query(
        r#"
        SELECT 
            csl.id as list_id,
            csl.name as list_name,
            csl.source_path,
            cs.repository as source_repository,
            csl.revision_sha,
            cse.position,
            cse.series_name,
            cse.issue_number,
            cse.volume_year,
            cse.publication_year,
            ei.external_id as comicvine_issue_id,
            ev.external_id as comicvine_volume_id
        FROM cbl_source_entries cse
        JOIN cbl_source_lists csl ON cse.list_id = csl.id
        JOIN cbl_sources cs ON csl.source_id = cs.id
        JOIN external_identities ei ON cse.external_issue_identity_id = ei.id
        LEFT JOIN external_identities ev ON cse.external_series_identity_id = ev.id
        WHERE csl.active = true AND ei.external_id = $1
        ORDER BY csl.id, cse.position
        LIMIT $2 OFFSET $3
        "#,
        &[&comicvine_issue_id, &params.limit, &params.offset],
    ).await.map_err(|e| {
        tracing::error!("find_cbl_sources_by_comicvine_issue query failed: {}", e);
        ApiError::Internal("CBL comicvine lookup failed".to_string())
    })?;
    
    let occurrences = rows.into_iter().map(|row| CblComicvineOccurrence {
        list_id: row.get(0),
        list_name: row.get(1),
        source_path: row.get(2),
        source_repository: row.get(3),
        source_ref: row.get(4),
        revision_sha: row.get(5),
        position: row.get(6),
        series_name: row.get(7),
        issue_number: row.get(8),
        volume_year: row.get(9),
        publication_year: row.get(10),
        comicvine_issue_id: row.get(11),
        comicvine_volume_id: row.get(12),
    }).collect();
    
    // Get totals
    let totals = pool.query_one(
        r#"
        SELECT COUNT(*), COUNT(DISTINCT csl.id)
        FROM cbl_source_entries cse
        JOIN cbl_source_lists csl ON cse.list_id = csl.id
        JOIN external_identities ei ON cse.external_issue_identity_id = ei.id
        WHERE csl.active = true AND ei.external_id = $1
        "#,
        &[&comicvine_issue_id],
    ).await.map_err(|e| {
        tracing::error!("find_cbl_sources_by_comicvine_issue totals query failed: {}", e);
        ApiError::Internal("CBL comicvine lookup totals failed".to_string())
    })?;
    
    let occurrences_total: i64 = totals.get(0);
    let lists_total: i64 = totals.get(1);
    
    let response = CblComicvineOccurrencePage {
        comicvine_issue_id: comicvine_issue_id.trim().to_string(),
        occurrences_total: occurrences_total as i32,
        lists_total: lists_total as i32,
        occurrences_offset: params.offset,
        occurrences_limit: params.limit,
        occurrences,
    };
    
    Ok(Json(response))
}

/// GET /api/v1/issue-identity/reading-lists/{list_id}/cbl-candidates
#[instrument(skip(state, auth))]
pub async fn find_cbl_candidates_for_reading_list(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
    Path(list_id): Path<i32>,
    Query(params): Query<CblCandidatesParams>,
) -> Result<Json<CblReadingListCandidatesResponse>, ApiError> {
    let pool = checkout(&state.pool).await?;
    
    // Placeholder - needs full implementation from cbl_comicvine_lookup_service.py
    let response = CblReadingListCandidatesResponse {
        list_id,
        list_name: String::new(),
        input_entry_count: 0,
        input_confirmed_total: 0,
        input_missing_count: 0,
        input_conflict_count: 0,
        input_ids: vec![],
        entries: vec![],
        candidates_total: 0,
        candidates: vec![],
    };
    
    Ok(Json(response))
}

/// GET /api/v1/issue-identity/cbl/{list_id}/adoption-preview
#[instrument(skip(state, auth))]
pub async fn cbl_adoption_preview(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
    Path(list_id): Path<i32>,
) -> Result<Json<CblAdoptionPreviewResponse>, ApiError> {
    let pool = checkout(&state.pool).await?;
    
    // Placeholder - needs full implementation from cbl_reconciliation.py
    // This requires reconcile_cbl_source_list + calculate_cbl_adoption_plan
    let response = CblAdoptionPreviewResponse {
        source: CblSourceFingerprintResponse {
            source_list_id: list_id,
            source_repository: String::new(),
            source_path: String::new(),
            content_hash: String::new(),
            revision_sha: String::new(),
        },
        total_positions: 0,
        entries: vec![],
        summary: CblAdoptionSummaryResponse {
            reused_existing_count: 0,
            missing_would_create_count: 0,
            excluded_count: 0,
            unresolved_count: 0,
            awaiting_opt_in_count: 0,
            final_adopted_count: 0,
            final_adopted_order: vec![],
            reused_existing_positions: vec![],
            missing_would_create_positions: vec![],
            excluded_positions: vec![],
            unresolved_positions: vec![],
            awaiting_opt_in_positions: vec![],
        },
    };
    
    Ok(Json(response))
}

/// POST /api/v1/issue-identity/cbl/{list_id}/adoption-plan
#[instrument(skip(state, auth))]
pub async fn cbl_adoption_plan(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
    Path(list_id): Path<i32>,
    Json(request): Json<CblAdoptionPlanRequest>,
) -> Result<Json<CblAdoptionPreviewResponse>, ApiError> {
    let pool = checkout(&state.pool).await?;
    
    // Placeholder - needs full implementation from cbl_reconciliation.py
    let response = CblAdoptionPreviewResponse {
        source: CblSourceFingerprintResponse {
            source_list_id: list_id,
            source_repository: String::new(),
            source_path: String::new(),
            content_hash: String::new(),
            revision_sha: String::new(),
        },
        total_positions: 0,
        entries: vec![],
        summary: CblAdoptionSummaryResponse {
            reused_existing_count: 0,
            missing_would_create_count: 0,
            excluded_count: 0,
            unresolved_count: 0,
            awaiting_opt_in_count: 0,
            final_adopted_count: 0,
            final_adopted_order: vec![],
            reused_existing_positions: vec![],
            missing_would_create_positions: vec![],
            excluded_positions: vec![],
            unresolved_positions: vec![],
            awaiting_opt_in_positions: vec![],
        },
    };
    
    Ok(Json(response))
}

/// GET /api/v1/issue-identity/cbl/{list_id}/reconciliation
#[instrument(skip(state, auth))]
pub async fn cbl_reconciliation(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
    Path(list_id): Path<i32>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let pool = checkout(&state.pool).await?;
    
    // Placeholder - returns basic reconciliation report
    let response = serde_json::json!({
        "total_positions": 0,
        "resolved_count": 0,
        "unresolved_count": 0,
        "duplicate_identity_groups": 0,
        "ambiguous_count": 0,
        "entries": [],
        "first_unread_position": null,
        "first_unread_entry": null,
        "source_list_id": list_id,
        "source_repository": null,
        "source_path": null,
        "content_hash": null,
        "revision_sha": null,
        "declared_issue_count": null,
        "missing_source_entries": [],
        "extra_member_issue_ids": [],
        "ambiguous_mappings": [],
        "duplicate_identity_issues": [],
        "first_unread_issue_id": null,
    });
    
    Ok(Json(response))
}

/// GET /api/v1/issue-identity/anomalies
#[instrument(skip(state, auth))]
pub async fn get_issue_identity_anomalies(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
) -> Result<Json<serde_json::Value>, ApiError> {
    // Placeholder - needs implementation
    Ok(Json(serde_json::json!({ "anomalies": [] })))
}

/// GET /api/v1/issue-identity/canonical/{comicvine_issue_id}
#[instrument(skip(state, auth))]
pub async fn get_canonical_issue(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
    Path(comicvine_issue_id): Path<String>,
) -> Result<Json<serde_json::Value>, ApiError> {
    // Placeholder - needs implementation
    Ok(Json(serde_json::json!({ "canonical_issue_id": null })))
}

/// GET /api/v1/issue-identity/conflicts
#[instrument(skip(state, auth))]
pub async fn get_issue_identity_conflicts(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
) -> Result<Json<serde_json::Value>, ApiError> {
    // Placeholder - needs implementation
    Ok(Json(serde_json::json!({ "conflicts": [] })))
}

/// POST /api/v1/issue-identity/consolidate
#[instrument(skip(state, auth))]
pub async fn consolidate_issue_identity(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
    Json(payload): Json<serde_json::Value>,
) -> Result<Json<serde_json::Value>, ApiError> {
    // Placeholder - needs implementation
    Ok(Json(serde_json::json!({ "consolidated": true })))
}

/// GET /api/v1/issue-identity/report
#[instrument(skip(state, auth))]
pub async fn get_issue_identity_report(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
) -> Result<Json<serde_json::Value>, ApiError> {
    // Placeholder - needs implementation
    Ok(Json(serde_json::json!({ "report": {} })))
}

/// POST /api/v1/cbl/{list_id}/adoption-commit
#[instrument(skip(state, auth))]
pub async fn cbl_adoption_commit(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
    Path(list_id): Path<i32>,
    Json(request): Json<CblAdoptionCommitRequest>,
) -> Result<Json<CblAdoptionCommitResponse>, ApiError> {
    // Placeholder - needs full implementation from cbl_plan_adoption.py
    // This is a complex transactional operation
    Err(ApiError::with_status(
        StatusCode::NOT_IMPLEMENTED,
        "CBL adoption commit not yet implemented in Rust".to_string(),
    ))
}

/// POST /api/v1/cbl/{list_id}/reading-plans/{plan_id}/adoption-commit
#[instrument(skip(state, auth))]
pub async fn cbl_targeted_adoption_commit(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
    Path((list_id, plan_id)): Path<(i32, i32)>,
    Json(request): Json<CblAdoptionCommitRequest>,
) -> Result<Json<CblAdoptionCommitResponse>, ApiError> {
    // Placeholder - needs full implementation from cbl_targeted_plan_adoption.py
    Err(ApiError::with_status(
        StatusCode::NOT_IMPLEMENTED,
        "CBL targeted adoption commit not yet implemented in Rust".to_string(),
    ))
}

/// POST /api/v1/issue-identity/cbl/{list_id}/reading-graph-preview
#[instrument(skip(state, auth))]
pub async fn cbl_reading_graph_preview(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
    Path(list_id): Path<i32>,
    Json(request): Json<ReadingGraphPreviewRequest>,
) -> Result<Json<ReadingGraphPreview>, ApiError> {
    // Placeholder - needs full implementation from reading_graph_preview_service.py
    let response = ReadingGraphPreview {
        source_list_id: list_id,
        content_hash: String::new(),
        revision_sha: String::new(),
        series: vec![],
        overlaps: vec![],
        issues: vec![],
        rollable_issue_ids: vec![],
        waiting_issue_ids: vec![],
        cycle_errors: vec![],
    };
    
    Ok(Json(response))
}