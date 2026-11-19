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

#[derive(Debug, Serialize, ToSchema, Clone)]
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

#[derive(Debug, Clone)]
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
    //    All existing owner lists are included; the proposed list (built from
    //    selected positions) replaces any existing list with the same id, or is
    //    appended as a new list.
    let proposed_list_entry: reading_constraints::List = reading_constraints::List {
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
    };

    let mut snapshot_lists: Vec<reading_constraints::List> = inputs
        .lists
        .iter()
        .filter(|l| l.list_id != proposed_list_id)
        .map(|l| reading_constraints::List {
            list_id: l.list_id,
            mode: l.mode.clone(),
            name: l.name.clone(),
            entries: l
                .entries
                .iter()
                .map(|e| reading_constraints::Entry {
                    issue_id: e.issue_id,
                    gate: e.gate.clone(),
                    skipped: e.skipped,
                })
                .collect(),
            overlap_decisions: l
                .overlap_decisions
                .iter()
                .map(|d| reading_constraints::Overlap {
                    continuing_volume_id: d.continuing_volume_id.clone(),
                    waiting_volume_id: d.waiting_volume_id.clone(),
                })
                .collect(),
        })
        .collect();
    snapshot_lists.push(proposed_list_entry);

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
        lists: snapshot_lists,
        prerequisites,
        excluded_issue_ids: inputs.excluded_issue_ids.clone(),
    };

    let names: BTreeMap<i32, String> = list_names.clone();
    let oi_lists: Vec<option_inputs::ReadingList> = snapshot
        .lists
        .iter()
        .map(|l| option_inputs::ReadingList {
            list_id: l.list_id,
            mode: l.mode.clone(),
            name: l.name.clone(),
            entries: l
                .entries
                .iter()
                .map(|e| option_inputs::ReadingEntry {
                    issue_id: e.issue_id,
                    gate: e.gate.clone(),
                    skipped: e.skipped,
                })
                .collect(),
            overlap_decisions: l
                .overlap_decisions
                .iter()
                .map(|d| option_inputs::OverlapDecision {
                    continuing_volume_id: d.continuing_volume_id.clone(),
                    waiting_volume_id: d.waiting_volume_id.clone(),
                })
                .collect(),
        })
        .collect();
    let oi = option_inputs::OptionInputs {
        core: inputs.core.clone(),
        thread_volumes: inputs.thread_volumes.clone(),
        lists: oi_lists,
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
    let graph_thread_ids =
        expand_graph_threads(&snapshot, &baseline, &seed_threads, &issue_meta);
    let graph_issue_ids: HashSet<i32> = issue_meta
        .iter()
        .filter(|(_, m)| graph_thread_ids.contains(&m.thread_id))
        .map(|(id, _)| *id)
        .collect();

    // 6. Series nodes (grouped by exact volume).
    let series = build_series_nodes(
        &issue_meta,
        &thread_names,
        &graph_thread_ids,
        &volume_by_thread,
        &baseline,
        &inputs.excluded_issue_ids,
        &inputs.thread_volumes,
    );

    // 7. Overlaps: strict_order cross-volume conflicts in the proposed list.
    let (overlaps, blocked_by_pair) = build_overlaps(
        &context_for_overlaps(
            &issue_meta,
            &thread_names,
            &volume_by_thread,
            &inputs.thread_volumes,
        ),
        &selected_issue_ids,
        &baseline,
        &volume_by_thread,
        &series_refs_for_volumes(
            &issue_meta,
            &thread_names,
            &volume_by_thread,
            &inputs.thread_volumes,
        ),
        &proposed_list_id,
        &payload.overlap_choices,
    );

    // 8. Issue directory.
    let issues = build_issue_references(
        &graph_issue_ids,
        &baseline,
        &issue_meta,
        &volume_by_thread,
        &series_refs_for_volumes(
            &issue_meta,
            &thread_names,
            &volume_by_thread,
            &inputs.thread_volumes,
        ),
    );

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
    let cycle_errors = build_cycle_errors(&snapshot, &issue_meta, &thread_names, &list_names);

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

fn build_series_nodes(
    issue_meta: &HashMap<i32, IssueMeta>,
    thread_names: &HashMap<i32, String>,
    graph_thread_ids: &HashSet<i32>,
    volume_by_thread: &HashMap<i32, Option<String>>,
    baseline: &HashMap<i32, reading_constraints::ThreadEligibility>,
    excluded: &std::collections::BTreeSet<i32>,
    thread_volumes: &std::collections::BTreeMap<i32, String>,
) -> Vec<ReadingGraphSeriesNode> {
    // Aggregate per exact volume: group all graph threads sharing the same
    // volume key into one series node.
    let mut volume_threads: std::collections::BTreeMap<String, Vec<i32>> =
        std::collections::BTreeMap::new();
    for &thread_id in graph_thread_ids.iter() {
        let volume_id = volume_by_thread
            .get(&thread_id)
            .cloned()
            .flatten()
            .unwrap_or_else(|| format!("unidentified-thread:{thread_id}"));
        volume_threads.entry(volume_id).or_default().push(thread_id);
    }

    let mut nodes: Vec<ReadingGraphSeriesNode> = vec![];
    for (volume_id, thread_ids) in volume_threads {
        let mut unread_count = 0i32;
        let mut rollable_count = 0i32;
        let mut waiting_count = 0i32;
        let mut waits_for: Vec<i32> = vec![];

        for &thread_id in &thread_ids {
            let state = baseline.get(&thread_id);
            let eligible = state.map(|s| s.eligible).unwrap_or(false);
            let next_issue = state.and_then(|s| s.next_issue_id);

            for (_, m) in issue_meta.iter() {
                if m.thread_id != thread_id {
                    continue;
                }
                if excluded.contains(&m.issue_id) || m.status == "read" {
                    continue;
                }
                unread_count += 1;
                if Some(m.issue_id) == next_issue && eligible {
                    rollable_count += 1;
                } else {
                    waiting_count += 1;
                }
            }

            if let Some(s) = state {
                for blocker in &s.blockers {
                    for wid in &blocker.waiting_on_issue_ids {
                        if let Some(wm) = issue_meta.get(wid) {
                            if wm.thread_id == thread_id
                                && !excluded.contains(wid)
                                && wm.status != "read"
                            {
                                waits_for.push(*wid);
                            }
                        }
                    }
                }
            }
        }

        waits_for.sort_unstable();
        waits_for.dedup();

        let series_name = thread_ids
            .iter()
            .filter_map(|tid| thread_names.get(tid))
            .cloned()
            .next()
            .unwrap_or_default();

        let state = if rollable_count > 0 {
            "continues"
        } else if waiting_count > 0 {
            "waits"
        } else {
            "mixed"
        };

        let year = thread_volumes
            .get(&thread_ids[0])
            .and_then(|v| v.split(':').nth(1))
            .and_then(|y| y.parse::<i32>().ok());

        nodes.push(ReadingGraphSeriesNode {
            comicvine_volume_id: volume_id,
            series_name,
            year,
            state: state.to_string(),
            unread_count,
            rollable_count,
            waiting_count,
            waits_for_issue_ids: waits_for,
        });
    }
    nodes.sort_by(|a, b| a.series_name.cmp(&b.series_name));
    nodes
}

struct OverlapContext {
    issue_meta: HashMap<i32, IssueMeta>,
    thread_names: HashMap<i32, String>,
    volume_by_thread: HashMap<i32, Option<String>>,
    series_refs: HashMap<String, ReadingGraphSeriesReference>,
}

fn series_refs_for_volumes(
    issue_meta: &HashMap<i32, IssueMeta>,
    thread_names: &HashMap<i32, String>,
    volume_by_thread: &HashMap<i32, Option<String>>,
    thread_volumes: &std::collections::BTreeMap<i32, String>,
) -> HashMap<String, ReadingGraphSeriesReference> {
    let mut refs: HashMap<String, ReadingGraphSeriesReference> = HashMap::new();
    for (thread_id, volume_opt) in volume_by_thread.iter() {
        let key = volume_opt
            .clone()
            .unwrap_or_else(|| format!("unidentified-thread:{thread_id}"));
        let series_name = thread_names
            .get(thread_id)
            .cloned()
            .unwrap_or_else(|| format!("Series {thread_id}"));
        let year = thread_volumes
            .get(thread_id)
            .and_then(|v| v.split(':').nth(1))
            .and_then(|y| y.parse::<i32>().ok());
        refs.insert(
            key.clone(),
            ReadingGraphSeriesReference {
                comicvine_volume_id: key,
                series_name,
                year,
            },
        );
    }
    refs
}

fn context_for_overlaps(
    _issue_meta: &HashMap<i32, IssueMeta>,
    thread_names: &HashMap<i32, String>,
    volume_by_thread: &HashMap<i32, Option<String>>,
    thread_volumes: &std::collections::BTreeMap<i32, String>,
) -> OverlapContext {
    OverlapContext {
        issue_meta: _issue_meta.clone(),
        thread_names: thread_names.clone(),
        volume_by_thread: volume_by_thread.clone(),
        series_refs: series_refs_for_volumes(
            _issue_meta,
            thread_names,
            volume_by_thread,
            thread_volumes,
        ),
    }
}

fn build_overlaps(
    ctx: &OverlapContext,
    _selected_issue_ids: &[i32],
    baseline: &HashMap<i32, reading_constraints::ThreadEligibility>,
    _volume_by_thread: &HashMap<i32, Option<String>>,
    _series_refs: &HashMap<String, ReadingGraphSeriesReference>,
    proposed_list_id: &i32,
    overlap_choices: &[ReadingGraphOverlapChoice],
) -> (
    Vec<ReadingGraphOverlap>,
    std::collections::HashMap<
        (String, String),
        std::collections::HashSet<i32>,
    >,
) {
    let mut pairs: std::collections::BTreeSet<(String, String)> =
        std::collections::BTreeSet::new();
    let mut blocked_by_pair: std::collections::HashMap<
        (String, String),
        std::collections::HashSet<i32>,
    > = std::collections::HashMap::new();

    // Detect strict_order cross-volume blockers in the proposed list.
    for (_tid, state) in baseline.iter() {
        for blocker in &state.blockers {
            if blocker.kind != "strict_order" {
                continue;
            }
            // Only blockers belonging to the proposed list create overlap questions.
            if blocker.list_id != Some(*proposed_list_id) {
                continue;
            }
            // The continuing thread is the state's own thread.
            let continuing_thread = state.thread_id;
            let continuing_volume = ctx
                .volume_by_thread
                .get(&continuing_thread)
                .cloned()
                .flatten();
            let continuing_key = continuing_volume
                .clone()
                .unwrap_or_else(|| format!("unidentified-thread:{continuing_thread}"));

            for wid in &blocker.waiting_on_issue_ids {
                if let Some(wm) = ctx.issue_meta.get(wid) {
                    let waiting_thread = wm.thread_id;
                    let waiting_volume = ctx
                        .volume_by_thread
                        .get(&waiting_thread)
                        .cloned()
                        .flatten();
                    let waiting_key = waiting_volume
                        .clone()
                        .unwrap_or_else(|| format!("unidentified-thread:{waiting_thread}"));

                    if continuing_key == waiting_key {
                        continue;
                    }

                    let pair = if continuing_key < waiting_key {
                        (continuing_key.clone(), waiting_key.clone())
                    } else {
                        (waiting_key.clone(), continuing_key.clone())
                    };
                    pairs.insert(pair.clone());
                    blocked_by_pair.entry(pair).or_default().insert(*wid);
                }
            }
        }
    }

    // Build chosen map from overlap_choices. We can't reverse opaque IDs, so we
    // match choices to pairs in deterministic order.
    let mut sorted_pairs: Vec<(String, String)> = pairs.into_iter().collect();
    sorted_pairs.sort();
    let mut choice_iter = overlap_choices.iter();

    let mut overlaps: Vec<ReadingGraphOverlap> = vec![];
    for pair in sorted_pairs {
        let (continuing_volume, waiting_volume) = &pair;
        let continuing_ref = ctx
            .series_refs
            .get(continuing_volume)
            .cloned()
            .unwrap_or_else(|| ReadingGraphSeriesReference {
                comicvine_volume_id: continuing_volume.clone(),
                series_name: continuing_volume.clone(),
                year: None,
            });
        let waiting_ref = ctx
            .series_refs
            .get(waiting_volume)
            .cloned()
            .unwrap_or_else(|| ReadingGraphSeriesReference {
                comicvine_volume_id: waiting_volume.clone(),
                series_name: waiting_volume.clone(),
                year: None,
            });

        let selected_choice = choice_iter.next().and_then(|oc| {
            if oc.overlap_id.is_empty() {
                None
            } else {
                Some(oc.choice.clone())
            }
        });

        let continuing_name = continuing_ref.series_name.clone();
        let waiting_name = waiting_ref.series_name.clone();

        overlaps.push(ReadingGraphOverlap {
            overlap_id: format!(
                "overlap-{:x}",
                simple_hash_u64(&format!("{continuing_volume}\0{waiting_volume}"))
            ),
            continuing_series: continuing_ref,
            waiting_series: waiting_ref,
            question: format!(
                "Should {continuing_name} continue while {waiting_name} waits?",
            ),
            blocked_issue_ids: {
                let mut v: Vec<i32> = blocked_by_pair
                    .get(&pair)
                    .cloned()
                    .unwrap_or_default()
                    .into_iter()
                    .collect();
                v.sort_unstable();
                v
            },
            choices: vec![
                ReadingGraphChoiceEffect {
                    choice: "protect_order".to_string(),
                    label: "Keep the full chosen order".to_string(),
                    detail: format!(
                        "{waiting_name} waits for every earlier unread {continuing_name} comic before it continues.",
                    ),
                    rollable_issue_ids: vec![],
                    waiting_issue_ids: vec![],
                    series: vec![],
                },
                ReadingGraphChoiceEffect {
                    choice: "continue_series".to_string(),
                    label: format!(
                        "Let {continuing_name} continue; {waiting_name} waits",
                    ),
                    detail: format!(
                        "Removes the ordering restriction between {continuing_name} and {waiting_name}; other prerequisites and restrictions still apply.",
                    ),
                    rollable_issue_ids: vec![],
                    waiting_issue_ids: vec![],
                    series: vec![],
                },
            ],
            selected_choice,
        });
    }

    (overlaps, blocked_by_pair)
}

fn simple_hash_u64(input: &str) -> u64 {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{Hash, Hasher};
    let mut h = DefaultHasher::new();
    input.hash(&mut h);
    h.finish()
}

fn build_issue_references(
    graph_issue_ids: &HashSet<i32>,
    baseline: &HashMap<i32, reading_constraints::ThreadEligibility>,
    issue_meta: &HashMap<i32, IssueMeta>,
    volume_by_thread: &HashMap<i32, Option<String>>,
    series_refs: &HashMap<String, ReadingGraphSeriesReference>,
) -> Vec<ReadingGraphIssueReference> {
    let mut references: Vec<ReadingGraphIssueReference> = vec![];

    for &issue_id in graph_issue_ids.iter() {
        let meta = match issue_meta.get(&issue_id) {
            Some(m) => m,
            None => continue,
        };
        let series_ref = volume_by_thread
            .get(&meta.thread_id)
            .and_then(|v| v.as_ref())
            .and_then(|v| series_refs.get(v));

        let series_name = series_ref
            .map(|r| r.series_name.clone())
            .unwrap_or_else(|| meta.issue_number.clone());

        let comicvine_volume_id = series_ref.map(|r| r.comicvine_volume_id.clone());

        let mut blockers: Vec<ReadingGraphBlocker> = vec![];
        if let Some(state) = baseline.get(&meta.thread_id) {
            if state.next_issue_id == Some(issue_id) {
                for blocker in &state.blockers {
                    let description = match blocker.kind.as_str() {
                        "prerequisite" => {
                            let origin = blocker.origin.as_deref().unwrap_or("converted");
                            format!(
                                "{} prerequisite",
                                if origin == "reader" { "Reader" } else { "Converted" }
                            )
                        }
                        "strict_order" => "Strict order".to_string(),
                        "hold" => "Hold".to_string(),
                        "after_previous" => "Wait for previous".to_string(),
                        _ => blocker.kind.clone(),
                    };
                    let waiting: Vec<i32> = blocker
                        .waiting_on_issue_ids
                        .iter()
                        .filter(|wid| graph_issue_ids.contains(wid))
                        .cloned()
                        .collect();
                    if !waiting.is_empty() {
                        blockers.push(ReadingGraphBlocker {
                            kind: blocker.kind.clone(),
                            list_id: blocker.list_id,
                            waiting_on_issue_ids: waiting,
                            gate_issue_id: blocker.gate_issue_id,
                            explanation: format!("{description}: waiting on {:?}", waiting),
                        });
                    }
                }
            }
        }

        references.push(ReadingGraphIssueReference {
            issue_id,
            series_name,
            issue_number: meta.issue_number.clone(),
            comicvine_volume_id,
            blockers,
        });
    }

    references.sort_by(|a, b| {
        issue_meta
            .get(&a.issue_id)
            .and_then(|m| issue_meta.get(&b.issue_id).map(|n| (m.position, n.position)))
            .map(|(pa, pb)| pa.cmp(&pb))
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    references
}

fn build_cycle_errors(
    snapshot: &reading_constraints::Snapshot,
    issue_meta: &HashMap<i32, IssueMeta>,
    thread_names: &HashMap<i32, String>,
    list_names: &std::collections::BTreeMap<i32, String>,
) -> Vec<ReadingGraphCycleError> {
    let _ = thread_names;
    let _ = list_names;
    match reading_constraints::validate(snapshot) {
        Ok(_) => vec![],
        Err(reading_constraints::ValidationError::Cycle { edges, .. }) => {
            let issue_label = |issue_id: i32| {
                issue_meta
                    .get(&issue_id)
                    .map(|m| format!("{} #{}", m.issue_number, m.issue_number))
                    .unwrap_or_else(|| format!("Issue {issue_id}"))
            };
            let path: String = edges
                .iter()
                .map(|e| {
                    format!(
                        "{} --[{}]--> {}",
                        issue_label(e.source_issue_id),
                        e.origin,
                        issue_label(e.target_issue_id)
                    )
                })
                .collect::<Vec<_>>()
                .join(" -> ");
            vec![ReadingGraphCycleError {
                code: "reading_constraint_cycle".to_string(),
                message: format!("Reading constraint cycle: {path}"),
            }]
        }
        Err(_) => vec![],
    }
}

fn expand_graph_threads(
    _snapshot: &reading_constraints::Snapshot,
    baseline: &HashMap<i32, reading_constraints::ThreadEligibility>,
    seed_threads: &HashSet<i32>,
    issue_meta: &HashMap<i32, IssueMeta>,
) -> HashSet<i32> {
    let mut thread_ids: HashSet<i32> = seed_threads.clone();
    loop {
        let mut discovered: HashSet<i32> = HashSet::new();
        for &thread_id in &thread_ids {
            if let Some(state) = baseline.get(&thread_id) {
                for blocker in &state.blockers {
                    for wid in &blocker.waiting_on_issue_ids {
                        if let Some(meta) = issue_meta.get(wid) {
                            discovered.insert(meta.thread_id);
                        }
                    }
                }
            }
        }
        let new_threads: HashSet<i32> = discovered.difference(&thread_ids).cloned().collect();
        if new_threads.is_empty() {
            break;
        }
        thread_ids.extend(new_threads);
    }
    thread_ids
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
