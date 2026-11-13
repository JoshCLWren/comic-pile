//! Data models for issue-identity and CBL operations.
//!
// This module contains the data structures used by the issue-identity
// API operations that are being migrated from Python to Rust.
//
// The models are designed to be wire-compatible with the existing Python
// Pydantic models while following Rust best practices for performance
// and memory safety.

use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};

/// CBL source list summary for discovery operations
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLSourceListSummary {
    /// Unique identifier for the CBL source list
    pub id: i32,
    /// Human-readable name of the source list
    pub name: String,
    /// Path within the source repository
    pub source_path: String,
    /// Source repository identifier (GitHub-style for public access)
    pub source_repository: String,
    /// Number of declared issues (may be null if unknown)
    pub declared_issue_count: Option<i32>,
    /// Content hash for integrity verification
    pub content_hash: String,
    /// Revision SHA for version tracking
    pub revision_sha: String,
}

/// Individual source entry preview for detailed views
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLSourceEntryPreview {
    /// Original position in the source list
    pub position: i32,
    /// Series name from the source
    pub series_name: String,
    /// Issue number as string (can include ranges, special designations)
    pub issue_number: String,
    /// Volume/year when available in the source
    pub volume_year: Option<i32>,
    /// Publication year when available in the source
    pub publication_year: Option<i32>,
    /// ComicVine issue ID when mapped (null when unmapped)
    pub comicvine_issue_id: Option<String>,
    /// ComicVine volume ID when mapped (null when unmapped)
    pub comicvine_volume_id: Option<String>,
}

/// Complete preview of a CBL source list with pagination
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLSourceListPreview {
    /// Unique identifier for the source list
    pub id: i32,
    /// Human-readable name of the source list
    pub name: String,
    /// Source path within repository
    pub source_path: String,
    /// Source repository identifier
    pub source_repository: String,
    /// Reader-safe repository reference for API responses
    pub source_ref: String,
    /// Number of declared issues (may be null)
    pub declared_issue_count: Option<i32>,
    /// Content hash for integrity verification
    pub content_hash: String,
    /// Revision SHA for version tracking
    pub revision_sha: String,
    /// Total number of source entries in the list
    pub entries_total: i32,
    /// Starting position for this page (0-based)
    pub entries_offset: i32,
    /// Maximum entries per page (limit)
    pub entries_limit: i32,
    /// The page of entries for this response
    pub entries: Vec<CBLSourceEntryPreview>,
}

/// Catalog browsing page with pagination and navigation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLCatalogBrowsePage {
    /// Current scope: "folder" or "search"
    pub scope: String,
    /// Folder path being browsed (empty string for root)
    pub folder: String,
    /// Search query when scope is "search" (null for folder browse)
    pub query: Option<String>,
    /// Breadcrumb navigation trail for the current view
    pub breadcrumbs: Vec<CBLBreadcrumb>,
    /// Subfolders available in the current folder
    pub folders: Vec<CBLSourceFolder>,
    /// Source lists in the current view
    pub items: Vec<CBLCatalogListItem>,
    /// Current page number (1-based)
    pub page: i32,
    /// Number of items per page
    pub page_size: i32,
    /// Total number of items across all pages
    pub total: i32,
    /// Total number of pages available
    pub total_pages: i32,
    /// Whether a next page exists
    pub has_next: bool,
    /// Whether a previous page exists
    pub has_previous: bool,
}

/// Breadcrumb navigation element for path trails
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLBreadcrumb {
    /// Display name for the breadcrumb
    pub name: String,
    /// Path that this breadcrumb represents
    pub path: String,
}

/// Folder information for navigation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLSourceFolder {
    /// Folder name
    pub name: String,
    /// Path to the folder
    pub path: String,
    /// Number of direct child lists
    pub direct_list_count: i32,
    /// Total number of descendant lists
    pub total_list_count: i32,
}

/// Catalog list item for browse operations
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLCatalogListItem {
    /// Unique identifier for the source list
    pub id: i32,
    /// Human-readable name
    pub name: String,
    /// Source path within repository
    pub source_path: String,
    /// Source repository identifier (reader-safe)
    pub source_repository: String,
    /// Number of declared issues (may be null)
    pub declared_issue_count: Option<i32>,
    /// Content hash for integrity verification
    pub content_hash: String,
    /// Revision SHA for version tracking
    pub revision_sha: String,
}

/// Folder listing for navigation operations
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLFolderListing {
    /// Current folder path
    pub folder: String,
    /// Breadcrumb navigation trail
    pub breadcrumbs: Vec<CBLBreadcrumb>,
    /// Available subfolders
    pub folders: Vec<CBLSourceFolder>,
    /// Number of direct child lists
    pub direct_list_count: i32,
    /// Total number of descendant lists
    pub total_list_count: i32,
}

/// Detailed source list entry for comprehensive views
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLSourceEntryDetail {
    /// Original position in the source list
    pub position: i32,
    /// Series name
    pub series_name: String,
    /// Issue number
    pub issue_number: String,
    /// Volume/year information
    pub volume_year: Option<i32>,
    /// Publication year information
    pub publication_year: Option<i32>,
    /// ComicVine issue ID (if mapped)
    pub comicvine_issue_id: Option<String>,
    /// ComicVine volume ID (if mapped)
    pub comicvine_volume_id: Option<String>,
}

/// Complete source list detail for comprehensive views
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLSourceListDetail {
    /// Unique identifier for the source list
    pub id: i32,
    /// Human-readable name
    pub name: String,
    /// Source path within repository
    pub source_path: String,
    /// Source repository identifier
    pub source_repository: String,
    /// Reader-safe repository reference
    pub source_ref: String,
    /// Number of declared issues
    pub declared_issue_count: Option<i32>,
    /// Content hash for integrity verification
    pub content_hash: String,
    /// Revision SHA for version tracking
    pub revision_sha: String,
    /// Total number of entries in the list
    pub entries_total: i32,
    /// Starting position for this page
    pub entries_offset: i32,
    /// Maximum number of entries to return
    pub entries_limit: i32,
    /// Page of entries for this response
    pub entries: Vec<CBLSourceEntryDetail>,
}

/// Reconciliation report for adoption preview
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLReconciliationReport {
    /// Total number of positions in the source list
    pub total_positions: i32,
    /// Number of successfully resolved positions
    pub resolved_count: i32,
    /// Number of unresolved positions
    pub unresolved_count: i32,
    /// Number of duplicate identity groups
    pub duplicate_identity_groups: i32,
    /// Number of ambiguous positions
    pub ambiguous_count: i32,
    /// Detailed reconciliation data for each position
    pub entries: Vec<HashMap<String, serde_json::Value>>,
    /// First unread position (if any)
    pub first_unread_position: Option<i32>,
    /// First unread entry details (if any)
    pub first_unread_entry: Option<HashMap<String, serde_json::Value>>,
    /// Source list ID for context
    pub source_list_id: Option<i32>,
    /// Source repository identifier
    pub source_repository: Option<String>,
    /// Source path for context
    pub source_path: Option<String>,
    /// Content hash for integrity
    pub content_hash: Option<String>,
    /// Revision SHA for version tracking
    pub revision_sha: Option<String>,
    /// Number of declared issues
    pub declared_issue_count: Option<i32>,
    /// Missing source entries
    pub missing_source_entries: Vec<i32>,
    /// Extra member issue IDs
    pub extra_member_issue_ids: Vec<i32>,
    /// Ambiguous mapping issue IDs
    pub ambiguous_mappings: Vec<i32>,
    /// Duplicate identity issue IDs
    pub duplicate_identity_issues: Vec<i32>,
    /// First unread issue ID (if any)
    pub first_unread_issue_id: Option<i32>,
}

/// Adoption plan for dry-run calculations
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLAdoptionPlan {
    /// Planned entries with adoption decisions
    pub entries: Vec<HashMap<String, serde_json::Value>>,
    /// Number of entries to keep existing
    pub reused_existing_count: i32,
    /// Number of entries that would create new issues
    pub missing_would_create_count: i32,
    /// Number of entries to exclude
    pub excluded_count: i32,
    /// Number of unresolved entries
    pub unresolved_count: i32,
    /// Number of entries in the final plan
    pub final_adopted_count: i32,
    /// Order of adopted entries (by position)
    pub final_adopted_order: Vec<i32>,
    /// Positions of entries to keep existing
    pub reused_existing_positions: Vec<i32>,
    /// Positions of entries that would create new issues
    pub missing_would_create_positions: Vec<i32>,
    /// Positions of entries to exclude
    pub excluded_positions: Vec<i32>,
    /// Positions of unresolved entries
    pub unresolved_positions: Vec<i32>,
    /// Positions of entries awaiting opt-in decisions
    pub awaiting_opt_in_positions: Vec<i32>,
}

/// Candidate reading list for adoption consideration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLCandidate {
    /// Reading list identifier
    pub list_id: i32,
    /// Human-readable name
    pub name: String,
    /// Reading list mode
    pub mode: String,
    /// Last update timestamp
    pub list_updated_at: String,
    /// Planned steps for this candidate
    pub steps: Vec<RecoveryStep>,
    /// Steps to be added
    pub added_steps: Vec<RecoveryStep>,
    /// Steps to be removed
    pub removed_steps: Vec<RecoveryStep>,
    /// Whether the order has changed
    pub order_changed: bool,
}

/// Recovery step for reading list adoption
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecoveryStep {
    /// Issue identifier
    pub issue_id: i32,
    /// Human-readable label for the step
    pub label: String,
}

/// Complete adoption preview response
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLAdoptionPreviewResponse {
    /// Source fingerprint for review
    pub source: CBLSourceFingerprintResponse,
    /// Total number of positions in the source
    pub total_positions: i32,
    /// Detailed adoption decisions for each position
    pub entries: Vec<CBLAdoptionEntryResponse>,
    /// Summary statistics for the adoption plan
    pub summary: CBLAdoptionSummaryResponse,
}

/// Source fingerprint for immutable evidence
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLSourceFingerprintResponse {
    /// Unique identifier for the source list
    pub source_list_id: i32,
    /// Reader-safe repository identifier
    pub source_repository: String,
    /// Source path for evidence
    pub source_path: String,
    /// Content hash for integrity
    pub content_hash: String,
    /// Revision SHA for immutable evidence
    pub revision_sha: String,
}

/// Individual adoption entry with detailed decision
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLAdoptionEntryResponse {
    /// Whether this entry is excluded from adoption
    pub collection_excluded: bool,
    /// Reason for exclusion (if applicable)
    pub collection_exclusion_reason: Option<String>,
    /// IDs of other entries affected by this exclusion
    pub collection_exclusion_ids: Vec<i32>,
    /// Position in the source list
    pub cbl_position: i32,
    /// Entry identifier within the source list
    pub cbl_entry_id: i32,
    /// Series name
    pub series_name: String,
    /// Issue number
    pub issue_number: String,
    /// Series grouping identifier
    pub series_group_id: String,
    /// Volume/year information
    pub volume_year: Option<i32>,
    /// Publication year information
    pub publication_year: Option<i32>,
    /// Adoption classification
    pub adoption_class: String,
    /// Final adoption decision
    pub adoption_decision: String,
    /// Whether this entry is adopted in the plan
    pub adopted: bool,
    /// ComicVine issue ID (if mapped)
    pub comicvine_issue_id: Option<String>,
    /// ComicVine series ID (if mapped)
    pub comicvine_series_id: Option<String>,
    /// Series provider identifier
    pub series_provider: Option<String>,
    /// Series external identifier
    pub series_external_id: Option<String>,
    /// Resolved issue identifier
    pub resolved_issue_id: Option<i32>,
    /// Canonical issue identifier
    pub canonical_issue_id: Option<i32>,
    /// Read status (if applicable)
    pub read_status: Option<String>,
    /// Read timestamp (if applicable)
    pub read_at: Option<String>,
    /// Resolution status for identity mapping
    pub resolution_status: String,
    /// Whether this entry is a duplicate identity
    pub is_duplicate_identity: bool,
}

/// Summary statistics for adoption plans
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CBLAdoptionSummaryResponse {
    /// Number of entries to keep existing
    pub reused_existing_count: i32,
    /// Number of entries that would create new issues
    pub missing_would_create_count: i32,
    /// Number of entries to exclude
    pub excluded_count: i32,
    /// Number of unresolved entries
    pub unresolved_count: i32,
    /// Number of entries awaiting opt-in decisions
    pub awaiting_opt_in_count: i32,
    /// Number of entries in the final plan
    pub final_adopted_count: i32,
    /// Order of adopted entries
    pub final_adopted_order: Vec<i32>,
    /// Positions of entries to keep existing
    pub reused_existing_positions: Vec<i32>,
    /// Positions of entries that would create new issues
    pub missing_would_create_positions: Vec<i32>,
    /// Positions of entries to exclude
    pub excluded_positions: Vec<i32>,
    /// Positions of unresolved entries
    pub unresolved_positions: Vec<i32>,
    /// Positions of entries awaiting opt-in
    pub awaiting_opt_in_positions: Vec<i32>,
}

/// Catalog comparison entry
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ComparisonEntry {
    /// Source list identifier
    pub list_id: i32,
    /// Human-readable name
    pub name: String,
    /// Source path within repository
    pub source_path: String,
    /// Similarity score (0.0 to 1.0)
    pub similarity_score: f64,
    /// Differences between the lists
    pub differences: Vec<Difference>,
}

/// Difference between two source lists
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Difference {
    /// Type of difference (content, order, metadata)
    pub type: String,
    /// Human-readable description of the difference
    pub description: String,
    /// Position affected (if applicable)
    pub position: Option<i32>,
}

/// Reading graph preview response
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphPreview {
    /// Status: "ok", "cycle", or "invalid"
    pub status: String,
    /// Cycles found in the reading graph
    pub cycles: Vec<ReadingGraphCycle>,
    /// Issue IDs involved in cycles
    pub cyclic_issue_ids: Vec<i32>,
    /// Reading lists affected by cycles
    pub affected_lists: Vec<ReadingGraphList>,
    /// Threads affected by cycles
    pub affected_threads: Vec<ReadingGraphThread>,
    /// Repair options available
    pub repairs: Vec<ReadingGraphRepairOption>,
    /// Number of unresolved references
    pub unresolved_reference_count: usize,
}

/// Reading graph cycle information
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphCycle {
    /// Human-readable description of the cycle
    pub message: String,
    /// Edges that form the cycle
    pub edges: Vec<ReadingGraphEdge>,
}

/// Reading graph edge information
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphEdge {
    /// Source issue information
    pub source: ReadingGraphIssue,
    /// Target issue information
    pub target: ReadingGraphIssue,
    /// Origin of the edge (e.g., "dependency", "order")
    pub origin: String,
    /// Kind of relationship
    pub kind: String,
    /// Reading list ID (if applicable)
    pub list_id: Option<i32>,
    /// Reading list name (if applicable)
    pub list_name: Option<String>,
    /// Prerequisite identifier (if applicable)
    pub prerequisite_id: Option<i32>,
}

/// Reading graph issue representation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphIssue {
    /// Unique identifier for the issue
    pub issue_id: i32,
    /// Issue number as string
    pub issue_number: String,
    /// Thread identifier
    pub thread_id: i32,
    /// Series title
    pub series_title: String,
}

/// Reading list information
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphList {
    /// Unique identifier for the reading list
    pub list_id: i32,
    /// Human-readable name
    pub name: String,
    /// Reading list mode
    pub mode: String,
}

/// Thread information
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphThread {
    /// Unique identifier for the thread
    pub thread_id: i32,
    /// Human-readable title
    pub title: String,
}

/// Repair option for reading graph cycles
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadingGraphRepairOption {
    /// Repair action identifier
    pub action: String,
    /// Human-readable label for the repair option
    pub label: String,
    /// Detailed explanation of the repair
    pub detail: String,
    /// Reading list ID (if applicable)
    pub list_id: Option<i32>,
    /// Issue ID (if applicable)
    pub issue_id: Option<i32>,
    /// Prerequisite ID (if applicable)
    pub prerequisite_id: Option<i32>,
}

/// Adoption commit result
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdoptionCommitResult {
    /// Whether the adoption was successful
    pub success: bool,
    /// Message describing the result
    pub message: String,
    /// Identifier for the adoption receipt
    pub receipt_id: i32,
}

/// Plan adoption commit result
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlanAdoptionCommitResult {
    /// Whether the adoption was successful
    pub success: bool,
    /// Message describing the result
    pub message: String,
    /// Identifier for the adoption receipt
    pub receipt_id: i32,
    /// Plan identifier
    pub plan_id: i32,
    /// Reading list identifier
    pub list_id: i32,
}

/// Request parameter structures for API operations
#[derive(Debug, Deserialize)]
pub struct DiscoverQuery {
    /// Optional text search query
    q: Option<String>,
    /// Maximum number of results to return
    limit: i32,
}

#[derive(Debug, Deserialize)]
pub struct BrowseQuery {
    /// Optional text search query
    q: Option<String>,
    /// Page number (1-based)
    page: i32,
    /// Number of items per page
    page_size: i32,
}

#[derive(Debug, Deserialize)]
pub struct FolderQuery {
    /// Folder path to list
    folder: String,
}

#[derive(Debug, Deserialize)]
pub struct CompareQuery {
    /// List of source list IDs to compare
    list_ids: Vec<i32>,
    /// Source path for context
    source_path: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct ListDetailQuery {
    /// Starting position (0-based)
    offset: i32,
    /// Maximum number of entries to return
    limit: i32,
}

#[derive(Debug, Deserialize)]
pub struct CBLAdoptionPlanRequest {
    /// Series-level adoption decisions
    series_decisions: HashMap<String, bool>,
    /// Entry-level adoption decisions
    entry_decisions: HashMap<String, bool>,
}

#[derive(Debug, Deserialize)]
pub struct CommitAdoptionRequest {
    /// Plan identifier for the adoption
    plan_id: i32,
    /// Fingerprint for request idempotency
    request_fingerprint: String,
}

#[derive(Debug, Deserialize)]
pub struct CommitPlanAdoptionRequest {
    /// Fingerprint for request idempotency
    request_fingerprint: String,
}

#[derive(Debug, Deserialize)]
pub struct ReadingGraphPreviewRequest {
    /// Positions included in the preview
    included_positions: Vec<i32>,
    /// Prior adoption decisions (series -> decision)
    prior_answers: HashMap<String, String>,
    /// Optional list to preview instead of adding
    optional_list_to_preview: Option<i32>,
}

#[derive(Debug, Deserialize)]
pub struct ComparisonRequest {
    /// List of source list IDs to compare
    list_ids: Vec<i32>,
    /// Source path for context
    source_path: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct AdoptionCommitRequest {
    /// Plan identifier
    plan_id: i32,
    /// Request fingerprint for idempotency
    request_fingerprint: String,
}

#[derive(Debug, Deserialize)]
pub struct PlanAdoptionCommitRequest {
    /// Request fingerprint for idempotency
    request_fingerprint: String,
}

// Re-export common types for easier access
pub use crate::issue_identity_models::{CBLSourceListSummary, CBLSourceEntryPreview};
pub use crate::issue_identity_models::{CBLSourceListPreview, CBLCatalogBrowsePage};
pub use crate::issue_identity_models::{CBLBreadcrumb, CBLSourceFolder};
pub use crate::issue_identity_models::{CBLCatalogListItem, CBLFolderListing};
pub use crate::issue_identity_models::{CBLSourceEntryDetail, CBLSourceListDetail};
pub use crate::issue_identity_models::{CBLReconciliationReport, CBLAdoptionPlan};
pub use crate::issue_identity_models::{CBLCandidate, RecoveryStep};
pub use crate::issue_identity_models::{CBLAdoptionPreviewResponse, CBLSourceFingerprintResponse};
pub use crate::issue_identity_models::{CBLAdoptionEntryResponse, CBLAdoptionSummaryResponse};
pub use crate::issue_identity_models::{ComparisonEntry, Difference};
pub use crate::issue_identity_models::{ReadingGraphPreview, ReadingGraphCycle, ReadingGraphEdge};
pub use crate::issue_identity_models::{ReadingGraphIssue, ReadingGraphList, ReadingGraphThread};
pub use crate::issue_identity_models::{ReadingGraphRepairOption, AdoptionCommitResult};
pub use crate::issue_identity_models::{PlanAdoptionCommitResult, CBLAdoptionPlanRequest};

// Query parameter structures
#[derive(Debug, Deserialize)]
pub struct DiscoverQuery {
    pub q: Option<String>,
    pub limit: i32,
}

#[derive(Debug, Deserialize)]
pub struct BrowseQuery {
    pub q: Option<String>,
    pub page: i32,
    pub page_size: i32,
}

#[derive(Debug, Deserialize)]
pub struct FolderQuery {
    pub folder: String,
}

#[derive(Debug, Deserialize)]
pub struct CompareQuery {
    pub list_ids: Vec<i32>,
    pub source_path: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct ListDetailQuery {
    pub offset: i32,
    pub limit: i32,
}