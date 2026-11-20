//! Owner-scoped identity reconciliation inbox.
//!
//! Rust replacement for the Python `/api/v2/identity-inbox/*` routes. The HTTP
//! method and exact path are preserved; only the implementation moves.

use crate::{
    auth::AuthenticatedUser,
    db,
    outbound::{OutboundHttp, OutboundRequest},
    ApiError, AppState,
};
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use bytes::Bytes;
use http_body_util::BodyExt;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::Arc;
use std::time::Duration;

#[derive(Debug, Deserialize)]
pub struct ListQuery {
    pub offset: Option<i64>,
    pub limit: Option<i64>,
}

#[derive(Debug, Deserialize)]
pub struct SearchQuery {
    pub q: String,
    pub limit: Option<i64>,
    pub issue_id: Option<i32>,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ActionRequest {
    pub external_identity_id: Option<i32>,
    pub rejection_reason: Option<String>,
    pub search_query: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IdentityInboxCandidate {
    pub external_identity_id: i32,
    pub provider: String,
    pub comicvine_id: Option<String>,
    pub external_url: Option<String>,
    pub metadata_json: Value,
    pub status: String,
    pub confidence: Option<f64>,
    pub evidence_source: Option<String>,
    pub evidence_json: Value,
    pub rejection_reason: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IdentityInboxItem {
    pub mapping_id: i32,
    pub issue_id: i32,
    pub thread_id: i32,
    pub thread_title: String,
    pub issue_number: String,
    pub status: String,
    pub provider: Option<String>,
    pub source_entry_summary: String,
    pub why_stopped: String,
    pub candidates: Vec<IdentityInboxCandidate>,
    pub created_at: Option<f64>,
    pub updated_at: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IdentityInboxResponse {
    pub items: Vec<IdentityInboxItem>,
    pub total: i64,
    pub offset: i64,
    pub limit: i64,
}

// OpenAPI-only body schema: `confirm` deserializes the shared `ActionRequest`
// and answers 400 when `external_identity_id` is missing.
/// Body for confirming an identity inbox candidate.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IdentityInboxConfirmRequest {
    pub external_identity_id: i32,
}

// OpenAPI-only body schema: `reject` answers 400 when `external_identity_id`
// is missing or `rejection_reason` is missing or blank.
/// Body for rejecting an identity inbox candidate.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IdentityInboxRejectRequest {
    pub external_identity_id: i32,
    #[schema(min_length = 1, pattern = r"\S")]
    pub rejection_reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IdentityInboxActionRequest {
    pub external_identity_id: Option<i32>,
    pub rejection_reason: Option<String>,
    pub search_query: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IdentityInboxActionResponse {
    pub success: bool,
    pub message: String,
    pub updated_item: Option<IdentityInboxItem>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IdentityInboxSearchResult {
    pub comicvine_issue_id: i32,
    pub comicvine_volume_id: Option<i32>,
    pub volume_name: Option<String>,
    pub issue_number: Option<String>,
    pub issue_name: Option<String>,
    pub publisher: Option<String>,
    pub start_year: Option<i32>,
    pub site_detail_url: Option<String>,
    pub image_url: Option<String>,
    pub score: Option<f64>,
    pub evidence: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IdentityInboxSearchResponse {
    pub issue_id: i32,
    pub query: String,
    pub results: Vec<IdentityInboxSearchResult>,
    pub total_available: Option<i64>,
}

fn bad_request(detail: &str) -> ApiError {
    ApiError::with_status(StatusCode::BAD_REQUEST, detail.to_string())
}

fn not_found(detail: &str) -> ApiError {
    ApiError::with_status(StatusCode::NOT_FOUND, detail.to_string())
}

fn unprocessable(detail: &str) -> ApiError {
    ApiError::with_status(StatusCode::UNPROCESSABLE_ENTITY, detail.to_string())
}

fn source_entry_summary(thread_title: &str, issue_number: &str, metadata: &Value) -> String {
    let mut parts = vec![format!("{} #{}", thread_title, issue_number)];
    if let Some(volume) = metadata.get("volume").and_then(|v| v.as_object()) {
        if let Some(name) = volume.get("name").and_then(|v| v.as_str()) {
            if !name.is_empty() {
                parts.push(format!("({name})"));
            }
        }
    }
    if let Some(publisher) = metadata.get("publisher").and_then(|v| v.as_str()) {
        if !publisher.is_empty() {
            parts.push(format!("- {publisher}"));
        }
    }
    parts.join(" ")
}

fn why_stopped(status: &str, evidence: &Value, candidate_count: usize) -> String {
    // The collapsed inbox header renders this string. The list endpoint now
    // batch-loads real candidates, so an evidence/status-only reason can
    // contradict the candidate cards shown on expand (#5382). Reflect the real
    // candidate state first. When candidates exist, keep any non-empty
    // decision_reason so the header still explains why review is needed; only
    // the empty-evidence "No candidates found" fallback is replaced by the
    // count. The reasons below apply only when there are genuinely no
    // candidates for the issue.
    if candidate_count > 0 {
        let count_text = if candidate_count == 1 {
            "1 candidate found".to_string()
        } else {
            format!("{candidate_count} candidates found")
        };
        if let Some(obj) = evidence.as_object() {
            if let Some(reason) = obj.get("decision_reason").and_then(|v| v.as_str()) {
                if !reason.is_empty() {
                    return format!("{count_text}: {reason}");
                }
            }
        }
        return count_text;
    }
    let is_empty_evidence = evidence.is_null()
        || evidence.as_object().map(|o| o.is_empty()).unwrap_or(false)
        || evidence.as_array().map(|a| a.is_empty()).unwrap_or(false);
    if is_empty_evidence {
        return "No candidates found".to_string();
    }
    if let Some(obj) = evidence.as_object() {
        if let Some(reason) = obj.get("decision_reason").and_then(|v| v.as_str()) {
            if !reason.is_empty() {
                return reason.to_string();
            }
        }
    }
    if status == "unresolved" {
        return "No validated local candidate".to_string();
    }
    if status == "candidate" {
        return "Multiple candidates require explicit review".to_string();
    }
    format!("Status: {status}")
}

fn parse_json_text(text: Option<String>) -> Value {
    text.and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_else(|| serde_json::json!({}))
}

async fn fetch_item(
    state: &Arc<AppState>,
    user_id: i32,
    mapping_id: i32,
) -> Result<Option<IdentityInboxItem>, ApiError> {
    let conn = db::checkout(state).await?;
    let mapping_row = conn
        .query_opt(
            "SELECT m.id, m.issue_id, m.status, m.evidence_json::text, \
                    EXTRACT(EPOCH FROM m.created_at)::float8, EXTRACT(EPOCH FROM m.updated_at)::float8 \
             FROM issue_external_identity_mappings m WHERE m.id = $1",
            &[&mapping_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(mr) = mapping_row else {
        return Ok(None);
    };
    let mid: i32 = mr.get(0);
    let issue_id: i32 = mr.get(1);
    let status: String = mr.get(2);
    let evidence_text: Option<String> = mr.get(3);
    let created_at: Option<f64> = mr.get(4);
    let updated_at: Option<f64> = mr.get(5);
    let evidence = parse_json_text(evidence_text);

    let issue_row = conn
        .query_opt(
            "SELECT i.id, i.issue_number, i.thread_id FROM issues i WHERE i.id = $1",
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(ir) = issue_row else {
        return Ok(None);
    };
    let issue_number: String = ir.get(1);
    let thread_id: i32 = ir.get(2);

    let thread_row = conn
        .query_opt(
            "SELECT t.id, t.title, t.user_id FROM threads t WHERE t.id = $1",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(tr) = thread_row else {
        return Ok(None);
    };
    let thread_title: String = tr.get(1);
    let owner_id: i32 = tr.get(2);
    if owner_id != user_id {
        return Ok(None);
    }

    let identity_row = conn
        .query_opt(
            "SELECT e.id, e.provider, e.external_id, e.external_url, e.metadata_json::text \
             FROM issue_external_identity_mappings m JOIN external_identities e ON e.id=m.external_identity_id \
             WHERE m.id=$1",
            &[&mapping_id],
        )
        .await
        .map_err(db::query_error)?;
    let (provider, metadata) = if let Some(idr) = identity_row {
        let provider: String = idr.get(1);
        let metadata_text: Option<String> = idr.get(4);
        (Some(provider), parse_json_text(metadata_text))
    } else {
        (None, serde_json::json!({}))
    };

    // candidates
    let candidate_rows = conn
        .query(
            "SELECT cm.external_identity_id, cm.status, cm.confidence, cm.evidence_source, \
                    cm.evidence_json::text, cm.rejection_reason, \
                    ex.provider, ex.external_id, ex.external_url, ex.metadata_json::text \
             FROM issue_external_identity_mappings cm \
             JOIN external_identities ex ON ex.id = cm.external_identity_id \
             WHERE cm.issue_id = $1 AND cm.status IN ('deferred','candidate','confirmed','unresolved') \
             ORDER BY cm.confidence DESC NULLS LAST",
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?;

    let mut candidates = Vec::new();
    for cr in candidate_rows {
        let ext_id: i32 = cr.get(0);
        let cstatus: String = cr.get(1);
        let confidence: Option<f64> = cr.get(2);
        let evidence_source: Option<String> = cr.get(3);
        let evidence_text: Option<String> = cr.get(4);
        let rejection_reason: Option<String> = cr.get(5);
        let cprovider: String = cr.get(6);
        let comicvine_id: String = cr.get(7);
        let external_url: Option<String> = cr.get(8);
        let meta_text: Option<String> = cr.get(9);
        let metadata_json = parse_json_text(meta_text);
        let evidence_json = parse_json_text(evidence_text);
        candidates.push(IdentityInboxCandidate {
            external_identity_id: ext_id,
            provider: cprovider,
            comicvine_id: Some(comicvine_id),
            external_url,
            metadata_json,
            status: cstatus,
            confidence,
            evidence_source,
            evidence_json,
            rejection_reason,
        });
    }

    let item = IdentityInboxItem {
        mapping_id: mid,
        issue_id,
        thread_id,
        thread_title: thread_title.clone(),
        issue_number: issue_number.clone(),
        status: status.clone(),
        provider,
        source_entry_summary: source_entry_summary(&thread_title, &issue_number, &metadata),
        why_stopped: why_stopped(&status, &evidence, candidates.len()),
        candidates,
        created_at,
        updated_at,
    };
    let _ = mid;
    Ok(Some(item))
}

pub async fn list_inbox(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Query(q): Query<ListQuery>,
) -> Result<Json<IdentityInboxResponse>, ApiError> {
    let offset = q.offset.unwrap_or(0);
    if offset < 0 {
        return Err(unprocessable("offset must be >= 0"));
    }
    let limit = q.limit.unwrap_or(50);
    if !(1..=100).contains(&limit) {
        return Err(unprocessable("limit out of range"));
    }

    let conn = db::checkout(&state).await?;
    let count_row = conn
        .query_one(
            "SELECT COUNT(*)::bigint FROM issue_external_identity_mappings m \
             JOIN issues i ON i.id = m.issue_id \
             JOIN threads t ON t.id = i.thread_id \
             WHERE t.user_id = $1 AND m.status IN ('unresolved','candidate','deferred')",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let total: i64 = count_row.get(0);

    let rows = conn
        .query(
            "SELECT m.id, m.status, \
                    EXTRACT(EPOCH FROM m.created_at)::float8, EXTRACT(EPOCH FROM m.updated_at)::float8, \
                    i.id, i.issue_number, \
                    t.id, t.title, \
                    e.id, e.provider, e.external_id, e.external_url, e.metadata_json::text, \
                    m.evidence_json::text \
             FROM issue_external_identity_mappings m \
             JOIN issues i ON i.id = m.issue_id \
             JOIN threads t ON t.id = i.thread_id \
             JOIN external_identities e ON e.id = m.external_identity_id \
             WHERE t.user_id = $1 AND m.status IN ('unresolved','candidate','deferred') \
             ORDER BY m.created_at DESC \
             OFFSET $2 LIMIT $3",
            &[&user.id(), &offset, &limit],
        )
        .await
        .map_err(db::query_error)?;

    // Batch-load candidates for every issue on this page in one query. The
    // detail endpoint resolves candidates by issue_id; grouping them per issue
    // here preserves the same wire contract without an N+1 round trip.
    let issue_ids: Vec<i32> = rows.iter().map(|r| r.get(4)).collect();
    let candidate_rows = if issue_ids.is_empty() {
        Vec::new()
    } else {
        conn.query(
            "SELECT cm.issue_id, cm.external_identity_id, cm.status, cm.confidence, \
                    cm.evidence_source, cm.evidence_json::text, cm.rejection_reason, \
                    ex.provider, ex.external_id, ex.external_url, ex.metadata_json::text \
             FROM issue_external_identity_mappings cm \
             JOIN external_identities ex ON ex.id = cm.external_identity_id \
             WHERE cm.issue_id = ANY($1) \
               AND cm.status IN ('deferred','candidate','confirmed','unresolved') \
             ORDER BY cm.issue_id, cm.confidence DESC NULLS LAST",
            &[&issue_ids],
        )
        .await
        .map_err(db::query_error)?
    };

    let mut candidates_by_issue: std::collections::HashMap<i32, Vec<IdentityInboxCandidate>> =
        std::collections::HashMap::new();
    for cr in candidate_rows {
        let candidate_issue_id: i32 = cr.get(0);
        let ext_id: i32 = cr.get(1);
        let cstatus: String = cr.get(2);
        let confidence: Option<f64> = cr.get(3);
        let evidence_source: Option<String> = cr.get(4);
        let evidence_text: Option<String> = cr.get(5);
        let rejection_reason: Option<String> = cr.get(6);
        let cprovider: String = cr.get(7);
        let comicvine_id: String = cr.get(8);
        let external_url: Option<String> = cr.get(9);
        let meta_text: Option<String> = cr.get(10);
        let metadata_json = parse_json_text(meta_text);
        let evidence_json = parse_json_text(evidence_text);
        candidates_by_issue
            .entry(candidate_issue_id)
            .or_default()
            .push(IdentityInboxCandidate {
                external_identity_id: ext_id,
                provider: cprovider,
                comicvine_id: Some(comicvine_id),
                external_url,
                metadata_json,
                status: cstatus,
                confidence,
                evidence_source,
                evidence_json,
                rejection_reason,
            });
    }

    let mut items = Vec::new();
    for r in rows {
        let mapping_id: i32 = r.get(0);
        let status: String = r.get(1);
        let created_at: Option<f64> = r.get(2);
        let updated_at: Option<f64> = r.get(3);
        let issue_id: i32 = r.get(4);
        let issue_number: String = r.get(5);
        let thread_id: i32 = r.get(6);
        let thread_title: String = r.get(7);
        let _ext_id: i32 = r.get(8);
        let provider: String = r.get(9);
        let comicvine_id: String = r.get(10);
        let external_url: Option<String> = r.get(11);
        let meta_text: Option<String> = r.get(12);
        let evidence_text: Option<String> = r.get(13);
        let metadata = parse_json_text(meta_text);
        let evidence = parse_json_text(evidence_text);
        let candidates = candidates_by_issue
            .get(&issue_id)
            .cloned()
            .unwrap_or_default();
        items.push(IdentityInboxItem {
            mapping_id,
            issue_id,
            thread_id,
            thread_title: thread_title.clone(),
            issue_number: issue_number.clone(),
            status: status.clone(),
            provider: Some(provider),
            source_entry_summary: source_entry_summary(&thread_title, &issue_number, &metadata),
            why_stopped: why_stopped(&status, &evidence, candidates.len()),
            candidates,
            created_at,
            updated_at,
        });
        let _ = (comicvine_id, external_url);
    }

    Ok(Json(IdentityInboxResponse {
        items,
        total,
        offset,
        limit,
    }))
}

pub async fn get_inbox_item(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(mapping_id): Path<i32>,
) -> Result<Json<IdentityInboxResponse>, ApiError> {
    let item = fetch_item(&state, user.id(), mapping_id)
        .await?
        .ok_or_else(|| not_found(&format!("Inbox item {mapping_id} not found")))?;
    Ok(Json(IdentityInboxResponse {
        items: vec![item],
        total: 1,
        offset: 0,
        limit: 1,
    }))
}

pub async fn search_issues(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Query(q): Query<SearchQuery>,
) -> Result<Json<IdentityInboxSearchResponse>, ApiError> {
    let _ = user;
    if q.q.trim().is_empty() || q.q.len() > 200 || q.q.is_empty() {
        return Err(unprocessable("q invalid"));
    }
    let limit = q.limit.unwrap_or(10);
    if !(1..=50).contains(&limit) {
        return Err(unprocessable("limit out of range"));
    }
    let clamped = limit.clamp(1, 50);
    let issue_id = q.issue_id.unwrap_or(0);

    let api_key = std::env::var("COMICVINE_API_KEY")
        .unwrap_or_default()
        .trim()
        .to_string();
    if api_key.is_empty() {
        return Ok(Json(IdentityInboxSearchResponse {
            issue_id,
            query: q.q.clone(),
            results: vec![],
            total_available: Some(0),
        }));
    }

    let url = build_search_url(&api_key, &q.q, clamped);
    let payload = fetch_comicvine(&state.outbound, url).await;

    let mut results = Vec::new();
    let mut total_available = Some(0i64);
    if let Some(p) = payload {
        if let Some(rows) = p.get("results").and_then(|v| v.as_array()) {
            for row in rows {
                let Some(obj) = row.as_object() else {
                    continue;
                };
                let comicvine_issue_id = match obj.get("id").and_then(|v| v.as_i64()) {
                    Some(v) => v as i32,
                    None => continue,
                };
                let volume = obj.get("volume").and_then(|v| v.as_object());
                let comicvine_volume_id = volume
                    .and_then(|v| v.get("id"))
                    .and_then(|v| v.as_i64())
                    .map(|v| v as i32);
                let volume_name = volume
                    .and_then(|v| v.get("name"))
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());

                let publisher = match obj.get("publisher") {
                    Some(Value::Object(o)) => o
                        .get("name")
                        .and_then(|v| v.as_str())
                        .map(|s| s.to_string()),
                    Some(Value::String(s)) => Some(s.clone()),
                    _ => None,
                };

                let image_url = obj.get("image").and_then(|v| v.as_object()).and_then(|o| {
                    o.get("medium_url")
                        .or_else(|| o.get("small_url"))
                        .and_then(|v| v.as_str())
                        .map(|s| s.to_string())
                });

                let cover_date = obj.get("cover_date").and_then(|v| v.as_str());
                let start_year = cover_date.and_then(|cd| {
                    if cd.len() >= 4 {
                        cd[..4].parse::<i32>().ok()
                    } else {
                        None
                    }
                });

                let site_detail_url = obj
                    .get("site_detail_url")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());

                let issue_number = obj.get("issue_number").and_then(|v| {
                    if v.is_null() {
                        None
                    } else {
                        Some(v.to_string().trim_matches('"').to_string())
                    }
                });

                let issue_name = obj
                    .get("name")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());

                let mut evidence = Vec::new();
                if let Some(vn) = &volume_name {
                    evidence.push(format!("Volume: {vn}"));
                }
                if let Some(pubn) = &publisher {
                    evidence.push(format!("Publisher: {pubn}"));
                }

                results.push(IdentityInboxSearchResult {
                    comicvine_issue_id,
                    comicvine_volume_id,
                    volume_name,
                    issue_number,
                    issue_name,
                    publisher,
                    start_year,
                    site_detail_url,
                    image_url,
                    score: None,
                    evidence,
                });
            }
        }
        if let Some(total) = p.get("number_of_total_results").and_then(|v| v.as_i64()) {
            total_available = Some(total);
        } else {
            total_available = Some(results.len() as i64);
        }
    }

    let issue_id_final = if q.issue_id.is_some() { issue_id } else { 0 };
    // Python sets issue_id=0 then caller sets issue_id if provided. Keep issue_id if provided else 0.
    let _ = issue_id_final;

    Ok(Json(IdentityInboxSearchResponse {
        issue_id: q.issue_id.unwrap_or(0),
        query: q.q.clone(),
        results,
        total_available,
    }))
}

fn percent_encode(s: &str) -> String {
    let mut out = String::new();
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char)
            }
            b' ' => out.push_str("%20"),
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

fn build_search_url(api_key: &str, query: &str, limit: i64) -> String {
    let field_list = "id,name,issue_number,cover_date,volume,publisher,site_detail_url,image";
    format!(
        "https://comicvine.gamespot.com/api/search/?api_key={}&format=json&query={}&resources=issue&limit={}&field_list={}",
        percent_encode(api_key),
        percent_encode(query),
        limit,
        percent_encode(field_list)
    )
}

/// Search-result payload cap. ComicVine search responses are small; the cap
/// keeps a hostile provider from driving unbounded allocation.
const MAX_SEARCH_BODY: usize = 5_000_000;
const SEARCH_TIMEOUT: Duration = Duration::from_secs(30);

/// Fetch one ComicVine search page through the app's outbound seam (#5339):
/// the real HTTPS client in production, a recording fake in test contexts
/// that never opens a socket. Any failure yields `None`, as before.
async fn fetch_comicvine(outbound: &Arc<dyn OutboundHttp>, url: String) -> Option<Value> {
    let without = url.strip_prefix("https://")?;
    let (host, rest) = without.split_once('/')?;
    let request = OutboundRequest {
        method: http::Method::GET,
        path: format!("/{rest}"),
        headers: vec![
            ("user-agent".to_string(), "ComicPile/1.0".to_string()),
            ("accept".to_string(), "application/json".to_string()),
            ("connection".to_string(), "close".to_string()),
        ],
        body: Bytes::new(),
    };
    let exchange = async {
        let response = outbound.send(host, request).await.ok()?;
        if !response.status.is_success() {
            return None;
        }
        let mut data = Vec::new();
        let mut body = response.body;
        while let Some(frame) = body.frame().await {
            let frame = frame.ok()?;
            if let Ok(bytes) = frame.into_data() {
                data.extend_from_slice(&bytes);
                if data.len() > MAX_SEARCH_BODY {
                    return None;
                }
            }
        }
        serde_json::from_slice(&data).ok()
    };
    tokio::time::timeout(SEARCH_TIMEOUT, exchange)
        .await
        .ok()
        .flatten()
}

pub async fn confirm(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(mapping_id): Path<i32>,
    Json(req): Json<ActionRequest>,
) -> Result<Json<IdentityInboxActionResponse>, ApiError> {
    let external_identity_id = req
        .external_identity_id
        .ok_or_else(|| bad_request("external_identity_id is required for confirm action"))?;

    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;

    // load mapping
    let mrow = tx
        .query_opt(
            "SELECT id, issue_id FROM issue_external_identity_mappings WHERE id = $1",
            &[&mapping_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(mr) = mrow else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not found"));
    };
    let issue_id: i32 = mr.get(1);

    // issue + thread ownership
    let it = tx
        .query_opt(
            "SELECT t.user_id FROM issues i JOIN threads t ON t.id = i.thread_id WHERE i.id = $1 FOR UPDATE OF i",
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(itr) = it else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not owned by this user"));
    };
    let owner_id: i32 = itr.get(0);
    if owner_id != user.id() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not owned by this user"));
    }

    // external identity
    let idr = tx
        .query_opt(
            "SELECT id, provider, entity_type FROM external_identities WHERE id = $1",
            &[&external_identity_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(ident) = idr else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("external identity is not an issue identity"));
    };
    let provider: String = ident.get(1);
    let entity_type: String = ident.get(2);
    if entity_type != "issue" {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("external identity is not an issue identity"));
    }

    // conflicting confirmed
    let conflict = tx
        .query_opt(
            "SELECT m.id FROM issue_external_identity_mappings m \
             JOIN external_identities e ON e.id = m.external_identity_id \
             WHERE m.issue_id = $1 AND m.status = 'confirmed' \
               AND m.external_identity_id <> $2 AND e.provider = $3 LIMIT 1",
            &[&issue_id, &external_identity_id, &provider],
        )
        .await
        .map_err(db::query_error)?;
    if conflict.is_some() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request(&format!(
            "issue already has a confirmed {provider} identity"
        )));
    }

    // upsert
    let existing = tx
        .query_opt(
            "SELECT id FROM issue_external_identity_mappings WHERE issue_id = $1 AND external_identity_id = $2",
            &[&issue_id, &external_identity_id],
        )
        .await
        .map_err(db::query_error)?;
    if let Some(er) = existing {
        let eid: i32 = er.get(0);
        tx.execute(
            "UPDATE issue_external_identity_mappings SET status='confirmed', evidence_source='user_confirmed', \
             confidence=1.0, rejection_reason=NULL, updated_at=NOW() WHERE id=$1",
            &[&eid],
        )
        .await
        .map_err(db::query_error)?;
    } else {
        tx.execute(
            "INSERT INTO issue_external_identity_mappings \
             (issue_id, external_identity_id, status, evidence_source, confidence, rejection_reason, created_at, updated_at) \
             VALUES ($1,$2,'confirmed','user_confirmed',1.0,NULL,NOW(),NOW())",
            &[&issue_id, &external_identity_id],
        )
        .await
        .map_err(db::query_error)?;
    }

    // reject others
    tx.execute(
        "UPDATE issue_external_identity_mappings m SET status='rejected', \
         rejection_reason='replaced by user-confirmed candidate', updated_at=NOW() \
         FROM external_identities e \
         WHERE m.external_identity_id = e.id AND m.issue_id = $1 \
           AND m.external_identity_id <> $2 AND m.status IN ('candidate','unresolved','deferred') \
           AND e.provider = $3",
        &[&issue_id, &external_identity_id, &provider],
    )
    .await
    .map_err(db::query_error)?;

    tx.commit().await.map_err(db::query_error)?;

    let updated = fetch_item(&state, user.id(), mapping_id).await?;
    Ok(Json(IdentityInboxActionResponse {
        success: true,
        message: "Candidate confirmed successfully".to_string(),
        updated_item: updated,
    }))
}

pub async fn reject(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(mapping_id): Path<i32>,
    Json(req): Json<ActionRequest>,
) -> Result<Json<IdentityInboxActionResponse>, ApiError> {
    let external_identity_id = req
        .external_identity_id
        .ok_or_else(|| bad_request("external_identity_id is required for reject action"))?;
    let rejection_reason = req
        .rejection_reason
        .as_deref()
        .map(|s| s.to_string())
        .unwrap_or_default();
    if rejection_reason.trim().is_empty() {
        return Err(bad_request(
            "rejection_reason is required when rejecting a candidate",
        ));
    }

    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;

    let mrow = tx
        .query_opt(
            "SELECT id, issue_id FROM issue_external_identity_mappings WHERE id = $1",
            &[&mapping_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(mr) = mrow else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not found"));
    };
    let issue_id: i32 = mr.get(1);

    let it = tx
        .query_opt(
            "SELECT t.user_id FROM issues i JOIN threads t ON t.id = i.thread_id WHERE i.id = $1",
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(itr) = it else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not owned by this user"));
    };
    let owner_id: i32 = itr.get(0);
    if owner_id != user.id() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not owned by this user"));
    }

    // validate external identity
    let idr = tx
        .query_opt(
            "SELECT id, entity_type FROM external_identities WHERE id = $1",
            &[&external_identity_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(ident) = idr else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("external identity is not an issue identity"));
    };
    let entity_type: String = ident.get(1);
    if entity_type != "issue" {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("external identity is not an issue identity"));
    }

    // upsert rejected
    let existing = tx
        .query_opt(
            "SELECT id FROM issue_external_identity_mappings WHERE issue_id = $1 AND external_identity_id = $2",
            &[&issue_id, &external_identity_id],
        )
        .await
        .map_err(db::query_error)?;
    if let Some(er) = existing {
        let eid: i32 = er.get(0);
        tx.execute(
            "UPDATE issue_external_identity_mappings SET status='rejected', evidence_source=NULL, confidence=NULL, rejection_reason=$2, updated_at=NOW() WHERE id=$1",
            &[&eid, &rejection_reason],
        )
        .await
        .map_err(db::query_error)?;
    } else {
        tx.execute(
            "INSERT INTO issue_external_identity_mappings \
             (issue_id, external_identity_id, status, evidence_source, confidence, rejection_reason, created_at, updated_at) \
             VALUES ($1,$2,'rejected',NULL,NULL,$3,NOW(),NOW())",
            &[&issue_id, &external_identity_id, &rejection_reason],
        )
        .await
        .map_err(db::query_error)?;
    }
    tx.execute(
        "UPDATE issue_external_identity_mappings SET updated_at=NOW() WHERE issue_id=$1",
        &[&issue_id],
    )
    .await
    .map_err(db::query_error)?;
    tx.commit().await.map_err(db::query_error)?;

    let updated = fetch_item(&state, user.id(), mapping_id).await?;
    Ok(Json(IdentityInboxActionResponse {
        success: true,
        message: "Candidate rejected".to_string(),
        updated_item: updated,
    }))
}

pub async fn defer(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(mapping_id): Path<i32>,
) -> Result<Json<IdentityInboxActionResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let mut tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;

    let mrow = tx
        .query_opt(
            "SELECT id, issue_id FROM issue_external_identity_mappings WHERE id = $1",
            &[&mapping_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(mr) = mrow else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not found"));
    };
    let issue_id: i32 = mr.get(1);

    let it = tx
        .query_opt(
            "SELECT t.user_id FROM issues i JOIN threads t ON t.id = i.thread_id WHERE i.id = $1",
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(itr) = it else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not owned by this user"));
    };
    let owner_id: i32 = itr.get(0);
    if owner_id != user.id() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not owned by this user"));
    }

    // Some deployed databases are stamped at a revision that added 'deferred'
    // to the status allow-list without the constraint change having actually
    // run (issue #5378). Writing status='deferred' then fails with a check
    // violation and used to surface as a generic HTTP 500. Use a savepoint so
    // the failed statement cannot poison the outer transaction, and fall back
    // to a representation the stale constraint accepts: a rejected mapping
    // with an explicit defer reason. Either way the item leaves the unresolved
    // inbox and the defer succeeds instead of returning a 500.
    let savepoint = tx
        .savepoint("identity_inbox_defer_status")
        .await
        .map_err(db::query_error)?;
    match savepoint
        .execute(
            "UPDATE issue_external_identity_mappings SET status='deferred', updated_at=NOW() WHERE id=$1",
            &[&mapping_id],
        )
        .await
    {
        Ok(_) => {
            savepoint.commit().await.map_err(db::query_error)?;
        }
        Err(error)
            if error.code() == Some(&tokio_postgres::error::SqlState::CHECK_VIOLATION) =>
        {
            savepoint.rollback().await.map_err(db::query_error)?;
            tx.execute(
                "UPDATE issue_external_identity_mappings SET status='rejected', \
                 rejection_reason='deferred by user', evidence_source='deferred', \
                 updated_at=NOW() WHERE id=$1",
                &[&mapping_id],
            )
            .await
            .map_err(db::query_error)?;
        }
        Err(error) => return Err(db::query_error(error)),
    }
    tx.commit().await.map_err(db::query_error)?;

    let updated = fetch_item(&state, user.id(), mapping_id).await?;
    Ok(Json(IdentityInboxActionResponse {
        success: true,
        message: "Item deferred for later review".to_string(),
        updated_item: updated,
    }))
}

pub async fn skip(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(mapping_id): Path<i32>,
) -> Result<Json<IdentityInboxActionResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;

    let mrow = tx
        .query_opt(
            "SELECT id, issue_id FROM issue_external_identity_mappings WHERE id = $1",
            &[&mapping_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(mr) = mrow else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not found"));
    };
    let issue_id: i32 = mr.get(1);

    let it = tx
        .query_opt(
            "SELECT t.user_id FROM issues i JOIN threads t ON t.id = i.thread_id WHERE i.id = $1",
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(itr) = it else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not owned by this user"));
    };
    let owner_id: i32 = itr.get(0);
    if owner_id != user.id() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not owned by this user"));
    }

    tx.execute(
        "UPDATE issue_external_identity_mappings SET status='rejected', rejection_reason='skipped by user', updated_at=NOW() WHERE id=$1",
        &[&mapping_id],
    )
    .await
    .map_err(db::query_error)?;
    tx.commit().await.map_err(db::query_error)?;

    let updated = fetch_item(&state, user.id(), mapping_id).await?;
    Ok(Json(IdentityInboxActionResponse {
        success: true,
        message: "Item skipped".to_string(),
        updated_item: updated,
    }))
}

// Documentation-only operations for OpenAPI
#[utoipa::path(
    get,
    path = "/api/v2/identity-inbox",
    tag = "identity-inbox",
    params(
        ("offset" = Option<i64>, Query, minimum = 0, description = "Items to skip (default 0)"),
        ("limit" = Option<i64>, Query, minimum = 1, maximum = 100, description = "Page size, 1-100 (default 50)")
    ),
    responses((status = 200, description = "ok", body = IdentityInboxResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v2/identity-inbox/issue-matches",
    tag = "identity-inbox",
    params(
        ("q" = String, Query, min_length = 1, description = "Non-blank search text, at most 200 UTF-8 bytes (required)"),
        ("limit" = Option<i64>, Query, minimum = 1, maximum = 50, description = "Maximum results, 1-50 (default 10)"),
        ("issue_id" = Option<i32>, Query, description = "Issue id echoed back in the response (default 0)")
    ),
    responses((status = 200, description = "ok", body = IdentityInboxSearchResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn search_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v2/identity-inbox/{mapping_id}",
    tag = "identity-inbox",
    params(("mapping_id" = i32, Path, description = "Mapping id")),
    responses((status = 200, description = "ok", body = IdentityInboxResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/identity-inbox/{mapping_id}/confirmations",
    tag = "identity-inbox",
    params(("mapping_id" = i32, Path, description = "Mapping id")),
    request_body = IdentityInboxConfirmRequest,
    responses((status = 200, description = "ok", body = IdentityInboxActionResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn confirm_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/identity-inbox/{mapping_id}/deferrals",
    tag = "identity-inbox",
    params(("mapping_id" = i32, Path, description = "Mapping id")),
    responses((status = 200, description = "ok", body = IdentityInboxActionResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn defer_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/identity-inbox/{mapping_id}/rejections",
    tag = "identity-inbox",
    params(("mapping_id" = i32, Path, description = "Mapping id")),
    request_body = IdentityInboxRejectRequest,
    responses((status = 200, description = "ok", body = IdentityInboxActionResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn reject_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/identity-inbox/{mapping_id}/skips",
    tag = "identity-inbox",
    params(("mapping_id" = i32, Path, description = "Mapping id")),
    responses((status = 200, description = "ok", body = IdentityInboxActionResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn skip_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::auth::AuthenticatedUser;
    use crate::test_support;

    /// ComICVine search must go through the outbound seam: the fake records
    /// the host and query and supplies the payload, never a socket (#5339).
    #[tokio::test]
    async fn fetch_comicvine_records_host_and_query_and_parses_the_payload() {
        let recorder = Arc::new(crate::outbound::RecordingFakeOutbound::new());
        let fake: Arc<dyn OutboundHttp> = recorder.clone();
        recorder.push_ok(
            http::StatusCode::OK,
            http::HeaderMap::new(),
            Bytes::from_static(
                br#"{"status_code":1,"number_of_total_results":1,"results":[{"id":40001,"name":"Batman"}]}"#,
            ),
        );
        let url = build_search_url("KEY123", "bat man", 10);
        let payload = fetch_comicvine(&fake, url)
            .await
            .expect("canned provider payload must parse");
        assert_eq!(payload["number_of_total_results"], 1);
        assert_eq!(payload["results"][0]["id"], 40001);

        let calls = recorder.calls();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].host, "comicvine.gamespot.com");
        assert_eq!(calls[0].method, "GET");
        assert!(
            calls[0].path.starts_with("/api/search/?api_key=KEY123"),
            "unexpected search path {}",
            calls[0].path
        );
        assert!(calls[0].path.contains("query=bat%20man"));
        assert!(calls[0].path.contains("resources=issue"));
    }

    #[tokio::test]
    async fn fetch_comicvine_returns_none_on_error_status_failure_and_oversize() {
        let recorder = Arc::new(crate::outbound::RecordingFakeOutbound::new());
        let fake: Arc<dyn OutboundHttp> = recorder.clone();
        // Non-success status.
        recorder.push_ok(
            http::StatusCode::INTERNAL_SERVER_ERROR,
            http::HeaderMap::new(),
            Bytes::from_static(br#"{"status_code":1}"#),
        );
        assert!(fetch_comicvine(&fake, build_search_url("K", "q", 10))
            .await
            .is_none());
        // Transport failure (the default fake behavior).
        assert!(fetch_comicvine(&fake, build_search_url("K", "q", 10))
            .await
            .is_none());
        // Oversized body is dropped instead of allocated unbounded.
        recorder.push_ok(
            http::StatusCode::OK,
            http::HeaderMap::new(),
            Bytes::from(vec![b'x'; MAX_SEARCH_BODY + 1]),
        );
        assert!(fetch_comicvine(&fake, build_search_url("K", "q", 10))
            .await
            .is_none());
        assert_eq!(recorder.calls().len(), 3);
    }

    /// End-to-end through the handler: a test-configured app answers search
    /// from the recording fake, so the route never touches the network.
    #[tokio::test]
    async fn search_issues_serves_results_from_the_recording_fake() {
        let Some(state) = test_support::test_state(2).await else {
            return;
        };
        let _guard = test_support::reset_for_test(&state).await;
        let fake = state
            .recording_fake()
            .expect("test state must install the recording fake outbound client");
        fake.clear();
        fake.push_ok(
            http::StatusCode::OK,
            http::HeaderMap::new(),
            Bytes::from_static(
                br#"{"status_code":1,"number_of_total_results":1,"results":[{"id":400077,"name":"Detective Comics","issue_number":"1","volume":{"id":40509},"site_detail_url":"https://comicvine.gamespot.com/issue/4000-77/"}]}"#,
            ),
        );
        let _env = ComicvineKeyEnv::install();
        let response = search_issues(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Query(SearchQuery {
                q: "detective".to_string(),
                limit: Some(10),
                issue_id: None,
            }),
        )
        .await
        .expect("search must succeed against the fake");
        assert_eq!(response.total_available, Some(1));
        assert_eq!(response.results.len(), 1);
        assert_eq!(response.results[0].comicvine_issue_id, 400077);
        let calls = fake.calls();
        assert_eq!(calls.len(), 1, "exactly one outbound call, no socket");
        assert_eq!(calls[0].host, "comicvine.gamespot.com");
    }

    /// Save/restore `COMICVINE_API_KEY` around one test (same pattern as the
    /// bug-reports GitHub env guard).
    struct ComicvineKeyEnv {
        previous: Option<String>,
    }

    impl ComicvineKeyEnv {
        fn install() -> Self {
            let previous = std::env::var("COMICVINE_API_KEY").ok();
            std::env::set_var("COMICVINE_API_KEY", "TESTKEY123");
            Self { previous }
        }
    }

    impl Drop for ComicvineKeyEnv {
        fn drop(&mut self) {
            match &self.previous {
                Some(value) => std::env::set_var("COMICVINE_API_KEY", value),
                None => std::env::remove_var("COMICVINE_API_KEY"),
            }
        }
    }

    #[test]
    fn why_stopped_uses_candidate_count_and_keeps_zero_candidate_reasons() {
        let empty = serde_json::json!({});
        // Real candidate state wins over the empty-evidence fallback, but a
        // non-empty decision_reason is preserved so the header still explains
        // why review is needed.
        assert_eq!(why_stopped("unresolved", &empty, 1), "1 candidate found");
        assert_eq!(why_stopped("unresolved", &empty, 3), "3 candidates found");
        let with_reason = serde_json::json!({"decision_reason": "ambiguous title"});
        assert_eq!(
            why_stopped("unresolved", &with_reason, 1),
            "1 candidate found: ambiguous title"
        );
        assert_eq!(
            why_stopped("candidate", &with_reason, 2),
            "2 candidates found: ambiguous title"
        );
        // With no candidates the original evidence/status reasons still apply.
        assert_eq!(why_stopped("unresolved", &empty, 0), "No candidates found");
        assert_eq!(why_stopped("candidate", &with_reason, 0), "ambiguous title");
    }

    #[tokio::test]
    async fn list_empty_returns_ok() {
        let Some(state) = test_support::test_state(2).await else {
            return;
        };
        let _guard = test_support::reset_for_test(&state).await;
        let user = AuthenticatedUser::for_test(1);
        // seed user
        let conn = state.pool.get().await.unwrap();
        conn.batch_execute(
            "INSERT INTO users (id, username, is_admin, created_at) VALUES (1,'u',false,NOW())",
        )
        .await
        .unwrap();
        drop(conn);
        let (status, body) = {
            let r = list_inbox(
                State(state.clone()),
                user,
                Query(ListQuery {
                    offset: None,
                    limit: None,
                }),
            )
            .await
            .unwrap();
            // call via function returns Json; extract
            (
                axum::http::StatusCode::OK,
                serde_json::to_value(r.0).unwrap(),
            )
        };
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["total"], 0);
    }

    #[tokio::test]
    async fn list_inbox_batch_loads_candidates_for_owned_issues_only() {
        let Some(state) = test_support::test_state(2).await else {
            return;
        };
        let _guard = test_support::reset_for_test(&state).await;
        let conn = state.pool.get().await.unwrap();
        conn.batch_execute(
            "INSERT INTO users (id, username, is_admin, created_at) VALUES \
                (1,'owner',false,NOW()), (2,'other',false,NOW()); \
             INSERT INTO threads (id, user_id, title, format, issues_remaining, queue_position, status, manual_creator_credits, is_blocked, is_test, queue_position_is_manual, created_at) VALUES \
                (1,1,'Owned thread','comics',2,0,'active','[]'::json,false,false,false,NOW()), \
                (2,2,'Other thread','comics',1,0,'active','[]'::json,false,false,false,NOW()); \
             INSERT INTO issues (id, thread_id, issue_number, status, position, created_at) VALUES \
                (1,1,'#1','unread',0,NOW()), \
                (2,1,'#2','unread',1,NOW()), \
                (3,2,'#1','unread',0,NOW()); \
             INSERT INTO external_identities (id, provider, entity_type, external_id, metadata_json, created_at, updated_at) VALUES \
                (1,'comicvine','issue','cv-1','{}'::json,NOW(),NOW()), \
                (2,'comicvine','issue','cv-2','{}'::json,NOW(),NOW()), \
                (3,'comicvine','issue','cv-3','{}'::json,NOW(),NOW()), \
                (4,'comicvine','issue','cv-4','{}'::json,NOW(),NOW()), \
                (5,'comicvine','issue','cv-5','{}'::json,NOW(),NOW()), \
                (6,'comicvine','issue','cv-6','{}'::json,NOW(),NOW()); \
             INSERT INTO issue_external_identity_mappings \
                (id, issue_id, external_identity_id, status, evidence_source, confidence, created_at, updated_at, evidence_json) VALUES \
                (1,1,1,'unresolved','heuristic',0.5,NOW(),NOW(),'{}'::json), \
                (2,1,2,'confirmed','user_confirmed',0.9,NOW(),NOW(),'{}'::json), \
                (3,2,3,'unresolved','heuristic',0.5,NOW(),NOW(),'{}'::json), \
                (4,2,4,'confirmed','user_confirmed',0.8,NOW(),NOW(),'{}'::json), \
                (5,3,5,'unresolved','heuristic',0.5,NOW(),NOW(),'{}'::json), \
                (6,3,6,'confirmed','user_confirmed',0.7,NOW(),NOW(),'{}'::json);",
        )
        .await
        .unwrap();
        drop(conn);

        let response = list_inbox(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Query(ListQuery {
                offset: None,
                limit: None,
            }),
        )
        .await
        .unwrap()
        .0;

        assert_eq!(response.total, 2);
        assert_eq!(response.items.len(), 2);
        let item_one = response
            .items
            .iter()
            .find(|item| item.issue_id == 1)
            .unwrap();
        let item_two = response
            .items
            .iter()
            .find(|item| item.issue_id == 2)
            .unwrap();
        assert_eq!(
            item_one
                .candidates
                .iter()
                .map(|c| c.external_identity_id)
                .collect::<Vec<_>>(),
            vec![2, 1]
        );
        assert_eq!(
            item_two
                .candidates
                .iter()
                .map(|c| c.external_identity_id)
                .collect::<Vec<_>>(),
            vec![4, 3]
        );
        assert!(!response.items.iter().any(|item| item.issue_id == 3));
        assert!(!response
            .items
            .iter()
            .any(|item| { item.candidates.iter().any(|c| c.external_identity_id == 6) }));
    }

    /// Regression test for #5382: the list endpoint now batch-loads real
    /// candidates, but `why_stopped` was ported from a Python implementation
    /// whose list response always had `candidates=[]`. An unresolved mapping
    /// with empty `evidence_json` therefore produced "No candidates found"
    /// while the very same response carried one candidate. The collapsed
    /// inbox header rendered that contradiction to the user. When candidates
    /// exist, a non-empty decision_reason is preserved alongside the count.
    #[tokio::test]
    async fn list_inbox_why_stopped_reflects_real_candidates() {
        let Some(state) = test_support::test_state(2).await else {
            return;
        };
        let _guard = test_support::reset_for_test(&state).await;
        let conn = state.pool.get().await.unwrap();
        conn.batch_execute(
            "INSERT INTO users (id, username, is_admin, created_at) VALUES (1,'owner',false,NOW()); \
             INSERT INTO threads (id, user_id, title, format, issues_remaining, queue_position, status, manual_creator_credits, is_blocked, is_test, queue_position_is_manual, created_at) VALUES \
                 (1,1,'Mutant X','comics',1,0,'active','[]'::json,false,false,false,NOW()), \
                 (2,1,'Mutant Y','comics',1,0,'active','[]'::json,false,false,false,NOW()); \
             INSERT INTO issues (id, thread_id, issue_number, status, position, created_at) VALUES \
                 (1,1,'#1','unread',0,NOW()), \
                 (2,2,'#1','unread',0,NOW()); \
             INSERT INTO external_identities (id, provider, entity_type, external_id, metadata_json, created_at, updated_at) VALUES \
                 (1,'comicvine','issue','cv-1','{}'::json,NOW(),NOW()), \
                 (2,'comicvine','issue','cv-2','{}'::json,NOW(),NOW()), \
                 (3,'comicvine','issue','cv-3','{}'::json,NOW(),NOW()); \
             INSERT INTO issue_external_identity_mappings \
                 (id, issue_id, external_identity_id, status, evidence_source, confidence, created_at, updated_at, evidence_json) VALUES \
                 (1,1,1,'unresolved','heuristic',0.5,NOW(),NOW(),'{\"decision_reason\":\"ambiguous title\"}'::json), \
                 (2,2,2,'unresolved','heuristic',0.5,NOW(),NOW(),'{\"decision_reason\":\"ambiguous title\"}'::json), \
                 (3,2,3,'confirmed','user_confirmed',0.9,NOW(),NOW(),'{}'::json);",
        )
        .await
        .unwrap();
        drop(conn);

        let response = list_inbox(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Query(ListQuery {
                offset: None,
                limit: None,
            }),
        )
        .await
        .unwrap()
        .0;

        assert_eq!(response.items.len(), 2);

        let one = response
            .items
            .iter()
            .find(|item| item.issue_id == 1)
            .expect("issue 1 item");
        assert_eq!(one.candidates.len(), 1, "issue 1 has one candidate mapping");
        assert!(
            !one.why_stopped.contains("No candidates found"),
            "collapsed header must not claim no candidates when a candidate exists; got {:?}",
            one.why_stopped,
        );
        assert_eq!(one.why_stopped, "1 candidate found: ambiguous title");

        let two = response
            .items
            .iter()
            .find(|item| item.issue_id == 2)
            .expect("issue 2 item");
        assert_eq!(
            two.candidates.len(),
            2,
            "issue 2 has N>1 candidate mappings"
        );
        assert!(
            !two.why_stopped.contains("No candidates found"),
            "collapsed header must not claim no candidates when candidates exist; got {:?}",
            two.why_stopped,
        );
        assert_eq!(two.why_stopped, "2 candidates found: ambiguous title");
    }

    #[tokio::test]
    async fn mutation_handlers_reach_database_write_boundary() {
        let Some(state) = test_support::test_state(2).await else {
            return;
        };
        let _guard = test_support::reset_for_test(&state).await;
        let user = AuthenticatedUser::for_test(1);
        let request = ActionRequest {
            external_identity_id: Some(1),
            rejection_reason: Some("not a match".to_string()),
            search_query: None,
        };

        let _ = confirm(State(state.clone()), user, Path(1), Json(request)).await;
        let _ = reject(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Path(1),
            Json(ActionRequest {
                external_identity_id: Some(1),
                rejection_reason: Some("not a match".to_string()),
                search_query: None,
            }),
        )
        .await;
        let _ = defer(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Path(1),
        )
        .await;
        let _ = skip(State(state), AuthenticatedUser::for_test(1), Path(1)).await;
    }

    /// A raw admin connection is needed only to simulate production's stale
    /// status constraint; the handler itself still runs as the DML-only role.
    async fn admin_client() -> tokio_postgres::Client {
        let (client, connection) = tokio_postgres::connect(
            &test_support::required_test_admin_url(),
            tokio_postgres::NoTls,
        )
        .await
        .expect("admin test connection");
        tokio::spawn(async move {
            let _ = connection.await;
        });
        client
    }

    /// Regression for #5378: production is stamped past the revision that
    /// added 'deferred' to the status allow-list, but its live constraint does
    /// not contain that value. Defer must succeed (and remove the item from the
    /// unresolved inbox) instead of failing with a check-violation 500.
    #[tokio::test]
    async fn defer_succeeds_when_status_constraint_predates_deferred_value() {
        let Some(state) = test_support::test_state(2).await else {
            return;
        };
        let _guard = test_support::reset_for_test(&state).await;
        let admin = admin_client().await;

        // Reproduce the deployed constraint from before c85700000001.
        admin
            .batch_execute(
                "ALTER TABLE issue_external_identity_mappings DROP CONSTRAINT IF EXISTS \
                 ck_issue_external_identity_status; \
                 ALTER TABLE issue_external_identity_mappings ADD CONSTRAINT \
                 ck_issue_external_identity_status CHECK (status IN \
                 ('unresolved','candidate','confirmed','rejected'));",
            )
            .await
            .expect("install stale status constraint");

        let conn = state.pool.get().await.unwrap();
        conn.batch_execute(
            "INSERT INTO users (id, username, is_admin, created_at) VALUES (1,'owner',false,NOW()); \
             INSERT INTO threads (id, user_id, title, format, issues_remaining, queue_position, status, manual_creator_credits, is_blocked, is_test, queue_position_is_manual, created_at) VALUES \
                 (1,1,'Owned','comics',1,0,'active','[]'::json,false,false,false,NOW()); \
             INSERT INTO issues (id, thread_id, issue_number, status, position, created_at) VALUES \
                 (1,1,'#6','unread',0,NOW()); \
             INSERT INTO external_identities (id, provider, entity_type, external_id, metadata_json, created_at, updated_at) VALUES \
                 (1,'comicvine','issue','901096','{}'::json,NOW(),NOW()); \
             INSERT INTO issue_external_identity_mappings \
                 (id, issue_id, external_identity_id, status, evidence_source, evidence_json, created_at, updated_at) VALUES \
                 (1,1,1,'unresolved','heuristic','{}'::json,NOW(),NOW());",
        )
        .await
        .unwrap();
        drop(conn);

        let response = defer(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Path(1),
        )
        .await;

        // Restore the canonical constraint before asserting so a failure here
        // cannot leak the stale schema into the next serialized test.
        admin
            .batch_execute(
                "ALTER TABLE issue_external_identity_mappings DROP CONSTRAINT IF EXISTS \
                 ck_issue_external_identity_status; \
                 ALTER TABLE issue_external_identity_mappings ADD CONSTRAINT \
                 ck_issue_external_identity_status CHECK (status IN \
                 ('unresolved','candidate','confirmed','rejected','deferred'));",
            )
            .await
            .expect("restore canonical status constraint");

        let body = response.expect("defer must succeed on a stale status constraint");
        assert!(body.success);
        assert_eq!(body.message, "Item deferred for later review");

        let conn = state.pool.get().await.unwrap();
        let row = conn
            .query_one(
                "SELECT status, rejection_reason FROM issue_external_identity_mappings WHERE id=1",
                &[],
            )
            .await
            .unwrap();
        let status: String = row.get(0);
        let reason: Option<String> = row.get(1);
        assert_eq!(status, "rejected");
        assert_eq!(reason.as_deref(), Some("deferred by user"));
        drop(conn);

        let list = list_inbox(
            State(state),
            AuthenticatedUser::for_test(1),
            Query(ListQuery {
                offset: None,
                limit: None,
            }),
        )
        .await
        .unwrap()
        .0;
        assert_eq!(list.total, 0);
    }
}
