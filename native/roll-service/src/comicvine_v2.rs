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
    comicvine_repair::{
        normalize_roster_issue_metadata, provider_issue, provider_response, ProviderFailure,
    },
    db, ApiError, AppState,
};
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{collections::HashMap, sync::Arc};
use tokio_postgres::Transaction;

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

/// Preserve the structured `SeriesImportError` envelope used by the retired
/// FastAPI route. The client distinguishes an upstream failure (502) from an
/// unconfigured provider (503), an empty roster, and invalid reading progress.
fn series_import_error(
    status: StatusCode,
    code: &'static str,
    message: impl Into<String>,
) -> ApiError {
    let message = message.into();
    ApiError::structured(status, json!({"code": code, "message": message}))
}

fn series_provider_failure(message: impl Into<String>) -> ApiError {
    series_import_error(StatusCode::BAD_GATEWAY, "provider_failure", message)
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
///
/// Roster facts are written only when the identity is first created. A retry
/// may refresh its provider URL, but must not replace richer deep metadata
/// with a shallow roster row (the same boundary as provider issue adoption).
async fn upsert_issue_identity(
    tx: &Transaction<'_>,
    comicvine_issue_id: i32,
    roster_row: Option<&Value>,
) -> Result<i32, ApiError> {
    let external_id = comicvine_issue_id.to_string();
    let external_url = roster_row
        .and_then(|row| provider_string(row.get("site_detail_url")))
        .unwrap_or_else(|| {
            format!("https://comicvine.gamespot.com/issue/4000-{comicvine_issue_id}/")
        });
    let metadata = roster_row
        .map(normalize_roster_issue_metadata)
        .unwrap_or_else(|| json!({}));
    let row = tx
        .query_one(
            "INSERT INTO external_identities \
                (provider, entity_type, external_id, external_url, metadata_json, created_at, updated_at) \
             VALUES ('comicvine', 'issue', $1, $2, $3::jsonb, now(), now()) \
             ON CONFLICT ON CONSTRAINT uq_external_identity_provider_entity \
             DO UPDATE SET external_url = EXCLUDED.external_url, updated_at = now() \
             RETURNING id",
            &[&external_id, &external_url, &metadata],
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
    let conflict = tx
        .query_opt(
            "SELECT m.id FROM issue_external_identity_mappings m \
             JOIN external_identities e ON e.id = m.external_identity_id \
             JOIN issues i ON i.id = m.issue_id \
             WHERE m.issue_id = $1 AND i.thread_id IN \
                 (SELECT id FROM threads WHERE user_id = $2) \
               AND m.status = 'confirmed' AND e.provider = 'comicvine' \
               AND e.external_id <> $3 LIMIT 1 FOR UPDATE OF m",
            &[&issue_id, &user, &comicvine_issue_id.to_string()],
        )
        .await
        .map_err(db::query_error)?;
    if conflict.is_some() {
        return Err(bad_request(
            "issue already has a confirmed comicvine identity",
        ));
    }
    let identity_id = upsert_issue_identity(tx, comicvine_issue_id, None).await?;
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
    Path(issue_id): Path<i32>,
    Json(request): Json<ConfirmIdentityRequest>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    if request.comicvine_issue_id <= 0 {
        return Err(bad_request("comicvine_issue_id must be positive"));
    }
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
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
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
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
    Path(issue_id): Path<i32>,
) -> Result<Json<MetadataCorrectionsResponse>, ApiError> {
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
    Path(issue_id): Path<i32>,
    Json(request): Json<MetadataCorrectionRequest>,
) -> Result<Json<MetadataCorrectionsResponse>, ApiError> {
    if request.field_name.is_empty() || request.field_name.len() > 100 {
        return Err(unprocessable("Invalid field name"));
    }
    if request.canonical_value.is_empty() {
        return Err(unprocessable("Invalid canonical value"));
    }
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
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
    Path(issue_id): Path<i32>,
) -> Result<Json<MetadataRefreshResponse>, ApiError> {
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

#[derive(Debug, Clone, Copy)]
struct ReadingOrderItemPlacement {
    id: Option<i32>,
    thread_id: i32,
    position: i32,
}

/// Port of the shared `apply_insert` placement rule. Existing memberships are
/// moved (and their neighbours shifted), while a new membership makes room at
/// the target position. Keeping this in memory also lets persistence stay
/// set-based instead of issuing one UPDATE per reading-order row.
fn apply_reading_order_insert(
    items: &mut Vec<ReadingOrderItemPlacement>,
    thread_id: i32,
    target_pos: i32,
) {
    if let Some(current_index) = items.iter().position(|item| item.thread_id == thread_id) {
        let old_pos = items[current_index].position;
        if old_pos < target_pos {
            for item in items.iter_mut() {
                if old_pos < item.position && item.position <= target_pos {
                    item.position -= 1;
                }
            }
        } else if target_pos < old_pos {
            for item in items.iter_mut() {
                if target_pos <= item.position && item.position < old_pos {
                    item.position += 1;
                }
            }
        }
        items[current_index].position = target_pos;
        return;
    }
    for item in items.iter_mut() {
        if item.position >= target_pos {
            item.position += 1;
        }
    }
    items.push(ReadingOrderItemPlacement {
        id: None,
        thread_id,
        position: target_pos,
    });
}

/// Shift an existing reading order and insert or move the imported thread.
async fn insert_into_reading_order(
    tx: &Transaction<'_>,
    order_id: i32,
    thread_id: i32,
    target_pos: i32,
) -> Result<i32, ApiError> {
    let rows = tx
        .query(
            "SELECT id, thread_id, position FROM reading_order_items \
             WHERE reading_order_id = $1 ORDER BY position, id FOR UPDATE",
            &[&order_id],
        )
        .await
        .map_err(db::query_error)?;
    let mut items: Vec<ReadingOrderItemPlacement> = rows
        .iter()
        .map(|row| ReadingOrderItemPlacement {
            id: Some(row.get(0)),
            thread_id: row.get(1),
            position: row.get(2),
        })
        .collect();
    let original_positions: HashMap<i32, i32> = items
        .iter()
        .filter_map(|item| item.id.map(|id| (id, item.position)))
        .collect();
    let already_present = items.iter().any(|item| item.thread_id == thread_id);
    apply_reading_order_insert(&mut items, thread_id, target_pos);

    let changed: Vec<(i32, i32)> = items
        .iter()
        .filter_map(|item| {
            let id = item.id?;
            (original_positions.get(&id) != Some(&item.position)).then_some((id, item.position))
        })
        .collect();
    if !changed.is_empty() {
        let ids: Vec<i32> = changed.iter().map(|(id, _)| *id).collect();
        let positions: Vec<i32> = changed.iter().map(|(_, position)| *position).collect();
        tx.execute(
            "UPDATE reading_order_items AS item SET position = update.position \
             FROM (SELECT unnest($1::int[]) AS id, unnest($2::int[]) AS position) AS update \
             WHERE item.id = update.id AND item.reading_order_id = $3",
            &[&ids, &positions, &order_id],
        )
        .await
        .map_err(db::query_error)?;
    }
    if !already_present {
        tx.execute(
            "INSERT INTO reading_order_items \
                (reading_order_id, thread_id, position, issue_number) \
             VALUES ($1, $2, $3, NULL)",
            &[&order_id, &thread_id, &target_pos],
        )
        .await
        .map_err(db::query_error)?;
    }
    let total_items: i64 = tx
        .query_one(
            "SELECT COUNT(*) FROM reading_order_items WHERE reading_order_id = $1",
            &[&order_id],
        )
        .await
        .map_err(db::query_error)?
        .get(0);
    Ok(i32::try_from(total_items).unwrap_or(i32::MAX))
}

/// `POST /api/v2/comicvine/issues:import`.
pub async fn import_issue(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<ImportIssueRequest>,
) -> Result<(StatusCode, Json<ImportIssueResponse>), ApiError> {
    let title = request.title.trim();
    if title.is_empty() || title.len() > 200 {
        return Err(unprocessable("Invalid title"));
    }
    if request.comicvine_issue_id <= 0 {
        return Err(unprocessable("Invalid comicvine_issue_id"));
    }
    if request
        .issue_number
        .as_deref()
        .is_some_and(|n| n.len() > 50)
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
        return Err(ApiError::structured(
            StatusCode::CONFLICT,
            json!({
                "code": "duplicate_physical_issue",
                "comicvine_issue_id": request.comicvine_issue_id,
                "existing_issue_id": existing_issue_id,
                "message": message,
            }),
        ));
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
    let external_identity_id =
        link_confirmed(&tx, user.id(), issue_id, request.comicvine_issue_id).await?;

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
        let total_items = insert_into_reading_order(&tx, order_id, thread_id, target).await?;
        response.reading_order_id = Some(order_id);
        response.position = Some(target);
        response.total_items = Some(total_items);
    }
    tx.commit().await.map_err(db::query_error)?;
    Ok((StatusCode::CREATED, Json(response)))
}

#[derive(Debug)]
struct SeriesLocalIssue {
    id: Option<i32>,
    issue_number: String,
    position: i32,
    confirmed_external_id: Option<String>,
}

#[derive(Debug, Clone)]
struct SeriesExternalMapping {
    issue_id: Option<i32>,
    issue_number: String,
    thread_id: i32,
}

#[derive(Debug)]
struct PlannedSeriesIssue {
    comicvine_issue_id: i32,
    issue_number: String,
    local_issue_number: Option<String>,
    existing_issue_id: Option<i32>,
    outcome: &'static str,
    conflict_detail: Option<String>,
}

/// Apply the shared one-issue natural-order insertion rule entirely in memory.
/// The caller persists the resulting position changes and new rows in two
/// set-based statements, avoiding the former per-roster-row database round trips.
fn create_series_issue_in_natural_order(
    local_issues: &mut Vec<SeriesLocalIssue>,
    issue_number: String,
) -> usize {
    let mut ordered: Vec<&SeriesLocalIssue> = local_issues.iter().collect();
    ordered.sort_by_key(|issue| (issue.position, issue.id.unwrap_or(i32::MAX)));
    let existing_numbers: Vec<String> = ordered
        .into_iter()
        .map(|issue| issue.issue_number.clone())
        .collect();
    let incoming = [issue_number.clone()];
    let natural =
        crate::reading_plan_sync::natural_issue_order(&existing_numbers, &incoming);
    let fallback_position = local_issues
        .iter()
        .map(|issue| issue.position)
        .max()
        .unwrap_or(0)
        + 1;
    let position = if let Some(order) = natural {
        let targets: HashMap<String, i32> = order
            .into_iter()
            .enumerate()
            .map(|(index, number)| (number, index as i32 + 1))
            .collect();
        for issue in local_issues.iter_mut() {
            if let Some(target) = targets.get(&issue.issue_number) {
                issue.position = *target;
            }
        }
        targets
            .get(&issue_number)
            .copied()
            .unwrap_or(fallback_position)
    } else {
        fallback_position
    };
    let index = local_issues.len();
    local_issues.push(SeriesLocalIssue {
        id: None,
        issue_number,
        position,
        confirmed_external_id: None,
    });
    index
}

/// `POST /api/v2/comicvine/series:import`.
pub async fn import_series(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<ImportSeriesRequest>,
) -> Result<(StatusCode, Json<ImportSeriesResponse>), ApiError> {
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
    let volume_id = request.comicvine_volume_id;
    let (series_name, rows) = series_import_provider_payload(volume_id).await?;
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
    if let Some(order_id) = request.reading_order_id {
        owned_reading_order(&tx, user.id(), order_id).await?;
    }
    let external_volume_id = volume_id.to_string();
    let reused_thread_id: Option<i32> = tx
        .query_opt(
            "SELECT t.id FROM threads t \
             JOIN thread_external_series_mappings m ON m.thread_id = t.id \
             JOIN external_identities e ON e.id = m.external_identity_id \
             WHERE t.user_id = $1 AND m.status = 'confirmed' \
               AND e.entity_type = 'series' AND e.provider = 'comicvine' \
               AND e.external_id = $2 ORDER BY m.id LIMIT 1",
            &[&user.id(), &external_volume_id],
        )
        .await
        .map_err(db::query_error)?
        .map(|row| row.get(0));
    let thread_created = reused_thread_id.is_none();
    let thread_id = match reused_thread_id {
        Some(id) => id,
        None => {
            let next_position: i32 = tx
                .query_one(
                    "SELECT COALESCE(MAX(queue_position), 0) + 1 FROM threads WHERE user_id = $1",
                    &[&user.id()],
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
                &[&series_name.trim(), &next_position, &user.id()],
            )
            .await
            .map_err(db::query_error)?
            .get(0)
        }
    };
    let prior_thread = tx
        .query_one(
            "SELECT total_issues, next_unread_issue_id, status FROM threads \
             WHERE id = $1 AND user_id = $2 FOR UPDATE",
            &[&thread_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let prior_total_issues: Option<i32> = prior_thread.get(0);
    let prior_next_unread: Option<i32> = prior_thread.get(1);
    let prior_status: String = prior_thread.get(2);

    let series_identity_row = tx
        .query_one(
            "INSERT INTO external_identities \
                (provider, entity_type, external_id, external_url, metadata_json, created_at, updated_at) \
             VALUES ('comicvine', 'series', $1, $2, '{}'::jsonb, now(), now()) \
             ON CONFLICT ON CONSTRAINT uq_external_identity_provider_entity \
             DO UPDATE SET external_url = EXCLUDED.external_url, updated_at = now() \
             RETURNING id",
            &[
                &external_volume_id,
                &format!("https://comicvine.gamespot.com/volume/4050-{volume_id}/"),
            ],
        )
        .await
        .map_err(db::query_error)?;
    let series_identity_id: i32 = series_identity_row.get(0);
    tx.execute(
        "INSERT INTO thread_external_series_mappings \
            (thread_id, external_identity_id, status, evidence_source, confidence, \
             created_at, updated_at) \
         VALUES ($1, $2, 'confirmed', 'comicvine_series_import', 1.0, now(), now()) \
         ON CONFLICT ON CONSTRAINT uq_thread_external_series_mapping \
         DO UPDATE SET status = 'confirmed', confidence = 1.0, updated_at = now()",
        &[&thread_id, &series_identity_id],
    )
    .await
    .map_err(db::query_error)?;

    let mut issue_results = Vec::with_capacity(rows.len());
    let mut adopted = 0i32;
    let mut skipped = 0i32;
    let conflicts = 0i32;
    for (index, row) in rows.iter().enumerate() {
        let Some(cv_id) = coerce_provider_int(row.get("id")) else {
            continue;
        };
        let issue_number = row
            .get("issue_number")
            .map(|value| match value {
                Value::String(text) => text.clone(),
                Value::Number(number) => number.to_string(),
                _ => value.to_string(),
            })
            .filter(|text| !text.is_empty())
            .unwrap_or_else(|| (index + 1).to_string());

        let existing: Option<i32> = tx
            .query_opt(
                "SELECT i.id FROM external_identities e \
                 JOIN issue_external_identity_mappings m ON m.external_identity_id = e.id \
                 JOIN issues i ON i.id = m.issue_id \
                 JOIN threads t ON t.id = i.thread_id \
                 WHERE e.provider = 'comicvine' AND e.entity_type = 'issue' \
                   AND e.external_id = $1 AND m.status = 'confirmed' AND t.user_id = $2 \
                 LIMIT 1",
                &[&cv_id.to_string(), &user.id()],
            )
            .await
            .map_err(db::query_error)?
            .map(|r| r.get(0));
        if let Some(issue_id) = existing {
            skipped += 1;
            issue_results.push(ImportSeriesIssueResult {
                comicvine_issue_id: cv_id,
                issue_number: Some(issue_number),
                issue_id: Some(issue_id),
                outcome: "reused".to_owned(),
                hydration: "pending".to_owned(),
                conflict_detail: None,
            });
            continue;
        }
        let position = index as i32 + 1;
        let new_issue = tx
            .query_one(
                "INSERT INTO issues \
                    (thread_id, issue_number, position, status, created_at) \
                 VALUES ($1, $2, $3, 'unread', now()) \
                 ON CONFLICT ON CONSTRAINT uq_issue_thread_number \
                 DO UPDATE SET position = EXCLUDED.position RETURNING id",
                &[&thread_id, &issue_number, &position],
            )
            .await
            .map_err(db::query_error)?;
        let issue_id: i32 = new_issue.get(0);
        link_confirmed(&tx, user.id(), issue_id, cv_id).await?;
        adopted += 1;
        issue_results.push(ImportSeriesIssueResult {
            comicvine_issue_id: cv_id,
            issue_number: Some(issue_number),
            issue_id: Some(issue_id),
            outcome: "created".to_owned(),
            hydration: "pending".to_owned(),
            conflict_detail: None,
        });
    }

    // Mark the leading locally-adopted issues read, then derive the thread's
    // canonical counters from the rows that actually exist.
    let thread_issues = tx
        .query(
            "SELECT id FROM issues WHERE thread_id = $1 ORDER BY position, id",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    let read_count = (request.already_read_count as usize).min(thread_issues.len());
    for row in thread_issues.iter().take(read_count) {
        tx.execute(
            "UPDATE issues SET status = 'read', read_at = now() WHERE id = $1",
            &[&row.get::<_, i32>(0)],
        )
        .await
        .map_err(db::query_error)?;
    }
    let total_issues = thread_issues.len() as i32;
    let issues_remaining = (total_issues - read_count as i32).max(0);
    let next_unread = thread_issues
        .get(read_count)
        .map(|row| row.get::<_, i32>(0));
    let status = if issues_remaining == 0 {
        "completed"
    } else {
        "active"
    };
    tx.execute(
        "UPDATE threads SET total_issues = $2, issues_remaining = $3, \
            next_unread_issue_id = $4, reading_progress = $5, status = $6, \
            is_blocked = CASE WHEN $3 = 0 THEN false ELSE is_blocked END \
            WHERE id = $1",
        &[
            &thread_id,
            &total_issues,
            &issues_remaining,
            &next_unread,
            &Some(format!("{read_count}/{total_issues}")),
            &status,
        ],
    )
    .await
    .map_err(db::query_error)?;

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
        let total_items = insert_into_reading_order(&tx, order_id, thread_id, target).await?;
        response.reading_order_id = Some(order_id);
        response.position = Some(target);
        response.total_items = Some(total_items);
    }
    tx.commit().await.map_err(db::query_error)?;
    Ok((StatusCode::CREATED, Json(response)))
}

// ---------------------------------------------------------------------------
// Provider-backed read handlers.
// ---------------------------------------------------------------------------

async fn series_import_provider_payload(
    volume_id: i32,
) -> Result<(String, Vec<Value>), ApiError> {
    #[cfg(test)]
    if let Some((series, roster)) =
        crate::test_support::lookup_test_volume_roster(&volume_id.to_string())
    {
        let series_name = series
            .get("name")
            .and_then(Value::as_str)
            .filter(|name| !name.trim().is_empty())
            .ok_or_else(|| series_provider_failure("ComicVine series has no name"))?;
        return Ok((series_name.to_owned(), roster));
    }

    let Some(key) = provider_key() else {
        return Err(series_import_error(
            StatusCode::SERVICE_UNAVAILABLE,
            "provider_unavailable",
            "ComicVine is not configured on this server",
        ));
    };
    let volume = provider_response(&format!("volume/4050-{volume_id}"), "", &key)
        .await
        .map_err(|error| {
            series_provider_failure(format!("Failed to fetch ComicVine series: {error:?}"))
        })?;
    let Some(result) = volume.get("results").and_then(Value::as_object) else {
        return Err(series_provider_failure(
            "ComicVine series response did not contain valid data",
        ));
    };
    let series_name = result
        .get("name")
        .and_then(Value::as_str)
        .filter(|name| !name.trim().is_empty())
        .ok_or_else(|| series_provider_failure("ComicVine series has no name"))?
        .to_owned();
    let rows = provider_roster(volume_id, &key).await.map_err(|error| {
        series_provider_failure(format!("Failed to fetch series issues: {error:?}"))
    })?;
    Ok((series_name, rows))
}

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
    _user: AuthenticatedUser,
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
    _user: AuthenticatedUser,
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
    let roster = provider_roster(comicvine_volume_id, &key)
        .await
        .unwrap_or_default();
    let issues: Vec<ComicVineIssueCandidate> = roster.iter().filter_map(issue_candidate).collect();
    if series_name.is_empty() {
        series_name = provider_issue_volume(comicvine_volume_id, &key)
            .await
            .unwrap_or_else(|| format!("Volume {comicvine_volume_id}"));
    }
    Ok(Json(ComicVineSeriesIssuesResponse {
        comicvine_volume_id,
        series_name,
        issues,
    }))
}

/// Fetch the complete, validated issue roster for one volume. ComicVine pages
/// at 100 rows; follow the reported total with a bounded fan-out and refuse a
/// response whose rows do not belong to the requested volume (the Python
/// provider applies the same guard so a bad filter cannot import mixed data).
const ROSTER_PAGE_SIZE: usize = 100;
const MAX_ROSTER_PAGES: usize = 10;

async fn provider_roster(volume_id: i32, key: &str) -> Result<Vec<Value>, ApiError> {
    async fn fetch_page(
        volume_id: i32,
        key: &str,
        offset: usize,
    ) -> Result<Value, ProviderFailure> {
        let extra = format!(
            "&filter=volume:{volume_id}&limit={ROSTER_PAGE_SIZE}&offset={offset}\
             &field_list=id,issue_number,name,cover_date,store_date,image,site_detail_url,volume"
        );
        provider_response("issues", &extra, key).await
    }
    let first = fetch_page(volume_id, key, 0)
        .await
        .map_err(map_provider_failure)?;
    let mut rows: Vec<Value> = first
        .get("results")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let total = coerce_provider_int(first.get("number_of_total_results")).unwrap_or(0);
    let mut offset = rows.len();
    while offset > 0 && offset < total as usize && rows.len() < MAX_ROSTER_PAGES * ROSTER_PAGE_SIZE
    {
        let page = fetch_page(volume_id, key, offset)
            .await
            .map_err(map_provider_failure)?;
        let page_rows: Vec<Value> = page
            .get("results")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        if page_rows.is_empty() {
            break;
        }
        offset += page_rows.len();
        rows.extend(page_rows);
    }
    for row in &rows {
        if let Some(volume_id_value) = row
            .get("volume")
            .and_then(Value::as_object)
            .and_then(|v| v.get("id"))
        {
            if coerce_provider_int(Some(volume_id_value)) != Some(volume_id) {
                return Err(ApiError::ServiceUnavailable(
                    "provider_invalid_payload".to_owned(),
                ));
            }
        }
    }
    Ok(rows)
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
    _user: AuthenticatedUser,
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
            let Ok(payload) = provider_response(&format!("volume/4050-{id}"), "", &key).await
            else {
                return Ok(failure());
            };
            let Some(series) =
                series_result(payload.get("results").unwrap_or(&Value::Null), Some(id))
            else {
                return Ok(failure());
            };
            let roster = provider_roster(id, &key).await.unwrap_or_default();
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
pub fn series_issues_documentation() {}

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
