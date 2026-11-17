//! Same-path Rust cutover for browser-called reading-plan-sync operations
//! (#4851, parent #4335).
//!
//! Preserves the Python `app/api/reading_plan_sync.py` wire contract at the
//! same HTTP method and exact path:
//!
//! * `GET /api/v1/reading-plan-sync/status`
//! * `POST /api/v1/reading-plan-sync/sync`
//!
//! Status is a direct read of persisted release-source state. The sync POST
//! mirrors the user-triggered `sync_released_issues` behavior: evaluate only
//! the authenticated user's enabled sources, adopt released ComicVine issues,
//! and preserve Python wire/auth/ownership/SQL/transaction semantics.
//! Full parity, authenticated production Rust-execution proof, and Python
//! handler/mount cleanup remain tracked under #4851 acceptance gates.

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{extract::State, Json};
use bytes::Bytes;
use chrono::{DateTime, SecondsFormat, Utc};
use http_body_util::{BodyExt, Empty};
use hyper::client::conn::http1;
use hyper_util::rt::TokioIo;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

const COMICVINE_HOST: &str = "comicvine.gamespot.com";
const PROVIDER_TIMEOUT: Duration = Duration::from_secs(30);
const MAX_BODY: usize = 2_000_000;

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct SyncRequest {
    #[schema(value_type = String, format = "date-time")]
    pub as_of: String,
    #[serde(default = "default_refresh")]
    pub refresh: bool,
}

fn default_refresh() -> bool {
    true
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SourceSyncFailure {
    pub source_id: i32,
    pub plan_id: i32,
    pub thread_id: i32,
    pub volume_id: i32,
    pub error: String,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SyncReport {
    pub total_sources: i64,
    pub enabled_sources: i64,
    pub checked_sources: i64,
    pub successful_sources: i64,
    pub failed_sources: i64,
    pub issues_checked: i64,
    pub created_issues: i64,
    pub reused_issues: i64,
    pub future_skips: i64,
    pub unknown_date_skips: i64,
    pub conflicts: i64,
    pub issue_failures: i64,
    #[serde(default)]
    pub excluded_sources: i64,
    #[serde(default)]
    pub excluded_issues: i64,
    #[serde(default)]
    pub skipped_sources: i64,
    pub failures: Vec<SourceSyncFailure>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SyncResponse {
    pub success: bool,
    pub message: String,
    pub result: SyncReport,
}

const STATUS_SQL: &str = "SELECT rps.id, rps.plan_id, rps.thread_id, \
     rps.external_identity_id, ei.external_id, rps.enabled, rps.last_synced_at \
     FROM reading_plan_release_sources rps \
     JOIN continuity_plans cp ON cp.id = rps.plan_id \
     JOIN external_identities ei ON ei.id = rps.external_identity_id \
     WHERE cp.user_id = $1 \
     ORDER BY rps.created_at";

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SyncStatusSource {
    pub id: i32,
    pub reading_plan_id: i32,
    pub thread_id: i32,
    pub external_identity_id: i32,
    pub provider_volume_id: String,
    pub enabled: bool,
    pub last_synced_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SyncStatusResponse {
    pub total_sources: i64,
    pub enabled_sources: i64,
    pub sources: Vec<SyncStatusSource>,
}

/// Wire parity with Python `SyncStatusSource.last_synced_at`
/// (`app/schemas/reading_plan_sync.py`): Pydantic v2 renders a UTC
/// `datetime` as RFC 3339 with a `Z` suffix and omits fractional seconds
/// when they are zero, so the native response must match byte for byte.
fn format_synced_at(value: DateTime<Utc>) -> String {
    let precision = if value.timestamp_subsec_micros() == 0 {
        SecondsFormat::Secs
    } else {
        SecondsFormat::Micros
    };
    value.to_rfc3339_opts(precision, true)
}

pub async fn get_sync_status(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> Result<Json<SyncStatusResponse>, ApiError> {
    let connection = db::checkout(&state).await?;
    let rows = connection
        .query(STATUS_SQL, &[&user.id()])
        .await
        .map_err(db::query_error)?;
    let mut sources = Vec::with_capacity(rows.len());
    let mut enabled: i64 = 0;
    for row in &rows {
        let enabled_flag: bool = row.get(5);
        if enabled_flag {
            enabled += 1;
        }
        sources.push(SyncStatusSource {
            id: row.get(0),
            reading_plan_id: row.get(1),
            thread_id: row.get(2),
            external_identity_id: row.get(3),
            provider_volume_id: row.get(4),
            enabled: enabled_flag,
            last_synced_at: row.get::<_, Option<DateTime<Utc>>>(6).map(format_synced_at),
        });
    }
    Ok(Json(SyncStatusResponse {
        total_sources: rows.len() as i64,
        enabled_sources: enabled,
        sources,
    }))
}

fn report_message(report: &SyncReport) -> String {
    format!(
        "Sync completed: {} successful, {} failed, {} created, {} reused, {} sources and {} issues excluded",
        report.successful_sources,
        report.failed_sources,
        report.created_issues,
        report.reused_issues,
        report.excluded_sources,
        report.excluded_issues
    )
}

fn parse_as_of(value: &str) -> Result<DateTime<Utc>, ApiError> {
    if let Ok(dt) = DateTime::parse_from_rfc3339(value) {
        return Ok(dt.with_timezone(&Utc));
    }
    if let Ok(naive) = chrono::NaiveDateTime::parse_from_str(value, "%Y-%m-%dT%H:%M:%S%.f") {
        return Ok(DateTime::<Utc>::from_naive_utc_and_offset(naive, Utc));
    }
    if let Ok(naive) = chrono::NaiveDateTime::parse_from_str(value, "%Y-%m-%dT%H:%M:%S") {
        return Ok(DateTime::<Utc>::from_naive_utc_and_offset(naive, Utc));
    }
    if let Ok(naive) = chrono::NaiveDateTime::parse_from_str(value, "%Y-%m-%d %H:%M:%S%.f") {
        return Ok(DateTime::<Utc>::from_naive_utc_and_offset(naive, Utc));
    }
    if let Ok(naive) = chrono::NaiveDateTime::parse_from_str(value, "%Y-%m-%d %H:%M:%S") {
        return Ok(DateTime::<Utc>::from_naive_utc_and_offset(naive, Utc));
    }
    Err(ApiError::Unprocessable(
        "as_of must be a valid datetime".to_string(),
    ))
}

fn parse_store_date(value: Option<&Value>) -> Option<DateTime<Utc>> {
    let value = value?;
    if value.is_null() {
        return None;
    }
    let text = value.as_str()?.trim();
    if text.is_empty() {
        return None;
    }
    let normalized = if text.ends_with(['Z', 'z']) {
        format!("{}+00:00", &text[..text.len() - 1])
    } else {
        text.to_string()
    };
    if let Ok(dt) = DateTime::parse_from_rfc3339(&normalized) {
        return Some(dt.with_timezone(&Utc));
    }
    if normalized.len() == 10
        && normalized.chars().nth(4) == Some('-')
        && normalized.chars().nth(7) == Some('-')
    {
        if let Ok(date) = chrono::NaiveDate::parse_from_str(&normalized, "%Y-%m-%d") {
            return date
                .and_hms_opt(0, 0, 0)
                .map(|naive| DateTime::<Utc>::from_naive_utc_and_offset(naive, Utc));
        }
    }
    None
}

#[derive(Debug, Clone)]
struct EnabledSourceRow {
    source_id: i32,
    plan_id: i32,
    thread_id: i32,
    external_identity_id: i32,
    provider_volume_id: String,
}

#[derive(Debug, Default)]
struct Exclusions {
    volume_ids: std::collections::HashSet<i32>,
    thread_ids: std::collections::HashSet<i32>,
    issue_ids: std::collections::HashSet<i32>,
}

impl Exclusions {
    fn excludes_source(&self, thread_id: i32, volume_id: i32) -> bool {
        self.thread_ids.contains(&thread_id) || self.volume_ids.contains(&volume_id)
    }
}

async fn load_release_exclusions(
    connection: &deadpool_postgres::Client,
    user_id: i32,
) -> Result<Exclusions, ApiError> {
    let rows = connection
        .query(
            "SELECT provider, external_volume_id, thread_id, issue_id \
             FROM collection_exclusions WHERE user_id = $1 ORDER BY id",
            &[&user_id],
        )
        .await
        .map_err(db::query_error)?;
    let mut out = Exclusions::default();
    for row in &rows {
        let provider: Option<String> = row.get(0);
        let external_volume_id: Option<String> = row.get(1);
        let thread_id: Option<i32> = row.get(2);
        let issue_id: Option<i32> = row.get(3);
        if let Some(tid) = thread_id {
            out.thread_ids.insert(tid);
        }
        if let Some(iid) = issue_id {
            out.issue_ids.insert(iid);
        }
        if provider.as_deref() == Some("comicvine") {
            if let Some(vol) = external_volume_id {
                let text = vol.trim().strip_prefix("4050-").unwrap_or(vol.trim());
                if !text.chars().all(|c| c.is_ascii_digit()) || text.is_empty() {
                    return Err(ApiError::Internal(
                        "Collection exclusion has an invalid ComicVine volume identity".to_string(),
                    ));
                }
                if let Ok(id) = text.parse::<i32>() {
                    out.volume_ids.insert(id);
                }
            }
        }
    }
    Ok(out)
}

#[allow(dead_code)]
fn parse_ordinary_issue_number(issue_number: &str) -> Option<i64> {
    if issue_number.is_empty() {
        return None;
    }
    let bytes = issue_number.as_bytes();
    if bytes[0] == b'0' {
        return None;
    }
    if !bytes.iter().all(|b| b.is_ascii_digit()) {
        return None;
    }
    issue_number.parse::<i64>().ok().filter(|n| *n > 0)
}

#[allow(dead_code)]
fn natural_issue_order(existing: &[String], new_numbers: &[String]) -> Option<Vec<String>> {
    let mut incoming: Vec<(i64, String)> = Vec::new();
    for issue_number in new_numbers {
        let value = parse_ordinary_issue_number(issue_number)?;
        incoming.push((value, issue_number.clone()));
    }

    let existing_numbered: Vec<(i64, String)> = existing
        .iter()
        .filter_map(|n| parse_ordinary_issue_number(n).map(|v| (v, n.clone())))
        .collect();

    if existing_numbered.len() == existing.len() {
        let mut merged = existing_numbered;
        merged.extend(incoming);
        merged.sort_by_key(|(n, _)| *n);
        return Some(merged.into_iter().map(|(_, s)| s).collect());
    }

    if existing_numbered.is_empty() {
        return None;
    }
    let numbers: Vec<i64> = existing_numbered.iter().map(|(n, _)| *n).collect();
    if numbers.windows(2).any(|w| w[0] > w[1]) {
        return None;
    }

    let mut result: Vec<String> = existing.to_vec();
    incoming.sort_by_key(|(n, _)| *n);
    for (number, label) in incoming {
        let mut inserted = false;
        for idx in 0..result.len() {
            if let Some(existing_number) = parse_ordinary_issue_number(&result[idx]) {
                if existing_number > number {
                    result.insert(idx, label.clone());
                    inserted = true;
                    break;
                }
            }
        }
        if !inserted {
            result.push(label);
        }
    }
    Some(result)
}

fn issue_identity(row: &Value) -> Option<String> {
    let raw = row.get("id")?;
    if raw.is_null() {
        return None;
    }
    let text = if let Some(s) = raw.as_str() {
        s.trim().to_string()
    } else {
        raw.to_string().trim_matches('"').trim().to_string()
    };
    if text.is_empty() {
        None
    } else {
        Some(text)
    }
}

fn issue_number_from_row(row: &Value) -> Option<String> {
    let raw = row.get("issue_number")?;
    if raw.is_null() {
        return None;
    }
    let text = if let Some(s) = raw.as_str() {
        s.trim().to_string()
    } else {
        raw.to_string().trim_matches('"').trim().to_string()
    };
    if text.is_empty() {
        None
    } else {
        Some(text)
    }
}

fn external_url_from_row(row: &Value, issue_id: &str) -> Option<String> {
    let raw = row.get("site_detail_url");
    if let Some(s) = raw.and_then(Value::as_str) {
        let trimmed = s.trim();
        if !trimmed.is_empty() {
            return Some(trimmed.to_string());
        }
    }
    Some(format!(
        "https://comicvine.gamespot.com/issue/4000-{issue_id}/"
    ))
}

fn issue_metadata_from_row(row: &Value) -> Value {
    let mut map = serde_json::Map::new();
    for key in [
        "name",
        "issue_number",
        "cover_date",
        "store_date",
        "date_last_updated",
    ] {
        if let Some(value) = row.get(key) {
            if !value.is_null() {
                map.insert(key.to_string(), value.clone());
            }
        }
    }
    if let Some(volume) = row.get("volume").and_then(Value::as_object) {
        if let Some(name) = volume.get("name").and_then(Value::as_str) {
            let trimmed = name.trim();
            if !trimmed.is_empty() {
                map.insert(
                    "volume_name".to_string(),
                    Value::String(trimmed.to_string()),
                );
            }
        }
    }
    Value::Object(map)
}

async fn upsert_external_issue_identity(
    tx: &tokio_postgres::Transaction<'_>,
    external_id: &str,
    external_url: Option<&str>,
    metadata: &Value,
) -> Result<i32, ApiError> {
    let row = tx
        .query_opt(
            "SELECT id, metadata_json FROM external_identities \
             WHERE provider = 'comicvine' AND entity_type = 'issue' AND external_id = $1 \
             FOR UPDATE",
            &[&external_id],
        )
        .await
        .map_err(db::query_error)?;
    if let Some(existing) = row {
        let id: i32 = existing.get(0);
        // Preserve existing metadata on retry when present; update URL if newly provided.
        if let Some(url) = external_url {
            tx.execute(
                "UPDATE external_identities SET external_url = COALESCE($1, external_url), updated_at = NOW() WHERE id = $2",
                &[&url, &id],
            )
            .await
            .map_err(db::query_error)?;
        }
        return Ok(id);
    }
    let created = tx
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, external_url, metadata_json, created_at, updated_at) \
             VALUES ('comicvine', 'issue', $1, $2, $3::jsonb, NOW(), NOW()) RETURNING id",
            &[&external_id, &external_url, &metadata],
        )
        .await
        .map_err(db::query_error)?;
    Ok(created.get(0))
}

async fn ensure_confirmed_issue_mapping(
    tx: &tokio_postgres::Transaction<'_>,
    issue_id: i32,
    external_identity_id: i32,
) -> Result<(), ApiError> {
    // Avoid conflicting confirmed mapping for a different identity on same issue in a way that breaks uniqueness;
    // best-effort upsert matching Python link semantics.
    tx.execute(
        "INSERT INTO issue_external_identity_mappings \
         (issue_id, external_identity_id, status, evidence_source, evidence_json, confidence, created_at, updated_at) \
         VALUES ($1, $2, 'confirmed', 'comicvine_issue_adoption', '{}'::jsonb, 1.0, NOW(), NOW()) \
         ON CONFLICT (issue_id, external_identity_id) DO UPDATE \
         SET status = 'confirmed', evidence_source = COALESCE(issue_external_identity_mappings.evidence_source, EXCLUDED.evidence_source), \
             confidence = COALESCE(issue_external_identity_mappings.confidence, EXCLUDED.confidence), updated_at = NOW()",
        &[&issue_id, &external_identity_id],
    )
    .await
    .map_err(db::query_error)?;
    Ok(())
}

async fn recalculate_thread_tracking(
    tx: &tokio_postgres::Transaction<'_>,
    thread_id: i32,
    user_id: i32,
    created_any: bool,
) -> Result<(), ApiError> {
    // Derive counters from issue rows (Issue.status/position). Mirror Python's apply_thread_issue_tracking_state behavior.
    let rows = tx
        .query(
            "SELECT id, status FROM issues WHERE thread_id = $1 ORDER BY position, id",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    let total = rows.len() as i32;
    let mut unread = 0_i32;
    let mut next_unread: Option<i32> = None;
    let mut read_count = 0_i32;
    for row in &rows {
        let status: String = row.get(1);
        if status == "unread" {
            unread += 1;
            if next_unread.is_none() {
                next_unread = Some(row.get(0));
            }
        } else if status == "read" {
            read_count += 1;
        }
    }
    let progress = if total <= 0 || read_count == 0 {
        "unread"
    } else if unread == 0 {
        "completed"
    } else {
        "in_progress"
    };

    let thread_row = tx
        .query_one(
            "SELECT total_issues, next_unread_issue_id, status FROM threads WHERE id = $1 AND user_id = $2 FOR UPDATE",
            &[&thread_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    let was_unmigrated: bool = thread_row
        .try_get::<_, Option<i32>>(0)
        .ok()
        .flatten()
        .is_none();
    let had_next: bool = thread_row
        .try_get::<_, Option<i32>>(1)
        .ok()
        .flatten()
        .is_some();
    let old_status: String = thread_row.get(2);

    let mut new_status = old_status.clone();
    let mut reseat_to_front = false;
    if next_unread.is_none() {
        new_status = "completed".to_string();
    } else if was_unmigrated || !had_next {
        if !was_unmigrated && old_status == "completed" {
            reseat_to_front = true;
        }
        new_status = "active".to_string();
    }

    if reseat_to_front {
        tx.execute(
            "UPDATE threads SET queue_position = queue_position + 1 WHERE user_id = $1 AND status = 'active' AND id <> $2",
            &[&user_id, &thread_id],
        )
        .await
        .map_err(db::query_error)?;
    }

    tx.execute(
        "UPDATE threads SET total_issues = $1, issues_remaining = $2, next_unread_issue_id = $3, reading_progress = $4, status = $5, queue_position = CASE WHEN $6 THEN 1 ELSE queue_position END WHERE id = $7",
        &[&total, &unread, &next_unread, &progress, &new_status, &reseat_to_front, &thread_id],
    )
    .await
    .map_err(db::query_error)?;

    if created_any {
        tx.execute(
            "INSERT INTO events (type, timestamp, thread_id) VALUES ('issues_created', NOW(), $1)",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    }
    Ok(())
}

async fn create_issues_in_natural_order_tx(
    tx: &tokio_postgres::Transaction<'_>,
    thread_id: i32,
    new_issue_numbers: &[String],
) -> Result<Vec<(i32, String, i32)>, ApiError> {
    if new_issue_numbers.is_empty() {
        return Ok(Vec::new());
    }

    let rows = tx
        .query(
            "SELECT id, issue_number, position FROM issues WHERE thread_id = $1 \
             ORDER BY position, id FOR UPDATE",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    let existing: Vec<(i32, String, i32)> = rows
        .iter()
        .map(|r| (r.get(0), r.get::<_, String>(1), r.get(2)))
        .collect();
    let existing_numbers: Vec<String> = existing.iter().map(|(_, n, _)| n.clone()).collect();

    let natural = natural_issue_order(&existing_numbers, new_issue_numbers);
    if let Some(order) = natural {
        let target_positions: HashMap<String, i32> = order
            .iter()
            .enumerate()
            .map(|(idx, n)| (n.clone(), (idx + 1) as i32))
            .collect();

        let mut updates: Vec<(i32, i32)> = Vec::new();
        for (id, number, position) in &existing {
            if let Some(&target) = target_positions.get(number) {
                if target != *position {
                    updates.push((*id, target));
                }
            }
        }
        if !updates.is_empty() {
            tx.execute("SET CONSTRAINTS uq_issue_thread_position DEFERRED", &[])
                .await
                .map_err(db::query_error)?;
            for (id, pos) in &updates {
                tx.execute("UPDATE issues SET position = $1 WHERE id = $2", &[pos, id])
                    .await
                    .map_err(db::query_error)?;
            }
        }

        let mut created = Vec::new();
        for number in new_issue_numbers {
            if let Some(&pos) = target_positions.get(number) {
                let row = tx
                    .query_one(
                        "INSERT INTO issues (thread_id, issue_number, position, status, read_at) \
                         VALUES ($1, $2, $3, 'unread', NULL) RETURNING id",
                        &[&thread_id, number, &pos],
                    )
                    .await
                    .map_err(db::query_error)?;
                let id: i32 = row.get(0);
                created.push((id, number.clone(), pos));
            }
        }
        created.sort_by_key(|(_, _, pos)| *pos);
        return Ok(created);
    }

    let max_pos = existing.iter().map(|(_, _, p)| *p).max().unwrap_or(0);
    let mut created = Vec::new();
    for (idx, number) in new_issue_numbers.iter().enumerate() {
        let pos = max_pos + (idx as i32) + 1;
        let row = tx
            .query_one(
                "INSERT INTO issues (thread_id, issue_number, position, status, read_at) \
                 VALUES ($1, $2, $3, 'unread', NULL) RETURNING id",
                &[&thread_id, number, &pos],
            )
            .await
            .map_err(db::query_error)?;
        let id: i32 = row.get(0);
        created.push((id, number.clone(), pos));
    }
    Ok(created)
}

fn parse_volume_id(raw: &str, source_id: i32) -> Result<i32, String> {
    let trimmed = raw.trim();
    let numeric = if trimmed.chars().all(|c| c.is_ascii_digit()) {
        trimmed
    } else if trimmed.contains('-') && trimmed.rsplit('-').next().is_some_and(|s| !s.is_empty()) {
        trimmed.rsplit('-').next().unwrap_or(trimmed)
    } else {
        trimmed
    };
    numeric.parse::<i32>().map_err(|_| {
        format!("Release source {source_id} has a non-numeric ComicVine volume id: {raw:?}")
    })
}

#[allow(dead_code)]
async fn comicvine_get(path_and_query: &str) -> Result<Value, String> {
    let connect = async {
        let tcp = tokio::net::TcpStream::connect((COMICVINE_HOST, 443))
            .await
            .map_err(|e| e.to_string())?;
        let tls = native_tls::TlsConnector::new().map_err(|e| e.to_string())?;
        let tls = tokio_native_tls::TlsConnector::from(tls)
            .connect(COMICVINE_HOST, tcp)
            .await
            .map_err(|e| e.to_string())?;
        let (mut sender, connection) = http1::handshake(TokioIo::new(tls))
            .await
            .map_err(|e| e.to_string())?;
        tokio::spawn(async move {
            let _ = connection.await;
        });
        let request = hyper::Request::builder()
            .method("GET")
            .uri(path_and_query)
            .header("host", COMICVINE_HOST)
            .header("accept", "application/json")
            .header("user-agent", "ComicPile/1.0")
            .body(Empty::<Bytes>::new())
            .map_err(|e| e.to_string())?;
        let mut response = sender
            .send_request(request)
            .await
            .map_err(|e| e.to_string())?;
        if !response.status().is_success() {
            return Err(format!("HTTP {}", response.status()));
        }
        let mut body = Vec::new();
        while let Some(frame) = response.frame().await {
            let frame = frame.map_err(|e| e.to_string())?;
            if let Some(data) = frame.data_ref() {
                body.extend_from_slice(data);
                if body.len() > MAX_BODY {
                    return Err("response too large".to_string());
                }
            }
        }
        serde_json::from_slice::<Value>(&body).map_err(|e| e.to_string())
    };
    tokio::time::timeout(PROVIDER_TIMEOUT, connect)
        .await
        .map_err(|_| "provider timeout".to_string())?
}

#[allow(dead_code)]
async fn fetch_volume_issues(api_key: &str, volume_id: i32) -> Result<Vec<Value>, String> {
    if api_key.is_empty() || !api_key.bytes().all(|c| c.is_ascii_alphanumeric()) {
        return Err("COMICVINE_API_KEY is required".to_string());
    }
    let mut rows = Vec::new();
    let mut offset = 0_usize;
    let mut expected_total: Option<usize> = None;
    loop {
        let path = format!(
            "/api/issues/?api_key={api_key}&format=json&filter=volume:{volume_id}&limit=100&offset={offset}"
        );
        let payload = comicvine_get(&path).await?;
        let status_code = payload
            .get("status_code")
            .and_then(Value::as_i64)
            .unwrap_or(1);
        if status_code != 1 {
            return Err(format!("ComicVine API error: {:?}", payload.get("error")));
        }
        let results = payload
            .get("results")
            .and_then(Value::as_array)
            .ok_or_else(|| {
                "ComicVine /issues response did not contain a results list".to_string()
            })?;
        if expected_total.is_none() {
            expected_total = payload
                .get("number_of_total_results")
                .and_then(Value::as_u64)
                .and_then(|n| usize::try_from(n).ok());
        }
        for row in results {
            if let Some(vol) = row.get("volume").and_then(Value::as_object) {
                if let Some(id) = vol.get("id").and_then(Value::as_i64) {
                    if id != i64::from(volume_id) {
                        return Err(
                            "ComicVine /issues ignored the requested volume filter; refusing mixed data"
                                .to_string(),
                        );
                    }
                }
            }
            if row.is_object() {
                rows.push(row.clone());
            }
        }
        if results.len() < 100 || expected_total.is_some_and(|n| offset + results.len() >= n) {
            break;
        }
        offset += results.len();
        if offset >= 10_000 {
            break;
        }
    }
    Ok(rows)
}

async fn rebuild_plan_issues_from_nodes_json(
    tx: &tokio_postgres::Transaction<'_>,
    plan_id: i32,
) -> Result<(), ApiError> {
    let row = tx
        .query_opt(
            "SELECT nodes_json FROM continuity_plans WHERE id = $1 FOR UPDATE",
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(row) = row else {
        return Ok(());
    };
    let nodes_json: Value = row
        .try_get::<_, Value>(0)
        .unwrap_or(Value::Array(Vec::new()));
    let nodes = nodes_json.as_array().cloned().unwrap_or_default();

    tx.execute(
        "DELETE FROM reading_plan_issues WHERE plan_id = $1",
        &[&plan_id],
    )
    .await
    .map_err(db::query_error)?;

    let mut seen_issue_ids: std::collections::HashSet<i32> = std::collections::HashSet::new();
    for node in &nodes {
        if node.get("node_type").and_then(Value::as_str) != Some("issue") {
            continue;
        }
        let Some(ref_id) = node.get("ref_id").and_then(Value::as_i64) else {
            continue;
        };
        let issue_id = i32::try_from(ref_id).unwrap_or(-1);
        if issue_id <= 0 || !seen_issue_ids.insert(issue_id) {
            continue;
        }
        let occurrence_id = node
            .get("id")
            .and_then(Value::as_str)
            .map(|s| s.to_string())
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| format!("release-{issue_id}"));
        let lane_id = node
            .get("lane_id")
            .and_then(Value::as_str)
            .unwrap_or("unread-tail")
            .to_string();
        let display_position = node.get("position").and_then(Value::as_i64).unwrap_or(0) as i32;
        let label = node
            .get("label")
            .and_then(Value::as_str)
            .map(|s| s.to_string());
        let reader_role = node
            .get("reader_role")
            .and_then(Value::as_str)
            .map(|s| s.to_string());
        let reader_optional = node.get("reader_optional").and_then(Value::as_bool);
        let is_checkpoint = node
            .get("is_checkpoint")
            .and_then(Value::as_bool)
            .unwrap_or(false);

        // Collect source metadata annotations similar to normalization service.
        let mut meta = serde_json::Map::new();
        if let Some(v) = node.get("source_role") {
            if !v.is_null() {
                meta.insert("source_role".into(), v.clone());
            }
        }
        if let Some(v) = node.get("source_confidence") {
            if !v.is_null() {
                meta.insert("source_confidence".into(), v.clone());
            }
        }
        if let Some(v) = node.get("source_explanation") {
            if !v.is_null() {
                meta.insert("source_explanation".into(), v.clone());
            }
        }
        if let Some(v) = node.get("source_story_arc_ids") {
            if !v.is_null() {
                meta.insert("source_story_arc_ids".into(), v.clone());
            }
        }
        if let Some(v) = node.get("source_target_story_arc_id") {
            if !v.is_null() {
                meta.insert("source_target_story_arc_id".into(), v.clone());
            }
        }
        let source_metadata_json: Option<Value> = if meta.is_empty() {
            None
        } else {
            Some(Value::Object(meta))
        };

        tx.execute(
            "INSERT INTO reading_plan_issues \
             (plan_id, occurrence_id, issue_id, lane_id, display_position, label, reader_role, reader_optional, is_checkpoint, source_metadata_json) \
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb) \
             ON CONFLICT (plan_id, occurrence_id) DO UPDATE SET \
               issue_id = EXCLUDED.issue_id, lane_id = EXCLUDED.lane_id, display_position = EXCLUDED.display_position, \
               label = EXCLUDED.label, reader_role = EXCLUDED.reader_role, reader_optional = EXCLUDED.reader_optional, \
               is_checkpoint = EXCLUDED.is_checkpoint, source_metadata_json = EXCLUDED.source_metadata_json",
            &[&plan_id, &occurrence_id, &issue_id, &lane_id, &display_position, &label, &reader_role, &reader_optional, &is_checkpoint, &source_metadata_json],
        )
        .await
        .map_err(db::query_error)?;
    }
    Ok(())
}

async fn extend_adopted_issue_to_following_plans(
    tx: &tokio_postgres::Transaction<'_>,
    user_id: i32,
    thread_id: i32,
    external_identity_id: i32,
    issue_id: i32,
) -> Result<(), ApiError> {
    // Extend enabled sibling plans following the same thread+volume for this user.
    // This is a minimal parity step; full rebuild_plan_membership/source-placement
    // parity remains pending.
    let plan_rows = tx
        .query(
            "SELECT DISTINCT rps.plan_id \
             FROM reading_plan_release_sources rps \
             JOIN continuity_plans cp ON cp.id = rps.plan_id \
             WHERE rps.thread_id = $1 AND rps.external_identity_id = $2 \
               AND rps.enabled = TRUE AND cp.user_id = $3 \
             ORDER BY rps.plan_id",
            &[&thread_id, &external_identity_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;

    for row in &plan_rows {
        let plan_id: i32 = row.get(0);
        // Lock plan row.
        let plan = tx
            .query_opt(
                "SELECT nodes_json FROM continuity_plans WHERE id = $1 AND user_id = $2 FOR UPDATE",
                &[&plan_id, &user_id],
            )
            .await
            .map_err(db::query_error)?;
        let Some(plan_row) = plan else {
            continue;
        };

        let exists = tx
            .query_opt(
                "SELECT 1 FROM reading_plan_issues WHERE plan_id = $1 AND issue_id = $2 LIMIT 1",
                &[&plan_id, &issue_id],
            )
            .await
            .map_err(db::query_error)?
            .is_some();
        if exists {
            continue;
        }

        let nodes_json: Value = plan_row
            .try_get::<_, Value>(0)
            .unwrap_or(Value::Array(Vec::new()));
        let mut nodes = nodes_json.as_array().cloned().unwrap_or_default();
        let mut max_pos: i64 = -1;
        let mut already_in_json = false;
        for node in &nodes {
            if let Some(pos) = node.get("position").and_then(Value::as_i64) {
                if pos > max_pos {
                    max_pos = pos;
                }
            }
            if node.get("node_type").and_then(Value::as_str) == Some("issue")
                && node.get("ref_id").and_then(Value::as_i64) == Some(i64::from(issue_id))
            {
                already_in_json = true;
            }
        }
        if !already_in_json {
            let new_pos = (max_pos + 1) as i32;
            nodes.push(serde_json::json!({
                "id": format!("release-{issue_id}"),
                "node_type": "issue",
                "ref_id": issue_id,
                "lane_id": "unread-tail",
                "position": new_pos,
                "label": Value::Null,
                "is_checkpoint": false
            }));
            tx.execute(
                "UPDATE continuity_plans SET nodes_json = $1::jsonb, updated_at = NOW() WHERE id = $2",
                &[&Value::Array(nodes), &plan_id],
            )
            .await
            .map_err(db::query_error)?;
        }
        // Rebuild issue membership from plan nodes for closer parity with
        // rebuild_plan_membership (source/placement rebuild still pending).
        rebuild_plan_issues_from_nodes_json(tx, plan_id).await?;
    }

    Ok(())
}

type SourceTxOutcome = Result<(i64, i64, i64, i64, i64, i64, i64, i64, bool), ApiError>;

pub async fn sync_released_issues_endpoint(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(payload): Json<SyncRequest>,
) -> Result<Json<SyncResponse>, ApiError> {
    let as_of = parse_as_of(&payload.as_of)?;
    let _refresh = payload.refresh;
    let mut connection = db::checkout(&state).await?;

    let all_rows = connection
        .query(
            "SELECT rps.id, rps.plan_id, rps.thread_id, rps.external_identity_id, ei.external_id, rps.enabled \
             FROM reading_plan_release_sources rps \
             JOIN continuity_plans cp ON cp.id = rps.plan_id \
             JOIN external_identities ei ON ei.id = rps.external_identity_id \
             WHERE cp.user_id = $1 \
             ORDER BY rps.created_at",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let total_sources = all_rows.len() as i64;

    let mut enabled_rows = Vec::new();
    for row in &all_rows {
        let enabled: bool = row.get(5);
        if enabled {
            enabled_rows.push(EnabledSourceRow {
                source_id: row.get(0),
                plan_id: row.get(1),
                thread_id: row.get(2),
                external_identity_id: row.get(3),
                provider_volume_id: row.get(4),
            });
        }
    }
    let enabled_sources = enabled_rows.len() as i64;

    let exclusions = load_release_exclusions(&connection, user.id()).await?;

    if enabled_sources == 0 {
        let report = SyncReport {
            total_sources,
            enabled_sources,
            checked_sources: 0,
            successful_sources: 0,
            failed_sources: 0,
            issues_checked: 0,
            created_issues: 0,
            reused_issues: 0,
            future_skips: 0,
            unknown_date_skips: 0,
            conflicts: 0,
            issue_failures: 0,
            excluded_sources: 0,
            excluded_issues: 0,
            skipped_sources: 0,
            failures: Vec::new(),
        };
        return Ok(Json(SyncResponse {
            success: report.failed_sources == 0 && report.issue_failures == 0,
            message: report_message(&report),
            result: report,
        }));
    }

    // Test-only roster injection: JSON object {"<volume_id>": [issue,...], "_fail_<volume_id>": "error"}
    let mock_rosters: Option<Value> = std::env::var("RUST_ROLL_SYNC_MOCK_ROSTER_JSON")
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok());

    // Match Python: missing API key fails all enabled sources with the
    // client-construction error message (unless test mocks are injected).
    let api_key = match std::env::var("COMICVINE_API_KEY")
        .ok()
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty())
    {
        Some(key) => key,
        None if mock_rosters.is_some() => String::new(),
        None => {
            let error = "COMICVINE_API_KEY is required".to_string();
            let mut failures = Vec::with_capacity(enabled_rows.len());
            for source in &enabled_rows {
                let volume_id =
                    parse_volume_id(&source.provider_volume_id, source.source_id).unwrap_or(-1);
                failures.push(SourceSyncFailure {
                    source_id: source.source_id,
                    plan_id: source.plan_id,
                    thread_id: source.thread_id,
                    volume_id,
                    error: error.clone(),
                });
            }
            let report = SyncReport {
                total_sources,
                enabled_sources,
                checked_sources: 0,
                successful_sources: 0,
                failed_sources: enabled_sources,
                issues_checked: 0,
                created_issues: 0,
                reused_issues: 0,
                future_skips: 0,
                unknown_date_skips: 0,
                conflicts: 0,
                issue_failures: 0,
                excluded_sources: 0,
                excluded_issues: 0,
                skipped_sources: 0,
                failures,
            };
            return Ok(Json(SyncResponse {
                success: false,
                message: report_message(&report),
                result: report,
            }));
        }
    };

    let mut report = SyncReport {
        total_sources,
        enabled_sources,
        checked_sources: 0,
        successful_sources: 0,
        failed_sources: 0,
        issues_checked: 0,
        created_issues: 0,
        reused_issues: 0,
        future_skips: 0,
        unknown_date_skips: 0,
        conflicts: 0,
        issue_failures: 0,
        excluded_sources: 0,
        excluded_issues: 0,
        skipped_sources: 0,
        failures: Vec::new(),
    };

    // Group by provider volume; isolate corrupt volume IDs as per-source failures.
    let mut volume_groups: HashMap<i32, Vec<EnabledSourceRow>> = HashMap::new();
    for source in enabled_rows {
        match parse_volume_id(&source.provider_volume_id, source.source_id) {
            Ok(volume_id) => volume_groups.entry(volume_id).or_default().push(source),
            Err(error) => {
                report.failed_sources += 1;
                report.failures.push(SourceSyncFailure {
                    source_id: source.source_id,
                    plan_id: source.plan_id,
                    thread_id: source.thread_id,
                    volume_id: -1,
                    error,
                });
            }
        }
    }

    let mut synced_source_ids: Vec<i32> = Vec::new();

    for (volume_id, sources) in volume_groups {
        let roster = if let Some(ref mocks) = mock_rosters {
            let fail_key = format!("_fail_{volume_id}");
            if let Some(msg) = mocks.get(&fail_key).and_then(Value::as_str) {
                Err(msg.to_string())
            } else if let Some(rows) = mocks.get(volume_id.to_string()).and_then(Value::as_array) {
                Ok(rows
                    .iter()
                    .filter(|r| r.is_object())
                    .cloned()
                    .collect::<Vec<Value>>())
            } else {
                Ok(Vec::new())
            }
        } else {
            fetch_volume_issues(&api_key, volume_id).await
        };
        let roster = match roster {
            Ok(roster) => roster,
            Err(error) => {
                let message = format!("Volume sync failed: {error}");
                for source in &sources {
                    report.failed_sources += 1;
                    report.failures.push(SourceSyncFailure {
                        source_id: source.source_id,
                        plan_id: source.plan_id,
                        thread_id: source.thread_id,
                        volume_id,
                        error: message.clone(),
                    });
                }
                continue;
            }
        };

        report.checked_sources += sources.len() as i64;
        for source in &sources {
            if exclusions.excludes_source(source.thread_id, volume_id) {
                report.successful_sources += 1;
                report.excluded_sources += 1;
                report.skipped_sources += 1;
                continue;
            }

            let tx = connection
                .build_transaction()
                .start()
                .await
                .map_err(db::query_error)?;

            let source_result: SourceTxOutcome = async {
                tx.execute(
                    "SELECT id FROM users WHERE id = $1 FOR UPDATE",
                    &[&user.id()],
                )
                .await
                .map_err(db::query_error)?;

                let confirmed = tx
                    .query_opt(
                        "SELECT 1 FROM thread_external_series_mappings \
                         WHERE thread_id = $1 AND external_identity_id = $2 AND status = 'confirmed' LIMIT 1",
                        &[&source.thread_id, &source.external_identity_id],
                    )
                    .await
                    .map_err(db::query_error)?
                    .is_some();
                let identity_ok = if confirmed {
                    tx.query_opt(
                        "SELECT 1 FROM external_identities \
                         WHERE id = $1 AND provider = 'comicvine' AND entity_type = 'series' LIMIT 1",
                        &[&source.external_identity_id],
                    )
                    .await
                    .map_err(db::query_error)?
                    .is_some()
                } else {
                    false
                };
                if !confirmed || !identity_ok {
                    return Err(ApiError::Unprocessable(format!(
                        "Volume {volume_id} is no longer a confirmed ComicVine mapping for thread {}",
                        source.thread_id
                    )));
                }

                let thread_ok = tx
                    .query_opt(
                        "SELECT 1 FROM threads t JOIN continuity_plans cp ON cp.id = $2 \
                         WHERE t.id = $1 AND t.user_id = $3 AND cp.user_id = $3 FOR UPDATE OF t",
                        &[&source.thread_id, &source.plan_id, &user.id()],
                    )
                    .await
                    .map_err(db::query_error)?
                    .is_some();
                if !thread_ok {
                    return Err(ApiError::Unprocessable(format!(
                        "Thread {} is not owned by plan {}'s user",
                        source.thread_id, source.plan_id
                    )));
                }

                // Re-check source is still enabled/current.
                let source_current = tx
                    .query_opt(
                        "SELECT enabled FROM reading_plan_release_sources WHERE id = $1",
                        &[&source.source_id],
                    )
                    .await
                    .map_err(db::query_error)?
                    .and_then(|r| r.get::<_, Option<bool>>(0))
                    .unwrap_or(false);
                if !source_current {
                    return Ok((0, 0, 0, 0, 0, 0, 0, 0, true)); // skipped
                }

                let mut source_issues_checked: i64 = 0;
                let mut source_future_skips: i64 = 0;
                let mut source_unknown_date_skips: i64 = 0;
                let mut source_excluded_issues: i64 = 0;
                let mut source_issue_failures: i64 = 0;
                let mut source_created: i64 = 0;
                let mut source_reused: i64 = 0;
                let mut source_conflicts: i64 = 0;
                let mut created_any = false;

                #[derive(Clone)]
                struct ReleasableIssue {
                    cv_issue_id: String,
                    issue_number: String,
                    row: Value,
                }
                let mut to_create: Vec<ReleasableIssue> = Vec::new();
                let mut releasable_existing: Vec<(i32, bool)> = Vec::new(); // (issue_id, excluded)
                let mut adopted_for_extension: Vec<i32> = Vec::new();

                for row in &roster {
                    source_issues_checked += 1;
                    let Some(issue_id_str) = issue_identity(row) else {
                        source_issue_failures += 1;
                        continue;
                    };
                    let store_date = parse_store_date(row.get("store_date"));
                    match store_date {
                        None => {
                            source_unknown_date_skips += 1;
                            continue;
                        }
                        Some(date) if date > as_of => {
                            source_future_skips += 1;
                            continue;
                        }
                        Some(_) => {}
                    }
                    let Some(issue_number) = issue_number_from_row(row) else {
                        source_issue_failures += 1;
                        continue;
                    };

                    let existing_by_identity: Option<(i32, i32)> = tx
                        .query_opt(
                            "SELECT i.id, i.thread_id \
                             FROM issues i \
                             JOIN threads t ON t.id = i.thread_id \
                             JOIN issue_external_identity_mappings m ON m.issue_id = i.id \
                             JOIN external_identities e ON e.id = m.external_identity_id \
                             WHERE t.user_id = $1 AND m.status = 'confirmed' \
                               AND e.provider = 'comicvine' AND e.entity_type = 'issue' \
                               AND e.external_id = $2 \
                             ORDER BY i.id LIMIT 1",
                            &[&user.id(), &issue_id_str],
                        )
                        .await
                        .map_err(db::query_error)?
                        .map(|r| (r.get(0), r.get(1)));

                    let (existing_issue_id, existing_thread_id) = if let Some(found) = existing_by_identity {
                        (Some(found.0), Some(found.1))
                    } else {
                        let in_thread: Option<i32> = tx
                            .query_opt(
                                "SELECT id FROM issues WHERE thread_id = $1 AND issue_number = $2 FOR UPDATE",
                                &[&source.thread_id, &issue_number],
                            )
                            .await
                            .map_err(db::query_error)?
                            .map(|r| r.get(0));
                        (in_thread, in_thread.map(|_| source.thread_id))
                    };

                    if let Some(eid) = existing_issue_id {
                        if existing_thread_id == Some(source.thread_id) {
                            let excluded = exclusions.issue_ids.contains(&eid) || exclusions.thread_ids.contains(&source.thread_id);
                            if excluded {
                                source_excluded_issues += 1;
                            } else {
                                source_reused += 1;
                                adopted_for_extension.push(eid);
                            }
                            if existing_by_identity.is_none() {
                                let ext_url = external_url_from_row(row, &issue_id_str);
                                let metadata = issue_metadata_from_row(row);
                                let identity_id = upsert_external_issue_identity(&tx, &issue_id_str, ext_url.as_deref(), &metadata).await?;
                                ensure_confirmed_issue_mapping(&tx, eid, identity_id).await?;
                            }
                            releasable_existing.push((eid, excluded));
                        } else {
                            source_conflicts += 1;
                        }
                        continue;
                    }

                    to_create.push(ReleasableIssue { cv_issue_id: issue_id_str, issue_number, row: row.clone() });
                }

                if !to_create.is_empty() {
                    let new_numbers: Vec<String> = to_create.iter().map(|i| i.issue_number.clone()).collect();
                    let created = create_issues_in_natural_order_tx(&tx, source.thread_id, &new_numbers).await?;
                    source_created += created.len() as i64;
                    created_any = !created.is_empty();
                    let mut by_number: HashMap<String, &ReleasableIssue> = HashMap::new();
                    for item in &to_create {
                        by_number.entry(item.issue_number.clone()).or_insert(item);
                    }
                    for (issue_id, number, _pos) in &created {
                        if let Some(item) = by_number.get(number) {
                            let ext_url = external_url_from_row(&item.row, &item.cv_issue_id);
                            let metadata = issue_metadata_from_row(&item.row);
                            let identity_id = upsert_external_issue_identity(&tx, &item.cv_issue_id, ext_url.as_deref(), &metadata).await?;
                            ensure_confirmed_issue_mapping(&tx, *issue_id, identity_id).await?;
                            adopted_for_extension.push(*issue_id);
                        }
                    }
                }

                if !adopted_for_extension.is_empty() {
                    // Best-effort plan extension for enabled sibling plans following this volume.
                    for issue_id in &adopted_for_extension {
                        extend_adopted_issue_to_following_plans(
                            &tx,
                            user.id(),
                            source.thread_id,
                            source.external_identity_id,
                            *issue_id,
                        )
                        .await?;
                    }
                }

                if created_any || source_reused > 0 {
                    recalculate_thread_tracking(&tx, source.thread_id, user.id(), created_any).await?;
                    crate::issue_service::refresh_blocked_threads(&tx, user.id()).await?;
                }

                Ok((source_issues_checked, source_created, source_reused, source_future_skips, source_unknown_date_skips, source_conflicts, source_issue_failures, source_excluded_issues, false))
            }
            .await;

            match source_result {
                Ok((
                    issues_checked,
                    created,
                    reused,
                    future_skips,
                    unknown_date_skips,
                    conflicts,
                    issue_failures,
                    excluded_issues,
                    skipped,
                )) => {
                    report.issues_checked += issues_checked;
                    report.created_issues += created;
                    report.reused_issues += reused;
                    report.future_skips += future_skips;
                    report.unknown_date_skips += unknown_date_skips;
                    report.conflicts += conflicts;
                    report.issue_failures += issue_failures;
                    report.excluded_issues += excluded_issues;
                    if skipped {
                        report.successful_sources += 1;
                        report.skipped_sources += 1;
                        tx.rollback().await.map_err(db::query_error)?;
                        continue;
                    }
                    tx.commit().await.map_err(db::query_error)?;
                    report.successful_sources += 1;
                    synced_source_ids.push(source.source_id);
                }
                Err(ApiError::Unprocessable(msg)) => {
                    tx.rollback().await.map_err(db::query_error)?;
                    report.failed_sources += 1;
                    report.failures.push(SourceSyncFailure {
                        source_id: source.source_id,
                        plan_id: source.plan_id,
                        thread_id: source.thread_id,
                        volume_id,
                        error: msg,
                    });
                }
                Err(e) => {
                    tx.rollback().await.map_err(db::query_error)?;
                    return Err(e);
                }
            }
        }
    }

    let synced_at = Utc::now();
    for source_id in synced_source_ids {
        let _ = connection
            .execute(
                "UPDATE reading_plan_release_sources SET last_synced_at = $1 WHERE id = $2",
                &[&synced_at, &source_id],
            )
            .await;
    }

    Ok(Json(SyncResponse {
        success: report.failed_sources == 0 && report.issue_failures == 0,
        message: report_message(&report),
        result: report,
    }))
}

#[utoipa::path(
    post,
    path = "/api/v1/reading-plan-sync/sync",
    tag = "reading-plan-sync",
    operation_id = "reading_plan_sync",
    request_body = SyncRequest,
    responses(
        (status = 200, description = "User-triggered sync report", body = SyncResponse),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Invalid request"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn sync_released_issues_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v1/reading-plan-sync/status",
    tag = "reading-plan-sync",
    operation_id = "reading_plan_sync_status",
    responses(
        (status = 200, description = "Sync state for every release source owned by the caller", body = SyncStatusResponse),
        (status = 401, description = "Not authenticated"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_sync_status_documentation() {}

#[derive(utoipa::OpenApi)]
#[openapi(
    paths(sync_released_issues_documentation, get_sync_status_documentation),
    components(schemas(SyncRequest, SyncResponse, SyncReport, SourceSyncFailure, SyncStatusSource, SyncStatusResponse)),
    modifiers(&ReadingPlanSyncSecurityAddon)
)]
pub struct ReadingPlanSyncApi;

struct ReadingPlanSyncSecurityAddon;
impl utoipa::Modify for ReadingPlanSyncSecurityAddon {
    fn modify(&self, openapi: &mut utoipa::openapi::OpenApi) {
        if let Some(components) = openapi.components.as_mut() {
            components.add_security_scheme(
                "HTTPBearer",
                utoipa::openapi::security::SecurityScheme::Http(
                    utoipa::openapi::security::Http::new(
                        utoipa::openapi::security::HttpAuthScheme::Bearer,
                    ),
                ),
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{config::Config, test_support::DB_LOCK};
    use axum::extract::State;
    use std::sync::Arc;

    async fn test_state() -> Arc<AppState> {
        let url = crate::test_support::database_url().await;
        let config = Config::from_lookup(|name| match name {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-reading-plan-sync-test".into()),
            "RUST_ROLL_POOL_SIZE" => Some("2".into()),
            _ => None,
        })
        .expect("reading-plan-sync test config");
        Arc::new(AppState::new(config).expect("reading-plan-sync test state"))
    }

    #[tokio::test]
    async fn get_sync_status_returns_empty_for_user_without_sources() {
        let _guard = DB_LOCK.lock().await;
        let state = test_state().await;
        crate::test_support::reset(&state).await;

        let connection = crate::db::checkout(&state).await.expect("seed connection");
        connection
            .execute(
                "INSERT INTO users (id, username) VALUES ($1, $2)",
                &[&77_i32, &"reader-77"],
            )
            .await
            .expect("seed user");
        drop(connection);

        let Json(response) = get_sync_status(State(state.clone()), AuthenticatedUser::for_test(77))
            .await
            .expect("get sync status");

        assert_eq!(response.total_sources, 0);
        assert_eq!(response.enabled_sources, 0);
        assert!(response.sources.is_empty());
    }

    #[test]
    fn format_synced_at_matches_python_datetime_json() {
        let whole_second = DateTime::from_timestamp(1_704_164_645, 0).expect("whole second");
        assert_eq!(format_synced_at(whole_second), "2024-01-02T03:04:05Z");

        let with_micros = DateTime::from_timestamp(1_704_164_645, 123_456_000).expect("micros");
        assert_eq!(format_synced_at(with_micros), "2024-01-02T03:04:05.123456Z");
    }
}
