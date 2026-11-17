//! Canonical Rust-backed `/api/v2/creators*` analytics (#4836).
//!
//! This module is the v2 replacement for the browser-called creator family in
//! `app/api/creators.py`. Every operation is scoped to the authenticated user's
//! own library and served from one bounded, set-based read of that library;
//! there is no per-row fan-out and no Python enrichment hop.
//!
//! Wire shapes mirror the Python Pydantic responses exactly: field names,
//! nullability, ordering, rounding and the literal explanation strings are
//! preserved so the existing React consumers need only switch their base path
//! from `/api/v1` to `/api/v2`.
//!
//! Python handlers remain mounted until authenticated production traffic proves
//! the native v2 ingress; deployed Vercel rewrites shadow them after cutover.

#![forbid(unsafe_code)]

use crate::{
    auth::VerifiedAccessClaims,
    db::{checkout, query_error},
    ApiError, AppState,
};
use axum::{
    extract::{Query, State},
    http::StatusCode,
    Json,
};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    cmp::Ordering,
    collections::{BTreeMap, BTreeSet, HashMap, HashSet},
    sync::Arc,
};
use utoipa::{IntoParams, ToSchema};

const HEADLINE_ROLES: &[&str] = &[
    "writer", "artist", "penciler", "inker", "colorist", "letterer",
];
const TEAM_ELIGIBLE_ROLES: &[&str] = &["writer", "artist", "penciler", "inker", "colorist"];
const MANUAL_CREATOR_ID_BASE: i64 = 1_000_000_000;
const MAX_COMPARISON_CREATORS: usize = 4;
const MIN_COMPARISON_CREATORS: usize = 2;
const MAX_CREATOR_KEYS: usize = 50;
const MAX_SERIES_AGGREGATES: usize = 5;
const MAX_ISSUE_REFS: usize = 5;
const MAX_RANKED_TEAM_PAIRS: usize = 10;
const MAX_SHARED_SERIES: usize = 5;
const MAX_DISCOVERY_ENTRIES: usize = 10;
const MIN_RATED_FOR_RELIABLE: usize = 5;
const MIN_SERIES_SAMPLE: usize = 3;
const INDIVIDUAL_ISSUE_LIMIT: usize = 3;
const MIN_SHARED_TEAM_SAMPLE: usize = 3;
const TREND_MIN_SAMPLE: usize = 6;
const TREND_MIN_DELTA: f64 = 0.5;
const RATING_BUCKETS: [f64; 10] = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0];

const INSUFFICIENT_SERIES_MESSAGE: &str = "Not enough rated issues in a single series yet. A series needs at least 3 rated issues before it is compared as strongest or weakest.";
const INCOMPLETE_METADATA_SERIES_MESSAGE: &str =
    "Series with enough rated issues are not compared yet because creator metadata is still incomplete.";
const NON_HEADLINE_SERIES_MESSAGE: &str = "Series with enough rated issues are not compared yet because some of those ratings come from credits that do not count toward your average.";

fn bad_request(msg: impl Into<String>) -> ApiError {
    ApiError::with_status(StatusCode::BAD_REQUEST, msg.into())
}

fn not_found(msg: impl Into<String>) -> ApiError {
    ApiError::NotFound(msg.into())
}

// ---------------------------------------------------------------------------
// Wire DTOs
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema, PartialEq)]
pub struct CreatorSummaryCoverage {
    pub rated_issues_total: i64,
    pub rated_issues_with_creator_metadata: i64,
    pub ratings_complete: bool,
    pub read_unrated_issues_total: i64,
    pub read_unrated_issues_with_creator_metadata: i64,
    pub read_unrated_complete: bool,
    pub unread_issues_total: i64,
    pub unread_issues_with_creator_metadata: i64,
    pub upcoming_complete: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema, PartialEq)]
pub struct CreatorSummaryItem {
    pub canonical_creator_key: String,
    pub display_name: String,
    pub normalized_roles: Vec<String>,
    pub average_rating: Option<f64>,
    pub ratings_count: i64,
    pub read_unrated_count: i64,
    pub upcoming_count: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorSummariesResponse {
    pub summaries: BTreeMap<String, CreatorSummaryItem>,
    pub coverage: CreatorSummaryCoverage,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorListItem {
    pub canonical_creator_key: String,
    pub display_name: String,
    pub normalized_roles: Vec<String>,
    pub average_rating: Option<f64>,
    pub ratings_count: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorListResponse {
    pub items: Vec<CreatorListItem>,
    pub total: i64,
    pub limit: i64,
    pub offset: i64,
    pub coverage: CreatorSummaryCoverage,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorRoleStat {
    pub role: String,
    pub issue_count: i64,
    pub rated_issue_count: i64,
    pub average_rating: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorIssueRow {
    pub issue_id: i64,
    pub issue_number: String,
    pub thread_id: i64,
    pub thread_title: String,
    pub status: String,
    pub roles: Vec<String>,
    pub effective_rating: Option<f64>,
    pub rating_timestamp: Option<String>,
    pub sort_key: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorRatingBucket {
    pub rating: f64,
    pub count: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorRatingDistribution {
    pub buckets: Vec<CreatorRatingBucket>,
    pub sample_count: i64,
    pub mean_rating: f64,
    pub median_rating: f64,
    pub min_rating: f64,
    pub max_rating: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorSeriesGroup {
    pub series_key: String,
    pub thread_id: i64,
    pub thread_title: String,
    pub rated_issue_count: i64,
    pub average_rating: Option<f64>,
    pub lowest_rating: Option<f64>,
    pub highest_rating: Option<f64>,
    pub roles: Vec<String>,
    pub unread_issue_count: i64,
    pub read_unrated_issue_count: i64,
    pub metadata_complete: bool,
    pub sort_key: String,
    pub population_scope: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorSeriesIssueListResponse {
    pub series_key: String,
    pub thread_id: i64,
    pub thread_title: String,
    pub roles: Vec<String>,
    pub rated_issue_count: i64,
    pub average_rating: Option<f64>,
    pub lowest_rating: Option<f64>,
    pub highest_rating: Option<f64>,
    pub metadata_complete: bool,
    pub population_scope: String,
    pub issues: Vec<CreatorIssueRow>,
    pub total: i64,
    pub limit: i64,
    pub offset: i64,
    pub next_cursor: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorIssueInsight {
    pub issue_id: i64,
    pub issue_number: String,
    pub thread_id: i64,
    pub thread_title: String,
    pub effective_rating: f64,
    pub roles: Vec<String>,
    pub sort_key: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorSeriesInsight {
    pub series_key: String,
    pub thread_id: i64,
    pub thread_title: String,
    pub rated_issue_count: i64,
    pub average_rating: f64,
    pub lowest_rating: f64,
    pub highest_rating: f64,
    pub roles: Vec<String>,
    pub metadata_complete: bool,
    pub sort_key: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorInsights {
    pub min_series_sample: i64,
    pub series_sample_met: bool,
    pub series_message: Option<String>,
    pub excluded_incomplete_series_count: i64,
    pub individual_issue_limit: i64,
    pub individual_issues_combined: bool,
    pub strongest_series: Option<CreatorSeriesInsight>,
    pub weakest_series: Option<CreatorSeriesInsight>,
    pub most_rated_series: Option<CreatorSeriesInsight>,
    pub highest_rated_issues: Vec<CreatorIssueInsight>,
    pub lowest_rated_issues: Vec<CreatorIssueInsight>,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorDetailResponse {
    pub summary: CreatorSummaryItem,
    pub coverage: CreatorSummaryCoverage,
    pub role_stats: Vec<CreatorRoleStat>,
    pub series_groups: Vec<CreatorSeriesGroup>,
    pub series_groups_total: i64,
    pub series_groups_complete: bool,
    pub rated_issues: Vec<CreatorIssueRow>,
    pub rated_population_scope: String,
    pub headline_roles: Vec<String>,
    pub read_unrated_issues: Vec<CreatorIssueRow>,
    pub upcoming_issues: Vec<CreatorIssueRow>,
    pub next_cursor: Option<String>,
    pub rating_distribution: Option<CreatorRatingDistribution>,
    pub insights: Option<CreatorInsights>,
}

// Comparison wire DTOs
#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorComparisonRoleStat {
    pub role: String,
    pub issue_count: i64,
    pub rated_issue_count: i64,
    pub average_rating: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorComparisonSeriesAggregate {
    pub thread_id: i64,
    pub thread_title: String,
    pub issue_count: i64,
    pub rated_issue_count: i64,
    pub average_rating: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorComparisonIssueRef {
    pub issue_id: i64,
    pub thread_id: i64,
    pub thread_title: String,
    pub issue_number: String,
    pub status: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorComparisonItem {
    pub canonical_creator_key: String,
    pub display_name: String,
    pub normalized_roles: Vec<String>,
    pub average_rating: Option<f64>,
    pub median_rating: Option<f64>,
    pub ratings_count: i64,
    pub rating_distribution: BTreeMap<String, i64>,
    pub top_rating_rate: Option<f64>,
    pub role_stats: Vec<CreatorComparisonRoleStat>,
    pub strongest_series: Vec<CreatorComparisonSeriesAggregate>,
    pub min_rated_issues_per_series: i64,
    pub unread_upcoming_count: i64,
    pub read_unrated_count: i64,
    pub unread_issue_refs: Vec<CreatorComparisonIssueRef>,
    pub read_unrated_issue_refs: Vec<CreatorComparisonIssueRef>,
    pub max_issue_refs_per_group: i64,
    pub insufficient_data: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorComparisonCoverage {
    pub rated_issues_total: i64,
    pub rated_issues_with_creator_metadata: i64,
    pub ratings_complete: bool,
    pub read_unrated_issues_total: i64,
    pub read_unrated_issues_with_creator_metadata: i64,
    pub read_unrated_complete: bool,
    pub unread_issues_total: i64,
    pub unread_issues_with_creator_metadata: i64,
    pub upcoming_complete: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorComparisonResponse {
    pub comparisons: BTreeMap<String, CreatorComparisonItem>,
    pub coverage: CreatorComparisonCoverage,
    pub insufficient_data_keys: Vec<String>,
}

// Discovery wire DTOs
#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorDiscoveryReason {
    pub metric: String,
    pub label: String,
    pub value: f64,
    pub threshold: f64,
    pub comparison: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorDiscoveryEntry {
    pub canonical_creator_key: String,
    pub display_name: String,
    pub normalized_roles: Vec<String>,
    pub rated_issue_count: i64,
    pub average_rating: Option<f64>,
    pub median_rating: Option<f64>,
    pub rating_stddev: Option<f64>,
    pub rating_spread: Option<f64>,
    pub min_rating: Option<f64>,
    pub max_rating: Option<f64>,
    pub top_rating_rate: Option<f64>,
    pub top_rating_count: i64,
    pub unread_issue_count: i64,
    pub read_unrated_issue_count: i64,
    pub trend_direction: Option<String>,
    pub earlier_average_rating: Option<f64>,
    pub recent_average_rating: Option<f64>,
    pub trend_delta: Option<f64>,
    pub trend_sample_count: i64,
    pub reasons: Vec<CreatorDiscoveryReason>,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorDiscoveryView {
    pub mode: String,
    pub title: String,
    pub description: String,
    pub min_sample: i64,
    pub total: i64,
    pub truncated: bool,
    pub max_entries: i64,
    pub entries: Vec<CreatorDiscoveryEntry>,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorDiscoveryCoverage {
    pub rated_issues_total: i64,
    pub rated_issues_with_creator_metadata: i64,
    pub ratings_complete: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorDiscoveryResponse {
    pub views: Vec<CreatorDiscoveryView>,
    pub coverage: CreatorDiscoveryCoverage,
    pub minimum_reliable_sample: i64,
    pub max_entries_per_view: i64,
}

// Team chemistry wire DTOs
#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorTeamMember {
    pub canonical_creator_key: String,
    pub display_name: String,
    pub roles: Vec<String>,
    pub baseline_rated_count: i64,
    pub baseline_average_rating: Option<f64>,
    pub difference_from_baseline: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorTeamIssueRef {
    pub issue_id: i64,
    pub thread_id: i64,
    pub thread_title: String,
    pub issue_number: String,
    pub effective_rating: Option<f64>,
    pub status: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorTeamSeriesRef {
    pub thread_id: i64,
    pub thread_title: String,
    pub shared_issue_count: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorTeamPair {
    pub pair_key: String,
    pub creators: Vec<CreatorTeamMember>,
    pub shared_rated_issue_count: i64,
    pub shared_average_rating: Option<f64>,
    pub shared_median_rating: Option<f64>,
    pub shared_rating_distribution: BTreeMap<String, i64>,
    pub shared_series: Vec<CreatorTeamSeriesRef>,
    pub shared_issue_refs: Vec<CreatorTeamIssueRef>,
    pub max_shared_issue_refs: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorTeamCoverage {
    pub rated_issues_total: i64,
    pub rated_issues_with_creator_metadata: i64,
    pub ratings_complete: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorTeamChemistryResponse {
    pub pairs: Vec<CreatorTeamPair>,
    pub pairs_total: i64,
    pub min_shared_team_sample: i64,
    pub max_ranked_pairs: i64,
    pub coverage: CreatorTeamCoverage,
}

// Metric drilldown wire DTOs
#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorMetricCalculation {
    pub formula: String,
    pub numerator: String,
    pub denominator: Option<String>,
    pub percentage: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorMetricIssue {
    pub issue_id: i64,
    pub thread_id: i64,
    pub thread_title: String,
    pub issue_number: String,
    pub status: String,
    pub effective_rating: Option<f64>,
    pub effective_rating_source: Option<String>,
    pub effective_rating_timestamp: Option<String>,
    pub creator_roles: Vec<String>,
    pub exclusion_reason: Option<String>,
    pub missing_rating_cause: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorMetricPagination {
    pub page: i64,
    pub page_size: i64,
    pub next_page_token: Option<i64>,
    pub total_pages: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorMetricDrilldown {
    pub metric_type: String,
    pub creator_key: String,
    pub calculation: CreatorMetricCalculation,
    pub total_count: i64,
    pub included_issues: Vec<CreatorMetricIssue>,
    pub excluded_issues: Vec<CreatorMetricIssue>,
    pub pagination: CreatorMetricPagination,
    pub rating_value: Option<String>,
    pub bucket_count: Option<i64>,
    pub bucket_percentage: Option<f64>,
    pub role: Option<String>,
    pub role_issue_count: Option<i64>,
    pub role_rated_issue_count: Option<i64>,
    pub role_average_rating: Option<f64>,
    pub series_id: Option<i64>,
    pub series_title: Option<String>,
    pub series_issue_count: Option<i64>,
    pub series_rated_issue_count: Option<i64>,
    pub series_average_rating: Option<f64>,
}

// ---------------------------------------------------------------------------
// Query param types
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize, IntoParams)]
pub struct CreatorListQuery {
    pub search: Option<String>,
    pub sort: Option<String>,
    pub limit: Option<i64>,
    pub offset: Option<i64>,
    pub min_ratings: Option<i64>,
}

#[derive(Debug, Deserialize, IntoParams)]
pub struct CreatorKeysQuery {
    pub keys: Option<String>,
}

#[derive(Debug, Deserialize, IntoParams)]
pub struct CreatorPageQuery {
    pub limit: Option<i64>,
    pub offset: Option<i64>,
}

#[derive(Debug, Deserialize, IntoParams)]
pub struct CreatorSeriesIssuesQuery {
    pub limit: Option<i64>,
    pub offset: Option<i64>,
}

#[derive(Debug, Deserialize, IntoParams)]
pub struct CreatorMetricQuery {
    pub role: Option<String>,
    pub rating_value: Option<String>,
    pub series_key: Option<String>,
    pub page: Option<i64>,
    pub page_size: Option<i64>,
}

#[derive(Debug, Deserialize, IntoParams)]
pub struct CreatorMetricPageQuery {
    pub page: Option<i64>,
    pub page_size: Option<i64>,
}

// ---------------------------------------------------------------------------
// Shared, user-scoped library snapshot
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
struct OwnedIssue {
    id: i64,
    status: String,
    thread_id: i64,
    thread_title: String,
    issue_number: String,
    queue_position: i64,
    position: i64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct CreatorCredit {
    external_id: i64,
    roles: Vec<String>,
    display_name: String,
}

#[derive(Debug, Clone)]
struct CreatorLibrary {
    issues: Vec<OwnedIssue>,
    issue_index: HashMap<i64, usize>,
    credits: HashMap<i64, Vec<CreatorCredit>>,
    ratings: HashMap<i64, f64>,
    rating_timestamps: HashMap<i64, DateTime<Utc>>,
    metadata_issues: HashSet<i64>,
}

impl CreatorLibrary {
    fn issue(&self, id: i64) -> Option<&OwnedIssue> {
        self.issue_index.get(&id).map(|i| &self.issues[*i])
    }

    fn issue_ids(&self) -> impl Iterator<Item = i64> + '_ {
        self.issues.iter().map(|issue| issue.id)
    }
}

fn manual_creator_id(name: &str) -> i64 {
    use sha2::{Digest, Sha256};
    let digest = Sha256::digest(name.as_bytes());
    let mut acc: i64 = 0;
    for ch in format!("{digest:x}").chars() {
        if let Some(digit) = ch.to_digit(16) {
            acc = (acc * 16 + digit as i64) % MANUAL_CREATOR_ID_BASE;
        }
    }
    MANUAL_CREATOR_ID_BASE + acc
}

fn normalize_manual_role(role: &str) -> Option<String> {
    let normalized = role.split_whitespace().collect::<Vec<_>>().join(" ").to_lowercase();
    if normalized.is_empty() {
        return None;
    }
    Some(match normalized.as_str() {
        "cover artist" => "cover".to_string(),
        "penciller" => "penciler".to_string(),
        _ => normalized,
    })
}

fn coerce_creator_id(value: &Value) -> Option<i64> {
    if let Some(i) = value.as_i64() {
        return Some(i);
    }
    if let Some(u) = value.as_u64() {
        return Some(u as i64);
    }
    value.as_str().filter(|s| !s.is_empty() && s.chars().all(|c| c.is_ascii_digit()))?.parse().ok()
}

fn extract_credits(raw: Option<&str>) -> Vec<CreatorCredit> {
    let Some(text) = raw else {
        return vec![];
    };
    let Ok(Value::Array(items)) = serde_json::from_str::<Value>(text) else {
        return vec![];
    };
    let mut out: Vec<CreatorCredit> = Vec::new();
    let mut seen: HashSet<(i64, Vec<String>)> = HashSet::new();
    for item in items {
        let Some(obj) = item.as_object() else {
            continue;
        };
        let Some(external_id) = obj.get("id").and_then(coerce_creator_id) else {
            continue;
        };
        let Some(name) = obj.get("name").and_then(|v| v.as_str()).map(str::trim).filter(|n| !n.is_empty()) else {
            continue;
        };
        let roles_raw = match obj.get("role") {
            Some(Value::Array(a)) => a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect::<Vec<_>>(),
            Some(Value::String(s)) => s.split(',').map(str::to_string).collect(),
            _ => vec![],
        };
        let mut roles: BTreeSet<String> = BTreeSet::new();
        for part in roles_raw {
            let role = part.trim();
            if !role.is_empty() {
                roles.insert(role.to_string());
            }
        }
        let roles: Vec<String> = roles.into_iter().collect();
        if seen.insert((external_id, roles.clone())) {
            out.push(CreatorCredit {
                external_id,
                roles,
                display_name: name.to_string(),
            });
        }
    }
    out.sort_by(|a, b| a.external_id.cmp(&b.external_id).then(a.roles.cmp(&b.roles)));
    out
}

fn extract_manual_credits(raw: Option<&str>) -> Vec<CreatorCredit> {
    let Some(text) = raw else {
        return vec![];
    };
    let Ok(Value::Array(items)) = serde_json::from_str::<Value>(text) else {
        return vec![];
    };
    let mut out: Vec<CreatorCredit> = Vec::new();
    let mut seen: HashSet<(i64, Vec<String>)> = HashSet::new();
    for item in items {
        let Some(obj) = item.as_object() else {
            continue;
        };
        let Some(name) = obj.get("name").and_then(|v| v.as_str()).map(str::trim).filter(|n| !n.is_empty()) else {
            continue;
        };
        let normalized_name = name.split_whitespace().collect::<Vec<_>>().join(" ");
        let roles_raw: Vec<String> = match obj.get("roles") {
            Some(Value::Array(a)) => a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect(),
            Some(Value::String(s)) => s.split(',').map(str::to_string).collect(),
            _ => vec![],
        };
        let mut roles: BTreeSet<String> = BTreeSet::new();
        for role in roles_raw {
            if let Some(normalized) = normalize_manual_role(&role) {
                roles.insert(normalized);
            }
        }
        let roles: Vec<String> = roles.into_iter().collect();
        let external_id = manual_creator_id(&normalized_name);
        if seen.insert((external_id, roles.clone())) {
            out.push(CreatorCredit {
                external_id,
                roles,
                display_name: normalized_name,
            });
        }
    }
    out.sort_by(|a, b| a.external_id.cmp(&b.external_id).then(a.roles.cmp(&b.roles)));
    out
}

async fn load_library(state: &AppState, user_id: i32) -> Result<CreatorLibrary, ApiError> {
    let connection = checkout(state).await?;
    let mut issues: Vec<OwnedIssue> = connection
        .query(
            "SELECT i.id, i.status, i.thread_id, i.issue_number, t.title,
                    t.queue_position, i.position
             FROM issues i JOIN threads t ON t.id = i.thread_id
             WHERE t.user_id = $1",
            &[&user_id],
        )
        .await
        .map_err(query_error)?
        .iter()
        .map(|row| OwnedIssue {
            id: row.get(0),
            status: row.get(1),
            thread_id: row.get(2),
            issue_number: row.get(3),
            thread_title: row.get(4),
            queue_position: row.try_get(5).unwrap_or(0),
            position: row.try_get(6).unwrap_or(0),
        })
        .collect();
    issues.sort_by_key(|issue| issue.id);
    let issue_index: HashMap<i64, usize> = issues
        .iter()
        .enumerate()
        .map(|(index, issue)| (issue.id, index))
        .collect();

    let mut thread_manual: HashMap<i64, String> = HashMap::new();
    for row in connection
        .query(
            "SELECT id, manual_creator_credits::text FROM threads WHERE user_id = $1",
            &[&user_id],
        )
        .await
        .map_err(query_error)?
    {
        if let Some(text) = row.try_get::<_, Option<String>>(1).map_err(query_error)? {
            thread_manual.insert(row.get(0), text);
        }
    }

    let mut credits: HashMap<i64, Vec<CreatorCredit>> = HashMap::new();
    let mut metadata_issues: HashSet<i64> = HashSet::new();
    for row in connection
        .query(
            "SELECT i.id, e.metadata_json->>'creator_credits'
             FROM issues i
             JOIN threads t ON t.id = i.thread_id
             JOIN issue_external_identity_mappings m ON m.issue_id = i.id
             JOIN external_identities e ON e.id = m.external_identity_id
             WHERE t.user_id = $1 AND m.status = 'confirmed' AND e.provider = 'comicvine'",
            &[&user_id],
        )
        .await
        .map_err(query_error)?
    {
        let issue_id: i64 = row.get(0);
        let found = extract_credits(row.try_get::<_, Option<String>>(1).map_err(query_error)?.as_deref());
        if !found.is_empty() {
            metadata_issues.insert(issue_id);
            credits.entry(issue_id).or_default().extend(found);
        }
    }
    for issue in &issues {
        if credits.contains_key(&issue.id) {
            continue;
        }
        if let Some(manual) = thread_manual.get(&issue.thread_id) {
            let found = extract_manual_credits(Some(manual));
            if !found.is_empty() {
                metadata_issues.insert(issue.id);
                credits.insert(issue.id, found);
            }
        }
    }
    for values in credits.values_mut() {
        values.sort_by(|a, b| a.external_id.cmp(&b.external_id).then(a.roles.cmp(&b.roles)));
        values.dedup_by(|a, b| a.external_id == b.external_id && a.roles == b.roles);
    }

    let mut ratings: HashMap<i64, f64> = HashMap::new();
    let mut rating_timestamps: HashMap<i64, DateTime<Utc>> = HashMap::new();
    for row in connection
        .query(
            "SELECT DISTINCT ON (ev.issue_id) ev.issue_id, ev.rating, ev.timestamp
             FROM events ev
             JOIN issues i ON i.id = ev.issue_id
             JOIN threads t ON t.id = i.thread_id
             WHERE t.user_id = $1 AND ev.type = 'rate' AND ev.issue_id IS NOT NULL
                   AND ev.rating IS NOT NULL
             ORDER BY ev.issue_id, ev.timestamp DESC, ev.id DESC",
            &[&user_id],
        )
        .await
        .map_err(query_error)?
    {
        let issue_id: i64 = row.get(0);
        let rating: f64 = row.try_get::<_, f64>(1).or_else(|_| row.try_get::<_, f32>(1).map(f64::from)).map_err(query_error)?;
        ratings.insert(issue_id, rating);
        if let Ok(timestamp) = row.try_get::<_, DateTime<Utc>>(2) {
            rating_timestamps.insert(issue_id, timestamp);
        }
    }

    Ok(CreatorLibrary {
        issues,
        issue_index,
        credits,
        ratings,
        rating_timestamps,
        metadata_issues,
    })
}

async fn resolve_user_id(state: &AppState, claims: &VerifiedAccessClaims) -> Result<i32, ApiError> {
    let username = claims.username().to_string();
    let jti = claims.jti().to_string();
    let expected_epoch = claims.expected_epoch().unwrap_or(i64::MAX);
    let connection = checkout(state).await?;
    let row = crate::db::query_one_optional(
        state,
        connection,
        "WITH auth AS (
            SELECT u.id AS user_id,
                   COALESCE(trunc(extract(epoch FROM u.password_changed_at))::bigint, 0) AS password_epoch,
                   EXISTS(SELECT 1 FROM revoked_tokens r WHERE r.jti = $2) AS revoked
            FROM users u WHERE u.username = $1 LIMIT 1
         )
         SELECT user_id, password_epoch, revoked FROM auth",
        &[&username, &jti],
    )
    .await?;
    let row = row.ok_or_else(|| ApiError::Unauthorized("User not found".to_string()))?;
    let user_id: i32 = row.get(0);
    let epoch: i64 = row.get(1);
    let revoked: bool = row.get(2);
    if revoked {
        return Err(ApiError::Unauthorized("Token has been revoked".to_string()));
    }
    if expected_epoch < epoch {
        return Err(ApiError::Unauthorized(
            "Password changed; please sign in again.".to_string(),
        ));
    }
    Ok(user_id)
}

// ---------------------------------------------------------------------------
// Validation and numeric helpers
// ---------------------------------------------------------------------------

fn parse_creator_key(key: &str) -> Option<i64> {
    let parts: Vec<&str> = key.split(':').collect();
    if parts.len() != 2 || parts[0] != "creator" || parts[1].is_empty() || !parts[1].chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    parts[1].parse().ok()
}

fn parse_series_key(key: &str) -> Option<i64> {
    let (prefix, separator, suffix) = match key.find(':') {
        Some(index) => (&key[..index], ":", &key[index + 1..]),
        None => (key, "", ""),
    };
    if separator.is_empty() || prefix != "thread" || suffix.is_empty() || !suffix.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    suffix.parse().ok()
}

fn split_keys(raw: &str) -> Vec<String> {
    let mut seen = HashSet::new();
    let mut out = Vec::new();
    for part in raw.split(',') {
        let key = part.trim();
        if !key.is_empty() && seen.insert(key.to_string()) {
            out.push(key.to_string());
        }
    }
    out
}

fn validate_summary_keys(raw: Option<&str>) -> Result<Vec<String>, ApiError> {
    let raw = raw.map(str::trim).filter(|value| !value.is_empty()).ok_or_else(|| {
        bad_request("keys must be a non-empty comma-separated list of creator keys")
    })?;
    let keys = split_keys(raw);
    if keys.is_empty() {
        return Err(bad_request("keys must be a non-empty comma-separated list of creator keys"));
    }
    if keys.len() > MAX_CREATOR_KEYS {
        return Err(bad_request(format!(
            "keys may list at most {MAX_CREATOR_KEYS} creators per request"
        )));
    }
    for key in &keys {
        if parse_creator_key(key).is_none() {
            return Err(bad_request(format!(
                "Invalid creator key {key:?}: expected creator:<external-person-id> (stable ComicVine person id, no display names)"
            )));
        }
    }
    Ok(keys)
}

fn validate_comparison_keys(raw: Option<&str>) -> Result<Vec<String>, ApiError> {
    let message = "keys must be a comma-separated list of 2-4 canonical creator keys";
    let raw = raw.map(str::trim).filter(|value| !value.is_empty()).ok_or_else(|| bad_request(message))?;
    let keys = split_keys(raw);
    if keys.is_empty() {
        return Err(bad_request(message));
    }
    if keys.len() < MIN_COMPARISON_CREATORS || keys.len() > MAX_COMPARISON_CREATORS {
        return Err(bad_request(format!(
            "keys must contain 2 to 4 creator keys, got {}",
            keys.len()
        )));
    }
    for key in &keys {
        if parse_creator_key(key).is_none() {
            return Err(bad_request(format!(
                "Invalid creator key {key:?}: expected creator:<external-person-id> (stable ComicVine person id, no display names)"
            )));
        }
    }
    Ok(keys)
}

/// Python `round(value, places)` (round half to even) on binary floats.
fn round_half_even(value: f64, places: i32) -> f64 {
    let factor = 10_f64.powi(places);
    let scaled = value * factor;
    let floor = scaled.floor();
    let fraction = scaled - floor;
    if (fraction - 0.5).abs() < 1e-9 {
        let base = floor as i64;
        if base % 2 == 0 {
            floor / factor
        } else {
            (floor + 1.0) / factor
        }
    } else {
        scaled.round() / factor
    }
}

fn round2(value: f64) -> f64 {
    round_half_even(value, 2)
}

fn round3(value: f64) -> f64 {
    round_half_even(value, 3)
}

fn mean(values: &[f64]) -> f64 {
    values.iter().sum::<f64>() / values.len() as f64
}

fn median(values: &[f64]) -> f64 {
    let mut sorted = values.to_vec();
    sorted.sort_by(|a, b| a.total_cmp(b));
    let middle = sorted.len() / 2;
    if sorted.len() % 2 == 1 {
        sorted[middle]
    } else {
        (sorted[middle - 1] + sorted[middle]) / 2.0
    }
}

fn pstdev(values: &[f64]) -> f64 {
    if values.len() <= 1 {
        return 0.0;
    }
    let average = mean(values);
    (values.iter().map(|value| (value - average).powi(2)).sum::<f64>() / values.len() as f64).sqrt()
}

fn iso_timestamp(value: &DateTime<Utc>) -> String {
    value.to_rfc3339()
}

#[derive(Debug, Clone, PartialEq)]
struct Attribution {
    issue_ids: BTreeSet<i64>,
    roles: BTreeSet<String>,
    display_name: String,
}

fn attribution(library: &CreatorLibrary, creator_id: i64) -> Option<Attribution> {
    let mut result = Attribution {
        issue_ids: BTreeSet::new(),
        roles: BTreeSet::new(),
        display_name: String::new(),
    };
    let mut found_name = false;
    for issue in &library.issues {
        let Some(credits) = library.credits.get(&issue.id) else {
            continue;
        };
        for credit in credits {
            if credit.external_id == creator_id {
                result.issue_ids.insert(issue.id);
                result.roles.extend(credit.roles.iter().cloned());
                if !found_name {
                    result.display_name = credit.display_name.clone();
                    found_name = true;
                }
            }
        }
    }
    if result.issue_ids.is_empty() || !found_name {
        None
    } else {
        Some(result)
    }
}

fn has_headline_role(credit: &CreatorCredit) -> bool {
    credit.roles.iter().any(|role| HEADLINE_ROLES.contains(&role.as_str()))
}

fn roles_on_issue(library: &CreatorLibrary, creator_id: i64, issue_id: i64) -> Vec<String> {
    library
        .credits
        .get(&issue_id)
        .into_iter()
        .flatten()
        .filter(|credit| credit.external_id == creator_id)
        .flat_map(|credit| credit.roles.iter().cloned())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

fn coverage(library: &CreatorLibrary) -> CreatorSummaryCoverage {
    let rated: HashSet<i64> = library.ratings.keys().copied().collect();
    let mut read_unrated = HashSet::new();
    let mut unread = HashSet::new();
    for issue in &library.issues {
        if issue.status == "read" && !library.ratings.contains_key(&issue.id) {
            read_unrated.insert(issue.id);
        } else if issue.status == "unread" {
            unread.insert(issue.id);
        }
    }
    let with_metadata = |ids: &HashSet<i64>| {
        ids.iter().filter(|id| library.metadata_issues.contains(id)).count() as i64
    };
    let rated_total = rated.len() as i64;
    let rated_with = with_metadata(&rated);
    let read_total = read_unrated.len() as i64;
    let read_with = with_metadata(&read_unrated);
    let unread_total = unread.len() as i64;
    let unread_with = with_metadata(&unread);
    CreatorSummaryCoverage {
        rated_issues_total: rated_total,
        rated_issues_with_creator_metadata: rated_with,
        ratings_complete: rated_with >= rated_total,
        read_unrated_issues_total: read_total,
        read_unrated_issues_with_creator_metadata: read_with,
        read_unrated_complete: read_with >= read_total,
        unread_issues_total: unread_total,
        unread_issues_with_creator_metadata: unread_with,
        upcoming_complete: unread_with >= unread_total,
    }
}

fn rating_distribution(ratings: &[f64]) -> Option<CreatorRatingDistribution> {
    if ratings.is_empty() {
        return None;
    }
    let mut counts: BTreeMap<String, i64> = BTreeMap::new();
    for rating in RATING_BUCKETS {
        counts.insert(format!("{rating:?}"), 0);
    }
    for rating in ratings {
        let bucket = (rating * 2.0).round() / 2.0;
        let bucket = bucket.clamp(0.5, 5.0);
        *counts.entry(format!("{bucket:?}")).or_default() += 1;
    }
    Some(CreatorRatingDistribution {
        buckets: RATING_BUCKETS
            .iter()
            .map(|rating| CreatorRatingBucket {
                rating: *rating,
                count: *counts.get(&format!("{rating:?}")).unwrap_or(&0),
            })
            .collect(),
        sample_count: ratings.len() as i64,
        mean_rating: round2(mean(ratings)),
        median_rating: round2(median(ratings)),
        min_rating: ratings.iter().copied().fold(f64::INFINITY, f64::min),
        max_rating: ratings.iter().copied().fold(f64::NEG_INFINITY, f64::max),
    })
}
