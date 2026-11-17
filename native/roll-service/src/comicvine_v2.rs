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
use serde_json::Value;
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

// ---------------------------------------------------------------------------
// Owner-scoped database helpers. Every caller passes the authenticated user
// id as a bind parameter, never as interpolated SQL.
// ---------------------------------------------------------------------------

/// Resolve an owned issue to its thread id and title, or 404.
async fn owned_issue(tx: &Transaction<'_>, user: i32, issue_id: i32) -> Result<(i32, String), ApiError> {
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
    "to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')";

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
            &format!(
                "SELECT c.id, c.field_name, c.provider_value, c.canonical_value, \
                        c.provenance, c.created_by, {CREATED_AT_SQL} \
                 FROM issue_metadata_corrections c \
                 JOIN issues i ON i.id = c.issue_id \
                 JOIN threads t ON t.id = i.thread_id \
                 WHERE c.issue_id = $1 AND t.user_id = $2 AND c.reverted_at IS NULL \
                 ORDER BY c.created_at ASC, c.id ASC"
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
             DO UPDATE SET external_url = EXCLUDED.external_url, updated_at = now() \
             RETURNING id",
            &[&external_id, &external_url],
        )
        .await
        .map_err(db::query_error)?;
    Ok(row.get(0))
}

/// Confirm (or re-confirm) one provider mapping for an issue.
async fn link_confirmed(
    tx: &Transaction<'_>,
    user: i32,
    issue_id: i32,
    comicvine_issue_id: i32,
) -> Result<i32, ApiError> {
    owned_issue(tx, user, issue_id).await?;
    let identity_id = upsert_issue_identity(tx, comicvine_issue_id).await?;
    tx.execute(
        "INSERT INTO issue_external_identity_mappings \
            (issue_id, external_identity_id, status, evidence_source, evidence_json, \
             confidence, created_at, updated_at) \
         VALUES ($1, $2, 'confirmed', 'user_confirmed', '{}'::jsonb, 1.0, now(), now()) \
         ON CONFLICT ON CONSTRAINT uq_issue_external_identity_mapping \
         DO UPDATE SET status = 'confirmed', evidence_source = 'user_confirmed', \
                       confidence = 1.0, rejection_reason = NULL, updated_at = now()",
        &[&issue_id, &identity_id],
    )
    .await
    .map_err(db::query_error)?;
    // Best-effort hydration: enqueue the existing native repair worker so deep
    // metadata is filled outside this request, exactly as the Python handler
    // did via refresh_issue_metadata. Failure never rolls back the confirmation.
    let _ = tx
        .execute(
            "INSERT INTO comicvine_metadata_refresh_requests \
                (external_identity_id, state, attempts, next_attempt_at, created_at, updated_at) \
             VALUES ($1, 'pending', 0, now(), now(), now()) \
             ON CONFLICT (external_identity_id) DO NOTHING",
            &[&identity_id],
        )
        .await;
    Ok(identity_id)
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
    Path(issue_id): Path<i32>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    let connection = db::checkout(&state).await?;
    let mut tx = connection.transaction().await.map_err(db::query_error)?;
    let response = identity_state(&tx, user.id(), issue_id).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

/// `POST /api/v2/comicvine/issues/{issue_id}/identity:confirm`.
pub async fn confirm_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
    Json(request): Json<ConfirmIdentityRequest>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    if request.comicvine_issue_id <= 0 {
        return Err(bad_request("comicvine_issue_id must be positive"));
    }
    let connection = db::checkout(&state).await?;
    let mut tx = connection.transaction().await.map_err(db::query_error)?;
    link_confirmed(&tx, user.id(), issue_id, request.comicvine_issue_id).await?;
    let response = identity_state(&tx, user.id(), issue_id).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

/// `POST /api/v2/comicvine/issues/{issue_id}/identity:replace`.
pub async fn replace_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
    Json(request): Json<ReplaceIdentityRequest>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    if request.comicvine_issue_id <= 0 {
        return Err(bad_request("comicvine_issue_id must be positive"));
    }
    if request.reason.as_deref().is_some_and(|r| r.len() > 500) {
        return Err(unprocessable("reason is too long"));
    }
    let connection = db::checkout(&state).await?;
    let mut tx = connection.transaction().await.map_err(db::query_error)?;
    owned_issue(&tx, user.id(), issue_id).await?;
    let reason = request
        .reason
        .filter(|r| !r.is_empty())
        .unwrap_or_else(|| "replaced by user".to_owned());
    tx.execute(
        "UPDATE issue_external_identity_mappings m \
         SET status = 'rejected', rejection_reason = $3, updated_at = now() \
         FROM external_identities e \
         WHERE m.external_identity_id = e.id AND m.issue_id = $1 \
           AND m.status = 'confirmed' AND e.provider = 'comicvine'",
        &[&issue_id, &user.id(), &reason],
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
    Path(issue_id): Path<i32>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    let connection = db::checkout(&state).await?;
    let mut tx = connection.transaction().await.map_err(db::query_error)?;
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
    Path(issue_id): Path<i32>,
) -> Result<Json<MetadataCorrectionsResponse>, ApiError> {
    let connection = db::checkout(&state).await?;
    let mut tx = connection.transaction().await.map_err(db::query_error)?;
    let response = corrections_list(&tx, user.id(), issue_id).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

/// `POST /api/v2/comicvine/issues/{issue_id}/metadata:correct`.
pub async fn apply_correction(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
    Json(request): Json<MetadataCorrectionRequest>,
) -> Result<Json<MetadataCorrectionsResponse>, ApiError> {
    if request.field_name.is_empty() || request.field_name.len() > 100 {
        return Err(unprocessable("Invalid field name"));
    }
    if request.canonical_value.is_empty() {
        return Err(unprocessable("Invalid canonical value"));
    }
    let connection = db::checkout(&state).await?;
    let mut tx = connection.transaction().await.map_err(db::query_error)?;
    owned_issue(&tx, user.id(), issue_id).await?;

    let provider_value: Option<String> = tx
        .query_opt(
            "SELECT e.metadata_json ->> $2 \
             FROM external_identities e \
             JOIN issue_external_identity_mappings m ON m.external_identity_id = e.id \
             WHERE m.issue_id = $1 AND m.status = 'confirmed' AND e.provider = 'comicvine' \
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
    Path(issue_id): Path<i32>,
    Json(request): Json<MetadataCorrectionRevertRequest>,
) -> Result<Json<MetadataCorrectionsResponse>, ApiError> {
    let connection = db::checkout(&state).await?;
    let mut tx = connection.transaction().await.map_err(db::query_error)?;
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
    Path(issue_id): Path<i32>,
) -> Result<Json<MetadataRefreshResponse>, ApiError> {
    let connection = db::checkout(&state).await?;
    let mut tx = connection.transaction().await.map_err(db::query_error)?;
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
    let issue_number = object
        .get("issue_number")
        .map(|value| match value {
            Value::String(text) => text.clone(),
            Value::Number(number) => number.to_string(),
            _ => value.to_string(),
        })
        .filter(|text| !text.is_empty());
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
    Query(query): Query<SearchQuery>,
) -> Result<Json<ComicVineSeriesSearchResponse>, ApiError> {
    let limit = query.limit.clamp(1, 50);
    let offset = query.offset.max(0);
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
    let payload = provider_response("search", &extra, &key)
        .await
        .map_err(map_provider_failure)?;
    let results: Vec<ComicVineSeriesResult> = payload
        .get("results")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|row| series_result(row, None))
        .collect();
    let total = coerce_provider_int(payload.get("number_of_total_results"))
        .unwrap_or_else(|| results.len() as i32);
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
    Path(comicvine_volume_id): Path<i32>,
    Query(query): Query<SeriesIssuesQuery>,
) -> Result<Json<ComicVineSeriesIssuesResponse>, ApiError> {
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
    let roster = provider_response(
        "issue",
        &format!(
            "&filter=volume:{comicvine_volume_id}&limit=100\
             &field_list=id,issue_number,name,cover_date,store_date,image,site_detail_url"
        ),
        &key,
    )
    .await
    .ok();
    let issues: Vec<ComicVineIssueCandidate> = roster
        .as_ref()
        .and_then(|payload| payload.get("results"))
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(issue_candidate)
        .collect();
    if series_name.is_empty() {
        let volume = provider_issue_volume(comicvine_volume_id, &key).await.ok();
        series_name = volume
            .as_deref()
            .and_then(|name| volume_name(&json!({ "results": { "name": name } })))
            .unwrap_or_else(|| format!("Volume {comicvine_volume_id}"));
    }
    Ok(Json(ComicVineSeriesIssuesResponse {
        comicvine_volume_id,
        series_name,
        issues,
    }))
}

/// Fetch a volume's canonical display name. Returns the raw name so callers
/// can apply their own empty-name fallback.
async fn provider_issue_volume(volume_id: i32, key: &str) -> Option<String> {
    let payload = provider_response(&format!("volume/4050-{volume_id}"), "", key)
        .await
        .ok()?;
    volume_name(&payload)
}

/// `GET /api/v2/comicvine/resolve`.
pub async fn resolve_input(
    Query(query): Query<ResolveQuery>,
) -> Result<Json<ComicVineResolveResponse>, ApiError> {
    if query.input.is_empty() || query.input.len() > 1000 {
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
        return Ok(Json(ComicVineResolveResponse::search(query.input, validation_error)));
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
            let Ok(result) = provider_issue(id as u32, &key).await else {
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
                issue_number: result
                    .get("issue_number")
                    .map(|value| match value {
                        Value::String(text) => text.clone(),
                        Value::Number(number) => number.to_string(),
                        _ => value.to_string(),
                    })
                    .filter(|text| !text.is_empty()),
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
            let Ok(payload) = provider_response(&format!("volume/4050-{id}"), "", &key).await else {
                return Ok(failure());
            };
            let Some(series) = series_result(
                payload.get("results").unwrap_or(&Value::Null),
                Some(id),
            ) else {
                return Ok(failure());
            };
            let roster = provider_response(
                "issue/",
                &format!(
                    "&filter=volume:{id}&limit=100\
                     &field_list=id,issue_number,name,cover_date,store_date,image,site_detail_url"
                ),
                &key,
            )
            .await
            .ok();
            let issues: Vec<ComicVineIssueCandidate> = roster
                .as_ref()
                .and_then(|p| p.get("results"))
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(issue_candidate)
                .collect();
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
    Path(comicvine_volume_id): Path<i32>,
) -> Result<Json<SeriesImportStatusResponse>, ApiError> {
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
