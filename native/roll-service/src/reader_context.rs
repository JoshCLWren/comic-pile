//! Same-path Rust cutover for `GET /api/v2/issues/{issue_id}/reader-context`
//! (#4832, part C).
//!
//! The frozen Python oracle is `app/services/reader_context.py` and
//! `app/schemas/reader_context.py`. The payload is bounded, user-scoped and
//! decorative: canonical-series analytics (ComicVine volume confirmed on the
//! requested issue), exact and thread-level crossover membership, and the
//! local reading neighborhood with at most 20 one-hop dependency/continuity
//! edges. Statement-for-statement parity notes:
//!
//! * Ratings are the latest `rate` event per issue (`timestamp DESC, id DESC`),
//!   exactly like Python, and averages use CPython's compensated float `sum`
//!   followed by `round(value, 2)` (round-half-even on the exact binary value).
//! * Edges are ordered `(kind, id)` — `"continuity"` sorts before
//!   `"dependency"` — and truncated to 20, as in Python.
//! * Only the requested issue is ownership-checked (`404 Issue {id} not found`
//!   for missing and foreign issues alike); every other statement is scoped by
//!   the same owner predicates as the Python queries.

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{extract::State, Json};
use chrono::{DateTime, Utc};
use serde::Serialize;
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

const COMICVINE_PROVIDER: &str = "comicvine";
const MAX_RECENT_RATINGS: usize = 5;
const MAX_CHAIN_EDGES: usize = 20;

/// Python `ReaderContextPreviousIssue`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReaderContextPreviousIssue {
    pub issue_id: i32,
    pub issue_number: String,
    pub rating: Option<f64>,
}

/// Python `ReaderContextRecentRating`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReaderContextRecentRating {
    pub issue_id: i32,
    pub issue_number: String,
    pub rating: f64,
}

/// Python `ReaderContextSeries`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReaderContextSeries {
    /// `comicvine` or `unavailable`.
    pub identity_source: String,
    pub canonical_series_id: Option<String>,
    pub series_name: Option<String>,
    pub average_rating: Option<f64>,
    pub ratings_count: i64,
    pub previous_issue: Option<ReaderContextPreviousIssue>,
    pub recent_ratings: Vec<ReaderContextRecentRating>,
    pub highest_rating: Option<f64>,
    pub lowest_rating: Option<f64>,
}

/// Python `ReaderContextCrossoverNextMember`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReaderContextCrossoverNextMember {
    pub issue_id: i32,
    pub issue_number: String,
}

/// Python `ReaderContextCrossover`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReaderContextCrossover {
    pub id: i32,
    pub name: String,
    pub applies_to_current_issue: bool,
    /// `issue` or `thread`.
    pub membership_kind: String,
    pub next_member: Option<ReaderContextCrossoverNextMember>,
    pub average_rating: Option<f64>,
    pub ratings_count: i64,
    pub read_count: i64,
}

/// Python `ReaderContextCrossoverMembership`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReaderContextCrossoverMembership {
    pub id: i32,
    pub name: String,
}

/// Python `ReaderContextLocalIssue`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReaderContextLocalIssue {
    pub issue_id: i32,
    pub issue_number: String,
    pub position: i32,
    pub status: String,
    /// `previous`, `current`, `next` or `future`.
    pub relation: String,
    pub rating: Option<f64>,
    pub crossover_memberships: Vec<ReaderContextCrossoverMembership>,
}

/// Python `ReaderContextEdge`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReaderContextEdge {
    pub id: i32,
    /// `dependency` or `continuity`.
    pub kind: String,
    pub source_issue_id: i32,
    pub target_issue_id: i32,
    pub source_thread_id: Option<i32>,
    pub target_thread_id: Option<i32>,
    pub source_label: Option<String>,
    pub target_label: Option<String>,
    pub source_issue_number: Option<String>,
    pub target_issue_number: Option<String>,
    pub source_thread_title: Option<String>,
    pub target_thread_title: Option<String>,
    pub source_status: Option<String>,
    pub target_status: Option<String>,
    pub note: Option<String>,
    pub explanation: Option<String>,
}

/// Python `ReaderContextLocalChain`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReaderContextLocalChain {
    pub issues: Vec<ReaderContextLocalIssue>,
    pub edges: Vec<ReaderContextEdge>,
}

/// Python `ReaderContextResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReaderContextResponse {
    pub issue_id: i32,
    pub series: ReaderContextSeries,
    pub crossovers: Vec<ReaderContextCrossover>,
    pub local_chain: ReaderContextLocalChain,
}

#[derive(Debug, Clone)]
struct IssueRow {
    id: i32,
    issue_number: String,
    position: i32,
    status: String,
    thread_id: i32,
}

impl IssueRow {
    fn from_row(row: &tokio_postgres::Row, offset: usize) -> Self {
        Self {
            id: row.get(offset),
            issue_number: row.get(offset + 1),
            position: row.get(offset + 2),
            status: row.get(offset + 3),
            thread_id: row.get(offset + 4),
        }
    }
}

#[derive(Debug, Clone)]
struct Group {
    id: i32,
    name: String,
}

type Effective = BTreeMap<i32, (f64, DateTime<Utc>)>;

/// CPython 3.12+ `sum()` over floats: Neumaier-compensated summation.
fn py_sum(values: &[f64]) -> f64 {
    let mut result = 0.0_f64;
    let mut compensation = 0.0_f64;
    for &value in values {
        let total = result + value;
        if total.is_finite() {
            if result.abs() >= value.abs() {
                compensation += (result - total) + value;
            } else {
                compensation += (value - total) + result;
            }
        }
        result = total;
    }
    if compensation != 0.0 && compensation.is_finite() {
        result += compensation;
    }
    result
}

/// Python `round(value, 2)`: correctly rounded, ties to even on the exact value.
fn py_round2(value: f64) -> f64 {
    format!("{value:.2}").parse().unwrap_or(value)
}

fn average(values: &[f64]) -> Option<f64> {
    if values.is_empty() {
        return None;
    }
    Some(py_round2(py_sum(values) / values.len() as f64))
}

fn integer(value: Option<&Value>) -> Option<i64> {
    match value? {
        Value::Number(number) => number.as_i64(),
        Value::String(text) => {
            let trimmed = text.trim();
            if !trimmed.is_empty() && trimmed.bytes().all(|byte| byte.is_ascii_digit()) {
                trimmed.parse().ok()
            } else {
                None
            }
        }
        _ => None,
    }
}

fn string(value: Option<&Value>) -> Option<String> {
    match value? {
        Value::String(text) if !text.trim().is_empty() => Some(text.trim().to_string()),
        _ => None,
    }
}

/// Canonical ComicVine series/volume id and name from confirmed issue metadata.
fn series_identity(metadata: &Value) -> (Option<i64>, Option<String>) {
    match metadata.get("volume") {
        Some(volume @ Value::Object(_)) => (integer(volume.get("id")), string(volume.get("name"))),
        _ => (
            integer(metadata.get("volume_id")),
            string(metadata.get("volume_name")),
        ),
    }
}

#[allow(clippy::too_many_arguments)]
fn edge_explanation(
    kind: &str,
    source_label: &str,
    target_label: &str,
    source_thread_title: Option<&str>,
    current_issue_id: i32,
    source_issue_id: i32,
    target_issue_id: i32,
    target_issue_number: Option<&str>,
    satisfaction: Option<&str>,
) -> String {
    if kind == "dependency" {
        if current_issue_id == source_issue_id {
            let downstream = if target_label.is_empty() {
                "An issue waits on it".to_string()
            } else {
                format!("{target_label} waits on it")
            };
            return format!("{source_label} can be read now. {downstream}.");
        }
        if current_issue_id == target_issue_id {
            return format!("You must read {source_label} first");
        }
        let readable = if !source_label.is_empty()
            && source_thread_title.is_some_and(|title| !title.is_empty())
        {
            format!("{source_label} can be read")
        } else {
            "This issue can be read".to_string()
        };
        return if target_issue_number.is_some_and(|number| !number.is_empty())
            && !target_label.is_empty()
        {
            format!("{readable}, but blocks {target_label}")
        } else {
            readable
        };
    }
    if matches!(satisfaction, Some("item_read" | "all_members_read")) {
        return format!("{source_label} must be read before {target_label}");
    }
    format!("{target_label} waits on a continuity checkpoint before it can be read")
}

async fn effective_ratings(
    conn: &deadpool_postgres::Object,
    issue_ids: &BTreeSet<i32>,
) -> Result<Effective, ApiError> {
    if issue_ids.is_empty() {
        return Ok(BTreeMap::new());
    }
    let ids: Vec<i32> = issue_ids.iter().copied().collect();
    let rows = conn
        .query(
            "SELECT issue_id, rating, \"timestamp\" FROM events
             WHERE type = 'rate' AND issue_id = ANY($1) AND rating IS NOT NULL
             ORDER BY issue_id, \"timestamp\" DESC, id DESC",
            &[&ids],
        )
        .await
        .map_err(db::query_error)?;
    let mut effective = BTreeMap::new();
    for row in rows {
        let issue_id: i32 = row.get(0);
        effective
            .entry(issue_id)
            .or_insert_with(|| (row.get::<_, f64>(1), row.get::<_, DateTime<Utc>>(2)));
    }
    Ok(effective)
}

fn not_found(issue_id: i32) -> ApiError {
    ApiError::NotFound(format!("Issue {issue_id} not found"))
}

/// Build the bounded reader-context payload for one owned issue.
pub(crate) async fn build_reader_context(
    state: &AppState,
    user_id: i32,
    issue_id: i32,
) -> Result<ReaderContextResponse, ApiError> {
    let conn = db::checkout(state).await?;
    let owned = conn
        .query_opt(
            "SELECT i.thread_id, i.position FROM issues i
             JOIN threads t ON t.id = i.thread_id
             WHERE i.id = $1 AND t.user_id = $2",
            &[&issue_id, &user_id],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| not_found(issue_id))?;
    let thread_id: i32 = owned.get(0);
    let current_position: i32 = owned.get(1);

    let ordered: Vec<IssueRow> = conn
        .query(
            "SELECT id, issue_number, position, status, thread_id FROM issues
             WHERE thread_id = $1 ORDER BY position, id",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| IssueRow::from_row(row, 0))
        .collect();
    let current_index = ordered
        .iter()
        .position(|candidate| candidate.id == issue_id)
        .ok_or_else(|| not_found(issue_id))?;
    let previous_issue = current_index
        .checked_sub(1)
        .and_then(|index| ordered.get(index));
    let neighborhood: Vec<&IssueRow> = ordered
        [current_index.saturating_sub(2)..(current_index + 3).min(ordered.len())]
        .iter()
        .collect();

    let identity = conn
        .query_opt(
            "SELECT ei.metadata_json::text
             FROM external_identities ei
             JOIN issue_external_identity_mappings m ON m.external_identity_id = ei.id
             WHERE m.issue_id = $1 AND m.status = 'confirmed'
               AND ei.provider = $2 AND ei.entity_type = 'issue'
             ORDER BY m.confidence DESC NULLS LAST, ei.id
             LIMIT 1",
            &[&issue_id, &COMICVINE_PROVIDER],
        )
        .await
        .map_err(db::query_error)?;
    let (series_id, series_name) = match &identity {
        Some(row) => {
            let text: String = row.get(0);
            let metadata: Value = serde_json::from_str(&text).unwrap_or(Value::Null);
            series_identity(&metadata)
        }
        None => (None, None),
    };
    let (identity_source, series_issues) = match (&identity, series_id) {
        (Some(_), Some(series_id)) => {
            let volume_shape = serde_json::json!({"volume": {"id": series_id}}).to_string();
            let volume_id_shape = serde_json::json!({"volume_id": series_id}).to_string();
            let rows = conn
                .query(
                    "SELECT DISTINCT i.id, i.issue_number, i.position, i.status, i.thread_id
                     FROM issues i
                     JOIN threads t ON t.id = i.thread_id AND t.user_id = $1
                     JOIN issue_external_identity_mappings iem
                       ON iem.issue_id = i.id AND iem.status = 'confirmed'
                     JOIN external_identities ei
                       ON ei.id = iem.external_identity_id
                      AND ei.provider = $2
                      AND ei.entity_type = 'issue'
                     WHERE i.status = 'read'
                       AND (
                         ei.metadata_json::text::jsonb @> ($3::text)::jsonb
                         OR ei.metadata_json::text::jsonb @> ($4::text)::jsonb
                       )
                     ORDER BY i.id",
                    &[
                        &user_id,
                        &COMICVINE_PROVIDER,
                        &volume_shape,
                        &volume_id_shape,
                    ],
                )
                .await
                .map_err(db::query_error)?;
            (
                "comicvine",
                rows.iter()
                    .map(|row| IssueRow::from_row(row, 0))
                    .collect::<Vec<_>>(),
            )
        }
        _ => ("unavailable", vec![]),
    };

    let groups: Vec<Group> = conn
        .query(
            "SELECT DISTINCT g.id, g.name
             FROM dependency_groups g
             JOIN dependency_group_memberships m ON m.group_id = g.id
             WHERE g.user_id = $1
               AND (
                 m.thread_id = $2
                 OR (m.issue_id IS NOT NULL
                     AND m.issue_id IN (SELECT id FROM issues WHERE thread_id = $2))
               )
             ORDER BY g.name, g.id",
            &[&user_id, &thread_id],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| Group {
            id: row.get(0),
            name: row.get(1),
        })
        .collect();
    let group_ids: Vec<i32> = groups.iter().map(|group| group.id).collect();

    let mut members_by_group: BTreeMap<i32, Vec<IssueRow>> = BTreeMap::new();
    if !group_ids.is_empty() {
        let rows = conn
            .query(
                "SELECT m.group_id, i.id, i.issue_number, i.position, i.status, i.thread_id
                 FROM dependency_group_memberships m
                 JOIN issues i ON i.id = m.issue_id
                 JOIN threads t ON t.id = i.thread_id
                 WHERE m.group_id = ANY($1) AND m.issue_id IS NOT NULL AND t.user_id = $2
                 ORDER BY m.group_id, i.id",
                &[&group_ids, &user_id],
            )
            .await
            .map_err(db::query_error)?;
        for row in rows {
            members_by_group
                .entry(row.get(0))
                .or_default()
                .push(IssueRow::from_row(&row, 1));
        }
    }
    let thread_level_group_ids: BTreeSet<i32> = conn
        .query(
            "SELECT m.group_id FROM dependency_group_memberships m
             JOIN dependency_groups g ON g.id = m.group_id
             WHERE g.user_id = $1 AND m.thread_id = $2 AND m.issue_id IS NULL",
            &[&user_id, &thread_id],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| row.get(0))
        .collect();

    let mut rating_issue_ids: BTreeSet<i32> = series_issues.iter().map(|issue| issue.id).collect();
    rating_issue_ids.extend(neighborhood.iter().map(|issue| issue.id));
    if let Some(previous) = previous_issue {
        rating_issue_ids.insert(previous.id);
    }
    for members in members_by_group.values() {
        rating_issue_ids.extend(members.iter().map(|member| member.id));
    }
    let effective = effective_ratings(&conn, &rating_issue_ids).await?;

    let next_unread = ordered
        .iter()
        .find(|candidate| candidate.position > current_position && candidate.status != "read");

    let series = build_series(
        identity_source,
        series_id,
        series_name,
        &series_issues,
        previous_issue,
        &effective,
    );
    let crossovers = build_crossovers(
        &groups,
        &members_by_group,
        issue_id,
        current_position,
        thread_id,
        &effective,
        &thread_level_group_ids,
        next_unread,
    );
    let local_issues = build_local_issues(
        &neighborhood,
        current_position,
        thread_id,
        &groups,
        &members_by_group,
        &effective,
        &thread_level_group_ids,
    );
    let neighborhood_ids: Vec<i32> = neighborhood.iter().map(|issue| issue.id).collect();
    let edges = local_edges(&conn, user_id, &neighborhood_ids, issue_id).await?;

    Ok(ReaderContextResponse {
        issue_id,
        series,
        crossovers,
        local_chain: ReaderContextLocalChain {
            issues: local_issues,
            edges,
        },
    })
}

fn build_series(
    identity_source: &str,
    series_id: Option<i64>,
    series_name: Option<String>,
    series_issues: &[IssueRow],
    previous_issue: Option<&IssueRow>,
    effective: &Effective,
) -> ReaderContextSeries {
    let ratings: Vec<(&IssueRow, f64, DateTime<Utc>)> = series_issues
        .iter()
        .filter_map(|candidate| {
            effective
                .get(&candidate.id)
                .map(|(rating, timestamp)| (candidate, *rating, *timestamp))
        })
        .collect();
    let values: Vec<f64> = ratings.iter().map(|(_, rating, _)| *rating).collect();
    let mut recent = ratings.clone();
    recent.sort_by_key(|item| std::cmp::Reverse((item.2, item.0.id)));
    recent.truncate(MAX_RECENT_RATINGS);
    ReaderContextSeries {
        identity_source: identity_source.to_string(),
        canonical_series_id: series_id.map(|id| id.to_string()),
        series_name,
        average_rating: average(&values),
        ratings_count: ratings.len() as i64,
        previous_issue: previous_issue.map(|previous| ReaderContextPreviousIssue {
            issue_id: previous.id,
            issue_number: previous.issue_number.clone(),
            rating: effective.get(&previous.id).map(|(rating, _)| *rating),
        }),
        recent_ratings: recent
            .iter()
            .map(|(candidate, rating, _)| ReaderContextRecentRating {
                issue_id: candidate.id,
                issue_number: candidate.issue_number.clone(),
                rating: *rating,
            })
            .collect(),
        highest_rating: values.iter().copied().reduce(f64::max),
        lowest_rating: values.iter().copied().reduce(f64::min),
    }
}

#[allow(clippy::too_many_arguments)]
fn build_crossovers(
    groups: &[Group],
    members_by_group: &BTreeMap<i32, Vec<IssueRow>>,
    current_issue_id: i32,
    current_position: i32,
    thread_id: i32,
    effective: &Effective,
    thread_level_group_ids: &BTreeSet<i32>,
    next_unread: Option<&IssueRow>,
) -> Vec<ReaderContextCrossover> {
    groups
        .iter()
        .map(|group| {
            let members: &[IssueRow] = members_by_group
                .get(&group.id)
                .map_or(&[], |members| members.as_slice());
            let member_ratings: Vec<f64> = members
                .iter()
                .filter_map(|member| effective.get(&member.id).map(|(rating, _)| *rating))
                .collect();
            let read_count = members
                .iter()
                .filter(|member| member.status == "read")
                .count() as i64;
            let is_thread_level = thread_level_group_ids.contains(&group.id);
            let nearest = members
                .iter()
                .filter(|member| {
                    member.thread_id == thread_id && member.position > current_position
                })
                .min_by_key(|member| (member.position, member.id));
            let next_member = if let Some(nearest) = nearest {
                Some(ReaderContextCrossoverNextMember {
                    issue_id: nearest.id,
                    issue_number: nearest.issue_number.clone(),
                })
            } else if is_thread_level {
                next_unread.map(|next| ReaderContextCrossoverNextMember {
                    issue_id: next.id,
                    issue_number: next.issue_number.clone(),
                })
            } else {
                None
            };
            ReaderContextCrossover {
                id: group.id,
                name: group.name.clone(),
                applies_to_current_issue: is_thread_level
                    || members.iter().any(|member| member.id == current_issue_id),
                membership_kind: if is_thread_level { "thread" } else { "issue" }.to_string(),
                next_member,
                average_rating: average(&member_ratings),
                ratings_count: member_ratings.len() as i64,
                read_count,
            }
        })
        .collect()
}

fn build_local_issues(
    neighborhood: &[&IssueRow],
    current_position: i32,
    thread_id: i32,
    groups: &[Group],
    members_by_group: &BTreeMap<i32, Vec<IssueRow>>,
    effective: &Effective,
    thread_level_group_ids: &BTreeSet<i32>,
) -> Vec<ReaderContextLocalIssue> {
    neighborhood
        .iter()
        .map(|candidate| {
            let relation = if candidate.position < current_position {
                "previous"
            } else if candidate.position == current_position {
                "current"
            } else if candidate.position == current_position + 1 {
                "next"
            } else {
                "future"
            };
            let memberships = groups
                .iter()
                .filter(|group| {
                    members_by_group.get(&group.id).is_some_and(|members| {
                        members.iter().any(|member| member.id == candidate.id)
                    }) || (candidate.thread_id == thread_id
                        && thread_level_group_ids.contains(&group.id))
                })
                .map(|group| ReaderContextCrossoverMembership {
                    id: group.id,
                    name: group.name.clone(),
                })
                .collect();
            ReaderContextLocalIssue {
                issue_id: candidate.id,
                issue_number: candidate.issue_number.clone(),
                position: candidate.position,
                status: candidate.status.clone(),
                relation: relation.to_string(),
                rating: effective.get(&candidate.id).map(|(rating, _)| *rating),
                crossover_memberships: memberships,
            }
        })
        .collect()
}

struct RawEdge {
    id: i32,
    kind: &'static str,
    source_issue_id: i32,
    target_issue_id: i32,
    note: Option<String>,
    satisfaction: Option<String>,
}

async fn local_edges(
    conn: &deadpool_postgres::Object,
    user_id: i32,
    neighborhood_ids: &[i32],
    current_issue_id: i32,
) -> Result<Vec<ReaderContextEdge>, ApiError> {
    if neighborhood_ids.is_empty() {
        return Ok(vec![]);
    }
    let ids = neighborhood_ids.to_vec();
    let mut raw: Vec<RawEdge> = conn
        .query(
            "SELECT d.id, d.source_issue_id, d.target_issue_id, d.note
             FROM dependencies d
             JOIN issues si ON si.id = d.source_issue_id
             JOIN threads st ON st.id = si.thread_id
             JOIN issues ti ON ti.id = d.target_issue_id
             JOIN threads tt ON tt.id = ti.thread_id
             WHERE st.user_id = $1 AND tt.user_id = $1
               AND (d.source_issue_id = ANY($2) OR d.target_issue_id = ANY($2))",
            &[&user_id, &ids],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| RawEdge {
            id: row.get(0),
            kind: "dependency",
            source_issue_id: row.get(1),
            target_issue_id: row.get(2),
            note: row.get(3),
            satisfaction: None,
        })
        .collect();
    raw.extend(
        conn.query(
            "SELECT id, source_id, target_id, note, satisfaction_type
             FROM continuity_rules
             WHERE user_id = $1 AND legacy_dependency_id IS NULL
               AND source_type = 'issue' AND target_type = 'issue'
               AND (source_id = ANY($2) OR target_id = ANY($2))",
            &[&user_id, &ids],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| RawEdge {
            id: row.get(0),
            kind: "continuity",
            source_issue_id: row.get(1),
            target_issue_id: row.get(2),
            note: row.get(3),
            satisfaction: row.get(4),
        }),
    );
    raw.sort_by(|left, right| (left.kind, left.id).cmp(&(right.kind, right.id)));
    raw.truncate(MAX_CHAIN_EDGES);
    if raw.is_empty() {
        return Ok(vec![]);
    }

    let endpoint_ids: Vec<i32> = raw
        .iter()
        .flat_map(|edge| [edge.source_issue_id, edge.target_issue_id])
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    // issue id -> (thread id, issue number, status)
    let issue_map: BTreeMap<i32, (i32, String, String)> = conn
        .query(
            "SELECT id, thread_id, issue_number, status FROM issues WHERE id = ANY($1)",
            &[&endpoint_ids],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| (row.get(0), (row.get(1), row.get(2), row.get(3))))
        .collect();
    let thread_ids: Vec<i32> = issue_map
        .values()
        .map(|(thread_id, _, _)| *thread_id)
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let thread_map: BTreeMap<i32, String> = if thread_ids.is_empty() {
        BTreeMap::new()
    } else {
        conn.query(
            "SELECT id, title FROM threads WHERE id = ANY($1)",
            &[&thread_ids],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| (row.get(0), row.get(1)))
        .collect()
    };

    struct Endpoint {
        label: Option<String>,
        number: Option<String>,
        title: Option<String>,
        thread_id: Option<i32>,
        status: Option<String>,
    }
    let endpoint = |issue_id: i32| -> Endpoint {
        match issue_map.get(&issue_id) {
            None => Endpoint {
                label: None,
                number: None,
                title: None,
                thread_id: None,
                status: None,
            },
            Some((thread_id, number, status)) => match thread_map.get(thread_id) {
                None => Endpoint {
                    label: Some(format!("Issue #{number}")),
                    number: Some(number.clone()),
                    title: None,
                    thread_id: None,
                    status: Some(status.clone()),
                },
                Some(title) => Endpoint {
                    label: Some(format!("{title} #{number}")),
                    number: Some(number.clone()),
                    title: Some(title.clone()),
                    thread_id: Some(*thread_id),
                    status: Some(status.clone()),
                },
            },
        }
    };

    Ok(raw
        .into_iter()
        .map(|edge| {
            let source = endpoint(edge.source_issue_id);
            let target = endpoint(edge.target_issue_id);
            let human = |label: &Option<String>| {
                label
                    .clone()
                    .unwrap_or_else(|| "a missing issue".to_string())
            };
            let explanation = edge_explanation(
                edge.kind,
                &human(&source.label),
                &human(&target.label),
                source.title.as_deref(),
                current_issue_id,
                edge.source_issue_id,
                edge.target_issue_id,
                target.number.as_deref(),
                edge.satisfaction.as_deref(),
            );
            ReaderContextEdge {
                id: edge.id,
                kind: edge.kind.to_string(),
                source_issue_id: edge.source_issue_id,
                target_issue_id: edge.target_issue_id,
                source_thread_id: source.thread_id,
                target_thread_id: target.thread_id,
                source_label: source.label,
                target_label: target.label,
                source_issue_number: source.number,
                target_issue_number: target.number,
                source_thread_title: source.title,
                target_thread_title: target.title,
                source_status: source.status,
                target_status: target.status,
                note: edge.note,
                explanation: Some(explanation),
            }
        })
        .collect())
}

/// `GET /api/v2/issues/{issue_id}/reader-context`
pub async fn get_issue_reader_context(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    raw_id: Result<axum::extract::Path<String>, axum::extract::rejection::PathRejection>,
) -> Result<Json<ReaderContextResponse>, ApiError> {
    let issue_id = crate::issue_read_state::parse_path_issue_id(raw_id)?;
    Ok(Json(
        build_reader_context(&state, user.id(), issue_id).await?,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn rounding_matches_python_round_half_even_on_exact_binary_value() {
        // Python: round(0.125, 2) == 0.12, round(0.375, 2) == 0.38,
        // round(2.675, 2) == 2.67 (binary value is below the tie).
        assert_eq!(py_round2(0.125), 0.12);
        assert_eq!(py_round2(0.375), 0.38);
        assert_eq!(py_round2(2.675), 2.67);
        assert_eq!(py_round2(3.5), 3.5);
    }

    #[test]
    fn sum_is_compensated_like_cpython() {
        // CPython 3.12+: sum([0.1] * 10) == 1.0 (naive summation gives 0.9999999999999999).
        assert_eq!(py_sum(&[0.1; 10]), 1.0);
        assert_eq!(average(&[]), None);
        assert_eq!(average(&[4.0, 3.5]), Some(3.75));
    }

    #[test]
    fn series_identity_follows_volume_object_then_flat_keys() {
        let nested = json!({"volume": {"id": "42", "name": "  Saga "}});
        assert_eq!(series_identity(&nested), (Some(42), Some("Saga".into())));
        let flat = json!({"volume_id": 7, "volume_name": "Flat"});
        assert_eq!(series_identity(&flat), (Some(7), Some("Flat".into())));
        // A volume object without usable keys does not fall back to flat keys.
        let empty_volume = json!({"volume": {}, "volume_id": 7});
        assert_eq!(series_identity(&empty_volume), (None, None));
        assert_eq!(
            series_identity(&json!({"volume": {"id": "4x"}})),
            (None, None)
        );
    }

    #[test]
    fn explanations_match_python_copy() {
        assert_eq!(
            edge_explanation(
                "dependency",
                "A #1",
                "B #2",
                Some("A"),
                10,
                10,
                20,
                Some("2"),
                None
            ),
            "A #1 can be read now. B #2 waits on it."
        );
        assert_eq!(
            edge_explanation(
                "dependency",
                "A #1",
                "B #2",
                Some("A"),
                20,
                10,
                20,
                Some("2"),
                None
            ),
            "You must read A #1 first"
        );
        assert_eq!(
            edge_explanation(
                "dependency",
                "A #1",
                "B #2",
                Some("A"),
                99,
                10,
                20,
                Some("2"),
                None
            ),
            "A #1 can be read, but blocks B #2"
        );
        assert_eq!(
            edge_explanation(
                "dependency",
                "a missing issue",
                "B #2",
                None,
                99,
                10,
                20,
                None,
                None
            ),
            "This issue can be read"
        );
        assert_eq!(
            edge_explanation(
                "continuity",
                "A #1",
                "B #2",
                None,
                99,
                10,
                20,
                None,
                Some("item_read")
            ),
            "A #1 must be read before B #2"
        );
        assert_eq!(
            edge_explanation(
                "continuity",
                "A #1",
                "B #2",
                None,
                99,
                10,
                20,
                None,
                Some("checkpoint")
            ),
            "B #2 waits on a continuity checkpoint before it can be read"
        );
    }
}
