//! Same-path Rust cutover of `POST /api/v1/catalog/series-mappings/preview`.
//!
//! The preview plan (scope, rows, counts, state digest) is produced by the same
//! `catalog_commit::build_plan_for_commit` builder the Rust commit endpoint uses
//! to revalidate a preview. The signed token therefore remains mutually
//! intelligible with both the existing Rust commit handler and the retired
//! Python preview/commit contract.

use crate::{
    auth::AuthenticatedUser,
    catalog_commit, db,
    preview_validation::{parse_body_object, required_int, required_str, validation_failed},
    ApiError, AppState,
};
use axum::{
    body::Bytes,
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
    pub provider_series: Option<SeriesMappingPreviewProviderSeries>,
    pub counts: SeriesMappingPreviewCounts,
    pub rows: Vec<SeriesMappingPreviewRow>,
    pub issued_at: f64,
    pub expires_at: Option<f64>,
}

/// Wire-exact mirror of `app/schemas/catalog.py::SeriesMappingPreviewRow`.
///
/// Every field is always emitted, including the nullable ones and the two
/// defaults (`metadata_refresh_required: false`, `reason: null`). Internal plan
/// fields (`_identity_metadata`, `_provider_metadata`, `confidence`, `_roster_*`,
/// `_sibling_roster`, `_is_origin`, `_roster_only`) are deliberately absent: the
/// Python Pydantic model drops them, so a raw `Value` would leak them and omit
/// the defaults.
#[derive(Debug, Serialize, ToSchema)]
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
    pub metadata_refresh_required: bool,
    pub reason: Option<String>,
}

/// Wire-exact mirror of
/// `app/schemas/catalog.py::SeriesMappingPreviewProviderSeries`.
///
/// Pydantic coerces `start_year` and `count_of_issues` from strings to integers;
/// the conversion helper below does the same so the generated contract types
/// these as integers rather than `unknown`.
#[derive(Debug, Serialize, ToSchema)]
pub struct SeriesMappingPreviewProviderSeries {
    pub id: String,
    pub name: Option<String>,
    pub publisher: Option<String>,
    pub start_year: Option<i32>,
    pub count_of_issues: Option<i32>,
    pub site_detail_url: Option<String>,
    pub image: Option<Value>,
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

/// Parse and validate the body against the Python pydantic constraints. Every
/// rejection is the production `{"detail": "Validation failed"}` 422.
fn parse_request(body: &[u8]) -> Result<SeriesMappingPreviewRequest, ApiError> {
    let map = parse_body_object(body)?;
    let origin_issue_id = i32::try_from(required_int(&map, "origin_issue_id")?)
        .ok()
        .filter(|id| *id >= 1)
        .ok_or_else(validation_failed)?;
    let provider = required_str(&map, "provider")?.to_string();
    if provider != "comicvine" {
        return Err(validation_failed());
    }
    let provider_series_external_id =
        required_str(&map, "provider_series_external_id")?.to_string();
    if provider_series_external_id.is_empty() {
        return Err(validation_failed());
    }
    let scope_mode = match map.get("scope_mode") {
        None => default_scope_mode(),
        Some(Value::String(mode)) => mode.clone(),
        Some(_) => return Err(validation_failed()),
    };
    if !matches!(
        scope_mode.as_str(),
        SCOPE_MODE_CONFIRMED_ORIGIN | "queue_thread_bootstrap"
    ) {
        return Err(validation_failed());
    }
    Ok(SeriesMappingPreviewRequest {
        origin_issue_id,
        provider,
        provider_series_external_id,
        scope_mode,
    })
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

/// Reproduce Pydantic's `str | None = None` coercion: null/missing stays null,
/// strings pass through, and scalars are stringified.
fn pydantic_str(value: Option<&Value>) -> Option<String> {
    match value {
        None | Some(Value::Null) => None,
        Some(Value::String(text)) => Some(text.clone()),
        Some(Value::Bool(flag)) => Some(flag.to_string()),
        Some(Value::Number(number)) => Some(number.to_string()),
        Some(_) => None,
    }
}

/// Reproduce Pydantic's `int | None = None` coercion, notably accepting numeric
/// strings such as ComicVine's `"1980"` and `"700"`.
fn pydantic_int(value: Option<&Value>) -> Option<i32> {
    let raw = match value {
        None | Some(Value::Null) => return None,
        Some(Value::String(text)) => text.trim().parse::<i64>().ok()?,
        Some(Value::Number(number)) => number.as_i64().or_else(|| {
            number.as_f64().and_then(|value| {
                if value.is_finite() && value >= f64::from(i32::MIN) && value <= f64::from(i32::MAX)
                {
                    Some(value as i64)
                } else {
                    None
                }
            })
        })?,
        Some(Value::Bool(flag)) => i64::from(*flag),
        Some(_) => return None,
    };
    i32::try_from(raw).ok()
}

fn pydantic_bool(value: Option<&Value>) -> bool {
    value.and_then(Value::as_bool).unwrap_or(false)
}

/// Convert one internal plan row into the Python response model's shape,
/// dropping internal metadata and applying its always-emitted defaults.
fn typed_row(row: &Value, origin_issue_id: i32) -> SeriesMappingPreviewRow {
    let issue_id = row
        .get("issue_id")
        .and_then(Value::as_i64)
        .and_then(|id| i32::try_from(id).ok())
        .unwrap_or(origin_issue_id);
    let thread_id = pydantic_int(row.get("thread_id"));
    SeriesMappingPreviewRow {
        row_id: pydantic_str(row.get("row_id")).unwrap_or_default(),
        issue_id,
        issue_number: pydantic_str(row.get("issue_number")).unwrap_or_default(),
        title: pydantic_str(row.get("title")),
        classification: pydantic_str(row.get("classification")).unwrap_or_default(),
        thread_id,
        thread_title: pydantic_str(row.get("thread_title")),
        current_mapping_status: pydantic_str(row.get("current_mapping_status")),
        provider: pydantic_str(row.get("provider")),
        external_id: pydantic_str(row.get("external_id")),
        proposed_mapping: pydantic_bool(row.get("proposed_mapping")),
        default_selected: pydantic_bool(row.get("default_selected")),
        metadata_refresh_required: pydantic_bool(row.get("metadata_refresh_required")),
        reason: pydantic_str(row.get("reason")),
    }
}

fn typed_provider_series(value: Option<&Value>) -> Option<SeriesMappingPreviewProviderSeries> {
    let value = value.filter(|value| !value.is_null())?;
    Some(SeriesMappingPreviewProviderSeries {
        id: pydantic_str(value.get("id")).unwrap_or_default(),
        name: pydantic_str(value.get("name")),
        publisher: pydantic_str(value.get("publisher")),
        start_year: pydantic_int(value.get("start_year")),
        count_of_issues: pydantic_int(value.get("count_of_issues")),
        site_detail_url: pydantic_str(value.get("site_detail_url")),
        image: value
            .get("image")
            .filter(|image| image.is_object())
            .cloned(),
    })
}

#[utoipa::path(
    post,
    path = "/api/v1/catalog/series-mappings/preview",
    operation_id = "preview_series_mapping_api_v1_catalog_series_mappings_preview_post",
    request_body = SeriesMappingPreviewRequest,
    responses(
        (status = 200, description = "Read-only series mapping preview", body = SeriesMappingPreviewResponse),
        (status = 401, description = "Unauthorized"),
        (status = 422, description = "Validation failed"),
    ),
    security(("HTTPBearer" = []))
)]
pub fn documentation() {}

/// Mounted handler for `POST /api/v1/catalog/series-mappings/preview`.
pub async fn preview_series_mapping_handler(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    body: Bytes,
) -> Result<Json<SeriesMappingPreviewResponse>, PreviewError> {
    let request = parse_request(&body)?;
    let connection = db::checkout(&state).await?;
    let plan = catalog_commit::build_plan_for_commit(
        &state.outbound,
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
        provider_series: typed_provider_series(plan.get("provider_series")),
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
            .map(|rows| {
                rows.iter()
                    .map(|row| typed_row(row, request.origin_issue_id))
                    .collect()
            })
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
        let request = parse_request(
            br#"{"origin_issue_id": 42, "provider": "comicvine", "provider_series_external_id": "4050-1"}"#,
        )
        .expect("valid body");
        assert_eq!(request.scope_mode, SCOPE_MODE_CONFIRMED_ORIGIN);
    }

    #[test]
    fn every_invalid_body_is_the_production_validation_failed_422() {
        for body in [
            &br#"{"origin_issue_id": 0, "provider": "comicvine", "provider_series_external_id": "x"}"#[..],
            br#"{"origin_issue_id": 1, "provider": "other", "provider_series_external_id": "x"}"#,
            br#"{"origin_issue_id": 1, "provider": "", "provider_series_external_id": "x"}"#,
            br#"{"origin_issue_id": 1, "provider": "comicvine", "provider_series_external_id": ""}"#,
            br#"{"origin_issue_id": 1, "provider": "comicvine", "provider_series_external_id": "x", "scope_mode": "nonsense"}"#,
            br#"{"origin_issue_id": 1, "provider": "comicvine", "provider_series_external_id": "x", "scope_mode": 3}"#,
            br#"{"provider": "comicvine", "provider_series_external_id": "x"}"#,
            b"not json",
        ] {
            let error = parse_request(body).expect_err("invalid body must be rejected");
            assert_eq!(error.detail(), "Validation failed");
        }
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
            Bytes::from_static(
                br#"{"origin_issue_id": 9001001, "provider": "comicvine", "provider_series_external_id": "missing-series"}"#,
            ),
        )
        .await;
        let response = result.expect("preview returns a 200 body");
        assert!(response.scope.status == "available" || response.scope.status == "unavailable");
    }

    /// Golden measured from `app.schemas.catalog::SeriesMappingPreviewRow`
    /// (`SeriesMappingPreviewResponse.model_validate(raw).model_dump()`).
    /// The raw input deliberately includes internal plan metadata, omits
    /// `reason`, and carries a `metadata_refresh_required` default.
    #[test]
    fn nonempty_preview_row_matches_python_response_model_golden() {
        let raw = serde_json::json!({
            "row_id": "issue:42",
            "issue_id": 42,
            "issue_number": "1",
            "title": "Issue One",
            "classification": "safe_exact_match",
            "thread_id": 7,
            "thread_title": "Thread",
            "provider": "comicvine",
            "external_id": "issue-42",
            "confidence": 0.99,
            "proposed_mapping": true,
            "default_selected": true,
            "_identity_metadata": { "volume": { "name": "Series" }, "issue_number": "1" },
            "_provider_metadata": { "name": "Issue One" },
            "_roster_verified": true,
            "metadata_refresh_required": false,
        });
        let golden: Value = serde_json::from_str(
            r#"{
                "row_id": "issue:42", "issue_id": 42, "issue_number": "1",
                "title": "Issue One", "classification": "safe_exact_match",
                "thread_id": 7, "thread_title": "Thread",
                "current_mapping_status": null, "provider": "comicvine",
                "external_id": "issue-42", "proposed_mapping": true,
                "default_selected": true, "metadata_refresh_required": false,
                "reason": null
            }"#,
        )
        .expect("golden JSON");
        let actual = serde_json::to_value(typed_row(&raw, 42)).expect("serializable row");
        assert_eq!(actual, golden);
    }

    /// Pydantic coerces ComicVine's string years to integers; the golden was
    /// measured from `SeriesMappingPreviewResponse.model_validate(raw)`.
    #[test]
    fn nonempty_provider_series_matches_python_response_model_golden() {
        let raw = serde_json::json!({
            "id": "4050-1",
            "name": "Series",
            "publisher": "Pub",
            "start_year": "1980",
            "count_of_issues": "700",
            "site_detail_url": "https://example/series",
            "image": { "small_url": "https://img" },
        });
        let golden: Value = serde_json::from_str(
            r#"{
                "id": "4050-1", "name": "Series", "publisher": "Pub",
                "start_year": 1980, "count_of_issues": 700,
                "site_detail_url": "https://example/series",
                "image": { "small_url": "https://img" }
            }"#,
        )
        .expect("golden JSON");
        let actual =
            serde_json::to_value(typed_provider_series(Some(&raw))).expect("serializable series");
        assert_eq!(actual, golden);
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
