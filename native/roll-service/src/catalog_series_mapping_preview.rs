//! Series-mapping preview, mounted canonically at
//! `POST /api/v2/seriesMappings:preview` (AIP-136 stateless collection method).
//!
//! The retained `POST /api/v1/catalog/series-mappings/preview` alias exists only
//! until production proof retires it; every real caller uses the v2 custom
//! method. Both URLs share one read-only implementation: the preview plan
//! (scope, rows, counts, state digest) is produced by the same
//! `catalog_commit::build_plan_for_commit` builder the durable commit endpoint
//! uses to revalidate a preview. The signed token therefore remains mutually
//! intelligible with the retained commit handler and carries the idempotency
//! evidence without writing any state itself.

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
        &state.comicvine_limits,
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

// ---------------------------------------------------------------------------
// POST /api/v2/seriesMappings:preview
// ---------------------------------------------------------------------------

/// Canonical v2 entry point: an AIP-136 stateless collection custom method.
///
/// It shares the read-only implementation with the retained v1 alias, so the
/// signed preview token, wire response, authorization, validation and state
/// digest stay identical. Preview never writes mappings, receipts, reading
/// history or provider cache entries; the durable commit remains
/// `POST /api/v2/series-mapping-commits`.
pub async fn preview_series_mappings_v2(
    state: State<Arc<AppState>>,
    user: AuthenticatedUser,
    body: Bytes,
) -> Result<Json<SeriesMappingPreviewResponse>, PreviewError> {
    preview_series_mapping_handler(state, user, body).await
}

#[utoipa::path(
    post,
    path = "/api/v2/seriesMappings:preview",
    operation_id = "preview_series_mappings",
    tag = "catalog",
    description = "Stateless AIP-136 collection custom method: build a read-only series-mapping preview and a signed idempotency token for the durable commit. No mappings, receipts, history or provider state are written.",
    request_body = SeriesMappingPreviewRequest,
    responses(
        (status = 200, description = "Read-only series mapping preview", body = SeriesMappingPreviewResponse),
        (status = 401, description = "Unauthorized"),
        (status = 422, description = "Validation failed"),
    ),
    security(("HTTPBearer" = []))
)]
pub fn preview_series_mappings_v2_documentation() {}

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

    const QUEUE_MAPPING_USER_ID: i32 = 9001;
    const QUEUE_MAPPING_VOLUME_ID: &str = "5610777";
    const QUEUE_MAPPING_API_KEY: &str = "TESTKEY123";

    struct ComicVineKeyEnv {
        previous: Option<String>,
    }

    impl ComicVineKeyEnv {
        fn install() -> Self {
            let previous = std::env::var("COMICVINE_API_KEY").ok();
            std::env::set_var("COMICVINE_API_KEY", QUEUE_MAPPING_API_KEY);
            Self { previous }
        }
    }

    impl Drop for ComicVineKeyEnv {
        fn drop(&mut self) {
            match &self.previous {
                Some(value) => std::env::set_var("COMICVINE_API_KEY", value),
                None => std::env::remove_var("COMICVINE_API_KEY"),
            }
        }
    }

    async fn seed_queue_mapping_thread(connection: &tokio_postgres::Client, confirm_first: bool) {
        connection
            .batch_execute(
                r#"
                INSERT INTO users (id, username, created_at, is_admin)
                VALUES (9001, 'map-series-preview', now(), false);
                INSERT INTO threads
                    (id, user_id, title, issues_remaining, queue_position, status, total_issues, created_at, is_blocked, is_test, manual_creator_credits, queue_position_is_manual)
                VALUES (561077, 9001, 'Terra Obscura (2003)', 0, 1, 'active', 6, now(), false, false, '[]', false);
                INSERT INTO issues
                    (id, thread_id, issue_number, status, created_at, position)
                SELECT 5610000 + n, 561077, n::text, 'unread', now(), n
                FROM generate_series(1, 6) AS n;
                "#,
            )
            .await
            .expect("seed Queue mapping thread");
        if confirm_first {
            connection
                .batch_execute(
                    r#"
                    WITH identity AS (
                        INSERT INTO external_identities
                            (provider, entity_type, external_id, metadata_json, created_at, updated_at)
                        VALUES ('comicvine', 'issue', '5610501',
                                '{"name":"Issue 1","issue_number":"1","volume":{"name":"Terra Obscura"}}'::jsonb,
                                now(), now())
                        RETURNING id
                    )
                    INSERT INTO issue_external_identity_mappings
                        (issue_id, external_identity_id, status, evidence_source, confidence,
                         evidence_json, created_at, updated_at)
                    SELECT 5610001, id, 'confirmed', 'seed', 1.0, '{}'::json, now(), now()
                    FROM identity;
                    "#,
                )
                .await
                .expect("seed existing confirmed mapping");
        }
    }

    fn queue_mapping_provider_payloads() -> (Value, Value) {
        let volume = serde_json::json!({
            "status_code": 1,
            "results": {
                "id": 5610777,
                "name": "Terra Obscura",
                "publisher": {"name": "DC Comics"},
                "start_year": 2003,
                "count_of_issues": 6,
                "site_detail_url": "https://comicvine.gamespot.com/volume/4050-5610777/",
                "image": null,
            },
        });
        let issues = serde_json::json!({
            "status_code": 1,
            "number_of_total_results": 6,
            "results": (1..=6_i32)
                .map(|n| serde_json::json!({
                    "id": 5610500 + n,
                    "issue_number": n.to_string(),
                    "name": format!("Issue {n}"),
                    "volume": {"id": 5610777},
                }))
                .collect::<Vec<_>>(),
        });
        (volume, issues)
    }

    async fn prime_queue_mapping_provider_cache(state: &AppState) {
        let fake = state.recording_fake().expect("recording provider fake");
        let (volume, issues) = queue_mapping_provider_payloads();
        for payload in [volume, issues] {
            fake.push_ok(
                StatusCode::OK,
                axum::http::HeaderMap::new(),
                Bytes::from(serde_json::to_vec(&payload).expect("provider payload JSON")),
            );
        }
        state
            .comicvine_limits
            .call(
                &state.outbound,
                &format!("volume/4050-{QUEUE_MAPPING_VOLUME_ID}"),
                "",
                QUEUE_MAPPING_API_KEY,
            )
            .await
            .expect("cache provider volume");
        state
            .comicvine_limits
            .call(
                &state.outbound,
                "issues",
                &format!("&filter=volume:{QUEUE_MAPPING_VOLUME_ID}&limit=100&offset=0"),
                QUEUE_MAPPING_API_KEY,
            )
            .await
            .expect("cache provider roster");
        assert_eq!(fake.calls().len(), 2, "prime both provider cache entries");
        fake.clear();
    }

    async fn load_queue_mapping_preview(
        state: Arc<AppState>,
    ) -> Result<Json<SeriesMappingPreviewResponse>, PreviewError> {
        preview_series_mapping_handler(
            State(state),
            crate::auth::AuthenticatedUser::for_test(QUEUE_MAPPING_USER_ID),
            Bytes::from_static(
                br#"{"origin_issue_id":5610001,"provider":"comicvine","provider_series_external_id":"5610777","scope_mode":"queue_thread_bootstrap"}"#,
            ),
        )
        .await
    }

    /// Regression for #5610: the Queue preview must use the shared provider
    /// cache/limiter. With no live response available, a raw provider call fails;
    /// the fixed path still loads every safe row from the shared cached roster.
    #[tokio::test]
    async fn queue_bootstrap_preview_reuses_shared_provider_cache() {
        let state = crate::test_support::test_state(2)
            .await
            .expect("disposable PostgreSQL required");
        let _guard = crate::test_support::reset_for_test(&state).await;
        {
            let connection = state.pool.get().await.expect("connection");
            seed_queue_mapping_thread(&connection, false).await;
        }
        let _env = ComicVineKeyEnv::install();
        prime_queue_mapping_provider_cache(&state).await;

        let Json(response) = load_queue_mapping_preview(state.clone())
            .await
            .expect("preview should load from the shared provider cache");

        assert_eq!(response.scope.status, "available");
        assert!(response.preview_token.is_some());
        assert_eq!(response.counts.safe_exact_match, 6);
        assert_eq!(response.rows.len(), 6);
        assert!(response.rows.iter().all(|row| row.default_selected));
        assert!(
            state
                .recording_fake()
                .expect("recording provider fake")
                .calls()
                .is_empty(),
            "preview must not bypass the shared cache with a raw provider call"
        );
    }

    /// MQA-MAP-002: a partially mapped thread still loads, leaves its existing
    /// correct mapping untouched, and approves all remaining safe rows at once.
    #[tokio::test]
    async fn queue_bootstrap_partial_preview_commits_only_safe_rows() {
        let state = crate::test_support::test_state(2)
            .await
            .expect("disposable PostgreSQL required");
        let _guard = crate::test_support::reset_for_test(&state).await;
        {
            let connection = state.pool.get().await.expect("connection");
            seed_queue_mapping_thread(&connection, true).await;
        }
        let _env = ComicVineKeyEnv::install();
        prime_queue_mapping_provider_cache(&state).await;

        let Json(preview) = load_queue_mapping_preview(state.clone())
            .await
            .expect("partially mapped preview should load");
        assert_eq!(preview.scope.status, "available");
        assert_eq!(preview.counts.already_confirmed, 1);
        assert_eq!(preview.counts.safe_exact_match, 5);
        let existing = preview
            .rows
            .iter()
            .find(|row| row.issue_id == 5610001)
            .expect("existing mapped row");
        assert_eq!(existing.classification, "already_confirmed");
        assert!(!existing.default_selected);
        assert!(!existing.metadata_refresh_required);
        let approved_row_ids: Vec<String> = preview
            .rows
            .iter()
            .filter(|row| row.default_selected)
            .map(|row| row.row_id.clone())
            .collect();
        assert_eq!(approved_row_ids.len(), 5);
        assert!(
            state
                .recording_fake()
                .expect("recording provider fake")
                .calls()
                .is_empty(),
            "preview must reuse the shared provider cache"
        );

        let Json(committed) = catalog_commit::commit_series_mapping_handler(
            State(state.clone()),
            crate::auth::AuthenticatedUser::for_test(QUEUE_MAPPING_USER_ID),
            axum::Json(catalog_commit::CommitRequest {
                preview_token: preview.preview_token.expect("available preview token"),
                idempotency_key: "queue-partial-preview-5610".to_string(),
                approved_row_ids,
            }),
        )
        .await
        .expect("safe rows should commit in one operation");
        assert_eq!(
            committed.confirmed_issue_ids,
            (5610002..=5610006).collect::<Vec<_>>()
        );
        assert_eq!(committed.already_confirmed_issue_ids, vec![5610001]);
        assert!(committed.needs_review_issue_ids.is_empty());
        assert_eq!(committed.series_mapping.status, "confirmed");

        let connection = state.pool.get().await.expect("connection");
        let confirmed: i64 = connection
            .query_one(
                "SELECT count(*) FROM issue_external_identity_mappings
                 WHERE status = 'confirmed' AND issue_id BETWEEN 5610001 AND 5610006",
                &[],
            )
            .await
            .expect("reload confirmed mappings")
            .get(0);
        assert_eq!(confirmed, 6);
        let existing = connection
            .query_one(
                "SELECT e.external_id, m.evidence_source
                 FROM issue_external_identity_mappings m
                 JOIN external_identities e ON e.id = m.external_identity_id
                 WHERE m.issue_id = 5610001 AND m.status = 'confirmed'",
                &[],
            )
            .await
            .expect("reload existing mapping");
        assert_eq!(existing.get::<_, String>(0), "5610501");
        assert_eq!(existing.get::<_, String>(1), "seed");
    }

    /// #5851: production starts each serverless invocation with a cold
    /// in-process provider cache, so a preview must load from live provider
    /// responses. ComicVine 301s slash-less singular URLs and the native
    /// transport never follows redirects, so the canonical `volume/.../` path
    /// is part of this acceptance contract.
    #[tokio::test]
    async fn cold_cache_queue_preview_loads_from_canonical_provider_urls() {
        let state = crate::test_support::test_state(2)
            .await
            .expect("disposable PostgreSQL required");
        let _guard = crate::test_support::reset_for_test(&state).await;
        {
            let connection = state.pool.get().await.expect("connection");
            seed_queue_mapping_thread(&connection, false).await;
        }
        let _env = ComicVineKeyEnv::install();
        let fake = state.recording_fake().expect("recording provider fake");
        fake.clear();
        let (volume, issues) = queue_mapping_provider_payloads();
        for payload in [volume, issues] {
            fake.push_ok(
                StatusCode::OK,
                axum::http::HeaderMap::new(),
                Bytes::from(serde_json::to_vec(&payload).expect("provider payload JSON")),
            );
        }

        let Json(response) = load_queue_mapping_preview(state.clone())
            .await
            .expect("cold-cache preview must load the mapping plan");

        assert_eq!(response.scope.status, "available");
        assert!(response.preview_token.is_some());
        assert_eq!(response.counts.safe_exact_match, 6);
        assert_eq!(response.rows.len(), 6);
        let calls = fake.calls();
        assert_eq!(
            calls.len(),
            2,
            "a cold cache makes one volume and one roster read"
        );
        assert!(
            calls[0].path.starts_with("/api/volume/4050-5610777/?"),
            "ComicVine redirects the slash-less volume URL: {}",
            calls[0].path
        );
        assert!(calls[1].path.starts_with("/api/issues/?"));
    }

    // -----------------------------------------------------------------------
    // #5716: canonical v2 AIP-136 preview acceptance contract.
    // -----------------------------------------------------------------------

    async fn seed_v2_preview_thread(
        connection: &tokio_postgres::Client,
        user_id: i32,
        thread_id: i32,
        title: &str,
        first_issue_id: i32,
        issue_count: i32,
    ) {
        connection
            .execute(
                "INSERT INTO users (id, username, created_at, is_admin)
                 VALUES ($1, $2, now(), false) ON CONFLICT (id) DO NOTHING",
                &[&user_id, &format!("v2-preview-{user_id}")],
            )
            .await
            .expect("seed v2 preview user");
        connection
            .execute(
                "INSERT INTO threads
                    (id, user_id, title, issues_remaining, queue_position, status, total_issues, created_at, is_blocked, is_test, manual_creator_credits, queue_position_is_manual)
                 VALUES ($1, $2, $3, 0, 1, 'active', $4, now(), false, false, '[]', false)",
                &[&thread_id, &user_id, &title.to_string(), &issue_count],
            )
            .await
            .expect("seed v2 preview thread");
        for n in 1..=issue_count {
            connection
                .execute(
                    "INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
                     VALUES ($1, $2, $3, 'unread', now(), $4)",
                    &[&(first_issue_id + n - 1), &thread_id, &n.to_string(), &n],
                )
                .await
                .expect("seed v2 preview issue");
        }
    }

    fn v2_preview_volume(external_id: &str, name: &str, issue_count: i32) -> Value {
        serde_json::json!({
            "id": external_id,
            "name": name,
            "publisher": {"name": "DC Comics"},
            "start_year": 1980,
            "count_of_issues": issue_count,
            "site_detail_url": format!("https://comicvine.gamespot.com/volume/4050-{external_id}/"),
            "image": null,
        })
    }

    fn v2_preview_roster(
        external_id: &str,
        numbers: &[&str],
        first_provider_id: i64,
    ) -> Vec<Value> {
        numbers
            .iter()
            .enumerate()
            .map(|(index, number)| {
                serde_json::json!({
                    "issue_id": first_provider_id + index as i64,
                    "issue_number": number,
                    "title": format!("Issue {number}"),
                    "thread_id": null,
                    "thread_title": null,
                    "current_mapping_status": "unresolved",
                    "provider": "comicvine",
                    "external_id": format!("{external_id}-issue-{number}"),
                    "classification": "unresolved",
                    "_roster_only": true,
                    "_provider_metadata": {
                        "name": format!("Issue {number}"),
                        "issue_number": number,
                    },
                })
            })
            .collect()
    }

    async fn load_v2_preview(
        state: Arc<AppState>,
        user_id: i32,
        origin_issue_id: i32,
        external_id: &str,
    ) -> Result<Json<SeriesMappingPreviewResponse>, PreviewError> {
        let body = Bytes::from(format!(
            r#"{{"origin_issue_id":{origin_issue_id},"provider":"comicvine","provider_series_external_id":"{external_id}","scope_mode":"queue_thread_bootstrap"}}"#
        ));
        preview_series_mappings_v2(
            State(state),
            crate::auth::AuthenticatedUser::for_test(user_id),
            body,
        )
        .await
    }

    async fn assert_no_preview_writes(state: &AppState) {
        let connection = state.pool.get().await.expect("connection");
        for (sql, label) in [
            (
                "SELECT count(*) FROM thread_external_series_mappings",
                "series mappings",
            ),
            (
                "SELECT count(*) FROM issue_external_identity_mappings",
                "issue mappings",
            ),
            ("SELECT count(*) FROM external_identities", "identities"),
            (
                "SELECT count(*) FROM catalog_commit_receipts",
                "commit receipts",
            ),
        ] {
            let count: i64 = connection
                .query_one(sql, &[])
                .await
                .expect("no-preview-write count")
                .get(0);
            assert_eq!(count, 0, "{label} must stay empty after a preview");
        }
    }

    fn v2_commit(
        state: Arc<AppState>,
        user_id: i32,
        preview_token: String,
        idempotency_key: &str,
        approved_row_ids: Vec<String>,
    ) -> impl std::future::Future<Output = Result<Json<catalog_commit::CommitResponse>, ApiError>> + Send
    {
        catalog_commit::commit_series_mapping_handler(
            State(state),
            crate::auth::AuthenticatedUser::for_test(user_id),
            axum::Json(catalog_commit::CommitRequest {
                preview_token,
                idempotency_key: idempotency_key.to_string(),
                approved_row_ids,
            }),
        )
    }

    /// The v2 custom method is stateless: it only reads and signs a token that
    /// the durable v2 commit accepts and replays by idempotency key.
    #[tokio::test]
    async fn v2_preview_is_read_only_and_signs_a_commit_ready_token() {
        let state = crate::test_support::test_state(2)
            .await
            .expect("disposable PostgreSQL required");
        let _guard = crate::test_support::reset_for_test(&state).await;
        let volume = "571601";
        {
            let connection = state.pool.get().await.expect("connection");
            seed_v2_preview_thread(&connection, 9101, 571101, "V2 Series", 5711100, 6).await;
        }
        crate::test_support::install_test_volume_roster(
            volume,
            v2_preview_volume(volume, "V2 Series", 6),
            v2_preview_roster(volume, &["1", "2", "3", "4", "5", "6"], 5717000),
        );

        let Json(preview) = load_v2_preview(state.clone(), 9101, 5711100, volume)
            .await
            .expect("v2 preview must load");
        assert_eq!(preview.scope.status, "available");
        assert_eq!(preview.counts.safe_exact_match, 6);
        assert_eq!(preview.rows.len(), 6);
        assert!(preview
            .rows
            .iter()
            .all(|row| row.classification == "safe_exact_match"
                && row.default_selected
                && row.thread_id.is_some()));
        let token = preview.preview_token.expect("available preview token");
        let token_data: Value = serde_json::from_str(&token).expect("signed token JSON");
        assert_eq!(token_data["payload"]["user_id"], 9101);
        assert_eq!(
            token_data["payload"]["scope_mode"],
            "queue_thread_bootstrap"
        );
        assert_eq!(token_data["payload"]["provider_series_external_id"], volume);
        assert!(token_data["signature"].as_str().is_some());
        assert_no_preview_writes(&state).await;

        let approved: Vec<String> = preview
            .rows
            .iter()
            .filter(|row| row.default_selected)
            .map(|row| row.row_id.clone())
            .collect();
        let Json(committed) = v2_commit(
            state.clone(),
            9101,
            token.clone(),
            "v2-preview-read-only",
            approved.clone(),
        )
        .await
        .expect("v2 preview token must commit");
        assert_eq!(committed.confirmed_issue_ids.len(), 6);
        let Json(replay) = v2_commit(state.clone(), 9101, token, "v2-preview-read-only", approved)
            .await
            .expect("identical idempotency key must replay");
        assert_eq!(
            serde_json::to_value(&committed).expect("original response"),
            serde_json::to_value(&replay).expect("replay response")
        );
        crate::test_support::clear_test_volume_roster(volume);
    }

    /// A provider volume whose identity disagrees with the owned thread is an
    /// unavailable preview: no token, no rows, no writes.
    #[tokio::test]
    async fn v2_preview_volume_identity_mismatch_is_unavailable() {
        let state = crate::test_support::test_state(2)
            .await
            .expect("disposable PostgreSQL required");
        let _guard = crate::test_support::reset_for_test(&state).await;
        let volume = "571602";
        {
            let connection = state.pool.get().await.expect("connection");
            seed_v2_preview_thread(&connection, 9102, 571102, "V2 Series", 5711200, 3).await;
        }
        crate::test_support::install_test_volume_roster(
            volume,
            v2_preview_volume(volume, "An Unrelated Comic", 3),
            v2_preview_roster(volume, &["1", "2", "3"], 5718000),
        );

        let Json(preview) = load_v2_preview(state.clone(), 9102, 5711200, volume)
            .await
            .expect("v2 preview must return an unavailable scope");
        assert_eq!(preview.scope.status, "unavailable");
        assert_eq!(
            preview.scope.basis.as_deref(),
            Some("queue_thread_bootstrap_volume_identity_mismatch")
        );
        assert!(preview.preview_token.is_none());
        assert!(preview.rows.is_empty());
        assert_eq!(preview.counts.safe_exact_match, 0);
        assert_no_preview_writes(&state).await;
        crate::test_support::clear_test_volume_roster(volume);
    }

    /// Rows that describe provider inventory (no owned thread) are reported but
    /// can never be approved by the durable commit.
    #[tokio::test]
    async fn v2_preview_provider_only_rows_are_not_committable() {
        let state = crate::test_support::test_state(2)
            .await
            .expect("disposable PostgreSQL required");
        let _guard = crate::test_support::reset_for_test(&state).await;
        let volume = "571603";
        {
            let connection = state.pool.get().await.expect("connection");
            seed_v2_preview_thread(&connection, 9103, 571103, "V2 Series", 5711300, 2).await;
        }
        crate::test_support::install_test_volume_roster(
            volume,
            v2_preview_volume(volume, "V2 Series", 4),
            v2_preview_roster(volume, &["1", "2", "3", "4"], 5719000),
        );

        let Json(preview) = load_v2_preview(state.clone(), 9103, 5711300, volume)
            .await
            .expect("v2 preview must load");
        assert_eq!(preview.counts.safe_exact_match, 2);
        assert_eq!(preview.counts.unresolved, 2);
        let provider_rows: Vec<&SeriesMappingPreviewRow> = preview
            .rows
            .iter()
            .filter(|row| row.thread_id.is_none())
            .collect();
        assert_eq!(provider_rows.len(), 2);
        assert!(provider_rows.iter().all(|row| !row.default_selected));
        let token = preview.preview_token.expect("available preview token");
        assert_no_preview_writes(&state).await;

        let rejected = match v2_commit(
            state.clone(),
            9103,
            token.clone(),
            "v2-provider-only-rejected",
            provider_rows.iter().map(|row| row.row_id.clone()).collect(),
        )
        .await
        {
            Ok(_) => panic!("provider-only rows must not be committable"),
            Err(error) => error,
        };
        assert_eq!(rejected.detail(), "invalid_approved_row");
        assert_no_preview_writes(&state).await;

        let owned: Vec<String> = preview
            .rows
            .iter()
            .filter(|row| row.default_selected)
            .map(|row| row.row_id.clone())
            .collect();
        let Json(committed) =
            v2_commit(state.clone(), 9103, token, "v2-owned-only-committed", owned)
                .await
                .expect("owned exact matches remain committable after the rejection");
        assert_eq!(committed.confirmed_issue_ids, vec![5711300, 5711301]);
        crate::test_support::clear_test_volume_roster(volume);
    }

    /// #5170: the canonical v2 preview must produce and commit the full 33-row
    /// "New Teen Titans (1980)" safe preview, with idempotent replay and no
    /// ambiguous/inventory row leaked into the approval set.
    #[tokio::test]
    async fn v2_preview_covers_5170_thirty_three_issue_regression() {
        let state = crate::test_support::test_state(2)
            .await
            .expect("disposable PostgreSQL required");
        let _guard = crate::test_support::reset_for_test(&state).await;
        let volume = "571604";
        {
            let connection = state.pool.get().await.expect("connection");
            seed_v2_preview_thread(&connection, 9104, 571104, "New Teen Titans", 5711400, 33).await;
        }
        let mut numbers: Vec<String> = (1..=33_i32).map(|n| n.to_string()).collect();
        numbers.push("34".to_string());
        numbers.push("35".to_string());
        let number_refs: Vec<&str> = numbers.iter().map(String::as_str).collect();
        crate::test_support::install_test_volume_roster(
            volume,
            v2_preview_volume(volume, "New Teen Titans (1980)", 35),
            v2_preview_roster(volume, &number_refs, 5720000),
        );

        let Json(preview) = load_v2_preview(state.clone(), 9104, 5711400, volume)
            .await
            .expect("v2 preview must load the 33-issue series");
        assert_eq!(preview.counts.safe_exact_match, 33);
        assert_eq!(preview.counts.unresolved, 2);
        assert_eq!(preview.rows.len(), 35);
        assert_no_preview_writes(&state).await;

        let token = preview.preview_token.expect("available preview token");
        let approved: Vec<String> = preview
            .rows
            .iter()
            .filter(|row| row.default_selected)
            .map(|row| row.row_id.clone())
            .collect();
        assert_eq!(approved.len(), 33);
        let Json(committed) = v2_commit(
            state.clone(),
            9104,
            token.clone(),
            "v2-ntt-33",
            approved.clone(),
        )
        .await
        .expect("all 33 exact owned matches must commit");
        assert_eq!(
            committed.confirmed_issue_ids,
            (5711400..5711433).collect::<Vec<_>>()
        );
        assert!(committed.needs_review_issue_ids.is_empty());

        let connection = state.pool.get().await.expect("connection");
        let confirmed: i64 = connection
            .query_one(
                "SELECT count(*) FROM issue_external_identity_mappings m
                 JOIN issues i ON i.id = m.issue_id
                 WHERE i.thread_id = 571104 AND m.status = 'confirmed'",
                &[],
            )
            .await
            .expect("reload confirmed 33 mappings")
            .get(0);
        assert_eq!(confirmed, 33);
        let series_link: bool = connection
            .query_one(
                "SELECT EXISTS (
                    SELECT 1 FROM thread_external_series_mappings tsm
                    JOIN external_identities e ON e.id = tsm.external_identity_id
                    WHERE tsm.thread_id = 571104 AND tsm.status = 'confirmed'
                      AND e.entity_type = 'series' AND e.external_id = $1
                 )",
                &[&volume],
            )
            .await
            .expect("reload confirmed series link")
            .get(0);
        assert!(series_link);

        let Json(replay) = v2_commit(
            state.clone(),
            9104,
            token.clone(),
            "v2-ntt-33",
            approved.clone(),
        )
        .await
        .expect("identical replay must succeed");
        assert_eq!(
            serde_json::to_value(&committed).expect("original response"),
            serde_json::to_value(&replay).expect("replay response")
        );
        let mut shortened = approved;
        shortened.pop();
        let changed = match v2_commit(state.clone(), 9104, token, "v2-ntt-33", shortened).await {
            Ok(_) => panic!("same key with changed rows must conflict"),
            Err(error) => error,
        };
        assert_eq!(changed.detail(), "idempotency_conflict");
        crate::test_support::clear_test_volume_roster(volume);
    }
}
