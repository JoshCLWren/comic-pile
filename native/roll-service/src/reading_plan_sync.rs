//! Same-path Rust cutover for the browser-called reading-plan-sync operations
//! (#4851, parent #4335).
//!
//! Preserves the Python `app/api/reading_plan_sync.py` wire contract at the
//! same HTTP methods and exact paths:
//!
//! * `GET /api/v1/reading-plan-sync/status`
//! * `POST /api/v1/reading-plan-sync/sync`
//!
//! Only the implementation moves from Python FastAPI to the native Roll
//! binary. No frontend URL changes; Python handlers remain mounted until
//! authenticated production proof permits their removal.
//!
//! Parity notes (Python oracles are `app/api/reading_plan_sync.py`,
//! `app/services/reading_plan_sync_service.py`,
//! `app/services/provider_issue_adoption.py`,
//! `app/services/reading_plan_release_extension.py`,
//! `app/services/reading_plan_normalization.py` (rebuild_plan_membership),
//! `app/services/release_exclusion_service.py`,
//! `app/comicvine_hydration.py` and `app/utils/issue_natural_order.py`):
//!
//! * `GET .../status` is one owner-scoped aggregate join, mirroring
//!   `list_for_user` (order of rows by `created_at`).
//! * `POST .../sync` keeps the Python statement order and transaction
//!   semantics: load all sources and enabled sources for the owner, build
//!   the provider exactly once (a missing `COMICVINE_API_KEY` records the
//!   Python `ValueError("api_key is required")` against every enabled
//!   source, as Python does), group enabled sources by provider volume, then
//!   per source lock the reader, the thread, re-read the source `FOR UPDATE`,
//!   verify the confirmed thread/volume mapping, apply collection exclusions,
//!   adopt each released roster row through the natural-order path, extend
//!   every plan following the source with the adopted issue, and only then
//!   advance `last_synced_at`.
//! * The whole run is one transaction. Provider, validation and exclusion
//!   failures are isolated per source/issue exactly like Python (they are
//!   captured into `SyncReport`). A PostgreSQL statement failure aborts the
//!   run with 500, which matches the poisoned-session behaviour of the
//!   Python service (its endpoint commit fails and the dependency rolls the
//!   session back).
//! * The roster client reads and writes the same on-disk cache layout as the
//!   Python provider (`{cache_dir}/responses/{endpoint}-{sha256}.json`, JSON
//!   sorted-key `sha256(json.dumps([endpoint, params_without_api_key]))`),
//!   so both runtimes share one cache. Persistent rate-limit and cooldown
//!   ledgers are not ported; a 429/420 response falls back to the cache and
//!   otherwise fails the volume, mirroring the Python throttled path. Live
//!   requests carry `User-Agent: ComicPile/1.0`.
//! * Store-date handling, the unknown/future skip reporting, the
//!   `find_owned_issue_by_confirmed_identity` / `find_in_thread_by_number`
//!   order, the `release-{issue_id}` node id, the unread-tail lane, the
//!   `(position, ref_id)` ordering of plan nodes, and the membership
//!   rebuild (replace `reading_plan_issues`, replace `reading_plan_sources`
//!   and re-insert `reading_plan_source_placements`) match Python.
//! * `refresh_user_blocked_status` (canonical unread-frontier dependency
//!   gate) is ported, including the `cbl-order:%` historical exclusion and
//!   the candidate/changed update pair.
//! * Business-logic 404/422/201/200 shapes match Python where Python uses
//!   them; input validation uses the house Rust convention
//!   (`{"detail": "..."}` 422).

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::State,
    http::StatusCode,
    Json,
};
use chrono::{DateTime, NaiveDate, NaiveDateTime, NaiveTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use std::{
    collections::{BTreeMap, BTreeSet},
    future::Future,
    pin::Pin,
    sync::Arc,
};

// ---------------------------------------------------------------------------
// SQL
// ---------------------------------------------------------------------------

const LIST_FOR_USER_SQL: &str = "SELECT s.id, s.plan_id, s.thread_id, s.external_identity_id, \
        s.enabled, s.last_synced_at, e.external_id, s.created_at \
     FROM reading_plan_release_sources s \
     JOIN continuity_plans p ON p.id = s.plan_id \
     JOIN external_identities e ON e.id = s.external_identity_id \
     WHERE p.user_id = $1 \
     ORDER BY s.created_at";

const LIST_ENABLED_FOR_USER_SQL: &str = "SELECT s.id, s.plan_id, s.thread_id, s.external_identity_id, \
        s.enabled, s.last_synced_at, e.external_id, s.created_at \
     FROM reading_plan_release_sources s \
     JOIN continuity_plans p ON p.id = s.plan_id \
     JOIN external_identities e ON e.id = s.external_identity_id \
     WHERE p.user_id = $1 AND s.enabled \
     ORDER BY s.created_at";

const MARK_SYNCED_SQL: &str =
    "UPDATE reading_plan_release_sources SET last_synced_at = $1 WHERE id = $2";

const EXCLUSIONS_SQL: &str =
    "SELECT provider, external_volume_id, thread_id, issue_id \
     FROM collection_exclusions WHERE user_id = $1 ORDER BY id";

const LOCK_READER_SQL: &str = "SELECT id FROM users WHERE id = $1 FOR UPDATE";
const LOCK_THREAD_SQL: &str = "SELECT id, user_id, status, total_issues, issues_remaining, \
        next_unread_issue_id, reading_progress, queue_position, is_blocked, queue_position_is_manual \
     FROM threads WHERE id = $1 FOR UPDATE";

const CURRENT_SOURCE_SQL: &str = "SELECT s.id, s.plan_id, s.thread_id, s.external_identity_id, \
        s.enabled, s.last_synced_at, e.external_id, s.created_at \
     FROM reading_plan_release_sources s \
     JOIN continuity_plans p ON p.id = s.plan_id \
     JOIN external_identities e ON e.id = s.external_identity_id \
     WHERE s.id = $1 AND p.user_id = $2 \
     FOR UPDATE OF s";

const SOURCE_EXISTS_FOR_USER_SQL: &str = "SELECT s.id, s.plan_id, s.thread_id, s.external_identity_id, \
        s.enabled, s.last_synced_at, e.external_id, s.created_at \
     FROM reading_plan_release_sources s \
     JOIN continuity_plans p ON p.id = s.plan_id \
     JOIN external_identities e ON e.id = s.external_identity_id \
     WHERE s.id = $1 AND p.user_id = $2";

const ENABLED_SIBLINGS_SQL: &str = "SELECT s.id, s.plan_id, s.thread_id, s.external_identity_id, \
        s.enabled, s.last_synced_at, e.external_id, s.created_at \
     FROM reading_plan_release_sources s \
     JOIN continuity_plans p ON p.id = s.plan_id \
     JOIN external_identities e ON e.id = s.external_identity_id \
     WHERE s.thread_id = $1 AND s.external_identity_id = $2 AND s.enabled AND p.user_id = $3 \
     ORDER BY s.id \
     FOR UPDATE OF s";

const CONFIRMED_MAPPING_SQL: &str = "SELECT id FROM thread_external_series_mappings \
     WHERE thread_id = $1 AND external_identity_id = $2 AND status = 'confirmed' LIMIT 1";
const CONFIRMED_IDENTITY_SQL: &str = "SELECT id FROM external_identities \
     WHERE id = $1 AND provider = 'comicvine' AND entity_type = 'series' LIMIT 1";

const IDENTITY_LOOKUP_SQL: &str = "SELECT id, provider_updated_at, metadata_json::text, external_url \
     FROM external_identities WHERE provider = $1 AND entity_type = $2 AND external_id = $3";
const IDENTITY_INSERT_SQL: &str = "INSERT INTO external_identities \
        (provider, entity_type, external_id, external_url, metadata_json, provider_updated_at, created_at, updated_at) \
     VALUES ($1, $2, $3, $4, $5::text::json, $6, NOW(), NOW())";
const IDENTITY_UPDATE_SQL: &str = "UPDATE external_identities SET \
        external_url = COALESCE($2, external_url), \
        provider_updated_at = COALESCE($3, provider_updated_at), \
        metadata_json = COALESCE($4::text::json, metadata_json), \
        updated_at = NOW() \
     WHERE id = $1";

const FIND_OWNED_ISSUE_BY_CONFIRMED_IDENTITY_SQL: &str = "SELECT i.id, i.thread_id, i.issue_number, i.position, i.status, i.catalog_issue_id \
     FROM issues i \
     JOIN threads t ON t.id = i.thread_id \
     JOIN issue_external_identity_mappings m ON m.issue_id = i.id \
     JOIN external_identities e ON e.id = m.external_identity_id \
     WHERE t.user_id = $1 AND m.status = 'confirmed' \
       AND e.provider = 'comicvine' AND e.entity_type = 'issue' AND e.external_id = $2 \
     LIMIT 1";

const FIND_IN_THREAD_BY_NUMBER_SQL: &str = "SELECT id, thread_id, issue_number, position, status, catalog_issue_id \
     FROM issues WHERE thread_id = $1 AND issue_number = $2";

const LOCKED_ISSUE_ROWS_SQL: &str = "SELECT id, issue_number, position FROM issues \
     WHERE thread_id = $1 FOR UPDATE ORDER BY position";
const ISSUES_ORDERED_SQL: &str = "SELECT id, issue_number, position, status FROM issues \
     WHERE thread_id = $1 ORDER BY position";
const INSERT_ISSUE_SQL: &str = "INSERT INTO issues (thread_id, issue_number, position, status, created_at) \
     VALUES ($1, $2, $3, 'unread', NOW()) RETURNING id";
const DEFER_POSITION_SQL: &str = "SET CONSTRAINTS uq_issue_thread_position DEFERRED";

const BLOCKED_IDS_SQL: &str = "SELECT DISTINCT target_thread.id \
     FROM threads AS target_thread \
     JOIN issues AS next_unread_issue ON next_unread_issue.id = target_thread.next_unread_issue_id \
     JOIN dependencies ON dependencies.target_issue_id = next_unread_issue.id \
     JOIN issues AS source_issue ON dependencies.source_issue_id = source_issue.id \
     JOIN threads AS source ON source_issue.thread_id = source.id \
     WHERE target_thread.user_id = $1 \
       AND source.user_id = $1 \
       AND source_issue.status <> 'read' \
       AND next_unread_issue.status <> 'read' \
       AND target_thread.next_unread_issue_id IS NOT NULL \
       AND (dependencies.note IS NULL OR dependencies.note NOT LIKE 'cbl-order:%')";
const BLOCKED_CANDIDATES_SQL: &str = "SELECT id, is_blocked FROM threads \
     WHERE user_id = $1 AND (is_blocked OR id = ANY($2))";
const BLOCKED_UPDATE_SQL: &str =
    "UPDATE threads SET is_blocked = $1 WHERE user_id = $2 AND id = ANY($3)";

const PLAN_FOR_EXTENSION_SQL: &str =
    "SELECT id, nodes_json::text FROM continuity_plans WHERE id = $1 AND user_id = $2 FOR UPDATE";
const PLAN_MEMBERSHIP_READ_SQL: &str = "SELECT rpi.issue_id FROM reading_plan_issues rpi \
     JOIN issues i ON i.id = rpi.issue_id \
     WHERE rpi.plan_id = $1 AND i.status <> 'unread'";
const PLAN_NODES_UPDATE_SQL: &str =
    "UPDATE continuity_plans SET nodes_json = $1::text::json, updated_at = NOW() WHERE id = $2";
const DELETE_PLAN_ISSUES_SQL: &str = "DELETE FROM reading_plan_issues WHERE plan_id = $1";
const INSERT_PLAN_ISSUE_SQL: &str = "INSERT INTO reading_plan_issues \
        (plan_id, occurrence_id, issue_id, lane_id, display_position, label, reader_role, reader_optional, is_checkpoint, source_metadata_json) \
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::text::json)";
const DELETE_PLAN_PLACEMENTS_SQL: &str =
    "DELETE FROM reading_plan_source_placements WHERE plan_id = $1";
const DELETE_PLAN_SOURCES_SQL: &str = "DELETE FROM reading_plan_sources WHERE plan_id = $1";
const INSERT_PLAN_SOURCE_SQL: &str = "INSERT INTO reading_plan_sources \
        (plan_id, raw_source_path, custom_cbl_list_id, recorded_at) \
     VALUES ($1, $2, $3, NOW()) RETURNING id";
const INSERT_PLAN_PLACEMENT_SQL: &str = "INSERT INTO reading_plan_source_placements \
        (plan_id, occurrence_id, plan_source_id, source_position) \
     VALUES ($1, $2, $3, $4)";
const CUSTOM_CBL_LIST_EXISTS_SQL: &str =
    "SELECT id FROM custom_cbl_lists WHERE id = $1";
const GET_ISSUE_SQL: &str = "SELECT id, thread_id FROM issues WHERE id = $1";

const LINKED_MAPPING_OWNED_SQL: &str = "SELECT i.id FROM issues i \
     JOIN threads t ON t.id = i.thread_id \
     WHERE i.id = $1 AND t.user_id = $2 FOR UPDATE OF i";
const MAPPING_IDENTITY_SQL: &str =
    "SELECT id, entity_type, provider FROM external_identities WHERE id = $1";
const MAPPING_CONFLICT_SQL: &str = "SELECT id FROM issue_external_identity_mappings m \
     JOIN external_identities e ON e.id = m.external_identity_id \
     WHERE m.issue_id = $1 AND m.status = 'confirmed' AND m.external_identity_id <> $2 AND e.provider = $3 \
     LIMIT 1";
const MAPPING_LOOKUP_SQL: &str = "SELECT id FROM issue_external_identity_mappings \
     WHERE issue_id = $1 AND external_identity_id = $2";
const MAPPING_INSERT_SQL: &str = "INSERT INTO issue_external_identity_mappings \
        (issue_id, external_identity_id, status, evidence_source, confidence, rejection_reason, evidence_json, created_at, updated_at) \
     VALUES ($1, $2, $3, $4, $5, $6, '{}'::json, NOW(), NOW())";
const MAPPING_UPDATE_SQL: &str = "UPDATE issue_external_identity_mappings SET \
        status = $2, evidence_source = $3, confidence = $4, rejection_reason = $5, updated_at = NOW() \
     WHERE id = $1";

const IDENTITY_SELECT_BY_IDENTITY_SQL: &str =
    "SELECT id FROM external_identities WHERE provider = 'comicvine' AND entity_type = 'issue' AND external_id = $1";

// ---------------------------------------------------------------------------
// Wire types
// ---------------------------------------------------------------------------

/// Python `SyncStatusSource`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SyncStatusSource {
    pub id: i32,
    pub reading_plan_id: i32,
    pub thread_id: i32,
    pub external_identity_id: i32,
    pub provider_volume_id: String,
    pub enabled: bool,
    pub last_synced_at: Option<DateTime<Utc>>,
}

/// Python `SyncStatusResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SyncStatusResponse {
    pub total_sources: i64,
    pub enabled_sources: i64,
    pub sources: Vec<SyncStatusSource>,
}

/// Python `SyncRequest`. `as_of` accepts RFC 3339 and the naive shapes
/// Python's `datetime.fromisoformat` accepts (`T`/space separated, optional
/// fractional seconds, optional numeric offset, bare date); naive values are
/// treated as UTC. `refresh` defaults to `true`.
#[derive(Debug, Clone, Deserialize, utoipa::ToSchema)]
pub struct SyncRequest {
    #[serde(deserialize_with = "deserialize_as_of")]
    pub as_of: DateTime<Utc>,
    #[serde(default = "default_refresh")]
    pub refresh: bool,
}

fn default_refresh() -> bool {
    true
}

fn parse_as_of(raw: &str) -> Option<DateTime<Utc>> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return None;
    }
    let normalized = if trimmed.ends_with(['Z', 'z']) {
        format!("{}+00:00", &trimmed[..trimmed.len() - 1])
    } else {
        trimmed.to_string()
    };
    if let Ok(parsed) = DateTime::parse_from_rfc3339(&normalized) {
        return Some(parsed.with_timezone(&Utc));
    }
    for format in [
        "%Y-%m-%dT%H:%M:%S%.f",
        "%Y-%m-%d %H:%M:%S%.f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ] {
        if let Ok(parsed) = NaiveDateTime::parse_from_str(&normalized, format) {
            return Some(parsed.and_utc());
        }
    }
    if let Ok(date) = NaiveDate::parse_from_str(&normalized, "%Y-%m-%d") {
        return Some(date.and_time(NaiveTime::MIN).and_utc());
    }
    None
}

fn deserialize_as_of<'de, D>(deserializer: D) -> Result<DateTime<Utc>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let raw = String::deserialize(deserializer)?;
    parse_as_of(&raw)
        .ok_or_else(|| serde::de::Error::custom("as_of must be a valid ISO-8601 datetime"))
}

/// Python `SourceSyncFailure`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SourceSyncFailure {
    pub source_id: i32,
    pub plan_id: i32,
    pub thread_id: i32,
    pub volume_id: i32,
    pub error: String,
}

/// Python `SyncReport` (counters plus bounded failures).
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
    pub excluded_sources: i64,
    pub excluded_issues: i64,
    pub skipped_sources: i64,
    pub failures: Vec<SourceSyncFailure>,
}

impl SyncReport {
    fn empty(total_sources: i64, enabled_sources: i64) -> Self {
        Self {
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
        }
    }

    fn success(&self) -> bool {
        self.failed_sources == 0 && self.issue_failures == 0
    }
}

/// Python `SyncResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SyncResponse {
    pub success: bool,
    pub message: String,
    pub result: SyncReport,
}

fn sync_message(report: &SyncReport) -> String {
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

// ---------------------------------------------------------------------------
// Provider boundary
// ---------------------------------------------------------------------------

/// One decoded provider response plus cache provenance.
#[derive(Debug, Clone)]
pub struct ProviderPayload {
    pub payload: Value,
    pub from_cache: bool,
}

/// Minimal ComicVine boundary needed by the sync run. Implementations may
/// reach the live provider or a scripted test double; the pipeline never
/// touches the network without going through this trait.
pub trait ComicVineSyncProvider: Send + Sync {
    fn fetch_volume_issues<'a>(
        &'a self,
        volume_id: i32,
        refresh: bool,
    ) -> Pin<Box<dyn Future<Output = Result<Vec<Value>, String>> + Send + 'a>>;
    fn fetch_issue<'a>(
        &'a self,
        issue_id: i64,
    ) -> Pin<Box<dyn Future<Output = Result<ProviderPayload, String>> + Send + 'a>>;
    fn fetch_story_arc<'a>(
        &'a self,
        arc_id: i64,
    ) -> Pin<Box<dyn Future<Output = Result<(), String>> + Send + 'a>>;
}

/// Result of attempting to build the provider from the environment, mirroring
/// Python's `build_comicvine_client` (a missing key is an `ValueError`
/// captured as a per-source failure, not a 500).
pub enum ProviderHandle {
    Ready(Box<dyn ComicVineSyncProvider>),
    Unavailable(String),
}

impl ProviderHandle {
    /// Build the live provider from `COMICVINE_API_KEY` / `COMICVINE_CACHE_DIR`.
    pub fn from_env() -> Self {
        let api_key = std::env::var("COMICVINE_API_KEY")
            .map(|value| value.trim().to_string())
            .unwrap_or_default();
        if api_key.is_empty() {
            return Self::Unavailable("api_key is required".to_string());
        }
        let cache_dir = std::env::var("COMICVINE_CACHE_DIR")
            .map(std::path::PathBuf::from)
            .unwrap_or_else(|_| std::path::PathBuf::from("/tmp/comicpile-comicvine"));
        Self::Ready(Box::new(LiveComicVineProvider { api_key, cache_dir }))
    }
}

const COMICVINE_HOST: &str = "comicvine.gamespot.com";
const PAGE_LIMIT: usize = 100;
const MAX_PROVIDER_BODY: usize = 32 * 1024 * 1024;
const PROVIDER_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(30);

/// Live ComicVine client with the Python-compatible file cache.
pub struct LiveComicVineProvider {
    api_key: String,
    cache_dir: std::path::PathBuf,
}

impl LiveComicVineProvider {
    fn cache_key(endpoint: &str, params: &BTreeMap<String, Value>) -> String {
        // Mirrors Python `json.dumps([endpoint, safe_params], sort_keys=True,
        // separators=(",", ":"))` with sha256, without letting the api_key
        // into the digest. BTreeMap iteration is already sorted by key.
        let mut rendered = String::from("[\"");
        rendered.push_str(endpoint);
        rendered.push_str("\",{");
        let mut first = true;
        for (key, value) in params {
            if !first {
                rendered.push(',');
            }
            first = false;
            rendered.push('"');
            rendered.push_str(key);
            rendered.push_str("\":");
            rendered.push_str(&value.to_string());
        }
        rendered.push_str("}]");
        format!("{}-{}", endpoint, hex_sha256(&rendered))
    }

    fn cache_path(&self, endpoint: &str, params: &BTreeMap<String, Value>) -> std::path::PathBuf {
        self.cache_dir
            .join("responses")
            .join(format!("{}.json", Self::cache_key(endpoint, params)))
    }

    fn read_cache(&self, endpoint: &str, params: &BTreeMap<String, Value>) -> Option<Value> {
        let text = std::fs::read_to_string(self.cache_path(endpoint, params)).ok()?;
        let payload: Value = serde_json::from_str(&text).ok()?;
        payload.is_object().then_some(payload)
    }

    fn write_cache(&self, endpoint: &str, params: &BTreeMap<String, Value>, payload: &Value) {
        let path = self.cache_path(endpoint, params);
        if let Some(parent) = path.parent() {
            if std::fs::create_dir_all(parent).is_err() {
                tracing::warn!("comicvine cache directory unavailable; skipping cache write");
                return;
            }
        }
        let mut sorted = payload.clone();
        sort_json_keys(&mut sorted);
        let text = match serde_json::to_string(&sorted) {
            Ok(text) => text,
            Err(error) => {
                tracing::debug!(
                    error_kind = crate::error_kind(&error),
                    "comicvine cache payload serialization failed"
                );
                return;
            }
        };
        let temporary = path.with_extension("tmp");
        if std::fs::write(&temporary, text).is_ok() {
            let _ = std::fs::rename(&temporary, &path);
        }
    }

    async fn request_json(
        &self,
        endpoint: &str,
        params: &BTreeMap<String, Value>,
        refresh: bool,
    ) -> Result<ProviderPayload, String> {
        if !refresh {
            if let Some(payload) = self.read_cache(endpoint, params) {
                return Ok(ProviderPayload {
                    payload,
                    from_cache: true,
                });
            }
        }
        let mut query = String::new();
        for (key, value) in params {
            if !query.is_empty() {
                query.push('&');
            }
            query.push_str(key);
            query.push('=');
            query.push_str(&url_encode(&value.to_string()));
        }
        if !query.is_empty() {
            query.push('&');
        }
        query.push_str("api_key=");
        query.push_str(&url_encode(&self.api_key));
        query.push_str("&format=json");
        let path = if endpoint == "issues" {
            format!("/api/issues/?{query}")
        } else {
            format!("/api/{endpoint}?{query}")
        };

        let result = tokio::time::timeout(PROVIDER_TIMEOUT, self.fetch(&path)).await;
        let result = match result {
            Ok(inner) => inner,
            Err(_) => {
                // Cache fallback on failure, mirroring the Python throttled
                // path: a cached successful payload is better than none.
                if let Some(payload) = self.read_cache(endpoint, params) {
                    return Ok(ProviderPayload {
                        payload,
                        from_cache: true,
                    });
                }
                return Err("ComicVine request timed out".to_string());
            }
        };
        match result {
            Ok(payload) => {
                self.write_cache(endpoint, params, &payload);
                Ok(ProviderPayload {
                    payload,
                    from_cache: false,
                })
            }
            Err(FetchFailure::Throttled) => {
                if let Some(payload) = self.read_cache(endpoint, params) {
                    return Ok(ProviderPayload {
                        payload,
                        from_cache: true,
                    });
                }
                Err("ComicVine returned HTTP 429".to_string())
            }
            Err(FetchFailure::Unavailable) => {
                if let Some(payload) = self.read_cache(endpoint, params) {
                    return Ok(ProviderPayload {
                        payload,
                        from_cache: true,
                    });
                }
                Err("ComicVine request failed".to_string())
            }
            Err(FetchFailure::Invalid) => Err(concat!(
                "ComicVine response JSON decode failed or was invalid; ",
                "refusing to use it"
            )
            .to_string()),
        }
    }

    async fn fetch(&self, path: &str) -> Result<Value, FetchFailure> {
        use bytes::Bytes;
        use http_body_util::{BodyExt, Empty};
        use hyper::{client::conn::http1, StatusCode};
        use hyper_util::rt::TokioIo;

        let tcp = tokio::net::TcpStream::connect((COMICVINE_HOST, 443))
            .await
            .map_err(|_| FetchFailure::Unavailable)?;
        let tls = native_tls::TlsConnector::new().map_err(|_| FetchFailure::Unavailable)?;
        let tls = tokio_native_tls::TlsConnector::from(tls)
            .connect(COMICVINE_HOST, tcp)
            .await
            .map_err(|_| FetchFailure::Unavailable)?;
        let (mut sender, connection) =
            http1::handshake(TokioIo::new(tls))
                .await
                .map_err(|_| FetchFailure::Unavailable)?;
        let connection_guard = ConnectionGuard(tokio::spawn(async move {
            let _ = connection.await;
        }));
        let request = http::Request::builder()
            .method("GET")
            .uri(path)
            .header("host", COMICVINE_HOST)
            .header("accept", "application/json")
            .header("user-agent", "ComicPile/1.0")
            .body(Empty::<Bytes>::new())
            .map_err(|_| FetchFailure::Unavailable)?;
        let mut response = sender
            .send_request(request)
            .await
            .map_err(|_| FetchFailure::Unavailable)?;
        let status = response.status();
        if status == StatusCode::TOO_MANY_REQUESTS
            || status == StatusCode::FORBIDDEN
            || status.as_u16() == 420
        {
            drop(connection_guard);
            return Err(FetchFailure::Throttled);
        }
        if !status.is_success() {
            return Err(FetchFailure::Unavailable);
        }
        if response
            .headers()
            .get("content-length")
            .and_then(|h| h.to_str().ok())
            .and_then(|n| n.parse::<usize>().ok())
            .is_some_and(|n| n > MAX_PROVIDER_BODY)
        {
            return Err(FetchFailure::Invalid);
        }
        let mut data = Vec::new();
        while let Some(frame) = response.body_mut().frame().await {
            let frame = frame.map_err(|_| FetchFailure::Unavailable)?;
            if let Ok(bytes) = frame.into_data() {
                if data.len() + bytes.len() > MAX_PROVIDER_BODY {
                    return Err(FetchFailure::Invalid);
                }
                data.extend_from_slice(&bytes);
            }
        }
        drop(connection_guard);
        let payload: Value = serde_json::from_slice(&data).map_err(|_| FetchFailure::Invalid)?;
        if !payload.is_object() {
            return Err(FetchFailure::Invalid);
        }
        if let Some(code) = payload.get("status_code").and_then(Value::as_i64) {
            if code != 1 {
                return Err(FetchFailure::Invalid);
            }
        }
        Ok(payload)
    }

    async fn fetch_page(
        &self,
        volume_id: i32,
        offset: usize,
        refresh: bool,
    ) -> Result<(Vec<Value>, Option<i64>), String> {
        let mut params = BTreeMap::new();
        params.insert("filter".to_string(), json!(format!("volume:{volume_id}")));
        params.insert("limit".to_string(), json!(PAGE_LIMIT as i64));
        params.insert("offset".to_string(), json!(offset as i64));
        let response = self.request_json("issues", &params, refresh).await?;
        let results = response
            .payload
            .get("results")
            .and_then(Value::as_array)
            .cloned()
            .ok_or_else(|| "ComicVine /issues response did not contain a results list".to_string())?;
        let mut rows = Vec::with_capacity(results.len());
        for row in results {
            if !row.is_object() {
                continue;
            }
            if let Some(volume) = row.get("volume").and_then(Value::as_object) {
                if let Some(id) = volume.get("id").and_then(Value::as_i64) {
                    if id != i64::from(volume_id) {
                        return Err(
                            "ComicVine /issues ignored the requested volume filter; refusing mixed data"
                                .to_string(),
                        );
                    }
                }
            }
            rows.push(row);
        }
        let total = response
            .payload
            .get("number_of_total_results")
            .and_then(Value::as_i64);
        Ok((rows, total))
    }
}

enum FetchFailure {
    Throttled,
    Unavailable,
    Invalid,
}

// Provider requests are in flight for the lifetime of the awaited Vercel
// request; never let the HTTP driver outlive it.
struct ConnectionGuard(tokio::task::JoinHandle<()>);
impl Drop for ConnectionGuard {
    fn drop(&mut self) {
        self.0.abort();
    }
}

fn hex_sha256(text: &str) -> String {
    use sha2::{Digest, Sha256};
    let digest = Sha256::digest(text.as_bytes());
    let mut out = String::with_capacity(digest.len() * 2);
    for byte in digest {
        out.push_str(&format!("{byte:02x}"));
    }
    out
}

fn sort_json_keys(value: &mut Value) {
    match value {
        Value::Object(map) => {
            let mut sorted = Map::new();
            for (key, val) in std::mem::take(map) {
                let mut val = val;
                sort_json_keys(&mut val);
                sorted.insert(key, val);
            }
            *map = sorted;
        }
        Value::Array(items) => {
            for item in items.iter_mut() {
                sort_json_keys(item);
            }
        }
        _ => {}
    }
}

fn url_encode(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for byte in value.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(byte as char)
            }
            _ => out.push_str(&format!("%{byte:02X}")),
        }
    }
    out
}

impl ComicVineSyncProvider for LiveComicVineProvider {
    fn fetch_volume_issues<'a>(
        &'a self,
        volume_id: i32,
        refresh: bool,
    ) -> Pin<Box<dyn Future<Output = Result<Vec<Value>, String>> + Send + 'a>> {
        Box::pin(async move {
            let (first_rows, first_total) = self.fetch_page(volume_id, 0, refresh).await?;
            match first_total {
                None => {
                    let mut rows = first_rows;
                    if rows.len() < PAGE_LIMIT {
                        return Ok(rows);
                    }
                    let mut offset = rows.len();
                    loop {
                        let (page_rows, _) = self.fetch_page(volume_id, offset, refresh).await?;
                        let fetched = page_rows.len();
                        rows.extend(page_rows);
                        if fetched < PAGE_LIMIT {
                            return Ok(rows);
                        }
                        offset += fetched;
                    }
                }
                Some(total) => {
                    let mut rows = first_rows;
                    if (rows.len() as i64) >= total || rows.len() < PAGE_LIMIT {
                        return Ok(rows);
                    }
                    let pages_needed = (total as usize).div_ceil(PAGE_LIMIT);
                    for page in 1..pages_needed {
                        let (page_rows, _) = self
                            .fetch_page(volume_id, page * PAGE_LIMIT, refresh)
                            .await?;
                        rows.extend(page_rows);
                    }
                    Ok(rows)
                }
            }
        })
    }

    fn fetch_issue<'a>(
        &'a self,
        issue_id: i64,
    ) -> Pin<Box<dyn Future<Output = Result<ProviderPayload, String>> + Send + 'a>> {
        Box::pin(async move {
            let mut params = BTreeMap::new();
            params.insert("field_list".to_string(), json!(DEEP_ISSUE_FIELDS.join(",")));
            let endpoint = format!("issue/4000-{issue_id}");
            self.request_json(&endpoint, &params, false).await
        })
    }

    fn fetch_story_arc<'a>(
        &'a self,
        arc_id: i64,
    ) -> Pin<Box<dyn Future<Output = Result<(), String>> + Send + 'a>> {
        Box::pin(async move {
            let params = BTreeMap::new();
            let endpoint = format!("story_arc/4045-{arc_id}");
            self.request_json(&endpoint, &params, false).await.map(|_| ())
        })
    }
}

const DEEP_ISSUE_FIELDS: [&str; 12] = [
    "id",
    "name",
    "issue_number",
    "cover_date",
    "store_date",
    "image",
    "volume",
    "person_credits",
    "character_credits",
    "team_credits",
    "story_arc_credits",
    "date_last_updated",
];
