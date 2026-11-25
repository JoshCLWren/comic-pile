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

async fn detect_duplicates_for_user(
    tx: &Transaction<'_>,
    user_id: i32,
) -> Result<Vec<DuplicateCandidateGroup>, ApiError> {
    let mut groups: Vec<DuplicateCandidateGroup> = Vec::new();
    let mut seen_groups: BTreeSet<String> = BTreeSet::new();

    // 1) Exact provider identity: same comicvine issue external_id mapped to multiple issues
    let dup_cv_rows = tx
        .query(
            r#"
            SELECT ei.external_id, array_agg(DISTINCT m.issue_id ORDER BY m.issue_id) AS issue_ids
            FROM issue_external_identity_mappings m
            JOIN external_identities ei ON ei.id = m.external_identity_id
            JOIN issues i ON i.id = m.issue_id
            JOIN threads t ON t.id = i.thread_id
            WHERE ei.provider = 'comicvine' AND ei.entity_type = 'issue'
              AND m.status IN ('confirmed', 'candidate')
              AND t.user_id = $1
            GROUP BY ei.external_id
            HAVING count(DISTINCT m.issue_id) > 1
            ORDER BY ei.external_id
            LIMIT $2
            "#,
            &[&user_id, &(MAX_CANDIDATE_GROUPS as i64)],
        )
        .await
        .map_err(db_err)?;

    for row in dup_cv_rows {
        let cv_id: String = row.get(0);
        let issue_ids: Vec<i32> = row.get(1);
        let group_key = format!("cv-issue:{cv_id}");
        if !seen_groups.insert(group_key.clone()) {
            continue;
        }
        let mut evidence = Vec::new();
        for iid in &issue_ids {
            evidence.push(load_issue_evidence(tx, user_id, *iid).await?);
        }
        let (canonical, dups) = suggest_canonical_and_duplicates(&evidence);
        groups.push(DuplicateCandidateGroup {
            group_key,
            confidence: "high".to_string(),
            reason: format!("Multiple owned issues map to the same Comic Vine issue {cv_id}"),
            suggested_canonical_issue_id: canonical,
            suggested_duplicate_issue_ids: dups,
            evidence,
        });
    }

    // 2) Story/overall-number relationship: CV-mapped issue has issue_number that
    // matches another unmapped issue in a different thread (same user), or a
    // CV issue number matches while story numbering differs. We look for cases
    // where a comicvine issue mapping's metadata issue_number matches an owned
    // issue's issue_number in a different thread AND the mapped issue is in a
    // different thread - indicating same physical comic represented twice.
    let story_rows = tx
        .query(
            r#"
            SELECT DISTINCT ON (i1.id, i2.id)
                   i1.id AS mapped_issue_id, i2.id AS other_issue_id,
                   ei.external_id AS cv_issue_id,
                   ei.metadata_json->>'issue_number' AS cv_issue_number
            FROM issue_external_identity_mappings m
            JOIN external_identities ei ON ei.id = m.external_identity_id
                AND ei.provider = 'comicvine' AND ei.entity_type = 'issue'
            JOIN issues i1 ON i1.id = m.issue_id
            JOIN threads t1 ON t1.id = i1.thread_id
            JOIN threads t2 ON t2.user_id = t1.user_id AND t2.id <> t1.id
            JOIN issues i2 ON i2.thread_id = t2.id
            WHERE t1.user_id = $1
              AND m.status IN ('confirmed', 'candidate')
              AND i2.id <> i1.id
              AND (
                  -- other issue has same number as CV issue number (overall-number alias)
                  (ei.metadata_json->>'issue_number' IS NOT NULL
                   AND ei.metadata_json->>'issue_number' <> ''
                   AND i2.issue_number = ei.metadata_json->>'issue_number')
                  OR
                  -- other issue has same number as mapped issue's issue number
                  i2.issue_number = i1.issue_number
              )
              -- avoid flagging clearly different comics: require same CV volume family or
              -- explicit story/overall signal. We use: same comicvine volume id in metadata
              -- OR the CV issue's story_arc_number matches the other issue's number.
              AND (
                  (ei.metadata_json->>'volume_id' IS NOT NULL
                   AND EXISTS (
                       SELECT 1 FROM issue_external_identity_mappings m2
                       JOIN external_identities ei2 ON ei2.id = m2.external_identity_id
                       WHERE m2.issue_id = i2.id AND ei2.provider = 'comicvine'
                         AND ei2.entity_type = 'issue'
                         AND ei2.metadata_json->>'volume_id' = ei.metadata_json->>'volume_id'
                   ))
                  OR
                  (ei.metadata_json->>'story_arc_number' IS NOT NULL
                   AND ei.metadata_json->>'story_arc_number' = i2.issue_number)
                  OR
                  (ei.metadata_json->>'issue_number' IS NOT NULL
                   AND i1.issue_number <> i2.issue_number
                   AND ei.metadata_json->>'issue_number' = i2.issue_number)
              )
            ORDER BY i1.id, i2.id
            LIMIT $2
            "#,
            &[&user_id, &(MAX_CANDIDATE_GROUPS as i64)],
        )
        .await
        .map_err(db_err)?;

    for row in story_rows {
        let mapped_id: i32 = row.get(0);
        let other_id: i32 = row.get(1);
        let cv_id: String = row.get(2);
        let mut pair = vec![mapped_id, other_id];
        pair.sort();
        let group_key = format!("story-overall:{}:{}", pair[0], pair[1]);
        if !seen_groups.insert(group_key.clone()) {
            continue;
        }
        // Skip if both already in a same-CV group
        let mut evidence = Vec::new();
        for iid in &pair {
            evidence.push(load_issue_evidence(tx, user_id, *iid).await?);
        }
        let (canonical, dups) = suggest_canonical_and_duplicates(&evidence);
        groups.push(DuplicateCandidateGroup {
            group_key,
            confidence: "medium".to_string(),
            reason: format!(
                "Issues share a story/overall-number relationship via Comic Vine issue {cv_id}"
            ),
            suggested_canonical_issue_id: canonical,
            suggested_duplicate_issue_ids: dups,
            evidence,
        });
    }

    Ok(groups)
}

fn suggest_canonical_and_duplicates(evidence: &[DuplicateIssueEvidence]) -> (Option<i32>, Vec<i32>) {
    if evidence.is_empty() {
        return (None, vec![]);
    }
    // Heuristic: prefer issue that has list memberships, or is in "arc" thread (not synthetic overall),
    // or has non-placeholder read history, or was created earlier. Prefer the one with Comic Vine mapping
    // as canonical target if it's the "original" (has list memberships).
    let mut scored: Vec<(i32, i32)> = evidence
        .iter()
        .map(|e| {
            let mut score = 0i32;
            if !e.list_memberships.is_empty() {
                score += 100;
            }
            if e.is_synthetic_placeholder_read {
                score -= 50;
            }
            if !e.rating_events.is_empty() {
                score += 10;
            }
            if e.comicvine_issue_id.is_some() {
                score += 5;
            }
            // Prefer lower id as tiebreaker (older)
            score -= (e.issue_id % 1000).min(999);
            (e.issue_id, score)
        })
        .collect();
    scored.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
    let canonical = scored.first().map(|s| s.0);
    let dups = scored.iter().skip(1).map(|s| s.0).collect();
    (canonical, dups)
}

fn compute_preview_token(
    user_id: i32,
    canonical_issue_id: i32,
    duplicate_issue_ids: &[i32],
    canonical: &DuplicateIssueEvidence,
    duplicates: &[DuplicateIssueEvidence],
) -> String {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(user_id.to_le_bytes());
    hasher.update(canonical_issue_id.to_le_bytes());
    for id in duplicate_issue_ids {
        hasher.update(id.to_le_bytes());
    }
    // capture state: statuses, read_ats, event counts, mapping ids
    hasher.update(canonical.status.as_bytes());
    if let Some(ra) = &canonical.read_at {
        hasher.update(ra.as_bytes());
    }
    hasher.update((canonical.rating_events.len() as i32).to_le_bytes());
    hasher.update((canonical.read_events.len() as i32).to_le_bytes());
    if let Some(cv) = &canonical.comicvine_issue_id {
        hasher.update(cv.as_bytes());
    }
    for d in duplicates {
        hasher.update(d.status.as_bytes());
        if let Some(ra) = &d.read_at {
            hasher.update(ra.as_bytes());
        }
        hasher.update((d.rating_events.len() as i32).to_le_bytes());
        hasher.update((d.read_events.len() as i32).to_le_bytes());
        if let Some(cv) = &d.comicvine_issue_id {
            hasher.update(cv.as_bytes());
        }
        hasher.update((d.list_memberships.len() as i32).to_le_bytes());
    }
    let digest = hasher.finalize();
    format!("{:x}", digest)
}

fn build_preview_actions(
    canonical: &DuplicateIssueEvidence,
    duplicates: &[DuplicateIssueEvidence],
    _decisions: &HashMap<String, String>,
) -> (Vec<ReconcilePreviewAction>, Vec<String>, bool) {
    let mut actions = Vec::new();
    let mut warnings = Vec::new();
    let mut can_apply = true;

    for dup in duplicates {
        // Check for ambiguity - different comicvine volumes with no clear relationship
        if let (Some(c_cv), Some(d_cv)) = (&canonical.comicvine_volume_id, &dup.comicvine_volume_id) {
            if c_cv != d_cv {
                // Different volumes - could be story/overall relationship, warn but allow with decision
                actions.push(ReconcilePreviewAction {
                    kind: "cross_volume_merge".to_string(),
                    description: format!(
                        "Issue {} (CV vol {d_cv}) and canonical {} (CV vol {c_cv}) are in different Comic Vine volumes; verify they represent the same physical comic.",
                        dup.issue_id, canonical.issue_id
                    ),
                    safe: false,
                    requires_decision: true,
                    decision_key: Some(format!("cross_volume:{}", dup.issue_id)),
                });
            }
        }

        if let Some(cv) = &dup.comicvine_issue_id {
            actions.push(ReconcilePreviewAction {
                kind: "move_comicvine_mapping".to_string(),
                description: format!(
                    "Move Comic Vine issue {cv} mapping from duplicate {} to canonical {}",
                    dup.issue_id, canonical.issue_id
                ),
                safe: true,
                requires_decision: false,
                decision_key: None,
            });
        }

        if !dup.rating_events.is_empty() {
            actions.push(ReconcilePreviewAction {
                kind: "move_rating_events".to_string(),
                description: format!(
                    "Move {} rating event(s) from duplicate {} to canonical {} (preserving timestamps)",
                    dup.rating_events.len(), dup.issue_id, canonical.issue_id
                ),
                safe: true,
                requires_decision: false,
                decision_key: None,
            });
        }

        if !dup.read_events.is_empty() {
            let synthetic = dup.is_synthetic_placeholder_read;
            if synthetic {
                warnings.push(format!(
                    "Duplicate {} has read events with read_at before created_at; these are invalid synthetic placeholders and will not be treated as actual reading completion.",
                    dup.issue_id
                ));
                actions.push(ReconcilePreviewAction {
                    kind: "suppress_synthetic_read_events".to_string(),
                    description: format!(
                        "Suppress {} synthetic placeholder read event(s) on duplicate {} (invalid timestamp order); canonical reading history is preserved.",
                        dup.read_events.len(), dup.issue_id
                    ),
                    safe: true,
                    requires_decision: false,
                    decision_key: None,
                });
            } else {
                actions.push(ReconcilePreviewAction {
                    kind: "move_read_events".to_string(),
                    description: format!(
                        "Move {} read event(s) from duplicate {} to canonical {}",
                        dup.read_events.len(), dup.issue_id, canonical.issue_id
                    ),
                    safe: true,
                    requires_decision: false,
                    decision_key: None,
                });
            }
        }

        if !dup.list_memberships.is_empty() {
            actions.push(ReconcilePreviewAction {
                kind: "move_list_memberships".to_string(),
                description: format!(
                    "Move {} list membership(s) from duplicate {} to canonical {} (preserving exact positions/IDs where possible)",
                    dup.list_memberships.len(), dup.issue_id, canonical.issue_id
                ),
                safe: true,
                requires_decision: false,
                decision_key: None,
            });
        }

        actions.push(ReconcilePreviewAction {
            kind: "suppress_duplicate".to_string(),
            description: format!(
                "Mark duplicate {} as merged into canonical {} (no destructive delete; excluded from Roll/Queue)",
                dup.issue_id, canonical.issue_id
            ),
            safe: true,
            requires_decision: false,
            decision_key: None,
        });
    }

    // If canonical has no CV mapping but a duplicate does, that's fine - we move it.
    // Warn if canonical already read and duplicate also has real (non-synthetic) read - potential double-count
    for dup in duplicates {
        if canonical.status == "read" && dup.status == "read" && !dup.is_synthetic_placeholder_read {
            warnings.push(format!(
                "Both canonical {} and duplicate {} are read with non-synthetic timestamps; reconciliation will preserve the canonical's actual read state and move real events without double-counting.",
                canonical.issue_id, dup.issue_id
            ));
        }
    }

    // check for unresolved decisions
    for action in &actions {
        if action.requires_decision {
            if let Some(key) = &action.decision_key {
                if !_decisions.contains_key(key) {
                    can_apply = false;
                }
            }
        }
    }

    (actions, warnings, can_apply)
}
