//! Provider-side controls for the browser-called ComicVine routes (#4835).
//!
//! The retired Python `ComicVineClient.request` wrapped every provider call in
//! a response cache, a rolling-hour per-endpoint request budget
//! (`DEFAULT_REQUESTS_PER_HOUR = 180`) and a throttle cooldown that honours the
//! `Retry-After` ComicVine returned. Browser traffic (search, resolve, series
//! roster) must not spend the shared provider allowance faster than that, so
//! the same three controls wrap `provider_exchange` here, with the Python
//! client's throttle rules (420/429, `Retry-After` honoured as sent,
//! header-less backoff). They live on
//! [`crate::AppState`] (process-wide, shared by every request, isolated per
//! test state). The metadata-repair worker keeps its own durable deferral
//! queue and calls the provider directly.
//!
//! Python served a cached payload whenever one existed (its cache never
//! expired) and fell back to it when the live call was throttled. Here a
//! cached payload is served without a provider call for [`CACHE_TTL`]; after
//! that a live call is attempted, and an older cached payload is still served
//! when the bucket is cooling down, over budget, or the live call is
//! throttled.

use crate::{
    comicvine_repair::{provider_exchange, Exchange, ProviderFailure},
    outbound::OutboundHttp,
};
use chrono::{DateTime, Utc};
use serde_json::Value;
use std::{
    collections::{HashMap, VecDeque},
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

/// Python `DEFAULT_REQUESTS_PER_HOUR`.
pub(crate) const REQUESTS_PER_HOUR: usize = 180;
const WINDOW: Duration = Duration::from_secs(3600);
/// Successful responses are reused without a provider call for this long.
const CACHE_TTL: Duration = Duration::from_secs(900);
const CACHE_CAPACITY: usize = 256;
/// Python `DEFAULT_NO_HEADER_COOLDOWN`: the first header-less throttle waits
/// this long, doubling per consecutive header-less throttle.
const NO_HEADER_COOLDOWN_SECS: f64 = 60.0;
/// Python `DEFAULT_MAX_NO_HEADER_COOLDOWN`.
const MAX_NO_HEADER_COOLDOWN_SECS: f64 = 3600.0;
/// Python never caps a provider `Retry-After`; Rust bounds it at a week only
/// so an absurd header cannot overflow `Instant` arithmetic.
const MAX_RETRY_AFTER_SECS: f64 = 7.0 * 24.0 * 3600.0;

/// A bucket's throttle window. `recorded_at` is when the 429 was observed, not
/// when the window ends: Python's `reset(..., observed_at=...)` keeps a cooldown
/// recorded at or after the successful request started (#4634312998).
/// `headerless_attempts` survives the window's expiry (Python keeps the entry
/// until a success resets it), so consecutive header-less throttles back off.
struct Cooldown {
    recorded_at: Instant,
    until: Instant,
    headerless_attempts: u32,
}

#[derive(Default)]
struct Inner {
    cache: HashMap<String, (Instant, Value)>,
    cooldowns: HashMap<String, Cooldown>,
    requests: HashMap<String, VecDeque<Instant>>,
}

/// Shared cache, per-endpoint rolling budget and cooldown tracker.
#[derive(Default)]
pub struct ComicVineLimits {
    inner: Mutex<Inner>,
}

/// Outcome of the pre-flight check.
#[derive(Debug, PartialEq)]
enum Admission {
    /// A payload cached within [`CACHE_TTL`].
    Cached(Value),
    /// The bucket is cooling down or over budget; the value is the wait in
    /// seconds and any older cached payload to serve instead.
    Denied(u32, Option<Value>),
    /// The caller may spend one request of the bucket's budget.
    Go,
}

impl ComicVineLimits {
    fn lock(&self) -> std::sync::MutexGuard<'_, Inner> {
        self.inner
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    /// `fresh` is Python `request(..., refresh=True)`: no cached payload is
    /// served before the live call (budget and cooldown still apply).
    fn admit(&self, bucket: &str, cache_key: &str, fresh: bool, now: Instant) -> Admission {
        let mut inner = self.lock();
        let cached = if fresh {
            None
        } else {
            inner.cache.get(cache_key).cloned()
        };
        if let Some((stored, value)) = &cached {
            if now.saturating_duration_since(*stored) < CACHE_TTL {
                return Admission::Cached(value.clone());
            }
        }
        let stale = cached.map(|(_, value)| value);
        if let Some(cooldown) = inner.cooldowns.get(bucket) {
            if cooldown.until > now {
                return Admission::Denied(remaining_secs(cooldown.until, now), stale);
            }
        }
        let recent = inner.requests.entry(bucket.to_owned()).or_default();
        while recent
            .front()
            .is_some_and(|stamp| now.saturating_duration_since(*stamp) >= WINDOW)
        {
            recent.pop_front();
        }
        if recent.len() >= REQUESTS_PER_HOUR {
            let until = recent
                .front()
                .map_or(now + WINDOW, |oldest| *oldest + WINDOW);
            return Admission::Denied(remaining_secs(until, now), stale);
        }
        recent.push_back(now);
        Admission::Go
    }

    /// Record a successful response. `request_started_at` must be captured
    /// before the provider call, matching Python's
    /// `reset(..., observed_at=request_started_at)`: a sibling request that
    /// received a 429 after ours started recorded a newer cooldown that must
    /// survive our success. Only cooldowns recorded strictly before the
    /// request started are cleared.
    fn record_success(
        &self,
        bucket: &str,
        cache_key: String,
        value: &Value,
        request_started_at: Instant,
        now: Instant,
    ) {
        let mut inner = self.lock();
        let older_cooldown = inner
            .cooldowns
            .get(bucket)
            .is_some_and(|cooldown| cooldown.recorded_at < request_started_at);
        if older_cooldown {
            inner.cooldowns.remove(bucket);
        }
        if !inner.cache.contains_key(&cache_key) && inner.cache.len() >= CACHE_CAPACITY {
            if let Some(oldest) = inner
                .cache
                .iter()
                .min_by_key(|(_, (stored, _))| *stored)
                .map(|(key, _)| key.clone())
            {
                inner.cache.remove(&oldest);
            }
        }
        inner.cache.insert(cache_key, (now, value.clone()));
    }

    /// Record a provider throttle (Python `ThrottleTracker.record_throttle`)
    /// and return the effective cooldown in seconds plus any cached payload
    /// for the same request (Python returned it instead of raising). A
    /// `Retry-After` is honoured as sent (never clamped up or down); without
    /// one the wait is 60 s doubling per consecutive header-less throttle, at
    /// most 3600 s.
    fn record_throttle(
        &self,
        bucket: &str,
        cache_key: &str,
        retry_after: Option<f64>,
        now: Instant,
    ) -> (u32, Option<Value>) {
        let mut inner = self.lock();
        let mut attempts = inner
            .cooldowns
            .get(bucket)
            .map_or(0, |cooldown| cooldown.headerless_attempts);
        let delay = match retry_after {
            Some(seconds) if seconds.is_nan() => 0.0,
            Some(seconds) => seconds.clamp(0.0, MAX_RETRY_AFTER_SECS),
            None => {
                attempts = attempts.saturating_add(1);
                let exponent = attempts.saturating_sub(1).min(20);
                (NO_HEADER_COOLDOWN_SECS * 2f64.powi(exponent as i32))
                    .min(MAX_NO_HEADER_COOLDOWN_SECS)
            }
        };
        let until = now + Duration::from_secs_f64(delay);
        inner.cooldowns.insert(
            bucket.to_owned(),
            Cooldown {
                recorded_at: now,
                until,
                headerless_attempts: attempts,
            },
        );
        let cached = inner.cache.get(cache_key).map(|(_, value)| value.clone());
        (remaining_secs(until, now), cached)
    }

    /// One provider call under the cache, budget and cooldown controls. The
    /// bucket is the resource's first path segment (`search`, `issues`,
    /// `volume`, `issue`), Python's `endpoint_bucket`.
    pub(crate) async fn call(
        &self,
        outbound: &Arc<dyn OutboundHttp>,
        resource: &str,
        extra_query: &str,
        api_key: &str,
    ) -> Result<Value, ProviderFailure> {
        self.call_with(outbound, resource, extra_query, api_key, false)
            .await
    }

    /// Python `request(..., refresh=True)` for series import, which must see
    /// the provider's current volume and roster: never served from the cache
    /// up front. A live 429/420 still falls back to a cached payload, like
    /// Python's throttle path; the budget and cooldown still apply.
    pub(crate) async fn call_fresh(
        &self,
        outbound: &Arc<dyn OutboundHttp>,
        resource: &str,
        extra_query: &str,
        api_key: &str,
    ) -> Result<Value, ProviderFailure> {
        self.call_with(outbound, resource, extra_query, api_key, true)
            .await
    }

    async fn call_with(
        &self,
        outbound: &Arc<dyn OutboundHttp>,
        resource: &str,
        extra_query: &str,
        api_key: &str,
        fresh: bool,
    ) -> Result<Value, ProviderFailure> {
        let bucket = resource.split('/').next().unwrap_or(resource);
        let cache_key = format!("{resource}?{extra_query}");
        // The same timestamp bounds admission and the request's start, so a
        // sibling 429 observed while this call is in flight is never cleared.
        let request_started_at = Instant::now();
        match self.admit(bucket, &cache_key, fresh, request_started_at) {
            Admission::Cached(value) | Admission::Denied(_, Some(value)) => return Ok(value),
            Admission::Denied(wait, None) => return Err(ProviderFailure::RateLimited(wait)),
            Admission::Go => {}
        }
        match provider_exchange(outbound, resource, extra_query, api_key).await? {
            Exchange::Payload(value) if browser_envelope_ok(&value) => {
                self.record_success(
                    bucket,
                    cache_key,
                    &value,
                    request_started_at,
                    Instant::now(),
                );
                Ok(value)
            }
            Exchange::Payload(_) => Err(ProviderFailure::Unavailable),
            // Python `ComicVineClient`: 420 and 429 are throttles; any other
            // non-2xx status (403 included) is a plain provider error.
            Exchange::Throttled {
                status: 420 | 429,
                retry_after,
            } => {
                let retry_after = retry_after.and_then(|raw| parse_retry_after(&raw, Utc::now()));
                match self.record_throttle(bucket, &cache_key, retry_after, Instant::now()) {
                    (_, Some(cached)) => Ok(cached),
                    (wait, None) => Err(ProviderFailure::RateLimited(wait)),
                }
            }
            Exchange::Throttled { .. } => Err(ProviderFailure::Unavailable),
        }
    }
}

/// Python `_request_async` envelope rule: the body must be an object whose
/// `status_code` is absent, `null` or equal to `1` (`status_code not in
/// (None, 1)` raises).
fn browser_envelope_ok(payload: &Value) -> bool {
    let Some(object) = payload.as_object() else {
        return false;
    };
    match object.get("status_code") {
        None | Some(Value::Null) | Some(Value::Bool(true)) => true,
        Some(Value::Number(n)) => n.as_f64() == Some(1.0),
        Some(_) => false,
    }
}

/// Python `_parse_retry_after`: delta-seconds (any float) or an HTTP date
/// measured from `now`; anything else is `None` (a header-less throttle).
fn parse_retry_after(raw: &str, now: DateTime<Utc>) -> Option<f64> {
    let value = raw.trim();
    if value.is_empty() {
        return None;
    }
    if let Ok(seconds) = value.parse::<f64>() {
        return Some(seconds);
    }
    DateTime::parse_from_rfc2822(value)
        .ok()
        .map(|at| (at.with_timezone(&Utc) - now).num_milliseconds() as f64 / 1000.0)
}

fn remaining_secs(until: Instant, now: Instant) -> u32 {
    let secs = until.saturating_duration_since(now).as_secs_f64().ceil();
    (secs as u32).max(1)
}

/// Deterministic timestamps only: no sleeps and no wall-clock timing.
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn go(limits: &ComicVineLimits, bucket: &str, key: &str, now: Instant) -> bool {
        limits.admit(bucket, key, false, now) == Admission::Go
    }

    #[test]
    fn budget_is_per_bucket_and_rolls_off_after_an_hour() {
        let limits = ComicVineLimits::default();
        let start = Instant::now();
        for n in 0..REQUESTS_PER_HOUR {
            assert!(go(&limits, "search", &format!("k{n}"), start));
        }
        assert!(matches!(
            limits.admit("search", "other", false, start),
            Admission::Denied(wait, None) if wait == 3600
        ));
        assert!(
            go(&limits, "issues", "k", start),
            "other buckets unaffected"
        );
        assert!(go(&limits, "search", "later", start + WINDOW));
    }

    #[test]
    fn throttle_sets_a_cooldown_that_expires_and_success_clears_it() {
        let limits = ComicVineLimits::default();
        let start = Instant::now();
        assert_eq!(
            limits.record_throttle("issues", "k", Some(90.0), start),
            (90, None)
        );
        assert_eq!(
            limits.admit("issues", "k", false, start + Duration::from_secs(10)),
            Admission::Denied(80, None)
        );
        assert!(go(&limits, "issues", "k", start + Duration::from_secs(91)));
        limits.record_throttle("issues", "k", Some(90.0), start);
        // The successful request started after the throttle was recorded, so
        // its success clears the (older) cooldown.
        limits.record_success(
            "issues",
            "k2".into(),
            &Value::Null,
            start + Duration::from_secs(1),
            start + Duration::from_secs(2),
        );
        assert!(go(&limits, "issues", "k3", start + Duration::from_secs(3)));
    }

    #[test]
    fn success_only_clears_cooldowns_recorded_before_the_request_started() {
        let base = Instant::now();

        // Two sibling requests are in flight. Ours starts at t=10; at t=12 the
        // other receives a 429 and records a 90s Retry-After cooldown.
        let request_started_at = base + Duration::from_secs(10);
        let limits = ComicVineLimits::default();
        limits.record_throttle(
            "search",
            "sibling",
            Some(90.0),
            base + Duration::from_secs(12),
        );
        // Our success lands at t=15 but must not erase the newer cooldown.
        limits.record_success(
            "search",
            "late-success".into(),
            &Value::Null,
            request_started_at,
            base + Duration::from_secs(15),
        );
        assert_eq!(
            limits.admit("search", "next", false, base + Duration::from_secs(20)),
            Admission::Denied(82, None)
        );

        // A cooldown recorded before our request started is cleared as usual.
        let older = ComicVineLimits::default();
        older.record_throttle(
            "issues",
            "sibling",
            Some(90.0),
            base + Duration::from_secs(5),
        );
        older.record_success(
            "issues",
            "early-success".into(),
            &Value::Null,
            base + Duration::from_secs(10),
            base + Duration::from_secs(11),
        );
        assert!(go(&older, "issues", "next", base + Duration::from_secs(12)));
    }

    #[test]
    fn cached_payloads_are_reused_then_served_only_as_a_throttle_fallback() {
        let limits = ComicVineLimits::default();
        let start = Instant::now();
        let payload = json!({"status_code": 1});
        assert!(go(&limits, "search", "q", start));
        limits.record_success("search", "q".into(), &payload, start, start);
        assert_eq!(
            limits.admit("search", "q", false, start + Duration::from_secs(60)),
            Admission::Cached(payload.clone())
        );
        // Past the TTL a live call is attempted again.
        let later = start + CACHE_TTL + Duration::from_secs(1);
        assert!(go(&limits, "search", "q", later));
        // A provider 429 on that live call answers with the older payload,
        // and the cooldown it records keeps serving it without a live call.
        assert_eq!(
            limits.record_throttle("search", "q", Some(120.0), later),
            (120, Some(payload.clone()))
        );
        assert_eq!(
            limits.admit("search", "q", false, later + Duration::from_secs(1)),
            Admission::Denied(119, Some(payload))
        );
        // A request with no cached payload is refused while cooling down.
        assert_eq!(
            limits.admit("search", "other", false, later + Duration::from_secs(1)),
            Admission::Denied(119, None)
        );
    }

    #[test]
    fn the_cache_is_bounded_by_evicting_the_oldest_entry() {
        let limits = ComicVineLimits::default();
        let start = Instant::now();
        for n in 0..CACHE_CAPACITY {
            let at = start + Duration::from_millis(n as u64);
            limits.record_success("search", format!("k{n}"), &json!(n), at, at);
        }
        let at = start + Duration::from_secs(60);
        limits.record_success("search", "new".into(), &json!("new"), at, at);
        let inner = limits.lock();
        assert_eq!(inner.cache.len(), CACHE_CAPACITY);
        assert!(!inner.cache.contains_key("k0"), "oldest entry evicted");
        assert!(inner.cache.contains_key("k1") && inner.cache.contains_key("new"));
    }

    /// Python `record_throttle` (#4637589533): a sent `Retry-After` is
    /// honoured as is (7200 s stays 7200 s); without one the wait doubles from
    /// 60 s per consecutive header-less throttle, capped at 3600 s, and the
    /// count survives the window's expiry until a success resets it.
    #[test]
    fn throttles_follow_the_python_cooldown_policy() {
        let limits = ComicVineLimits::default();
        let start = Instant::now();
        assert_eq!(
            limits.record_throttle("search", "k", Some(7200.0), start).0,
            7200
        );
        let mut at = start + Duration::from_secs(7201);
        let mut waits = Vec::new();
        for _ in 0..8 {
            let (wait, _) = limits.record_throttle("issues", "k", None, at);
            waits.push(wait);
            // Each window expires before the next throttle arrives.
            at += Duration::from_secs(u64::from(wait) + 1);
            assert!(go(&limits, "issues", &format!("k{wait}"), at));
        }
        assert_eq!(waits, [60, 120, 240, 480, 960, 1920, 3600, 3600]);
        // A header between header-less throttles keeps the count.
        assert_eq!(limits.record_throttle("issues", "k", Some(5.0), at).0, 5);
        at += Duration::from_secs(6);
        assert_eq!(limits.record_throttle("issues", "k", None, at).0, 3600);
        // A success that started after the last throttle resets the backoff.
        at += Duration::from_secs(3601);
        limits.record_success("issues", "ok".into(), &json!(1), at, at);
        assert_eq!(
            limits
                .record_throttle("issues", "k", None, at + Duration::from_secs(1))
                .0,
            60
        );
        // Zero, negative and NaN delays never block; absurd ones are bounded.
        for (raw, wait) in [(0.0, 1), (-30.0, 1), (f64::NAN, 1)] {
            let other = ComicVineLimits::default();
            assert_eq!(
                other.record_throttle("volume", "k", Some(raw), start).0,
                wait
            );
            assert!(go(&other, "volume", "k", start));
        }
        assert_eq!(
            ComicVineLimits::default()
                .record_throttle("volume", "k", Some(f64::INFINITY), start)
                .0,
            604_800
        );
    }

    #[test]
    fn retry_after_parses_seconds_and_http_dates_like_python() {
        let now = DateTime::parse_from_rfc3339("2026-11-19T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        assert_eq!(parse_retry_after("120", now), Some(120.0));
        assert_eq!(parse_retry_after(" 1.5 ", now), Some(1.5));
        assert_eq!(
            parse_retry_after("Thu, 19 Nov 2026 12:02:00 GMT", now),
            Some(120.0)
        );
        assert_eq!(
            parse_retry_after("Thu, 19 Nov 2026 11:59:00 GMT", now),
            Some(-60.0)
        );
        assert_eq!(parse_retry_after("soon", now), None);
        assert_eq!(parse_retry_after("", now), None);
    }

    #[test]
    fn browser_envelopes_follow_the_python_status_code_rule() {
        for (payload, ok) in [
            (json!({"results": []}), true),
            (json!({"status_code": null}), true),
            (json!({"status_code": 1}), true),
            (json!({"status_code": 1.0}), true),
            (json!({"status_code": true}), true),
            (json!({"status_code": 100}), false),
            (json!({"status_code": "1"}), false),
            (json!([]), false),
        ] {
            assert_eq!(browser_envelope_ok(&payload), ok, "{payload}");
        }
    }

    /// Python `refresh=True`: a cached payload is never served up front, but
    /// the budget and cooldown still gate the live call.
    #[test]
    fn fresh_calls_skip_the_cache_but_keep_budget_and_cooldown() {
        let limits = ComicVineLimits::default();
        let start = Instant::now();
        let payload = json!({"status_code": 1});
        limits.record_success("volume", "v".into(), &payload, start, start);
        let soon = start + Duration::from_secs(1);
        assert_eq!(
            limits.admit("volume", "v", false, soon),
            Admission::Cached(payload)
        );
        assert_eq!(limits.admit("volume", "v", true, soon), Admission::Go);
        limits.record_throttle("volume", "v", Some(30.0), soon);
        assert_eq!(
            limits.admit("volume", "v", true, soon + Duration::from_secs(1)),
            Admission::Denied(29, None),
            "a fresh call never gets the stale payload while cooling down"
        );
    }
}
