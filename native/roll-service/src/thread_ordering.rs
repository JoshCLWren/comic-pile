//! Same-path Rust cutover for the browser-called thread ordering and
//! dependency-inspection reads (#4832, part B).
//!
//! Preserves the frozen Python wire contract (the oracle is
//! `app/api/dependency.py`, `app/api/issue.py`, `app/api/reading_orders.py`,
//! `app/services/dependency_service.py`, `comic_pile/dependencies.py` and
//! `app/services/reading_order_service.py`) at the identical HTTP methods and
//! paths:
//!
//! * `POST /api/v1/threads/{thread_id}:getBlockingInfo`
//! * `POST /api/v1/threads:getBlockingInfo`
//! * `GET  /api/v1/threads/{thread_id}/connected`
//! * `GET  /api/v1/threads/{thread_id}/dependency-order-check`
//! * `GET  /api/v1/threads/{thread_id}/issues:validateOrder`
//! * `GET  /api/v1/threads/{thread_id}/reading-orders`
//!
//! All six are reads (the two `getBlockingInfo` POSTs are idempotent
//! queries), so there are no transactions or side effects to preserve; each
//! handler is owner-scoped on every statement.
//!
//! Parity notes:
//!
//! * Blocking explanations follow the two Python execution authorities. The
//!   legacy default reads the canonical `Dependency` rows (notes beginning
//!   `cbl-order:` are inert) for each thread's unread frontier; the
//!   owner-approved Option E preview projects live blockers from the evaluated
//!   reading graph with reader-facing origins and issue links.
//! * The batch response is a JSON object keyed by thread id in request order
//!   (Python dict insertion order), so it is serialized through an ordered
//!   map instead of a sorted one.
//! * Python never reveals a foreign thread: ownership failures are 404s with
//!   the same detail text as a missing thread.
//! * Path and body validation uses the house Rust convention
//!   (`{"detail": "Validation failed"}` 422), matching every other native v1
//!   cutover; FastAPI's list-shaped validation body is not reproduced.

#![forbid(unsafe_code)]

use crate::{
    auth::AuthenticatedUser, db, option_inputs, reading_blocker_projection, reading_eligibility,
    thread_issues, ApiError, AppState,
};
use axum::{
    extract::{rejection::PathRejection, Path, State},
    response::{IntoResponse, Response},
    Json,
};
use serde::{ser::SerializeMap, Serialize, Serializer};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::sync::Arc;

const MAX_BATCH_THREAD_IDS: usize = 500;

/// One blocking issue (Python `BlockingDependency`).
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct BlockingDependency {
    pub thread_id: i32,
    pub thread_title: String,
    pub issue_number: String,
    pub label: String,
    pub issue_id: Option<i32>,
}

/// Blocked status plus reader-language reasons (Python `BlockingExplanation`).
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct BlockingExplanation {
    pub is_blocked: bool,
    pub blocking_reasons: Vec<String>,
    pub blocking_dependencies: Vec<BlockingDependency>,
}

/// Ordered `thread_id -> explanation` object (Python `dict[int, ...]`).
#[derive(Debug, Clone, utoipa::ToSchema)]
#[schema(value_type = HashMap<String, BlockingExplanation>)]
pub struct OrderedExplanations(pub Vec<(i32, BlockingExplanation)>);

impl Serialize for OrderedExplanations {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut map = serializer.serialize_map(Some(self.0.len()))?;
        for (thread_id, explanation) in &self.0 {
            map.serialize_entry(&thread_id.to_string(), explanation)?;
        }
        map.end()
    }
}

/// Python `BatchBlockingExplanationResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct BatchBlockingExplanationResponse {
    pub threads: OrderedExplanations,
}

/// Python `BatchBlockingExplanationRequest` (documentation schema).
#[derive(Debug, Clone, serde::Deserialize, utoipa::ToSchema)]
pub struct BatchBlockingExplanationRequest {
    #[schema(min_items = 1, max_items = 500)]
    pub thread_ids: Vec<i32>,
}

/// Python `ConnectedThreadInfo`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ConnectedThreadInfo {
    pub thread_id: i32,
    pub title: String,
    pub connection_type: String,
    pub dependency_id: i32,
    pub issue_number: Option<String>,
    pub is_circular: bool,
}

/// Python `ThreadConnectedResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ThreadConnectedResponse {
    pub thread_id: i32,
    pub connected_threads: Vec<ConnectedThreadInfo>,
}

/// Python `DependencyOrderRequirement`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct DependencyOrderRequirement {
    pub issue_id: i32,
    pub issue_number: String,
    pub position: i32,
}

/// Python `DependencyOrderConflict`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct DependencyOrderConflict {
    pub issue_id: i32,
    pub issue_number: String,
    pub position: i32,
    pub dependency_requires_before: Vec<DependencyOrderRequirement>,
    pub conflict: String,
}

/// Python `ThreadDependencyOrderCheckResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ThreadDependencyOrderCheckResponse {
    pub thread_id: i32,
    pub conflicts: Vec<DependencyOrderConflict>,
}

/// Python `IssueOrderValidationResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct IssueOrderValidationResponse {
    pub warnings: Vec<String>,
}

/// Python `ReadingOrderItemResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingOrderItemResponse {
    pub thread_id: i32,
    pub thread_title: String,
    pub position: i32,
    pub issue_number: Option<String>,
    pub is_read: bool,
}

/// Python `ReadingOrderResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingOrderResponse {
    pub id: i32,
    pub name: String,
    pub description: Option<String>,
    pub total_items: i64,
    pub completed_items: i64,
    pub items: Vec<ReadingOrderItemResponse>,
}

/// Python `ThreadReadingOrdersResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ThreadReadingOrdersResponse {
    pub reading_orders: Vec<ReadingOrderResponse>,
}

fn validation_failed() -> ApiError {
    ApiError::Unprocessable("Validation failed".into())
}

fn thread_not_found(thread_id: i32) -> ApiError {
    ApiError::NotFound(format!("Thread {thread_id} not found"))
}

/// FastAPI `int` path parameters reject non-integers (and invalid UTF-8) with 422.
fn parse_thread_id(raw: Result<Path<String>, PathRejection>) -> Result<i32, ApiError> {
    let Path(raw) = raw.map_err(|_| validation_failed())?;
    parse_int_text(&raw).ok_or_else(validation_failed)
}

/// Accept the decimal integers pydantic's lax int parser accepts for a path value.
pub(crate) fn parse_int_text(raw: &str) -> Option<i32> {
    let trimmed = raw.trim();
    let digits = trimmed
        .strip_prefix(['+', '-'])
        .map_or(trimmed, |rest| rest);
    if digits.is_empty() || !digits.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    trimmed.parse().ok()
}

async fn require_owned_thread<C>(
    client: &C,
    user: AuthenticatedUser,
    thread_id: i32,
) -> Result<String, ApiError>
where
    C: tokio_postgres::GenericClient + Sync,
{
    let row = client
        .query_opt(
            "SELECT title FROM threads WHERE id = $1 AND user_id = $2",
            &[&thread_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    row.map(|row| row.get(0))
        .ok_or_else(|| thread_not_found(thread_id))
}

// ---------------------------------------------------------------------------
// Blocking explanations
// ---------------------------------------------------------------------------

fn build_blocking_explanation(issue_number: &str, thread_title: &str) -> String {
    format!("Blocked by {thread_title}: #{issue_number}")
}

const CANONICAL_BLOCKERS_SQL: &str = "SELECT tt.id, st.id, st.title, si.issue_number \
     FROM threads tt \
     JOIN issues ni ON ni.id = tt.next_unread_issue_id \
     JOIN dependencies d ON d.target_issue_id = ni.id \
     JOIN issues si ON si.id = d.source_issue_id \
     JOIN threads st ON st.id = si.thread_id \
     WHERE tt.id = ANY($1) AND tt.user_id = $2 AND st.user_id = $2 \
       AND si.status <> 'read' AND ni.status <> 'read' \
       AND tt.next_unread_issue_id IS NOT NULL \
       AND (d.note IS NULL OR d.note NOT LIKE 'cbl-order:%') \
     ORDER BY tt.id, d.id";

/// Legacy authority: canonical unread `Dependency` blockers on the frontier.
async fn legacy_explanations<C>(
    client: &C,
    user: AuthenticatedUser,
    thread_ids: &[i32],
) -> Result<Vec<(i32, BlockingExplanation)>, ApiError>
where
    C: tokio_postgres::GenericClient + Sync,
{
    let rows = client
        .query(CANONICAL_BLOCKERS_SQL, &[&thread_ids, &user.id()])
        .await
        .map_err(db::query_error)?;
    let mut by_thread: HashMap<i32, Vec<BlockingDependency>> = HashMap::new();
    let mut seen: HashSet<(i32, i32, String)> = HashSet::new();
    for row in &rows {
        let target: i32 = row.get(0);
        let source_thread: i32 = row.get(1);
        let title: String = row.get(2);
        let number: String = row.get(3);
        if !seen.insert((target, source_thread, number.clone())) {
            continue;
        }
        let label = build_blocking_explanation(&number, &title);
        by_thread
            .entry(target)
            .or_default()
            .push(BlockingDependency {
                thread_id: source_thread,
                thread_title: title,
                issue_number: number,
                label,
                issue_id: None,
            });
    }
    Ok(thread_ids
        .iter()
        .map(|thread_id| {
            let dependencies = by_thread.remove(thread_id).unwrap_or_default();
            (
                *thread_id,
                BlockingExplanation {
                    is_blocked: !dependencies.is_empty(),
                    blocking_reasons: dependencies
                        .iter()
                        .map(|dependency| dependency.label.clone())
                        .collect(),
                    blocking_dependencies: dependencies,
                },
            )
        })
        .collect())
}

fn describe_origin(
    blocker: &crate::reading_constraints::Blocker,
    list_names: &HashMap<i32, String>,
) -> String {
    if blocker.kind == "prerequisite" {
        return if blocker.origin.as_deref() == Some("reader") {
            "Reader prerequisite".into()
        } else {
            "Converted prerequisite".into()
        };
    }
    let kind = match blocker.kind.as_str() {
        "strict_order" => "Strict order",
        "hold" => "Hold",
        "after_previous" => "Wait for previous",
        other => other,
    };
    let list = blocker
        .list_id
        .and_then(|list_id| list_names.get(&list_id))
        .map_or("Reading List", String::as_str);
    format!("{kind} in {list}")
}

/// Option E authority: live blockers from the evaluated reading graph.
async fn option_e_explanations(
    state: &AppState,
    user: AuthenticatedUser,
    thread_ids: &[i32],
) -> Result<Vec<(i32, BlockingExplanation)>, ApiError> {
    let validated = option_inputs::load_option_inputs(state, user).await?;
    let evaluated = reading_eligibility::evaluate(&validated)?;
    let inputs = validated.inputs();
    let thread_titles: HashMap<i32, &str> = inputs
        .core
        .threads
        .iter()
        .map(|thread| (thread.id, thread.title.as_str()))
        .collect();
    let issues: HashMap<i32, (i32, &str)> = inputs
        .core
        .issues
        .iter()
        .map(|issue| (issue.id, (issue.thread_id, issue.issue_number.as_str())))
        .collect();
    let list_names: HashMap<i32, String> = inputs
        .lists
        .iter()
        .map(|list| (list.list_id, list.name.clone()))
        .collect();

    let mut result = Vec::with_capacity(thread_ids.len());
    for thread_id in thread_ids {
        let state = evaluated.get(thread_id);
        let mut reasons = Vec::new();
        let mut dependencies = Vec::new();
        if let Some(state) = state {
            for gate in reading_blocker_projection::describe_blocker_gates(state.blockers.clone()) {
                let origin = describe_origin(&gate.blocker, &list_names);
                for issue_id in gate.described_issue_ids {
                    let Some((source_thread_id, number)) = issues.get(&issue_id).copied() else {
                        return Err(ApiError::Internal("Internal Server Error".into()));
                    };
                    let source_title = thread_titles
                        .get(&source_thread_id)
                        .copied()
                        .unwrap_or("Required series");
                    let issue_label = format!("{source_title} #{number}");
                    let label = format!("{origin}: waiting on {issue_label}");
                    reasons.push(label.clone());
                    dependencies.push(BlockingDependency {
                        thread_id: source_thread_id,
                        thread_title: source_title.to_string(),
                        issue_number: number.to_string(),
                        label,
                        issue_id: Some(issue_id),
                    });
                }
            }
            if state.next_issue_id.is_none() {
                reasons.push("No available unread issue".to_string());
            }
        }
        result.push((
            *thread_id,
            BlockingExplanation {
                is_blocked: state.is_some_and(|state| !state.eligible),
                blocking_reasons: reasons,
                blocking_dependencies: dependencies,
            },
        ));
    }
    Ok(result)
}

async fn blocking_details(
    state: &AppState,
    user: AuthenticatedUser,
    thread_ids: &[i32],
) -> Result<Vec<(i32, BlockingExplanation)>, ApiError> {
    if state.option_e {
        return option_e_explanations(state, user, thread_ids).await;
    }
    let connection = db::checkout(state).await?;
    legacy_explanations(&**connection, user, thread_ids).await
}

/// Dispatch `POST /api/v1/threads/{thread_id}:{action}` operations.
///
/// The router cannot express a parameter followed by `:action`, so the whole
/// segment is captured and split on the first colon. Unknown actions (and a
/// bare `POST /api/v1/threads/{id}`) are a JSON 404, like any unrouted path.
pub async fn post_thread_action(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    segment: Result<Path<String>, PathRejection>,
    body: axum::body::Bytes,
) -> Result<Response, ApiError> {
    let Path(segment) = segment.map_err(|_| validation_failed())?;
    match segment.split_once(':') {
        Some((raw_id, "getBlockingInfo")) => get_thread_blocking_info(&state, user, raw_id)
            .await
            .map(IntoResponse::into_response),
        Some((raw_id, "migrateToIssues")) => {
            thread_issues::migrate_to_issues(&state, user, raw_id, &body).await
        }
        Some((raw_id, "migrateToIssuesSimple")) => {
            thread_issues::migrate_to_issues_simple(&state, user, raw_id, &body).await
        }
        Some((raw_id, "setCurrentIssue")) => {
            thread_issues::set_current_issue(&state, user, raw_id, &body).await
        }
        _ => Err(ApiError::NotFound("Not Found".to_string())),
    }
}

async fn get_thread_blocking_info(
    state: &Arc<AppState>,
    user: AuthenticatedUser,
    raw_id: &str,
) -> Result<Json<BlockingExplanation>, ApiError> {
    let thread_id = parse_int_text(raw_id).ok_or_else(validation_failed)?;
    let state = state.as_ref();
    {
        let connection = db::checkout(state).await?;
        require_owned_thread(&**connection, user, thread_id).await?;
    }
    let mut details = blocking_details(state, user, &[thread_id]).await?;
    let (_, explanation) = details
        .pop()
        .ok_or_else(|| ApiError::Internal("Internal Server Error".into()))?;
    Ok(Json(explanation))
}

/// Coerce one JSON element the way pydantic's lax `int` does for plain values.
pub(crate) fn coerce_json_int(value: &Value) -> Option<i64> {
    match value {
        Value::Number(number) => number.as_i64().or_else(|| {
            number
                .as_f64()
                .filter(|float| float.fract() == 0.0 && float.abs() < 9.0e15)
                .map(|float| float as i64)
        }),
        Value::String(text) => {
            let trimmed = text.trim();
            let digits = trimmed.strip_prefix(['+', '-']).unwrap_or(trimmed);
            if digits.is_empty() || !digits.bytes().all(|byte| byte.is_ascii_digit()) {
                return None;
            }
            trimmed.parse().ok()
        }
        Value::Bool(flag) => Some(i64::from(*flag)),
        _ => None,
    }
}

/// Parse and validate the batch body: 1..=500 integers, de-duplicated in order.
fn parse_batch_thread_ids(body: &[u8]) -> Result<Vec<i64>, ApiError> {
    let value: Value = serde_json::from_slice(body).map_err(|_| validation_failed())?;
    let items = value
        .get("thread_ids")
        .and_then(Value::as_array)
        .ok_or_else(validation_failed)?;
    if items.is_empty() || items.len() > MAX_BATCH_THREAD_IDS {
        return Err(validation_failed());
    }
    let mut seen = BTreeSet::new();
    let mut ids = Vec::with_capacity(items.len());
    for item in items {
        let id = coerce_json_int(item).ok_or_else(validation_failed)?;
        if seen.insert(id) {
            ids.push(id);
        }
    }
    Ok(ids)
}

/// Serve `POST /api/v1/threads:getBlockingInfo`.
pub async fn get_threads_blocking_info(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    body: axum::body::Bytes,
) -> Result<Json<BatchBlockingExplanationResponse>, ApiError> {
    let requested = parse_batch_thread_ids(&body)?;
    // Ids outside the integer column range cannot name a stored thread.
    let thread_ids: Vec<i32> = requested
        .iter()
        .filter_map(|id| i32::try_from(*id).ok())
        .collect();
    let not_found = || ApiError::NotFound("One or more threads not found".to_string());
    if thread_ids.len() != requested.len() {
        return Err(not_found());
    }
    {
        let connection = db::checkout(&state).await?;
        let owned: i64 = connection
            .query_one(
                "SELECT count(*) FROM threads WHERE id = ANY($1) AND user_id = $2",
                &[&thread_ids, &user.id()],
            )
            .await
            .map_err(db::query_error)?
            .get(0);
        if owned != thread_ids.len() as i64 {
            return Err(not_found());
        }
    }
    let details = blocking_details(&state, user, &thread_ids).await?;
    Ok(Json(BatchBlockingExplanationResponse {
        threads: OrderedExplanations(details),
    }))
}

// ---------------------------------------------------------------------------
// Dependency order check / validate order
// ---------------------------------------------------------------------------

const IN_THREAD_ORDER_SQL: &str = "SELECT t.title, si.id, si.issue_number, si.position, \
            ti.id, ti.issue_number, ti.position \
     FROM dependencies d \
     JOIN issues si ON si.id = d.source_issue_id \
     JOIN issues ti ON ti.id = d.target_issue_id \
     JOIN threads t ON t.id = si.thread_id \
     WHERE t.id = $1 AND t.user_id = $2 AND ti.thread_id = t.id \
       AND si.position >= ti.position \
     ORDER BY si.position, ti.position, d.id";

/// Serve `GET /api/v1/threads/{thread_id}/dependency-order-check`.
pub async fn check_thread_dependency_order(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    thread_id: Result<Path<String>, PathRejection>,
) -> Result<Json<ThreadDependencyOrderCheckResponse>, ApiError> {
    let thread_id = parse_thread_id(thread_id)?;
    let connection = db::checkout(&state).await?;
    require_owned_thread(&**connection, user, thread_id).await?;
    let rows = connection
        .query(IN_THREAD_ORDER_SQL, &[&thread_id, &user.id()])
        .await
        .map_err(db::query_error)?;
    let conflicts = rows
        .iter()
        .map(|row| {
            let source_position: i32 = row.get(3);
            let target_position: i32 = row.get(6);
            DependencyOrderConflict {
                issue_id: row.get(1),
                issue_number: row.get(2),
                position: source_position,
                dependency_requires_before: vec![DependencyOrderRequirement {
                    issue_id: row.get(4),
                    issue_number: row.get(5),
                    position: target_position,
                }],
                conflict: format!(
                    "position {source_position} comes after issue at position {target_position}, but dependency says it must come before"
                ),
            }
        })
        .collect();
    Ok(Json(ThreadDependencyOrderCheckResponse {
        thread_id,
        conflicts,
    }))
}

/// Serve `GET /api/v1/threads/{thread_id}/issues:validateOrder`.
pub async fn validate_issue_order(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    thread_id: Result<Path<String>, PathRejection>,
) -> Result<Json<IssueOrderValidationResponse>, ApiError> {
    let thread_id = parse_thread_id(thread_id)?;
    let connection = db::checkout(&state).await?;
    require_owned_thread(&**connection, user, thread_id).await?;
    let rows = connection
        .query(IN_THREAD_ORDER_SQL, &[&thread_id, &user.id()])
        .await
        .map_err(db::query_error)?;
    let warnings = rows
        .iter()
        .map(|row| {
            let title: String = row.get(0);
            let source_number: String = row.get(2);
            let source_position: i32 = row.get(3);
            let target_number: String = row.get(5);
            let target_position: i32 = row.get(6);
            format!(
                "In thread \"{title}\", issue #{source_number} (position {source_position}) blocks issue #{target_number} (position {target_position}). Position is canonical for in-thread order."
            )
        })
        .collect();
    Ok(Json(IssueOrderValidationResponse { warnings }))
}

// ---------------------------------------------------------------------------
// Connected threads
// ---------------------------------------------------------------------------

struct DependencyRow {
    id: i32,
    source_issue_id: i32,
    target_issue_id: i32,
}

struct IssueInfo {
    thread_id: i32,
    issue_number: String,
    status: String,
}

struct ConnectedEntry {
    thread_id: i32,
    title: String,
    blocks: bool,
    blocked_by: bool,
    dependency_id: i32,
    issue_number: String,
}

/// Port of `app/services/dependency_cycle.py::build_reading_order_graph`.
fn reading_order_edges(
    dependency_edges: &[(i32, i32)],
    issues: &[(i32, i32, i32, String)],
) -> (Vec<(i32, i32)>, HashMap<i32, i32>) {
    let mut issue_threads = HashMap::new();
    let mut unread_by_thread: BTreeMap<i32, Vec<(i32, i32)>> = BTreeMap::new();
    for (issue_id, thread_id, position, status) in issues {
        issue_threads.insert(*issue_id, *thread_id);
        if status != "read" {
            unread_by_thread
                .entry(*thread_id)
                .or_default()
                .push((*position, *issue_id));
        }
    }
    let unread: HashSet<i32> = unread_by_thread
        .values()
        .flat_map(|rows| rows.iter().map(|(_, issue_id)| *issue_id))
        .collect();
    let mut edges: Vec<(i32, i32)> = dependency_edges
        .iter()
        .filter(|(source, target)| unread.contains(source) && unread.contains(target))
        .copied()
        .collect();
    for rows in unread_by_thread.values_mut() {
        rows.sort_unstable();
        for pair in rows.windows(2) {
            edges.push((pair[0].1, pair[1].1));
        }
    }
    (edges, issue_threads)
}

/// Port of `find_cyclic_component_members` (iterative Tarjan).
fn cyclic_components(edges: &[(i32, i32)]) -> Vec<BTreeSet<i32>> {
    let mut adjacency: BTreeMap<i32, Vec<i32>> = BTreeMap::new();
    for (source, target) in edges {
        adjacency.entry(*source).or_default().push(*target);
        adjacency.entry(*target).or_default();
    }
    let mut indices: HashMap<i32, usize> = HashMap::new();
    let mut lowlinks: HashMap<i32, usize> = HashMap::new();
    let mut on_stack: HashSet<i32> = HashSet::new();
    let mut stack: Vec<i32> = Vec::new();
    let mut components = Vec::new();
    let mut next_index = 0usize;
    for root in adjacency.keys().copied().collect::<Vec<_>>() {
        if indices.contains_key(&root) {
            continue;
        }
        let mut work: Vec<(i32, usize)> = vec![(root, 0)];
        while let Some(&(node, mut neighbor_index)) = work.last() {
            if let std::collections::hash_map::Entry::Vacant(slot) = indices.entry(node) {
                slot.insert(next_index);
                lowlinks.insert(node, next_index);
                next_index += 1;
                stack.push(node);
                on_stack.insert(node);
            }
            let neighbors = &adjacency[&node];
            let mut descended = false;
            while neighbor_index < neighbors.len() {
                let neighbor = neighbors[neighbor_index];
                neighbor_index += 1;
                if !indices.contains_key(&neighbor) {
                    if let Some(last) = work.last_mut() {
                        *last = (node, neighbor_index);
                    }
                    work.push((neighbor, 0));
                    descended = true;
                    break;
                }
                if on_stack.contains(&neighbor) {
                    let low = lowlinks[&node].min(indices[&neighbor]);
                    lowlinks.insert(node, low);
                }
            }
            if descended {
                continue;
            }
            if let Some(last) = work.last_mut() {
                *last = (node, neighbor_index);
            }
            work.pop();
            if let Some(&(parent, _)) = work.last() {
                let low = lowlinks[&parent].min(lowlinks[&node]);
                lowlinks.insert(parent, low);
            }
            if lowlinks[&node] == indices[&node] {
                let mut members = BTreeSet::new();
                while let Some(member) = stack.pop() {
                    on_stack.remove(&member);
                    members.insert(member);
                    if member == node {
                        break;
                    }
                }
                if members.len() > 1 || adjacency[&node].contains(&node) {
                    components.push(members);
                }
            }
        }
    }
    components
}

const CONNECTED_BLOCKING_SQL: &str = "SELECT d.id, d.source_issue_id, d.target_issue_id \
     FROM dependencies d JOIN issues si ON si.id = d.source_issue_id \
     WHERE si.thread_id = $1 AND ($2 = false OR d.origin = 'reader') \
     ORDER BY d.id";

const CONNECTED_BLOCKED_BY_SQL: &str = "SELECT d.id, d.source_issue_id, d.target_issue_id \
     FROM dependencies d JOIN issues ti ON ti.id = d.target_issue_id \
     WHERE ti.thread_id = $1 AND ($2 = false OR d.origin = 'reader') \
     ORDER BY d.id";

const READER_GRAPH_EDGES_SQL: &str = "SELECT d.source_issue_id, d.target_issue_id \
     FROM dependencies d \
     JOIN issues si ON si.id = d.source_issue_id \
     JOIN threads st ON st.id = si.thread_id \
     JOIN issues ti ON ti.id = d.target_issue_id \
     JOIN threads tt ON tt.id = ti.thread_id \
     WHERE (st.user_id = $1 OR tt.user_id = $1) \
       AND (d.note IS NULL OR d.note NOT LIKE 'cbl-order:%') \
     ORDER BY d.id";

fn dependency_rows(rows: &[tokio_postgres::Row]) -> Vec<DependencyRow> {
    rows.iter()
        .map(|row| DependencyRow {
            id: row.get(0),
            source_issue_id: row.get(1),
            target_issue_id: row.get(2),
        })
        .collect()
}

/// Serve `GET /api/v1/threads/{thread_id}/connected`.
pub async fn get_thread_connected_threads(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    thread_id: Result<Path<String>, PathRejection>,
) -> Result<Json<ThreadConnectedResponse>, ApiError> {
    let thread_id = parse_thread_id(thread_id)?;
    let connection = db::checkout(&state).await?;
    require_owned_thread(&**connection, user, thread_id).await?;

    let reader_only = state.option_e;
    let blocking = dependency_rows(
        &connection
            .query(CONNECTED_BLOCKING_SQL, &[&thread_id, &reader_only])
            .await
            .map_err(db::query_error)?,
    );
    let blocked_by = dependency_rows(
        &connection
            .query(CONNECTED_BLOCKED_BY_SQL, &[&thread_id, &reader_only])
            .await
            .map_err(db::query_error)?,
    );
    if blocking.is_empty() && blocked_by.is_empty() {
        return Ok(Json(ThreadConnectedResponse {
            thread_id,
            connected_threads: Vec::new(),
        }));
    }

    let mut issue_ids: BTreeSet<i32> = BTreeSet::new();
    for dependency in blocking.iter().chain(blocked_by.iter()) {
        issue_ids.insert(dependency.source_issue_id);
        issue_ids.insert(dependency.target_issue_id);
    }
    let issue_id_list: Vec<i32> = issue_ids.into_iter().collect();
    let issue_rows = connection
        .query(
            "SELECT id, thread_id, issue_number, status FROM issues WHERE id = ANY($1)",
            &[&issue_id_list],
        )
        .await
        .map_err(db::query_error)?;
    let issue_map: HashMap<i32, IssueInfo> = issue_rows
        .iter()
        .map(|row| {
            (
                row.get(0),
                IssueInfo {
                    thread_id: row.get(1),
                    issue_number: row.get(2),
                    status: row.get(3),
                },
            )
        })
        .collect();
    let thread_id_list: Vec<i32> = issue_map
        .values()
        .map(|issue| issue.thread_id)
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let thread_rows = connection
        .query(
            "SELECT id, title FROM threads WHERE id = ANY($1) AND user_id = $2",
            &[&thread_id_list, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let thread_map: HashMap<i32, String> = thread_rows
        .iter()
        .map(|row| (row.get(0), row.get(1)))
        .collect();

    // A prerequisite whose source issue is already read is satisfied and no
    // longer an active blocker.
    let active_blocked_by: Vec<&DependencyRow> = blocked_by
        .iter()
        .filter(|dependency| {
            issue_map
                .get(&dependency.source_issue_id)
                .is_none_or(|source| source.status != "read")
        })
        .collect();

    let mut order: Vec<i32> = Vec::new();
    let mut entries: HashMap<i32, ConnectedEntry> = HashMap::new();
    let mut connect = |other_issue_id: i32, dependency_id: i32, blocks: bool| {
        let Some(issue) = issue_map.get(&other_issue_id) else {
            return;
        };
        let Some(title) = thread_map.get(&issue.thread_id) else {
            return;
        };
        if issue.thread_id == thread_id {
            return;
        }
        match entries.get_mut(&issue.thread_id) {
            Some(entry) => {
                if blocks {
                    entry.blocks = true;
                } else {
                    entry.blocked_by = true;
                }
                entry.dependency_id = entry.dependency_id.min(dependency_id);
            }
            None => {
                order.push(issue.thread_id);
                entries.insert(
                    issue.thread_id,
                    ConnectedEntry {
                        thread_id: issue.thread_id,
                        title: title.clone(),
                        blocks,
                        blocked_by: !blocks,
                        dependency_id,
                        issue_number: issue.issue_number.clone(),
                    },
                );
            }
        }
    };
    for dependency in &blocking {
        connect(dependency.target_issue_id, dependency.id, true);
    }
    for dependency in &active_blocked_by {
        connect(dependency.source_issue_id, dependency.id, false);
    }

    // Circularity is a verdict on the effective reading precedence graph:
    // stored prerequisites plus the required within-series issue order.
    let edge_rows = connection
        .query(READER_GRAPH_EDGES_SQL, &[&user.id()])
        .await
        .map_err(db::query_error)?;
    let stored_edges: Vec<(i32, i32)> = edge_rows
        .iter()
        .map(|row| (row.get(0), row.get(1)))
        .collect();
    let graph_issue_ids: Vec<i32> = stored_edges
        .iter()
        .flat_map(|(source, target)| [*source, *target])
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let mut circular_threads: HashSet<i32> = HashSet::new();
    if !graph_issue_ids.is_empty() {
        let graph_rows = connection
            .query(
                "SELECT id, thread_id, position, status FROM issues WHERE id = ANY($1)",
                &[&graph_issue_ids],
            )
            .await
            .map_err(db::query_error)?;
        let graph_issues: Vec<(i32, i32, i32, String)> = graph_rows
            .iter()
            .map(|row| (row.get(0), row.get(1), row.get(2), row.get(3)))
            .collect();
        let (edges, graph_issue_threads) = reading_order_edges(&stored_edges, &graph_issues);
        for component in cyclic_components(&edges) {
            if component
                .iter()
                .any(|issue_id| graph_issue_threads.get(issue_id) == Some(&thread_id))
            {
                circular_threads.extend(
                    component
                        .iter()
                        .filter_map(|issue_id| graph_issue_threads.get(issue_id).copied()),
                );
            }
        }
    }

    let connected_threads = order
        .iter()
        .filter_map(|id| entries.get(id))
        .map(|entry| ConnectedThreadInfo {
            thread_id: entry.thread_id,
            title: entry.title.clone(),
            connection_type: match (entry.blocks, entry.blocked_by) {
                (true, false) => "blocks",
                (false, true) => "blocked_by",
                _ => "blocks & blocked_by",
            }
            .to_string(),
            dependency_id: entry.dependency_id,
            issue_number: Some(entry.issue_number.clone()),
            is_circular: circular_threads.contains(&entry.thread_id),
        })
        .collect();
    Ok(Json(ThreadConnectedResponse {
        thread_id,
        connected_threads,
    }))
}

// ---------------------------------------------------------------------------
// Reading orders containing a thread
// ---------------------------------------------------------------------------

/// Serve `GET /api/v1/threads/{thread_id}/reading-orders`.
///
/// Like Python this performs no thread-ownership check: only the caller's own
/// reading orders are searched, so an unknown or foreign thread yields an
/// empty list.
pub async fn get_thread_reading_orders(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    thread_id: Result<Path<String>, PathRejection>,
) -> Result<Json<ThreadReadingOrdersResponse>, ApiError> {
    let thread_id = parse_thread_id(thread_id)?;
    let connection = db::checkout(&state).await?;
    let order_rows = connection
        .query(
            "SELECT o.id, o.name, o.description FROM reading_orders o \
             WHERE o.user_id = $1 \
               AND EXISTS (SELECT 1 FROM reading_order_items i \
                           WHERE i.reading_order_id = o.id AND i.thread_id = $2) \
             ORDER BY o.id",
            &[&user.id(), &thread_id],
        )
        .await
        .map_err(db::query_error)?;
    if order_rows.is_empty() {
        return Ok(Json(ThreadReadingOrdersResponse {
            reading_orders: Vec::new(),
        }));
    }
    let order_ids: Vec<i32> = order_rows.iter().map(|row| row.get(0)).collect();
    let item_rows = connection
        .query(
            "SELECT reading_order_id, thread_id, position, issue_number \
             FROM reading_order_items WHERE reading_order_id = ANY($1) \
             ORDER BY reading_order_id, position, id",
            &[&order_ids],
        )
        .await
        .map_err(db::query_error)?;
    let item_thread_ids: Vec<i32> = item_rows
        .iter()
        .map(|row| row.get::<_, i32>(1))
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let titles: HashMap<i32, String> = connection
        .query(
            "SELECT id, title FROM threads WHERE id = ANY($1)",
            &[&item_thread_ids],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| (row.get(0), row.get(1)))
        .collect();
    let read_keys: HashSet<(i32, String)> = connection
        .query(
            "SELECT thread_id, issue_number FROM issues \
             WHERE thread_id = ANY($1) AND status = 'read'",
            &[&item_thread_ids],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| (row.get(0), row.get(1)))
        .collect();

    let mut items_by_order: HashMap<i32, Vec<ReadingOrderItemResponse>> = HashMap::new();
    for row in &item_rows {
        let order_id: i32 = row.get(0);
        let item_thread_id: i32 = row.get(1);
        let issue_number: Option<String> = row.get(3);
        let is_read = issue_number
            .as_ref()
            .is_some_and(|number| read_keys.contains(&(item_thread_id, number.clone())));
        items_by_order
            .entry(order_id)
            .or_default()
            .push(ReadingOrderItemResponse {
                thread_id: item_thread_id,
                thread_title: titles
                    .get(&item_thread_id)
                    .cloned()
                    .unwrap_or_else(|| format!("Thread {item_thread_id}")),
                position: row.get(2),
                issue_number,
                is_read,
            });
    }
    let reading_orders = order_rows
        .iter()
        .map(|row| {
            let id: i32 = row.get(0);
            let items = items_by_order.remove(&id).unwrap_or_default();
            ReadingOrderResponse {
                id,
                name: row.get(1),
                description: row.get(2),
                total_items: items.len() as i64,
                completed_items: items.iter().filter(|item| item.is_read).count() as i64,
                items,
            }
        })
        .collect();
    Ok(Json(ThreadReadingOrdersResponse { reading_orders }))
}

// ---------------------------------------------------------------------------
// OpenAPI documentation
// ---------------------------------------------------------------------------

/// Documentation-only operation for the single-thread blocking explanation.
#[utoipa::path(
    post,
    path = "/api/v1/threads/{thread_id}:getBlockingInfo",
    tag = "dependencies",
    operation_id = "thread_ordering_get_blocking_info",
    params(("thread_id" = i32, Path, description = "Owned Thread identifier")),
    responses(
        (status = 200, description = "Blocked status and reasons", body = BlockingExplanation),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_blocking_info_documentation() {}

/// Documentation-only operation for the batch blocking explanation.
#[utoipa::path(
    post,
    path = "/api/v1/threads:getBlockingInfo",
    tag = "dependencies",
    operation_id = "thread_ordering_get_threads_blocking_info",
    request_body = BatchBlockingExplanationRequest,
    responses(
        (status = 200, description = "Blocking explanations keyed by thread id", body = BatchBlockingExplanationResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "One or more threads not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_threads_blocking_info_documentation() {}

/// Documentation-only operation for connected threads.
#[utoipa::path(
    get,
    path = "/api/v1/threads/{thread_id}/connected",
    tag = "dependencies",
    operation_id = "thread_ordering_connected_threads",
    params(("thread_id" = i32, Path, description = "Owned Thread identifier")),
    responses(
        (status = 200, description = "Threads connected through dependencies", body = ThreadConnectedResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn connected_documentation() {}

/// Documentation-only operation for the dependency order check.
#[utoipa::path(
    get,
    path = "/api/v1/threads/{thread_id}/dependency-order-check",
    tag = "dependencies",
    operation_id = "thread_ordering_dependency_order_check",
    params(("thread_id" = i32, Path, description = "Owned Thread identifier")),
    responses(
        (status = 200, description = "Dependency edges that disagree with issue positions", body = ThreadDependencyOrderCheckResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn dependency_order_check_documentation() {}

/// Documentation-only operation for issue order validation.
#[utoipa::path(
    get,
    path = "/api/v1/threads/{thread_id}/issues:validateOrder",
    tag = "issues",
    operation_id = "thread_ordering_validate_order",
    params(("thread_id" = i32, Path, description = "Owned Thread identifier")),
    responses(
        (status = 200, description = "Human-readable ordering warnings", body = IssueOrderValidationResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread not found"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn validate_order_documentation() {}

/// Documentation-only operation for reading orders containing a thread.
#[utoipa::path(
    get,
    path = "/api/v1/threads/{thread_id}/reading-orders",
    tag = "reading-orders",
    operation_id = "thread_ordering_reading_orders",
    params(("thread_id" = i32, Path, description = "Thread identifier")),
    responses(
        (status = 200, description = "Owned reading orders containing the thread", body = ThreadReadingOrdersResponse),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Request validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn thread_reading_orders_documentation() {}

/// OpenAPI document for the native same-path thread ordering surface.
#[derive(utoipa::OpenApi)]
#[openapi(
    info(
        title = "ComicPile native same-path thread ordering API",
        version = "1.0.0",
        description = "Generated contract for the native thread ordering and dependency-inspection handlers that retain their original method and path."
    ),
    paths(
        get_blocking_info_documentation,
        get_threads_blocking_info_documentation,
        connected_documentation,
        dependency_order_check_documentation,
        validate_order_documentation,
        thread_reading_orders_documentation
    ),
    components(schemas(
        BlockingDependency,
        BlockingExplanation,
        OrderedExplanations,
        BatchBlockingExplanationRequest,
        BatchBlockingExplanationResponse,
        ConnectedThreadInfo,
        ThreadConnectedResponse,
        DependencyOrderRequirement,
        DependencyOrderConflict,
        ThreadDependencyOrderCheckResponse,
        IssueOrderValidationResponse,
        ReadingOrderItemResponse,
        ReadingOrderResponse,
        ThreadReadingOrdersResponse
    )),
    modifiers(&ThreadOrderingSecurityAddon)
)]
pub struct ThreadOrderingApi;

struct ThreadOrderingSecurityAddon;
impl utoipa::Modify for ThreadOrderingSecurityAddon {
    fn modify(&self, openapi: &mut utoipa::openapi::OpenApi) {
        if let Some(components) = openapi.components.as_mut() {
            components.add_security_scheme(
                "HTTPBearer",
                utoipa::openapi::security::SecurityScheme::Http(
                    utoipa::openapi::security::Http::new(
                        utoipa::openapi::security::HttpAuthScheme::Bearer,
                    ),
                ),
            );
        }
    }
}

/// Emit the same-path native thread ordering contract.
pub fn thread_ordering_openapi() -> utoipa::openapi::OpenApi {
    use utoipa::OpenApi;
    ThreadOrderingApi::openapi()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn path_ids_follow_integer_path_semantics() {
        assert_eq!(parse_int_text("12"), Some(12));
        assert_eq!(parse_int_text("-3"), Some(-3));
        assert_eq!(parse_int_text("+4"), Some(4));
        assert_eq!(parse_int_text("1.5"), None);
        assert_eq!(parse_int_text("abc"), None);
        assert_eq!(parse_int_text(""), None);
        assert_eq!(parse_int_text("99999999999999999999"), None);
    }

    #[test]
    fn batch_body_validation_and_deduplication() {
        assert_eq!(
            parse_batch_thread_ids(br#"{"thread_ids":[3,1,3,2,"1"]}"#).unwrap(),
            vec![3, 1, 2]
        );
        for bad in [
            &br#"{"thread_ids":[]}"#[..],
            br#"{}"#,
            br#"{"thread_ids":"1"}"#,
            br#"{"thread_ids":[null]}"#,
            br#"{"thread_ids":["x"]}"#,
            b"not json",
        ] {
            assert!(parse_batch_thread_ids(bad).is_err());
        }
        let too_many = format!(
            "{{\"thread_ids\":[{}]}}",
            (1..=501)
                .map(|n| n.to_string())
                .collect::<Vec<_>>()
                .join(",")
        );
        assert!(parse_batch_thread_ids(too_many.as_bytes()).is_err());
    }

    #[test]
    fn ordered_batch_response_keeps_request_order() {
        let explanation = |blocked| BlockingExplanation {
            is_blocked: blocked,
            blocking_reasons: vec![],
            blocking_dependencies: vec![],
        };
        let response = BatchBlockingExplanationResponse {
            threads: OrderedExplanations(vec![(10, explanation(false)), (2, explanation(true))]),
        };
        let text = serde_json::to_string(&response).unwrap();
        assert!(text.find("\"10\"").unwrap() < text.find("\"2\"").unwrap());
    }

    #[test]
    fn interleaved_series_are_not_circular_but_backward_chain_is() {
        // issue: (id, thread, position, status)
        let issues = vec![
            (1, 100, 1, "unread".to_string()),
            (2, 100, 2, "unread".to_string()),
            (3, 200, 1, "unread".to_string()),
        ];
        // A#1 -> B#1 -> A#2: interleaved, acyclic with series order.
        let (edges, _) = reading_order_edges(&[(1, 3), (3, 2)], &issues);
        assert!(cyclic_components(&edges).is_empty());
        // A#2 -> B#1 -> A#1: backward chain closes a loop with A#1 -> A#2.
        let (edges, _) = reading_order_edges(&[(2, 3), (3, 1)], &issues);
        let components = cyclic_components(&edges);
        assert_eq!(components.len(), 1);
        assert_eq!(components[0], BTreeSet::from([1, 2, 3]));
    }

    #[test]
    fn read_issues_do_not_participate_in_cycles() {
        let issues = vec![
            (1, 100, 1, "read".to_string()),
            (2, 100, 2, "unread".to_string()),
            (3, 200, 1, "unread".to_string()),
        ];
        let (edges, _) = reading_order_edges(&[(2, 3), (3, 1)], &issues);
        assert!(cyclic_components(&edges).is_empty());
    }

    #[test]
    fn contract_documents_every_operation_and_stays_current() {
        let document = serde_json::to_value(thread_ordering_openapi()).unwrap();
        for path in [
            "/api/v1/threads/{thread_id}:getBlockingInfo",
            "/api/v1/threads:getBlockingInfo",
            "/api/v1/threads/{thread_id}/connected",
            "/api/v1/threads/{thread_id}/dependency-order-check",
            "/api/v1/threads/{thread_id}/issues:validateOrder",
            "/api/v1/threads/{thread_id}/reading-orders",
        ] {
            assert!(document["paths"].get(path).is_some(), "{path}");
        }
    }
}
