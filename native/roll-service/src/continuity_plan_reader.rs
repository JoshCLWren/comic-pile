//! Authenticated Continuity Plan Reader v2 resource.
//! Implements GET /api/v2/continuity-plans/{plan_id}/reader
//!
//! Returns the Option E Reading List projection for a plan with a linked
//! authoritative Reading List. Fails with 409 if the plan has no linked list
//! or ambiguous associations, matching Python's behavior.

use crate::{
    auth::VerifiedAccessClaims,
    db, option_inputs,
    reading_blocker_projection::describe_blocker_gates,
    reading_constraints::{Blocker, ValidatedReadingInputs},
    reading_eligibility::evaluate,
    ApiError, AppState,
};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use std::{
    collections::{HashMap, HashSet},
    sync::{Arc, OnceLock},
};
use utoipa::ToSchema;

#[derive(Deserialize, ToSchema)]
pub struct ContinuityPlanReaderPath {
    pub plan_id: i32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum ReaderExecutionMode {
    OptionE,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum ReaderOrderingMode {
    StrictSequential,
    Informational,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum ReaderAvailability {
    Read,
    Available,
    Blocked,
    Later,
    Excluded,
    Inactive,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum ReleaseMappingState {
    Confirmed,
    Ambiguous,
    Unmapped,
}

/// Canonical v2 response for the Continuity Plan Reader.
/// Matches Python's ReadingPlanReaderResponse shape for Option E execution mode.
#[derive(Serialize, ToSchema)]
pub struct ContinuityPlanReaderResponse {
    pub execution_mode: ReaderExecutionMode,
    pub plan_id: i32,
    pub name: String,
    pub ordering_mode: ReaderOrderingMode,
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
    pub availability: ReaderAvailability,
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
    pub mapping_state: ReleaseMappingState,
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
#[derive(Debug, Deserialize)]
struct ContinuityPlanRow {
    id: i32,
    name: String,
}

/// Database row for a reading plan source.
#[derive(Debug, Deserialize)]
struct ReadingPlanSourceRow {
    id: i32,
    raw_source_path: String,
    display_name: Option<String>,
    repository: Option<String>,
    source_path: Option<String>,
    revision_sha: Option<String>,
    content_hash: Option<String>,
    adopted_at: Option<String>,
    recorded_at: String,
}

/// Database row for a custom CBL list entry.
#[derive(Debug, Default, Deserialize)]
struct CustomCBLEntryRow {
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
#[derive(Debug, Deserialize)]
struct ReleaseSourceRow {
    id: i32,
    thread_id: i32,
    external_identity_id: i32,
    provider_volume_id: String,
    metadata_json: Option<serde_json::Value>,
    enabled: bool,
    last_synced_at: Option<String>,
}

/// Database row for a release candidate.
#[derive(Debug, Deserialize)]
struct ReleaseCandidateRow {
    thread_id: i32,
    thread_title: String,
    mapping_state: ReleaseMappingState,
    metadata_json: Option<serde_json::Value>,
    external_identity_id: Option<i32>,
    provider_volume_id: Option<String>,
    mapping_status: Option<String>,
    enableable: bool,
    followed: bool,
}

#[derive(Deserialize)]
struct ReaderAuthRow {
    id: i32,
    password_epoch: i64,
    revoked: bool,
}

#[derive(Deserialize)]
struct ReaderSqlSnapshot {
    auth: Option<ReaderAuthRow>,
    plan: Option<ContinuityPlanRow>,
    linked_list_count: i64,
    linked_list_id: Option<i32>,
    list_mode: Option<String>,
    entries: Vec<CustomCBLEntryRow>,
    sources: Vec<ReadingPlanSourceRow>,
    release_sources: Vec<ReleaseSourceRow>,
    release_candidates: Vec<ReleaseCandidateRow>,
    option_e: Option<serde_json::Value>,
}

const READER_SNAPSHOT_SQL: &str = r#"
WITH
reader_auth AS MATERIALIZED (
    SELECT u.id,
           COALESCE(trunc(extract(epoch FROM u.password_changed_at))::bigint, 0)
               AS password_epoch,
           EXISTS (SELECT 1 FROM revoked_tokens r WHERE r.jti = $2) AS revoked
    FROM users u
    WHERE u.username = $1
),
owner AS MATERIALIZED (
    SELECT id FROM reader_auth
    WHERE NOT revoked AND $3 >= password_epoch
),
{option_e_ctes},
reader_plan AS MATERIALIZED (
    SELECT p.id, p.name
    FROM continuity_plans p
    JOIN owner o ON o.id = p.user_id
    WHERE p.id = $4
),
linked_lists AS (
    SELECT DISTINCT s.custom_cbl_list_id AS id
    FROM reading_plan_sources s
    JOIN reader_plan p ON p.id = s.plan_id
    WHERE s.custom_cbl_list_id IS NOT NULL
),
selected_list AS (
    SELECT l.id, l.mode
    FROM custom_cbl_lists l
    JOIN linked_lists x ON x.id = l.id
    JOIN owner o ON o.id = l.user_id
    WHERE (SELECT count(*) FROM linked_lists) = 1
),
reader_entries AS (
    SELECT e.position, e.issue_id, e.gate, e.skipped, e.is_checkpoint,
           e.checkpoint_target_issue_ids,
           i.thread_id, i.issue_number, i.status, t.title AS thread_title
    FROM selected_list l
    JOIN custom_cbl_entries e ON e.list_id = l.id
    JOIN issues i ON i.id = e.issue_id
    JOIN threads t ON t.id = i.thread_id
    JOIN owner o ON o.id = t.user_id
),
reader_sources AS (
    SELECT s.id, s.raw_source_path, source_list.name AS display_name,
           s.repository, s.source_path,
           s.revision_sha, s.content_hash, s.adopted_at, s.recorded_at
    FROM reading_plan_sources s
    JOIN reader_plan p ON p.id = s.plan_id
    LEFT JOIN custom_cbl_lists source_list
      ON source_list.user_id = (SELECT id FROM owner)
     AND source_list.id::numeric = CASE
         WHEN btrim(s.raw_source_path) ~ '^custom-cbl:[0-9]{1,10}$'
          AND substring(btrim(s.raw_source_path) FROM 12)::numeric BETWEEN 1 AND 2147483647
         THEN substring(btrim(s.raw_source_path) FROM 12)::numeric
         ELSE NULL
     END
),
reader_release_sources AS (
    SELECT rs.id, rs.thread_id, rs.external_identity_id,
           e.external_id AS provider_volume_id, e.metadata_json,
           rs.enabled, rs.last_synced_at
    FROM reading_plan_release_sources rs
    JOIN reader_plan p ON p.id = rs.plan_id
    JOIN external_identities e ON e.id = rs.external_identity_id
),
plan_threads AS (
    SELECT i.thread_id, t.title AS thread_title,
           min(rpi.display_position) AS first_position
    FROM reading_plan_issues rpi
    JOIN reader_plan p ON p.id = rpi.plan_id
    JOIN issues i ON i.id = rpi.issue_id
    JOIN threads t ON t.id = i.thread_id
    JOIN owner o ON o.id = t.user_id
    GROUP BY i.thread_id, t.title
),
-- Preserve Python's per-volume candidate cardinality: an already-followed
-- volume must not hide another confirmed mapping for the same thread.
series_mappings AS (
    SELECT m.id AS mapping_id, m.thread_id, m.status,
           e.id AS external_identity_id, e.external_id AS provider_volume_id,
           e.metadata_json
    FROM thread_external_series_mappings m
    JOIN external_identities e ON e.id = m.external_identity_id
    JOIN plan_threads pt ON pt.thread_id = m.thread_id
    WHERE m.status <> 'rejected'
      AND e.provider = 'comicvine'
      AND e.entity_type = 'series'
),
confirmed_threads AS (
    SELECT DISTINCT thread_id
    FROM series_mappings
    WHERE status = 'confirmed'
),
followed_volumes AS (
    SELECT DISTINCT rs.thread_id, rs.external_identity_id
    FROM reading_plan_release_sources rs
    JOIN reader_plan p ON p.id = rs.plan_id
),
release_candidate_rows AS (
    SELECT pt.thread_id, pt.thread_title, pt.first_position, m.mapping_id,
           CASE
               WHEN m.mapping_id IS NULL THEN 'unmapped'
               WHEN ct.thread_id IS NOT NULL THEN 'confirmed'
               ELSE 'ambiguous'
           END AS mapping_state,
           m.external_identity_id, m.provider_volume_id, m.metadata_json,
           m.status AS mapping_status,
           COALESCE(m.status = 'confirmed' AND fv.thread_id IS NULL, FALSE) AS enableable,
           FALSE AS followed
    FROM plan_threads pt
    LEFT JOIN series_mappings m ON m.thread_id = pt.thread_id
    LEFT JOIN confirmed_threads ct ON ct.thread_id = pt.thread_id
    LEFT JOIN followed_volumes fv
      ON fv.thread_id = m.thread_id
     AND fv.external_identity_id = m.external_identity_id
    WHERE m.mapping_id IS NULL
       OR ct.thread_id IS NULL
       OR (m.status = 'confirmed' AND fv.thread_id IS NULL)
)
SELECT jsonb_build_object(
    'auth', (SELECT to_jsonb(a) FROM reader_auth a),
    'plan', (SELECT to_jsonb(p) FROM reader_plan p),
    'linked_list_count', (SELECT count(*) FROM linked_lists),
    'linked_list_id', (SELECT id FROM selected_list),
    'list_mode', (SELECT mode FROM selected_list),
    'entries', COALESCE((SELECT jsonb_agg(to_jsonb(e) ORDER BY e.position, e.issue_id)
                         FROM reader_entries e), '[]'::jsonb),
    'sources', COALESCE((SELECT jsonb_agg(to_jsonb(s) ORDER BY s.id)
                         FROM reader_sources s), '[]'::jsonb),
    'release_sources', COALESCE((SELECT jsonb_agg(to_jsonb(s) ORDER BY s.id)
                                 FROM reader_release_sources s), '[]'::jsonb),
    'release_candidates', COALESCE((SELECT jsonb_agg(to_jsonb(c) ORDER BY c.first_position, c.thread_title, c.mapping_id)
                                    FROM release_candidate_rows c), '[]'::jsonb),
    'option_e', CASE WHEN EXISTS (SELECT 1 FROM reader_plan)
                     THEN {option_e_json}
                     ELSE NULL END
)::text
"#;

fn reader_snapshot_sql() -> &'static str {
    static SQL: OnceLock<String> = OnceLock::new();
    SQL.get_or_init(|| {
        READER_SNAPSHOT_SQL
            .replace("{option_e_ctes}", option_inputs::SNAPSHOT_CTES)
            .replace("{option_e_json}", option_inputs::SNAPSHOT_JSON)
    })
}

async fn load_reader_snapshot(
    state: &AppState,
    claims: &VerifiedAccessClaims,
    plan_id: i32,
) -> Result<ReaderSqlSnapshot, ApiError> {
    let expected_epoch = claims.expected_epoch()?;
    let connection = db::checkout(state).await?;
    let row = db::query_one_optional(
        state,
        connection,
        reader_snapshot_sql(),
        &[&claims.username(), &claims.jti(), &expected_epoch, &plan_id],
    )
    .await?
    .ok_or(ApiError(
        StatusCode::INTERNAL_SERVER_ERROR,
        "Invalid reading snapshot".to_string(),
    ))?;
    let encoded: String = row.try_get(0).map_err(db::query_error)?;
    serde_json::from_str(&encoded).map_err(|error| {
        tracing::error!(%error, "Invalid continuity reader snapshot response");
        ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Invalid reading snapshot".to_string(),
        )
    })
}

/// Match Python's reader-safe provider metadata aliases and number coercion.
fn provider_display_metadata(
    metadata: Option<&serde_json::Value>,
) -> (Option<String>, Option<String>, Option<i32>, Option<i32>) {
    let string = |key: &str| {
        metadata
            .and_then(|value| value.get(key))
            .and_then(serde_json::Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(str::to_owned)
    };
    let integer = |key: &str| {
        metadata.and_then(|value| value.get(key)).and_then(|value| {
            value
                .as_i64()
                .and_then(|value| i32::try_from(value).ok())
                .or_else(|| {
                    value
                        .as_str()
                        .and_then(|value| value.trim().parse::<i32>().ok())
                })
        })
    };
    let title = string("name").or_else(|| string("title"));
    let publisher = string("publisher").or_else(|| {
        metadata
            .and_then(|value| value.get("publisher"))
            .and_then(|value| value.get("name"))
            .and_then(serde_json::Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(str::to_owned)
    });
    (
        title,
        publisher,
        integer("start_year"),
        integer("count_of_issues").or_else(|| integer("issue_count")),
    )
}

fn release_candidate_metadata(
    row: &ReleaseCandidateRow,
) -> (Option<String>, Option<String>, Option<i32>, Option<i32>) {
    provider_display_metadata(row.metadata_json.as_ref())
}

fn release_source_metadata(
    row: &ReleaseSourceRow,
) -> (Option<String>, Option<String>, Option<i32>, Option<i32>) {
    provider_display_metadata(row.metadata_json.as_ref())
}

fn project_reader_blockers(
    blockers: &[Blocker],
    issue_thread_id: &HashMap<i32, i32>,
    issue_number: &HashMap<i32, String>,
    thread_title: &HashMap<i32, String>,
) -> Vec<ContinuityPlanBlocker> {
    describe_blocker_gates(blockers.to_vec())
        .into_iter()
        .flat_map(|gate| gate.described_issue_ids)
        .filter_map(|source_issue_id| {
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

    // Project each list entry to reader issue
    let mut reader_issues: Vec<ContinuityPlanReaderIssue> = Vec::with_capacity(list_entries.len());

    for entry in list_entries {
        let thread_id = entry.thread_id;
        let state = evaluated.get(&thread_id);

        let availability = if entry.status == "read" {
            ReaderAvailability::Read
        } else if state.is_none() {
            ReaderAvailability::Inactive
        } else if validated
            .inputs()
            .excluded_issue_ids
            .contains(&entry.issue_id)
        {
            ReaderAvailability::Excluded
        } else if state.as_ref().and_then(|s| s.next_issue_id) != Some(entry.issue_id) {
            ReaderAvailability::Later
        } else if state.as_ref().map(|s| s.eligible).unwrap_or(false) {
            ReaderAvailability::Available
        } else {
            ReaderAvailability::Blocked
        };

        let blockers = if availability == ReaderAvailability::Blocked {
            state
                .map(|s| {
                    project_reader_blockers(
                        &s.blockers,
                        &issue_thread_id,
                        &issue_number,
                        &thread_title,
                    )
                })
                .unwrap_or_default()
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
            availability,
            blockers,
            source_paths: vec![format!("custom-cbl:{list_id}")],
        });
    }

    // Build available_now and blocked_next
    let available_now: Vec<ContinuityPlanReaderIssue> = reader_issues
        .iter()
        .filter(|i| i.availability == ReaderAvailability::Available)
        .cloned()
        .collect();

    let blocked_next: Vec<ContinuityPlanReaderIssue> = reader_issues
        .iter()
        .filter(|i| i.availability == ReaderAvailability::Blocked)
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
            display_name: s.display_name.clone(),
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
        .map(|rs| {
            let (provider_title, provider_publisher, provider_start_year, provider_issue_count) =
                release_source_metadata(rs);
            ReadingPlanReleaseSourceStatus {
                source_id: rs.id,
                thread_id: rs.thread_id,
                external_identity_id: rs.external_identity_id,
                provider_volume_id: rs.provider_volume_id.clone(),
                provider_title,
                provider_publisher,
                provider_start_year,
                provider_issue_count,
                enabled: rs.enabled,
                last_synced_at: rs.last_synced_at.clone(),
            }
        })
        .collect();

    // Build release candidates
    let release_candidates_resp: Vec<ReadingPlanReleaseCandidate> = release_candidates
        .iter()
        .map(|rc| {
            let (provider_title, provider_publisher, provider_start_year, provider_issue_count) =
                release_candidate_metadata(rc);
            ReadingPlanReleaseCandidate {
                thread_id: rc.thread_id,
                thread_title: rc.thread_title.clone(),
                mapping_state: rc.mapping_state,
                external_identity_id: rc.external_identity_id,
                provider_volume_id: rc.provider_volume_id.clone(),
                provider_title,
                provider_publisher,
                provider_start_year,
                provider_issue_count,
                mapping_status: rc.mapping_status.clone(),
                enableable: rc.enableable,
                followed: rc.followed,
            }
        })
        .collect();

    Ok(ContinuityPlanReaderResponse {
        execution_mode: ReaderExecutionMode::OptionE,
        plan_id: plan.id,
        name: plan.name.clone(),
        ordering_mode: if list_mode == "strict" {
            ReaderOrderingMode::StrictSequential
        } else {
            ReaderOrderingMode::Informational
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
    claims: VerifiedAccessClaims,
    Path(path): Path<ContinuityPlanReaderPath>,
) -> Result<Json<ContinuityPlanReaderResponse>, ApiError> {
    let plan_id = path.plan_id;
    let mut snapshot = load_reader_snapshot(&state, &claims, plan_id).await?;
    let auth = snapshot.auth.take().ok_or(ApiError(
        StatusCode::UNAUTHORIZED,
        "User not found".to_string(),
    ))?;
    let _user = claims.authenticate_statement_result(auth.id, auth.password_epoch, auth.revoked)?;
    let plan = snapshot.plan.ok_or_else(|| {
        ApiError(
            StatusCode::NOT_FOUND,
            format!("Continuity plan {plan_id} not found"),
        )
    })?;
    if snapshot.linked_list_count == 0 {
        return Err(ApiError(
            StatusCode::CONFLICT,
            "Reading Plan has no linked authoritative Reading List".to_string(),
        ));
    }
    if snapshot.linked_list_count != 1 {
        return Err(ApiError(
            StatusCode::CONFLICT,
            "Ambiguous Reading List association".to_string(),
        ));
    }
    let linked_list_id = snapshot.linked_list_id.ok_or(ApiError(
        StatusCode::CONFLICT,
        "Reading Plan has no linked authoritative Reading List".to_string(),
    ))?;
    let list_mode = snapshot.list_mode.ok_or(ApiError(
        StatusCode::CONFLICT,
        "Reading Plan has no linked authoritative Reading List".to_string(),
    ))?;
    let option_e = snapshot.option_e.take().ok_or(ApiError(
        StatusCode::INTERNAL_SERVER_ERROR,
        "Invalid reading snapshot".to_string(),
    ))?;
    let validated = option_inputs::decode_validated_snapshot(&option_e.to_string())?;

    // Build response
    let response = build_response(
        &plan,
        linked_list_id,
        &list_mode,
        &snapshot.entries,
        &validated,
        &snapshot.sources,
        &snapshot.release_sources,
        &snapshot.release_candidates,
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
    use crate::config::Config;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn ordering_mode_mapping() {
        assert_eq!(
            ContinuityPlanReaderResponse {
                execution_mode: ReaderExecutionMode::OptionE,
                plan_id: 1,
                name: "Test".into(),
                ordering_mode: ReaderOrderingMode::StrictSequential,
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
            ReaderOrderingMode::StrictSequential
        );
    }

    #[test]
    fn reader_state_enums_preserve_wire_values() {
        assert_eq!(
            serde_json::to_string(&ReaderExecutionMode::OptionE).unwrap(),
            "\"option_e\""
        );
        assert_eq!(
            serde_json::to_string(&ReaderOrderingMode::StrictSequential).unwrap(),
            "\"strict_sequential\""
        );
        assert_eq!(
            serde_json::to_string(&ReaderAvailability::Available).unwrap(),
            "\"available\""
        );
        assert_eq!(
            serde_json::to_string(&ReleaseMappingState::Confirmed).unwrap(),
            "\"confirmed\""
        );
    }

    #[test]
    fn reader_blockers_include_each_distinct_issue_across_gates() {
        let blockers = vec![
            Blocker {
                kind: "prerequisite".into(),
                list_id: None,
                waiting_on_issue_ids: vec![1, 2],
                gate_issue_id: None,
                prerequisite_id: Some(1),
                origin: Some("reader".into()),
                provenance: vec![],
            },
            Blocker {
                kind: "hold".into(),
                list_id: Some(10),
                waiting_on_issue_ids: vec![2, 3],
                gate_issue_id: None,
                prerequisite_id: None,
                origin: None,
                provenance: vec![],
            },
        ];
        let issue_thread_id = HashMap::from([(1, 10), (2, 20), (3, 30)]);
        let issue_number = HashMap::from([
            (1, "1".to_string()),
            (2, "2".to_string()),
            (3, "3".to_string()),
        ]);
        let thread_title = HashMap::from([
            (10, "First Series".to_string()),
            (20, "Second Series".to_string()),
            (30, "Third Series".to_string()),
        ]);

        let projected =
            project_reader_blockers(&blockers, &issue_thread_id, &issue_number, &thread_title);

        assert_eq!(
            projected
                .iter()
                .map(|blocker| blocker.issue_id)
                .collect::<Vec<_>>(),
            vec![1, 2, 3]
        );
        assert_eq!(projected[1].thread_id, 20);
        assert_eq!(projected[1].thread_title, "Second Series");
        assert_eq!(projected[1].explanation, "Read Second Series #2 first");
    }

    #[test]
    fn reader_snapshot_is_one_authenticated_option_e_statement() {
        let sql = reader_snapshot_sql();
        let normalized = sql.to_ascii_lowercase();
        assert_eq!(sql.matches(';').count(), 0);
        for required in [
            "reader_auth as materialized",
            "from revoked_tokens",
            "password_epoch",
            "reader_plan as materialized",
            "reader_entries as",
            "reader_sources as",
            "release_candidate_rows as",
            "'option_e'",
            "from dependencies",
        ] {
            assert!(normalized.contains(required), "missing {required}");
        }
        assert!(!normalized.contains("load_release_candidates"));
    }

    #[test]
    fn release_candidate_metadata_matches_provider_fields() {
        let row = ReleaseCandidateRow {
            thread_id: 7,
            thread_title: "Reader Thread".into(),
            mapping_state: ReleaseMappingState::Confirmed,
            metadata_json: Some(serde_json::json!({
                "name": "Series",
                "publisher": "Publisher",
                "start_year": 2024,
                "issue_count": 12,
            })),
            external_identity_id: Some(9),
            provider_volume_id: Some("42".into()),
            mapping_status: Some("confirmed".into()),
            enableable: true,
            followed: false,
        };
        assert_eq!(
            release_candidate_metadata(&row),
            (
                Some("Series".into()),
                Some("Publisher".into()),
                Some(2024),
                Some(12)
            )
        );
    }

    #[tokio::test]
    async fn one_statement_reader_uses_migrated_schema_and_returns_option_e_projection() {
        let _ = tracing_subscriber::fmt().with_test_writer().try_init();
        let base = std::env::var("RUST_ROLL_TEST_DATABASE_URL")
            .expect("disposable RUST_ROLL_TEST_DATABASE_URL required; test never skips");
        let (admin, connection) = tokio_postgres::connect(&base, tokio_postgres::NoTls)
            .await
            .expect("disposable Postgres");
        tokio::spawn(async move {
            let _ = connection.await;
        });
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let schema = format!("continuity_reader_{}_{}", std::process::id(), nonce);
        admin
            .batch_execute(&format!("CREATE SCHEMA {schema};"))
            .await
            .unwrap();
        // Clone the migrated test-schema definitions so the fixture adds no app columns.
        let tables = [
            "users",
            "revoked_tokens",
            "threads",
            "issues",
            "custom_cbl_lists",
            "custom_cbl_entries",
            "dependencies",
            "thread_external_series_mappings",
            "external_identities",
            "collection_exclusions",
            "catalog_issues",
            "catalog_series",
            "continuity_plans",
            "reading_plan_issues",
            "reading_plan_sources",
            "reading_plan_release_sources",
            "custom_cbl_overlap_decisions",
        ];
        let clone_tables = tables
            .iter()
            .map(|table| {
                format!("CREATE TABLE {schema}.{table} (LIKE public.{table} INCLUDING ALL);")
            })
            .collect::<String>();
        admin.batch_execute(&clone_tables).await.unwrap();

        let scoped_url = format!("{base}?options=-c%20search_path%3D{schema}");
        let config = Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(scoped_url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some("continuity-reader-test-secret".into()),
            _ => None,
        })
        .unwrap();
        let state = AppState::new(config).unwrap();
        let connection = state.pool.get().await.unwrap();
        connection
            .batch_execute(
                r#"
                INSERT INTO users (id, username, is_admin, created_at)
                VALUES (7, 'reader-fixture', false, now());
                INSERT INTO threads
                    (id, title, format, issues_remaining, queue_position, status,
                     manual_creator_credits, is_test, is_blocked,
                     queue_position_is_manual, created_at, user_id, next_unread_issue_id)
                VALUES
                    (10, 'Fixture Thread', 'comic', 1, 1, 'active', '[]'::json,
                     false, false, false, now(), 7, 100);
                INSERT INTO issues (id, thread_id, issue_number, position, status, created_at)
                VALUES (100, 10, '1', 1, 'unread', now());
                INSERT INTO continuity_plans
                    (id, user_id, name, ordering_mode, nodes_json, lanes_json,
                     created_at, updated_at)
                VALUES (20, 7, 'Fixture Plan', 'strict_sequential', '[]'::json, '[]'::json, now(), now());
                INSERT INTO custom_cbl_lists
                    (id, user_id, name, mode, created_at, updated_at)
                VALUES (30, 7, 'Fixture List', 'strict', now(), now());
                INSERT INTO custom_cbl_entries
                    (id, list_id, issue_id, position, is_checkpoint, created_at)
                VALUES (40, 30, 100, 1, false, now());
                INSERT INTO reading_plan_issues
                    (plan_id, occurrence_id, issue_id, lane_id, display_position, is_checkpoint)
                VALUES (20, 'fixture-occurrence', 100, 'fixture-lane', 1, false);
                INSERT INTO reading_plan_sources
                    (id, plan_id, raw_source_path, custom_cbl_list_id, recorded_at)
                VALUES (50, 20, 'custom-cbl:30', 30, now());
                INSERT INTO external_identities
                    (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
                VALUES (60, 'comicvine', 'series', '42',
                        '{"name":"Fixture Series","publisher":"Fixture Publisher","start_year":2024,"issue_count":12}'::json,
                        now(), now());
                INSERT INTO thread_external_series_mappings
                    (id, thread_id, external_identity_id, status, created_at, updated_at)
                VALUES (70, 10, 60, 'confirmed', now(), now());
                INSERT INTO external_identities
                    (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
                VALUES (61, 'comicvine', 'series', '43',
                        '{"title":"Followed Series","publisher":"Fixture Publisher","start_year":2023,"issue_count":8}'::json,
                        now(), now());
                INSERT INTO reading_plan_release_sources
                    (id, plan_id, thread_id, external_identity_id, enabled, created_at, updated_at)
                VALUES (80, 20, 10, 61, true, now(), now());
                "#,
            )
            .await
            .unwrap();
        drop(connection);

        let claims = VerifiedAccessClaims::for_test("reader-fixture", "fixture-jti", 0);
        let mut snapshot = load_reader_snapshot(&state, &claims, 20).await.unwrap();
        let auth = snapshot.auth.take().unwrap();
        assert_eq!(
            claims
                .authenticate_statement_result(auth.id, auth.password_epoch, auth.revoked)
                .unwrap()
                .id(),
            7
        );
        let plan = snapshot.plan.take().unwrap();
        assert_eq!(plan.name, "Fixture Plan");
        assert_eq!(snapshot.linked_list_count, 1);
        assert_eq!(snapshot.linked_list_id, Some(30));
        let validated = option_inputs::decode_validated_snapshot(
            &snapshot.option_e.take().unwrap().to_string(),
        )
        .unwrap();
        let response = build_response(
            &plan,
            30,
            snapshot.list_mode.as_deref().unwrap(),
            &snapshot.entries,
            &validated,
            &snapshot.sources,
            &snapshot.release_sources,
            &snapshot.release_candidates,
        )
        .unwrap();
        assert_eq!(response.progress.total_issues, 1);
        assert_eq!(
            response.sources[0].display_name.as_deref(),
            Some("Fixture List")
        );
        assert_eq!(response.available_now.len(), 1);
        assert_eq!(response.available_now[0].issue_id, 100);
        assert_eq!(response.available_now[0].source_paths, ["custom-cbl:30"]);
        assert_eq!(response.release_sources.len(), 1);
        assert_eq!(response.release_sources[0].provider_volume_id, "43");
        assert_eq!(
            response.release_sources[0].provider_title.as_deref(),
            Some("Followed Series")
        );
        assert_eq!(response.release_candidates.len(), 1);
        assert_eq!(
            response.release_candidates[0].mapping_state,
            ReleaseMappingState::Confirmed
        );
        assert_eq!(
            response.release_candidates[0].provider_title.as_deref(),
            Some("Fixture Series")
        );
        // Following another volume in this thread must not hide this one.
        assert!(!response.release_candidates[0].followed);
        assert!(response.release_candidates[0].enableable);

        let connection = state.pool.get().await.unwrap();
        connection
            .batch_execute(
                r#"
                INSERT INTO external_identities
                    (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
                VALUES (62, 'comicvine', 'series', '44',
                        '{"title":"Second Volume","publisher":{"name":"Nested Publisher"},"start_year":"2025","count_of_issues":"17"}'::json,
                        now(), now());
                INSERT INTO thread_external_series_mappings
                    (id, thread_id, external_identity_id, status, created_at, updated_at)
                VALUES (71, 10, 62, 'confirmed', now(), now());
                "#,
            )
            .await
            .unwrap();
        drop(connection);

        // Two confirmed volumes on one thread yield two independently followable candidates.
        let snapshot = load_reader_snapshot(&state, &claims, 20).await.unwrap();
        assert_eq!(
            snapshot
                .release_candidates
                .iter()
                .map(|candidate| candidate.external_identity_id)
                .collect::<Vec<_>>(),
            vec![Some(60), Some(62)]
        );
        assert!(snapshot
            .release_candidates
            .iter()
            .all(|candidate| candidate.enableable && !candidate.followed));
        assert_eq!(
            release_candidate_metadata(&snapshot.release_candidates[1]),
            (
                Some("Second Volume".to_string()),
                Some("Nested Publisher".to_string()),
                Some(2025),
                Some(17)
            )
        );

        let connection = state.pool.get().await.unwrap();
        connection
            .batch_execute(
                r#"
                INSERT INTO reading_plan_release_sources
                    (id, plan_id, thread_id, external_identity_id, enabled, created_at, updated_at)
                VALUES (81, 20, 10, 60, true, now(), now());
                "#,
            )
            .await
            .unwrap();
        drop(connection);
        let snapshot = load_reader_snapshot(&state, &claims, 20).await.unwrap();
        assert_eq!(snapshot.release_candidates.len(), 1);
        assert_eq!(snapshot.release_candidates[0].external_identity_id, Some(62));
        assert!(snapshot.release_candidates[0].enableable);
        // The source metadata may use "name" rather than "title".
        let followed_source = snapshot
            .release_sources
            .iter()
            .find(|source| source.external_identity_id == 60)
            .unwrap();
        assert_eq!(
            release_source_metadata(followed_source).0.as_deref(),
            Some("Fixture Series")
        );

        let connection = state.pool.get().await.unwrap();
        connection
            .batch_execute(
                r#"
                INSERT INTO users (id, username, is_admin, created_at)
                VALUES (8, 'other-fixture', false, now());
                INSERT INTO custom_cbl_lists
                    (id, user_id, name, mode, created_at, updated_at)
                VALUES (31, 7, 'Second Fixture List', 'loose', now(), now());
                INSERT INTO reading_plan_sources
                    (id, plan_id, raw_source_path, custom_cbl_list_id, recorded_at)
                VALUES (51, 20, 'fixture/second.cbl', 31, now());
                INSERT INTO continuity_plans
                    (id, user_id, name, ordering_mode, nodes_json, lanes_json,
                     created_at, updated_at)
                VALUES
                    (21, 8, 'Foreign Plan', 'strict_sequential', '[]'::json, '[]'::json, now(), now()),
                    (22, 7, 'Unlinked Plan', 'strict_sequential', '[]'::json, '[]'::json, now(), now());
                "#,
            )
            .await
            .unwrap();
        drop(connection);
        let ambiguous = load_reader_snapshot(&state, &claims, 20).await.unwrap();
        assert_eq!(ambiguous.linked_list_count, 2);
        assert!(ambiguous.linked_list_id.is_none());
        let unlinked = load_reader_snapshot(&state, &claims, 22).await.unwrap();
        assert_eq!(unlinked.linked_list_count, 0);
        let foreign = load_reader_snapshot(&state, &claims, 21).await.unwrap();
        assert!(foreign.plan.is_none());

        state.pool.close();
        drop(state);
        admin
            .batch_execute(&format!("DROP SCHEMA {schema} CASCADE"))
            .await
            .unwrap();
    }
}
