//! Authenticated series-mapping commit (same-path Rust cutover for #4846).
//! Preserves the Python wire contract: POST /api/v1/catalog/series-mappings/commit.
//! Preview token verification and plan/state-digest revalidation must remain
//! compatible with the Python preview implementation until #4842 migrates preview.

use crate::{auth::AuthenticatedUser, comicvine_repair, db, ApiError, AppState};
use axum::{
    extract::{Json as AxumJson, State},
    Json,
};
use hmac::{Hmac, Mac};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::{HashMap, HashSet},
    sync::Arc,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use unicode_casefold::UnicodeCaseFold;

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
    ApiError::Conflict(code.to_string())
}
fn unprocessable(code: &str) -> ApiError {
    // 422 Unprocessable Entity matches Python's HTTP_422_UNPROCESSABLE_CONTENT
    ApiError::Unprocessable(code.to_string())
}
fn unauthorized(code: &str) -> ApiError {
    ApiError::Unauthorized(code.to_string())
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
    let mut mac = HmacSha256::new_from_slice(secret.as_bytes())
        .map_err(|_| ApiError::Internal("signature unavailable".to_string()))?;
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
/// Python defaults: separators=(', ', ': '), ensure_ascii=True.
fn python_json_string(value: &str) -> String {
    let encoded = serde_json::to_string(value).unwrap_or_else(|_| "\"\"".to_string());
    let mut ascii = String::with_capacity(encoded.len());
    for ch in encoded.chars() {
        if ch.is_ascii() {
            ascii.push(ch);
        } else {
            for unit in ch.encode_utf16(&mut [0; 2]).iter() {
                ascii.push_str(&format!("\\u{unit:04x}"));
            }
        }
    }
    ascii
}

fn canonical_json(v: &Value) -> String {
    match v {
        Value::Null => "null".to_string(),
        Value::Bool(b) => if *b { "true" } else { "false" }.to_string(),
        Value::Number(n) => n.to_string(),
        Value::String(s) => python_json_string(s),
        Value::Array(a) => {
            let items: Vec<String> = a.iter().map(canonical_json).collect();
            format!("[{}]", items.join(", "))
        }
        Value::Object(m) => {
            let mut keys: Vec<&String> = m.keys().collect();
            keys.sort();
            let items: Vec<String> = keys
                .into_iter()
                .map(|k| format!("{}: {}", python_json_string(k), canonical_json(&m[k])))
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
    let started = Instant::now();
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

    let response = persist_commit_or_replay(
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

    // Mirror Python's request-relative inline hydration deadline (#3776).
    // No detached serverless work, and no provider error can roll back identity.
    let budget = inline_hydration_budget(started.elapsed());
    comicvine_repair::hydrate_catalog_commit(
        &state,
        user.id(),
        &response.confirmed_issue_ids,
        budget,
    )
    .await;

    Ok(Json(response))
}

fn inline_hydration_budget(elapsed: Duration) -> Duration {
    // 10s browser deadline minus 1.5s routing/response reserve; hydration
    // must not consume more than 3s or the remainder of that request.
    Duration::from_secs_f64((8.5_f64 - elapsed.as_secs_f64()).clamp(0.0, 3.0))
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
            "SELECT i.id, i.issue_number, e.metadata_json->>'name' AS title,
                    i.thread_id, t.title as thread_title,
                    m.status as current_mapping_status, e.provider, e.external_id, m.confidence,
                    e.metadata_json
             FROM issues i
             JOIN threads t ON t.id = i.thread_id AND t.user_id = $1
             LEFT JOIN issue_external_identity_mappings m ON m.issue_id = i.id
             LEFT JOIN external_identities e ON e.id = m.external_identity_id
             WHERE i.id = $2
             ORDER BY m.id NULLS LAST
             LIMIT 1",
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
            None,
        )
        .await;
    }

    // Try to find series info locally
    let series_row = conn
        .query_opt(
            "SELECT e.id, e.external_id, e.metadata_json, e.external_url FROM external_identities e
             WHERE e.provider = $1 AND e.entity_type = 'series' AND e.external_id = $2",
            &[&provider, &provider_series_external_id],
        )
        .await
        .map_err(db::query_error)?;

    // Get issues with mappings for this series (local catalog path)
    let mut issues_with_mappings: Vec<Value> = Vec::new();
    let mut series_info: Option<Value>;
    let mut roster_rows: Vec<Value> = Vec::new();

    if let Some(sr) = series_row {
        let meta: Value = sr
            .try_get::<_, Option<Value>>(2)
            .map_err(db::query_error)?
            .unwrap_or(Value::Null);
        let external_url: Option<String> = sr.try_get(3).map_err(db::query_error)?;
        series_info = Some(series_info_from_meta(
            provider_series_external_id,
            &meta,
            external_url.as_deref(),
        ));
        // Load mapped issues for this series
        let mapped = conn
            .query(
                "SELECT i.id, i.issue_number, e.metadata_json::text, i.thread_id,
                        t.title, m.status, e.provider, e.external_id, m.confidence
                 FROM issues i
                 JOIN threads t ON t.id = i.thread_id AND t.user_id = $1
                 JOIN issue_external_identity_mappings m ON m.issue_id = i.id
                 JOIN external_identities e ON e.id = m.external_identity_id
                 JOIN thread_external_series_mappings tsm ON tsm.thread_id = t.id
                   AND tsm.external_identity_id = $3 AND tsm.status = 'confirmed'
                 WHERE e.provider = $2 AND e.entity_type = 'issue'",
                &[&user_id, &provider, &sr.get::<_, i32>(0)],
            )
            .await
            .map_err(db::query_error)?;
        for r in mapped {
            let metadata_text: Option<String> = r.get(2);
            let identity_meta: Value = metadata_text
                .as_deref()
                .and_then(|raw| serde_json::from_str(raw).ok())
                .unwrap_or(Value::Null);
            issues_with_mappings.push(serde_json::json!({
                "issue_id": r.get::<_, i32>(0),
                "issue_number": r.get::<_, Option<String>>(1).unwrap_or_default(),
                "title": identity_meta.get("name"),
                "thread_id": r.get::<_, Option<i32>>(3),
                "thread_title": r.get::<_, Option<String>>(4),
                "current_mapping_status": r.get::<_, Option<String>>(5),
                "provider": r.get::<_, Option<String>>(6),
                "external_id": r.get::<_, Option<String>>(7),
                "confidence": r.get::<_, Option<f64>>(8),
                "classification": "unresolved",
                "_identity_metadata": identity_meta,
            }));
        }

        // Generic sibling previews are legal only after the anchor carries
        // confirmed provider evidence or its thread has a confirmed link to
        // this exact volume. Mere thread membership proves nothing.
        let origin_confirmed = origin_mapping_status.as_deref() == Some("confirmed")
            && origin_mapping_provider.as_deref() == Some(provider);
        let linked_thread = if let Some(thread_id) = origin_thread_id {
            conn.query_one(
                "SELECT EXISTS (
                   SELECT 1 FROM thread_external_series_mappings
                   WHERE thread_id = $1 AND external_identity_id = $2
                     AND status = 'confirmed'
                 )",
                &[&thread_id, &sr.get::<_, i32>(0)],
            )
            .await
            .map_err(db::query_error)?
            .get::<_, bool>(0)
        } else {
            false
        };
        if origin_confirmed || linked_thread {
            // This lookup is best-effort only for locally confirmed series:
            // Python falls back to local rows on provider 503.
            if let Ok((provider_info, roster)) =
                crate::comicvine_repair::catalog_volume_roster(provider_series_external_id).await
            {
                if let (Some(local), Some(fetched)) = (
                    series_info.as_mut().and_then(Value::as_object_mut),
                    provider_info.as_object(),
                ) {
                    local.extend(fetched.clone());
                }
                roster_rows = roster;
                if let Some(thread_id) = origin_thread_id {
                    let siblings = conn
                        .query(
                            "SELECT i.id, i.issue_number, i.thread_id, t.title,
                                m.status, e.provider, e.external_id, m.confidence,
                                e.metadata_json::text
                         FROM issues i
                         JOIN threads t ON t.id = i.thread_id AND t.user_id = $2
                         LEFT JOIN issue_external_identity_mappings m ON m.issue_id = i.id
                         LEFT JOIN external_identities e ON e.id = m.external_identity_id
                         WHERE i.thread_id = $1 AND i.id <> $3
                         ORDER BY i.position, i.id",
                            &[&thread_id, &user_id, &origin_issue_id],
                        )
                        .await
                        .map_err(db::query_error)?;
                    let rows: Vec<Value> = siblings
                        .iter()
                        .map(|row| {
                            let meta_text: Option<String> = row.get(8);
                            let metadata: Value = meta_text
                                .as_deref()
                                .and_then(|raw| serde_json::from_str(raw).ok())
                                .unwrap_or(Value::Null);
                            serde_json::json!({
                                "issue_id": row.get::<_, i32>(0),
                                "issue_number": row.get::<_, Option<String>>(1),
                                "title": metadata.get("name"),
                                "thread_id": row.get::<_, Option<i32>>(2),
                                "thread_title": row.get::<_, Option<String>>(3),
                                "current_mapping_status": row.get::<_, Option<String>>(4),
                                "provider": row.get::<_, Option<String>>(5),
                                "external_id": row.get::<_, Option<String>>(6),
                                "confidence": row.get::<_, Option<f64>>(7),
                                "_identity_metadata": metadata,
                            })
                        })
                        .collect();
                    issues_with_mappings.extend(build_sibling_mapping_rows(
                        &rows,
                        &roster_rows,
                        provider,
                    ));
                }
            }
        }
    } else {
        // A brand-new provider volume is a normal valid preview. Rebuild its
        // complete roster instead of turning every signed preview into a 409.
        let (provider_series, fetched_roster) =
            crate::comicvine_repair::catalog_volume_roster(provider_series_external_id).await?;
        series_info = Some(provider_series);
        issues_with_mappings = fetched_roster.clone();
        roster_rows = fetched_roster;
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
                "_identity_metadata": origin.try_get::<_, Option<Value>>(9).ok().flatten(),
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
    attach_verified_roster_metadata(&mut classified, &roster_rows);
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

fn series_info_from_meta(external_id: &str, meta: &Value, external_url: Option<&str>) -> Value {
    serde_json::json!({
        "id": external_id,
        "name": meta.get("name"),
        "publisher": meta.get("publisher").and_then(|p| if p.is_object() { p.get("name").cloned() } else { Some(p.clone()) }),
        "start_year": meta.get("start_year"),
        "count_of_issues": meta.get("count_of_issues"),
        "site_detail_url": external_url,
        "image": meta.get("image"),
    })
}

// Mirror Python catalog.py's stable preview classification and dedupe rules.
fn normalize_issue_number(value: &str) -> String {
    let stripped = value.trim().strip_suffix('.').unwrap_or(value.trim());
    if !stripped.is_empty() && stripped.bytes().all(|b| b.is_ascii_digit()) {
        return stripped.to_string();
    }
    let groups: Vec<&str> = stripped.split(',').collect();
    if groups.len() > 1
        && (1..=3).contains(&groups[0].len())
        && groups[0].bytes().all(|b| b.is_ascii_digit())
        && groups[1..]
            .iter()
            .all(|g| g.len() == 3 && g.bytes().all(|b| b.is_ascii_digit()))
    {
        return groups.join("");
    }
    String::new()
}

fn is_special_issue(issue_number: &str) -> bool {
    let stripped = issue_number.trim().to_lowercase();
    if stripped.is_empty() {
        return true;
    }
    if stripped.chars().all(|c| matches!(c, 'i' | 'v' | 'x')) {
        return false;
    }
    let words = [
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
    let tokens: Vec<&str> = stripped
        .split(|c: char| !c.is_alphabetic())
        .filter(|x| !x.is_empty())
        .collect();
    if words.iter().any(|w| {
        if w.contains(' ') {
            stripped.contains(w)
        } else {
            tokens.contains(w)
        }
    }) {
        return true;
    }
    if !stripped.bytes().any(|c| c.is_ascii_digit()) {
        return true;
    }
    // Python treats a nonnumeric trailing decimal suffix as special.
    stripped
        .rsplit_once('.')
        .is_some_and(|(_, tail)| !tail.is_empty() && !tail.bytes().any(|c| c.is_ascii_digit()))
}

fn is_ambiguous_issue(issue_number: &str) -> bool {
    normalize_issue_number(issue_number).is_empty()
}

fn row_precedence_key(row: &Value) -> (u8, u8, u8, String, String) {
    let status = row
        .get("current_mapping_status")
        .and_then(Value::as_str)
        .unwrap_or("");
    let rank = match status {
        "confirmed" => 0,
        "candidate" => 1,
        "unresolved" => 2,
        "rejected" => 3,
        _ => 4,
    };
    (
        u8::from(row.get("thread_id").is_none_or(Value::is_null)),
        u8::from(row.get("_sibling_roster").and_then(Value::as_str) != Some("unique")),
        rank,
        row.get("external_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_owned(),
        row.get("issue_number")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_owned(),
    )
}

fn dedupe_rows_by_issue(issues: &[Value]) -> Vec<Value> {
    let mut unique: HashMap<i64, Value> = HashMap::new();
    for row in issues {
        let Some(issue_id) = row.get("issue_id").and_then(Value::as_i64) else {
            continue;
        };
        unique
            .entry(issue_id)
            .and_modify(|old| {
                if row_precedence_key(row) < row_precedence_key(old) {
                    *old = row.clone();
                }
            })
            .or_insert_with(|| row.clone());
    }
    let mut rows: Vec<(i64, Value)> = unique.into_iter().collect();
    rows.sort_by_key(|(id, _)| *id);
    rows.into_iter().map(|(_, row)| row).collect()
}

fn build_sibling_mapping_rows(siblings: &[Value], roster: &[Value], provider: &str) -> Vec<Value> {
    let mut by_number: HashMap<String, Vec<&Value>> = HashMap::new();
    for entry in roster {
        let number = entry
            .get("issue_number")
            .and_then(Value::as_str)
            .unwrap_or("");
        let key = normalize_issue_number(number);
        if !key.is_empty() {
            by_number.entry(key).or_default().push(entry);
        }
    }
    let mut result = Vec::new();
    for issue in siblings {
        let number = issue
            .get("issue_number")
            .and_then(Value::as_str)
            .unwrap_or("");
        if number.is_empty() {
            continue;
        }
        // Confirmed sibling evidence cannot be overwritten by a new volume
        // proposal, even if the provider roster has another issue number.
        if issue.get("current_mapping_status").and_then(Value::as_str) == Some("confirmed") {
            result.push(issue.clone());
            continue;
        }
        let key = normalize_issue_number(number);
        let matching = by_number.get(&key);
        let mut row = issue.clone();
        let state = match matching.map_or(0, Vec::len) {
            1 => {
                if let Some(matched) = matching.and_then(|m| m.first()) {
                    if let Some(obj) = row.as_object_mut() {
                        obj.insert("provider".to_owned(), serde_json::json!(provider));
                        obj.insert(
                            "external_id".to_owned(),
                            matched.get("external_id").cloned().unwrap_or(Value::Null),
                        );
                        let old_title = obj.get("title").cloned().unwrap_or(Value::Null);
                        obj.insert(
                            "title".to_owned(),
                            matched
                                .get("title")
                                .filter(|v| !v.is_null())
                                .cloned()
                                .unwrap_or(old_title),
                        );
                        obj.insert(
                            "confidence".to_owned(),
                            matched.get("confidence").cloned().unwrap_or(Value::Null),
                        );
                    }
                }
                "unique"
            }
            n if n > 1 => "duplicate",
            _ => "none",
        };
        if let Some(obj) = row.as_object_mut() {
            obj.insert("_sibling_roster".to_owned(), serde_json::json!(state));
        }
        result.push(row);
    }
    result
}

fn classify_rows(
    issues: &[Value],
    provider: &str,
    origin_issue_number: &str,
    counts: &mut Value,
) -> Vec<Value> {
    let candidates = dedupe_rows_by_issue(issues);
    let mut normalized_counts: HashMap<String, usize> = HashMap::new();
    for row in &candidates {
        if row.get("_is_origin").and_then(Value::as_bool) == Some(true) {
            continue;
        }
        let number = row
            .get("issue_number")
            .and_then(Value::as_str)
            .unwrap_or("");
        if !is_special_issue(number) && !is_ambiguous_issue(number) {
            let normalized = normalize_issue_number(number);
            if !normalized.is_empty() {
                *normalized_counts.entry(normalized).or_default() += 1;
            }
        }
    }

    let mut out = Vec::with_capacity(candidates.len());
    for mut row in candidates {
        let number = row
            .get("issue_number")
            .and_then(Value::as_str)
            .unwrap_or("");
        let status = row.get("current_mapping_status").and_then(Value::as_str);
        let conflicting = status == Some("confirmed")
            && row.get("provider").and_then(Value::as_str) != Some(provider);
        let normalized = normalize_issue_number(number);
        let origin_normalized = normalize_issue_number(origin_issue_number);
        let classification = if is_special_issue(number) {
            "excluded_special"
        } else if conflicting {
            "needs_review_conflict"
        } else if is_ambiguous_issue(number) {
            "needs_review_ambiguous"
        } else if status == Some("confirmed") {
            "already_confirmed"
        } else if !normalized.is_empty() && normalized == origin_normalized {
            if normalized_counts.get(&normalized) == Some(&1) {
                "safe_exact_match"
            } else {
                "needs_review_ambiguous"
            }
        } else {
            match row.get("_sibling_roster").and_then(Value::as_str) {
                Some("unique") => "safe_exact_match",
                Some("duplicate") => "needs_review_ambiguous",
                _ => "unresolved",
            }
        };
        let id = row
            .get("issue_id")
            .and_then(Value::as_i64)
            .unwrap_or_default();
        let roster_only = row
            .get("_roster_only")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let prefix = if roster_only { "roster:" } else { "issue:" };
        let proposed = matches!(classification, "safe_exact_match" | "already_confirmed");
        if let Some(c) = counts.get(classification).and_then(Value::as_i64) {
            counts[classification] = serde_json::json!(c + 1);
        }
        if let Some(map) = row.as_object_mut() {
            map.insert(
                "row_id".to_owned(),
                serde_json::json!(format!("{prefix}{id}")),
            );
            map.insert(
                "classification".to_owned(),
                serde_json::json!(classification),
            );
            map.insert("proposed_mapping".to_owned(), serde_json::json!(proposed));
            map.insert(
                "default_selected".to_owned(),
                serde_json::json!(classification == "safe_exact_match"),
            );
        }
        out.push(row);
    }
    out
}

fn attach_verified_roster_metadata(rows: &mut [Value], roster: &[Value]) {
    let mut by_number: HashMap<String, Vec<&Value>> = HashMap::new();
    for record in roster {
        let number = record
            .get("issue_number")
            .and_then(Value::as_str)
            .unwrap_or("");
        by_number
            .entry(normalize_issue_number(number))
            .or_default()
            .push(record);
    }
    for row in rows {
        if row.get("thread_id").and_then(Value::as_i64).is_none() {
            continue;
        }
        let class = row.get("classification").and_then(Value::as_str);
        if !matches!(class, Some("safe_exact_match" | "already_confirmed")) {
            continue;
        }
        let already_confirmed = class == Some("already_confirmed");
        let number = row
            .get("issue_number")
            .and_then(Value::as_str)
            .unwrap_or("");
        let normalized = normalize_issue_number(number);
        let Some(matches) = by_number.get(&normalized) else {
            continue;
        };
        if matches.len() != 1
            || matches[0].get("external_id").and_then(Value::as_str)
                != row.get("external_id").and_then(Value::as_str)
        {
            continue;
        }
        let raw = matches[0].get("_provider_metadata");
        let old_title = row.get("title").cloned().unwrap_or(Value::Null);
        let title = if old_title.is_null() {
            raw.and_then(|v| v.get("name"))
                .cloned()
                .unwrap_or(Value::Null)
        } else {
            old_title
        };
        let metadata = row
            .get("_identity_metadata")
            .cloned()
            .unwrap_or(Value::Null);
        let volume_name = metadata
            .get("volume")
            .and_then(|v| v.get("name"))
            .or_else(|| metadata.get("volume_name"))
            .and_then(Value::as_str)
            .filter(|v| !v.is_empty());
        let incomplete = metadata
            .get("issue_number")
            .is_none_or(|v| v.is_null() || v.as_str().is_some_and(str::is_empty))
            || volume_name.is_none();
        if let Some(obj) = row.as_object_mut() {
            obj.insert("_roster_verified".to_owned(), serde_json::json!(true));
            obj.insert("title".to_owned(), title);
            if let Some(raw) = raw.filter(|value| value.is_object()) {
                obj.insert(
                    "_provider_metadata".to_owned(),
                    crate::comicvine_repair::normalize_roster_issue_metadata(raw),
                );
            }
            if already_confirmed && incomplete {
                obj.insert(
                    "metadata_refresh_required".to_owned(),
                    serde_json::json!(raw.is_some()),
                );
                obj.insert(
                    "default_selected".to_owned(),
                    serde_json::json!(raw.is_some()),
                );
            }
        }
    }
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
    conn: &tokio_postgres::Client,
    user_id: i32,
    origin_issue_id: i32,
    provider: &str,
    provider_series_external_id: &str,
    origin_thread_id: Option<i32>,
    _origin_issue_number: &str,
    origin: &tokio_postgres::Row,
    _series_info: Option<Value>,
) -> Result<Value, ApiError> {
    let Some(thread_id) = origin_thread_id else {
        return Ok(unavailable_plan(
            origin_issue_id,
            "origin_issue_without_thread",
            "queue_thread_bootstrap",
        ));
    };
    // The Queue preview relies on an actual, complete provider roster to
    // prove cardinality. Do not replace that evidence with local guesses.
    let (series_info, roster) =
        crate::comicvine_repair::catalog_volume_roster(provider_series_external_id).await?;
    if roster.is_empty() {
        return Ok(unavailable_plan(
            origin_issue_id,
            "provider_roster_unavailable",
            "queue_thread_bootstrap",
        ));
    }
    let thread_title: String = origin
        .try_get::<_, Option<String>>(4)
        .map_err(db::query_error)?
        .unwrap_or_default();
    let volume_title = series_info
        .get("name")
        .and_then(Value::as_str)
        .unwrap_or("");
    if !volume_identity_matches(&thread_title, volume_title) {
        return Ok(unavailable_plan(
            origin_issue_id,
            "queue_thread_bootstrap_volume_identity_mismatch",
            "queue_thread_bootstrap",
        ));
    }
    let db_rows = conn
        .query(
            "SELECT i.id, i.issue_number, i.thread_id, t.title, m.status,
                e.provider, e.external_id, m.confidence, e.metadata_json::text
         FROM issues i
         JOIN threads t ON t.id = i.thread_id AND t.user_id = $2
         LEFT JOIN issue_external_identity_mappings m ON m.issue_id = i.id
         LEFT JOIN external_identities e ON e.id = m.external_identity_id
         WHERE i.thread_id = $1
         ORDER BY i.position, i.id",
            &[&thread_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    let local: Vec<Value> = db_rows
        .iter()
        .map(|r| {
            let meta_string: Option<String> = r.get(8);
            let meta: Value = meta_string
                .as_deref()
                .and_then(|raw| serde_json::from_str(raw).ok())
                .unwrap_or(Value::Null);
            serde_json::json!({
                "issue_id": r.get::<_, i32>(0),
                "issue_number": r.get::<_, Option<String>>(1),
                "title": meta.get("name"),
                "thread_id": r.get::<_, Option<i32>>(2),
                "thread_title": r.get::<_, Option<String>>(3),
                "current_mapping_status": r.get::<_, Option<String>>(4),
                "provider": r.get::<_, Option<String>>(5),
                "external_id": r.get::<_, Option<String>>(6),
                "confidence": r.get::<_, Option<f64>>(7),
                "_identity_metadata": meta,
            })
        })
        .collect();
    if local.is_empty() {
        return Ok(unavailable_plan(
            origin_issue_id,
            "thread_has_no_issues",
            "queue_thread_bootstrap",
        ));
    }
    let mut counts = empty_counts();
    let mut classified = classify_queue_bootstrap_rows(
        &dedupe_rows_by_issue(&local),
        &roster,
        provider,
        &mut counts,
    );
    attach_verified_roster_metadata(&mut classified, &roster);
    let scope_key = derive_scope_key(&classified, origin_issue_id);
    let basis = if scope_key.is_some() {
        "queue_thread_bootstrap_exact_match"
    } else {
        "queue_thread_bootstrap_no_exact_match"
    };
    let status = if scope_key.is_some() {
        "available"
    } else {
        "unavailable"
    };
    if scope_key.is_none() {
        counts = empty_counts();
        classified.clear();
    }
    let issue_numbers: Vec<String> = classified
        .iter()
        .filter_map(|r| {
            r.get("issue_number")
                .and_then(Value::as_str)
                .map(str::to_owned)
        })
        .filter(|s| !s.is_empty())
        .collect();
    let digest = plan_state_digest(
        provider,
        provider_series_external_id,
        origin_issue_id,
        scope_key.as_deref(),
        basis,
        &classified,
        "queue_thread_bootstrap",
    );
    Ok(serde_json::json!({
        "scope": {
            "status": status,
            "scope_key": scope_key,
            "origin_issue_id": origin_issue_id,
            "series_label": series_info.get("name"),
            "basis": basis,
        },
        "provider_series": series_info,
        "counts": counts,
        "rows": classified,
        "scope_key": scope_key,
        "issue_numbers": issue_numbers,
        "state_digest": digest,
    }))
}

fn normalize_volume_title(value: &str) -> (String, Option<String>) {
    // Python treats suffixes like "(1940)" and "(2011-2016)" as edition
    // evidence, preserving explicit disagreements between launch years.
    let suffix = regex::Regex::new(r"\s*\((\d{4})(?:-\d{4})?\)\s*$").ok();
    let launch = suffix
        .as_ref()
        .and_then(|regex| regex.captures(value))
        .and_then(|caps| caps.get(1).map(|m| m.as_str().to_string()));
    let stripped = suffix
        .as_ref()
        .map(|r| r.replace(value, ""))
        .map(|text| text.to_string())
        .unwrap_or_else(|| value.to_string());
    (
        stripped
            .case_fold()
            .collect::<String>()
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" "),
        launch,
    )
}

fn volume_identity_matches(thread_title: &str, volume_title: &str) -> bool {
    let (thread, thread_year) = normalize_volume_title(thread_title);
    let (volume, volume_year) = normalize_volume_title(volume_title);
    if thread.is_empty() || volume.is_empty() || thread != volume {
        return false;
    }
    !matches!((thread_year, volume_year), (Some(a), Some(b)) if a != b)
}

fn classify_queue_bootstrap_rows(
    local_rows: &[Value],
    roster: &[Value],
    provider: &str,
    counts: &mut Value,
) -> Vec<Value> {
    let mut by_number: HashMap<String, Vec<&Value>> = HashMap::new();
    for item in roster {
        let number = item
            .get("issue_number")
            .and_then(Value::as_str)
            .unwrap_or("");
        let normalized = normalize_issue_number(number);
        if !normalized.is_empty() {
            by_number.entry(normalized).or_default().push(item);
        }
    }
    let mut local_number_counts: HashMap<String, usize> = HashMap::new();
    for item in local_rows {
        let number = item
            .get("issue_number")
            .and_then(Value::as_str)
            .unwrap_or("");
        if is_special_issue(number) || is_ambiguous_issue(number) {
            continue;
        }
        let normalized = normalize_issue_number(number);
        if !normalized.is_empty() {
            *local_number_counts.entry(normalized).or_default() += 1;
        }
    }
    let confirmed_external_ids: HashSet<String> = local_rows
        .iter()
        .filter_map(|row| {
            if row.get("current_mapping_status").and_then(Value::as_str) == Some("confirmed") {
                row.get("external_id")
                    .and_then(Value::as_str)
                    .map(str::to_owned)
            } else {
                None
            }
        })
        .collect();
    let mut consumed_ids: HashSet<String> = HashSet::new();
    let mut out = Vec::new();
    for info in local_rows {
        let mut row = info.clone();
        let number = row
            .get("issue_number")
            .and_then(Value::as_str)
            .unwrap_or("");
        let normalized = normalize_issue_number(number);
        let matches = by_number.get(&normalized);
        let match_count = matches.map_or(0, Vec::len);
        let mapping_status = row.get("current_mapping_status").and_then(Value::as_str);
        let mapping_provider = row.get("provider").and_then(Value::as_str);
        let classification = if is_special_issue(number) {
            "excluded_special"
        } else if mapping_status == Some("confirmed") && mapping_provider != Some(provider) {
            "needs_review_conflict"
        } else if is_ambiguous_issue(number) {
            "needs_review_ambiguous"
        } else if mapping_status == Some("confirmed") {
            if match_count == 0 {
                "unresolved"
            } else if match_count > 1 {
                "needs_review_ambiguous"
            } else if matches
                .and_then(|v| v.first())
                .and_then(|r| r.get("external_id"))
                .and_then(Value::as_str)
                != row.get("external_id").and_then(Value::as_str)
            {
                "needs_review_conflict"
            } else {
                "already_confirmed"
            }
        } else if !normalized.is_empty()
            && local_number_counts.get(&normalized) == Some(&1)
            && match_count == 1
        {
            let match_row = matches.and_then(|v| v.first());
            if let Some(match_row) = match_row {
                if let Some(external_id) = match_row.get("external_id").and_then(Value::as_str) {
                    consumed_ids.insert(external_id.to_owned());
                }
                if let Some(object) = row.as_object_mut() {
                    object.insert("provider".to_owned(), serde_json::json!(provider));
                    object.insert(
                        "external_id".to_owned(),
                        match_row.get("external_id").cloned().unwrap_or(Value::Null),
                    );
                    let old_title = object.get("title").cloned().unwrap_or(Value::Null);
                    object.insert(
                        "title".to_owned(),
                        match_row
                            .get("title")
                            .filter(|t| !t.is_null())
                            .cloned()
                            .unwrap_or(old_title),
                    );
                    object.insert(
                        "confidence".to_owned(),
                        match_row.get("confidence").cloned().unwrap_or(Value::Null),
                    );
                }
            }
            "safe_exact_match"
        } else if !normalized.is_empty()
            && (local_number_counts.get(&normalized).is_some_and(|v| *v > 1) || match_count > 1)
        {
            "needs_review_ambiguous"
        } else {
            "unresolved"
        };
        if let Some(c) = counts.get(classification).and_then(Value::as_i64) {
            counts[classification] = serde_json::json!(c + 1);
        }
        let id = row
            .get("issue_id")
            .and_then(Value::as_i64)
            .unwrap_or_default();
        if let Some(obj) = row.as_object_mut() {
            obj.insert(
                "row_id".to_owned(),
                serde_json::json!(format!("issue:{id}")),
            );
            obj.insert(
                "classification".to_owned(),
                serde_json::json!(classification),
            );
            obj.insert(
                "proposed_mapping".to_owned(),
                serde_json::json!(matches!(
                    classification,
                    "safe_exact_match" | "already_confirmed"
                )),
            );
            obj.insert(
                "default_selected".to_owned(),
                serde_json::json!(classification == "safe_exact_match"),
            );
        }
        out.push(row);
    }
    for item in roster {
        let eid = item
            .get("external_id")
            .and_then(Value::as_str)
            .unwrap_or("");
        if consumed_ids.contains(eid) || confirmed_external_ids.contains(eid) {
            continue;
        }
        let mut row = item.clone();
        if let Some(c) = counts.get("unresolved").and_then(Value::as_i64) {
            counts["unresolved"] = serde_json::json!(c + 1);
        }
        let id = row
            .get("issue_id")
            .and_then(Value::as_i64)
            .unwrap_or_default();
        if let Some(obj) = row.as_object_mut() {
            obj.insert("_roster_only".to_owned(), serde_json::json!(true));
            obj.insert(
                "row_id".to_owned(),
                serde_json::json!(format!("roster:{id}")),
            );
            obj.insert("classification".to_owned(), serde_json::json!("unresolved"));
            obj.insert("proposed_mapping".to_owned(), serde_json::json!(false));
            obj.insert("default_selected".to_owned(), serde_json::json!(false));
        }
        out.push(row);
    }
    out
}

/// A concurrent identical request may have inserted the receipt after our
/// initial lookup and preview revalidation. The losing transaction must fully
/// roll back before reading the winning receipt on this connection.
#[allow(clippy::too_many_arguments)]
async fn persist_commit_or_replay(
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
    match persist_commit_series_mapping_handler(
        conn,
        user_id,
        approved_rows,
        provider,
        series_external_id,
        idempotency_key,
        request_fingerprint,
        all_rows,
        series_metadata,
    )
    .await
    {
        Ok(response) => Ok(response),
        Err(ApiError::Conflict(code)) if code == ERROR_IDEMPOTENCY_CONFLICT => {
            replay_receipt(conn, user_id, idempotency_key, request_fingerprint)
                .await?
                .ok_or_else(|| conflict(ERROR_IDEMPOTENCY_CONFLICT))
        }
        Err(err) => Err(err),
    }
}

fn fill_missing_metadata(existing: Option<&Value>, incoming: Option<&Value>) -> Value {
    let Some(incoming) = incoming.and_then(Value::as_object) else {
        return existing.cloned().unwrap_or_else(|| serde_json::json!({}));
    };
    let mut merged = incoming.clone();
    if let Some(previous) = existing.and_then(Value::as_object) {
        for (key, value) in previous {
            if !value.is_null() && value != "" {
                merged.insert(key.clone(), value.clone());
            }
        }
        for key in ["volume", "publisher", "image"] {
            if let (Some(Value::Object(old)), Some(Value::Object(new))) =
                (previous.get(key), incoming.get(key))
            {
                if old.get("id").is_some_and(|id| !id.is_null())
                    && new.get("id").is_some_and(|id| !id.is_null())
                    && old.get("id") != new.get("id")
                {
                    merged.insert(key.to_owned(), Value::Object(new.clone()));
                } else {
                    let mut reference = new.clone();
                    for (field, value) in old {
                        if !value.is_null() && value != "" {
                            reference.insert(field.clone(), value.clone());
                        }
                    }
                    merged.insert(key.to_owned(), Value::Object(reference));
                }
            }
        }
    }
    Value::Object(merged)
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
    let mut providers = vec![provider.to_owned()];
    let mut external_ids = vec![series_external_id.to_owned()];
    for row in approved_rows {
        if let Some(value) = row.get("provider").and_then(Value::as_str) {
            providers.push(value.to_owned());
        }
        if let Some(value) = row.get("external_id").and_then(Value::as_str) {
            external_ids.push(value.to_owned());
        }
    }
    providers.sort();
    providers.dedup();
    external_ids.sort();
    external_ids.dedup();
    let existing = tx
        .query(
            "SELECT provider, entity_type, external_id, metadata_json FROM external_identities
         WHERE provider = ANY($1) AND external_id = ANY($2)
         ORDER BY provider, entity_type, external_id FOR UPDATE",
            &[&providers, &external_ids],
        )
        .await
        .map_err(db::query_error)?;
    let existing_metadata: HashMap<(String, String, String), Value> = existing
        .into_iter()
        .map(|row| ((row.get(0), row.get(1), row.get(2)), row.get(3)))
        .collect();

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
        let previous = existing_metadata.get(&(
            row_provider.to_owned(),
            "issue".to_owned(),
            row_eid.to_owned(),
        ));
        let metadata_known = previous.is_some();
        let issue_meta_json = fill_missing_metadata(previous, row.get("_provider_metadata"));
        // upsert external identity
        let identity = tx
            .query_one(
                "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, created_at, updated_at)
                 VALUES ($1, 'issue', $2, $3, NOW(), NOW())
                 ON CONFLICT (provider, entity_type, external_id) DO UPDATE SET
                   metadata_json = CASE
                     WHEN $4::boolean OR COALESCE(external_identities.metadata_json::jsonb, '{}'::jsonb) = '{}'::jsonb
                       THEN EXCLUDED.metadata_json
                     ELSE external_identities.metadata_json
                   END,
                   updated_at = NOW()
                 RETURNING id, metadata_json",
                &[&row_provider, &row_eid, &issue_meta_json, &metadata_known],
            )
            .await
            .map_err(db::query_error)?;
        let identity_id: i32 = identity.get(0);
        if !metadata_known
            && row
                .get("_provider_metadata")
                .and_then(Value::as_object)
                .is_some()
        {
            // A concurrent insert can win after the batched read. ON CONFLICT
            // locks that row; enrich its latest metadata while the lock is held.
            let persisted: Value = identity.get(1);
            let enriched = fill_missing_metadata(Some(&persisted), row.get("_provider_metadata"));
            if enriched != persisted {
                tx.execute(
                    "UPDATE external_identities SET metadata_json = $2, updated_at = NOW()
                     WHERE id = $1",
                    &[&identity_id, &enriched],
                )
                .await
                .map_err(db::query_error)?;
            }
        }
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
    let previous_series = existing_metadata.get(&(
        provider.to_owned(),
        "series".to_owned(),
        series_external_id.to_owned(),
    ));
    let series_metadata_known = previous_series.is_some();
    let series_meta_json = fill_missing_metadata(previous_series, series_metadata);
    let series_identity = tx
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, created_at, updated_at)
             VALUES ($1, 'series', $2, $3, NOW(), NOW())
             ON CONFLICT (provider, entity_type, external_id) DO UPDATE SET
               metadata_json = CASE
                 WHEN $4::boolean OR COALESCE(external_identities.metadata_json::jsonb, '{}'::jsonb) = '{}'::jsonb
                   THEN EXCLUDED.metadata_json
                 ELSE external_identities.metadata_json
               END,
               updated_at = NOW()
             RETURNING id, metadata_json",
            &[&provider, &series_external_id, &series_meta_json, &series_metadata_known],
        )
        .await
        .map_err(db::query_error)?;
    let series_identity_id: i32 = series_identity.get(0);
    if !series_metadata_known && series_metadata.and_then(Value::as_object).is_some() {
        let persisted: Value = series_identity.get(1);
        let enriched = fill_missing_metadata(Some(&persisted), series_metadata);
        if enriched != persisted {
            tx.execute(
                "UPDATE external_identities SET metadata_json = $2, updated_at = NOW()
                 WHERE id = $1",
                &[&series_identity_id, &enriched],
            )
            .await
            .map_err(db::query_error)?;
        }
    }
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
    let response_json = serde_json::to_value(&response)
        .map_err(|_| ApiError::Internal("serialization failed".to_string()))?;

    if let Err(err) = tx
        .execute(
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
    {
        if err.code() == Some(&tokio_postgres::error::SqlState::UNIQUE_VIOLATION) {
            // PostgreSQL has aborted this transaction. Explicitly roll it
            // back before the caller can safely query the winning receipt.
            tx.rollback().await.map_err(db::query_error)?;
            return Err(conflict(ERROR_IDEMPOTENCY_CONFLICT));
        }
        return Err(db::query_error(err));
    }

    tx.commit().await.map_err(db::query_error)?;
    Ok(response)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn queue_bootstrap_requires_volume_identity_and_unique_roster_numbers() {
        assert!(volume_identity_matches("Batman", "Batman (1940)"));
        assert!(volume_identity_matches("STRASSE", "Straße"));
        assert!(volume_identity_matches(
            "Batman (2011-2016)",
            "Batman (2011)"
        ));
        assert!(!volume_identity_matches("Batman (2011)", "Batman (1940)"));
        assert!(!volume_identity_matches("Green Lantern", "Batman (1940)"));
        assert!(!volume_identity_matches("", "Batman"));

        let local = vec![
            serde_json::json!({"issue_id":1, "issue_number":"1", "thread_id":7, "thread_title":"Batman",
                "current_mapping_status":null, "provider":null, "external_id":null}),
            serde_json::json!({"issue_id":2, "issue_number":"2", "thread_id":7, "thread_title":"Batman",
                "current_mapping_status":null, "provider":null, "external_id":null}),
            serde_json::json!({"issue_id":3, "issue_number":"2", "thread_id":7, "thread_title":"Batman",
                "current_mapping_status":null, "provider":null, "external_id":null}),
            serde_json::json!({"issue_id":4, "issue_number":"Annual 1", "thread_id":7, "thread_title":"Batman",
                "current_mapping_status":null, "provider":null, "external_id":null}),
        ];
        let roster = vec![
            serde_json::json!({"issue_id":3001,"issue_number":"1","external_id":"3001",
                "provider":"comicvine","thread_id":null,"_roster_only":true}),
            serde_json::json!({"issue_id":3002,"issue_number":"2","external_id":"3002",
                "provider":"comicvine","thread_id":null,"_roster_only":true}),
            serde_json::json!({"issue_id":3003,"issue_number":"3","external_id":"3003",
                "provider":"comicvine","thread_id":null,"_roster_only":true}),
        ];
        let mut counts = empty_counts();
        let plan = classify_queue_bootstrap_rows(&local, &roster, "comicvine", &mut counts);
        assert_eq!(plan[0]["row_id"], "issue:1");
        assert_eq!(plan[0]["classification"], "safe_exact_match");
        assert_eq!(plan[0]["external_id"], "3001");
        assert_eq!(plan[1]["classification"], "needs_review_ambiguous");
        assert_eq!(plan[2]["classification"], "needs_review_ambiguous");
        assert_eq!(plan[3]["classification"], "excluded_special");
        assert_eq!(plan[4]["row_id"], "roster:3002");
        assert_eq!(plan[5]["row_id"], "roster:3003");
        assert_eq!(counts["safe_exact_match"], 1);
        assert_eq!(counts["needs_review_ambiguous"], 2);
        assert_eq!(counts["excluded_special"], 1);
        assert_eq!(counts["unresolved"], 2);
        assert_eq!(derive_scope_key(&plan, 1).as_deref(), Some("exact:1:1"));
    }

    #[test]
    fn fresh_provider_roster_uses_roster_ids_not_comicpile_issue_ids() {
        let roster = vec![
            serde_json::json!({"issue_id":4001,"issue_number":"1","thread_id":null,
                "_roster_only":true,"provider":"comicvine","external_id":"4001"}),
            serde_json::json!({"issue_id":4002,"issue_number":"1","thread_id":null,
                "_roster_only":true,"provider":"comicvine","external_id":"4002"}),
            serde_json::json!({"issue_id":4003,"issue_number":"2","thread_id":null,
                "_roster_only":true,"provider":"comicvine","external_id":"4003"}),
        ];
        let mut counts = empty_counts();
        let rows = classify_rows(&roster, "comicvine", "1", &mut counts);
        assert_eq!(rows[0]["row_id"], "roster:4001");
        assert_eq!(rows[0]["classification"], "needs_review_ambiguous");
        assert_eq!(rows[1]["classification"], "needs_review_ambiguous");
        assert_eq!(rows[2]["classification"], "unresolved");
        assert!(derive_scope_key(&rows, 12).is_none());

        let mut counts = empty_counts();
        let rows = classify_rows(&roster, "comicvine", "2", &mut counts);
        assert_eq!(rows[2]["classification"], "safe_exact_match");
        assert_eq!(derive_scope_key(&rows, 12).as_deref(), Some("exact:12:2"));
    }

    #[tokio::test]
    async fn persist_commit_writes_identity_mappings_and_receipt() {
        let state = crate::test_support::test_state(1)
            .await
            .expect("disposable PostgreSQL required");
        let _db = crate::test_support::reset_for_test(&state).await;
        let mut connection = state.pool.get().await.expect("database connection");
        connection
            .batch_execute(
                r#"INSERT INTO users (id, username, created_at, is_admin)
                 VALUES (1, 'catalog-commit-test', now(), false);
                 INSERT INTO threads
                     (id, user_id, title, format, issues_remaining, queue_position, status,
                      total_issues, created_at, is_blocked, is_test, manual_creator_credits,
                      queue_position_is_manual)
                 VALUES (10, 1, 'Test Series', 'Comic', 1, 1, 'active', 1, now(), false, false,
                         '[]', false);
                 INSERT INTO issues
                     (id, thread_id, issue_number, status, created_at, position)
                 VALUES (100, 10, '1', 'unread', now(), 1);
                 INSERT INTO external_identities
                     (provider, entity_type, external_id, external_url, metadata_json,
                      created_at, updated_at)
                 VALUES ('comicvine', 'series', 'series-10',
                         'https://comicvine.example/series-10',
                         '{"name":"Trusted Series","publisher":{"id":9,"name":""}}'::jsonb,
                         now(), now());"#,
            )
            .await
            .expect("seed catalog commit schema");

        let mut approved_rows = vec![serde_json::json!({
            "issue_id": 100,
            "issue_number": "1",
            "thread_id": 10,
            "provider": "comicvine",
            "external_id": "issue-100",
            "classification": "safe_exact_match",
            "row_id": "issue:100"
        })];
        let roster = vec![serde_json::json!({
            "issue_number":"1", "external_id":"issue-100",
            "_provider_metadata": {"name":"Issue One","issue_number":"1",
                "volume":{"id":10,"name":"Test Series","unused":"raw-only"},
                "image":{"original_url":"https://comicvine.example/cover.jpg"},
                "person_credits":[{"id":7,"name":"Writer","role":"writer"}]}
        })];
        attach_verified_roster_metadata(&mut approved_rows, &roster);
        let response = persist_commit_series_mapping_handler(
            &mut connection,
            1,
            &approved_rows,
            "comicvine",
            "series-10",
            "catalog-commit-test-key",
            "catalog-commit-test-fingerprint",
            &approved_rows,
            Some(&serde_json::json!({"name": "Test Series",
                "publisher":{"id":9,"name":"Publisher"}})),
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
        let issue_metadata: Value = connection
            .query_one(
                "SELECT metadata_json FROM external_identities
             WHERE entity_type = 'issue' AND external_id = 'issue-100'",
                &[],
            )
            .await
            .expect("issue identity metadata")
            .get(0);
        assert_eq!(issue_metadata["name"], "Issue One");
        assert_eq!(issue_metadata["volume"]["name"], "Test Series");
        assert!(issue_metadata["volume"].get("unused").is_none());
        assert_eq!(
            issue_metadata["primary_image"],
            "https://comicvine.example/cover.jpg"
        );
        assert_eq!(issue_metadata["creator_credits"][0]["role"], "writer");
        assert_eq!(
            issue_metadata["raw_provider_payload"]["volume"]["unused"],
            "raw-only"
        );
        let series_metadata: Value = connection
            .query_one(
                "SELECT metadata_json FROM external_identities
             WHERE entity_type = 'series' AND external_id = 'series-10'",
                &[],
            )
            .await
            .expect("series identity metadata")
            .get(0);
        assert_eq!(series_metadata["name"], "Trusted Series");
        assert_eq!(series_metadata["publisher"]["name"], "Publisher");
        connection
            .batch_execute(
                "INSERT INTO external_identities
               (provider, entity_type, external_id, metadata_json, created_at, updated_at)
             VALUES ('comicvine', 'issue', 'candidate-100', '{}'::json, now(), now());
             INSERT INTO issue_external_identity_mappings
               (issue_id, external_identity_id, status, evidence_source, confidence,
                created_at, updated_at, evidence_json)
             SELECT 100, id, 'candidate', 'test', 0.5, now(), now(), '{}'::json
             FROM external_identities WHERE external_id = 'candidate-100';",
            )
            .await
            .expect("seed second valid mapping for origin issue");
        let plan = build_plan_db(
            &connection,
            1,
            100,
            "comicvine",
            "series-10",
            "confirmed_origin",
        )
        .await
        .expect("rebuild local series plan");
        assert_eq!(
            plan["provider_series"]["site_detail_url"],
            "https://comicvine.example/series-10"
        );

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

        // A second writer with an identical key reaches the receipt unique
        // constraint after provisional identity writes. Roll back and replay
        // the committed response instead of surfacing a spurious 409.
        let replayed = persist_commit_or_replay(
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
        .expect("identical receipt must replay after rollback");
        assert_eq!(
            serde_json::to_value(&response).expect("original response JSON"),
            serde_json::to_value(&replayed).expect("replayed response JSON"),
        );

        // Reusing the key with a different request must remain a 409, and
        // must not change the winning receipt.
        let mismatch = persist_commit_or_replay(
            &mut connection,
            1,
            &approved_rows,
            "comicvine",
            "series-10",
            "catalog-commit-test-key",
            "different-request-fingerprint",
            &approved_rows,
            None,
        )
        .await;
        assert!(matches!(
            mismatch,
            Err(ApiError::Conflict(code)) if code == ERROR_IDEMPOTENCY_CONFLICT
        ));
        let stored_after = replay_receipt(
            &connection,
            1,
            "catalog-commit-test-key",
            "catalog-commit-test-fingerprint",
        )
        .await
        .expect("receipt lookup")
        .expect("winning receipt remains");
        assert_eq!(
            serde_json::to_value(&response).expect("original response JSON"),
            serde_json::to_value(&stored_after).expect("stored response JSON"),
        );
    }

    #[tokio::test]
    async fn concurrent_partial_commit_fills_missing_identity_metadata() {
        let state = crate::test_support::test_state(2)
            .await
            .expect("disposable PostgreSQL required");
        let _db = crate::test_support::reset_for_test(&state).await;
        let mut first = state.pool.get().await.expect("first connection");
        let mut second = state.pool.get().await.expect("second connection");
        first
            .batch_execute(
                "INSERT INTO users (id, username, created_at, is_admin)
             VALUES (1, 'catalog-concurrent-test', now(), false);
             INSERT INTO threads (id, user_id, title, format, issues_remaining,
               queue_position, status, total_issues, created_at, is_blocked,
               is_test, manual_creator_credits, queue_position_is_manual)
             VALUES (10, 1, 'Test Series', 'Comic', 1, 1, 'active', 1,
               now(), false, false, '[]', false);
             INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
             VALUES (100, 10, '1', 'unread', now(), 1);",
            )
            .await
            .expect("seed concurrent commit");
        let rich = vec![serde_json::json!({
            "issue_id":100, "thread_id":10, "provider":"comicvine",
            "external_id":"issue-100", "classification":"safe_exact_match",
            "row_id":"issue:100", "_provider_metadata":{"name":"Rich Issue","issue_number":"1"}
        })];
        let partial = vec![serde_json::json!({
            "issue_id":100, "thread_id":10, "provider":"comicvine",
            "external_id":"issue-100", "classification":"safe_exact_match",
            "row_id":"issue:100", "_provider_metadata":{"name":"Partial Issue"}
        })];
        let rich_series =
            serde_json::json!({"name":"Rich Series", "publisher":{"name":"Publisher"}});
        let partial_series = serde_json::json!({"name":"Partial Series"});
        let (rich_result, partial_result) = tokio::join!(
            persist_commit_series_mapping_handler(
                &mut first,
                1,
                &rich,
                "comicvine",
                "series-10",
                "rich-key",
                "rich-fp",
                &rich,
                Some(&rich_series),
            ),
            persist_commit_series_mapping_handler(
                &mut second,
                1,
                &partial,
                "comicvine",
                "series-10",
                "partial-key",
                "partial-fp",
                &partial,
                Some(&partial_series),
            ),
        );
        rich_result.expect("rich commit");
        partial_result.expect("partial concurrent commit");
        let sparse = vec![serde_json::json!({
            "issue_id":100, "thread_id":10, "provider":"comicvine",
            "external_id":"issue-100", "classification":"safe_exact_match", "row_id":"issue:100"
        })];
        persist_commit_series_mapping_handler(
            &mut second,
            1,
            &sparse,
            "comicvine",
            "series-10",
            "sparse-key",
            "sparse-fp",
            &sparse,
            None,
        )
        .await
        .expect("sparse follow-up cannot erase metadata");
        let metadata: Value = first
            .query_one(
                "SELECT metadata_json FROM external_identities
             WHERE provider = 'comicvine' AND entity_type = 'issue'
               AND external_id = 'issue-100'",
                &[],
            )
            .await
            .expect("final issue metadata")
            .get(0);
        assert_eq!(metadata["issue_number"], "1");
        let series: Value = first
            .query_one(
                "SELECT metadata_json FROM external_identities
             WHERE provider = 'comicvine' AND entity_type = 'series'
               AND external_id = 'series-10'",
                &[],
            )
            .await
            .expect("final series metadata")
            .get(0);
        assert_eq!(series["publisher"]["name"], "Publisher");
    }

    #[test]
    fn canonical_json_matches_python_sort_keys_default_separators() {
        let v = serde_json::json!({"b": 1, "a": 2});
        assert_eq!(canonical_json(&v), r#"{"a": 2, "b": 1}"#);
        let unicode = serde_json::json!({"issue_numbers": ["Été", "🦇"]});
        assert_eq!(
            canonical_json(&unicode),
            r#"{"issue_numbers": ["\u00c9t\u00e9", "\ud83e\udd87"]}"#
        );
    }

    #[test]
    fn metadata_merge_preserves_populated_and_fills_nested_references() {
        let old = serde_json::json!({"name":"Trusted","volume":{"id":10,"name":""},
            "credits":["deep"]});
        let new = serde_json::json!({"name":"New","issue_number":"1",
            "volume":{"id":10,"name":"Volume"}, "credits":["shallow"]});
        let merged = fill_missing_metadata(Some(&old), Some(&new));
        assert_eq!(merged["name"], "Trusted");
        assert_eq!(merged["issue_number"], "1");
        assert_eq!(merged["volume"]["name"], "Volume");
        assert_eq!(merged["credits"], serde_json::json!(["deep"]));
    }

    #[test]
    fn request_fingerprint_key_order() {
        let fp = request_fingerprint("tok", &["issue:1".to_string()]);
        // approved_row_ids sorts before preview_token
        let expected_material = r#"{"approved_row_ids":["issue:1"],"preview_token":"tok"}"#;
        assert_eq!(fp, sha256_hex(expected_material));
    }

    #[test]
    fn catalog_inline_hydration_budget_matches_request_deadline() {
        assert_eq!(
            inline_hydration_budget(Duration::ZERO),
            Duration::from_secs(3)
        );
        assert_eq!(
            inline_hydration_budget(Duration::from_secs(7)),
            Duration::from_millis(1500)
        );
        assert!(inline_hydration_budget(Duration::from_secs(9)).is_zero());
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
