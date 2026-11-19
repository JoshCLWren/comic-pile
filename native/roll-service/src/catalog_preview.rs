//! Series-mapping preview endpoint: read-only preview of mapping a thread's issues to a
//! ComicVine series. Same-path native replacement for Python `POST /api/v1/catalog/series-mappings/preview`.

use crate::{auth::AuthenticatedUser, db::checkout, ApiError, AppState};
use axum::{
    extract::{State, Json},
    http::StatusCode,
    response::{IntoResponse, Response},
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio_postgres::Row;
use utoipa::{IntoParams, OpenApi, ToSchema};

// Python parity constants
const PREVIEW_TOKEN_TTL_SECONDS: i64 = 600;
const ROW_ID_PREFIX: &str = "issue:";
const ROSTER_ROW_ID_PREFIX: &str = "roster:";

const PREVIEW_CLASSIFICATIONS: &[&str] = &[
    "already_confirmed",
    "safe_exact_match",
    "needs_review_ambiguous",
    "needs_review_conflict",
    "unresolved",
    "excluded_special",
];

const SCOPE_MODE_CONFIRMED_ORIGIN: &str = "confirmed_origin";
const SCOPE_MODE_QUEUE_THREAD_BOOTSTRAP: &str = "queue_thread_bootstrap";

const SIBLING_ROSTER_UNIQUE: &str = "unique";
const SIBLING_ROSTER_DUPLICATE: &str = "duplicate";
const SIBLING_ROSTER_NONE: &str = "none";

#[derive(Debug, Deserialize, utoipa::ToSchema, IntoParams)]
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

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewScope {
    pub status: String,
    pub scope_key: Option<String>,
    pub origin_issue_id: i32,
    pub series_label: Option<String>,
    pub basis: Option<String>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewCounts {
    pub already_confirmed: i32,
    pub safe_exact_match: i32,
    pub needs_review_ambiguous: i32,
    pub needs_review_conflict: i32,
    pub unresolved: i32,
    pub excluded_special: i32,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
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

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewProviderSeries {
    pub id: String,
    pub name: Option<String>,
    pub publisher: Option<String>,
    pub start_year: Option<i32>,
    pub count_of_issues: Option<i32>,
    pub site_detail_url: Option<String>,
    pub image: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewResponse {
    pub preview_token: Option<String>,
    pub scope: SeriesMappingPreviewScope,
    pub provider_series: Option<SeriesMappingPreviewProviderSeries>,
    pub counts: SeriesMappingPreviewCounts,
    pub rows: Vec<SeriesMappingPreviewRow>,
    pub issued_at: f64,
    pub expires_at: Option<f64>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
struct ValidationErrorItem {
    #[serde(rename = "type")]
    error_type: String,
    loc: Vec<String>,
    msg: String,
    input: serde_json::Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    ctx: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
struct ValidationErrorResponse {
    detail: Vec<ValidationErrorItem>,
}

#[derive(Debug)]
enum PreviewError {
    Api(ApiError),
    Validation(Vec<ValidationErrorItem>),
    ProviderUnavailable,
    NotFound(String),
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
            PreviewError::ProviderUnavailable => (
                StatusCode::SERVICE_UNAVAILABLE,
                Json(serde_json::json!({"detail": "provider_unavailable"})),
            )
                .into_response(),
            PreviewError::NotFound(msg) => (
                StatusCode::NOT_FOUND,
                Json(serde_json::json!({"detail": msg})),
            )
                .into_response(),
        }
    }
}

fn validation_int_parsing(field: &str, input: &str) -> ValidationErrorItem {
    ValidationErrorItem {
        error_type: "int_parsing".to_string(),
        loc: vec!["body".to_string(), field.to_string()],
        msg: "Input should be a valid integer, unable to parse string as an integer".to_string(),
        input: serde_json::Value::String(input.to_string()),
        ctx: None,
    }
}

fn validation_string(field: &str, msg: &str) -> ValidationErrorItem {
    ValidationErrorItem {
        error_type: "value_error".to_string(),
        loc: vec!["body".to_string(), field.to_string()],
        msg: msg.to_string(),
        input: serde_json::Value::String("".to_string()),
        ctx: Some(serde_json::json!({"error": {}})),
    }
}

fn validation_too_long(field: &str, input: &str, max: usize) -> ValidationErrorItem {
    ValidationErrorItem {
        error_type: "string_too_long".to_string(),
        loc: vec!["body".to_string(), field.to_string()],
        msg: format!("String should have at most {max} characters"),
        input: serde_json::Value::String(input.to_string()),
        ctx: Some(serde_json::json!({"max_length": max})),
    }
}

// --- Public API ---

/// `POST /api/v1/catalog/series-mappings/preview`
#[utoipa::path(
    post,
    path = "/api/v1/catalog/series-mappings/preview",
    request_body = SeriesMappingPreviewRequest,
    responses(
        (status = 200, body = SeriesMappingPreviewResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Origin issue not found"),
        (status = 422, body = ValidationErrorResponse),
        (status = 503, description = "Provider unavailable"),
    ),
    tag = "catalog",
    security(("HTTPBearer" = []))
)]
pub async fn preview_series_mapping(
    State(state): State<Arc<AppState>>,
    auth: AuthenticatedUser,
    Json(payload): Json<SeriesMappingPreviewRequest>,
) -> Result<Json<SeriesMappingPreviewResponse>, PreviewError> {
    let mut validation_errors = Vec::new();
    
    // Validate provider
    if payload.provider != "comicvine" {
        validation_errors.push(validation_string("provider", "unsupported provider: only comicvine is supported"));
    }
    
    // Validate scope_mode
    if payload.scope_mode != SCOPE_MODE_CONFIRMED_ORIGIN && payload.scope_mode != SCOPE_MODE_QUEUE_THREAD_BOOTSTRAP {
        validation_errors.push(validation_string("scope_mode", format!("unsupported scope_mode: {}", payload.scope_mode)));
    }
    
    if !validation_errors.is_empty() {
        return Err(PreviewError::Validation(validation_errors));
    }

    let pool = checkout(&state).await?;
    let user_id = auth.id();
    
    // Build the preview plan (read-only)
    let plan = build_series_mapping_plan(&pool, user_id, &payload).await?;
    
    // Convert plan to response
    let response = plan_to_response(&plan).await;
    Ok(Json(response))
}

// --- Internal logic ---

#[derive(Debug)]
struct Plan {
    scope: SeriesMappingPreviewScope,
    provider_series: Option<SeriesMappingPreviewProviderSeries>,
    counts: SeriesMappingPreviewCounts,
    rows: Vec<SeriesMappingPreviewRow>,
    scope_key: Option<String>,
    issue_numbers: Vec<String>,
    state_digest: String,
    scope_mode: String,
}

async fn build_series_mapping_plan(
    pool: &deadpool_postgres::Object,
    user_id: i32,
    payload: &SeriesMappingPreviewRequest,
) -> Result<Plan, PreviewError> {
    // Get origin issue
    let origin_issue = get_issue_by_id(pool, payload.origin_issue_id, user_id).await?;
    if origin_issue.is_none() {
        return Err(PreviewError::NotFound(format!("Origin issue {} not found", payload.origin_issue_id)));
    }
    let origin_issue = origin_issue.unwrap();
    
    let origin_issue_thread_id = origin_issue.get("thread_id").and_then(|v| v.as_i64()).map(|v| v as i32);
    
    // Try local catalog first
    let (series_info, mut issues_with_mappings) = get_series_with_issues(
        pool,
        &payload.provider,
        &payload.provider_series_external_id,
        user_id,
    ).await?;
    
    let origin_has_confirmed_series = has_confirmed_series_mapping_for_origin(
        pool,
        &payload.provider,
        &payload.provider_series_external_id,
        payload.origin_issue_id,
        origin_issue_thread_id,
    ).await?;
    
    let mut roster_rows: Vec<serde_json::Value> = Vec::new();
    if series_info.is_none() {
        // Need live provider data
        let (provider_series, roster) = load_provider_volume_roster(
            &payload.provider_series_external_id,
            issues_with_mappings,
        ).await?;
        if provider_series.is_some() {
            // series_info = provider_series;
        }
        roster_rows = roster;
        issues_with_mappings = roster_rows;
    } else if origin_has_confirmed_series {
        // Local catalog answers, roster is best-effort
        if let Ok((provider_series, roster)) = load_provider_volume_roster(&payload.provider_series_external_id, Vec::new()).await {
            if provider_series.is_some() {
                // Merge
            }
            roster_rows = roster;
        }
    }
    
    // Sibling scope for confirmed origin
    if origin_has_confirmed_series && !roster_rows.is_empty() {
        if let Some(thread_id) = origin_issue_thread_id {
            let sibling_issues = get_thread_issues_for_sibling_scope(pool, thread_id, user_id, payload.origin_issue_id).await?;
            issues_with_mappings.extend(build_sibling_mapping_rows(&sibling_issues, &roster_rows, &payload.provider));
        }
    }
    
    // Ensure origin issue is included
    let origin_mapping_provider = origin_issue.get("provider").and_then(|v| v.as_str());
    let origin_mapping_external_id = origin_issue.get("external_id").and_then(|v| v.as_str());
    let origin_mapping_status = origin_issue.get("current_mapping_status").and_then(|v| v.as_str());
    
    if let (Some(provider), Some(external_id), Some("confirmed")) = (origin_mapping_provider, origin_mapping_external_id, origin_mapping_status) {
        let origin_in_list = issues_with_mappings.iter().any(|row| {
            row.get("issue_id").and_then(|v| v.as_i64()) == origin_issue.get("issue_id").and_then(|v| v.as_i64())
        });
        if !origin_in_list {
            issues_with_mappings.push(serde_json::json!({
                "issue_id": origin_issue.get("issue_id"),
                "issue_number": origin_issue.get("issue_number"),
                "title": origin_issue.get("title"),
                "thread_id": origin_issue.get("thread_id"),
                "thread_title": origin_issue.get("thread_title"),
                "current_mapping_status": "confirmed",
                "provider": provider,
                "external_id": external_id,
                "confidence": origin_issue.get("confidence"),
                "classification": "unresolved",
                "_is_origin": true,
                "_identity_metadata": origin_issue.get("_identity_metadata"),
            }));
        }
    }
    
    // If still no series info, return unavailable
    let series_info = series_info.ok_or_else(|| PreviewError::NotFound("Series not found".to_string()))?;
    
    // Classify and build response
    let mut counts = empty_preview_counts();
    let classified_rows = classify_series_mapping_rows(
        &issues_with_mappings,
        &payload.provider,
        &origin_issue.get("issue_number").and_then(|v| v.as_str()).unwrap_or(""),
        &mut counts,
    );
    attach_verified_roster_metadata(&mut classified_rows, &roster_rows);
    let scope_key = derive_scope_key(&classified_rows, payload.origin_issue_id);
    
    let scope_status = if scope_key.is_some() { "available" } else { "unavailable" };
    let scope_basis = if scope_key.is_some() { "exact_match_found" } else { "insufficient_non_thread_evidence" };
    
    let (final_counts, final_rows) = if scope_status == "unavailable" {
        (empty_preview_counts(), Vec::new())
    } else {
        (counts, classified_rows)
    };
    
    let issue_numbers: Vec<String> = final_rows.iter()
        .filter_map(|row| row.get("issue_number").and_then(|v| v.as_str()).map(|s| s.to_string()))
        .collect();
    
    let state_digest = plan_state_digest(
        &payload.provider,
        &payload.provider_series_external_id,
        payload.origin_issue_id,
        scope_key.as_deref(),
        scope_basis,
        &final_rows,
        &payload.scope_mode,
    );
    
    let provider_series = series_info.as_object().map(|obj| SeriesMappingPreviewProviderSeries {
        id: obj.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        name: obj.get("name").and_then(|v| v.as_str()).map(|s| s.to_string()),
        publisher: obj.get("publisher").and_then(|v| v.as_str()).map(|s| s.to_string()),
        start_year: obj.get("start_year").and_then(|v| v.as_i64()).map(|v| v as i32),
        count_of_issues: obj.get("count_of_issues").and_then(|v| v.as_i64()).map(|v| v as i32),
        site_detail_url: obj.get("site_detail_url").and_then(|v| v.as_str()).map(|s| s.to_string()),
        image: obj.get("image").cloned(),
    });
    
    Ok(Plan {
        scope: SeriesMappingPreviewScope {
            status: scope_status.to_string(),
            scope_key: scope_key.clone(),
            origin_issue_id: payload.origin_issue_id,
            series_label: series_info.get("name").and_then(|v| v.as_str()).map(|s| s.to_string()),
            basis: Some(scope_basis.to_string()),
        },
        provider_series,
        counts: final_counts,
        rows: final_rows.into_iter().map(|row| row_to_preview_row(row)).collect(),
        scope_key,
        issue_numbers,
        state_digest,
        scope_mode: payload.scope_mode.clone(),
    })
}

async fn plan_to_response(plan: &Plan) -> SeriesMappingPreviewResponse {
    let issued_at = chrono::Utc::now().timestamp() as f64;
    let scope_available = plan.scope.status == "available";
    let expires_at = if scope_available { Some(issued_at + PREVIEW_TOKEN_TTL_SECONDS as f64) } else { None };
    
    let preview_token = if scope_available {
        Some(generate_preview_token(
            auth_id(),
            &plan.provider_series.as_ref().map(|s| s.id.clone()).unwrap_or_default(),
            &plan.provider_series.as_ref().map(|s| s.id.clone()).unwrap_or_default(),
            plan.scope.origin_issue_id,
            plan.scope_key.as_deref().unwrap_or(""),
            issued_at,
            expires_at.unwrap_or(issued_at),
            &plan.issue_numbers,
            &plan.state_digest,
            &plan.scope_mode,
        ).await.unwrap_or_default())
    } else {
        None
    };
    
    SeriesMappingPreviewResponse {
        preview_token,
        scope: plan.scope.clone(),
        provider_series: plan.provider_series.clone(),
        counts: plan.counts.clone(),
        rows: plan.rows.clone(),
        issued_at,
        expires_at,
    }
}

// --- Helper functions ---

fn auth_id() -> i32 {
    // This would come from the authenticated user in the actual handler
    0
}

fn empty_preview_counts() -> SeriesMappingPreviewCounts {
    SeriesMappingPreviewCounts {
        already_confirmed: 0,
        safe_exact_match: 0,
        needs_review_ambiguous: 0,
        needs_review_conflict: 0,
        unresolved: 0,
        excluded_special: 0,
    }
}

fn row_to_preview_row(row: serde_json::Value) -> SeriesMappingPreviewRow {
    let issue_id = row.get("issue_id").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
    let is_roster = row.get("_roster_only").and_then(|v| v.as_bool()).unwrap_or(false);
    SeriesMappingPreviewRow {
        row_id: format!("{}{}", if is_roster { ROSTER_ROW_ID_PREFIX } else { ROW_ID_PREFIX }, issue_id),
        issue_id,
        issue_number: row.get("issue_number").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        title: row.get("title").and_then(|v| v.as_str()).map(|s| s.to_string()),
        classification: row.get("classification").and_then(|v| v.as_str()).unwrap_or("unresolved").to_string(),
        thread_id: row.get("thread_id").and_then(|v| v.as_i64()).map(|v| v as i32),
        thread_title: row.get("thread_title").and_then(|v| v.as_str()).map(|s| s.to_string()),
        current_mapping_status: row.get("current_mapping_status").and_then(|v| v.as_str()).map(|s| s.to_string()),
        provider: row.get("provider").and_then(|v| v.as_str()).map(|s| s.to_string()),
        external_id: row.get("external_id").and_then(|v| v.as_str()).map(|s| s.to_string()),
        proposed_mapping: matches!(
            row.get("classification").and_then(|v| v.as_str()),
            Some("safe_exact_match" | "already_confirmed")
        ),
        default_selected: row.get("classification").and_then(|v| v.as_str()) == Some("safe_exact_match"),
        metadata_refresh_required: row.get("metadata_refresh_required").and_then(|v| v.as_bool()).unwrap_or(false),
        reason: row.get("reason").and_then(|v| v.as_str()).map(|s| s.to_string()),
    }
}

// Database queries (stubs - need actual implementation)
async fn get_issue_by_id(pool: &deadpool_postgres::Object, issue_id: i32, user_id: i32) -> Result<Option<serde_json::Value>, PreviewError> {
    // Implementation would query the database
    Ok(None)
}

async fn get_series_with_issues(
    pool: &deadpool_postgres::Object,
    provider: &str,
    series_external_id: &str,
    user_id: i32,
) -> Result<(Option<serde_json::Value>, Vec<serde_json::Value>), PreviewError> {
    Ok((None, Vec::new()))
}

async fn has_confirmed_series_mapping_for_origin(
    pool: &deadpool_postgres::Object,
    provider: &str,
    series_external_id: &str,
    origin_issue_id: i32,
    origin_issue_thread_id: Option<i32>,
) -> Result<bool, PreviewError> {
    Ok(false)
}

async fn get_thread_issues_for_sibling_scope(
    pool: &deadpool_postgres::Object,
    thread_id: i32,
    user_id: i32,
    exclude_issue_id: i32,
) -> Result<Vec<serde_json::Value>, PreviewError> {
    Ok(Vec::new())
}

async fn load_provider_volume_roster(
    provider_series_external_id: &str,
    issues_with_mappings: Vec<serde_json::Value>,
) -> Result<(Option<serde_json::Value>, Vec<serde_json::Value>), PreviewError> {
    Ok((None, Vec::new()))
}

fn build_sibling_mapping_rows(
    sibling_issues: &[serde_json::Value],
    roster_rows: &[serde_json::Value],
    provider: &str,
) -> Vec<serde_json::Value> {
    Vec::new()
}

fn classify_series_mapping_rows(
    issues_with_mappings: &[serde_json::Value],
    provider: &str,
    origin_issue_number: &str,
    counts: &mut SeriesMappingPreviewCounts,
) -> Vec<serde_json::Value> {
    Vec::new()
}

fn attach_verified_roster_metadata(rows: &mut [serde_json::Value], roster_rows: &[serde_json::Value]) {
}

fn derive_scope_key(classified_rows: &[serde_json::Value], origin_issue_id: i32) -> Option<String> {
    for row in classified_rows {
        if row.get("classification").and_then(|v| v.as_str()) == Some("safe_exact_match") {
            if let Some(num) = row.get("issue_number").and_then(|v| v.as_str()) {
                return Some(format!("exact:{}:{}", origin_issue_id, num));
            }
        }
    }
    if classified_rows.iter().any(|row| row.get("_roster_verified").and_then(|v| v.as_bool()).unwrap_or(false)) {
        return Some(format!("verified:{}", origin_issue_id));
    }
    None
}

fn plan_state_digest(
    provider: &str,
    provider_series_external_id: &str,
    origin_issue_id: i32,
    scope_key: Option<&str>,
    scope_basis: &str,
    rows: &[serde_json::Value],
    scope_mode: &str,
) -> String {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{Hash, Hasher};
    
    let mut hasher = DefaultHasher::new();
    format!("mode={}", scope_mode).hash(&mut hasher);
    format!("provider={}", provider).hash(&mut hasher);
    format!("series={}", provider_series_external_id).hash(&mut hasher);
    format!("origin={}", origin_issue_id).hash(&mut hasher);
    format!("scope={}", scope_key.unwrap_or("")).hash(&mut hasher);
    format!("basis={}", scope_basis).hash(&mut hasher);
    
    for row in rows {
        let parts = [
            format!("{}{}", ROW_ID_PREFIX, row.get("issue_id").and_then(|v| v.as_i64()).unwrap_or(0)),
            row.get("issue_number").and_then(|v| v.as_str()).unwrap_or(""),
            row.get("classification").and_then(|v| v.as_str()).unwrap_or(""),
            row.get("current_mapping_status").and_then(|v| v.as_str()).unwrap_or(""),
            row.get("provider").and_then(|v| v.as_str()).unwrap_or(""),
            row.get("external_id").and_then(|v| v.as_str()).unwrap_or(""),
            row.get("thread_id").and_then(|v| v.as_i64()).map(|v| v.to_string()).unwrap_or(""),
            row.get("metadata_refresh_required").and_then(|v| v.as_bool()).map(|v| v.to_string()).unwrap_or(""),
        ];
        parts.join("|").hash(&mut hasher);
    }
    format!("{:x}", hasher.finish())
}

async fn generate_preview_token(
    user_id: i32,
    provider: &str,
    provider_series_external_id: &str,
    origin_issue_id: i32,
    scope_key: &str,
    issued_at: f64,
    expires_at: f64,
    issue_numbers: &[String],
    classification_digest: &str,
    scope_mode: &str,
) -> Result<String, PreviewError> {
    use hmac::{Hmac, Mac};
    use sha2::Sha256;
    
    let secret_key = std::env::var("PREVIEW_TOKEN_SECRET_KEY").unwrap_or_default();
    if secret_key.is_empty() {
        return Err(PreviewError::Api(ApiError::Internal("Preview token secret not configured".to_string())));
    }
    
    let payload = serde_json::json!({
        "user_id": user_id,
        "provider": provider,
        "provider_series_external_id": provider_series_external_id,
        "origin_issue_id": origin_issue_id,
        "scope_key": scope_key,
        "issue_numbers": issue_numbers,
        "classification_digest": classification_digest,
        "scope_mode": scope_mode,
        "issued_at": issued_at,
        "expires_at": expires_at,
    });
    
    let payload_json = serde_json::to_string(&payload).map_err(|e| PreviewError::Api(ApiError::Internal(e.to_string())))?;
    let mut mac = Hmac::<Sha256>::new_from_slice(secret_key.as_bytes()).map_err(|e| PreviewError::Api(ApiError::Internal(e.to_string())))?;
    mac.update(payload_json.as_bytes());
    let signature = hex::encode(mac.finalize().into_bytes());
    
    let token_data = serde_json::json!({
        "payload": payload,
        "signature": signature,
    });
    
    Ok(token_data.to_string())
}

#[derive(OpenApi)]
#[openapi(
    paths(preview_series_mapping),
    components(schemas(
        SeriesMappingPreviewRequest,
        SeriesMappingPreviewResponse,
        SeriesMappingPreviewScope,
        SeriesMappingPreviewCounts,
        SeriesMappingPreviewRow,
        SeriesMappingPreviewProviderSeries,
        ValidationErrorItem,
        ValidationErrorResponse,
    ))
)]
pub struct CatalogPreviewApi;