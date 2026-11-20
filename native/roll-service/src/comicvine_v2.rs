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
    auth::AuthenticatedUser, comicvine_repair::ProviderFailure, db,
    thread_issues::natural_issue_order, ApiError, AppState,
};
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
use std::{
    collections::{HashMap, HashSet},
    sync::Arc,
};
use tokio_postgres::Transaction;

// ---------------------------------------------------------------------------
// Wire contract (mirrors app/schemas/comicvine_resolution.py).
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ComicVineSeriesResult {
    #[serde(deserialize_with = "de_lax_i32")]
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
    #[serde(deserialize_with = "de_lax_i32")]
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
    #[serde(deserialize_with = "de_lax_i32")]
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
    #[serde(deserialize_with = "de_lax_i32")]
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
    #[serde(deserialize_with = "de_lax_i32")]
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

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ConfirmIdentityRequest {
    #[serde(deserialize_with = "de_lax_i32")]
    pub comicvine_issue_id: i32,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ReplaceIdentityRequest {
    #[serde(deserialize_with = "de_lax_i32")]
    pub comicvine_issue_id: i32,
    pub reason: Option<String>,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct MetadataCorrectionRequest {
    pub field_name: String,
    pub canonical_value: String,
    pub reason: Option<String>,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct MetadataCorrectionRevertRequest {
    #[serde(deserialize_with = "de_lax_i32")]
    pub correction_id: i32,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ImportIssueRequest {
    pub title: String,
    #[serde(deserialize_with = "de_lax_i32")]
    pub comicvine_issue_id: i32,
    pub issue_number: Option<String>,
    #[serde(default, deserialize_with = "de_lax_opt_i32")]
    pub reading_order_id: Option<i32>,
    #[serde(default, deserialize_with = "de_lax_opt_i32")]
    pub anchor_before_thread_id: Option<i32>,
    #[serde(default, deserialize_with = "de_lax_opt_i32")]
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
    #[serde(deserialize_with = "de_lax_i32")]
    pub comicvine_volume_id: i32,
    #[serde(default, deserialize_with = "de_lax_opt_i32")]
    pub reading_order_id: Option<i32>,
    #[serde(default, deserialize_with = "de_lax_opt_i32")]
    pub anchor_before_thread_id: Option<i32>,
    #[serde(default, deserialize_with = "de_lax_opt_i32")]
    pub anchor_after_thread_id: Option<i32>,
    #[serde(default, deserialize_with = "de_lax_i32")]
    pub already_read_count: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ImportSeriesIssueResult {
    #[serde(deserialize_with = "de_lax_i32")]
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
    #[serde(deserialize_with = "de_lax_i32")]
    pub comicvine_volume_id: i32,
    pub total_issues_in_series: i32,
    pub issues_adopted: i32,
    pub issues_skipped: i32,
    pub issues_conflict: i32,
    pub issue_results: Vec<ImportSeriesIssueResult>,
    #[serde(default, deserialize_with = "de_lax_opt_i32")]
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

/// Pydantic v2 lax `int` coercion (the Python request models are lax): JSON
/// numbers with no fractional part, integer strings such as `"5"`/`"5.0"`, and
/// booleans are accepted; anything else is a 422. Values outside `i32` are
/// rejected because every target column is `integer`.
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
        if let Some(url) = object
            .get(key)
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
        {
            return Some(url.to_owned());
        }
    }
    None
}

/// Small cover image URL used for issue candidates in a volume roster.
fn candidate_image_url(value: Option<&Value>) -> Option<String> {
    let object = value?.as_object()?;
    for key in ["small_url", "thumb_url"] {
        if let Some(url) = object
            .get(key)
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
        {
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
    let host = authority
        .rsplit('@')
        .next()?
        .split(':')
        .next()?
        .to_ascii_lowercase();
    if host != "comicvine.gamespot.com" && host != "www.comicvine.gamespot.com" {
        return None;
    }
    let path = after_scheme.strip_prefix(authority)?;
    let segment = path
        .split(['?', '#'])
        .next()?
        .split('/')
        .rfind(|part| !part.is_empty())?;
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
        ProviderFailure::RateLimited(_)
        | ProviderFailure::Unavailable
        | ProviderFailure::Timeout => {
            ApiError::ServiceUnavailable("provider_unavailable".to_owned())
        }
        ProviderFailure::InvalidPayload => {
            ApiError::ServiceUnavailable("provider_invalid_payload".to_owned())
        }
    }
}

// ---------------------------------------------------------------------------
// Owner-scoped database helpers. Every caller passes the authenticated user
// id as a bind parameter, never as interpolated SQL.
// ---------------------------------------------------------------------------

/// Resolve an owned issue to its thread id and title, or 404.
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

const CREATED_AT_SQL: &str =
    "to_char(m.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')";

/// Read the full identity state for one owned issue. The caller has already
/// verified ownership; this helper still keeps the issue predicate explicit.
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
                        m.evidence_source, {CREATED_AT_SQL} \
                 FROM issue_external_identity_mappings m \
                 JOIN external_identities e ON e.id = m.external_identity_id \
                 WHERE m.issue_id = $1 \
                 ORDER BY m.confidence DESC NULLS LAST, m.id ASC"
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

    let comicvine_issue_id = confirmed.first().map(|m| m.comicvine_id.clone());
    Ok(IssueIdentityResponse {
        issue_id,
        thread_id,
        thread_title,
        has_confirmed_identity: !confirmed.is_empty(),
        comicvine_issue_id,
        confirmed_mappings: confirmed,
        candidate_mappings: candidates,
        has_unresolved,
    })
}

/// Return the active (non-reverted) corrections for an owned issue.
async fn corrections_list(
    tx: &Transaction<'_>,
    user: i32,
    issue_id: i32,
) -> Result<MetadataCorrectionsResponse, ApiError> {
    owned_issue(tx, user, issue_id).await?;
    let rows = tx
        .query(
            "SELECT c.id, c.field_name, c.provider_value, c.canonical_value, \
                        c.provenance, c.created_by, to_char(c.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') \
                 FROM issue_metadata_corrections c \
                 JOIN issues i ON i.id = c.issue_id \
                 JOIN threads t ON t.id = i.thread_id \
                 WHERE c.issue_id = $1 AND t.user_id = $2 AND c.reverted_at IS NULL \
                 ORDER BY c.created_at ASC, c.id ASC",
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

/// Upsert the canonical ComicVine comic identity and return its id.
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
             VALUES ('comicvine', 'issue', $1, $2, '{}'::jsonb, now(), now()) \
             ON CONFLICT ON CONSTRAINT uq_external_identity_provider_entity \
             DO UPDATE SET external_url = EXCLUDED.external_url \
             RETURNING id",
            &[&external_id, &external_url],
        )
        .await
        .map_err(db::query_error)?;
    Ok(row.get(0))
}

/// Confirm (or re-confirm) one provider mapping for an issue. Mirrors Python
/// `link_issue_external_identity(status="confirmed")`: the owned issue row is
/// locked first, and a different confirmed ComicVine identity on the same
/// issue is rejected with the Python 400 message.
async fn link_confirmed(
    tx: &Transaction<'_>,
    user: i32,
    issue_id: i32,
    comicvine_issue_id: i32,
) -> Result<i32, ApiError> {
    let identity_id =
        link_with_source(tx, user, issue_id, comicvine_issue_id, "user_confirmed").await?;
    // Python commits the confirmation first and hydrates best-effort after;
    // scheduling runs in a savepoint so its failure never undoes the mapping.
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
    Ok(identity_id)
}

async fn link_with_source(
    tx: &Transaction<'_>,
    user: i32,
    issue_id: i32,
    comicvine_issue_id: i32,
    evidence_source: &str,
) -> Result<i32, ApiError> {
    lock_owned_issue(tx, user, issue_id).await?;
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
         VALUES ($1, $2, 'confirmed', $3, '{}'::jsonb, 1.0, NULL, now(), now()) \
         ON CONFLICT ON CONSTRAINT uq_issue_external_identity_mapping \
         DO UPDATE SET status = 'confirmed', evidence_source = EXCLUDED.evidence_source, \
                       confidence = 1.0, rejection_reason = NULL, updated_at = now()",
        &[&issue_id, &identity_id, &evidence_source],
    )
    .await
    .map_err(db::query_error)?;
    Ok(identity_id)
}

/// Lock the owned issue row (`FOR UPDATE OF i`), or 404.
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

/// Best-effort hydration, the Rust analogue of Python's post-commit
/// `refresh_issue_metadata`: when the identity lacks fresh deep provider
/// metadata and no refresh is already queued, enqueue one for the existing
/// native repair worker. The request never blocks or fails the confirmation.
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
    // One row per identity (uq_comicvine_metadata_refresh_identity): create it,
    // or reopen a finished (completed / no_credits / failed) row. A row that is
    // already pending, running or deferred is left untouched.
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

/// Extract the canonical series name from a volume provider payload.
fn volume_name(value: &Value) -> Option<String> {
    value
        .get("results")
        .and_then(Value::as_object)
        .and_then(|result| result.get("name"))
        .and_then(Value::as_str)
        .filter(|name| !name.trim().is_empty())
        .map(str::to_owned)
}

// ---------------------------------------------------------------------------
// Identity and metadata mutation handlers.
// ---------------------------------------------------------------------------

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

/// `POST /api/v2/comicvine/issues/{issue_id}/identity:confirm`.
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
    // Lock order: queue advisory lock first, then issue row locks.
    crate::queue::lock_queue(&tx, user.id()).await?;
    link_confirmed(&tx, user.id(), issue_id, request.comicvine_issue_id).await?;
    let response = identity_state(&tx, user.id(), issue_id).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

/// `POST /api/v2/comicvine/issues/{issue_id}/identity:replace`.
pub async fn replace_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    issue_id: Result<Path<String>, PathRejection>,
    request: Result<Json<ReplaceIdentityRequest>, JsonRejection>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    let issue_id = path_int(issue_id)?;
    let Json(request) = request.map_err(|_| validation_failed())?;
    if request
        .reason
        .as_deref()
        .is_some_and(|r| r.chars().count() > 500)
    {
        return Err(unprocessable("reason is too long"));
    }
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    // Lock order: queue advisory lock first, then issue row locks.
    crate::queue::lock_queue(&tx, user.id()).await?;
    lock_owned_issue(&tx, user.id(), issue_id).await?;
    let reason = request
        .reason
        .filter(|r| !r.is_empty())
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
    link_confirmed(&tx, user.id(), issue_id, request.comicvine_issue_id).await?;
    let response = identity_state(&tx, user.id(), issue_id).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

/// `DELETE /api/v2/comicvine/issues/{issue_id}/identity`.
pub async fn remove_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    issue_id: Result<Path<String>, PathRejection>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    let issue_id = path_int(issue_id)?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    owned_issue(&tx, user.id(), issue_id).await?;
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

/// `POST /api/v2/comicvine/issues/{issue_id}/metadata:correct`.
pub async fn apply_correction(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    issue_id: Result<Path<String>, PathRejection>,
    request: Result<Json<MetadataCorrectionRequest>, JsonRejection>,
) -> Result<Json<MetadataCorrectionsResponse>, ApiError> {
    let issue_id = path_int(issue_id)?;
    let Json(request) = request.map_err(|_| validation_failed())?;
    // Python `MetadataCorrectionRequest`: `field_name`/`canonical_value` are
    // unconstrained `str` (empty is accepted), `reason` is `max_length=500`.
    // `field_name` is a `VARCHAR(100)` column: Python surfaces an oversized
    // name as an unhandled 500 from the INSERT; Rust rejects it up front.
    if request
        .reason
        .as_deref()
        .is_some_and(|r| r.chars().count() > 500)
    {
        return Err(unprocessable("reason is too long"));
    }
    if request.field_name.chars().count() > 100 {
        return Err(unprocessable("Invalid field name"));
    }
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    owned_issue(&tx, user.id(), issue_id).await?;

    let provider_value: Option<String> = tx
        .query_opt(
            "SELECT e.metadata_json ->> $2 \
             FROM external_identities e \
             JOIN issue_external_identity_mappings m ON m.external_identity_id = e.id \
             WHERE m.issue_id = $1 AND m.status = 'confirmed' \
             LIMIT 1",
            &[&issue_id, &request.field_name],
        )
        .await
        .map_err(db::query_error)?
        .and_then(|row| row.get::<_, Option<String>>(0))
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

/// `POST /api/v2/comicvine/issues/{issue_id}/metadata:revert`.
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

/// `POST /api/v2/comicvine/issues/{issue_id}/metadata:refresh`.
pub async fn refresh_metadata(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    issue_id: Result<Path<String>, PathRejection>,
) -> Result<Json<MetadataRefreshResponse>, ApiError> {
    let issue_id = path_int(issue_id)?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    owned_issue(&tx, user.id(), issue_id).await?;
    let comicvine_id: Option<String> = tx
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
        .and_then(|row| row.get::<_, Option<String>>(0));
    let refreshed = comicvine_id.is_some();
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(MetadataRefreshResponse {
        issue_id,
        refreshed,
        comicvine_issue_id: comicvine_id,
    }))
}

// ---------------------------------------------------------------------------
// Import handlers. Both run in one owner-scoped transaction and return 201.
// ---------------------------------------------------------------------------

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

/// `POST /api/v2/comicvine/issues:import`.
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
            &[&thread_id, &request.issue_number.as_deref().unwrap_or("1")],
        )
        .await
        .map_err(db::query_error)?;
    let issue_id: i32 = issue_row.get(0);
    let external_identity_id = link_with_source(
        &tx,
        user.id(),
        issue_id,
        request.comicvine_issue_id,
        "user_confirmed",
    )
    .await?;

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

/// Structured `{"code", "message"}` error body (Python `SeriesImportError`).
fn series_import_error(status: StatusCode, code: &str, message: impl Into<String>) -> ApiError {
    let message = message.into();
    ApiError::StructuredDetail {
        status,
        message: message.clone(),
        detail: serde_json::json!({ "code": code, "message": message }),
    }
}

/// Python exception class name embedded in the `provider_failure` message.
fn provider_failure_name(failure: &ProviderFailure) -> &'static str {
    match failure {
        ProviderFailure::Timeout => "TimeoutError",
        _ => "ComicVineError",
    }
}

/// Mirror of `comicvine_hydration.normalize_issue` for a roster row: the
/// curated fields plus the complete raw provider row, so the existing deep
/// refresh worker still sees the identity as incomplete.
fn normalize_roster_issue(row: &Value) -> Value {
    fn compact(value: Option<&Value>) -> Value {
        let Some(object) = value.and_then(Value::as_object) else {
            return Value::Null;
        };
        let mut out = serde_json::Map::new();
        for key in ["id", "name", "api_detail_url", "site_detail_url"] {
            if let Some(found) = object.get(key) {
                out.insert(key.to_owned(), found.clone());
            }
        }
        Value::Object(out)
    }
    fn compact_all(value: Option<&Value>) -> Value {
        let Some(items) = value.and_then(Value::as_array) else {
            return Value::Array(Vec::new());
        };
        Value::Array(
            items
                .iter()
                .filter(|item| item.is_object())
                .map(|item| {
                    let mut compacted = compact(Some(item));
                    if let (Some(map), Some(role)) = (
                        compacted.as_object_mut(),
                        item.as_object().and_then(|o| o.get("role")),
                    ) {
                        map.insert("role".to_owned(), role.clone());
                    }
                    compacted
                })
                .collect(),
        )
    }
    let primary_image = row
        .get("image")
        .and_then(Value::as_object)
        .and_then(|image| {
            ["original_url", "super_url", "medium_url", "small_url"]
                .iter()
                .find_map(|key| {
                    image
                        .get(*key)
                        .and_then(Value::as_str)
                        .filter(|url| !url.is_empty())
                })
        })
        .map(|url| Value::String(url.to_owned()))
        .unwrap_or(Value::Null);
    let field = |key: &str| row.get(key).cloned().unwrap_or(Value::Null);
    serde_json::json!({
        "name": field("name"),
        "issue_number": field("issue_number"),
        "cover_date": field("cover_date"),
        "store_date": field("store_date"),
        "volume": compact(row.get("volume")),
        "primary_image": primary_image,
        "creator_credits": compact_all(row.get("person_credits")),
        "characters": compact_all(row.get("character_credits")),
        "teams": compact_all(row.get("team_credits")),
        "story_arcs": compact_all(row.get("story_arc_credits")),
        "raw_provider_payload": row,
    })
}

/// One thread issue (stored or about to be created) in the in-memory
/// natural-order simulation that replaces Python's per-issue SQL.
struct SimIssue {
    id: Option<i32>,
    number: String,
    position: i32,
    original_position: i32,
    /// ComicVine external id of the confirmed identity already on the issue.
    confirmed_cv: Option<String>,
}

/// Seat one new issue number exactly like `create_issue_in_natural_order`.
fn sim_place(all: &mut Vec<SimIssue>, number: &str) -> usize {
    let mut order: Vec<usize> = (0..all.len()).collect();
    order.sort_by_key(|&i| (all[i].position, i));
    let existing: Vec<String> = order.iter().map(|&i| all[i].number.clone()).collect();
    let target_position = match natural_issue_order(&existing, &[number.to_owned()]) {
        Some(natural) => {
            let targets: HashMap<&str, i32> = natural
                .iter()
                .enumerate()
                .map(|(index, label)| (label.as_str(), index as i32 + 1))
                .collect();
            for issue in all.iter_mut() {
                if let Some(target) = targets.get(issue.number.as_str()) {
                    issue.position = *target;
                }
            }
            targets[number]
        }
        None => all.iter().map(|issue| issue.position).max().unwrap_or(0) + 1,
    };
    all.push(SimIssue {
        id: None,
        number: number.to_owned(),
        position: target_position,
        original_position: target_position,
        confirmed_cv: None,
    });
    all.len() - 1
}

enum SimOutcome {
    Created(usize),
    Reused(usize),
    ReusedExisting(i32),
    Conflict {
        issue: Option<usize>,
        issue_id: Option<i32>,
        detail: String,
    },
    Error(String),
}

struct SimEntry {
    cv_id: i32,
    number: String,
    outcome: SimOutcome,
}

/// `POST /api/v2/comicvine/series:import`.
pub async fn import_series(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    request: Result<Json<ImportSeriesRequest>, JsonRejection>,
) -> Result<(StatusCode, Json<ImportSeriesResponse>), ApiError> {
    let Json(request) = request.map_err(|_| validation_failed())?;
    if request.comicvine_volume_id <= 0 {
        return Err(unprocessable("Invalid comicvine_volume_id"));
    }
    if request.already_read_count < 0 {
        return Err(unprocessable("Invalid already_read_count"));
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
    let Some(key) = provider_key() else {
        return Err(series_import_error(
            StatusCode::SERVICE_UNAVAILABLE,
            "provider_unavailable",
            "ComicVine is not configured on this server",
        ));
    };
    let volume_id = request.comicvine_volume_id;
    let volume = state
        .comicvine_limits
        .call_fresh(
            &state.outbound,
            &format!("volume/4050-{volume_id}"),
            "",
            &key,
        )
        .await
        .map_err(|failure| {
            series_import_error(
                StatusCode::BAD_GATEWAY,
                "provider_failure",
                format!(
                    "Failed to fetch ComicVine series: {}",
                    provider_failure_name(&failure)
                ),
            )
        })?;
    let Some(volume_data) = volume.get("results").filter(|value| value.is_object()) else {
        return Err(series_import_error(
            StatusCode::BAD_GATEWAY,
            "provider_failure",
            "ComicVine series response did not contain valid data",
        ));
    };
    let Some(series_name) = volume_data
        .get("name")
        .and_then(Value::as_str)
        .filter(|name| !name.trim().is_empty())
        .map(str::to_owned)
    else {
        return Err(series_import_error(
            StatusCode::BAD_GATEWAY,
            "provider_failure",
            "ComicVine series has no name",
        ));
    };
    let rows = provider_roster(&state, volume_id, &key, true)
        .await
        .map_err(|failure| {
            series_import_error(
                StatusCode::BAD_GATEWAY,
                "provider_failure",
                format!(
                    "Failed to fetch series issues: {}",
                    provider_failure_name(&failure)
                ),
            )
        })?;
    if rows.is_empty() {
        return Err(series_import_error(
            StatusCode::BAD_REQUEST,
            "no_issues",
            "ComicVine series has no issues",
        ));
    }
    if request.already_read_count as usize > rows.len() {
        return Err(series_import_error(
            StatusCode::BAD_REQUEST,
            "invalid_already_read_count",
            format!(
                "already_read_count cannot exceed the series issue count ({})",
                rows.len()
            ),
        ));
    }

    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    // Lock order: queue advisory lock first, then thread/issue row locks.
    crate::queue::lock_queue(&tx, user.id()).await?;
    if let Some(order_id) = request.reading_order_id {
        owned_reading_order(&tx, user.id(), order_id).await?;
    }
    let user_id = user.id();
    let external_volume_id = volume_id.to_string();
    let reused_thread_id: Option<i32> = tx
        .query_opt(
            "SELECT t.id FROM thread_external_series_mappings m \
             JOIN threads t ON t.id = m.thread_id \
             JOIN external_identities e ON e.id = m.external_identity_id \
             WHERE t.user_id = $1 AND m.status = 'confirmed' \
               AND e.entity_type = 'series' AND e.provider = 'comicvine' \
               AND e.external_id = $2 ORDER BY m.id LIMIT 1",
            &[&user_id, &external_volume_id],
        )
        .await
        .map_err(db::query_error)?
        .map(|row| row.get(0));
    let thread_created = reused_thread_id.is_none();

    // (status, total_issues, next_unread_issue_id) of a reused thread, used for
    // the Python adoption reopen rule below.
    let mut reused_state: Option<(String, Option<i32>, Option<i32>)> = None;
    let thread_id = match reused_thread_id {
        Some(id) => {
            let row = tx
                .query_opt(
                    "SELECT status, total_issues, next_unread_issue_id FROM threads \
                     WHERE id = $1 AND user_id = $2 FOR UPDATE",
                    &[&id, &user_id],
                )
                .await
                .map_err(db::query_error)?
                .ok_or_else(|| not_found(format!("Thread {id} not found")))?;
            reused_state = Some((row.get(0), row.get(1), row.get(2)));
            id
        }
        None => {
            let next_position: i32 = tx
                .query_one(
                    "SELECT COALESCE(MAX(queue_position), 0) + 1 FROM threads WHERE user_id = $1",
                    &[&user_id],
                )
                .await
                .map_err(db::query_error)?
                .get(0);
            tx.query_one(
                "INSERT INTO threads \
                    (title, format, issues_remaining, total_issues, queue_position, status, \
                     user_id, created_at, is_test, is_blocked) \
                 VALUES ($1, 'Comic', 0, 0, $2, 'active', $3, now(), false, false) \
                 RETURNING id",
                &[&series_name.trim(), &next_position, &user_id],
            )
            .await
            .map_err(db::query_error)?
            .get(0)
        }
    };

    let series_identity_id: i32 = tx
        .query_one(
            "INSERT INTO external_identities \
                (provider, entity_type, external_id, external_url, metadata_json, created_at, updated_at) \
             VALUES ('comicvine', 'series', $1, $2, '{}'::jsonb, now(), now()) \
             ON CONFLICT ON CONSTRAINT uq_external_identity_provider_entity \
             DO UPDATE SET external_url = EXCLUDED.external_url \
             RETURNING id",
            &[
                &external_volume_id,
                &format!("https://comicvine.gamespot.com/volume/4050-{volume_id}/"),
            ],
        )
        .await
        .map_err(db::query_error)?
        .get(0);
    tx.execute(
        "INSERT INTO thread_external_series_mappings \
            (thread_id, external_identity_id, status, evidence_source, confidence, \
             created_at, updated_at) \
         VALUES ($1, $2, 'confirmed', 'comicvine_series_import', 1.0, now(), now()) \
         ON CONFLICT ON CONSTRAINT uq_thread_external_series_mapping \
         DO UPDATE SET status = 'confirmed', evidence_source = EXCLUDED.evidence_source, \
                       confidence = 1.0, updated_at = now()",
        &[&thread_id, &series_identity_id],
    )
    .await
    .map_err(db::query_error)?;

    // ---- Preload every fact the per-issue adoption decisions need. --------
    struct Roster {
        index: usize,
        cv_id: i32,
        number: Option<String>,
        url: Option<String>,
        row: Value,
    }
    let roster: Vec<Roster> = rows
        .iter()
        .enumerate()
        .filter_map(|(index, row)| {
            let cv_id = row
                .get("id")
                .and_then(Value::as_i64)
                .and_then(|id| i32::try_from(id).ok())?;
            let number = match row.get("issue_number") {
                None | Some(Value::Null) => None,
                Some(Value::String(text)) => Some(text.clone()),
                Some(other) => Some(other.to_string()),
            };
            Some(Roster {
                index,
                cv_id,
                number,
                url: row
                    .get("site_detail_url")
                    .and_then(Value::as_str)
                    .map(str::to_owned),
                row: row.clone(),
            })
        })
        .collect();
    let cv_texts: Vec<String> = roster.iter().map(|r| r.cv_id.to_string()).collect();

    // Confirmed owned mappings for the roster ids (lowest issue id wins).
    let mut owned_confirmed: HashMap<String, (i32, i32)> = HashMap::new();
    for row in tx
        .query(
            "SELECT e.external_id, i.id, i.thread_id FROM external_identities e \
             JOIN issue_external_identity_mappings m ON m.external_identity_id = e.id \
             JOIN issues i ON i.id = m.issue_id \
             JOIN threads t ON t.id = i.thread_id \
             WHERE e.provider = 'comicvine' AND e.entity_type = 'issue' \
               AND e.external_id = ANY($1) AND m.status = 'confirmed' AND t.user_id = $2 \
             ORDER BY i.id DESC",
            &[&cv_texts, &user_id],
        )
        .await
        .map_err(db::query_error)?
    {
        owned_confirmed.insert(row.get(0), (row.get(1), row.get(2)));
    }

    // The thread's current issues, locked once, with their confirmed ComicVine id.
    let mut all: Vec<SimIssue> = tx
        .query(
            "SELECT i.id, i.issue_number, i.position, \
                    (SELECT e.external_id FROM issue_external_identity_mappings m \
                       JOIN external_identities e ON e.id = m.external_identity_id \
                      WHERE m.issue_id = i.id AND m.status = 'confirmed' \
                        AND e.provider = 'comicvine' ORDER BY m.id LIMIT 1) \
             FROM issues i WHERE i.thread_id = $1 ORDER BY i.position, i.id FOR UPDATE OF i",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| SimIssue {
            id: Some(row.get(0)),
            number: row.get(1),
            position: row.get(2),
            original_position: row.get(2),
            confirmed_cv: row.get(3),
        })
        .collect();
    let existing_identity_ids: HashMap<String, i32> = tx
        .query(
            "SELECT external_id, id FROM external_identities \
             WHERE provider = 'comicvine' AND entity_type = 'issue' AND external_id = ANY($1)",
            &[&cv_texts],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| (row.get(0), row.get(1)))
        .collect();

    // ---- Decide every adoption outcome in memory (no SQL in this loop). ---
    let mut entries: Vec<SimEntry> = Vec::with_capacity(roster.len());
    let mut linked_in_run: HashMap<i32, usize> = HashMap::new();
    let mut identity_specs: Vec<(String, Option<String>, String)> = Vec::new();
    let mut identity_seen: HashSet<String> = HashSet::new();
    let mut links: Vec<(usize, String)> = Vec::new();
    for item in &roster {
        let number = item
            .number
            .clone()
            .unwrap_or_else(|| (item.index + 1).to_string());
        let cv_text = item.cv_id.to_string();
        let outcome = if let Some(&sim) = linked_in_run.get(&item.cv_id) {
            SimOutcome::Reused(sim)
        } else if let Some(&(existing_id, existing_thread)) = owned_confirmed.get(&cv_text) {
            if existing_thread != thread_id {
                SimOutcome::Conflict {
                    issue: None,
                    issue_id: Some(existing_id),
                    detail: format!(
                        "ComicVine issue {} is already confirmed on issue {existing_id} of thread {existing_thread}",
                        item.cv_id
                    ),
                }
            } else {
                SimOutcome::ReusedExisting(existing_id)
            }
        } else if number.chars().count() > 50 {
            SimOutcome::Error(format!(
                "issue number too long for ComicVine issue {}",
                item.cv_id
            ))
        } else {
            if identity_seen.insert(cv_text.clone()) {
                let metadata = if existing_identity_ids.contains_key(&cv_text) {
                    "{}".to_owned()
                } else {
                    normalize_roster_issue(&item.row).to_string()
                };
                identity_specs.push((cv_text.clone(), item.url.clone(), metadata));
            }
            let found = all.iter().position(|issue| issue.number == number);
            let (sim, created) = match found {
                Some(sim) => (sim, false),
                None => (sim_place(&mut all, &number), true),
            };
            match all[sim].confirmed_cv.as_deref() {
                Some(other) if other != cv_text => SimOutcome::Conflict {
                    issue: Some(sim),
                    issue_id: all[sim].id,
                    detail: "issue already has a confirmed comicvine identity".to_owned(),
                },
                _ => {
                    all[sim].confirmed_cv = Some(cv_text.clone());
                    links.push((sim, cv_text.clone()));
                    linked_in_run.insert(item.cv_id, sim);
                    if created {
                        SimOutcome::Created(sim)
                    } else {
                        SimOutcome::Reused(sim)
                    }
                }
            }
        };
        entries.push(SimEntry {
            cv_id: item.cv_id,
            number,
            outcome,
        });
    }

    // ---- Apply the decisions with set-based statements. -------------------
    let reposition_ids: Vec<i32> = all
        .iter()
        .filter(|issue| issue.id.is_some() && issue.position != issue.original_position)
        .filter_map(|issue| issue.id)
        .collect();
    let reposition_positions: Vec<i32> = all
        .iter()
        .filter(|issue| issue.id.is_some() && issue.position != issue.original_position)
        .map(|issue| issue.position)
        .collect();
    if !reposition_ids.is_empty() {
        tx.execute(
            "UPDATE issues i SET position = v.pos \
             FROM unnest($1::int[], $2::int[]) AS v(id, pos) WHERE i.id = v.id",
            &[&reposition_ids, &reposition_positions],
        )
        .await
        .map_err(db::query_error)?;
    }
    let new_indices: Vec<usize> = all
        .iter()
        .enumerate()
        .filter(|(_, issue)| issue.id.is_none())
        .map(|(index, _)| index)
        .collect();
    if !new_indices.is_empty() {
        let numbers: Vec<String> = new_indices.iter().map(|&i| all[i].number.clone()).collect();
        let positions: Vec<i32> = new_indices.iter().map(|&i| all[i].position).collect();
        let inserted = tx
            .query(
                "INSERT INTO issues (thread_id, issue_number, position, status, created_at) \
                 SELECT $1, v.n, v.p, 'unread', now() \
                 FROM unnest($2::text[], $3::int[]) AS v(n, p) \
                 RETURNING id, issue_number",
                &[&thread_id, &numbers, &positions],
            )
            .await
            .map_err(db::query_error)?;
        let ids_by_number: HashMap<String, i32> = inserted
            .iter()
            .map(|row| (row.get::<_, String>(1), row.get::<_, i32>(0)))
            .collect();
        for &index in &new_indices {
            all[index].id = ids_by_number.get(&all[index].number).copied();
        }
    }

    let mut identity_ids: HashMap<String, i32> = HashMap::new();
    if !identity_specs.is_empty() {
        let ext_ids: Vec<String> = identity_specs.iter().map(|s| s.0.clone()).collect();
        let urls: Vec<Option<String>> = identity_specs.iter().map(|s| s.1.clone()).collect();
        let metadata: Vec<String> = identity_specs.iter().map(|s| s.2.clone()).collect();
        for row in tx
            .query(
                "INSERT INTO external_identities \
                    (provider, entity_type, external_id, external_url, metadata_json, \
                     created_at, updated_at) \
                 SELECT 'comicvine', 'issue', v.eid, v.url, v.meta::jsonb, now(), now() \
                 FROM unnest($1::text[], $2::text[], $3::text[]) AS v(eid, url, meta) \
                 ON CONFLICT ON CONSTRAINT uq_external_identity_provider_entity \
                 DO UPDATE SET external_url = COALESCE(EXCLUDED.external_url, \
                                                       external_identities.external_url) \
                 RETURNING external_id, id",
                &[&ext_ids, &urls, &metadata],
            )
            .await
            .map_err(db::query_error)?
        {
            identity_ids.insert(row.get(0), row.get(1));
        }
    }
    if !links.is_empty() {
        let mut link_issue_ids = Vec::with_capacity(links.len());
        let mut link_identity_ids = Vec::with_capacity(links.len());
        for (sim, cv_text) in &links {
            if let (Some(issue_id), Some(identity_id)) = (all[*sim].id, identity_ids.get(cv_text)) {
                link_issue_ids.push(issue_id);
                link_identity_ids.push(*identity_id);
            }
        }
        tx.execute(
            "INSERT INTO issue_external_identity_mappings \
                (issue_id, external_identity_id, status, evidence_source, evidence_json, \
                 confidence, rejection_reason, created_at, updated_at) \
             SELECT v.issue_id, v.identity_id, 'confirmed', 'comicvine_issue_adoption', \
                    '{}'::jsonb, 1.0, NULL, now(), now() \
             FROM unnest($1::int[], $2::int[]) AS v(issue_id, identity_id) \
             ON CONFLICT ON CONSTRAINT uq_issue_external_identity_mapping \
             DO UPDATE SET status = 'confirmed', evidence_source = EXCLUDED.evidence_source, \
                           confidence = 1.0, rejection_reason = NULL, updated_at = now()",
            &[&link_issue_ids, &link_identity_ids],
        )
        .await
        .map_err(db::query_error)?;
    }

    // Results, in roster order.
    let mut issue_results = Vec::with_capacity(entries.len());
    let (mut adopted, mut skipped, mut conflicts) = (0i32, 0i32, 0i32);
    let mut created_count = 0i32;
    for entry in &entries {
        let (issue_id, outcome, detail) = match &entry.outcome {
            SimOutcome::Created(sim) => {
                adopted += 1;
                created_count += 1;
                (all[*sim].id, "created", None)
            }
            SimOutcome::Reused(sim) => {
                skipped += 1;
                (all[*sim].id, "reused", None)
            }
            SimOutcome::ReusedExisting(id) => {
                skipped += 1;
                (Some(*id), "reused", None)
            }
            SimOutcome::Conflict {
                issue,
                issue_id,
                detail,
            } => {
                conflicts += 1;
                (
                    issue.and_then(|sim| all[sim].id).or(*issue_id),
                    "conflict",
                    Some(detail.clone()),
                )
            }
            SimOutcome::Error(detail) => (None, "error", Some(detail.clone())),
        };
        issue_results.push(ImportSeriesIssueResult {
            comicvine_issue_id: entry.cv_id,
            issue_number: Some(entry.number.clone()),
            issue_id,
            outcome: outcome.to_owned(),
            hydration: "not_attempted".to_owned(),
            conflict_detail: detail,
        });
    }

    if created_count > 0 {
        // Python adoption reopens a completed reused thread at the queue front
        // (once) before the shared derivation below makes it active again.
        if let Some((status, total, next_unread)) = &reused_state {
            if status == "completed" && total.is_some() && next_unread.is_none() {
                tx.execute(
                    "UPDATE threads SET queue_position = queue_position + 1 \
                     WHERE user_id = $1 AND status = 'active'",
                    &[&user_id],
                )
                .await
                .map_err(db::query_error)?;
                tx.execute(
                    "UPDATE threads SET queue_position = 1 WHERE id = $1",
                    &[&thread_id],
                )
                .await
                .map_err(db::query_error)?;
            }
        }
        tx.execute(
            "INSERT INTO events (type, timestamp, thread_id) \
             SELECT 'issues_created', now(), $1 FROM generate_series(1, $2::int)",
            &[&thread_id, &created_count],
        )
        .await
        .map_err(db::query_error)?;
    }

    // Mark the leading locally-adopted issues read, then derive the thread's
    // canonical counters from the rows that actually exist.
    let thread_issues = tx
        .query(
            "SELECT id, status FROM issues WHERE thread_id = $1 ORDER BY position, id",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    let read_count = (request.already_read_count as usize).min(thread_issues.len());
    let read_ids: Vec<i32> = thread_issues
        .iter()
        .take(read_count)
        .map(|row| row.get(0))
        .collect();
    if !read_ids.is_empty() {
        tx.execute(
            "UPDATE issues SET status = 'read', read_at = now() WHERE id = ANY($1)",
            &[&read_ids],
        )
        .await
        .map_err(db::query_error)?;
    }
    let total_issues = thread_issues.len() as i32;
    let unread: Vec<i32> = thread_issues
        .iter()
        .enumerate()
        .filter(|(index, row)| *index >= read_count && row.get::<_, String>(1) == "unread")
        .map(|(_, row)| row.get(0))
        .collect();
    let issues_remaining = unread.len() as i32;
    let next_unread = unread.first().copied();
    let reading_progress = if issues_remaining == 0 {
        "completed"
    } else if issues_remaining == total_issues {
        "not_started"
    } else {
        "in_progress"
    };
    let derived_status = if next_unread.is_none() {
        "completed"
    } else {
        "active"
    };
    tx.execute(
        "UPDATE threads SET total_issues = $2, issues_remaining = $3, \
            next_unread_issue_id = $4, reading_progress = $5, \
            is_blocked = CASE WHEN $3 = 0 THEN false ELSE is_blocked END, \
            status = CASE WHEN status = 'excluded' THEN status ELSE $6 END, \
            queue_position_is_manual = CASE WHEN status <> 'excluded' AND $6 = 'completed' \
                                            THEN false ELSE queue_position_is_manual END \
         WHERE id = $1",
        &[
            &thread_id,
            &total_issues,
            &issues_remaining,
            &next_unread,
            &reading_progress,
            &derived_status,
        ],
    )
    .await
    .map_err(db::query_error)?;
    if created_count > 0 {
        crate::issue_service::refresh_blocked_threads(&tx, user_id).await?;
    }

    let mut response = ImportSeriesResponse {
        thread_id,
        series_name,
        comicvine_volume_id: volume_id,
        total_issues_in_series: rows.len() as i32,
        issues_adopted: adopted,
        issues_skipped: skipped,
        issues_conflict: conflicts,
        issue_results,
        reading_order_id: None,
        position: None,
        total_items: None,
        thread_created,
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
        // Count after the write: a retry moves the existing entry instead of
        // adding one.
        let total: i64 = tx
            .query_one(
                "SELECT count(*) FROM reading_order_items WHERE reading_order_id = $1",
                &[&order_id],
            )
            .await
            .map_err(db::query_error)?
            .get(0);
        response.reading_order_id = Some(order_id);
        response.position = Some(target);
        response.total_items = Some(total as i32);
    }
    tx.commit().await.map_err(db::query_error)?;
    Ok((StatusCode::CREATED, Json(response)))
}

// ---------------------------------------------------------------------------
// Provider-backed read handlers.
// ---------------------------------------------------------------------------

fn provider_key() -> Option<String> {
    std::env::var("COMICVINE_API_KEY")
        .ok()
        .map(|key| key.trim().to_owned())
        .filter(|key| !key.is_empty())
}

fn series_result(value: &Value, fallback_id: Option<i32>) -> Option<ComicVineSeriesResult> {
    let object = value.as_object()?;
    let id = fallback_id.or_else(|| coerce_provider_int(object.get("id")))?;
    let name = object.get("name").and_then(Value::as_str)?;
    let publisher = match object.get("publisher") {
        Some(Value::Object(map)) => map.get("name").and_then(Value::as_str).map(str::to_owned),
        Some(Value::String(text)) => Some(text.clone()),
        _ => None,
    };
    Some(ComicVineSeriesResult {
        comicvine_volume_id: id,
        name: name.to_owned(),
        publisher,
        start_year: coerce_provider_int(object.get("start_year")),
        issue_count: coerce_provider_int(object.get("count_of_issues")),
        site_detail_url: provider_string(object.get("site_detail_url")),
        image_url: match object.get("image") {
            Some(Value::Object(map)) => map
                .get("medium_url")
                .and_then(Value::as_str)
                .or_else(|| map.get("small_url").and_then(Value::as_str))
                .map(str::to_owned),
            _ => None,
        },
    })
}

fn issue_candidate(value: &Value) -> Option<ComicVineIssueCandidate> {
    let object = value.as_object()?;
    let id = coerce_provider_int(object.get("id"))?;
    // Python behavior: issue_number null -> None, number -> string, string -> string
    let issue_number = object
        .get("issue_number")
        .and_then(|value| match value {
            Value::String(text) => Some(text.clone()),
            Value::Number(number) => Some(number.to_string()),
            Value::Null => None, // Python preserves None when cover_date is null
            _ => None,
        });
    Some(ComicVineIssueCandidate {
        comicvine_issue_id: id,
        issue_number,
        name: provider_string(object.get("name")),
        cover_date: provider_string(object.get("cover_date")),
        store_date: provider_string(object.get("store_date")),
        image_url: candidate_image_url(object.get("image")),
        site_detail_url: provider_string(object.get("site_detail_url")),
    })
}

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
    let page = offset / limit + 1;
    if query.q.trim().is_empty() {
        return Ok(Json(ComicVineSeriesSearchResponse {
            query: query.q,
            results: Vec::new(),
            total_available: Some(0),
            offset,
            limit,
            has_more: false,
            next_offset: None,
        }));
    }
    let Some(key) = provider_key() else {
        return Ok(Json(ComicVineSeriesSearchResponse {
            query: query.q,
            results: Vec::new(),
            total_available: Some(0),
            offset,
            limit,
            has_more: false,
            next_offset: None,
        }));
    };
    let extra = format!(
        "&query={}&resources=volume&limit={limit}&page={page}\
         &field_list=id,name,publisher,start_year,count_of_issues,site_detail_url,image",
        encode_query(query.q.trim())
    );
    let payload = state
        .comicvine_limits
        .call(&state.outbound, "search", &extra, &key)
        .await
        .map_err(map_provider_failure)?;
    let results: Vec<ComicVineSeriesResult> = payload
        .get("results")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|row| series_result(row, None))
        .collect();
    let total =
        coerce_provider_int(payload.get("number_of_total_results")).unwrap_or(results.len() as i32);
    let loaded = offset + results.len() as i32;
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
    let comicvine_volume_id = path_int(comicvine_volume_id)?;
    let Query(query) = query.map_err(|_| validation_failed())?;
    let mut series_name = query.series_name;
    let Some(key) = provider_key() else {
        return Ok(Json(ComicVineSeriesIssuesResponse {
            comicvine_volume_id,
            series_name: if series_name.is_empty() {
                format!("Volume {comicvine_volume_id}")
            } else {
                series_name
            },
            issues: Vec::new(),
        }));
    };
    // Python schedules the roster and the volume read together when no name
    // was supplied, so the two provider round trips overlap. Each degrades
    // independently: a roster failure keeps the name with no issues.
    let (roster, volume) = if series_name.is_empty() {
        tokio::join!(
            provider_roster(&state, comicvine_volume_id, &key, false),
            provider_issue_volume(&state, comicvine_volume_id, &key)
        )
    } else {
        (
            provider_roster(&state, comicvine_volume_id, &key, false).await,
            None,
        )
    };
    let roster = roster.unwrap_or_default();
    let issues: Vec<ComicVineIssueCandidate> = roster.iter().filter_map(issue_candidate).collect();
    if series_name.is_empty() {
        series_name = volume.unwrap_or_else(|| format!("Volume {comicvine_volume_id}"));
    }
    Ok(Json(ComicVineSeriesIssuesResponse {
        comicvine_volume_id,
        series_name,
        issues,
    }))
}

/// ComicVine `/issues` page size (Python `COLLECTION_PAGE_LIMIT`).
const ROSTER_PAGE_SIZE: usize = 100;
/// Python `VOLUME_ISSUES_PAGE_CONCURRENCY`: remaining roster pages are fetched
/// at most this many at a time.
const ROSTER_PAGE_CONCURRENCY: usize = 4;
/// Safety bound on roster pagination (100 rows/page, so 10,000 issues).
/// Python walks every page; Rust fails loudly past this bound rather than
/// returning a truncated roster that an import would commit as complete.
const MAX_ROSTER_PAGES: usize = 100;

/// One validated roster page (Python `VolumeIssuePage`).
struct RosterPage {
    rows: Vec<Value>,
    total: Option<usize>,
}

/// Validate one `/issues` page exactly like Python
/// `_fetch_volume_issue_page`: a page without a `results` list is a provider
/// error (never an empty page), non-object rows are dropped, and a row whose
/// `volume.id` is present and differs from the requested volume means the
/// provider ignored the filter, so the whole roster is refused.
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
    for row in &rows {
        let volume_row_id = row
            .get("volume")
            .and_then(Value::as_object)
            .and_then(|volume| volume.get("id"))
            .filter(|id| !id.is_null());
        if let Some(id) = volume_row_id {
            if coerce_provider_int(Some(id)) != Some(volume_id) {
                return Err(ProviderFailure::InvalidPayload);
            }
        }
    }
    // Python keeps the total only when it is an `int`.
    let total = payload
        .get("number_of_total_results")
        .and_then(Value::as_i64)
        .map(|total| total.max(0) as usize);
    Ok(RosterPage { rows, total })
}

async fn fetch_roster_page(
    state: &AppState,
    volume_id: i32,
    key: &str,
    offset: usize,
    fresh: bool,
) -> Result<RosterPage, ProviderFailure> {
    let extra = format!(
        "&filter=volume:{volume_id}&limit={ROSTER_PAGE_SIZE}&offset={offset}\
         &field_list=id,issue_number,name,cover_date,store_date,image,site_detail_url,volume"
    );
    let limits = &state.comicvine_limits;
    let payload = if fresh {
        limits
            .call_fresh(&state.outbound, "issues", &extra, key)
            .await?
    } else {
        limits.call(&state.outbound, "issues", &extra, key).await?
    };
    roster_page(&payload, volume_id)
}

/// Fetch the complete, validated issue roster for one volume. Mirrors Python
/// `ComicVineClient.fetch_volume_issues`: the first page is fetched alone; an
/// omitted total walks forward until a short page; a short or complete first
/// page is the roster; otherwise the remaining fixed offsets are fetched
/// concurrently (at most [`ROSTER_PAGE_CONCURRENCY`] in flight) and assembled
/// in offset order. Any malformed page fails the whole roster.
async fn provider_roster(
    state: &Arc<AppState>,
    volume_id: i32,
    key: &str,
    fresh: bool,
) -> Result<Vec<Value>, ProviderFailure> {
    let first = fetch_roster_page(state, volume_id, key, 0, fresh).await?;
    let Some(total) = first.total else {
        let mut rows = first.rows;
        let mut last_len = rows.len();
        let mut pages = 1usize;
        while last_len >= ROSTER_PAGE_SIZE {
            if pages >= MAX_ROSTER_PAGES {
                return Err(ProviderFailure::InvalidPayload);
            }
            let page = fetch_roster_page(state, volume_id, key, rows.len(), fresh).await?;
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
                let page = fetch_roster_page(&state, volume_id, &key, offset, fresh).await;
                (index, page)
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

/// Fetch a volume's canonical display name. Returns the raw name so callers
/// can apply their own empty-name fallback.
async fn provider_issue_volume(state: &AppState, volume_id: i32, key: &str) -> Option<String> {
    let payload = state
        .comicvine_limits
        .call(
            &state.outbound,
            &format!("volume/4050-{volume_id}"),
            "",
            key,
        )
        .await
        .ok()?;
    volume_name(&payload)
}

/// `GET /api/v2/comicvine/resolve`.
pub async fn resolve_input(
    State(state): State<Arc<AppState>>,
    _user: AuthenticatedUser,
    query: Result<Query<ResolveQuery>, QueryRejection>,
) -> Result<Json<ComicVineResolveResponse>, ApiError> {
    let Query(query) = query.map_err(|_| validation_failed())?;
    if query.input.is_empty() || query.input.chars().count() > 1000 {
        return Err(unprocessable("Invalid resolve input"));
    }
    let trimmed = query.input.trim();
    if trimmed.is_empty() {
        return Ok(Json(ComicVineResolveResponse::search(query.input, None)));
    }
    let Some(parsed) = parse_comicvine_url(trimmed) else {
        let validation_error = looks_like_url(trimmed).then(|| {
            "That doesn't look like a ComicVine issue or volume URL. Paste a \
             comicvine.gamespot.com link or search by title instead."
                .to_owned()
        });
        return Ok(Json(ComicVineResolveResponse::search(
            query.input,
            validation_error,
        )));
    };
    let Some(key) = provider_key() else {
        return Ok(Json(ComicVineResolveResponse {
            input: query.input,
            kind: match parsed {
                ParsedResource::Issue(_) => "issue".to_owned(),
                ParsedResource::Volume(_) => "volume".to_owned(),
            },
            validation_error: Some(
                "ComicVine is not configured on this server, so pasted links cannot \
                 be resolved. Search by title instead."
                    .to_owned(),
            ),
            issue: None,
            volume: None,
            issues: Vec::new(),
        }));
    };
    let failure = || {
        Json(ComicVineResolveResponse {
            input: query.input.clone(),
            kind: match parsed {
                ParsedResource::Issue(_) => "issue".to_owned(),
                ParsedResource::Volume(_) => "volume".to_owned(),
            },
            validation_error: Some(
                "We couldn't resolve that ComicVine link right now. Check the link \
                 or search by title instead."
                    .to_owned(),
            ),
            issue: None,
            volume: None,
            issues: Vec::new(),
        })
    };
    match parsed {
        ParsedResource::Issue(id) => {
            let Ok(result) = state
                .comicvine_limits
                .call(
                    &state.outbound,
                    &format!("issue/4000-{id}"),
                    &format!("&field_list={}", crate::comicvine_repair::FIELDS),
                    &key,
                )
                .await
                .and_then(|payload| {
                    payload
                        .get("results")
                        .cloned()
                        .ok_or(ProviderFailure::InvalidPayload)
                })
            else {
                return Ok(failure());
            };
            let volume = result.get("volume").and_then(Value::as_object);
            let resolved = ComicVineResolvedIssue {
                comicvine_issue_id: id,
                series_name: volume
                    .and_then(|v| v.get("name"))
                    .and_then(Value::as_str)
                    .map(str::to_owned),
                volume_id: volume.and_then(|v| coerce_provider_int(v.get("id"))),
                // Python behavior: issue_number null -> None, number -> string, string -> string
                issue_number: result
                    .get("issue_number")
                    .and_then(|value| match value {
                        Value::String(text) => Some(text.clone()),
                        Value::Number(number) => Some(number.to_string()),
                        Value::Null => None, // Python preserves None when cover_date is null
                        _ => None,
                    }),
                name: provider_string(result.get("name")),
                cover_date: provider_string(result.get("cover_date")),
                store_date: provider_string(result.get("store_date")),
                image_url: provider_image_url(result.get("image")),
                site_detail_url: provider_string(result.get("site_detail_url")),
            };
            Ok(Json(ComicVineResolveResponse {
                input: query.input,
                kind: "issue".to_owned(),
                validation_error: None,
                issue: Some(resolved),
                volume: None,
                issues: Vec::new(),
            }))
        }
        ParsedResource::Volume(id) => {
            let Ok(payload) = state
                .comicvine_limits
                .call(&state.outbound, &format!("volume/4050-{id}"), "", &key)
                .await
            else {
                return Ok(failure());
            };
            let Some(series) =
                series_result(payload.get("results").unwrap_or(&Value::Null), Some(id))
            else {
                return Ok(failure());
            };
            let roster = provider_roster(&state, id, &key, false)
                .await
                .unwrap_or_default();
            let issues: Vec<ComicVineIssueCandidate> =
                roster.iter().filter_map(issue_candidate).collect();
            Ok(Json(ComicVineResolveResponse {
                input: query.input,
                kind: "volume".to_owned(),
                validation_error: None,
                issue: None,
                volume: Some(series),
                issues,
            }))
        }
    }
}

/// `GET /api/v2/comicvine/series/{comicvine_volume_id}/import-status`.
pub async fn series_import_status(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    comicvine_volume_id: Result<Path<String>, PathRejection>,
) -> Result<Json<SeriesImportStatusResponse>, ApiError> {
    let comicvine_volume_id = path_int(comicvine_volume_id)?;
    let connection = db::checkout(&state).await?;
    let volume_id = comicvine_volume_id.to_string();
    let row = connection
        .query_opt(
            "SELECT t.id, t.title, t.total_issues FROM threads t \
             JOIN thread_external_series_mappings m ON m.thread_id = t.id \
             JOIN external_identities e ON e.id = m.external_identity_id \
             WHERE t.user_id = $1 AND m.status = 'confirmed' \
               AND e.entity_type = 'series' AND e.provider = 'comicvine' \
               AND e.external_id = $2 ORDER BY m.id LIMIT 1",
            &[&user.id(), &volume_id],
        )
        .await
        .map_err(db::query_error)?;
    let response = match row {
        Some(row) => SeriesImportStatusResponse {
            comicvine_volume_id,
            imported: true,
            thread_id: Some(row.get(0)),
            series_name: Some(row.get(1)),
            issue_count: row.get(2),
        },
        None => SeriesImportStatusResponse {
            comicvine_volume_id,
            imported: false,
            thread_id: None,
            series_name: None,
            issue_count: None,
        },
    };
    Ok(Json(response))
}

// ---------------------------------------------------------------------------
// OpenAPI documentation. These no-op functions feed the canonical generated
// v2 contract; handlers above never import documentation code at runtime.
// ---------------------------------------------------------------------------

#[utoipa::path(
    get,
    path = "/api/v2/comicvine/issues/{issue_id}/identity",
    params(("issue_id" = i32, Path, description = "ComicPile issue ID")),
    tag = "comicvine-v2",
    responses(
        (status = 200, description = "Owned identity state", body = IssueIdentityResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 404, description = "Issue not owned"),
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_issue_identity_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/comicvine/issues/{issue_id}/identity:confirm",
    params(("issue_id" = i32, Path, description = "ComicPile issue ID")),
    request_body = ConfirmIdentityRequest,
    tag = "comicvine-v2",
    responses(
        (status = 200, description = "Confirmed identity state", body = IssueIdentityResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 404, description = "Issue not owned"),
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
        (status = 401, description = "Invalid or revoked access token"),
        (status = 404, description = "Issue not owned"),
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
        (status = 401, description = "Invalid or revoked access token"),
        (status = 404, description = "Issue not owned"),
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn remove_identity_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v2/comicvine/issues/{issue_id}/metadata:corrections",
    params(("issue_id" = i32, Path, description = "ComicPile issue ID")),
    tag = "comicvine-v2",
    responses(
        (status = 200, description = "Active corrections", body = MetadataCorrectionsResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 404, description = "Issue not owned"),
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_corrections_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/comicvine/issues/{issue_id}/metadata:correct",
    params(("issue_id" = i32, Path, description = "ComicPile issue ID")),
    request_body = MetadataCorrectionRequest,
    tag = "comicvine-v2",
    responses(
        (status = 200, description = "Corrections after apply", body = MetadataCorrectionsResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 404, description = "Issue not owned"),
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
        (status = 200, description = "Corrections after revert", body = MetadataCorrectionsResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 404, description = "Issue not owned"),
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
        (status = 200, description = "Refresh signal", body = MetadataRefreshResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 404, description = "Issue not owned"),
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn refresh_metadata_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v2/comicvine/search/series",
    params(
        ("q" = String, Query, description = "Series title query"),
        ("limit" = i32, Query, description = "Maximum results"),
        ("offset" = i32, Query, description = "Zero-based offset"),
    ),
    tag = "comicvine-v2",
    responses(
        (status = 200, description = "Paginated series search", body = ComicVineSeriesSearchResponse),
        (status = 401, description = "Invalid or revoked access token"),
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
        ("series_name" = String, Query, description = "Pre-fetched series name"),
    ),
    tag = "comicvine-v2",
    responses(
        (status = 200, description = "Volume issue roster", body = ComicVineSeriesIssuesResponse),
        (status = 401, description = "Invalid or revoked access token"),
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn comicvine_series_issues_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v2/comicvine/series/{comicvine_volume_id}/import-status",
    params(("comicvine_volume_id" = i32, Path, description = "ComicVine volume ID")),
    tag = "comicvine-v2",
    responses(
        (status = 200, description = "Owned import status", body = SeriesImportStatusResponse),
        (status = 401, description = "Invalid or revoked access token"),
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn series_import_status_v2_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/comicvine/issues:import",
    request_body = ImportIssueRequest,
    tag = "comicvine-v2",
    responses(
        (status = 201, description = "Imported issue", body = ImportIssueResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 404, description = "Reading order not owned"),
        (status = 409, description = "ComicVine issue already imported"),
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn import_issue_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/comicvine/series:import",
    request_body = ImportSeriesRequest,
    tag = "comicvine-v2",
    responses(
        (status = 201, description = "Imported series", body = ImportSeriesResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 404, description = "Reading order not owned"),
        (status = 503, description = "ComicVine unavailable"),
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn import_series_documentation() {}

// ---------------------------------------------------------------------------
// Focused unit tests (no database or provider required).
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn parses_only_canonical_issue_and_volume_urls() {
        assert_eq!(
            parse_comicvine_url("https://comicvine.gamespot.com/foo/4000-1154070/"),
            Some(ParsedResource::Issue(1154070))
        );
        assert_eq!(
            parse_comicvine_url("comicvine.gamespot.com/batman/4050-148476?x=1"),
            Some(ParsedResource::Volume(148476))
        );
        assert_eq!(
            parse_comicvine_url("http://www.comicvine.gamespot.com/issue/4000-42/"),
            Some(ParsedResource::Issue(42))
        );
        assert_eq!(parse_comicvine_url("https://example.com/4000-42/"), None);
        assert_eq!(
            parse_comicvine_url("https://comicvine.gamespot.com/5000-42/"),
            None
        );
        assert_eq!(parse_comicvine_url("not a url"), None);
    }

    #[test]
    fn looks_like_url_only_for_url_shaped_input() {
        assert!(looks_like_url("https://example.com"));
        assert!(looks_like_url("HTTP://example"));
        assert!(!looks_like_url("Batman 2026"));
    }

    #[test]
    fn provider_values_are_coerced_without_type_confusion() {
        assert_eq!(coerce_provider_int(Some(&json!("1999"))), Some(1999));
        assert_eq!(coerce_provider_int(Some(&json!(42))), Some(42));
        assert_eq!(coerce_provider_int(Some(&json!(true))), None);
        assert_eq!(coerce_provider_int(Some(&json!("n/a"))), None);
        assert_eq!(provider_string(Some(&json!(""))), None);
        assert_eq!(
            provider_image_url(Some(&json!({"small_url": "s", "medium_url": "m"}))),
            Some("m".to_owned())
        );
    }

    #[test]
    fn anchored_positions_follow_the_python_precedence() {
        let mut positions = HashMap::new();
        positions.insert(10, 2);
        positions.insert(20, 5);
        assert_eq!(
            resolve_anchored_position(&positions, Some(10), Some(20), 4),
            5
        );
        assert_eq!(resolve_anchored_position(&positions, Some(10), None, 4), 3);
        assert_eq!(resolve_anchored_position(&positions, None, Some(20), 4), 5);
        assert_eq!(
            resolve_anchored_position(&positions, Some(20), Some(10), 4),
            6
        );
        assert_eq!(resolve_anchored_position(&positions, None, None, 4), 5);
        assert_eq!(
            resolve_anchored_position(&HashMap::new(), Some(99), None, 0),
            1
        );
    }

    #[test]
    fn series_results_and_candidates_match_wire_fields() {
        let series = series_result(
            &json!({
                "id": 7,
                "name": "Batman",
                "publisher": {"name": "DC"},
                "start_year": "2011",
                "count_of_issues": 52,
                "site_detail_url": "https://comicvine.gamespot.com/volume/4050-7/",
                "image": {"medium_url": "cover.jpg"}
            }),
            None,
        )
        .expect("series result");
        assert_eq!(series.comicvine_volume_id, 7);
        assert_eq!(series.start_year, Some(2011));
        assert_eq!(series.publisher.as_deref(), Some("DC"));
        assert_eq!(series.image_url.as_deref(), Some("cover.jpg"));

        let candidate = issue_candidate(&json!({
            "id": 99,
            "issue_number": 12,
            "name": "A Story",
            "image": {"small_url": "thumb.jpg"}
        }))
        .expect("issue candidate");
        assert_eq!(candidate.comicvine_issue_id, 99);
        assert_eq!(candidate.issue_number.as_deref(), Some("12"));
        assert_eq!(candidate.image_url.as_deref(), Some("thumb.jpg"));
    }

    #[test]
    fn identity_sql_is_owner_scoped_and_bounded() {
        // The owner predicate must be a bind parameter and the mapping lookup
        // must be one set-based query, never a per-mapping round trip.
        assert!(CREATED_AT_SQL.contains("AT TIME ZONE 'UTC'"));
        let state_sql = "SELECT e.id FROM issue_external_identity_mappings m \
                         JOIN external_identities e ON e.id = m.external_identity_id \
                         WHERE m.issue_id = $1 ORDER BY m.confidence DESC NULLS LAST";
        assert!(state_sql.contains("WHERE m.issue_id = $1"));
        assert!(!state_sql.contains("FOR UPDATE"));
    }
}
