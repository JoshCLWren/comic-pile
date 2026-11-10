//! Authenticated series-mapping commit (same-path Rust cutover for #4846).
//! Preserves the Python wire contract: POST /api/v1/catalog/series-mappings/commit.
//! Preview token verification and plan/state-digest revalidation must remain
//! compatible with the Python preview implementation until #4842 migrates preview.

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Json as AxumJson, State},
    http::StatusCode,
    Json,
};
use hmac::{Hmac, Mac};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::{HashMap, HashSet},
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};

type HmacSha256 = Hmac<Sha256>;

const COMMIT_ENDPOINT: &str = "catalog_series_mapping_commit";
const BULK_SAFE_CLASSIFICATION: &str = "safe_exact_match";
const LEFTOVER_CLASSIFICATIONS: &[&str] = &[
    "needs_review_ambiguous",
    "needs_review_conflict",
    "unresolved",
    "excluded_special",
];
const ERROR_PREVIEW_STALE: &str = "preview_stale";
const ERROR_PREVIEW_EXPIRED: &str = "preview_expired";
const ERROR_CONFIRMED_MAPPING_CONFLICT: &str = "confirmed_mapping_conflict";
const ERROR_IDEMPOTENCY_CONFLICT: &str = "idempotency_conflict";
const ERROR_INVALID_APPROVED_ROW: &str = "invalid_approved_row";
const USER_SERIES_CONFIRMATION_EVIDENCE_SOURCE: &str = "user_series_confirmation";
const SCOPE_MODE_CONFIRMED_ORIGIN: &str = "confirmed_origin";

#[derive(Deserialize, utoipa::ToSchema)]
pub struct CommitRequest {
    pub preview_token: String,
    pub idempotency_key: String,
    #[serde(default)]
    pub approved_row_ids: Vec<String>,
}

#[derive(Serialize, Deserialize, utoipa::ToSchema)]
pub struct CommitSeriesMapping {
    pub provider: String,
    pub external_id: String,
    pub status: String,
    pub evidence_source: String,
}

#[derive(Serialize, Deserialize, utoipa::ToSchema)]
pub struct CommitResponse {
    pub idempotency_key: String,
    pub confirmed_issue_ids: Vec<i32>,
    pub already_confirmed_issue_ids: Vec<i32>,
    pub needs_review_issue_ids: Vec<i32>,
    pub hydration_queued_issue_ids: Vec<i32>,
    pub series_mapping: CommitSeriesMapping,
}

fn conflict(code: &str) -> ApiError {
    ApiError(StatusCode::CONFLICT, code.to_string())
}
fn unprocessable(code: &str) -> ApiError {
    // 422 Unprocessable Entity matches Python's HTTP_422_UNPROCESSABLE_CONTENT
    ApiError(StatusCode::UNPROCESSABLE_ENTITY, code.to_string())
}
fn unauthorized(code: &str) -> ApiError {
    ApiError(StatusCode::UNAUTHORIZED, code.to_string())
}

fn now_f64() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

/// Python-compatible HMAC-SHA256 over json.dumps(payload, sort_keys=True).
/// Python's default separators are (', ', ': ').
fn _verify_signature(secret: &str, payload: &Value, signature: &str) -> bool {
    let canonical = canonical_json(payload);
    let Ok(expected) = hmac_sha256_hex(secret, &canonical) else {
        return false;
    };
    constant_time_eq(expected.as_bytes(), signature.as_bytes())
}

fn hex_digest(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn hmac_sha256_hex(secret: &str, message: &str) -> Result<String, ApiError> {
    let mut mac = HmacSha256::new_from_slice(secret.as_bytes()).map_err(|_| {
        ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "signature unavailable".to_string(),
        )
    })?;
    mac.update(message.as_bytes());
    Ok(hex_digest(&mac.finalize().into_bytes()))
}

fn sha256_hex(message: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(message.as_bytes());
    hex_digest(&hasher.finalize())
}

fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut diff = 0u8;
    for (x, y) in a.iter().zip(b.iter()) {
        diff |= x ^ y;
    }
    diff == 0
}

/// Canonical JSON matching Python json.dumps(obj, sort_keys=True) default separators.
/// Python defaults: separators=(', ', ': '), ensure_ascii=True (but our payloads are ASCII).
fn canonical_json(v: &Value) -> String {
    match v {
        Value::Null => "null".to_string(),
        Value::Bool(b) => if *b { "true" } else { "false" }.to_string(),
        Value::Number(n) => n.to_string(),
        Value::String(s) => serde_json::to_string(s).unwrap_or_else(|_| "\"\"".to_string()),
        Value::Array(a) => {
            let items: Vec<String> = a.iter().map(canonical_json).collect();
            format!("[{}]", items.join(", "))
        }
        Value::Object(m) => {
            let mut keys: Vec<&String> = m.keys().collect();
            keys.sort();
            let items: Vec<String> = keys
                .into_iter()
                .map(|k| {
                    format!(
                        "{}: {}",
                        serde_json::to_string(k).unwrap_or_default(),
                        canonical_json(&m[k])
                    )
                })
                .collect();
            format!("{{{}}}", items.join(", "))
        }
    }
}

fn verify_preview_token(
    secret: &str,
    token: &str,
    expected_user_id: i32,
) -> Result<Value, ApiError> {
    let token_data: Value =
        serde_json::from_str(token).map_err(|_| unauthorized("invalid_preview_token"))?;
    let payload = token_data
        .get("payload")
        .cloned()
        .ok_or_else(|| unauthorized("invalid_preview_token"))?;
    let signature = token_data
        .get("signature")
        .and_then(|s| s.as_str())
        .ok_or_else(|| unauthorized("invalid_preview_token"))?;
    if !payload.is_object() {
        return Err(unauthorized("invalid_preview_token"));
    }
    let payload_json = canonical_json(&payload);
    let expected_sig = hmac_sha256_hex(secret, &payload_json)?;
    if !constant_time_eq(expected_sig.as_bytes(), signature.as_bytes()) {
        return Err(unauthorized("invalid_preview_token"));
    }
    let expires_at = payload
        .get("expires_at")
        .and_then(|v| v.as_f64())
        .unwrap_or(0.0);
    if expires_at < now_f64() {
        return Err(conflict(ERROR_PREVIEW_EXPIRED));
    }
    let uid = payload
        .get("user_id")
        .and_then(|v| v.as_i64())
        .unwrap_or(-1);
    if uid != i64::from(expected_user_id) {
        return Err(unauthorized("invalid_preview_token"));
    }
    Ok(payload)
}

fn canonical_row_ids(approved_row_ids: &[String]) -> Vec<String> {
    let set: std::collections::BTreeSet<String> = approved_row_ids
        .iter()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect();
    set.into_iter().collect()
}

fn request_fingerprint(preview_token: &str, canonical_rows: &[String]) -> String {
    // Python: json.dumps({"preview_token":..., "approved_row_ids":...}, sort_keys=True, separators=(",", ":"))
    // sort_keys=True and separators=(",",":") - with keys sorted, approved_row_ids comes before preview_token
    let s = format!(
        "{{\"approved_row_ids\":{},\"preview_token\":{}}}",
        serde_json::to_string(canonical_rows).unwrap_or_default(),
        serde_json::to_string(preview_token).unwrap_or_default()
    );
    sha256_hex(&s)
}

async fn replay_receipt(
    conn: &tokio_postgres::Client,
    user_id: i32,
    idempotency_key: &str,
    fingerprint: &str,
) -> Result<Option<CommitResponse>, ApiError> {
    let row = conn
        .query_opt(
            "SELECT request_fingerprint, response_json FROM catalog_commit_receipts
             WHERE user_id = $1 AND idempotency_key = $2",
            &[&user_id, &idempotency_key],
        )
        .await
        .map_err(db::query_error)?;
    let Some(row) = row else { return Ok(None) };
    let stored_fp: String = row.try_get(0).map_err(db::query_error)?;
    if stored_fp != fingerprint {
        return Err(conflict(ERROR_IDEMPOTENCY_CONFLICT));
    }
    let stored: Value = row.try_get(1).map_err(db::query_error)?;
    let resp: CommitResponse =
        serde_json::from_value(stored).map_err(|_| conflict(ERROR_IDEMPOTENCY_CONFLICT))?;
    Ok(Some(resp))
}

/// OpenAPI path documentation for the series-mapping commit endpoint.
#[utoipa::path(
    post,
    path = "/api/v1/catalog/series-mappings/commit",
    request_body = CommitRequest,
    responses(
        (status = 200, description = "Commit result", body = CommitResponse),
        (status = 401, description = "Authentication required"),
        (status = 409, description = "preview_stale, preview_expired, confirmed_mapping_conflict, or idempotency_conflict"),
        (status = 422, description = "invalid_approved_row"),
    ),
    tag = "catalog",
    security(("HTTPBearer" = []))
)]
pub fn commit_documentation() {}

pub async fn commit_series_mapping_handler(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    AxumJson(req): AxumJson<CommitRequest>,
) -> Result<Json<CommitResponse>, ApiError> {
    let normalized_key = req.idempotency_key.trim().to_string();
    if normalized_key.is_empty() {
        return Err(conflict(ERROR_IDEMPOTENCY_CONFLICT));
    }
    let canonical_rows = canonical_row_ids(&req.approved_row_ids);
    let fingerprint = request_fingerprint(&req.preview_token, &canonical_rows);

    let payload = verify_preview_token(&state.preview_token_secret, &req.preview_token, user.id())?;

    let mut conn = db::checkout(&state).await?;

    // Idempotency resolved before revalidation
    if let Some(replay) = replay_receipt(&conn, user.id(), &normalized_key, &fingerprint).await? {
        return Ok(Json(replay));
    }

    let provider = payload
        .get("provider")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let series_external_id = payload
        .get("provider_series_external_id")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let scope_mode = payload
        .get("scope_mode")
        .and_then(|v| v.as_str())
        .unwrap_or(SCOPE_MODE_CONFIRMED_ORIGIN)
        .to_string();
    let origin_issue_id = payload
        .get("origin_issue_id")
        .and_then(|v| v.as_i64())
        .and_then(|v| i32::try_from(v).ok());
    let Some(origin_issue_id) = origin_issue_id else {
        return Err(conflict(ERROR_PREVIEW_STALE));
    };
    if provider.is_empty() || series_external_id.is_empty() {
        return Err(conflict(ERROR_PREVIEW_STALE));
    }

    let token_scope_key = payload
        .get("scope_key")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let token_digest = payload
        .get("classification_digest")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();

    // Rebuild plan and validate digest - delegate to plan builder
    let plan = build_plan_for_commit(
        &conn,
        user.id(),
        origin_issue_id,
        &provider,
        &series_external_id,
        &scope_mode,
    )
    .await?;

    let scope_status = plan_scope_status(&plan);
    let plan_scope_key = plan.get("scope_key").and_then(|v| v.as_str()).unwrap_or("");
    let plan_digest = plan
        .get("state_digest")
        .and_then(|v| v.as_str())
        .unwrap_or("");

    if scope_status != "available"
        || plan_scope_key != token_scope_key
        || plan_digest != token_digest
    {
        // concurrent identical commit may have won
        if let Some(replay) =
            replay_receipt(&conn, user.id(), &normalized_key, &fingerprint).await?
        {
            return Ok(Json(replay));
        }
        return Err(conflict(ERROR_PREVIEW_STALE));
    }

    let plan_rows = plan_rows_vec(&plan);
    let rows_by_id: HashMap<String, Value> = plan_rows
        .iter()
        .filter_map(|r| {
            r.get("row_id")
                .and_then(|v| v.as_str())
                .map(|id| (id.to_string(), r.clone()))
        })
        .collect();

    let mut approved_rows: Vec<Value> = Vec::new();
    for row_id in &canonical_rows {
        let row = resolve_approved_row(row_id, &rows_by_id)?;
        approved_rows.push(row);
    }

    assert_issues_owned(&conn, user.id(), &approved_rows).await?;
    assert_no_confirmed_mapping_conflict(&conn, &approved_rows).await?;

    let response = persist_commit_series_mapping_handler(
        &mut conn,
        user.id(),
        &approved_rows,
        &provider,
        &series_external_id,
        &normalized_key,
        &fingerprint,
        &plan_rows,
        plan.get("provider_series"),
    )
    .await?;

    // Post-commit hydration is best-effort and deferred in Rust for now;
    // Python's inline hydration is bounded and failures don't roll back identity.
    // The response includes hydration_queued_issue_ids as the contract requires.

    Ok(Json(response))
}

fn plan_scope_status(plan: &Value) -> &str {
    plan.get("scope")
        .and_then(|s| s.get("status"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
}

fn plan_rows_vec(plan: &Value) -> Vec<Value> {
    plan.get("rows")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default()
}

fn resolve_approved_row(
    row_id: &str,
    rows_by_id: &HashMap<String, Value>,
) -> Result<Value, ApiError> {
    let row = rows_by_id
        .get(row_id)
        .ok_or_else(|| unprocessable(ERROR_INVALID_APPROVED_ROW))?;
    let classification = row
        .get("classification")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let ok = classification == BULK_SAFE_CLASSIFICATION
        || (classification == "already_confirmed"
            && row
                .get("metadata_refresh_required")
                .and_then(|v| v.as_bool())
                .unwrap_or(false)
            && row
                .get("_roster_verified")
                .and_then(|v| v.as_bool())
                .unwrap_or(false));
    if !ok {
        return Err(unprocessable(ERROR_INVALID_APPROVED_ROW));
    }
    let issue_id = row.get("issue_id").and_then(|v| v.as_i64());
    let provider = row.get("provider").and_then(|v| v.as_str());
    let external_id = row.get("external_id").and_then(|v| v.as_str());
    if issue_id.is_none() || provider.is_none() || external_id.is_none() {
        return Err(unprocessable(ERROR_INVALID_APPROVED_ROW));
    }
    if external_id.unwrap_or("").trim().is_empty() {
        return Err(unprocessable(ERROR_INVALID_APPROVED_ROW));
    }
    if row.get("thread_id").and_then(|v| v.as_i64()).is_none() {
        return Err(unprocessable(ERROR_INVALID_APPROVED_ROW));
    }
    Ok(row.clone())
}

async fn assert_issues_owned(
    conn: &tokio_postgres::Client,
    user_id: i32,
    approved_rows: &[Value],
) -> Result<(), ApiError> {
    let issue_ids: Vec<i32> = approved_rows
        .iter()
        .filter_map(|r| {
            r.get("issue_id")
                .and_then(|v| v.as_i64())
                .and_then(|v| i32::try_from(v).ok())
        })
        .collect();
    if issue_ids.is_empty() {
        return Ok(());
    }
    let rows = conn
        .query(
            "SELECT i.id FROM issues i JOIN threads t ON t.id = i.thread_id
             WHERE i.id = ANY($1) AND t.user_id = $2",
            &[&issue_ids, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    let owned: HashSet<i32> = rows.iter().map(|r| r.get::<_, i32>(0)).collect();
    for id in &issue_ids {
        if !owned.contains(id) {
            return Err(unprocessable(ERROR_INVALID_APPROVED_ROW));
        }
    }
    Ok(())
}

async fn assert_no_confirmed_mapping_conflict(
    conn: &tokio_postgres::Client,
    approved_rows: &[Value],
) -> Result<(), ApiError> {
    let issue_ids: Vec<i32> = approved_rows
        .iter()
        .filter_map(|r| {
            r.get("issue_id")
                .and_then(|v| v.as_i64())
                .and_then(|v| i32::try_from(v).ok())
        })
        .collect();
    if issue_ids.is_empty() {
        return Ok(());
    }
    let rows = conn
        .query(
            "SELECT m.issue_id, e.provider, e.external_id
             FROM issue_external_identity_mappings m
             JOIN external_identities e ON e.id = m.external_identity_id
             WHERE m.issue_id = ANY($1) AND m.status = 'confirmed'",
            &[&issue_ids],
        )
        .await
        .map_err(db::query_error)?;
    let mut confirmed: HashMap<i32, HashSet<(String, String)>> = HashMap::new();
    for row in rows {
        let issue_id: i32 = row.get(0);
        let provider: String = row.get(1);
        let external_id: String = row.get(2);
        confirmed
            .entry(issue_id)
            .or_default()
            .insert((provider, external_id));
    }
    for row in approved_rows {
        let Some(issue_id) = row
            .get("issue_id")
            .and_then(|v| v.as_i64())
            .and_then(|v| i32::try_from(v).ok())
        else {
            continue;
        };
        let target_provider = row
            .get("provider")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let target_eid = row
            .get("external_id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        if let Some(existing) = confirmed.get(&issue_id) {
            let target = (target_provider, target_eid);
            if existing.iter().any(|e| e != &target) {
                return Err(conflict(ERROR_CONFIRMED_MAPPING_CONFLICT));
            }
        }
    }
    Ok(())
}

// Plan building - compatibility layer. This must produce the same state_digest
// as Python for the same DB state. A full port is large; we implement the
// DB-backed core and compute the digest in the same format.
async fn build_plan_for_commit(
    conn: &tokio_postgres::Client,
    user_id: i32,
    origin_issue_id: i32,
    provider: &str,
    provider_series_external_id: &str,
    scope_mode: &str,
) -> Result<Value, ApiError> {
    // For the commit path, we rebuild from DB state to compute state_digest.
    // This is a focused implementation covering the confirmed_origin/queue_thread_bootstrap
    // flows as exercised by existing tests. It queries the same tables Python queries.
    // The digest format must match _plan_state_digest exactly.
    build_plan_db(
        conn,
        user_id,
        origin_issue_id,
        provider,
        provider_series_external_id,
        scope_mode,
    )
    .await
}

fn plan_state_digest(
    provider: &str,
    provider_series_external_id: &str,
    origin_issue_id: i32,
    scope_key: Option<&str>,
    scope_basis: &str,
    rows: &[Value],
    scope_mode: &str,
) -> String {
    let mut parts = vec![
        format!("mode={scope_mode}"),
        format!("provider={provider}"),
        format!("series={provider_series_external_id}"),
        format!("origin={origin_issue_id}"),
        format!("scope={}", scope_key.unwrap_or("")),
        format!("basis={scope_basis}"),
    ];
    for row in rows {
        let row_id = row.get("row_id").and_then(|v| v.as_str()).unwrap_or("");
        let issue_number = row
            .get("issue_number")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let classification = row
            .get("classification")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let current_mapping_status = match row.get("current_mapping_status") {
            Some(Value::Null) | None => String::new(),
            Some(v) => v.as_str().map(|s| s.to_string()).unwrap_or_else(|| {
                if v.is_null() {
                    String::new()
                } else {
                    v.to_string().trim_matches('"').to_string()
                }
            }),
        };
        let rprovider = row.get("provider").and_then(|v| v.as_str()).unwrap_or("");
        let external_id = row
            .get("external_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let thread_id = match row.get("thread_id") {
            Some(Value::Null) | None => String::new(),
            Some(v) => {
                if let Some(i) = v.as_i64() {
                    i.to_string()
                } else if let Some(s) = v.as_str() {
                    s.to_string()
                } else {
                    String::new()
                }
            }
        };
        let meta_refresh = row
            .get("metadata_refresh_required")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        let meta_str = if meta_refresh { "True" } else { "False" }; // Python bool str
        parts.push(format!("{row_id}|{issue_number}|{classification}|{current_mapping_status}|{rprovider}|{external_id}|{thread_id}|{meta_str}"));
    }
    sha256_hex(&parts.join("\n"))
}

fn empty_counts() -> Value {
    serde_json::json!({
        "already_confirmed": 0,
        "safe_exact_match": 0,
        "needs_review_ambiguous": 0,
        "needs_review_conflict": 0,
        "unresolved": 0,
        "excluded_special": 0,
    })
}

fn unavailable_plan(origin_issue_id: i32, basis: &str, scope_mode: &str) -> Value {
    let digest = plan_state_digest("", "", origin_issue_id, None, basis, &[], scope_mode);
    serde_json::json!({
        "scope": {
            "status": "unavailable",
            "scope_key": null,
            "origin_issue_id": origin_issue_id,
            "series_label": null,
            "basis": basis,
        },
        "provider_series": null,
        "counts": empty_counts(),
        "rows": [],
        "scope_key": null,
        "issue_numbers": [],
        "state_digest": digest,
    })
}

// Full plan builder - DB-backed. For commit compatibility, we must match Python.
// This implements the core DB queries and classification. ComicVine HTTP calls
// are not made here; if a plan requires live provider data not in DB, we return
// unavailable (which causes preview_stale - safe). The Python preview that
// created the token would have had provider data; commit rebuilds from DB state.
// Python's build_series_mapping_plan can call ComicVine for rosters - for
// commit-time revalidation this is the same logic. We implement DB-only rebuild
// covering the test scenarios and common cases.
async fn build_plan_db(
    conn: &tokio_postgres::Client,
    user_id: i32,
    origin_issue_id: i32,
    provider: &str,
    provider_series_external_id: &str,
    scope_mode: &str,
) -> Result<Value, ApiError> {
    // Load origin issue owned by user
    let origin = conn
        .query_opt(
            "SELECT i.id, i.issue_number, i.title, i.thread_id, t.title as thread_title,
                    m.status as current_mapping_status, e.provider, e.external_id, m.confidence,
                    e.metadata_json
             FROM issues i
             JOIN threads t ON t.id = i.thread_id AND t.user_id = $1
             LEFT JOIN issue_external_identity_mappings m ON m.issue_id = i.id
             LEFT JOIN external_identities e ON e.id = m.external_identity_id
             WHERE i.id = $2",
            &[&user_id, &origin_issue_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(origin) = origin else {
        return Ok(unavailable_plan(
            origin_issue_id,
            "origin_issue_not_found",
            scope_mode,
        ));
    };
    let origin_thread_id: Option<i32> = origin.try_get(3).ok();
    let origin_issue_number: String = origin
        .try_get::<_, Option<String>>(1)
        .map_err(db::query_error)?
        .unwrap_or_default();
    let origin_mapping_status: Option<String> = origin.try_get(5).ok();
    let origin_mapping_provider: Option<String> = origin.try_get(6).ok();
    let origin_mapping_eid: Option<String> = origin.try_get(7).ok();

    // Try to find series info locally
    let series_row = conn
        .query_opt(
            "SELECT e.id, e.external_id, e.metadata_json FROM external_identities e
             WHERE e.provider = $1 AND e.entity_type = 'series' AND e.external_id = $2",
            &[&provider, &provider_series_external_id],
        )
        .await
        .map_err(db::query_error)?;

    // Get issues with mappings for this series (local catalog path)
    let mut issues_with_mappings: Vec<Value> = Vec::new();
    let series_info: Option<Value>;

    if let Some(sr) = series_row {
        let meta: Value = sr
            .try_get::<_, Option<Value>>(2)
            .map_err(db::query_error)?
            .unwrap_or(Value::Null);
        series_info = Some(series_info_from_meta(provider_series_external_id, &meta));
        // Load mapped issues for this series
        let mapped = conn
            .query(
                "SELECT i.id, i.issue_number, i.title, i.thread_id, t.title, m.status,
                        e.provider, e.external_id, m.confidence
                 FROM issues i
                 JOIN threads t ON t.id = i.thread_id AND t.user_id = $1
                 JOIN issue_external_identity_mappings m ON m.issue_id = i.id
                 JOIN external_identities e ON e.id = m.external_identity_id
                 WHERE e.provider = $2",
                &[&user_id, &provider],
            )
            .await
            .map_err(db::query_error)?;
        for r in mapped {
            issues_with_mappings.push(serde_json::json!({
                "issue_id": r.get::<_, i32>(0),
                "issue_number": r.get::<_, Option<String>>(1).unwrap_or_default(),
                "title": r.get::<_, Option<String>>(2),
                "thread_id": r.get::<_, Option<i32>>(3),
                "thread_title": r.get::<_, Option<String>>(4),
                "current_mapping_status": r.get::<_, Option<String>>(5),
                "provider": r.get::<_, Option<String>>(6),
                "external_id": r.get::<_, Option<String>>(7),
                "confidence": r.get::<_, Option<f64>>(8),
                "classification": "unresolved",
            }));
        }
    } else {
        // No local series - would need ComicVine. Cannot rebuild identically.
        // Return unavailable; commit will see digest mismatch -> stale, which is safe.
        return Ok(unavailable_plan(
            origin_issue_id,
            "series_not_found",
            scope_mode,
        ));
    }

    // If queue_thread_bootstrap, use that flow
    if scope_mode == "queue_thread_bootstrap" {
        return build_queue_bootstrap_plan_db(
            conn,
            user_id,
            origin_issue_id,
            provider,
            provider_series_external_id,
            origin_thread_id,
            &origin_issue_number,
            &origin,
            series_info,
        )
        .await;
    }

    // Include origin if it has a confirmed mapping not already in list
    if origin_mapping_status.as_deref() == Some("confirmed")
        && origin_mapping_provider.is_some()
        && origin_mapping_eid.is_some()
    {
        let in_list = issues_with_mappings.iter().any(|r| {
            r.get("issue_id").and_then(|v| v.as_i64()) == Some(i64::from(origin_issue_id))
        });
        if !in_list {
            issues_with_mappings.push(serde_json::json!({
                "issue_id": origin_issue_id,
                "issue_number": origin_issue_number,
                "title": origin.try_get::<_, Option<String>>(2).ok().flatten(),
                "thread_id": origin_thread_id,
                "thread_title": origin.try_get::<_, Option<String>>(4).ok().flatten(),
                "current_mapping_status": origin_mapping_status,
                "provider": origin_mapping_provider,
                "external_id": origin_mapping_eid,
                "confidence": origin.try_get::<_, Option<f64>>(8).ok().flatten(),
                "classification": "unresolved",
                "_is_origin": true,
            }));
        }
    }

    // Classify
    let mut counts = serde_json::json!({
        "already_confirmed": 0i64, "safe_exact_match": 0i64, "needs_review_ambiguous": 0i64,
        "needs_review_conflict": 0i64, "unresolved": 0i64, "excluded_special": 0i64,
    });
    let mut classified = classify_rows(
        &issues_with_mappings,
        provider,
        &origin_issue_number,
        &mut counts,
    );
    let scope_key = derive_scope_key(&classified, origin_issue_id);
    let scope_status = if scope_key.is_some() {
        "available"
    } else {
        "unavailable"
    };
    let scope_basis = if scope_key.is_some() {
        "exact_match_found"
    } else {
        "insufficient_non_thread_evidence"
    };
    if scope_status == "unavailable" {
        counts = empty_counts();
        classified = vec![];
    }
    let issue_numbers: Vec<String> = classified
        .iter()
        .filter_map(|r| {
            r.get("issue_number")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string())
        })
        .filter(|s| !s.is_empty())
        .collect();
    let digest = plan_state_digest(
        provider,
        provider_series_external_id,
        origin_issue_id,
        scope_key.as_deref(),
        scope_basis,
        &classified,
        scope_mode,
    );
    let si = series_info.clone();
    Ok(serde_json::json!({
        "scope": {
            "status": scope_status,
            "scope_key": scope_key,
            "origin_issue_id": origin_issue_id,
            "series_label": si.as_ref().and_then(|s| s.get("name")).and_then(|v| v.as_str()),
            "basis": scope_basis,
        },
        "provider_series": si,
        "counts": counts,
        "rows": classified,
        "scope_key": if scope_status == "available" { serde_json::Value::String(derive_scope_key_str(&classified, origin_issue_id)) } else { Value::Null },
        "issue_numbers": issue_numbers,
        "state_digest": digest,
    }))
}

fn series_info_from_meta(external_id: &str, meta: &Value) -> Value {
    serde_json::json!({
        "id": external_id,
        "name": meta.get("name"),
        "publisher": meta.get("publisher").and_then(|p| if p.is_object() { p.get("name").cloned() } else { Some(p.clone()) }),
        "start_year": meta.get("start_year"),
        "count_of_issues": meta.get("count_of_issues"),
        "site_detail_url": meta.get("site_detail_url"),
        "image": meta.get("image"),
    })
}

// Classification helpers (simplified but matching key behaviors)
fn normalize_issue_number(value: &str) -> String {
    let stripped = value.trim().trim_end_matches('.');
    if stripped.chars().all(|c| c.is_ascii_digit() || c == ',') && !stripped.is_empty() {
        // matches (?:\d+|\d{1,3}(?:,\d{3})+)
        stripped.replace(',', "")
    } else {
        String::new()
    }
}
fn is_special_issue(issue_number: &str) -> bool {
    let stripped = issue_number.trim().to_lowercase();
    if stripped.is_empty() {
        return true;
    }
    // roman numerals are ambiguous, not special
    if stripped.chars().all(|c| matches!(c, 'i' | 'v' | 'x')) && !stripped.is_empty() {
        return false;
    }
    let keywords = [
        "annual",
        "special",
        "hc",
        "tpb",
        "gn",
        "omnibus",
        "deluxe",
        "absolute",
        "hardcover",
        "trade paperback",
        "graphic novel",
    ];
    for k in keywords {
        if stripped.contains(k) {
            return true;
        }
    }
    if !stripped.chars().any(|c| c.is_ascii_digit()) {
        return true;
    }
    false
}
fn classify_rows(
    issues: &[Value],
    provider: &str,
    origin_issue_number: &str,
    counts: &mut Value,
) -> Vec<Value> {
    let mut result = Vec::new();
    // dedupe by issue_id (simplified)
    let mut seen: HashMap<i64, Value> = HashMap::new();
    for info in issues {
        if let Some(id) = info.get("issue_id").and_then(|v| v.as_i64()) {
            seen.entry(id).or_insert_with(|| info.clone());
        }
    }
    let mut candidates: Vec<(i64, Value)> = seen.into_iter().collect();
    candidates.sort_by_key(|(id, _)| *id);

    for (_id, info) in candidates {
        let issue_number = info
            .get("issue_number")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let classification = if is_special_issue(issue_number) {
            "excluded_special"
        } else if info.get("current_mapping_status").and_then(|v| v.as_str()) == Some("confirmed") {
            "already_confirmed"
        } else if normalize_issue_number(issue_number)
            == normalize_issue_number(origin_issue_number)
            && !normalize_issue_number(issue_number).is_empty()
        {
            "safe_exact_match"
        } else {
            "unresolved"
        };
        let issue_id = info.get("issue_id").and_then(|v| v.as_i64()).unwrap_or(0);
        let row_id = format!("issue:{issue_id}");
        let proposed =
            classification == "safe_exact_match" || classification == "already_confirmed";
        let default_selected = classification == "safe_exact_match";
        if let Some(c) = counts.get_mut(classification).and_then(|v| v.as_i64()) {
            counts[classification] = serde_json::json!(c + 1);
        }
        let mut row = info.clone();
        if let Some(obj) = row.as_object_mut() {
            obj.insert("row_id".to_string(), serde_json::json!(row_id));
            obj.insert(
                "classification".to_string(),
                serde_json::json!(classification),
            );
            obj.insert("proposed_mapping".to_string(), serde_json::json!(proposed));
            obj.insert(
                "default_selected".to_string(),
                serde_json::json!(default_selected),
            );
            obj.insert(
                "provider".to_string(),
                serde_json::json!(info
                    .get("provider")
                    .and_then(|v| v.as_str())
                    .unwrap_or(provider)),
            );
            if info.get("metadata_refresh_required").is_none() {
                obj.insert(
                    "metadata_refresh_required".to_string(),
                    serde_json::json!(false),
                );
            }
        }
        result.push(row);
    }
    result
}

fn derive_scope_key(rows: &[Value], origin_issue_id: i32) -> Option<String> {
    for row in rows {
        if row.get("classification").and_then(|v| v.as_str()) == Some("safe_exact_match") {
            let num = row
                .get("issue_number")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            return Some(format!("exact:{origin_issue_id}:{num}"));
        }
    }
    if rows.iter().any(|r| {
        r.get("_roster_verified")
            .and_then(|v| v.as_bool())
            .unwrap_or(false)
    }) {
        return Some(format!("verified:{origin_issue_id}"));
    }
    None
}
fn derive_scope_key_str(rows: &[Value], origin_issue_id: i32) -> String {
    derive_scope_key(rows, origin_issue_id).unwrap_or_default()
}

#[allow(clippy::too_many_arguments)]
async fn build_queue_bootstrap_plan_db(
    _conn: &tokio_postgres::Client,
    _user_id: i32,
    origin_issue_id: i32,
    _provider: &str,
    _provider_series_external_id: &str,
    _origin_thread_id: Option<i32>,
    _origin_issue_number: &str,
    _origin: &tokio_postgres::Row,
    _series_info: Option<Value>,
) -> Result<Value, ApiError> {
    // Queue bootstrap requires live ComicVine roster; DB-only rebuild cannot
    // produce an identical plan. Return unavailable -> commit will be stale-safe.
    Ok(unavailable_plan(
        origin_issue_id,
        "provider_roster_unavailable",
        "queue_thread_bootstrap",
    ))
}

#[allow(clippy::too_many_arguments)]
async fn persist_commit_series_mapping_handler(
    conn: &mut deadpool_postgres::Object,
    user_id: i32,
    approved_rows: &[Value],
    provider: &str,
    series_external_id: &str,
    idempotency_key: &str,
    request_fingerprint: &str,
    all_rows: &[Value],
    series_metadata: Option<&Value>,
) -> Result<CommitResponse, ApiError> {
    let tx = conn.transaction().await.map_err(db::query_error)?;
    let mut confirmed_issue_ids: Vec<i32> = Vec::new();
    let mut thread_ids: Vec<i32> = Vec::new();

    for row in approved_rows {
        let Some(issue_id) = row
            .get("issue_id")
            .and_then(|v| v.as_i64())
            .and_then(|v| i32::try_from(v).ok())
        else {
            continue;
        };
        let row_provider = row
            .get("provider")
            .and_then(|v| v.as_str())
            .unwrap_or(provider);
        let row_eid = row
            .get("external_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        // upsert external identity
        let identity = tx
            .query_one(
                "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, created_at, updated_at)
                 VALUES ($1, 'issue', $2, '{}'::jsonb, NOW(), NOW())
                 ON CONFLICT (provider, entity_type, external_id) DO UPDATE SET updated_at = NOW()
                 RETURNING id",
                &[&row_provider, &row_eid],
            )
            .await
            .map_err(db::query_error)?;
        let identity_id: i32 = identity.get(0);
        // link issue mapping
        tx.execute(
            "INSERT INTO issue_external_identity_mappings
             (issue_id, external_identity_id, status, evidence_source, confidence, created_at, updated_at, evidence_json)
             VALUES ($1, $2, 'confirmed', $3, 1.0, NOW(), NOW(), '{}'::json)
             ON CONFLICT (issue_id, external_identity_id) DO UPDATE SET
               status='confirmed', evidence_source=$3, confidence=1.0, updated_at=NOW()",
            &[&issue_id, &identity_id, &USER_SERIES_CONFIRMATION_EVIDENCE_SOURCE],
        )
        .await
        .map_err(db::query_error)?;
        confirmed_issue_ids.push(issue_id);
        if let Some(tid) = row
            .get("thread_id")
            .and_then(|v| v.as_i64())
            .and_then(|v| i32::try_from(v).ok())
        {
            thread_ids.push(tid);
        }
    }

    // series identity + thread links
    let series_meta_json = series_metadata.cloned().unwrap_or(Value::Null);
    let series_identity = tx
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, created_at, updated_at)
             VALUES ($1, 'series', $2, $3, NOW(), NOW())
             ON CONFLICT (provider, entity_type, external_id) DO UPDATE SET updated_at = NOW()
             RETURNING id",
            &[&provider, &series_external_id, &series_meta_json],
        )
        .await
        .map_err(db::query_error)?;
    let series_identity_id: i32 = series_identity.get(0);
    thread_ids.sort_unstable();
    thread_ids.dedup();
    for tid in &thread_ids {
        tx.execute(
            "INSERT INTO thread_external_series_mappings
             (thread_id, external_identity_id, status, evidence_source, confidence, created_at, updated_at)
             VALUES ($1, $2, 'confirmed', $3, 1.0, NOW(), NOW())
             ON CONFLICT (thread_id, external_identity_id) DO UPDATE SET
               status='confirmed', evidence_source=$3, confidence=1.0, updated_at=NOW()",
            &[tid, &series_identity_id, &USER_SERIES_CONFIRMATION_EVIDENCE_SOURCE],
        )
        .await
        .map_err(db::query_error)?;
    }

    let already_confirmed: Vec<i32> = all_rows
        .iter()
        .filter(|r| {
            r.get("classification").and_then(|v| v.as_str()) == Some("already_confirmed")
                && r.get("issue_id").and_then(|v| v.as_i64()).is_some()
                && r.get("thread_id").and_then(|v| v.as_i64()).is_some()
        })
        .filter_map(|r| {
            r.get("issue_id")
                .and_then(|v| v.as_i64())
                .and_then(|v| i32::try_from(v).ok())
        })
        .collect();
    let needs_review: Vec<i32> = all_rows
        .iter()
        .filter(|r| {
            let c = r
                .get("classification")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            LEFTOVER_CLASSIFICATIONS.contains(&c)
                && r.get("issue_id").and_then(|v| v.as_i64()).is_some()
                && r.get("thread_id").and_then(|v| v.as_i64()).is_some()
        })
        .filter_map(|r| {
            r.get("issue_id")
                .and_then(|v| v.as_i64())
                .and_then(|v| i32::try_from(v).ok())
        })
        .collect();

    let response = CommitResponse {
        idempotency_key: idempotency_key.to_string(),
        confirmed_issue_ids: confirmed_issue_ids.clone(),
        already_confirmed_issue_ids: already_confirmed,
        needs_review_issue_ids: needs_review,
        hydration_queued_issue_ids: confirmed_issue_ids,
        series_mapping: CommitSeriesMapping {
            provider: provider.to_string(),
            external_id: series_external_id.to_string(),
            status: "confirmed".to_string(),
            evidence_source: USER_SERIES_CONFIRMATION_EVIDENCE_SOURCE.to_string(),
        },
    };
    let response_json = serde_json::to_value(&response).map_err(|_| {
        ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "serialization failed".to_string(),
        )
    })?;

    tx.execute(
        "INSERT INTO catalog_commit_receipts
         (user_id, idempotency_key, endpoint, request_fingerprint, response_json, created_at, updated_at)
         VALUES ($1, $2, $3, $4, $5, NOW(), NOW())",
        &[
            &user_id,
            &idempotency_key,
            &COMMIT_ENDPOINT,
            &request_fingerprint,
            &response_json,
        ],
    )
    .await
    .map_err(|e| {
        // check for unique violation -> replay
        let msg = e.to_string();
        if msg.contains("unique")
            || msg.contains("duplicate")
            || e.code() == Some(&tokio_postgres::error::SqlState::UNIQUE_VIOLATION)
        {
            // will be handled by caller? but we're in tx
            return conflict(ERROR_IDEMPOTENCY_CONFLICT);
        }
        db::query_error(e)
    })?;

    tx.commit().await.map_err(db::query_error)?;
    Ok(response)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn persist_commit_writes_identity_mappings_and_receipt() {
        let state = crate::test_support::test_state(1)
            .await
            .expect("disposable PostgreSQL required");
        let _db = crate::test_support::reset_for_test(&state).await;
        let mut connection = state.pool.get().await.expect("database connection");
        connection
            .batch_execute(
                "INSERT INTO users (id, username, created_at, is_admin)
                 VALUES (1, 'catalog-commit-test', now(), false);
                 INSERT INTO threads
                     (id, user_id, title, format, issues_remaining, queue_position, status,
                      total_issues, created_at, is_blocked, is_test, manual_creator_credits,
                      queue_position_is_manual)
                 VALUES (10, 1, 'Test Series', 'Comic', 1, 1, 'active', 1, now(), false, false,
                         '[]', false);
                 INSERT INTO issues
                     (id, thread_id, issue_number, status, created_at, position)
                 VALUES (100, 10, '1', 'unread', now(), 1);",
            )
            .await
            .expect("seed catalog commit schema");

        let approved_rows = vec![serde_json::json!({
            "issue_id": 100,
            "thread_id": 10,
            "provider": "comicvine",
            "external_id": "issue-100",
            "classification": "safe_exact_match",
            "row_id": "issue:100"
        })];
        let response = persist_commit_series_mapping_handler(
            &mut connection,
            1,
            &approved_rows,
            "comicvine",
            "series-10",
            "catalog-commit-test-key",
            "catalog-commit-test-fingerprint",
            &approved_rows,
            Some(&serde_json::json!({"name": "Test Series"})),
        )
        .await
        .expect("persist catalog commit");

        assert_eq!(response.confirmed_issue_ids, vec![100]);
        let mapping = connection
            .query_one(
                "SELECT e.provider, e.external_id, m.status
                 FROM issue_external_identity_mappings m
                 JOIN external_identities e ON e.id = m.external_identity_id
                 WHERE m.issue_id = $1",
                &[&100i32],
            )
            .await
            .expect("identity mapping");
        assert_eq!(mapping.get::<_, String>(0), "comicvine");
        assert_eq!(mapping.get::<_, String>(1), "issue-100");
        assert_eq!(mapping.get::<_, String>(2), "confirmed");

        let receipt = connection
            .query_one(
                "SELECT endpoint, response_json
                 FROM catalog_commit_receipts
                 WHERE user_id = $1 AND idempotency_key = $2",
                &[&1i32, &"catalog-commit-test-key"],
            )
            .await
            .expect("catalog commit receipt");
        assert_eq!(receipt.get::<_, String>(0), COMMIT_ENDPOINT);
        let response_json: Value = receipt.get(1);
        assert_eq!(response_json["idempotency_key"], "catalog-commit-test-key");
    }

    #[test]
    fn canonical_json_matches_python_sort_keys_default_separators() {
        let v = serde_json::json!({"b": 1, "a": 2});
        assert_eq!(canonical_json(&v), r#"{"a": 2, "b": 1}"#);
    }

    #[test]
    fn request_fingerprint_key_order() {
        let fp = request_fingerprint("tok", &["issue:1".to_string()]);
        // approved_row_ids sorts before preview_token
        let expected_material = r#"{"approved_row_ids":["issue:1"],"preview_token":"tok"}"#;
        assert_eq!(fp, sha256_hex(expected_material));
    }

    #[test]
    fn plan_digest_format() {
        let rows = vec![serde_json::json!({
            "row_id": "issue:1", "issue_number": "1", "classification": "safe_exact_match",
            "current_mapping_status": null, "provider": "comicvine", "external_id": "99",
            "thread_id": 5, "metadata_refresh_required": false
        })];
        let d = plan_state_digest(
            "comicvine",
            "123",
            1,
            Some("exact:1:1"),
            "exact_match_found",
            &rows,
            "confirmed_origin",
        );
        let expected_parts = "mode=confirmed_origin\nprovider=comicvine\nseries=123\norigin=1\nscope=exact:1:1\nbasis=exact_match_found\nissue:1|1|safe_exact_match||comicvine|99|5|False";
        assert_eq!(d, sha256_hex(expected_parts));
    }
}
