//! Bounded, awaited ComicVine metadata-repair worker.
//! A Vercel request is the lifetime of the work: never spawn and forget a task.
use crate::{
    db,
    outbound::{OutboundHttp, OutboundRequest},
    ApiError, AppState,
};
use axum::{
    extract::State,
    http::{HeaderMap, StatusCode},
    Json,
};
use bytes::Bytes;
use http_body_util::BodyExt;
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use std::{
    sync::{Arc, LazyLock},
    time::Duration,
};
use tokio_postgres::Transaction;

const HOST: &str = "comicvine.gamespot.com";
const MAX_BODY: usize = 2_000_000;
const BATCH_LIMIT: usize = 8;
const PROVIDER_TIMEOUT: Duration = Duration::from_secs(5);
// Shared with comicvine_issue.rs READ_SQL: complete rows stay fresh 30 days;
// a deep response with empty credits is rechecked after 7 days. The two
// implementations must use the same precise policy (see needs_provider_fetch).
const COMPLETE_FRESH_DAYS: i64 = 30;
const EMPTY_CREDIT_RECHECK_DAYS: i64 = 7;

pub(crate) const FIELDS: &str = "id,name,issue_number,cover_date,store_date,image,volume,person_credits,character_credits,team_credits,story_arc_credits,date_last_updated";
/// Bound every backfill invocation so an operator cannot enqueue the whole
/// library in one request (#5592 AC3).
pub const BACKFILL_MAX_LIMIT: i32 = 500;
/// SQL predicate for a ComicVine issue identity whose deep provider metadata
/// is missing or incomplete. `e` is the `external_identities` alias. Import
/// and backfill use the same predicate so a roster-only identity is enqueued
/// once and a hydrated identity is never reopened by a later reimport
/// (#5592 AC1/AC3). The full freshness window logic lives in
/// `comicvine_issue::READ_SQL` and `needs_provider_fetch`; those paths still
/// handle genuine staleness of already-hydrated rows.
const NEEDS_DEEP_FETCH_SQL: &str =
    "(e.metadata_json::jsonb->>'deep_metadata_refreshed_at' IS NULL \
     OR NOT COALESCE((e.metadata_json::jsonb->'raw_provider_payload') ?& ARRAY[ \
       'id','name','issue_number','cover_date','store_date','image','volume', \
       'person_credits','character_credits','team_credits','story_arc_credits', \
       'date_last_updated'], false))";
/// Set-based, idempotent hydration enqueue. One statement for the whole
/// batch, with no per-issue SQL and no provider call (#5592 AC1).
static ENQUEUE_BATCH_SQL: LazyLock<String> = LazyLock::new(|| {
    format!(
        "INSERT INTO comicvine_metadata_refresh_requests \
           (external_identity_id, state, attempts, next_attempt_at, created_at, updated_at) \
         SELECT e.id, 'pending', 0, now(), now(), now() \
         FROM external_identities e \
         WHERE e.id = ANY($1::int[]) \
           AND e.provider = 'comicvine' AND e.entity_type = 'issue' \
           AND {NEEDS_DEEP_FETCH_SQL} \
           AND NOT EXISTS (SELECT 1 FROM comicvine_metadata_refresh_requests r \
                           WHERE r.external_identity_id = e.id) \
         ON CONFLICT ON CONSTRAINT uq_comicvine_metadata_refresh_identity DO NOTHING"
    )
});
const CLAIM: &str = r#"
WITH candidate AS (
  SELECT id FROM comicvine_metadata_refresh_requests
  WHERE (state IN ('pending', 'deferred', 'failed') AND next_attempt_at <= now())
     OR (state = 'running' AND (lease_expires_at IS NULL OR lease_expires_at <= now()))
  ORDER BY next_attempt_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
), claimed AS (
  UPDATE comicvine_metadata_refresh_requests r SET state='running',
    attempts=r.attempts+1, lease_expires_at=now()+interval '120 seconds',
    updated_at=now()
  WHERE r.id=(SELECT id FROM candidate)
  RETURNING r.id, r.external_identity_id, r.attempts
)
SELECT c.id, c.external_identity_id, c.attempts, e.external_id,
       e.provider, e.entity_type, e.metadata_json::text
FROM claimed c LEFT JOIN external_identities e ON e.id=c.external_identity_id
"#;
const SETTLE: &str = r#"
UPDATE comicvine_metadata_refresh_requests
SET state=($4::text)::varchar, lease_expires_at=NULL,
    next_attempt_at=now()+($5::integer * interval '1 second'),
    last_error=$6, completed_at=CASE WHEN ($4::text) IN ('completed','no_credits')
      THEN now() ELSE NULL END, updated_at=now()
WHERE id=$1 AND external_identity_id=$2 AND attempts=$3
  AND state='running' AND lease_expires_at > now()
RETURNING id
"#;
const PERSIST: &str = r#"
WITH lease AS (
  SELECT id FROM comicvine_metadata_refresh_requests
  WHERE id=$2 AND external_identity_id=$1 AND attempts=$3
    AND state='running' AND lease_expires_at > now()
  FOR UPDATE
), hydrated AS (
  UPDATE external_identities e SET
    metadata_json=(e.metadata_json::jsonb || ($4::text)::jsonb)::json,
    external_url=COALESCE($5, e.external_url),
    provider_updated_at=COALESCE(($6::text)::timestamptz, e.provider_updated_at),
    updated_at=now()
  WHERE e.id=$1 AND e.provider='comicvine' AND e.entity_type='issue'
    AND EXISTS (SELECT 1 FROM lease)
  RETURNING e.id
), settled AS (
  UPDATE comicvine_metadata_refresh_requests r
  SET state=$7, lease_expires_at=NULL, next_attempt_at=now(),
    last_error=NULL, completed_at=now(), updated_at=now()
  WHERE r.id=$2 AND EXISTS (SELECT 1 FROM hydrated)
  RETURNING r.id
)
SELECT EXISTS(SELECT 1 FROM settled)
"#;

#[derive(Debug)]
struct Job {
    id: i32,
    identity_id: i32,
    attempt: i32,
    external_id: Option<String>,
    provider: Option<String>,
    entity_type: Option<String>,
    metadata: Option<String>,
}

#[derive(Default, Serialize)]
pub struct DrainReport {
    claimed: u32,
    completed: u32,
    no_credits: u32,
    deferred: u32,
    failed: u32,
    provider_configured: bool,
}

#[derive(Debug)]
pub(crate) enum ProviderFailure {
    RateLimited(u32),
    Unavailable,
    Timeout,
    InvalidPayload,
}

/// Authorize the ComicVine metadata-repair cron route through the same shared
/// gate as the release-sync cron. [`crate::cron_auth::authorize_cron_http`] owns
/// the fail-closed placeholder rejection, case-insensitive `Bearer` scheme
/// (RFC 6750, Python's `scheme.lower()`), constant-time compare and the crucial
/// 503 (unconfigured) vs 401 (bad bearer) status split. Keeping the typed
/// `Result` here instead of collapsing it to a `bool` is what preserves Python's
/// `require_cron_secret` contract on this route.
fn authorize(headers: &HeaderMap, expected: Option<&str>) -> Result<(), ApiError> {
    crate::cron_auth::authorize_cron_http(headers, expected)
}

fn issue_id(external_id: &str) -> Option<u32> {
    let raw = external_id.strip_prefix("4000-").unwrap_or(external_id);
    raw.parse::<u32>().ok().filter(|id| *id > 0)
}

fn compact_refs(value: &Value) -> Value {
    Value::Array(
        value
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|v| {
                let source = v.as_object()?;
                let mut compact = Map::new();
                for field in ["id", "name", "api_detail_url", "site_detail_url", "role"] {
                    if let Some(value) = source.get(field) {
                        compact.insert(field.to_owned(), value.clone());
                    }
                }
                Some(Value::Object(compact))
            })
            .collect(),
    )
}

/// Normalize a roster row for catalog commit without claiming a deep refresh.
pub(crate) fn normalize_roster_issue_metadata(result: &Value) -> Value {
    let volume = result
        .get("volume")
        .and_then(Value::as_object)
        .map(|source| {
            let mut compact = Map::new();
            for field in ["id", "name", "api_detail_url", "site_detail_url"] {
                if let Some(value) = source.get(field) {
                    compact.insert(field.to_owned(), value.clone());
                }
            }
            Value::Object(compact)
        });
    let primary_image = result
        .get("image")
        .and_then(Value::as_object)
        .and_then(|image| {
            ["original_url", "super_url", "medium_url", "small_url"]
                .iter()
                .filter_map(|key| image.get(*key).and_then(Value::as_str))
                .find(|value| !value.is_empty())
        });
    json!({
        "name": result.get("name"),
        "issue_number": result.get("issue_number"),
        "cover_date": result.get("cover_date"),
        "store_date": result.get("store_date"),
        "volume": volume,
        "primary_image": primary_image,
        "creator_credits": compact_refs(&result["person_credits"]),
        "characters": compact_refs(&result["character_credits"]),
        "teams": compact_refs(&result["team_credits"]),
        "story_arcs": compact_refs(&result["story_arc_credits"]),
        "raw_provider_payload": result,
    })
}

fn normalized_metadata(
    result: &Value,
    expected_id: u32,
) -> Result<(Value, bool, Option<String>, Option<String>), ProviderFailure> {
    let obj = result.as_object().ok_or(ProviderFailure::InvalidPayload)?;
    if obj.get("id").and_then(Value::as_u64) != Some(u64::from(expected_id)) {
        return Err(ProviderFailure::InvalidPayload);
    }
    for field in [
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
    ] {
        if !obj.contains_key(field) {
            return Err(ProviderFailure::InvalidPayload);
        }
    }
    let image = obj.get("image").and_then(Value::as_object);
    let cover = image.and_then(|v| {
        ["original_url", "super_url", "medium_url", "small_url"]
            .iter()
            .filter_map(|k| v.get(*k).and_then(Value::as_str))
            .find(|s| !s.is_empty())
    });
    let person = compact_refs(&result["person_credits"]);
    let present = person.as_array().is_some_and(|v| !v.is_empty());
    let patch = json!({
        "name": result["name"],
        "issue_number": result["issue_number"],
        "cover_date": result["cover_date"],
        "store_date": result["store_date"],
        "volume": compact_refs(&json!([result["volume"]])).as_array().and_then(|v|v.first()).cloned(),
        "primary_image": cover,
        "creator_credits": person,
        "characters": compact_refs(&result["character_credits"]),
        "teams": compact_refs(&result["team_credits"]),
        "story_arcs": compact_refs(&result["story_arc_credits"]),
        "raw_provider_payload": result,
        "deep_metadata_refreshed_at": chrono::Utc::now().to_rfc3339(),
    });
    let url = result["site_detail_url"]
        .as_str()
        .filter(|s| s.starts_with("https://comicvine.gamespot.com/"))
        .map(str::to_owned);
    let updated = provider_timestamp(&result["date_last_updated"]);
    Ok((patch, present, url, updated))
}

/// Parse ComicVine's provider revision stamp.
///
/// ComicVine documents RFC 3339 timestamps but the live API commonly returns
/// `YYYY-MM-DD HH:MM:SS` without an offset. Both forms are UTC-equivalent, so
/// accept either instead of silently dropping the provider revision clock.
fn provider_timestamp(value: &Value) -> Option<String> {
    let stamp = value.as_str()?;
    if let Ok(parsed) = chrono::DateTime::parse_from_rfc3339(stamp) {
        return Some(parsed.to_rfc3339());
    }
    let naive = chrono::NaiveDateTime::parse_from_str(stamp, "%Y-%m-%d %H:%M:%S").ok()?;
    Some(
        chrono::DateTime::<chrono::Utc>::from_naive_utc_and_offset(naive, chrono::Utc).to_rfc3339(),
    )
}

/// Raw outcome of one ComicVine exchange, before a caller applies its own
/// throttle and envelope policy (the repair worker and the browser routes
/// mirror different retired Python clients).
#[derive(Debug)]
pub(crate) enum Exchange {
    /// A decoded JSON body from a 2xx response.
    Payload(Value),
    /// HTTP 403, 420 or 429 with the raw `Retry-After` header, if any.
    Throttled {
        status: u16,
        retry_after: Option<String>,
    },
}

/// Python `ComicVineClient._request_async` envelope rule: `status_code` may
/// be absent, null, `true` or `1` (including the JSON float `1.0`), and
/// anything else is a provider error. The browser routes already use this
/// rule through `comicvine_limits::browser_envelope_ok`; the repair worker
/// previously required `as_i64() == Some(1)` and misclassified valid `1.0`
/// / `true` / absent-status responses as `provider_unavailable` while the
/// singular Python fetch succeeded. Share one implementation so the two
/// paths cannot drift again (#5592 AC2).
pub(crate) fn provider_envelope_ok(payload: &Value) -> bool {
    let Some(object) = payload.as_object() else {
        return false;
    };
    match object.get("status_code") {
        None | Some(Value::Null) | Some(Value::Bool(true)) => true,
        Some(Value::Number(n)) => n.as_f64() == Some(1.0),
        Some(_) => false,
    }
}

/// One repair-worker provider call: 429/403 are throttles whose
/// `Retry-After` is clamped to 60..=3600 s, other non-2xx statuses (420
/// included) are unavailable, and the envelope must satisfy the Python
/// `status_code` rule above.
pub(crate) async fn provider_response(
    outbound: &Arc<dyn OutboundHttp>,
    resource: &str,
    extra_query: &str,
    api_key: &str,
) -> Result<Value, ProviderFailure> {
    match provider_exchange(outbound, resource, extra_query, api_key).await? {
        Exchange::Throttled {
            status: 429 | 403,
            retry_after,
        } => Err(ProviderFailure::RateLimited(
            retry_after
                .and_then(|h| h.parse::<u32>().ok())
                .unwrap_or(60)
                .clamp(60, 3600),
        )),
        Exchange::Throttled { .. } => Err(ProviderFailure::Unavailable),
        Exchange::Payload(payload) if provider_envelope_ok(&payload) => Ok(payload),
        Exchange::Payload(_) => Err(ProviderFailure::Unavailable),
    }
}

pub(crate) async fn provider_exchange(
    outbound: &Arc<dyn OutboundHttp>,
    resource: &str,
    extra_query: &str,
    api_key: &str,
) -> Result<Exchange, ProviderFailure> {
    // Callers construct only trusted resource names and numeric query values.
    // Fail closed on unexpected credential syntax rather than sending an unescaped secret.
    if api_key.is_empty() || !api_key.bytes().all(|c| c.is_ascii_alphanumeric()) {
        return Err(ProviderFailure::Unavailable);
    }
    let request = OutboundRequest {
        method: http::Method::GET,
        path: format!("/api/{resource}/?api_key={api_key}&format=json{extra_query}"),
        headers: vec![
            ("accept".to_string(), "application/json".to_string()),
            (
                "user-agent".to_string(),
                "ComicPile/1.0 (metadata repair)".to_string(),
            ),
        ],
        body: Bytes::new(),
    };
    let exchange = async {
        let response = outbound.send(HOST, request).await.map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            ProviderFailure::Unavailable
        })?;
        let status = response.status;
        if status == StatusCode::TOO_MANY_REQUESTS
            || status == StatusCode::FORBIDDEN
            || status.as_u16() == 420
        {
            return Ok(Exchange::Throttled {
                status: status.as_u16(),
                retry_after: response
                    .headers
                    .get("retry-after")
                    .and_then(|h| h.to_str().ok())
                    .map(str::to_owned),
            });
        }
        if !status.is_success() {
            return Err(ProviderFailure::Unavailable);
        }
        if response
            .headers
            .get("content-length")
            .and_then(|h| h.to_str().ok())
            .and_then(|n| n.parse::<usize>().ok())
            .is_some_and(|n| n > MAX_BODY)
        {
            return Err(ProviderFailure::InvalidPayload);
        }
        let mut data = Vec::new();
        let mut body = response.body;
        while let Some(frame) = body.frame().await {
            let frame = frame.map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                ProviderFailure::Unavailable
            })?;
            if let Ok(bytes) = frame.into_data() {
                if data.len() + bytes.len() > MAX_BODY {
                    return Err(ProviderFailure::InvalidPayload);
                }
                data.extend_from_slice(&bytes);
            }
        }
        let payload: Value = serde_json::from_slice(&data).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            ProviderFailure::InvalidPayload
        })?;
        Ok(Exchange::Payload(payload))
    };
    tokio::time::timeout(PROVIDER_TIMEOUT, exchange)
        .await
        .map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            ProviderFailure::Timeout
        })?
}

async fn provider_issue(
    outbound: &Arc<dyn OutboundHttp>,
    id: u32,
    api_key: &str,
) -> Result<Value, ProviderFailure> {
    provider_response(
        outbound,
        &format!("issue/4000-{id}"),
        &format!("&field_list={FIELDS}"),
        api_key,
    )
    .await?
    .get("results")
    .cloned()
    .ok_or(ProviderFailure::InvalidPayload)
}

/// Read the same ComicVine volume and complete, validated issue roster used
/// by the Python preview builder. Never turn an outage or partial roster into
/// an empty successful plan: doing so can approve a wrong comic identity.
pub(crate) async fn catalog_volume_roster(
    outbound: &Arc<dyn OutboundHttp>,
    external_id: &str,
) -> Result<(Value, Vec<Value>), ApiError> {
    // Test scaffolding only: an installed fixture short-circuits the live
    // provider so handler tests stay deterministic. Production never installs
    // one, so this is an inert map lookup.
    if let Some(fixture) = crate::test_support::lookup_test_volume_roster(external_id) {
        return Ok(fixture);
    }
    let unavailable = || ApiError::ServiceUnavailable("provider_unavailable".to_owned());
    let volume_id = external_id
        .parse::<u32>()
        .ok()
        .filter(|v| *v > 0)
        .ok_or_else(unavailable)?;
    let api_key = std::env::var("COMICVINE_API_KEY")
        .ok()
        .filter(|v| !v.is_empty())
        .ok_or_else(unavailable)?;
    let volume = provider_response(outbound, &format!("volume/4050-{volume_id}"), "", &api_key)
        .await
        .map_err(|_| unavailable())?;
    let volume_info = volume
        .get("results")
        .filter(|v| v.is_object())
        .ok_or_else(unavailable)?;
    let series_info = json!({
        "id": volume_info.get("id").map(ToString::to_string).map(|v| v.trim_matches('"').to_string()),
        "name": volume_info.get("name"),
        "publisher": volume_info.get("publisher").and_then(|p| p.get("name")),
        "start_year": volume_info.get("start_year"),
        "count_of_issues": volume_info.get("count_of_issues"),
        "site_detail_url": volume_info.get("site_detail_url"),
        "image": volume_info.get("image"),
    });

    let mut roster = Vec::new();
    let mut offset = 0_usize;
    let mut expected_total: Option<usize> = None;
    loop {
        let query = format!("&filter=volume:{volume_id}&limit=100&offset={offset}");
        let page = provider_response(outbound, "issues", &query, &api_key)
            .await
            .map_err(|_| unavailable())?;
        let results = page
            .get("results")
            .and_then(Value::as_array)
            .ok_or_else(unavailable)?;
        if expected_total.is_none() {
            expected_total = page
                .get("number_of_total_results")
                .and_then(Value::as_u64)
                .and_then(|n| usize::try_from(n).ok());
        }
        for row in results {
            if row
                .get("volume")
                .and_then(|v| v.get("id"))
                .and_then(Value::as_u64)
                .is_some_and(|id| id != u64::from(volume_id))
            {
                return Err(unavailable());
            }
            let Some(issue_number) = row.get("issue_number").filter(|v| !v.is_null()) else {
                continue;
            };
            let Some(pid) = row.get("id").and_then(Value::as_i64).filter(|id| *id > 0) else {
                continue;
            };
            let number = issue_number
                .as_str()
                .map(str::to_owned)
                .unwrap_or_else(|| issue_number.to_string());
            roster.push(json!({
                "issue_id": pid,
                "issue_number": number,
                "title": row.get("name"),
                "thread_id": null,
                "thread_title": null,
                "current_mapping_status": "unresolved",
                "provider": "comicvine",
                "external_id": pid.to_string(),
                "classification": "unresolved",
                "_roster_only": true,
                "_provider_metadata": row,
            }));
        }
        offset += results.len();
        if results.len() < 100 || expected_total.is_some_and(|n| offset >= n) {
            break;
        }
        // Reject a truncated or pathological roster rather than silently
        // authorizing false unique matches. The full provider roster is
        // required to prove issue-number cardinality.
        if offset >= 10_000 {
            return Err(unavailable());
        }
    }
    Ok((series_info, roster))
}

async fn claim(state: &AppState) -> Result<Option<Job>, ApiError> {
    let connection = db::checkout(state).await?;
    let row = connection
        .query_opt(CLAIM, &[])
        .await
        .map_err(db::query_error)?;
    row.map(|row| {
        Ok(Job {
            id: row.try_get(0).map_err(db::query_error)?,
            identity_id: row.try_get(1).map_err(db::query_error)?,
            attempt: row.try_get(2).map_err(db::query_error)?,
            external_id: row.try_get(3).map_err(db::query_error)?,
            provider: row.try_get(4).map_err(db::query_error)?,
            entity_type: row.try_get(5).map_err(db::query_error)?,
            metadata: row.try_get(6).map_err(db::query_error)?,
        })
    })
    .transpose()
}

async fn settle(
    state: &AppState,
    job: &Job,
    status: &str,
    delay: i32,
    error: Option<&str>,
) -> Result<(), ApiError> {
    let connection = db::checkout(state).await?;
    connection
        .query_opt(
            SETTLE,
            &[
                &job.id,
                &job.identity_id,
                &job.attempt,
                &status,
                &delay,
                &error,
            ],
        )
        .await
        .map_err(db::query_error)?;
    Ok(())
}

async fn persist(
    state: &AppState,
    job: &Job,
    patch: &Value,
    has_credits: bool,
    url: &Option<String>,
    updated: &Option<String>,
) -> Result<bool, ApiError> {
    let content = patch.to_string();
    let status = if has_credits {
        "completed"
    } else {
        "no_credits"
    };
    let connection = db::checkout(state).await?;
    let row = connection
        .query_one(
            PERSIST,
            &[
                &job.identity_id,
                &job.id,
                &job.attempt,
                &content,
                url,
                updated,
                &status,
            ],
        )
        .await
        .map_err(db::query_error)?;
    row.try_get(0).map_err(db::query_error)
}

fn failure_transition(error: &ProviderFailure, attempt: i32) -> (&'static str, i32, &'static str) {
    match error {
        ProviderFailure::RateLimited(delay) => {
            ("deferred", (*delay).min(3600) as i32, "rate_limit")
        }
        ProviderFailure::InvalidPayload if attempt >= 3 => {
            ("failed", 21600, "invalid_provider_payload")
        }
        ProviderFailure::InvalidPayload => ("deferred", 300, "invalid_provider_payload"),
        ProviderFailure::Unavailable if attempt >= 3 => ("failed", 21600, "provider_unavailable"),
        ProviderFailure::Unavailable => (
            "deferred",
            if attempt <= 1 { 60 } else { 300 },
            "provider_unavailable",
        ),
        ProviderFailure::Timeout if attempt >= 3 => ("failed", 21600, "provider_timeout"),
        ProviderFailure::Timeout => (
            "deferred",
            if attempt <= 1 { 60 } else { 300 },
            "provider_timeout",
        ),
    }
}

fn has_complete_provider_payload(metadata: &Value) -> bool {
    metadata["raw_provider_payload"]
        .as_object()
        .is_some_and(|raw| FIELDS.split(',').all(|key| raw.contains_key(key)))
}

fn cached_has_credits(metadata: &Value) -> bool {
    let creator = metadata["creator_credits"]
        .as_array()
        .is_some_and(|v| !v.is_empty());
    let raw = metadata["raw_provider_payload"]["person_credits"]
        .as_array()
        .is_some_and(|v| !v.is_empty());
    creator || raw
}

fn provider_newer_than_deep_fetch(metadata: &Value) -> bool {
    let deep = metadata["deep_metadata_refreshed_at"]
        .as_str()
        .and_then(|v| chrono::DateTime::parse_from_rfc3339(v).ok());
    let Some(deep) = deep else {
        return false;
    };
    provider_timestamp(&metadata["raw_provider_payload"]["date_last_updated"])
        .and_then(|v| chrono::DateTime::parse_from_rfc3339(&v).ok())
        .is_some_and(|provider| provider > deep)
}

/// Whether the worker must call the provider instead of settling from cache.
/// Must mirror comicvine_issue.rs freshness exactly: a provider revision
/// newer than the deep fetch is always stale; complete rows use 30 days;
/// empty-credit rows use 7 days. Malformed/absent timestamps are stale.
pub(crate) fn needs_provider_fetch(metadata: &Value, now: chrono::DateTime<chrono::Utc>) -> bool {
    if !has_complete_provider_payload(metadata) {
        return true;
    }
    if provider_newer_than_deep_fetch(metadata) {
        return true;
    }
    let Some(fetched_at) = metadata["deep_metadata_refreshed_at"]
        .as_str()
        .and_then(|v| chrono::DateTime::parse_from_rfc3339(v).ok())
    else {
        return true;
    };
    let age = now.signed_duration_since(fetched_at);
    let window = if cached_has_credits(metadata) {
        chrono::Duration::days(COMPLETE_FRESH_DAYS)
    } else {
        chrono::Duration::days(EMPTY_CREDIT_RECHECK_DAYS)
    };
    age >= window
}

/// Durably enqueue one pending hydration request per confirmed imported
/// identity that lacks deep relationship/creator metadata. Callers run this
/// inside the import transaction, so the work record commits atomically with
/// the adoption and never depends on the Roll issue page being opened
/// (#5592 AC1).
///
/// One set-based statement: no per-issue SQL, no provider fan-out. Rows that
/// already have a request in any state are left alone, so reimports dedup and
/// never reset a worker's attempts, lease or backoff. `ON CONFLICT DO NOTHING`
/// is a second dedup guard for a racing enqueue; it cannot deadlock against
/// the worker because enqueues hold the reader's queue advisory lock and the
/// worker only ever *updates* existing request rows.
pub(crate) async fn enqueue_hydration_batch(
    tx: &Transaction<'_>,
    identity_ids: &[i32],
) -> Result<usize, ApiError> {
    if identity_ids.is_empty() {
        return Ok(0);
    }
    let count = tx
        .execute(&*ENQUEUE_BATCH_SQL, &[&identity_ids])
        .await
        .map_err(db::query_error)?;
    Ok(usize::try_from(count).unwrap_or(usize::MAX))
}

/// Optional, bounded query contract for the maintenance backfill (#5592 AC3).
#[derive(Debug, Deserialize)]
pub struct BackfillQuery {
    pub dry_run: Option<bool>,
    pub limit: Option<i32>,
    /// Exclusive lower bound on identity ids; pass the report's
    /// `last_identity_id` to resume where the previous batch stopped.
    pub after_identity_id: Option<i32>,
}

/// Auditable result of one bounded backfill batch (#5592 AC3).
#[derive(Debug, Serialize)]
pub struct BackfillReport {
    pub dry_run: bool,
    pub limit: i32,
    pub scanned: i32,
    pub eligible: i32,
    pub enqueued: i32,
    pub already_present: i32,
    pub before_pending: i64,
    pub after_pending: i64,
    /// `None` means the batch was empty; otherwise feed it back as
    /// `after_identity_id` to continue.
    pub last_identity_id: Option<i32>,
}

/// CRON_SECRET-authenticated, bounded and resumable hydration backfill.
///
/// ```text
/// # dry run: counts only, no ledger writes
/// curl -X POST -H "Authorization: Bearer $CRON_SECRET" \
///   'https://comic-pile.vercel.app/api/v2/maintenance/comicvine-hydration-backfill?dry_run=true&limit=50'
/// # apply a batch, then pass the reported last_identity_id back as after_identity_id
/// curl -X POST -H "Authorization: Bearer $CRON_SECRET" \
///   'https://comic-pile.vercel.app/api/v2/maintenance/comicvine-hydration-backfill?limit=50&after_identity_id=12345'
/// ```
///
/// Identities are scanned by ascending id with `LIMIT`; because each enqueued
/// identity gains a request row, the next batch naturally starts after the
/// previous one without any stored cursor.
pub async fn backfill(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    query: Result<axum::extract::Query<BackfillQuery>, axum::extract::rejection::QueryRejection>,
) -> Result<Json<BackfillReport>, ApiError> {
    let axum::extract::Query(query) =
        query.map_err(|_| crate::ApiError::Unprocessable("Validation failed".to_owned()))?;
    let limit = query.limit.unwrap_or(BACKFILL_MAX_LIMIT);
    if !(1..=BACKFILL_MAX_LIMIT).contains(&limit) {
        return Err(crate::ApiError::Unprocessable(
            "Validation failed".to_owned(),
        ));
    }
    let after = query.after_identity_id.unwrap_or(0).max(0);
    let dry_run = query.dry_run.unwrap_or(false);
    let secret = std::env::var("CRON_SECRET").ok();
    let report =
        backfill_authorized(&state, &headers, secret.as_deref(), dry_run, limit, after).await?;
    Ok(Json(report))
}

async fn backfill_authorized(
    state: &AppState,
    headers: &HeaderMap,
    expected: Option<&str>,
    dry_run: bool,
    limit: i32,
    after: i32,
) -> Result<BackfillReport, ApiError> {
    authorize(headers, expected)?;
    let before_pending = count_by_state(state, "pending").await?;
    let candidates = {
        let connection = db::checkout(state).await?;
        connection
            .query(
                &format!(
                    "SELECT DISTINCT e.id, (r.id IS NOT NULL) AS has_request \
                     FROM external_identities e \
                     JOIN issue_external_identity_mappings m \
                       ON m.external_identity_id = e.id AND m.status = 'confirmed' \
                     JOIN issues i ON i.id = m.issue_id \
                     LEFT JOIN comicvine_metadata_refresh_requests r \
                       ON r.external_identity_id = e.id \
                     WHERE e.id > $1 AND e.provider = 'comicvine' \
                       AND e.entity_type = 'issue' AND {NEEDS_DEEP_FETCH_SQL} \
                     ORDER BY e.id LIMIT $2"
                ),
                &[&after, &limit],
            )
            .await
            .map_err(db::query_error)?
    };
    let scanned = candidates.len() as i32;
    let last_identity_id = candidates.last().map(|row| row.get::<_, i32>(0));
    let mut ids = Vec::with_capacity(candidates.len());
    let mut already_present = 0i32;
    for row in &candidates {
        let id = row.get::<_, i32>(0);
        if row.get::<_, bool>(1) {
            already_present += 1;
        } else {
            ids.push(id);
        }
    }
    let eligible = ids.len() as i32;
    let enqueued = if dry_run || ids.is_empty() {
        0
    } else {
        let mut connection = db::checkout(state).await?;
        let tx = connection.transaction().await.map_err(db::query_error)?;
        let inserted = enqueue_hydration_batch(&tx, &ids).await?;
        tx.commit().await.map_err(db::query_error)?;
        inserted as i32
    };
    let after_pending = count_by_state(state, "pending").await?;
    Ok(BackfillReport {
        dry_run,
        limit,
        scanned,
        eligible,
        enqueued,
        already_present,
        before_pending,
        after_pending,
        last_identity_id,
    })
}

async fn count_by_state(state: &AppState, state_name: &str) -> Result<i64, ApiError> {
    let connection = db::checkout(state).await?;
    let count: i64 = connection
        .query_one(
            "SELECT count(*) FROM comicvine_metadata_refresh_requests WHERE state = $1",
            &[&state_name],
        )
        .await
        .map_err(db::query_error)?
        .get(0);
    Ok(count)
}

async fn process(state: &AppState, job: &Job, key: Option<&str>) -> Result<&'static str, ApiError> {
    if job.provider.as_deref() != Some("comicvine") || job.entity_type.as_deref() != Some("issue") {
        settle(state, job, "failed", 21600, Some("identity_ineligible")).await?;
        return Ok("failed");
    }
    let Some(id) = job.external_id.as_deref().and_then(issue_id) else {
        settle(state, job, "failed", 21600, Some("invalid_external_id")).await?;
        return Ok("failed");
    };
    let cached: Option<Value> = job
        .metadata
        .as_deref()
        .and_then(|v| serde_json::from_str::<Value>(v).ok());
    if let Some(metadata) = &cached {
        if !needs_provider_fetch(metadata, chrono::Utc::now()) {
            let has = cached_has_credits(metadata);
            settle(
                state,
                job,
                if has { "completed" } else { "no_credits" },
                0,
                None,
            )
            .await?;
            return Ok(if has { "completed" } else { "no_credits" });
        }
    }
    let Some(key) = key else {
        settle(
            state,
            job,
            "deferred",
            21600,
            Some("provider_not_configured"),
        )
        .await?;
        return Ok("deferred");
    };
    match provider_issue(&state.outbound, id, key)
        .await
        .and_then(|value| normalized_metadata(&value, id))
    {
        Ok((mut patch, has, url, updated)) => {
            // A lower-fidelity / sparser fresh roster must never erase
            // previously persisted creators: keep cached credits when the
            // new fetch is empty but the cache already has them.
            if !has {
                if let Some(existing) = &cached {
                    if existing["creator_credits"]
                        .as_array()
                        .is_some_and(|v| !v.is_empty())
                    {
                        if let Some(obj) = patch.as_object_mut() {
                            obj.insert(
                                "creator_credits".to_owned(),
                                existing["creator_credits"].clone(),
                            );
                        }
                    } else if existing["raw_provider_payload"]["person_credits"]
                        .as_array()
                        .is_some_and(|v| !v.is_empty())
                    {
                        // Normalize cached raw credits into creator_credits when
                        // the cached normalized array is empty
                        if let Some(obj) = patch.as_object_mut() {
                            obj.insert(
                                "creator_credits".to_owned(),
                                compact_refs(&existing["raw_provider_payload"]["person_credits"]),
                            );
                        }
                    }
                }
            }
            let effective = cached_has_credits(&patch) || has;
            if persist(state, job, &patch, effective, &url, &updated).await? {
                Ok(if effective { "completed" } else { "no_credits" })
            } else {
                // Another worker reclaimed the expired lease; its result is authoritative.
                Ok("deferred")
            }
        }
        Err(error) => {
            let (status, delay, code) = failure_transition(&error, job.attempt);
            settle(state, job, status, delay, Some(code)).await?;
            Ok(status)
        }
    }
}

/// Hydrate user-confirmed catalog identities *inline after commit*, using a
/// single request-wide budget. A provider failure never undoes the completed
/// identity transaction. No detached tasks are left running after the response.
pub(crate) async fn hydrate_catalog_commit(
    state: &AppState,
    user_id: i32,
    committed_issue_ids: &[i32],
    budget: Duration,
) {
    if committed_issue_ids.is_empty() || budget.is_zero() {
        return;
    }
    let Ok(api_key) = std::env::var("COMICVINE_API_KEY") else {
        return;
    };
    if api_key.is_empty() {
        return;
    }

    // The timeout encloses both database queries and provider requests; it
    // cannot become N * provider_timeout for a large sibling confirmation.
    let run = async {
        let conn = match db::checkout(state).await {
            Ok(c) => c,
            Err(_) => return,
        };
        let rows = match conn
            .query(
                "SELECT DISTINCT e.id, e.external_id
                 FROM issue_external_identity_mappings m
                 JOIN external_identities e ON e.id = m.external_identity_id
                 JOIN issues i ON i.id = m.issue_id
                 JOIN threads t ON t.id = i.thread_id
                 WHERE m.issue_id = ANY($1::integer[])
                   AND t.user_id = $2
                   AND m.status = 'confirmed'
                   AND m.evidence_source = 'user_series_confirmation'
                   AND e.provider = 'comicvine'
                   AND e.entity_type = 'issue'
                 ORDER BY e.id",
                &[&committed_issue_ids, &user_id],
            )
            .await
        {
            Ok(rows) => rows,
            Err(_) => return,
        };
        for row in rows {
            let id: i32 = row.get(0);
            let external_id: String = row.get(1);
            let Some(comicvine_id) = issue_id(&external_id) else {
                continue;
            };
            let Ok(provider_data) = provider_issue(&state.outbound, comicvine_id, &api_key).await
            else {
                continue;
            };
            let Ok((patch, _, external_url, provider_updated_at)) =
                normalized_metadata(&provider_data, comicvine_id)
            else {
                continue;
            };
            let Ok(json_patch) = serde_json::to_string(&patch) else {
                continue;
            };
            // The identity transaction has committed; a failed metadata
            // refresh is best-effort and must not cause a client retry.
            if let Err(err) = conn
                .execute(
                    "UPDATE external_identities
                 SET metadata_json = (COALESCE(metadata_json::jsonb, '{}'::jsonb)
                                      || ($2::text)::jsonb)::json,
                     external_url = COALESCE($3, external_url),
                     provider_updated_at = COALESCE(($4::text)::timestamptz, provider_updated_at),
                     updated_at = now()
                 WHERE id = $1 AND provider = 'comicvine' AND entity_type = 'issue'",
                    &[&id, &json_patch, &external_url, &provider_updated_at],
                )
                .await
            {
                tracing::warn!(
                    error_kind = crate::error_kind(&err),
                    "catalog commit metadata hydration failed"
                );
            }
        }
    };
    if tokio::time::timeout(budget, run).await.is_err() {
        tracing::info!("catalog commit inline hydration budget exhausted");
    }
}

/// CRON_SECRET authenticated, awaited Rust repair batch. No detached task or silent success.
pub async fn drain(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Result<Json<DrainReport>, ApiError> {
    let secret = std::env::var("CRON_SECRET").ok();
    drain_authorized(&state, &headers, secret.as_deref()).await
}

/// Handler body with the expected secret injected so the 503/401 route gate is
/// directly testable without mutating the process-global `CRON_SECRET`. The
/// auth check returns before any database work, so authorization regressions
/// need no database.
async fn drain_authorized(
    state: &AppState,
    headers: &HeaderMap,
    expected: Option<&str>,
) -> Result<Json<DrainReport>, ApiError> {
    authorize(headers, expected)?;
    let key = std::env::var("COMICVINE_API_KEY").ok();
    let key = key.as_deref().filter(|v| !v.is_empty());
    let mut report = DrainReport {
        provider_configured: key.is_some(),
        ..Default::default()
    };
    for index in 0..BATCH_LIMIT {
        let Some(job) = claim(state).await? else {
            break;
        };
        report.claimed += 1;
        match process(state, &job, key).await? {
            "completed" => report.completed += 1,
            "no_credits" => report.no_credits += 1,
            "failed" => report.failed += 1,
            _ => report.deferred += 1,
        }
        if index + 1 < BATCH_LIMIT {
            tokio::time::sleep(Duration::from_secs(1)).await;
        }
    }
    Ok(Json(report))
}

#[cfg(test)]
mod tests {
    use super::*;
    use deadpool_postgres::Object;

    async fn seed_identity(state: &AppState) -> i32 {
        let connection = db::checkout(state).await.expect("seed connection");
        let identity_id: i32 = connection
            .query_one(
                "INSERT INTO external_identities \
                 (provider, entity_type, external_id, metadata_json, created_at, updated_at) \
                 VALUES ('comicvine', 'issue', '4000-29319', '{}'::json, now(), now()) \
                 RETURNING id",
                &[],
            )
            .await
            .expect("seed identity")
            .get(0);
        drop(Object::take(connection));
        identity_id
    }

    async fn seed_request(
        state: &AppState,
        identity_id: i32,
        request_state: &str,
        attempts: i32,
        next_attempt_offset: &str,
        lease_offset: Option<&str>,
    ) {
        let connection = db::checkout(state).await.expect("request connection");
        connection
            .execute(
                "INSERT INTO comicvine_metadata_refresh_requests \
                 (external_identity_id, state, attempts, next_attempt_at, lease_expires_at, \
                  created_at, updated_at) \
                 VALUES ($1, $2, $3, now()+($4::text)::interval, \
                   CASE WHEN $5::text IS NULL THEN NULL \
                        ELSE now()+($5::text)::interval END, \
                   now(), now())",
                &[
                    &identity_id,
                    &request_state,
                    &attempts,
                    &next_attempt_offset,
                    &lease_offset,
                ],
            )
            .await
            .expect("seed request");
        drop(Object::take(connection));
    }

    #[tokio::test]
    async fn expired_lease_is_reclaimed_and_persist_is_fenced() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let identity_id = seed_identity(&state).await;
        seed_request(
            &state,
            identity_id,
            "running",
            2,
            "-1 hour",
            Some("-1 minute"),
        )
        .await;

        let job = claim(&state)
            .await
            .expect("claim")
            .expect("expired lease job");
        assert_eq!(job.attempt, 3);
        assert_eq!(job.identity_id, identity_id);

        let patch = json!({"creator_credits": [{"id": 1, "name": "Jamie Delano"}]});
        let stale = Job {
            id: job.id,
            identity_id: job.identity_id,
            attempt: job.attempt + 1,
            external_id: job.external_id.clone(),
            provider: job.provider.clone(),
            entity_type: job.entity_type.clone(),
            metadata: job.metadata.clone(),
        };
        assert!(!persist(&state, &stale, &patch, true, &None, &None)
            .await
            .expect("stale persist"));
        assert!(persist(&state, &job, &patch, true, &None, &None)
            .await
            .expect("current persist"));

        let connection = db::checkout(&state).await.expect("assert connection");
        let row = connection
            .query_one(
                "SELECT state, lease_expires_at IS NULL \
                 FROM comicvine_metadata_refresh_requests \
                 WHERE external_identity_id=$1",
                &[&identity_id],
            )
            .await
            .expect("read settled request");
        let request_state: String = row.get(0);
        let lease_cleared: bool = row.get(1);
        assert_eq!(request_state, "completed");
        assert!(lease_cleared);
        drop(Object::take(connection));

        assert!(claim(&state).await.expect("empty claim").is_none());
    }

    #[tokio::test]
    async fn unreleased_lease_is_not_double_claimed_and_settle_is_fenced() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let identity_id = seed_identity(&state).await;
        seed_request(&state, identity_id, "pending", 0, "0 seconds", None).await;

        let job = claim(&state).await.expect("claim").expect("due job");
        assert_eq!(job.attempt, 1);
        assert!(claim(&state).await.expect("leased claim").is_none());

        let stale = Job {
            id: job.id,
            identity_id: job.identity_id,
            attempt: job.attempt + 1,
            external_id: job.external_id.clone(),
            provider: job.provider.clone(),
            entity_type: job.entity_type.clone(),
            metadata: job.metadata.clone(),
        };
        settle(&state, &stale, "deferred", 60, Some("provider_unavailable"))
            .await
            .expect("stale settle");
        let connection = db::checkout(&state).await.expect("assert connection");
        let request_state: String = connection
            .query_one(
                "SELECT state FROM comicvine_metadata_refresh_requests \
                 WHERE external_identity_id=$1",
                &[&identity_id],
            )
            .await
            .expect("read running request")
            .get(0);
        assert_eq!(request_state, "running");

        settle(&state, &job, "deferred", 60, Some("provider_unavailable"))
            .await
            .expect("current settle");
        let request_state: String = connection
            .query_one(
                "SELECT state FROM comicvine_metadata_refresh_requests \
                 WHERE external_identity_id=$1",
                &[&identity_id],
            )
            .await
            .expect("read settled request")
            .get(0);
        assert_eq!(request_state, "deferred");
        drop(Object::take(connection));

        assert!(claim(&state).await.expect("cooled claim").is_none());
    }

    #[test]
    fn cron_auth_fails_closed() {
        let mut headers = HeaderMap::new();
        headers.insert("authorization", "Bearer 1234567890123456".parse().unwrap());
        authorize(&headers, Some("1234567890123456")).expect("matching secret");
        assert_eq!(
            authorize(&headers, Some("1234567890123457"))
                .expect_err("wrong secret")
                .status(),
            StatusCode::UNAUTHORIZED
        );
        assert_eq!(
            authorize(&headers, Some("short"))
                .expect_err("non-matching secret")
                .status(),
            StatusCode::UNAUTHORIZED
        );
        assert_eq!(
            authorize(&headers, None)
                .expect_err("unconfigured")
                .status(),
            StatusCode::SERVICE_UNAVAILABLE
        );
    }

    #[test]
    fn authorize_accepts_case_insensitive_bearer_scheme() {
        // Parity with Python's `scheme.lower()` and the release-sync cron gate
        // (RFC 6750): this route used to require the literal "Bearer " prefix,
        // diverging from Python for `bearer`/`BEARER` casings.
        let secret = "a-very-secret-value";
        for scheme in ["bearer", "BEARER", "Bearer"] {
            let mut headers = HeaderMap::new();
            headers.insert(
                "authorization",
                format!("{scheme} {secret}").parse().expect("valid header"),
            );
            authorize(&headers, Some(secret)).expect("case-insensitive bearer scheme");
        }
    }

    #[test]
    fn cron_auth_rejects_placeholder_secrets_as_unconfigured() {
        // Missing/unconfigured/placeholder secret must fail closed as 503,
        // matching Python's `require_cron_secret`, never collapse to a 401.
        let mut headers = HeaderMap::new();
        headers.insert("authorization", "Bearer 1234567890123456".parse().unwrap());
        for placeholder in [
            "",
            "   ",
            "[SENSITIVE]",
            "  [SENSITIVE]  ",
            "<redacted>",
            "<REDACTED>",
            "redacted",
            "REDACTED",
            "undefined",
            "UNDEFINED",
            "null",
            "NULL",
        ] {
            assert_eq!(
                authorize(&headers, Some(placeholder))
                    .expect_err("placeholder secret must be treated as unconfigured")
                    .status(),
                StatusCode::SERVICE_UNAVAILABLE,
                "placeholder: {placeholder:?}"
            );
        }
    }

    /// Auth failures return before any database work, so a synthetic state is
    /// enough to exercise the real handler's 503/401 mapping.
    fn cron_test_state() -> Arc<AppState> {
        let config = crate::Config::from_lookup(|name| match name {
            "RUST_ROLL_DATABASE_URL" => Some("postgresql://localhost/unused".into()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-secret".into()),
            _ => None,
        })
        .expect("synthetic config");
        Arc::new(AppState::new(config).expect("synthetic state"))
    }

    /// Extract the status from a rejected drain without requiring `Debug` on
    /// the success payload (`Json<DrainReport>`), which is never produced on
    /// the authorization-failure paths under test.
    fn rejected_status(result: Result<Json<DrainReport>, ApiError>) -> StatusCode {
        match result {
            Ok(_) => panic!("cron request should have been rejected"),
            Err(error) => error.status(),
        }
    }

    #[tokio::test]
    async fn drain_route_returns_503_for_unconfigured_cron_secret() {
        // Route-level regression: the ComicVine repair cron must report a
        // missing/placeholder CRON_SECRET as fail-closed 503, matching Python
        // and the release-sync cron, rather than the pre-fix blanket 401.
        let state = cron_test_state();
        let mut headers = HeaderMap::new();
        headers.insert(
            "authorization",
            "Bearer a-very-secret-value".parse().expect("valid header"),
        );
        for expected in [
            None,
            Some(""),
            Some("[SENSITIVE]"),
            Some("<redacted>"),
            Some("redacted"),
            Some("undefined"),
            Some("null"),
        ] {
            assert_eq!(
                rejected_status(drain_authorized(&state, &headers, expected).await),
                StatusCode::SERVICE_UNAVAILABLE,
                "expected: {expected:?}"
            );
        }
    }

    #[tokio::test]
    async fn drain_route_returns_401_for_bad_or_missing_bearer() {
        // Route-level regression: a configured secret with a missing/malformed/
        // wrong bearer remains a 401 (distinct from the 503 above).
        let state = cron_test_state();
        let expected = Some("a-very-secret-value");
        assert_eq!(
            rejected_status(drain_authorized(&state, &HeaderMap::new(), expected).await),
            StatusCode::UNAUTHORIZED
        );

        let mut wrong = HeaderMap::new();
        wrong.insert(
            "authorization",
            "Bearer not-the-secret".parse().expect("valid header"),
        );
        assert_eq!(
            rejected_status(drain_authorized(&state, &wrong, expected).await),
            StatusCode::UNAUTHORIZED
        );

        let mut malformed = HeaderMap::new();
        malformed.insert(
            "authorization",
            "Token a-very-secret-value".parse().unwrap(),
        );
        assert_eq!(
            rejected_status(drain_authorized(&state, &malformed, expected).await),
            StatusCode::UNAUTHORIZED
        );
    }
    #[test]
    fn only_verified_singular_issue_payload_completes() {
        let result = json!({"id": 29319, "name":"Going For It", "issue_number":"3",
            "cover_date":"1988-03-01", "store_date":"1988-03-24", "image":{},
            "volume":{"id": 4001,"name":"Hellblazer"},
            "person_credits":[{"id":1,"name":"Jamie Delano","api_detail_url":"https://example"}],
            "character_credits":[], "team_credits":[], "story_arc_credits":[],
            "date_last_updated":"2020-01-01T00:00:00+00:00"});
        let (metadata, present, _, _) = normalized_metadata(&result, 29319).unwrap();
        assert!(present);
        assert_eq!(metadata["creator_credits"][0]["name"], "Jamie Delano");
        assert!(normalized_metadata(&result, 29320).is_err());
        let mut incomplete = result;
        incomplete.as_object_mut().unwrap().remove("person_credits");
        assert!(normalized_metadata(&incomplete, 29319).is_err());
    }
    #[tokio::test]
    async fn float_status_singular_fetch_completes_and_persists_credits() {
        // Production returned `status_code: 1.0` on the working singular
        // fetch while the worker recorded `provider_unavailable`. The worker
        // must now accept that payload, persist the creators and settle the
        // durable request as completed (#5592 AC2/AC4).
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let identity_id = seed_identity(&state).await; // external id 4000-29319
        seed_request(&state, identity_id, "pending", 0, "-1 hour", None).await;

        let issue = json!({"id": 29319, "name":"Going For It", "issue_number":"3",
            "cover_date":"1988-03-01", "store_date":"1988-03-24", "image":{},
            "volume":{"id": 4001,"name":"Hellblazer"},
            "person_credits":[{"id":1,"name":"Jamie Delano","api_detail_url":"https://example"}],
            "character_credits":[], "team_credits":[], "story_arc_credits":[],
            "date_last_updated":"2020-01-01T00:00:00+00:00"});
        // ComicVine carries `status_code` on the response envelope, not on the
        // issue `results` object. Production returned `status_code: 1.0` there;
        // the worker must accept that float and complete the singular fetch.
        let envelope = json!({"status_code": 1.0, "error": "OK", "results": issue});
        let fake = state
            .outbound
            .as_any()
            .downcast_ref::<crate::outbound::RecordingFakeOutbound>()
            .expect("test state uses the recording fake outbound client");
        fake.push_ok(
            StatusCode::OK,
            HeaderMap::new(),
            bytes::Bytes::from(envelope.to_string()),
        );

        let job = claim(&state).await.expect("claim").expect("pending job");
        let outcome = process(&state, &job, Some("TESTKEY123"))
            .await
            .expect("process");
        assert_eq!(outcome, "completed");

        let connection = db::checkout(&state).await.expect("verify connection");
        let credits: serde_json::Value = connection
            .query_one(
                "SELECT metadata_json::jsonb->'creator_credits' \
                 FROM external_identities WHERE id = $1",
                &[&identity_id],
            )
            .await
            .expect("credits")
            .get(0);
        assert_eq!(credits[0]["name"], "Jamie Delano");
        let request_state: String = connection
            .query_one(
                "SELECT state FROM comicvine_metadata_refresh_requests WHERE id = $1",
                &[&job.id],
            )
            .await
            .expect("request state")
            .get(0);
        assert_eq!(request_state, "completed");
    }

    #[test]
    fn provider_timestamp_accepts_rfc3339_and_comicvine_space_format() {
        assert_eq!(
            provider_timestamp(&json!("2020-01-01T00:00:00+00:00")).as_deref(),
            Some("2020-01-01T00:00:00+00:00")
        );
        assert_eq!(
            provider_timestamp(&json!("2020-01-01 00:00:00")).as_deref(),
            Some("2020-01-01T00:00:00+00:00")
        );
        assert!(provider_timestamp(&json!("not-a-timestamp")).is_none());
    }

    #[test]
    fn cached_metadata_requires_all_provider_fields_before_skipping_refresh() {
        let mut fields = Map::new();
        for field in FIELDS.split(',') {
            fields.insert(field.to_string(), Value::Null);
        }
        let mut metadata = json!({"raw_provider_payload": fields});
        assert!(has_complete_provider_payload(&metadata));
        metadata["raw_provider_payload"]
            .as_object_mut()
            .expect("provider payload")
            .remove("image");
        assert!(!has_complete_provider_payload(&metadata));
    }

    #[test]
    fn empty_credits_use_bounded_recheck_not_30_day_lock() {
        let now = chrono::DateTime::parse_from_rfc3339("2026-11-08T15:00:00+00:00")
            .unwrap()
            .with_timezone(&chrono::Utc);
        // Issue 1121330-shaped: deep payload complete, person_credits and
        // creator_credits empty, fetched ~1 day ago.
        let mut fields = Map::new();
        for field in FIELDS.split(',') {
            fields.insert(field.to_string(), Value::Null);
        }
        // Provider revision predates the deep fetch so only age decides.
        fields.insert(
            "date_last_updated".to_owned(),
            json!("2026-11-05T08:37:31Z"),
        );
        fields.insert("person_credits".to_owned(), json!([]));
        let empty_recent = json!({
            "raw_provider_payload": fields,
            "creator_credits": [],
            "deep_metadata_refreshed_at": "2026-11-07T21:09:17.019489+00:00",
        });
        // 1 day old: still within the 7-day empty recheck, no hot loop.
        assert!(!needs_provider_fetch(&empty_recent, now));
        // 8 days old: past the 7-day recheck, must fetch again. Provider
        // revision predates the deep fetch so only age decides.
        let mut old_fields = empty_recent["raw_provider_payload"].clone();
        old_fields.as_object_mut().expect("payload object").insert(
            "date_last_updated".to_owned(),
            json!("2026-10-20T08:37:31Z"),
        );
        let empty_old = json!({
            "raw_provider_payload": old_fields,
            "creator_credits": [],
            "deep_metadata_refreshed_at": "2026-10-26T15:00:00+00:00",
        });
        assert!(needs_provider_fetch(&empty_old, now));
        // Same age but populated (issue #24 shape): 8 days is still fresh.
        let full_old = json!({
            "raw_provider_payload": empty_old["raw_provider_payload"],
            "creator_credits": [{"id": 1, "name": "Creator One"}],
            "deep_metadata_refreshed_at": "2026-10-26T15:00:00+00:00",
        });
        assert!(!needs_provider_fetch(&full_old, now));
        // R1 regression: credits in only one array count as having credits.
        // A row with creator_credits empty but person_credits non-empty uses
        // the 30-day window (not the 7-day recheck), matching cached_has_credits
        // (creator || raw) and comicvine_issue.rs NOT (has credits).
        let mut person_old_fields = empty_old["raw_provider_payload"].clone();
        person_old_fields
            .as_object_mut()
            .expect("payload object")
            .insert(
                "person_credits".to_owned(),
                json!([{"id": 1, "name": "Creator One"}]),
            );
        let person_only_old = json!({
            "raw_provider_payload": person_old_fields,
            "creator_credits": [],
            "deep_metadata_refreshed_at": "2026-10-26T15:00:00+00:00",
        });
        assert!(cached_has_credits(&person_only_old));
        assert!(!needs_provider_fetch(&person_only_old, now));
        // 31 days old populated row is stale under the 30-day window.
        let mut stale_fields = empty_recent["raw_provider_payload"].clone();
        stale_fields
            .as_object_mut()
            .expect("payload object")
            .insert(
                "date_last_updated".to_owned(),
                json!("2026-09-01T08:37:31Z"),
            );
        let full_stale = json!({
            "raw_provider_payload": stale_fields,
            "creator_credits": [{"id": 1, "name": "Creator One"}],
            "deep_metadata_refreshed_at": "2026-10-01T15:00:00+00:00",
        });
        assert!(needs_provider_fetch(&full_stale, now));
        // Provider revision newer than the deep fetch forces a refetch even
        // when the deep timestamp is recent.
        let mut newer_fields = empty_recent["raw_provider_payload"].clone();
        newer_fields
            .as_object_mut()
            .expect("payload object")
            .insert(
                "date_last_updated".to_owned(),
                json!("2026-11-08T10:00:00Z"),
            );
        let provider_newer = json!({
            "raw_provider_payload": newer_fields,
            "creator_credits": [],
            "deep_metadata_refreshed_at": "2026-11-07T21:09:17.019489+00:00",
        });
        assert!(needs_provider_fetch(&provider_newer, now));
        // Missing/incomplete payload or timestamps are stale, never fresh.
        assert!(needs_provider_fetch(&json!({}), now));
        let no_timestamp = json!({
            "raw_provider_payload": empty_recent["raw_provider_payload"],
            "creator_credits": [{"id": 1, "name": "Creator One"}],
        });
        assert!(needs_provider_fetch(&no_timestamp, now));
    }

    #[test]
    fn cached_has_credits_detects_seven_creators_from_issue_24() {
        // Regression test for #4819/#24: verify that cached_has_credits correctly
        // identifies issues with multiple creators, which is used by
        // needs_provider_fetch() and process() for the 7-day recheck window.
        let metadata_with_seven = json!({
            "creator_credits": [
                {"id": 1, "name": "Creator One", "role": "writer"},
                {"id": 2, "name": "Creator Two", "role": "penciler"},
                {"id": 3, "name": "Creator Three", "role": "inker"},
                {"id": 4, "name": "Creator Four", "role": "colorist"},
                {"id": 5, "name": "Creator Five", "role": "letterer"},
                {"id": 6, "name": "Creator Six", "role": "cover"},
                {"id": 7, "name": "Creator Seven", "role": "editor"}
            ],
            "raw_provider_payload": {
                "person_credits": [
                    {"id": 1, "name": "Creator One", "role": "writer"},
                    {"id": 2, "name": "Creator Two", "role": "penciler"},
                    {"id": 3, "name": "Creator Three", "role": "inker"},
                    {"id": 4, "name": "Creator Four", "role": "colorist"},
                    {"id": 5, "name": "Creator Five", "role": "letterer"},
                    {"id": 6, "name": "Creator Six", "role": "cover"},
                    {"id": 7, "name": "Creator Seven", "role": "editor"}
                ]
            }
        });
        assert!(cached_has_credits(&metadata_with_seven));

        // Empty credits should return false.
        let empty_metadata = json!({
            "creator_credits": [],
            "raw_provider_payload": {"person_credits": []}
        });
        assert!(!cached_has_credits(&empty_metadata));

        // One creator should return true.
        let one_creator = json!({
            "creator_credits": [{"id": 1, "name": "One", "role": "writer"}],
            "raw_provider_payload": {"person_credits": []}
        });
        assert!(cached_has_credits(&one_creator));
    }

    #[test]
    fn timeout_is_distinct_from_provider_unavailable() {
        assert_eq!(
            failure_transition(&ProviderFailure::Timeout, 1),
            ("deferred", 60, "provider_timeout")
        );
        assert_eq!(
            failure_transition(&ProviderFailure::Timeout, 3),
            ("failed", 21600, "provider_timeout")
        );
        // Rate limiting stays distinct and never reported as empty credits.
        assert_eq!(
            failure_transition(&ProviderFailure::RateLimited(120), 1),
            ("deferred", 120, "rate_limit")
        );
    }

    #[test]
    fn backoff_does_not_retry_exhausted_jobs_without_cooldown() {
        assert!(CLAIM.contains("FOR UPDATE SKIP LOCKED"));
        // Failed jobs are durable but must retry after their cooldown without
        // requiring a user to reopen the issue to enqueue them again.
        assert!(CLAIM.contains("\'failed\'"));
        assert!(CLAIM.contains("next_attempt_at <= now()"));
        assert!(PERSIST.contains("lease_expires_at > now()"));
        assert_eq!(
            failure_transition(&ProviderFailure::Unavailable, 3).0,
            "failed"
        );
        assert_eq!(
            failure_transition(&ProviderFailure::RateLimited(120), 1).1,
            120
        );
        assert_eq!(issue_id("4000-29319"), Some(29319));
    }

    #[test]
    fn provider_envelope_accepts_every_python_status_code_shape() {
        // ComicVine has been observed returning the success flag as an integer,
        // a float, a boolean, or omitting it. All of those satisfy Python's
        // `status_code not in (None, 1)` rule and must not become
        // `provider_unavailable` in the repair worker (#5592 AC2).
        for payload in [
            json!({}),
            json!({"status_code": null}),
            json!({"status_code": true}),
            json!({"status_code": 1}),
            json!({"status_code": 1.0}),
        ] {
            assert!(provider_envelope_ok(&payload), "{payload}");
        }
        for payload in [
            json!({"status_code": 0}),
            json!({"status_code": 2}),
            json!({"status_code": "1"}),
            json!({"status_code": false}),
            json!([]),
        ] {
            assert!(!provider_envelope_ok(&payload), "{payload}");
        }
    }

    #[test]
    fn enqueue_batch_sql_is_set_based_and_deduping() {
        let sql = ENQUEUE_BATCH_SQL.as_str();
        assert!(sql.contains("ANY($1::int[])"));
        assert!(sql.contains("NOT EXISTS"));
        assert!(sql.contains(NEEDS_DEEP_FETCH_SQL));
        assert!(sql.contains("uq_comicvine_metadata_refresh_identity"));
        // It must never wait on a request row the repair worker is persisting.
        assert!(!sql.contains("FOR UPDATE"));
    }

    #[tokio::test]
    async fn hydration_batch_is_idempotent_and_preserves_hydrated_credits() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let connection = db::checkout(&state).await.expect("connection");

        let roster_only: i32 = connection
            .query_one(
                "INSERT INTO external_identities \
                 (provider, entity_type, external_id, metadata_json, created_at, updated_at) \
                 VALUES ('comicvine','issue','4000-8001', \
                   '{\"creator_credits\":[]}'::json, now(), now()) RETURNING id",
                &[],
            )
            .await
            .expect("roster identity")
            .get(0);
        let hydrated: i32 = connection
            .query_one(
                "INSERT INTO external_identities \
                 (provider, entity_type, external_id, metadata_json, created_at, updated_at) \
                 VALUES ('comicvine','issue','4000-8002', \
                   '{\"creator_credits\":[{\"id\":1,\"name\":\"Jamie Delano\"}],\
                     \"deep_metadata_refreshed_at\":\"2026-11-22T00:00:00+00:00\",\
                     \"raw_provider_payload\":{\"id\":8002,\"name\":\"Batman\",\
                       \"issue_number\":\"1\",\"cover_date\":null,\"store_date\":null,\
                       \"image\":{},\"volume\":{},\"person_credits\":[{\"id\":1}],\
                       \"character_credits\":[],\"team_credits\":[],\
                       \"story_arc_credits\":[],\"date_last_updated\":\"2026-11-22 00:00:00\"}}'::json, \
                   now(), now()) RETURNING id",
                &[],
            )
            .await
            .expect("hydrated identity")
            .get(0);
        let with_request: i32 = connection
            .query_one(
                "INSERT INTO external_identities \
                 (provider, entity_type, external_id, metadata_json, created_at, updated_at) \
                 VALUES ('comicvine','issue','4000-8003', '{}'::json, now(), now()) RETURNING id",
                &[],
            )
            .await
            .expect("request identity")
            .get(0);
        drop(Object::take(connection));
        seed_request(&state, with_request, "failed", 3, "-1 hour", None).await;

        let mut connection = db::checkout(&state).await.expect("enqueue connection");
        let tx = connection.transaction().await.expect("transaction");
        let inserted = enqueue_hydration_batch(&tx, &[roster_only, hydrated, with_request])
            .await
            .expect("enqueue batch");
        tx.commit().await.expect("commit");
        assert_eq!(inserted, 1, "only the roster-only identity is enqueued");

        let states: Vec<String> = connection
            .query(
                "SELECT state FROM comicvine_metadata_refresh_requests \
                 ORDER BY external_identity_id",
                &[],
            )
            .await
            .expect("ledger")
            .iter()
            .map(|row| row.get(0))
            .collect();
        assert_eq!(states, ["pending", "failed"]);
        let credits: serde_json::Value = connection
            .query_one(
                "SELECT metadata_json::jsonb->'creator_credits' FROM external_identities WHERE id=$1",
                &[&hydrated],
            )
            .await
            .expect("hydrated credits")
            .get(0);
        assert_eq!(credits[0]["name"], "Jamie Delano");
        drop(Object::take(connection));

        // A reimport cannot duplicate work or reset an existing job.
        let mut connection = db::checkout(&state).await.expect("recheck connection");
        let tx = connection.transaction().await.expect("transaction");
        assert_eq!(
            enqueue_hydration_batch(&tx, &[roster_only, with_request])
                .await
                .expect("idempotent enqueue"),
            0
        );
        tx.commit().await.expect("commit");
    }

    #[tokio::test]
    async fn backfill_is_bounded_resumable_and_dry_runnable() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let connection = db::checkout(&state).await.expect("connection");
        let user_id: i32 = connection
            .query_one(
                "INSERT INTO users (username, created_at) VALUES ($1, now()) RETURNING id",
                &[&"cv5592-backfill"],
            )
            .await
            .expect("user")
            .get(0);
        let thread_id: i32 = connection
            .query_one(
                "INSERT INTO threads (title, format, issues_remaining, total_issues, \
                 queue_position, status, user_id) \
                 VALUES ('Backfill','Comic',0,0,1,'active',$1) RETURNING id",
                &[&user_id],
            )
            .await
            .expect("thread")
            .get(0);

        let mut identity_ids = Vec::new();
        // Three roster-only identities and one hydrated identity.
        for (index, metadata) in [
            "{}".to_owned(),
            "{}".to_owned(),
            "{}".to_owned(),
            json!({
                "creator_credits": [{"id":1,"name":"Creator"}],
                "deep_metadata_refreshed_at": "2026-11-22T00:00:00+00:00",
                "raw_provider_payload": {"id":8004,"name":"Hydrated",
                  "issue_number":"4","cover_date":null,"store_date":null,
                  "image":{},"volume":{},"person_credits":[{"id":1}],
                  "character_credits":[],"team_credits":[],"story_arc_credits":[],
                  "date_last_updated":"2026-11-22 00:00:00"}
            })
            .to_string(),
        ]
        .into_iter()
        .enumerate()
        {
            let external_id = format!("4000-81{:02}", index + 1);
            let issue_id: i32 = connection
                .query_one(
                    "INSERT INTO issues (thread_id, issue_number, position, status, created_at) \
                     VALUES ($1,$2,$3,'unread',now()) RETURNING id",
                    &[&thread_id, &(index + 1).to_string(), &(index as i32 + 1)],
                )
                .await
                .expect("issue")
                .get(0);
            let identity: i32 = connection
                .query_one(
                    "INSERT INTO external_identities \
                     (provider, entity_type, external_id, metadata_json, created_at, updated_at) \
                     VALUES ('comicvine','issue',$1,($2::text)::json,now(),now()) RETURNING id",
                    &[&external_id, &metadata],
                )
                .await
                .expect("identity")
                .get(0);
            connection
                .execute(
                    "INSERT INTO issue_external_identity_mappings \
                     (issue_id, external_identity_id, status, evidence_source, evidence_json, \
                      confidence, created_at, updated_at) \
                     VALUES ($1,$2,'confirmed','comicvine_issue_adoption','{}'::json,1.0,now(),now())",
                    &[&issue_id, &identity],
                )
                .await
                .expect("mapping");
            identity_ids.push(identity);
        }
        drop(Object::take(connection));

        let mut headers = HeaderMap::new();
        headers.insert(
            "authorization",
            "Bearer cron-test-secret".parse().expect("valid header"),
        );
        let expected = Some("cron-test-secret");

        let dry = backfill_authorized(&state, &headers, expected, true, 2, 0)
            .await
            .expect("dry run");
        assert!(dry.dry_run);
        assert_eq!(dry.scanned, 2);
        assert_eq!(dry.eligible, 2);
        assert_eq!(dry.enqueued, 0);
        assert_eq!(dry.before_pending, dry.after_pending);
        assert_eq!(dry.last_identity_id, Some(identity_ids[1]));

        let first = backfill_authorized(&state, &headers, expected, false, 2, 0)
            .await
            .expect("first batch");
        assert_eq!(first.enqueued, 2);
        assert_eq!(first.last_identity_id, Some(identity_ids[1]));

        let second = backfill_authorized(
            &state,
            &headers,
            expected,
            false,
            BACKFILL_MAX_LIMIT,
            first.last_identity_id.unwrap(),
        )
        .await
        .expect("resumed batch");
        assert_eq!(second.enqueued, 1, "hydrated identity is never enqueued");
        assert_eq!(second.scanned, 2);
        assert_eq!(second.already_present, 1);
        assert!(second.after_pending > second.before_pending);

        let connection = db::checkout(&state).await.expect("final connection");
        let count: i64 = connection
            .query_one(
                "SELECT count(*) FROM comicvine_metadata_refresh_requests",
                &[],
            )
            .await
            .expect("final count")
            .get(0);
        assert_eq!(count, 3);
        let hydrated_requests: i64 = connection
            .query_one(
                "SELECT count(*) FROM comicvine_metadata_refresh_requests \
                 WHERE external_identity_id = $1",
                &[&identity_ids[3]],
            )
            .await
            .expect("hydrated identity ledger")
            .get(0);
        assert_eq!(hydrated_requests, 0);
    }
}
