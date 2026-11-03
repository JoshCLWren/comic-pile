//! Authenticated Continuity Plan Reader v2 resource.
//! Implements GET /api/v2/continuity-plans/{plan_id}/reader
//!
//! Returns the Option E Reading List projection for a plan with a linked
//! authoritative Reading List. Fails with 409 if the plan has no linked list
//! or ambiguous associations, matching Python's behavior.

use crate::{
    auth::AuthenticatedUser, db, option_inputs, reading_constraints::ValidatedReadingInputs,
    reading_eligibility::evaluate, ApiError, AppState,
};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use deadpool_postgres::Object;
use serde::{Deserialize, Serialize};
use std::{
    collections::{HashMap, HashSet},
    sync::Arc,
};
use utoipa::ToSchema;

#[derive(Deserialize, ToSchema)]
pub struct ContinuityPlanReaderPath {
    pub plan_id: i32,
}

/// Canonical v2 response for the Continuity Plan Reader.
/// Matches Python's ReadingPlanReaderResponse shape for Option E execution mode.
#[derive(Serialize, ToSchema)]
pub struct ContinuityPlanReaderResponse {
    pub execution_mode: String, // Always "option_e"
    pub plan_id: i32,
    pub name: String,
    pub ordering_mode: String, // "strict_sequential" or "informational"
    pub progress: ReadingPlanProgress,
    pub available_now: Vec<ContinuityPlanReaderIssue>,
    pub blocked_next: Vec<ContinuityPlanReaderIssue>,
    pub lanes: Vec<ContinuityPlanReaderLane>,
    pub sources: Vec<ReadingPlanSourceSnapshot>,
    pub release_sources: Vec<ReadingPlanReleaseSourceStatus>,
    pub release_candidates: Vec<ReadingPlanReleaseCandidate>,
}

#[derive(Serialize, ToSchema)]
pub struct ReadingPlanProgress {
    pub total_issues: i32,
    pub read_issues: i32,
}

#[derive(Serialize, Clone, ToSchema)]
pub struct ContinuityPlanReaderIssue {
    pub occurrence_id: String,
    pub issue_id: i32,
    pub lane_id: String,
    pub display_position: i32,
    pub label: Option<String>,
    pub reader_role: Option<String>,
    pub reader_optional: Option<bool>,
    pub is_checkpoint: bool,
    pub issue_number: String,
    pub thread_id: i32,
    pub thread_title: String,
    pub status: String,
    pub availability: String,
    pub blockers: Vec<ContinuityPlanBlocker>,
    pub source_paths: Vec<String>,
}

#[derive(Serialize, Clone, ToSchema)]
pub struct ContinuityPlanBlocker {
    pub issue_id: i32,
    pub thread_id: i32,
    pub thread_title: String,
    pub issue_number: String,
    pub explanation: String,
}

#[derive(Serialize, Clone, ToSchema)]
pub struct ContinuityPlanReaderLane {
    pub id: String,
    pub name: String,
    pub order: i32,
    pub issues: Vec<ContinuityPlanReaderIssue>,
}

#[derive(Serialize, ToSchema)]
pub struct ReadingPlanSourceSnapshot {
    pub id: i32,
    pub display_name: Option<String>,
    pub raw_source_path: String,
    pub repository: Option<String>,
    pub source_path: Option<String>,
    pub revision_sha: Option<String>,
    pub content_hash: Option<String>,
    pub adopted_at: Option<String>,
    pub recorded_at: String,
}

#[derive(Serialize, ToSchema)]
pub struct ReadingPlanReleaseSourceStatus {
    pub source_id: i32,
    pub thread_id: i32,
    pub external_identity_id: i32,
    pub provider_volume_id: String,
    pub provider_title: Option<String>,
    pub provider_publisher: Option<String>,
    pub provider_start_year: Option<i32>,
    pub provider_issue_count: Option<i32>,
    pub enabled: bool,
    pub last_synced_at: Option<String>,
}

#[derive(Serialize, ToSchema)]
pub struct ReadingPlanReleaseCandidate {
    pub thread_id: i32,
    pub thread_title: String,
    pub mapping_state: String,
    pub external_identity_id: Option<i32>,
    pub provider_volume_id: Option<String>,
    pub provider_title: Option<String>,
    pub provider_publisher: Option<String>,
    pub provider_start_year: Option<i32>,
    pub provider_issue_count: Option<i32>,
    pub mapping_status: Option<String>,
    pub enableable: bool,
    pub followed: bool,
}

/// Database row for a continuity plan.
#[derive(Debug)]
struct ContinuityPlanRow {
    id: i32,
    name: String,
    #[allow(dead_code)]
    ordering_mode: String,
    #[allow(dead_code)]
    lanes_json: String,
}

/// Database row for a reading plan source.
#[derive(Debug)]
struct ReadingPlanSourceRow {
    id: i32,
    raw_source_path: String,
    repository: Option<String>,
    source_path: Option<String>,
    revision_sha: Option<String>,
    content_hash: Option<String>,
    custom_cbl_list_id: Option<i32>,
    adopted_at: Option<String>,
    recorded_at: String,
}

/// Database row for a custom CBL list entry.
#[derive(Debug, Default)]
struct CustomCBLEntryRow {
    id: i32,
    position: i32,
    issue_id: i32,
    thread_id: i32,
    thread_title: String,
    issue_number: String,
    status: String,
    is_checkpoint: bool,
    #[allow(dead_code)]
    gate: String,
    #[allow(dead_code)]
    skipped: bool,
    #[allow(dead_code)]
    checkpoint_target_issue_ids: Vec<i32>,
}

/// Database row for a release source.
#[derive(Debug)]
struct ReleaseSourceRow {
    id: i32,
    thread_id: i32,
    external_identity_id: i32,
    provider_volume_id: String,
    provider_title: Option<String>,
    provider_publisher: Option<String>,
    provider_start_year: Option<i32>,
    provider_issue_count: Option<i32>,
    enabled: bool,
    last_synced_at: Option<String>,
}

/// Database row for a release candidate.
#[derive(Debug)]
struct ReleaseCandidateRow {
    thread_id: i32,
    thread_title: String,
    mapping_state: String,
    external_identity_id: Option<i32>,
    provider_volume_id: Option<String>,
    provider_title: Option<String>,
    provider_publisher: Option<String>,
    provider_start_year: Option<i32>,
    provider_issue_count: Option<i32>,
    mapping_status: Option<String>,
    enableable: bool,
    followed: bool,
}

/// Load the continuity plan and verify ownership.
async fn load_plan(
    db: &Object,
    user_id: i32,
    plan_id: i32,
) -> Result<Option<ContinuityPlanRow>, ApiError> {
    let rows = db
        .query(
            "SELECT id, name, ordering_mode, lanes_json FROM continuity_plans WHERE id = $1 AND user_id = $2",
            &[&plan_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;

    if rows.is_empty() {
        return Ok(None);
    }

    let row = &rows[0];
    Ok(Some(ContinuityPlanRow {
        id: row.get(0),
        name: row.get(1),
        ordering_mode: row.get(2),
        lanes_json: row.get(3),
    }))
}

/// Load reading plan sources and extract the linked custom CBL list ID.
async fn load_linked_list_id(db: &Object, plan_id: i32) -> Result<Option<i32>, ApiError> {
    let rows = db
        .query(
            "SELECT custom_cbl_list_id FROM reading_plan_sources WHERE plan_id = $1 AND custom_cbl_list_id IS NOT NULL",
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;

    let list_ids: Vec<i32> = rows.iter().filter_map(|r| r.get(0)).collect();
    Ok(list_ids.first().copied())
}

/// Load custom CBL list entries for a given list.
async fn load_list_entries(db: &Object, list_id: i32) -> Result<Vec<CustomCBLEntryRow>, ApiError> {
    let rows = db
        .query(
            r#"
            SELECT
                e.id, e.position, e.issue_id, e.gate, e.skipped, e.is_checkpoint,
                e.checkpoint_target_issue_ids,
                i.thread_id, i.issue_number, i.status,
                t.title as thread_title
            FROM custom_cbl_entries e
            JOIN issues i ON i.id = e.issue_id
            JOIN threads t ON t.id = i.thread_id
            WHERE e.list_id = $1
            ORDER BY e.position, e.id
            "#,
            &[&list_id],
        )
        .await
        .map_err(db::query_error)?;

    let mut entries = Vec::with_capacity(rows.len());
    for row in rows {
        entries.push(CustomCBLEntryRow {
            id: row.get(0),
            position: row.get(1),
            issue_id: row.get(2),
            gate: row.get(3),
            skipped: row.get(4),
            is_checkpoint: row.get(5),
            checkpoint_target_issue_ids: row.get(6),
            thread_id: row.get(7),
            issue_number: row.get(8),
            status: row.get(9),
            thread_title: row.get(10),
        });
    }
    Ok(entries)
}

/// Load reading plan sources for the response.
async fn load_sources(db: &Object, plan_id: i32) -> Result<Vec<ReadingPlanSourceRow>, ApiError> {
    let rows = db
        .query(
            r#"
            SELECT
                id, raw_source_path, repository, source_path,
                revision_sha, content_hash, custom_cbl_list_id,
                adopted_at, recorded_at
            FROM reading_plan_sources
            WHERE plan_id = $1
            ORDER BY id
            "#,
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;

    let mut sources = Vec::with_capacity(rows.len());
    for row in rows {
        sources.push(ReadingPlanSourceRow {
            id: row.get(0),
            raw_source_path: row.get(1),
            repository: row.get(2),
            source_path: row.get(3),
            revision_sha: row.get(4),
            content_hash: row.get(5),
            custom_cbl_list_id: row.get(6),
            adopted_at: row.get(7),
            recorded_at: row.get(8),
        });
    }
    Ok(sources)
}

/// Load release sources for the response.
async fn load_release_sources(
    db: &Object,
    plan_id: i32,
) -> Result<Vec<ReleaseSourceRow>, ApiError> {
    let rows = db
        .query(
            r#"
            SELECT
                rs.id, rs.thread_id, rs.external_identity_id,
                rs.provider_volume_id, rs.provider_title, rs.provider_publisher,
                rs.provider_start_year, rs.provider_issue_count,
                rs.enabled, rs.last_synced_at
            FROM reading_plan_release_sources rs
            WHERE rs.plan_id = $1
            ORDER BY rs.id
            "#,
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;

    let mut sources = Vec::with_capacity(rows.len());
    for row in rows {
        sources.push(ReleaseSourceRow {
            id: row.get(0),
            thread_id: row.get(1),
            external_identity_id: row.get(2),
            provider_volume_id: row.get(3),
            provider_title: row.get(4),
            provider_publisher: row.get(5),
            provider_start_year: row.get(6),
            provider_issue_count: row.get(7),
            enabled: row.get(8),
            last_synced_at: row.get(9),
        });
    }
    Ok(sources)
}

/// Load release candidates for the response.
async fn load_release_candidates(
    db: &Object,
    plan_id: i32,
) -> Result<Vec<ReleaseCandidateRow>, ApiError> {
    // Get threads in this plan
    let plan_threads = db
        .query(
            r#"
            SELECT DISTINCT i.thread_id, t.title
            FROM reading_plan_issues rpi
            JOIN issues i ON i.id = rpi.issue_id
            JOIN threads t ON t.id = i.thread_id
            WHERE rpi.plan_id = $1
            "#,
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;

    let mut candidates = Vec::new();
    for row in plan_threads {
        let thread_id: i32 = row.get(0);
        let thread_title: String = row.get(1);

        // Check for confirmed series mapping
        let mapping_row = db
            .query_opt(
                r#"
                SELECT e.id, e.external_id, e.metadata_json
                FROM thread_external_series_mappings m
                JOIN external_identities e ON e.id = m.external_identity_id
                WHERE m.thread_id = $1 AND m.status = 'confirmed' AND e.provider = 'comicvine'
                "#,
                &[&thread_id],
            )
            .await
            .map_err(db::query_error)?;

        let (
            mapping_state,
            external_identity_id,
            provider_volume_id,
            provider_title,
            provider_publisher,
            provider_start_year,
            provider_issue_count,
            mapping_status,
            enableable,
            followed,
        ) = if let Some(mapping) = mapping_row {
            // Check if already followed as a release source
            let followed_row = db
                    .query_opt(
                        "SELECT 1 FROM reading_plan_release_sources WHERE plan_id = $1 AND thread_id = $2",
                        &[&plan_id, &thread_id],
                    )
                    .await
                    .map_err(db::query_error)?;
            let followed = followed_row.is_some();

            let metadata_str: Option<String> = mapping.get(2);
            let metadata: Option<serde_json::Value> = metadata_str
                .as_ref()
                .and_then(|s| serde_json::from_str(s).ok());
            let title = metadata
                .as_ref()
                .and_then(|m| m.get("name"))
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            let publisher = metadata
                .as_ref()
                .and_then(|m| m.get("publisher"))
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            let start_year = metadata
                .as_ref()
                .and_then(|m| m.get("start_year"))
                .and_then(|v| v.as_i64())
                .map(|i| i as i32);
            let issue_count = metadata
                .as_ref()
                .and_then(|m| m.get("issue_count"))
                .and_then(|v| v.as_i64())
                .map(|i| i as i32);

            (
                "confirmed",
                Some(mapping.get(0)),
                Some(mapping.get(1)),
                title,
                publisher,
                start_year,
                issue_count,
                Some("confirmed".to_string()),
                !followed,
                followed,
            )
        } else {
            // Check for ambiguous mappings
            let ambiguous_count = db
                    .query_opt(
                        "SELECT count(*) FROM thread_external_series_mappings WHERE thread_id = $1 AND status = 'ambiguous'",
                        &[&thread_id],
                    )
                    .await
                    .map_err(db::query_error)?
                    .map(|r| r.get::<_, i64>(0))
                    .unwrap_or(0);

            if ambiguous_count > 0 {
                (
                    "ambiguous",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    Some("ambiguous".to_string()),
                    false,
                    false,
                )
            } else {
                (
                    "unmapped",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    Some("unmapped".to_string()),
                    false,
                    false,
                )
            }
        };

        candidates.push(ReleaseCandidateRow {
            thread_id,
            thread_title,
            mapping_state: mapping_state.to_string(),
            external_identity_id,
            provider_volume_id,
            provider_title,
            provider_publisher,
            provider_start_year,
            provider_issue_count,
            mapping_status,
            enableable,
            followed,
        });
    }

    Ok(candidates)
}

/// Build the reader response from the evaluated eligibility and list entries.
#[allow(clippy::too_many_arguments)]
fn build_response(
    plan: &ContinuityPlanRow,
    list_id: i32,
    list_mode: &str,
    list_entries: &[CustomCBLEntryRow],
    validated: &ValidatedReadingInputs,
    sources: &[ReadingPlanSourceRow],
    release_sources: &[ReleaseSourceRow],
    release_candidates: &[ReleaseCandidateRow],
) -> Result<ContinuityPlanReaderResponse, ApiError> {
    // Evaluate eligibility using Option E
    let evaluated = evaluate(validated)?;

    // Build issue -> thread mapping and thread labels
    let mut issue_thread_id: HashMap<i32, i32> = HashMap::new();
    let mut issue_number: HashMap<i32, String> = HashMap::new();
    let mut thread_title: HashMap<i32, String> = HashMap::new();
    let mut thread_ids_in_list: HashSet<i32> = HashSet::new();

    for entry in list_entries {
        issue_thread_id.insert(entry.issue_id, entry.thread_id);
        issue_number.insert(entry.issue_id, entry.issue_number.clone());
        thread_title.insert(entry.thread_id, entry.thread_title.clone());
        thread_ids_in_list.insert(entry.thread_id);
    }

    // Also add issues from the validated inputs that might not be in the list
    for issue in &validated.inputs().core.issues {
        issue_thread_id.entry(issue.id).or_insert(issue.thread_id);
        issue_number
            .entry(issue.id)
            .or_insert_with(|| issue.issue_number.clone());
    }

    for thread in &validated.inputs().core.threads {
        thread_title
            .entry(thread.id)
            .or_insert_with(|| thread.title.clone());
    }

    // Build source paths for each entry
    let source_paths: HashMap<i32, Vec<String>> = sources
        .iter()
        .filter(|s| s.custom_cbl_list_id == Some(list_id))
        .map(|s| (s.id, vec![s.raw_source_path.clone()]))
        .collect();

    // Project each list entry to reader issue
    let mut reader_issues: Vec<ContinuityPlanReaderIssue> = Vec::with_capacity(list_entries.len());

    for entry in list_entries {
        let thread_id = entry.thread_id;
        let state = evaluated.get(&thread_id);

        let availability = if entry.status == "read" {
            "read"
        } else if state.is_none() {
            "inactive"
        } else if validated
            .inputs()
            .excluded_issue_ids
            .contains(&entry.issue_id)
        {
            "excluded"
        } else if state.as_ref().and_then(|s| s.next_issue_id) != Some(entry.issue_id) {
            "later"
        } else if state.as_ref().map(|s| s.eligible).unwrap_or(false) {
            "available"
        } else {
            "blocked"
        };

        let blockers = if matches!(availability, "blocked") {
            state
                .map(|s| &s.blockers)
                .unwrap_or(&vec![])
                .iter()
                .filter_map(|b| {
                    if b.waiting_on_issue_ids.is_empty() {
                        return None;
                    }
                    let source_issue_id = b.waiting_on_issue_ids[0];
                    let target_thread_id = *issue_thread_id.get(&source_issue_id)?;
                    Some(ContinuityPlanBlocker {
                        issue_id: source_issue_id,
                        thread_id: target_thread_id,
                        thread_title: thread_title.get(&target_thread_id)?.clone(),
                        issue_number: issue_number.get(&source_issue_id)?.clone(),
                        explanation: format!(
                            "Read {} #{} first",
                            thread_title.get(&target_thread_id)?,
                            issue_number.get(&source_issue_id)?
                        ),
                    })
                })
                .collect()
        } else {
            vec![]
        };

        reader_issues.push(ContinuityPlanReaderIssue {
            occurrence_id: format!("reading-list:{}:{}", list_id, entry.issue_id),
            issue_id: entry.issue_id,
            lane_id: "reading-list".to_string(),
            display_position: entry.position,
            label: None,
            reader_role: None,
            reader_optional: None,
            is_checkpoint: entry.is_checkpoint,
            issue_number: entry.issue_number.clone(),
            thread_id: entry.thread_id,
            thread_title: entry.thread_title.clone(),
            status: entry.status.clone(),
            availability: availability.to_string(),
            blockers,
            source_paths: source_paths.get(&entry.id).cloned().unwrap_or_default(),
        });
    }

    // Build available_now and blocked_next
    let available_now: Vec<ContinuityPlanReaderIssue> = reader_issues
        .iter()
        .filter(|i| i.availability == "available")
        .cloned()
        .collect();

    let blocked_next: Vec<ContinuityPlanReaderIssue> = reader_issues
        .iter()
        .filter(|i| i.availability == "blocked")
        .cloned()
        .collect();

    // Build lanes - single "Reading order" lane for Option E
    let lane = ContinuityPlanReaderLane {
        id: "reading-list".to_string(),
        name: "Reading order".to_string(),
        order: 0,
        issues: reader_issues,
    };

    // Build progress
    let total_issues = list_entries.len() as i32;
    let read_issues = list_entries.iter().filter(|e| e.status == "read").count() as i32;

    // Build sources
    let sources_resp: Vec<ReadingPlanSourceSnapshot> = sources
        .iter()
        .map(|s| ReadingPlanSourceSnapshot {
            id: s.id,
            display_name: None, // Python loads this separately; we keep it simple
            raw_source_path: s.raw_source_path.clone(),
            repository: s.repository.clone(),
            source_path: s.source_path.clone(),
            revision_sha: s.revision_sha.clone(),
            content_hash: s.content_hash.clone(),
            adopted_at: s.adopted_at.clone(),
            recorded_at: s.recorded_at.clone(),
        })
        .collect();

    // Build release sources
    let release_sources_resp: Vec<ReadingPlanReleaseSourceStatus> = release_sources
        .iter()
        .map(|rs| ReadingPlanReleaseSourceStatus {
            source_id: rs.id,
            thread_id: rs.thread_id,
            external_identity_id: rs.external_identity_id,
            provider_volume_id: rs.provider_volume_id.clone(),
            provider_title: rs.provider_title.clone(),
            provider_publisher: rs.provider_publisher.clone(),
            provider_start_year: rs.provider_start_year,
            provider_issue_count: rs.provider_issue_count,
            enabled: rs.enabled,
            last_synced_at: rs.last_synced_at.clone(),
        })
        .collect();

    // Build release candidates
    let release_candidates_resp: Vec<ReadingPlanReleaseCandidate> = release_candidates
        .iter()
        .map(|rc| ReadingPlanReleaseCandidate {
            thread_id: rc.thread_id,
            thread_title: rc.thread_title.clone(),
            mapping_state: rc.mapping_state.clone(),
            external_identity_id: rc.external_identity_id,
            provider_volume_id: rc.provider_volume_id.clone(),
            provider_title: rc.provider_title.clone(),
            provider_publisher: rc.provider_publisher.clone(),
            provider_start_year: rc.provider_start_year,
            provider_issue_count: rc.provider_issue_count,
            mapping_status: rc.mapping_status.clone(),
            enableable: rc.enableable,
            followed: rc.followed,
        })
        .collect();

    Ok(ContinuityPlanReaderResponse {
        execution_mode: "option_e".to_string(),
        plan_id: plan.id,
        name: plan.name.clone(),
        ordering_mode: if list_mode == "strict" {
            "strict_sequential".to_string()
        } else {
            "informational".to_string()
        },
        progress: ReadingPlanProgress {
            total_issues,
            read_issues,
        },
        available_now,
        blocked_next,
        lanes: vec![lane],
        sources: sources_resp,
        release_sources: release_sources_resp,
        release_candidates: release_candidates_resp,
    })
}

/// GET /api/v2/continuity-plans/{plan_id}/reader
pub async fn continuity_plan_reader_v2(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(path): Path<ContinuityPlanReaderPath>,
) -> Result<Json<ContinuityPlanReaderResponse>, ApiError> {
    let user_id = user.id();
    let plan_id = path.plan_id;

    // Checkout connection
    let connection = db::checkout(&state).await?;

    // Load plan and verify ownership
    let plan = load_plan(&connection, user_id, plan_id)
        .await?
        .ok_or_else(|| {
            ApiError(
                StatusCode::NOT_FOUND,
                format!("Continuity plan {plan_id} not found"),
            )
        })?;

    // Load linked custom CBL list ID
    let linked_list_id = load_linked_list_id(&connection, plan_id)
        .await?
        .ok_or_else(|| {
            ApiError(
                StatusCode::CONFLICT,
                "Reading Plan has no linked authoritative Reading List".to_string(),
            )
        })?;

    // Load list entries
    let list_entries = load_list_entries(&connection, linked_list_id).await?;
    let list_mode = {
        let row = connection
            .query_opt(
                "SELECT mode FROM custom_cbl_lists WHERE id = $1",
                &[&linked_list_id],
            )
            .await
            .map_err(db::query_error)?;
        row.map(|r| r.get(0)).unwrap_or_else(|| "loose".to_string())
    };

    // Load sources
    let sources = load_sources(&connection, plan_id).await?;

    // Load release sources
    let release_sources = load_release_sources(&connection, plan_id).await?;

    // Load release candidates
    let release_candidates = load_release_candidates(&connection, plan_id).await?;

    // Load Option E inputs (single SQL statement in repeatable-read transaction)
    let validated = option_inputs::load_option_inputs(&state, user).await?;

    // Build response
    let response = build_response(
        &plan,
        linked_list_id,
        &list_mode,
        &list_entries,
        &validated,
        &sources,
        &release_sources,
        &release_candidates,
    )?;

    Ok(Json(response))
}

/// Documentation-only operation for the mounted v2 continuity plan reader.
#[utoipa::path(
    get,
    path = "/api/v2/continuity-plans/{plan_id}/reader",
    tag = "continuity-plans",
    params(("plan_id" = i32, Path, description = "Owned continuity plan identifier")),
    responses(
        (status = 200, description = "Option E Reading List projection for the continuity plan", body = ContinuityPlanReaderResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Continuity plan not found for this reader"),
        (status = 409, description = "Reading Plan has no linked authoritative Reading List or ambiguous associations"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
fn continuity_plan_reader_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        config::Config,
        reading_inputs::{CoreReadingInputs, ReadingIssue, ReadingThread, StoredThreadEligibility},
    };
    use std::collections::BTreeMap;

    #[test]
    fn ordering_mode_mapping() {
        assert_eq!(
            ContinuityPlanReaderResponse {
                execution_mode: "option_e".into(),
                plan_id: 1,
                name: "Test".into(),
                ordering_mode: "strict_sequential".into(),
                progress: ReadingPlanProgress {
                    total_issues: 0,
                    read_issues: 0
                },
                available_now: vec![],
                blocked_next: vec![],
                lanes: vec![],
                sources: vec![],
                release_sources: vec![],
                release_candidates: vec![],
            }
            .ordering_mode,
            "strict_sequential"
        );
    }
}
