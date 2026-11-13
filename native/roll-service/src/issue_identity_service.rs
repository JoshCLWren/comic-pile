//! Service layer for issue-identity and CBL operations.
//!
// Core business logic for the 12 API operations that are being migrated
// from Python FastAPI to native Rust v2.
//
// This module contains the actual implementation of the business logic
// for:
// - CBL source list discovery and browsing
// - Adoption plan calculation and preview
// - Reading graph preview
// - Adoption commit operations
// - CBL candidate management
//
// The service layer integrates with:
// - Existing Rust modules: identity_inbox.rs, creators.rs, comicvine_issue.rs, reading_graph.rs
// - Database operations through deadpool_postgres pool
// - Error handling through ApiError enum
// - Authentication through VerifiedAccessClaims

use super::models;
use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use tokio_postgres::Transaction;

pub mod models;

/// CBL source list discovery service
/// Handles GET /api/v1/issue-identity/cbl-sources
pub async fn list_cbl_source_previews(
    conn: &tokio_postgres::Connection,
    user_id: i32,
    query_text: Option<String>,
    limit: i32,
) -> Result<Vec<CBLSourceListSummary>, ApiError> {
    // Implementation will use existing Rust repository
    // For now, returns an error indicating incomplete implementation
    Err(ApiError::Internal("CBL source list discovery not yet implemented".to_string()))
}

/// CBL source list detail service
/// Handles GET /api/v1/issue-identity/cbl-sources/{list_id}
pub async fn get_cbl_source_list_detail(
    conn: &tokio_postgres::Connection,
    user_id: i32,
    list_id: i32,
    offset: i32,
    limit: i32,
) -> Result<Option<CBLSourceListPreview>, ApiError> {
    // Implementation will use existing Rust repository
    Err(ApiError::Internal("CBL source list detail not yet implemented".to_string()))
}

/// CBL catalog browsing service
/// Handles GET /api/v1/issue-identity/cbl-sources/browse
pub async fn browse_cbl_catalog(
    conn: &tokio_postgres::Connection,
    user_id: i32,
    folder: String,
    query: Option<String>,
    page: i32,
    page_size: i32,
) -> Result<CBLCatalogBrowsePage, ApiError> {
    // Implementation will use existing Rust repository
    Err(ApiError::Internal("CBL catalog browsing not yet implemented".to_string()))
}

/// Search CBL sources by ComicVine issue
/// Handles GET /api/v1/issue-identity/cbl-sources/by-comicvine-issue/{comicvine_issue_id}
pub async fn search_cbl_sources_by_comicvine_issue(
    conn: &tokio_postgres::Connection,
    user_id: i32,
    comicvine_issue_id: String,
) -> Result<Vec<CBLCatalogListItem>, ApiError> {
    // Implementation will use existing Rust repository
    Err(ApiError::Internal("CBL sources search not yet implemented".to_string()))
}

/// Compare CBL sources
/// Handles POST /api/v1/issue-identity/cbl-sources/compare
pub async fn compare_cbl_sources(
    conn: &tokio_postgres::Connection,
    user_id: i32,
    list_ids: Vec<i32>,
    source_path: Option<String>,
) -> Result<CompareResult, ApiError> {
    // Implementation will use existing Rust repository
    Err(ApiError::Internal("CBL sources comparison not yet implemented".to_string()))
}

/// List CBL source folders
/// Handles GET /api/v1/issue-identity/cbl-sources/folders
pub async fn list_cbl_source_folders(
    conn: &tokio_postgres::Connection,
    user_id: i32,
    folder: String,
) -> Result<CBLFolderListing, ApiError> {
    // Implementation will use existing Rust repository
    Err(ApiError::Internal("CBL source folders listing not yet implemented".to_string()))
}

/// Preview CBL adoption
/// Handles GET /api/v1/issue-identity/cbl/{list_id}/adoption-preview
pub async fn preview_cbl_adoption(
    conn: &tokio_postgres::Connection,
    user_id: i32,
    list_id: i32,
    series_decisions: Option<HashMap<String, bool>>,
    entry_decisions: Option<HashMap<String, bool>>,
) -> Result<(CBLReconciliationReport, CBLAdoptionPlan), ApiError> {
    // Implementation will use existing Rust adoption logic
    Err(ApiError::Internal("CBL adoption preview not yet implemented".to_string()))
}

/// Calculate adoption plan
/// Handles POST /api/v1/issue-identity/cbl/{list_id}/adoption-plan
pub async fn preview_cbl_adoption_with_decisions(
    conn: &tokio_postgres::Connection,
    user_id: i32,
    list_id: i32,
    series_decisions: Option<HashMap<String, bool>>,
    entry_decisions: Option<HashMap<String, bool>>,
) -> Result<(CBLReconciliationReport, CBLAdoptionPlan), ApiError> {
    // Wrapper around preview_cbl_adoption with decision parameters
    preview_cbl_adoption(conn, user_id, list_id, series_decisions, entry_decisions)
}

/// Preview CBL reading graph
/// Handles POST /api/v1/issue-identity/cbl/{list_id}/reading-graph-preview
pub async fn preview_cbl_reading_graph(
    conn: &tokio_postgres::Connection,
    user_id: i32,
    list_id: i32,
    request: ReadingGraphPreviewRequest,
) -> Result<ReadingGraphPreview, ApiError> {
    // Implementation will use existing Rust reading graph functionality
    Err(ApiError::Internal("CBL reading graph preview not yet implemented".to_string()))
}

/// Get CBL candidates
/// Handles GET /api/v1/issue-identity/reading-lists/{list_id}/cbl-candidates
pub async fn get_cbl_candidates(
    conn: &tokio_postgres::Connection,
    user_id: i32,
    list_id: i32,
) -> Result<Vec<CBLCandidate>, ApiError> {
    // Implementation will use existing Rust candidate functionality
    Err(ApiError::Internal("CBL candidates not yet implemented".to_string()))
}

/// Commit CBL adoption
/// Handles POST /api/v1/cbl/{list_id}/adoption-commit
pub async fn commit_cbl_adoption(
    tx: &mut tokio_postgres::Transaction<'_, tokio_postgres::Client>,
    user_id: i32,
    cbl_source_list_id: i32,
    plan_id: i32,
    request_fingerprint: String,
) -> Result<AdoptionCommitResult, ApiError> {
    // Implementation will use existing Rust adoption receipt functionality
    Err(ApiError::Internal("CBL adoption commit not yet implemented".to_string()))
}

/// Commit plan adoption
/// Handles POST /api/v1/cbl/{list_id}/reading-plans/{plan_id}/adoption-commit
pub async fn commit_plan_adoption(
    tx: &mut tokio_postgres::Transaction<'_, tokio_postgres::Client>,
    user_id: i32,
    cbl_source_list_id: i32,
    plan_id: i32,
    request_fingerprint: String,
) -> Result<PlanAdoptionCommitResult, ApiError> {
    // Implementation will use existing Rust adoption receipt functionality
    Err(ApiError::Internal("Plan adoption commit not yet implemented".to_string()))
}

/// Build CBL adoption preview response
/// Utility function to create preview response from report and plan
pub fn build_cbl_adoption_preview(
    report: CBLReconciliationReport,
    plan: CBLAdoptionPlan,
) -> CBLAdoptionPreviewResponse {
    // Implementation will format the preview response
    CBLAdoptionPreviewResponse {
        source: CBLSourceFingerprintResponse {
            source_list_id: report.source_list_id.unwrap_or(0),
            source_repository: report.source_repository.unwrap_or_else(|| "CBL source".to_string()),
            source_path: report.source_path.unwrap_or_else(|| "".to_string()),
            content_hash: report.content_hash.unwrap_or_else(|| "".to_string()),
            revision_sha: report.revision_sha.unwrap_or_else(|| "".to_string()),
        },
        total_positions: report.total_positions,
        entries: plan.entries.iter().map(|entry| {
            CBLAdoptionEntryResponse {
                collection_excluded: entry.get("collection_excluded").unwrap_or(&false) == &true,
                collection_exclusion_reason: entry.get("collection_exclusion_reason").cloned(),
                collection_exclusion_ids: entry.get("collection_exclusion_ids").cloned().unwrap_or_default(),
                cbl_position: entry.get("cbl_position").cloned().unwrap_or(0),
                cbl_entry_id: entry.get("cbl_entry_id").cloned().unwrap_or(0),
                series_name: entry.get("series_name").cloned().unwrap_or_else(|| "".to_string()),
                issue_number: entry.get("issue_number").cloned().unwrap_or_else(|| "".to_string()),
                series_group_id: entry.get("series_group_id").cloned().unwrap_or_else(|| "".to_string()),
                volume_year: entry.get("volume_year").and_then(|v| v.as_i64()).map(|v| v as i32),
                publication_year: entry.get("publication_year").and_then(|v| v.as_i64()).map(|v| v as i32),
                adoption_class: entry.get("adoption_class").cloned().unwrap_or_else(|| "unresolved".to_string()),
                adoption_decision: entry.get("adoption_decision").cloned().unwrap_or_else(|| "unresolved".to_string()),
                adopted: entry.get("adopted").unwrap_or(&false) == &true,
                comicvine_issue_id: entry.get("comicvine_issue_id").and_then(|v| v.as_str()).map(|s| s.to_string()),
                comicvine_series_id: entry.get("comicvine_series_id").and_then(|v| v.as_str()).map(|s| s.to_string()),
                series_provider: entry.get("series_provider").and_then(|v| v.as_str()).map(|s| s.to_string()),
                series_external_id: entry.get("series_external_id").and_then(|v| v.as_str()).map(|s| s.to_string()),
                resolved_issue_id: entry.get("resolved_issue_id").and_then(|v| v.as_i64()).map(|v| v as i32),
                canonical_issue_id: entry.get("canonical_issue_id").and_then(|v| v.as_i64()).map(|v| v as i32),
                read_status: entry.get("read_status").and_then(|v| v.as_str()).map(|s| s.to_string()),
                read_at: entry.get("read_at").and_then(|v| v.as_str()).map(|s| s.to_string()),
                resolution_status: entry.get("resolution_status").cloned().unwrap_or_else(|| "unresolved".to_string()),
                is_duplicate_identity: entry.get("is_duplicate_identity").unwrap_or(&false) == &true,
            }
        }).collect(),
        summary: CBLAdoptionSummaryResponse {
            reused_existing_count: plan.reused_existing_count,
            missing_would_create_count: plan.missing_would_create_count,
            excluded_count: plan.excluded_count,
            unresolved_count: plan.unresolved_count,
            awaiting_opt_in_count: plan.awaiting_opt_in_count,
            final_adopted_count: plan.final_adopted_count,
            final_adopted_order: plan.final_adopted_order.iter().cloned().collect(),
            reused_existing_positions: plan.reused_existing_positions.iter().cloned().collect(),
            missing_would_create_positions: plan.missing_would_create_positions.iter().cloned().collect(),
            excluded_positions: plan.excluded_positions.iter().cloned().collect(),
            unresolved_positions: plan.unresolved_positions.iter().cloned().collect(),
            awaiting_opt_in_positions: plan.awaiting_opt_in_positions.iter().cloned().collect(),
        },
    }
}

// Data model definitions
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLSourceListSummary {
    pub id: i32,
    pub name: String,
    pub source_path: String,
    pub source_repository: String,
    pub declared_issue_count: Option<i32>,
    pub content_hash: String,
    pub revision_sha: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLSourceEntryPreview {
    pub position: i32,
    pub series_name: String,
    pub issue_number: String,
    pub volume_year: Option<i32>,
    pub publication_year: Option<i32>,
    pub comicvine_issue_id: Option<String>,
    pub comicvine_volume_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLSourceListPreview {
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
    pub entries: Vec<CBLSourceEntryPreview>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLCatalogBrowsePage {
    pub scope: String,
    pub folder: String,
    pub query: Option<String>,
    pub breadcrumbs: Vec<CBLBreadcrumb>,
    pub folders: Vec<CBLSourceFolder>,
    pub items: Vec<CBLCatalogListItem>,
    pub page: i32,
    pub page_size: i32,
    pub total: i32,
    pub total_pages: i32,
    pub has_next: bool,
    pub has_previous: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLBreadcrumb {
    pub name: String,
    pub path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLSourceFolder {
    pub name: String,
    pub path: String,
    pub direct_list_count: i32,
    pub total_list_count: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLCatalogListItem {
    pub id: i32,
    pub name: String,
    pub source_path: String,
    pub source_repository: String,
    pub declared_issue_count: Option<i32>,
    pub content_hash: String,
    pub revision_sha: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLFolderListing {
    pub folder: String,
    pub breadcrumbs: Vec<CBLBreadcrumb>,
    pub folders: Vec<CBLSourceFolder>,
    pub direct_list_count: i32,
    pub total_list_count: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLSourceEntryDetail {
    pub position: i32,
    pub series_name: String,
    pub issue_number: String,
    pub volume_year: Option<i32>,
    pub publication_year: Option<i32>,
    pub comicvine_issue_id: Option<String>,
    pub comicvine_volume_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLSourceListDetail {
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
    pub entries: Vec<CBLSourceEntryDetail>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLReconciliationReport {
    pub total_positions: i32,
    pub resolved_count: i32,
    pub unresolved_count: i32,
    pub duplicate_identity_groups: i32,
    pub ambiguous_count: i32,
    pub entries: Vec<std::collections::HashMap<String, serde_json::Value>>,
    pub first_unread_position: Option<i32>,
    pub first_unread_entry: Option<std::collections::HashMap<String, serde_json::Value>>,
    pub source_list_id: Option<i32>,
    pub source_repository: Option<String>,
    pub source_path: Option<String>,
    pub content_hash: Option<String>,
    pub revision_sha: Option<String>,
    pub declared_issue_count: Option<i32>,
    pub missing_source_entries: Vec<i32>,
    pub extra_member_issue_ids: Vec<i32>,
    pub ambiguous_mappings: Vec<i32>,
    pub duplicate_identity_issues: Vec<i32>,
    pub first_unread_issue_id: Option<i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLAdoptionPlan {
    pub entries: Vec<std::collections::HashMap<String, serde_json::Value>>,
    pub reused_existing_count: i32,
    pub missing_would_create_count: i32,
    pub excluded_count: i32,
    pub unresolved_count: i32,
    pub final_adopted_count: i32,
    pub final_adopted_order: Vec<i32>,
    pub reused_existing_positions: Vec<i32>,
    pub missing_would_create_positions: Vec<i32>,
    pub excluded_positions: Vec<i32>,
    pub unresolved_positions: Vec<i32>,
    pub awaiting_opt_in_positions: Vec<i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLCandidate {
    pub list_id: i32,
    pub name: String,
    pub mode: String,
    pub list_updated_at: String,
    pub steps: Vec<RecoveryStep>,
    pub added_steps: Vec<RecoveryStep>,
    pub removed_steps: Vec<RecoveryStep>,
    pub order_changed: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecoveryStep {
    pub issue_id: i32,
    pub label: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLAdoptionPreviewResponse {
    pub source: CBLSourceFingerprintResponse,
    pub total_positions: i32,
    pub entries: Vec<CBLAdoptionEntryResponse>,
    pub summary: CBLAdoptionSummaryResponse,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLSourceFingerprintResponse {
    pub source_list_id: i32,
    pub source_repository: String,
    pub source_path: String,
    pub content_hash: String,
    pub revision_sha: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLAdoptionEntryResponse {
    pub collection_excluded: bool,
    pub collection_exclusion_reason: Option<String>,
    pub collection_exclusion_ids: Vec<i32>,
    pub cbl_position: i32,
    pub cbl_entry_id: i32,
    pub series_name: String,
    pub issue_number: String,
    pub series_group_id: String,
    pub volume_year: Option<i32>,
    pub publication_year: Option<i32>,
    pub adoption_class: String,
    pub adoption_decision: String,
    pub adopted: bool,
    pub comicvine_issue_id: Option<String>,
    pub comicvine_series_id: Option<String>,
    pub series_provider: Option<String>,
    pub series_external_id: Option<String>,
    pub resolved_issue_id: Option<i32>,
    pub canonical_issue_id: Option<i32>,
    pub read_status: Option<String>,
    pub read_at: Option<String>,
    pub resolution_status: String,
    pub is_duplicate_identity: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLAdoptionSummaryResponse {
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

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ComparisonResult {
    pub comparisons: Vec<ComparisonEntry>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ComparisonEntry {
    pub list_id: i32,
    pub name: String,
    pub source_path: String,
    pub similarity_score: f64,
    pub differences: Vec<Difference>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Difference {
    pub type: String,
    pub description: String,
    pub position: Option<i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphPreviewRequest {
    pub included_positions: Vec<i32>,
    pub prior_answers: HashMap<String, String>,
    pub optional_list_to_preview: Option<i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphPreview {
    // Fields based on existing Rust reading_graph.rs module
    pub status: String,
    pub cycles: Vec<ReadingGraphCycle>,
    pub cyclic_issue_ids: Vec<i32>,
    pub affected_lists: Vec<ReadingGraphList>,
    pub affected_threads: Vec<ReadingGraphThread>,
    pub repairs: Vec<ReadingGraphRepairOption>,
    pub unresolved_reference_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphCycle {
    pub message: String,
    pub edges: Vec<ReadingGraphEdge>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphEdge {
    pub source: ReadingGraphIssue,
    pub target: ReadingGraphIssue,
    pub origin: String,
    pub kind: String,
    pub list_id: Option<i32>,
    pub list_name: Option<String>,
    pub prerequisite_id: Option<i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphIssue {
    pub issue_id: i32,
    pub issue_number: String,
    pub thread_id: i32,
    pub series_title: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphList {
    pub list_id: i32,
    pub name: String,
    pub mode: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphThread {
    pub thread_id: i32,
    pub title: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphRepairOption {
    pub action: String,
    pub label: String,
    pub detail: String,
    pub list_id: Option<i32>,
    pub issue_id: Option<i32>,
    pub prerequisite_id: Option<i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdoptionCommitResult {
    pub success: bool,
    pub message: String,
    pub receipt_id: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlanAdoptionCommitResult {
    pub success: bool,
    pub message: String,
    pub receipt_id: i32,
    pub plan_id: i32,
    pub list_id: i32,
}

#[derive(Debug, Deserialize)]
pub struct DiscoverQuery {
    q: Option<String>,
    limit: i32,
}

#[derive(Debug, Deserialize)]
pub struct BrowseQuery {
    q: Option<String>,
    page: i32,
    page_size: i32,
}

#[derive(Debug, Deserialize)]
pub struct FolderQuery {
    folder: String,
}

#[derive(Debug, Deserialize)]
pub struct CompareRequest {
    list_ids: Vec<i32>,
    source_path: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct ListDetailQuery {
    offset: i32,
    limit: i32,
}

#[derive(Debug, Deserialize)]
pub struct CBLAdoptionPlanRequest {
    series_decisions: HashMap<String, bool>,
    entry_decisions: HashMap<String, bool>,
}

#[derive(Debug, Deserialize)]
pub struct CommitAdoptionRequest {
    plan_id: i32,
    request_fingerprint: String,
}

#[derive(Debug, Deserialize)]
pub struct CommitPlanAdoptionRequest {
    request_fingerprint: String,
}