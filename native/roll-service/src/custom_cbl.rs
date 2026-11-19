//! Reading List authoring operations on /api/v2/reading-lists paths.
//!
//! Issue search, export, Reading Plan application and overlap decisions.
//! They share tables and authorization logic with the canonical
//! `reading_list` resource handlers.

use crate::{
    auth::AuthenticatedUser,
    cbl_catalog::{ValidationErrorItem, ValidationErrorResponse},
    db, option_inputs,
    reading_constraints::ValidatedReadingInputs,
    reading_graph::custom_cbl_cycle_conflict,
    ApiError, AppState,
};
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use deadpool_postgres::Transaction;
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::sync::Arc;
use tokio_postgres::types::ToSql;

const QUEUE_LOCK_NAMESPACE: i32 = 699001;

#[derive(Debug, Clone, Deserialize, Serialize, utoipa::ToSchema)]
pub struct CustomCBLEntryIntent {
    pub gate: String,
    #[serde(default)]
    pub skipped: bool,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct CustomCBLEntryResponse {
    pub id: i32,
    pub position: i32,
    pub issue_id: i32,
    pub thread_id: i32,
    pub series_name: String,
    pub issue_number: String,
    pub status: String,
    pub is_checkpoint: bool,
    pub gate: String,
    pub skipped: bool,
    pub checkpoint_target_issue_ids: Vec<i32>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct CustomCBLListItem {
    pub id: i32,
    pub name: String,
    pub description: Option<String>,
    pub mode: String,
    pub issue_count: i32,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct CustomCBLResponse {
    pub id: i32,
    pub user_id: i32,
    pub name: String,
    pub description: Option<String>,
    pub mode: String,
    pub issue_count: i32,
    pub created_at: String,
    pub updated_at: String,
    pub entries: Vec<CustomCBLEntryResponse>,
    #[serde(default)]
    pub predecessor_changes: Vec<CustomCBLPredecessorChange>,
    #[serde(default)]
    pub warnings: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct CustomCBLPredecessorChange {
    pub issue_id: i32,
    pub issue_name: String,
    pub before_issue_ids: Vec<i32>,
    pub before_issue_names: Vec<String>,
    pub after_issue_ids: Vec<i32>,
    pub after_issue_names: Vec<String>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct CustomCBLIssueSearchResult {
    pub issue_id: i32,
    pub thread_id: i32,
    pub series_name: String,
    pub issue_number: String,
    pub status: String,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct CustomCBLWrite {
    pub name: String,
    pub description: Option<String>,
    pub mode: Option<String>,
    #[serde(default)]
    pub issue_ids: Vec<i32>,
    #[serde(default)]
    pub entry_intents: Option<BTreeMap<i32, CustomCBLEntryIntent>>,
    #[serde(default)]
    pub checkpoint_issue_ids: Option<Vec<i32>>,
    #[serde(default)]
    pub checkpoint_targets: Option<BTreeMap<i32, Vec<i32>>>,
    #[serde(default)]
    pub confirmed_predecessor_changes: Option<serde_json::Value>,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct CustomCBLApplyRequest {
    pub lane_id: Option<String>,
    pub expected_updated_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct CustomCBLApplyResponse {
    pub id: i32,
    pub user_id: i32,
    pub name: String,
    pub ordering_mode: String,
    pub lanes: Vec<serde_json::Value>,
    pub nodes: Vec<serde_json::Value>,
    pub created_at: String,
    pub updated_at: String,
    pub added_issue_ids: Vec<i32>,
    pub skipped_existing_issue_ids: Vec<i32>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct OverlapDecisionItem {
    pub id: i32,
    pub list_id: i32,
    pub continuing_volume_id: String,
    pub waiting_volume_id: String,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct OverlapVolumeCandidate {
    pub thread_id: i32,
    pub thread_title: String,
    pub volume_id: String,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct OverlapDecisionSetResponse {
    pub list_id: i32,
    pub updated_at: String,
    #[serde(default)]
    pub decisions: Vec<OverlapDecisionItem>,
    #[serde(default)]
    pub candidate_volumes: Vec<OverlapVolumeCandidate>,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct OverlapDecisionWrite {
    pub continuing_volume_id: String,
    pub waiting_volume_id: String,
    pub expected_updated_at: Option<String>,
}

async fn lock_reader(tx: &Transaction<'_>, user_id: i32) -> Result<(), ApiError> {
    tx.execute(
        "SELECT pg_advisory_xact_lock($1,$2)",
        &[&QUEUE_LOCK_NAMESPACE, &user_id],
    )
    .await
    .map_err(db::query_error)?;
    Ok(())
}

#[allow(dead_code)]
fn validate_name(name: &str) -> Result<String, ApiError> {
    let name = name.trim();
    if name.is_empty() || name.chars().count() > 200 {
        return Err(ApiError::BadRequest(
            "Reading List name must be between 1 and 200 characters".to_string(),
        ));
    }
    Ok(name.to_string())
}

#[allow(dead_code)]
fn validate_mode(mode: Option<&str>) -> Result<String, ApiError> {
    match mode.unwrap_or("loose") {
        "strict" => Ok("strict".to_string()),
        "loose" => Ok("loose".to_string()),
        _ => Err(ApiError::BadRequest(
            "mode must be strict or loose".to_string(),
        )),
    }
}

#[allow(dead_code)]
async fn owned_issue_ids(
    tx: &Transaction<'_>,
    user_id: i32,
    issue_ids: &[i32],
) -> Result<BTreeSet<i32>, ApiError> {
    let rows = tx
        .query(
            "SELECT i.id FROM issues i JOIN threads t ON t.id=i.thread_id
             WHERE t.user_id=$1 AND i.id=ANY($2::int[])",
            &[&user_id, &issue_ids.to_vec()],
        )
        .await
        .map_err(db::query_error)?;
    Ok(rows.iter().map(|row| row.get(0)).collect())
}

async fn load_entries(
    tx: &Transaction<'_>,
    list_id: i32,
) -> Result<Vec<CustomCBLEntryResponse>, ApiError> {
    let rows = tx
        .query(
            "SELECT e.id, e.position, e.issue_id, i.thread_id, t.title, i.issue_number,
                    i.status, e.is_checkpoint, e.gate, e.skipped,
                    e.checkpoint_target_issue_ids::text
             FROM custom_cbl_entries e
             JOIN issues i ON i.id=e.issue_id
             JOIN threads t ON t.id=i.thread_id
             WHERE e.list_id=$1
             ORDER BY e.position, e.id",
            &[&list_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(rows
        .iter()
        .map(|row| CustomCBLEntryResponse {
            id: row.get(0),
            position: row.get(1),
            issue_id: row.get(2),
            thread_id: row.get(3),
            series_name: row.get(4),
            issue_number: row.get(5),
            status: row.get(6),
            is_checkpoint: row.get(7),
            gate: row.get(8),
            skipped: row.get(9),
            checkpoint_target_issue_ids: serde_json::from_str::<Vec<i32>>(
                &row.get::<_, String>(10),
            )
            .unwrap_or_default(),
        })
        .collect())
}

#[allow(dead_code)]
async fn load_list(
    conn: &deadpool_postgres::Object,
    list_id: i32,
    user_id: i32,
) -> Result<Option<(i32, String, Option<String>, String, String, String, i32)>, ApiError> {
    let row = conn
        .query_opt(
            "SELECT l.id, l.name, l.description, l.mode, l.created_at::text, l.updated_at::text,
                    l.user_id, count(e.id)::int
             FROM custom_cbl_lists l
             LEFT JOIN custom_cbl_entries e ON e.list_id=l.id
             WHERE l.id=$1 AND l.user_id=$2
             GROUP BY l.id",
            &[&list_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(row.map(|row| {
        (
            row.get(0),
            row.get(1),
            row.get(2),
            row.get(3),
            row.get(4),
            row.get(5),
            row.get(7),
        )
    }))
}

#[allow(dead_code)]
fn list_item_from_row(
    row: (i32, String, Option<String>, String, String, i32),
) -> CustomCBLListItem {
    CustomCBLListItem {
        id: row.0,
        name: row.1,
        description: row.2,
        mode: row.3,
        updated_at: row.4,
        issue_count: row.5,
    }
}

#[allow(dead_code)]
fn response_from_row(
    row: (i32, String, Option<String>, String, String, String, i32),
    user_id: i32,
    entries: Vec<CustomCBLEntryResponse>,
    predecessor_changes: Vec<CustomCBLPredecessorChange>,
    warnings: Vec<String>,
) -> CustomCBLResponse {
    CustomCBLResponse {
        id: row.0,
        user_id,
        name: row.1,
        description: row.2,
        mode: row.3,
        created_at: row.4,
        updated_at: row.5,
        issue_count: row.6,
        entries,
        predecessor_changes,
        warnings,
    }
}

#[allow(dead_code)]
async fn graph_preflight(
    tx: &Transaction<'_>,
    user: &AuthenticatedUser,
) -> Result<option_inputs::OptionInputs, ApiError> {
    let inputs = option_inputs::load_inputs_in_transaction(tx, *user).await?;
    let names = inputs
        .lists
        .iter()
        .map(|list| (list.list_id, list.name.clone()))
        .collect();
    ValidatedReadingInputs::new(inputs.clone(), &names)
        .map_err(|error| custom_cbl_cycle_conflict(error, &inputs))?;
    Ok(inputs)
}

/// Mirror Python `validate_authored_list` strict partial-coverage warnings.
///
/// A strict list still represents every placed Thread, so unread, unexcluded,
/// skipped Issues inside those Threads are reported even though execution
/// ignores them. The same bounded snapshot feeds the cycle preflight, so no
/// extra round trip is needed here.
#[allow(dead_code)]
fn strict_coverage_warnings(
    inputs: &option_inputs::OptionInputs,
    entries: &[CustomCBLEntryResponse],
    mode: &str,
) -> Vec<String> {
    if mode != "strict" {
        return Vec::new();
    }

    let placed: BTreeSet<i32> = entries.iter().map(|entry| entry.issue_id).collect();
    let covered: BTreeSet<i32> = entries
        .iter()
        .filter(|entry| !entry.skipped)
        .map(|entry| entry.issue_id)
        .collect();
    let represented: BTreeSet<i32> = inputs
        .core
        .issues
        .iter()
        .filter(|issue| placed.contains(&issue.id))
        .map(|issue| issue.thread_id)
        .collect();
    let titles: BTreeMap<i32, &str> = inputs
        .core
        .threads
        .iter()
        .map(|thread| (thread.id, thread.title.as_str()))
        .collect();
    let names: BTreeMap<i32, String> = inputs
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

    let mut omitted_counts: BTreeMap<i32, usize> = BTreeMap::new();
    let mut samples: BTreeMap<i32, Vec<String>> = BTreeMap::new();
    for issue in &inputs.core.issues {
        if represented.contains(&issue.thread_id)
            && !covered.contains(&issue.id)
            && issue.status != "read"
            && !inputs.excluded_issue_ids.contains(&issue.id)
        {
            *omitted_counts.entry(issue.thread_id).or_default() += 1;
            let sample = samples.entry(issue.thread_id).or_default();
            if sample.len() < 5 {
                sample.push(
                    names
                        .get(&issue.id)
                        .cloned()
                        .unwrap_or_default()
                        .chars()
                        .take(80)
                        .collect(),
                );
            }
        }
    }

    let affected: Vec<&crate::reading_inputs::ReadingThread> = inputs
        .core
        .threads
        .iter()
        .filter(|thread| omitted_counts.contains_key(&thread.id))
        .collect();
    let mut warnings = Vec::new();
    for thread in affected.iter().take(10) {
        let count = omitted_counts[&thread.id];
        let sample = samples.get(&thread.id).cloned().unwrap_or_default();
        let suffix = if count > sample.len() {
            format!(", … (+{} more)", count - sample.len())
        } else {
            String::new()
        };
        let thread_name: String = thread.title.chars().take(80).collect();
        warnings.push(format!(
            "Strict list omits {count} unread Issues from {thread_name}: {}{}",
            sample.join(", "),
            suffix
        ));
    }
    if affected.len() > 10 {
        warnings.push(format!(
            "Partial coverage also affects {} more Threads.",
            affected.len() - 10
        ));
    }
    warnings
}

#[allow(dead_code)]
fn stored_requirements(mode: &str, entries: &[CustomCBLEntryResponse]) -> BTreeMap<i32, Vec<i32>> {
    let mut results = BTreeMap::new();
    let mut earlier = Vec::<i32>::new();
    let mut hold = BTreeSet::<i32>::new();
    for entry in entries {
        if entry.skipped {
            continue;
        }
        let mut sources = hold.clone();
        if mode == "strict" || entry.gate == "hold" {
            sources.extend(&earlier);
        }
        if entry.gate == "after_previous" {
            if let Some(last) = earlier.last() {
                sources.insert(*last);
            }
        }
        results.insert(
            entry.issue_id,
            earlier
                .iter()
                .copied()
                .filter(|id| sources.contains(id))
                .collect(),
        );
        earlier.push(entry.issue_id);
        if entry.gate == "hold" {
            hold.extend(&earlier);
        }
    }
    results
}

#[allow(dead_code)]
fn predecessor_changes(
    before: &BTreeMap<i32, Vec<i32>>,
    after: &BTreeMap<i32, Vec<i32>>,
    labels: &BTreeMap<i32, String>,
) -> Vec<CustomCBLPredecessorChange> {
    let ids: BTreeSet<i32> = before.keys().chain(after.keys()).copied().collect();
    ids.into_iter()
        .filter_map(|issue_id| {
            let old = before.get(&issue_id).cloned().unwrap_or_default();
            let new = after.get(&issue_id).cloned().unwrap_or_default();
            if old == new {
                return None;
            }
            let name = |id: &i32| {
                labels
                    .get(id)
                    .cloned()
                    .unwrap_or_else(|| format!("Issue #{id}"))
            };
            Some(CustomCBLPredecessorChange {
                issue_id,
                issue_name: name(&issue_id),
                before_issue_names: old.iter().map(&name).collect(),
                after_issue_names: new.iter().map(&name).collect(),
                before_issue_ids: old,
                after_issue_ids: new,
            })
        })
        .collect()
}

#[allow(dead_code)]
fn confirmed_changes_match(
    actual: &[CustomCBLPredecessorChange],
    confirmed: &[CustomCBLPredecessorChange],
) -> bool {
    let key = |row: &CustomCBLPredecessorChange| {
        let mut before = row.before_issue_ids.clone();
        let mut after = row.after_issue_ids.clone();
        before.sort();
        after.sort();
        (row.issue_id, before, after)
    };
    let mut left: Vec<_> = actual.iter().map(&key).collect();
    let mut right: Vec<_> = confirmed.iter().map(&key).collect();
    left.sort();
    right.sort();
    left == right
}

#[allow(dead_code)]
fn normalize_checkpoint_targets(
    issue_ids: &[i32],
    checkpoint_issue_ids: Option<&Vec<i32>>,
    checkpoint_targets: Option<&BTreeMap<i32, Vec<i32>>>,
    previous_entries: &[CustomCBLEntryResponse],
) -> Result<BTreeMap<i32, Vec<i32>>, ApiError> {
    let membership: BTreeSet<i32> = issue_ids.iter().copied().collect();
    let checkpoint_set: BTreeSet<i32> = checkpoint_issue_ids
        .map(|ids| ids.iter().copied().collect())
        .unwrap_or_default();
    if !checkpoint_set.is_subset(&membership) {
        return Err(invalid_checkpoint_targets());
    }

    let mut targets = if let Some(requested) = checkpoint_targets {
        requested.clone()
    } else {
        let mut preserved = BTreeMap::new();
        for (index, entry) in previous_entries.iter().enumerate() {
            let entry_targets = if !entry.checkpoint_target_issue_ids.is_empty() {
                entry.checkpoint_target_issue_ids.clone()
            } else if entry.is_checkpoint {
                previous_entries
                    .get(index + 1)
                    .map(|next| vec![next.issue_id])
                    .unwrap_or_default()
            } else {
                Vec::new()
            };
            let filtered: Vec<i32> = entry_targets
                .into_iter()
                .filter(|target| membership.contains(target))
                .collect();
            if membership.contains(&entry.issue_id)
                && match checkpoint_issue_ids {
                    Some(_) => checkpoint_set.contains(&entry.issue_id),
                    None => true,
                }
                && !filtered.is_empty()
            {
                preserved.insert(entry.issue_id, filtered);
            }
        }
        preserved
    };

    if checkpoint_targets.is_none() {
        for (position, source) in issue_ids.iter().enumerate() {
            if checkpoint_set.contains(source) && !targets.contains_key(source) {
                let default_target = issue_ids
                    .get(position + 1)
                    .copied()
                    .into_iter()
                    .collect::<Vec<_>>();
                targets.insert(*source, default_target);
            }
        }
    }

    targets.retain(|_, values| !values.is_empty());
    for (source, values) in &targets {
        let unique: BTreeSet<i32> = values.iter().copied().collect();
        if !membership.contains(source)
            || unique.len() != values.len()
            || unique.contains(source)
            || !unique.is_subset(&membership)
        {
            return Err(invalid_checkpoint_targets());
        }
    }
    Ok(targets)
}

#[allow(dead_code)]
fn invalid_checkpoint_targets() -> ApiError {
    ApiError::structured(
        StatusCode::UNPROCESSABLE_ENTITY,
        json!({"code": "custom_cbl_invalid_checkpoint_targets"}),
    )
}

#[allow(dead_code)]
fn issue_not_owned(issue_ids: &[i32], owned: &BTreeSet<i32>) -> ApiError {
    let missing: Vec<i32> = issue_ids
        .iter()
        .copied()
        .filter(|issue_id| !owned.contains(issue_id))
        .collect();
    ApiError::structured(
        StatusCode::UNPROCESSABLE_ENTITY,
        json!({"code": "custom_cbl_issue_not_owned", "issue_ids": missing}),
    )
}

async fn load_list_entries_for_export(
    tx: &Transaction<'_>,
    list_id: i32,
) -> Result<Vec<CustomCBLEntryResponse>, ApiError> {
    let rows = tx
        .query(
            "SELECT e.id, e.position, e.issue_id, i.thread_id, t.title, i.issue_number,
                    i.status, e.is_checkpoint, e.gate, e.skipped,
                    e.checkpoint_target_issue_ids::text
             FROM custom_cbl_entries e
             JOIN issues i ON i.id=e.issue_id
             JOIN threads t ON t.id=i.thread_id
             WHERE e.list_id=$1
             ORDER BY e.position, e.id",
            &[&list_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(rows
        .iter()
        .map(|row| CustomCBLEntryResponse {
            id: row.get(0),
            position: row.get(1),
            issue_id: row.get(2),
            thread_id: row.get(3),
            series_name: row.get(4),
            issue_number: row.get(5),
            status: row.get(6),
            is_checkpoint: row.get(7),
            gate: row.get(8),
            skipped: row.get(9),
            checkpoint_target_issue_ids: serde_json::from_str::<Vec<i32>>(
                &row.get::<_, String>(10),
            )
            .unwrap_or_default(),
        })
        .collect())
}

fn export_custom_cbl_xml(name: &str, entries: &[CustomCBLEntryResponse]) -> String {
    use html_escape::encode_text;
    let books = entries
        .iter()
        .map(|entry| {
            format!(
                "    <Book Series=\"{}\" Number=\"{}\" />",
                encode_text(&entry.series_name),
                encode_text(&entry.issue_number)
            )
        })
        .collect::<Vec<_>>()
        .join("\n");
    format!(
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<ReadingList>\n  <Name>{}</Name>\n  <NumIssues>{}</NumIssues>\n  <Books>\n{}\n  </Books>\n</ReadingList>\n",
        encode_text(name),
        entries.len(),
        books
    )
}

// ========================================================================
// Overlap Decisions
// ========================================================================

fn normalized_volume_key(key: &str) -> Option<String> {
    let rest = key.strip_prefix("comicvine:")?;
    if rest.is_empty() {
        return None;
    }

    let numeric = rest.strip_prefix("4050-").unwrap_or(rest);
    if !numeric.is_empty() && numeric.chars().all(|c| c.is_ascii_digit()) {
        let trimmed = numeric.trim_start_matches('0');
        return Some(format!(
            "comicvine:{}",
            if trimmed.is_empty() { "0" } else { trimmed }
        ));
    }

    let mut chars = rest.chars();
    let first = chars.next()?;
    if !first.is_ascii_alphanumeric() {
        return None;
    }
    if chars.all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-')) {
        Some(format!("comicvine:{rest}"))
    } else {
        None
    }
}

fn volume_external_id_variants(key: &str) -> Vec<String> {
    let Some(normalized) = normalized_volume_key(key) else {
        return Vec::new();
    };
    let rest = normalized.strip_prefix("comicvine:").unwrap_or_default();
    let mut variants = vec![rest.to_string()];
    if rest.chars().all(|c| c.is_ascii_digit()) {
        variants.push(format!("4050-{rest}"));
    }
    variants.sort();
    variants.dedup();
    variants
}

fn timestamp_token_to_utc(value: &str) -> Option<chrono::DateTime<chrono::Utc>> {
    if let Ok(parsed) = chrono::DateTime::parse_from_rfc3339(value) {
        return Some(parsed.with_timezone(&chrono::Utc));
    }
    let mut normalized = value.trim().replacen(' ', "T", 1);
    if normalized.len() >= 3 {
        let suffix = &normalized[normalized.len() - 3..];
        if (suffix.starts_with('+') || suffix.starts_with('-'))
            && suffix[1..].chars().all(|c| c.is_ascii_digit())
        {
            normalized.push_str(":00");
        }
    }
    chrono::DateTime::parse_from_rfc3339(&normalized)
        .map(|parsed| parsed.with_timezone(&chrono::Utc))
        .ok()
}

async fn load_overlap_decisions(
    tx: &Transaction<'_>,
    user_id: i32,
) -> Result<Vec<OverlapDecisionItem>, ApiError> {
    let rows = tx
        .query(
            "SELECT d.id, d.list_id, d.created_at::text, d.updated_at::text,
                    ci.provider, ci.external_id, wi.provider, wi.external_id
             FROM custom_cbl_overlap_decisions d
             JOIN external_identities ci ON ci.id = d.continuing_external_identity_id
             JOIN external_identities wi ON wi.id = d.waiting_external_identity_id
             WHERE d.user_id = $1
             ORDER BY d.id",
            &[&user_id],
        )
        .await
        .map_err(db::query_error)?;

    let mut decisions = Vec::new();
    for row in rows {
        let continuing_key = format!("{}:{}", row.get::<_, String>(4), row.get::<_, String>(5));
        let waiting_key = format!("{}:{}", row.get::<_, String>(6), row.get::<_, String>(7));
        if let (Some(continuing), Some(waiting)) = (
            normalized_volume_key(&continuing_key),
            normalized_volume_key(&waiting_key),
        ) {
            decisions.push(OverlapDecisionItem {
                id: row.get(0),
                list_id: row.get(1),
                created_at: row.get(2),
                updated_at: row.get(3),
                continuing_volume_id: continuing,
                waiting_volume_id: waiting,
            });
        }
    }
    Ok(decisions)
}

async fn load_list_overlap_decisions(
    tx: &Transaction<'_>,
    user_id: i32,
    list_id: i32,
) -> Result<Vec<OverlapDecisionItem>, ApiError> {
    let rows = tx
        .query(
            "SELECT d.id, d.list_id, d.created_at::text, d.updated_at::text,
                    ci.provider, ci.external_id, wi.provider, wi.external_id
             FROM custom_cbl_overlap_decisions d
             JOIN external_identities ci ON ci.id = d.continuing_external_identity_id
             JOIN external_identities wi ON wi.id = d.waiting_external_identity_id
             WHERE d.user_id = $1 AND d.list_id = $2
             ORDER BY d.id",
            &[&user_id, &list_id],
        )
        .await
        .map_err(db::query_error)?;

    let mut decisions = Vec::new();
    for row in rows {
        let continuing_key = format!("{}:{}", row.get::<_, String>(4), row.get::<_, String>(5));
        let waiting_key = format!("{}:{}", row.get::<_, String>(6), row.get::<_, String>(7));
        if let (Some(continuing), Some(waiting)) = (
            normalized_volume_key(&continuing_key),
            normalized_volume_key(&waiting_key),
        ) {
            decisions.push(OverlapDecisionItem {
                id: row.get(0),
                list_id: row.get(1),
                created_at: row.get(2),
                updated_at: row.get(3),
                continuing_volume_id: continuing,
                waiting_volume_id: waiting,
            });
        }
    }
    Ok(decisions)
}

async fn load_thread_volume_candidates(
    tx: &Transaction<'_>,
    user_id: i32,
) -> Result<Vec<OverlapVolumeCandidate>, ApiError> {
    let rows = tx
        .query(
            "SELECT t.id, t.title
             FROM threads t
             WHERE t.user_id = $1",
            &[&user_id],
        )
        .await
        .map_err(db::query_error)?;

    let thread_ids: Vec<i32> = rows.iter().map(|row| row.get(0)).collect();
    if thread_ids.is_empty() {
        return Ok(Vec::new());
    }

    let confirmed = tx
        .query(
            "SELECT t.id, ei.external_id
             FROM threads t
             JOIN thread_external_series_mappings tem ON tem.thread_id = t.id
             JOIN external_identities ei ON ei.id = tem.external_identity_id
             WHERE t.id = ANY($1) AND t.user_id = $2
               AND tem.status = 'confirmed'
               AND ei.entity_type = 'series'
               AND ei.provider = 'comicvine'",
            &[&thread_ids, &user_id],
        )
        .await
        .map_err(db::query_error)?;

    let catalog = tx
        .query(
            "SELECT t.id, ei.external_id
             FROM threads t
             JOIN catalog_series cs ON cs.id = t.catalog_series_id
             JOIN external_identities ei ON ei.id = cs.canonical_external_identity_id
             WHERE t.id = ANY($1) AND t.user_id = $2
               AND ei.entity_type = 'series'
               AND ei.provider = 'comicvine'",
            &[&thread_ids, &user_id],
        )
        .await
        .map_err(db::query_error)?;

    let mut candidates: std::collections::HashMap<i32, std::collections::HashSet<String>> =
        std::collections::HashMap::new();
    for row in confirmed.iter().chain(catalog.iter()) {
        let thread_id: i32 = row.get(0);
        let external_id: String = row.get(1);
        if let Some(key) = normalized_volume_key(&format!("comicvine:{}", external_id)) {
            candidates.entry(thread_id).or_default().insert(key);
        }
    }

    let mut result = Vec::new();
    for row in rows {
        let thread_id: i32 = row.get(0);
        let title: String = row.get(1);
        if let Some(keys) = candidates.get(&thread_id) {
            if keys.len() == 1 {
                if let Some(volume_id) = keys.iter().next() {
                    result.push(OverlapVolumeCandidate {
                        thread_id,
                        thread_title: title,
                        volume_id: volume_id.clone(),
                    });
                }
            }
        }
    }
    result.sort_by_key(|candidate| candidate.thread_id);
    Ok(result)
}

async fn resolve_volume_identity_ids(
    tx: &Transaction<'_>,
    keys: &[String],
) -> Result<std::collections::HashMap<String, i32>, ApiError> {
    if keys.is_empty() {
        return Ok(std::collections::HashMap::new());
    }
    let mut candidates = std::collections::HashSet::new();
    for key in keys {
        for variant in volume_external_id_variants(key) {
            candidates.insert(variant);
        }
    }
    if candidates.is_empty() {
        return Ok(std::collections::HashMap::new());
    }
    let candidate_vec: Vec<String> = candidates.into_iter().collect();
    let rows = tx
        .query(
            "SELECT id, external_id FROM external_identities
              WHERE provider = 'comicvine' AND entity_type = 'series'
              AND external_id = ANY($1::text[])",
            &[&candidate_vec],
        )
        .await
        .map_err(db::query_error)?;

    let mut resolved = std::collections::HashMap::new();
    for row in rows {
        let id: i32 = row.get(0);
        let external_id: String = row.get(1);
        if let Some(canonical) = normalized_volume_key(&format!("comicvine:{}", external_id)) {
            resolved.insert(canonical, id);
        }
    }
    let mut result = std::collections::HashMap::new();
    for key in keys {
        if let Some(norm) = normalized_volume_key(key) {
            if let Some(&id) = resolved.get(&norm) {
                result.insert(norm, id);
            }
        }
    }
    Ok(result)
}

async fn validate_projection(
    tx: &Transaction<'_>,
    user: &AuthenticatedUser,
    projected: &std::collections::HashMap<i32, Vec<(String, String)>>,
) -> Result<(), ApiError> {
    let mut inputs = option_inputs::load_inputs_in_transaction(tx, *user).await?;
    let names = inputs
        .lists
        .iter()
        .map(|list| (list.list_id, list.name.clone()))
        .collect::<BTreeMap<_, _>>();

    // Update overlap decisions in the loaded inputs
    for list in &mut inputs.lists {
        if let Some(decisions) = projected.get(&list.list_id) {
            list.overlap_decisions = decisions
                .iter()
                .map(|(c, w)| option_inputs::OverlapDecision {
                    continuing_volume_id: c.clone(),
                    waiting_volume_id: w.clone(),
                })
                .collect();
        }
    }

    ValidatedReadingInputs::new(inputs.clone(), &names)
        .map_err(|error| custom_cbl_cycle_conflict(error, &inputs))?;
    Ok(())
}

fn guard_version(current: &str, expected: Option<&str>) -> Result<(), ApiError> {
    if let Some(expected) = expected {
        let matches = match (
            timestamp_token_to_utc(current),
            timestamp_token_to_utc(expected),
        ) {
            (Some(current_at), Some(expected_at)) => current_at == expected_at,
            _ => current == expected,
        };
        if !matches {
            return Err(ApiError::structured(
                StatusCode::CONFLICT,
                json!({
                    "code": "reading_overlap_version_conflict",
                    "message": "The Reading List's overlap decisions changed since they were read",
                    "updated_at": current
                }),
            ));
        }
    }
    Ok(())
}

// ========================================================================
// Handlers
// ========================================================================

/// `GET /api/v2/reading-lists/issue-candidates`
pub async fn search_custom_cbl_issues(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Query(params): Query<CustomCBLSearchParams>,
) -> Response {
    async fn inner(
        state: Arc<AppState>,
        user_id: i32,
        params: CustomCBLSearchParams,
    ) -> Result<Json<Vec<CustomCBLIssueSearchResult>>, SearchError> {
        let raw_q = params.q.unwrap_or_default();
        let mut validation_errors = Vec::new();
        if raw_q.chars().count() > MAX_SEARCH_Q_LENGTH {
            validation_errors.push(validation_string_too_long("q", &raw_q, MAX_SEARCH_Q_LENGTH));
        }
        let limit = parse_search_limit(params.limit.as_deref(), &mut validation_errors);
        let Some(limit) = limit else {
            return Err(SearchError::ValidationItems(validation_errors));
        };
        if !validation_errors.is_empty() {
            return Err(SearchError::ValidationItems(validation_errors));
        }

        let conn = db::checkout(&state).await?;
        let normalized = raw_q.trim();
        let mut query = String::from(
            "SELECT i.id, i.thread_id, t.title, i.issue_number, i.status
             FROM issues i
             JOIN threads t ON t.id=i.thread_id
             WHERE t.user_id=$1",
        );
        let pattern;
        let mut params_vec: Vec<&(dyn ToSql + Sync)> = vec![&user_id];
        if !normalized.is_empty() {
            query.push_str(" AND (t.title ILIKE $2 OR i.issue_number ILIKE $2 OR (t.title || ' #' || i.issue_number) ILIKE $2)");
            pattern = format!("%{}%", normalized);
            params_vec.push(&pattern);
        }
        query.push_str(" ORDER BY t.title ASC, i.position ASC, i.id ASC");
        query.push_str(" LIMIT $");
        query.push_str(&(params_vec.len() + 1).to_string());
        params_vec.push(&limit);

        let rows = conn
            .query(&query, &params_vec)
            .await
            .map_err(db::query_error)?;
        Ok(Json(
            rows.iter()
                .map(|row| CustomCBLIssueSearchResult {
                    issue_id: row.get(0),
                    thread_id: row.get(1),
                    series_name: row.get(2),
                    issue_number: row.get(3),
                    status: row.get(4),
                })
                .collect(),
        ))
    }

    match inner(state, user.id(), params).await {
        Ok(response) => response.into_response(),
        Err(error) => error.into_response(),
    }
}

const MAX_SEARCH_Q_LENGTH: usize = 200;
const MAX_SEARCH_LIMIT: i64 = 100;
const DEFAULT_SEARCH_LIMIT: i64 = 30;

/// Query params for custom CBL issue search. Parsed as raw strings so malformed
/// values can be rejected with the Python/FastAPI 422 contract at the handler boundary.
#[derive(Debug, Default, Deserialize)]
pub struct CustomCBLSearchParams {
    #[serde(default)]
    pub q: Option<String>,
    #[serde(default)]
    pub limit: Option<String>,
}

#[derive(Debug)]
enum SearchError {
    /// One or more `limit`/`q` values failed Python/FastAPI validation.
    ValidationItems(Vec<ValidationErrorItem>),
    Database(ApiError),
}

impl From<ApiError> for SearchError {
    fn from(error: ApiError) -> Self {
        Self::Database(error)
    }
}

impl IntoResponse for SearchError {
    fn into_response(self) -> Response {
        match self {
            SearchError::ValidationItems(items) => (
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(ValidationErrorResponse { detail: items }),
            )
                .into_response(),
            SearchError::Database(error) => error.into_response(),
        }
    }
}

fn validation_string_too_long(field: &str, input: &str, max_length: usize) -> ValidationErrorItem {
    ValidationErrorItem {
        error_type: "string_too_long".to_string(),
        loc: vec!["query".to_string(), field.to_string()],
        msg: format!("String should have at most {max_length} characters"),
        input: serde_json::Value::String(input.to_string()),
        ctx: Some(serde_json::json!({"max_length": max_length})),
    }
}

fn validation_int_parsing(field: &str, input: &str) -> ValidationErrorItem {
    ValidationErrorItem {
        error_type: "int_parsing".to_string(),
        loc: vec!["query".to_string(), field.to_string()],
        msg: "Input should be a valid integer, unable to parse string as an integer".to_string(),
        input: serde_json::Value::String(input.to_string()),
        ctx: None,
    }
}

fn validation_greater_than_equal(field: &str, input: &str, ge: i64) -> ValidationErrorItem {
    ValidationErrorItem {
        error_type: "greater_than_equal".to_string(),
        loc: vec!["query".to_string(), field.to_string()],
        msg: format!("Input should be greater than or equal to {ge}"),
        input: serde_json::Value::String(input.to_string()),
        ctx: Some(serde_json::json!({"ge": ge})),
    }
}

fn validation_less_than_equal(field: &str, input: &str, le: i64) -> ValidationErrorItem {
    ValidationErrorItem {
        error_type: "less_than_equal".to_string(),
        loc: vec!["query".to_string(), field.to_string()],
        msg: format!("Input should be less than or equal to {le}"),
        input: serde_json::Value::String(input.to_string()),
        ctx: Some(serde_json::json!({"le": le})),
    }
}

fn parse_search_limit(
    raw: Option<&str>,
    validation_errors: &mut Vec<ValidationErrorItem>,
) -> Option<i64> {
    let Some(value) = raw else {
        return Some(DEFAULT_SEARCH_LIMIT);
    };
    match value.parse::<i64>() {
        Ok(parsed) => {
            if parsed < 1 {
                validation_errors.push(validation_greater_than_equal("limit", value, 1));
                None
            } else if parsed > MAX_SEARCH_LIMIT {
                validation_errors.push(validation_less_than_equal(
                    "limit",
                    value,
                    MAX_SEARCH_LIMIT,
                ));
                None
            } else {
                Some(parsed)
            }
        }
        Err(_) => {
            if !value.is_empty() && value.chars().all(|c| c.is_ascii_digit()) {
                // Python `Query(le=100)` reports values above the i64 range as less_than_equal.
                validation_errors.push(validation_less_than_equal(
                    "limit",
                    value,
                    MAX_SEARCH_LIMIT,
                ));
            } else {
                validation_errors.push(validation_int_parsing("limit", value));
            }
            None
        }
    }
}

#[allow(dead_code)]
async fn load_entries_conn(
    conn: &deadpool_postgres::Object,
    list_id: i32,
) -> Result<Vec<CustomCBLEntryResponse>, ApiError> {
    let rows = conn
        .query(
            "SELECT e.id, e.position, e.issue_id, i.thread_id, t.title, i.issue_number,
                    i.status, e.is_checkpoint, e.gate, e.skipped,
                    e.checkpoint_target_issue_ids::text
             FROM custom_cbl_entries e
             JOIN issues i ON i.id=e.issue_id
             JOIN threads t ON t.id=i.thread_id
             WHERE e.list_id=$1
             ORDER BY e.position, e.id",
            &[&list_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(rows
        .iter()
        .map(|row| CustomCBLEntryResponse {
            id: row.get(0),
            position: row.get(1),
            issue_id: row.get(2),
            thread_id: row.get(3),
            series_name: row.get(4),
            issue_number: row.get(5),
            status: row.get(6),
            is_checkpoint: row.get(7),
            gate: row.get(8),
            skipped: row.get(9),
            checkpoint_target_issue_ids: serde_json::from_str::<Vec<i32>>(
                &row.get::<_, String>(10),
            )
            .unwrap_or_default(),
        })
        .collect())
}

/// `GET /api/v2/reading-lists/{list_id}/export`
pub async fn export_custom_cbl(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i32>,
) -> Result<Response, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    lock_reader(&tx, user.id()).await?;
    let row = tx
        .query_opt(
            "SELECT name FROM custom_cbl_lists WHERE id=$1 AND user_id=$2",
            &[&list_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound("Reading List not found".to_string()))?;
    let name: String = row.get(0);
    let entries = load_list_entries_for_export(&tx, list_id).await?;
    tx.commit().await.map_err(db::query_error)?;

    let xml = export_custom_cbl_xml(&name, &entries);
    Response::builder()
        .status(StatusCode::OK)
        .header("Content-Type", "application/xml")
        .header(
            "Content-Disposition",
            format!("attachment; filename=\"custom-cbl-{}.cbl\"", list_id),
        )
        .body(axum::body::Body::from(xml))
        .map_err(|error| {
            tracing::debug!(
                error_kind = crate::error_kind(&error),
                "preserved underlying error before mapping"
            );
            ApiError::Internal("Custom CBL export response failed".into())
        })
}

/// Validate every merged node reference before the plan document is written.
///
/// Mirrors Python `validate_node_ownership`: issue refs resolve through the
/// owning Thread, and thread/crossover refs are checked in bulk so validation
/// never issues a query per node.
async fn validate_merged_node_ownership(
    tx: &Transaction<'_>,
    user: &AuthenticatedUser,
    owned_issues: &BTreeSet<i32>,
    nodes: &[serde_json::Value],
) -> Result<(), ApiError> {
    let node_ref = |node: &serde_json::Value| -> Option<i32> {
        node.get("ref_id")
            .and_then(|value| value.as_i64())
            .and_then(|value| i32::try_from(value).ok())
    };
    let of_type = |kind: &str| -> Vec<i32> {
        nodes
            .iter()
            .filter(|node| node.get("node_type").and_then(|v| v.as_str()) == Some(kind))
            .filter_map(node_ref)
            .collect()
    };
    let thread_refs: BTreeSet<i32> = of_type("thread").into_iter().collect();
    let crossover_refs: BTreeSet<i32> = of_type("crossover").into_iter().collect();

    let owned_threads: BTreeSet<i32> = if thread_refs.is_empty() {
        BTreeSet::new()
    } else {
        let refs: Vec<i32> = thread_refs.iter().copied().collect();
        tx.query(
            "SELECT id FROM threads WHERE user_id=$1 AND id=ANY($2)",
            &[&user.id(), &refs],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| row.get(0))
        .collect()
    };
    let owned_crossovers: BTreeSet<i32> = if crossover_refs.is_empty() {
        BTreeSet::new()
    } else {
        let refs: Vec<i32> = crossover_refs.iter().copied().collect();
        tx.query(
            "SELECT id FROM dependency_groups WHERE user_id=$1 AND id=ANY($2)",
            &[&user.id(), &refs],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| row.get(0))
        .collect()
    };

    for node in nodes {
        let kind = node.get("node_type").and_then(|v| v.as_str()).unwrap_or("");
        let reference = node_ref(node);
        let owned = match kind {
            "issue" => reference.is_some_and(|id| owned_issues.contains(&id)),
            "thread" => reference.is_some_and(|id| owned_threads.contains(&id)),
            "crossover" => reference.is_some_and(|id| owned_crossovers.contains(&id)),
            _ => false,
        };
        if !owned {
            return Err(ApiError::structured(
                StatusCode::UNPROCESSABLE_ENTITY,
                json!({
                    "code": "dangling_plan_reference",
                    "node_id": node.get("id").cloned().unwrap_or(serde_json::Value::Null),
                }),
            ));
        }
    }
    Ok(())
}

/// Mirror Python `editor_nodes_for_plan`: `reading_plan_issues` is the
/// membership authority and `nodes_json` only supplies annotations for
/// matching occurrence ids. Legacy plans with no membership rows fall back to
/// the persisted document. Applying on top of raw `nodes_json` would rebuild
/// the overlay from a stale superset and silently drop authoritative members.
async fn editor_nodes_for_plan(
    tx: &Transaction<'_>,
    plan_id: i32,
    nodes_json: &serde_json::Value,
) -> Result<Vec<serde_json::Value>, ApiError> {
    let rows = tx
        .query(
            "SELECT occurrence_id, issue_id, lane_id, display_position, label,
                    reader_role, reader_optional, is_checkpoint,
                    source_metadata_json::text
             FROM reading_plan_issues WHERE plan_id=$1
             ORDER BY lane_id, display_position",
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;
    let stored = nodes_json.as_array().cloned().unwrap_or_default();
    if rows.is_empty() {
        return Ok(stored);
    }

    // ContinuityPlanNode fields; stale JSON keys are dropped like Python's
    // `model_validate`, while source/reader/checkpoint annotations survive.
    const ISSUE_FIELDS: &[&str] = &[
        "id",
        "node_type",
        "ref_id",
        "lane_id",
        "position",
        "label",
        "source_role",
        "source_confidence",
        "source_explanation",
        "source_paths",
        "source_cbl_placements",
        "source_story_arc_ids",
        "source_target_story_arc_id",
        "reader_role",
        "reader_optional",
        "is_checkpoint",
        "checkpoint_target_ref_id",
        "checkpoint_target_ref_ids",
        "convergence_gate",
    ];

    let mut json_by_id: HashMap<String, serde_json::Value> = HashMap::new();
    let mut extra_non_issue = Vec::new();
    for raw in &stored {
        match raw.get("node_type").and_then(|value| value.as_str()) {
            Some("issue") => {
                if let Some(id) = raw
                    .get("id")
                    .and_then(|value| value.as_str())
                    .filter(|id| !id.is_empty())
                {
                    json_by_id.insert(id.to_string(), raw.clone());
                }
            }
            Some("crossover") | Some("thread") => extra_non_issue.push(raw.clone()),
            _ => {}
        }
    }

    let mut nodes = Vec::with_capacity(rows.len() + extra_non_issue.len());
    for row in &rows {
        let occurrence_id: String = row.get(0);
        let issue_id: i32 = row.get(1);
        let lane_id: String = row.get(2);
        let display_position: i32 = row.get(3);
        let label: Option<String> = row.get(4);
        let reader_role: Option<String> = row.get(5);
        let reader_optional: Option<bool> = row.get(6);
        let is_checkpoint: bool = row.get(7);
        let metadata_text: Option<String> = row.get(8);

        let mut node = json_by_id
            .get(&occurrence_id)
            .and_then(serde_json::Value::as_object)
            .map(|object| {
                object
                    .iter()
                    .filter(|(key, _)| ISSUE_FIELDS.contains(&key.as_str()))
                    .map(|(key, value)| (key.clone(), value.clone()))
                    .collect::<serde_json::Map<String, serde_json::Value>>()
            })
            .unwrap_or_default();
        node.insert("id".into(), serde_json::Value::String(occurrence_id));
        node.insert("node_type".into(), json!("issue"));
        node.insert("ref_id".into(), json!(issue_id));
        node.insert("lane_id".into(), serde_json::Value::String(lane_id));
        node.insert("position".into(), json!(display_position));
        node.insert("is_checkpoint".into(), json!(is_checkpoint));
        if let Some(label) = label {
            node.insert("label".into(), json!(label));
        }
        if let Some(role) = reader_role {
            node.insert("reader_role".into(), json!(role));
        }
        if let Some(optional) = reader_optional {
            node.insert("reader_optional".into(), json!(optional));
        }
        if let Some(text) = metadata_text {
            if let Ok(serde_json::Value::Object(metadata)) =
                serde_json::from_str::<serde_json::Value>(&text)
            {
                for (key, value) in metadata {
                    if node.get(&key).is_none_or(|current| current.is_null()) {
                        node.insert(key, value);
                    }
                }
            }
        }
        nodes.push(serde_json::Value::Object(node));
    }
    nodes.extend(extra_non_issue);
    fn node_position(node: &serde_json::Value) -> i64 {
        node.get("position")
            .and_then(|value| value.as_i64())
            .unwrap_or(0)
    }
    fn node_lane(node: &serde_json::Value) -> &str {
        node.get("lane_id")
            .and_then(|value| value.as_str())
            .unwrap_or("")
    }
    fn node_id(node: &serde_json::Value) -> &str {
        node.get("id")
            .and_then(|value| value.as_str())
            .unwrap_or("")
    }
    nodes.sort_by(|left, right| {
        node_position(left)
            .cmp(&node_position(right))
            .then_with(|| node_lane(left).cmp(node_lane(right)))
            .then_with(|| node_id(left).cmp(node_id(right)))
    });
    Ok(nodes)
}

/// Re-attach current custom-CBL provenance to a reused or newly created plan
/// node, mirroring Python `_with_source_provenance`: existing source paths keep
/// their order with this source appended once, placements for this source are
/// replaced by the fresh one, and the explanation defaults when unset.
fn attach_source_provenance(
    node: &mut serde_json::Value,
    source_path: &str,
    source_position: i32,
    list_name: &str,
) {
    let mut paths: Vec<serde_json::Value> = node
        .get("source_paths")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let path_value = serde_json::Value::String(source_path.to_string());
    if !paths.contains(&path_value) {
        paths.push(path_value);
    }
    node["source_paths"] = serde_json::Value::Array(paths);

    let mut placements: Vec<serde_json::Value> = node
        .get("source_cbl_placements")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    placements.retain(|p| p.get("source_path").and_then(|v| v.as_str()) != Some(source_path));
    placements.push(json!({
        "source_path": source_path,
        "position": source_position,
    }));
    node["source_cbl_placements"] = serde_json::Value::Array(placements);

    let explanation_absent = node
        .get("source_explanation")
        .and_then(|v| v.as_str())
        .is_none_or(|text| text.is_empty());
    if explanation_absent {
        node["source_explanation"] = json!(format!("Added from custom CBL '{list_name}'."));
    }
}

fn node_lane(node: &serde_json::Value) -> &str {
    node.get("lane_id").and_then(|v| v.as_str()).unwrap_or("")
}

/// `POST /api/v2/reading-lists/{list_id}/reading-plans/{plan_id}/applications`
pub async fn apply_custom_cbl(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path((list_id, plan_id)): Path<(i32, i32)>,
    Json(request): Json<CustomCBLApplyRequest>,
) -> Result<Json<CustomCBLApplyResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    lock_reader(&tx, user.id()).await?;

    // Load the custom CBL list
    let list_row = tx
        .query_opt(
            "SELECT id, name, mode FROM custom_cbl_lists WHERE id=$1 AND user_id=$2 FOR SHARE",
            &[&list_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound("Reading List not found".to_string()))?;
    let list_name: String = list_row.get(1);
    let _list_mode: String = list_row.get(2);

    // Load the continuity plan
    let plan_row = tx
        .query_opt(
            "SELECT id, user_id, name, lanes_json, nodes_json, ordering_mode, created_at, updated_at
             FROM continuity_plans WHERE id=$1 AND user_id=$2 FOR UPDATE",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound(format!("Continuity plan {} not found", plan_id)))?;

    // Load CBL entries
    let entries = load_entries(&tx, list_id).await?;
    if entries.is_empty() {
        return Err(ApiError::structured(
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({
                "code": "custom_cbl_empty",
                "message": "Custom CBL has no issues"
            }),
        ));
    }

    // Parse plan data
    let lanes_json: serde_json::Value = plan_row.get(3);
    let nodes_json: serde_json::Value = plan_row.get(4);
    let ordering_mode: String = plan_row.get(5);
    let created_at: chrono::DateTime<chrono::Utc> = plan_row.get(6);
    let updated_at: chrono::DateTime<chrono::Utc> = plan_row.get(7);

    // Validate optimistic concurrency. Compare parsed instants, not raw
    // strings, so a token written by Python (`+00:00`) matches the stored
    // instant regardless of text formatting.
    if let Some(expected) = request.expected_updated_at.as_deref() {
        let parsed = chrono::DateTime::parse_from_rfc3339(expected)
            .map(|value| value.with_timezone(&chrono::Utc));
        match parsed {
            Ok(expected_at) if expected_at == updated_at => {}
            Ok(_) => {
                return Err(ApiError::structured(
                    StatusCode::CONFLICT,
                    json!({
                        "code": "plan_version_conflict",
                        "expected_updated_at": updated_at.to_rfc3339()
                    }),
                ));
            }
            Err(_) => {
                return Err(ApiError::Unprocessable(format!(
                    "Input should be a valid datetime, unable to parse string as a datetime: \"{expected}\""
                )));
            }
        }
    }

    // Determine target lane; an empty plan gets the same default lane the
    // Python writer creates (ContinuityPlanLane(id="custom-cbl", ...)).
    let mut lanes: Vec<serde_json::Value> =
        serde_json::from_value(lanes_json.clone()).unwrap_or_default();
    let target_lane_id = if let Some(lane_id) = request.lane_id {
        lane_id
    } else if !lanes.is_empty() {
        lanes
            .iter()
            .min_by_key(|l| l.get("order").and_then(|v| v.as_i64()).unwrap_or(0))
            .and_then(|l| l.get("id").and_then(|v| v.as_str()))
            .unwrap_or("custom-cbl")
            .to_string()
    } else {
        lanes.push(json!({"id": "custom-cbl", "name": "Custom CBL", "order": 0}));
        "custom-cbl".to_string()
    };

    // Verify lane exists
    if !lanes
        .iter()
        .any(|l| l.get("id").and_then(|v| v.as_str()) == Some(&target_lane_id))
    {
        return Err(ApiError::structured(
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({
                "code": "custom_cbl_lane_not_found",
                "lane_id": target_lane_id
            }),
        ));
    }

    // Read membership-authoritative editor nodes: Python applies on top of
    // `editor_nodes_for_plan`, where `reading_plan_issues` overrides a stale
    // `nodes_json` superset. Reading the persisted document directly here
    // would let `:apply` drop authoritative members during the overlay rebuild.
    let mut nodes = editor_nodes_for_plan(&tx, plan_id, &nodes_json).await?;

    // Load all owned issue IDs for validation
    let owned_issues: BTreeSet<i32> = {
        let rows = tx
            .query(
                "SELECT i.id FROM issues i JOIN threads t ON t.id=i.thread_id WHERE t.user_id=$1",
                &[&user.id()],
            )
            .await
            .map_err(db::query_error)?;
        rows.iter().map(|r| r.get(0)).collect()
    };

    // Merge CBL into lane
    let source_path = format!("custom-cbl:{}", list_id);
    let source_issue_ids: Vec<i32> = entries.iter().map(|e| e.issue_id).collect();
    let source_issue_set: BTreeSet<i32> = source_issue_ids.iter().copied().collect();

    let is_issue_node =
        |node: &serde_json::Value| node.get("node_type").and_then(|v| v.as_str()) == Some("issue");
    let node_ref_id =
        |node: &serde_json::Value| node.get("ref_id").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
    // Clean this CBL's stale provenance from every node except cross-lane
    // source issues, which stay untouched: Python leaves them in their own
    // lane and reports them as reused, so applying a CBL never moves or
    // duplicates an issue across lanes.
    for node in nodes.iter_mut() {
        let is_cross_lane_source = is_issue_node(node)
            && source_issue_set.contains(&node_ref_id(node))
            && node_lane(node) != target_lane_id;
        if is_cross_lane_source {
            continue;
        }
        let mut clear_paths = false;
        if let Some(paths) = node.get_mut("source_paths").and_then(|v| v.as_array_mut()) {
            paths.retain(|p| p.as_str() != Some(source_path.as_str()));
            clear_paths = paths.is_empty();
        }
        if clear_paths {
            node["source_paths"] = serde_json::Value::Null;
        }
        let mut clear_placements = false;
        if let Some(placements) = node
            .get_mut("source_cbl_placements")
            .and_then(|v| v.as_array_mut())
        {
            placements.retain(|p| {
                p.get("source_path").and_then(|v| v.as_str()) != Some(source_path.as_str())
            });
            clear_placements = placements.is_empty();
        }
        if clear_placements {
            node["source_cbl_placements"] = serde_json::Value::Null;
        }
        if let Some(explanation) = node.get("source_explanation").and_then(|v| v.as_str()) {
            if explanation.starts_with("Added from custom CBL '") {
                node["source_explanation"] = serde_json::Value::Null;
            }
        }
    }

    // Index existing source issues across every lane; a source issue appearing
    // twice anywhere in the plan is a 422, matching Python's
    // `custom_cbl_duplicate_plan_issue` guard.
    let mut existing_by_issue: BTreeMap<i32, usize> = BTreeMap::new();
    for (idx, node) in nodes.iter().enumerate() {
        if !is_issue_node(node) {
            continue;
        }
        let ref_id = node_ref_id(node);
        if !source_issue_set.contains(&ref_id) {
            continue;
        }
        if existing_by_issue.contains_key(&ref_id) {
            return Err(ApiError::structured(
                StatusCode::UNPROCESSABLE_ENTITY,
                json!({
                    "code": "custom_cbl_duplicate_plan_issue",
                    "issue_id": ref_id
                }),
            ));
        }
        existing_by_issue.insert(ref_id, idx);
    }

    // Build ordered source nodes
    let mut ordered_source_nodes = Vec::new();
    let mut added_issue_ids = Vec::new();
    let mut skipped_existing_issue_ids = Vec::new();

    for entry in entries.iter() {
        match existing_by_issue.get(&entry.issue_id) {
            Some(&existing_idx) => {
                if node_lane(&nodes[existing_idx]) != target_lane_id {
                    // Cross-lane source issue: leave the other lane untouched
                    // and report it as reused instead of duplicating it into
                    // the target lane.
                    skipped_existing_issue_ids.push(entry.issue_id);
                    continue;
                }
                let node = &mut nodes[existing_idx];
                node["is_checkpoint"] = serde_json::json!(entry.is_checkpoint);
                // Clear the legacy singular target so a reused node cannot
                // keep a stale checkpoint reference.
                node["checkpoint_target_ref_id"] = serde_json::Value::Null;
                node["checkpoint_target_ref_ids"] =
                    serde_json::json!(entry.checkpoint_target_issue_ids);
                attach_source_provenance(node, &source_path, entry.position, &list_name);
                skipped_existing_issue_ids.push(entry.issue_id);
                ordered_source_nodes.push(node.clone());
            }
            None => {
                if !owned_issues.contains(&entry.issue_id) {
                    return Err(ApiError::NotFound("Issue not found".to_string()));
                }
                let mut node = json!({
                    "id": format!("custom-cbl-{}-{}", list_id, entry.id),
                    "node_type": "issue",
                    "ref_id": entry.issue_id,
                    "lane_id": target_lane_id,
                    "position": 0,
                    "label": format!("{} #{}", entry.series_name, entry.issue_number),
                    "is_checkpoint": entry.is_checkpoint,
                    "checkpoint_target_ref_id": null,
                    "checkpoint_target_ref_ids": entry.checkpoint_target_issue_ids,
                    "convergence_gate": [],
                });
                attach_source_provenance(&mut node, &source_path, entry.position, &list_name);
                added_issue_ids.push(entry.issue_id);
                ordered_source_nodes.push(node);
            }
        }
    }

    // Merge into target lane
    let target_nodes: Vec<serde_json::Value> = nodes
        .iter()
        .filter(|n| n.get("lane_id").and_then(|v| v.as_str()) == Some(&target_lane_id))
        .cloned()
        .collect();
    let other_nodes: Vec<serde_json::Value> = nodes
        .iter()
        .filter(|n| n.get("lane_id").and_then(|v| v.as_str()) != Some(&target_lane_id))
        .cloned()
        .collect();

    // Find anchor index
    let source_indexes: Vec<usize> = target_nodes
        .iter()
        .enumerate()
        .filter_map(|(idx, node)| {
            if node.get("node_type").and_then(|v| v.as_str()) == Some("issue") {
                let ref_id = node.get("ref_id").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
                if source_issue_set.contains(&ref_id) {
                    Some(idx)
                } else {
                    None
                }
            } else {
                None
            }
        })
        .collect();
    let anchor_index = source_indexes
        .into_iter()
        .min()
        .unwrap_or(target_nodes.len());
    let target_without_source: Vec<serde_json::Value> = target_nodes
        .into_iter()
        .filter(|node| {
            if node.get("node_type").and_then(|v| v.as_str()) == Some("issue") {
                let ref_id = node.get("ref_id").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
                !source_issue_set.contains(&ref_id)
            } else {
                true
            }
        })
        .collect();

    let mut merged_target = Vec::new();
    merged_target.extend(target_without_source[..anchor_index].iter().cloned());
    merged_target.extend(ordered_source_nodes);
    merged_target.extend(target_without_source[anchor_index..].iter().cloned());

    // Renumber positions
    for (pos, node) in merged_target.iter_mut().enumerate() {
        node["position"] = serde_json::json!(pos);
    }

    let mut new_nodes = other_nodes;
    new_nodes.extend(merged_target);

    validate_merged_node_ownership(&tx, &user, &owned_issues, &new_nodes).await?;

    // Graph preflight with new nodes
    let mut inputs = option_inputs::load_inputs_in_transaction(&tx, user).await?;
    let list_names: BTreeMap<i32, String> = inputs
        .lists
        .iter()
        .map(|list| (list.list_id, list.name.clone()))
        .collect();

    // Build overlap decisions from current state
    let decisions_rows = tx
        .query(
            "SELECT d.list_id, ci.provider, ci.external_id, wi.provider, wi.external_id
             FROM custom_cbl_overlap_decisions d
             JOIN external_identities ci ON ci.id = d.continuing_external_identity_id
             JOIN external_identities wi ON wi.id = d.waiting_external_identity_id
             WHERE d.user_id = $1",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;

    let mut overlap_decisions: std::collections::HashMap<i32, Vec<(String, String)>> =
        std::collections::HashMap::new();
    for row in decisions_rows {
        let list_id: i32 = row.get(0);
        let continuing = format!("{}:{}", row.get::<_, String>(1), row.get::<_, String>(2));
        let waiting = format!("{}:{}", row.get::<_, String>(3), row.get::<_, String>(4));
        if let (Some(c), Some(w)) = (
            normalized_volume_key(&continuing),
            normalized_volume_key(&waiting),
        ) {
            overlap_decisions.entry(list_id).or_default().push((c, w));
        }
    }

    // Update overlap decisions in the loaded inputs
    for list in &mut inputs.lists {
        if let Some(decisions) = overlap_decisions.get(&list.list_id) {
            list.overlap_decisions = decisions
                .iter()
                .map(|(c, w)| option_inputs::OverlapDecision {
                    continuing_volume_id: c.clone(),
                    waiting_volume_id: w.clone(),
                })
                .collect();
        }
    }

    ValidatedReadingInputs::new(inputs.clone(), &list_names)
        .map_err(|error| custom_cbl_cycle_conflict(error, &inputs))?;

    // Persist the merged plan document, then rebuild the membership overlay
    // and plan-owned compiled rules in the same transaction, matching the
    // Python writer's `replace_compiled_rules` path.
    let new_lanes_json = serde_json::to_value(&lanes)
        .map_err(|_| ApiError::Internal("lanes serialization failed".into()))?;
    let new_nodes_json = serde_json::to_value(&new_nodes)
        .map_err(|_| ApiError::Internal("nodes serialization failed".into()))?;

    let updated_row = tx
        .query_one(
            "UPDATE continuity_plans
             SET lanes_json = $3, nodes_json = $4, updated_at = NOW()
             WHERE id = $1 AND user_id = $2
             RETURNING updated_at",
            &[&plan_id, &user.id(), &new_lanes_json, &new_nodes_json],
        )
        .await
        .map_err(db::query_error)?;
    let new_updated_at: chrono::DateTime<chrono::Utc> = updated_row.get(0);

    crate::plan_rule_compiler::replace_compiled_rules(
        &tx,
        user.id(),
        plan_id,
        &new_nodes,
        &ordering_mode,
    )
    .await?;

    if ordering_mode == "strict_sequential" {
        crate::issue_service::refresh_blocked_threads(&tx, user.id()).await?;
    }

    tx.commit().await.map_err(db::query_error)?;

    // Return the updated plan with the persisted token
    Ok(Json(CustomCBLApplyResponse {
        id: plan_id,
        user_id: user.id(),
        name: plan_row.get(2),
        ordering_mode,
        lanes: serde_json::from_value(new_lanes_json).unwrap_or_default(),
        nodes: serde_json::from_value(new_nodes_json).unwrap_or_default(),
        created_at: created_at.to_rfc3339(),
        updated_at: new_updated_at.to_rfc3339(),
        added_issue_ids,
        skipped_existing_issue_ids,
    }))
}

/// `GET /api/v2/reading-lists/{list_id}/overlap-decisions`
pub async fn get_overlap_decisions(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i32>,
) -> Result<Json<OverlapDecisionSetResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;

    // Verify ownership and get version token
    let row = tx
        .query_opt(
            "SELECT overlap_decisions_updated_at::text FROM custom_cbl_lists
             WHERE id = $1 AND user_id = $2 FOR SHARE",
            &[&list_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound("Reading List not found".to_string()))?;
    let updated_at: String = row.get(0);

    let decisions = load_list_overlap_decisions(&tx, user.id(), list_id).await?;
    let candidates = load_thread_volume_candidates(&tx, user.id()).await?;

    tx.commit().await.map_err(db::query_error)?;

    Ok(Json(OverlapDecisionSetResponse {
        list_id,
        updated_at,
        decisions,
        candidate_volumes: candidates,
    }))
}

/// `PUT /api/v2/reading-lists/{list_id}/overlap-decisions`
pub async fn save_overlap_decision(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i32>,
    Json(request): Json<OverlapDecisionWrite>,
) -> Result<Json<OverlapDecisionSetResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    lock_reader(&tx, user.id()).await?;

    // Verify ownership and get current token
    let row = tx
        .query_opt(
            "SELECT overlap_decisions_updated_at::text FROM custom_cbl_lists
             WHERE id = $1 AND user_id = $2 FOR SHARE",
            &[&list_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound("Reading List not found".to_string()))?;
    let current_token: String = row.get(0);
    guard_version(&current_token, request.expected_updated_at.as_deref())?;

    // Validate volume keys
    let continuing_key = normalized_volume_key(&request.continuing_volume_id).ok_or_else(|| {
        ApiError::structured(
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({
                "code": "reading_overlap_invalid_volume",
                "message": "An overlap decision must name two exact Comic Vine volumes"
            }),
        )
    })?;
    let waiting_key = normalized_volume_key(&request.waiting_volume_id).ok_or_else(|| {
        ApiError::structured(
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({
                "code": "reading_overlap_invalid_volume",
                "message": "An overlap decision must name two exact Comic Vine volumes"
            }),
        )
    })?;

    if continuing_key == waiting_key {
        return Err(ApiError::structured(
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({
                "code": "reading_overlap_same_volume",
                "message": "An overlap decision must name two distinct volumes"
            }),
        ));
    }

    // Resolve identity IDs
    let resolved =
        resolve_volume_identity_ids(&tx, &[continuing_key.clone(), waiting_key.clone()]).await?;
    let continuing_identity_id = resolved.get(&continuing_key).ok_or_else(|| {
        ApiError::structured(
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({
                "code": "reading_overlap_unknown_volume",
                "message": "An overlap decision must name two known Comic Vine volumes"
            }),
        )
    })?;
    let waiting_identity_id = resolved.get(&waiting_key).ok_or_else(|| {
        ApiError::structured(
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({
                "code": "reading_overlap_unknown_volume",
                "message": "An overlap decision must name two known Comic Vine volumes"
            }),
        )
    })?;

    // Load all decisions for projection validation
    let all_decisions = load_overlap_decisions(&tx, user.id()).await?;
    let mut projected: std::collections::HashMap<i32, Vec<(String, String)>> =
        std::collections::HashMap::new();
    for d in &all_decisions {
        if d.list_id != list_id {
            projected
                .entry(d.list_id)
                .or_default()
                .push((d.continuing_volume_id.clone(), d.waiting_volume_id.clone()));
        }
    }
    // Add the new decision, superseding opposite direction
    let list_decisions = projected.entry(list_id).or_default();
    list_decisions.retain(|(c, w)| {
        !((c == &continuing_key && w == &waiting_key)
            || (c == &waiting_key && w == &continuing_key))
    });
    list_decisions.push((continuing_key.clone(), waiting_key.clone()));

    validate_projection(&tx, &user, &projected).await?;

    // Upsert the decision
    let now = chrono::Utc::now();

    // Delete opposite direction
    tx.execute(
        "DELETE FROM custom_cbl_overlap_decisions
         WHERE list_id = $1 AND user_id = $2
           AND continuing_external_identity_id = $3
           AND waiting_external_identity_id = $4",
        &[
            &list_id,
            &user.id(),
            waiting_identity_id,
            continuing_identity_id,
        ],
    )
    .await
    .map_err(db::query_error)?;

    // Upsert
    let existing = tx
        .query_opt(
            "SELECT id FROM custom_cbl_overlap_decisions
             WHERE list_id = $1 AND user_id = $2
               AND continuing_external_identity_id = $3
               AND waiting_external_identity_id = $4",
            &[
                &list_id,
                &user.id(),
                continuing_identity_id,
                waiting_identity_id,
            ],
        )
        .await
        .map_err(db::query_error)?;

    if let Some(row) = existing {
        let id: i32 = row.get(0);
        tx.execute(
            "UPDATE custom_cbl_overlap_decisions SET updated_at = $2
             WHERE id = $1",
            &[&id, &now],
        )
        .await
        .map_err(db::query_error)?;
    } else {
        tx.execute(
            "INSERT INTO custom_cbl_overlap_decisions
             (user_id, list_id, continuing_external_identity_id, waiting_external_identity_id, created_at, updated_at)
             VALUES ($1,$2,$3,$4,$5,$5)",
            &[&user.id(), &list_id, continuing_identity_id, waiting_identity_id, &now],
        )
        .await
        .map_err(db::query_error)?;
    }

    // Advance version token
    let updated_row = tx
        .query_opt(
            "UPDATE custom_cbl_lists
             SET overlap_decisions_updated_at = $3,
                 updated_at = updated_at
             WHERE id = $1 AND user_id = $2
             RETURNING overlap_decisions_updated_at::text",
            &[&list_id, &user.id(), &now],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound("Reading List not found".to_string()))?;
    let advanced_token: String = updated_row.get(0);

    // Load decisions for response before committing
    let decisions = load_list_overlap_decisions(&tx, user.id(), list_id).await?;
    let candidates = load_thread_volume_candidates(&tx, user.id()).await?;

    tx.commit().await.map_err(db::query_error)?;

    Ok(Json(OverlapDecisionSetResponse {
        list_id,
        updated_at: advanced_token,
        decisions,
        candidate_volumes: candidates,
    }))
}

/// `DELETE /api/v2/reading-lists/{list_id}/overlap-decisions/{decision_id}`
pub async fn delete_overlap_decision(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path((list_id, decision_id)): Path<(i32, i32)>,
    Query(params): Query<DeleteOverlapParams>,
) -> Result<Json<OverlapDecisionSetResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    lock_reader(&tx, user.id()).await?;

    // Verify ownership and get current token
    let row = tx
        .query_opt(
            "SELECT overlap_decisions_updated_at::text FROM custom_cbl_lists
             WHERE id = $1 AND user_id = $2 FOR SHARE",
            &[&list_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound("Reading List not found".to_string()))?;
    let current_token: String = row.get(0);
    guard_version(&current_token, params.expected_updated_at.as_deref())?;

    // Verify decision exists and belongs to this list
    tx.query_opt(
        "SELECT id FROM custom_cbl_overlap_decisions
         WHERE id = $1 AND list_id = $2 AND user_id = $3",
        &[&decision_id, &list_id, &user.id()],
    )
    .await
    .map_err(db::query_error)?
    .ok_or_else(|| ApiError::NotFound(format!("Overlap decision {} not found", decision_id)))?;

    // Load all decisions for projection validation
    let all_decisions = load_overlap_decisions(&tx, user.id()).await?;
    let mut projected: std::collections::HashMap<i32, Vec<(String, String)>> =
        std::collections::HashMap::new();
    for d in &all_decisions {
        if d.id != decision_id {
            projected
                .entry(d.list_id)
                .or_default()
                .push((d.continuing_volume_id.clone(), d.waiting_volume_id.clone()));
        }
    }

    validate_projection(&tx, &user, &projected).await?;

    // Delete the decision
    tx.execute(
        "DELETE FROM custom_cbl_overlap_decisions WHERE id = $1",
        &[&decision_id],
    )
    .await
    .map_err(db::query_error)?;

    // Advance version token
    let new_token = chrono::Utc::now().to_rfc3339();
    let updated_row = tx
        .query_opt(
            "UPDATE custom_cbl_lists
             SET overlap_decisions_updated_at = $3::timestamptz,
                 updated_at = updated_at
             WHERE id = $1 AND user_id = $2
             RETURNING overlap_decisions_updated_at::text",
            &[&list_id, &user.id(), &new_token],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound("Reading List not found".to_string()))?;
    let advanced_token: String = updated_row.get(0);

    // Load decisions for response before committing
    let decisions = load_list_overlap_decisions(&tx, user.id(), list_id).await?;
    let candidates = load_thread_volume_candidates(&tx, user.id()).await?;

    tx.commit().await.map_err(db::query_error)?;

    Ok(Json(OverlapDecisionSetResponse {
        list_id,
        updated_at: advanced_token,
        decisions,
        candidate_volumes: candidates,
    }))
}

#[derive(Deserialize)]
pub struct DeleteOverlapParams {
    pub expected_updated_at: Option<String>,
}

// ========================================================================
// Documentation-only OpenAPI operations for the same-path native contract.
// These describe the live handlers above; they are not mounted anywhere.
// ========================================================================

/// Documentation-only operation for custom CBL issue search.
#[utoipa::path(
    get,
    path = "/api/v2/reading-lists/issue-candidates",
    tag = "reading-lists",
    params(
        ("q" = Option<String>, Query, description = "Case-insensitive title or issue-number filter, max 200 characters"),
        ("limit" = Option<i32>, Query, description = "Maximum results, 1-100 (default 30)")
    ),
    responses(
        (status = 200, description = "Matching owned issues", body = Vec<CustomCBLIssueSearchResult>),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Query failed validation", body = ValidationErrorResponse),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn search_custom_cbl_issues_documentation() {}

/// Documentation-only operation for custom CBL export.
#[utoipa::path(
    get,
    path = "/api/v2/reading-lists/{list_id}/export",
    tag = "reading-lists",
    params(("list_id" = i32, Path, description = "Owned custom CBL identifier")),
    responses(
        (status = 200, description = "Portable .cbl XML document", content((String = "application/xml"))),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Reading List not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn export_custom_cbl_documentation() {}

/// Documentation-only operation for overlap decisions read.
#[utoipa::path(
    get,
    path = "/api/v2/reading-lists/{list_id}/overlap-decisions",
    tag = "reading-lists",
    params(("list_id" = i32, Path, description = "Owned custom CBL identifier")),
    responses(
        (status = 200, description = "Saved overlap decisions and version token", body = OverlapDecisionSetResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Reading List not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_overlap_decisions_documentation() {}

/// Documentation-only operation for overlap decision save.
#[utoipa::path(
    put,
    path = "/api/v2/reading-lists/{list_id}/overlap-decisions",
    tag = "reading-lists",
    params(("list_id" = i32, Path, description = "Owned custom CBL identifier")),
    request_body = OverlapDecisionWrite,
    responses(
        (status = 200, description = "Updated overlap decisions and version token", body = OverlapDecisionSetResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Reading List not found"),
        (status = 409, description = "Stale version token"),
        (status = 422, description = "Unusable or cyclic choice"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn save_overlap_decision_documentation() {}

/// Documentation-only operation for overlap decision removal.
#[utoipa::path(
    delete,
    path = "/api/v2/reading-lists/{list_id}/overlap-decisions/{decision_id}",
    tag = "reading-lists",
    params(
        ("list_id" = i32, Path, description = "Owned custom CBL identifier"),
        ("decision_id" = i32, Path, description = "Overlap decision identifier"),
        ("expected_updated_at" = Option<String>, Query, description = "Decision version token the client last read")
    ),
    responses(
        (status = 200, description = "Updated overlap decisions and version token", body = OverlapDecisionSetResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Reading List not found"),
        (status = 409, description = "Stale version token"),
        (status = 422, description = "Cycle conflict"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn delete_overlap_decision_documentation() {}

/// Documentation-only operation for Reading Plan application.
#[utoipa::path(
    post,
    path = "/api/v2/reading-lists/{list_id}/reading-plans/{plan_id}/applications",
    tag = "reading-lists",
    params(
        ("list_id" = i32, Path, description = "Owned custom CBL identifier"),
        ("plan_id" = i32, Path, description = "Continuity plan identifier")
    ),
    request_body = CustomCBLApplyRequest,
    responses(
        (status = 200, description = "Reading Plan updated with the custom CBL merged into one lane", body = CustomCBLApplyResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Reading List not found"),
        (status = 409, description = "Stale plan version token"),
        (status = 422, description = "Empty list, unknown lane, or cycle conflict"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn apply_custom_cbl_documentation() {}

/// Same-path native contract document for the custom CBL endpoints.
#[derive(utoipa::OpenApi)]
#[openapi(
    info(
        title = "ComicPile native Custom CBL API",
        version = "1.0.0",
        description = "Generated contract for operations served by the native Rust router at the original custom-CBL URLs."
    ),
    paths(
        search_custom_cbl_issues_documentation,
        export_custom_cbl_documentation,
        get_overlap_decisions_documentation,
        save_overlap_decision_documentation,
        delete_overlap_decision_documentation,
        apply_custom_cbl_documentation,
    ),
    components(schemas(
        CustomCBLEntryIntent,
        CustomCBLEntryResponse,
        CustomCBLListItem,
        CustomCBLResponse,
        CustomCBLPredecessorChange,
        CustomCBLIssueSearchResult,
        CustomCBLWrite,
        CustomCBLApplyRequest,
        CustomCBLApplyResponse,
        OverlapDecisionItem,
        OverlapVolumeCandidate,
        OverlapDecisionSetResponse,
        OverlapDecisionWrite,
        crate::reading_list::ReadingListReader,
        crate::reading_list::ReadingListReaderEntry,
        crate::reading_list::ReadingListDependency,
        crate::reading_list::ReadingListBlockerExplanation,
    )),
    modifiers(&CustomCblSecurityAddon)
)]
pub(crate) struct CustomCblApi;

struct CustomCblSecurityAddon;

impl utoipa::Modify for CustomCblSecurityAddon {
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalized_volume_key_accepts_comicvine_ids() {
        assert_eq!(
            normalized_volume_key("comicvine:12345"),
            Some("comicvine:12345".to_string())
        );
        assert_eq!(
            normalized_volume_key("comicvine:4050-12345"),
            Some("comicvine:12345".to_string())
        );
        assert_eq!(
            normalized_volume_key("comicvine:0"),
            Some("comicvine:0".to_string())
        );
        assert_eq!(
            normalized_volume_key("comicvine:abc"),
            Some("comicvine:abc".to_string())
        );
        assert_eq!(
            normalized_volume_key("comicvine:my-vol_1.2"),
            Some("comicvine:my-vol_1.2".to_string())
        );
        assert_eq!(normalized_volume_key("marvel:12345"), None);
        assert_eq!(normalized_volume_key("comicvine:"), None);
        assert_eq!(normalized_volume_key("comicvine: bad"), None);
        assert_eq!(normalized_volume_key(""), None);
    }

    #[test]
    fn validate_mode_accepts_valid_modes() {
        assert_eq!(validate_mode(Some("strict")).unwrap(), "strict");
        assert_eq!(validate_mode(Some("loose")).unwrap(), "loose");
        assert_eq!(validate_mode(None).unwrap(), "loose");
        assert!(validate_mode(Some("invalid")).is_err());
    }

    #[test]
    fn validate_name_rejects_empty_and_long() {
        assert!(validate_name("").is_err());
        assert!(validate_name("   ").is_err());
        assert!(validate_name(&"a".repeat(201)).is_err());
        assert_eq!(validate_name(" Valid Name ").unwrap(), "Valid Name");
    }
}
