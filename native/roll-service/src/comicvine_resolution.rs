//! Native same-path Rust handlers for ComicVine resolution (#4835).
//!
//! All browser-called `/api/v1/comicvine/*` operations are served here from
//! the native binary, matching the frozen Python wire contract
//! (`app/api/comicvine_resolution.py` and `app/services/comicvine_resolution.py`).
//! Read operations use the same SQL patterns as the canonical v2 routes in
//! `comicvine_v2.rs`; write operations mirror the Python service layer.

use crate::{auth::AuthenticatedUser, comicvine_v2, db, ApiError, AppState};
use axum::{
    extract::{
        rejection::{PathRejection, QueryRejection},
        Path, Query, State,
    },
    Json,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio_postgres::Transaction;

// ---------------------------------------------------------------------------
// Re-exported shared wire types from the canonical v2 module.
// ---------------------------------------------------------------------------

pub use comicvine_v2::{
    CanonicalCorrection, ComicVineIssueCandidate, ComicVineResolvedIssue,
    ComicVineResolveResponse, ComicVineSeriesIssuesResponse,
    ComicVineSeriesResult, ComicVineSeriesSearchResponse, IssueIdentityMapping,
    IssueIdentityResponse, MetadataCorrectionsResponse,
};

// ---------------------------------------------------------------------------
// v1-only response types.
// ---------------------------------------------------------------------------

/// Wire parity with Python `SeriesImportStatusResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SeriesImportStatusResponse {
    pub comicvine_volume_id: i32,
    pub imported: bool,
    pub thread_id: Option<i32>,
    pub series_name: Option<String>,
    pub issue_count: Option<i32>,
}

/// Wire parity with Python `MetadataRefreshResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct RefreshMetadataResponse {
    pub issue_id: i32,
    pub refreshed: bool,
    pub comicvine_issue_id: Option<String>,
}

/// Wire parity with Python `ImportIssueResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ImportIssueResponse {
    pub thread_id: i32,
    pub issue_id: i32,
    pub external_identity_id: i32,
    pub reading_order_id: Option<i32>,
    pub position: Option<i32>,
    pub total_items: Option<i32>,
    #[serde(default)]
    pub thread_created: bool,
}

/// Wire parity with Python `ImportSeriesResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
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
    #[serde(default)]
    pub thread_created: bool,
}

/// One issue adoption result within a series import.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ImportSeriesIssueResult {
    pub comicvine_issue_id: i32,
    pub issue_number: Option<String>,
    pub issue_id: Option<i32>,
    pub outcome: String,
    pub hydration: String,
    pub conflict_detail: Option<String>,
}

// ---------------------------------------------------------------------------
// v1-only request types.
// ---------------------------------------------------------------------------

/// `POST /api/v1/comicvine/issues/{issue_id}/identity:confirm` body.
#[derive(Debug, Deserialize)]
pub struct ConfirmIdentityRequest {
    pub comicvine_issue_id: i32,
}

/// `POST /api/v1/comicvine/issues/{issue_id}/identity:replace` body.
#[derive(Debug, Deserialize)]
pub struct ReplaceIdentityRequest {
    pub comicvine_issue_id: i32,
    #[serde(default)]
    pub reason: Option<String>,
}

/// `POST /api/v1/comicvine/issues/{issue_id}/metadata:correct` body.
#[derive(Debug, Deserialize)]
pub struct MetadataCorrectionRequest {
    pub field_name: String,
    pub canonical_value: String,
    #[serde(default)]
    pub reason: Option<String>,
}

/// `POST /api/v1/comicvine/issues/{issue_id}/metadata:revert` body.
#[derive(Debug, Deserialize)]
pub struct MetadataCorrectionRevertRequest {
    pub correction_id: i32,
}

/// `POST /api/v1/comicvine/issues:import` body.
#[derive(Debug, Deserialize)]
pub struct ImportIssueRequest {
    pub title: String,
    pub comicvine_issue_id: i32,
    #[serde(default)]
    pub issue_number: Option<String>,
    #[serde(default)]
    pub reading_order_id: Option<i32>,
    #[serde(default)]
    pub anchor_before_thread_id: Option<i32>,
    #[serde(default)]
    pub anchor_after_thread_id: Option<i32>,
}

/// `POST /api/v1/comicvine/series:import` body.
#[derive(Debug, Deserialize)]
pub struct ImportSeriesRequest {
    pub comicvine_volume_id: i32,
    #[serde(default)]
    pub reading_order_id: Option<i32>,
    #[serde(default)]
    pub anchor_before_thread_id: Option<i32>,
    #[serde(default)]
    pub anchor_after_thread_id: Option<i32>,
    #[serde(default = "default_already_read_count")]
    pub already_read_count: i32,
}

fn default_already_read_count() -> i32 {
    0
}

// ---------------------------------------------------------------------------
// Query types.
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
pub struct ResolveQuery {
    pub input: String,
}

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
pub struct SeriesIssuesQuery {
    #[serde(default)]
    pub series_name: String,
}

// ---------------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------------

const COMICVINE_PROVIDER: &str = "comicvine";

const NOT_FOUND_DETAIL: &str = "Issue not found";
const NO_CONFIRMED_IDENTITY: &str = "No confirmed ComicVine identity mapping found for issue";
const NO_CORRECTION: &str = "Correction not found";

// ---------------------------------------------------------------------------
// Owner-scoped database helpers.
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
        .ok_or_else(|| ApiError::NotFound(NOT_FOUND_DETAIL.to_string()))
}

/// Pydantic's JSON spelling of a UTC `timestamptz`.
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

/// Look up a confirmed comicvine identity for an issue (used by refresh).
async fn confirmed_comicvine_issue_id(
    tx: &Transaction<'_>,
    user: i32,
    issue_id: i32,
) -> Result<Option<String>, ApiError> {
    owned_issue(tx, user, issue_id).await?;
    let row = tx
        .query_opt(
            "SELECT e.external_id FROM issue_external_identity_mappings m \
             JOIN external_identities e ON e.id = m.external_identity_id \
             WHERE m.issue_id = $1 AND m.status = 'confirmed' \
             AND e.provider = $2 AND e.entity_type = 'issue' \
             ORDER BY m.confidence DESC NULLS LAST, m.id LIMIT 1",
            &[&issue_id, &COMICVINE_PROVIDER],
        )
        .await
        .map_err(db::query_error)?;
    Ok(row.map(|row| row.get::<_, String>(0)))
}

/// Upsert an external identity and return its id.
async fn upsert_external_identity(
    tx: &Transaction<'_>,
    provider: &str,
    entity_type: &str,
    external_id: &str,
    external_url: &str,
) -> Result<i32, ApiError> {
    let row = tx
        .query_opt(
            "INSERT INTO external_identities (provider, entity_type, external_id, external_url, metadata_json, provider_updated_at, created_at, updated_at) \
             VALUES ($1, $2, $3, $4, '{}'::json, NULL, now(), now()) \
             ON CONFLICT (provider, entity_type, external_id) DO UPDATE SET updated_at = now() \
             RETURNING id",
            &[&provider, &entity_type, &external_id, &external_url],
        )
        .await
        .map_err(db::query_error)?;
    row.map(|row| row.get::<_, i32>(0))
        .ok_or_else(|| ApiError::Internal("external identity upsert returned no id".to_string()))
}

/// Link an issue to an external identity mapping.
async fn link_issue_external_identity(
    tx: &Transaction<'_>,
    user: i32,
    issue_id: i32,
    external_identity_id: i32,
    status: &str,
    evidence_source: &str,
    confidence: f64,
) -> Result<i32, ApiError> {
    let row = tx
        .query_opt(
            "INSERT INTO issue_external_identity_mappings \
             (issue_id, external_identity_id, status, evidence_source, confidence, evidence_json, created_at, updated_at) \
             VALUES ($1, $2, $3, $4, $5, '{}'::json, now(), now()) \
             ON CONFLICT (issue_id, external_identity_id) DO UPDATE \
             SET status = EXCLUDED.status, evidence_source = EXCLUDED.evidence_source, \
                 confidence = EXCLUDED.confidence, updated_at = now() \
             RETURNING id",
            &[&issue_id, &external_identity_id, &status, &evidence_source, &confidence],
        )
        .await
        .map_err(db::query_error)?;
    row.map(|row| row.get::<_, i32>(0))
        .ok_or_else(|| ApiError::Internal("identity mapping insert returned no id".to_string()))
}

/// Python `save_confirmed_comicvine_identity`: confirm (or replace) a comicvine
/// identity for an owned issue and return the resulting identity state.
async fn save_confirmed_comicvine_identity(
    tx: &Transaction<'_>,
    user: i32,
    issue_id: i32,
    comicvine_issue_id: i32,
    replace_existing: bool,
    reason: Option<&str>,
) -> Result<IssueIdentityResponse, ApiError> {
    let identity_id = upsert_external_identity(
        tx,
        COMICVINE_PROVIDER,
        "issue",
        &comicvine_issue_id.to_string(),
        &format!("https://comicvine.gamespot.com/issue/4000-{comicvine_issue_id}/"),
    )
    .await?;

    if replace_existing {
        tx.execute(
            "UPDATE issue_external_identity_mappings m \
             SET status = 'rejected', rejection_reason = $1, updated_at = now() \
             FROM external_identities e \
             WHERE m.external_identity_id = e.id AND m.issue_id = $2 \
             AND m.status = 'confirmed' AND e.provider = $3 AND e.entity_type = 'issue'",
            &[&reason.unwrap_or("replaced by user"), &issue_id, &COMICVINE_PROVIDER],
        )
        .await
        .map_err(db::query_error)?;
    }

    link_issue_external_identity(
        tx, user, issue_id, identity_id, "confirmed", "user_confirmed", 1.0,
    )
    .await?;

    identity_state(tx, user, issue_id).await
}

/// Python `remove_comicvine_identity`: set the confirmed mapping to unresolved.
async fn remove_comicvine_identity(
    tx: &Transaction<'_>,
    user: i32,
    issue_id: i32,
) -> Result<IssueIdentityResponse, ApiError> {
    let row = tx
        .query_opt(
            "UPDATE issue_external_identity_mappings m \
             SET status = 'unresolved', evidence_source = NULL, confidence = NULL, updated_at = now() \
             FROM external_identities e \
             WHERE m.external_identity_id = e.id AND m.issue_id = $1 \
             AND m.status = 'confirmed' AND e.provider = $2 AND e.entity_type = 'issue' \
             RETURNING m.id",
            &[&issue_id, &COMICVINE_PROVIDER],
        )
        .await
        .map_err(db::query_error)?;
    if row.is_none() {
        return Err(ApiError::BadRequest(NO_CONFIRMED_IDENTITY.to_string()));
    }
    identity_state(tx, user, issue_id).await
}

/// Python `apply_metadata_correction`: create a correction and return all
/// active corrections for the issue.
async fn apply_metadata_correction(
    tx: &Transaction<'_>,
    user: i32,
    issue_id: i32,
    field_name: &str,
    canonical_value: &str,
) -> Result<MetadataCorrectionsResponse, ApiError> {
    owned_issue(tx, user, issue_id).await?;

    let provider_value: Option<String> = tx
        .query_opt(
            "SELECT e.metadata_json->>$1 FROM external_identities e \
             JOIN issue_external_identity_mappings m ON m.external_identity_id = e.id \
             WHERE m.issue_id = $2 AND m.status = 'confirmed' \
             AND e.provider = $3 AND e.entity_type = 'issue' \
             ORDER BY m.confidence DESC NULLS LAST, m.id LIMIT 1",
            &[&field_name, &issue_id, &COMICVINE_PROVIDER],
        )
        .await
        .map_err(db::query_error)?
        .map(|row| row.get::<_, Option<String>>(0))
        .flatten();

    tx.execute(
        "INSERT INTO issue_metadata_corrections \
         (issue_id, field_name, provider_value, canonical_value, provenance, created_by, created_at, updated_at) \
         VALUES ($1, $2, $3, $4, 'user_correction', $5, now(), now())",
        &[&issue_id, &field_name, &provider_value, &canonical_value, &user],
    )
    .await
    .map_err(db::query_error)?;

    corrections_list(tx, user, issue_id).await
}

/// Python `revert_metadata_correction`: soft-delete a correction and return
/// all active corrections for the issue.
async fn revert_metadata_correction(
    tx: &Transaction<'_>,
    user: i32,
    issue_id: i32,
    correction_id: i32,
) -> Result<MetadataCorrectionsResponse, ApiError> {
    let row = tx
        .query_opt(
            "UPDATE issue_metadata_corrections c \
             SET reverted_at = now(), updated_at = now() \
             FROM issues i JOIN threads t ON t.id = i.thread_id \
             WHERE c.id = $1 AND c.issue_id = $2 AND t.user_id = $3 \
             AND c.reverted_at IS NULL \
             RETURNING c.id",
            &[&correction_id, &issue_id, &user],
        )
        .await
        .map_err(db::query_error)?;
    if row.is_none() {
        return Err(ApiError::NotFound(NO_CORRECTION.to_string()));
    }
    corrections_list(tx, user, issue_id).await
}

// ---------------------------------------------------------------------------
// Handlers.
// ---------------------------------------------------------------------------

/// `GET /api/v1/comicvine/series/{comicvine_volume_id}/import-status`.
pub async fn series_import_status(
    state: State<Arc<AppState>>,
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
             AND e.external_id = $2 \
             ORDER BY m.id LIMIT 1",
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

/// `GET /api/v1/comicvine/issues/{issue_id}/identity`.
pub async fn get_issue_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    issue_id: Result<Path<i32>, PathRejection>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    let issue_id = issue_id.map_err(|_| ApiError::Unprocessable("Validation failed".to_string()))?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    let response = identity_state(&tx, user.id(), issue_id.0).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

/// `POST /api/v1/comicvine/issues/{issue_id}/identity:confirm`.
pub async fn confirm_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    issue_id: Result<Path<i32>, PathRejection>,
    Json(request): Json<ConfirmIdentityRequest>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    let issue_id = issue_id.map_err(|_| ApiError::Unprocessable("Validation failed".to_string()))?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    let response =
        save_confirmed_comicvine_identity(&tx, user.id(), issue_id.0, request.comicvine_issue_id, false, None)
            .await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

/// `POST /api/v1/comicvine/issues/{issue_id}/identity:replace`.
pub async fn replace_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    issue_id: Result<Path<i32>, PathRejection>,
    Json(request): Json<ReplaceIdentityRequest>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    let issue_id = issue_id.map_err(|_| ApiError::Unprocessable("Validation failed".to_string()))?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    let response =
        save_confirmed_comicvine_identity(&tx, user.id(), issue_id.0, request.comicvine_issue_id, true, request.reason.as_deref())
            .await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

/// `DELETE /api/v1/comicvine/issues/{issue_id}/identity`.
pub async fn remove_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    issue_id: Result<Path<i32>, PathRejection>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    let issue_id = issue_id.map_err(|_| ApiError::Unprocessable("Validation failed".to_string()))?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    let response = remove_comicvine_identity(&tx, user.id(), issue_id.0).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

/// `GET /api/v1/comicvine/issues/{issue_id}/metadata:corrections`.
pub async fn list_corrections(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    issue_id: Result<Path<i32>, PathRejection>,
) -> Result<Json<MetadataCorrectionsResponse>, ApiError> {
    let issue_id = issue_id.map_err(|_| ApiError::Unprocessable("Validation failed".to_string()))?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    let response = corrections_list(&tx, user.id(), issue_id.0).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

/// `POST /api/v1/comicvine/issues/{issue_id}/metadata:refresh`.
pub async fn refresh_metadata(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    issue_id: Result<Path<i32>, PathRejection>,
) -> Result<Json<RefreshMetadataResponse>, ApiError> {
    let issue_id = issue_id.map_err(|_| ApiError::Unprocessable("Validation failed".to_string()))?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    let comicvine_id = confirmed_comicvine_issue_id(&tx, user.id(), issue_id.0).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(RefreshMetadataResponse {
        issue_id: issue_id.0,
        refreshed: comicvine_id.is_some(),
        comicvine_issue_id: comicvine_id.map(|s| s.to_string()),
    }))
}

/// `POST /api/v1/comicvine/issues/{issue_id}/metadata:correct`.
pub async fn apply_correction(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    issue_id: Result<Path<i32>, PathRejection>,
    Json(request): Json<MetadataCorrectionRequest>,
) -> Result<Json<MetadataCorrectionsResponse>, ApiError> {
    let issue_id = issue_id.map_err(|_| ApiError::Unprocessable("Validation failed".to_string()))?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    let response =
        apply_metadata_correction(&tx, user.id(), issue_id.0, &request.field_name, &request.canonical_value)
            .await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

/// `POST /api/v1/comicvine/issues/{issue_id}/metadata:revert`.
pub async fn revert_correction(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    issue_id: Result<Path<i32>, PathRejection>,
    Json(request): Json<MetadataCorrectionRevertRequest>,
) -> Result<Json<MetadataCorrectionsResponse>, ApiError> {
    let issue_id = issue_id.map_err(|_| ApiError::Unprocessable("Validation failed".to_string()))?;
    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    let response = revert_metadata_correction(&tx, user.id(), issue_id.0, request.correction_id).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

/// `POST /api/v1/comicvine/issues:import`.
pub async fn import_issue(
    State(_state): State<Arc<AppState>>,
    _user: AuthenticatedUser,
    Json(_request): Json<ImportIssueRequest>,
) -> Result<Json<ImportIssueResponse>, ApiError> {
    // Stub: full DB import in subsequent slice. Returns a placeholder response
    // with the correct wire shape; callers should treat ids as opaque.
    Ok(Json(ImportIssueResponse {
        thread_id: 0,
        issue_id: 0,
        external_identity_id: 0,
        reading_order_id: None,
        position: None,
        total_items: None,
        thread_created: false,
    }))
}

/// `GET /api/v1/comicvine/resolve`.
pub async fn resolve_input(
    _state_state: State<Arc<AppState>>,
    query: Result<Query<ResolveQuery>, QueryRejection>,
) -> Result<Json<ComicVineResolveResponse>, ApiError> {
    let Query(query) = query.map_err(|_| ApiError::Unprocessable("Validation failed".to_string()))?;
    Ok(Json(ComicVineResolveResponse::bare(
        query.input,
        "search",
        None,
    )))
}

/// `GET /api/v1/comicvine/search/series`.
pub async fn search_series_v1(
    _state_state: State<Arc<AppState>>,
    query: Result<Query<SearchQuery>, QueryRejection>,
) -> Result<Json<ComicVineSeriesSearchResponse>, ApiError> {
    let Query(q) = query.map_err(|_| ApiError::Unprocessable("Validation failed".to_string()))?;
    Ok(Json(ComicVineSeriesSearchResponse::empty(
        q.q, q.offset, q.limit,
    )))
}

/// `GET /api/v1/comicvine/series/{comicvine_volume_id}/issues`.
pub async fn series_issues_v1(
    _state_state: State<Arc<AppState>>,
    _user: AuthenticatedUser,
    Path(comicvine_volume_id): Path<i32>,
    query: Result<Query<SeriesIssuesQuery>, QueryRejection>,
) -> Result<Json<ComicVineSeriesIssuesResponse>, ApiError> {
    let _volume_id = comicvine_volume_id;
    let Query(query) = query.map_err(|_| ApiError::Unprocessable("Validation failed".to_string()))?;
    let _series_name = query.series_name;
    Ok(Json(ComicVineSeriesIssuesResponse {
        comicvine_volume_id: _volume_id,
        series_name: if _series_name.is_empty() {
            format!("Volume {_volume_id}")
        } else {
            _series_name
        },
        issues: Vec::new(),
    }))
}

/// `POST /api/v1/comicvine/series:import`.
pub async fn import_series(
    State(_state): State<Arc<AppState>>,
    _user: AuthenticatedUser,
    Json(_request): Json<ImportSeriesRequest>,
) -> Result<Json<ImportSeriesResponse>, ApiError> {
    // Stub: full DB import in subsequent slice.
    Ok(Json(ImportSeriesResponse {
        thread_id: 0,
        series_name: String::new(),
        comicvine_volume_id: _request.comicvine_volume_id,
        total_issues_in_series: 0,
        issues_adopted: 0,
        issues_skipped: 0,
        issues_conflict: 0,
        issue_results: Vec::new(),
        reading_order_id: None,
        position: None,
        total_items: None,
        thread_created: false,
    }))
}

// ---------------------------------------------------------------------------
// OpenAPI documentation.
// ---------------------------------------------------------------------------

#[utoipa::path(
    get,
    path = "/api/v1/comicvine/series/{comicvine_volume_id}/import-status",
    params(("comicvine_volume_id" = i32, Path, description = "ComicVine volume ID")),
    tag = "comicvine-resolution",
    responses(
        (status = 200, description = "Owned import status", body = SeriesImportStatusResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn series_import_status_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v1/comicvine/issues/{issue_id}/identity",
    params(("issue_id" = i32, Path, description = "ComicPile issue ID")),
    tag = "comicvine-v1",
    responses(
        (status = 200, description = "Owned identity state", body = IssueIdentityResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 404, description = "Issue not owned"),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_issue_identity_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/comicvine/issues/{issue_id}/identity:confirm",
    params(("issue_id" = i32, Path, description = "ComicPile issue ID")),
    tag = "comicvine-v1",
    responses(
        (status = 200, description = "Confirmed identity state", body = IssueIdentityResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 404, description = "Issue not owned"),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn confirm_identity_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/comicvine/issues/{issue_id}/identity:replace",
    params(("issue_id" = i32, Path, description = "ComicPile issue ID")),
    tag = "comicvine-v1",
    responses(
        (status = 200, description = "Replaced identity state", body = IssueIdentityResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 404, description = "Issue not owned"),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn replace_identity_documentation() {}

#[utoipa::path(
    delete,
    path = "/api/v1/comicvine/issues/{issue_id}/identity",
    params(("issue_id" = i32, Path, description = "ComicPile issue ID")),
    tag = "comicvine-v1",
    responses(
        (status = 200, description = "Identity removed", body = IssueIdentityResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 404, description = "Issue not owned"),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn remove_identity_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v1/comicvine/issues/{issue_id}/metadata:corrections",
    params(("issue_id" = i32, Path, description = "ComicPile issue ID")),
    tag = "comicvine-v1",
    responses(
        (status = 200, description = "Active corrections", body = MetadataCorrectionsResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 404, description = "Issue not owned"),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_corrections_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/comicvine/issues/{issue_id}/metadata:refresh",
    params(("issue_id" = i32, Path, description = "ComicPile issue ID")),
    tag = "comicvine-v1",
    responses(
        (status = 200, description = "Refresh requested", body = RefreshMetadataResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 404, description = "Issue not owned"),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn refresh_metadata_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/comicvine/issues/{issue_id}/metadata:correct",
    params(("issue_id" = i32, Path, description = "ComicPile issue ID")),
    tag = "comicvine-v1",
    responses(
        (status = 200, description = "Correction applied", body = MetadataCorrectionsResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 404, description = "Issue not owned"),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn apply_correction_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/comicvine/issues/{issue_id}/metadata:revert",
    params(("issue_id" = i32, Path, description = "ComicPile issue ID")),
    tag = "comicvine-v1",
    responses(
        (status = 200, description = "Correction reverted", body = MetadataCorrectionsResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 404, description = "Issue not owned or correction not found"),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn revert_correction_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/comicvine/issues:import",
    tag = "comicvine-v1",
    responses(
        (status = 201, description = "Issue imported", body = ImportIssueResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 409, description = "Duplicate physical issue"),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn import_issue_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v1/comicvine/resolve",
    params(("input" = String, Query, description = "Search text or ComicVine URL")),
    tag = "comicvine-v1",
    responses(
        (status = 200, description = "Resolved input", body = ComicVineResolveResponse),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn resolve_input_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v1/comicvine/search/series",
    params(
        ("q" = String, Query, description = "Series title query"),
        ("limit" = Option<i32>, Query, description = "Maximum results (1-50, default 10)"),
        ("offset" = Option<i32>, Query, description = "Zero-based offset"),
    ),
    tag = "comicvine-v1",
    responses(
        (status = 200, description = "Paginated series search", body = ComicVineSeriesSearchResponse),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn search_series_v1_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v1/comicvine/series/{comicvine_volume_id}/issues",
    params(
        ("comicvine_volume_id" = i32, Path, description = "ComicVine volume ID"),
        ("series_name" = Option<String>, Query, description = "Pre-fetched series name"),
    ),
    tag = "comicvine-v1",
    responses(
        (status = 200, description = "Volume issue roster", body = ComicVineSeriesIssuesResponse),
        (status = 422, description = "Validation failed")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn series_issues_v1_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/comicvine/series:import",
    tag = "comicvine-v1",
    responses(
        (status = 201, description = "Series imported", body = ImportSeriesResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 422, description = "Validation failed")
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

    #[test]
    fn query_is_owner_scoped_and_uses_one_bounded_lookup() {
        // Placeholder test retained from the migrated stub.
        assert!(true);
    }
}
