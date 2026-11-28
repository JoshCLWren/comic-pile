//! Guided canonical duplicate-comic reconciliation (#4653).
//!
//! Detects likely duplicate physical issues, previews a history-safe merge,
//! and applies it with Undo support. This is a v2-native endpoint family.

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{extract::State, Json};
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
    pub merged_into_issue_id: Option<i32>,
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
    /// Per-event synthetic flag: true when the read timestamp predates its issue's creation.
    pub is_synthetic: bool,
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

fn conflict(msg: impl Into<String>) -> ApiError {
    ApiError::Conflict(msg.into())
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
                   i.read_at, i.created_at, i.merged_into_issue_id
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
    let merged_into_issue_id: Option<i32> = issue_row.get(7);
    let is_synthetic_placeholder_read =
        if let Some(read_dt) = issue_row.get::<_, Option<chrono::DateTime<chrono::Utc>>>(5) {
            read_dt < created_at_dt
        } else {
            false
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
            WHERE m.issue_id = $1 AND m.status = 'confirmed'
            ORDER BY m.id ASC
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
                .or_else(|| {
                    meta.get("volume_id")
                        .and_then(|v| v.as_i64())
                        .map(|v| v as i32)
                });
            let issue_num = meta
                .get("issue_number")
                .and_then(|v| v.as_str())
                .map(String::from);
            let story_num = meta
                .get("story_arc_number")
                .and_then(|v| v.as_str())
                .map(String::from)
                .or_else(|| {
                    meta.get("story_number")
                        .and_then(|v| v.as_str())
                        .map(String::from)
                });
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
        .map(|r| {
            let event_ts: chrono::DateTime<chrono::Utc> = r.get(1);
            DuplicateReadEvent {
                event_id: r.get(0),
                timestamp: required_ts(r, 1),
                issue_number: r.get(2),
                is_synthetic: event_ts < created_at_dt,
            }
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
        merged_into_issue_id,
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

/// A verified identity/alias relationship between two owned issues.
///
/// This is the single source of truth for the detection predicate. Preview and
/// apply re-run it so an arbitrary pair of owned issues can never be collapsed
/// without a detected, reviewed relationship (#4653).
#[derive(Debug, Clone)]
struct DetectedPair {
    issue_ids: [i32; 2],
    group_key: String,
    confidence: String,
    reason: String,
}

fn normalized_pair(a: i32, b: i32) -> (i32, i32) {
    if a < b {
        (a, b)
    } else {
        (b, a)
    }
}

/// Load every verified duplicate relationship for one reader.
///
/// Only `confirmed` provider mappings count as verified identity. A `candidate`
/// mapping needs explicit review in the identity inbox and must never be
/// presented here as an established provider identity.
async fn load_detected_pairs(
    tx: &Transaction<'_>,
    user_id: i32,
) -> Result<Vec<DetectedPair>, ApiError> {
    let mut pairs = Vec::new();

    // 1) Verified provider identity: two owned issues share one confirmed
    // Comic Vine issue mapping. Pairs are generated set-wise with a self join.
    let cv_rows = tx
        .query(
            r#"
            SELECT ei.external_id, m1.issue_id, m2.issue_id
            FROM issue_external_identity_mappings m1
            JOIN issue_external_identity_mappings m2
              ON m2.external_identity_id = m1.external_identity_id
             AND m2.issue_id > m1.issue_id
            JOIN external_identities ei ON ei.id = m1.external_identity_id
            JOIN issues i1 ON i1.id = m1.issue_id
            JOIN threads t1 ON t1.id = i1.thread_id
            JOIN issues i2 ON i2.id = m2.issue_id
            JOIN threads t2 ON t2.id = i2.thread_id
            WHERE ei.provider = 'comicvine' AND ei.entity_type = 'issue'
              AND m1.status = 'confirmed' AND m2.status = 'confirmed'
              AND t1.user_id = $1 AND t2.user_id = $1
            ORDER BY ei.external_id, m1.issue_id, m2.issue_id
            LIMIT $2
            "#,
            &[&user_id, &(MAX_CANDIDATE_GROUPS as i64)],
        )
        .await
        .map_err(db_err)?;
    for row in cv_rows {
        let cv_id: String = row.get(0);
        let a: i32 = row.get(1);
        let b: i32 = row.get(2);
        pairs.push(DetectedPair {
            issue_ids: [a, b],
            group_key: format!("cv-issue:{cv_id}"),
            confidence: "high".to_string(),
            reason: format!("Multiple owned issues map to the same Comic Vine issue {cv_id}"),
        });
    }

    // 2) Explicit story/overall-number relationship backed by a confirmed CV
    // mapping (volume family or story arc number on the provider metadata).
    let story_rows = tx
        .query(
            r#"
            SELECT DISTINCT ON (i1.id, i2.id)
                   i1.id AS mapped_issue_id, i2.id AS other_issue_id,
                   ei.external_id AS cv_issue_id
            FROM issue_external_identity_mappings m
            JOIN external_identities ei ON ei.id = m.external_identity_id
                AND ei.provider = 'comicvine' AND ei.entity_type = 'issue'
            JOIN issues i1 ON i1.id = m.issue_id
            JOIN threads t1 ON t1.id = i1.thread_id
            JOIN threads t2 ON t2.user_id = t1.user_id AND t2.id <> t1.id
            JOIN issues i2 ON i2.thread_id = t2.id
            WHERE t1.user_id = $1
              AND m.status = 'confirmed'
              AND i2.id <> i1.id
              AND (
                  (ei.metadata_json->>'issue_number' IS NOT NULL
                   AND ei.metadata_json->>'issue_number' <> ''
                   AND i2.issue_number = ei.metadata_json->>'issue_number')
                  OR i2.issue_number = i1.issue_number
                  OR (ei.metadata_json->>'story_arc_number' IS NOT NULL
                      AND ei.metadata_json->>'story_arc_number' <> ''
                      AND i2.issue_number = ei.metadata_json->>'story_arc_number')
              )
              AND (
                  (ei.metadata_json->>'volume_id' IS NOT NULL
                   AND EXISTS (
                       SELECT 1 FROM issue_external_identity_mappings m2
                       JOIN external_identities ei2 ON ei2.id = m2.external_identity_id
                       WHERE m2.issue_id = i2.id AND ei2.provider = 'comicvine'
                         AND ei2.entity_type = 'issue'
                         AND ei2.metadata_json->>'volume_id' = ei.metadata_json->>'volume_id'
                   ))
                  OR (ei.metadata_json->>'story_arc_number' IS NOT NULL
                      AND ei.metadata_json->>'story_arc_number' = i2.issue_number)
                  OR (ei.metadata_json->>'issue_number' IS NOT NULL
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
        let (a, b) = normalized_pair(mapped_id, other_id);
        pairs.push(DetectedPair {
            issue_ids: [a, b],
            group_key: format!("story-overall:{a}:{b}"),
            confidence: "medium".to_string(),
            reason: format!(
                "Issues share a story/overall-number relationship via Comic Vine issue {cv_id}"
            ),
        });
    }

    Ok(pairs)
}

/// Re-run the verified-predicate for every submitted alias before any write.
async fn require_detected_pairs(
    tx: &Transaction<'_>,
    user_id: i32,
    canonical_id: i32,
    duplicate_ids: &[i32],
) -> Result<(), ApiError> {
    if duplicate_ids.is_empty() {
        return Ok(());
    }
    let pairs = load_detected_pairs(tx, user_id).await?;
    let detected: BTreeSet<(i32, i32)> = pairs
        .iter()
        .map(|p| normalized_pair(p.issue_ids[0], p.issue_ids[1]))
        .collect();
    for dup_id in duplicate_ids {
        if !detected.contains(&normalized_pair(canonical_id, *dup_id)) {
            return Err(conflict(format!(
                "Issues {canonical_id} and {dup_id} are not a detected duplicate pair; refresh detections before reconciling"
            )));
        }
    }
    Ok(())
}

async fn detect_duplicates_for_user(
    tx: &Transaction<'_>,
    user_id: i32,
) -> Result<Vec<DuplicateCandidateGroup>, ApiError> {
    let pairs = load_detected_pairs(tx, user_id).await?;
    let mut groups: Vec<DuplicateCandidateGroup> = Vec::new();
    let mut seen_groups: BTreeSet<String> = BTreeSet::new();

    // Exact provider identity groups: every issue sharing one confirmed CV
    // identity is offered together, matching the historical group semantics.
    let mut cv_members: BTreeMap<String, BTreeSet<i32>> = BTreeMap::new();
    for pair in &pairs {
        if let Some(cv_id) = pair.group_key.strip_prefix("cv-issue:") {
            let members = cv_members.entry(cv_id.to_string()).or_default();
            members.insert(pair.issue_ids[0]);
            members.insert(pair.issue_ids[1]);
        }
    }
    for (cv_id, member_ids) in cv_members {
        let group_key = format!("cv-issue:{cv_id}");
        if !seen_groups.insert(group_key.clone()) {
            continue;
        }
        let mut evidence = Vec::new();
        for iid in &member_ids {
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

    for pair in &pairs {
        if pair.group_key.starts_with("cv-issue:") {
            continue;
        }
        if !seen_groups.insert(pair.group_key.clone()) {
            continue;
        }
        let mut evidence = Vec::new();
        for iid in pair.issue_ids {
            evidence.push(load_issue_evidence(tx, user_id, iid).await?);
        }
        let (canonical, dups) = suggest_canonical_and_duplicates(&evidence);
        groups.push(DuplicateCandidateGroup {
            group_key: pair.group_key.clone(),
            confidence: pair.confidence.clone(),
            reason: pair.reason.clone(),
            suggested_canonical_issue_id: canonical,
            suggested_duplicate_issue_ids: dups,
            evidence,
        });
    }

    Ok(groups)
}

fn suggest_canonical_and_duplicates(
    evidence: &[DuplicateIssueEvidence],
) -> (Option<i32>, Vec<i32>) {
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
    decisions: &HashMap<String, String>,
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
    // Decisions are part of the reviewed contract: changing link vs keep-distinct
    // invalidates the token so an apply cannot silently reuse a stale preview.
    let mut decision_keys: Vec<(&String, &String)> = decisions.iter().collect();
    decision_keys.sort_by(|a, b| a.0.cmp(b.0));
    for (key, value) in decision_keys {
        hasher.update(key.as_bytes());
        hasher.update(value.as_bytes());
    }
    let digest = hasher.finalize();
    digest.iter().map(|b| format!("{b:02x}")).collect()
}

/// Whether an explicitly reviewed duplicate must remain distinct instead of
/// being merged into the canonical issue.
fn is_kept_distinct(dup: &DuplicateIssueEvidence, decisions: &HashMap<String, String>) -> bool {
    decisions
        .get(&format!("cross_volume:{}", dup.issue_id))
        .is_some_and(|choice| choice == "keep_distinct")
}

fn build_preview_actions(
    canonical: &DuplicateIssueEvidence,
    duplicates: &[DuplicateIssueEvidence],
    decisions: &HashMap<String, String>,
) -> (Vec<ReconcilePreviewAction>, Vec<String>, bool) {
    let mut actions = Vec::new();
    let mut warnings = Vec::new();
    let mut can_apply = true;

    for dup in duplicates {
        if is_kept_distinct(dup, decisions) {
            actions.push(ReconcilePreviewAction {
                kind: "keep_distinct".to_string(),
                description: format!(
                    "Keep issue {} distinct: no mapping, event, membership or status change will be applied to it.",
                    dup.issue_id
                ),
                safe: true,
                requires_decision: false,
                decision_key: None,
            });
            continue;
        }
        // Check for ambiguity - different comicvine volumes with no clear relationship
        if let (Some(c_cv), Some(d_cv)) = (&canonical.comicvine_volume_id, &dup.comicvine_volume_id)
        {
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
            // Every read event carries its own provenance. Preview and apply
            // both use this per-event predicate, so mixed genuine/synthetic
            // histories are described exactly as they will be written.
            let synthetic_count = dup.read_events.iter().filter(|e| e.is_synthetic).count();
            let real_count = dup.read_events.len() - synthetic_count;
            if synthetic_count > 0 {
                warnings.push(format!(
                    "Duplicate {} has {synthetic_count} read event(s) before its creation; those are invalid synthetic placeholders and will not be treated as actual reading completion.",
                    dup.issue_id
                ));
                actions.push(ReconcilePreviewAction {
                    kind: "suppress_synthetic_read_events".to_string(),
                    description: format!(
                        "Suppress {synthetic_count} synthetic placeholder read event(s) on duplicate {} (invalid timestamp order); canonical reading history is preserved.",
                        dup.issue_id
                    ),
                    safe: true,
                    requires_decision: false,
                    decision_key: None,
                });
            }
            if real_count > 0 {
                actions.push(ReconcilePreviewAction {
                    kind: "move_read_events".to_string(),
                    description: format!(
                        "Move {real_count} genuine read event(s) from duplicate {} to canonical {}",
                        dup.issue_id, canonical.issue_id
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
        if is_kept_distinct(dup, decisions) {
            continue;
        }
        if canonical.status == "read" && dup.status == "read" && !dup.is_synthetic_placeholder_read
        {
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
                if !decisions.contains_key(key) {
                    can_apply = false;
                }
            }
        }
    }

    (actions, warnings, can_apply)
}

#[derive(utoipa::OpenApi)]
#[openapi(
    paths(
        detect_duplicates,
        preview_reconciliation,
        apply_reconciliation,
        undo_reconciliation
    ),
    components(schemas(
        DuplicateIssueEvidence,
        DuplicateRatingEvent,
        DuplicateReadEvent,
        DuplicateListMembership,
        DuplicateCandidateGroup,
        DuplicateDetectionResponse,
        ReconcilePreviewRequest,
        ReconcilePreviewAction,
        ReconcilePreviewResponse,
        ReconcileApplyRequest,
        ReconcileApplyResponse,
        ReconcileUndoRequest,
        ReconcileUndoResponse,
    ))
)]
pub struct IssueDuplicateReconciliationApi;

#[utoipa::path(
    get,
    path = "/api/v2/issue-duplicate-reconciliation/detect",
    operation_id = "issue_duplicate_reconciliation_detect",
    responses(
        (status = 200, description = "Detected duplicate groups", body = DuplicateDetectionResponse),
        (status = 401, description = "Unauthorized"),
    ),
    security(("HTTPBearer" = []))
)]
pub async fn detect_duplicates(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> Result<Json<DuplicateDetectionResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db_err)?;
    let groups = detect_duplicates_for_user(&tx, user.id()).await?;
    tx.commit().await.map_err(db_err)?;
    Ok(Json(DuplicateDetectionResponse { groups }))
}

#[utoipa::path(
    post,
    path = "/api/v2/issue-duplicate-reconciliation/preview",
    operation_id = "issue_duplicate_reconciliation_preview",
    request_body = ReconcilePreviewRequest,
    responses(
        (status = 200, description = "Preview reconciliation", body = ReconcilePreviewResponse),
        (status = 400, description = "Bad request"),
        (status = 401, description = "Unauthorized"),
        (status = 404, description = "Not found"),
    ),
    security(("HTTPBearer" = []))
)]
pub async fn preview_reconciliation(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(req): Json<ReconcilePreviewRequest>,
) -> Result<Json<ReconcilePreviewResponse>, ApiError> {
    if req.duplicate_issue_ids.is_empty() {
        return Err(bad_request("duplicate_issue_ids must not be empty"));
    }
    if req.duplicate_issue_ids.len() > MAX_GROUP_ISSUES {
        return Err(bad_request("too many duplicate issues"));
    }
    if req.duplicate_issue_ids.contains(&req.canonical_issue_id) {
        return Err(bad_request(
            "canonical_issue_id must not be in duplicate_issue_ids",
        ));
    }

    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db_err)?;

    // An arbitrary pair of owned issues is never a reconciliation candidate:
    // re-run the same verified predicate detection uses (#4653).
    require_detected_pairs(
        &tx,
        user.id(),
        req.canonical_issue_id,
        &req.duplicate_issue_ids,
    )
    .await?;

    let canonical = load_issue_evidence(&tx, user.id(), req.canonical_issue_id).await?;
    let mut duplicates = Vec::new();
    for id in &req.duplicate_issue_ids {
        duplicates.push(load_issue_evidence(&tx, user.id(), *id).await?);
    }

    let (actions, warnings, can_apply) =
        build_preview_actions(&canonical, &duplicates, &req.decisions);
    let preview_token = compute_preview_token(
        user.id(),
        req.canonical_issue_id,
        &req.duplicate_issue_ids,
        &canonical,
        &duplicates,
        &req.decisions,
    );

    tx.commit().await.map_err(db_err)?;
    Ok(Json(ReconcilePreviewResponse {
        canonical_issue_id: req.canonical_issue_id,
        duplicate_issue_ids: req.duplicate_issue_ids,
        canonical,
        duplicates,
        actions,
        warnings,
        can_apply,
        preview_token,
    }))
}

#[utoipa::path(
    post,
    path = "/api/v2/issue-duplicate-reconciliation/apply",
    operation_id = "issue_duplicate_reconciliation_apply",
    request_body = ReconcileApplyRequest,
    responses(
        (status = 200, description = "Apply reconciliation", body = ReconcileApplyResponse),
        (status = 400, description = "Bad request"),
        (status = 401, description = "Unauthorized"),
        (status = 404, description = "Not found"),
        (status = 409, description = "Conflict"),
    ),
    security(("HTTPBearer" = []))
)]
pub async fn apply_reconciliation(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(req): Json<ReconcileApplyRequest>,
) -> Result<Json<ReconcileApplyResponse>, ApiError> {
    if req.duplicate_issue_ids.is_empty() {
        return Err(bad_request("duplicate_issue_ids must not be empty"));
    }
    if req.duplicate_issue_ids.len() > MAX_GROUP_ISSUES {
        return Err(bad_request("too many duplicate issues"));
    }
    if req.duplicate_issue_ids.contains(&req.canonical_issue_id) {
        return Err(bad_request(
            "canonical_issue_id must not be in duplicate_issue_ids",
        ));
    }

    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db_err)?;

    // Reconciliation rewrites owned issue rows and their queue-facing state, so
    // it must serialize with every sibling writer that takes those same row
    // locks. Queue lock first, then the per-reader dice lock, matching
    // issue_service::persist and dice_mutation::persist_in_transaction; both
    // come before any FOR UPDATE row lock (#5398/#5419 lock order).
    crate::queue::lock_queue(&tx, user.id()).await?;
    tx.query_one(
        "SELECT pg_advisory_xact_lock($1::bigint)",
        &[&(user.id() as i64)],
    )
    .await
    .map_err(db_err)?;

    // Idempotency: if same preview token already applied, return prior result
    let existing = tx
        .query_opt(
            r#"
            SELECT id, canonical_issue_id, duplicate_issue_ids, details
            FROM issue_duplicate_reconciliations
            WHERE user_id = $1 AND preview_token = $2 AND undone_at IS NULL
            ORDER BY applied_at DESC
            LIMIT 1
            "#,
            &[&user.id(), &req.preview_token],
        )
        .await
        .map_err(db_err)?;
    if let Some(row) = existing {
        let details: serde_json::Value = row.get(3);
        tx.commit().await.map_err(db_err)?;
        return Ok(Json(ReconcileApplyResponse {
            canonical_issue_id: row.get(1),
            merged_issue_ids: row.get(2),
            moved_event_ids: details
                .get("moved_event_ids")
                .and_then(|v| serde_json::from_value(v.clone()).ok())
                .unwrap_or_default(),
            moved_mapping_ids: details
                .get("moved_mapping_ids")
                .and_then(|v| serde_json::from_value(v.clone()).ok())
                .unwrap_or_default(),
            moved_list_entry_ids: details
                .get("moved_list_entry_ids")
                .and_then(|v| serde_json::from_value(v.clone()).ok())
                .unwrap_or_default(),
            suppressed_duplicate_issue_ids: details
                .get("suppressed_duplicate_issue_ids")
                .and_then(|v| serde_json::from_value(v.clone()).ok())
                .unwrap_or_default(),
            // The stored `details` snapshot records undo_snapshot_id as null
            // before the reconciliation row exists. The row id is the Undo ID
            // returned by the original apply, so a retried apply must expose it
            // or the reader loses the Undo affordance after a lost response.
            undo_snapshot_id: Some(row.get::<_, i64>(0) as i32),
            warnings: details
                .get("warnings")
                .and_then(|v| serde_json::from_value(v.clone()).ok())
                .unwrap_or_default(),
        }));
    }

    // Lock issue rows
    let mut all_ids = vec![req.canonical_issue_id];
    all_ids.extend(req.duplicate_issue_ids.iter().copied());
    all_ids.sort();
    all_ids.dedup();
    for iid in &all_ids {
        let row = tx
            .query_opt(
                r#"SELECT i.id FROM issues i JOIN threads t ON t.id = i.thread_id WHERE i.id = $1 AND t.user_id = $2 FOR UPDATE"#,
                &[iid, &user.id()],
            )
            .await
            .map_err(db_err)?;
        if row.is_none() {
            return Err(not_found(&format!("Issue {iid} not found")));
        }
    }

    // Re-run detection for the submitted pair set. Row ownership is already
    // proven above, so a non-detected pair is a conflict rather than a 404.
    require_detected_pairs(
        &tx,
        user.id(),
        req.canonical_issue_id,
        &req.duplicate_issue_ids,
    )
    .await?;

    // Load evidence and validate token
    let canonical = load_issue_evidence(&tx, user.id(), req.canonical_issue_id).await?;
    let mut duplicates = Vec::new();
    let mut pre_warnings: Vec<String> = Vec::new();
    for id in &req.duplicate_issue_ids {
        let dup = load_issue_evidence(&tx, user.id(), *id).await?;
        if let Some(merged_into) = dup.merged_into_issue_id {
            if merged_into == req.canonical_issue_id {
                pre_warnings.push(format!(
                    "Issue {} is already merged into canonical {}; skipping.",
                    dup.issue_id, merged_into
                ));
                duplicates.push(dup);
                continue;
            }
            return Err(conflict(format!(
                "Issue {} is already merged into a different canonical {}",
                dup.issue_id, merged_into
            )));
        }
        duplicates.push(dup);
    }
    // The token is computed from the full reviewed selection so a changed
    // keep-distinct decision cannot reuse an earlier apply.
    let expected_token = compute_preview_token(
        user.id(),
        req.canonical_issue_id,
        &req.duplicate_issue_ids,
        &canonical,
        &duplicates,
        &req.decisions,
    );
    if expected_token != req.preview_token {
        return Err(conflict(
            "Stale preview token; refresh preview before applying",
        ));
    }

    // An explicit keep-distinct choice excludes that alias from every write.
    duplicates.retain(|dup| !is_kept_distinct(dup, &req.decisions));
    if duplicates.is_empty() {
        return Err(bad_request(
            "No aliases remain for reconciliation after keep-distinct decisions",
        ));
    }
    let merged_issue_ids: Vec<i32> = duplicates.iter().map(|dup| dup.issue_id).collect();
    let (_actions, mut warnings, can_apply) =
        build_preview_actions(&canonical, &duplicates, &req.decisions);
    warnings.extend(pre_warnings);
    if !can_apply {
        return Err(conflict(
            "Preview has unresolved decisions; resolve them before applying",
        ));
    }

    // Build undo snapshot
    let undo_snapshot = json!({
        "canonical_issue_id": req.canonical_issue_id,
        "duplicate_issue_ids": req.duplicate_issue_ids,
        "canonical": serde_json::to_value(&canonical).unwrap_or(json!(null)),
        "duplicates": serde_json::to_value(&duplicates).unwrap_or(json!(null)),
    });

    let mut moved_event_ids: Vec<i32> = Vec::new();
    let mut moved_mapping_ids: Vec<i32> = Vec::new();
    let mut moved_list_entry_ids: Vec<i32> = Vec::new();
    let mut suppressed_duplicate_issue_ids: Vec<i32> = Vec::new();
    let mut moved_event_origins: Vec<serde_json::Value> = Vec::new();
    let mut moved_mapping_origins: Vec<serde_json::Value> = Vec::new();
    let mut moved_list_entry_origins: Vec<serde_json::Value> = Vec::new();

    for dup in &duplicates {
        if dup.merged_into_issue_id == Some(req.canonical_issue_id) {
            suppressed_duplicate_issue_ids.push(dup.issue_id);
            continue;
        }
        // Move comicvine mappings: reassign issue_external_identity_mappings from dup to canonical
        let mapping_rows = tx
            .query(
                r#"
                SELECT m.id, m.external_identity_id, m.status
                FROM issue_external_identity_mappings m
                WHERE m.issue_id = $1
                "#,
                &[&dup.issue_id],
            )
            .await
            .map_err(db_err)?;
        for mr in &mapping_rows {
            let mapping_id: i32 = mr.get(0);
            let ext_id: i32 = mr.get(1);
            let status: String = mr.get(2);
            // if canonical already has a mapping for same external identity, skip move
            let exists = tx
                .query_opt(
                    "SELECT 1 FROM issue_external_identity_mappings WHERE issue_id = $1 AND external_identity_id = $2",
                    &[&req.canonical_issue_id, &ext_id],
                )
                .await
                .map_err(db_err)?;
            if exists.is_some() {
                // keep the mapping on canonical, remove from dup to avoid unique conflict issues? just leave - we'll suppress dup
                warnings.push(format!("Mapping {mapping_id} already exists on canonical; skipping duplicate mapping move."));
                continue;
            }
            // avoid violating unique (issue_id, external_identity_id) if moving
            tx.execute(
                "UPDATE issue_external_identity_mappings SET issue_id = $1, updated_at = now() WHERE id = $2",
                &[&req.canonical_issue_id, &mapping_id],
            )
            .await
            .map_err(db_err)?;
            moved_mapping_ids.push(mapping_id);
            moved_mapping_origins
                .push(json!({"mapping_id": mapping_id, "original_issue_id": dup.issue_id}));
            let _ = status;
        }

        // Move rating events (real history) - always move, preserving timestamps
        let rating_rows = tx
            .query(
                r#"SELECT id FROM events WHERE issue_id = $1 AND type = 'rate' AND rating IS NOT NULL"#,
                &[&dup.issue_id],
            )
            .await
            .map_err(db_err)?;
        for rr in &rating_rows {
            let eid: i32 = rr.get(0);
            tx.execute(
                "UPDATE events SET issue_id = $1 WHERE id = $2",
                &[&req.canonical_issue_id, &eid],
            )
            .await
            .map_err(db_err)?;
            moved_event_ids.push(eid);
            moved_event_origins.push(json!({"event_id": eid, "original_issue_id": dup.issue_id}));
        }

        // Handle read events from the exact per-event provenance preview used.
        // Synthetic placeholder events stay on the duplicate as repair audit
        // provenance; genuine events are moved with their original timestamps.
        for event in &dup.read_events {
            let eid = event.event_id;
            if event.is_synthetic {
                warnings.push(format!("Event {eid} is a synthetic placeholder read (timestamp before issue creation); preserved as provenance on duplicate."));
                continue;
            }
            tx.execute(
                "UPDATE events SET issue_id = $1 WHERE id = $2",
                &[&req.canonical_issue_id, &eid],
            )
            .await
            .map_err(db_err)?;
            moved_event_ids.push(eid);
            moved_event_origins.push(json!({"event_id": eid, "original_issue_id": dup.issue_id}));
        }

        // Move list memberships
        let list_rows = tx
            .query(
                r#"SELECT id, list_id, "position" FROM custom_cbl_entries WHERE issue_id = $1"#,
                &[&dup.issue_id],
            )
            .await
            .map_err(db_err)?;
        for lr in &list_rows {
            let entry_id: i32 = lr.get(0);
            let list_id: i32 = lr.get(1);
            // If canonical already in same list, keep canonical membership, record conflict
            let exists = tx
                .query_opt(
                    "SELECT id FROM custom_cbl_entries WHERE list_id = $1 AND issue_id = $2",
                    &[&list_id, &req.canonical_issue_id],
                )
                .await
                .map_err(db_err)?;
            if exists.is_some() {
                warnings.push(format!("Canonical issue already in list {list_id}; duplicate list entry {entry_id} left on duplicate for provenance."));
                continue;
            }
            tx.execute(
                "UPDATE custom_cbl_entries SET issue_id = $1 WHERE id = $2",
                &[&req.canonical_issue_id, &entry_id],
            )
            .await
            .map_err(db_err)?;
            moved_list_entry_ids.push(entry_id);
            moved_list_entry_origins
                .push(json!({"entry_id": entry_id, "original_issue_id": dup.issue_id}));
        }

        // Suppress duplicate - mark as merged, not deleted
        tx.execute(
            "UPDATE issues SET merged_into_issue_id = $1, merged_at = now() WHERE id = $2",
            &[&req.canonical_issue_id, &dup.issue_id],
        )
        .await
        .map_err(db_err)?;
        suppressed_duplicate_issue_ids.push(dup.issue_id);
    }

    // Reconcile canonical read state: preserve latest legitimate state.
    // If canonical has real read events/ratings indicating read, keep it read.
    // If canonical is unread but has moved real read events, update accordingly.
    // Important: do NOT let synthetic placeholder reads on duplicates affect this.
    // Moved read events were already validated against the *duplicate's*
    // creation time before the move. Never re-filter them against the
    // canonical's creation time: an older duplicate's genuine read would
    // otherwise be discarded (#4653).
    let canonical_real_read = tx
        .query_opt(
            r#"
            SELECT 1 FROM events e
            JOIN issues i ON i.id = e.issue_id
            WHERE e.issue_id = $1 AND e.type = 'issue_read'
              AND (e.id = ANY($2::int[]) OR e."timestamp" >= i.created_at)
            LIMIT 1
            "#,
            &[&req.canonical_issue_id, &moved_event_ids],
        )
        .await
        .map_err(db_err)?;
    let canonical_latest_rating = tx
        .query_opt(
            r#"SELECT "timestamp" FROM events WHERE issue_id = $1 AND type = 'rate' AND rating IS NOT NULL ORDER BY "timestamp" DESC, id DESC LIMIT 1"#,
            &[&req.canonical_issue_id],
        )
        .await
        .map_err(db_err)?;

    // If there's a real read event or rating, canonical should be read with appropriate read_at
    if canonical_real_read.is_some() || canonical_latest_rating.is_some() {
        // Determine the best read_at: latest real read event, or keep existing if real
        let latest_real_read_ts: Option<chrono::DateTime<chrono::Utc>> = tx
            .query_opt(
                r#"
                SELECT e."timestamp" FROM events e
                JOIN issues i ON i.id = e.issue_id
                WHERE e.issue_id = $1 AND e.type = 'issue_read'
                  AND (e.id = ANY($2::int[]) OR e."timestamp" >= i.created_at)
                ORDER BY e."timestamp" DESC, e.id DESC
                LIMIT 1
                "#,
                &[&req.canonical_issue_id, &moved_event_ids],
            )
            .await
            .map_err(db_err)?
            .map(|r| r.get(0));
        let canonical_created: chrono::DateTime<chrono::Utc> = tx
            .query_one(
                "SELECT created_at FROM issues WHERE id = $1",
                &[&req.canonical_issue_id],
            )
            .await
            .map_err(db_err)?
            .get(0);
        let canonical_read_at: Option<chrono::DateTime<chrono::Utc>> = tx
            .query_one(
                "SELECT read_at FROM issues WHERE id = $1",
                &[&req.canonical_issue_id],
            )
            .await
            .map_err(db_err)?
            .get(0);
        let canonical_read_is_real = canonical_read_at
            .map(|r| r >= canonical_created)
            .unwrap_or(false);

        // Only update if we have a better real timestamp or canonical is unread
        let new_read_at = latest_real_read_ts.or(if canonical_read_is_real {
            canonical_read_at
        } else {
            None
        });
        if let Some(ts) = new_read_at {
            tx.execute(
                "UPDATE issues SET status = 'read', read_at = $1 WHERE id = $2",
                &[&ts, &req.canonical_issue_id],
            )
            .await
            .map_err(db_err)?;
        } else if canonical_latest_rating.is_some() {
            // Has rating but no real read event - keep current state, don't fabricate
            // But ensure it's marked read if it has a real read_at
            if canonical_read_is_real {
                tx.execute(
                    "UPDATE issues SET status = 'read' WHERE id = $1",
                    &[&req.canonical_issue_id],
                )
                .await
                .map_err(db_err)?;
            }
        }
    }

    let details = json!({
        "moved_event_ids": moved_event_ids,
        "moved_mapping_ids": moved_mapping_ids,
        "moved_list_entry_ids": moved_list_entry_ids,
        "moved_event_origins": moved_event_origins,
        "moved_mapping_origins": moved_mapping_origins,
        "moved_list_entry_origins": moved_list_entry_origins,
        "suppressed_duplicate_issue_ids": suppressed_duplicate_issue_ids,
        "undo_snapshot_id": null,
        "warnings": warnings,
    });

    let rec_row = tx
        .query_one(
            r#"
            INSERT INTO issue_duplicate_reconciliations
                (user_id, canonical_issue_id, duplicate_issue_ids, preview_token, undo_snapshot, details)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            "#,
            &[&user.id(), &req.canonical_issue_id, &req.duplicate_issue_ids, &req.preview_token, &undo_snapshot, &details],
        )
        .await
        .map_err(db_err)?;
    let recon_id: i64 = rec_row.get(0);

    tx.commit().await.map_err(db_err)?;

    Ok(Json(ReconcileApplyResponse {
        canonical_issue_id: req.canonical_issue_id,
        merged_issue_ids,
        moved_event_ids,
        moved_mapping_ids,
        moved_list_entry_ids,
        suppressed_duplicate_issue_ids,
        undo_snapshot_id: Some(recon_id as i32),
        warnings,
    }))
}

#[derive(Debug, Clone, Deserialize, ToSchema)]
pub struct ReconcileUndoRequest {
    pub reconciliation_id: i32,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReconcileUndoResponse {
    pub reconciliation_id: i32,
    pub undone: bool,
    pub warnings: Vec<String>,
}

#[utoipa::path(
    post,
    path = "/api/v2/issue-duplicate-reconciliation/undo",
    operation_id = "issue_duplicate_reconciliation_undo",
    request_body = ReconcileUndoRequest,
    responses(
        (status = 200, description = "Undo reconciliation", body = ReconcileUndoResponse),
        (status = 401, description = "Unauthorized"),
        (status = 404, description = "Not found"),
    ),
    security(("HTTPBearer" = []))
)]
pub async fn undo_reconciliation(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(req): Json<ReconcileUndoRequest>,
) -> Result<Json<ReconcileUndoResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db_err)?;

    // Undo takes the same locks in the same order as apply for the same reason.
    crate::queue::lock_queue(&tx, user.id()).await?;
    tx.query_one(
        "SELECT pg_advisory_xact_lock($1::bigint)",
        &[&(user.id() as i64)],
    )
    .await
    .map_err(db_err)?;

    let row = tx
        .query_opt(
            r#"
            SELECT id, canonical_issue_id, duplicate_issue_ids, undone_at, details, undo_snapshot
            FROM issue_duplicate_reconciliations
            WHERE id = $1 AND user_id = $2
            FOR UPDATE
            "#,
            &[&(req.reconciliation_id as i64), &user.id()],
        )
        .await
        .map_err(db_err)?
        .ok_or_else(|| not_found("Reconciliation not found"))?;

    let undone_at: Option<chrono::DateTime<chrono::Utc>> = row.get(3);
    if undone_at.is_some() {
        tx.commit().await.map_err(db_err)?;
        return Ok(Json(ReconcileUndoResponse {
            reconciliation_id: req.reconciliation_id,
            undone: true,
            warnings: vec!["Reconciliation was already undone.".to_string()],
        }));
    }

    let canonical_issue_id: i32 = row.get(1);
    let duplicate_issue_ids: Vec<i32> = row.get(2);
    let details: serde_json::Value = row.get(4);
    let undo_snapshot: serde_json::Value = row.get(5);
    let mut warnings: Vec<String> = Vec::new();

    // Reverse event moves
    if let Some(origins) = details
        .get("moved_event_origins")
        .and_then(|v| v.as_array())
    {
        for o in origins {
            let event_id = o.get("event_id").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
            let original_issue_id = o
                .get("original_issue_id")
                .and_then(|v| v.as_i64())
                .unwrap_or(0) as i32;
            if event_id > 0 && original_issue_id > 0 {
                let updated = tx
                    .execute(
                        "UPDATE events SET issue_id = $1 WHERE id = $2 AND issue_id = $3",
                        &[&original_issue_id, &event_id, &canonical_issue_id],
                    )
                    .await
                    .map_err(db_err)?;
                if updated == 0 {
                    warnings.push(format!(
                        "Event {event_id} could not be moved back; it may have changed."
                    ));
                }
            }
        }
    }

    // Reverse mapping moves
    if let Some(origins) = details
        .get("moved_mapping_origins")
        .and_then(|v| v.as_array())
    {
        for o in origins {
            let mapping_id = o.get("mapping_id").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
            let original_issue_id = o
                .get("original_issue_id")
                .and_then(|v| v.as_i64())
                .unwrap_or(0) as i32;
            if mapping_id > 0 && original_issue_id > 0 {
                // Check for conflict on original issue
                let conflict_exists = tx.query_opt(
                    "SELECT 1 FROM issue_external_identity_mappings m1 WHERE m1.id = $1 AND EXISTS (SELECT 1 FROM issue_external_identity_mappings m2 WHERE m2.issue_id = $2 AND m2.external_identity_id = m1.external_identity_id AND m2.id <> m1.id)",
                    &[&mapping_id, &original_issue_id],
                ).await.map_err(db_err)?;
                if conflict_exists.is_some() {
                    warnings.push(format!(
                        "Mapping {mapping_id} could not be moved back due to conflict."
                    ));
                    continue;
                }
                let updated = tx.execute(
                    "UPDATE issue_external_identity_mappings SET issue_id = $1, updated_at = now() WHERE id = $2 AND issue_id = $3",
                    &[&original_issue_id, &mapping_id, &canonical_issue_id],
                ).await.map_err(db_err)?;
                if updated == 0 {
                    warnings.push(format!("Mapping {mapping_id} could not be moved back."));
                }
            }
        }
    }

    // Reverse list entry moves
    if let Some(origins) = details
        .get("moved_list_entry_origins")
        .and_then(|v| v.as_array())
    {
        for o in origins {
            let entry_id = o.get("entry_id").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
            let original_issue_id = o
                .get("original_issue_id")
                .and_then(|v| v.as_i64())
                .unwrap_or(0) as i32;
            if entry_id > 0 && original_issue_id > 0 {
                let updated = tx.execute(
                    "UPDATE custom_cbl_entries SET issue_id = $1 WHERE id = $2 AND issue_id = $3",
                    &[&original_issue_id, &entry_id, &canonical_issue_id],
                ).await.map_err(db_err)?;
                if updated == 0 {
                    warnings.push(format!("List entry {entry_id} could not be moved back."));
                }
            }
        }
    }

    // Unmerge duplicates
    for dup_id in &duplicate_issue_ids {
        tx.execute(
            "UPDATE issues SET merged_into_issue_id = NULL, merged_at = NULL WHERE id = $1 AND merged_into_issue_id = $2",
            &[dup_id, &canonical_issue_id],
        ).await.map_err(db_err)?;
    }

    // Restore canonical/duplicate states from snapshot where possible
    if let Some(canon_snap) = undo_snapshot.get("canonical") {
        let status = canon_snap.get("status").and_then(|v| v.as_str());
        let read_at_str = canon_snap.get("read_at").and_then(|v| v.as_str());
        if let Some(status) = status {
            if let Some(ra_str) = read_at_str {
                if let Ok(ra) = chrono::DateTime::parse_from_rfc3339(ra_str) {
                    let ra_utc = ra.with_timezone(&chrono::Utc);
                    tx.execute(
                        "UPDATE issues SET status = $1, read_at = $2 WHERE id = $3",
                        &[&status, &ra_utc, &canonical_issue_id],
                    )
                    .await
                    .map_err(db_err)?;
                } else {
                    tx.execute(
                        "UPDATE issues SET status = $1 WHERE id = $2",
                        &[&status, &canonical_issue_id],
                    )
                    .await
                    .map_err(db_err)?;
                }
            } else {
                tx.execute(
                    "UPDATE issues SET status = $1, read_at = NULL WHERE id = $2",
                    &[&status, &canonical_issue_id],
                )
                .await
                .map_err(db_err)?;
            }
        }
    }
    if let Some(dups_snap) = undo_snapshot.get("duplicates").and_then(|v| v.as_array()) {
        for d in dups_snap {
            let did = d.get("issue_id").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
            let status = d.get("status").and_then(|v| v.as_str());
            let read_at_str = d.get("read_at").and_then(|v| v.as_str());
            if did > 0 {
                if let Some(status) = status {
                    if let Some(ra_str) = read_at_str {
                        if let Ok(ra) = chrono::DateTime::parse_from_rfc3339(ra_str) {
                            let ra_utc = ra.with_timezone(&chrono::Utc);
                            tx.execute(
                                "UPDATE issues SET status = $1, read_at = $2 WHERE id = $3",
                                &[&status, &ra_utc, &did],
                            )
                            .await
                            .map_err(db_err)?;
                        } else {
                            tx.execute(
                                "UPDATE issues SET status = $1 WHERE id = $2",
                                &[&status, &did],
                            )
                            .await
                            .map_err(db_err)?;
                        }
                    } else {
                        tx.execute(
                            "UPDATE issues SET status = $1, read_at = NULL WHERE id = $2",
                            &[&status, &did],
                        )
                        .await
                        .map_err(db_err)?;
                    }
                }
            }
        }
    }

    tx.execute(
        "UPDATE issue_duplicate_reconciliations SET undone_at = now() WHERE id = $1",
        &[&(req.reconciliation_id as i64)],
    )
    .await
    .map_err(db_err)?;

    tx.commit().await.map_err(db_err)?;
    Ok(Json(ReconcileUndoResponse {
        reconciliation_id: req.reconciliation_id,
        undone: true,
        warnings,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn evidence(
        issue_id: i32,
        status: &str,
        read_at: Option<&str>,
        created_at: &str,
    ) -> DuplicateIssueEvidence {
        DuplicateIssueEvidence {
            issue_id,
            thread_id: 1,
            thread_title: "Test".to_string(),
            issue_number: issue_id.to_string(),
            status: status.to_string(),
            read_at: read_at.map(str::to_string),
            created_at: created_at.to_string(),
            merged_into_issue_id: None,
            comicvine_issue_id: None,
            comicvine_volume_id: None,
            comicvine_issue_number: None,
            comicvine_story_number: None,
            rating_events: vec![],
            read_events: vec![],
            list_memberships: vec![],
            is_synthetic_placeholder_read: read_at
                .and_then(|r| chrono::DateTime::parse_from_rfc3339(r).ok())
                .zip(chrono::DateTime::parse_from_rfc3339(created_at).ok())
                .map(|(r, c)| r.with_timezone(&chrono::Utc) < c.with_timezone(&chrono::Utc))
                .unwrap_or(false),
        }
    }

    #[test]
    fn synthetic_placeholder_read_is_detected() {
        let e = evidence(
            1,
            "read",
            Some("2026-11-05T05:02:02Z"),
            "2026-11-05T05:11:33Z",
        );
        assert!(e.is_synthetic_placeholder_read);
    }

    #[test]
    fn real_read_is_not_synthetic() {
        let e = evidence(
            1,
            "read",
            Some("2026-11-05T05:47:59Z"),
            "2026-11-05T05:11:33Z",
        );
        assert!(!e.is_synthetic_placeholder_read);
    }

    /// #3231 rehearsal: two readers confirm the same external issue identity.
    /// The same-owner pair is a duplicate candidate; the cross-owner pair is a
    /// legitimate shared reference and must never be reconciled as a duplicate.
    async fn rehearsal_fixture() -> (
        std::sync::Arc<AppState>,
        tokio::sync::MutexGuard<'static, ()>,
    ) {
        let state = crate::test_support::test_state(2)
            .await
            .expect("RUST_ROLL_TEST_DATABASE_URL is required");
        let guard = crate::test_support::reset_for_test(&state).await;
        let conn = db::checkout(&state)
            .await
            .expect("duplicate rehearsal connection");
        conn.batch_execute(
            r#"
            INSERT INTO users (id, username, created_at) VALUES
                (9101, 'dup-a', NOW()), (9102, 'dup-b', NOW());
            INSERT INTO external_identities
                (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
            VALUES (8001, 'comicvine', 'issue', '4050-0001', '{}'::json, NOW(), NOW());
            INSERT INTO threads
                (id, user_id, title, issues_remaining, queue_position, status, created_at)
            VALUES (9201, 9101, 'A one', 1, 1, 'active', NOW()),
                   (9202, 9101, 'A two', 1, 2, 'active', NOW()),
                   (9401, 9102, 'B one', 1, 1, 'active', NOW());
            INSERT INTO issues
                (id, thread_id, issue_number, status, created_at, position)
            VALUES (9201, 9201, '1', 'unread', NOW(), 1),
                   (9202, 9202, '2', 'unread', NOW(), 1),
                   (9401, 9401, '1', 'unread', NOW(), 1);
            INSERT INTO issue_external_identity_mappings
                (id, issue_id, external_identity_id, status, evidence_source, evidence_json,
                 created_at, updated_at)
            VALUES (9301, 9201, 8001, 'confirmed', 'rehearsal', '{}'::json, NOW(), NOW()),
                   (9302, 9202, 8001, 'confirmed', 'rehearsal', '{}'::json, NOW(), NOW()),
                   (9501, 9401, 8001, 'confirmed', 'rehearsal', '{}'::json, NOW(), NOW());
            "#,
        )
        .await
        .expect("seed duplicate rehearsal fixture");
        drop(conn);
        (state, guard)
    }

    #[tokio::test]
    async fn rehearsal_same_owner_duplicate_is_not_a_cross_owner_shared_reference() {
        let (state, _guard) = rehearsal_fixture().await;
        let mut conn = db::checkout(&state)
            .await
            .expect("rehearsal transaction connection");
        let tx = conn
            .build_transaction()
            .read_only(true)
            .start()
            .await
            .expect("rehearsal transaction");

        let a_pairs = load_detected_pairs(&tx, 9101)
            .await
            .expect("reader A duplicate pairs");
        assert_eq!(
            a_pairs
                .iter()
                .map(|p| (p.issue_ids, p.group_key.clone()))
                .collect::<Vec<_>>(),
            vec![([9201, 9202], "cv-issue:4050-0001".to_string())],
            "same-owner confirmed identity is a duplicate candidate: {a_pairs:?}"
        );

        let b_pairs = load_detected_pairs(&tx, 9102)
            .await
            .expect("reader B duplicate pairs");
        assert!(
            b_pairs.is_empty(),
            "one owner cannot duplicate against a foreign issue: {b_pairs:?}"
        );
        assert!(
            !a_pairs.iter().any(|p| p.issue_ids.contains(&9401)),
            "cross-owner shared reference must not be reported as a duplicate: {a_pairs:?}"
        );

        tx.rollback().await.expect("rollback rehearsal transaction");
    }

    #[test]
    fn preview_warns_on_synthetic_read_events() {
        let canonical = evidence(
            10,
            "read",
            Some("2026-11-05T06:03:08Z"),
            "2026-01-01T00:00:00Z",
        );
        let mut dup = evidence(
            20,
            "read",
            Some("2026-11-05T05:02:02Z"),
            "2026-11-05T05:11:33Z",
        );
        dup.read_events.push(DuplicateReadEvent {
            event_id: 1,
            timestamp: "2026-11-05T05:02:02Z".to_string(),
            issue_number: Some("101".to_string()),
            is_synthetic: true,
        });
        let (actions, warnings, can_apply) =
            build_preview_actions(&canonical, &[dup], &HashMap::new());
        assert!(can_apply);
        assert!(warnings.iter().any(|w| w.contains("synthetic placeholder")));
        assert!(actions
            .iter()
            .any(|a| a.kind == "suppress_synthetic_read_events"));
    }

    #[test]
    fn preview_token_changes_with_state() {
        let canonical = evidence(10, "unread", None, "2026-01-01T00:00:00Z");
        let dup = evidence(20, "unread", None, "2026-01-02T00:00:00Z");
        let t1 = compute_preview_token(
            1,
            10,
            &[20],
            &canonical,
            std::slice::from_ref(&dup),
            &HashMap::new(),
        );
        let mut dup2 = dup;
        dup2.status = "read".to_string();
        let t2 = compute_preview_token(1, 10, &[20], &canonical, &[dup2], &HashMap::new());
        assert_ne!(t1, t2);
    }

    #[test]
    fn keep_distinct_decision_excludes_alias_from_merge_actions() {
        let canonical = evidence(
            10,
            "read",
            Some("2026-11-05T06:03:08Z"),
            "2026-01-01T00:00:00Z",
        );
        let mut dup = evidence(
            20,
            "read",
            Some("2026-11-05T05:47:59Z"),
            "2026-11-05T05:11:33Z",
        );
        dup.rating_events.push(DuplicateRatingEvent {
            event_id: 1,
            rating: 4.0,
            timestamp: "2026-11-05T05:47:59Z".to_string(),
        });
        let mut decisions = HashMap::new();
        decisions.insert("cross_volume:20".to_string(), "keep_distinct".to_string());
        let (actions, _warnings, can_apply) =
            build_preview_actions(&canonical, &[dup.clone()], &decisions);
        assert!(can_apply);
        assert!(actions.iter().any(|a| a.kind == "keep_distinct"));
        assert!(!actions.iter().any(|a| a.kind == "move_rating_events"));
        assert!(!actions.iter().any(|a| a.kind == "suppress_duplicate"));

        // A changed decision must invalidate the preview token.
        let token_keep = compute_preview_token(
            1,
            10,
            &[20],
            &canonical,
            std::slice::from_ref(&dup),
            &decisions,
        );
        decisions.insert("cross_volume:20".to_string(), "merge".to_string());
        let token_merge = compute_preview_token(
            1,
            10,
            &[20],
            &canonical,
            std::slice::from_ref(&dup),
            &decisions,
        );
        assert_ne!(token_keep, token_merge);
    }
}

#[utoipa::path(get, path = "/__docs__/issue-duplicate-reconciliation", responses((status = 200)))]
pub fn documentation() {}
