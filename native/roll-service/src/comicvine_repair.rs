//! Bounded, awaited ComicVine metadata-repair worker.
//! A Vercel request is the lifetime of the work: never spawn and forget a task.
use crate::{
    comicvine_limits::{parse_retry_after, python_envelope_ok},
    db,
    outbound::{OutboundHttp, OutboundRequest},
    ApiError, AppState,
};
use axum::{
    extract::{Query, State},
    http::{HeaderMap, StatusCode},
    Json,
};
use bytes::Bytes;
use http_body_util::BodyExt;
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use std::{sync::Arc, time::Duration};

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
            [
                "original_url",
                "super_url",
                "medium_url",
                "small_url",
                "thumb_url",
            ]
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

/// Parse Python-compatible delta-seconds or an HTTP-date, then apply the
/// repair worker's 60..=3600 second bound. Fractional values round up so
/// integer persistence never retries before the provider's requested deadline.
fn repair_retry_after_seconds(raw: Option<&str>, now: chrono::DateTime<chrono::Utc>) -> u32 {
    raw.and_then(|header| parse_retry_after(header, now))
        .filter(|seconds| seconds.is_finite())
        .map(|seconds| seconds.clamp(60.0, 3600.0).ceil() as u32)
        .unwrap_or(60)
}

/// One repair-worker provider call, matching Python `ComicVineClient`
/// throttle rules: 420/429 are throttles whose `Retry-After` is clamped to
/// 60..=3600 s; any other non-2xx status (403 included) is a plain provider
/// error. Success envelopes use the same status-code rule as the Python fetch.
pub(crate) async fn provider_response(
    outbound: &Arc<dyn OutboundHttp>,
    resource: &str,
    extra_query: &str,
    api_key: &str,
) -> Result<Value, ProviderFailure> {
    match provider_exchange(outbound, resource, extra_query, api_key).await? {
        Exchange::Throttled {
            status: 420 | 429,
            retry_after,
        } => Err(ProviderFailure::RateLimited(repair_retry_after_seconds(
            retry_after.as_deref(),
            chrono::Utc::now(),
        ))),
        Exchange::Throttled { .. } => Err(ProviderFailure::Unavailable),
        Exchange::Payload(payload) => {
            let status_code = payload.get("status_code").and_then(Value::as_i64);
            if python_envelope_ok(&payload) {
                Ok(payload)
            } else {
                // Never log provider-controlled error text: it can reflect the
                // credential-bearing request URL. Keep only typed categories.
                tracing::warn!(
                    comicvine_status_code = ?status_code,
                    resource,
                    "comicvine provider returned non-success envelope"
                );
                Err(ProviderFailure::Unavailable)
            }
        }
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
    // Python `_provider_url`: only collection endpoints use a trailing slash.
    // Singular issue/volume requests must not redirect with credentials in the
    // URL; the native transport intentionally does not follow redirects.
    let collection_slash = if matches!(resource, "issues" | "search") {
        "/"
    } else {
        ""
    };
    let request = OutboundRequest {
        method: http::Method::GET,
        path: format!(
            "/api/{resource}{collection_slash}?api_key={api_key}&format=json{extra_query}"
        ),
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
            // Retain only a redacted status/resource category: never log the
            // credential-bearing URL, response body, or provider headers.
            tracing::warn!(
                status = status.as_u16(),
                resource,
                "comicvine provider returned throttled or forbidden status"
            );
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
            tracing::warn!(
                status = status.as_u16(),
                resource,
                "comicvine provider returned non-success status"
            );
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
        ProviderFailure::RateLimited(_) if attempt >= 3 => ("failed", 21600, "rate_limit"),
        ProviderFailure::RateLimited(delay) => {
            let local_backoff = if attempt <= 1 { 60 } else { 300 };
            (
                "deferred",
                (*delay).max(local_backoff).min(3600) as i32,
                "rate_limit",
            )
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
    let Some(raw) = metadata
        .get("raw_provider_payload")
        .and_then(|v| v.as_object())
    else {
        return false;
    };
    FIELDS.split(',').all(|key| raw.contains_key(key))
}

fn cached_has_credits(metadata: &Value) -> bool {
    let creator = metadata
        .get("creator_credits")
        .and_then(|v| v.as_array())
        .is_some_and(|v| !v.is_empty());
    let raw = metadata
        .get("raw_provider_payload")
        .and_then(|v| v.get("person_credits"))
        .and_then(|v| v.as_array())
        .is_some_and(|v| !v.is_empty());
    creator || raw
}

fn provider_newer_than_deep_fetch(metadata: &Value) -> bool {
    let deep = metadata
        .get("deep_metadata_refreshed_at")
        .and_then(|v| v.as_str())
        .and_then(|v| chrono::DateTime::parse_from_rfc3339(v).ok());
    let Some(deep) = deep else {
        return false;
    };
    let Some(last_updated) = metadata
        .get("raw_provider_payload")
        .and_then(|v| v.get("date_last_updated"))
        .and_then(|v| v.as_str())
    else {
        return false;
    };
    provider_timestamp(&serde_json::Value::String(last_updated.to_owned()))
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

/// Freshness for import/backfill scans, including legacy rows that predate the
/// explicit deep-fetch marker. Like the retired Python policy, a newer identity
/// revision than the stored deep payload forces hydration; otherwise the
/// provider revision, then the identity update time, supplies the legacy age.
pub(crate) fn needs_provider_fetch_with_legacy_fallback(
    metadata: &Value,
    provider_updated_at: Option<chrono::DateTime<chrono::Utc>>,
    updated_at: chrono::DateTime<chrono::Utc>,
    now: chrono::DateTime<chrono::Utc>,
) -> bool {
    if !has_complete_provider_payload(metadata) {
        return true;
    }
    let deep_refreshed_at = metadata["deep_metadata_refreshed_at"]
        .as_str()
        .and_then(|value| chrono::DateTime::parse_from_rfc3339(value).ok());
    if deep_refreshed_at.is_some() {
        return needs_provider_fetch(metadata, now);
    }
    if let Some(provider_updated_at) = provider_updated_at {
        let raw_revision = metadata
            .get("raw_provider_payload")
            .and_then(|raw| raw.get("date_last_updated"))
            .and_then(Value::as_str)
            .and_then(|stamp| {
                let normalized = provider_timestamp(&Value::String(stamp.to_owned()))?;
                chrono::DateTime::parse_from_rfc3339(&normalized).ok()
            });
        if raw_revision.is_some_and(|revision| revision.with_timezone(&chrono::Utc) < provider_updated_at) {
            return true;
        }
    }
    let fetched_at = provider_updated_at.unwrap_or(updated_at);
    let window = if cached_has_credits(metadata) {
        chrono::Duration::days(COMPLETE_FRESH_DAYS)
    } else {
        chrono::Duration::days(EMPTY_CREDIT_RECHECK_DAYS)
    };
    now.signed_duration_since(fetched_at) >= window
}

async fn process(
    state: &AppState,
    job: &Job,
    key: Option<&str>,
) -> Result<(&'static str, bool), ApiError> {
    if job.provider.as_deref() != Some("comicvine") || job.entity_type.as_deref() != Some("issue") {
        settle(state, job, "failed", 21600, Some("identity_ineligible")).await?;
        return Ok(("failed", false));
    }
    let Some(id) = job.external_id.as_deref().and_then(issue_id) else {
        settle(state, job, "failed", 21600, Some("invalid_external_id")).await?;
        return Ok(("failed", false));
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
            return Ok((if has { "completed" } else { "no_credits" }, false));
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
        return Ok(("deferred", false));
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
                Ok((if effective { "completed" } else { "no_credits" }, false))
            } else {
                // Another worker reclaimed the expired lease; its result is authoritative.
                Ok(("deferred", false))
            }
        }
        Err(error) => {
            let rate_limited = matches!(&error, ProviderFailure::RateLimited(_));
            let (status, delay, code) = failure_transition(&error, job.attempt);
            settle(state, job, status, delay, Some(code)).await?;
            Ok((status, rate_limited))
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
    let Ok(api_key) = std::env::var("COMICVINE_API_KEY") else {
        return;
    };
    hydrate_catalog_commit_with_key(state, user_id, committed_issue_ids, budget, &api_key).await;
}

/// Post-commit hydration with provider configuration supplied by the caller.
/// Keeping environment lookup at the HTTP boundary lets the DB regression use
/// the recording transport without mutating process-global environment state.
async fn hydrate_catalog_commit_with_key(
    state: &AppState,
    user_id: i32,
    committed_issue_ids: &[i32],
    budget: Duration,
    api_key: &str,
) {
    if committed_issue_ids.is_empty() || budget.is_zero() || api_key.is_empty() {
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
            let Ok(provider_data) = provider_issue(&state.outbound, comicvine_id, api_key).await
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
        let (status, rate_limited) = process(state, &job, key).await?;
        match status {
            "completed" => report.completed += 1,
            "no_credits" => report.no_credits += 1,
            "failed" => report.failed += 1,
            _ => report.deferred += 1,
        }
        if rate_limited {
            // ComicVine throttles are provider-wide. The current row is durably
            // deferred/failed; do not spend sibling requests during its cooldown.
            break;
        }
        if index + 1 < BATCH_LIMIT {
            tokio::time::sleep(Duration::from_secs(1)).await;
        }
    }
    Ok(Json(report))
}

#[derive(Debug, Deserialize)]
pub struct BackfillQuery {
    #[serde(default = "default_backfill_dry_run")]
    pub dry_run: bool,
    #[serde(default = "default_backfill_limit")]
    pub limit: i64,
    #[serde(default)]
    pub after_id: i32,
}

fn default_backfill_dry_run() -> bool {
    true
}

fn default_backfill_limit() -> i64 {
    500
}

#[derive(Debug, Serialize, Default)]
pub struct BackfillReport {
    pub dry_run: bool,
    pub scanned: u32,
    pub needs_enqueue: u32,
    pub enqueued: u32,
    pub already_queued_or_fresh: u32,
    pub next_after_id: Option<i32>,
}

/// CRON_SECRET authenticated backfill for confirmed ComicVine issue identities
/// that lack deep metadata (#5592). Bounded and resumable: scan by identity id
/// cursor, dry-run by default, set-based enqueue when `dry_run=false`.
pub async fn backfill(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(query): Query<BackfillQuery>,
) -> Result<Json<BackfillReport>, ApiError> {
    let secret = std::env::var("CRON_SECRET").ok();
    backfill_authorized(&state, &headers, secret.as_deref(), query).await
}

/// Handler body with the expected secret injected for deterministic route and
/// accounting regressions without mutating process-global cron configuration.
async fn backfill_authorized(
    state: &AppState,
    headers: &HeaderMap,
    expected: Option<&str>,
    query: BackfillQuery,
) -> Result<Json<BackfillReport>, ApiError> {
    authorize(headers, expected)?;
    let limit = query.limit.clamp(1, 2000);
    let mut connection = db::checkout(state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    let rows = tx
        .query(
            "SELECT e.id, e.metadata_json::text, e.provider_updated_at, e.updated_at \
             FROM external_identities e \
             WHERE e.provider = 'comicvine' \
               AND e.entity_type = 'issue' \
               AND e.id > $1 \
               AND EXISTS ( \
                 SELECT 1 FROM issue_external_identity_mappings m \
                 WHERE m.external_identity_id = e.id \
                   AND m.status = 'confirmed' \
               ) \
             ORDER BY e.id \
             LIMIT $2",
            &[&query.after_id, &limit],
        )
        .await
        .map_err(db::query_error)?;
    let mut report = BackfillReport {
        dry_run: query.dry_run,
        ..Default::default()
    };
    let now = chrono::Utc::now();
    let mut needs_fetch: Vec<i32> = Vec::new();
    let mut last_id: Option<i32> = None;
    for row in &rows {
        report.scanned += 1;
        let id: i32 = row.get(0);
        last_id = Some(id);
        let metadata: Value = row
            .get::<_, Option<String>>(1)
            .and_then(|text| serde_json::from_str(&text).ok())
            .unwrap_or(Value::Null);
        if needs_provider_fetch_with_legacy_fallback(
            &metadata,
            row.get(2),
            row.get(3),
            now,
        ) {
            report.needs_enqueue += 1;
            needs_fetch.push(id);
        } else {
            report.already_queued_or_fresh += 1;
        }
    }
    report.next_after_id = if rows.len() as i64 == limit {
        last_id
    } else {
        None
    };

    if query.dry_run && !needs_fetch.is_empty() {
        // Dry-run classifies existing active work without locking or writing.
        let active_rows = tx
            .query(
                "SELECT external_identity_id \
                 FROM comicvine_metadata_refresh_requests \
                 WHERE external_identity_id = ANY($1::int[]) \
                   AND ( \
                     state IN ('pending', 'running', 'deferred') OR \
                     (state = 'failed' AND next_attempt_at > now()) OR \
                     (state = 'completed' AND completed_at IS NOT NULL \
                       AND completed_at > now() - interval '30 days') OR \
                     (state = 'no_credits' AND completed_at IS NOT NULL \
                       AND completed_at > now() - interval '7 days') \
                   )",
                &[&needs_fetch],
            )
            .await
            .map_err(db::query_error)?;
        let already_active = active_rows.len() as u32;
        report.already_queued_or_fresh += already_active;
        report.needs_enqueue = report.needs_enqueue.saturating_sub(already_active);
    }

    if !query.dry_run && !needs_fetch.is_empty() {
        let claimable_rows = tx
            .query(
                "WITH claimable AS ( \
                    SELECT id, external_identity_id, state, next_attempt_at, completed_at \
                    FROM comicvine_metadata_refresh_requests \
                    WHERE external_identity_id = ANY($1::int[]) \
                    FOR UPDATE SKIP LOCKED \
                 ), reopened AS ( \
                    UPDATE comicvine_metadata_refresh_requests r \
                    SET state = 'pending', attempts = 0, next_attempt_at = now(), \
                        lease_expires_at = NULL, last_error = NULL, completed_at = NULL, \
                        updated_at = now() \
                    FROM claimable c \
                    WHERE r.id = c.id AND ( \
                       (r.state = 'completed' AND (r.completed_at IS NULL OR \
                         r.completed_at <= now() - interval '30 days')) OR \
                       (r.state = 'no_credits' AND (r.completed_at IS NULL OR \
                         r.completed_at <= now() - interval '7 days')) OR \
                       (r.state = 'failed' AND r.next_attempt_at <= now()) \
                    ) \
                    RETURNING r.external_identity_id \
                 ) \
                 SELECT c.external_identity_id, \
                        EXISTS (SELECT 1 FROM reopened r \
                                WHERE r.external_identity_id = c.external_identity_id) \
                 FROM claimable c",
                &[&needs_fetch],
            )
            .await
            .map_err(db::query_error)?;
        let claimable: std::collections::HashMap<i32, bool> = claimable_rows
            .iter()
            .map(|row| (row.get::<_, i32>(0), row.get::<_, bool>(1)))
            .collect();
        let reopened = claimable.values().filter(|reopened| **reopened).count() as u32;
        let already_scheduled = claimable.len() as u32 - reopened;
        let missing: Vec<i32> = needs_fetch
            .iter()
            .copied()
            .filter(|id| !claimable.contains_key(id))
            .collect();
        let mut inserted = 0_u32;
        if !missing.is_empty() {
            inserted = tx.execute(
                "INSERT INTO comicvine_metadata_refresh_requests \
                    (external_identity_id, state, attempts, next_attempt_at, created_at, updated_at) \
                 SELECT v, 'pending', 0, now(), now(), now() \
                 FROM unnest($1::int[]) AS v \
                 WHERE NOT EXISTS ( \
                     SELECT 1 FROM comicvine_metadata_refresh_requests \
                     WHERE external_identity_id = v \
                 ) \
                 ON CONFLICT ON CONSTRAINT uq_comicvine_metadata_refresh_identity DO NOTHING",
                &[&missing],
            )
            .await
            .map_err(db::query_error)? as u32;
        }
        // Only inserts and reopened terminal rows are new work. Active rows,
        // terminal rows still inside their cooldown/freshness window, plus rows
        // concurrently locked or inserted by another worker, must not inflate
        // the operator-facing audit or bypass durable backoff.
        let unresolved = missing.len() as u32 - inserted;
        report.enqueued = reopened + inserted;
        report.already_queued_or_fresh += already_scheduled + unresolved;
        report.needs_enqueue = report
            .needs_enqueue
            .saturating_sub(already_scheduled + unresolved);
    }

    tx.commit().await.map_err(db::query_error)?;
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

    async fn seed_confirmed_identity_for_thread(
        connection: &Object,
        thread_id: i32,
        issue_number: &str,
        external_id: &str,
        metadata: &Value,
    ) -> i32 {
        let identity_id: i32 = connection
            .query_one(
                "INSERT INTO external_identities \
                 (provider, entity_type, external_id, metadata_json, created_at, updated_at) \
                 VALUES ('comicvine', 'issue', $1, ($2::text)::json, now(), now()) \
                 RETURNING id",
                &[&external_id, &metadata.to_string()],
            )
            .await
            .expect("backfill identity")
            .get(0);
        // Bind position as its own typed parameter: reusing $2 for the varchar
        // issue_number column and a text-to-int cast makes Postgres deduce
        // inconsistent parameter types (E42P08).
        let position: i32 = issue_number.parse().expect("numeric issue number");
        let issue_id: i32 = connection
            .query_one(
                "INSERT INTO issues (thread_id, issue_number, status, position, created_at) \
                 VALUES ($1, $2, 'unread', $3, now()) RETURNING id",
                &[&thread_id, &issue_number, &position],
            )
            .await
            .expect("backfill issue")
            .get(0);
        connection
            .execute(
                "INSERT INTO issue_external_identity_mappings \
                 (issue_id, external_identity_id, status, evidence_source, confidence, \
                  evidence_json, created_at, updated_at) \
                 VALUES ($1, $2, 'confirmed', 'seed', 1.0, '{}'::json, now(), now())",
                &[&issue_id, &identity_id],
            )
            .await
            .expect("confirmed backfill mapping");
        identity_id
    }

    fn deep_provider_result(issue_id: u32, date_last_updated: &str) -> Value {
        json!({
            "id": issue_id,
            "name": "Going For It",
            "issue_number": "3",
            "cover_date": "1988-03-01",
            "store_date": "1988-03-24",
            "image": {"medium_url": "https://img.example/medium.jpg"},
            "volume": {"id": 4001, "name": "Hellblazer"},
            "person_credits": [{"id": 1, "name": "Writer", "role": "writer"}],
            "character_credits": [],
            "team_credits": [],
            "story_arc_credits": [{"id": 4, "name": "Arc"}],
            "date_last_updated": date_last_updated,
        })
    }

    fn queue_deep_provider_result(state: &AppState, issue_id: u32, date_last_updated: &str) {
        let body = json!({
            "status_code": 1,
            "results": deep_provider_result(issue_id, date_last_updated),
        })
        .to_string();
        state.recording_fake().expect("recording provider").push_ok(
            StatusCode::OK,
            HeaderMap::new(),
            Bytes::from(body),
        );
    }

    async fn drain_for_test(state: &AppState) -> DrainReport {
        std::env::set_var("COMICVINE_API_KEY", "TESTKEY123");
        let mut headers = HeaderMap::new();
        headers.insert("authorization", "Bearer test-secret".parse().unwrap());
        drain_authorized(state, &headers, Some("test-secret"))
            .await
            .expect("authorized drain")
            .0
    }

    fn cron_headers() -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert("authorization", "Bearer test-secret".parse().unwrap());
        headers
    }

    /// #4516 legacy oracle: `_provider_timestamp` returned a naive datetime
    /// for ComicVine's `YYYY-MM-DD HH:MM:SS` revision. The retired Python
    /// identity upsert then evaluated
    /// `provider_updated_at < identity.provider_updated_at` against the
    /// UTC-aware value read from PostgreSQL, raising TypeError before metadata
    /// could be persisted. This exercises the canonical Rust replacement with
    /// the same pre-existing aware DB value and deterministic provider payload.
    #[tokio::test]
    async fn naive_provider_revision_hydrates_existing_utc_identity() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let identity_id = seed_identity(&state).await;
        let connection = db::checkout(&state).await.expect("seed connection");
        connection
            .execute(
                "UPDATE external_identities \
                 SET metadata_json = '{\"issue_number\":\"3\"}'::json, \
                     provider_updated_at = TIMESTAMPTZ '2025-01-01 00:00:00+00' \
                 WHERE id = $1",
                &[&identity_id],
            )
            .await
            .expect("seed aware provider revision");
        drop(Object::take(connection));
        seed_request(&state, identity_id, "pending", 0, "0 seconds", None).await;
        queue_deep_provider_result(&state, 29319, "2026-11-01 17:33:53");

        let job = claim(&state).await.expect("claim").expect("due job");
        assert_eq!(
            process(&state, &job, Some("TESTKEY123"))
                .await
                .expect("hydrate naive provider revision"),
            "completed"
        );

        let connection = db::checkout(&state).await.expect("assert connection");
        let row = connection
            .query_one(
                "SELECT e.metadata_json::text, e.provider_updated_at, \
                        r.state, r.last_error, r.completed_at IS NOT NULL \
                 FROM external_identities e \
                 JOIN comicvine_metadata_refresh_requests r \
                   ON r.external_identity_id = e.id \
                 WHERE e.id = $1",
                &[&identity_id],
            )
            .await
            .expect("read hydrated identity");
        let metadata: Value = serde_json::from_str(row.get(0)).expect("stored metadata JSON");
        assert_eq!(metadata["primary_image"], "https://img.example/medium.jpg");
        assert_eq!(metadata["creator_credits"][0]["name"], "Writer");
        assert_eq!(metadata["story_arcs"][0]["name"], "Arc");
        assert!(metadata["deep_metadata_refreshed_at"].is_string());
        let provider_updated_at: Option<chrono::DateTime<chrono::Utc>> = row.get(1);
        assert_eq!(
            provider_updated_at,
            Some(
                chrono::DateTime::parse_from_rfc3339("2026-11-01T17:33:53+00:00")
                    .expect("expected revision")
                    .with_timezone(&chrono::Utc)
            )
        );
        assert_eq!(row.get::<_, String>(2), "completed");
        assert_eq!(row.get::<_, Option<String>>(3), None);
        assert!(row.get::<_, bool>(4));
        drop(Object::take(connection));

        let calls = state.recording_fake().expect("recording provider").calls();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].host, HOST);
        assert!(calls[0].path.starts_with("/api/issue/4000-29319/"));
    }

    /// The inline catalog path runs only after its identity transaction has
    /// committed. Passing another owner's issue id must neither fetch nor
    /// mutate that owner's provider identity, while the requested owner's
    /// sparse identity receives the complete response and UTC revision.
    #[tokio::test]
    async fn post_commit_hydration_is_owner_scoped_and_persists_utc_metadata() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let connection = db::checkout(&state).await.expect("seed connection");
        connection
            .batch_execute(
                "INSERT INTO users (id, username) VALUES \
                   (1, 'repair-owner'), (2, 'repair-other'); \
                 INSERT INTO threads \
                   (id, title, format, issues_remaining, queue_position, status, user_id) \
                 VALUES \
                   (11, 'Owned', 'Series', 1, 1, 'active', 1), \
                   (12, 'Other', 'Series', 1, 1, 'active', 2); \
                 INSERT INTO issues \
                   (id, thread_id, issue_number, status, position, created_at) \
                 VALUES \
                   (101, 11, '3', 'unread', 1, now()), \
                   (102, 12, '3', 'unread', 1, now()); \
                 INSERT INTO external_identities \
                   (id, provider, entity_type, external_id, metadata_json, \
                    provider_updated_at, created_at, updated_at) \
                 VALUES \
                   (201, 'comicvine', 'issue', '4000-29319', \
                    '{\"issue_number\":\"3\"}'::json, \
                    TIMESTAMPTZ '2025-01-01 00:00:00+00', now(), now()), \
                   (202, 'comicvine', 'issue', '4000-29320', \
                    '{\"issue_number\":\"other\"}'::json, \
                    TIMESTAMPTZ '2025-02-02 00:00:00+00', now(), now()); \
                 INSERT INTO issue_external_identity_mappings \
                   (issue_id, external_identity_id, status, evidence_source, confidence, \
                    evidence_json, created_at, updated_at) \
                 VALUES \
                   (101, 201, 'confirmed', 'user_series_confirmation', 1.0, \
                    '{}'::json, now(), now()), \
                   (102, 202, 'confirmed', 'user_series_confirmation', 1.0, \
                    '{}'::json, now(), now());",
            )
            .await
            .expect("seed committed owner mappings");
        drop(Object::take(connection));
        queue_deep_provider_result(&state, 29319, "2026-11-01 17:33:53");

        hydrate_catalog_commit_with_key(
            &state,
            1,
            &[101, 102],
            Duration::from_secs(5),
            "TESTKEY123",
        )
        .await;

        let connection = db::checkout(&state).await.expect("assert connection");
        let owned = connection
            .query_one(
                "SELECT metadata_json::text, provider_updated_at \
                 FROM external_identities WHERE id = 201",
                &[],
            )
            .await
            .expect("read owned hydration");
        let metadata: Value = serde_json::from_str(owned.get(0)).expect("owned metadata JSON");
        assert_eq!(metadata["creator_credits"][0]["name"], "Writer");
        assert_eq!(metadata["story_arcs"][0]["name"], "Arc");
        assert!(metadata["deep_metadata_refreshed_at"].is_string());
        let provider_updated_at: Option<chrono::DateTime<chrono::Utc>> = owned.get(1);
        assert_eq!(
            provider_updated_at,
            Some(
                chrono::DateTime::parse_from_rfc3339("2026-11-01T17:33:53+00:00")
                    .expect("expected revision")
                    .with_timezone(&chrono::Utc)
            )
        );

        let other = connection
            .query_one(
                "SELECT metadata_json::text, provider_updated_at \
                 FROM external_identities WHERE id = 202",
                &[],
            )
            .await
            .expect("read other owner identity");
        let other_metadata: Value =
            serde_json::from_str(other.get(0)).expect("other owner metadata JSON");
        assert_eq!(other_metadata, json!({"issue_number": "other"}));
        let other_revision: Option<chrono::DateTime<chrono::Utc>> = other.get(1);
        assert_eq!(
            other_revision,
            Some(
                chrono::DateTime::parse_from_rfc3339("2025-02-02T00:00:00+00:00")
                    .expect("original revision")
                    .with_timezone(&chrono::Utc)
            )
        );
        drop(Object::take(connection));

        let calls = state.recording_fake().expect("recording provider").calls();
        assert_eq!(calls.len(), 1, "cross-owner ids must not be fetched");
        assert!(calls[0].path.starts_with("/api/issue/4000-29319/"));
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

    /// #5592: backfill dry-run and write reports share truthful accounting,
    /// resume by identity cursor, and leave user reading state untouched.
    #[tokio::test]
    async fn backfill_is_bounded_idempotent_and_preserves_reading_state() {
        let Some(state) = crate::test_support::test_state(4).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let connection = db::checkout(&state).await.expect("seed connection");
        let user_id: i32 = connection
            .query_one(
                "INSERT INTO users (username) VALUES ('backfill-owner') RETURNING id",
                &[],
            )
            .await
            .expect("backfill user")
            .get(0);
        let thread_id: i32 = connection
            .query_one(
                "INSERT INTO threads \
                 (title, format, issues_remaining, total_issues, queue_position, status, \
                  user_id, last_rating, reading_progress) \
                 VALUES ('Backfill', 'Comic', 3, 4, 7, 'active', $1, 4.5, 'in_progress') \
                 RETURNING id",
                &[&user_id],
            )
            .await
            .expect("backfill thread")
            .get(0);
        let missing = seed_confirmed_identity_for_thread(
            &connection,
            thread_id,
            "1",
            "4000-30001",
            &json!({}),
        )
        .await;
        let active = seed_confirmed_identity_for_thread(
            &connection,
            thread_id,
            "2",
            "4000-30002",
            &json!({}),
        )
        .await;
        let terminal = seed_confirmed_identity_for_thread(
            &connection,
            thread_id,
            "3",
            "4000-30003",
            &json!({}),
        )
        .await;
        let fresh_metadata =
            normalized_metadata(&deep_provider_result(30004, "2026-11-01 17:33:53"), 30004)
                .expect("fresh metadata")
                .0;
        let fresh = seed_confirmed_identity_for_thread(
            &connection,
            thread_id,
            "4",
            "4000-30004",
            &fresh_metadata,
        )
        .await;
        seed_request(&state, active, "pending", 4, "1 hour", None).await;
        seed_request(&state, terminal, "failed", 3, "1 hour", None).await;
        connection
            .execute(
                "UPDATE issues SET status = 'read', read_at = now() \
                 WHERE thread_id = $1 AND issue_number = '1'",
                &[&thread_id],
            )
            .await
            .expect("reading state");
        connection
            .execute(
                "INSERT INTO events (type, thread_id, issue_id, user_id) \
                 SELECT 'item_read', thread_id, id, $2 FROM issues \
                 WHERE thread_id = $1 AND issue_number = '1'",
                &[&thread_id, &user_id],
            )
            .await
            .expect("reading history");

        let dry = backfill_authorized(
            &state,
            &cron_headers(),
            Some("test-secret"),
            BackfillQuery {
                dry_run: true,
                limit: 500,
                after_id: 0,
            },
        )
        .await
        .expect("dry backfill")
        .0;
        assert_eq!(dry.scanned, 4);
        assert_eq!(dry.needs_enqueue, 2, "missing and terminal rows need work");
        assert_eq!(dry.enqueued, 0);
        assert_eq!(dry.already_queued_or_fresh, 2, "active and fresh rows");
        assert_eq!(dry.next_after_id, None);
        let unchanged: i64 = connection
            .query_one(
                "SELECT count(*) FROM comicvine_metadata_refresh_requests",
                &[],
            )
            .await
            .expect("dry-run ledger")
            .get(0);
        assert_eq!(unchanged, 2, "dry-run must not insert or reopen rows");

        let written = backfill_authorized(
            &state,
            &cron_headers(),
            Some("test-secret"),
            BackfillQuery {
                dry_run: false,
                limit: 500,
                after_id: 0,
            },
        )
        .await
        .expect("write backfill")
        .0;
        assert_eq!(written.scanned, 4);
        assert_eq!(written.needs_enqueue, 2);
        assert_eq!(written.enqueued, 2, "one insert plus one reopen");
        assert_eq!(written.already_queued_or_fresh, 2);
        let rows = connection
            .query(
                "SELECT external_identity_id, state, attempts, last_error \
                 FROM comicvine_metadata_refresh_requests ORDER BY external_identity_id",
                &[],
            )
            .await
            .expect("written ledger");
        assert_eq!(rows.len(), 3, "fresh metadata must not be enqueued");
        assert!(rows.iter().all(|row| row.get::<_, i32>(0) != fresh));
        for row in &rows {
            let identity_id: i32 = row.get(0);
            assert_eq!(row.get::<_, String>(1), "pending");
            if identity_id == active {
                assert_eq!(row.get::<_, i32>(2), 4, "active work is untouched");
            } else {
                assert_eq!(row.get::<_, i32>(2), 0);
                assert!(identity_id == missing || identity_id == terminal);
            }
        }

        let rerun = backfill_authorized(
            &state,
            &cron_headers(),
            Some("test-secret"),
            BackfillQuery {
                dry_run: false,
                limit: 500,
                after_id: 0,
            },
        )
        .await
        .expect("idempotent backfill")
        .0;
        assert_eq!(rerun.scanned, 4);
        assert_eq!(rerun.needs_enqueue, 0);
        assert_eq!(rerun.enqueued, 0, "active rows are not new work");
        assert_eq!(rerun.already_queued_or_fresh, 4);

        let first_page = backfill_authorized(
            &state,
            &cron_headers(),
            Some("test-secret"),
            BackfillQuery {
                dry_run: true,
                limit: 2,
                after_id: 0,
            },
        )
        .await
        .expect("first cursor page")
        .0;
        assert_eq!(first_page.scanned, 2);
        assert_eq!(first_page.next_after_id, Some(active));
        let second_page = backfill_authorized(
            &state,
            &cron_headers(),
            Some("test-secret"),
            BackfillQuery {
                dry_run: true,
                limit: 3,
                after_id: first_page.next_after_id.expect("cursor"),
            },
        )
        .await
        .expect("second cursor page")
        .0;
        assert_eq!(second_page.scanned, 2);
        assert_eq!(second_page.next_after_id, None);

        let thread = connection
            .query_one(
                "SELECT queue_position, last_rating, reading_progress FROM threads WHERE id = $1",
                &[&thread_id],
            )
            .await
            .expect("preserved thread");
        assert_eq!(thread.get::<_, i32>(0), 7);
        assert_eq!(thread.get::<_, Option<f64>>(1), Some(4.5));
        assert_eq!(
            thread.get::<_, Option<String>>(2).as_deref(),
            Some("in_progress")
        );
        let reading = connection
            .query_one(
                "SELECT \
                   (SELECT count(*) FROM issues WHERE thread_id = $1 AND status = 'read'), \
                   (SELECT count(*) FROM events WHERE thread_id = $1 AND type = 'item_read'), \
                   (SELECT count(*) FROM issue_external_identity_mappings m \
                    JOIN issues i ON i.id = m.issue_id \
                    WHERE i.thread_id = $1 AND m.status = 'confirmed')",
                &[&thread_id],
            )
            .await
            .expect("preserved reading and mappings");
        assert_eq!(reading.get::<_, i64>(0), 1);
        assert_eq!(reading.get::<_, i64>(1), 1);
        assert_eq!(reading.get::<_, i64>(2), 4);
    }

    /// #5592: ComicVine 420 is a rate limit (Python parity), not provider_unavailable.
    #[tokio::test]
    async fn provider_response_treats_420_as_rate_limited() {
        let fake = Arc::new(crate::outbound::RecordingFakeOutbound::new());
        let mut headers = HeaderMap::new();
        headers.insert("retry-after", "120".parse().unwrap());
        fake.push_ok(StatusCode::from_u16(420).unwrap(), headers, Bytes::new());
        let outbound: Arc<dyn crate::outbound::OutboundHttp> = fake;
        let err = provider_response(&outbound, "issue/4000-1", "", "TESTKEY123")
            .await
            .expect_err("420 must be rate limited");
        assert!(matches!(err, ProviderFailure::RateLimited(120)));
    }

    /// #5592: 403 is a plain provider error (Python parity), not a throttle.
    #[tokio::test]
    async fn provider_response_treats_403_as_unavailable() {
        let fake = Arc::new(crate::outbound::RecordingFakeOutbound::new());
        fake.push_ok(StatusCode::FORBIDDEN, HeaderMap::new(), Bytes::new());
        let outbound: Arc<dyn crate::outbound::OutboundHttp> = fake;
        let err = provider_response(&outbound, "issue/4000-1", "", "TESTKEY123")
            .await
            .expect_err("403 must be unavailable");
        assert!(matches!(err, ProviderFailure::Unavailable));
    }

    /// #5592: worker fetches a singular issue and persists creator credits.
    #[tokio::test]
    async fn drain_persists_creator_credits_for_pending_identity() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let identity_id = seed_identity(&state).await;
        seed_request(&state, identity_id, "pending", 0, "0 seconds", None).await;
        queue_deep_provider_result(&state, 29319, "2026-11-01 17:33:53");

        let report = drain_for_test(&state).await;
        assert_eq!(report.claimed, 1);
        assert_eq!(report.completed, 1);
        assert_eq!(report.deferred, 0);

        let connection = db::checkout(&state).await.expect("assert connection");
        let row = connection
            .query_one(
                "SELECT e.metadata_json::text, r.state \
                 FROM external_identities e \
                 JOIN comicvine_metadata_refresh_requests r ON r.external_identity_id = e.id \
                 WHERE e.id = $1",
                &[&identity_id],
            )
            .await
            .expect("row");
        let metadata: Value = serde_json::from_str(row.get(0)).expect("json");
        assert_eq!(metadata["creator_credits"][0]["name"], "Writer");
        assert_eq!(row.get::<_, String>(1), "completed");
    }

    /// #5592: legitimate empty credits remain distinct from transient failure.
    #[tokio::test]
    async fn drain_marks_explicit_empty_credits_as_no_credits() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let identity_id = seed_identity(&state).await;
        seed_request(&state, identity_id, "pending", 0, "0 seconds", None).await;
        let body = json!({
            "status_code": 1,
            "results": {
                "id": 29319,
                "name": "Issue",
                "issue_number": "1",
                "cover_date": "2020-01-01",
                "store_date": "2020-01-01",
                "image": {"medium_url": "https://img.example/m.jpg"},
                "volume": {"id": 1, "name": "V"},
                "person_credits": [],
                "character_credits": [],
                "team_credits": [],
                "story_arc_credits": [],
                "date_last_updated": "2026-11-01 17:33:53",
            }
        })
        .to_string();
        state.recording_fake().expect("recording provider").push_ok(
            StatusCode::OK,
            HeaderMap::new(),
            Bytes::from(body),
        );

        let report = drain_for_test(&state).await;
        assert_eq!(report.claimed, 1);
        assert_eq!(report.no_credits, 1);
        assert_eq!(report.deferred, 0);

        let connection = db::checkout(&state).await.expect("assert connection");
        let state_value: String = connection
            .query_one(
                "SELECT state FROM comicvine_metadata_refresh_requests WHERE external_identity_id = $1",
                &[&identity_id],
            )
            .await
            .expect("row")
            .get(0);
        assert_eq!(state_value, "no_credits");
    }

    /// #5592: a transient provider failure stays durable, observes its
    /// cooldown, and succeeds on a later worker invocation without reopening
    /// the issue or creating another request.
    #[tokio::test]
    async fn drain_retries_a_transient_failure_after_its_cooldown() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let identity_id = seed_identity(&state).await;
        seed_request(&state, identity_id, "pending", 0, "0 seconds", None).await;
        state.recording_fake().expect("recording provider").push_ok(
            StatusCode::SERVICE_UNAVAILABLE,
            HeaderMap::new(),
            Bytes::new(),
        );

        let first = drain_for_test(&state).await;
        assert_eq!(first.claimed, 1);
        assert_eq!(first.deferred, 1);
        assert_eq!(first.failed, 0);
        let connection = db::checkout(&state).await.expect("request connection");
        let row = connection
            .query_one(
                "SELECT state, attempts, last_error, next_attempt_at > now() \
                 FROM comicvine_metadata_refresh_requests WHERE external_identity_id = $1",
                &[&identity_id],
            )
            .await
            .expect("deferred request");
        assert_eq!(row.get::<_, String>(0), "deferred");
        assert_eq!(row.get::<_, i32>(1), 1);
        assert_eq!(
            row.get::<_, Option<String>>(2).as_deref(),
            Some("provider_unavailable")
        );
        assert!(row.get::<_, bool>(3));

        let cooled = drain_for_test(&state).await;
        assert_eq!(cooled.claimed, 0, "backoff must suppress immediate retries");
        connection
            .execute(
                "UPDATE comicvine_metadata_refresh_requests \
                 SET next_attempt_at = now() - interval '1 second' \
                 WHERE external_identity_id = $1",
                &[&identity_id],
            )
            .await
            .expect("make retry due");
        queue_deep_provider_result(&state, 29319, "2026-11-01 17:33:53");

        let retry = drain_for_test(&state).await;
        assert_eq!(retry.claimed, 1);
        assert_eq!(retry.completed, 1);
        let row = connection
            .query_one(
                "SELECT r.state, r.attempts, r.last_error, e.metadata_json::text \
                 FROM comicvine_metadata_refresh_requests r \
                 JOIN external_identities e ON e.id = r.external_identity_id \
                 WHERE r.external_identity_id = $1",
                &[&identity_id],
            )
            .await
            .expect("completed retry");
        assert_eq!(row.get::<_, String>(0), "completed");
        assert_eq!(row.get::<_, i32>(1), 2);
        assert_eq!(row.get::<_, Option<String>>(2), None);
        let metadata: Value = serde_json::from_str(row.get(3)).expect("hydrated metadata");
        assert_eq!(metadata["creator_credits"][0]["name"], "Writer");
        let count: i64 = connection
            .query_one(
                "SELECT count(*) FROM comicvine_metadata_refresh_requests \
                 WHERE external_identity_id = $1",
                &[&identity_id],
            )
            .await
            .expect("single durable request")
            .get(0);
        assert_eq!(count, 1);
        assert_eq!(
            state
                .recording_fake()
                .expect("recording provider")
                .calls()
                .len(),
            2
        );
    }

    /// #5592: a sparse/empty fresh roster must not overwrite previously hydrated credits.
    #[tokio::test]
    async fn drain_preserves_previously_hydrated_credits_on_sparse_refresh() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let identity_id = seed_identity(&state).await;
        let connection = db::checkout(&state).await.expect("seed connection");
        connection
            .execute(
                "UPDATE external_identities SET metadata_json = ($2::text)::json, updated_at = now() WHERE id = $1",
                &[
                    &identity_id,
                    &json!({
                        "creator_credits": [{"id": 7, "name": "Existing Writer"}],
                        "raw_provider_payload": {
                            "id": 29319, "name": "Old", "issue_number": "1",
                            "cover_date": null, "store_date": null, "image": null,
                            "volume": {"id": 1}, "person_credits": [{"id": 7, "name": "Existing Writer"}],
                            "character_credits": [], "team_credits": [], "story_arc_credits": [],
                            "date_last_updated": "2020-01-01 00:00:00"
                        },
                        "deep_metadata_refreshed_at": "2020-01-01T00:00:00+00:00"
                    }).to_string(),
                ],
            )
            .await
            .expect("seed metadata");
        drop(Object::take(connection));
        seed_request(&state, identity_id, "pending", 0, "0 seconds", None).await;
        let body = json!({
            "status_code": 1,
            "results": {
                "id": 29319, "name": "Issue", "issue_number": "1",
                "cover_date": "2020-01-01", "store_date": "2020-01-01",
                "image": {"medium_url": "https://img.example/m.jpg"},
                "volume": {"id": 1, "name": "V"},
                "person_credits": [], "character_credits": [], "team_credits": [],
                "story_arc_credits": [], "date_last_updated": "2026-11-01 17:33:53",
            }
        })
        .to_string();
        state.recording_fake().expect("recording provider").push_ok(
            StatusCode::OK,
            HeaderMap::new(),
            Bytes::from(body),
        );

        let report = drain_for_test(&state).await;
        assert_eq!(report.claimed, 1);
        assert_eq!(report.completed, 1);
        assert_eq!(report.deferred, 0);

        let connection = db::checkout(&state).await.expect("assert connection");
        let metadata_text: String = connection
            .query_one(
                "SELECT metadata_json::text FROM external_identities WHERE id = $1",
                &[&identity_id],
            )
            .await
            .expect("row")
            .get(0);
        let metadata: Value = serde_json::from_str(&metadata_text).expect("json");
        assert_eq!(metadata["creator_credits"][0]["name"], "Existing Writer");
    }
}
