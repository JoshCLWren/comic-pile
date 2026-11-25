//! Guided canonical duplicate-comic reconciliation (#4653).
//!
//! Detects likely duplicate physical issues, previews a history-safe merge,
//! and applies it with Undo support. This is a v2-native endpoint family.

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{extract::State, http::StatusCode, Json};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::sync::Arc;
use tokio_postgres::Transaction;
use utoipa::ToSchema;

const MAX_CANDIDATE_GROUPS: usize = 50;
const MAX_GROUP_ISSUES: usize = 20;

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct DuplicateIssueEvidence {
    pub issue_id: i32,
    pub thread_id: i32,
    pub thread_title: String,
    pub issue_number: String,
    pub status: String,
    pub read_at: Option<String>,
    pub created_at: String,
    pub comicvine_issue_id: Option<String>,
    pub comicvine_volume_id: Option<i32>,
    pub comicvine_issue_number: Option<String>,
    pub comicvine_story_number: Option<String>,
    pub rating_events: Vec<DuplicateRatingEvent>,
    pub read_events: Vec<DuplicateReadEvent>,
    pub list_memberships: Vec<DuplicateListMembership>,
    pub is_synthetic_placeholder_read: bool,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct DuplicateRatingEvent {
    pub event_id: i32,
    pub rating: f64,
    pub timestamp: String,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct DuplicateReadEvent {
    pub event_id: i32,
    pub timestamp: String,
    pub issue_number: Option<String>,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct DuplicateListMembership {
    pub list_id: i32,
    pub list_name: String,
    pub position: i32,
    pub entry_id: i32,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct DuplicateCandidateGroup {
    pub group_key: String,
    pub confidence: String,
    pub reason: String,
    pub evidence: Vec<DuplicateIssueEvidence>,
    pub suggested_canonical_issue_id: Option<i32>,
    pub suggested_duplicate_issue_ids: Vec<i32>,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct DuplicateDetectionResponse {
    pub groups: Vec<DuplicateCandidateGroup>,
}

#[derive(Debug, Clone, Deserialize, ToSchema)]
pub struct ReconcilePreviewRequest {
    pub canonical_issue_id: i32,
    pub duplicate_issue_ids: Vec<i32>,
    /// Explicit choices for ambiguous actions: "merge" (default) or "keep_distinct"
    #[serde(default)]
    pub decisions: HashMap<String, String>,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReconcilePreviewAction {
    pub kind: String,
    pub description: String,
    pub safe: bool,
    pub requires_decision: bool,
    pub decision_key: Option<String>,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReconcilePreviewResponse {
    pub canonical_issue_id: i32,
    pub duplicate_issue_ids: Vec<i32>,
    pub canonical: DuplicateIssueEvidence,
    pub duplicates: Vec<DuplicateIssueEvidence>,
    pub actions: Vec<ReconcilePreviewAction>,
    pub warnings: Vec<String>,
    pub can_apply: bool,
    pub preview_token: String,
}

#[derive(Debug, Clone, Deserialize, ToSchema)]
pub struct ReconcileApplyRequest {
    pub canonical_issue_id: i32,
    pub duplicate_issue_ids: Vec<i32>,
    #[serde(default)]
    pub decisions: HashMap<String, String>,
    pub preview_token: String,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReconcileApplyResponse {
    pub canonical_issue_id: i32,
    pub merged_issue_ids: Vec<i32>,
    pub moved_event_ids: Vec<i32>,
    pub moved_mapping_ids: Vec<i32>,
    pub moved_list_entry_ids: Vec<i32>,
    pub suppressed_duplicate_issue_ids: Vec<i32>,
    pub undo_snapshot_id: Option<i32>,
    pub warnings: Vec<String>,
}
