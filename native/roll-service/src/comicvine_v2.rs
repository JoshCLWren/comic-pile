//! Canonical native v2 ComicVine identity/resolution endpoints (#4835).
//!
//! This module is the Rust v2 replacement for the browser-called
//! `/api/v1/comicvine/*` operations. The frontend calls the v2 paths below;
//! the wire contract (field names, optionality, colon-action suffixes, status
//! codes and error envelopes) mirrors the retired Python handler exactly.
//!
//! Every mutation is owner-scoped and runs in one database transaction. No
//! Python enrichment hop is involved: provider reads go directly to ComicVine
//! with the shared credential and all persistence is executed here.

use crate::{
    auth::AuthenticatedUser,
    comicvine_repair::{provider_issue, provider_response, ProviderFailure},
    db,
    ApiError, AppState,
};
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{collections::HashMap, sync::Arc};
use tokio_postgres::{Row, Transaction};

// ---------------------------------------------------------------------------
// Wire contract (mirrors app/schemas/comicvine_resolution.py).
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ComicVineSeriesResult {
    pub comicvine_volume_id: i32,
    pub name: String,
    pub publisher: Option<String>,
    pub start_year: Option<i32>,
    pub issue_count: Option<i32>,
    pub site_detail_url: Option<String>,
    pub image_url: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ComicVineSeriesSearchResponse {
    pub query: String,
    pub results: Vec<ComicVineSeriesResult>,
    pub total_available: Option<i32>,
    pub offset: i32,
    pub limit: i32,
    pub has_more: bool,
    pub next_offset: Option<i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ComicVineResolvedIssue {
    pub comicvine_issue_id: i32,
    pub series_name: Option<String>,
    pub volume_id: Option<i32>,
    pub issue_number: Option<String>,
    pub name: Option<String>,
    pub cover_date: Option<String>,
    pub store_date: Option<String>,
    pub image_url: Option<String>,
    pub site_detail_url: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ComicVineIssueCandidate {
    pub comicvine_issue_id: i32,
    pub issue_number: Option<String>,
    pub name: Option<String>,
    pub cover_date: Option<String>,
    pub store_date: Option<String>,
    pub image_url: Option<String>,
    pub site_detail_url: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ComicVineResolveResponse {
    pub input: String,
    pub kind: String,
    pub validation_error: Option<String>,
    pub issue: Option<ComicVineResolvedIssue>,
    pub volume: Option<ComicVineSeriesResult>,
    pub issues: Vec<ComicVineIssueCandidate>,
}

impl ComicVineResolveResponse {
    fn search(input: String, validation_error: Option<String>) -> Self {
        Self {
            input,
            kind: "search".to_owned(),
            validation_error,
            issue: None,
            volume: None,
            issues: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ComicVineSeriesIssuesResponse {
    pub comicvine_volume_id: i32,
    pub series_name: String,
    pub issues: Vec<ComicVineIssueCandidate>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IssueIdentityMapping {
    pub external_identity_id: i32,
    pub provider: String,
    pub comicvine_id: String,
    pub status: String,
    pub confidence: Option<f64>,
    pub evidence_source: Option<String>,
    pub created_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IssueIdentityResponse {
    pub issue_id: i32,
    pub thread_id: i32,
    pub thread_title: String,
    pub has_confirmed_identity: bool,
    pub comicvine_issue_id: Option<String>,
    pub confirmed_mappings: Vec<IssueIdentityMapping>,
    pub candidate_mappings: Vec<IssueIdentityMapping>,
    pub has_unresolved: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct MetadataRefreshResponse {
    pub issue_id: i32,
    pub refreshed: bool,
    pub comicvine_issue_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct CanonicalCorrection {
    pub id: i32,
    pub field_name: String,
    pub provider_value: Option<String>,
    pub canonical_value: String,
    pub provenance: String,
    pub created_by: i32,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct MetadataCorrectionsResponse {
    pub issue_id: i32,
    pub corrections: Vec<CanonicalCorrection>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct SeriesImportStatusResponse {
    pub comicvine_volume_id: i32,
    pub imported: bool,
    pub thread_id: Option<i32>,
    pub series_name: Option<String>,
    pub issue_count: Option<i32>,
}

// ---------------------------------------------------------------------------
// Request bodies and query strings.
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
pub struct SearchQuery {
    pub q: String,
    #[serde(default = "default_limit")]
    pub limit: i32,
    #[serde(default)]
    pub offset: i32,
}

fn default_limit() -> i32 {
    10
}

#[derive(Debug, Deserialize)]
pub struct ResolveQuery {
    pub input: String,
}

#[derive(Debug, Deserialize)]
pub struct SeriesIssuesQuery {
    #[serde(default)]
    pub series_name: String,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ConfirmIdentityRequest {
    pub comicvine_issue_id: i32,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ReplaceIdentityRequest {
    pub comicvine_issue_id: i32,
    pub reason: Option<String>,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct MetadataCorrectionRequest {
    pub field_name: String,
    pub canonical_value: String,
    #[allow(dead_code)]
    pub reason: Option<String>,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct MetadataCorrectionRevertRequest {
    pub correction_id: i32,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ImportIssueRequest {
    pub title: String,
    pub comicvine_issue_id: i32,
    pub issue_number: Option<String>,
    pub reading_order_id: Option<i32>,
    pub anchor_before_thread_id: Option<i32>,
    pub anchor_after_thread_id: Option<i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ImportIssueResponse {
    pub thread_id: i32,
    pub issue_id: i32,
    pub external_identity_id: i32,
    pub reading_order_id: Option<i32>,
    pub position: Option<i32>,
    pub total_items: Option<i32>,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ImportSeriesRequest {
    pub comicvine_volume_id: i32,
    pub reading_order_id: Option<i32>,
    pub anchor_before_thread_id: Option<i32>,
    pub anchor_after_thread_id: Option<i32>,
    #[serde(default)]
    pub already_read_count: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ImportSeriesIssueResult {
    pub comicvine_issue_id: i32,
    pub issue_number: Option<String>,
    pub issue_id: Option<i32>,
    pub outcome: String,
    pub hydration: String,
    pub conflict_detail: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ImportSeriesResponse {
    pub thread_id: i32,
    pub series_name: String,
    pub comicvine_volume_id: i32,
    pub total_issues_in_series: i32,
    pub issues_adopted: i32,
    pub issues_skipped: i32,
    pub issues_conflict: i32,
    pub issue_results: Vec<ImportSeriesIssueResult>,
    pub reading_order_id: Option<i32>,
    pub position: Option<i32>,
    pub total_items: Option<i32>,
    pub thread_created: bool,
}

// ---------------------------------------------------------------------------
// Pure helpers.
// ---------------------------------------------------------------------------

fn bad_request(detail: impl Into<String>) -> ApiError {
    ApiError::BadRequest(detail.into())
}

fn not_found(detail: impl Into<String>) -> ApiError {
    ApiError::NotFound(detail.into())
}

fn unprocessable(detail: &'static str) -> ApiError {
    ApiError::Unprocessable(detail.to_owned())
}

/// Coerce a provider value to an integer. ComicVine returns some numbers as
/// strings, so parse both, but never treat booleans or decimals as IDs.
fn coerce_provider_int(value: Option<&Value>) -> Option<i32> {
    match value {
        Some(Value::Number(n)) => n.as_i64().and_then(|n| i32::try_from(n).ok()),
        Some(Value::String(s)) => s.trim().parse::<i32>().ok(),
        _ => None,
    }
}

/// Return a non-empty provider string, otherwise `None`.
fn provider_string(value: Option<&Value>) -> Option<String> {
    value
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
}

/// Best available provider image URL, in the Python handler's priority order.
fn provider_image_url(value: Option<&Value>) -> Option<String> {
    let object = value?.as_object()?;
    for key in ["medium_url", "small_url", "super_url", "thumb_url"] {
        if let Some(url) = object.get(key).and_then(Value::as_str).filter(|s| !s.is_empty()) {
            return Some(url.to_owned());
        }
    }
    None
}

/// Small cover image URL used for issue candidates in a volume roster.
fn candidate_image_url(value: Option<&Value>) -> Option<String> {
    let object = value?.as_object()?;
    for key in ["small_url", "thumb_url"] {
        if let Some(url) = object.get(key).and_then(Value::as_str).filter(|s| !s.is_empty()) {
            return Some(url.to_owned());
        }
    }
    None
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ParsedResource {
    Issue(i32),
    Volume(i32),
}

/// Parse a pasted ComicVine URL into a trusted resource reference. Only the
/// canonical host and the `4000-` (issue) / `4050-` (volume) terminal segment
/// are accepted. Query strings, trailing slashes and `http` are tolerated.
fn parse_comicvine_url(raw: &str) -> Option<ParsedResource> {
    let value = raw.trim();
    if value.is_empty() {
        return None;
    }
    let with_scheme = if value.contains("://") {
        value.to_owned()
    } else {
        format!("https://{value}")
    };
    let after_scheme = with_scheme.split_once("://")?.1;
    let authority = after_scheme.split('/').next()?;
    let host = authority.rsplit('@').next()?.split(':').next()?.to_ascii_lowercase();
    if host != "comicvine.gamespot.com" && host != "www.comicvine.gamespot.com" {
        return None;
    }
    let path = after_scheme.strip_prefix(authority)?;
    let segment = path
        .split(['?', '#'])
        .next()?
        .split('/')
        .filter(|part| !part.is_empty())
        .last()?;
    let (prefix, digits) = segment.split_once('-')?;
    if !digits.bytes().all(|b| b.is_ascii_digit()) || digits.is_empty() {
        return None;
    }
    let id = digits.parse::<i32>().ok()?;
    match prefix {
        "4000" => Some(ParsedResource::Issue(id)),
        "4050" => Some(ParsedResource::Volume(id)),
        _ => None,
    }
}

fn looks_like_url(raw: &str) -> bool {
    let value = raw.trim();
    !value.is_empty() && (value.contains("://") || value.to_ascii_lowercase().starts_with("http"))
}

/// Percent-encode a provider search query. ComicVine treats `+` as a space.
fn encode_query(value: &str) -> String {
    let mut encoded = String::with_capacity(value.len());
    for byte in value.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                encoded.push(byte as char)
            }
            b' ' => encoded.push('+'),
            _ => encoded.push_str(&format!("%{byte:02X}")),
        }
    }
    encoded
}

/// 1-based insertion position between neighbor anchors. Mirrors the Python
/// `resolve_anchored_position` rules exactly.
fn resolve_anchored_position(
    positions: &HashMap<i32, i32>,
    before: Option<i32>,
    after: Option<i32>,
    total_items: usize,
) -> i32 {
    let before_pos = before.and_then(|id| positions.get(&id)).copied();
    let after_pos = after.and_then(|id| positions.get(&id)).copied();
    match (before_pos, after_pos) {
        (Some(b), Some(a)) if b < a => a,
        (Some(b), _) => b + 1,
        (None, Some(a)) => a,
        (None, None) => (total_items + 1) as i32,
    }
}

fn map_provider_failure(error: ProviderFailure) -> ApiError {
    match error {
        ProviderFailure::RateLimited(_) | ProviderFailure::Unavailable | ProviderFailure::Timeout => {
            ApiError::ServiceUnavailable("provider_unavailable".to_owned())
        }
        ProviderFailure::InvalidPayload => {
            ApiError::ServiceUnavailable("provider_invalid_payload".to_owned())
        }
    }
}
