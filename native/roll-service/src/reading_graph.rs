//! Owner-scoped reading-graph diagnostics and safe constraint repair.
//!
//! The graph is projected from the same single-statement Option E snapshot that
//! Roll, Queue and the reading-boundary resources use. Nothing here performs a
//! second eligibility interpretation: the Rust constraint validator is the one
//! authority that both rejects new cycles and isolates a persisted one.
//!
//! A persisted cycle must never turn an unaffected reader's request into a 500.
//! This resource names the exact stored edges that close the cycle, identifies
//! the affected Reading Lists and Threads, and exposes owner-scoped repair
//! actions that remove only the selected constraint. A repair never deletes an
//! Issue, read state, rating, history event, or another reader's row.

use crate::{
    auth::AuthenticatedUser, db, option_inputs, option_inputs::OptionInputs,
    reading_constraints::ValidationError, ApiError, AppState,
};
use axum::{extract::State, http::StatusCode, Json};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
use tokio_postgres::Transaction;

const MAX_REPORTED_CYCLES: usize = 8;
const MAX_REPORTED_EDGES: usize = 40;
const MAX_REPAIR_OPTIONS: usize = 16;

/// One issue endpoint as a reader sees it, never a bare database identifier.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphIssue {
    pub issue_id: i32,
    pub issue_number: String,
    pub thread_id: i32,
    pub series_title: String,
}

/// One stored requirement that participates in a cycle.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphEdge {
    pub source: ReadingGraphIssue,
    pub target: ReadingGraphIssue,
    pub origin: String,
    pub kind: String,
    pub list_id: Option<i32>,
    pub list_name: Option<String>,
    pub prerequisite_id: Option<i32>,
}

/// One cycle with its concrete edge path.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphCycle {
    pub message: String,
    pub edges: Vec<ReadingGraphEdge>,
}

/// One affected Reading List.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphList {
    pub list_id: i32,
    pub name: String,
    pub mode: String,
}

/// One affected Thread.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphThread {
    pub thread_id: i32,
    pub title: String,
}

/// One owner-scoped repair the reader can preview and apply.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphRepairOption {
    pub action: String,
    pub label: String,
    pub detail: String,
    pub list_id: Option<i32>,
    pub issue_id: Option<i32>,
    pub prerequisite_id: Option<i32>,
}

/// Complete graph state. `status` is `ok`, `cycle`, or `invalid`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphResponse {
    pub status: String,
    pub cycles: Vec<ReadingGraphCycle>,
    pub cyclic_issue_ids: Vec<i32>,
    pub affected_lists: Vec<ReadingGraphList>,
    pub affected_threads: Vec<ReadingGraphThread>,
    pub repairs: Vec<ReadingGraphRepairOption>,
    pub unresolved_reference_count: usize,
}

/// One validated repair action.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ReadingGraphRepairAction {
    /// Delete one owned Reading List. Entries cascade; reading history does not.
    DeleteList { list_id: i32 },
    /// Remove one reader-authored prerequisite edge.
    DeletePrerequisite { prerequisite_id: i32 },
    /// Remove one issue placement from one owned Reading List.
    DeleteListEntry { list_id: i32, issue_id: i32 },
}

/// Flat wire request so a preview never depends on tagged-enum deserialization.
#[derive(Debug, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ReadingGraphRepairRequest {
    pub action: String,
    pub list_id: Option<i32>,
    pub issue_id: Option<i32>,
    pub prerequisite_id: Option<i32>,
    /// Preview by default. A repair applies only when this is explicitly true.
    #[serde(default)]
    pub confirm: bool,
}

impl ReadingGraphRepairRequest {
    fn action(&self) -> Result<ReadingGraphRepairAction, crate::ApiError> {
        match self.action.as_str() {
            "delete_list" => self
                .list_id
                .map(|list_id| ReadingGraphRepairAction::DeleteList { list_id })
                .ok_or_else(|| {
                    crate::ApiError(StatusCode::BAD_REQUEST, "list_id is required".to_string())
                }),
            "delete_prerequisite" => self
                .prerequisite_id
                .map(
                    |prerequisite_id| ReadingGraphRepairAction::DeletePrerequisite {
                        prerequisite_id,
                    },
                )
                .ok_or_else(|| {
                    crate::ApiError(
                        StatusCode::BAD_REQUEST,
                        "prerequisite_id is required".to_string(),
                    )
                }),
            "delete_list_entry" => match (self.list_id, self.issue_id) {
                (Some(list_id), Some(issue_id)) => {
                    Ok(ReadingGraphRepairAction::DeleteListEntry { list_id, issue_id })
                }
                _ => Err(crate::ApiError(
                    StatusCode::BAD_REQUEST,
                    "list_id and issue_id are required".to_string(),
                )),
            },
            _ => Err(crate::ApiError(
                StatusCode::BAD_REQUEST,
                "action must be delete_list, delete_prerequisite or delete_list_entry".to_string(),
            )),
        }
    }
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphRepairResponse {
    pub applied: bool,
    pub status_before: String,
    pub status_after: String,
    pub removed: String,
    pub graph: ReadingGraphResponse,
}

pub(crate) fn cycle_conflict(
    error: ValidationError,
    inputs: &option_inputs::OptionInputs,
) -> ApiError {
    match error {
        ValidationError::Cycle { edges, .. } => {
            let titles: BTreeMap<i32, &str> = inputs
                .core
                .threads
                .iter()
                .map(|thread| (thread.id, thread.title.as_str()))
                .collect();
            let numbers: BTreeMap<i32, String> = inputs
                .core
                .issues
                .iter()
                .map(|issue| {
                    (
                        issue.id,
                        format!(
                            "{} #{}",
                            titles.get(&issue.thread_id).copied().unwrap_or("Series"),
                            issue.issue_number
                        ),
                    )
                })
                .collect();
            let path = edges
                .iter()
                .map(|edge| {
                    format!(
                        "{} --[{}]--> {}",
                        numbers
                            .get(&edge.source_issue_id)
                            .cloned()
                            .unwrap_or_else(|| format!("Issue {}", edge.source_issue_id)),
                        edge.origin,
                        numbers
                            .get(&edge.target_issue_id)
                            .cloned()
                            .unwrap_or_else(|| format!("Issue {}", edge.target_issue_id)),
                    )
                })
                .collect::<Vec<_>>()
                .join(" -> ");
            ApiError(
                StatusCode::CONFLICT,
                format!("Reading constraint cycle: {path}. Nothing was changed."),
            )
        }
        ValidationError::InvalidSnapshot { message } => {
            ApiError(StatusCode::UNPROCESSABLE_ENTITY, message)
        }
    }
}

fn issue_lookup(
    inputs: &OptionInputs,
) -> (BTreeMap<i32, ReadingGraphIssue>, BTreeMap<i32, String>) {
    let titles: BTreeMap<i32, String> = inputs
        .core
        .threads
        .iter()
        .map(|thread| (thread.id, thread.title.clone()))
        .collect();
    let issues = inputs
        .core
        .issues
        .iter()
        .filter_map(|issue| {
            Some((
                issue.id,
                ReadingGraphIssue {
                    issue_id: issue.id,
                    issue_number: issue.issue_number.clone(),
                    thread_id: issue.thread_id,
                    series_title: titles.get(&issue.thread_id)?.clone(),
                },
            ))
        })
        .collect();
    (issues, titles)
}

fn list_lookup(inputs: &OptionInputs) -> BTreeMap<i32, ReadingGraphList> {
    inputs
        .lists
        .iter()
        .map(|list| {
            (
                list.list_id,
                ReadingGraphList {
                    list_id: list.list_id,
                    name: list.name.clone(),
                    mode: list.mode.clone(),
                },
            )
        })
        .collect()
}

fn origin_kind(origin: &str, has_prerequisite: bool) -> &'static str {
    if has_prerequisite {
        "prerequisite"
    } else if origin.contains("strict order") {
        "strict_order"
    } else if origin.contains("after_previous") {
        "after_previous"
    } else if origin.contains("hold") {
        "hold"
    } else if origin.contains("series order") {
        "series_order"
    } else {
        "other"
    }
}

fn prerequisite_id(origin: &str) -> Option<i32> {
    origin
        .strip_prefix("prerequisite ")
        .and_then(|rest| rest.split_whitespace().next())
        .and_then(|value| value.parse().ok())
}

fn push_repairs(
    edge: &crate::reading_constraints::ConstraintEdge,
    issues: &BTreeMap<i32, ReadingGraphIssue>,
    lists: &BTreeMap<i32, ReadingGraphList>,
    repairs: &mut Vec<ReadingGraphRepairOption>,
    repair_keys: &mut BTreeSet<String>,
) {
    let Some(source) = issues.get(&edge.source_issue_id) else {
        return;
    };
    let Some(target) = issues.get(&edge.target_issue_id) else {
        return;
    };
    if let Some(list_id) = edge.list_id {
        let key = format!("delete_list:{list_id}");
        if repair_keys.insert(key) {
            if let Some(list) = lists.get(&list_id) {
                repairs.push(ReadingGraphRepairOption {
                    action: "delete_list".to_string(),
                    label: format!("Delete Reading List \u{201c}{}\u{201d}", list.name),
                    detail: "Removes this list's ordering constraints. Issues, reads, ratings and history are preserved.".to_string(),
                    list_id: Some(list_id),
                    issue_id: None,
                    prerequisite_id: None,
                });
            }
        }
        let key = format!("delete_list_entry:{list_id}:{}", edge.target_issue_id);
        if repair_keys.insert(key) {
            repairs.push(ReadingGraphRepairOption {
                action: "delete_list_entry".to_string(),
                label: format!(
                    "Remove {} #{} from \u{201c}{}\u{201d}",
                    target.series_title,
                    target.issue_number,
                    lists.get(&list_id).map(|list| list.name.as_str()).unwrap_or("Reading List")
                ),
                detail: "Removes only this list placement. The issue, its read state and its history are preserved.".to_string(),
                list_id: Some(list_id),
                issue_id: Some(edge.target_issue_id),
                prerequisite_id: None,
            });
        }
    }
    if edge.prerequisite_origin.is_some() {
        if let Some(prerequisite_id) = prerequisite_id(&edge.origin) {
            let key = format!("delete_prerequisite:{prerequisite_id}");
            if repair_keys.insert(key) {
                repairs.push(ReadingGraphRepairOption {
                    action: "delete_prerequisite".to_string(),
                    label: format!(
                        "Remove prerequisite {} #{} \u{2192} {} #{}",
                        source.series_title,
                        source.issue_number,
                        target.series_title,
                        target.issue_number
                    ),
                    detail: "Removes only this reader prerequisite. Read state and history are preserved.".to_string(),
                    list_id: None,
                    issue_id: None,
                    prerequisite_id: Some(prerequisite_id),
                });
            }
        }
    }
}

fn project(
    inputs: &OptionInputs,
    validated: &crate::reading_constraints::ValidatedReadingInputs,
) -> ReadingGraphResponse {
    let (issues, titles) = issue_lookup(inputs);
    let lists = list_lookup(inputs);
    let mut repairs: Vec<ReadingGraphRepairOption> = vec![];
    let mut repair_keys: BTreeSet<String> = BTreeSet::new();
    let mut cycles = vec![];
    let mut edge_count = 0usize;
    if let Some(problem) = validated.graph_problem() {
        for edge in &problem.affected_edges {
            push_repairs(edge, &issues, &lists, &mut repairs, &mut repair_keys);
        }
        for cycle in problem.cycles.iter().take(MAX_REPORTED_CYCLES) {
            let mut edges = vec![];
            for edge in &cycle.edges {
                let (Some(source), Some(target)) = (
                    issues.get(&edge.source_issue_id),
                    issues.get(&edge.target_issue_id),
                ) else {
                    continue;
                };
                edges.push(ReadingGraphEdge {
                    source: source.clone(),
                    target: target.clone(),
                    origin: edge.origin.clone(),
                    kind: origin_kind(&edge.origin, edge.prerequisite_origin.is_some()).to_string(),
                    list_id: edge.list_id,
                    list_name: edge
                        .list_id
                        .and_then(|list_id| lists.get(&list_id).map(|list| list.name.clone())),
                    prerequisite_id: edge
                        .prerequisite_origin
                        .is_some()
                        .then(|| prerequisite_id(&edge.origin))
                        .flatten(),
                });
                edge_count += 1;
                if edge_count >= MAX_REPORTED_EDGES {
                    break;
                }
            }
            cycles.push(ReadingGraphCycle {
                message: cycle.message.clone(),
                edges,
            });
            if edge_count >= MAX_REPORTED_EDGES {
                break;
            }
        }
    }
    repairs.truncate(MAX_REPAIR_OPTIONS);
    let affected_lists = validated
        .graph_problem()
        .into_iter()
        .flat_map(|problem| problem.affected_list_ids.iter())
        .filter_map(|list_id| lists.get(list_id).cloned())
        .collect();
    let affected_threads = validated
        .graph_problem()
        .into_iter()
        .flat_map(|problem| problem.affected_thread_ids.iter())
        .filter_map(|thread_id| {
            titles.get(thread_id).map(|title| ReadingGraphThread {
                thread_id: *thread_id,
                title: title.clone(),
            })
        })
        .collect();
    let cyclic_issue_ids = validated
        .graph_problem()
        .map(|problem| problem.cyclic_issue_ids.iter().copied().collect())
        .unwrap_or_default();
    ReadingGraphResponse {
        status: if validated.graph_problem().is_some() {
            "cycle".to_string()
        } else {
            "ok".to_string()
        },
        cycles,
        cyclic_issue_ids,
        affected_lists,
        affected_threads,
        repairs,
        unresolved_reference_count: inputs.unresolved.len(),
    }
}

fn repair_target_exists(inputs: &OptionInputs, action: &ReadingGraphRepairAction) -> bool {
    match action {
        ReadingGraphRepairAction::DeleteList { list_id } => {
            inputs.lists.iter().any(|list| list.list_id == *list_id)
        }
        ReadingGraphRepairAction::DeletePrerequisite { prerequisite_id } => inputs
            .prerequisites
            .iter()
            .any(|prerequisite| prerequisite.prerequisite_id == *prerequisite_id),
        ReadingGraphRepairAction::DeleteListEntry { list_id, issue_id } => inputs
            .lists
            .iter()
            .find(|list| list.list_id == *list_id)
            .is_some_and(|list| list.entries.iter().any(|entry| entry.issue_id == *issue_id)),
    }
}

fn repair_is_offered(
    options: &[ReadingGraphRepairOption],
    action: &ReadingGraphRepairAction,
) -> bool {
    options.iter().any(|option| match action {
        ReadingGraphRepairAction::DeleteList { list_id } => {
            option.action == "delete_list" && option.list_id == Some(*list_id)
        }
        ReadingGraphRepairAction::DeletePrerequisite { prerequisite_id } => {
            option.action == "delete_prerequisite"
                && option.prerequisite_id == Some(*prerequisite_id)
        }
        ReadingGraphRepairAction::DeleteListEntry { list_id, issue_id } => {
            option.action == "delete_list_entry"
                && option.list_id == Some(*list_id)
                && option.issue_id == Some(*issue_id)
        }
    })
}

fn invalid_response(inputs: &OptionInputs) -> ReadingGraphResponse {
    ReadingGraphResponse {
        status: "invalid".to_string(),
        cycles: vec![],
        cyclic_issue_ids: vec![],
        affected_lists: vec![],
        affected_threads: vec![],
        repairs: vec![],
        unresolved_reference_count: inputs.unresolved.len(),
    }
}

/// `GET /api/v2/reading-graph`
pub async fn reading_graph(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> Result<Json<ReadingGraphResponse>, crate::ApiError> {
    // A confirmed repair must validate the *same* graph it will modify.
    // Lock before taking its snapshot, so a concurrent list/dependency write
    // cannot invalidate an offered action between preflight and deletion.
    // Preview remains a read-only diagnostic and never locks a writer.
    let mut connection = if request.confirm {
        Some(db::checkout(&state).await?)
    } else {
        None
    };
    let transaction = if let Some(connection) = connection.as_mut() {
        let transaction = connection
            .build_transaction()
            .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
            .start()
            .await
            .map_err(db::query_error)?;
        transaction
            .execute(
                "SELECT pg_advisory_xact_lock($1,$2)",
                &[&699001, &user.id()],
            )
            .await
            .map_err(db::query_error)?;
        Some(transaction)
    } else {
        None
    };
    let inputs = if let Some(transaction) = transaction.as_ref() {
        option_inputs::load_inputs_in_transaction(transaction, user).await?
    } else {
        option_inputs::load_option_diagnostics(&state, user).await?
    };
    if !inputs.unresolved.is_empty() {
        return Ok(Json(invalid_response(&inputs)));
    }
    let validated = option_inputs::validated_contained(inputs)?;
    Ok(Json(project(validated.inputs(), &validated)))
}

fn remove_from_inputs(
    inputs: &mut OptionInputs,
    action: &ReadingGraphRepairAction,
) -> Result<String, &'static str> {
    match action {
        ReadingGraphRepairAction::DeleteList { list_id } => {
            let before = inputs.lists.len();
            inputs.lists.retain(|list| list.list_id != *list_id);
            if inputs.lists.len() == before {
                return Err("Reading List not found");
            }
            Ok("Reading List deleted".to_string())
        }
        ReadingGraphRepairAction::DeletePrerequisite { prerequisite_id } => {
            let before = inputs.prerequisites.len();
            inputs
                .prerequisites
                .retain(|prerequisite| prerequisite.prerequisite_id != *prerequisite_id);
            if inputs.prerequisites.len() == before {
                return Err("Prerequisite not found");
            }
            Ok("Prerequisite deleted".to_string())
        }
        ReadingGraphRepairAction::DeleteListEntry { list_id, issue_id } => {
            let Some(list) = inputs
                .lists
                .iter_mut()
                .find(|list| list.list_id == *list_id)
            else {
                return Err("Reading List not found");
            };
            let before = list.entries.len();
            list.entries.retain(|entry| entry.issue_id != *issue_id);
            if list.entries.len() == before {
                return Err("Reading List entry not found");
            }
            Ok("Reading List entry deleted".to_string())
        }
    }
}

async fn delete_owned(
    tx: &Transaction<'_>,
    user_id: i32,
    action: &ReadingGraphRepairAction,
) -> Result<u64, crate::ApiError> {
    let removed = match action {
        ReadingGraphRepairAction::DeleteList { list_id } => {
            crate::reading_list::ensure_list_unlinked(tx, user_id, *list_id).await?;
            tx.execute(
                "DELETE FROM custom_cbl_lists WHERE id=$1 AND user_id=$2",
                &[list_id, &user_id],
            )
            .await
            .map_err(db::query_error)?
        }
        ReadingGraphRepairAction::DeletePrerequisite { prerequisite_id } => tx
            .execute(
                "DELETE FROM dependencies d
                 USING issues si, threads st, issues ti, threads tt
                 WHERE d.id=$1
                   AND d.source_issue_id=si.id AND si.thread_id=st.id AND st.user_id=$2
                   AND d.target_issue_id=ti.id AND ti.thread_id=tt.id AND tt.user_id=$2
                   AND d.origin='reader'",
                &[prerequisite_id, &user_id],
            )
            .await
            .map_err(db::query_error)?,
        ReadingGraphRepairAction::DeleteListEntry { list_id, issue_id } => tx
            .execute(
                "DELETE FROM custom_cbl_entries e
                 USING custom_cbl_lists l
                 WHERE e.list_id=$1 AND e.issue_id=$2
                   AND l.id=e.list_id AND l.user_id=$3",
                &[list_id, issue_id, &user_id],
            )
            .await
            .map_err(db::query_error)?,
    };
    Ok(removed)
}

/// `POST /api/v2/reading-graph/repairs`
///
/// Preview is the default. `confirm: true` applies exactly one action after the
/// projected graph has been recomputed in memory from the same snapshot. Both
/// modes return the remaining graph so the UI can show restored eligibility.
pub async fn repair(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<ReadingGraphRepairRequest>,
) -> Result<Json<ReadingGraphRepairResponse>, crate::ApiError> {
    let inputs = option_inputs::load_option_diagnostics(&state, user).await?;
    if !inputs.unresolved.is_empty() {
        if request.confirm {
            return Err(crate::ApiError(
                StatusCode::CONFLICT,
                "Resolve the missing reading reference before applying a repair".to_string(),
            ));
        }
        return Ok(Json(ReadingGraphRepairResponse {
            applied: false,
            status_before: "invalid".to_string(),
            status_after: "invalid".to_string(),
            removed: "Unresolved reading reference".to_string(),
            graph: invalid_response(&inputs),
        }));
    }
    let validated = option_inputs::validated_contained(inputs.clone())?;
    let allowed = project(&inputs, &validated).repairs;
    let status_before = if validated.graph_problem().is_some() {
        "cycle"
    } else {
        "ok"
    };
    let action = request.action()?;
    if !repair_target_exists(&inputs, &action) {
        return Err(crate::ApiError(
            StatusCode::NOT_FOUND,
            "Constraint not found".to_string(),
        ));
    }
    if !repair_is_offered(&allowed, &action) {
        return Err(crate::ApiError(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Repair is not applicable to the current reading graph".to_string(),
        ));
    }
    let mut projected = inputs;
    let removed = remove_from_inputs(&mut projected, &action)
        .map_err(|detail| crate::ApiError(StatusCode::NOT_FOUND, detail.to_string()))?;

    if let Some(tx) = transaction {
        let deleted = delete_owned(&tx, user.id(), &action).await?;
        if deleted == 0 {
            tx.rollback().await.map_err(db::query_error)?;
            return Err(crate::ApiError(
                StatusCode::NOT_FOUND,
                "Constraint not found".to_string(),
            ));
        }
        tx.commit().await.map_err(db::query_error)?;
    }

    if request.confirm {
        // Re-read after commit so the response is the persisted graph, not the
        // pre-transaction snapshot with an in-memory deletion applied.
        let fresh = option_inputs::load_option_diagnostics(&state, user).await?;
        let after = option_inputs::validated_contained(fresh)?;
        return Ok(Json(ReadingGraphRepairResponse {
            applied: true,
            status_before: status_before.to_string(),
            status_after: if after.graph_problem().is_some() {
                "cycle".to_string()
            } else {
                "ok".to_string()
            },
            removed,
            graph: project(after.inputs(), &after),
        }));
    }
    let after = option_inputs::validated_contained(projected)?;
    Ok(Json(ReadingGraphRepairResponse {
        applied: false,
        status_before: status_before.to_string(),
        status_after: if after.graph_problem().is_some() {
            "cycle".to_string()
        } else {
            "ok".to_string()
        },
        removed,
        graph: project(after.inputs(), &after),
    }))
}

/// Documentation-only operation for the mounted reading-graph read.
#[utoipa::path(
    get,
    path = "/api/v2/reading-graph",
    tag = "reading-graph",
    description = "Owner-scoped projection of the complete Option E graph. A persisted cycle is isolated to its affected Threads and Reading Lists; every cycle edge names its series, issue and stored origin.",
    responses(
        (status = 200, description = "Graph status, cycles and safe repair options", body = ReadingGraphResponse),
        (status = 401, description = "Not authenticated"),
        (status = 500, description = "Invalid reading snapshot"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn reading_graph_documentation() {}

/// Documentation-only operation for the mounted graph repair action.
#[utoipa::path(
    post,
    path = "/api/v2/reading-graph/repairs",
    tag = "reading-graph",
    description = "Preview (default) or apply exactly one owner-scoped constraint repair. Deleting a list, list entry or reader prerequisite removes only that effective constraint and preserves Issues, reads, ratings and history.",
    request_body = ReadingGraphRepairRequest,
    responses(
        (status = 200, description = "Repair preview or applied result with the remaining graph", body = ReadingGraphRepairResponse),
        (status = 400, description = "Invalid repair request"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Constraint not found"),
        (status = 500, description = "Invalid reading snapshot"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn repair_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        option_inputs::{OverlapDecision, Prerequisite, ReadingEntry, ReadingList},
        reading_inputs::{CoreReadingInputs, ReadingIssue, ReadingThread, StoredThreadEligibility},
    };

    fn inputs() -> OptionInputs {
        OptionInputs {
            core: CoreReadingInputs {
                threads: vec![ReadingThread {
                    id: 8,
                    status: "active".into(),
                    title: "B.P.R.D.".into(),
                }],
                issues: vec![
                    ReadingIssue {
                        id: 11,
                        thread_id: 8,
                        position: 1,
                        status: "unread".into(),
                        issue_number: "130".into(),
                    },
                    ReadingIssue {
                        id: 14,
                        thread_id: 8,
                        position: 2,
                        status: "unread".into(),
                        issue_number: "142".into(),
                    },
                ],
                stored: vec![StoredThreadEligibility {
                    thread_id: 8,
                    next_issue_id: None,
                    is_blocked: false,
                    queue_position: 1,
                }],
            },
            thread_volumes: BTreeMap::new(),
            lists: vec![ReadingList {
                list_id: 7,
                mode: "strict".into(),
                name: "Julix".into(),
                entries: vec![
                    ReadingEntry {
                        issue_id: 14,
                        gate: "none".into(),
                        skipped: false,
                    },
                    ReadingEntry {
                        issue_id: 11,
                        gate: "none".into(),
                        skipped: false,
                    },
                ],
                overlap_decisions: vec![] as Vec<OverlapDecision>,
            }],
            prerequisites: vec![Prerequisite {
                prerequisite_id: 5,
                source_issue_id: 11,
                target_issue_id: 14,
                origin: "reader".into(),
                provenance: vec![],
            }],
            excluded_issue_ids: BTreeSet::new(),
            unresolved: vec![],
        }
    }

    #[test]
    fn projection_names_edges_lists_and_safe_repairs() {
        let source = inputs();
        let validated = crate::reading_constraints::ValidatedReadingInputs::contained(
            source.clone(),
            &BTreeMap::from([(7, "Julix".to_string())]),
        )
        .unwrap();
        let graph = project(&source, &validated);
        assert_eq!(graph.status, "cycle");
        assert!(!graph.cycles.is_empty());
        assert_eq!(graph.cycles[0].edges[0].source.series_title, "B.P.R.D.");
        assert_eq!(graph.affected_lists[0].name, "Julix");
        assert!(graph
            .repairs
            .iter()
            .any(|repair| repair.action == "delete_list" && repair.list_id == Some(7)));
        assert!(graph
            .repairs
            .iter()
            .any(|repair| repair.action == "delete_list_entry" && repair.issue_id == Some(11)));
        assert!(graph
            .repairs
            .iter()
            .any(|repair| repair.action == "delete_prerequisite"
                && repair.prerequisite_id == Some(5)));
    }

    #[test]
    fn repair_simulation_restores_an_acyclic_graph() {
        let mut source = inputs();
        let removed = remove_from_inputs(
            &mut source,
            &ReadingGraphRepairAction::DeleteList { list_id: 7 },
        )
        .unwrap();
        assert_eq!(removed, "Reading List deleted");
        let validated =
            crate::reading_constraints::ValidatedReadingInputs::contained(source, &BTreeMap::new())
                .unwrap();
        assert!(validated.graph_problem().is_none());
    }
}
