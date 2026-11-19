//! Native same-path handling for the ComicVine resolution family (#4835).
//!
//! Ports the browser-called `/api/v1/comicvine/*` operations from the Python
//! handler to Rust. Front-end URLs are unchanged.

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, outbound::OutboundHttp, ApiError, AppState};
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use chrono::{DateTime, Utc};
use http_body_util::BodyExt;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::Arc;

// ---------------------------------------------------------------------------
// Wire structs
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ComicVineSeriesResult {
    pub comicvine_volume_id: i32,
    pub name: String,
    pub publisher: Option<String>,
    pub start_year: Option<i32>,
    pub issue_count: Option<i32>,
    pub site_detail_url: Option<String>,
    pub image_url: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ComicVineSeriesSearchResponse {
    pub query: String,
    pub results: Vec<ComicVineSeriesResult>,
    pub total_available: Option<i32>,
    pub offset: i32,
    pub limit: i32,
    pub has_more: bool,
    pub next_offset: Option<i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ComicVineIssueCandidate {
    pub comicvine_issue_id: i32,
    pub issue_number: Option<String>,
    pub name: Option<String>,
    pub cover_date: Option<String>,
    pub store_date: Option<String>,
    pub image_url: Option<String>,
    pub site_detail_url: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ComicVineResolvedIssue {
    pub comicvine_issue_id: i32,
    pub series_name: Option<String>,
    pub volume_id: Option<i32>,
    pub issue_number: Option<String>,
    pub name: Option<String>,
    pub cover_date: Option<String>,
    pub store_date: Option<String>,
    pub image_url: Option<String>,
    pub site_detail_url: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ComicVineSeriesIssuesResponse {
    pub comicvine_volume_id: i32,
    pub series_name: String,
    pub issues: Vec<ComicVineIssueCandidate>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ComicVineResolveResponse {
    pub input: String,
    pub kind: String,
    pub validation_error: Option<String>,
    pub issue: Option<ComicVineResolvedIssue>,
    pub volume: Option<ComicVineSeriesResult>,
    pub issues: Vec<ComicVineIssueCandidate>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IssueIdentityMapping {
    pub external_identity_id: i32,
    pub provider: String,
    pub comicvine_id: String,
    pub status: String,
    pub confidence: Option<f64>,
    pub evidence_source: Option<String>,
    pub created_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IssueIdentityResponse {
    pub issue_id: i32,
    pub thread_id: i32,
    pub thread_title: String,
    pub has_confirmed_identity: bool,
    pub comicvine_issue_id: Option<String>,
    pub confirmed_mappings: Vec<IssueIdentityMapping>,
    pub candidate_mappings: Vec<IssueIdentityMapping>,
    pub has_unresolved: bool,
}

#[derive(Debug, Clone, Deserialize, utoipa::ToSchema)]
pub struct ConfirmIdentityRequest {
    pub comicvine_issue_id: i32,
}

#[derive(Debug, Clone, Deserialize, utoipa::ToSchema)]
pub struct ReplaceIdentityRequest {
    pub comicvine_issue_id: i32,
    pub reason: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct MetadataRefreshResponse {
    pub issue_id: i32,
    pub refreshed: bool,
    pub comicvine_issue_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct CanonicalCorrection {
    pub id: i32,
    pub field_name: String,
    pub provider_value: Option<String>,
    pub canonical_value: String,
    pub provenance: String,
    pub created_by: i32,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct MetadataCorrectionsResponse {
    pub issue_id: i32,
    pub corrections: Vec<CanonicalCorrection>,
}

#[derive(Debug, Clone, Deserialize, utoipa::ToSchema)]
pub struct MetadataCorrectionRequest {
    pub field_name: String,
    pub canonical_value: String,
    pub reason: Option<String>,
}

#[derive(Debug, Clone, Deserialize, utoipa::ToSchema)]
pub struct MetadataCorrectionRevertRequest {
    pub correction_id: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct SeriesImportStatusResponse {
    pub comicvine_volume_id: i32,
    pub imported: bool,
    pub thread_id: Option<i32>,
    pub series_name: Option<String>,
    pub issue_count: Option<i32>,
}

// ---------------------------------------------------------------------------
// Query structs
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
pub struct SearchQuery {
    q: String,
    #[serde(default = "default_limit")]
    limit: i32,
    #[serde(default)]
    offset: i32,
}

fn default_limit() -> i32 {
    10
}

#[derive(Debug, Deserialize)]
pub struct ResolveQuery {
    #[serde(rename = "input")]
    input: String,
}

#[derive(Debug, Deserialize)]
pub struct SeriesIssuesQuery {
    #[serde(default)]
    series_name: String,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn env_api_key() -> Option<String> {
    std::env::var("COMICVINE_API_KEY").ok().filter(|s| !s.trim().is_empty())
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

async fn fetch_json(
    state: &AppState,
    url: &str,
) -> Option<Value> {
    let without = url.strip_prefix("https://")?;
    let (host, rest) = without.split_once('/')?;
    let request = crate::outbound::OutboundRequest {
        method: http::Method::GET,
        path: format!("/{rest}"),
        headers: vec![
            ("user-agent".to_string(), "ComicPile/1.0".to_string()),
            ("accept".to_string(), "application/json".to_string()),
            ("connection".to_string(), "close".to_string()),
        ],
        body: bytes::Bytes::new(),
    };
    let outbound = state.outbound.clone();
    let response = outbound.send(host, request).await.ok()?;
    if !response.status.is_success() {
        return None;
    }
    let mut data = Vec::new();
    let mut body = response.body;
    while let Some(frame) = body.frame().await {
        let frame = frame.ok()?;
        if let Some(chunk) = frame.data_ref() {
            data.extend_from_slice(chunk);
            if data.len() > 5_000_000 {
                return None;
            }
        }
    }
    serde_json::from_slice(&data).ok()
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

pub async fn search_comicvine_series(
    State(state): State<Arc<AppState>>,
    _user: AuthenticatedUser,
    Query(q): Query<SearchQuery>,
) -> Result<Json<ComicVineSeriesSearchResponse>, ApiError> {
    let clamped_limit = q.limit.clamp(1, 100);
    let clamped_offset = q.offset.max(0);
    let page = clamped_offset / clamped_limit + 1;

    if env_api_key().is_none() || q.q.trim().is_empty() {
        return Ok(Json(ComicVineSeriesSearchResponse {
            query: q.q,
            results: vec![],
            total_available: Some(0),
            offset: clamped_offset,
            limit: clamped_limit,
            has_more: false,
            next_offset: None,
        }));
    }
    let api_key = env_api_key().unwrap();
    let field_list = "id,name,publisher,start_year,count_of_issues,site_detail_url,image";
    let url = format!(
        "https://comicvine.gamespot.com/api/search/?api_key={}&format=json&query={}&resources=volume&limit={}&page={}&field_list={}",
        percent_encode(&api_key),
        percent_encode(&q.q),
        clamped_limit,
        page,
        percent_encode(field_list),
    );
    let payload = fetch_json(&state, &url).await;
    let mut results = Vec::new();
    let mut total_available = 0i32;
    if let Some(p) = payload {
        if let Some(arr) = p.get("results").and_then(|v| v.as_array()) {
            for row in arr {
                let volume_id = row.get("id").and_then(|v| v.as_i64()).map(|v| v as i32);
                let name = row.get("name").and_then(|v| v.as_str());
                if volume_id.is_none() || name.is_none() {
                    continue;
                }
                let publisher = row.get("publisher").and_then(|v| {
                    if let Some(o) = v.as_object() {
                        o.get("name").and_then(|x| x.as_str()).map(str::to_string)
                    } else {
                        v.as_str().map(str::to_string)
                    }
                });
                let image_url = row.get("image").and_then(|v| {
                    v.as_object().and_then(|o| {
                        o.get("medium_url")
                            .or_else(|| o.get("small_url"))
                            .and_then(|x| x.as_str())
                            .map(str::to_string)
                    })
                });
                results.push(ComicVineSeriesResult {
                    comicvine_volume_id: volume_id.unwrap(),
                    name: name.unwrap().to_string(),
                    publisher,
                    start_year: row.get("start_year").and_then(|v| {
                        v.as_i64().map(|x| x as i32).or_else(|| v.as_str().and_then(|s| s.parse().ok()))
                    }),
                    issue_count: row.get("count_of_issues").and_then(|v| {
                        v.as_i64().map(|x| x as i32).or_else(|| v.as_str().and_then(|s| s.parse().ok()))
                    }),
                    site_detail_url: row.get("site_detail_url").and_then(|v| v.as_str()).map(str::to_string),
                    image_url,
                });
            }
        }
        total_available = p.get("number_of_total_results").and_then(|v| v.as_i64()).map(|x| x as i32).unwrap_or(results.len() as i32);
    }
    let loaded = clamped_offset + results.len() as i32;
    let has_more = loaded < total_available;
    Ok(Json(ComicVineSeriesSearchResponse {
        query: q.q,
        results,
        total_available: Some(total_available),
        offset: clamped_offset,
        limit: clamped_limit,
        has_more,
        next_offset: if has_more { Some(loaded) } else { None },
    }))
}

// ---------------------------------------------------------------------------
// Series issues
// ---------------------------------------------------------------------------

pub async fn get_comicvine_series_issues(
    State(state): State<Arc<AppState>>,
    _user: AuthenticatedUser,
    Path(comicvine_volume_id): Path<i32>,
    Query(q): Query<SeriesIssuesQuery>,
) -> Result<Json<ComicVineSeriesIssuesResponse>, ApiError> {
    let mut series_name = if q.series_name.is_empty() {
        format!("Volume {comicvine_volume_id}")
    } else {
        q.series_name.clone()
    };
    let mut issues: Vec<ComicVineIssueCandidate> = Vec::new();

    if let Some(api_key) = env_api_key() {
        // fetch volume metadata if name not provided
        if q.series_name.is_empty() {
            let url = format!(
                "https://comicvine.gamespot.com/api/volume/4050-{}/?api_key={}&format=json&field_list=name",
                comicvine_volume_id, percent_encode(&api_key)
            );
            if let Some(p) = fetch_json(&state, &url).await {
                if let Some(r) = p.get("results") {
                    if let Some(n) = r.get("name").and_then(|v| v.as_str()) {
                        series_name = n.to_string();
                    }
                }
            }
        }
        // fetch issues pages
        let mut offset = 0i32;
        loop {
            let url = format!(
                "https://comicvine.gamespot.com/api/volume/4050-{}/issues/?api_key={}&format=json&offset={}&limit=100&field_list=id,issue_number,name,cover_date,store_date,image,site_detail_url",
                comicvine_volume_id, percent_encode(&api_key), offset
            );
            match fetch_json(&state, &url).await {
                Some(p) => {
                    let arr = p.get("results").and_then(|v| v.as_array()).cloned().unwrap_or_default();
                    if arr.is_empty() {
                        break;
                    }
                    for row in &arr {
                        let id = row.get("id").and_then(|v| v.as_i64()).map(|x| x as i32);
                        if id.is_none() {
                            continue;
                        }
                        let image_url = row.get("image").and_then(|v| {
                            v.as_object().and_then(|o| {
                                o.get("small_url")
                                    .or_else(|| o.get("thumb_url"))
                                    .and_then(|x| x.as_str())
                                    .map(str::to_string)
                            })
                        });
                        issues.push(ComicVineIssueCandidate {
                            comicvine_issue_id: id.unwrap(),
                            issue_number: row.get("issue_number").map(|v| {
                                if let Some(s) = v.as_str() { s.to_string() } else { v.to_string() }
                            }),
                            name: row.get("name").and_then(|v| v.as_str()).map(str::to_string),
                            cover_date: row.get("cover_date").and_then(|v| v.as_str()).map(str::to_string),
                            store_date: row.get("store_date").and_then(|v| v.as_str()).map(str::to_string),
                            image_url,
                            site_detail_url: row.get("site_detail_url").and_then(|v| v.as_str()).map(str::to_string),
                        });
                    }
                    if arr.len() < 100 {
                        break;
                    }
                    offset += arr.len() as i32;
                }
                None => break,
            }
        }
    }

    Ok(Json(ComicVineSeriesIssuesResponse {
        comicvine_volume_id,
        series_name,
        issues,
    }))
}

// ---------------------------------------------------------------------------
// Resolve
// ---------------------------------------------------------------------------

fn parse_comicvine_url(raw: &str) -> Option<(String, i32)> {
    // returns (kind, id)
    let value = raw.trim();
    if value.is_empty() {
        return None;
    }
    let url = if value.contains("://") {
        value.to_string()
    } else {
        format!("https://{value}")
    };
    // parse host
    let without_scheme = url.split("://").nth(1)?;
    let host_part = without_scheme.split('/').next()?;
    let host = host_part.split(':').next()?.to_lowercase();
    if host != "comicvine.gamespot.com" && host != "www.comicvine.gamespot.com" {
        return None;
    }
    // path segments
    let path = without_scheme.split('?').next()?.split('#').next()?;
    let segments: Vec<&str> = path.split('/').filter(|s| !s.is_empty()).collect();
    if segments.is_empty() {
        return None;
    }
    let last = segments[segments.len() - 1];
    // match 4000-id or 4050-id
    let parts: Vec<&str> = last.split('-').collect();
    if parts.len() != 2 {
        return None;
    }
    let prefix = parts[0];
    let id: i32 = parts[1].parse().ok()?;
    let kind = if prefix == "4000" {
        "issue"
    } else if prefix == "4050" {
        "volume"
    } else {
        return None;
    };
    Some((kind.to_string(), id))
}

pub async fn resolve_comicvine_input(
    State(state): State<Arc<AppState>>,
    _user: AuthenticatedUser,
    Query(q): Query<ResolveQuery>,
) -> Result<Json<ComicVineResolveResponse>, ApiError> {
    let input = q.input.clone();
    // if URL
    if let Some((kind, id)) = parse_comicvine_url(&input) {
        if kind == "issue" {
            // fetch issue
            if let Some(api_key) = env_api_key() {
                let url = format!(
                    "https://comicvine.gamespot.com/api/issue/4000-{}/?api_key={}&format=json&field_list=id,name,issue_number,cover_date,store_date,image,site_detail_url,volume",
                    id, percent_encode(&api_key)
                );
                if let Some(p) = fetch_json(&state, &url).await {
                    let r = p.get("results");
                    if let Some(r) = r {
                        let volume_id = r.get("volume").and_then(|v| v.get("id")).and_then(|x| x.as_i64()).map(|x| x as i32);
                        let series_name = r.get("volume").and_then(|v| v.get("name")).and_then(|x| x.as_str()).map(str::to_string);
                        let image_url = r.get("image").and_then(|v| {
                            v.as_object().and_then(|o| {
                                o.get("medium_url").or_else(|| o.get("small_url")).and_then(|x| x.as_str()).map(str::to_string)
                            })
                        });
                        let issue = ComicVineResolvedIssue {
                            comicvine_issue_id: id,
                            series_name,
                            volume_id,
                            issue_number: r.get("issue_number").map(|v| if let Some(s)=v.as_str(){s.to_string()} else {v.to_string()}),
                            name: r.get("name").and_then(|v| v.as_str()).map(str::to_string),
                            cover_date: r.get("cover_date").and_then(|v| v.as_str()).map(str::to_string),
                            store_date: r.get("store_date").and_then(|v| v.as_str()).map(str::to_string),
                            image_url,
                            site_detail_url: r.get("site_detail_url").and_then(|v| v.as_str()).map(str::to_string),
                        };
                        return Ok(Json(ComicVineResolveResponse {
                            input,
                            kind: "issue".to_string(),
                            validation_error: None,
                            issue: Some(issue),
                            volume: None,
                            issues: vec![],
                        }));
                    }
                }
                // provider failure
                return Ok(Json(ComicVineResolveResponse {
                    input,
                    kind: "search".to_string(),
                    validation_error: Some("Failed to resolve ComicVine issue".to_string()),
                    issue: None,
                    volume: None,
                    issues: vec![],
                }));
            }
            return Ok(Json(ComicVineResolveResponse {
                input,
                kind: "search".to_string(),
                validation_error: Some("ComicVine API key not configured".to_string()),
                issue: None,
                volume: None,
                issues: vec![],
            }));
        } else if kind == "volume" {
            // fetch volume + issues
            let mut volume: Option<ComicVineSeriesResult> = None;
            let mut issues: Vec<ComicVineIssueCandidate> = Vec::new();
            if let Some(api_key) = env_api_key() {
                let url = format!(
                    "https://comicvine.gamespot.com/api/volume/4050-{}/?api_key={}&format=json&field_list=id,name,publisher,start_year,count_of_issues,site_detail_url,image",
                    id, percent_encode(&api_key)
                );
                if let Some(p) = fetch_json(&state, &url).await {
                    if let Some(r) = p.get("results") {
                        volume = Some(ComicVineSeriesResult {
                            comicvine_volume_id: id,
                            name: r.get("name").and_then(|v| v.as_str()).unwrap_or(&format!("Volume {id}")).to_string(),
                            publisher: r.get("publisher").and_then(|v| {
                                if let Some(o)=v.as_object(){o.get("name").and_then(|x|x.as_str()).map(str::to_string)} else {v.as_str().map(str::to_string)}
                            }),
                            start_year: r.get("start_year").and_then(|v| v.as_i64().map(|x|x as i32).or_else(|| v.as_str().and_then(|s|s.parse().ok()))),
                            issue_count: r.get("count_of_issues").and_then(|v| v.as_i64().map(|x|x as i32).or_else(|| v.as_str().and_then(|s|s.parse().ok()))),
                            site_detail_url: r.get("site_detail_url").and_then(|v| v.as_str()).map(str::to_string),
                            image_url: r.get("image").and_then(|v| v.as_object().and_then(|o| o.get("medium_url").or_else(||o.get("small_url")).and_then(|x|x.as_str()).map(str::to_string))),
                        });
                    }
                }
                // fetch issues
                let mut offset = 0i32;
                loop {
                    let url = format!(
                        "https://comicvine.gamespot.com/api/volume/4050-{}/issues/?api_key={}&format=json&offset={}&limit=100&field_list=id,issue_number,name,cover_date,store_date,image,site_detail_url",
                        id, percent_encode(&api_key), offset
                    );
                    match fetch_json(&state, &url).await {
                        Some(p) => {
                            let arr = p.get("results").and_then(|v| v.as_array()).cloned().unwrap_or_default();
                            if arr.is_empty() { break; }
                            for row in &arr {
                                let iid = row.get("id").and_then(|v| v.as_i64()).map(|x| x as i32);
                                if iid.is_none() { continue; }
                                let image_url = row.get("image").and_then(|v| v.as_object().and_then(|o| o.get("small_url").or_else(||o.get("thumb_url")).and_then(|x|x.as_str()).map(str::to_string)));
                                issues.push(ComicVineIssueCandidate {
                                    comicvine_issue_id: iid.unwrap(),
                                    issue_number: row.get("issue_number").map(|v| if let Some(s)=v.as_str(){s.to_string()} else {v.to_string()}),
                                    name: row.get("name").and_then(|v| v.as_str()).map(str::to_string),
                                    cover_date: row.get("cover_date").and_then(|v| v.as_str()).map(str::to_string),
                                    store_date: row.get("store_date").and_then(|v| v.as_str()).map(str::to_string),
                                    image_url,
                                    site_detail_url: row.get("site_detail_url").and_then(|v| v.as_str()).map(str::to_string),
                                });
                            }
                            if arr.len() < 100 { break; }
                            offset += arr.len() as i32;
                        }
                        None => break,
                    }
                }
            }
            return Ok(Json(ComicVineResolveResponse {
                input,
                kind: "volume".to_string(),
                validation_error: None,
                issue: None,
                volume,
                issues,
            }));
        }
    }
    // search kind
    Ok(Json(ComicVineResolveResponse {
        input,
        kind: "search".to_string(),
        validation_error: None,
        issue: None,
        volume: None,
        issues: vec![],
    }))
}

// ---------------------------------------------------------------------------
// DB helpers
// ---------------------------------------------------------------------------

async fn owned_issue_thread(
    conn: &deadpool_postgres::Object,
    issue_id: i32,
    user_id: i32,
) -> Result<(i32, String), ApiError> {
    // returns (thread_id, thread_title)
    let row = conn
        .query_opt(
            "SELECT t.id, t.title FROM threads t JOIN issues i ON i.thread_id = t.id WHERE i.id = $1 AND t.user_id = $2",
            &[&issue_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    match row {
        Some(r) => Ok((r.get(0), r.get(1))),
        None => Err(ApiError::NotFound(format!("Issue {} not found", issue_id))),
    }
}

// ---------------------------------------------------------------------------
// Identity GET
// ---------------------------------------------------------------------------

pub async fn get_issue_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    let conn = db::checkout(&state).await?;
    let (thread_id, thread_title) = owned_issue_thread(&conn, issue_id, user.id()).await?;

    let rows = conn
        .query(
            "SELECT m.id, m.external_identity_id, e.provider, e.external_id, m.status, m.confidence, m.evidence_source, m.created_at::text, e.id \
             FROM issue_external_identity_mappings m JOIN external_identities e ON e.id = m.external_identity_id \
             WHERE m.issue_id = $1 ORDER BY m.confidence DESC NULLS LAST",
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?;

    let mut confirmed = Vec::new();
    let mut candidates = Vec::new();
    let mut has_unresolved = false;
    for row in rows {
        let mapping = IssueIdentityMapping {
            external_identity_id: row.get(1),
            provider: row.get(2),
            comicvine_id: row.get(3),
            status: row.get(4),
            confidence: row.get(5),
            evidence_source: row.get(6),
            created_at: row.get(7),
        };
        let status: String = row.get(4);
        if status == "confirmed" {
            confirmed.push(mapping);
        } else if status == "candidate" {
            candidates.push(mapping);
        } else if status == "unresolved" {
            has_unresolved = true;
        }
    }
    let comicvine_issue_id = confirmed.first().map(|m| m.comicvine_id.clone());

    Ok(Json(IssueIdentityResponse {
        issue_id,
        thread_id,
        thread_title,
        has_confirmed_identity: !confirmed.is_empty(),
        comicvine_issue_id,
        confirmed_mappings: confirmed,
        candidate_mappings: candidates,
        has_unresolved,
    }))
}

// ---------------------------------------------------------------------------
// Confirm
// ---------------------------------------------------------------------------

pub async fn confirm_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
    Json(req): Json<ConfirmIdentityRequest>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    // ownership
    let mut conn = db::checkout(&state).await?;
    // verify owned
    let exists = conn
        .query_opt(
            "SELECT 1 FROM issues i JOIN threads t ON t.id=i.thread_id WHERE i.id=$1 AND t.user_id=$2",
            &[&issue_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    if exists.is_none() {
        return Err(ApiError::NotFound(format!("Issue {} not found", issue_id)));
    }

    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;

    // upsert external identity
    let external_id = req.comicvine_issue_id.to_string();
    let url = format!("https://comicvine.gamespot.com/issue/4000-{}/", req.comicvine_issue_id);
    let row = tx
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, external_url, metadata_json, created_at, updated_at) \
             VALUES ('comicvine','issue',$1,$2,'{}'::jsonb, now(), now()) \
             ON CONFLICT (provider, entity_type, external_id) DO UPDATE SET external_url=COALESCE(EXCLUDED.external_url, external_identities.external_url), updated_at=now() \
             RETURNING id",
            &[&external_id, &url],
        )
        .await
        .map_err(db::query_error)?;
    let identity_id: i32 = row.get(0);

    // conflict check: existing confirmed mapping for same provider
    let conflict = tx
        .query_opt(
            "SELECT m.id FROM issue_external_identity_mappings m JOIN external_identities e ON e.id=m.external_identity_id \
             WHERE m.issue_id=$1 AND m.status='confirmed' AND e.provider='comicvine' AND m.external_identity_id <> $2 LIMIT 1",
            &[&issue_id, &identity_id],
        )
        .await
        .map_err(db::query_error)?;
    if conflict.is_some() {
        tx.rollback().await.ok();
        return Err(ApiError::BadRequest("issue already has a confirmed comicvine identity".to_string()));
    }

    // upsert mapping: if existing mapping for this issue+identity update status, else insert
    // Check existing
    let existing = tx
        .query_opt(
            "SELECT id FROM issue_external_identity_mappings WHERE issue_id=$1 AND external_identity_id=$2",
            &[&issue_id, &identity_id],
        )
        .await
        .map_err(db::query_error)?;
    if let Some(r) = existing {
        let mid: i32 = r.get(0);
        tx.execute(
            "UPDATE issue_external_identity_mappings SET status='confirmed', evidence_source='user_confirmed', confidence=1.0, updated_at=now() WHERE id=$1",
            &[&mid],
        )
        .await
        .map_err(db::query_error)?;
    } else {
        tx.execute(
            "INSERT INTO issue_external_identity_mappings (issue_id, external_identity_id, status, evidence_source, confidence, created_at, updated_at) VALUES ($1,$2,'confirmed','user_confirmed',1.0,now(),now())",
            &[&issue_id, &identity_id],
        )
        .await
        .map_err(db::query_error)?;
    }

    tx.commit().await.map_err(db::query_error)?;

    // return identity state
    get_issue_identity(State(state), user, Path(issue_id)).await
}

// ---------------------------------------------------------------------------
// Replace
// ---------------------------------------------------------------------------

pub async fn replace_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
    Json(req): Json<ReplaceIdentityRequest>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let exists = conn
        .query_opt(
            "SELECT 1 FROM issues i JOIN threads t ON t.id=i.thread_id WHERE i.id=$1 AND t.user_id=$2",
            &[&issue_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    if exists.is_none() {
        return Err(ApiError::NotFound(format!("Issue {} not found", issue_id)));
    }

    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;

    // demote old confirmed mappings
    tx.execute(
        "UPDATE issue_external_identity_mappings m SET status='rejected', rejection_reason=$2, updated_at=now() \
         FROM external_identities e WHERE m.external_identity_id=e.id AND m.issue_id=$1 AND m.status='confirmed' AND e.provider='comicvine'",
        &[&issue_id, &req.reason.clone().unwrap_or_else(|| "replaced by user".to_string())],
    )
    .await
    .map_err(db::query_error)?;

    tx.commit().await.map_err(db::query_error)?;

    // now confirm new
    confirm_identity(State(state), user, Path(issue_id), Json(ConfirmIdentityRequest { comicvine_issue_id: req.comicvine_issue_id })).await
}

// ---------------------------------------------------------------------------
// Remove
// ---------------------------------------------------------------------------

pub async fn remove_identity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
) -> Result<Json<IssueIdentityResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let exists = conn
        .query_opt(
            "SELECT 1 FROM issues i JOIN threads t ON t.id=i.thread_id WHERE i.id=$1 AND t.user_id=$2",
            &[&issue_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    if exists.is_none() {
        return Err(ApiError::NotFound(format!("Issue {} not found", issue_id)));
    }

    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;

    // find confirmed mapping
    let mapping = tx
        .query_opt(
            "SELECT m.id FROM issue_external_identity_mappings m JOIN external_identities e ON e.id=m.external_identity_id \
             WHERE m.issue_id=$1 AND m.status='confirmed' AND e.provider='comicvine'",
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?;
    let mid: i32 = match mapping {
        Some(r) => r.get(0),
        None => {
            tx.rollback().await.ok();
            return Err(ApiError::BadRequest(format!("No confirmed ComicVine identity mapping found for issue {}", issue_id)));
        }
    };
    tx.execute(
        "UPDATE issue_external_identity_mappings SET status='unresolved', evidence_source=NULL, confidence=NULL, updated_at=now() WHERE id=$1",
        &[&mid],
    )
    .await
    .map_err(db::query_error)?;

    tx.commit().await.map_err(db::query_error)?;

    get_issue_identity(State(state), user, Path(issue_id)).await
}

// ---------------------------------------------------------------------------
// Refresh
// ---------------------------------------------------------------------------

pub async fn refresh_metadata(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
) -> Result<Json<MetadataRefreshResponse>, ApiError> {
    let conn = db::checkout(&state).await?;
    let (thread_id, _) = owned_issue_thread(&conn, issue_id, user.id()).await?;
    let _ = thread_id;

    // find confirmed comicvine identity
    let row = conn
        .query_opt(
            "SELECT e.external_id FROM issue_external_identity_mappings m JOIN external_identities e ON e.id=m.external_identity_id \
             WHERE m.issue_id=$1 AND m.status='confirmed' AND e.provider='comicvine' LIMIT 1",
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?;
    let cid: Option<String> = row.map(|r| r.get(0));
    Ok(Json(MetadataRefreshResponse {
        issue_id,
        refreshed: cid.is_some(),
        comicvine_issue_id: cid,
    }))
}

// ---------------------------------------------------------------------------
// Corrections list
// ---------------------------------------------------------------------------

pub async fn list_corrections(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
) -> Result<Json<MetadataCorrectionsResponse>, ApiError> {
    let conn = db::checkout(&state).await?;
    let _ = owned_issue_thread(&conn, issue_id, user.id()).await?;

    let rows = conn
        .query(
            "SELECT id, field_name, provider_value, canonical_value, provenance, created_by, created_at::text \
             FROM issue_metadata_corrections WHERE issue_id=$1 AND reverted_at IS NULL ORDER BY created_at DESC",
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?;
    let mut corrections = Vec::new();
    for row in rows {
        corrections.push(CanonicalCorrection {
            id: row.get(0),
            field_name: row.get(1),
            provider_value: row.get(2),
            canonical_value: row.get(3),
            provenance: row.get(4),
            created_by: row.get(5),
            created_at: row.get(6),
        });
    }
    Ok(Json(MetadataCorrectionsResponse { issue_id, corrections }))
}

// ---------------------------------------------------------------------------
// Apply correction
// ---------------------------------------------------------------------------

pub async fn apply_correction(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
    Json(req): Json<MetadataCorrectionRequest>,
) -> Result<Json<MetadataCorrectionsResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let _ = owned_issue_thread(&conn, issue_id, user.id()).await?;

    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;

    tx.execute(
        "INSERT INTO issue_metadata_corrections (issue_id, field_name, provider_value, canonical_value, provenance, created_by, created_at, updated_at) \
         VALUES ($1,$2,NULL,$3,'user_correction',$4,now(),now())",
        &[&issue_id, &req.field_name, &req.canonical_value, &user.id()],
    )
    .await
    .map_err(db::query_error)?;

    tx.commit().await.map_err(db::query_error)?;

    // return list
    list_corrections(State(state), user, Path(issue_id)).await
}

// ---------------------------------------------------------------------------
// Revert correction
// ---------------------------------------------------------------------------

pub async fn revert_correction(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
    Json(req): Json<MetadataCorrectionRevertRequest>,
) -> Result<Json<MetadataCorrectionsResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let _ = owned_issue_thread(&conn, issue_id, user.id()).await?;

    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;

    tx.execute(
        "UPDATE issue_metadata_corrections SET reverted_at=now(), updated_at=now() WHERE id=$1 AND issue_id=$2 AND reverted_at IS NULL",
        &[&req.correction_id, &issue_id],
    )
    .await
    .map_err(db::query_error)?;

    tx.commit().await.map_err(db::query_error)?;

    list_corrections(State(state), user, Path(issue_id)).await
}

// ---------------------------------------------------------------------------
// Series import status (already migrated)
// ---------------------------------------------------------------------------

pub async fn series_import_status(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(comicvine_volume_id): Path<i32>,
) -> Result<Json<SeriesImportStatusResponse>, ApiError> {
    let conn = db::checkout(&state).await?;
    let volume_id = comicvine_volume_id.to_string();
    let row = conn
        .query_opt(
            "SELECT t.id, t.title, t.total_issues FROM threads t JOIN thread_external_series_mappings m ON m.thread_id = t.id JOIN external_identities e ON e.id = m.external_identity_id WHERE t.user_id = $1 AND m.status = 'confirmed' AND e.entity_type = 'series' AND e.provider = 'comicvine' AND e.external_id = $2 ORDER BY m.id LIMIT 1",
            &[&user.id(), &volume_id],
        )
        .await
        .map_err(db::query_error)?;
    let response = match row {
        Some(r) => SeriesImportStatusResponse {
            comicvine_volume_id,
            imported: true,
            thread_id: Some(r.get(0)),
            series_name: Some(r.get(1)),
            issue_count: r.get(2),
        },
        None => SeriesImportStatusResponse {
            comicvine_volume_id,
            imported: false,
            thread_id: None,
            series_name: None,
            issue_count: None,
        },
    };
    Ok(Json(response))
}

// ---------------------------------------------------------------------------
// OpenAPI docs (stubs)
// ---------------------------------------------------------------------------

#[utoipa::path(get, path = "/api/v1/comicvine/search/series", tag = "comicvine-resolution", responses((status = 200, description = "ok", body = ComicVineSeriesSearchResponse)), security(("HTTPBearer" = [])))]
#[allow(dead_code)]
pub fn search_comicvine_series_documentation() {}

#[utoipa::path(get, path = "/api/v1/comicvine/series/{comicvine_volume_id}/import-status", tag = "comicvine-resolution", responses((status = 200, description = "ok", body = SeriesImportStatusResponse)), security(("HTTPBearer" = [])))]
#[allow(dead_code)]
pub fn series_import_status_documentation() {}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_url_issue() {
        assert_eq!(parse_comicvine_url("https://comicvine.gamespot.com/x/4000-5/"), Some(("issue".to_string(), 5)));
    }
    #[test]
    fn parse_url_volume() {
        assert_eq!(parse_comicvine_url("https://comicvine.gamespot.com/x/4050-9/"), Some(("volume".to_string(), 9)));
    }
}
