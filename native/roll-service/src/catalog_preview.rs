//! Same-path native Rust handler for the browser-called series-mapping preview
//! operation migrated for #4842.
//!
//! Preserves the Python `app/api/catalog.py` + `app/services/catalog.py`
//! wire contract at the same HTTP method and exact path:
//!
//! * `POST /api/v1/catalog/series-mappings/preview`
//!
//! Only the implementation moves from Python FastAPI to the native Roll
//! binary. No frontend URL changes; the Python handler remains mounted until
//! authenticated production proof permits its removal.
//!
//! The plan build reuses `catalog_commit::build_plan_db` (the same deterministic
//! plan the commit path revalidates), so preview and commit stay wire-compatible.
//! Preview token generation mirrors Python's `_generate_preview_token`:
//! HMAC-SHA256 over `json.dumps(payload, sort_keys=True)` default separators,
//! wrapped as `{"payload": ..., "signature": ...}`.

use crate::{
    auth::AuthenticatedUser, catalog_commit, db, ApiError, AppState,
};
use axum::{
    extract::State,
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};
use tracing::instrument;

// ---------------------------------------------------------------------------
// Wire schemas (field-for-field parity with app/schemas/catalog.py)
// ---------------------------------------------------------------------------

/// Python `SeriesMappingPreviewRequest`.
#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewRequest {
    pub origin_issue_id: i32,
    pub provider: String,
    pub provider_series_external_id: String,
    #[serde(default = "default_scope_mode")]
    pub scope_mode: String,
}

fn default_scope_mode() -> String {
    "confirmed_origin".to_string()
}

/// Python `SeriesMappingPreviewScope`.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewScope {
    pub status: String,
    pub scope_key: Option<String>,
    pub origin_issue_id: i32,
    pub series_label: Option<String>,
    pub basis: Option<String>,
}

/// Python `SeriesMappingPreviewCounts`.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewCounts {
    pub already_confirmed: i64,
    pub safe_exact_match: i64,
    pub needs_review_ambiguous: i64,
    pub needs_review_conflict: i64,
    pub unresolved: i64,
    pub excluded_special: i64,
}

/// Python `SeriesMappingPreviewRow`.
#[derive(Debug, Serialize, utoipa::ToSchema)]
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
    #[serde(skip_serializing_if = "Option::is_none")]
    pub metadata_refresh_required: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
}

/// Python `SeriesMappingPreviewProviderSeries`.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewProviderSeries {
    pub id: String,
    pub name: Option<String>,
    pub publisher: Option<String>,
    pub start_year: Option<i64>,
    pub count_of_issues: Option<i64>,
    pub site_detail_url: Option<String>,
    pub image: Option<Value>,
}

/// Python `SeriesMappingPreviewResponse`.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewResponse {
    pub preview_token: Option<String>,
    pub scope: SeriesMappingPreviewScope,
    pub provider_series: Option<SeriesMappingPreviewProviderSeries>,
    pub counts: SeriesMappingPreviewCounts,
    pub rows: Vec<SeriesMappingPreviewRow>,
    pub issued_at: f64,
    pub expires_at: Option<f64>,
}

// ---------------------------------------------------------------------------
// Validation errors (FastAPI-compatible 422 envelopes)
// ---------------------------------------------------------------------------

#[derive(Debug, Serialize)]
pub struct ValidationErrorItem {
    #[serde(rename = "type")]
    pub error_type: String,
    pub loc: Vec<String>,
    pub msg: String,
    pub input: Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ctx: Option<Value>,
}

#[derive(Debug, Serialize)]
struct ValidationErrorResponse {
    pub detail: Vec<ValidationErrorItem>,
}

#[derive(Debug)]
pub enum PreviewError {
    Api(ApiError),
    Validation(Vec<ValidationErrorItem>),
}

impl From<ApiError> for PreviewError {
    fn from(error: ApiError) -> Self {
        PreviewError::Api(error)
    }
}

impl IntoResponse for PreviewError {
    fn into_response(self) -> Response {
        match self {
            PreviewError::Api(error) => error.into_response(),
            PreviewError::Validation(items) => (
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(ValidationErrorResponse { detail: items }),
            )
                .into_response(),
        }
    }
}

fn value_error(field: &str, msg: String, input: Value) -> ValidationErrorItem {
    ValidationErrorItem {
        error_type: "value_error".to_string(),
        loc: vec!["body".to_string(), field.to_string()],
        msg,
        input,
        ctx: Some(serde_json::json!({"error": {}})),
    }
}

/// Validate request fields with Python Pydantic semantics, returning a single
/// 422 envelope with every violation.
fn validate_request(
    req: &SeriesMappingPreviewRequest,
) -> Result<(), Vec<ValidationErrorItem>> {
    let mut errors: Vec<ValidationErrorItem> = Vec::new();

    if req.origin_issue_id < 1 {
        errors.push(value_error(
            "origin_issue_id",
            format!(
                "Input should be greater than or equal to 1, not {}",
                req.origin_issue_id
            ),
            Value::Number(req.origin_issue_id.into()),
        ));
    }

    if req.provider.trim().is_empty() {
        errors.push(value_error(
            "provider",
            "Value error, provider must not be blank".to_string(),
            Value::String(req.provider.clone()),
        ));
    } else if req.provider != "comicvine" {
        errors.push(value_error(
            "provider",
            format!("unsupported provider: {}", req.provider),
            Value::String(req.provider.clone()),
        ));
    }

    if req.provider_series_external_id.trim().is_empty() {
        errors.push(value_error(
            "provider_series_external_id",
            "Value error, provider_series_external_id must not be blank".to_string(),
            Value::String(req.provider_series_external_id.clone()),
        ));
    }

    let mode = req.scope_mode.trim();
    if mode != "confirmed_origin" && mode != "queue_thread_bootstrap" {
        errors.push(value_error(
            "scope_mode",
            format!("unsupported scope_mode: {}", req.scope_mode),
            Value::String(req.scope_mode.clone()),
        ));
    }

    if errors.is_empty() {
        Ok(())
    } else {
        Err(errors)
    }
}

// ---------------------------------------------------------------------------
// Plan → response conversion
// ---------------------------------------------------------------------------

fn counts_from_plan(plan: &Value) -> SeriesMappingPreviewCounts {
    let counts = plan
        .get("counts")
        .and_then(|c| c.as_object())
        .cloned()
        .unwrap_or_default();
    SeriesMappingPreviewCounts {
        already_confirmed: counts
            .get("already_confirmed")
            .and_then(|v| v.as_i64())
            .unwrap_or(0),
        safe_exact_match: counts
            .get("safe_exact_match")
            .and_then(|v| v.as_i64())
            .unwrap_or(0),
        needs_review_ambiguous: counts
            .get("needs_review_ambiguous")
            .and_then(|v| v.as_i64())
            .unwrap_or(0),
        needs_review_conflict: counts
            .get("needs_review_conflict")
            .and_then(|v| v.as_i64())
            .unwrap_or(0),
        unresolved: counts
            .get("unresolved")
            .and_then(|v| v.as_i64())
            .unwrap_or(0),
        excluded_special: counts
            .get("excluded_special")
            .and_then(|v| v.as_i64())
            .unwrap_or(0),
    }
}

fn rows_from_plan(plan: &Value) -> Vec<SeriesMappingPreviewRow> {
    let rows = plan
        .get("rows")
        .and_then(|r| r.as_array())
        .cloned()
        .unwrap_or_default();
    rows.iter()
        .map(|row| {
            let row_id = row
                .get("row_id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let issue_id = row
                .get("issue_id")
                .and_then(|v| v.as_i64())
                .map(|v| v as i32)
                .unwrap_or(0);
            let issue_number = row
                .get("issue_number")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let title = row.get("title").and_then(|v| v.as_str()).map(|s| s.to_string());
            let classification = row
                .get("classification")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let thread_id = row.get("thread_id").and_then(|v| v.as_i64()).map(|v| v as i32);
            let thread_title = row
                .get("thread_title")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            let current_mapping_status = row
                .get("current_mapping_status")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            let provider = row.get("provider").and_then(|v| v.as_str()).map(|s| s.to_string());
            let external_id = row
                .get("external_id")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            let proposed_mapping = row
                .get("proposed_mapping")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            let default_selected = row
                .get("default_selected")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            let metadata_refresh_required = row
                .get("metadata_refresh_required")
                .and_then(|v| v.as_bool());
            let reason = row.get("reason").and_then(|v| v.as_str()).map(|s| s.to_string());
            SeriesMappingPreviewRow {
                row_id,
                issue_id,
                issue_number,
                title,
                classification,
                thread_id,
                thread_title,
                current_mapping_status,
                provider,
                external_id,
                proposed_mapping,
                default_selected,
                metadata_refresh_required,
                reason,
            }
        })
        .collect()
}

fn provider_series_from_plan(plan: &Value) -> Option<SeriesMappingPreviewProviderSeries> {
    let ps = plan.get("provider_series")?;
    Some(SeriesMappingPreviewProviderSeries {
        id: ps.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        name: ps.get("name").and_then(|v| v.as_str()).map(|s| s.to_string()),
        publisher: ps
            .get("publisher")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string()),
        start_year: ps.get("start_year").and_then(|v| v.as_i64()),
        count_of_issues: ps.get("count_of_issues").and_then(|v| v.as_i64()),
        site_detail_url: ps
            .get("site_detail_url")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string()),
        image: ps.get("image").cloned(),
    })
}

fn scope_from_plan(plan: &Value) -> SeriesMappingPreviewScope {
    let scope = plan.get("scope").and_then(|s| s.as_object()).cloned().unwrap_or_default();
    SeriesMappingPreviewScope {
        status: scope
            .get("status")
            .and_then(|v| v.as_str())
            .unwrap_or("unavailable")
            .to_string(),
        scope_key: scope.get("scope_key").and_then(|v| v.as_str()).map(|s| s.to_string()),
        origin_issue_id: scope
            .get("origin_issue_id")
            .and_then(|v| v.as_i64())
            .map(|v| v as i32)
            .unwrap_or(0),
        series_label: scope
            .get("series_label")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string()),
        basis: scope.get("basis").and_then(|v| v.as_str()).map(|s| s.to_string()),
    }
}

// ---------------------------------------------------------------------------
// Handler
// ---------------------------------------------------------------------------

/// `POST /api/v1/catalog/series-mappings/preview`
#[instrument(skip(state, auth, payload))]
pub async fn preview_series_mapping(
    State(state): State<Arc<AppState>>,
    auth: AuthenticatedUser,
    Json(payload): Json<SeriesMappingPreviewRequest>,
) -> Result<Json<SeriesMappingPreviewResponse>, PreviewError> {
    let validation_errors = validate_request(&payload);
    if let Err(errors) = validation_errors {
        return Err(PreviewError::Validation(errors));
    }

    let scope_mode = payload.scope_mode.trim();
    let provider = payload.provider.trim();
    let series_external_id = payload.provider_series_external_id.trim();

    let conn = db::checkout(&state).await?;

    let plan = catalog_commit::build_plan_db(
        &state.outbound,
        &conn,
        auth.id(),
        payload.origin_issue_id,
        provider,
        series_external_id,
        scope_mode,
    )
    .await?;

    let scope_available = plan
        .get("scope")
        .and_then(|s| s.get("status"))
        .and_then(|v| v.as_str())
        == Some("available");

    let issued_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64();
    let expires_at = if scope_available {
        Some(issued_at + 600.0)
    } else {
        None
    };

    let preview_token = if scope_available {
        let scope_key = plan
            .get("scope_key")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let issue_numbers: Vec<String> = plan
            .get("issue_numbers")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default();
        let classification_digest = plan
            .get("state_digest")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        Some(catalog_commit::generate_preview_token(
            &state.preview_token_secret,
            auth.id(),
            provider,
            series_external_id,
            payload.origin_issue_id,
            &scope_key,
            &issue_numbers,
            &classification_digest,
            scope_mode,
            issued_at,
            expires_at.unwrap_or(issued_at),
        ))
    } else {
        None
    };

    Ok(Json(SeriesMappingPreviewResponse {
        preview_token,
        scope: scope_from_plan(&plan),
        provider_series: provider_series_from_plan(&plan),
        counts: counts_from_plan(&plan),
        rows: rows_from_plan(&plan),
        issued_at,
        expires_at,
    }))
}

// ---------------------------------------------------------------------------
// OpenAPI documentation
// ---------------------------------------------------------------------------

/// OpenAPI path documentation for the series-mapping preview endpoint.
#[utoipa::path(
    post,
    path = "/api/v1/catalog/series-mappings/preview",
    request_body = SeriesMappingPreviewRequest,
    responses(
        (status = 200, description = "Series mapping preview", body = SeriesMappingPreviewResponse),
        (status = 401, description = "Authentication required"),
        (status = 409, description = "preview_stale or provider unavailable"),
        (status = 422, description = "Validation failed"),
    ),
    tag = "catalog",
    security(("HTTPBearer" = []))
)]
pub fn preview_series_mapping_documentation() {}
