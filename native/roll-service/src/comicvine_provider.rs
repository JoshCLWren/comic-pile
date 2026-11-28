//! Shared ComicVine provider transport, normalization and synchronous hydration.
//!
//! Hydration is request/response work: there is no queue, scheduler, lease,
//! dispatch or background drain here. Every provider call is awaited inside the
//! HTTP request that requested it, already-persisted metadata is preserved on
//! failure, and no detached task outlives the response.
use crate::{
    comicvine_limits::{parse_retry_after, python_envelope_ok},
    db,
    outbound::{OutboundHttp, OutboundRequest},
    ApiError, AppState,
};
use axum::http::StatusCode;
use bytes::Bytes;
use http_body_util::BodyExt;
use serde_json::{json, Map, Value};
use std::{sync::Arc, time::Duration};

const HOST: &str = "comicvine.gamespot.com";
const MAX_BODY: usize = 2_000_000;
const PROVIDER_TIMEOUT: Duration = Duration::from_secs(5);
// Shared with comicvine_issue.rs READ_SQL: complete rows stay fresh 30 days;
// a deep response with empty credits is rechecked after 7 days. The two
// implementations must use the same precise policy (see needs_provider_fetch).
const COMPLETE_FRESH_DAYS: i64 = 30;
const EMPTY_CREDIT_RECHECK_DAYS: i64 = 7;

pub(crate) const FIELDS: &str = "id,name,issue_number,cover_date,store_date,image,volume,person_credits,character_credits,team_credits,story_arc_credits,date_last_updated";

/// Closed set of *safe* reasons a provider call can be unavailable. No variant
/// carries provider-controlled text, headers or a credential-bearing URL.
/// Callers use this to tell a real HTTP status from a reported error envelope
/// from a connectivity failure instead of collapsing all three into one class.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ProviderUnavailableCategory {
    /// A non-success HTTP status was observed before any body was trusted.
    HttpStatus { status: u16 },
    /// A 2xx response whose ComicVine envelope reported failure.
    ErrorEnvelope,
    /// Connect/TLS/HTTP/body-stream failure: no usable provider response.
    Transport,
}

impl ProviderUnavailableCategory {
    /// Stable diagnostic code; safe to log and to use as a wire discriminator.
    pub(crate) fn code(self) -> &'static str {
        match self {
            Self::HttpStatus { .. } => "http_status",
            Self::ErrorEnvelope => "error_envelope",
            Self::Transport => "transport",
        }
    }
}

/// Bounded, typed vocabulary for every ComicVine boundary failure.
///
/// Each variant is deliberately small and secret-free so it can be logged and
/// eventually surfaced to handlers without exposing the request URL (which
/// embeds `api_key`). `RateLimited` always carries a bounded delay sourced from
/// the provider's `Retry-After` (or the local cooldown when none was sent).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ProviderFailure {
    /// No usable credential is configured (empty, whitespace or malformed).
    ProviderNotConfigured,
    /// The provider failed without a usable payload; category says how.
    ProviderUnavailable(ProviderUnavailableCategory),
    /// The provider asked for a bounded backoff before retrying.
    RateLimited { retry_after_seconds: u32 },
    /// The request exceeded the bounded provider deadline.
    Timeout,
    /// Missing, oversized or non-JSON provider payload.
    InvalidResponse,
    /// A successful fetch could not be persisted.
    PersistFailed,
}

impl ProviderFailure {
    /// Stable snake-case diagnostic code for this failure class.
    pub(crate) fn code(self) -> &'static str {
        match self {
            Self::ProviderNotConfigured => "provider_not_configured",
            Self::ProviderUnavailable(_) => "provider_unavailable",
            Self::RateLimited { .. } => "rate_limited",
            Self::Timeout => "timeout",
            Self::InvalidResponse => "invalid_response",
            Self::PersistFailed => "persist_failed",
        }
    }
}

/// The single redacted diagnostic emitter for classified provider failures.
///
/// `context` is a code-owned static label. Only typed codes, numeric HTTP
/// status, the bounded retry delay and a type name are ever logged: never a
/// key, token, cookie, query string, credential-bearing URL or provider body.
pub(crate) fn log_provider_failure(context: &'static str, failure: ProviderFailure) {
    match failure {
        ProviderFailure::ProviderNotConfigured => tracing::warn!(
            comicvine_failure = failure.code(),
            context,
            "comicvine provider credential not configured"
        ),
        ProviderFailure::ProviderUnavailable(category) => {
            let status = match category {
                ProviderUnavailableCategory::HttpStatus { status } => Some(status),
                _ => None,
            };
            tracing::warn!(
                comicvine_failure = failure.code(),
                comicvine_category = category.code(),
                comicvine_status = ?status,
                context,
                "comicvine provider unavailable"
            );
        }
        ProviderFailure::RateLimited { retry_after_seconds } => tracing::warn!(
            comicvine_failure = failure.code(),
            retry_after_seconds,
            context,
            "comicvine provider rate limited"
        ),
        ProviderFailure::Timeout => tracing::warn!(
            comicvine_failure = failure.code(),
            context,
            "comicvine provider timeout"
        ),
        ProviderFailure::InvalidResponse => tracing::warn!(
            comicvine_failure = failure.code(),
            context,
            "comicvine provider invalid response"
        ),
        ProviderFailure::PersistFailed => tracing::warn!(
            comicvine_failure = failure.code(),
            context,
            "comicvine provider metadata persist failed"
        ),
    }
}

/// Classify a decoded envelope that failed [`python_envelope_ok`]. A JSON
/// object carrying a non-success `status_code` is an error envelope; anything
/// else is a malformed payload. No field value is copied into the classification.
pub(crate) fn envelope_failure(payload: &Value) -> ProviderFailure {
    if payload.is_object() {
        ProviderFailure::ProviderUnavailable(ProviderUnavailableCategory::ErrorEnvelope)
    } else {
        ProviderFailure::InvalidResponse
    }
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
                "screen_large_url",
                "medium_url",
                "screen_url",
                "small_url",
                "thumb_url",
                "tiny_url",
                "icon_url",
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
    let obj = result.as_object().ok_or(ProviderFailure::InvalidResponse)?;
    if obj.get("id").and_then(Value::as_u64) != Some(u64::from(expected_id)) {
        return Err(ProviderFailure::InvalidResponse);
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
            return Err(ProviderFailure::InvalidResponse);
        }
    }
    let image = obj.get("image").and_then(Value::as_object);
    let cover = image.and_then(|v| {
        [
            "original_url",
            "super_url",
            "screen_large_url",
            "medium_url",
            "screen_url",
            "small_url",
            "thumb_url",
            "tiny_url",
            "icon_url",
        ]
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
    /// HTTP 420/429 throttle with the raw `Retry-After` header, if any. The
    /// provider-supplied delay is preserved by the caller, never discarded.
    Throttled {
        retry_after: Option<String>,
    },
    /// Any other non-success HTTP status. The body is never read or logged.
    HttpStatus {
        status: u16,
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

/// One provider call, matching Python `ComicVineClient`
/// throttle rules: 420/429 are throttles whose `Retry-After` is clamped to
/// 60..=3600 s; any other non-2xx status (403 included) is a plain provider
/// error. Success envelopes use the same status-code rule as the Python fetch.
pub(crate) async fn provider_response(
    outbound: &Arc<dyn OutboundHttp>,
    resource: &str,
    extra_query: &str,
    api_key: &str,
) -> Result<Value, ProviderFailure> {
    let failure = match provider_exchange(outbound, resource, extra_query, api_key).await {
        Ok(Exchange::Payload(payload)) if python_envelope_ok(&payload) => return Ok(payload),
        Ok(Exchange::Payload(payload)) => envelope_failure(&payload),
        Ok(Exchange::Throttled { retry_after }) => ProviderFailure::RateLimited {
            retry_after_seconds: repair_retry_after_seconds(
                retry_after.as_deref(),
                chrono::Utc::now(),
            ),
        },
        Ok(Exchange::HttpStatus { status }) => {
            ProviderFailure::ProviderUnavailable(ProviderUnavailableCategory::HttpStatus { status })
        }
        Err(failure) => failure,
    };
    log_provider_failure("provider_response", failure);
    Err(failure)
}

/// Normalize one configured credential value. ComicVine keys are alphanumeric
/// and [`provider_exchange`] refuses anything else before it builds a URL, so a
/// value pasted into a deployment dashboard with a trailing newline (or
/// surrounding spaces) must be trimmed where it is read instead of being
/// reported as a provider outage. An absent or all-whitespace value is "not
/// configured", matching the Python client's empty-key check.
fn normalize_provider_api_key(raw: &str) -> Option<String> {
    let key = raw.trim();
    (!key.is_empty()).then(|| key.to_owned())
}

/// The single `COMICVINE_API_KEY` read. Every provider path (catalog roster,
/// inline hydration, search, plan sync) goes through this so
/// they agree on one normalization and on what "configured" means. The
/// returned value is never logged.
pub(crate) fn provider_api_key() -> Option<String> {
    std::env::var("COMICVINE_API_KEY")
        .ok()
        .and_then(|raw| normalize_provider_api_key(&raw))
}

pub(crate) async fn provider_exchange(
    outbound: &Arc<dyn OutboundHttp>,
    resource: &str,
    extra_query: &str,
    api_key: &str,
) -> Result<Exchange, ProviderFailure> {
    provider_exchange_with_timeout(outbound, resource, extra_query, api_key, PROVIDER_TIMEOUT).await
}

/// One exchange under an injectable deadline. The production wrapper always
/// uses [`PROVIDER_TIMEOUT`]; tests use a tiny deadline with a pending fake so
/// the timeout class is exercised without sleeping or opening a socket.
async fn provider_exchange_with_timeout(
    outbound: &Arc<dyn OutboundHttp>,
    resource: &str,
    extra_query: &str,
    api_key: &str,
    deadline: Duration,
) -> Result<Exchange, ProviderFailure> {
    // Callers construct only trusted resource names and numeric query values.
    // Fail closed on unexpected credential syntax rather than sending an unescaped secret.
    // Normalizing here as well as at the read boundary makes the invariant hold
    // for every caller, including future ones: whitespace can never turn into
    // `ProviderNotConfigured` being mistaken for an outage (#5695).
    let Some(api_key) = normalize_provider_api_key(api_key) else {
        return Err(ProviderFailure::ProviderNotConfigured);
    };
    if !api_key.bytes().all(|c| c.is_ascii_alphanumeric()) {
        // Never log the value, any fragment of it, or the credential-bearing URL.
        tracing::warn!("comicvine provider credential contains non-alphanumeric bytes");
        return Err(ProviderFailure::ProviderNotConfigured);
    }
    // ComicVine's API appends a slash to every resource, singular ones
    // included: `/api/volume/4050-<id>` and `/api/issue/4000-<id>` answer 301
    // with a `Location` that repeats the credential. The native transport never
    // follows redirects (so a credential can never be replayed on a new URL),
    // which turns every slash-less roster fetch into `provider_unavailable`
    // and breaks the Queue mapping-plan preview (#5851). Request the canonical
    // slash URL directly instead; the caller-provided `resource` never carries
    // a query string.
    let resource = resource.trim_end_matches('/');
    let request = OutboundRequest {
        method: http::Method::GET,
        path: format!("/api/{resource}/?api_key={api_key}&format=json{extra_query}"),
        headers: vec![
            ("accept".to_string(), "application/json".to_string()),
            (
                "user-agent".to_string(),
                "ComicPile/1.0 (metadata hydration)".to_string(),
            ),
        ],
        body: Bytes::new(),
    };
    let exchange = async {
        let response = outbound.send(HOST, request).await.map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "comicvine transport error classified"
            );
            ProviderFailure::ProviderUnavailable(ProviderUnavailableCategory::Transport)
        })?;
        let status = response.status;
        if status == StatusCode::TOO_MANY_REQUESTS || status.as_u16() == 420 {
            // Retain only the raw header; the caller bounds and records the
            // delay. Never log the credential-bearing URL, body or headers.
            return Ok(Exchange::Throttled {
                retry_after: response
                    .headers
                    .get("retry-after")
                    .and_then(|h| h.to_str().ok())
                    .map(str::to_owned),
            });
        }
        if !status.is_success() {
            // 403 stays a plain provider error (Python parity), now classified
            // as a distinct HTTP status rather than a generic unavailable.
            return Err(ProviderFailure::ProviderUnavailable(
                ProviderUnavailableCategory::HttpStatus {
                    status: status.as_u16(),
                },
            ));
        }
        if response
            .headers
            .get("content-length")
            .and_then(|h| h.to_str().ok())
            .and_then(|n| n.parse::<usize>().ok())
            .is_some_and(|n| n > MAX_BODY)
        {
            return Err(ProviderFailure::InvalidResponse);
        }
        let mut data = Vec::new();
        let mut body = response.body;
        while let Some(frame) = body.frame().await {
            let frame = frame.map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "comicvine transport error classified"
                );
                ProviderFailure::ProviderUnavailable(ProviderUnavailableCategory::Transport)
            })?;
            if let Ok(bytes) = frame.into_data() {
                if data.len() + bytes.len() > MAX_BODY {
                    return Err(ProviderFailure::InvalidResponse);
                }
                data.extend_from_slice(&bytes);
            }
        }
        let payload: Value = serde_json::from_slice(&data).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "comicvine malformed payload classified"
            );
            ProviderFailure::InvalidResponse
        })?;
        Ok(Exchange::Payload(payload))
    };
    tokio::time::timeout(deadline, exchange)
        .await
        .map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "comicvine deadline classified"
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
    .ok_or(ProviderFailure::InvalidResponse)
}

/// Classify and log a provider failure at a catalog call site before mapping
/// it to the unchanged public `provider_unavailable` API error. Later children
/// consume the typed vocabulary directly; this child only adds diagnostics.
fn log_and_unavailable(failure: ProviderFailure) -> ApiError {
    log_provider_failure("catalog_volume_roster", failure);
    ApiError::ServiceUnavailable("provider_unavailable".to_owned())
}

/// Read the same ComicVine volume and complete, validated issue roster used
/// by the Python preview builder. Never turn an outage or partial roster into
/// an empty successful plan: doing so can approve a wrong comic identity.
///
/// Routes through the shared ComicVine limits so preview roster fetches respect
/// rate limits, cooldowns, and cache fallback, matching the v2 series routes.
pub(crate) async fn catalog_volume_roster(
    limits: &crate::comicvine_limits::ComicVineLimits,
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
    let api_key = provider_api_key().ok_or_else(|| {
        log_provider_failure("catalog_volume_roster", ProviderFailure::ProviderNotConfigured);
        unavailable()
    })?;
    let volume = limits
        .call(outbound, &format!("volume/4050-{volume_id}"), "", &api_key)
        .await
        .map_err(log_and_unavailable)?;
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
        let page = limits
            .call(outbound, "issues", &query, &api_key)
            .await
            .map_err(log_and_unavailable)?;
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

/// Hydrate user-confirmed catalog identities *inline after commit*, using a
/// single request-wide budget. A provider failure never undoes the completed
/// identity transaction. No detached tasks are left running after the response.
pub(crate) async fn hydrate_catalog_commit(
    state: &AppState,
    user_id: i32,
    committed_issue_ids: &[i32],
    budget: Duration,
) {
    let Some(api_key) = provider_api_key() else {
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
            let provider_data = match provider_issue(&state.outbound, comicvine_id, api_key).await {
                Ok(value) => value,
                Err(failure) => {
                    log_provider_failure("catalog_commit_hydration", failure);
                    continue;
                }
            };
            let (patch, _, external_url, provider_updated_at) =
                match normalized_metadata(&provider_data, comicvine_id) {
                    Ok(value) => value,
                    Err(failure) => {
                        log_provider_failure("catalog_commit_hydration_normalize", failure);
                        continue;
                    }
                };
            let Ok(json_patch) = serde_json::to_string(&patch) else {
                log_provider_failure(
                    "catalog_commit_hydration_serialize",
                    ProviderFailure::InvalidResponse,
                );
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
                log_provider_failure("catalog_commit_persist", ProviderFailure::PersistFailed);
                tracing::debug!(
                    error_kind = crate::error_kind(&err),
                    "catalog commit persist error classified"
                );
            }
        }
    };
    if tokio::time::timeout(budget, run).await.is_err() {
        tracing::info!("catalog commit inline hydration budget exhausted");
    }
}

/// Resolve the currently confirmed ComicVine issue identity for an owned issue.
/// Evidence provenance is not part of eligibility: imported
/// (`comicvine_issue_adoption`) and user-confirmed identities are both
/// recoverable through the explicit synchronous Retry path. One set-based
/// query: no per-row round trips and no N+1. Returns the identity id, its
/// external id and the already-cached metadata used to preserve credits when
/// the fresh roster is empty.
async fn confirmed_identity_for_issue(
    conn: &deadpool_postgres::Object,
    user_id: i32,
    issue_id: i32,
) -> Option<(i32, String, Option<Value>)> {
    let row = conn
        .query_opt(
            "SELECT e.id, e.external_id, e.metadata_json::text
             FROM issue_external_identity_mappings m
             JOIN external_identities e ON e.id = m.external_identity_id
             JOIN issues i ON i.id = m.issue_id
             JOIN threads t ON t.id = i.thread_id
             WHERE m.issue_id = $1
               AND t.user_id = $2
               AND m.status = 'confirmed'
               AND e.provider = 'comicvine'
               AND e.entity_type = 'issue'
             ORDER BY e.id
             LIMIT 1",
            &[&issue_id, &user_id],
        )
        .await
        .ok()
        .flatten()?;
    let id: i32 = row.get(0);
    let external_id: String = row.get(1);
    let metadata = row
        .get::<_, Option<String>>(2)
        .and_then(|text| serde_json::from_str::<Value>(&text).ok());
    Some((id, external_id, metadata))
}

/// Synchronous, bounded creator-credit hydration for identity confirm/replace
/// and explicit Retry.
///
/// Runs *after* the mapping transaction commits: a provider failure, timeout or
/// unconfigured key never rolls back the confirmation. On success the fetched
/// credits (names + roles) and deep metadata are merged into the identity's
/// `metadata_json`, so the immediately-following `getIssueIntelligence` refetch
/// shows them without waiting on a background worker. On failure nothing is
/// persisted and the stored metadata stays usable; the issue remains eligible
/// for another explicit Retry. The whole operation is enclosed in a single
/// `timeout(budget, ...)` that covers the DB and provider calls.
pub(crate) async fn hydrate_confirmed_identity_inline(
    state: &AppState,
    user_id: i32,
    issue_id: i32,
    budget: Duration,
    api_key: &str,
    force: bool,
) {
    if budget.is_zero() || api_key.is_empty() {
        return;
    }
    let run = async {
        let conn = match db::checkout(state).await {
            Ok(c) => c,
            Err(_) => return,
        };
        let Some((identity_id, external_id, cached)) =
            confirmed_identity_for_issue(&conn, user_id, issue_id).await
        else {
            return;
        };
        // A confirm/remap can reuse already-complete same-identity metadata;
        // an explicit Retry (`force`) always performs a fresh bounded attempt.
        if !force {
            if let Some(metadata) = &cached {
                if !needs_provider_fetch(metadata, chrono::Utc::now()) {
                    return;
                }
            }
        }
        let Some(comicvine_id) = issue_id_from_external(&external_id) else {
            return;
        };
        let provider_data = match provider_issue(&state.outbound, comicvine_id, api_key).await {
            Ok(value) => value,
            Err(failure) => {
                log_provider_failure("inline_identity_hydration", failure);
                return;
            }
        };
        let (mut patch, has, url, updated) = match normalized_metadata(&provider_data, comicvine_id)
        {
            Ok(ok) => ok,
            Err(failure) => {
                log_provider_failure("inline_identity_hydration_normalize", failure);
                return;
            }
        };
        // A sparser fresh roster must never erase cached creator credits.
        if !has {
            preserve_cached_credits(&mut patch, cached.as_ref());
        }
        let Ok(json_patch) = serde_json::to_string(&patch) else {
            log_provider_failure(
                "inline_identity_hydration_serialize",
                ProviderFailure::InvalidResponse,
            );
            return;
        };
        if let Err(err) = conn
            .execute(
                "UPDATE external_identities
                 SET metadata_json = (COALESCE(metadata_json::jsonb, '{}'::jsonb)
                                      || ($2::text)::jsonb)::json,
                     external_url = COALESCE($3, external_url),
                     provider_updated_at = COALESCE(($4::text)::timestamptz, provider_updated_at),
                     updated_at = now()
                 WHERE id = $1 AND provider = 'comicvine' AND entity_type = 'issue'",
                &[&identity_id, &json_patch, &url, &updated],
            )
            .await
        {
            log_provider_failure("inline_identity_persist", ProviderFailure::PersistFailed);
            tracing::debug!(
                error_kind = crate::error_kind(&err),
                "inline identity persist error classified"
            );
        }
    };
    if tokio::time::timeout(budget, run).await.is_err() {
        tracing::info!("inline identity creator-credit hydration budget exhausted");
    }
}

/// Extract the numeric ComicVine issue id from an external identity id.
fn issue_id_from_external(external_id: &str) -> Option<u32> {
    issue_id(external_id)
}

/// Keep cached creator credits when a fresh fetch did not include a roster.
fn preserve_cached_credits(patch: &mut Value, cached: Option<&Value>) {
    let Some(existing) = cached else {
        return;
    };
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
        if let Some(obj) = patch.as_object_mut() {
            obj.insert(
                "creator_credits".to_owned(),
                compact_refs(&existing["raw_provider_payload"]["person_credits"]),
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::outbound::{OutboundFuture, OutboundResponse};
    use axum::{body::Body, http::HeaderMap};
    use deadpool_postgres::Object;
    use std::{any::Any, sync::Mutex};

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

    /// Push a canned provider response into the recording outbound fake.
    fn push_deep_provider_result(state: &AppState, issue_id: u32, date_last_updated: &str) {
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

    /// #5695: `provider_exchange` refuses non-alphanumeric credential bytes
    /// before any round trip, so an untrimmed read used to surface a pasted
    /// dashboard value with a trailing newline as a provider outage in tens of
    /// milliseconds. Normalization must make a padded key indistinguishable
    /// from a clean one, and an all-whitespace value "not configured".
    #[test]
    fn provider_api_key_normalizes_surrounding_whitespace() {
        assert_eq!(
            normalize_provider_api_key("c0ffee1234"),
            Some("c0ffee1234".to_owned())
        );
        assert_eq!(
            normalize_provider_api_key("  c0ffee1234\n"),
            Some("c0ffee1234".to_owned())
        );
        assert_eq!(
            normalize_provider_api_key("\tc0ffee1234 \r\n"),
            Some("c0ffee1234".to_owned())
        );
        assert_eq!(normalize_provider_api_key(""), None);
        assert_eq!(normalize_provider_api_key(" \n\t\r"), None);
    }

    /// #5695: the transport must enforce the same normalization as the read
    /// boundary, even when a future caller supplies a padded key directly.
    /// Blank and malformed credentials must fail before any outbound request.
    #[tokio::test]
    async fn provider_exchange_normalizes_key_before_request() {
        let fake = Arc::new(crate::outbound::RecordingFakeOutbound::new());
        fake.push_ok(
            StatusCode::OK,
            HeaderMap::new(),
            Bytes::from_static(br#"{"status_code":1,"results":{}}"#),
        );
        let outbound: Arc<dyn crate::outbound::OutboundHttp> = fake.clone();

        let exchange = provider_exchange(&outbound, "issue/4000-1", "", " \tTESTKEY123\n")
            .await
            .expect("padded credential must reach the provider");
        assert!(matches!(exchange, Exchange::Payload(_)));

        let calls = fake.calls();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].host, HOST);
        assert_eq!(
            calls[0].path,
            "/api/issue/4000-1/?api_key=TESTKEY123&format=json"
        );

        fake.clear();
        let error = provider_exchange(&outbound, "issue/4000-1", "", " \n\t")
            .await
            .expect_err("blank credential must be unconfigured");
        assert!(matches!(error, ProviderFailure::Unavailable));
        assert!(fake.calls().is_empty());

        let error = provider_exchange(&outbound, "issue/4000-1", "", "TEST KEY123")
            .await
            .expect_err("internal whitespace must remain malformed");
        assert!(matches!(error, ProviderFailure::Unavailable));
        assert!(fake.calls().is_empty());
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
        push_deep_provider_result(&state, 29319, "2026-11-01 17:33:53");

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
        assert!(calls[0].path.starts_with("/api/issue/4000-29319/?"));
    }

    /// Seed an owned issue with a freshly `user_confirmed` ComicVine identity
    /// and the pending fallback refresh row written by the enqueue savepoint.
    async fn seed_confirmed_identity(state: &AppState, external_id: &str, metadata: &Value) -> i32 {
        let connection = db::checkout(state).await.expect("seed connection");
        connection
            .batch_execute(
                "INSERT INTO users (id, username, is_admin, created_at) \
                 VALUES (1, 'confirm-owner', false, now()); \
                 INSERT INTO threads \
                   (id, title, format, issues_remaining, queue_position, status, user_id) \
                 VALUES (1, 'Owned', 'Series', 1, 1, 'active', 1); \
                 INSERT INTO issues (id, thread_id, issue_number, status, position, created_at) \
                 VALUES (1, 1, '3', 'unread', 1, now());",
            )
            .await
            .expect("seed owner");
        let identity_id: i32 = connection
            .query_one(
                "INSERT INTO external_identities \
                   (provider, entity_type, external_id, metadata_json, created_at, updated_at) \
                 VALUES ('comicvine', 'issue', $1, ($2::text)::json, now(), now()) \
                 RETURNING id",
                &[&external_id, &metadata.to_string()],
            )
            .await
            .expect("seed identity")
            .get(0);
        connection
            .execute(
                "INSERT INTO issue_external_identity_mappings \
                   (issue_id, external_identity_id, status, evidence_source, confidence, \
                    evidence_json, created_at, updated_at) \
                 VALUES (1, $1, 'confirmed', 'user_confirmed', 1.0, '{}'::json, now(), now())",
                &[&identity_id],
            )
            .await
            .expect("seed mapping");
        drop(Object::take(connection));
        identity_id
    }

    #[tokio::test]
    async fn inline_hydration_persists_creator_names_and_roles_after_confirm() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let identity_id = seed_confirmed_identity(&state, "4000-29319", &json!({})).await;
        push_deep_provider_result(&state, 29319, "2026-11-01 17:33:53");

        hydrate_confirmed_identity_inline(&state, 1, 1, Duration::from_secs(5), "TESTKEY123", true)
            .await;

        let connection = db::checkout(&state).await.expect("assert connection");
        let metadata: Value = serde_json::from_str(
            connection
                .query_one(
                    "SELECT metadata_json::text FROM external_identities WHERE id = $1",
                    &[&identity_id],
                )
                .await
                .expect("read hydrated metadata")
                .get(0),
        )
        .expect("metadata JSON");
        assert_eq!(metadata["creator_credits"][0]["name"], "Writer");
        assert_eq!(metadata["creator_credits"][0]["role"], "writer");
        assert_eq!(metadata["story_arcs"][0]["name"], "Arc");
        drop(Object::take(connection));
        let calls = state.recording_fake().expect("recording provider").calls();
        assert_eq!(calls.len(), 1);
        assert!(calls[0].path.starts_with("/api/issue/4000-29319/?"));
    }

    #[tokio::test]
    async fn inline_hydration_failure_keeps_mapping_and_stored_metadata() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let identity_id = seed_confirmed_identity(&state, "4000-29319", &json!({})).await;
        // No canned provider response: the recording fake fails closed.

        hydrate_confirmed_identity_inline(&state, 1, 1, Duration::from_secs(5), "TESTKEY123", true)
            .await;

        let connection = db::checkout(&state).await.expect("assert connection");
        let mapping_status: String = connection
            .query_one(
                "SELECT m.status FROM issue_external_identity_mappings m \
                 WHERE m.external_identity_id = $1",
                &[&identity_id],
            )
            .await
            .expect("mapping kept")
            .get(0);
        assert_eq!(mapping_status, "confirmed");
        let metadata: Value = serde_json::from_str(
            connection
                .query_one(
                    "SELECT metadata_json::text FROM external_identities WHERE id = $1",
                    &[&identity_id],
                )
                .await
                .expect("read metadata")
                .get(0),
        )
        .expect("metadata JSON");
        assert_eq!(
            metadata,
            json!({}),
            "provider failure must not fabricate credits"
        );
        drop(Object::take(connection));
    }

    #[tokio::test]
    async fn inline_hydration_zero_credits_persists_truthful_empty_metadata() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let identity_id = seed_confirmed_identity(&state, "4000-29319", &json!({})).await;
        let mut empty = deep_provider_result(29319, "2026-11-01 17:33:53");
        empty["person_credits"] = json!([]);
        let body = json!({"status_code": 1, "results": empty}).to_string();
        state.recording_fake().expect("recording provider").push_ok(
            StatusCode::OK,
            HeaderMap::new(),
            Bytes::from(body),
        );

        hydrate_confirmed_identity_inline(&state, 1, 1, Duration::from_secs(5), "TESTKEY123", true)
            .await;

        let connection = db::checkout(&state).await.expect("assert connection");
        let metadata: Value = serde_json::from_str(
            connection
                .query_one(
                    "SELECT metadata_json::text FROM external_identities WHERE id = $1",
                    &[&identity_id],
                )
                .await
                .expect("read metadata")
                .get(0),
        )
        .expect("metadata JSON");
        assert_eq!(metadata["creator_credits"], json!([]));
        assert!(metadata["raw_provider_payload"].is_object());
        drop(Object::take(connection));
    }

    #[tokio::test]
    async fn inline_hydration_empty_roster_preserves_cached_credits() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let identity_id = seed_confirmed_identity(
            &state,
            "4000-29319",
            &json!({"creator_credits": [{"id": 9, "name": "Cached Writer", "role": "writer"}]}),
        )
        .await;
        let mut empty = deep_provider_result(29319, "2026-11-01 17:33:53");
        empty["person_credits"] = json!([]);
        let body = json!({"status_code": 1, "results": empty}).to_string();
        state.recording_fake().expect("recording provider").push_ok(
            StatusCode::OK,
            HeaderMap::new(),
            Bytes::from(body),
        );

        hydrate_confirmed_identity_inline(&state, 1, 1, Duration::from_secs(5), "TESTKEY123", true)
            .await;

        let connection = db::checkout(&state).await.expect("assert connection");
        let metadata: Value = serde_json::from_str(
            connection
                .query_one(
                    "SELECT metadata_json::text FROM external_identities WHERE id = $1",
                    &[&identity_id],
                )
                .await
                .expect("read metadata")
                .get(0),
        )
        .expect("metadata JSON");
        assert_eq!(metadata["creator_credits"][0]["name"], "Cached Writer");
        drop(Object::take(connection));
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

    /// Minimal ComicVine stand-in: a missing trailing slash on any resource
    /// produces the same 301 the real API returns, and the native transport
    /// never follows it.
    #[derive(Default)]
    struct SlashEnforcingOutbound {
        calls: Mutex<Vec<String>>,
    }

    impl SlashEnforcingOutbound {
        fn paths(&self) -> Vec<String> {
            self.calls
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner())
                .clone()
        }
    }

    impl OutboundHttp for SlashEnforcingOutbound {
        fn send(&self, _host: &str, request: OutboundRequest) -> OutboundFuture {
            let path = request.path.clone();
            self.calls
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner())
                .push(path.clone());
            let redirect = path
                .split('?')
                .next()
                .is_some_and(|resource| !resource.ends_with('/'));
            let (status, body) = if redirect {
                (StatusCode::MOVED_PERMANENTLY, Bytes::new())
            } else if path.starts_with("/api/issues/") {
                (
                    StatusCode::OK,
                    Bytes::from(
                        r#"{"status_code":1,"number_of_total_results":2,"results":[
                            {"id":5851000,"issue_number":"1","name":"One","volume":{"id":5851001}},
                            {"id":5851001,"issue_number":"2","name":"Two","volume":{"id":5851001}}
                        ]}"#
                        .to_string(),
                    ),
                )
            } else {
                (
                    StatusCode::OK,
                    Bytes::from(
                        r#"{"status_code":1,"results":{"id":5851001,"name":"Nova (2007)",
                            "publisher":{"name":"Marvel"},"start_year":2007,
                            "count_of_issues":2,"site_detail_url":"https://example.test/volume",
                            "image":null}}"#,
                    ),
                )
            };
            Box::pin(async move {
                Ok(OutboundResponse {
                    status,
                    headers: HeaderMap::new(),
                    body: Body::from(body),
                })
            })
        }

        fn as_any(&self) -> &dyn Any {
            self
        }
    }

    /// #5851: ComicVine 301s slash-less singular resources. The preview's
    /// volume/issue roster fetch must request the canonical slash URL on the
    /// first round trip: the native transport never replays a credential on a
    /// redirect.
    #[tokio::test]
    async fn provider_requests_canonical_slash_urls_without_following_redirects() {
        let outbound: Arc<dyn OutboundHttp> = Arc::new(SlashEnforcingOutbound::default());
        let fake = outbound
            .as_any()
            .downcast_ref::<SlashEnforcingOutbound>()
            .expect("slash-enforcing fake");

        for resource in [
            "volume/4050-5851001",
            "issue/4000-5851000",
            "issues",
            "search",
        ] {
            let exchange = provider_exchange(&outbound, resource, "", "TESTKEY123")
                .await
                .expect("canonical URL must not be redirected");
            assert!(matches!(exchange, Exchange::Payload(_)), "{resource}");
        }

        let paths = fake.paths();
        assert_eq!(paths.len(), 4);
        for (path, resource) in paths.iter().zip([
            "volume/4050-5851001",
            "issue/4000-5851000",
            "issues",
            "search",
        ]) {
            assert!(
                path.starts_with(&format!("/api/{resource}/?")),
                "ComicVine requires a trailing slash: {path}"
            );
        }
    }

    /// #5851: the Queue mapping-plan builder must load a real roster through
    /// the canonical provider URLs, with no warm in-process cache to hide the
    /// slash-less redirect.
    #[tokio::test]
    async fn catalog_volume_roster_loads_without_following_provider_redirects() {
        let outbound: Arc<dyn OutboundHttp> = Arc::new(SlashEnforcingOutbound::default());
        let fake = outbound
            .as_any()
            .downcast_ref::<SlashEnforcingOutbound>()
            .expect("slash-enforcing fake");
        let mut previous = std::env::var("COMICVINE_API_KEY").ok();
        std::env::set_var("COMICVINE_API_KEY", "TESTKEY123");

        let limits = crate::comicvine_limits::ComicVineLimits::default();
        let result = catalog_volume_roster(&limits, &outbound, "5851001").await;

        match previous.take() {
            Some(value) => std::env::set_var("COMICVINE_API_KEY", value),
            None => std::env::remove_var("COMICVINE_API_KEY"),
        }
        let (series, roster) = result.expect("roster must load without a redirect");
        assert_eq!(series["id"], "5851001");
        assert_eq!(series["name"], "Nova (2007)");
        assert_eq!(roster.len(), 2);
        let paths = fake.paths();
        assert_eq!(paths.len(), 2, "one volume read and one roster page");
        assert!(paths[0].starts_with("/api/volume/4050-5851001/?"));
        assert!(paths[1].starts_with("/api/issues/?"));
    }
}
