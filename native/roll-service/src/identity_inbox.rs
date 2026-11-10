//! Owner-scoped identity reconciliation inbox.
//!
//! Rust replacement for the Python `/api/v1/identity-inbox/*` routes. The HTTP
//! method and exact path are preserved; only the implementation moves.

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::Arc;

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
    ApiError(StatusCode::BAD_REQUEST, detail.to_string())
}

fn not_found(detail: &str) -> ApiError {
    ApiError(StatusCode::NOT_FOUND, detail.to_string())
}

fn unprocessable(detail: &str) -> ApiError {
    ApiError(StatusCode::UNPROCESSABLE_ENTITY, detail.to_string())
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

fn why_stopped(status: &str, evidence: &Value) -> String {
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
             WHERE cm.issue_id = $1 AND cm.status IN ('candidate','confirmed','unresolved') \
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
        why_stopped: why_stopped(&status, &evidence),
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
        items.push(IdentityInboxItem {
            mapping_id,
            issue_id,
            thread_id,
            thread_title: thread_title.clone(),
            issue_number: issue_number.clone(),
            status: status.clone(),
            provider: Some(provider),
            source_entry_summary: source_entry_summary(&thread_title, &issue_number, &metadata),
            why_stopped: why_stopped(&status, &evidence),
            candidates: vec![],
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
    let _ = (state, user);
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
    let payload = tokio::task::spawn_blocking(move || fetch_comicvine(url))
        .await
        .ok()
        .flatten();

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

fn fetch_comicvine(url: String) -> Option<Value> {
    use native_tls::TlsConnector;
    use std::io::{Read, Write};
    let without = url.strip_prefix("https://")?;
    let (host, rest) = without.split_once('/')?;
    let path = format!("/{rest}");
    let addr = format!("{host}:443");
    let stream = std::net::TcpStream::connect(&addr).ok()?;
    let _ = stream.set_read_timeout(Some(std::time::Duration::from_secs(30)));
    let connector = TlsConnector::new().ok()?;
    let mut tls = connector.connect(host, stream).ok()?;
    let request = format!(
        "GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: ComicPile/1.0\r\nAccept: application/json\r\nConnection: close\r\n\r\n"
    );
    tls.write_all(request.as_bytes()).ok()?;
    let mut buf = Vec::new();
    tls.read_to_end(&mut buf).ok()?;
    let text = String::from_utf8_lossy(&buf);
    let body = text.split("\r\n\r\n").nth(1)?;
    serde_json::from_str(body).ok()
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
        "UPDATE issue_external_identity_mappings SET status='deferred', updated_at=NOW() WHERE id=$1",
        &[&mapping_id],
    )
    .await
    .map_err(db::query_error)?;
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
    path = "/api/v1/identity-inbox",
    tag = "identity-inbox",
    responses((status = 200, description = "ok", body = IdentityInboxResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v1/identity-inbox/search/issues",
    tag = "identity-inbox",
    responses((status = 200, description = "ok", body = IdentityInboxSearchResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn search_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v1/identity-inbox/{mapping_id}",
    tag = "identity-inbox",
    params(("mapping_id" = i32, Path, description = "Mapping id")),
    responses((status = 200, description = "ok", body = IdentityInboxResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/identity-inbox/{mapping_id}/confirm",
    tag = "identity-inbox",
    params(("mapping_id" = i32, Path, description = "Mapping id")),
    request_body = ActionRequest,
    responses((status = 200, description = "ok", body = IdentityInboxActionResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn confirm_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/identity-inbox/{mapping_id}/defer",
    tag = "identity-inbox",
    params(("mapping_id" = i32, Path, description = "Mapping id")),
    responses((status = 200, description = "ok", body = IdentityInboxActionResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn defer_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/identity-inbox/{mapping_id}/reject",
    tag = "identity-inbox",
    params(("mapping_id" = i32, Path, description = "Mapping id")),
    request_body = ActionRequest,
    responses((status = 200, description = "ok", body = IdentityInboxActionResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn reject_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/identity-inbox/{mapping_id}/skip",
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
}
