//! Owner-scoped Reading Boundaries v2 explanation endpoint.
//! Mirrors Python `app/api/reading_boundary.py::get_reading_boundary_batch_v2`.
use crate::{
    auth::AuthenticatedUser,
    db,
    option_inputs,
    reading_constraints::{ConstraintEdge, EligibleFrontier, ValidatedReadingInputs},
    ApiError, AppState,
};
use axum::{
    extract::{Json, State},
    http::StatusCode,
};
use deadpool_postgres::Object;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::{BTreeMap, BTreeSet, HashMap, HashSet},
    sync::Arc,
    time::Instant,
};
use tokio_postgres::{IsolationLevel, Transaction};

#[derive(Deserialize)]
pub struct ReadingBoundaryBatchRequest {
    pub thread_ids: Vec<i32>,
}

#[derive(Serialize, Clone, Debug)]
pub struct BoundaryReadingList {
    pub list_id: i32,
    pub name: String,
    pub mode: String,
}

#[derive(Serialize, Clone, Debug)]
pub struct BoundaryEditorTarget {
    pub kind: String,
    pub label: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub list_id: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub thread_id: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub issue_id: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub prerequisite_id: Option<i32>,
}

#[derive(Serialize, Clone, Debug)]
pub struct BoundaryIssue {
    pub issue_id: i32,
    pub thread_id: i32,
    pub thread_title: String,
    pub issue_number: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub volume_label: Option<String>,
    pub label: String,
    pub reading_lists: Vec<BoundaryReadingList>,
}

#[derive(Serialize, Clone, Debug)]
pub struct ReadingBoundaryBlocker {
    pub kind: String,
    pub origin: String,
    pub reason: String,
    pub waiting_on: Vec<BoundaryIssue>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub editor: Option<BoundaryEditorTarget>,
}

#[derive(Serialize, Clone, Debug)]
pub struct ReadingBoundaryNext {
    pub issue: BoundaryIssue,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub editor: Option<BoundaryEditorTarget>,
}

#[derive(Serialize, Clone, Debug)]
pub struct ReadingBoundaryExplanationV2 {
    pub thread_id: i32,
    pub state: String,
    pub summary: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub next: Option<ReadingBoundaryNext>,
    pub blockers: Vec<ReadingBoundaryBlocker>,
}

#[derive(Serialize, Clone, Debug)]
pub struct ReadingBoundaryBatchResponseV2 {
    pub threads: BTreeMap<i32, ReadingBoundaryExplanationV2>,
}

/// Load reader-facing labels for owned issues, lists, and prerequisites.
async fn load_boundary_labels_transaction(
    tx: &Transaction<'_>,
    user_id: i32,
    requested_thread_ids: &[i32],
) -> Result<BoundaryShadowLabels, tokio_postgres::Error> {
    let requested_set: HashSet<i32> = requested_thread_ids.iter().copied().collect();
    let thread_ids: HashSet<i32> = requested_set.clone();

    // Load threads with volume labels
    let thread_rows = tx
        .query(
            "SELECT t.id, t.title, t.status FROM threads t WHERE t.user_id = $1",
            &[&user_id],
        )
        .await?;
    let mut thread_labels = HashMap::new();
    let mut thread_volume_labels = HashMap::new();

    for row in &thread_rows {
        let id: i32 = row.try_get(0)?;
        let title: String = row.try_get(1)?;
        let status: String = row.try_get(2)?;
        thread_labels.insert(
            id,
            BoundaryThreadLabels {
                thread_id: id,
                title,
                status,
                volume_label: None,
            },
        );
    }

    // Resolve volume labels (only when unambiguous)
    let volume_rows = tx
        .query(
            "SELECT t.id, e.metadata_json::jsonb->>'name' AS volume_name FROM threads t
             JOIN thread_external_series_mappings m ON m.thread_id = t.id
             JOIN external_identities e ON e.id = m.external_identity_id
             WHERE t.user_id = $1 AND m.status = 'confirmed'
             AND e.provider = 'comicvine' AND e.entity_type = 'series'",
            &[&user_id],
        )
        .await?;
    let mut grouped: HashMap<i32, Vec<String>> = HashMap::new();
    for row in volume_rows {
        let thread_id: i32 = row.try_get(0)?;
        let volume_name: String = row.try_get(1)?;
        grouped.entry(thread_id).or_default().push(volume_name);
    }
    for (thread_id, names) in grouped {
        if names.len() == 1 {
            thread_volume_labels.insert(thread_id, names[0].clone());
        }
    }
    for labels in thread_labels.values_mut() {
        if let Some(volume) = thread_volume_labels.get(&labels.thread_id) {
            labels.volume_label = Some(volume.clone());
        }
    }

    // Load issues for these threads
    let thread_id_list: Vec<i32> = thread_labels.keys().copied().collect();
    let issue_rows = tx
        .query(
            "SELECT i.id, i.thread_id, i.issue_number FROM issues i WHERE i.thread_id = ANY($1) ORDER BY i.thread_id, i.position, i.id",
            &[&thread_id_list],
        )
        .await?;
    let mut issue_labels = HashMap::new();
    let mut issue_reading_lists: HashMap<i32, Vec<BoundaryReadingListMembership>> = HashMap::new();
    for row in issue_rows {
        let issue_id: i32 = row.try_get(0)?;
        let thread_id: i32 = row.try_get(1)?;
        let issue_number: String = row.try_get(2)?;
        let thread = thread_labels.get(&thread_id).unwrap();
        issue_labels.insert(
            issue_id,
            BoundaryIssueLabels {
                issue_id,
                thread_id,
                thread_title: thread.title.clone(),
                issue_number,
                volume_label: thread.volume_label.clone(),
                reading_lists: vec![],
            },
        );
        issue_reading_lists.insert(issue_id, vec![]);
    }

    // Load active reading lists and their entries
    let list_rows = tx
        .query(
            "SELECT id, name, mode FROM custom_cbl_lists WHERE user_id = $1 ORDER BY id",
            &[&user_id],
        )
        .await?;
    let list_ids: Vec<i32> = list_rows.iter().map(|r| r.try_get::<_, i32>(0).unwrap()).collect();
    let mut lists = HashMap::new();
    let mut active_list_ids = HashSet::new();
    if !list_ids.is_empty() {
        let entry_list_ids = tx
            .query(
                "SELECT DISTINCT list_id FROM custom_cbl_entries WHERE list_id = ANY($1)",
                &[&list_ids],
            )
            .await?;
        for row in entry_list_ids {
            active_list_ids.insert(row.try_get(0)?);
        }
    }
    for row in list_rows {
        let id: i32 = row.try_get(0)?;
        if active_list_ids.contains(&id) {
            lists.insert(
                id,
                BoundaryListLabels {
                    list_id: id,
                    name: row.try_get(1)?,
                    mode: row.try_get(2)?,
                },
            );
        }
    }

    // Load list memberships for issues
    if !active_list_ids.is_empty() {
        let entry_rows = tx
            .query(
                "SELECT list_id, issue_id FROM custom_cbl_entries WHERE list_id = ANY($1)",
                &[&active_list_ids.iter().copied().collect::<Vec<_>>()],
            )
            .await?;
        for row in entry_rows {
            let issue_id: i32 = row.try_get(1)?;
            let list_id: i32 = row.try_get(0)?;
            if let Some(list) = lists.get(&list_id) {
                issue_reading_lists
                    .entry(issue_id)
                    .or_default()
                    .push(BoundaryReadingListMembership {
                        list_id: list.list_id,
                        name: list.name.clone(),
                        mode: list.mode.clone(),
                    });
            }
        }
    }
    // Attach memberships to issue labels
    for (issue_id, memberships) in issue_reading_lists {
        if let Some(labels) = issue_labels.get_mut(&issue_id) {
            labels.reading_lists = memberships;
        }
    }

    // Load prerequisites (historical for requested threads)
    let mut prerequisite_rows = vec![];
    if !requested_thread_ids.is_empty() {
        let source_issue = Issue.__table__.alias("boundary_source_issue");
        let target_issue = Issue.__table__.alias("boundary_target_issue");
        let source_thread = Thread.__table__.alias("boundary_source_thread");
        let target_thread = Thread.__table__.alias("boundary_target_thread");

        let outbound = tx
            .query(
                "SELECT d.id, d.source_issue_id, d.target_issue_id, d.origin, d.classification, d.provenance
                 FROM dependencies d
                 JOIN issues si ON si.id = d.source_issue_id
                 JOIN threads st ON st.id = si.thread_id
                 JOIN issues ti ON ti.id = d.target_issue_id
                 JOIN threads tt ON tt.id = ti.thread_id
                 WHERE si.thread_id = ANY($1) AND tt.user_id = $2
                 ORDER BY d.id",
                &[&requested_thread_ids, &user_id],
            )
            .await?;
        let inbound = tx
            .query(
                "SELECT d.id, d.source_issue_id, d.target_issue_id, d.origin, d.classification, d.provenance
                 FROM dependencies d
                 JOIN issues ti ON ti.id = d.target_issue_id
                 JOIN threads tt ON tt.id = ti.thread_id
                 JOIN issues si ON si.id = d.source_issue_id
                 JOIN threads st ON st.id = si.thread_id
                 WHERE ti.thread_id = ANY($1) AND st.user_id = $2
                 ORDER BY d.id",
                &[&requested_thread_ids, &user_id],
            )
            .await?;

        // Deduplicate edges between two requested series
        let mut seen = HashSet::new();
        for row in outbound.into_iter().chain(inbound) {
            let id: i32 = row.try_get(0)?;
            if seen.insert(id) {
                prerequisite_rows.push(row);
            }
        }
    }

    let mut prerequisites = HashMap::new();
    for row in prerequisite_rows {
        let id: i32 = row.try_get(0)?;
        let source: i32 = row.try_get(1)?;
        let target: i32 = row.try_get(2)?;
        let origin: Option<String> = row.try_get(3)?;
        let classification: Option<String> = row.try_get(4)?;
        let provenance: Option<String> = row.try_get(5)?;
        let mut prov = vec![format!(
            "classification:{}",
            classification.as_deref().unwrap_or("None")
        )];
        if let Some(p) = provenance {
            if !p.is_empty() {
                prov.push(p);
            }
        }
        prerequisites.insert(
            id,
            BoundaryPrerequisiteLabels {
                prerequisite_id: id,
                source_issue_id: source,
                target_issue_id: target,
                origin,
                provenance: prov,
            },
        );
    }

    // Index incident edges by thread
    let mut incident_ids: HashMap<i32, Vec<i32>> = HashMap::new();
    for (id, prereq) in &prerequisites {
        let source_thread = issue_labels
            .get(&prereq.source_issue_id)
            .map(|l| l.thread_id);
        let target_thread = issue_labels
            .get(&prereq.target_issue_id)
            .map(|l| l.thread_id);
        if let Some(t) = source_thread {
            incident_ids.entry(t).or_default().push(*id);
        }
        if let Some(t) = target_thread {
            incident_ids.entry(t).or_default().push(*id);
        }
    }
    let mut prerequisite_ids_by_thread = HashMap::new();
    for (thread_id, mut ids) in incident_ids {
        ids.sort();
        prerequisite_ids_by_thread.insert(thread_id, ids);
    }

    Ok(BoundaryShadowLabels {
        threads: thread_labels,
        issues: issue_labels,
        lists,
        prerequisites,
        prerequisite_ids_by_thread,
    })
}

/// Load reader-facing labels for boundary explanations.
async fn load_boundary_labels(
    state: &AppState,
    user: AuthenticatedUser,
    requested_thread_ids: &[i32],
) -> Result<BoundaryShadowLabels, ApiError> {
    let started = Instant::now();
    let mut pending = Pending(Some(db::checkout(state).await?));
    let result = tokio::time::timeout(state.request_timeout, async {
        let tx = pending
            .0
            .as_mut()
            .unwrap()
            .build_transaction()
            .isolation_level(IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await?;
        let labels = load_boundary_labels_transaction(&tx, user.id(), requested_thread_ids).await?;
        tx.rollback().await?;
        Ok::<_, tokio_postgres::Error>(labels)
    })
    .await;
    match result {
        Err(_) => Err(ApiError(
            StatusCode::SERVICE_UNAVAILABLE,
            "Database temporarily unavailable",
        )),
        Ok(Err(error)) => Err(db::query_error(error)),
        Ok(Ok(labels)) => {
            drop(pending.0.take());
            tracing::info!(
                elapsed_us = started.elapsed().as_micros() as u64,
                "boundary labels loaded"
            );
            Ok(labels)
        }
    }
}

struct Pending(Option<Object>);
impl Drop for Pending {
    fn drop(&mut self) {
        if let Some(c) = self.0.take() {
            drop(Object::take(c));
        }
    }
}

#[derive(Debug)]
struct BoundaryThreadLabels {
    thread_id: i32,
    title: String,
    status: String,
    volume_label: Option<String>,
}

#[derive(Debug)]
struct BoundaryReadingListMembership {
    list_id: i32,
    name: String,
    mode: String,
}

#[derive(Debug)]
struct BoundaryIssueLabels {
    issue_id: i32,
    thread_id: i32,
    thread_title: String,
    issue_number: String,
    volume_label: Option<String>,
    reading_lists: Vec<BoundaryReadingListMembership>,
}

#[derive(Debug)]
struct BoundaryListLabels {
    list_id: i32,
    name: String,
    mode: String,
}

#[derive(Debug)]
struct BoundaryPrerequisiteLabels {
    prerequisite_id: i32,
    source_issue_id: i32,
    target_issue_id: i32,
    origin: Option<String>,
    provenance: Vec<String>,
}

#[derive(Debug)]
struct BoundaryShadowLabels {
    threads: HashMap<i32, BoundaryThreadLabels>,
    issues: HashMap<i32, BoundaryIssueLabels>,
    lists: HashMap<i32, BoundaryListLabels>,
    prerequisites: HashMap<i32, BoundaryPrerequisiteLabels>,
    prerequisite_ids_by_thread: HashMap<i32, Vec<i32>>,
}

const KIND_TEXT: &[(&str, &str)] = &[
    ("strict_order", "Strict order"),
    ("hold", "Hold"),
    ("after_previous", "Wait for previous"),
];

const PREREQUISITE_ORIGIN: &[(&str, &str)] = &[
    ("reader", "Reader prerequisite"),
    ("converted", "Converted prerequisite"),
];

fn prerequisite_origin_label(origin: Option<&str>) -> String {
    PREREQUISITE_ORIGIN
        .iter()
        .find(|(k, _)| Some(*k) == origin)
        .map(|(_, v)| (*v).to_string())
        .unwrap_or_else(|| "Historical prerequisite".into())
}

fn list_name(
    snapshot: &ReadingEligibilitySnapshot,
    labels: &BoundaryShadowLabels,
    list_id: Option<i32>,
) -> String {
    if let Some(id) = list_id {
        if let Some(name) = snapshot.list_labels.get(&id) {
            return name.clone();
        }
        if let Some(list) = labels.lists.get(&id) {
            return list.name.clone();
        }
    }
    "Reading List".into()
}

fn blocker_editor(
    snapshot: &ReadingEligibilitySnapshot,
    labels: &BoundaryShadowLabels,
    blocker: &Blocker,
) -> Option<BoundaryEditorTarget> {
    if let Some(list_id) = blocker.list_id {
        return Some(BoundaryEditorTarget {
            kind: "reading_list".into(),
            label: list_name(snapshot, labels, Some(list_id)),
            list_id: Some(list_id),
            thread_id: None,
            issue_id: None,
            prerequisite_id: None,
        });
    }
    let prerequisite_id = blocker.prerequisite_id?;
    let source_id = blocker.waiting_on_issue_ids.first().copied();
    Some(BoundaryEditorTarget {
        kind: "prerequisite".into(),
        label: prerequisite_origin_label(blocker.origin.as_deref()),
        list_id: None,
        thread_id: source_id.and_then(|id| snapshot.issue_thread_ids.get(&id).copied()),
        issue_id: source_id,
        prerequisite_id: Some(prerequisite_id),
    })
}

fn blocker_reason(
    snapshot: &ReadingEligibilitySnapshot,
    labels: &BoundaryShadowLabels,
    blocker: &Blocker,
) -> String {
    let waiting = issue_names(labels, &blocker.waiting_on_issue_ids);
    if blocker.kind == "prerequisite" {
        let origin = prerequisite_origin_label(blocker.origin.as_deref());
        return format!("{origin}: read {waiting} first");
    }
    let list_name = list_name(snapshot, labels, blocker.list_id);
    let kind = KIND_TEXT
        .iter()
        .find(|(k, _)| *k == blocker.kind)
        .map(|(_, v)| *v)
        .unwrap_or("Requirement");
    format!("{kind} in {list_name}: read {waiting} first")
}

fn issue_names(labels: &BoundaryShadowLabels, issue_ids: &[i32]) -> String {
    issue_ids
        .iter()
        .filter_map(|id| labels.issues.get(id))
        .map(|l| l.label.clone())
        .collect::<Vec<_>>()
        .join(", ")
}

fn issue_label(labels: &BoundaryShadowLabels, issue_id: i32) -> BoundaryIssue {
    labels
        .issues
        .get(&issue_id)
        .map(|row| BoundaryIssue {
            issue_id: row.issue_id,
            thread_id: row.thread_id,
            thread_title: row.thread_title.clone(),
            issue_number: row.issue_number.clone(),
            volume_label: row.volume_label.clone(),
            label: format!("{} #{}", row.thread_title.trim(), row.issue_number).trim().into(),
            reading_lists: row
                .reading_lists
                .iter()
                .map(|m| BoundaryReadingList {
                    list_id: m.list_id,
                    name: m.name.clone(),
                    mode: m.mode.clone(),
                })
                .collect(),
        })
        .unwrap_or_else(|| BoundaryIssue {
            issue_id,
            thread_id: 0,
            thread_title: "Unknown series".into(),
            issue_number: "".into(),
            volume_label: None,
            label: format!("Issue {issue_id}"),
            reading_lists: vec![],
        })
}

fn project_blocker(
    snapshot: &ReadingEligibilitySnapshot,
    labels: &BoundaryShadowLabels,
    blocker: &Blocker,
) -> ReadingBoundaryBlocker {
    ReadingBoundaryBlocker {
        kind: blocker.kind.clone(),
        origin: if blocker.list_id.is_some() {
            "reading_list".into()
        } else {
            "reader_prerequisite".into()
        },
        reason: blocker_reason(snapshot, labels, blocker),
        waiting_on: blocker
            .waiting_on_issue_ids
            .iter()
            .map(|id| issue_label(labels, *id))
            .collect(),
        editor: blocker_editor(snapshot, labels, blocker),
    }
}

fn summary(
    title: &str,
    state: Option<&ThreadEligibility>,
    next_issue: Option<&BoundaryIssue>,
    blockers: &[ReadingBoundaryBlocker],
) -> String {
    if state.is_none() {
        return format!("{title} is not currently active.");
    }
    if next_issue.is_none() {
        return format!("{title} has no unread issues.");
    }
    if !blockers.is_empty() {
        return format!(
            "{} is waiting on {} live requirement{}.",
            next_issue.as_ref().unwrap().label,
            blockers.len(),
            if blockers.len() != 1 { "s" } else { "" }
        );
    }
    format!("{} is available next.", next_issue.as_ref().unwrap().label)
}

/// Reader-facing eligibility snapshot (matches Python ReadingEligibilitySnapshot)
#[derive(Debug, Serialize, Deserialize)]
struct ReadingEligibilitySnapshot {
    user_id: i32,
    threads: BTreeMap<i32, ThreadEligibility>,
    queued_thread_ids: BTreeSet<i32>,
    excluded_issue_ids: BTreeSet<i32>,
    unread_counts: BTreeMap<i32, i32>,
    issue_numbers: BTreeMap<i32, String>,
    issue_labels: BTreeMap<i32, String>,
    issue_thread_ids: BTreeMap<i32, i32>,
    list_labels: BTreeMap<i32, String>,
    thread_labels: BTreeMap<i32, String>,
    active_prerequisite_ids: BTreeSet<i32>,
}

#[derive(Debug, Serialize, Deserialize)]
struct ThreadEligibility {
    thread_id: i32,
    next_issue_id: Option<i32>,
    blockers: Vec<Blocker>,
}

#[derive(Debug, Serialize, Deserialize)]
struct Blocker {
    kind: String,
    list_id: Option<i32>,
    waiting_on_issue_ids: Vec<i32>,
    gate_issue_id: Option<i32>,
    prerequisite_id: Option<i32>,
    origin: Option<String>,
    provenance: Vec<String>,
}

fn build_eligibility_snapshot(
    validated: &ValidatedReadingInputs,
    queued_thread_ids: BTreeSet<i32>,
) -> ReadingEligibilitySnapshot {
    let snapshot = option_inputs::Snapshot::from_inputs(validated.inputs(), &BTreeMap::new());
    let edges = ValidatedReadingInputs::constraint_edges(&snapshot).unwrap();
    let excluded = &validated.inputs().excluded_issue_ids;

    // Build blockers per issue
    let mut blockers: HashMap<i32, Vec<Blocker>> = HashMap::new();
    for edge in edges {
        if !excluded.contains(&edge.source_issue_id) {
            blockers
                .entry(edge.target_issue_id)
                .or_default()
                .push(Blocker {
                    kind: edge.origin.clone(),
                    list_id: None, // Will need to parse from origin
                    waiting_on_issue_ids: vec![edge.source_issue_id],
                    gate_issue_id: None,
                    prerequisite_id: edge.prerequisite_origin.as_ref().map(|_| 0).or(None),
                    origin: edge.prerequisite_origin.clone(),
                    provenance: edge.provenance.clone(),
                });
        }
    }

    // We need to properly map edges to blocker kinds
    // For now, this is a simplified version - the full logic would parse the origin string
    // Let's use a simpler approach matching the Python evaluator output

    let snapshot_result = validated.inputs();
    let mut thread_eligibility = BTreeMap::new();

    // Build issue thread mapping
    let issue_thread_ids: BTreeMap<i32, i32> = snapshot_result
        .core
        .issues
        .iter()
        .map(|i| (i.id, i.thread_id))
        .collect();

    // Build volume by issue
    let thread_volumes: BTreeMap<i32, String> = snapshot_result
        .core
        .threads
        .iter()
        .filter_map(|t| t.title.clone().and_then(|n| Some((t.id, n))))
        .collect();
    let volume_by_issue: BTreeMap<i32, Option<String>> = snapshot_result
        .core
        .issues
        .iter()
        .map(|i| {
            (
                i.id,
                snapshot_result
                    .thread_volumes
                    .get(&i.thread_id)
                    .cloned(),
            )
        })
        .collect();

    // Load lists for building blockers properly
    let lists = &snapshot_result.lists;
    let unread: BTreeSet<i32> = snapshot_result
        .core
        .issues
        .iter()
        .filter(|i| i.status != "read" && !excluded.contains(&i.id))
        .map(|i| i.id)
        .collect();

    // Use the same logic as Python to build blockers
    let mut restrictions: HashMap<i32, Vec<Blocker>> = HashMap::new();

    for reading_list in lists {
        let entries: Vec<_> = reading_list
            .entries
            .iter()
            .filter(|e| !e.skipped && !excluded.contains(&e.issue_id))
            .collect();
        let waiting_by_volume: HashMap<&str, HashSet<&str>> = reading_list
            .overlap_decisions
            .iter()
            .fold(HashMap::new(), |mut acc, d| {
                acc.entry(&d.continuing_volume_id)
                    .or_default()
                    .insert(&d.waiting_volume_id);
                acc
            });

        let mut earlier_unread: Vec<i32> = vec![];
        let mut hold_issue_id: Option<i32> = None;
        let mut hold_unread: Vec<i32> = vec![];
        let mut previous: Option<i32> = None;

        for entry in entries {
            let mut current: Vec<Blocker> = vec![];
            if unread.contains(&entry.issue_id) {
                if reading_list.mode == "strict" {
                    let continuing_volume = volume_by_issue.get(&entry.issue_id).cloned();
                    let waiting_volumes = continuing_volume
                        .as_ref()
                        .and_then(|v| waiting_by_volume.get(v.as_str()))
                        .cloned()
                        .unwrap_or_default();
                    let strict_predecessors: Vec<i32> = earlier_unread
                        .iter()
                        .filter(|pred| {
                            volume_by_issue
                                .get(pred)
                                .and_then(|v| v.as_ref())
                                .map(|v| !waiting_volumes.contains(v.as_str()))
                                .unwrap_or(true)
                        })
                        .copied()
                        .collect();
                    if !strict_predecessors.is_empty() {
                        current.push(Blocker {
                            kind: "strict_order".into(),
                            list_id: Some(reading_list.list_id),
                            waiting_on_issue_ids: strict_predecessors,
                            gate_issue_id: None,
                            prerequisite_id: None,
                            origin: None,
                            provenance: vec![],
                        });
                    }
                }
                if !hold_unread.is_empty() {
                    current.push(Blocker {
                        kind: "hold".into(),
                        list_id: Some(reading_list.list_id),
                        waiting_on_issue_ids: hold_unread.clone(),
                        gate_issue_id: hold_issue_id,
                        prerequisite_id: None,
                        origin: None,
                        provenance: vec![],
                    });
                }
                if entry.gate == "hold" && !earlier_unread.is_empty() {
                    current.push(Blocker {
                        kind: "hold".into(),
                        list_id: Some(reading_list.list_id),
                        waiting_on_issue_ids: earlier_unread.clone(),
                        gate_issue_id: Some(entry.issue_id),
                        prerequisite_id: None,
                        origin: None,
                        provenance: vec![],
                    });
                }
                if entry.gate == "after_previous" {
                    if let Some(prev) = previous {
                        if unread.contains(&prev) {
                            current.push(Blocker {
                                kind: "after_previous".into(),
                                list_id: Some(reading_list.list_id),
                                waiting_on_issue_ids: vec![prev],
                                gate_issue_id: Some(entry.issue_id),
                                prerequisite_id: None,
                                origin: None,
                                provenance: vec![],
                            });
                        }
                    }
                }
                if !current.is_empty() {
                    restrictions
                        .entry(entry.issue_id)
                        .or_default()
                        .extend(current);
                }
                earlier_unread.push(entry.issue_id);
            }
            if entry.gate == "hold" {
                hold_issue_id = Some(entry.issue_id);
                hold_unread = earlier_unread.clone();
            }
            previous = Some(entry.issue_id);
        }
    }

    for prerequisite in &snapshot_result.prerequisites {
        if unread.contains(&prerequisite.source_issue_id) {
            restrictions
                .entry(prerequisite.target_issue_id)
                .or_default()
                .push(Blocker {
                    kind: "prerequisite".into(),
                    list_id: None,
                    waiting_on_issue_ids: vec![prerequisite.source_issue_id],
                    gate_issue_id: None,
                    prerequisite_id: Some(prerequisite.prerequisite_id),
                    origin: Some(prerequisite.origin.clone()),
                    provenance: prerequisite.provenance.clone(),
                });
        }
    }

    // Build frontiers
    let mut frontiers: HashMap<i32, &option_inputs::ReadingIssue> = HashMap::new();
    for issue in snapshot_result
        .core
        .issues
        .iter()
        .filter(|i| i.status != "read" && !excluded.contains(&i.id))
    {
        frontiers.entry(issue.thread_id).or_insert(issue);
    }

    for thread in &snapshot_result.core.threads {
        if thread.status != "active" {
            continue;
        }
        let next_issue_id = frontiers.get(&thread.id).map(|i| i.id);
        let blockers = next_issue_id
            .and_then(|id| restrictions.get(&id))
            .cloned()
            .unwrap_or_default();
        thread_eligibility.insert(
            thread.id,
            ThreadEligibility {
                thread_id: thread.id,
                next_issue_id,
                blockers,
            },
        );
    }

    // Build snapshot
    let queued = snapshot_result
        .core
        .stored
        .iter()
        .filter(|s| s.queue_position > 0)
        .map(|s| s.thread_id)
        .collect();

    ReadingEligibilitySnapshot {
        user_id: snapshot_result.core.threads.first().map(|t| 0).unwrap_or(0), // placeholder, not used
        threads: thread_eligibility,
        queued_thread_ids: queued,
        excluded_issue_ids: excluded.clone(),
        unread_counts: BTreeMap::new(),
        issue_numbers: snapshot_result
            .core
            .issues
            .iter()
            .map(|i| (i.id, i.issue_number.clone()))
            .collect(),
        issue_labels: BTreeMap::new(),
        issue_thread_ids,
        list_labels: lists.iter().map(|l| (l.list_id, l.name.clone())).collect(),
        thread_labels: snapshot_result
            .core
            .threads
            .iter()
            .map(|t| (t.id, t.title.clone()))
            .collect(),
        active_prerequisite_ids: snapshot_result
            .prerequisites
            .iter()
            .map(|p| p.prerequisite_id)
            .collect(),
    }
}

fn project_boundary_explanation(
    snapshot: &ReadingEligibilitySnapshot,
    labels: &BoundaryShadowLabels,
    thread_id: i32,
) -> ReadingBoundaryExplanationV2 {
    let thread = labels.threads.get(&thread_id).unwrap();
    let state = snapshot.threads.get(&thread_id);
    let next_issue = state
        .and_then(|s| s.next_issue_id)
        .and_then(|id| labels.issues.get(&id))
        .map(|row| issue_label(labels, row.issue_id));
    let blockers = state
        .map(|s| {
            s.blockers
                .iter()
                .map(|b| project_blocker(snapshot, labels, b))
                .collect()
        })
        .unwrap_or_default();
    let boundary_state = if state.is_none() {
        "unavailable"
    } else if next_issue.is_none() {
        "complete"
    } else if !blockers.is_empty() {
        "blocked"
    } else {
        "available"
    };
    ReadingBoundaryExplanationV2 {
        thread_id,
        state: boundary_state.into(),
        summary: summary(&thread.title, state, next_issue.as_ref(), &blockers),
        next: next_issue.map(|issue| ReadingBoundaryNext {
            issue,
            editor: Some(BoundaryEditorTarget {
                kind: "issue".into(),
                label: issue.label.clone(),
                list_id: None,
                thread_id: Some(issue.thread_id),
                issue_id: Some(issue.issue_id),
                prerequisite_id: None,
            }),
        }),
        blockers,
    }
}

pub async fn get_reading_boundary_batch_v2(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(payload): Json<ReadingBoundaryBatchRequest>,
) -> Result<Json<ReadingBoundaryBatchResponseV2>, ApiError> {
    // Validate request
    if payload.thread_ids.is_empty() || payload.thread_ids.len() > 200 {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "thread_ids must contain 1-200 items",
        ));
    }

    // Load labels for requested threads
    let labels = load_boundary_labels(&state, user, &payload.thread_ids).await?;

    // Verify ownership
    let missing: Vec<i32> = payload
        .thread_ids
        .iter()
        .filter(|id| !labels.threads.contains_key(id))
        .copied()
        .collect();
    if !missing.is_empty() {
        return Err(ApiError(
            StatusCode::NOT_FOUND,
            &format!("Thread {} not found", missing[0]),
        ));
    }

    // Load and validate Option E inputs
    let validated = option_inputs::load_option_inputs(&state, user).await?;

    // Build eligibility snapshot
    let queued_thread_ids: BTreeSet<i32> = validated
        .inputs()
        .core
        .stored
        .iter()
        .filter(|s| s.queue_position > 0)
        .map(|s| s.thread_id)
        .collect();
    let snapshot = build_eligibility_snapshot(&validated, queued_thread_ids);

    // Project explanations for each requested thread
    let mut threads = BTreeMap::new();
    for thread_id in &payload.thread_ids {
        threads.insert(
            *thread_id,
            project_boundary_explanation(&snapshot, &labels, *thread_id),
        );
    }

    Ok(Json(ReadingBoundaryBatchResponseV2 { threads }))
}