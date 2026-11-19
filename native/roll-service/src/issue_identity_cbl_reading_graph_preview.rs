//! Same-path Rust cutover of
//! `POST /api/v1/issue-identity/cbl/{list_id}/reading-graph-preview`.
//!
//! Faithful port of `app/services/reading_graph_preview_service.py`: the
//! prospective graph a reader would get by adopting (or updating a list from) a
//! CBL selection. It reconciles the source list with the same code as the
//! adoption plan, substitutes the proposed list into the reader's complete
//! owner snapshot, and evaluates it with a pure Option E evaluator
//! (`reading_preview_eval`) plus the stored-constraint cycle validator. Series
//! are exact Comic Vine volumes, overlap questions carry both choice effects,
//! and nothing is written. All reads share one repeatable-read read-only
//! snapshot; there are no per-row queries.

use crate::{
    auth::AuthenticatedUser,
    db,
    issue_identity::{
        load_active_cbl_list_meta, reconcile_entries_for_adoption_positions, sha256_hex,
    },
    option_inputs::{self, normalize_volume, OptionInputs, ReadingEntry},
    preview_validation::{parse_body_object, parse_path_int, validation_failed},
    reading_blocker_projection::{describe_blocker_gates, DescribedBlockerGate},
    reading_constraints::{self, Blocker, ThreadEligibility, ValidationError},
    reading_preview_eval::{evaluate, Decision, EvalInput, ProposedList},
    thread_ordering::coerce_json_int,
    ApiError, AppState,
};
use axum::{
    body::Bytes,
    extract::{rejection::PathRejection, Path, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::{BTreeMap, BTreeSet, HashMap, HashSet},
    sync::Arc,
};
use tokio_postgres::IsolationLevel;
use unicode_casefold::UnicodeCaseFold;
use utoipa::ToSchema;

/// Small response error used instead of returning a large Axum `Response` from
/// helpers (see `clippy::result_large_err`).
#[derive(Debug)]
pub enum PreviewError {
    Api(ApiError),
    Json(StatusCode, Value),
}

impl From<ApiError> for PreviewError {
    fn from(error: ApiError) -> Self {
        Self::Api(error)
    }
}

impl IntoResponse for PreviewError {
    fn into_response(self) -> Response {
        match self {
            Self::Api(error) => error.into_response(),
            Self::Json(status, body) => (status, Json(body)).into_response(),
        }
    }
}

#[derive(Debug, Deserialize, ToSchema)]
pub struct ReadingGraphPreviewRequest {
    #[serde(default)]
    pub included_positions: Vec<i64>,
    #[serde(default)]
    pub overlap_choices: Vec<ReadingGraphOverlapChoice>,
    pub target_list_id: Option<i64>,
}

#[derive(Debug, Deserialize, ToSchema)]
pub struct ReadingGraphOverlapChoice {
    pub overlap_id: String,
    pub choice: String,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphPreview {
    pub source_list_id: i64,
    pub content_hash: String,
    pub revision_sha: String,
    pub series: Vec<ReadingGraphSeriesNode>,
    pub overlaps: Vec<ReadingGraphOverlap>,
    pub issues: Vec<ReadingGraphIssueReference>,
    pub rollable_issue_ids: Vec<i64>,
    pub waiting_issue_ids: Vec<i64>,
    pub cycle_errors: Vec<ReadingGraphCycleError>,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReadingGraphSeriesReference {
    pub comicvine_volume_id: String,
    pub series_name: String,
    pub year: Option<i64>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphSeriesNode {
    pub comicvine_volume_id: String,
    pub series_name: String,
    pub year: Option<i64>,
    pub state: String,
    pub unread_count: i64,
    pub rollable_count: i64,
    pub waiting_count: i64,
    pub waits_for_issue_ids: Vec<i64>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphBlocker {
    pub kind: String,
    pub list_id: Option<i64>,
    pub waiting_on_issue_ids: Vec<i64>,
    pub gate_issue_id: Option<i64>,
    pub explanation: String,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphIssueReference {
    pub issue_id: i64,
    pub series_name: String,
    pub issue_number: String,
    pub comicvine_volume_id: Option<String>,
    pub blockers: Vec<ReadingGraphBlocker>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphOverlap {
    pub overlap_id: String,
    pub continuing_series: ReadingGraphSeriesReference,
    pub waiting_series: ReadingGraphSeriesReference,
    pub question: String,
    pub blocked_issue_ids: Vec<i64>,
    pub choices: Vec<ReadingGraphChoiceEffect>,
    pub selected_choice: Option<String>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphChoiceEffect {
    pub choice: String,
    pub label: String,
    pub detail: String,
    pub rollable_issue_ids: Vec<i64>,
    pub waiting_issue_ids: Vec<i64>,
    pub series: Vec<ReadingGraphSeriesNode>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ReadingGraphCycleError {
    pub code: String,
    pub message: String,
}

fn structured_error(status: StatusCode, code: &str, message: String) -> PreviewError {
    PreviewError::Json(
        status,
        serde_json::json!({ "detail": { "code": code, "message": message } }),
    )
}

fn unprocessable(code: &str, message: String) -> PreviewError {
    structured_error(StatusCode::UNPROCESSABLE_ENTITY, code, message)
}

const CHOICE_PROTECT: &str = "protect_order";
const CHOICE_CONTINUE: &str = "continue_series";

/// Parse the body like `ReadingGraphPreviewRequest`. Any pydantic rejection is
/// the production `{"detail": "Validation failed"}` 422.
fn parse_request(body: &[u8]) -> Result<ReadingGraphPreviewRequest, ApiError> {
    let map = parse_body_object(body)?;
    let included_positions = match map.get("included_positions") {
        None => Vec::new(),
        Some(Value::Array(items)) if items.len() <= 10_000 => items
            .iter()
            .map(|item| coerce_json_int(item).filter(|position| *position > 0))
            .collect::<Option<Vec<i64>>>()
            .ok_or_else(validation_failed)?,
        Some(_) => return Err(validation_failed()),
    };
    let overlap_choices = match map.get("overlap_choices") {
        None => Vec::new(),
        Some(Value::Array(items)) if items.len() <= 1_000 => items
            .iter()
            .map(|item| {
                let object = item.as_object()?;
                let overlap_id = object.get("overlap_id")?.as_str()?;
                let choice = object.get("choice")?.as_str()?;
                let length = overlap_id.chars().count();
                ((1..=300).contains(&length) && matches!(choice, CHOICE_PROTECT | CHOICE_CONTINUE))
                    .then(|| ReadingGraphOverlapChoice {
                        overlap_id: overlap_id.to_string(),
                        choice: choice.to_string(),
                    })
            })
            .collect::<Option<Vec<_>>>()
            .ok_or_else(validation_failed)?,
        Some(_) => return Err(validation_failed()),
    };
    let target_list_id = match map.get("target_list_id") {
        None | Some(Value::Null) => None,
        Some(value) => Some(
            coerce_json_int(value)
                .filter(|id| *id > 0)
                .ok_or_else(validation_failed)?,
        ),
    };
    Ok(ReadingGraphPreviewRequest {
        included_positions,
        overlap_choices,
        target_list_id,
    })
}

/// Python `canonical_volume_key`: `comicvine:<normalized id>` or `None`.
fn canonical_volume_key(provider: &str, external_id: &str) -> Option<String> {
    let (provider, value) = normalize_volume(provider, external_id);
    (provider == "comicvine" && !value.is_empty()).then(|| format!("comicvine:{value}"))
}

/// Stored external-id spellings that can produce one volume key.
fn external_id_candidates(key: &str) -> Vec<String> {
    let Some(external_id) = key.strip_prefix("comicvine:") else {
        return Vec::new();
    };
    let mut values = BTreeSet::from([external_id.to_string()]);
    let numeric = external_id.strip_prefix("4050-").unwrap_or(external_id);
    if !numeric.is_empty() && numeric.bytes().all(|byte| byte.is_ascii_digit()) {
        values.insert(numeric.to_string());
        values.insert(format!("4050-{numeric}"));
    }
    values.into_iter().collect()
}

/// A stored publication year from provider metadata, when valid.
fn metadata_year(metadata: &Value) -> Option<i32> {
    let object = metadata.as_object()?;
    ["start_year", "year", "volume_year"]
        .iter()
        .filter_map(|field| object.get(*field)?.as_i64())
        .find(|value| (1000..=9999).contains(value))
        .and_then(|value| i32::try_from(value).ok())
}

async fn load_volume_years<E: crate::issue_identity::DbExec>(
    tx: &E,
    keys: &BTreeSet<String>,
) -> Result<HashMap<String, i32>, ApiError> {
    let spellings: Vec<String> = keys
        .iter()
        .flat_map(|key| external_id_candidates(key))
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    if spellings.is_empty() {
        return Ok(HashMap::new());
    }
    let rows = tx
        .run_query(
            "SELECT external_id, metadata_json::text FROM external_identities \
             WHERE provider = 'comicvine' AND entity_type = 'series' \
               AND external_id = ANY($1::text[]) ORDER BY id",
            &[&spellings],
        )
        .await
        .map_err(db::query_error)?;
    let mut years = HashMap::new();
    for row in rows {
        let external_id: String = row.get(0);
        let metadata: Option<String> = row.get(1);
        let Some(key) = canonical_volume_key("comicvine", &external_id) else {
            continue;
        };
        if !keys.contains(&key) {
            continue;
        }
        let metadata = metadata
            .and_then(|text| serde_json::from_str::<Value>(&text).ok())
            .unwrap_or(Value::Null);
        if let Some(year) = metadata_year(&metadata) {
            years.insert(key, year);
        }
    }
    Ok(years)
}

#[derive(Debug, Clone)]
struct IssueMeta {
    thread_id: i32,
    issue_number: String,
    position: i32,
    status: String,
}

/// Immutable graph facts shared by the top-level preview and choice effects.
struct Context<'a> {
    input: EvalInput<'a>,
    graph_thread_ids: BTreeSet<i32>,
    graph_issue_ids: BTreeSet<i32>,
    issue_meta: HashMap<i32, IssueMeta>,
    volume_by_thread: &'a BTreeMap<i32, String>,
    series_refs: HashMap<String, ReadingGraphSeriesReference>,
    list_names: HashMap<i32, String>,
    thread_names: HashMap<i32, &'a str>,
}

impl Context<'_> {
    fn volume_of_issue(&self, issue_id: i32) -> Option<&str> {
        let thread_id = self.issue_meta.get(&issue_id)?.thread_id;
        self.volume_by_thread.get(&thread_id).map(String::as_str)
    }

    fn thread_name_or_default(&self, thread_id: i32) -> String {
        self.thread_names
            .get(&thread_id)
            .map_or_else(|| format!("Series {thread_id}"), |name| (*name).to_string())
    }

    fn series_name_of_issue(&self, issue_id: i32) -> String {
        let reference = self
            .volume_of_issue(issue_id)
            .and_then(|volume| self.series_refs.get(volume));
        match (reference, self.issue_meta.get(&issue_id)) {
            (Some(reference), _) => reference.series_name.clone(),
            (None, Some(meta)) => self.thread_name_or_default(meta.thread_id),
            (None, None) => String::new(),
        }
    }

    fn issue_label(&self, issue_id: i32) -> String {
        let number = self
            .issue_meta
            .get(&issue_id)
            .map_or("", |meta| meta.issue_number.as_str());
        format!("{} #{number}", self.series_name_of_issue(issue_id))
    }

    fn is_unread_unexcluded(&self, issue_id: i32) -> bool {
        self.issue_meta
            .get(&issue_id)
            .is_some_and(|meta| meta.status != "read")
            && !self.input.inputs.excluded_issue_ids.contains(&issue_id)
    }
}

fn series_reference(
    volume_id: Option<&str>,
    thread_id: i32,
    thread_names: &HashMap<i32, &str>,
    source_names: &HashMap<String, (String, Option<i32>)>,
    volume_years: &HashMap<String, i32>,
) -> ReadingGraphSeriesReference {
    let thread_name = thread_names.get(&thread_id).copied().unwrap_or_default();
    match volume_id {
        None => ReadingGraphSeriesReference {
            comicvine_volume_id: format!("unidentified-thread:{thread_id}"),
            series_name: if thread_name.is_empty() {
                format!("Series {thread_id}")
            } else {
                thread_name.to_string()
            },
            year: None,
        },
        Some(volume) => {
            let (source_name, source_year) = source_names
                .get(volume)
                .map_or(("", None), |(name, year)| (name.as_str(), *year));
            let series_name = [source_name, thread_name, volume]
                .into_iter()
                .find(|name| !name.is_empty())
                .unwrap_or_default();
            ReadingGraphSeriesReference {
                comicvine_volume_id: volume.to_string(),
                series_name: series_name.to_string(),
                year: source_year
                    .or_else(|| volume_years.get(volume).copied())
                    .map(i64::from),
            }
        }
    }
}

fn node_key(volume: Option<&String>, thread_id: i32) -> String {
    volume.map_or_else(|| format!("unidentified-thread:{thread_id}"), Clone::clone)
}

#[derive(Default)]
struct SeriesAggregate {
    thread_id: i32,
    unread: i64,
    rollable: BTreeSet<i32>,
    waiting: BTreeSet<i32>,
    waits_for: BTreeSet<i32>,
}

fn blocker_thread_ids(
    context: &Context<'_>,
    eligibility: &BTreeMap<i32, ThreadEligibility>,
) -> BTreeSet<i32> {
    eligibility
        .values()
        .flat_map(|state| &state.blockers)
        .flat_map(|blocker| &blocker.waiting_on_issue_ids)
        .filter_map(|issue_id| context.issue_meta.get(issue_id).map(|meta| meta.thread_id))
        .collect()
}

/// Project evaluator state onto exact-volume series nodes.
fn series_nodes(
    context: &Context<'_>,
    eligibility: &BTreeMap<i32, ThreadEligibility>,
) -> Vec<ReadingGraphSeriesNode> {
    let inputs = context.input.inputs;
    let active: HashSet<i32> = inputs
        .core
        .threads
        .iter()
        .filter(|thread| thread.status == "active")
        .map(|thread| thread.id)
        .collect();
    let blocking_threads = blocker_thread_ids(context, eligibility);
    let mut unread_by_thread: HashMap<i32, Vec<i32>> = HashMap::new();
    let mut graph_issues: Vec<(&i32, &IssueMeta)> = context
        .issue_meta
        .iter()
        .filter(|(issue_id, _)| context.graph_issue_ids.contains(issue_id))
        .collect();
    graph_issues.sort_by_key(|(issue_id, _)| **issue_id);
    for (issue_id, meta) in graph_issues {
        if context.is_unread_unexcluded(*issue_id) {
            unread_by_thread
                .entry(meta.thread_id)
                .or_default()
                .push(*issue_id);
        }
    }
    let mut grouped: BTreeMap<String, SeriesAggregate> = BTreeMap::new();
    let mut order: Vec<String> = Vec::new();
    for thread_id in &context.graph_thread_ids {
        if !active.contains(thread_id) && !blocking_threads.contains(thread_id) {
            continue;
        }
        let key = node_key(context.volume_by_thread.get(thread_id), *thread_id);
        let unread_ids = unread_by_thread.get(thread_id).cloned().unwrap_or_default();
        let state = eligibility.get(thread_id);
        let mut rollable: BTreeSet<i32> = BTreeSet::new();
        let mut waits_for: BTreeSet<i32> = BTreeSet::new();
        if let Some(state) = state {
            if let Some(next) = state.next_issue_id {
                if state.eligible && context.graph_issue_ids.contains(&next) {
                    rollable.insert(next);
                }
                for blocker in &state.blockers {
                    for issue_id in &blocker.waiting_on_issue_ids {
                        if context
                            .issue_meta
                            .get(issue_id)
                            .is_some_and(|meta| meta.thread_id != *thread_id)
                        {
                            waits_for.insert(*issue_id);
                        }
                    }
                }
            }
        }
        if !grouped.contains_key(&key) {
            order.push(key.clone());
        }
        let aggregate = grouped.entry(key).or_insert_with(|| SeriesAggregate {
            thread_id: *thread_id,
            ..SeriesAggregate::default()
        });
        aggregate.unread += unread_ids.len() as i64;
        for issue_id in &unread_ids {
            if rollable.contains(issue_id) {
                aggregate.rollable.insert(*issue_id);
            } else {
                aggregate.waiting.insert(*issue_id);
            }
        }
        aggregate
            .waits_for
            .extend(waits_for.into_iter().filter(|issue_id| {
                context.graph_issue_ids.contains(issue_id)
                    && context.is_unread_unexcluded(*issue_id)
            }));
    }
    let mut nodes: Vec<ReadingGraphSeriesNode> = order
        .into_iter()
        .map(|key| {
            let aggregate = &grouped[&key];
            let reference = context.series_refs.get(&key).cloned().unwrap_or_else(|| {
                ReadingGraphSeriesReference {
                    comicvine_volume_id: key.clone(),
                    series_name: context.thread_name_or_default(aggregate.thread_id),
                    year: None,
                }
            });
            let state = match (aggregate.rollable.is_empty(), aggregate.waiting.is_empty()) {
                (false, false) => "mixed",
                (false, true) => "continues",
                _ => "waits",
            };
            ReadingGraphSeriesNode {
                comicvine_volume_id: reference.comicvine_volume_id,
                series_name: reference.series_name,
                year: reference.year,
                state: state.to_string(),
                unread_count: aggregate.unread,
                rollable_count: aggregate.rollable.len() as i64,
                waiting_count: aggregate.waiting.len() as i64,
                waits_for_issue_ids: aggregate
                    .waits_for
                    .iter()
                    .map(|id| i64::from(*id))
                    .collect(),
            }
        })
        .collect();
    nodes.sort_by_cached_key(|node| {
        (
            node.series_name.case_fold().collect::<String>(),
            node.year.unwrap_or(0),
            node.comicvine_volume_id.clone(),
        )
    });
    nodes
}

fn blocker_explanation(context: &Context<'_>, gate: &DescribedBlockerGate) -> String {
    let blocker = &gate.blocker;
    let label = if blocker.kind == "prerequisite" {
        if blocker.origin.as_deref() == Some("reader") {
            "Reader prerequisite".to_string()
        } else {
            "Converted prerequisite".to_string()
        }
    } else {
        let kind = match blocker.kind.as_str() {
            "strict_order" => "Strict order",
            "hold" => "Hold",
            _ => "Wait for previous",
        };
        let list_name = blocker
            .list_id
            .and_then(|id| context.list_names.get(&id))
            .map_or("Reading List", String::as_str);
        format!("{kind} in {list_name}")
    };
    if gate.described_issue_ids.is_empty() {
        return format!("Also gated by {label}.");
    }
    let waiting = gate
        .described_issue_ids
        .iter()
        .map(|issue_id| context.issue_label(*issue_id))
        .collect::<Vec<_>>()
        .join(", ");
    format!("{label}: waiting on {waiting}")
}

fn issue_references(
    context: &Context<'_>,
    eligibility: &BTreeMap<i32, ThreadEligibility>,
) -> Vec<ReadingGraphIssueReference> {
    let mut ids: Vec<i32> = context.graph_issue_ids.iter().copied().collect();
    ids.sort_by_key(|issue_id| {
        let meta = &context.issue_meta[issue_id];
        (meta.position, meta.thread_id, *issue_id)
    });
    ids.into_iter()
        .map(|issue_id| {
            let meta = &context.issue_meta[&issue_id];
            let blockers = eligibility
                .get(&meta.thread_id)
                .filter(|state| state.next_issue_id == Some(issue_id))
                .map(|state| {
                    describe_blocker_gates(state.blockers.clone())
                        .into_iter()
                        .map(|gate| ReadingGraphBlocker {
                            kind: gate.blocker.kind.clone(),
                            list_id: gate.blocker.list_id.map(i64::from),
                            waiting_on_issue_ids: gate
                                .described_issue_ids
                                .iter()
                                .map(|id| i64::from(*id))
                                .collect(),
                            gate_issue_id: gate.blocker.gate_issue_id.map(i64::from),
                            explanation: blocker_explanation(context, &gate),
                        })
                        .collect()
                })
                .unwrap_or_default();
            ReadingGraphIssueReference {
                issue_id: i64::from(issue_id),
                series_name: context.series_name_of_issue(issue_id),
                issue_number: meta.issue_number.clone(),
                comicvine_volume_id: context.volume_of_issue(issue_id).map(str::to_string),
                blockers,
            }
        })
        .collect()
}

fn rollable_ids(context: &Context<'_>, eligibility: &BTreeMap<i32, ThreadEligibility>) -> Vec<i32> {
    let mut ids: Vec<i32> = eligibility
        .values()
        .filter(|state| state.eligible)
        .filter_map(|state| state.next_issue_id)
        .filter(|issue_id| context.graph_issue_ids.contains(issue_id))
        .collect();
    ids.sort_unstable();
    ids
}

fn waiting_ids(context: &Context<'_>, eligibility: &BTreeMap<i32, ThreadEligibility>) -> Vec<i32> {
    let rollable: HashSet<i32> = rollable_ids(context, eligibility).into_iter().collect();
    let mut ids: Vec<i32> = context
        .graph_issue_ids
        .iter()
        .copied()
        .filter(|issue_id| context.is_unread_unexcluded(*issue_id) && !rollable.contains(issue_id))
        .collect();
    ids.sort_unstable();
    ids
}

fn wire_ids(ids: Vec<i32>) -> Vec<i64> {
    ids.into_iter().map(i64::from).collect()
}

/// Follow every active blocker until the graph names all relevant series.
fn expand_graph_threads(
    context_issue_meta: &HashMap<i32, IssueMeta>,
    eligibility: &BTreeMap<i32, ThreadEligibility>,
    seeds: BTreeSet<i32>,
) -> BTreeSet<i32> {
    let mut thread_ids = seeds;
    loop {
        let discovered: BTreeSet<i32> = thread_ids
            .iter()
            .filter_map(|thread_id| eligibility.get(thread_id))
            .flat_map(|state| &state.blockers)
            .flat_map(|blocker| &blocker.waiting_on_issue_ids)
            .filter_map(|issue_id| context_issue_meta.get(issue_id).map(|meta| meta.thread_id))
            .collect();
        let before = thread_ids.len();
        thread_ids.extend(discovered);
        if thread_ids.len() == before {
            return thread_ids;
        }
    }
}

fn overlap_identity(continuing: &str, waiting: &str) -> String {
    let digest = sha256_hex(format!("{continuing}\0{waiting}").as_bytes());
    format!("overlap-{}", &digest[..24])
}

/// Translate reader answers into evaluator overlap decisions (sorted by pair).
fn decisions_for(chosen: &BTreeMap<(String, String), String>) -> Vec<Decision> {
    chosen
        .iter()
        .filter(|(_, choice)| choice.as_str() == CHOICE_CONTINUE)
        .map(|(pair, _)| pair.clone())
        .collect()
}

fn choice_effect(
    context: &Context<'_>,
    choice: &str,
    decisions: &[Decision],
    continuing: &ReadingGraphSeriesReference,
    waiting: &ReadingGraphSeriesReference,
) -> ReadingGraphChoiceEffect {
    let eligibility = evaluate(&context.input, decisions);
    let (label, detail) = if choice == CHOICE_CONTINUE {
        (
            format!(
                "Let {} continue; {} waits",
                continuing.series_name, waiting.series_name
            ),
            format!(
                "Removes the ordering restriction between {} and {}; other prerequisites and \
                 restrictions still apply.",
                continuing.series_name, waiting.series_name
            ),
        )
    } else {
        (
            "Keep the full chosen order".to_string(),
            format!(
                "{} waits for every earlier unread {} comic before it continues.",
                continuing.series_name, waiting.series_name
            ),
        )
    };
    ReadingGraphChoiceEffect {
        choice: choice.to_string(),
        label,
        detail,
        rollable_issue_ids: wire_ids(rollable_ids(context, &eligibility)),
        waiting_issue_ids: wire_ids(waiting_ids(context, &eligibility)),
        series: series_nodes(context, &eligibility),
    }
}

/// The validator's explanation of an invalid proposed graph (empty when valid).
fn cycle_errors(
    context: &Context<'_>,
    decisions: &[Decision],
) -> Result<Vec<ReadingGraphCycleError>, ApiError> {
    let inputs = context.input.inputs;
    let proposed = context.input.proposed;
    let lists = context
        .input
        .owned_lists
        .iter()
        .map(|list| reading_constraints::List {
            list_id: list.list_id,
            mode: list.mode.clone(),
            name: list.name.clone(),
            entries: list.entries.iter().map(constraint_entry).collect(),
            overlap_decisions: Vec::new(),
        })
        .chain(std::iter::once(reading_constraints::List {
            list_id: proposed.id,
            mode: proposed.mode.clone(),
            name: proposed.name.clone(),
            entries: proposed.entries.iter().map(constraint_entry).collect(),
            overlap_decisions: decisions
                .iter()
                .map(|(continuing, waiting)| reading_constraints::Overlap {
                    continuing_volume_id: continuing.clone(),
                    waiting_volume_id: waiting.clone(),
                })
                .collect(),
        }))
        .collect();
    let snapshot = reading_constraints::Snapshot {
        threads: inputs
            .core
            .threads
            .iter()
            .map(|thread| reading_constraints::Thread {
                thread_id: thread.id,
                name: thread.title.clone(),
                comicvine_volume_id: inputs.thread_volumes.get(&thread.id).cloned(),
            })
            .collect(),
        issues: inputs
            .core
            .issues
            .iter()
            .map(|issue| reading_constraints::Issue {
                issue_id: issue.id,
                thread_id: issue.thread_id,
                position: issue.position,
            })
            .collect(),
        lists,
        prerequisites: context
            .input
            .prerequisites
            .iter()
            .map(|p| reading_constraints::Prerequisite {
                prerequisite_id: p.prerequisite_id,
                source_issue_id: p.source_issue_id,
                target_issue_id: p.target_issue_id,
                origin: p.origin.clone(),
                provenance: p.provenance.clone(),
            })
            .collect(),
        excluded_issue_ids: inputs.excluded_issue_ids.clone(),
    };
    match reading_constraints::validate(&snapshot) {
        Ok(_) => Ok(Vec::new()),
        Err(ValidationError::Cycle { edges, .. }) => {
            let path = edges
                .iter()
                .map(|edge| {
                    format!(
                        "{} --[{}]--> {}",
                        context.issue_label(edge.source_issue_id),
                        edge.origin,
                        context.issue_label(edge.target_issue_id)
                    )
                })
                .collect::<Vec<_>>()
                .join(" -> ");
            Ok(vec![ReadingGraphCycleError {
                code: "reading_constraint_cycle".to_string(),
                message: format!("Reading constraint cycle: {path}"),
            }])
        }
        Err(ValidationError::InvalidSnapshot { message }) => {
            tracing::error!(%message, "reading-graph preview snapshot invalid");
            Err(ApiError::Internal("Internal Server Error".to_string()))
        }
    }
}

fn constraint_entry(entry: &ReadingEntry) -> reading_constraints::Entry {
    reading_constraints::Entry {
        issue_id: entry.issue_id,
        gate: entry.gate.clone(),
        skipped: entry.skipped,
    }
}

#[utoipa::path(
    post,
    path = "/api/v1/issue-identity/cbl/{list_id}/reading-graph-preview",
    operation_id = "preview_cbl_reading_graph_api_v1_issue_identity_cbl__list_id__reading_graph_preview_post",
    request_body = ReadingGraphPreviewRequest,
    params(("list_id" = i64, Path, description = "CBL source list id")),
    responses(
        (status = 200, description = "Read-only graph preview", body = ReadingGraphPreview),
        (status = 401, description = "Unauthorized"),
        (status = 404, description = "CBL source list or target reading list not found"),
        (status = 422, description = "Validation failed, or unknown/unresolved source position or overlap answer"),
    ),
    security(("HTTPBearer" = []))
)]
pub fn documentation() {}

/// Everything read from the database for one preview, from one snapshot.
struct Loaded {
    content_hash: String,
    revision_sha: String,
    list_name: String,
    entries: Vec<serde_json::Map<String, Value>>,
    inputs: OptionInputs,
    volume_years: HashMap<String, i32>,
}

async fn load(
    state: &AppState,
    user: AuthenticatedUser,
    list_id: i64,
    included_positions: &[i64],
) -> Result<Loaded, PreviewError> {
    let not_found = || {
        structured_error(
            StatusCode::NOT_FOUND,
            "cbl_source_not_found",
            format!("CBL source list {list_id} was not found or is inactive"),
        )
    };
    // `cbl_source_lists.id` is an int4 column: an id outside that domain cannot
    // match a row and is the same 404 as a missing/inactive list.
    let list_key = i32::try_from(list_id).map_err(|_| not_found())?;
    let mut connection = db::checkout(state).await?;
    let tx = connection
        .build_transaction()
        .isolation_level(IsolationLevel::RepeatableRead)
        .read_only(true)
        .start()
        .await
        .map_err(db::query_error)?;
    let meta = match load_active_cbl_list_meta(&tx, list_key).await {
        Ok(meta) => meta,
        Err(ApiError::NotFound(_)) => return Err(not_found()),
        Err(error) => return Err(error.into()),
    };
    // Reconcile only the selected positions: the generic adoption helper walks
    // the entire source list and issues per-entry lookups, which would turn a
    // short preview selection into a full-list fan-out (#5342 review).
    let entries =
        reconcile_entries_for_adoption_positions(&tx, user.id(), &meta, included_positions).await?;
    let inputs = option_inputs::load_inputs_in_transaction(&tx, user).await?;
    let keys: BTreeSet<String> = inputs.thread_volumes.values().cloned().collect();
    let volume_years = load_volume_years(&tx, &keys).await?;
    tx.rollback().await.map_err(db::query_error)?;
    Ok(Loaded {
        content_hash: meta.content_hash,
        revision_sha: meta.revision_sha,
        list_name: meta.name,
        entries,
        inputs,
        volume_years,
    })
}

fn entry_position(entry: &serde_json::Map<String, Value>) -> i64 {
    entry
        .get("cbl_position")
        .and_then(Value::as_i64)
        .unwrap_or(0)
}

fn entry_str<'a>(entry: &'a serde_json::Map<String, Value>, key: &str) -> Option<&'a str> {
    entry.get(key).and_then(Value::as_str)
}

fn entry_year(entry: &serde_json::Map<String, Value>) -> Option<i32> {
    ["volume_year", "publication_year"]
        .iter()
        .find_map(|key| entry.get(*key).and_then(Value::as_i64))
        .and_then(|year| i32::try_from(year).ok())
}

/// Mounted handler for `POST .../cbl/{list_id}/reading-graph-preview`.
pub async fn preview_cbl_reading_graph_handler(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    list_id: Result<Path<String>, PathRejection>,
    body: Bytes,
) -> Result<Json<ReadingGraphPreview>, PreviewError> {
    let list_id = parse_path_int(list_id)?;
    let request = parse_request(&body)?;
    let loaded = load(&state, user, list_id, &request.included_positions).await?;
    build_preview(&loaded, user.id(), list_id, &request).map(Json)
}

fn build_preview(
    loaded: &Loaded,
    user_id: i32,
    source_list_id: i64,
    request: &ReadingGraphPreviewRequest,
) -> Result<ReadingGraphPreview, PreviewError> {
    let _ = user_id;
    let entries_by_position: HashMap<i64, &serde_json::Map<String, Value>> = loaded
        .entries
        .iter()
        .map(|entry| (entry_position(entry), entry))
        .collect();
    let selected_positions: Vec<i64> = request
        .included_positions
        .iter()
        .copied()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let unknown: Vec<i64> = selected_positions
        .iter()
        .copied()
        .filter(|position| !entries_by_position.contains_key(position))
        .collect();
    if !unknown.is_empty() {
        return Err(unprocessable(
            "unknown_source_position",
            format!("Source positions are not part of list {source_list_id}: {unknown:?}"),
        ));
    }
    let selected: Vec<&serde_json::Map<String, Value>> = selected_positions
        .iter()
        .map(|position| entries_by_position[position])
        .collect();
    let unresolved: Vec<i64> = selected
        .iter()
        .filter(|entry| entry.get("resolved_issue_id").is_none_or(Value::is_null))
        .map(|entry| entry_position(entry))
        .collect();
    if !unresolved.is_empty() {
        return Err(unprocessable(
            "unresolved_source_position",
            format!("Resolve these source positions before previewing the graph: {unresolved:?}"),
        ));
    }

    let inputs = &loaded.inputs;
    let issue_meta: HashMap<i32, IssueMeta> = inputs
        .core
        .issues
        .iter()
        .map(|issue| {
            (
                issue.id,
                IssueMeta {
                    thread_id: issue.thread_id,
                    issue_number: issue.issue_number.clone(),
                    position: issue.position,
                    status: issue.status.clone(),
                },
            )
        })
        .collect();
    let thread_names: HashMap<i32, &str> = inputs
        .core
        .threads
        .iter()
        .map(|thread| (thread.id, thread.title.as_str()))
        .collect();

    let mut selected_issue_ids: Vec<i32> = Vec::new();
    let mut seen: HashSet<i32> = HashSet::new();
    for entry in &selected {
        let resolved = entry
            .get("resolved_issue_id")
            .and_then(Value::as_i64)
            .and_then(|id| i32::try_from(id).ok())
            .filter(|id| issue_meta.contains_key(id));
        let Some(issue_id) = resolved else {
            return Err(unprocessable(
                "source_position_not_owned",
                format!(
                    "Source position {} does not resolve to an owned issue",
                    entry_position(entry)
                ),
            ));
        };
        if seen.insert(issue_id) {
            selected_issue_ids.push(issue_id);
        }
    }

    let mut owned_lists: Vec<&option_inputs::ReadingList> = inputs.lists.iter().collect();
    owned_lists.sort_by_key(|list| list.list_id);
    let target = match request.target_list_id {
        None => None,
        Some(target_id) => Some(
            owned_lists
                .iter()
                .copied()
                .find(|list| i64::from(list.list_id) == target_id)
                .ok_or_else(|| {
                    structured_error(
                        StatusCode::NOT_FOUND,
                        "reading_list_not_found",
                        format!("Reading List {target_id} was not found"),
                    )
                })?,
        ),
    };
    let proposed_id = target.map_or_else(
        || {
            owned_lists
                .iter()
                .map(|list| list.list_id)
                .max()
                .unwrap_or(0)
                + 1
        },
        |list| list.list_id,
    );
    let target_entries: HashMap<i32, &ReadingEntry> = target
        .map(|list| {
            list.entries
                .iter()
                .map(|entry| (entry.issue_id, entry))
                .collect()
        })
        .unwrap_or_default();
    let proposed = ProposedList {
        id: proposed_id,
        mode: target.map_or_else(|| "strict".to_string(), |list| list.mode.clone()),
        name: target.map_or_else(|| loaded.list_name.clone(), |list| list.name.clone()),
        entries: selected_issue_ids
            .iter()
            .map(|issue_id| {
                target_entries.get(issue_id).map_or_else(
                    || ReadingEntry {
                        issue_id: *issue_id,
                        gate: "none".to_string(),
                        skipped: false,
                    },
                    |entry| (*entry).clone(),
                )
            })
            .collect(),
    };
    owned_lists.retain(|list| list.list_id != proposed_id);

    let mut source_names: HashMap<String, (String, Option<i32>)> = HashMap::new();
    for entry in &selected {
        let (Some(provider), Some(external_id)) = (
            entry_str(entry, "series_provider"),
            entry_str(entry, "series_external_id"),
        ) else {
            continue;
        };
        if let Some(volume) = canonical_volume_key(provider, external_id) {
            source_names.entry(volume).or_insert_with(|| {
                (
                    entry_str(entry, "series_name")
                        .unwrap_or_default()
                        .to_string(),
                    entry_year(entry),
                )
            });
        }
    }

    let mut list_names: HashMap<i32, String> = owned_lists
        .iter()
        .map(|list| (list.list_id, list.name.clone()))
        .collect();
    if let Some(target) = target {
        list_names.insert(target.list_id, target.name.clone());
    }
    list_names.insert(proposed_id, proposed.name.clone());

    let owned_issue_ids: HashSet<i32> = issue_meta.keys().copied().collect();
    let prerequisites = inputs
        .prerequisites
        .iter()
        .filter(|p| {
            owned_issue_ids.contains(&p.source_issue_id)
                && owned_issue_ids.contains(&p.target_issue_id)
        })
        .collect();
    let input = EvalInput {
        inputs,
        prerequisites,
        owned_lists,
        proposed: &proposed,
    };
    let baseline = evaluate(&input, &[]);
    let graph_thread_ids = expand_graph_threads(
        &issue_meta,
        &baseline,
        selected_issue_ids
            .iter()
            .map(|issue_id| issue_meta[issue_id].thread_id)
            .collect(),
    );
    let graph_issue_ids: BTreeSet<i32> = issue_meta
        .iter()
        .filter(|(_, meta)| graph_thread_ids.contains(&meta.thread_id))
        .map(|(issue_id, _)| *issue_id)
        .collect();
    let series_refs: HashMap<String, ReadingGraphSeriesReference> = graph_thread_ids
        .iter()
        .map(|thread_id| {
            let volume = inputs.thread_volumes.get(thread_id).map(String::as_str);
            let reference = series_reference(
                volume,
                *thread_id,
                &thread_names,
                &source_names,
                &loaded.volume_years,
            );
            (reference.comicvine_volume_id.clone(), reference)
        })
        .collect();
    let context = Context {
        input,
        graph_thread_ids,
        graph_issue_ids,
        issue_meta,
        volume_by_thread: &inputs.thread_volumes,
        series_refs,
        list_names,
        thread_names,
    };

    // Genuine overlaps: a selected frontier issue held back by a strict-order
    // blocker of the proposed list on a different exact volume.
    let mut blocked_by_pair: BTreeMap<(String, String), BTreeSet<i32>> = BTreeMap::new();
    for issue_id in &selected_issue_ids {
        let thread_id = context.issue_meta[issue_id].thread_id;
        let Some(state) = baseline.get(&thread_id) else {
            continue;
        };
        let Some(continuing) = inputs.thread_volumes.get(&thread_id) else {
            continue;
        };
        if state.next_issue_id != Some(*issue_id) {
            continue;
        }
        for blocker in state
            .blockers
            .iter()
            .filter(|b: &&Blocker| b.kind == "strict_order" && b.list_id == Some(proposed_id))
        {
            for waiting_issue_id in &blocker.waiting_on_issue_ids {
                let Some(waiting) = context.volume_of_issue(*waiting_issue_id) else {
                    continue;
                };
                if waiting == continuing {
                    continue;
                }
                blocked_by_pair
                    .entry((continuing.clone(), waiting.to_string()))
                    .or_default()
                    .insert(*issue_id);
            }
        }
    }
    let identified: HashMap<String, (String, String)> = blocked_by_pair
        .keys()
        .map(|pair| (overlap_identity(&pair.0, &pair.1), pair.clone()))
        .collect();
    let mut answered: HashSet<&str> = HashSet::new();
    let mut requested: BTreeMap<(String, String), String> = BTreeMap::new();
    for answer in &request.overlap_choices {
        let Some(pair) = identified.get(&answer.overlap_id) else {
            return Err(unprocessable(
                "unknown_overlap_choice",
                format!(
                    "Overlap {} is not part of this proposed graph",
                    answer.overlap_id
                ),
            ));
        };
        if !answered.insert(answer.overlap_id.as_str()) {
            return Err(unprocessable(
                "duplicate_overlap_choice",
                format!("Overlap {} was answered more than once", answer.overlap_id),
            ));
        }
        requested.insert(pair.clone(), answer.choice.clone());
    }

    let top_decisions = decisions_for(&requested);
    let top = evaluate(&context.input, &top_decisions);

    let mut overlaps = Vec::with_capacity(blocked_by_pair.len());
    for (pair, blocked) in &blocked_by_pair {
        let continuing = &context.series_refs[&pair.0];
        let waiting = &context.series_refs[&pair.1];
        let mut without_pair = requested.clone();
        without_pair.remove(pair);
        let protect = choice_effect(
            &context,
            CHOICE_PROTECT,
            &decisions_for(&without_pair),
            continuing,
            waiting,
        );
        let mut with_continue = without_pair;
        with_continue.insert(pair.clone(), CHOICE_CONTINUE.to_string());
        let proceed = choice_effect(
            &context,
            CHOICE_CONTINUE,
            &decisions_for(&with_continue),
            continuing,
            waiting,
        );
        overlaps.push(ReadingGraphOverlap {
            overlap_id: overlap_identity(&pair.0, &pair.1),
            continuing_series: continuing.clone(),
            waiting_series: waiting.clone(),
            question: format!(
                "Should {} continue while {} waits?",
                continuing.series_name, waiting.series_name
            ),
            blocked_issue_ids: blocked.iter().map(|id| i64::from(*id)).collect(),
            choices: vec![proceed, protect],
            selected_choice: requested.get(pair).cloned(),
        });
    }

    Ok(ReadingGraphPreview {
        source_list_id,
        content_hash: loaded.content_hash.clone(),
        revision_sha: loaded.revision_sha.clone(),
        series: series_nodes(&context, &top),
        overlaps,
        issues: issue_references(&context, &top),
        rollable_issue_ids: wire_ids(rollable_ids(&context, &top)),
        waiting_issue_ids: wire_ids(waiting_ids(&context, &top)),
        cycle_errors: cycle_errors(&context, &top_decisions)?,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn request_defaults_and_lax_ints_match_pydantic() {
        let request = parse_request(br#"{"included_positions": ["2", 1.0, 2]}"#).unwrap();
        assert_eq!(request.included_positions, vec![2, 1, 2]);
        assert!(request.overlap_choices.is_empty());
        assert_eq!(request.target_list_id, None);
        let request = parse_request(br#"{"target_list_id": null}"#).unwrap();
        assert_eq!(request.target_list_id, None);
        assert!(parse_request(b"{}").is_ok());
    }

    #[test]
    fn invalid_requests_are_the_production_validation_failed_422() {
        for body in [
            &br#"{"included_positions": [0]}"#[..],
            br#"{"included_positions": null}"#,
            br#"{"target_list_id": -1}"#,
            br#"{"overlap_choices": [{"overlap_id": "a", "choice": "nope"}]}"#,
            br#"{"overlap_choices": [{"choice": "protect_order"}]}"#,
            b"[]",
        ] {
            assert_eq!(
                parse_request(body).unwrap_err().detail(),
                "Validation failed"
            );
        }
        let too_many = format!(r#"{{"included_positions": [{}]}}"#, ["1"; 10_001].join(","));
        assert!(parse_request(too_many.as_bytes()).is_err());
    }

    #[test]
    fn volume_keys_and_year_metadata_follow_python() {
        assert_eq!(
            canonical_volume_key("ComicVine", " 4050-0042 ").as_deref(),
            Some("comicvine:42")
        );
        assert_eq!(canonical_volume_key("gcd", "42"), None);
        assert_eq!(
            external_id_candidates("comicvine:42"),
            vec!["4050-42".to_string(), "42".to_string()]
        );
        assert!(external_id_candidates("gcd:42").is_empty());
        assert_eq!(
            metadata_year(&serde_json::json!({"year": 1999})),
            Some(1999)
        );
        assert_eq!(metadata_year(&serde_json::json!({"year": 12})), None);
        assert_eq!(metadata_year(&serde_json::json!({"year": true})), None);
        assert_eq!(
            metadata_year(&serde_json::json!({"year": 5, "volume_year": 2001})),
            Some(2001)
        );
    }

    /// A short preview selection must not reconcile every row in a long source
    /// list: the generic helper issues per-entry lookups, while this caller
    /// filters positions in SQL before any of that work (#5342 review).
    #[tokio::test]
    async fn preview_reconciles_only_selected_source_positions() {
        let state = crate::test_support::test_state(1)
            .await
            .expect("disposable PostgreSQL required");
        let _guard = crate::test_support::reset_for_test(&state).await;
        let connection = db::checkout(&state).await.expect("test connection");
        connection
            .batch_execute(
                r#"
                INSERT INTO users (id, username) VALUES (9001, 'graph-preview-reader');
                INSERT INTO cbl_sources (id, repository, revision_sha, synced_at, created_at, updated_at)
                VALUES (1, 'cbl-test', 'rev', now(), now(), now());
                INSERT INTO cbl_source_lists
                    (id, source_id, source_path, name, declared_issue_count,
                     content_hash, revision_sha, active, created_at, updated_at)
                VALUES (1, 1, 'lists/test.json', 'Test list', 3,
                        'hash', 'rev', true, now(), now());
                INSERT INTO cbl_source_entries
                    (id, list_id, position, series_name, issue_number, created_at)
                VALUES (1, 1, 1, 'Series', '1', now()),
                       (2, 1, 2, 'Series', '2', now()),
                       (3, 1, 3, 'Series', '3', now());
                "#,
            )
            .await
            .expect("seed CBL source list");
        let meta = crate::issue_identity::load_active_cbl_list_meta(&connection, 1)
            .await
            .expect("list meta");

        let all = crate::issue_identity::reconcile_entries_for_adoption(&connection, 9001, &meta)
            .await
            .expect("all rows");
        assert_eq!(all.len(), 3);

        let selected = crate::issue_identity::reconcile_entries_for_adoption_positions(
            &connection,
            9001,
            &meta,
            &[2],
        )
        .await
        .expect("selected rows");
        assert_eq!(selected.len(), 1);
        assert_eq!(
            selected[0].get("cbl_position").and_then(Value::as_i64),
            Some(2)
        );
    }

    #[test]
    fn overlap_identity_is_stable_and_pair_specific() {
        let id = overlap_identity("comicvine:1", "comicvine:2");
        assert_eq!(id, overlap_identity("comicvine:1", "comicvine:2"));
        assert_ne!(id, overlap_identity("comicvine:2", "comicvine:1"));
        assert!(id.starts_with("overlap-") && id.len() == "overlap-".len() + 24);
    }
}
