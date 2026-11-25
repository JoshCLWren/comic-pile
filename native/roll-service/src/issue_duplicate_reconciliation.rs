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

fn db_err(err: tokio_postgres::Error) -> ApiError {
    db::query_error(err)
}

fn not_found(msg: &str) -> ApiError {
    ApiError::NotFound(msg.to_string())
}

fn bad_request(msg: &str) -> ApiError {
    ApiError::BadRequest(msg.to_string())
}

fn conflict(msg: &str) -> ApiError {
    ApiError::Conflict(msg.to_string())
}

fn internal(msg: &str) -> ApiError {
    ApiError::Internal(msg.to_string())
}

fn iso(ts: chrono::DateTime<chrono::Utc>) -> String {
    ts.to_rfc3339_opts(chrono::SecondsFormat::Millis, true)
}

fn row_ts(row: &tokio_postgres::Row, idx: usize) -> Option<String> {
    row.get::<_, Option<chrono::DateTime<chrono::Utc>>>(idx)
        .map(iso)
}

fn required_ts(row: &tokio_postgres::Row, idx: usize) -> String {
    iso(row.get::<_, chrono::DateTime<chrono::Utc>>(idx))
}

async fn load_issue_evidence(
    tx: &Transaction<'_>,
    user_id: i32,
    issue_id: i32,
) -> Result<DuplicateIssueEvidence, ApiError> {
    let issue_row = tx
        .query_opt(
            r#"
            SELECT i.id, i.thread_id, t.title, i.issue_number, i.status,
                   i.read_at, i.created_at
            FROM issues i
            JOIN threads t ON t.id = i.thread_id
            WHERE i.id = $1 AND t.user_id = $2
            "#,
            &[&issue_id, &user_id],
        )
        .await
        .map_err(db_err)?
        .ok_or_else(|| not_found(&format!("Issue {issue_id} not found")))?;

    let read_at = row_ts(&issue_row, 5);
    let created_at = required_ts(&issue_row, 6);
    let created_at_dt: chrono::DateTime<chrono::Utc> = issue_row.get(6);
    let is_synthetic_placeholder_read = match (&read_at, issue_row.get::<_, chrono::DateTime<chrono::Utc>>(6)) {
        (Some(_), _) => {
            if let Some(read_dt) = issue_row.get::<_, Option<chrono::DateTime<chrono::Utc>>>(5) {
                read_dt < created_at_dt
            } else {
                false
            }
        }
        _ => false,
    };

    // Comic Vine mapping
    let cv_row = tx
        .query_opt(
            r#"
            SELECT ei.external_id, ev.external_id AS volume_id, ei.metadata_json
            FROM issue_external_identity_mappings m
            JOIN external_identities ei ON ei.id = m.external_identity_id
                AND ei.provider = 'comicvine' AND ei.entity_type = 'issue'
            LEFT JOIN external_identities ev ON ev.provider = 'comicvine'
                AND ev.entity_type = 'series'
                AND ev.external_id = (ei.metadata_json->>'volume_id')
            WHERE m.issue_id = $1 AND m.status IN ('confirmed', 'candidate')
            ORDER BY CASE m.status WHEN 'confirmed' THEN 0 ELSE 1 END, m.id ASC
            LIMIT 1
            "#,
            &[&issue_id],
        )
        .await
        .map_err(db_err)?;

    let (comicvine_issue_id, comicvine_volume_id, comicvine_issue_number, comicvine_story_number) =
        if let Some(r) = cv_row {
            let cv_id: String = r.get(0);
            let vol_id_str: Option<String> = r.get(1);
            let meta: serde_json::Value = r.get(2);
            let vol_id = vol_id_str
                .as_deref()
                .and_then(|s| s.parse::<i32>().ok())
                .or_else(|| meta.get("volume_id").and_then(|v| v.as_i64()).map(|v| v as i32));
            let issue_num = meta.get("issue_number").and_then(|v| v.as_str()).map(String::from);
            let story_num = meta.get("story_arc_number").and_then(|v| v.as_str()).map(String::from)
                .or_else(|| meta.get("story_number").and_then(|v| v.as_str()).map(String::from));
            (Some(cv_id), vol_id, issue_num, story_num)
        } else {
            (None, None, None, None)
        };

    // Rating events
    let rating_rows = tx
        .query(
            r#"
            SELECT id, rating, "timestamp"
            FROM events
            WHERE issue_id = $1 AND type = 'rate' AND rating IS NOT NULL
            ORDER BY "timestamp" ASC, id ASC
            "#,
            &[&issue_id],
        )
        .await
        .map_err(db_err)?;
    let rating_events = rating_rows
        .iter()
        .map(|r| DuplicateRatingEvent {
            event_id: r.get(0),
            rating: r.get::<_, f64>(1),
            timestamp: required_ts(r, 2),
        })
        .collect();

    // Read events
    let read_rows = tx
        .query(
            r#"
            SELECT id, "timestamp", issue_number
            FROM events
            WHERE issue_id = $1 AND type = 'issue_read'
            ORDER BY "timestamp" ASC, id ASC
            "#,
            &[&issue_id],
        )
        .await
        .map_err(db_err)?;
    let read_events = read_rows
        .iter()
        .map(|r| DuplicateReadEvent {
            event_id: r.get(0),
            timestamp: required_ts(r, 1),
            issue_number: r.get(2),
        })
        .collect();

    // List memberships
    let list_rows = tx
        .query(
            r#"
            SELECT l.id, l.name, e."position", e.id
            FROM custom_cbl_entries e
            JOIN custom_cbl_lists l ON l.id = e.list_id
            WHERE e.issue_id = $1 AND l.user_id = $2
            ORDER BY l.id ASC, e."position" ASC
            "#,
            &[&issue_id, &user_id],
        )
        .await
        .map_err(db_err)?;
    let list_memberships = list_rows
        .iter()
        .map(|r| DuplicateListMembership {
            list_id: r.get(0),
            list_name: r.get(1),
            position: r.get(2),
            entry_id: r.get(3),
        })
        .collect();

    Ok(DuplicateIssueEvidence {
        issue_id: issue_row.get(0),
        thread_id: issue_row.get(1),
        thread_title: issue_row.get(2),
        issue_number: issue_row.get(3),
        status: issue_row.get(4),
        read_at,
        created_at,
        comicvine_issue_id,
        comicvine_volume_id,
        comicvine_issue_number,
        comicvine_story_number,
        rating_events,
        read_events,
        list_memberships,
        is_synthetic_placeholder_read,
    })
}
