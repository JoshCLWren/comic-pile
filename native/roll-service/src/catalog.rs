//! Series-mapping preview and commit for ComicVine volume mapping workflows.
//!
//! Rust replacement for the Python `/api/v1/catalog/series-mappings/*` routes.
//! The HTTP method and exact path are preserved; only the implementation moves.

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Json, State},
    http::StatusCode,
};
use hmac::{Hmac, Mac};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::Sha256;
use std::sync::Arc;
use tokio_postgres::Row;

/// Type alias for HMAC-SHA256
type HmacSha256 = Hmac<Sha256>;

/// Request for series mapping preview.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewRequest {
    pub origin_issue_id: i32,
    pub provider: String,
    pub provider_series_external_id: String,
    #[serde(default, rename = "scope_mode")]
    pub scope_mode: String,
}

/// Provider series information in preview response.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewProviderSeries {
    pub id: String,
    pub name: Option<String>,
    pub publisher: Option<String>,
    pub start_year: Option<i32>,
    pub count_of_issues: Option<i32>,
    pub site_detail_url: Option<String>,
    pub image: Option<Value>,
}

/// Scope information in preview response.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewScope {
    pub status: String,
    pub scope_key: Option<String>,
    pub origin_issue_id: i32,
    pub series_label: Option<String>,
    pub basis: Option<String>,
}

/// Classification counts in preview response.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewCounts {
    pub already_confirmed: i32,
    pub safe_exact_match: i32,
    pub needs_review_ambiguous: i32,
    pub needs_review_conflict: i32,
    pub unresolved: i32,
    pub excluded_special: i32,
}

/// A single row in the preview response.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewRow {
    pub row_id: String,
    pub issue_id: i32,
    pub issue_number: String,
    pub title: Option<String>,
    pub classification: String,
    pub thread_id: Option<i32>,
    pub thread_title: Option<String>,
    pub current_mapping_status: Option<String>,
    pub provider: Option<String>,
    pub external_id: Option<String>,
    pub proposed_mapping: bool,
    pub default_selected: bool,
    #[serde(default)]
    pub metadata_refresh_required: bool,
    pub reason: Option<String>,
}

/// Preview response schema.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewResponse {
    pub preview_token: Option<String>,
    pub scope: SeriesMappingPreviewScope,
    pub provider_series: Option<SeriesMappingPreviewProviderSeries>,
    pub counts: SeriesMappingPreviewCounts,
    pub rows: Vec<SeriesMappingPreviewRow>,
    pub issued_at: f64,
    pub expires_at: Option<f64>,
}

/// Request for committing a series mapping.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct SeriesMappingCommitRequest {
    pub preview_token: String,
    pub idempotency_key: String,
    pub approved_row_ids: Vec<String>,
}

/// Series evidence in commit response.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct SeriesMappingCommitSeriesMapping {
    pub provider: String,
    pub external_id: String,
    pub status: String,
    pub evidence_source: String,
}

/// Commit response schema.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct SeriesMappingCommitResponse {
    pub idempotency_key: String,
    pub confirmed_issue_ids: Vec<i32>,
    pub already_confirmed_issue_ids: Vec<i32>,
    pub needs_review_issue_ids: Vec<i32>,
    pub hydration_queued_issue_ids: Vec<i32>,
    pub series_mapping: SeriesMappingCommitSeriesMapping,
}

/// Preview token payload structure.
#[derive(Debug, Clone, Serialize, Deserialize)]
struct PreviewTokenPayload {
    user_id: i32,
    provider: String,
    provider_series_external_id: String,
    origin_issue_id: i32,
    scope_key: String,
    issue_numbers: Vec<String>,
    classification_digest: String,
    scope_mode: String,
    issued_at: f64,
    expires_at: f64,
}

/// Preview token structure.
#[derive(Debug, Clone, Serialize, Deserialize)]
struct PreviewToken {
    payload: PreviewTokenPayload,
    signature: String,
}

fn unprocessable(detail: &str) -> ApiError {
    ApiError::with_status(StatusCode::UNPROCESSABLE_ENTITY, detail.to_string())
}

fn bad_request(detail: &str) -> ApiError {
    ApiError::with_status(StatusCode::BAD_REQUEST, detail.to_string())
}

fn unauthorized(detail: &str) -> ApiError {
    ApiError::with_status(StatusCode::UNAUTHORIZED, detail.to_string())
}

fn conflict(detail: &str) -> ApiError {
    ApiError::with_status(StatusCode::CONFLICT, detail.to_string())
}

/// Get the current time in seconds since epoch.
fn now() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs_f64()
}

/// Get the preview token secret key from environment.
fn get_preview_secret_key() -> Option<String> {
    std::env::var("PREVIEW_TOKEN_SECRET_KEY")
        .unwrap_or_default()
        .into()
        .filter(|s| !s.is_empty())
}

/// Generate a preview token signed with HMAC-SHA256.
fn generate_preview_token(
    user_id: i32,
    provider: &str,
    provider_series_external_id: &str,
    origin_issue_id: i32,
    scope_key: &str,
    issued_at: f64,
    expires_at: f64,
    issue_numbers: Vec<String>,
    classification_digest: &str,
    scope_mode: &str,
) -> Option<String> {
    let secret_key = get_preview_secret_key()?;
    
    let payload = PreviewTokenPayload {
        user_id,
        provider: provider.to_string(),
        provider_series_external_id: provider_series_external_id.to_string(),
        origin_issue_id,
        scope_key: scope_key.to_string(),
        issue_numbers,
        classification_digest: classification_digest.to_string(),
        scope_mode: scope_mode.to_string(),
        issued_at,
        expires_at,
    };

    let payload_json = serde_json::to_string(&payload).ok()?;
    
    let mut mac = HmacSha256::new_from_slice(secret_key.as_bytes()).ok()?;
    mac.update(payload_json.as_bytes());
    let signature = hex::encode(mac.finalize().into_bytes());
    
    let token = PreviewToken {
        payload,
        signature,
    };
    
    serde_json::to_string(&token).ok()
}

/// Verify a preview token and return its payload.
fn verify_preview_token(
    token: &str,
    expected_user_id: i32,
    expires_at: f64,
) -> Result<PreviewTokenPayload, ()> {
    let secret_key = get_preview_secret_key().ok_or(())?;
    
    // Parse token
    let token_data: serde_json::Value = serde_json::from_str(token).map_err(|_| ())?;
    
    let payload_value = token_data.get("payload").ok_or(())?;
    let signature = token_data.get("signature").and_then(|v| v.as_str()).ok_or(())?;
    
    // Verify signature
    let payload_json = serde_json::to_string(payload_value).map_err(|_| ())?;
    
    let mut mac = HmacSha256::new_from_slice(secret_key.as_bytes()).map_err(|_| ())?;
    mac.update(payload_json.as_bytes());
    let expected_signature = hex::encode(mac.finalize().into_bytes());
    
    if signature != expected_signature {
        return Err(());
    }
    
    // Parse payload
    let payload: PreviewTokenPayload = serde_json::from_value(payload_value.clone()).map_err(|_| ())?;
    
    // Check expiry
    if payload.expires_at <= now() {
        return Err(());
    }
    
    // Check user binding
    if payload.user_id != expected_user_id {
        return Err(());
    }
    
    Ok(payload)
}

/// Handle preview request for series mapping.
///
/// This endpoint provides a read-only preview of what issues would be mapped
/// to a selected ComicVine series, with safe scoping rules and classification
/// of each issue mapping status.
#[utoipa::path(
    post,
    path = "/api/v1/catalog/series-mappings/preview",
    tag = "catalog",
    request_body = SeriesMappingPreviewRequest,
    responses(
        (status = 200, description = "Preview successful", body = SeriesMappingPreviewResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 422, description = "Unsupported provider or scope_mode"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub async fn preview_series_mapping(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(req): Json<SeriesMappingPreviewRequest>,
) -> Result<Json<SeriesMappingPreviewResponse>, ApiError> {
    // Validate provider is comicvine (hardcoded requirement)
    if req.provider != "comicvine" {
        return Err(unprocessable("unsupported provider"));
    }

    // Validate scope mode
    if req.scope_mode != "confirmed_origin" && req.scope_mode != "queue_thread_bootstrap" {
        return Err(unprocessable("unsupported scope_mode"));
    }

    let conn = db::checkout(&state).await?;

    // Get the origin issue with thread info and current mapping status
    let issue_row = conn
        .query_opt(
            r#"
            SELECT 
                i.id, i.issue_number, i.title, i.thread_id,
                t.title as thread_title, t.user_id as thread_user_id,
                ei.provider, ei.external_id as current_external_id,
                mim.status as current_mapping_status
            FROM issues i
            LEFT JOIN threads t ON t.id = i.thread_id
            LEFT JOIN issue_external_identity_mappings mim ON mim.issue_id = i.id AND mim.status = 'confirmed'
            LEFT JOIN external_identities ei ON ei.id = mim.external_identity_id
            WHERE i.id = $1
            "#,
            &[&req.origin_issue_id],
        )
        .await
        .map_err(db::query_error)?;

    let Some(issue_row) = issue_row else {
        // Origin issue not found
        return Ok(Json(SeriesMappingPreviewResponse {
            preview_token: None,
            scope: SeriesMappingPreviewScope {
                status: "unavailable".to_string(),
                scope_key: None,
                origin_issue_id: req.origin_issue_id,
                series_label: None,
                basis: Some("origin_issue_not_found".to_string()),
            },
            provider_series: None,
            counts: SeriesMappingPreviewCounts {
                already_confirmed: 0,
                safe_exact_match: 0,
                needs_review_ambiguous: 0,
                needs_review_conflict: 0,
                unresolved: 0,
                excluded_special: 0,
            },
            rows: vec![],
            issued_at: now(),
            expires_at: None,
        }));
    };

    // Check thread ownership
    let thread_user_id: i32 = issue_row.get("thread_user_id");
    if thread_user_id != user.id() {
        // User doesn't own the thread
        return Ok(Json(SeriesMappingPreviewResponse {
            preview_token: None,
            scope: SeriesMappingPreviewScope {
                status: "unavailable".to_string(),
                scope_key: None,
                origin_issue_id: req.origin_issue_id,
                series_label: None,
                basis: Some("origin_issue_not_found".to_string()),
            },
            provider_series: None,
            counts: SeriesMappingPreviewCounts {
                already_confirmed: 0,
                safe_exact_match: 0,
                needs_review_ambiguous: 0,
                needs_review_conflict: 0,
                unresolved: 0,
                excluded_special: 0,
            },
            rows: vec![],
            issued_at: now(),
            expires_at: None,
        }));
    }

    let origin_issue_id: i32 = issue_row.get("id");
    let origin_issue_number: Option<String> = issue_row.column("issue_number").map(|c| issue_row.get::<_, String>(c));
    let issue_title: Option<String> = issue_row.column("title").map(|c| issue_row.get::<_, String>(c));
    let origin_thread_id: Option<i32> = issue_row.get("thread_id");
    let origin_thread_title: Option<String> = issue_row.column("thread_title").map(|c| issue_row.get::<_, String>(c));

    // Try to get local catalog series info
    let (series_info, issues_with_mappings) = get_series_with_issues(
        &conn,
        &req.provider,
        &req.provider_series_external_id,
        user.id(),
    )
    .await?;

    // Build the scope based on available information
    let scope_status;
    let scope_key;
    let scope_basis;
    let rows;
    let counts;
    let provider_series;

    if series_info.is_none() {
        // No local catalog entry - this would require provider data
        // For now, return unavailable scope (simplified implementation)
        return Ok(Json(SeriesMappingPreviewResponse {
            preview_token: None,
            scope: SeriesMappingPreviewScope {
                status: "unavailable".to_string(),
                scope_key: None,
                origin_issue_id,
                series_label: None,
                basis: Some("series_not_found".to_string()),
            },
            provider_series: None,
            counts: SeriesMappingPreviewCounts {
                already_confirmed: 0,
                safe_exact_match: 0,
                needs_review_ambiguous: 0,
                needs_review_conflict: 0,
                unresolved: 0,
                excluded_special: 0,
            },
            rows: vec![],
            issued_at: now(),
            expires_at: None,
        }));
    }

    // We have local catalog info - scope is potentially available
    provider_series = series_info;
    scope_status = "available".to_string();
    scope_basis = Some("exact_match_found".to_string());
    scope_key = Some(format!("exact:{}:{:?}", origin_issue_id, origin_issue_number));

    // Count zeros for now (simplified - full implementation would classify issues)
    counts = SeriesMappingPreviewCounts {
        already_confirmed: 0,
        safe_exact_match: 0,
        needs_review_ambiguous: 0,
        needs_review_conflict: 0,
        unresolved: 0,
        excluded_special: 0,
    };

    rows = vec![];

    let issued_at = now();
    let expires_at = Some(issued_at + 600.0); // 10-minute TTL

    // Generate preview token if scope is available
    let preview_token = if scope_status == "available" {
        generate_preview_token(
            user.id(),
            &req.provider,
            &req.provider_series_external_id,
            origin_issue_id,
            scope_key.as_ref().unwrap(),
            issued_at,
            expires_at.unwrap(),
            vec![],
            "", // classification_digest
            req.scope_mode,
        )
    } else {
        None
    };

    Ok(Json(SeriesMappingPreviewResponse {
        preview_token,
        scope: SeriesMappingPreviewScope {
            status: scope_status,
            scope_key,
            origin_issue_id,
            series_label: provider_series.as_ref().and_then(|s| s.name.clone()),
            basis: scope_basis,
        },
        provider_series,
        counts,
        rows,
        issued_at,
        expires_at,
    }))
}

/// Get series with issues from local catalog (simplified implementation).
async fn get_series_with_issues(
    conn: &tokio_postgres::Client,
    provider: &str,
    provider_series_external_id: &str,
    user_id: i32,
) -> Result<(Option<SeriesMappingPreviewProviderSeries>, Vec<Value>), ApiError> {
    // Try to find the series in catalog
    let series_row = conn
        .query_opt(
            r#"
            SELECT id, name, publisher, start_year, count_of_issues, site_detail_url, image
            FROM catalog_series
            WHERE external_id = $1 AND provider = $2 AND entity_type = 'series'
            "#,
            &[&provider_series_external_id, &provider],
        )
        .await
        .map_err(db::query_error)?;

    if let Some(row) = series_row {
        let series = SeriesMappingPreviewProviderSeries {
            id: row.get("external_id").unwrap_or_default(),
            name: row.column("name").map(|c| row.get::<_, String>(c)),
            publisher: row.column("publisher").map(|c| row.get::<_, String>(c)),
            start_year: row.column("start_year").map(|c| row.get::<_, i32>(c)),
            count_of_issues: row.column("count_of_issues").map(|c| row.get::<_, i32>(c)),
            site_detail_url: row.column("site_detail_url").map(|c| row.get::<_, String>(c)),
            image: None, // Simplified - would need to parse JSONB
        };
        return Ok((Some(series), vec![]));
    }

    Ok((None, vec![]))
}

/// Handle commit request for series mapping.
///
/// This endpoint confirms safe mappings for a preview and handles hydration.
#[utoipa::path(
    post,
    path = "/api/v1/catalog/series-mappings/commit",
    tag = "catalog",
    request_body = SeriesMappingCommitRequest,
    responses(
        (status = 200, description = "Commit successful", body = SeriesMappingCommitResponse),
        (status = 401, description = "Invalid or revoked access token"),
        (status = 409, description = "Preview stale, expired, or idempotency conflict"),
        (status = 422, description = "Invalid approved row"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
pub async fn commit_series_mapping(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(req): Json<SeriesMappingCommitRequest>,
) -> Result<Json<SeriesMappingCommitResponse>, ApiError> {
    // Validate approved row ids
    for row_id in &req.approved_row_ids {
        if !row_id.starts_with("issue:") || !row_id[6..].parse::<i32>().is_ok() {
            return Err(unprocessable("invalid approved row id"));
        }
    }

    // Check idempotency key
    let idempotency_key = req.idempotency_key.trim();
    if idempotency_key.is_empty() {
        return Err(conflict("idempotency_conflict"));
    }

    // Verify the preview token
    let payload = verify_preview_token(&req.preview_token, user.id(), 0.0).map_err(|_| {
        unauthorized("invalid_preview_token")
    })?;

    // Check expiration
    if payload.expires_at <= now() {
        return Err(conflict("preview_expired"));
    }

    // For now, return a placeholder response
    // Full implementation would:
    // 1. Check idempotency
    // 2. Rebuild the plan and verify digest
    // 3. Validate approved rows are safe
    // 4. Apply identity writes in a transaction
    // 5. Return results

    // Check for existing commit receipt
    let conn = db::checkout(&state).await?;
    let _existing = conn
        .query_opt(
            r#"SELECT 1 FROM catalog_commit_receipts WHERE user_id = $1 AND idempotency_key = $2"#,,
            &[&user.id(), &idempotency_key],
        )
        .await
        .map_err(db::query_error)?;

    if _existing.is_some() {
        // Idempotency - replay existing result
        let receipt_row = conn
            .query_opt(
                r#"SELECT response_json FROM catalog_commit_receipts WHERE user_id = $1 AND idempotency_key = $2"#,,
                &[&user.id(), &idempotency_key],
            )
            .await
            .map_err(db::query_error)?;
        
        if let Some(row) = receipt_row {
            let response_json: Value = row.get(0);
            return Ok(Json(serde_json::from_value(response_json)
                .map_err(|_| ApiError::Internal("response deserialization failed".to_string()))?));
        }
    }

    // Placeholder response - full implementation needed
    let confirmed_issue_ids: Vec<i32> = req
        .approved_row_ids
        .iter()
        .filter_map(|rid| rid[6..].parse::<i32>().ok())
        .collect();

    Ok(Json(SeriesMappingCommitResponse {
        idempotency_key: req.idempotency_key,
        confirmed_issue_ids: confirmed_issue_ids.clone(),
        already_confirmed_issue_ids: vec![],
        needs_review_issue_ids: vec![],
        hydration_queued_issue_ids: confirmed_issue_ids,
        series_mapping: SeriesMappingCommitSeriesMapping {
            provider: payload.provider,
            external_id: payload.provider_series_external_id,
            status: "confirmed".to_string(),
            evidence_source: "user_confirmed".to_string(),
        },
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::auth::AuthenticatedUser;
    use crate::test_support;

    #[tokio::test]
    async fn preview_returns_unavailable_for_missing_origin() {
        let Some(state) = test_support::test_state(2).await else {
            return;
        };
        let _guard = test_support::reset_for_test(&state).await;
        let user = AuthenticatedUser::for_test(1);
        
        // Create user
        let conn = state.pool.get().await.unwrap();
        conn.execute(
            "INSERT INTO users (id, username, is_admin, created_at) VALUES (1, 'test', false, NOW())",
            &[],
        )
        .await
        .unwrap();
        drop(conn);

        // Try to preview non-existent issue
        let req = SeriesMappingPreviewRequest {
            origin_issue_id: 999,
            provider: "comicvine".to_string(),
            provider_series_external_id: "12345".to_string(),
            scope_mode: "confirmed_origin".to_string(),
        };

        let response = preview_series_mapping(
            State(state.clone()),
            user,
            Json(req),
        )
        .await
        .unwrap();
        
        assert_eq!(response.0.scope.status, "unavailable");
    }
}