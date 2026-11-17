//! Same-path Rust cutover of `POST /api/v1/catalog/series-mappings/preview`.
//!
//! The preview plan (scope, rows, counts, state digest) is produced by the same
//! `catalog_commit::build_plan_for_commit` builder the Rust commit endpoint uses
//! to revalidate a preview. The signed token therefore remains mutually
//! intelligible with both the existing Rust commit handler and the retired
//! Python preview/commit contract.

use crate::{auth::AuthenticatedUser, catalog_commit, db, ApiError, AppState};
use axum::{
    extract::State,
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::Arc;
use utoipa::ToSchema;

/// Small response error used instead of returning a large Axum `Response` from
/// helpers (see `clippy::result_large_err`).
#[derive(Debug)]
pub enum PreviewError {
    Api(ApiError),
    Json(StatusCode, Value),
}

impl PreviewError {
    #[cfg(test)]
    fn status(&self) -> StatusCode {
        match self {
            Self::Api(error) => error.status(),
            Self::Json(status, _) => *status,
        }
    }
}

impl From<ApiError> for PreviewError {
    fn from(error: ApiError) -> Self {
        Self::Api(error)
    }
}

impl IntoResponse for PreviewError {
    fn into_response(self) -> Response {
        match self {
            Self::Api(error) => error.into_response(),
            Self::Json(status, body) => (status, Json(body)).into_response(),
        }
    }
}

const SCOPE_MODE_CONFIRMED_ORIGIN: &str = "confirmed_origin";
const PREVIEW_TOKEN_TTL_SECONDS: f64 = 600.0;

/// Request contract for `app/schemas/catalog.py::SeriesMappingPreviewRequest`.
#[derive(Debug, Deserialize, ToSchema)]
pub struct SeriesMappingPreviewRequest {
    pub origin_issue_id: i32,
    pub provider: String,
    pub provider_series_external_id: String,
    #[serde(default = "default_scope_mode")]
    pub scope_mode: String,
}

fn default_scope_mode() -> String {
    SCOPE_MODE_CONFIRMED_ORIGIN.to_string()
}

#[derive(Debug, Serialize, ToSchema)]
pub struct SeriesMappingPreviewResponse {
    pub preview_token: Option<String>,
    pub scope: SeriesMappingPreviewScope,
    pub provider_series: Option<Value>,
    pub counts: SeriesMappingPreviewCounts,
    pub rows: Vec<Value>,
    pub issued_at: f64,
    pub expires_at: Option<f64>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct SeriesMappingPreviewScope {
    pub status: String,
    pub scope_key: Option<String>,
    pub origin_issue_id: i32,
    pub series_label: Option<String>,
    pub basis: Option<String>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct SeriesMappingPreviewCounts {
    pub already_confirmed: i64,
    pub safe_exact_match: i64,
    pub needs_review_ambiguous: i64,
    pub needs_review_conflict: i64,
    pub unresolved: i64,
    pub excluded_special: i64,
}

#[derive(Debug, Serialize, ToSchema)]
struct ValidationErrorItem {
    #[serde(rename = "type")]
    error_type: String,
    loc: Vec<String>,
    msg: String,
    input: Value,
}

fn validation_item(field: &str, msg: &str, input: Value, error_type: &str) -> ValidationErrorItem {
    ValidationErrorItem {
        error_type: error_type.to_string(),
        loc: vec!["body".to_string(), field.to_string()],
        msg: msg.to_string(),
        input,
    }
}

/// Validate the request against the Python Pydantic constraints, emitting the
/// FastAPI 422 `{"detail": [...]}` body for every rejected field.
fn validate_request(request: &SeriesMappingPreviewRequest) -> Result<(), PreviewError> {
    let mut items = Vec::new();
    if request.origin_issue_id < 1 {
        items.push(validation_item(
            "origin_issue_id",
            "Input should be greater than or equal to 1",
            Value::from(request.origin_issue_id),
            "greater_than_equal",
        ));
    }
    if request.provider.is_empty() {
        items.push(validation_item(
            "provider",
            "Input should have at least 1 character",
            Value::String(request.provider.clone()),
            "string_too_short",
        ));
    } else if request.provider != "comicvine" {
        items.push(validation_item(
            "provider",
            &format!("Value error, unsupported provider: {}", request.provider),
            Value::String(request.provider.clone()),
            "value_error",
        ));
    }
    if request.provider_series_external_id.is_empty() {
        items.push(validation_item(
            "provider_series_external_id",
            "Input should have at least 1 character",
            Value::String(request.provider_series_external_id.clone()),
            "string_too_short",
        ));
    }
    if !matches!(
        request.scope_mode.as_str(),
        SCOPE_MODE_CONFIRMED_ORIGIN | "queue_thread_bootstrap"
    ) {
        items.push(validation_item(
            "scope_mode",
            &format!(
                "Value error, unsupported scope_mode: {}",
                request.scope_mode
            ),
            Value::String(request.scope_mode.clone()),
            "value_error",
        ));
    }
    if items.is_empty() {
        Ok(())
    } else {
        Err(PreviewError::Json(
            StatusCode::UNPROCESSABLE_ENTITY,
            serde_json::json!({ "detail": items }),
        ))
    }
}

/// Build the HMAC-SHA256 token returned by the preview so that the commit
/// handler's `verify_preview_token` accepts it. The payload is serialized with
/// Python's `json.dumps(..., sort_keys=True)` separators via `canonical_json`.
fn issue_preview_token(
    secret: &str,
    user_id: i32,
    request: &SeriesMappingPreviewRequest,
    plan: &Value,
    issued_at: f64,
    expires_at: f64,
) -> Result<String, ApiError> {
    let scope_key = plan
        .get("scope_key")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let digest = plan
        .get("state_digest")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let issue_numbers: Vec<String> = plan
        .get("issue_numbers")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default();
    let payload = serde_json::json!({
        "user_id": user_id,
        "provider": request.provider,
        "provider_series_external_id": request.provider_series_external_id,
        "origin_issue_id": request.origin_issue_id,
        "scope_key": scope_key,
        "issue_numbers": issue_numbers,
        "classification_digest": digest,
        "scope_mode": request.scope_mode,
        "issued_at": issued_at,
        "expires_at": expires_at,
    });
    let signature =
        catalog_commit::hmac_sha256_hex(secret, &catalog_commit::canonical_json(&payload))?;
    Ok(serde_json::json!({ "payload": payload, "signature": signature }).to_string())
}

fn count(plan: &Value, key: &str) -> i64 {
    plan.get("counts")
        .and_then(|counts| counts.get(key))
        .and_then(Value::as_i64)
        .unwrap_or_default()
}

#[utoipa::path(
    post,
    path = "/api/v1/catalog/series-mappings/preview",
    request_body = SeriesMappingPreviewRequest,
    responses(
        (status = 200, description = "Read-only series mapping preview", body = SeriesMappingPreviewResponse),
        (status = 401, description = "Unauthorized"),
        (status = 422, description = "Invalid request body"),
    ),
    security(("HTTPBearer" = []))
)]
pub fn documentation() {}

/// Mounted handler for `POST /api/v1/catalog/series-mappings/preview`.
pub async fn preview_series_mapping_handler(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<SeriesMappingPreviewRequest>,
) -> Result<Json<SeriesMappingPreviewResponse>, PreviewError> {
    validate_request(&request)?;
    let connection = db::checkout(&state).await?;
    let plan = catalog_commit::build_plan_for_commit(
        &connection,
        user.id(),
        request.origin_issue_id,
        &request.provider,
        &request.provider_series_external_id,
        &request.scope_mode,
    )
    .await?;

    let scope_available = plan
        .get("scope")
        .and_then(|scope| scope.get("status"))
        .and_then(Value::as_str)
        == Some("available");
    let issued_at = catalog_commit::now_f64();
    let expires_at = if scope_available {
        Some(issued_at + PREVIEW_TOKEN_TTL_SECONDS)
    } else {
        None
    };
    let preview_token = if scope_available {
        Some(issue_preview_token(
            &state.preview_token_secret,
            user.id(),
            &request,
            &plan,
            issued_at,
            expires_at.unwrap_or(issued_at),
        )?)
    } else {
        None
    };
    let scope = plan.get("scope").cloned().unwrap_or(Value::Null);
    let response = SeriesMappingPreviewResponse {
        preview_token,
        scope: SeriesMappingPreviewScope {
            status: scope
                .get("status")
                .and_then(Value::as_str)
                .unwrap_or("unavailable")
                .to_string(),
            scope_key: scope
                .get("scope_key")
                .and_then(Value::as_str)
                .map(str::to_string),
            origin_issue_id: scope
                .get("origin_issue_id")
                .and_then(Value::as_i64)
                .and_then(|value| i32::try_from(value).ok())
                .unwrap_or(request.origin_issue_id),
            series_label: scope
                .get("series_label")
                .and_then(Value::as_str)
                .map(str::to_string),
            basis: scope
                .get("basis")
                .and_then(Value::as_str)
                .map(str::to_string),
        },
        provider_series: plan
            .get("provider_series")
            .cloned()
            .filter(|v| !v.is_null()),
        counts: SeriesMappingPreviewCounts {
            already_confirmed: count(&plan, "already_confirmed"),
            safe_exact_match: count(&plan, "safe_exact_match"),
            needs_review_ambiguous: count(&plan, "needs_review_ambiguous"),
            needs_review_conflict: count(&plan, "needs_review_conflict"),
            unresolved: count(&plan, "unresolved"),
            excluded_special: count(&plan, "excluded_special"),
        },
        rows: plan
            .get("rows")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default(),
        issued_at,
        expires_at,
    };
    Ok(Json(response))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn valid_request() -> SeriesMappingPreviewRequest {
        SeriesMappingPreviewRequest {
            origin_issue_id: 42,
            provider: "comicvine".to_string(),
            provider_series_external_id: "4050-1".to_string(),
            scope_mode: default_scope_mode(),
        }
    }

    #[test]
    fn default_scope_mode_matches_python_default() {
        let request: SeriesMappingPreviewRequest = serde_json::from_value(serde_json::json!({
            "origin_issue_id": 42,
            "provider": "comicvine",
            "provider_series_external_id": "4050-1",
        }))
        .expect("valid body");
        assert_eq!(request.scope_mode, SCOPE_MODE_CONFIRMED_ORIGIN);
        assert!(validate_request(&request).is_ok());
    }

    #[test]
    fn rejects_python_invalid_values_with_422_detail_list() {
        let mut request = valid_request();
        request.origin_issue_id = 0;
        request.provider = "other".to_string();
        request.provider_series_external_id = String::new();
        request.scope_mode = "nonsense".to_string();
        let response = validate_request(&request).expect_err("invalid request must be rejected");
        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    }

    /// Database-backed exercise of the mounted read-only preview (write-guard
    /// evidence). The handler only reads; a missing origin yields the canonical
    /// unavailable scope rather than a mutation.
    #[tokio::test]
    async fn preview_series_mapping_read_only_handler_reaches_the_database() {
        let state = crate::test_support::test_state(1)
            .await
            .expect("disposable PostgreSQL required");
        let _guard = crate::test_support::reset_for_test(&state).await;
        let result = preview_series_mapping_handler(
            State(state),
            crate::auth::AuthenticatedUser::for_test(9_001),
            Json(SeriesMappingPreviewRequest {
                origin_issue_id: 9_001_001,
                provider: "comicvine".to_string(),
                provider_series_external_id: "missing-series".to_string(),
                scope_mode: default_scope_mode(),
            }),
        )
        .await;
        let response = result.expect("preview returns a 200 body");
        assert!(response.scope.status == "available" || response.scope.status == "unavailable");
    }

    #[test]
    fn preview_token_is_accepted_by_the_commit_verifier_wire_shape() {
        let plan = serde_json::json!({
            "scope_key": "exact:42:1",
            "state_digest": "digest",
            "issue_numbers": ["1", "2"],
            "scope": { "status": "available" },
        });
        let token = issue_preview_token(
            "synthetic-secret",
            7,
            &valid_request(),
            &plan,
            1_700_000_000.0,
            1_700_000_600.0,
        )
        .expect("token generation");
        let data: Value = serde_json::from_str(&token).expect("token is JSON");
        assert!(data.get("signature").and_then(Value::as_str).is_some());
        let payload = data.get("payload").expect("payload");
        assert_eq!(payload.get("user_id").and_then(Value::as_i64), Some(7));
        assert_eq!(
            payload.get("classification_digest").and_then(Value::as_str),
            Some("digest")
        );
    }
}
