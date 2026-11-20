//! Canonical native v2 ComicVine read routes (#4835, split plan chunk A).
//!
//! Rust v2 replacements for the browser-called, read-only
//! `/api/v1/comicvine/*` provider operations: series search, pasted-URL
//! resolution and a volume's issue roster. The wire contract (field names,
//! optionality, status codes and error envelopes) mirrors the frozen Python
//! handlers in `app/api/comicvine_resolution.py` and
//! `app/services/comicvine_resolution.py`. None of these routes touch the
//! database; every provider call goes through [`crate::comicvine_limits`].
//!
//! Chunk B adds the owner-scoped identity and correction READ routes
//! (`app/services/comicvine_resolution.py` `get_issue_identity_state` and
//! `list_metadata_corrections`). Chunk C adds the identity and correction
//! WRITE routes. Lock order for every identity writer: the per-reader queue
//! advisory lock ([`crate::queue::lock_queue`]) first, then the owned issue
//! row (`FOR UPDATE OF i`), matching `thread_repository.py:155-158`.
//! Chunk D adds the single-issue import (`import_comicvine_issue`), which
//! takes the same queue lock before its duplicate check, queue-position
//! assignment and reading-order insert. Series import moves in chunk E.

use crate::{auth::AuthenticatedUser, comicvine_repair::ProviderFailure, db, ApiError, AppState};
use axum::{
    extract::{
        rejection::{JsonRejection, PathRejection, QueryRejection},
        Path, Query, State,
    },
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{collections::HashMap, sync::Arc, time::Duration};
use tokio_postgres::Transaction;

/// Server deadline for the roster-backed reads (series issues and volume
/// resolve). A roster costs one first page plus `ceil((pages - 1) / 4)` waves
/// of concurrent pages, each bounded by the 5 s provider timeout, so the
/// default 10 s request deadline would cancel a cold multi-page roster that
/// is still succeeding (#4635551186). Matches the repair cron's 50 s budget;
/// the browser waits slightly longer (`COMICVINE_ROSTER_TIMEOUT_MS`).
pub const ROSTER_REQUEST_DEADLINE: Duration = Duration::from_secs(50);

/// True for the routes that need [`ROSTER_REQUEST_DEADLINE`].
pub fn needs_roster_deadline(path: &str) -> bool {
    path == "/api/v2/comicvine/resolve"
        || path
            .strip_prefix("/api/v2/comicvine/series/")
            .and_then(|rest| rest.strip_suffix("/issues"))
            .is_some_and(|id| !id.is_empty() && !id.contains('/'))
}

// ---------------------------------------------------------------------------
// Wire contract (mirrors app/schemas/comicvine_resolution.py).
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Serialize, utoipa::ToSchema)]
pub struct ComicVineSeriesResult {
    pub comicvine_volume_id: i32,
    pub name: String,
    pub publisher: Option<String>,
    pub start_year: Option<i32>,
    pub issue_count: Option<i32>,
    pub site_detail_url: Option<String>,
    pub image_url: Option<String>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ComicVineSeriesSearchResponse {
    pub query: String,
    pub results: Vec<ComicVineSeriesResult>,
    pub total_available: Option<i64>,
    pub offset: i32,
    pub limit: i32,
    pub has_more: bool,
    /// `offset + results` can exceed `i32` at the accepted offset bound, so
    /// paging arithmetic is widened (#4636390843).
    pub next_offset: Option<i64>,
}

impl ComicVineSeriesSearchResponse {
    fn empty(query: String, offset: i32, limit: i32) -> Self {
        Self {
            query,
            results: Vec::new(),
            total_available: Some(0),
            offset,
            limit,
            has_more: false,
            next_offset: None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, utoipa::ToSchema)]
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

#[derive(Debug, Clone, PartialEq, Serialize, utoipa::ToSchema)]
pub struct ComicVineIssueCandidate {
    pub comicvine_issue_id: i32,
    pub issue_number: Option<String>,
    pub name: Option<String>,
    pub cover_date: Option<String>,
    pub store_date: Option<String>,
    pub image_url: Option<String>,
    pub site_detail_url: Option<String>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ComicVineResolveResponse {
    pub input: String,
    /// `issue`, `volume` or `search`.
    pub kind: String,
    pub validation_error: Option<String>,
    pub issue: Option<ComicVineResolvedIssue>,
    pub volume: Option<ComicVineSeriesResult>,
    pub issues: Vec<ComicVineIssueCandidate>,
}

impl ComicVineResolveResponse {
    fn bare(input: String, kind: &str, validation_error: Option<&str>) -> Self {
        Self {
            input,
            kind: kind.to_owned(),
            validation_error: validation_error.map(str::to_owned),
            issue: None,
            volume: None,
            issues: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ComicVineSeriesIssuesResponse {
    pub comicvine_volume_id: i32,
    pub series_name: String,
    pub issues: Vec<ComicVineIssueCandidate>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct IssueIdentityMapping {
    pub external_identity_id: i32,
    pub provider: String,
    pub comicvine_id: String,
    pub status: String,
    pub confidence: Option<f64>,
    pub evidence_source: Option<String>,
    pub created_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
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

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct CanonicalCorrection {
    pub id: i32,
    pub field_name: String,
    pub provider_value: Option<String>,
    pub canonical_value: String,
    pub provenance: String,
    pub created_by: i32,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct MetadataCorrectionsResponse {
    pub issue_id: i32,
    pub corrections: Vec<CanonicalCorrection>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct MetadataRefreshResponse {
    pub issue_id: i32,
    pub refreshed: bool,
    pub comicvine_issue_id: Option<String>,
}

/// Python `ConfirmIdentityRequest` (lax `int`).
#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ConfirmIdentityRequest {
    #[serde(deserialize_with = "de_lax_i32")]
    pub comicvine_issue_id: i32,
}

/// Python `ReplaceIdentityRequest` (`reason` `max_length=500`).
#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ReplaceIdentityRequest {
    #[serde(deserialize_with = "de_lax_i32")]
    pub comicvine_issue_id: i32,
    #[serde(default)]
    pub reason: Option<String>,
}

/// Python `MetadataCorrectionRequest`: unconstrained `str` fields (empty is
/// accepted), `reason` `max_length=500`.
#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct MetadataCorrectionRequest {
    pub field_name: String,
    pub canonical_value: String,
    #[serde(default)]
    pub reason: Option<String>,
}

/// Python `ImportIssueRequest`: `title` 1-200 characters (stored stripped),
/// `comicvine_issue_id > 0`, `issue_number` at most 50 characters, and the
/// optional reading-order ids `> 0`.
#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ImportIssueRequest {
    pub title: String,
    #[serde(deserialize_with = "de_lax_i32")]
    pub comicvine_issue_id: i32,
    #[serde(default)]
    pub issue_number: Option<String>,
    #[serde(default, deserialize_with = "de_lax_opt_i32")]
    pub reading_order_id: Option<i32>,
    #[serde(default, deserialize_with = "de_lax_opt_i32")]
    pub anchor_before_thread_id: Option<i32>,
    #[serde(default, deserialize_with = "de_lax_opt_i32")]
    pub anchor_after_thread_id: Option<i32>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ImportIssueResponse {
    pub thread_id: i32,
    pub issue_id: i32,
    pub external_identity_id: i32,
    pub reading_order_id: Option<i32>,
    pub position: Option<i32>,
    pub total_items: Option<i32>,
}

/// Python `MetadataCorrectionRevertRequest` (lax `int`).
#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct MetadataCorrectionRevertRequest {
    #[serde(deserialize_with = "de_lax_i32")]
    pub correction_id: i32,
}

// ---------------------------------------------------------------------------
// Query strings (FastAPI `Query(...)` declarations in the Python router).
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
pub struct SearchQuery {
    pub q: String,
    #[serde(default = "default_limit", deserialize_with = "de_lax_i32")]
    pub limit: i32,
    #[serde(default, deserialize_with = "de_lax_i32")]
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

const NOT_A_COMICVINE_URL: &str = "That doesn't look like a ComicVine issue or volume URL. \
     Paste a comicvine.gamespot.com link or search by title instead.";
const PROVIDER_NOT_CONFIGURED: &str = "ComicVine is not configured on this server, so pasted \
     links cannot be resolved. Search by title instead.";
const RESOLVE_FAILED: &str = "We couldn't resolve that ComicVine link right now. Check the \
     link or search by title instead.";

// ---------------------------------------------------------------------------
// Request validation helpers.
// ---------------------------------------------------------------------------

/// Production `RequestValidationError` body (`app/exception_handlers.py`):
/// every 422 is the generic `{"detail": "Validation failed"}`; the specific
/// reason is only logged.
fn unprocessable(reason: &'static str) -> ApiError {
    tracing::debug!(reason, "comicvine request validation failed");
    ApiError::Unprocessable("Validation failed".to_owned())
}

fn validation_failed() -> ApiError {
    unprocessable("extractor rejection")
}

fn not_found(detail: impl Into<String>) -> ApiError {
    ApiError::NotFound(detail.into())
}

/// Python `ExternalIdentityMappingError` -> `400 {"detail": <message>}`.
fn bad_request(detail: impl Into<String>) -> ApiError {
    ApiError::BadRequest(detail.into())
}

/// Python Pydantic `max_length=500` on the optional `reason` fields.
fn reason_too_long(reason: Option<&str>) -> bool {
    reason.is_some_and(|reason| reason.chars().count() > 500)
}

/// Pydantic v2 lax `int` coercion for query and path values (integer strings
/// such as `"5"`/`"5.0"`). Values outside `i32` are rejected.
fn lax_i32(value: &Value) -> Option<i32> {
    crate::bug_reports::pydantic_lax_int(value).and_then(|n| i32::try_from(n).ok())
}

fn de_lax_i32<'de, D>(deserializer: D) -> Result<i32, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = Value::deserialize(deserializer)?;
    lax_i32(&value).ok_or_else(|| serde::de::Error::custom("invalid integer"))
}

fn de_lax_opt_i32<'de, D>(deserializer: D) -> Result<Option<i32>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    match Value::deserialize(deserializer)? {
        Value::Null => Ok(None),
        value => lax_i32(&value)
            .map(Some)
            .ok_or_else(|| serde::de::Error::custom("invalid integer")),
    }
}

/// FastAPI `int` path parameter: lax string coercion, otherwise 422.
fn path_int(raw: Result<Path<String>, PathRejection>) -> Result<i32, ApiError> {
    let Path(raw) = raw.map_err(|_| validation_failed())?;
    lax_i32(&Value::String(raw)).ok_or_else(validation_failed)
}

// ---------------------------------------------------------------------------
// Provider payload mapping (Python `isinstance` checks, value for value).
// ---------------------------------------------------------------------------

/// Python `isinstance(value, int)`: JSON integers and booleans (a Python
/// `bool` is an `int`); never floats or numeric strings.
fn python_int(value: Option<&Value>) -> Option<i32> {
    match value? {
        Value::Number(n) => n.as_i64().and_then(|n| i32::try_from(n).ok()),
        Value::Bool(flag) => Some(i32::from(*flag)),
        _ => None,
    }
}

/// Python `_coerce_provider_int`: integers and integral floats, or strings
/// whose stripped text is all digits; never booleans. Wide (`i64`) so a
/// provider total past `i32` still pages correctly (#4636390843).
fn coerce_provider_i64(value: Option<&Value>) -> Option<i64> {
    match value? {
        Value::Number(n) => match n.as_i64() {
            Some(n) => Some(n),
            None => n
                .as_f64()
                .filter(|f| f.fract() == 0.0 && f.abs() < 9.0e15)
                .map(|f| f as i64),
        },
        Value::String(s) => {
            let digits = s.trim();
            if !digits.is_empty() && digits.bytes().all(|b| b.is_ascii_digit()) {
                digits.parse::<i64>().ok()
            } else {
                None
            }
        }
        _ => None,
    }
}

/// [`coerce_provider_i64`] for the `i32` wire fields (`start_year`,
/// `issue_count`); values outside `i32` are dropped.
fn coerce_provider_int(value: Option<&Value>) -> Option<i32> {
    coerce_provider_i64(value).and_then(|n| i32::try_from(n).ok())
}

/// Python `value if isinstance(value, str) else None` (empty strings kept).
fn python_str(value: Option<&Value>) -> Option<String> {
    value.and_then(Value::as_str).map(str::to_owned)
}

/// Python `_provider_string`: a non-empty string, otherwise `None`.
fn provider_string(value: Option<&Value>) -> Option<String> {
    value
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
}

/// Python `str(value) if value is not None else None` for a provider
/// `issue_number`: JSON `null` (or a missing key) is `None`, never the text
/// `"null"`, and an empty string stays `""` (#4635845117).
fn python_str_or_none(value: Option<&Value>) -> Option<String> {
    match value? {
        Value::Null => None,
        Value::String(text) => Some(text.clone()),
        Value::Bool(true) => Some("True".to_owned()),
        Value::Bool(false) => Some("False".to_owned()),
        other => Some(other.to_string()),
    }
}

/// Python `a or b` over two string fields of a provider object.
fn first_truthy(
    object: &serde_json::Map<String, Value>,
    first: &str,
    second: &str,
) -> Option<String> {
    match object.get(first).and_then(Value::as_str) {
        Some(text) if !text.is_empty() => Some(text.to_owned()),
        _ => python_str(object.get(second)),
    }
}

/// Python `_provider_image_url`: best non-empty image URL in priority order.
fn provider_image_url(value: Option<&Value>) -> Option<String> {
    let object = value?.as_object()?;
    ["medium_url", "small_url", "super_url", "thumb_url"]
        .into_iter()
        .find_map(|key| provider_string(object.get(key)))
}

fn publisher_name(value: Option<&Value>) -> Option<String> {
    match value? {
        Value::Object(map) => python_str(map.get("name")),
        Value::String(text) => Some(text.clone()),
        _ => None,
    }
}

/// One search row (Python `search_comicvine_series` loop body).
fn search_result(value: &Value) -> Option<ComicVineSeriesResult> {
    let object = value.as_object()?;
    let id = python_int(object.get("id"))?;
    let name = python_str(object.get("name"))?;
    Some(ComicVineSeriesResult {
        comicvine_volume_id: id,
        name,
        publisher: publisher_name(object.get("publisher")),
        start_year: coerce_provider_int(object.get("start_year")),
        issue_count: coerce_provider_int(object.get("count_of_issues")),
        site_detail_url: python_str(object.get("site_detail_url")),
        image_url: object
            .get("image")
            .and_then(Value::as_object)
            .and_then(|image| first_truthy(image, "medium_url", "small_url")),
    })
}

/// A volume resolved from a pasted URL (Python `_resolve_comicvine_volume`):
/// the result must be an object with a non-blank name.
fn resolved_volume(result: &Value, volume_id: i32) -> Option<ComicVineSeriesResult> {
    let object = result.as_object()?;
    let name = python_str(object.get("name")).filter(|name| !name.trim().is_empty())?;
    Some(ComicVineSeriesResult {
        comicvine_volume_id: volume_id,
        name,
        publisher: publisher_name(object.get("publisher")),
        start_year: coerce_provider_int(object.get("start_year")),
        issue_count: coerce_provider_int(object.get("count_of_issues")),
        site_detail_url: provider_string(object.get("site_detail_url")),
        image_url: provider_image_url(object.get("image")),
    })
}

/// An issue resolved from a pasted URL (Python `_resolve_comicvine_issue`):
/// the result must be an object.
fn resolved_issue(result: &Value, issue_id: i32) -> Option<ComicVineResolvedIssue> {
    let object = result.as_object()?;
    let volume = object.get("volume").and_then(Value::as_object);
    Some(ComicVineResolvedIssue {
        comicvine_issue_id: issue_id,
        series_name: volume.and_then(|v| python_str(v.get("name"))),
        volume_id: volume.and_then(|v| python_int(v.get("id"))),
        issue_number: python_str_or_none(object.get("issue_number")),
        name: provider_string(object.get("name")),
        cover_date: provider_string(object.get("cover_date")),
        store_date: provider_string(object.get("store_date")),
        image_url: provider_image_url(object.get("image")),
        site_detail_url: provider_string(object.get("site_detail_url")),
    })
}

/// One roster row (Python `get_comicvine_series_issues` loop body).
fn issue_candidate(value: &Value) -> Option<ComicVineIssueCandidate> {
    let object = value.as_object()?;
    Some(ComicVineIssueCandidate {
        comicvine_issue_id: python_int(object.get("id"))?,
        issue_number: python_str_or_none(object.get("issue_number")),
        name: python_str(object.get("name")),
        cover_date: python_str(object.get("cover_date")),
        store_date: python_str(object.get("store_date")),
        image_url: object
            .get("image")
            .and_then(Value::as_object)
            .and_then(|image| first_truthy(image, "small_url", "thumb_url")),
        site_detail_url: python_str(object.get("site_detail_url")),
    })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ParsedResource {
    Issue(i32),
    Volume(i32),
}

impl ParsedResource {
    fn kind(self) -> &'static str {
        match self {
            ParsedResource::Issue(_) => "issue",
            ParsedResource::Volume(_) => "volume",
        }
    }
}

/// Python `parse_comicvine_url`: only `http`/`https`, the canonical host and a
/// final `4000-<id>` (issue) / `4050-<id>` (volume) path segment are accepted.
/// Query strings, fragments, ports, user info and trailing slashes are
/// tolerated.
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
    let (scheme, after_scheme) = with_scheme.split_once("://")?;
    if !scheme.eq_ignore_ascii_case("http") && !scheme.eq_ignore_ascii_case("https") {
        return None;
    }
    let authority_end = after_scheme
        .find(['/', '?', '#'])
        .unwrap_or(after_scheme.len());
    let (authority, rest) = after_scheme.split_at(authority_end);
    let host = authority
        .rsplit('@')
        .next()?
        .split(':')
        .next()?
        .to_ascii_lowercase();
    if host != "comicvine.gamespot.com" && host != "www.comicvine.gamespot.com" {
        return None;
    }
    let path = rest.split(['?', '#']).next()?;
    let segment = path.split('/').rfind(|part| !part.is_empty())?;
    let (prefix, digits) = segment.split_once('-')?;
    if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let id = digits.parse::<i32>().ok()?;
    match prefix {
        "4000" => Some(ParsedResource::Issue(id)),
        "4050" => Some(ParsedResource::Volume(id)),
        _ => None,
    }
}

/// Python `looks_like_url`.
fn looks_like_url(raw: &str) -> bool {
    let value = raw.trim();
    !value.is_empty() && (value.contains("://") || value.to_ascii_lowercase().starts_with("http"))
}

/// Percent-encode a provider search query (form encoding: space is `+`).
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

fn provider_key() -> Option<String> {
    std::env::var("COMICVINE_API_KEY")
        .ok()
        .map(|key| key.trim().to_owned())
        .filter(|key| !key.is_empty())
}

// ---------------------------------------------------------------------------
// Volume issue roster (Python `ComicVineClient.fetch_volume_issues`).
// ---------------------------------------------------------------------------

/// ComicVine `/issues` page size (Python `COLLECTION_PAGE_LIMIT`).
const ROSTER_PAGE_SIZE: usize = 100;
/// Python `VOLUME_ISSUES_PAGE_CONCURRENCY`: remaining roster pages are fetched
/// at most this many at a time.
const ROSTER_PAGE_CONCURRENCY: usize = 4;
/// Safety bound on roster pagination (100 rows/page, so 10,000 issues).
/// Python walks every page; Rust fails loudly past this bound rather than
/// returning a truncated roster as if it were complete.
const MAX_ROSTER_PAGES: usize = 100;

/// One validated roster page (Python `VolumeIssuePage`).
#[derive(Debug)]
struct RosterPage {
    rows: Vec<Value>,
    total: Option<usize>,
}

/// Python `volume.get("id") not in (None, volume_id)` with Python equality
/// (`5 == 5.0 == True`-style numeric comparison, strings never equal).
fn belongs_to_volume(id: &Value, volume_id: i32) -> bool {
    match id {
        Value::Null => true,
        Value::Number(n) => n.as_f64() == Some(f64::from(volume_id)),
        Value::Bool(flag) => i32::from(*flag) == volume_id,
        _ => false,
    }
}

/// Validate one `/issues` page exactly like Python `_fetch_volume_issue_page`:
/// a page without a `results` list is a provider error, never an empty page
/// (#4635551195); non-object rows are dropped; a row whose `volume.id`
/// differs from the requested volume means the provider ignored the filter,
/// so the whole roster is refused.
fn roster_page(payload: &Value, volume_id: i32) -> Result<RosterPage, ProviderFailure> {
    let results = payload
        .get("results")
        .and_then(Value::as_array)
        .ok_or(ProviderFailure::InvalidPayload)?;
    let rows: Vec<Value> = results
        .iter()
        .filter(|row| row.is_object())
        .cloned()
        .collect();
    let foreign_row = rows.iter().any(|row| {
        row.get("volume")
            .and_then(Value::as_object)
            .is_some_and(|volume| {
                !belongs_to_volume(volume.get("id").unwrap_or(&Value::Null), volume_id)
            })
    });
    if foreign_row {
        return Err(ProviderFailure::InvalidPayload);
    }
    // Python keeps the total only when it is an `int`.
    let total = match payload.get("number_of_total_results") {
        Some(Value::Number(n)) => n.as_i64().map(|total| total.max(0) as usize),
        Some(Value::Bool(flag)) => Some(usize::from(*flag)),
        _ => None,
    };
    Ok(RosterPage { rows, total })
}

async fn fetch_roster_page(
    state: &AppState,
    volume_id: i32,
    key: &str,
    offset: usize,
) -> Result<RosterPage, ProviderFailure> {
    let extra = format!(
        "&filter=volume:{volume_id}&limit={ROSTER_PAGE_SIZE}&offset={offset}\
         &field_list=id,issue_number,name,cover_date,store_date,image,site_detail_url,volume"
    );
    let payload = state
        .comicvine_limits
        .call(&state.outbound, "issues", &extra, key)
        .await?;
    roster_page(&payload, volume_id)
}

/// Fetch the complete, validated issue roster for one volume. The first page
/// is fetched alone; an omitted total walks forward until a short page; a
/// short or complete first page is the roster; otherwise the remaining fixed
/// offsets are fetched concurrently (at most [`ROSTER_PAGE_CONCURRENCY`] in
/// flight) and assembled in offset order (#4635551186). Any malformed page
/// fails the whole roster.
async fn provider_roster(
    state: &Arc<AppState>,
    volume_id: i32,
    key: &str,
) -> Result<Vec<Value>, ProviderFailure> {
    let first = fetch_roster_page(state, volume_id, key, 0).await?;
    let Some(total) = first.total else {
        let mut rows = first.rows;
        let mut last_len = rows.len();
        let mut pages = 1usize;
        while last_len >= ROSTER_PAGE_SIZE {
            if pages >= MAX_ROSTER_PAGES {
                return Err(ProviderFailure::InvalidPayload);
            }
            let page = fetch_roster_page(state, volume_id, key, rows.len()).await?;
            pages += 1;
            last_len = page.rows.len();
            rows.extend(page.rows);
        }
        return Ok(rows);
    };
    if first.rows.len() >= total || first.rows.len() < ROSTER_PAGE_SIZE {
        return Ok(first.rows);
    }
    let pages_needed = total.div_ceil(ROSTER_PAGE_SIZE);
    if pages_needed > MAX_ROSTER_PAGES {
        return Err(ProviderFailure::InvalidPayload);
    }
    let offsets: Vec<usize> = (1..pages_needed)
        .map(|page| page * ROSTER_PAGE_SIZE)
        .collect();
    let mut pages: Vec<Option<Vec<Value>>> = vec![None; offsets.len()];
    // Dropping the set (error or request deadline) aborts in-flight fetches.
    let mut in_flight = tokio::task::JoinSet::new();
    let mut next = 0usize;
    loop {
        while next < offsets.len() && in_flight.len() < ROSTER_PAGE_CONCURRENCY {
            let (state, key, index, offset) =
                (Arc::clone(state), key.to_owned(), next, offsets[next]);
            in_flight.spawn(async move {
                (
                    index,
                    fetch_roster_page(&state, volume_id, &key, offset).await,
                )
            });
            next += 1;
        }
        let Some(joined) = in_flight.join_next().await else {
            break;
        };
        let (index, page) = joined.map_err(|_| ProviderFailure::Unavailable)?;
        pages[index] = Some(page?.rows);
    }
    let mut rows = first.rows;
    for page in pages {
        rows.extend(page.ok_or(ProviderFailure::Unavailable)?);
    }
    Ok(rows)
}

/// Python `ComicVineClient.fetch_volume` (`payload["results"]`).
async fn provider_volume(
    state: &AppState,
    volume_id: i32,
    key: &str,
) -> Result<Value, ProviderFailure> {
    let payload = state
        .comicvine_limits
        .call(
            &state.outbound,
            &format!("volume/4050-{volume_id}"),
            "",
            key,
        )
        .await?;
    Ok(payload.get("results").cloned().unwrap_or(Value::Null))
}

/// Python `get_comicvine_series_issues`: each provider read degrades
/// independently (a roster failure is an empty roster; a volume failure or a
/// volume without a string name is the `Volume <id>` label).
async fn series_issues_response(
    state: &Arc<AppState>,
    volume_id: i32,
    series_name: String,
    key: Option<&str>,
) -> ComicVineSeriesIssuesResponse {
    let fallback = || format!("Volume {volume_id}");
    let Some(key) = key else {
        return ComicVineSeriesIssuesResponse {
            comicvine_volume_id: volume_id,
            series_name: if series_name.is_empty() {
                fallback()
            } else {
                series_name
            },
            issues: Vec::new(),
        };
    };
    let (roster, series_name) = if series_name.is_empty() {
        // Python schedules the roster and the volume read together, so the
        // two provider round trips overlap.
        let (roster, volume) = tokio::join!(
            provider_roster(state, volume_id, key),
            provider_volume(state, volume_id, key)
        );
        let name = volume.ok().and_then(|volume| match volume {
            Value::Object(map) => Some(python_str(map.get("name")).unwrap_or_else(fallback)),
            _ => None,
        });
        (roster, name.unwrap_or_else(fallback))
    } else {
        (provider_roster(state, volume_id, key).await, series_name)
    };
    let issues = match roster {
        Ok(rows) => rows.iter().filter_map(issue_candidate).collect(),
        Err(failure) => {
            tracing::warn!(volume_id, ?failure, "comicvine roster fetch failed");
            Vec::new()
        }
    };
    ComicVineSeriesIssuesResponse {
        comicvine_volume_id: volume_id,
        series_name,
        issues,
    }
}

// ---------------------------------------------------------------------------
// Owner-scoped database helpers. Every caller passes the authenticated user
// id as a bind parameter, never as interpolated SQL.
// ---------------------------------------------------------------------------

/// Python `get_owned_issue_or_404`: resolve an owned issue to its thread id
/// and title, or `404 {"detail": "Issue <id> not found"}`.
async fn owned_issue(
    tx: &Transaction<'_>,
    user: i32,
    issue_id: i32,
) -> Result<(i32, String), ApiError> {
    let row = tx
        .query_opt(
            "SELECT t.id, t.title FROM issues i \
             JOIN threads t ON t.id = i.thread_id \
             WHERE i.id = $1 AND t.user_id = $2",
            &[&issue_id, &user],
        )
        .await
        .map_err(db::query_error)?;
    row.map(|row| (row.get::<_, i32>(0), row.get::<_, String>(1)))
        .ok_or_else(|| not_found(format!("Issue {issue_id} not found")))
}

/// Pydantic's JSON spelling of a UTC `timestamptz`: `Z` suffix, and the
/// fractional part only when the value has one (the projection the other
/// native v2 resources use, e.g. `preferences::iso_timestamp`).
fn iso_timestamp(column: &str) -> String {
    format!(
        "CASE WHEN {column} IS NULL THEN NULL \
         WHEN date_trunc('second', {column}) = {column} \
         THEN to_char({column} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
         ELSE to_char({column} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') END"
    )
}

/// Python `get_issue_identity_state`: every mapping of one owned issue,
/// ordered by confidence (nulls last), split into confirmed and candidate
/// lists; an `unresolved` row only sets `has_unresolved`.
async fn identity_state(
    tx: &Transaction<'_>,
    user: i32,
    issue_id: i32,
) -> Result<IssueIdentityResponse, ApiError> {
    let (thread_id, thread_title) = owned_issue(tx, user, issue_id).await?;
    let rows = tx
        .query(
            &format!(
                "SELECT e.id, e.provider, e.external_id, m.status, m.confidence, \
                        m.evidence_source, {} \
                 FROM issue_external_identity_mappings m \
                 JOIN external_identities e ON e.id = m.external_identity_id \
                 WHERE m.issue_id = $1 \
                 ORDER BY m.confidence DESC NULLS LAST, m.id ASC",
                iso_timestamp("m.created_at")
            ),
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?;
    let mut confirmed = Vec::new();
    let mut candidates = Vec::new();
    let mut has_unresolved = false;
    for row in &rows {
        let mapping = IssueIdentityMapping {
            external_identity_id: row.get(0),
            provider: row.get(1),
            comicvine_id: row.get(2),
            status: row.get(3),
            confidence: row.get(4),
            evidence_source: row.get(5),
            created_at: row.get(6),
        };
        match mapping.status.as_str() {
            "confirmed" => confirmed.push(mapping),
            "candidate" => candidates.push(mapping),
            "unresolved" => has_unresolved = true,
            _ => {}
        }
    }
    Ok(IssueIdentityResponse {
        issue_id,
        thread_id,
        thread_title,
        has_confirmed_identity: !confirmed.is_empty(),
        comicvine_issue_id: confirmed.first().map(|m| m.comicvine_id.clone()),
        confirmed_mappings: confirmed,
        candidate_mappings: candidates,
        has_unresolved,
    })
}

/// Python `list_metadata_corrections`: the active (non-reverted)
/// corrections of one owned issue, oldest first.
async fn corrections_list(
    tx: &Transaction<'_>,
    user: i32,
    issue_id: i32,
) -> Result<MetadataCorrectionsResponse, ApiError> {
    owned_issue(tx, user, issue_id).await?;
    let rows = tx
        .query(
            &format!(
                "SELECT c.id, c.field_name, c.provider_value, c.canonical_value, \
                        c.provenance, c.created_by, {} \
                 FROM issue_metadata_corrections c \
                 JOIN issues i ON i.id = c.issue_id \
                 JOIN threads t ON t.id = i.thread_id \
                 WHERE c.issue_id = $1 AND t.user_id = $2 AND c.reverted_at IS NULL \
                 ORDER BY c.created_at ASC, c.id ASC",
                iso_timestamp("c.created_at")
            ),
            &[&issue_id, &user],
        )
        .await
        .map_err(db::query_error)?;
    let corrections = rows
        .iter()
        .map(|row| CanonicalCorrection {
            id: row.get(0),
            field_name: row.get(1),
            provider_value: row.get(2),
            canonical_value: row.get(3),
            provenance: row.get(4),
            created_by: row.get(5),
            created_at: row.get(6),
        })
        .collect();
    Ok(MetadataCorrectionsResponse {
        issue_id,
        corrections,
    })
}

/// Lock the owned issue row (`FOR UPDATE OF i`), or `404 Issue <id> not
/// found` (Python `get_owned_issue_or_404` runs before every identity write).
/// Callers hold the reader's queue lock already.
async fn lock_owned_issue(tx: &Transaction<'_>, user: i32, issue_id: i32) -> Result<(), ApiError> {
    tx.query_opt(
        "SELECT i.id FROM issues i JOIN threads t ON t.id = i.thread_id \
         WHERE i.id = $1 AND t.user_id = $2 FOR UPDATE OF i",
        &[&issue_id, &user],
    )
    .await
    .map_err(db::query_error)?
    .map(|_| ())
    .ok_or_else(|| not_found(format!("Issue {issue_id} not found")))
}

/// Python `upsert_external_identity(provider="comicvine", entity_type="issue")`:
/// the canonical identity row, created on first use. An existing row keeps its
/// metadata and `updated_at` (a URL rewrite is not a provider refresh).
async fn upsert_issue_identity(
    tx: &Transaction<'_>,
    comicvine_issue_id: i32,
) -> Result<i32, ApiError> {
    let external_id = comicvine_issue_id.to_string();
    let external_url = format!("https://comicvine.gamespot.com/issue/4000-{comicvine_issue_id}/");
    let row = tx
        .query_one(
            "INSERT INTO external_identities \
                (provider, entity_type, external_id, external_url, metadata_json, created_at, updated_at) \
             VALUES ('comicvine', 'issue', $1, $2, '{}'::json, now(), now()) \
             ON CONFLICT ON CONSTRAINT uq_external_identity_provider_entity \
             DO UPDATE SET external_url = EXCLUDED.external_url \
             RETURNING id",
            &[&external_id, &external_url],
        )
        .await
        .map_err(db::query_error)?;
    Ok(row.get(0))
}

/// Python `link_issue_external_identity(status="confirmed")` for an issue row
/// the caller has locked: a different confirmed ComicVine identity on the
/// same issue is the Python 400; otherwise the mapping is created or
/// re-confirmed (`confidence 1.0`, no rejection reason).
async fn link_with_source(
    tx: &Transaction<'_>,
    issue_id: i32,
    comicvine_issue_id: i32,
    evidence_source: &str,
) -> Result<i32, ApiError> {
    let identity_id = upsert_issue_identity(tx, comicvine_issue_id).await?;
    let conflicting = tx
        .query_opt(
            "SELECT m.id FROM issue_external_identity_mappings m \
             JOIN external_identities e ON e.id = m.external_identity_id \
             WHERE m.issue_id = $1 AND m.status = 'confirmed' \
               AND m.external_identity_id <> $2 AND e.provider = 'comicvine' \
             LIMIT 1",
            &[&issue_id, &identity_id],
        )
        .await
        .map_err(db::query_error)?;
    if conflicting.is_some() {
        return Err(bad_request(
            "issue already has a confirmed comicvine identity",
        ));
    }
    tx.execute(
        "INSERT INTO issue_external_identity_mappings \
            (issue_id, external_identity_id, status, evidence_source, evidence_json, \
             confidence, rejection_reason, created_at, updated_at) \
         VALUES ($1, $2, 'confirmed', $3, '{}'::json, 1.0, NULL, now(), now()) \
         ON CONFLICT ON CONSTRAINT uq_issue_external_identity_mapping \
         DO UPDATE SET status = 'confirmed', evidence_source = EXCLUDED.evidence_source, \
                       confidence = 1.0, rejection_reason = NULL, updated_at = now()",
        &[&issue_id, &identity_id, &evidence_source],
    )
    .await
    .map_err(db::query_error)?;
    Ok(identity_id)
}

/// Confirm one user-selected identity, then schedule best-effort hydration.
/// Python commits the confirmation and hydrates after; here scheduling runs
/// in a savepoint so its failure never undoes the mapping (#4631578606).
async fn link_confirmed(
    tx: &Transaction<'_>,
    issue_id: i32,
    comicvine_issue_id: i32,
) -> Result<(), ApiError> {
    let identity_id = link_with_source(tx, issue_id, comicvine_issue_id, "user_confirmed").await?;
    tx.batch_execute("SAVEPOINT comicvine_hydration_enqueue")
        .await
        .map_err(db::query_error)?;
    if enqueue_hydration_if_needed(tx, identity_id).await.is_ok() {
        tx.batch_execute("RELEASE SAVEPOINT comicvine_hydration_enqueue")
            .await
            .map_err(db::query_error)?;
    } else {
        tracing::warn!(
            identity_id,
            "comicvine hydration scheduling failed; confirmation kept"
        );
        tx.batch_execute("ROLLBACK TO SAVEPOINT comicvine_hydration_enqueue")
            .await
            .map_err(db::query_error)?;
    }
    Ok(())
}

/// Rust analogue of Python's post-commit `refresh_issue_metadata`: when the
/// identity lacks fresh deep provider metadata, queue a refresh for the
/// native repair worker. The table holds one row per identity in any state
/// (`uq_comicvine_metadata_refresh_identity`), so a finished row (completed,
/// no_credits or failed) is reopened instead of colliding (#4631578606); a
/// pending, running or deferred row is left alone.
async fn enqueue_hydration_if_needed(
    tx: &Transaction<'_>,
    identity_id: i32,
) -> Result<(), ApiError> {
    let metadata: Value = tx
        .query_one(
            "SELECT metadata_json::text FROM external_identities WHERE id = $1",
            &[&identity_id],
        )
        .await
        .map_err(db::query_error)?
        .get::<_, Option<String>>(0)
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or(Value::Null);
    if !crate::comicvine_repair::needs_provider_fetch(&metadata, chrono::Utc::now()) {
        return Ok(());
    }
    tx.execute(
        "INSERT INTO comicvine_metadata_refresh_requests \
            (external_identity_id, state, attempts, next_attempt_at, created_at, updated_at) \
         VALUES ($1, 'pending', 0, now(), now(), now()) \
         ON CONFLICT ON CONSTRAINT uq_comicvine_metadata_refresh_identity \
         DO UPDATE SET state = 'pending', attempts = 0, next_attempt_at = now(), \
                       lease_expires_at = NULL, last_error = NULL, completed_at = NULL, \
                       updated_at = now() \
         WHERE comicvine_metadata_refresh_requests.state \
               NOT IN ('pending', 'running', 'deferred')",
        &[&identity_id],
    )
    .await
    .map_err(db::query_error)?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Handlers.
// ---------------------------------------------------------------------------

/// `GET /api/v2/comicvine/search/series`.
pub async fn search_series(
    State(state): State<Arc<AppState>>,
    _user: AuthenticatedUser,
    query: Result<Query<SearchQuery>, QueryRejection>,
) -> Result<Json<ComicVineSeriesSearchResponse>, ApiError> {
    let Query(query) = query.map_err(|_| validation_failed())?;
    // Python `Query(min_length=1, max_length=200)`, `limit` ge=1 le=50, `offset` ge=0.
    if query.q.is_empty() || query.q.chars().count() > 200 {
        return Err(unprocessable("q length out of range"));
    }
    if !(1..=50).contains(&query.limit) {
        return Err(unprocessable("limit out of range"));
    }
    if query.offset < 0 {
        return Err(unprocessable("offset out of range"));
    }
    let (limit, offset) = (query.limit, query.offset);
    let page = i64::from(offset) / i64::from(limit) + 1;
    let key = match provider_key() {
        Some(key) if !query.q.trim().is_empty() => key,
        _ => {
            return Ok(Json(ComicVineSeriesSearchResponse::empty(
                query.q, offset, limit,
            )))
        }
    };
    let extra = format!(
        "&query={}&resources=volume&limit={limit}&page={page}\
         &field_list=id,name,publisher,start_year,count_of_issues,site_detail_url,image",
        encode_query(&query.q)
    );
    // Python lets provider errors escape to the global handler: a generic 500.
    let payload = state
        .comicvine_limits
        .call(&state.outbound, "search", &extra, &key)
        .await
        .map_err(|failure| {
            tracing::warn!(?failure, "comicvine series search failed");
            ApiError::Internal("Internal server error".to_owned())
        })?;
    let Some(rows) = payload.get("results").and_then(Value::as_array) else {
        return Ok(Json(ComicVineSeriesSearchResponse::empty(
            query.q, offset, limit,
        )));
    };
    let results: Vec<ComicVineSeriesResult> = rows.iter().filter_map(search_result).collect();
    // Widened arithmetic: `offset` may be `i32::MAX` (#4636390843).
    let total =
        coerce_provider_i64(payload.get("number_of_total_results")).unwrap_or(results.len() as i64);
    let loaded = i64::from(offset) + results.len() as i64;
    let has_more = loaded < total;
    Ok(Json(ComicVineSeriesSearchResponse {
        query: query.q,
        results,
        total_available: Some(total),
        offset,
        limit,
        has_more,
        next_offset: has_more.then_some(loaded),
    }))
}

/// `GET /api/v2/comicvine/series/{comicvine_volume_id}/issues`.
pub async fn series_issues(
    State(state): State<Arc<AppState>>,
    _user: AuthenticatedUser,
    comicvine_volume_id: Result<Path<String>, PathRejection>,
    query: Result<Query<SeriesIssuesQuery>, QueryRejection>,
) -> Result<Json<ComicVineSeriesIssuesResponse>, ApiError> {
    let volume_id = path_int(comicvine_volume_id)?;
    let Query(query) = query.map_err(|_| validation_failed())?;
    let key = provider_key();
    Ok(Json(
        series_issues_response(&state, volume_id, query.series_name, key.as_deref()).await,
    ))
}

/// `GET /api/v2/comicvine/resolve`.
pub async fn resolve_input(
    State(state): State<Arc<AppState>>,
    _user: AuthenticatedUser,
    query: Result<Query<ResolveQuery>, QueryRejection>,
) -> Result<Json<ComicVineResolveResponse>, ApiError> {
    let Query(query) = query.map_err(|_| validation_failed())?;
    // Python `Query(min_length=1, max_length=1000)`.
    if query.input.is_empty() || query.input.chars().count() > 1000 {
        return Err(unprocessable("resolve input length out of range"));
    }
    let input = query.input;
    let trimmed = input.trim();
    if trimmed.is_empty() {
        return Ok(Json(ComicVineResolveResponse::bare(input, "search", None)));
    }
    let Some(parsed) = parse_comicvine_url(trimmed) else {
        let error = looks_like_url(trimmed).then_some(NOT_A_COMICVINE_URL);
        return Ok(Json(ComicVineResolveResponse::bare(input, "search", error)));
    };
    let Some(key) = provider_key() else {
        return Ok(Json(ComicVineResolveResponse::bare(
            input,
            parsed.kind(),
            Some(PROVIDER_NOT_CONFIGURED),
        )));
    };
    let mut response = ComicVineResolveResponse::bare(input, parsed.kind(), None);
    let resolved = match parsed {
        ParsedResource::Issue(id) => state
            .comicvine_limits
            .call(
                &state.outbound,
                &format!("issue/4000-{id}"),
                &format!("&field_list={}", crate::comicvine_repair::FIELDS),
                &key,
            )
            .await
            .ok()
            .and_then(|payload| resolved_issue(payload.get("results")?, id))
            .map(|issue| response.issue = Some(issue)),
        ParsedResource::Volume(id) => {
            match provider_volume(&state, id, &key)
                .await
                .ok()
                .and_then(|result| resolved_volume(&result, id))
            {
                Some(volume) => {
                    let name = volume.name.clone();
                    response.issues = series_issues_response(&state, id, name, Some(&key))
                        .await
                        .issues;
                    response.volume = Some(volume);
                    Some(())
                }
                None => None,
            }
        }
    };
    if resolved.is_none() {
        tracing::warn!(kind = parsed.kind(), "comicvine resolve failed");
        response.validation_error = Some(RESOLVE_FAILED.to_owned());
    }
    Ok(Json(response))
}

/// `GET /api/v2/comicvine/issues/{issue_id}/identity`.
pub async fn get_issue_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    issue_id: Result<Path<String>, PathRejection>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    let issue_id = path_int(issue_id)?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    let response = identity_state(&tx, user.id(), issue_id).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

/// `GET /api/v2/comicvine/issues/{issue_id}/metadata:corrections`.
pub async fn list_corrections(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    issue_id: Result<Path<String>, PathRejection>,
) -> Result<Json<MetadataCorrectionsResponse>, ApiError> {
    let issue_id = path_int(issue_id)?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    let response = corrections_list(&tx, user.id(), issue_id).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

/// `POST /api/v2/comicvine/issues/{issue_id}/identity:confirm` (Python
/// `save_confirmed_comicvine_identity`).
pub async fn confirm_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    issue_id: Result<Path<String>, PathRejection>,
    request: Result<Json<ConfirmIdentityRequest>, JsonRejection>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    let issue_id = path_int(issue_id)?;
    let Json(request) = request.map_err(|_| validation_failed())?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    crate::queue::lock_queue(&tx, user.id()).await?;
    lock_owned_issue(&tx, user.id(), issue_id).await?;
    link_confirmed(&tx, issue_id, request.comicvine_issue_id).await?;
    let response = identity_state(&tx, user.id(), issue_id).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

/// `POST /api/v2/comicvine/issues/{issue_id}/identity:replace` (Python
/// `replace_comicvine_identity`): the issue row is locked before any mapping
/// changes; the old confirmed ComicVine mappings become `rejected`.
pub async fn replace_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    issue_id: Result<Path<String>, PathRejection>,
    request: Result<Json<ReplaceIdentityRequest>, JsonRejection>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    let issue_id = path_int(issue_id)?;
    let Json(request) = request.map_err(|_| validation_failed())?;
    if reason_too_long(request.reason.as_deref()) {
        return Err(unprocessable("reason is too long"));
    }
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    crate::queue::lock_queue(&tx, user.id()).await?;
    lock_owned_issue(&tx, user.id(), issue_id).await?;
    // Python `reason or "replaced by user"`.
    let reason = request
        .reason
        .filter(|reason| !reason.is_empty())
        .unwrap_or_else(|| "replaced by user".to_owned());
    tx.execute(
        "UPDATE issue_external_identity_mappings m \
         SET status = 'rejected', rejection_reason = $2, updated_at = now() \
         FROM external_identities e \
         WHERE m.external_identity_id = e.id AND m.issue_id = $1 \
           AND m.status = 'confirmed' AND e.provider = 'comicvine'",
        &[&issue_id, &reason],
    )
    .await
    .map_err(db::query_error)?;
    link_confirmed(&tx, issue_id, request.comicvine_issue_id).await?;
    let response = identity_state(&tx, user.id(), issue_id).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

/// `DELETE /api/v2/comicvine/issues/{issue_id}/identity` (Python
/// `remove_comicvine_identity`): the confirmed mapping becomes `unresolved`.
pub async fn remove_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    issue_id: Result<Path<String>, PathRejection>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    let issue_id = path_int(issue_id)?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    crate::queue::lock_queue(&tx, user.id()).await?;
    lock_owned_issue(&tx, user.id(), issue_id).await?;
    let updated = tx
        .execute(
            "UPDATE issue_external_identity_mappings m \
             SET status = 'unresolved', evidence_source = NULL, confidence = NULL, \
                 updated_at = now() \
             FROM external_identities e \
             WHERE m.external_identity_id = e.id AND m.issue_id = $1 \
               AND m.status = 'confirmed' AND e.provider = 'comicvine'",
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?;
    if updated == 0 {
        return Err(bad_request(format!(
            "No confirmed ComicVine identity mapping found for issue {issue_id}"
        )));
    }
    let response = identity_state(&tx, user.id(), issue_id).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

/// `POST /api/v2/comicvine/issues/{issue_id}/metadata:correct` (Python
/// `apply_metadata_correction`). The provider value is Python
/// `str(metadata_json.get(field_name, "")) or None` over the issue's
/// confirmed identity metadata (#4636390879: `null` is `"None"`, booleans
/// `True`/`False`, objects and lists their Python repr).
pub async fn apply_correction(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    issue_id: Result<Path<String>, PathRejection>,
    request: Result<Json<MetadataCorrectionRequest>, JsonRejection>,
) -> Result<Json<MetadataCorrectionsResponse>, ApiError> {
    let issue_id = path_int(issue_id)?;
    let Json(request) = request.map_err(|_| validation_failed())?;
    if reason_too_long(request.reason.as_deref()) {
        return Err(unprocessable("reason is too long"));
    }
    // `field_name` is a VARCHAR(100) column: Python surfaces an oversized
    // name as an unhandled 500 from the INSERT; Rust rejects it up front.
    if request.field_name.chars().count() > 100 {
        return Err(unprocessable("field_name is too long"));
    }
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    owned_issue(&tx, user.id(), issue_id).await?;
    let provider_value = tx
        .query_opt(
            "SELECT json_typeof(e.metadata_json) = 'object', (e.metadata_json -> $2)::text \
             FROM external_identities e \
             JOIN issue_external_identity_mappings m ON m.external_identity_id = e.id \
             WHERE m.issue_id = $1 AND m.status = 'confirmed' \
             LIMIT 1",
            &[&issue_id, &request.field_name],
        )
        .await
        .map_err(db::query_error)?
        .filter(|row| row.get::<_, Option<bool>>(0) == Some(true))
        .and_then(|row| row.get::<_, Option<String>>(1))
        .and_then(|text| crate::python_text::python_str_of_json(&text))
        .filter(|value| !value.is_empty());
    tx.execute(
        "INSERT INTO issue_metadata_corrections \
            (issue_id, field_name, provider_value, canonical_value, provenance, \
             created_by, reverted_at, created_at, updated_at) \
         VALUES ($1, $2, $3, $4, 'user_correction', $5, NULL, now(), now())",
        &[
            &issue_id,
            &request.field_name,
            &provider_value,
            &request.canonical_value,
            &user.id(),
        ],
    )
    .await
    .map_err(db::query_error)?;
    let response = corrections_list(&tx, user.id(), issue_id).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

/// `POST /api/v2/comicvine/issues/{issue_id}/metadata:revert` (Python
/// `revert_metadata_correction`: a soft delete).
pub async fn revert_correction(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    issue_id: Result<Path<String>, PathRejection>,
    request: Result<Json<MetadataCorrectionRevertRequest>, JsonRejection>,
) -> Result<Json<MetadataCorrectionsResponse>, ApiError> {
    let issue_id = path_int(issue_id)?;
    let Json(request) = request.map_err(|_| validation_failed())?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    owned_issue(&tx, user.id(), issue_id).await?;
    let updated = tx
        .execute(
            "UPDATE issue_metadata_corrections c \
             SET reverted_at = now(), updated_at = now() \
             FROM issues i JOIN threads t ON t.id = i.thread_id \
             WHERE c.id = $1 AND c.issue_id = $2 AND i.id = c.issue_id \
               AND t.user_id = $3 AND c.reverted_at IS NULL",
            &[&request.correction_id, &issue_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    if updated == 0 {
        return Err(bad_request(format!(
            "Correction {} not found",
            request.correction_id
        )));
    }
    let response = corrections_list(&tx, user.id(), issue_id).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

/// `POST /api/v2/comicvine/issues/{issue_id}/metadata:refresh` (Python
/// `request_provider_refresh`): reports the confirmed ComicVine id; nothing
/// is written.
pub async fn refresh_metadata(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    issue_id: Result<Path<String>, PathRejection>,
) -> Result<Json<MetadataRefreshResponse>, ApiError> {
    let issue_id = path_int(issue_id)?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    owned_issue(&tx, user.id(), issue_id).await?;
    let comicvine_issue_id: Option<String> = tx
        .query_opt(
            "SELECT e.external_id \
             FROM external_identities e \
             JOIN issue_external_identity_mappings m ON m.external_identity_id = e.id \
             JOIN issues i ON i.id = m.issue_id \
             JOIN threads t ON t.id = i.thread_id \
             WHERE i.id = $1 AND t.user_id = $2 AND m.status = 'confirmed' \
               AND e.provider = 'comicvine' \
             LIMIT 1",
            &[&issue_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .map(|row| row.get(0));
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(MetadataRefreshResponse {
        issue_id,
        refreshed: comicvine_issue_id.is_some(),
        comicvine_issue_id,
    }))
}

// ---------------------------------------------------------------------------
// Single-issue import (chunk D).
// ---------------------------------------------------------------------------

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

/// Verify that a reading order belongs to the caller.
async fn owned_reading_order(
    tx: &Transaction<'_>,
    user: i32,
    order_id: i32,
) -> Result<(), ApiError> {
    let exists = tx
        .query_opt(
            "SELECT id FROM reading_orders WHERE id = $1 AND user_id = $2",
            &[&order_id, &user],
        )
        .await
        .map_err(db::query_error)?
        .is_some();
    if exists {
        Ok(())
    } else {
        Err(not_found(format!("Reading order {order_id} not found")))
    }
}

/// Shift an existing reading order and insert the new thread at `target_pos`
/// (Python `apply_insert`: a thread already in the order is moved, not
/// duplicated).
async fn insert_into_reading_order(
    tx: &Transaction<'_>,
    order_id: i32,
    thread_id: i32,
    target_pos: i32,
) -> Result<(), ApiError> {
    let current: Option<i32> = tx
        .query_opt(
            "SELECT position FROM reading_order_items \
             WHERE reading_order_id = $1 AND thread_id = $2 ORDER BY id LIMIT 1",
            &[&order_id, &thread_id],
        )
        .await
        .map_err(db::query_error)?
        .map(|row| row.get(0));
    if let Some(old_pos) = current {
        if old_pos < target_pos {
            tx.execute(
                "UPDATE reading_order_items SET position = position - 1 \
                 WHERE reading_order_id = $1 AND thread_id <> $2 \
                   AND position > $3 AND position <= $4",
                &[&order_id, &thread_id, &old_pos, &target_pos],
            )
            .await
            .map_err(db::query_error)?;
        } else if target_pos < old_pos {
            tx.execute(
                "UPDATE reading_order_items SET position = position + 1 \
                 WHERE reading_order_id = $1 AND thread_id <> $2 \
                   AND position >= $3 AND position < $4",
                &[&order_id, &thread_id, &target_pos, &old_pos],
            )
            .await
            .map_err(db::query_error)?;
        }
        tx.execute(
            "UPDATE reading_order_items SET position = $3 \
             WHERE reading_order_id = $1 AND thread_id = $2",
            &[&order_id, &thread_id, &target_pos],
        )
        .await
        .map_err(db::query_error)?;
    } else {
        tx.execute(
            "UPDATE reading_order_items SET position = position + 1 \
             WHERE reading_order_id = $1 AND position >= $2",
            &[&order_id, &target_pos],
        )
        .await
        .map_err(db::query_error)?;
        tx.execute(
            "INSERT INTO reading_order_items (reading_order_id, thread_id, position) \
             VALUES ($1, $2, $3)",
            &[&order_id, &thread_id, &target_pos],
        )
        .await
        .map_err(db::query_error)?;
    }
    Ok(())
}

/// `POST /api/v2/comicvine/issues:import` (Python `import_comicvine_issue`).
pub async fn import_issue(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    request: Result<Json<ImportIssueRequest>, JsonRejection>,
) -> Result<(StatusCode, Json<ImportIssueResponse>), ApiError> {
    let Json(request) = request.map_err(|_| validation_failed())?;
    // Python `title: Field(min_length=1, max_length=200)` bounds the raw
    // string; the service then stores `title.strip()` (possibly empty).
    let title = request.title.trim();
    if request.title.is_empty() || request.title.chars().count() > 200 {
        return Err(unprocessable("Invalid title"));
    }
    if request.comicvine_issue_id <= 0 {
        return Err(unprocessable("Invalid comicvine_issue_id"));
    }
    if request
        .issue_number
        .as_deref()
        .is_some_and(|n| n.chars().count() > 50)
    {
        return Err(unprocessable("Invalid issue number"));
    }
    for id in [
        request.reading_order_id,
        request.anchor_before_thread_id,
        request.anchor_after_thread_id,
    ]
    .into_iter()
    .flatten()
    {
        if id <= 0 {
            return Err(unprocessable("Invalid reading order anchor"));
        }
    }

    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    // Lock order: queue advisory lock first, then thread/issue row locks; it
    // also serializes the duplicate check and queue-position assignment.
    crate::queue::lock_queue(&tx, user.id()).await?;
    let external_id = request.comicvine_issue_id.to_string();
    if let Some(order_id) = request.reading_order_id {
        owned_reading_order(&tx, user.id(), order_id).await?;
    }
    let duplicate: Option<i32> = tx
        .query_opt(
            "SELECT i.id FROM external_identities e \
             JOIN issue_external_identity_mappings m ON m.external_identity_id = e.id \
             JOIN issues i ON i.id = m.issue_id \
             JOIN threads t ON t.id = i.thread_id \
             WHERE e.provider = 'comicvine' AND e.entity_type = 'issue' \
               AND e.external_id = $1 AND m.status = 'confirmed' AND t.user_id = $2 \
             ORDER BY (i.status = 'read') DESC, i.read_at ASC NULLS LAST, i.id \
             LIMIT 1",
            &[&external_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .map(|row| row.get(0));
    if let Some(existing_issue_id) = duplicate {
        let message = format!(
            "ComicVine issue {} already exists as issue {}",
            request.comicvine_issue_id, existing_issue_id
        );
        return Err(ApiError::StructuredDetail {
            status: StatusCode::CONFLICT,
            message: message.clone(),
            detail: serde_json::json!({
                "code": "duplicate_physical_issue",
                "comicvine_issue_id": request.comicvine_issue_id,
                "existing_issue_id": existing_issue_id,
                "message": message,
            }),
        });
    }

    let next_position: i32 = tx
        .query_one(
            "SELECT COALESCE(MAX(queue_position), 0) + 1 FROM threads WHERE user_id = $1",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?
        .get(0);
    let thread_row = tx
        .query_one(
            "INSERT INTO threads \
                (title, format, issues_remaining, total_issues, queue_position, status, \
                 user_id, created_at, is_test, is_blocked) \
             VALUES ($1, 'Comic', 1, 1, $2, 'active', $3, now(), false, false) \
             RETURNING id",
            &[&title, &next_position, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let thread_id: i32 = thread_row.get(0);
    let issue_row = tx
        .query_one(
            "INSERT INTO issues \
                (thread_id, issue_number, position, status, created_at) \
             VALUES ($1, $2, 1, 'unread', now()) RETURNING id",
            // Python `request.issue_number or "1"`: empty is "1" too (#4636390879).
            &[
                &thread_id,
                &request
                    .issue_number
                    .as_deref()
                    .filter(|number| !number.is_empty())
                    .unwrap_or("1"),
            ],
        )
        .await
        .map_err(db::query_error)?;
    let issue_id: i32 = issue_row.get(0);
    // Python `confirm_comicvine_identity` (no post-commit hydration on import).
    let external_identity_id =
        link_with_source(&tx, issue_id, request.comicvine_issue_id, "user_confirmed").await?;

    let mut response = ImportIssueResponse {
        thread_id,
        issue_id,
        external_identity_id,
        reading_order_id: None,
        position: None,
        total_items: None,
    };
    if let Some(order_id) = request.reading_order_id {
        let items = tx
            .query(
                "SELECT thread_id, position FROM reading_order_items \
                 WHERE reading_order_id = $1 ORDER BY position, id",
                &[&order_id],
            )
            .await
            .map_err(db::query_error)?;
        let mut positions = HashMap::new();
        for row in &items {
            positions.insert(row.get::<_, i32>(0), row.get::<_, i32>(1));
        }
        let target = resolve_anchored_position(
            &positions,
            request.anchor_before_thread_id,
            request.anchor_after_thread_id,
            items.len(),
        );
        insert_into_reading_order(&tx, order_id, thread_id, target).await?;
        response.reading_order_id = Some(order_id);
        response.position = Some(target);
        response.total_items = Some(items.len() as i32 + 1);
    }
    tx.commit().await.map_err(db::query_error)?;
    Ok((StatusCode::CREATED, Json(response)))
}

// ---------------------------------------------------------------------------
// OpenAPI documentation. These no-op functions feed the canonical generated
// v2 contract; handlers above never import documentation code at runtime.
// ---------------------------------------------------------------------------

#[utoipa::path(
    get,
    path = "/api/v2/comicvine/search/series",
    params(
        ("q" = String, Query, description = "Series title query"),
        ("limit" = Option<i32>, Query, description = "Maximum results (1-50, default 10)"),
        ("offset" = Option<i32>, Query, description = "Zero-based offset"),
    ),
    tag = "comicvine-v2",
    responses(
        (status = 200, description = "Paginated series search", body = ComicVineSeriesSearchResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 422, description = "Validation failed"),
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn search_series_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v2/comicvine/resolve",
    params(("input" = String, Query, description = "Search text or ComicVine URL")),
    tag = "comicvine-v2",
    responses(
        (status = 200, description = "Resolved input", body = ComicVineResolveResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 422, description = "Validation failed"),
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn resolve_input_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v2/comicvine/series/{comicvine_volume_id}/issues",
    params(
        ("comicvine_volume_id" = i32, Path, description = "ComicVine volume ID"),
        ("series_name" = Option<String>, Query, description = "Pre-fetched series name"),
    ),
    tag = "comicvine-v2",
    responses(
        (status = 200, description = "Volume issue roster", body = ComicVineSeriesIssuesResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 422, description = "Validation failed"),
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn comicvine_series_issues_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v2/comicvine/issues/{issue_id}/identity",
    params(("issue_id" = i32, Path, description = "ComicPile issue ID")),
    tag = "comicvine-v2",
    responses(
        (status = 200, description = "Owned identity state", body = IssueIdentityResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 404, description = "Issue not owned"),
        (status = 422, description = "Validation failed"),
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_issue_identity_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v2/comicvine/issues/{issue_id}/metadata:corrections",
    params(("issue_id" = i32, Path, description = "ComicPile issue ID")),
    tag = "comicvine-v2",
    responses(
        (status = 200, description = "Active corrections", body = MetadataCorrectionsResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 404, description = "Issue not owned"),
        (status = 422, description = "Validation failed"),
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_corrections_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/comicvine/issues/{issue_id}/identity:confirm",
    params(("issue_id" = i32, Path, description = "ComicPile issue ID")),
    request_body = ConfirmIdentityRequest,
    tag = "comicvine-v2",
    responses(
        (status = 200, description = "Confirmed identity state", body = IssueIdentityResponse),
        (status = 400, description = "Identity or correction conflict"),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 403, description = "CSRF validation failed"),
        (status = 404, description = "Issue not owned"),
        (status = 422, description = "Validation failed"),
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn confirm_identity_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/comicvine/issues/{issue_id}/identity:replace",
    params(("issue_id" = i32, Path, description = "ComicPile issue ID")),
    request_body = ReplaceIdentityRequest,
    tag = "comicvine-v2",
    responses(
        (status = 200, description = "Replaced identity state", body = IssueIdentityResponse),
        (status = 400, description = "Identity or correction conflict"),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 403, description = "CSRF validation failed"),
        (status = 404, description = "Issue not owned"),
        (status = 422, description = "Validation failed"),
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn replace_identity_documentation() {}

#[utoipa::path(
    delete,
    path = "/api/v2/comicvine/issues/{issue_id}/identity",
    params(("issue_id" = i32, Path, description = "ComicPile issue ID")),
    tag = "comicvine-v2",
    responses(
        (status = 200, description = "Identity removed", body = IssueIdentityResponse),
        (status = 400, description = "Identity or correction conflict"),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 403, description = "CSRF validation failed"),
        (status = 404, description = "Issue not owned"),
        (status = 422, description = "Validation failed"),
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn remove_identity_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/comicvine/issues/{issue_id}/metadata:correct",
    params(("issue_id" = i32, Path, description = "ComicPile issue ID")),
    request_body = MetadataCorrectionRequest,
    tag = "comicvine-v2",
    responses(
        (status = 200, description = "Active corrections after the write", body = MetadataCorrectionsResponse),
        (status = 400, description = "Identity or correction conflict"),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 403, description = "CSRF validation failed"),
        (status = 404, description = "Issue not owned"),
        (status = 422, description = "Validation failed"),
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn apply_correction_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/comicvine/issues/{issue_id}/metadata:revert",
    params(("issue_id" = i32, Path, description = "ComicPile issue ID")),
    request_body = MetadataCorrectionRevertRequest,
    tag = "comicvine-v2",
    responses(
        (status = 200, description = "Active corrections after the revert", body = MetadataCorrectionsResponse),
        (status = 400, description = "Identity or correction conflict"),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 403, description = "CSRF validation failed"),
        (status = 404, description = "Issue not owned"),
        (status = 422, description = "Validation failed"),
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn revert_correction_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/comicvine/issues/{issue_id}/metadata:refresh",
    params(("issue_id" = i32, Path, description = "ComicPile issue ID")),
    tag = "comicvine-v2",
    responses(
        (status = 200, description = "Confirmed identity to refresh", body = MetadataRefreshResponse),
        (status = 400, description = "Identity or correction conflict"),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 403, description = "CSRF validation failed"),
        (status = 404, description = "Issue not owned"),
        (status = 422, description = "Validation failed"),
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn refresh_metadata_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/comicvine/issues:import",
    request_body = ImportIssueRequest,
    tag = "comicvine-v2",
    responses(
        (status = 201, description = "Imported thread, issue and identity", body = ImportIssueResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 403, description = "CSRF validation failed"),
        (status = 404, description = "Reading order not found"),
        (status = 409, description = "ComicVine issue already exists for this reader"),
        (status = 422, description = "Validation failed"),
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn import_issue_documentation() {}

// ---------------------------------------------------------------------------
// Focused unit tests (no database or provider required).
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn parses_only_canonical_issue_and_volume_urls() {
        for (raw, expected) in [
            (
                "https://comicvine.gamespot.com/foo/4000-1154070/",
                Some(ParsedResource::Issue(1154070)),
            ),
            (
                "comicvine.gamespot.com/batman/4050-148476?x=1",
                Some(ParsedResource::Volume(148476)),
            ),
            (
                "http://www.comicvine.gamespot.com/issue/4000-42/",
                Some(ParsedResource::Issue(42)),
            ),
            (
                "HTTPS://User@ComicVine.GameSpot.com:443/x/4050-7#frag",
                Some(ParsedResource::Volume(7)),
            ),
            ("https://example.com/4000-42/", None),
            ("https://comicvine.gamespot.com/5000-42/", None),
            ("https://comicvine.gamespot.com/x/4000-/", None),
            ("https://comicvine.gamespot.com/x/4000-4a/", None),
            ("ftp://comicvine.gamespot.com/x/4000-42/", None),
            ("https://comicvine.gamespot.com", None),
            ("not a url", None),
            ("   ", None),
        ] {
            assert_eq!(parse_comicvine_url(raw), expected, "{raw}");
        }
    }

    #[test]
    fn looks_like_url_only_for_url_shaped_input() {
        assert!(looks_like_url("https://example.com"));
        assert!(looks_like_url("HTTP://example"));
        assert!(looks_like_url("httpfoo"));
        assert!(!looks_like_url("Batman 2026"));
        assert!(!looks_like_url("  "));
    }

    #[test]
    fn roster_deadline_applies_only_to_roster_backed_reads() {
        assert!(needs_roster_deadline("/api/v2/comicvine/resolve"));
        assert!(needs_roster_deadline("/api/v2/comicvine/series/42/issues"));
        assert!(!needs_roster_deadline("/api/v2/comicvine/series//issues"));
        assert!(!needs_roster_deadline(
            "/api/v2/comicvine/series/42/import-status"
        ));
        assert!(!needs_roster_deadline("/api/v2/comicvine/search/series"));
        assert!(!needs_roster_deadline("/api/v1/comicvine/series/42/issues"));
    }

    /// Golden values derived line by line from Python `_coerce_provider_int`
    /// and `isinstance(value, int)`.
    #[test]
    fn provider_ints_follow_the_python_rules() {
        for (value, coerced, strict) in [
            (json!(42), Some(42), Some(42)),
            (json!(42.0), Some(42), None),
            (json!(42.5), None, None),
            (json!("1999"), Some(1999), None),
            (json!(" 7 "), Some(7), None),
            (json!("-5"), None, None),
            (json!("+5"), None, None),
            (json!("n/a"), None, None),
            (json!(""), None, None),
            (json!(true), None, Some(1)),
            (json!(null), None, None),
        ] {
            assert_eq!(coerce_provider_int(Some(&value)), coerced, "coerce {value}");
            assert_eq!(python_int(Some(&value)), strict, "isinstance {value}");
        }
        assert_eq!(coerce_provider_int(None), None);
    }

    /// Python `str(issue_number) if issue_number is not None else None`
    /// (#4635845117): `null` is `None`, never the text `"null"`.
    #[test]
    fn issue_numbers_use_python_str_semantics() {
        for (value, expected) in [
            (json!(null), None),
            (json!(""), Some("")),
            (json!("12"), Some("12")),
            (json!(12), Some("12")),
            (json!(1.5), Some("1.5")),
            (json!(true), Some("True")),
        ] {
            let row = json!({"id": 1, "issue_number": value});
            assert_eq!(
                issue_candidate(&row).unwrap().issue_number.as_deref(),
                expected,
                "candidate {value}"
            );
            let issue = json!({"issue_number": value});
            assert_eq!(
                resolved_issue(&issue, 1).unwrap().issue_number.as_deref(),
                expected,
                "resolved {value}"
            );
        }
        assert_eq!(
            issue_candidate(&json!({"id": 1})).unwrap().issue_number,
            None
        );
    }

    #[test]
    fn search_rows_match_the_python_loop() {
        let row = search_result(&json!({
            "id": 7,
            "name": "Batman",
            "publisher": {"name": "DC"},
            "start_year": "2011",
            "count_of_issues": 52,
            "site_detail_url": "",
            "image": {"medium_url": "", "small_url": "small.jpg"}
        }))
        .expect("series result");
        assert_eq!(
            row,
            ComicVineSeriesResult {
                comicvine_volume_id: 7,
                name: "Batman".into(),
                publisher: Some("DC".into()),
                start_year: Some(2011),
                issue_count: Some(52),
                site_detail_url: Some(String::new()),
                image_url: Some("small.jpg".into()),
            }
        );
        // A string id, a missing name or a non-object row is skipped.
        assert_eq!(search_result(&json!({"id": "7", "name": "Batman"})), None);
        assert_eq!(search_result(&json!({"id": 7})), None);
        assert_eq!(search_result(&json!("row")), None);
        assert_eq!(
            search_result(&json!({"id": 7, "name": "", "publisher": "Image"}))
                .map(|row| (row.name, row.publisher)),
            Some((String::new(), Some("Image".into())))
        );
    }

    #[test]
    fn resolved_volumes_need_an_object_with_a_name() {
        let volume = resolved_volume(
            &json!({"name": "Saga", "image": {"medium_url": "", "super_url": "super.jpg"},
                    "site_detail_url": "", "start_year": "2012"}),
            9,
        )
        .expect("volume");
        assert_eq!(volume.comicvine_volume_id, 9);
        assert_eq!(volume.image_url.as_deref(), Some("super.jpg"));
        assert_eq!(volume.site_detail_url, None);
        assert_eq!(volume.start_year, Some(2012));
        assert_eq!(resolved_volume(&json!({"name": "  "}), 9), None);
        assert_eq!(resolved_volume(&json!({"name": 5}), 9), None);
        assert_eq!(resolved_volume(&json!([]), 9), None);
        assert_eq!(resolved_issue(&json!("issue"), 9), None);
    }

    #[test]
    fn roster_candidates_keep_empty_strings_like_python() {
        let candidate = issue_candidate(&json!({
            "id": 99,
            "issue_number": 12,
            "name": "",
            "cover_date": "",
            "store_date": null,
            "image": {"small_url": "", "thumb_url": "thumb.jpg"},
            "site_detail_url": ""
        }))
        .expect("issue candidate");
        assert_eq!(
            candidate,
            ComicVineIssueCandidate {
                comicvine_issue_id: 99,
                issue_number: Some("12".into()),
                name: Some(String::new()),
                cover_date: Some(String::new()),
                store_date: None,
                image_url: Some("thumb.jpg".into()),
                site_detail_url: Some(String::new()),
            }
        );
        assert_eq!(issue_candidate(&json!({"id": "99"})), None);
    }

    #[test]
    fn roster_pages_are_validated_like_python() {
        assert!(matches!(
            roster_page(&json!({"number_of_total_results": 5}), 9),
            Err(ProviderFailure::InvalidPayload)
        ));
        assert!(matches!(
            roster_page(&json!({"results": {}}), 9),
            Err(ProviderFailure::InvalidPayload)
        ));
        assert!(matches!(
            roster_page(&json!({"results": [{"id": 1, "volume": {"id": 10}}]}), 9),
            Err(ProviderFailure::InvalidPayload)
        ));
        assert!(matches!(
            roster_page(&json!({"results": [{"id": 1, "volume": {"id": "9"}}]}), 9),
            Err(ProviderFailure::InvalidPayload)
        ));
        let page = roster_page(
            &json!({"number_of_total_results": 3, "results": [
                {"id": 1, "volume": {"id": 9}}, {"id": 2, "volume": {"id": null}},
                {"id": 3, "volume": {"id": 9.0}}, {"id": 4}, "junk"]}),
            9,
        )
        .expect("valid page");
        assert_eq!(page.rows.len(), 4);
        assert_eq!(page.total, Some(3));
        let page = roster_page(&json!({"number_of_total_results": "3", "results": []}), 9)
            .expect("valid page");
        assert_eq!(page.total, None, "only an int total is kept");
    }

    #[test]
    fn search_queries_are_form_encoded() {
        assert_eq!(encode_query(" saga the&x=1 "), "+saga+the%26x%3D1+");
        assert_eq!(encode_query("ü"), "%C3%BC");
    }
}
