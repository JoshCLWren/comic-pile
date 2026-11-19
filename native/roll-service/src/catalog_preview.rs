//! Same-path native Rust handler for catalog series-mapping preview.
//! Preserves the Python wire contract: POST /api/v1/catalog/series-mappings/preview.
//!
//! API version is not implementation language; see AGENTS.md.

use axum::{
    extract::{State, Json as AxumJson},
    Json,
};
use serde::Deserialize;
use serde_json::Value;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};
use tracing::instrument;

use crate::{
    auth::AuthenticatedUser, catalog_commit::{build_plan_db, canonical_json, hex_digest},
    db::checkout, ApiError, AppState,
};

/// Preview token TTL in seconds, matching Python's PREVIEW_TOKEN_TTL_SECONDS.
const PREVIEW_TOKEN_TTL_SECONDS: f64 = 600.0;

/// Python `SeriesMappingPreviewRequest` wire schema.
#[derive(Debug, Clone, Deserialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewRequest {
    pub origin_issue_id: i32,
    pub provider: String,
    pub provider_series_external_id: String,
    #[serde(default)]
    pub scope_mode: String,
}

/// Python `SeriesMappingPreviewResponse` wire schema.
#[derive(Debug, Clone, serde::Serialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewResponse {
    pub preview_token: Option<String>,
    pub scope: Value,
    pub provider_series: Option<Value>,
    pub counts: Value,
    pub rows: Vec<Value>,
    pub issued_at: f64,
    pub expires_at: Option<f64>,
}

/// Serve `POST /api/v1/catalog/series-mappings/preview`.
///
/// Builds the same read-only series-mapping plan Python builds, then mints an
/// HMAC-signed preview token when the scope is available. No rows are mutated.
#[instrument(skip(state))]
pub async fn preview_series_mapping_handler(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    AxumJson(req): AxumJson<SeriesMappingPreviewRequest>,
) -> Result<Json<SeriesMappingPreviewResponse>, ApiError> {
    let conn = checkout(&state).await?;
    let plan = build_plan_db(
        &state.outbound,
        &conn,
        user.id(),
        req.origin_issue_id,
        &req.provider,
        &req.provider_series_external_id,
        &req.scope_mode,
    )
    .await?;

    let scope = plan.get("scope").cloned().unwrap_or(Value::Null);
    let scope_available = scope
        .get("status")
        .and_then(|v| v.as_str())
        == Some("available");

    let issued_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64();
    let expires_at = if scope_available {
        Some(issued_at + PREVIEW_TOKEN_TTL_SECONDS)
    } else {
        None
    };

    let preview_token = if scope_available {
        let scope_key = plan
            .get("scope_key")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let issue_numbers = plan
            .get("issue_numbers")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        let state_digest = plan
            .get("state_digest")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        let payload = serde_json::json!({
            "user_id": user.id(),
            "provider": req.provider,
            "provider_series_external_id": req.provider_series_external_id,
            "origin_issue_id": req.origin_issue_id,
            "scope_key": scope_key,
            "issue_numbers": issue_numbers,
            "classification_digest": state_digest,
            "scope_mode": req.scope_mode,
            "issued_at": issued_at,
            "expires_at": expires_at.unwrap_or(issued_at),
        });

        let signature = hmac_sign(&state.preview_token_secret, &payload)?;
        serde_json::to_string(&serde_json::json!({
            "payload": payload,
            "signature": signature,
        }))
        .ok()
    } else {
        None
    };

    Ok(Json(SeriesMappingPreviewResponse {
        preview_token,
        scope,
        provider_series: plan.get("provider_series").cloned(),
        counts: plan.get("counts").cloned().unwrap_or(Value::Null),
        rows: plan.get("rows").and_then(|v| v.as_array()).cloned().unwrap_or_default(),
        issued_at,
        expires_at,
    }))
}

/// HMAC-SHA256 signature matching Python's `hmac.new(secret, json.dumps(payload, sort_keys=True))`.
fn hmac_sign(secret: &str, payload: &Value) -> Result<String, ApiError> {
    let canonical = canonical_json(payload);
    hex_hmac_sha256(secret, &canonical).map_err(|_| {
        ApiError::Internal("preview signature unavailable".to_string())
    })
}

fn hex_hmac_sha256(secret: &str, message: &str) -> Result<String, hmac::digest::InvalidLength> {
    use hmac::{digest::KeyInit, Hmac, Mac};
    use sha2::Sha256;
    type HmacSha256 = Hmac<Sha256>;
    let mut mac = HmacSha256::new_from_slice(secret.as_bytes())?;
    mac.update(message.as_bytes());
    Ok(hex_digest(&mac.finalize().into_bytes()))
}

/// Documentation-only operation for the preview handler.
#[utoipa::path(
    post,
    path = "/api/v1/catalog/series-mappings/preview",
    request_body = SeriesMappingPreviewRequest,
    responses(
        (status = 200, description = "Series mapping preview", body = SeriesMappingPreviewResponse),
        (status = 401, description = "Not authenticated"),
        (status = 409, description = "preview_stale or preview_expired"),
        (status = 422, description = "Request payload failed validation"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    tag = "catalog",
    security(("HTTPBearer" = []))
)]
pub fn preview_series_mapping_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{config::Config, test_support::DB_LOCK};
    use axum::extract::State;
    use std::sync::Arc;

    async fn test_state() -> Arc<AppState> {
        let url = crate::test_support::database_url().await;
        let config = Config::from_lookup(|name| match name {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-catalog-preview-test".into()),
            "RUST_ROLL_POOL_SIZE" => Some("2".into()),
            _ => None,
        })
        .expect("catalog-preview test config");
        Arc::new(AppState::new(config).expect("catalog-preview test state"))
    }

    #[tokio::test]
    async fn preview_series_mapping_returns_200_for_missing_origin() {
        let _guard = DB_LOCK.lock().await;
        let state = test_state().await;
        crate::test_support::reset(&state).await;

        let result = preview_series_mapping_handler(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            AxumJson(SeriesMappingPreviewRequest {
                origin_issue_id: 999999,
                provider: "comicvine".to_string(),
                provider_series_external_id: "12345".to_string(),
                scope_mode: "confirmed_origin".to_string(),
            }),
        )
        .await;

        assert!(result.is_ok());
        let response = result.unwrap();
        let scope = response.scope.get("status").and_then(|v| v.as_str());
        assert_eq!(scope, Some("unavailable"));
        assert!(response.preview_token.is_none());
        assert_eq!(response.rows.len(), 0);
    }

    #[tokio::test]
    async fn preview_series_mapping_requires_auth() {
        let _guard = DB_LOCK.lock().await;
        let state = test_state().await;
        crate::test_support::reset(&state).await;

        let result = preview_series_mapping_handler(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            AxumJson(SeriesMappingPreviewRequest {
                origin_issue_id: 1,
                provider: "comicvine".to_string(),
                provider_series_external_id: "12345".to_string(),
                scope_mode: "confirmed_origin".to_string(),
            }),
        )
        .await;

        assert!(result.is_ok());
    }
}
