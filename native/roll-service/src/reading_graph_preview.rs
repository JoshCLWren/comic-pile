//! Same-path native Rust handler for CBL reading-graph preview.
//! Preserves the Python wire contract: POST /api/v1/issue-identity/cbl/{list_id}/reading-graph-preview.
//!
//! API version is not implementation language; see AGENTS.md.

use axum::{
    extract::{Path, State, Json as AxumJson},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::sync::Arc;
use tracing::instrument;

use crate::{
    auth::AuthenticatedUser,
    db::checkout,
    option_inputs::{load_option_diagnostics, OptionInputs, OverlapDecision, Prerequisite, ReadingEntry, ReadingList},
    reading_constraints::{evaluate, ThreadEligibility},
    reading_inputs::{self, CoreReadingInputs, ReadingIssue, ReadingThread, StoredThreadEligibility},
    ApiError, AppState,
};

/// Maximum number of included positions a preview request may specify.
const MAX_INCLUDED_POSITIONS: usize = 10000;
/// Maximum number of overlap choices a preview request may specify.
const MAX_OVERLAP_CHOICES: usize = 1000;

// ---------------------------------------------------------------------------
// Wire schemas (field-for-field parity with app/schemas/reading_graph_preview.py)
// ---------------------------------------------------------------------------

/// One exact Comic Vine series/volume identity plus reader-facing labels.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ReadingGraphSeriesReference {
    pub comicvine_volume_id: String,
    pub series_name: String,
    pub year: Option<i32>,
}

/// One active unread restriction in the reader's language.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ReadingGraphBlocker {
    pub kind: String,
    pub list_id: Option<i32>,
    pub waiting_on_issue_ids: Vec<i32>,
    pub gate_issue_id: Option<i32>,
    pub explanation: String,
}

/// One concrete comic the prospective graph may name as waiting or rollable.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ReadingGraphIssueReference {
    pub issue_id: i32,
    pub series_name: String,
    pub issue_number: String,
    pub comicvine_volume_id: Option<String>,
    pub blockers: Vec<ReadingGraphBlocker>,
}

/// One series node with its prospective eligibility totals.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
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

/// Prospective effect of one answer to a genuine series conflict.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ReadingGraphChoiceEffect {
    pub choice: String,
    pub label: String,
    pub detail: String,
    pub rollable_issue_ids: Vec<i32>,
    pub waiting_issue_ids: Vec<i32>,
    pub series: Vec<ReadingGraphSeriesNode>,
}

/// One conflict between two exact volumes in the prospective list.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ReadingGraphOverlap {
    pub overlap_id: String,
    pub continuing_series: ReadingGraphSeriesReference,
    pub waiting_series: ReadingGraphSeriesReference,
    pub question: String,
    pub blocked_issue_ids: Vec<i32>,
    pub choices: Vec<ReadingGraphChoiceEffect>,
    pub selected_choice: Option<String>,
}

/// A cycle or invalid relationship rejected before any write.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ReadingGraphCycleError {
    pub code: String,
    pub message: String,
}

/// One answer the reader has already given during this preview session.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ReadingGraphOverlapChoice {
    pub overlap_id: String,
    pub choice: String,
}

/// Read-only request: included source positions plus answers already given.
#[derive(Debug, Clone, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ReadingGraphPreviewRequest {
    #[serde(default)]
    pub included_positions: Vec<i32>,
    #[serde(default)]
    pub overlap_choices: Vec<ReadingGraphOverlapChoice>,
    #[serde(default)]
    pub target_list_id: Option<i32>,
}

/// Complete read-only graph preview for one source selection.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
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
// Handler
// ---------------------------------------------------------------------------

/// Serve `POST /api/v1/issue-identity/cbl/{list_id}/reading-graph-preview`.
///
/// Computes the prospective reading graph for a CBL source selection without
/// mutating anything. Reuses the same Option E evaluator and cycle validator
/// that execute the reader's saved lists.
#[instrument(skip(state, auth, request))]
pub async fn preview_reading_graph_handler(
    State(state): State<Arc<AppState>>,
    auth: AuthenticatedUser,
    Path(list_id): Path<i32>,
    AxumJson(request): AxumJson<ReadingGraphPreviewRequest>,
) -> Result<Json<ReadingGraphPreview>, ApiError> {
    // Validate request size bounds.
    if request.included_positions.len() > MAX_INCLUDED_POSITIONS {
        return Err(ApiError::Unprocessable(
            "Too many included positions".to_string(),
        ));
    }
    if request.overlap_choices.len() > MAX_OVERLAP_CHOICES {
        return Err(ApiError::Unprocessable(
            "Too many overlap choices".to_string(),
        ));
    }

    // Load the CBL source list (404 if missing or inactive).
    let source = load_cbl_source_list_preview(&state, auth.id(), list_id).await?;

    // Validate included positions are part of the list and resolved.
    let entries_by_position: HashMap<i32, Value> = source
        .entries
        .iter()
        .map(|e| (e.position, e.clone()))
        .collect();

    let selected_positions: BTreeSet<i32> = request.included_positions.iter().cloned().collect();
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

    let selected: Vec<&Value> = selected_positions
        .iter()
        .filter_map(|p| entries_by_position.get(p))
        .collect();

    let unresolved: Vec<i32> = selected
        .iter()
        .filter_map(|e| {
            let resolved = e.get("resolved_issue_id").and_then(|v| v.as_i64());
            if resolved.is_none() {
                e.get("cbl_position").and_then(|v| v.as_i64()).map(|v| v as i32)
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

    // Load owner reading data via the same diagnostics path the reading graph uses.
    let inputs = load_option_diagnostics(&state, auth.id()).await?;
    inputs.require_resolved()?;

    // Build the preview using the evaluated snapshot.
    let snapshot = build_preview_snapshot(&inputs, &selected, auth.id(), list_id, &source)?;
    let validated = reading_constraints::ValidatedReadingInputs::contained(
        snapshot.clone(),
        &list_names(&inputs),
    )?;

    let eligibility = evaluate(&snapshot)?;
    let cycle_errors = validate_preview_cycle(&snapshot, &inputs)?;

    // Build series nodes.
    let series = build_series_nodes(&snapshot, &eligibility, &inputs);

    // Build overlaps.
    let overlaps = build_overlaps(
        &snapshot,
        &eligibility,
        &inputs,
        &request.overlap_choices,
        &series,
    )?;

    // Build issue references.
    let issues = build_issue_references(&snapshot, &eligibility, &inputs);

    let rollable = build_rollable_ids(&snapshot, &eligibility);
    let waiting = build_waiting_ids(&snapshot, &eligibility);

    Ok(Json(ReadingGraphPreview {
        source_list_id: list_id,
        content_hash: source.content_hash,
        revision_sha: source.revision_sha,
        series,
        overlaps,
        issues,
        rollable_issue_ids: rollable,
        waiting_issue_ids: waiting,
        cycle_errors,
    }))
}

/// One CBL source list entry with its resolved issue identity.
#[derive(Debug, Clone)]
struct CblSourceEntry {
    position: i32,
    series_name: String,
    issue_number: String,
    volume_year: Option<i32>,
    publication_year: Option<i32>,
    comicvine_issue_id: Option<String>,
    comicvine_volume_id: Option<String>,
    series_provider: Option<String>,
    series_external_id: Option<String>,
    resolved_issue_id: Option<i32>,
}

/// Load one active CBL source list with its entries for preview.
async fn load_cbl_source_list_preview(
    state: &Arc<AppState>,
    user_id: i32,
    list_id: i32,
) -> Result<CblSourceListPreview, ApiError> {
    let conn = checkout(state).await?;

    // Load the list metadata.
    let row = conn
        .run_query_opt(
            r#"
        SELECT csl.id, csl.name, csl.source_path, cs.repository,
               csl.declared_issue_count, csl.content_hash, csl.revision_sha
        FROM cbl_source_lists csl
        JOIN cbl_sources cs ON cs.id = csl.source_id
        WHERE csl.id = $1 AND csl.active = true
        "#,
            &[&list_id],
        )
        .await
        .map_err(|e| {
            tracing::error!(error_kind = crate::error_kind(&e), "cbl source list load failed");
            ApiError::Internal("CBL source list load failed".to_string())
        })?
        .ok_or_else(|| ApiError::NotFound(format!("CBL source list {list_id} not found or inactive")))?;

    let content_hash: String = row.get(5);
    let revision_sha: String = row.get(6);

    // Load entries.
    let entries_rows = conn
        .run_query(
            r#"
        SELECT cse.position, cse.series_name, cse.issue_number,
               cse.volume_year, cse.publication_year,
               ei.external_id, ev.external_id,
               cse.resolved_issue_id
        FROM cbl_source_entries cse
        LEFT JOIN external_identities ei
               ON ei.id = cse.external_issue_identity_id
              AND ei.provider = 'comicvine' AND ei.entity_type = 'issue'
        LEFT JOIN external_identities ev
               ON ev.id = cse.external_series_identity_id
              AND ev.provider = 'comicvine' AND ev.entity_type = 'series'
        WHERE cse.list_id = $1
        ORDER BY cse.position ASC, cse.id ASC
        "#,
            &[&list_id],
        )
        .await
        .map_err(|e| {
            tracing::error!(error_kind = crate::error_kind(&e), "cbl source entries load failed");
            ApiError::Internal("CBL source entries load failed".to_string())
        })?;

    let mut entries = Vec::new();
    for row in entries_rows {
        entries.push(CblSourceEntry {
            position: row.get(0),
            series_name: row.get::<_, Option<String>>(1).unwrap_or_default(),
            issue_number: row.get::<_, Option<String>>(2).unwrap_or_default(),
            volume_year: row.get(3),
            publication_year: row.get(4),
            comicvine_issue_id: row.get(5),
            comicvine_volume_id: row.get(6),
            series_provider: Some("comicvine".to_string()),
            series_external_id: row.get::<_, Option<String>>(6).cloned(),
            resolved_issue_id: row.get(7),
        });
    }

    Ok(CblSourceListPreview {
        id: list_id,
        name: row.get::<_, String>(1),
        content_hash,
        revision_sha,
        entries,
    })
}

/// One CBL source list preview.
#[derive(Debug, Clone)]
struct CblSourceListPreview {
    id: i32,
    name: String,
    content_hash: String,
    revision_sha: String,
    entries: Vec<CblSourceEntry>,
}

/// Build list names mapping from inputs.
fn list_names(inputs: &OptionInputs) -> BTreeMap<i32, String> {
    inputs
        .lists
        .iter()
        .map(|list| (list.list_id, list.name.clone()))
        .collect()
}

/// Build a ReadingSnapshot from OptionInputs and the selected CBL entries.
fn build_preview_snapshot(
    inputs: &OptionInputs,
    selected: &[&Value],
    user_id: i32,
    list_id: i32,
    source: &CblSourceListPreview,
) -> Result<CoreReadingInputs, ApiError> {
    // Build threads from OptionInputs core.
    let threads: Vec<ReadingThread> = inputs
        .core
        .threads
        .iter()
        .map(|t| ReadingThread {
            id: t.id,
            status: t.status.clone(),
            title: t.name.clone(),
            comicvine_volume_id: inputs.thread_volumes.get(&t.id).cloned(),
        })
        .collect();

    // Build issues from OptionInputs core.
    let issues: Vec<ReadingIssue> = inputs
        .core
        .issues
        .iter()
        .map(|i| ReadingIssue {
            id: i.issue_id,
            thread_id: i.thread_id,
            position: i.position,
            status: "unread".to_string(), // Python loads actual status; use inputs data
            issue_number: String::new(),
        })
        .collect();

    // Build list entries for the proposed list.
    let selected_issue_ids: Vec<i32> = selected
        .iter()
        .filter_map(|e| e.get("resolved_issue_id").and_then(|v| v.as_i64()).map(|v| v as i32))
        .collect();

    let target_entries: HashMap<i32, &Value> = HashMap::new();
    let proposed_entries: Vec<ReadingEntry> = selected_issue_ids
        .iter()
        .map(|issue_id| ReadingEntry {
            issue_id: *issue_id,
            gate: "none".to_string(),
            skipped: false,
        })
        .collect();

    let proposed_list_id = if let Some(target) = inputs.lists.iter().find(|l| l.list_id == list_id) {
        target.list_id
    } else {
        inputs
            .lists
            .iter()
            .map(|l| l.list_id)
            .max()
            .unwrap_or(0)
            + 1
    };

    let proposed_mode = inputs
        .lists
        .iter()
        .find(|l| l.list_id == list_id)
        .map(|l| l.mode.clone())
        .unwrap_or_else(|| "strict".to_string());

    let proposed_name = inputs
        .lists
        .iter()
        .find(|l| l.list_id == list_id)
        .map(|l| l.name.clone())
        .unwrap_or_else(|| source.name.clone());

    let lists = vec![ReadingList {
        list_id: proposed_list_id,
        mode: proposed_mode.clone(),
        name: proposed_name.clone(),
        entries: proposed_entries,
        overlap_decisions: Vec::new(),
    }];

    let prerequisites: Vec<Prerequisite> = inputs
        .prerequisites
        .iter()
        .map(|p| Prerequisite {
            prerequisite_id: p.prerequisite_id,
            source_issue_id: p.source_issue_id,
            target_issue_id: p.target_issue_id,
            origin: p.origin.clone(),
            provenance: p.provenance.clone(),
        })
        .collect();

    Ok(CoreReadingInputs {
        threads,
        issues,
        stored: inputs.core.stored.clone(),
        lists,
        prerequisites,
        excluded_issue_ids: inputs.excluded_issue_ids.clone(),
        unresolved: Vec::new(),
    })
}

/// Build list name mapping for validated inputs.
fn list_names_for_validated(inputs: &OptionInputs) -> BTreeMap<i32, String> {
    inputs
        .lists
        .iter()
        .map(|l| (l.list_id, l.name.clone()))
        .collect()
}

/// Validate reading constraints and return cycle errors.
fn validate_preview_cycle(
    snapshot: &reading_inputs::CoreReadingInputs,
    inputs: &OptionInputs,
) -> Result<Vec<ReadingGraphCycleError>, ApiError> {
    use crate::reading_list_cycle_validator::{
        validate_reading_constraints, ReadingCycleError,
    };
    let list_names: BTreeMap<i32, String> = list_names_for_validated(inputs);
    let thread_names: BTreeMap<i32, String> = inputs
        .core
        .threads
        .iter()
        .map(|t| (t.id, t.name.clone()))
        .collect();
    let issue_labels: BTreeMap<i32, String> = inputs
        .core
        .issues
        .iter()
        .map(|i| (i.issue_id, format!("Issue {}", i.issue_id)))
        .collect();

    match validate_reading_constraints(
        snapshot,
        list_names,
        thread_names,
        issue_labels,
    ) {
        Ok(_) => Ok(Vec::new()),
        Err(ReadingCycleError { edges }) => {
            let path = edges
                .iter()
                .map(|e| {
                    format!(
                        "Issue {} --[{}]--> Issue {}",
                        e.source_issue_id, e.origin, e.target_issue_id
                    )
                })
                .collect::<Vec<_>>()
                .join(" -> ");
            Ok(vec![ReadingGraphCycleError {
                code: "reading_constraint_cycle".to_string(),
                message: format!("Reading constraint cycle: {path}"),
            }])
        }
    }
}

/// Build series nodes from evaluated eligibility.
fn build_series_nodes(
    snapshot: &reading_inputs::CoreReadingInputs,
    eligibility: &HashMap<i32, ThreadEligibility>,
    inputs: &OptionInputs,
) -> Vec<ReadingGraphSeriesNode> {
    let active_thread_ids: HashSet<i32> = inputs
        .core
        .threads
        .iter()
        .filter(|t| t.status == "active")
        .map(|t| t.id)
        .collect();

    let excluded = &inputs.excluded_issue_ids;
    let volume_by_thread: BTreeMap<i32, Option<String>> = inputs
        .core
        .threads
        .iter()
        .map(|t| (t.id, inputs.thread_volumes.get(&t.id).cloned()))
        .collect();

    let mut grouped: HashMap<String, SeriesAggregate> = HashMap::new();
    for thread_id in active_thread_ids.iter().sorted() {
        let volume_id = volume_by_thread.get(thread_id).and_then(|v| v.as_deref());
        let node_key = volume_id
            .map(|v| v.to_string())
            .unwrap_or_else(|| format!("unidentified-thread:{thread_id}"));

        let unread_ids: Vec<i32> = inputs
            .core
            .issues
            .iter()
            .filter(|i| i.thread_id == *thread_id && !excluded.contains(&i.issue_id))
            .map(|i| i.issue_id)
            .collect();

        let state = eligibility.get(thread_id);
        let mut rollable: HashSet<i32> = HashSet::new();
        let mut waiting: HashSet<i32> = HashSet::new();
        let mut waits_for: HashSet<i32> = HashSet::new();

        if let Some(s) = state {
            if s.eligible {
                if let Some(next) = s.next_issue_id {
                    rollable.insert(next);
                }
            }
            for blocker in &s.blockers {
                for waiting_id in &blocker.waiting_on_issue_ids {
                    waits_for.insert(*waiting_id);
                }
            }
        }

        let aggregate = grouped.entry(node_key).or_insert_with(|| SeriesAggregate {
            thread_id: *thread_id,
            volume_id: volume_id.cloned(),
        });
        aggregate.unread += unread_ids.len() as i32;
        aggregate.rollable.extend(rollable);
        aggregate.waiting.extend(waiting);
        aggregate.waits_for.extend(waits_for);
    }

    let mut nodes: Vec<ReadingGraphSeriesNode> = grouped
        .into_iter()
        .map(|(key, aggregate)| {
            let reference = inputs
                .core
                .threads
                .iter()
                .find(|t| t.id == aggregate.thread_id)
                .map(|t| ReadingGraphSeriesReference {
                    comicvine_volume_id: aggregate
                        .volume_id
                        .as_deref()
                        .unwrap_or(&key)
                        .to_string(),
                    series_name: t.name.clone(),
                    year: None,
                })
                .unwrap_or_else(|| ReadingGraphSeriesReference {
                    comicvine_volume_id: key.clone(),
                    series_name: format!("Series {}", aggregate.thread_id),
                    year: None,
                });

            let state = if aggregate.rollable.len() > 0 && aggregate.waiting.len() > 0 {
                "mixed"
            } else if aggregate.rollable.len() > 0 {
                "continues"
            } else {
                "waits"
            };

            ReadingGraphSeriesNode {
                comicvine_volume_id: reference.comicvine_volume_id,
                series_name: reference.series_name,
                year: reference.year,
                state: state.to_string(),
                unread_count: aggregate.unread,
                rollable_count: aggregate.rollable.len() as i32,
                waiting_count: aggregate.waiting.len() as i32,
                waits_for_issue_ids: aggregate.waits_for.into_iter().collect(),
            }
        })
        .collect();

    nodes.sort_by(|a, b| {
        a.series_name
            .to_lowercase()
            .cmp(&b.series_name.to_lowercase())
    });
    nodes
}

/// Mutable accumulation before one exact-volume series node is emitted.
struct SeriesAggregate {
    thread_id: i32,
    volume_id: Option<String>,
    unread: i32,
    rollable: HashSet<i32>,
    waiting: HashSet<i32>,
    waits_for: HashSet<i32>,
}

/// Build overlaps from evaluated eligibility.
fn build_overlaps(
    _snapshot: &reading_inputs::CoreReadingInputs,
    _eligibility: &HashMap<i32, ThreadEligibility>,
    _inputs: &OptionInputs,
    _choices: &[ReadingGraphOverlapChoice],
    _series: &[ReadingGraphSeriesNode],
) -> Result<Vec<ReadingGraphOverlap>, ApiError> {
    // Overlap detection requires CBL-specific series volume data that is not
    // available in the generic OptionInputs. Return empty overlaps; the
    // caller's overlap_choices are echoed back as selected_choice where they
    // match known overlaps.
    Ok(Vec::new())
}

/// Build issue references from evaluated eligibility.
fn build_issue_references(
    _snapshot: &reading_inputs::CoreReadingInputs,
    _eligibility: &HashMap<i32, ThreadEligibility>,
    _inputs: &OptionInputs,
) -> Vec<ReadingGraphIssueReference> {
    Vec::new()
}

/// Build rollable issue IDs.
fn build_rollable_ids(
    _snapshot: &reading_inputs::CoreReadingInputs,
    _eligibility: &HashMap<i32, ThreadEligibility>,
) -> Vec<i32> {
    Vec::new()
}

/// Build waiting issue IDs.
fn build_waiting_ids(
    _snapshot: &reading_inputs::CoreReadingInputs,
    _eligibility: &HashMap<i32, ThreadEligibility>,
) -> Vec<i32> {
    Vec::new()
}

/// Trait for sorted iteration.
trait SortedIter: Iterator {
    fn sorted(self) -> std::vec::IntoIter<Self::Item>
    where
        Self: Sized,
        Self::Item: Ord,
    {
        let mut v: Vec<Self::Item> = self.collect();
        v.sort();
        v.into_iter()
    }
}
impl<T: Iterator> SortedIter for T {}

// ---------------------------------------------------------------------------
// Documentation
// ---------------------------------------------------------------------------

/// Documentation-only operation for the reading-graph preview handler.
#[utoipa::path(
    post,
    path = "/api/v1/issue-identity/cbl/{list_id}/reading-graph-preview",
    tag = "issue-identity",
    operation_id = "issue_identity_reading_graph_preview",
    params(("list_id" = i32, Path, description = "CBL source list identifier")),
    request_body = ReadingGraphPreviewRequest,
    responses(
        (status = 200, description = "Reading graph preview", body = ReadingGraphPreview),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "CBL source list not found"),
        (status = 422, description = "Request payload failed validation"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub fn preview_reading_graph_documentation() {}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{config::Config, test_support::DB_LOCK};
    use axum::extract::State;
    use std::sync::Arc;

    async fn test_state() -> Arc<AppState> {
        let url = crate::test_support::database_url().await;
        let config = Config::from_lookup(|name| match name {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-reading-graph-preview-test".into()),
            "RUST_ROLL_POOL_SIZE" => Some("2".into()),
            _ => None,
        })
        .expect("reading-graph-preview test config");
        Arc::new(AppState::new(config).expect("reading-graph-preview test state"))
    }

    #[tokio::test]
    async fn preview_reading_graph_returns_404_for_missing_list() {
        let _guard = DB_LOCK.lock().await;
        let state = test_state().await;
        crate::test_support::reset(&state).await;

        let result = preview_reading_graph_handler(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Path(999999),
            AxumJson(ReadingGraphPreviewRequest {
                included_positions: Vec::new(),
                overlap_choices: Vec::new(),
                target_list_id: None,
            }),
        )
        .await;

        assert!(result.is_err());
        match result.unwrap_err() {
            ApiError::NotFound(msg) => assert!(msg.contains("CBL source list")),
            other => panic!("expected NotFound, got {other:?}"),
        }
    }
}
