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
    extract::{rejection::QueryRejection, Path, Query, State},
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
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rating_value: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub bucket_count: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub bucket_percentage: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub role: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub role_issue_count: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub role_rated_issue_count: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub role_average_rating: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub series_id: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub series_title: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub series_issue_count: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub series_rated_issue_count: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub series_average_rating: Option<f64>,
}

// ---------------------------------------------------------------------------
// Query param types
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize, IntoParams)]
#[into_params(parameter_in = Query)]
pub struct CreatorListQuery {
    pub search: Option<String>,
    pub sort: Option<String>,
    pub limit: Option<i64>,
    pub offset: Option<i64>,
    pub min_ratings: Option<i64>,
}

#[derive(Debug, Deserialize, IntoParams)]
#[into_params(parameter_in = Query)]
pub struct CreatorKeysQuery {
    pub keys: Option<String>,
}

#[derive(Debug, Deserialize, IntoParams)]
#[into_params(parameter_in = Query)]
pub struct CreatorPageQuery {
    pub limit: Option<i64>,
    pub offset: Option<i64>,
}

#[derive(Debug, Deserialize, IntoParams)]
#[into_params(parameter_in = Query)]
pub struct CreatorSeriesIssuesQuery {
    pub limit: Option<i64>,
    pub offset: Option<i64>,
}

#[derive(Debug, Deserialize, IntoParams)]
#[into_params(parameter_in = Query)]
pub struct CreatorMetricQuery {
    pub role: Option<String>,
    pub rating_value: Option<String>,
    pub series_key: Option<String>,
    pub page: Option<i64>,
    pub page_size: Option<i64>,
}

#[derive(Debug, Deserialize, IntoParams)]
#[into_params(parameter_in = Query)]
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
    /// Read-without-rating audit cause keys for issues that are read and have
    /// no effective rating, matching Python's `classify_issue_ids` contract.
    missing_rating_causes: HashMap<i64, String>,
    /// Set-based library-wide coverage totals for scoped loads.
    coverage_override: Option<CreatorSummaryCoverage>,
}

impl CreatorLibrary {
    fn issue(&self, id: i64) -> Option<&OwnedIssue> {
        self.issue_index.get(&id).map(|i| &self.issues[*i])
    }
}

fn manual_creator_id(name: &str) -> i64 {
    use sha2::{Digest, Sha256};
    let digest = Sha256::digest(name.as_bytes());
    // GenericArray does not implement LowerHex; render each byte explicitly so
    // the 64 hex chars match Python's int(hexdigest, 16) modulo arithmetic.
    let hex: String = digest.iter().map(|b| format!("{b:02x}")).collect();
    let mut acc: i64 = 0;
    for ch in hex.chars() {
        if let Some(digit) = ch.to_digit(16) {
            acc = (acc * 16 + digit as i64) % MANUAL_CREATOR_ID_BASE;
        }
    }
    MANUAL_CREATOR_ID_BASE + acc
}

fn normalize_manual_role(role: &str) -> Option<String> {
    let normalized = role
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase();
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
    value
        .as_str()
        .filter(|s| !s.is_empty() && s.chars().all(|c| c.is_ascii_digit()))?
        .parse()
        .ok()
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
        let Some(name) = obj
            .get("name")
            .and_then(|v| v.as_str())
            .map(str::trim)
            .filter(|n| !n.is_empty())
        else {
            continue;
        };
        let roles_raw = match obj.get("role") {
            Some(Value::Array(a)) => a
                .iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect::<Vec<_>>(),
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
    out.sort_by(|a, b| {
        a.external_id
            .cmp(&b.external_id)
            .then(a.roles.cmp(&b.roles))
    });
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
        let Some(name) = obj
            .get("name")
            .and_then(|v| v.as_str())
            .map(str::trim)
            .filter(|n| !n.is_empty())
        else {
            continue;
        };
        let normalized_name = name.split_whitespace().collect::<Vec<_>>().join(" ");
        let roles_raw: Vec<String> = match obj.get("roles") {
            Some(Value::Array(a)) => a
                .iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect(),
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
    out.sort_by(|a, b| {
        a.external_id
            .cmp(&b.external_id)
            .then(a.roles.cmp(&b.roles))
    });
    out
}

/// Which part of a reader's library a request needs.
#[derive(Debug, Clone)]
enum LibraryScope {
    /// Every owned issue (list, discoveries, team chemistry aggregate all creators).
    Full,
    /// Only series that can carry credits for the requested creator ids.
    Creators(Vec<i64>),
}

/// SQL predicate (over a jsonb element `c`) mirroring `extract_credits`
/// validity: an object with a string name that is non-blank after trimming and
/// an id that coerces to an integer (JSON integer or all-digit string).
const CV_CREDIT_VALID: &str = r#"jsonb_typeof(c) = 'object'
    AND jsonb_typeof(c->'name') = 'string'
    AND btrim(c->>'name', E' \t\r\n') <> ''
    AND ((jsonb_typeof(c->'id') = 'number' AND c->>'id' ~ '^-?[0-9]{1,18}$')
         OR (jsonb_typeof(c->'id') = 'string' AND c->>'id' ~ '^[0-9]{1,18}$'))"#;

/// SQL predicate mirroring `extract_manual_credits` validity (object with a
/// non-blank string name).
const MANUAL_CREDIT_VALID: &str = r#"jsonb_typeof(c) = 'object'
    AND jsonb_typeof(c->'name') = 'string'
    AND btrim(c->>'name', E' \t\r\n') <> ''"#;

/// Library-wide coverage computed as set-based totals in PostgreSQL so scoped
/// requests never materialize every issue, credit and rating.
async fn load_coverage(
    connection: &deadpool_postgres::Object,
    user_id: i32,
) -> Result<CreatorSummaryCoverage, ApiError> {
    let sql = format!(
        "WITH owned AS (
             SELECT i.id, i.status, t.manual_creator_credits::jsonb AS manual
             FROM issues i JOIN threads t ON t.id = i.thread_id
             WHERE t.user_id = $1),
         rated AS (
             SELECT DISTINCT ev.issue_id
             FROM events ev JOIN owned o ON o.id = ev.issue_id
             WHERE ev.type = 'rate' AND ev.rating IS NOT NULL),
         cv AS (
             SELECT DISTINCT m.issue_id
             FROM issue_external_identity_mappings m
             JOIN owned o ON o.id = m.issue_id
             JOIN external_identities e ON e.id = m.external_identity_id,
             LATERAL jsonb_array_elements(
                 CASE WHEN jsonb_typeof(e.metadata_json::jsonb->'creator_credits') = 'array'
                      THEN e.metadata_json::jsonb->'creator_credits' ELSE '[]'::jsonb END) c
             WHERE m.status = 'confirmed' AND e.provider = 'comicvine' AND {CV_CREDIT_VALID}),
         classified AS (
             SELECT o.status,
                    (r.issue_id IS NOT NULL) AS rated,
                    (cv.issue_id IS NOT NULL OR EXISTS (
                        SELECT 1 FROM jsonb_array_elements(
                            CASE WHEN jsonb_typeof(o.manual) = 'array'
                                 THEN o.manual ELSE '[]'::jsonb END) c
                        WHERE {MANUAL_CREDIT_VALID})) AS has_meta
             FROM owned o
             LEFT JOIN rated r ON r.issue_id = o.id
             LEFT JOIN cv ON cv.issue_id = o.id)
         SELECT count(*) FILTER (WHERE rated),
                count(*) FILTER (WHERE rated AND has_meta),
                count(*) FILTER (WHERE status = 'read' AND NOT rated),
                count(*) FILTER (WHERE status = 'read' AND NOT rated AND has_meta),
                count(*) FILTER (WHERE status = 'unread'),
                count(*) FILTER (WHERE status = 'unread' AND has_meta)
         FROM classified"
    );
    let row = connection
        .query_one(sql.as_str(), &[&user_id])
        .await
        .map_err(query_error)?;
    let (rated_total, rated_with, read_total, read_with, unread_total, unread_with): (
        i64,
        i64,
        i64,
        i64,
        i64,
        i64,
    ) = (
        row.get(0),
        row.get(1),
        row.get(2),
        row.get(3),
        row.get(4),
        row.get(5),
    );
    Ok(CreatorSummaryCoverage {
        rated_issues_total: rated_total,
        rated_issues_with_creator_metadata: rated_with,
        ratings_complete: rated_with >= rated_total,
        read_unrated_issues_total: read_total,
        read_unrated_issues_with_creator_metadata: read_with,
        read_unrated_complete: read_with >= read_total,
        unread_issues_total: unread_total,
        unread_issues_with_creator_metadata: unread_with,
        upcoming_complete: unread_with >= unread_total,
    })
}

/// Thread ids that may carry credits for `creator_ids`: threads with a
/// confirmed ComicVine credit for one of them (filtered in SQL) plus threads
/// whose manual credits resolve to one of them.
async fn candidate_threads(
    connection: &deadpool_postgres::Object,
    user_id: i32,
    creator_ids: &[i64],
) -> Result<Vec<i64>, ApiError> {
    let wanted: Vec<String> = creator_ids.iter().map(|id| id.to_string()).collect();
    let sql = format!(
        "SELECT DISTINCT i.thread_id::bigint
         FROM issues i
         JOIN threads t ON t.id = i.thread_id
         JOIN issue_external_identity_mappings m ON m.issue_id = i.id
         JOIN external_identities e ON e.id = m.external_identity_id,
         LATERAL jsonb_array_elements(
             CASE WHEN jsonb_typeof(e.metadata_json::jsonb->'creator_credits') = 'array'
                  THEN e.metadata_json::jsonb->'creator_credits' ELSE '[]'::jsonb END) c
         WHERE t.user_id = $1 AND m.status = 'confirmed' AND e.provider = 'comicvine'
               AND {CV_CREDIT_VALID}
               AND COALESCE(NULLIF(ltrim(c->>'id', '0'), ''), '0') = ANY($2::text[])"
    );
    let mut threads: BTreeSet<i64> = connection
        .query(sql.as_str(), &[&user_id, &wanted])
        .await
        .map_err(query_error)?
        .iter()
        .map(|row| row.get::<_, i64>(0))
        .collect();
    let wanted_set: HashSet<i64> = creator_ids.iter().copied().collect();
    for row in connection
        .query(
            "SELECT id::bigint, manual_creator_credits::text FROM threads
             WHERE user_id = $1 AND jsonb_typeof(manual_creator_credits::jsonb) = 'array'
                   AND jsonb_array_length(manual_creator_credits::jsonb) > 0",
            &[&user_id],
        )
        .await
        .map_err(query_error)?
    {
        let text: Option<String> = row.try_get(1).map_err(query_error)?;
        if extract_manual_credits(text.as_deref())
            .iter()
            .any(|credit| wanted_set.contains(&credit.external_id))
        {
            threads.insert(row.get(0));
        }
    }
    Ok(threads.into_iter().collect())
}

async fn load_library(
    state: &AppState,
    user_id: i32,
    scope: LibraryScope,
    audit_missing_ratings: bool,
) -> Result<CreatorLibrary, ApiError> {
    let connection = checkout(state).await?;
    let (thread_filter, coverage_override): (Option<Vec<i64>>, Option<CreatorSummaryCoverage>) =
        match &scope {
            LibraryScope::Full => (None, None),
            LibraryScope::Creators(ids) => {
                let coverage = load_coverage(&connection, user_id).await?;
                (
                    Some(candidate_threads(&connection, user_id, ids).await?),
                    Some(coverage),
                )
            }
        };
    if thread_filter.as_ref().is_some_and(Vec::is_empty) {
        return Ok(CreatorLibrary {
            issues: Vec::new(),
            issue_index: HashMap::new(),
            credits: HashMap::new(),
            ratings: HashMap::new(),
            rating_timestamps: HashMap::new(),
            metadata_issues: HashSet::new(),
            missing_rating_causes: HashMap::new(),
            coverage_override,
        });
    }
    let mut issues: Vec<OwnedIssue> = connection
        .query(
            "SELECT i.id::bigint, i.status, i.thread_id::bigint, i.issue_number, t.title,
                    t.queue_position::bigint, i.position::bigint
             FROM issues i JOIN threads t ON t.id = i.thread_id
             WHERE t.user_id = $1
                   AND ($2::bigint[] IS NULL OR i.thread_id = ANY($2::bigint[]))",
            &[&user_id, &thread_filter],
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
            queue_position: row.get(5),
            position: row.get(6),
        })
        .collect();
    issues.sort_by_key(|issue| issue.id);
    let issue_index: HashMap<i64, usize> = issues
        .iter()
        .enumerate()
        .map(|(index, issue)| (issue.id, index))
        .collect();
    let issue_filter: Option<Vec<i64>> = thread_filter
        .as_ref()
        .map(|_| issues.iter().map(|issue| issue.id).collect());

    let mut thread_manual: HashMap<i64, String> = HashMap::new();
    for row in connection
        .query(
            "SELECT id::bigint, manual_creator_credits::text FROM threads
             WHERE user_id = $1 AND ($2::bigint[] IS NULL OR id = ANY($2::bigint[]))",
            &[&user_id, &thread_filter],
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
            "SELECT i.id::bigint, e.metadata_json->>'creator_credits'
             FROM issues i
             JOIN threads t ON t.id = i.thread_id
             JOIN issue_external_identity_mappings m ON m.issue_id = i.id
             JOIN external_identities e ON e.id = m.external_identity_id
             WHERE t.user_id = $1 AND m.status = 'confirmed' AND e.provider = 'comicvine'
                   AND ($2::bigint[] IS NULL OR i.id = ANY($2::bigint[]))",
            &[&user_id, &issue_filter],
        )
        .await
        .map_err(query_error)?
    {
        let issue_id: i64 = row.get(0);
        let found = extract_credits(
            row.try_get::<_, Option<String>>(1)
                .map_err(query_error)?
                .as_deref(),
        );
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
        values.sort_by(|a, b| {
            a.external_id
                .cmp(&b.external_id)
                .then(a.roles.cmp(&b.roles))
        });
        values.dedup_by(|a, b| a.external_id == b.external_id && a.roles == b.roles);
    }

    let mut ratings: HashMap<i64, f64> = HashMap::new();
    let mut rating_timestamps: HashMap<i64, DateTime<Utc>> = HashMap::new();
    for row in connection
        .query(
            "SELECT DISTINCT ON (ev.issue_id) ev.issue_id::bigint, ev.rating, ev.timestamp
             FROM events ev
             JOIN issues i ON i.id = ev.issue_id
             JOIN threads t ON t.id = i.thread_id
             WHERE t.user_id = $1 AND ev.type = 'rate' AND ev.issue_id IS NOT NULL
                   AND ev.rating IS NOT NULL
                   AND ($2::bigint[] IS NULL OR ev.issue_id = ANY($2::bigint[]))
             ORDER BY ev.issue_id, ev.timestamp DESC, ev.id DESC",
            &[&user_id, &issue_filter],
        )
        .await
        .map_err(query_error)?
    {
        let issue_id: i64 = row.get(0);
        let rating: f64 = row
            .try_get::<_, f64>(1)
            .or_else(|_| row.try_get::<_, f32>(1).map(f64::from))
            .map_err(query_error)?;
        ratings.insert(issue_id, rating);
        if let Ok(timestamp) = row.try_get::<_, DateTime<Utc>>(2) {
            rating_timestamps.insert(issue_id, timestamp);
        }
    }

    // Read-without-rating audit causes (issue #3175), matching Python's
    // `classify_issue_ids` contract so metric drilldowns can expose
    // `missing_rating_cause` for read issues without an effective rating.
    let mut missing_rating_causes: HashMap<i64, String> = HashMap::new();
    let read_without_rating: Vec<i64> = issues
        .iter()
        .filter(|issue| issue.status == "read" && !ratings.contains_key(&issue.id))
        .map(|issue| issue.id)
        .collect();
    if audit_missing_ratings && !read_without_rating.is_empty() {
        // Thread-level historical ratings for threads that own the population.
        let thread_ids: Vec<i64> = {
            let mut set: HashSet<i64> = HashSet::new();
            for issue_id in &read_without_rating {
                if let Some(issue) = issue_index.get(issue_id).map(|i| &issues[*i]) {
                    set.insert(issue.thread_id);
                }
            }
            let mut v: Vec<i64> = set.into_iter().collect();
            v.sort_unstable();
            v
        };

        #[derive(Clone)]
        struct ThreadHistoricalRating {
            _event_id: i64,
            rating: f64,
            _recorded_at: Option<DateTime<Utc>>,
        }
        let mut thread_historical: HashMap<i64, Vec<ThreadHistoricalRating>> = HashMap::new();
        if !thread_ids.is_empty() {
            for row in connection
                .query(
                    "SELECT ev.id::bigint, ev.thread_id::bigint, ev.rating, ev.timestamp
                     FROM events ev
                     JOIN threads t ON t.id = ev.thread_id
                     WHERE t.user_id = $1 AND ev.type = 'rate'
                           AND ev.rating IS NOT NULL AND ev.issue_id IS NULL
                           AND ev.thread_id = ANY($2::bigint[])
                     ORDER BY ev.thread_id, ev.timestamp ASC, ev.id ASC",
                    &[&user_id, &thread_ids],
                )
                .await
                .map_err(query_error)?
            {
                let event_id: i64 = row.get(0);
                let thread_id: i64 = row.get(1);
                let rating: f64 = row
                    .try_get::<_, f64>(2)
                    .or_else(|_| row.try_get::<_, f32>(2).map(f64::from))
                    .map_err(query_error)?;
                let recorded_at = row.try_get::<_, DateTime<Utc>>(3).ok();
                thread_historical
                    .entry(thread_id)
                    .or_default()
                    .push(ThreadHistoricalRating {
                        _event_id: event_id,
                        rating,
                        _recorded_at: recorded_at,
                    });
            }
        }

        // Distinct mapping statuses per requested issue.
        let mut mapping_statuses: HashMap<i64, Vec<String>> = HashMap::new();
        for row in connection
            .query(
                "SELECT DISTINCT issue_id::bigint, status
                 FROM issue_external_identity_mappings
                 WHERE issue_id = ANY($1::bigint[])",
                &[&read_without_rating],
            )
            .await
            .map_err(query_error)?
        {
            let issue_id: i64 = row.get(0);
            let status: String = row.get(1);
            mapping_statuses.entry(issue_id).or_default().push(status);
        }
        for statuses in mapping_statuses.values_mut() {
            statuses.sort();
            statuses.dedup();
        }

        // Edition/duplicate conflicts: requested read-without-rating issues that
        // share a confirmed external identity with another owned read issue.
        let mut duplicate_issue_ids: HashMap<i64, Vec<i64>> = HashMap::new();
        let mut requested_identities: HashMap<i64, HashSet<i64>> = HashMap::new();
        for row in connection
            .query(
                "SELECT issue_id::bigint, external_identity_id::bigint
                 FROM issue_external_identity_mappings
                 WHERE issue_id = ANY($1::bigint[]) AND status = 'confirmed'",
                &[&read_without_rating],
            )
            .await
            .map_err(query_error)?
        {
            let issue_id: i64 = row.get(0);
            let external_identity_id: i64 = row.get(1);
            requested_identities
                .entry(issue_id)
                .or_default()
                .insert(external_identity_id);
        }
        let shared_identities: Vec<i64> = {
            let mut set: HashSet<i64> = HashSet::new();
            for ids in requested_identities.values() {
                set.extend(ids.iter().copied());
            }
            let mut v: Vec<i64> = set.into_iter().collect();
            v.sort_unstable();
            v
        };
        if !shared_identities.is_empty() {
            let mut by_identity: HashMap<i64, HashSet<i64>> = HashMap::new();
            for row in connection
                .query(
                    "SELECT m.issue_id::bigint, m.external_identity_id::bigint
                     FROM issue_external_identity_mappings m
                     JOIN issues i ON i.id = m.issue_id
                     JOIN threads t ON t.id = i.thread_id
                     WHERE t.user_id = $1 AND i.status = 'read'
                           AND m.status = 'confirmed'
                           AND m.external_identity_id = ANY($2::bigint[])",
                    &[&user_id, &shared_identities],
                )
                .await
                .map_err(query_error)?
            {
                let issue_id: i64 = row.get(0);
                let external_identity_id: i64 = row.get(1);
                by_identity
                    .entry(external_identity_id)
                    .or_default()
                    .insert(issue_id);
            }
            for (issue_id, identities) in &requested_identities {
                let mut others: HashSet<i64> = HashSet::new();
                for identity_id in identities {
                    if let Some(members) = by_identity.get(identity_id) {
                        others.extend(members.iter().copied());
                    }
                }
                others.remove(issue_id);
                if !others.is_empty() {
                    let mut v: Vec<i64> = others.into_iter().collect();
                    v.sort_unstable();
                    duplicate_issue_ids.insert(*issue_id, v);
                }
            }
        }

        // Unrated read issue counts per thread over the full library.
        let mut thread_unrated_counts: HashMap<i64, i64> = HashMap::new();
        for issue in &issues {
            if issue.status == "read" && !ratings.contains_key(&issue.id) {
                *thread_unrated_counts.entry(issue.thread_id).or_default() += 1;
            }
        }

        fn agreed_historical_rating(entries: &[ThreadHistoricalRating]) -> Option<f64> {
            let mut values: Vec<f64> = entries.iter().map(|e| e.rating).collect();
            values.sort_by(|a, b| a.total_cmp(b));
            values.dedup_by(|a, b| a.total_cmp(b) == std::cmp::Ordering::Equal);
            if values.len() == 1 {
                values.first().copied()
            } else {
                None
            }
        }

        for issue_id in &read_without_rating {
            let Some(issue) = issue_index.get(issue_id).map(|i| &issues[*i]) else {
                continue;
            };
            let thread_id = issue.thread_id;
            let historical = thread_historical.get(&thread_id);
            let duplicates = duplicate_issue_ids.get(issue_id);
            let statuses = mapping_statuses.get(issue_id);
            let unrated_read_in_thread =
                thread_unrated_counts.get(&thread_id).copied().unwrap_or(1);

            let cause = if duplicates.is_some_and(|v| !v.is_empty()) {
                "edition_conflict".to_string()
            } else if let Some(entries) = historical.filter(|e| !e.is_empty()) {
                if agreed_historical_rating(entries).is_none() || unrated_read_in_thread != 1 {
                    "ambiguous_thread_rating".to_string()
                } else {
                    "missing_rate_event".to_string()
                }
            } else if !statuses.is_some_and(|s| s.iter().any(|v| v == "confirmed")) {
                "unresolved_mapping".to_string()
            } else {
                "no_source_rating".to_string()
            };
            missing_rating_causes.insert(*issue_id, cause);
        }
    }

    Ok(CreatorLibrary {
        issues,
        issue_index,
        credits,
        ratings,
        rating_timestamps,
        metadata_issues,
        missing_rating_causes,
        coverage_override,
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
    if parts.len() != 2
        || parts[0] != "creator"
        || parts[1].is_empty()
        || !parts[1].chars().all(|c| c.is_ascii_digit())
    {
        return None;
    }
    parts[1].parse().ok()
}

fn parse_series_key(key: &str) -> Option<i64> {
    let (prefix, separator, suffix) = match key.find(':') {
        Some(index) => (&key[..index], ":", &key[index + 1..]),
        None => (key, "", ""),
    };
    if separator.is_empty()
        || prefix != "thread"
        || suffix.is_empty()
        || !suffix.chars().all(|c| c.is_ascii_digit())
    {
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
    let raw = raw
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| {
            bad_request("keys must be a non-empty comma-separated list of creator keys")
        })?;
    let keys = split_keys(raw);
    if keys.is_empty() {
        return Err(bad_request(
            "keys must be a non-empty comma-separated list of creator keys",
        ));
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
    let raw = raw
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| bad_request(message))?;
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

/// Python `round(value, places)` on binary floats: round half to even on the
/// exact binary value (so 4.175, stored just below the tie, rounds to 4.17).
///
/// Rust's `{:.N}` float formatting is exact, so the digits below are the true
/// decimal expansion of the double; a tie exists only when they are exactly `5`
/// followed by zeros.
fn round_half_even(value: f64, places: i32) -> f64 {
    if !value.is_finite() || !(0..=15).contains(&places) {
        return value;
    }
    let places_usize = places as usize;
    let text = format!("{:.*}", places_usize + 120, value.abs());
    let (int_part, frac_part) = text.split_once('.').unwrap_or((text.as_str(), ""));
    let kept = &frac_part[..places_usize];
    let rest = frac_part[places_usize..].bytes().collect::<Vec<u8>>();
    let Ok(mut digits) = format!("{int_part}{kept}").parse::<u128>() else {
        return value;
    };
    let round_up = match rest.first() {
        Some(b'5') => {
            if rest[1..].iter().any(|digit| *digit != b'0') {
                true
            } else {
                digits % 2 == 1
            }
        }
        Some(digit) => *digit > b'5',
        None => false,
    };
    if round_up {
        digits += 1;
    }
    let magnitude = digits as f64 / 10_f64.powi(places);
    magnitude.copysign(value)
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
    (values
        .iter()
        .map(|value| (value - average).powi(2))
        .sum::<f64>()
        / values.len() as f64)
        .sqrt()
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
    credit
        .roles
        .iter()
        .any(|role| HEADLINE_ROLES.contains(&role.as_str()))
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
    if let Some(totals) = &library.coverage_override {
        return totals.clone();
    }
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
        ids.iter()
            .filter(|id| library.metadata_issues.contains(id))
            .count() as i64
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

// ---------------------------------------------------------------------------
// Series aggregation, issue projection, detail and drilldown
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
struct SeriesAggregate {
    thread_id: i64,
    thread_title: String,
    attributed_issue_count: i64,
    rated_issue_ids: Vec<i64>,
    ratings: Vec<f64>,
    roles: BTreeSet<String>,
    unread_issue_count: i64,
    read_unrated_issue_count: i64,
    metadata_complete: bool,
}

impl SeriesAggregate {
    fn rated_issue_count(&self) -> i64 {
        self.rated_issue_ids.len() as i64
    }

    fn average_rating(&self) -> Option<f64> {
        (!self.ratings.is_empty()).then(|| round2(mean(&self.ratings)))
    }

    fn lowest_rating(&self) -> Option<f64> {
        self.ratings.iter().copied().fold1(f64::min)
    }

    fn highest_rating(&self) -> Option<f64> {
        self.ratings.iter().copied().fold1(f64::max)
    }
}

trait FoldFirst {
    fn fold1(self, function: fn(f64, f64) -> f64) -> Option<f64>;
}

impl<T: Iterator<Item = f64>> FoldFirst for T {
    fn fold1(mut self, function: fn(f64, f64) -> f64) -> Option<f64> {
        self.next().map(|first| self.fold(first, function))
    }
}

fn series_sort_key(thread_id: i64) -> String {
    format!("thread:{thread_id}")
}

fn aggregate_series(
    library: &CreatorLibrary,
    creator_id: i64,
    attribution: &Attribution,
) -> Vec<SeriesAggregate> {
    let mut completeness: HashMap<i64, bool> = HashMap::new();
    for issue in &library.issues {
        let covered = library.metadata_issues.contains(&issue.id);
        completeness
            .entry(issue.thread_id)
            .and_modify(|value| *value = *value && covered)
            .or_insert(covered);
    }

    let mut groups: BTreeMap<i64, SeriesAggregate> = BTreeMap::new();
    for issue_id in attribution.issue_ids.iter().copied() {
        let Some(issue) = library.issue(issue_id) else {
            continue;
        };
        let aggregate = groups
            .entry(issue.thread_id)
            .or_insert_with(|| SeriesAggregate {
                thread_id: issue.thread_id,
                thread_title: issue.thread_title.clone(),
                attributed_issue_count: 0,
                rated_issue_ids: Vec::new(),
                ratings: Vec::new(),
                roles: BTreeSet::new(),
                unread_issue_count: 0,
                read_unrated_issue_count: 0,
                metadata_complete: completeness.get(&issue.thread_id).copied().unwrap_or(true),
            });
        aggregate.attributed_issue_count += 1;
        aggregate
            .roles
            .extend(roles_on_issue(library, creator_id, issue_id));
        if issue.status == "unread" {
            aggregate.unread_issue_count += 1;
        }
        if let Some(rating) = library.ratings.get(&issue_id) {
            aggregate.rated_issue_ids.push(issue_id);
            aggregate.ratings.push(*rating);
        } else if issue.status == "read" {
            aggregate.read_unrated_issue_count += 1;
        }
    }

    let mut aggregates: Vec<SeriesAggregate> = groups
        .into_values()
        .filter(|aggregate| !aggregate.rated_issue_ids.is_empty())
        .collect();
    aggregates.sort_by(|a, b| {
        b.rated_issue_count()
            .cmp(&a.rated_issue_count())
            .then_with(|| {
                a.thread_title
                    .to_lowercase()
                    .cmp(&b.thread_title.to_lowercase())
            })
            .then_with(|| a.thread_title.cmp(&b.thread_title))
            .then_with(|| a.thread_id.cmp(&b.thread_id))
    });
    aggregates
}

fn build_series_group(aggregate: &SeriesAggregate) -> CreatorSeriesGroup {
    CreatorSeriesGroup {
        series_key: series_sort_key(aggregate.thread_id),
        thread_id: aggregate.thread_id,
        thread_title: aggregate.thread_title.clone(),
        rated_issue_count: aggregate.rated_issue_count(),
        average_rating: aggregate.average_rating(),
        lowest_rating: aggregate.lowest_rating(),
        highest_rating: aggregate.highest_rating(),
        roles: aggregate.roles.iter().cloned().collect(),
        unread_issue_count: aggregate.unread_issue_count,
        read_unrated_issue_count: aggregate.read_unrated_issue_count,
        metadata_complete: aggregate.metadata_complete,
        sort_key: format!("{:012}", aggregate.thread_id),
        population_scope: "all_verified_credits".to_string(),
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum IssueRowOrder {
    Recent,
    Upcoming,
}

fn issue_row(
    library: &CreatorLibrary,
    creator_id: i64,
    issue: &OwnedIssue,
    order: IssueRowOrder,
) -> CreatorIssueRow {
    let sort_key = match order {
        IssueRowOrder::Recent => issue.id.to_string(),
        IssueRowOrder::Upcoming => format!(
            "{:07}:{:07}:{}",
            issue.queue_position, issue.position, issue.id
        ),
    };
    CreatorIssueRow {
        issue_id: issue.id,
        issue_number: issue.issue_number.clone(),
        thread_id: issue.thread_id,
        thread_title: issue.thread_title.clone(),
        status: issue.status.clone(),
        roles: roles_on_issue(library, creator_id, issue.id),
        effective_rating: library.ratings.get(&issue.id).copied(),
        rating_timestamp: library.rating_timestamps.get(&issue.id).map(iso_timestamp),
        sort_key,
    }
}

fn recent_rows(
    library: &CreatorLibrary,
    creator_id: i64,
    ids: &BTreeSet<i64>,
    page_offset: usize,
    limit: usize,
) -> Vec<CreatorIssueRow> {
    ids.iter()
        .copied()
        .filter_map(|id| library.issue(id))
        .filter(|issue| library.credits.contains_key(&issue.id))
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .skip(page_offset)
        .take(limit)
        .map(|issue| issue_row(library, creator_id, issue, IssueRowOrder::Recent))
        .collect()
}

fn filter_aggregate_to_headline(
    aggregate: &SeriesAggregate,
    rated_issue_ids: &BTreeSet<i64>,
) -> Option<SeriesAggregate> {
    let headline_ids: Vec<i64> = aggregate
        .rated_issue_ids
        .iter()
        .copied()
        .filter(|id| rated_issue_ids.contains(id))
        .collect();
    if headline_ids.len() < MIN_SERIES_SAMPLE {
        return None;
    }
    let id_to_rating: HashMap<i64, f64> = aggregate
        .rated_issue_ids
        .iter()
        .copied()
        .zip(aggregate.ratings.iter().copied())
        .collect();
    let headline_ratings: Vec<f64> = headline_ids
        .iter()
        .filter_map(|id| id_to_rating.get(id).copied())
        .collect();
    Some(SeriesAggregate {
        thread_id: aggregate.thread_id,
        thread_title: aggregate.thread_title.clone(),
        attributed_issue_count: aggregate.attributed_issue_count,
        rated_issue_ids: headline_ids,
        ratings: headline_ratings,
        roles: aggregate.roles.clone(),
        unread_issue_count: aggregate.unread_issue_count,
        read_unrated_issue_count: aggregate.read_unrated_issue_count,
        metadata_complete: aggregate.metadata_complete,
    })
}

fn series_insight(aggregate: &SeriesAggregate) -> CreatorSeriesInsight {
    let group = build_series_group(aggregate);
    CreatorSeriesInsight {
        series_key: group.series_key,
        thread_id: group.thread_id,
        thread_title: group.thread_title,
        rated_issue_count: group.rated_issue_count,
        average_rating: aggregate.average_rating().unwrap_or(0.0),
        lowest_rating: aggregate.lowest_rating().unwrap_or(0.0),
        highest_rating: aggregate.highest_rating().unwrap_or(0.0),
        roles: group.roles,
        metadata_complete: group.metadata_complete,
        sort_key: series_sort_key(group.thread_id),
    }
}

fn compute_insights(
    library: &CreatorLibrary,
    creator_id: i64,
    attribution: &Attribution,
    headline_rated: &BTreeSet<i64>,
    aggregates: &[SeriesAggregate],
) -> Option<CreatorInsights> {
    if headline_rated.is_empty() {
        return None;
    }
    let filtered: Vec<SeriesAggregate> = aggregates
        .iter()
        .filter(|aggregate| aggregate.metadata_complete)
        .filter_map(|aggregate| filter_aggregate_to_headline(aggregate, headline_rated))
        .collect();
    let qualifying: Vec<&SeriesAggregate> = filtered.iter().collect();
    let excluded_incomplete = aggregates
        .iter()
        .filter(|aggregate| !aggregate.metadata_complete && !aggregate.rated_issue_ids.is_empty())
        .count() as i64;

    let pick = |key: fn(&SeriesAggregate) -> (f64, String)| -> Option<&SeriesAggregate> {
        qualifying
            .iter()
            .copied()
            .min_by(|a, b| key(a).partial_cmp(&key(b)).unwrap_or(Ordering::Equal))
    };
    let strongest = pick(|aggregate| {
        (
            -(aggregate.average_rating().unwrap_or(0.0)),
            series_sort_key(aggregate.thread_id),
        )
    });
    let weakest = pick(|aggregate| {
        (
            aggregate.average_rating().unwrap_or(0.0),
            series_sort_key(aggregate.thread_id),
        )
    });
    let most_rated = pick(|aggregate| {
        (
            -(aggregate.rated_issue_count() as f64),
            series_sort_key(aggregate.thread_id),
        )
    });

    let mut issue_insights: Vec<CreatorIssueInsight> = headline_rated
        .iter()
        .copied()
        .filter_map(|id| library.issue(id))
        .map(|issue| CreatorIssueInsight {
            issue_id: issue.id,
            issue_number: issue.issue_number.clone(),
            thread_id: issue.thread_id,
            thread_title: issue.thread_title.clone(),
            effective_rating: *library.ratings.get(&issue.id).unwrap_or(&0.0),
            roles: roles_on_issue(library, creator_id, issue.id),
            sort_key: issue.id.to_string(),
        })
        .collect();
    issue_insights.sort_by_key(|insight| insight.issue_id);

    let mut highest: Vec<CreatorIssueInsight> = issue_insights.to_vec();
    highest.sort_by(|a, b| {
        b.effective_rating
            .partial_cmp(&a.effective_rating)
            .unwrap_or(Ordering::Equal)
            .then(a.thread_id.cmp(&b.thread_id))
            .then(a.issue_id.cmp(&b.issue_id))
    });
    highest.truncate(INDIVIDUAL_ISSUE_LIMIT);
    let highest_ids: HashSet<i64> = highest.iter().map(|insight| insight.issue_id).collect();
    let mut lowest: Vec<CreatorIssueInsight> = issue_insights
        .iter()
        .filter(|insight| !highest_ids.contains(&insight.issue_id))
        .cloned()
        .collect();
    lowest.sort_by(|a, b| {
        a.effective_rating
            .partial_cmp(&b.effective_rating)
            .unwrap_or(Ordering::Equal)
            .then(a.thread_id.cmp(&b.thread_id))
            .then(a.issue_id.cmp(&b.issue_id))
    });
    lowest.truncate(INDIVIDUAL_ISSUE_LIMIT);
    let combined = lowest.is_empty();

    let message = if !qualifying.is_empty() {
        None
    } else {
        let sample_sized: Vec<&SeriesAggregate> = aggregates
            .iter()
            .filter(|aggregate| aggregate.rated_issue_count() >= MIN_SERIES_SAMPLE as i64)
            .collect();
        if sample_sized
            .iter()
            .any(|aggregate| !aggregate.metadata_complete)
        {
            Some(INCOMPLETE_METADATA_SERIES_MESSAGE.to_string())
        } else if !sample_sized.is_empty() {
            Some(NON_HEADLINE_SERIES_MESSAGE.to_string())
        } else {
            Some(INSUFFICIENT_SERIES_MESSAGE.to_string())
        }
    };

    let _ = attribution;
    Some(CreatorInsights {
        min_series_sample: MIN_SERIES_SAMPLE as i64,
        series_sample_met: !qualifying.is_empty(),
        series_message: message,
        excluded_incomplete_series_count: excluded_incomplete,
        individual_issue_limit: INDIVIDUAL_ISSUE_LIMIT as i64,
        individual_issues_combined: combined,
        strongest_series: strongest.map(series_insight),
        weakest_series: weakest.map(series_insight),
        most_rated_series: most_rated.map(series_insight),
        highest_rated_issues: highest,
        lowest_rated_issues: lowest,
    })
}

fn build_detail(
    library: &CreatorLibrary,
    creator_key: &str,
    creator_id: i64,
    attribution: &Attribution,
    limit: usize,
    offset: usize,
) -> CreatorDetailResponse {
    let mut headline_rated: BTreeSet<i64> = BTreeSet::new();
    let mut read_unrated: BTreeSet<i64> = BTreeSet::new();
    let mut upcoming: BTreeSet<i64> = BTreeSet::new();
    for issue_id in attribution.issue_ids.iter().copied() {
        let Some(issue) = library.issue(issue_id) else {
            continue;
        };
        let rated = library.ratings.contains_key(&issue_id)
            && library
                .credits
                .get(&issue_id)
                .into_iter()
                .flatten()
                .any(|credit| credit.external_id == creator_id && has_headline_role(credit));
        if rated {
            headline_rated.insert(issue_id);
        }
        if issue.status == "read" && !library.ratings.contains_key(&issue_id) {
            read_unrated.insert(issue_id);
        }
        if issue.status == "unread" {
            upcoming.insert(issue_id);
        }
    }
    let headline_ratings: Vec<f64> = headline_rated
        .iter()
        .filter_map(|id| library.ratings.get(id).copied())
        .collect();
    let summary = CreatorSummaryItem {
        canonical_creator_key: creator_key.to_string(),
        display_name: attribution.display_name.clone(),
        normalized_roles: attribution.roles.iter().cloned().collect(),
        average_rating: (!headline_ratings.is_empty()).then(|| round2(mean(&headline_ratings))),
        ratings_count: headline_ratings.len() as i64,
        read_unrated_count: read_unrated.len() as i64,
        upcoming_count: upcoming.len() as i64,
    };
    let role_stats: Vec<CreatorRoleStat> = attribution
        .roles
        .iter()
        .map(|role| {
            let mut issue_ids = Vec::new();
            for issue_id in attribution.issue_ids.iter().copied() {
                if library
                    .credits
                    .get(&issue_id)
                    .into_iter()
                    .flatten()
                    .any(|credit| credit.external_id == creator_id && credit.roles.contains(role))
                {
                    issue_ids.push(issue_id);
                }
            }
            let role_ratings: Vec<f64> = issue_ids
                .iter()
                .filter_map(|id| library.ratings.get(id).copied())
                .collect();
            CreatorRoleStat {
                role: role.clone(),
                issue_count: issue_ids.len() as i64,
                rated_issue_count: role_ratings.len() as i64,
                average_rating: (!role_ratings.is_empty()).then(|| round2(mean(&role_ratings))),
            }
        })
        .collect();

    let aggregates = aggregate_series(library, creator_id, attribution);
    let series_groups_total = aggregates.len();
    let series_groups: Vec<CreatorSeriesGroup> = aggregates
        .iter()
        .skip(offset)
        .take(limit)
        .map(build_series_group)
        .collect();
    let series_groups_complete = offset + series_groups.len() >= series_groups_total;

    let rated_rows = recent_rows(library, creator_id, &headline_rated, offset, limit);
    let read_unrated_rows = recent_rows(library, creator_id, &read_unrated, offset, limit);
    let mut upcoming_issues: Vec<&OwnedIssue> = upcoming
        .iter()
        .copied()
        .filter_map(|id| library.issue(id))
        .filter(|issue| library.credits.contains_key(&issue.id))
        .collect();
    upcoming_issues.sort_by(|a, b| {
        a.queue_position
            .cmp(&b.queue_position)
            .then(a.position.cmp(&b.position))
            .then(a.id.cmp(&b.id))
    });
    let upcoming_rows: Vec<CreatorIssueRow> = upcoming_issues
        .into_iter()
        .skip(offset)
        .take(limit)
        .map(|issue| issue_row(library, creator_id, issue, IssueRowOrder::Upcoming))
        .collect();

    let has_next = headline_rated.len() > offset + rated_rows.len()
        || read_unrated.len() > offset + read_unrated_rows.len()
        || upcoming.len() > offset + upcoming_rows.len()
        || series_groups_total > offset + series_groups.len();
    let next_cursor = has_next.then(|| (offset + limit).to_string());

    CreatorDetailResponse {
        summary,
        coverage: coverage(library),
        role_stats,
        series_groups,
        series_groups_total: series_groups_total as i64,
        series_groups_complete,
        rated_issues: rated_rows,
        rated_population_scope: "headline_roles_only".to_string(),
        headline_roles: HEADLINE_ROLES
            .iter()
            .map(|role| role.to_string())
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect(),
        read_unrated_issues: read_unrated_rows,
        upcoming_issues: upcoming_rows,
        next_cursor,
        rating_distribution: rating_distribution(&headline_ratings),
        insights: compute_insights(
            library,
            creator_id,
            attribution,
            &headline_rated,
            &aggregates,
        ),
    }
}

fn build_series_issues(
    library: &CreatorLibrary,
    creator_id: i64,
    thread_id: i64,
    limit: usize,
    offset: usize,
) -> Option<CreatorSeriesIssueListResponse> {
    let attribution = attribution(library, creator_id)?;
    let aggregates = aggregate_series(library, creator_id, &attribution);
    let aggregate = aggregates
        .iter()
        .find(|aggregate| aggregate.thread_id == thread_id)?;
    let group_ids: BTreeSet<i64> = aggregate.rated_issue_ids.iter().copied().collect();
    let rows = recent_rows(library, creator_id, &group_ids, offset, limit);
    let group = build_series_group(aggregate);
    let total = group.rated_issue_count;
    Some(CreatorSeriesIssueListResponse {
        series_key: group.series_key,
        thread_id: group.thread_id,
        thread_title: group.thread_title,
        roles: group.roles,
        rated_issue_count: total,
        average_rating: group.average_rating,
        lowest_rating: group.lowest_rating,
        highest_rating: group.highest_rating,
        metadata_complete: group.metadata_complete,
        population_scope: group.population_scope,
        total,
        limit: limit as i64,
        offset: offset as i64,
        issues: rows.clone(),
        next_cursor: (total > offset as i64 + rows.len() as i64)
            .then(|| (offset + limit).to_string()),
    })
}

// ---------------------------------------------------------------------------
// List, summaries and comparison
// ---------------------------------------------------------------------------

fn creator_headline_ratings(
    library: &CreatorLibrary,
    creator_id: i64,
    issue_ids: &BTreeSet<i64>,
) -> Vec<f64> {
    issue_ids
        .iter()
        .copied()
        .filter(|id| {
            library.ratings.contains_key(id)
                && library
                    .credits
                    .get(id)
                    .into_iter()
                    .flatten()
                    .any(|credit| credit.external_id == creator_id && has_headline_role(credit))
        })
        .filter_map(|id| library.ratings.get(&id).copied())
        .collect()
}

fn summary_item(
    library: &CreatorLibrary,
    creator_id: i64,
    creator_key: &str,
    attribution: &Attribution,
) -> CreatorSummaryItem {
    let ratings = creator_headline_ratings(library, creator_id, &attribution.issue_ids);
    let read_unrated = attribution
        .issue_ids
        .iter()
        .filter(|id| {
            library
                .issue(**id)
                .map(|issue| issue.status == "read")
                .unwrap_or(false)
                && !library.ratings.contains_key(id)
        })
        .count() as i64;
    let upcoming = attribution
        .issue_ids
        .iter()
        .filter(|id| {
            library
                .issue(**id)
                .map(|issue| issue.status == "unread")
                .unwrap_or(false)
        })
        .count() as i64;
    CreatorSummaryItem {
        canonical_creator_key: creator_key.to_string(),
        display_name: attribution.display_name.clone(),
        normalized_roles: attribution.roles.iter().cloned().collect(),
        average_rating: (!ratings.is_empty()).then(|| round2(mean(&ratings))),
        ratings_count: ratings.len() as i64,
        read_unrated_count: read_unrated,
        upcoming_count: upcoming,
    }
}

fn all_creator_ids(library: &CreatorLibrary) -> BTreeSet<i64> {
    library
        .credits
        .values()
        .flatten()
        .map(|credit| credit.external_id)
        .collect()
}

fn build_list(
    library: &CreatorLibrary,
    search: Option<&str>,
    sort: &str,
    limit: usize,
    offset: usize,
    min_ratings: usize,
) -> CreatorListResponse {
    let mut items: Vec<CreatorListItem> = Vec::new();
    for creator_id in all_creator_ids(library) {
        let Some(attribution) = attribution(library, creator_id) else {
            continue;
        };
        let ratings = creator_headline_ratings(library, creator_id, &attribution.issue_ids);
        if ratings.is_empty() || ratings.len() < min_ratings {
            continue;
        }
        let display_name = attribution.display_name.clone();
        if let Some(needle) = search {
            if !display_name.to_lowercase().contains(&needle.to_lowercase()) {
                continue;
            }
        }
        items.push(CreatorListItem {
            canonical_creator_key: format!("creator:{creator_id}"),
            display_name,
            normalized_roles: attribution.roles.iter().cloned().collect(),
            average_rating: Some(round2(mean(&ratings))),
            ratings_count: ratings.len() as i64,
        });
    }
    match sort {
        "ratings_count" => items.sort_by(|a, b| {
            b.ratings_count
                .cmp(&a.ratings_count)
                .then(
                    a.display_name
                        .to_lowercase()
                        .cmp(&b.display_name.to_lowercase()),
                )
                .then(a.canonical_creator_key.cmp(&b.canonical_creator_key))
        }),
        "average_rating" => items.sort_by(|a, b| {
            let an = a.average_rating.is_none();
            let bn = b.average_rating.is_none();
            an.cmp(&bn)
                .then_with(|| {
                    b.average_rating
                        .unwrap_or(0.0)
                        .partial_cmp(&a.average_rating.unwrap_or(0.0))
                        .unwrap_or(Ordering::Equal)
                })
                .then_with(|| b.ratings_count.cmp(&a.ratings_count))
                .then_with(|| {
                    a.display_name
                        .to_lowercase()
                        .cmp(&b.display_name.to_lowercase())
                })
                .then_with(|| a.canonical_creator_key.cmp(&b.canonical_creator_key))
        }),
        _ => items.sort_by(|a, b| {
            a.display_name
                .to_lowercase()
                .cmp(&b.display_name.to_lowercase())
                .then(a.canonical_creator_key.cmp(&b.canonical_creator_key))
        }),
    }
    let total = items.len();
    let paged = if offset >= items.len() {
        vec![]
    } else {
        items[offset..(offset + limit).min(items.len())].to_vec()
    };
    CreatorListResponse {
        items: paged,
        total: total as i64,
        limit: limit as i64,
        offset: offset as i64,
        coverage: coverage(library),
    }
}

fn build_summaries(library: &CreatorLibrary, keys: &[String]) -> CreatorSummariesResponse {
    let mut summaries = BTreeMap::new();
    for key in keys {
        let Some(creator_id) = parse_creator_key(key) else {
            continue;
        };
        let Some(attribution) = attribution(library, creator_id) else {
            continue;
        };
        summaries.insert(
            key.clone(),
            summary_item(library, creator_id, key, &attribution),
        );
    }
    CreatorSummariesResponse {
        summaries,
        coverage: coverage(library),
    }
}

fn distribution_key(rating: f64) -> String {
    if rating == (rating as i64) as f64 {
        (rating as i64).to_string()
    } else {
        rating.to_string()
    }
}

fn issue_refs(
    library: &CreatorLibrary,
    issue_ids: &BTreeSet<i64>,
) -> Vec<CreatorComparisonIssueRef> {
    let mut entries: Vec<(bool, String, String, i64, i64, CreatorComparisonIssueRef)> = issue_ids
        .iter()
        .copied()
        .filter_map(|id| library.issue(id).map(|issue| (id, issue)))
        .map(|(id, issue)| {
            (
                false,
                issue.thread_title.to_lowercase(),
                issue.thread_title.clone(),
                issue.thread_id,
                id,
                CreatorComparisonIssueRef {
                    issue_id: id,
                    thread_id: issue.thread_id,
                    thread_title: issue.thread_title.clone(),
                    issue_number: issue.issue_number.clone(),
                    status: issue.status.clone(),
                },
            )
        })
        .collect();
    entries.sort_by(|a, b| {
        a.0.cmp(&b.0)
            .then(a.1.cmp(&b.1))
            .then(a.2.cmp(&b.2))
            .then(a.3.cmp(&b.3))
            .then(a.4.cmp(&b.4))
    });
    entries
        .into_iter()
        .take(MAX_ISSUE_REFS)
        .map(|entry| entry.5)
        .collect()
}

fn build_comparison(
    library: &CreatorLibrary,
    requested_keys: &[String],
) -> CreatorComparisonResponse {
    let mut comparisons = BTreeMap::new();
    let mut insufficient_data_keys = Vec::new();
    for key in requested_keys {
        let Some(creator_id) = parse_creator_key(key) else {
            continue;
        };
        let Some(attribution) = attribution(library, creator_id) else {
            continue;
        };
        let ratings = creator_headline_ratings(library, creator_id, &attribution.issue_ids);
        let average = (!ratings.is_empty()).then(|| round2(mean(&ratings)));
        let median_value = (!ratings.is_empty()).then(|| round2(median(&ratings)));
        let mut distribution: BTreeMap<String, i64> = BTreeMap::new();
        for rating in &ratings {
            *distribution.entry(distribution_key(*rating)).or_default() += 1;
        }
        let top_rating_rate = (!ratings.is_empty()).then(|| {
            round3(
                ratings.iter().filter(|rating| **rating >= 5.0).count() as f64
                    / ratings.len() as f64,
            )
        });
        let role_stats: Vec<CreatorComparisonRoleStat> = attribution
            .roles
            .iter()
            .map(|role| {
                let ids: Vec<i64> = attribution
                    .issue_ids
                    .iter()
                    .copied()
                    .filter(|id| {
                        library.credits.get(id).into_iter().flatten().any(|credit| {
                            credit.external_id == creator_id && credit.roles.contains(role)
                        })
                    })
                    .collect();
                let role_ratings: Vec<f64> = ids
                    .iter()
                    .filter_map(|id| library.ratings.get(id).copied())
                    .collect();
                CreatorComparisonRoleStat {
                    role: role.clone(),
                    issue_count: ids.len() as i64,
                    rated_issue_count: role_ratings.len() as i64,
                    average_rating: (!role_ratings.is_empty()).then(|| round2(mean(&role_ratings))),
                }
            })
            .collect();

        let aggregates = aggregate_series(library, creator_id, &attribution);
        let mut ranked: Vec<&SeriesAggregate> = aggregates
            .iter()
            .filter(|aggregate| aggregate.rated_issue_count() >= MIN_RATED_FOR_RELIABLE as i64)
            .collect();
        ranked.sort_by(|a, b| {
            b.average_rating()
                .unwrap_or(0.0)
                .partial_cmp(&a.average_rating().unwrap_or(0.0))
                .unwrap_or(Ordering::Equal)
                .then_with(|| b.attributed_issue_count.cmp(&a.attributed_issue_count))
                .then_with(|| {
                    a.thread_title
                        .to_lowercase()
                        .cmp(&b.thread_title.to_lowercase())
                })
                .then_with(|| a.thread_title.cmp(&b.thread_title))
                .then_with(|| a.thread_id.cmp(&b.thread_id))
        });
        let strongest_series: Vec<CreatorComparisonSeriesAggregate> = ranked
            .into_iter()
            .take(MAX_SERIES_AGGREGATES)
            .map(|aggregate| CreatorComparisonSeriesAggregate {
                thread_id: aggregate.thread_id,
                thread_title: aggregate.thread_title.clone(),
                issue_count: aggregate.attributed_issue_count,
                rated_issue_count: aggregate.rated_issue_count(),
                average_rating: aggregate.average_rating().unwrap_or(0.0),
            })
            .collect();

        let unread_ids: BTreeSet<i64> = attribution
            .issue_ids
            .iter()
            .copied()
            .filter(|id| {
                library
                    .issue(*id)
                    .map(|issue| issue.status == "unread")
                    .unwrap_or(false)
            })
            .collect();
        let read_unrated_ids: BTreeSet<i64> = attribution
            .issue_ids
            .iter()
            .copied()
            .filter(|id| {
                library
                    .issue(*id)
                    .map(|issue| issue.status == "read")
                    .unwrap_or(false)
                    && !library.ratings.contains_key(id)
            })
            .collect();
        let insufficient_data = ratings.len() < MIN_RATED_FOR_RELIABLE;
        if insufficient_data {
            insufficient_data_keys.push(key.clone());
        }
        comparisons.insert(
            format!("creator:{creator_id}"),
            CreatorComparisonItem {
                canonical_creator_key: format!("creator:{creator_id}"),
                display_name: attribution.display_name.clone(),
                normalized_roles: attribution.roles.iter().cloned().collect(),
                average_rating: average,
                median_rating: median_value,
                ratings_count: ratings.len() as i64,
                rating_distribution: distribution,
                top_rating_rate,
                role_stats,
                strongest_series,
                min_rated_issues_per_series: MIN_RATED_FOR_RELIABLE as i64,
                unread_upcoming_count: unread_ids.len() as i64,
                read_unrated_count: read_unrated_ids.len() as i64,
                unread_issue_refs: issue_refs(library, &unread_ids),
                read_unrated_issue_refs: issue_refs(library, &read_unrated_ids),
                max_issue_refs_per_group: MAX_ISSUE_REFS as i64,
                insufficient_data,
            },
        );
    }
    let library_coverage = coverage(library);
    CreatorComparisonResponse {
        comparisons,
        coverage: CreatorComparisonCoverage {
            rated_issues_total: library_coverage.rated_issues_total,
            rated_issues_with_creator_metadata: library_coverage.rated_issues_with_creator_metadata,
            ratings_complete: library_coverage.ratings_complete,
            read_unrated_issues_total: library_coverage.read_unrated_issues_total,
            read_unrated_issues_with_creator_metadata: library_coverage
                .read_unrated_issues_with_creator_metadata,
            read_unrated_complete: library_coverage.read_unrated_complete,
            unread_issues_total: library_coverage.unread_issues_total,
            unread_issues_with_creator_metadata: library_coverage
                .unread_issues_with_creator_metadata,
            upcoming_complete: library_coverage.upcoming_complete,
        },
        insufficient_data_keys,
    }
}

// ---------------------------------------------------------------------------
// Discovery views
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
struct DiscoveryProfile {
    key: String,
    display_name: String,
    roles: Vec<String>,
    rated_issue_count: i64,
    average_rating: Option<f64>,
    median_rating: Option<f64>,
    rating_stddev: Option<f64>,
    rating_spread: Option<f64>,
    min_rating: Option<f64>,
    max_rating: Option<f64>,
    top_rating_rate: Option<f64>,
    top_rating_count: i64,
    unread_issue_count: i64,
    read_unrated_issue_count: i64,
    trend_points: Vec<(DateTime<Utc>, i64, f64)>,
}

fn discovery_profile(library: &CreatorLibrary, creator_id: i64) -> Option<DiscoveryProfile> {
    let attribution = attribution(library, creator_id)?;
    let ratings = creator_headline_ratings(library, creator_id, &attribution.issue_ids);
    let (average, median, stddev, spread, min, max, top_rate, top_count) = if ratings.is_empty() {
        (None, None, None, None, None, None, None, 0)
    } else {
        let min = ratings.iter().copied().fold(f64::INFINITY, f64::min);
        let max = ratings.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        let top_count = ratings.iter().filter(|rating| **rating >= 5.0).count() as i64;
        (
            Some(round2(mean(&ratings))),
            Some(round2(median(&ratings))),
            Some(round2(pstdev(&ratings))),
            Some(round2(max - min)),
            Some(min),
            Some(max),
            Some(round3(top_count as f64 / ratings.len() as f64)),
            top_count,
        )
    };
    let unread_issue_count = attribution
        .issue_ids
        .iter()
        .filter(|id| {
            library
                .issue(**id)
                .map(|issue| issue.status == "unread")
                .unwrap_or(false)
        })
        .count() as i64;
    let read_unrated_issue_count = attribution
        .issue_ids
        .iter()
        .filter(|id| {
            library
                .issue(**id)
                .map(|issue| issue.status == "read")
                .unwrap_or(false)
                && !library.ratings.contains_key(id)
        })
        .count() as i64;
    // Same headline-eligible issue set as the personal average (Python
    // `rated_issue_ids`): cover-only and editorial credits never feed the trend.
    let mut trend_points: Vec<(DateTime<Utc>, i64, f64)> = attribution
        .issue_ids
        .iter()
        .copied()
        .filter(|id| {
            library
                .credits
                .get(id)
                .into_iter()
                .flatten()
                .any(|credit| credit.external_id == creator_id && has_headline_role(credit))
        })
        .filter_map(|id| {
            let rating = *library.ratings.get(&id)?;
            let timestamp = *library.rating_timestamps.get(&id)?;
            Some((timestamp, id, rating))
        })
        .collect();
    trend_points.sort_by(|a, b| a.0.cmp(&b.0).then(a.1.cmp(&b.1)));
    Some(DiscoveryProfile {
        key: format!("creator:{creator_id}"),
        display_name: attribution.display_name,
        roles: attribution.roles.into_iter().collect(),
        rated_issue_count: ratings.len() as i64,
        average_rating: average,
        median_rating: median,
        rating_stddev: stddev,
        rating_spread: spread,
        min_rating: min,
        max_rating: max,
        top_rating_rate: top_rate,
        top_rating_count: top_count,
        unread_issue_count,
        read_unrated_issue_count,
        trend_points,
    })
}

fn reason(
    metric: &str,
    label: &str,
    value: f64,
    threshold: f64,
    comparison: &str,
) -> CreatorDiscoveryReason {
    CreatorDiscoveryReason {
        metric: metric.to_string(),
        label: label.to_string(),
        value: round3(value),
        threshold: round3(threshold),
        comparison: comparison.to_string(),
    }
}

fn discovery_entry(
    profile: &DiscoveryProfile,
    reasons: Vec<CreatorDiscoveryReason>,
) -> CreatorDiscoveryEntry {
    CreatorDiscoveryEntry {
        canonical_creator_key: profile.key.clone(),
        display_name: profile.display_name.clone(),
        normalized_roles: profile.roles.clone(),
        rated_issue_count: profile.rated_issue_count,
        average_rating: profile.average_rating,
        median_rating: profile.median_rating,
        rating_stddev: profile.rating_stddev,
        rating_spread: profile.rating_spread,
        min_rating: profile.min_rating,
        max_rating: profile.max_rating,
        top_rating_rate: profile.top_rating_rate,
        top_rating_count: profile.top_rating_count,
        unread_issue_count: profile.unread_issue_count,
        read_unrated_issue_count: profile.read_unrated_issue_count,
        trend_direction: None,
        earlier_average_rating: None,
        recent_average_rating: None,
        trend_delta: None,
        trend_sample_count: 0,
        reasons,
    }
}

fn discovery_view(
    mode: &str,
    title: &str,
    description: &str,
    min_sample: i64,
    mut entries: Vec<CreatorDiscoveryEntry>,
) -> CreatorDiscoveryView {
    let total = entries.len() as i64;
    let truncated = entries.len() > MAX_DISCOVERY_ENTRIES;
    entries.truncate(MAX_DISCOVERY_ENTRIES);
    CreatorDiscoveryView {
        mode: mode.to_string(),
        title: title.to_string(),
        description: description.to_string(),
        min_sample,
        total,
        truncated,
        max_entries: MAX_DISCOVERY_ENTRIES as i64,
        entries,
    }
}

fn build_discoveries(library: &CreatorLibrary) -> CreatorDiscoveryResponse {
    let profiles: Vec<DiscoveryProfile> = all_creator_ids(library)
        .into_iter()
        .filter_map(|creator_id| discovery_profile(library, creator_id))
        .collect();

    let mut consistently_loved: Vec<(f64, f64, i64, String, CreatorDiscoveryEntry)> = Vec::new();
    let mut polarizing: Vec<(f64, f64, i64, String, CreatorDiscoveryEntry)> = Vec::new();
    let mut most_read: Vec<(i64, f64, String, CreatorDiscoveryEntry)> = Vec::new();
    let mut top_rate: Vec<(f64, i64, f64, String, CreatorDiscoveryEntry)> = Vec::new();
    let mut small_sample: Vec<(f64, i64, String, CreatorDiscoveryEntry)> = Vec::new();
    let mut loved_unread: Vec<(i64, f64, i64, String, CreatorDiscoveryEntry)> = Vec::new();
    let mut trend: Vec<(f64, usize, String, CreatorDiscoveryEntry)> = Vec::new();

    for profile in &profiles {
        let average = profile.average_rating.unwrap_or(0.0);
        let stddev = profile.rating_stddev.unwrap_or(0.0);
        let spread = profile.rating_spread.unwrap_or(0.0);
        let top = profile.top_rating_rate.unwrap_or(0.0);
        let count = profile.rated_issue_count;

        if count >= MIN_RATED_FOR_RELIABLE as i64 && average >= 4.0 && stddev <= 0.5 {
            let entry = discovery_entry(
                profile,
                vec![
                    reason("average_rating", "average rating", average, 4.0, "gte"),
                    reason(
                        "rating_stddev",
                        "rating standard deviation",
                        stddev,
                        0.5,
                        "lte",
                    ),
                    reason(
                        "rated_issue_count",
                        "rated issues",
                        count as f64,
                        5.0,
                        "gte",
                    ),
                ],
            );
            consistently_loved.push((-average, stddev, -count, profile.key.clone(), entry));
        }
        if count >= MIN_RATED_FOR_RELIABLE as i64 && spread >= 2.0 {
            let entry = discovery_entry(
                profile,
                vec![
                    reason("rating_spread", "rating spread", spread, 2.0, "gte"),
                    reason(
                        "rated_issue_count",
                        "rated issues",
                        count as f64,
                        5.0,
                        "gte",
                    ),
                ],
            );
            polarizing.push((-stddev, -spread, -count, profile.key.clone(), entry));
        }
        if count >= 1 {
            let entry = discovery_entry(
                profile,
                vec![reason(
                    "rated_issue_count",
                    "rated issues",
                    count as f64,
                    1.0,
                    "gte",
                )],
            );
            most_read.push((-count, -average, profile.key.clone(), entry));
        }
        if count >= MIN_RATED_FOR_RELIABLE as i64 && top >= 0.6 {
            let entry = discovery_entry(
                profile,
                vec![
                    reason("top_rating_rate", "top-rating rate", top, 0.6, "gte"),
                    reason(
                        "rated_issue_count",
                        "rated issues",
                        count as f64,
                        5.0,
                        "gte",
                    ),
                ],
            );
            top_rate.push((-top, -count, -average, profile.key.clone(), entry));
        }
        if (1..=(MIN_RATED_FOR_RELIABLE - 1) as i64).contains(&count) && average >= 4.0 {
            let entry = discovery_entry(
                profile,
                vec![
                    reason("average_rating", "average rating", average, 4.0, "gte"),
                    reason(
                        "rated_issue_count",
                        "rated issues",
                        count as f64,
                        4.0,
                        "lte",
                    ),
                ],
            );
            small_sample.push((-average, -count, profile.key.clone(), entry));
        }
        if count >= 1 && profile.unread_issue_count >= 1 && average >= 4.0 {
            let entry = discovery_entry(
                profile,
                vec![
                    reason("average_rating", "average rating", average, 4.0, "gte"),
                    reason(
                        "unread_issue_count",
                        "unread issues",
                        profile.unread_issue_count as f64,
                        1.0,
                        "gte",
                    ),
                ],
            );
            loved_unread.push((
                -profile.unread_issue_count,
                -average,
                -count,
                profile.key.clone(),
                entry,
            ));
        }
        if profile.trend_points.len() >= TREND_MIN_SAMPLE {
            let midpoint = profile.trend_points.len() / 2;
            let earlier: Vec<f64> = profile.trend_points[..midpoint]
                .iter()
                .map(|point| point.2)
                .collect();
            let recent: Vec<f64> = profile.trend_points[midpoint..]
                .iter()
                .map(|point| point.2)
                .collect();
            let earlier_average = round2(mean(&earlier));
            let recent_average = round2(mean(&recent));
            let delta = round2(recent_average - earlier_average);
            if delta.abs() >= TREND_MIN_DELTA {
                let mut entry = discovery_entry(
                    profile,
                    vec![
                        reason(
                            "trend_delta",
                            "change in average",
                            delta.abs(),
                            TREND_MIN_DELTA,
                            "gte",
                        ),
                        reason(
                            "trend_sample_count",
                            "dated rated issues",
                            profile.trend_points.len() as f64,
                            TREND_MIN_SAMPLE as f64,
                            "gte",
                        ),
                    ],
                );
                entry.trend_direction =
                    Some(if delta > 0.0 { "warmed" } else { "cooled" }.to_string());
                entry.earlier_average_rating = Some(earlier_average);
                entry.recent_average_rating = Some(recent_average);
                entry.trend_delta = Some(delta);
                entry.trend_sample_count = profile.trend_points.len() as i64;
                trend.push((
                    -delta.abs(),
                    profile.trend_points.len(),
                    profile.key.clone(),
                    entry,
                ));
            }
        }
    }

    let finish4 = |mut rows: Vec<(f64, f64, i64, String, CreatorDiscoveryEntry)>| {
        rows.sort_by(|a, b| {
            a.0.partial_cmp(&b.0)
                .unwrap_or(Ordering::Equal)
                .then(a.1.partial_cmp(&b.1).unwrap_or(Ordering::Equal))
                .then(a.2.cmp(&b.2))
                .then(a.3.cmp(&b.3))
        });
        rows.into_iter().map(|row| row.4).collect::<Vec<_>>()
    };
    let consistently_loved = finish4(consistently_loved);
    let polarizing = finish4(polarizing);

    most_read.sort_by(|a, b| {
        a.0.cmp(&b.0)
            .then(a.1.partial_cmp(&b.1).unwrap_or(Ordering::Equal))
            .then(a.2.cmp(&b.2))
    });
    let most_read: Vec<CreatorDiscoveryEntry> = most_read.into_iter().map(|row| row.3).collect();

    top_rate.sort_by(|a, b| {
        a.0.partial_cmp(&b.0)
            .unwrap_or(Ordering::Equal)
            .then(a.1.cmp(&b.1))
            .then(a.2.partial_cmp(&b.2).unwrap_or(Ordering::Equal))
            .then(a.3.cmp(&b.3))
    });
    let top_rate: Vec<CreatorDiscoveryEntry> = top_rate.into_iter().map(|row| row.4).collect();

    small_sample.sort_by(|a, b| {
        a.0.partial_cmp(&b.0)
            .unwrap_or(Ordering::Equal)
            .then(a.1.cmp(&b.1))
            .then(a.2.cmp(&b.2))
    });
    let small_sample: Vec<CreatorDiscoveryEntry> =
        small_sample.into_iter().map(|row| row.3).collect();

    loved_unread.sort_by(|a, b| {
        a.0.cmp(&b.0)
            .then(a.1.partial_cmp(&b.1).unwrap_or(Ordering::Equal))
            .then(a.2.cmp(&b.2))
            .then(a.3.cmp(&b.3))
    });
    let loved_unread: Vec<CreatorDiscoveryEntry> =
        loved_unread.into_iter().map(|row| row.4).collect();

    trend.sort_by(|a, b| {
        a.0.partial_cmp(&b.0)
            .unwrap_or(Ordering::Equal)
            .then(b.1.cmp(&a.1))
            .then(a.2.cmp(&b.2))
    });
    let trend: Vec<CreatorDiscoveryEntry> = trend.into_iter().map(|row| row.3).collect();

    let rated_ids: HashSet<i64> = library.ratings.keys().copied().collect();
    let with_metadata = rated_ids
        .iter()
        .filter(|id| library.metadata_issues.contains(id))
        .count() as i64;

    CreatorDiscoveryResponse {
        views: vec![
            discovery_view("consistently_loved", "Most consistently loved", "High personal average with at least 5 rated issues and a standard deviation of 0.5 or less.", 5, consistently_loved),
            discovery_view("polarizing", "Most polarizing", "At least 5 rated issues with a spread of 2.0 or more between the lowest and highest rating.", 5, polarizing),
            discovery_view("most_read", "Most read", "Creators with the largest rated sample in your library.", 1, most_read),
            discovery_view("highest_top_rating_rate", "Highest top-rating rate", "At least 5 rated issues with 60% or more at the top of your scale.", 5, top_rate),
            discovery_view("great_average_small_sample", "Great average, small sample", "An average of 4.0 or more from 4 rated issues or fewer — promising, but not yet proven.", 1, small_sample),
            discovery_view("loved_with_unread", "Loved creators with unread work", "An average of 4.0 or more with unread issues still in your pile.", 1, loved_unread),
            discovery_view("moved_over_time", "Warmed to / cooled on", "At least 6 dated ratings where the recent half averages 0.5 or more away from the earlier half.", 6, trend),
        ],
        coverage: CreatorDiscoveryCoverage {
            rated_issues_total: rated_ids.len() as i64,
            rated_issues_with_creator_metadata: with_metadata,
            ratings_complete: with_metadata >= rated_ids.len() as i64,
        },
        minimum_reliable_sample: MIN_RATED_FOR_RELIABLE as i64,
        max_entries_per_view: MAX_DISCOVERY_ENTRIES as i64,
    }
}

// ---------------------------------------------------------------------------
// Team chemistry
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
struct TeamInputs {
    eligible_issue_creators: BTreeMap<i64, BTreeMap<i64, BTreeSet<String>>>,
    display_names: HashMap<i64, String>,
    baseline_ratings: HashMap<i64, BTreeMap<i64, f64>>,
}

fn team_inputs(library: &CreatorLibrary) -> TeamInputs {
    let mut eligible_issue_creators: BTreeMap<i64, BTreeMap<i64, BTreeSet<String>>> =
        BTreeMap::new();
    let mut display_names: HashMap<i64, String> = HashMap::new();
    let mut baseline_ratings: HashMap<i64, BTreeMap<i64, f64>> = HashMap::new();
    for issue in &library.issues {
        let Some(rating) = library.ratings.get(&issue.id).copied() else {
            continue;
        };
        let Some(credits) = library.credits.get(&issue.id) else {
            continue;
        };
        let mut members: BTreeMap<i64, BTreeSet<String>> = BTreeMap::new();
        for credit in credits {
            display_names
                .entry(credit.external_id)
                .or_insert_with(|| credit.display_name.clone());
            if credit
                .roles
                .iter()
                .any(|role| HEADLINE_ROLES.contains(&role.as_str()))
            {
                baseline_ratings
                    .entry(credit.external_id)
                    .or_default()
                    .entry(issue.id)
                    .or_insert(rating);
            }
            let eligible: BTreeSet<String> = credit
                .roles
                .iter()
                .filter(|role| TEAM_ELIGIBLE_ROLES.contains(&role.as_str()))
                .cloned()
                .collect();
            if !eligible.is_empty() {
                members
                    .entry(credit.external_id)
                    .or_default()
                    .extend(eligible);
            }
        }
        if members.len() >= 2 {
            eligible_issue_creators.insert(issue.id, members);
        }
    }
    TeamInputs {
        eligible_issue_creators,
        display_names,
        baseline_ratings,
    }
}

fn team_distribution(ratings: &[f64]) -> BTreeMap<String, i64> {
    let mut counts: Vec<(String, i64)> = Vec::new();
    for rating in ratings {
        let key = distribution_key(*rating);
        if let Some(entry) = counts.iter_mut().find(|entry| entry.0 == key) {
            entry.1 += 1;
        } else {
            counts.push((key, 1));
        }
    }
    counts.sort_by(|a, b| {
        let a_value: f64 = a.0.parse().unwrap_or(0.0);
        let b_value: f64 = b.0.parse().unwrap_or(0.0);
        b_value.partial_cmp(&a_value).unwrap_or(Ordering::Equal)
    });
    counts.into_iter().collect()
}

fn team_issue_refs(
    library: &CreatorLibrary,
    issue_ids: &BTreeSet<i64>,
) -> Vec<CreatorTeamIssueRef> {
    let mut entries: Vec<(String, String, i64, i64, CreatorTeamIssueRef)> = issue_ids
        .iter()
        .copied()
        .filter_map(|id| library.issue(id).map(|issue| (id, issue)))
        .map(|(id, issue)| {
            (
                issue.thread_title.to_lowercase(),
                issue.thread_title.clone(),
                issue.thread_id,
                id,
                CreatorTeamIssueRef {
                    issue_id: id,
                    thread_id: issue.thread_id,
                    thread_title: issue.thread_title.clone(),
                    issue_number: issue.issue_number.clone(),
                    effective_rating: library.ratings.get(&id).copied(),
                    status: if library.ratings.contains_key(&id) {
                        "read"
                    } else {
                        "unread"
                    }
                    .to_string(),
                },
            )
        })
        .collect();
    entries.sort_by(|a, b| {
        a.0.cmp(&b.0)
            .then(a.1.cmp(&b.1))
            .then(a.2.cmp(&b.2))
            .then(a.3.cmp(&b.3))
    });
    entries
        .into_iter()
        .take(MAX_ISSUE_REFS)
        .map(|entry| entry.4)
        .collect()
}

type RankedTeamPair<'a> = (f64, usize, (i64, i64), &'a BTreeSet<i64>);

fn build_team_chemistry(library: &CreatorLibrary) -> CreatorTeamChemistryResponse {
    let inputs = team_inputs(library);
    let mut pair_issues: BTreeMap<(i64, i64), BTreeSet<i64>> = BTreeMap::new();
    for (issue_id, members) in &inputs.eligible_issue_creators {
        let ids: Vec<i64> = members.keys().copied().collect();
        for first in 0..ids.len() {
            for second in (first + 1)..ids.len() {
                pair_issues
                    .entry((ids[first], ids[second]))
                    .or_default()
                    .insert(*issue_id);
            }
        }
    }
    let qualifying: Vec<(&(i64, i64), &BTreeSet<i64>)> = pair_issues
        .iter()
        .filter(|(_, issues)| issues.len() >= MIN_SHARED_TEAM_SAMPLE)
        .collect();

    let mut ranked: Vec<RankedTeamPair<'_>> = qualifying
        .iter()
        .map(|(pair, issues)| {
            let ratings: Vec<f64> = issues
                .iter()
                .filter_map(|id| library.ratings.get(id).copied())
                .collect();
            (round2(mean(&ratings)), issues.len(), **pair, *issues)
        })
        .collect();
    ranked.sort_by(|a, b| {
        b.0.partial_cmp(&a.0)
            .unwrap_or(Ordering::Equal)
            .then(b.1.cmp(&a.1))
            .then(a.2.cmp(&b.2))
    });

    let pairs: Vec<CreatorTeamPair> = ranked
        .into_iter()
        .take(MAX_RANKED_TEAM_PAIRS)
        .map(|(shared_average, _, pair, issues)| {
            let mut members: Vec<CreatorTeamMember> = Vec::new();
            for creator_id in [pair.0, pair.1] {
                let baseline: Vec<f64> = inputs
                    .baseline_ratings
                    .get(&creator_id)
                    .into_iter()
                    .flat_map(|ratings| ratings.values().copied())
                    .collect();
                let baseline_average = (!baseline.is_empty()).then(|| round2(mean(&baseline)));
                let roles: BTreeSet<String> = issues
                    .iter()
                    .filter_map(|id| inputs.eligible_issue_creators.get(id))
                    .filter_map(|members| members.get(&creator_id))
                    .flatten()
                    .cloned()
                    .collect();
                members.push(CreatorTeamMember {
                    canonical_creator_key: format!("creator:{creator_id}"),
                    display_name: inputs
                        .display_names
                        .get(&creator_id)
                        .cloned()
                        .unwrap_or_default(),
                    roles: roles.into_iter().collect(),
                    baseline_rated_count: baseline.len() as i64,
                    difference_from_baseline: baseline_average
                        .map(|average| round2(shared_average - average)),
                    baseline_average_rating: baseline_average,
                });
            }
            let ratings: Vec<f64> = issues
                .iter()
                .filter_map(|id| library.ratings.get(id).copied())
                .collect();
            let mut series_counts: BTreeMap<i64, (String, i64)> = BTreeMap::new();
            for issue_id in issues.iter().copied() {
                if let Some(issue) = library.issue(issue_id) {
                    let entry = series_counts
                        .entry(issue.thread_id)
                        .or_insert_with(|| (issue.thread_title.clone(), 0));
                    entry.1 += 1;
                }
            }
            let mut shared_series: Vec<CreatorTeamSeriesRef> = series_counts
                .into_iter()
                .map(
                    |(thread_id, (thread_title, shared_issue_count))| CreatorTeamSeriesRef {
                        thread_id,
                        thread_title,
                        shared_issue_count,
                    },
                )
                .collect();
            shared_series.sort_by(|a, b| {
                b.shared_issue_count
                    .cmp(&a.shared_issue_count)
                    .then(
                        a.thread_title
                            .to_lowercase()
                            .cmp(&b.thread_title.to_lowercase()),
                    )
                    .then(a.thread_id.cmp(&b.thread_id))
            });
            shared_series.truncate(MAX_SHARED_SERIES);
            CreatorTeamPair {
                pair_key: format!("creator:{}|creator:{}", pair.0, pair.1),
                creators: members,
                shared_rated_issue_count: issues.len() as i64,
                shared_average_rating: Some(shared_average),
                shared_median_rating: (!ratings.is_empty()).then(|| round2(median(&ratings))),
                shared_rating_distribution: team_distribution(&ratings),
                shared_series,
                shared_issue_refs: team_issue_refs(library, issues),
                max_shared_issue_refs: MAX_ISSUE_REFS as i64,
            }
        })
        .collect();

    let rated_ids: HashSet<i64> = library.ratings.keys().copied().collect();
    let with_metadata = rated_ids
        .iter()
        .filter(|id| library.metadata_issues.contains(id))
        .count() as i64;
    CreatorTeamChemistryResponse {
        pairs,
        pairs_total: qualifying.len() as i64,
        min_shared_team_sample: MIN_SHARED_TEAM_SAMPLE as i64,
        max_ranked_pairs: MAX_RANKED_TEAM_PAIRS as i64,
        coverage: CreatorTeamCoverage {
            rated_issues_total: rated_ids.len() as i64,
            rated_issues_with_creator_metadata: with_metadata,
            ratings_complete: with_metadata >= rated_ids.len() as i64,
        },
    }
}

// ---------------------------------------------------------------------------
// Metric drilldowns
// ---------------------------------------------------------------------------

fn paginate<T: Clone>(items: &[T], page: i64, page_size: i64) -> (Vec<T>, CreatorMetricPagination) {
    let total_pages = items.len().div_ceil(page_size as usize) as i64;
    let start = ((page - 1) * page_size) as usize;
    let paged = if start >= items.len() {
        vec![]
    } else {
        items[start..(start + page_size as usize).min(items.len())].to_vec()
    };
    (
        paged,
        CreatorMetricPagination {
            page,
            page_size,
            next_page_token: (page < total_pages).then_some(page + 1),
            total_pages,
        },
    )
}

fn drilldown_issue(
    library: &CreatorLibrary,
    creator_id: i64,
    issue_id: i64,
    exclusion_reason: Option<String>,
) -> CreatorMetricIssue {
    let issue = library.issue(issue_id);
    CreatorMetricIssue {
        issue_id,
        thread_id: issue.map(|issue| issue.thread_id).unwrap_or(0),
        thread_title: issue
            .map(|issue| issue.thread_title.clone())
            .unwrap_or_default(),
        issue_number: issue
            .map(|issue| issue.issue_number.clone())
            .unwrap_or_default(),
        status: issue.map(|issue| issue.status.clone()).unwrap_or_default(),
        effective_rating: library.ratings.get(&issue_id).copied(),
        effective_rating_source: None,
        effective_rating_timestamp: library.rating_timestamps.get(&issue_id).map(iso_timestamp),
        creator_roles: roles_on_issue(library, creator_id, issue_id),
        exclusion_reason,
        missing_rating_cause: library.missing_rating_causes.get(&issue_id).cloned(),
    }
}

fn empty_calculation() -> CreatorMetricCalculation {
    CreatorMetricCalculation {
        formula: "No ratings available".to_string(),
        numerator: "No rated issues".to_string(),
        denominator: None,
        percentage: None,
    }
}

fn base_drilldown(
    metric_type: &str,
    creator_key: &str,
    calculation: CreatorMetricCalculation,
    total_count: i64,
    included: Vec<CreatorMetricIssue>,
    excluded: Vec<CreatorMetricIssue>,
    pagination: CreatorMetricPagination,
) -> CreatorMetricDrilldown {
    CreatorMetricDrilldown {
        metric_type: metric_type.to_string(),
        creator_key: creator_key.to_string(),
        calculation,
        total_count,
        included_issues: included,
        excluded_issues: excluded,
        pagination,
        rating_value: None,
        bucket_count: None,
        bucket_percentage: None,
        role: None,
        role_issue_count: None,
        role_rated_issue_count: None,
        role_average_rating: None,
        series_id: None,
        series_title: None,
        series_issue_count: None,
        series_rated_issue_count: None,
        series_average_rating: None,
    }
}

#[allow(clippy::too_many_arguments)]
fn build_drilldown(
    library: &CreatorLibrary,
    creator_id: i64,
    creator_key: &str,
    metric_type: &str,
    role: Option<&str>,
    rating_value: Option<&str>,
    series_key: Option<&str>,
    page: i64,
    page_size: i64,
) -> Result<CreatorMetricDrilldown, ApiError> {
    const VALID: &[&str] = &[
        "average-rating",
        "median-rating",
        "rated-issue-count",
        "five-star-rate",
        "rating-distribution",
        "unread-count",
        "read-unrated-count",
        "role-stats",
        "series-stats",
    ];
    if !VALID.contains(&metric_type) {
        let mut valid_types: Vec<&str> = VALID.to_vec();
        valid_types.sort_unstable();
        let valid_types = format!(
            "{{{}}}",
            valid_types
                .iter()
                .map(|value| format!("'{value}'"))
                .collect::<Vec<_>>()
                .join(", ")
        );
        return Err(bad_request(format!(
            "Invalid metric type: {metric_type}. Valid types: {valid_types}"
        )));
    }
    let Some(attribution) = attribution(library, creator_id) else {
        return Err(not_found(format!(
            "Metric {metric_type} not available for creator {creator_key}"
        )));
    };
    let all_ids: Vec<i64> = attribution.issue_ids.iter().copied().collect();
    let rated_ids: Vec<i64> = all_ids
        .iter()
        .copied()
        .filter(|id| {
            library.ratings.contains_key(id)
                && library
                    .credits
                    .get(id)
                    .into_iter()
                    .flatten()
                    .any(|credit| credit.external_id == creator_id && has_headline_role(credit))
        })
        .collect();
    let ratings: Vec<f64> = rated_ids
        .iter()
        .filter_map(|id| library.ratings.get(id).copied())
        .collect();
    let headline_exclusion = |id: i64| -> String {
        if !library.ratings.contains_key(&id) {
            "No stored effective rating".to_string()
        } else {
            "Creator only credited in a non-headline role excluded from headline stats".to_string()
        }
    };
    let non_rated: Vec<i64> = all_ids
        .iter()
        .copied()
        .filter(|id| !rated_ids.contains(id))
        .collect();

    match metric_type {
        "average-rating" => {
            if ratings.is_empty() {
                let excluded: Vec<CreatorMetricIssue> = all_ids
                    .iter()
                    .map(|id| {
                        drilldown_issue(
                            library,
                            creator_id,
                            *id,
                            Some("No stored effective rating".to_string()),
                        )
                    })
                    .collect();
                return Ok(base_drilldown(
                    metric_type,
                    creator_key,
                    empty_calculation(),
                    0,
                    vec![],
                    excluded,
                    paginate::<i64>(&[], page, page_size).1,
                ));
            }
            let points: f64 = ratings.iter().sum();
            let average = points / ratings.len() as f64;
            let calculation = CreatorMetricCalculation {
                formula: format!(
                    "{points} total rating points ÷ {} rated issues = {average:.2}★",
                    ratings.len()
                ),
                numerator: format!("{points} total rating points"),
                denominator: Some(format!("{} rated issues", ratings.len())),
                percentage: Some(format!("{average:.2}★")),
            };
            let (paged, pagination) = paginate(&rated_ids, page, page_size);
            let included = paged
                .into_iter()
                .map(|id| drilldown_issue(library, creator_id, id, None))
                .collect();
            let excluded = non_rated
                .into_iter()
                .map(|id| drilldown_issue(library, creator_id, id, Some(headline_exclusion(id))))
                .collect();
            Ok(base_drilldown(
                metric_type,
                creator_key,
                calculation,
                ratings.len() as i64,
                included,
                excluded,
                pagination,
            ))
        }
        "median-rating" => {
            if ratings.is_empty() {
                let excluded: Vec<CreatorMetricIssue> = all_ids
                    .iter()
                    .map(|id| {
                        drilldown_issue(
                            library,
                            creator_id,
                            *id,
                            Some("No stored effective rating".to_string()),
                        )
                    })
                    .collect();
                return Ok(base_drilldown(
                    metric_type,
                    creator_key,
                    empty_calculation(),
                    0,
                    vec![],
                    excluded,
                    paginate::<i64>(&[], page, page_size).1,
                ));
            }
            let mut sorted = rated_ids.clone();
            sorted.sort_by(|a, b| {
                library
                    .ratings
                    .get(a)
                    .copied()
                    .partial_cmp(&library.ratings.get(b).copied())
                    .unwrap_or(Ordering::Equal)
            });
            let count = sorted.len();
            let middle = count / 2;
            let median_value = median(&ratings);
            let observation = if count % 2 == 1 {
                let value = library.ratings[&sorted[middle]];
                format!("middle value (#{}) = {value}★", middle + 1)
            } else {
                let first = library.ratings[&sorted[middle - 1]];
                let second = library.ratings[&sorted[middle]];
                format!(
                    "middle observations (#{} and #{}) = {first}★ and {second}★, average = {median_value}★",
                    middle, middle + 1
                )
            };
            let median_ids: HashSet<i64> = if count % 2 == 1 {
                HashSet::from([sorted[middle]])
            } else {
                HashSet::from([sorted[middle - 1], sorted[middle]])
            };
            let calculation = CreatorMetricCalculation {
                formula: format!("{count} rated issues sorted by rating\n{observation}"),
                numerator: observation,
                denominator: Some(format!("{count} rated issues")),
                percentage: Some(format!("{median_value:.2}★")),
            };
            let (paged, pagination) = paginate(&sorted, page, page_size);
            let included = paged
                .into_iter()
                .map(|id| {
                    drilldown_issue(
                        library,
                        creator_id,
                        id,
                        median_ids
                            .contains(&id)
                            .then(|| "Median observation".to_string()),
                    )
                })
                .collect();
            let excluded = non_rated
                .into_iter()
                .map(|id| drilldown_issue(library, creator_id, id, Some(headline_exclusion(id))))
                .collect();
            Ok(base_drilldown(
                metric_type,
                creator_key,
                calculation,
                count as i64,
                included,
                excluded,
                pagination,
            ))
        }
        "rated-issue-count" => {
            let calculation = CreatorMetricCalculation {
                formula: format!("{} rated issues", rated_ids.len()),
                numerator: format!("{} rated issues", rated_ids.len()),
                denominator: None,
                percentage: None,
            };
            let (paged, pagination) = paginate(&rated_ids, page, page_size);
            let included = paged
                .into_iter()
                .map(|id| drilldown_issue(library, creator_id, id, None))
                .collect();
            let excluded = non_rated
                .into_iter()
                .map(|id| drilldown_issue(library, creator_id, id, Some(headline_exclusion(id))))
                .collect();
            Ok(base_drilldown(
                metric_type,
                creator_key,
                calculation,
                rated_ids.len() as i64,
                included,
                excluded,
                pagination,
            ))
        }
        "five-star-rate" => {
            if ratings.is_empty() {
                let excluded: Vec<CreatorMetricIssue> = all_ids
                    .iter()
                    .map(|id| {
                        drilldown_issue(
                            library,
                            creator_id,
                            *id,
                            Some("No stored effective rating".to_string()),
                        )
                    })
                    .collect();
                let mut result = base_drilldown(
                    metric_type,
                    creator_key,
                    empty_calculation(),
                    0,
                    vec![],
                    excluded,
                    paginate::<i64>(&[], page, page_size).1,
                );
                result.calculation.percentage = Some("0%".to_string());
                return Ok(result);
            }
            let five_star: Vec<i64> = rated_ids
                .iter()
                .copied()
                .filter(|id| library.ratings.get(id).is_some_and(|rating| *rating >= 5.0))
                .collect();
            let rate = five_star.len() as f64 / ratings.len() as f64 * 100.0;
            let calculation = CreatorMetricCalculation {
                formula: format!(
                    "{} five-star ratings ÷ {} rated issues = {rate:.1}%",
                    five_star.len(),
                    ratings.len()
                ),
                numerator: format!("{} five-star ratings", five_star.len()),
                denominator: Some(format!("{} rated issues", ratings.len())),
                percentage: Some(format!("{rate:.1}%")),
            };
            let (paged, pagination) = paginate(&five_star, page, page_size);
            let included = paged
                .into_iter()
                .map(|id| drilldown_issue(library, creator_id, id, None))
                .collect();
            let mut excluded: Vec<CreatorMetricIssue> = rated_ids
                .iter()
                .filter(|id| !five_star.contains(id))
                .map(|id| {
                    let rating = library.ratings.get(id).copied().unwrap_or(0.0);
                    drilldown_issue(
                        library,
                        creator_id,
                        *id,
                        Some(format!("Rated {rating}★, not 5★")),
                    )
                })
                .collect();
            excluded.extend(
                non_rated.into_iter().map(|id| {
                    drilldown_issue(library, creator_id, id, Some(headline_exclusion(id)))
                }),
            );
            Ok(base_drilldown(
                metric_type,
                creator_key,
                calculation,
                five_star.len() as i64,
                included,
                excluded,
                pagination,
            ))
        }
        "rating-distribution" => {
            let Some(raw_value) = rating_value else {
                return Err(bad_request(
                    "Rating value is required for rating-distribution metric type",
                ));
            };
            let Ok(target) = raw_value.parse::<f64>() else {
                return Err(bad_request(format!("Invalid rating value: {raw_value}")));
            };
            if ratings.is_empty() {
                let calculation = CreatorMetricCalculation {
                    formula: format!("0 of 0 rated issues are exactly {raw_value}★ = 0.0%"),
                    numerator: format!("0 issues with {raw_value}★ rating"),
                    denominator: Some("0 rated issues".to_string()),
                    percentage: Some("0.0%".to_string()),
                };
                let excluded: Vec<CreatorMetricIssue> = all_ids
                    .iter()
                    .map(|id| {
                        drilldown_issue(
                            library,
                            creator_id,
                            *id,
                            Some("No stored effective rating".to_string()),
                        )
                    })
                    .collect();
                let mut result = base_drilldown(
                    metric_type,
                    creator_key,
                    calculation,
                    0,
                    vec![],
                    excluded,
                    paginate::<i64>(&[], page, page_size).1,
                );
                result.rating_value = Some(raw_value.to_string());
                result.bucket_count = Some(0);
                result.bucket_percentage = Some(0.0);
                return Ok(result);
            }
            let bucket: Vec<i64> = rated_ids
                .iter()
                .copied()
                .filter(|id| {
                    library
                        .ratings
                        .get(id)
                        .is_some_and(|rating| *rating == target)
                })
                .collect();
            let percentage = bucket.len() as f64 / ratings.len() as f64 * 100.0;
            let calculation = CreatorMetricCalculation {
                formula: format!(
                    "{} of {} rated issues are exactly {raw_value}★ = {percentage:.1}%",
                    bucket.len(),
                    ratings.len()
                ),
                numerator: format!("{} issues with {raw_value}★ rating", bucket.len()),
                denominator: Some(format!("{} rated issues", ratings.len())),
                percentage: Some(format!("{percentage:.1}%")),
            };
            let (paged, pagination) = paginate(&bucket, page, page_size);
            let included = paged
                .into_iter()
                .map(|id| drilldown_issue(library, creator_id, id, None))
                .collect();
            let mut excluded: Vec<CreatorMetricIssue> = rated_ids
                .iter()
                .filter(|id| {
                    library
                        .ratings
                        .get(id)
                        .is_some_and(|rating| *rating != target)
                })
                .map(|id| {
                    drilldown_issue(
                        library,
                        creator_id,
                        *id,
                        Some(format!(
                            "Rated {}★, not {raw_value}★",
                            library.ratings.get(id).copied().unwrap_or(0.0)
                        )),
                    )
                })
                .collect();
            excluded.extend(
                non_rated.into_iter().map(|id| {
                    drilldown_issue(library, creator_id, id, Some(headline_exclusion(id)))
                }),
            );
            let mut result = base_drilldown(
                metric_type,
                creator_key,
                calculation,
                ratings.len() as i64,
                included,
                excluded,
                pagination,
            );
            result.rating_value = Some(raw_value.to_string());
            result.bucket_count = Some(bucket.len() as i64);
            result.bucket_percentage = Some(round2(percentage));
            Ok(result)
        }
        "unread-count" => {
            let unread: Vec<i64> = all_ids
                .iter()
                .copied()
                .filter(|id| {
                    library
                        .issue(*id)
                        .is_some_and(|issue| issue.status == "unread")
                })
                .collect();
            let calculation = CreatorMetricCalculation {
                formula: format!("{} unread issues attributed to this creator", unread.len()),
                numerator: format!("{} unread issues", unread.len()),
                denominator: None,
                percentage: None,
            };
            let (paged, pagination) = paginate(&unread, page, page_size);
            let included = paged
                .into_iter()
                .map(|id| drilldown_issue(library, creator_id, id, None))
                .collect();
            let excluded: Vec<CreatorMetricIssue> = all_ids
                .iter()
                .filter(|id| {
                    library
                        .issue(**id)
                        .is_some_and(|issue| issue.status == "read")
                })
                .map(|id| {
                    drilldown_issue(
                        library,
                        creator_id,
                        *id,
                        Some("Issue is marked as read".to_string()),
                    )
                })
                .collect();
            Ok(base_drilldown(
                metric_type,
                creator_key,
                calculation,
                unread.len() as i64,
                included,
                excluded,
                pagination,
            ))
        }
        "read-unrated-count" => {
            let read_unrated: Vec<i64> = all_ids
                .iter()
                .copied()
                .filter(|id| {
                    library
                        .issue(*id)
                        .is_some_and(|issue| issue.status == "read")
                        && !library.ratings.contains_key(id)
                })
                .collect();
            let calculation = CreatorMetricCalculation {
                formula: format!(
                    "{} attributed issues are marked read and have no effective rate event",
                    read_unrated.len()
                ),
                numerator: format!("{} read issues without ratings", read_unrated.len()),
                denominator: None,
                percentage: None,
            };
            let (paged, pagination) = paginate(&read_unrated, page, page_size);
            let included = paged
                .into_iter()
                .map(|id| {
                    drilldown_issue(
                        library,
                        creator_id,
                        id,
                        Some("Read but has no effective rating".to_string()),
                    )
                })
                .collect();
            let excluded: Vec<CreatorMetricIssue> = all_ids
                .iter()
                .filter(|id| {
                    library
                        .issue(**id)
                        .is_some_and(|issue| issue.status == "unread")
                        || library.ratings.contains_key(*id)
                })
                .map(|id| {
                    let reason = if library
                        .issue(*id)
                        .is_some_and(|issue| issue.status == "unread")
                    {
                        "Issue is unread"
                    } else {
                        "Issue has an effective rating"
                    };
                    drilldown_issue(library, creator_id, *id, Some(reason.to_string()))
                })
                .collect();
            Ok(base_drilldown(
                metric_type,
                creator_key,
                calculation,
                read_unrated.len() as i64,
                included,
                excluded,
                pagination,
            ))
        }
        "role-stats" => {
            let Some(role) = role else {
                return Err(bad_request("Role is required for role-stats metric type"));
            };
            let role_issues: Vec<i64> = all_ids
                .iter()
                .copied()
                .filter(|id| {
                    roles_on_issue(library, creator_id, *id)
                        .iter()
                        .any(|value| value == role)
                })
                .collect();
            if role_issues.is_empty() {
                return Err(not_found(format!(
                    "Role {role} not available for creator {creator_key}"
                )));
            }
            let role_ratings: Vec<f64> = role_issues
                .iter()
                .filter_map(|id| library.ratings.get(id).copied())
                .collect();
            let points: f64 = role_ratings.iter().sum();
            let average = (!role_ratings.is_empty()).then(|| points / role_ratings.len() as f64);
            let calculation = CreatorMetricCalculation {
                formula: if let Some(average) = average {
                    format!("{role}\n{} credited issues\n{} with effective ratings\n{points} rating points ÷ {} = {average:.2}★", role_issues.len(), role_ratings.len(), role_ratings.len())
                } else {
                    format!("{role}\n{} credited issues\n0 with effective ratings\nNo rating data available", role_issues.len())
                },
                numerator: if role_ratings.is_empty() {
                    "No rated issues".to_string()
                } else {
                    format!("{} rated issues", role_ratings.len())
                },
                denominator: Some(format!("{} total issues", role_issues.len())),
                percentage: average.map(|value| format!("{value:.2}★")),
            };
            let (paged, pagination) = paginate(&role_issues, page, page_size);
            let included = paged
                .into_iter()
                .map(|id| drilldown_issue(library, creator_id, id, None))
                .collect();
            let excluded: Vec<CreatorMetricIssue> = all_ids
                .iter()
                .filter(|id| !role_issues.contains(id))
                .map(|id| {
                    drilldown_issue(
                        library,
                        creator_id,
                        *id,
                        Some(format!("Creator not credited as {role} on this issue")),
                    )
                })
                .collect();
            let mut result = base_drilldown(
                metric_type,
                creator_key,
                calculation,
                role_issues.len() as i64,
                included,
                excluded,
                pagination,
            );
            result.role = Some(role.to_string());
            result.role_issue_count = Some(role_issues.len() as i64);
            result.role_rated_issue_count = Some(role_ratings.len() as i64);
            result.role_average_rating = average;
            Ok(result)
        }
        "series-stats" => {
            let Some(raw_key) = series_key else {
                return Err(bad_request(
                    "Series key is required for series-stats metric type",
                ));
            };
            let Some(thread_id) = parse_series_key(raw_key) else {
                return Err(bad_request(format!("Invalid series key: {raw_key}")));
            };
            let series_issues: Vec<i64> = all_ids
                .iter()
                .copied()
                .filter(|id| {
                    library
                        .issue(*id)
                        .is_some_and(|issue| issue.thread_id == thread_id)
                })
                .collect();
            if series_issues.is_empty() {
                return Err(not_found(format!(
                    "Series {raw_key} not available for creator {creator_key}"
                )));
            }
            let series_ratings: Vec<f64> = series_issues
                .iter()
                .filter_map(|id| library.ratings.get(id).copied())
                .collect();
            let points: f64 = series_ratings.iter().sum();
            let average =
                (!series_ratings.is_empty()).then(|| round2(points / series_ratings.len() as f64));
            let title = series_issues
                .iter()
                .filter_map(|id| library.issue(*id))
                .find(|issue| !issue.thread_title.is_empty())
                .map(|issue| issue.thread_title.clone())
                .unwrap_or_else(|| "Unknown Series".to_string());
            let calculation = CreatorMetricCalculation {
                formula: if let Some(average) = average {
                    format!("{title}\n{} attributed issues\n{} with effective ratings\n{points} rating points ÷ {} = {average:.2}★", series_issues.len(), series_ratings.len(), series_ratings.len())
                } else {
                    format!("{title}\n{} attributed issues\n0 with effective ratings\nNo rating data available", series_issues.len())
                },
                numerator: if series_ratings.is_empty() {
                    "No rated issues".to_string()
                } else {
                    format!("{} rated issues", series_ratings.len())
                },
                denominator: Some(format!("{} total issues", series_issues.len())),
                percentage: average.map(|value| format!("{value:.2}★")),
            };
            let (paged, pagination) = paginate(&series_issues, page, page_size);
            let included = paged
                .into_iter()
                .map(|id| drilldown_issue(library, creator_id, id, None))
                .collect();
            let excluded: Vec<CreatorMetricIssue> = all_ids
                .iter()
                .filter(|id| !series_issues.contains(id))
                .map(|id| {
                    drilldown_issue(
                        library,
                        creator_id,
                        *id,
                        Some(format!("Issue not part of {title}")),
                    )
                })
                .collect();
            let mut result = base_drilldown(
                metric_type,
                creator_key,
                calculation,
                series_issues.len() as i64,
                included,
                excluded,
                pagination,
            );
            result.series_id = Some(thread_id);
            result.series_title = Some(title);
            result.series_issue_count = Some(series_issues.len() as i64);
            result.series_rated_issue_count = Some(series_ratings.len() as i64);
            result.series_average_rating = average;
            Ok(result)
        }
        _ => unreachable!("validated above"),
    }
}

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

fn validation_failed() -> ApiError {
    ApiError::Unprocessable("Validation failed".into())
}

fn page_params(
    limit: Option<i64>,
    offset: Option<i64>,
    default_limit: i64,
    max_limit: i64,
) -> Result<(usize, usize), ApiError> {
    let limit = limit.unwrap_or(default_limit);
    if !(1..=max_limit).contains(&limit) {
        return Err(validation_failed());
    }
    let offset = offset.unwrap_or(0);
    if offset < 0 {
        return Err(validation_failed());
    }
    Ok((limit as usize, offset as usize))
}

fn summary_ids(keys: &[String]) -> Vec<i64> {
    keys.iter()
        .filter_map(|key| parse_creator_key(key))
        .collect()
}

fn drilldown_page(page: Option<i64>, page_size: Option<i64>) -> Result<(i64, i64), ApiError> {
    let page = page.unwrap_or(1);
    let page_size = page_size.unwrap_or(50);
    if page < 1 || !(1..=200).contains(&page_size) {
        return Err(validation_failed());
    }
    Ok((page, page_size))
}

pub async fn list_creators(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
    query: Result<Query<CreatorListQuery>, QueryRejection>,
) -> Result<Json<CreatorListResponse>, ApiError> {
    let Query(query) = query.map_err(|_| validation_failed())?;
    let user_id = resolve_user_id(&state, &claims).await?;
    let (limit, offset) = page_params(query.limit, query.offset, 20, 50)?;
    let min_ratings = query.min_ratings.unwrap_or(0).max(0);
    let sort = query.sort.unwrap_or_else(|| "name".to_string());
    let search = query
        .search
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .map(|value| {
            if value.chars().count() > 100 {
                value.chars().take(100).collect()
            } else {
                value
            }
        });
    let library = load_library(&state, user_id, LibraryScope::Full, false).await?;
    Ok(Json(build_list(
        &library,
        search.as_deref(),
        &sort,
        limit,
        offset,
        min_ratings as usize,
    )))
}

pub async fn get_summaries(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
    query: Result<Query<CreatorKeysQuery>, QueryRejection>,
) -> Result<Json<CreatorSummariesResponse>, ApiError> {
    let Query(query) = query.map_err(|_| validation_failed())?;
    let keys = validate_summary_keys(query.keys.as_deref())?;
    let user_id = resolve_user_id(&state, &claims).await?;
    let library = load_library(
        &state,
        user_id,
        LibraryScope::Creators(summary_ids(&keys)),
        false,
    )
    .await?;
    Ok(Json(build_summaries(&library, &keys)))
}

pub async fn get_detail(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
    Path(creator_key): Path<String>,
    query: Result<Query<CreatorPageQuery>, QueryRejection>,
) -> Result<Json<CreatorDetailResponse>, ApiError> {
    let Query(query) = query.map_err(|_| validation_failed())?;
    let Some(creator_id) = parse_creator_key(&creator_key) else {
        return Err(bad_request("Invalid creator key format"));
    };
    let (limit, offset) = page_params(query.limit, query.offset, 50, 100)?;
    let user_id = resolve_user_id(&state, &claims).await?;
    let library = load_library(
        &state,
        user_id,
        LibraryScope::Creators(vec![creator_id]),
        false,
    )
    .await?;
    let owner = attribution(&library, creator_id)
        .ok_or_else(|| not_found(format!("Creator {creator_key} not found in your library")))?;
    Ok(Json(build_detail(
        &library,
        &creator_key,
        creator_id,
        &owner,
        limit,
        offset,
    )))
}

pub async fn get_series_issues(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
    Path((creator_key, series_key)): Path<(String, String)>,
    query: Result<Query<CreatorSeriesIssuesQuery>, QueryRejection>,
) -> Result<Json<CreatorSeriesIssueListResponse>, ApiError> {
    let Query(query) = query.map_err(|_| validation_failed())?;
    let Some(creator_id) = parse_creator_key(&creator_key) else {
        return Err(bad_request("Invalid creator key format"));
    };
    let Some(thread_id) = parse_series_key(&series_key) else {
        return Err(bad_request("Invalid series key format"));
    };
    let (limit, offset) = page_params(query.limit, query.offset, 50, 100)?;
    let user_id = resolve_user_id(&state, &claims).await?;
    let library = load_library(
        &state,
        user_id,
        LibraryScope::Creators(vec![creator_id]),
        false,
    )
    .await?;
    if attribution(&library, creator_id).is_none() {
        return Err(not_found(format!(
            "Creator {creator_key} not found in your library"
        )));
    }
    let response = build_series_issues(&library, creator_id, thread_id, limit, offset)
        .ok_or_else(|| not_found(format!("Series {series_key} not found in your library")))?;
    Ok(Json(response))
}

pub async fn get_comparison(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
    query: Result<Query<CreatorKeysQuery>, QueryRejection>,
) -> Result<Json<CreatorComparisonResponse>, ApiError> {
    let Query(query) = query.map_err(|_| validation_failed())?;
    let keys = validate_comparison_keys(query.keys.as_deref())?;
    let user_id = resolve_user_id(&state, &claims).await?;
    let library = load_library(
        &state,
        user_id,
        LibraryScope::Creators(summary_ids(&keys)),
        false,
    )
    .await?;
    Ok(Json(build_comparison(&library, &keys)))
}

pub async fn get_discoveries(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
) -> Result<Json<CreatorDiscoveryResponse>, ApiError> {
    let user_id = resolve_user_id(&state, &claims).await?;
    let library = load_library(&state, user_id, LibraryScope::Full, false).await?;
    Ok(Json(build_discoveries(&library)))
}

pub async fn get_team_chemistry(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
) -> Result<Json<CreatorTeamChemistryResponse>, ApiError> {
    let user_id = resolve_user_id(&state, &claims).await?;
    let library = load_library(&state, user_id, LibraryScope::Full, false).await?;
    Ok(Json(build_team_chemistry(&library)))
}

pub async fn get_metric_drilldown(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
    Path((creator_key, metric_type)): Path<(String, String)>,
    query: Result<Query<CreatorMetricQuery>, QueryRejection>,
) -> Result<Json<CreatorMetricDrilldown>, ApiError> {
    let Query(query) = query.map_err(|_| validation_failed())?;
    let Some(creator_id) = parse_creator_key(&creator_key) else {
        return Err(bad_request(format!(
            "Invalid creator key format: {creator_key}"
        )));
    };
    let (page, page_size) = drilldown_page(query.page, query.page_size)?;
    let user_id = resolve_user_id(&state, &claims).await?;
    let library = load_library(
        &state,
        user_id,
        LibraryScope::Creators(vec![creator_id]),
        true,
    )
    .await?;
    let result = build_drilldown(
        &library,
        creator_id,
        &creator_key,
        &metric_type,
        query.role.as_deref(),
        query.rating_value.as_deref(),
        query.series_key.as_deref(),
        page,
        page_size,
    )?;
    Ok(Json(result))
}

pub async fn get_rating_distribution_drilldown(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
    Path((creator_key, rating_value)): Path<(String, String)>,
    query: Result<Query<CreatorMetricPageQuery>, QueryRejection>,
) -> Result<Json<CreatorMetricDrilldown>, ApiError> {
    let Query(query) = query.map_err(|_| validation_failed())?;
    let Some(creator_id) = parse_creator_key(&creator_key) else {
        return Err(bad_request(format!(
            "Invalid creator key format: {creator_key}"
        )));
    };
    let (page, page_size) = drilldown_page(query.page, query.page_size)?;
    let user_id = resolve_user_id(&state, &claims).await?;
    let library = load_library(
        &state,
        user_id,
        LibraryScope::Creators(vec![creator_id]),
        true,
    )
    .await?;
    let result = build_drilldown(
        &library,
        creator_id,
        &creator_key,
        "rating-distribution",
        None,
        Some(&rating_value),
        None,
        page,
        page_size,
    )
    .map_err(|error| {
        if error.status() == StatusCode::NOT_FOUND {
            not_found(format!(
                "Rating distribution {rating_value} not available for creator {creator_key}"
            ))
        } else {
            error
        }
    })?;
    Ok(Json(result))
}

pub async fn get_role_drilldown(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
    Path((creator_key, role)): Path<(String, String)>,
    query: Result<Query<CreatorMetricPageQuery>, QueryRejection>,
) -> Result<Json<CreatorMetricDrilldown>, ApiError> {
    let Query(query) = query.map_err(|_| validation_failed())?;
    let Some(creator_id) = parse_creator_key(&creator_key) else {
        return Err(bad_request(format!(
            "Invalid creator key format: {creator_key}"
        )));
    };
    let (page, page_size) = drilldown_page(query.page, query.page_size)?;
    let user_id = resolve_user_id(&state, &claims).await?;
    let library = load_library(
        &state,
        user_id,
        LibraryScope::Creators(vec![creator_id]),
        true,
    )
    .await?;
    let result = build_drilldown(
        &library,
        creator_id,
        &creator_key,
        "role-stats",
        Some(&role),
        None,
        None,
        page,
        page_size,
    )
    .map_err(|error| {
        if error.status() == StatusCode::NOT_FOUND {
            not_found(format!(
                "Role {role} not available for creator {creator_key}"
            ))
        } else {
            error
        }
    })?;
    Ok(Json(result))
}

pub async fn get_series_drilldown(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
    Path((creator_key, series_key)): Path<(String, String)>,
    query: Result<Query<CreatorMetricPageQuery>, QueryRejection>,
) -> Result<Json<CreatorMetricDrilldown>, ApiError> {
    let Query(query) = query.map_err(|_| validation_failed())?;
    let Some(creator_id) = parse_creator_key(&creator_key) else {
        return Err(bad_request(format!(
            "Invalid creator key format: {creator_key}"
        )));
    };
    let (page, page_size) = drilldown_page(query.page, query.page_size)?;
    let user_id = resolve_user_id(&state, &claims).await?;
    let library = load_library(
        &state,
        user_id,
        LibraryScope::Creators(vec![creator_id]),
        true,
    )
    .await?;
    let result = build_drilldown(
        &library,
        creator_id,
        &creator_key,
        "series-stats",
        None,
        None,
        Some(&series_key),
        page,
        page_size,
    )
    .map_err(|error| {
        if error.status() == StatusCode::NOT_FOUND {
            not_found(format!(
                "Series {series_key} not available for creator {creator_key}"
            ))
        } else {
            error
        }
    })?;
    Ok(Json(result))
}

// ---------------------------------------------------------------------------
// OpenAPI documentation-only operations (registered in openapi.rs)
// ---------------------------------------------------------------------------

#[utoipa::path(get, path = "/api/v2/creators", tag = "creators",
    operation_id = "creators_list",
    params(CreatorListQuery),
    responses((status = 200, description = "Creator list", body = CreatorListResponse),
        (status = 422, description = "Invalid filters"),
        (status = 401, description = "Not authenticated")),
    security(("HTTPBearer" = [])))]
pub fn list_documentation() {}

#[utoipa::path(get, path = "/api/v2/creators/summaries", tag = "creators",
    params(CreatorKeysQuery),
    responses((status = 200, description = "Creator summaries", body = CreatorSummariesResponse),
        (status = 400, description = "Invalid creator keys"),
        (status = 401, description = "Not authenticated")),
    security(("HTTPBearer" = [])))]
pub fn summaries_documentation() {}

#[utoipa::path(get, path = "/api/v2/creators/compare", tag = "creators",
    params(CreatorKeysQuery),
    responses((status = 200, description = "Creator comparison", body = CreatorComparisonResponse),
        (status = 400, description = "Invalid creator keys"),
        (status = 401, description = "Not authenticated")),
    security(("HTTPBearer" = [])))]
pub fn compare_documentation() {}

#[utoipa::path(get, path = "/api/v2/creators/discoveries", tag = "creators",
    responses((status = 200, description = "Creator discoveries", body = CreatorDiscoveryResponse),
        (status = 401, description = "Not authenticated")),
    security(("HTTPBearer" = [])))]
pub fn discoveries_documentation() {}

#[utoipa::path(get, path = "/api/v2/creators/team-chemistry", tag = "creators",
    responses((status = 200, description = "Creator team chemistry", body = CreatorTeamChemistryResponse),
        (status = 401, description = "Not authenticated")),
    security(("HTTPBearer" = [])))]
pub fn team_chemistry_documentation() {}

#[utoipa::path(get, path = "/api/v2/creators/{creator_key}", tag = "creators",
    params(
        ("creator_key" = String, Path, description = "Canonical creator key"),
        CreatorPageQuery
    ),
    responses((status = 200, description = "Creator detail", body = CreatorDetailResponse),
        (status = 400, description = "Invalid key"),
        (status = 404, description = "Creator not found"),
        (status = 401, description = "Not authenticated")),
    security(("HTTPBearer" = [])))]
pub fn detail_documentation() {}

#[utoipa::path(get, path = "/api/v2/creators/{creator_key}/series/{series_key}/issues", tag = "creators",
    params(
        ("creator_key" = String, Path, description = "Canonical creator key"),
        ("series_key" = String, Path, description = "Series key"),
        CreatorSeriesIssuesQuery
    ),
    responses((status = 200, description = "Creator series issues", body = CreatorSeriesIssueListResponse),
        (status = 400, description = "Invalid keys"),
        (status = 404, description = "Series not found"),
        (status = 401, description = "Not authenticated")),
    security(("HTTPBearer" = [])))]
pub fn series_issues_documentation() {}

#[utoipa::path(get, path = "/api/v2/creators/{creator_key}/metrics/{metric_type}", tag = "creators",
    params(
        ("creator_key" = String, Path, description = "Canonical creator key"),
        ("metric_type" = String, Path, description = "Metric type"),
        CreatorMetricQuery
    ),
    responses((status = 200, description = "Creator metric drilldown", body = CreatorMetricDrilldown),
        (status = 400, description = "Invalid metric"),
        (status = 404, description = "Metric not available"),
        (status = 401, description = "Not authenticated")),
    security(("HTTPBearer" = [])))]
pub fn metric_documentation() {}

#[utoipa::path(get, path = "/api/v2/creators/{creator_key}/metrics/rating-distribution/{rating_value}", tag = "creators",
    params(
        ("creator_key" = String, Path, description = "Canonical creator key"),
        ("rating_value" = String, Path, description = "Rating value"),
        CreatorMetricPageQuery
    ),
    responses((status = 200, description = "Rating distribution drilldown", body = CreatorMetricDrilldown),
        (status = 400, description = "Invalid value"),
        (status = 404, description = "Not available"),
        (status = 401, description = "Not authenticated")),
    security(("HTTPBearer" = [])))]
pub fn rating_distribution_documentation() {}

#[utoipa::path(get, path = "/api/v2/creators/{creator_key}/metrics/role-stats/{role}", tag = "creators",
    params(
        ("creator_key" = String, Path, description = "Canonical creator key"),
        ("role" = String, Path, description = "Creator role"),
        CreatorMetricPageQuery
    ),
    responses((status = 200, description = "Role drilldown", body = CreatorMetricDrilldown),
        (status = 400, description = "Invalid role"),
        (status = 404, description = "Not available"),
        (status = 401, description = "Not authenticated")),
    security(("HTTPBearer" = [])))]
pub fn role_documentation() {}

#[utoipa::path(get, path = "/api/v2/creators/{creator_key}/metrics/series-stats/{series_key}", tag = "creators",
    params(
        ("creator_key" = String, Path, description = "Canonical creator key"),
        ("series_key" = String, Path, description = "Series key"),
        CreatorMetricPageQuery
    ),
    responses((status = 200, description = "Series drilldown", body = CreatorMetricDrilldown),
        (status = 400, description = "Invalid series"),
        (status = 404, description = "Not available"),
        (status = 401, description = "Not authenticated")),
    security(("HTTPBearer" = [])))]
pub fn series_documentation() {}

// ---------------------------------------------------------------------------
// Focused unit tests for the pure, wire-shaping analytics
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn credit(external_id: i64, role: &str, name: &str) -> CreatorCredit {
        CreatorCredit {
            external_id,
            roles: vec![role.to_string()],
            display_name: name.to_string(),
        }
    }

    fn fixture_library() -> CreatorLibrary {
        let issues = vec![
            OwnedIssue {
                id: 1,
                status: "read".into(),
                thread_id: 10,
                thread_title: "Series A".into(),
                issue_number: "1".into(),
                queue_position: 1,
                position: 1,
            },
            OwnedIssue {
                id: 2,
                status: "read".into(),
                thread_id: 10,
                thread_title: "Series A".into(),
                issue_number: "2".into(),
                queue_position: 1,
                position: 2,
            },
            OwnedIssue {
                id: 3,
                status: "read".into(),
                thread_id: 11,
                thread_title: "Series B".into(),
                issue_number: "1".into(),
                queue_position: 2,
                position: 1,
            },
            OwnedIssue {
                id: 4,
                status: "read".into(),
                thread_id: 11,
                thread_title: "Series B".into(),
                issue_number: "2".into(),
                queue_position: 2,
                position: 2,
            },
            OwnedIssue {
                id: 5,
                status: "unread".into(),
                thread_id: 12,
                thread_title: "Series C".into(),
                issue_number: "1".into(),
                queue_position: 3,
                position: 1,
            },
        ];
        let issue_index = issues
            .iter()
            .enumerate()
            .map(|(index, issue)| (issue.id, index))
            .collect();
        let credits = HashMap::from([
            (
                1,
                vec![
                    credit(7, "writer", "Writer Seven"),
                    credit(12, "penciler", "Penciler Twelve"),
                ],
            ),
            (2, vec![credit(7, "writer", "Writer Seven")]),
            (
                3,
                vec![
                    credit(7, "writer", "Writer Seven"),
                    credit(12, "penciler", "Penciler Twelve"),
                ],
            ),
            (4, vec![credit(7, "writer", "Writer Seven")]),
            (5, vec![credit(7, "writer", "Writer Seven")]),
        ]);
        let ratings = HashMap::from([(1, 4.0), (2, 5.0), (3, 3.0)]);
        let rating_timestamps = HashMap::from([
            (1, Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap()),
            (2, Utc.with_ymd_and_hms(2026, 2, 1, 0, 0, 0).unwrap()),
            (3, Utc.with_ymd_and_hms(2026, 3, 1, 0, 0, 0).unwrap()),
        ]);
        let metadata_issues = HashSet::from([1, 2, 3, 4, 5]);
        CreatorLibrary {
            issues,
            issue_index,
            credits,
            ratings,
            rating_timestamps,
            metadata_issues,
            missing_rating_causes: HashMap::new(),
            coverage_override: None,
        }
    }

    #[test]
    fn creator_and_series_keys_follow_the_python_contract() {
        assert_eq!(parse_creator_key("creator:117106"), Some(117106));
        assert_eq!(parse_creator_key("creator:007"), Some(7));
        assert_eq!(parse_creator_key("creator:abc"), None);
        assert_eq!(parse_creator_key("creator:1:2"), None);
        assert_eq!(parse_series_key("thread:10"), Some(10));
        assert_eq!(parse_series_key("creator:10"), None);
        assert_eq!(parse_series_key("thread:"), None);
    }

    /// Golden table measured from CPython 3.13 `round(value, places)`.
    #[test]
    fn rounding_matches_python_round_golden_table() {
        let golden: [(f64, i32, f64); 22] = [
            (83.5 / 20.0, 2, 4.17),
            (4.175, 2, 4.17),
            (0.125, 2, 0.12),
            (0.135, 2, 0.14),
            (2.675, 2, 2.67),
            (1.005, 2, 1.0),
            (2.5, 0, 2.0),
            (3.5, 0, 4.0),
            (0.5, 0, 0.0),
            (1.5, 0, 2.0),
            (8.345, 2, 8.35),
            (0.0005, 3, 0.001),
            (0.0015, 3, 0.002),
            (0.0025, 3, 0.003),
            (2.0 / 3.0, 3, 0.667),
            (1.0 / 3.0, 2, 0.33),
            (4.5, 0, 4.0),
            (1.23456, 2, 1.23),
            (0.875, 2, 0.88),
            (0.285, 2, 0.28),
            (1.115, 2, 1.11),
            (4.125, 2, 4.12),
        ];
        for (value, places, expected) in golden {
            assert_eq!(
                round_half_even(value, places),
                expected,
                "round({value:?}, {places})"
            );
        }
        assert_eq!(round2(0.625), 0.62);
        assert_eq!(round3(5.0 / 6.0), 0.833);
        assert_eq!(round2(4.0), 4.0);
        assert_eq!(median(&[3.0, 4.0, 5.0]), 4.0);
        assert_eq!(median(&[3.0, 5.0]), 4.0);
    }

    #[test]
    fn discovery_trend_counts_only_headline_eligible_credits() {
        let mut library = fixture_library();
        let creator_id = 7;
        let issue_ids: Vec<i64> = library
            .credits
            .iter()
            .filter(|(_, credits)| credits.iter().any(|c| c.external_id == creator_id))
            .map(|(id, _)| *id)
            .collect();
        assert!(!issue_ids.is_empty());
        let stamp = Utc::now();
        for id in &issue_ids {
            library.ratings.insert(*id, 4.0);
            library.rating_timestamps.insert(*id, stamp);
            for credit in library.credits.get_mut(id).unwrap() {
                if credit.external_id == creator_id {
                    credit.roles = vec!["cover".to_string()];
                }
            }
        }
        let profile = discovery_profile(&library, creator_id).expect("profile");
        assert!(profile.trend_points.is_empty());
        assert_eq!(profile.rated_issue_count, 0);
        for id in &issue_ids {
            for credit in library.credits.get_mut(id).unwrap() {
                if credit.external_id == creator_id {
                    credit.roles = vec!["writer".to_string()];
                }
            }
        }
        let profile = discovery_profile(&library, creator_id).expect("profile");
        assert_eq!(profile.trend_points.len(), issue_ids.len());
        assert_eq!(profile.rated_issue_count as usize, issue_ids.len());
    }

    #[test]
    fn rating_distribution_exposes_every_bucket_and_rounded_statistics() {
        let distribution = rating_distribution(&[4.0, 5.0, 3.0]).expect("rated sample");
        assert_eq!(distribution.sample_count, 3);
        assert_eq!(distribution.buckets.len(), 10);
        assert_eq!(distribution.mean_rating, 4.0);
        assert_eq!(distribution.median_rating, 4.0);
        assert_eq!(distribution.min_rating, 3.0);
        assert_eq!(distribution.max_rating, 5.0);
        let filled: Vec<(f64, i64)> = distribution
            .buckets
            .iter()
            .filter(|bucket| bucket.count > 0)
            .map(|bucket| (bucket.rating, bucket.count))
            .collect();
        assert_eq!(filled, vec![(3.0, 1), (4.0, 1), (5.0, 1)]);
        assert!(rating_distribution(&[]).is_none());
        assert_eq!(distribution_key(4.0), "4");
        assert_eq!(distribution_key(3.5), "3.5");
    }

    #[test]
    fn detail_preserves_headline_population_coverage_and_pagination() {
        let library = fixture_library();
        let detail = build_detail(
            &library,
            "creator:7",
            7,
            &attribution(&library, 7).unwrap(),
            50,
            0,
        );
        assert_eq!(detail.summary.ratings_count, 3);
        assert_eq!(detail.summary.average_rating, Some(4.0));
        assert_eq!(detail.summary.read_unrated_count, 1);
        assert_eq!(detail.summary.upcoming_count, 1);
        assert_eq!(detail.coverage.rated_issues_total, 3);
        assert_eq!(detail.rated_issues.len(), 3);
        assert_eq!(detail.rated_issues[0].issue_id, 3);
        assert_eq!(
            detail.headline_roles,
            vec!["artist", "colorist", "inker", "letterer", "penciler", "writer"]
        );
        assert_eq!(detail.series_groups_total, 2);
        assert_eq!(detail.series_groups[0].thread_id, 10);
        assert_eq!(detail.series_groups[0].sort_key, "000000000010");
        assert_eq!(
            detail.series_groups[0].population_scope,
            "all_verified_credits"
        );
        assert_eq!(detail.rated_population_scope, "headline_roles_only");
        assert_eq!(detail.next_cursor, None);
        let insights = detail.insights.expect("insights");
        assert_eq!(insights.individual_issue_limit, 3);
        assert_eq!(insights.highest_rated_issues[0].issue_id, 2);
        assert!(insights.series_message.is_some());
        let page = build_detail(
            &library,
            "creator:7",
            7,
            &attribution(&library, 7).unwrap(),
            1,
            0,
        );
        assert_eq!(page.next_cursor, Some("1".to_string()));
    }

    #[test]
    fn series_issue_drilldown_reports_all_verified_credit_population() {
        let library = fixture_library();
        let response = build_series_issues(&library, 7, 10, 50, 0).expect("series");
        assert_eq!(response.series_key, "thread:10");
        assert_eq!(response.rated_issue_count, 2);
        assert_eq!(response.total, 2);
        assert_eq!(response.population_scope, "all_verified_credits");
        assert_eq!(
            response
                .issues
                .iter()
                .map(|row| row.issue_id)
                .collect::<Vec<_>>(),
            vec![2, 1]
        );
        assert!(build_series_issues(&library, 7, 999, 50, 0).is_none());
    }

    #[test]
    fn list_summaries_and_comparison_share_one_owner_scope() {
        let library = fixture_library();
        let list = build_list(&library, None, "name", 20, 0, 0);
        assert_eq!(list.total, 2);
        assert!(list
            .items
            .iter()
            .any(|item| item.canonical_creator_key == "creator:7"));
        let filtered = build_list(&library, Some("Penciler"), "ratings_count", 20, 0, 2);
        assert_eq!(filtered.total, 1);
        assert_eq!(filtered.items[0].canonical_creator_key, "creator:12");
        let summaries = build_summaries(
            &library,
            &["creator:7".to_string(), "creator:999".to_string()],
        );
        assert_eq!(summaries.summaries.len(), 1);
        assert_eq!(summaries.summaries["creator:7"].ratings_count, 3);
        let comparison = build_comparison(
            &library,
            &["creator:7".to_string(), "creator:12".to_string()],
        );
        assert_eq!(
            comparison.comparisons["creator:7"].average_rating,
            Some(4.0)
        );
        assert_eq!(comparison.comparisons["creator:7"].median_rating, Some(4.0));
        assert_eq!(
            comparison.comparisons["creator:7"].rating_distribution["4"],
            1
        );
        assert_eq!(comparison.comparisons["creator:12"].ratings_count, 2);
        assert_eq!(
            comparison.insufficient_data_keys,
            vec!["creator:7", "creator:12"]
        );
        assert_eq!(comparison.coverage.rated_issues_total, 3);
    }

    #[test]
    fn discovery_and_team_chemistry_are_bounded_and_deterministic() {
        let library = fixture_library();
        let discoveries = build_discoveries(&library);
        assert_eq!(discoveries.views.len(), 7);
        assert_eq!(discoveries.minimum_reliable_sample, 5);
        assert_eq!(discoveries.max_entries_per_view, 10);
        let most_read = discoveries
            .views
            .iter()
            .find(|view| view.mode == "most_read")
            .expect("view");
        assert_eq!(most_read.entries[0].canonical_creator_key, "creator:7");
        let loved_unread = discoveries
            .views
            .iter()
            .find(|view| view.mode == "loved_with_unread")
            .expect("view");
        assert_eq!(loved_unread.entries[0].canonical_creator_key, "creator:7");
        // Two shared rated issues are below the three-issue ranking floor.
        let team = build_team_chemistry(&library);
        assert!(team.pairs.is_empty());
        assert_eq!(team.pairs_total, 0);
        // A third shared rated issue promotes the pair.
        let mut team_library = fixture_library();
        team_library.issues.push(OwnedIssue {
            id: 6,
            status: "read".into(),
            thread_id: 13,
            thread_title: "Series D".into(),
            issue_number: "1".into(),
            queue_position: 4,
            position: 1,
        });
        team_library.issue_index.insert(6, 5);
        team_library.credits.insert(
            6,
            vec![
                credit(7, "writer", "Writer Seven"),
                credit(12, "penciler", "Penciler Twelve"),
            ],
        );
        team_library.ratings.insert(6, 4.5);
        team_library.metadata_issues.insert(6);
        let team = build_team_chemistry(&team_library);
        assert_eq!(team.pairs_total, 1);
        assert_eq!(team.pairs[0].pair_key, "creator:7|creator:12");
        assert_eq!(team.pairs[0].shared_rated_issue_count, 3);
        assert_eq!(team.min_shared_team_sample, 3);
        assert_eq!(team.max_ranked_pairs, 10);
    }

    #[test]
    fn metric_drilldowns_preserve_calculation_and_pagination_semantics() {
        let library = fixture_library();
        let average = build_drilldown(
            &library,
            7,
            "creator:7",
            "average-rating",
            None,
            None,
            None,
            1,
            50,
        )
        .expect("average");
        assert_eq!(average.total_count, 3);
        assert_eq!(
            average.calculation.formula,
            "12 total rating points ÷ 3 rated issues = 4.00★"
        );
        assert!(average.calculation.percentage.is_some());
        let median = build_drilldown(
            &library,
            7,
            "creator:7",
            "median-rating",
            None,
            None,
            None,
            1,
            50,
        )
        .expect("median");
        assert_eq!(
            median.calculation.formula,
            "3 rated issues sorted by rating\nmiddle value (#2) = 4★"
        );
        assert_eq!(
            median
                .included_issues
                .iter()
                .filter(|row| row.exclusion_reason.as_deref() == Some("Median observation"))
                .count(),
            1
        );
        let five_star = build_drilldown(
            &library,
            7,
            "creator:7",
            "five-star-rate",
            None,
            None,
            None,
            1,
            50,
        )
        .expect("five star");
        assert_eq!(five_star.total_count, 1);
        assert_eq!(
            five_star.calculation.formula,
            "1 five-star ratings ÷ 3 rated issues = 33.3%"
        );
        let distribution = build_drilldown(
            &library,
            7,
            "creator:7",
            "rating-distribution",
            None,
            Some("4.0"),
            None,
            1,
            50,
        )
        .expect("distribution");
        assert_eq!(distribution.rating_value.as_deref(), Some("4.0"));
        assert_eq!(distribution.bucket_count, Some(1));
        assert_eq!(distribution.bucket_percentage, Some(33.33));
        let unread = build_drilldown(
            &library,
            7,
            "creator:7",
            "unread-count",
            None,
            None,
            None,
            1,
            50,
        )
        .expect("unread");
        assert_eq!(unread.total_count, 1);
        let role = build_drilldown(
            &library,
            7,
            "creator:7",
            "role-stats",
            Some("writer"),
            None,
            None,
            1,
            50,
        )
        .expect("role");
        assert_eq!(role.role_issue_count, Some(5));
        assert_eq!(role.role_rated_issue_count, Some(3));
        let series = build_drilldown(
            &library,
            7,
            "creator:7",
            "series-stats",
            None,
            None,
            Some("thread:10"),
            1,
            50,
        )
        .expect("series");
        assert_eq!(series.series_issue_count, Some(2));
        assert_eq!(series.series_title.as_deref(), Some("Series A"));
        let second_page = build_drilldown(
            &library,
            7,
            "creator:7",
            "average-rating",
            None,
            None,
            None,
            2,
            1,
        )
        .expect("paged");
        assert_eq!(second_page.pagination.total_pages, 3);
        assert_eq!(second_page.pagination.next_page_token, Some(3));
        assert!(build_drilldown(
            &library,
            7,
            "creator:7",
            "not-a-metric",
            None,
            None,
            None,
            1,
            50
        )
        .is_err());
    }

    #[test]
    fn validation_errors_use_the_python_contract() {
        assert_eq!(
            validate_comparison_keys(Some("creator:7"))
                .unwrap_err()
                .status(),
            StatusCode::BAD_REQUEST
        );
        assert_eq!(
            validate_summary_keys(Some("creator:not-a-number"))
                .unwrap_err()
                .status(),
            StatusCode::BAD_REQUEST
        );
        assert_eq!(
            build_drilldown(
                &library_fixture_without_creator(),
                7,
                "creator:7",
                "average-rating",
                None,
                None,
                None,
                1,
                50
            )
            .unwrap_err()
            .status(),
            StatusCode::NOT_FOUND
        );
        assert_eq!(
            page_params(Some(0), None, 20, 50).unwrap_err().detail(),
            "Validation failed"
        );
        assert_eq!(
            page_params(None, Some(-1), 20, 50).unwrap_err().detail(),
            "Validation failed"
        );
        assert_eq!(
            drilldown_page(Some(0), None).unwrap_err().detail(),
            "Validation failed"
        );
        assert_eq!(
            drilldown_page(Some(1), Some(201)).unwrap_err().detail(),
            "Validation failed"
        );
    }

    fn library_fixture_without_creator() -> CreatorLibrary {
        let mut library = fixture_library();
        library.credits.clear();
        library
    }
}
