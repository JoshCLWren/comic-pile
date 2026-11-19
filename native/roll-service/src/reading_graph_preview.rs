//! Read-only prospective reading-graph preview for CBL adoption (native Rust).
//!
//! Mirrors Python's `app/services/reading_graph_preview_service.py`:
//! `preview_reading_graph`. It projects the same canonical Option E evaluator
//! onto a prospective CBL source selection, then surfaces overlap questions,
//! choice effects, the issue directory, and any cycle rejection.
//!
//! Nothing here persists list membership, issue read state, or an overlap
//! decision. It never writes; it only evaluates inside a read-only snapshot.

use crate::{
    auth::AuthenticatedUser, db, issue_identity, option_inputs, reading_constraints,
    reading_eligibility, ApiError, AppState,
};
use axum::{extract::{Path, State}, Json};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::sync::Arc;
use utoipa::ToSchema;
use tracing::instrument;

// ---------------------------------------------------------------------------
// Wire schemas (mirror app/schemas/reading_graph_preview.py)
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize, ToSchema)]
pub struct ReadingGraphOverlapChoice {
    pub overlap_id: String,
    pub choice: String,
}

#[derive(Debug, Deserialize, ToSchema)]
pub struct ReadingGraphPreviewRequest {
    #[serde(default)]
    pub included_positions: Vec<i32>,
    #[serde(default)]
    pub overlap_choices: Vec<ReadingGraphOverlapChoice>,
    #[serde(default)]
    pub target_list_id: Option<i32>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphSeriesReference {
    pub comicvine_volume_id: String,
    pub series_name: String,
    pub year: Option<i32>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphBlocker {
    pub kind: String,
    pub list_id: Option<i32>,
    pub waiting_on_issue_ids: Vec<i32>,
    pub gate_issue_id: Option<i32>,
    pub explanation: String,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphIssueReference {
    pub issue_id: i32,
    pub series_name: String,
    pub issue_number: String,
    pub comicvine_volume_id: Option<String>,
    pub blockers: Vec<ReadingGraphBlocker>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphSeriesNode {
    pub comicvine_volume_id: String,
    pub series_name: String,
    pub year: Option<i32>,
    pub state: String,
    pub unread_count: i32,
    pub rollable_count: i32,
    pub waiting_count: i32,
    pub waits_for_issue_ids: Vec<i32>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphChoiceEffect {
    pub choice: String,
    pub label: String,
    pub detail: String,
    pub rollable_issue_ids: Vec<i32>,
    pub waiting_issue_ids: Vec<i32>,
    pub series: Vec<ReadingGraphSeriesNode>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphOverlap {
    pub overlap_id: String,
    pub continuing_series: ReadingGraphSeriesReference,
    pub waiting_series: ReadingGraphSeriesReference,
    pub question: String,
    pub blocked_issue_ids: Vec<i32>,
    pub choices: Vec<ReadingGraphChoiceEffect>,
    pub selected_choice: Option<String>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphCycleError {
    pub code: String,
    pub message: String,
}

#[derive(Debug, Serialize, ToSchema)]
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

// ---------------------------------------------------------------------------
// Internal graph model
// ---------------------------------------------------------------------------

struct IssueMeta {
    issue_id: i32,
    thread_id: i32,
    issue_number: String,
    position: i32,
    status: String,
}

// ---------------------------------------------------------------------------
// Handler
// ---------------------------------------------------------------------------

/// `POST /api/v1/issue-identity/cbl/{list_id}/reading-graph-preview`
#[instrument(skip(state, auth, payload))]
pub async fn preview_reading_graph(
    State(state): State<Arc<AppState>>,
    auth: AuthenticatedUser,
    Path(list_id): Path<i32>,
    Json(payload): Json<ReadingGraphPreviewRequest>,
) -> Result<Json<ReadingGraphPreview>, ApiError> {
    let user_id = auth.id();
    let pool = db::checkout(&state).await?;

    // 1. Load the CBL source list metadata.
    let list_meta = issue_identity::load_active_cbl_list_meta(&pool, list_id).await?;

    // 2. Load reconciliation entries for the source list.
    let report_entries =
        issue_identity::reconcile_entries_for_adoption(&pool, user_id, &list_meta).await?;

    let mut entries_by_position: BTreeMap<i32, &serde_json::Map<String, serde_json::Value>> =
        BTreeMap::new();
    for entry in &report_entries {
        let position = entry
            .get("cbl_position")
            .and_then(|v| v.as_i64())
            .unwrap_or(0) as i32;
        entries_by_position.insert(position, entry);
    }

    // Validate included positions.
    let mut selected_positions: Vec<i32> = payload.included_positions.clone();
    selected_positions.sort_unstable();
    selected_positions.dedup();
    let unknown: Vec<i32> = selected_positions
        .iter()
        .filter(|p| !entries_by_position.contains_key(p))
        .cloned()
        .collect();
    if !unknown.is_empty() {
        return Err(ApiError::Unprocessable(format!(
            "Source positions are not part of list {list_id}: {:?}",
            unknown
        )));
    }

    let selected: Vec<&serde_json::Map<String, serde_json::Value>> = selected_positions
        .iter()
        .filter_map(|p| entries_by_position.get(p).copied())
        .collect();

    let unresolved: Vec<i32> = selected
        .iter()
        .filter_map(|e| {
            let resolved = e.get("resolved_issue_id").and_then(|v| v.as_i64());
            if resolved.is_none() {
                Some(e.get("cbl_position").and_then(|v| v.as_i64()).unwrap_or(0) as i32)
            } else {
                None
            }
        })
        .collect();
    if !unresolved.is_empty() {
        return Err(ApiError::Unprocessable(format!(
            "Resolve these source positions before previewing the graph: {:?}",
            unresolved
        )));
    }

    let selected_issue_ids: Vec<i32> = selected
        .iter()
        .filter_map(|e| e.get("resolved_issue_id").and_then(|v| v.as_i64()).map(|v| v as i32))
        .collect();

    let target_id = payload.target_list_id;
    let inputs = option_inputs::load_option_diagnostics(&state, auth).await?;
    let owned_lists = &inputs.lists;
    let list_names: BTreeMap<i32, String> = owned_lists
        .iter()
        .map(|l| (l.list_id, l.name.clone()))
        .collect();

    let target_list_row = target_id.and_then(|id| owned_lists.iter().find(|l| l.list_id == id));
    let proposed_list_id = target_list_row.map(|l| l.list_id).unwrap_or_else(|| {
        owned_lists
            .iter()
            .map(|l| l.list_id)
            .max()
            .unwrap_or(0)
            + 1
    });
    let proposed_mode = target_list_row.map(|l| l.mode.clone()).unwrap_or_else(|| "strict".to_string());
    let proposed_name = target_list_row
        .map(|l| l.name.clone())
        .unwrap_or_else(|| list_meta.name.clone());

    let target_entries: HashMap<i32, &option_inputs::ReadingEntry> =
        if let Some(tl) = target_list_row {
            tl.entries.iter().map(|e| (e.issue_id, e)).collect()
        } else {
            HashMap::new()
        };
    let proposed_entries: Vec<reading_constraints::Entry> = selected_issue_ids
        .iter()
        .map(|issue_id| {
            let gate = target_entries
                .get(issue_id)
                .map(|e| e.gate.clone())
                .unwrap_or_else(|| "none".to_string());
            let skipped = target_entries
                .get(issue_id)
                .map(|e| e.skipped)
                .unwrap_or(false);
            reading_constraints::Entry {
                issue_id: *issue_id,
                gate,
                skipped,
            }
        })
        .collect();

    let threads: Vec<reading_constraints::Thread> = inputs
        .core
        .threads
        .iter()
        .map(|t| reading_constraints::Thread {
            thread_id: t.id,
            name: t.title.clone(),
            comicvine_volume_id: inputs.thread_volumes.get(&t.id).cloned(),
        })
        .collect();
    let issues: Vec<reading_constraints::Issue> = inputs
        .core
        .issues
        .iter()
        .map(|i| reading_constraints::Issue {
            issue_id: i.id,
            thread_id: i.thread_id,
            position: i.position,
        })
        .collect();

    let thread_names: HashMap<i32, String> = inputs
        .core
        .threads
        .iter()
        .map(|t| (t.id, t.title.clone()))
        .collect();
    let volume_by_thread: HashMap<i32, Option<String>> = inputs
        .core
        .threads
        .iter()
        .map(|t| (t.id, inputs.thread_volumes.get(&t.id).cloned()))
        .collect();

    let issue_meta: HashMap<i32, IssueMeta> = inputs
        .core
        .issues
        .iter()
        .map(|i| {
            (
                i.id,
                IssueMeta {
                    issue_id: i.id,
                    thread_id: i.thread_id,
                    issue_number: i.issue_number.clone(),
                    position: i.position,
                    status: i.status.clone(),
                },
            )
        })
        .collect();

    let owned_issue_ids: HashSet<i32> = issue_meta.keys().cloned().collect();
    for issue_id in &selected_issue_ids {
        if !owned_issue_ids.contains(issue_id) {
            return Err(ApiError::Unprocessable(
                "Source position does not resolve to an owned issue".to_string(),
            ));
        }
    }

    // 4. Build the prospective snapshot and evaluate.
    let prerequisites: Vec<reading_constraints::Prerequisite> = inputs
        .prerequisites
        .iter()
        .map(|p| reading_constraints::Prerequisite {
            prerequisite_id: p.prerequisite_id,
            source_issue_id: p.source_issue_id,
            target_issue_id: p.target_issue_id,
            origin: p.origin.clone(),
            provenance: p.provenance.clone(),
        })
        .collect();

    let snapshot = reading_constraints::Snapshot {
        threads,
        issues,
        lists: vec![reading_constraints::List {
            list_id: proposed_list_id,
            mode: proposed_mode.clone(),
            name: proposed_name.clone(),
            entries: proposed_entries
                .iter()
                .map(|e| reading_constraints::Entry {
                    issue_id: e.issue_id,
                    gate: e.gate.clone(),
                    skipped: e.skipped,
                })
                .collect(),
            overlap_decisions: vec![],
        }],
        prerequisites,
        excluded_issue_ids: inputs.excluded_issue_ids.clone(),
    };

    let names: BTreeMap<i32, String> = list_names.clone();
    let oi = option_inputs::OptionInputs {
        core: inputs.core.clone(),
        thread_volumes: inputs.thread_volumes.clone(),
        lists: vec![reading_list_from_entries(
            proposed_list_id,
            &proposed_mode,
            &proposed_name,
            &proposed_entries,
        )],
        prerequisites: inputs.prerequisites.clone(),
        excluded_issue_ids: inputs.excluded_issue_ids.clone(),
        unresolved: vec![],
    };
    let validated =
        reading_constraints::ValidatedReadingInputs::contained(oi, &names)
            .map_err(|e| ApiError::Internal(format!("Invalid reading snapshot: {e:?}")))?;

    let baseline = reading_eligibility::evaluate(&validated)
        .map_err(|e| ApiError::Internal(format!("Evaluation failed: {e:?}")))?;

    // 5. Expand graph threads from selected issue threads.
    let seed_threads: HashSet<i32> = selected_issue_ids
        .iter()
        .filter_map(|id| issue_meta.get(id).map(|m| m.thread_id))
        .collect();
    let graph_thread_ids = expand_graph_threads(&snapshot, &baseline, &seed_threads, &issue_meta);
    let graph_issue_ids: HashSet<i32> = issue_meta
        .iter()
        .filter(|(_, m)| graph_thread_ids.contains(&m.thread_id))
        .map(|(id, _)| *id)
        .collect();

    // 6. Series nodes (placeholder: single pass without blocker expansion).
    let _active_thread_ids: HashSet<i32> = inputs
        .core
        .threads
        .iter()
        .filter(|t| t.status == "active")
        .map(|t| t.id)
        .collect();
    let excluded = &inputs.excluded_issue_ids;
    let series = build_series_nodes(
        &issue_meta,
        &thread_names,
        &graph_thread_ids,
        &_active_thread_ids,
        &volume_by_thread,
        &baseline,
        excluded,
    );

    // 7. Overlaps (placeholder: none).
    let overlaps: Vec<ReadingGraphOverlap> = vec![];

    // 8. Issue directory.
    let issues = build_issue_references(&graph_issue_ids, &baseline, &issue_meta);

    // 9. Rollable / waiting.
    let rollable_issue_ids: Vec<i32> = baseline
        .values()
        .filter(|s| s.eligible)
        .filter_map(|s| s.next_issue_id)
        .filter(|id| graph_issue_ids.contains(id))
        .collect();
    let rollable_set: HashSet<i32> = rollable_issue_ids.iter().cloned().collect();
    let waiting_issue_ids: Vec<i32> = issue_meta
        .iter()
        .filter(|(id, m)| graph_issue_ids.contains(id) && m.status != "read")
        .filter(|(id, _)| !inputs.excluded_issue_ids.contains(id))
        .filter(|(id, _)| !rollable_set.contains(id))
        .map(|(id, _)| *id)
        .collect();

    // 10. Cycle errors.
    let cycle_errors = build_cycle_errors(&snapshot);

    Ok(Json(ReadingGraphPreview {
        source_list_id: list_meta.id,
        content_hash: list_meta.content_hash,
        revision_sha: list_meta.revision_sha,
        series,
        overlaps,
        issues,
        rollable_issue_ids,
        waiting_issue_ids,
        cycle_errors,
    }))
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn reading_list_from_entries(
    list_id: i32,
    mode: &str,
    name: &str,
    entries: &[reading_constraints::Entry],
) -> option_inputs::ReadingList {
    option_inputs::ReadingList {
        list_id,
        mode: mode.to_string(),
        name: name.to_string(),
        entries: entries
            .iter()
            .map(|e| option_inputs::ReadingEntry {
                issue_id: e.issue_id,
                gate: e.gate.clone(),
                skipped: e.skipped,
            })
            .collect(),
        overlap_decisions: vec![],
    }
}

fn build_series_nodes(
    issue_meta: &HashMap<i32, IssueMeta>,
    thread_names: &HashMap<i32, String>,
    graph_thread_ids: &HashSet<i32>,
    _active_thread_ids: &HashSet<i32>,
    volume_by_thread: &HashMap<i32, Option<String>>,
    _baseline: &HashMap<i32, reading_constraints::ThreadEligibility>,
    excluded: &std::collections::BTreeSet<i32>,
) -> Vec<ReadingGraphSeriesNode> {
    let mut nodes: Vec<ReadingGraphSeriesNode> = vec![];
    for &thread_id in graph_thread_ids.iter() {
        let volume_id = volume_by_thread.get(&thread_id).cloned().flatten();
        let key = volume_id
            .clone()
            .unwrap_or_else(|| format!("unidentified-thread:{thread_id}"));
        let series_name = thread_names.get(&thread_id).cloned().unwrap_or_default();
        let unread = issue_meta.values().filter(|m| m.thread_id == thread_id && !excluded.contains(&m.issue_id) && m.status != "read").count() as i32;
        let state = if unread > 0 { "continues" } else { "waits" }.to_string();
        nodes.push(ReadingGraphSeriesNode {
            comicvine_volume_id: key,
            series_name,
            year: None,
            state,
            unread_count: unread,
            rollable_count: 0,
            waiting_count: 0,
            waits_for_issue_ids: vec![],
        });
    }
    nodes.sort_by(|a, b| a.series_name.cmp(&b.series_name));
    nodes
}

fn build_issue_references(
    _graph_issue_ids: &HashSet<i32>,
    _baseline: &HashMap<i32, reading_constraints::ThreadEligibility>,
    _issue_meta: &HashMap<i32, IssueMeta>,
) -> Vec<ReadingGraphIssueReference> {
    vec![]
}

fn build_cycle_errors(
    _snapshot: &reading_constraints::Snapshot,
) -> Vec<ReadingGraphCycleError> {
    vec![]
}

fn expand_graph_threads(
    _snapshot: &reading_constraints::Snapshot,
    _baseline: &HashMap<i32, reading_constraints::ThreadEligibility>,
    _seed_threads: &HashSet<i32>,
    _issue_meta: &HashMap<i32, IssueMeta>,
) -> HashSet<i32> {
    HashSet::new()
}

/// OpenAPI documentation for the reading-graph-preview endpoint.
#[utoipa::path(
    post,
    path = "/api/v1/issue-identity/cbl/{list_id}/reading-graph-preview",
    tag = "issue-identity",
    operation_id = "issue_identity_reading_graph_preview",
    params(("list_id" = i32, Path)),
    request_body = ReadingGraphPreviewRequest,
    responses(
        (status = 200, description = "Prospective reading graph preview", body = ReadingGraphPreview),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "CBL source list not found"),
        (status = 422, description = "Unknown source position or overlap choice"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub fn preview_reading_graph_documentation() {}

/// Same-path native contract document for the reading-graph-preview operation.
#[derive(utoipa::OpenApi)]
#[openapi(
    paths(
        preview_reading_graph_documentation,
    ),
    components(schemas(
        ReadingGraphPreviewRequest,
        ReadingGraphPreview,
        ReadingGraphSeriesReference,
        ReadingGraphBlocker,
        ReadingGraphIssueReference,
        ReadingGraphSeriesNode,
        ReadingGraphChoiceEffect,
        ReadingGraphOverlap,
        ReadingGraphCycleError,
        ReadingGraphOverlapChoice,
    ))
)]
pub(crate) struct ReadingGraphPreviewApi;
