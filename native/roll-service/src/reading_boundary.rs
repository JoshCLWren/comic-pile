//! Authenticated Reading Boundaries v2 explanation endpoint.
//! Implements the same contract as Python's POST /api/v2/reading-boundaries.

use crate::{
    auth::AuthenticatedUser, db, option_inputs, reading_constraints::ValidatedReadingInputs,
    ApiError, AppState,
};
use axum::{
    extract::{Json as AxumJson, State},
    http::StatusCode,
    Json,
};
use deadpool_postgres::Object;
use serde::{Deserialize, Serialize};
use std::{
    collections::{HashMap, HashSet},
    sync::Arc,
};

#[derive(Deserialize)]
pub struct ReadingBoundaryBatchRequest {
    pub thread_ids: Vec<i32>,
}

/// Canonical v2 batch bound from `ReadingBoundaryBatchRequest.thread_ids`.
pub const MAX_BATCH_THREAD_IDS: usize = 200;

/// Reject an empty or oversized batch exactly where Pydantic would.
pub fn validate_thread_ids(thread_ids: &[i32]) -> Result<(), ApiError> {
    if thread_ids.is_empty() || thread_ids.len() > MAX_BATCH_THREAD_IDS {
        return Err(ApiError(
            StatusCode::UNPROCESSABLE_ENTITY,
            "thread_ids must contain between 1 and 200 entries".to_string(),
        ));
    }
    Ok(())
}

#[derive(Serialize)]
pub struct BoundaryReadingList {
    pub list_id: i32,
    pub name: String,
    pub mode: String,
}

#[derive(Serialize)]
pub struct BoundaryIssue {
    pub issue_id: i32,
    pub thread_id: i32,
    pub thread_title: String,
    pub issue_number: String,
    pub volume_label: Option<String>,
    pub label: String,
    pub reading_lists: Vec<BoundaryReadingList>,
}

#[derive(Serialize)]
pub struct ReadingBoundaryBlocker {
    pub kind: String,
    pub origin: String,
    pub reason: String,
    pub waiting_on: Vec<BoundaryIssue>,
    pub editor: Option<BoundaryEditorTarget>,
}

#[derive(Serialize)]
pub struct BoundaryEditorTarget {
    pub kind: String,
    pub label: String,
    pub list_id: Option<i32>,
    pub thread_id: Option<i32>,
    pub issue_id: Option<i32>,
    pub prerequisite_id: Option<i32>,
}

#[derive(Serialize)]
pub struct ReadingBoundaryNext {
    pub issue: BoundaryIssue,
    pub editor: Option<BoundaryEditorTarget>,
}

#[derive(Serialize)]
pub struct ReadingBoundaryExplanationV2 {
    pub thread_id: i32,
    pub state: String,
    pub summary: String,
    pub next: Option<ReadingBoundaryNext>,
    pub blockers: Vec<ReadingBoundaryBlocker>,
}

#[derive(Serialize)]
pub struct ReadingBoundaryBatchResponseV2 {
    pub threads: HashMap<i32, ReadingBoundaryExplanationV2>,
}

#[derive(Debug, Serialize)]
struct BoundaryThreadLabels {
    thread_id: i32,
    title: String,
    status: String,
    volume_label: Option<String>,
}

#[derive(Debug, Serialize)]
struct BoundaryIssueLabels {
    issue_id: i32,
    thread_id: i32,
    thread_title: String,
    issue_number: String,
    volume_label: Option<String>,
    reading_lists: Vec<BoundaryReadingListMembership>,
}

#[derive(Debug, Serialize)]
struct BoundaryReadingListMembership {
    list_id: i32,
    name: String,
    mode: String,
}

#[derive(Debug, Serialize)]
struct BoundaryListLabels {
    list_id: i32,
    name: String,
    mode: String,
}

#[derive(Debug, Serialize)]
struct BoundaryPrerequisiteLabels {
    prerequisite_id: i32,
    source_issue_id: i32,
    target_issue_id: i32,
    origin: Option<String>,
    provenance: Vec<String>,
}

#[derive(Debug, Serialize)]
pub struct BoundaryShadowLabels {
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

fn prerequisite_origin_label(origin: Option<&str>) -> String {
    match origin {
        Some("reader") => "Reader prerequisite".to_string(),
        Some("converted") => "Converted prerequisite".to_string(),
        _ => "Historical prerequisite".to_string(),
    }
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
            label: format!("{} #{}", row.thread_title, row.issue_number)
                .trim()
                .to_string(),
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
            thread_title: "Unknown series".to_string(),
            issue_number: "".to_string(),
            volume_label: None,
            label: format!("Issue {issue_id}"),
            reading_lists: vec![],
        })
}

fn issue_names(labels: &BoundaryShadowLabels, issue_ids: &[i32]) -> String {
    issue_ids
        .iter()
        .map(|&id| issue_label(labels, id).label)
        .collect::<Vec<_>>()
        .join(", ")
}

fn list_name(
    snapshot: &ReadingEligibilitySnapshot,
    labels: &BoundaryShadowLabels,
    list_id: Option<i32>,
) -> String {
    list_id
        .and_then(|id| {
            labels
                .lists
                .get(&id)
                .map(|l| l.name.clone())
                .or_else(|| snapshot.list_labels.get(&id).cloned())
        })
        .unwrap_or_else(|| "Reading List".to_string())
}

fn blocker_editor(
    snapshot: &ReadingEligibilitySnapshot,
    labels: &BoundaryShadowLabels,
    blocker: &crate::reading_constraints::Blocker,
) -> Option<BoundaryEditorTarget> {
    if let Some(list_id) = blocker.list_id {
        return Some(BoundaryEditorTarget {
            kind: "reading_list".to_string(),
            label: list_name(snapshot, labels, Some(list_id)),
            list_id: Some(list_id),
            thread_id: None,
            issue_id: None,
            prerequisite_id: None,
        });
    }
    blocker.prerequisite_id?;
    let source_id = blocker.waiting_on_issue_ids.first().copied();
    Some(BoundaryEditorTarget {
        kind: "prerequisite".to_string(),
        label: prerequisite_origin_label(blocker.origin.as_deref()),
        list_id: None,
        thread_id: source_id.and_then(|id| snapshot.issue_thread_ids.get(&id).copied()),
        issue_id: source_id,
        prerequisite_id: blocker.prerequisite_id,
    })
}

fn blocker_reason(
    snapshot: &ReadingEligibilitySnapshot,
    labels: &BoundaryShadowLabels,
    gate: &crate::reading_blocker_projection::DescribedBlockerGate,
) -> String {
    let label = gate_label(snapshot, labels, &gate.blocker);
    if gate.described_issue_ids.is_empty() {
        format!("Also gated by {label}.")
    } else {
        let waiting = issue_names(labels, &gate.described_issue_ids);
        format!("{label}: read {waiting} first")
    }
}

fn gate_label(
    snapshot: &ReadingEligibilitySnapshot,
    labels: &BoundaryShadowLabels,
    blocker: &crate::reading_constraints::Blocker,
) -> String {
    if blocker.kind == "prerequisite" {
        prerequisite_origin_label(blocker.origin.as_deref())
    } else {
        let list_name = list_name(snapshot, labels, blocker.list_id);
        format!(
            "{} in {list_name}",
            KIND_TEXT
                .iter()
                .find(|(k, _)| *k == blocker.kind)
                .map(|(_, v)| *v)
                .unwrap_or(&blocker.kind)
        )
    }
}

fn project_blocker(
    snapshot: &ReadingEligibilitySnapshot,
    labels: &BoundaryShadowLabels,
    gate: &crate::reading_blocker_projection::DescribedBlockerGate,
) -> ReadingBoundaryBlocker {
    let blocker = &gate.blocker;
    ReadingBoundaryBlocker {
        kind: blocker.kind.clone(),
        origin: if blocker.list_id.is_some() {
            "reading_list"
        } else {
            "reader_prerequisite"
        }
        .to_string(),
        reason: blocker_reason(snapshot, labels, gate),
        waiting_on: gate
            .described_issue_ids
            .iter()
            .map(|&id| issue_label(labels, id))
            .collect(),
        editor: blocker_editor(snapshot, labels, blocker),
    }
}

fn summary(
    title: &str,
    state: Option<&crate::reading_constraints::ThreadEligibility>,
    next_issue: Option<&BoundaryIssue>,
    blockers: &[ReadingBoundaryBlocker],
    requirements: usize,
) -> String {
    if state.is_none() {
        return format!("{title} is not currently active.");
    }
    if next_issue.is_none() {
        return format!("{title} has no unread issues.");
    }
    if requirements > 0 {
        return format!(
            "{} is waiting on {} live requirement{}.",
            next_issue.as_ref().unwrap().label,
            requirements,
            if requirements != 1 { "s" } else { "" }
        );
    }
    if !blockers.is_empty() {
        return format!(
            "{} is blocked by an active reading rule.",
            next_issue.as_ref().unwrap().label
        );
    }
    format!("{} is available next.", next_issue.as_ref().unwrap().label)
}

#[derive(Debug, Serialize)]
pub struct ReadingEligibilitySnapshot {
    user_id: i32,
    threads: HashMap<i32, crate::reading_constraints::ThreadEligibility>,
    queued_thread_ids: HashSet<i32>,
    excluded_issue_ids: HashSet<i32>,
    unread_counts: HashMap<i32, i32>,
    issue_numbers: HashMap<i32, String>,
    issue_labels: HashMap<i32, String>,
    issue_thread_ids: HashMap<i32, i32>,
    list_labels: HashMap<i32, String>,
    thread_labels: HashMap<i32, String>,
    active_prerequisite_ids: HashSet<i32>,
}

async fn load_boundary_labels(
    db: &Object,
    user: AuthenticatedUser,
    requested_thread_ids: &HashSet<i32>,
) -> Result<BoundaryShadowLabels, ApiError> {
    let user_id = user.id();

    // Load all owned threads
    let thread_rows = db
        .query(
            "SELECT id, title, status FROM threads WHERE user_id = $1",
            &[&user_id],
        )
        .await
        .map_err(db::query_error)?;

    let thread_ids: HashSet<i32> = thread_rows.iter().map(|r| r.get(0)).collect();
    let volume_by_thread = _volume_labels_by_thread(db, user_id, &thread_ids).await?;

    let mut thread_labels = HashMap::new();
    for row in &thread_rows {
        let id: i32 = row.get(0);
        thread_labels.insert(
            id,
            BoundaryThreadLabels {
                thread_id: id,
                title: row.get(1),
                status: row.get(2),
                volume_label: volume_by_thread.get(&id).cloned(),
            },
        );
    }

    // Load all owned issues
    let issue_rows = if thread_ids.is_empty() {
        vec![]
    } else {
        db.query(
            "SELECT i.id, i.thread_id, i.issue_number FROM issues i WHERE i.thread_id = ANY($1)",
            &[&thread_ids.iter().copied().collect::<Vec<_>>()],
        )
        .await
        .map_err(db::query_error)?
    };

    let mut issue_labels: HashMap<i32, BoundaryIssueLabels> = HashMap::new();
    for row in &issue_rows {
        let thread = thread_labels.get(&row.get(1)).unwrap();
        issue_labels.insert(
            row.get(0),
            BoundaryIssueLabels {
                issue_id: row.get(0),
                thread_id: row.get(1),
                thread_title: thread.title.clone(),
                issue_number: row.get(2),
                volume_label: thread.volume_label.clone(),
                reading_lists: vec![],
            },
        );
    }

    // Load active lists
    let list_rows = db
        .query(
            "SELECT id, name, mode FROM custom_cbl_lists WHERE user_id = $1",
            &[&user_id],
        )
        .await
        .map_err(db::query_error)?;

    let list_ids: Vec<i32> = list_rows.iter().map(|r| r.get(0)).collect();
    let active_list_ids: HashSet<i32> = if list_ids.is_empty() {
        HashSet::new()
    } else {
        let entry_list_ids = db
            .query(
                "SELECT DISTINCT list_id FROM custom_cbl_entries WHERE list_id = ANY($1)",
                &[&list_ids],
            )
            .await
            .map_err(db::query_error)?
            .iter()
            .map(|r| r.get(0))
            .collect::<HashSet<_>>();
        entry_list_ids
    };

    let mut lists = HashMap::new();
    for row in list_rows {
        let id: i32 = row.get(0);
        if active_list_ids.contains(&id) {
            lists.insert(
                id,
                BoundaryListLabels {
                    list_id: id,
                    name: row.get(1),
                    mode: row.get(2),
                },
            );
        }
    }

    // Load owned list memberships for each issue
    let mut issue_reading_lists: HashMap<i32, Vec<BoundaryReadingListMembership>> = HashMap::new();
    if !active_list_ids.is_empty() {
        let entry_rows = db
            .query(
                "SELECT list_id, issue_id FROM custom_cbl_entries WHERE list_id = ANY($1)",
                &[&active_list_ids.iter().copied().collect::<Vec<i32>>()],
            )
            .await
            .map_err(db::query_error)?;

        for entry in entry_rows {
            let issue_id: i32 = entry.get(1);
            if !issue_labels.contains_key(&issue_id) {
                continue;
            }
            let list_id: i32 = entry.get(0);
            if let Some(list_row) = lists.get(&list_id) {
                issue_reading_lists.entry(issue_id).or_default().push(
                    BoundaryReadingListMembership {
                        list_id: list_row.list_id,
                        name: list_row.name.clone(),
                        mode: list_row.mode.clone(),
                    },
                );
            }
        }
    }

    // Attach memberships to issue labels
    for (issue_id, lists) in issue_reading_lists {
        if let Some(mut label) = issue_labels.remove(&issue_id) {
            label.reading_lists = lists;
            issue_labels.insert(issue_id, label);
        }
    }

    // Load reader prerequisites only (not historical)
    let prerequisite_rows = db
        .query(
            r#"
            SELECT d.id, d.source_issue_id, d.target_issue_id,
                   d.classification, d.provenance
            FROM dependencies d
            JOIN issues si ON si.id = d.source_issue_id
            JOIN issues ti ON ti.id = d.target_issue_id
            JOIN threads st ON st.id = si.thread_id
            JOIN threads tt ON tt.id = ti.thread_id
            WHERE st.user_id = $1 AND tt.user_id = $1
              AND d.origin = 'reader'
              AND (si.thread_id = ANY($2) OR ti.thread_id = ANY($2))
            ORDER BY d.id
            "#,
            &[
                &user_id,
                &requested_thread_ids.iter().copied().collect::<Vec<_>>(),
            ],
        )
        .await
        .map_err(db::query_error)?;

    let mut prerequisites = HashMap::new();
    for row in prerequisite_rows {
        prerequisites.insert(
            row.get(0),
            BoundaryPrerequisiteLabels {
                prerequisite_id: row.get(0),
                source_issue_id: row.get(1),
                target_issue_id: row.get(2),
                origin: row.get(3),
                provenance: vec![
                    format!(
                        "classification:{}",
                        row.get::<_, Option<String>>(3).unwrap_or_default()
                    ),
                    row.get::<_, Option<String>>(4).unwrap_or_default(),
                ],
            },
        );
    }

    // Index incident edges
    let mut incident_ids: HashMap<i32, HashSet<i32>> = HashMap::new();
    for (prereq_id, prereq) in &prerequisites {
        let source_thread = issue_labels[&prereq.source_issue_id].thread_id;
        let target_thread = issue_labels[&prereq.target_issue_id].thread_id;
        incident_ids
            .entry(source_thread)
            .or_default()
            .insert(*prereq_id);
        incident_ids
            .entry(target_thread)
            .or_default()
            .insert(*prereq_id);
    }

    let prerequisite_ids_by_thread = incident_ids
        .into_iter()
        .map(|(k, v)| (k, v.into_iter().collect()))
        .collect();

    Ok(BoundaryShadowLabels {
        threads: thread_labels,
        issues: issue_labels,
        lists,
        prerequisites,
        prerequisite_ids_by_thread,
    })
}

async fn _volume_labels_by_thread(
    db: &Object,
    user_id: i32,
    thread_ids: &HashSet<i32>,
) -> Result<HashMap<i32, String>, ApiError> {
    if thread_ids.is_empty() {
        return Ok(HashMap::new());
    }
    let rows = db
        .query(
            r#"
            SELECT t.id, e.metadata_json::jsonb->>'name' as name
            FROM threads t
            JOIN thread_external_series_mappings m ON m.thread_id = t.id
            JOIN external_identities e ON e.id = m.external_identity_id
            WHERE t.id = ANY($1)
              AND t.user_id = $2
              AND m.status = 'confirmed'
              AND e.provider = 'comicvine'
              AND e.entity_type = 'series'
            "#,
            &[&thread_ids.iter().copied().collect::<Vec<_>>(), &user_id],
        )
        .await
        .map_err(db::query_error)?;

    let mut grouped: HashMap<i32, Vec<String>> = HashMap::new();
    for row in rows {
        let thread_id: i32 = row.get(0);
        let name: Option<String> = row.get(1);
        if let Some(name) = name {
            if !name.trim().is_empty() {
                grouped
                    .entry(thread_id)
                    .or_default()
                    .push(name.trim().to_string());
            }
        }
    }

    let mut labels = HashMap::new();
    for (thread_id, names) in grouped {
        if names.len() == 1 {
            labels.insert(thread_id, names.into_iter().next().unwrap());
        }
    }
    Ok(labels)
}

pub async fn project_boundary_explanation(
    snapshot: &ReadingEligibilitySnapshot,
    labels: &BoundaryShadowLabels,
    thread_id: i32,
) -> Result<ReadingBoundaryExplanationV2, ApiError> {
    let thread = labels.threads.get(&thread_id).ok_or(ApiError(
        StatusCode::NOT_FOUND,
        format!("Thread {thread_id} not found"),
    ))?;
    let state = snapshot.threads.get(&thread_id);
    let next_issue = state
        .and_then(|s| s.next_issue_id)
        .map(|id| issue_label(labels, id));

    let gates = crate::reading_blocker_projection::describe_blocker_gates(
        state.map(|s| s.blockers.clone()).unwrap_or_default(),
    );
    let blockers: Vec<ReadingBoundaryBlocker> = gates
        .iter()
        .map(|gate| project_blocker(snapshot, labels, gate))
        .collect();
    let requirements = crate::reading_blocker_projection::requirement_count(&gates);

    let boundary_state = match state {
        None => "unavailable",
        Some(_) if next_issue.is_none() => "complete",
        Some(evaluated) if evaluated.eligible => "available",
        Some(_) => "blocked",
    };

    Ok(ReadingBoundaryExplanationV2 {
        thread_id,
        state: boundary_state.to_string(),
        summary: summary(
            &thread.title,
            state,
            next_issue.as_ref(),
            &blockers,
            requirements,
        ),
        next: next_issue.map(|issue| {
            let issue_issue_id = issue.issue_id;
            let issue_thread_id = issue.thread_id;
            let issue_label = issue.label.clone();
            ReadingBoundaryNext {
                issue,
                editor: Some(BoundaryEditorTarget {
                    kind: "issue".to_string(),
                    label: issue_label,
                    list_id: None,
                    thread_id: Some(issue_thread_id),
                    issue_id: Some(issue_issue_id),
                    prerequisite_id: None,
                }),
            }
        }),
        blockers,
    })
}

async fn get_reading_boundary_explanations(
    state: &AppState,
    user: AuthenticatedUser,
    thread_ids: Vec<i32>,
) -> Result<ReadingBoundaryBatchResponseV2, ApiError> {
    validate_thread_ids(&thread_ids)?;
    let requested: HashSet<i32> = thread_ids.iter().copied().collect();
    let labels = load_boundary_labels(&db::checkout(state).await?, user, &requested).await?;

    let missing = thread_ids
        .iter()
        .copied()
        .find(|id| !labels.threads.contains_key(id));
    if let Some(thread_id) = missing {
        return Err(ApiError(
            StatusCode::NOT_FOUND,
            format!("Thread {thread_id} not found"),
        ));
    }

    let validated = option_inputs::load_option_inputs(state, user).await?;
    let snapshot = build_eligibility_snapshot(&validated, &labels, &requested)?;

    let mut threads = HashMap::new();
    for thread_id in thread_ids {
        threads.insert(
            thread_id,
            project_boundary_explanation(&snapshot, &labels, thread_id).await?,
        );
    }

    Ok(ReadingBoundaryBatchResponseV2 { threads })
}

fn build_eligibility_snapshot(
    validated: &ValidatedReadingInputs,
    labels: &BoundaryShadowLabels,
    _requested_thread_ids: &HashSet<i32>,
) -> Result<ReadingEligibilitySnapshot, ApiError> {
    let core = validated.inputs();
    let inputs = core;

    // Build queued thread IDs from stored eligibility
    let queued_thread_ids: HashSet<i32> = inputs
        .core
        .stored
        .iter()
        .filter(|s| s.queue_position >= 1)
        .map(|s| s.thread_id)
        .collect();

    // Build excluded issue IDs
    let excluded_issue_ids: HashSet<i32> = inputs.excluded_issue_ids.iter().copied().collect();

    // Build unread counts
    let mut unread_counts = HashMap::new();
    for issue in &inputs.core.issues {
        if issue.status != "read" && !excluded_issue_ids.contains(&issue.id) {
            *unread_counts.entry(issue.thread_id).or_insert(0) += 1;
        }
    }

    // Build issue labels and thread mappings
    let mut issue_numbers = HashMap::new();
    let issue_labels = HashMap::new();
    let mut issue_thread_ids = HashMap::new();
    for issue in &inputs.core.issues {
        issue_numbers.insert(issue.id, issue.issue_number.clone());
        issue_thread_ids.insert(issue.id, issue.thread_id);
        // We'll use the label from boundary labels
    }

    // Build thread labels
    let mut thread_labels = HashMap::new();
    for thread in &inputs.core.threads {
        thread_labels.insert(thread.id, thread.title.clone());
    }

    // Build list labels from provided labels (not from raw input which may not have names)
    let list_labels: HashMap<i32, String> = labels
        .lists
        .values()
        .map(|l| (l.list_id, l.name.clone()))
        .collect();

    // Build active prerequisite IDs
    let active_prerequisite_ids: HashSet<i32> = inputs
        .prerequisites
        .iter()
        .map(|p| p.prerequisite_id)
        .collect();

    // Get the evaluated threads from the validated inputs
    let evaluated_threads = crate::reading_eligibility::evaluate(validated)?;

    Ok(ReadingEligibilitySnapshot {
        user_id: 0, // Will be set by caller
        threads: evaluated_threads,
        queued_thread_ids,
        excluded_issue_ids,
        unread_counts,
        issue_numbers,
        issue_labels,
        issue_thread_ids,
        list_labels,
        thread_labels,
        active_prerequisite_ids,
    })
}

pub async fn reading_boundary_batch_v2(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    AxumJson(payload): AxumJson<ReadingBoundaryBatchRequest>,
) -> Result<Json<ReadingBoundaryBatchResponseV2>, ApiError> {
    get_reading_boundary_explanations(&state, user, payload.thread_ids)
        .await
        .map(Json)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::reading_constraints::ThreadEligibility;

    #[test]
    fn batch_bounds_match_the_canonical_python_request() {
        assert!(validate_thread_ids(&[1]).is_ok());
        assert!(validate_thread_ids(&[1; MAX_BATCH_THREAD_IDS]).is_ok());

        let empty = validate_thread_ids(&[]).expect_err("empty batch is rejected");
        assert_eq!(empty.0, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(empty.1, "thread_ids must contain between 1 and 200 entries");

        let oversized = vec![1; MAX_BATCH_THREAD_IDS + 1];
        let rejected = validate_thread_ids(&oversized).expect_err("oversized batch is rejected");
        assert_eq!(rejected.0, StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[test]
    fn prerequisite_origin_label_mapping() {
        assert_eq!(
            prerequisite_origin_label(Some("reader")),
            "Reader prerequisite"
        );
        assert_eq!(
            prerequisite_origin_label(Some("converted")),
            "Converted prerequisite"
        );
        assert_eq!(prerequisite_origin_label(None), "Historical prerequisite");
        assert_eq!(
            prerequisite_origin_label(Some("unknown")),
            "Historical prerequisite"
        );
    }

    #[test]
    fn summary_states_match_python() {
        let mut blockers = vec![];
        let next = Some(BoundaryIssue {
            issue_id: 1,
            thread_id: 1,
            thread_title: "Test".to_string(),
            issue_number: "1".to_string(),
            volume_label: None,
            label: "Test #1".to_string(),
            reading_lists: vec![],
        });

        assert_eq!(
            summary("Test", None, next.as_ref(), &blockers, 0),
            "Test is not currently active."
        );

        let state = ThreadEligibility {
            thread_id: 1,
            next_issue_id: None,
            eligible: false,
            blockers: vec![],
        };
        assert_eq!(
            summary("Test", Some(&state), None, &blockers, 0),
            "Test has no unread issues."
        );

        blockers.push(ReadingBoundaryBlocker {
            kind: "prerequisite".to_string(),
            origin: "reader_prerequisite".to_string(),
            reason: "Reader prerequisite: read Fourth World #2 first".to_string(),
            waiting_on: vec![],
            editor: None,
        });
        assert_eq!(
            summary("Test", Some(&state), next.as_ref(), &blockers, 1),
            "Test #1 is waiting on 1 live requirement."
        );
    }
}
