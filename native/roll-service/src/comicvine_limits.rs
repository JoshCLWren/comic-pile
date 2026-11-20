//! Provider-side controls for the browser-called ComicVine routes (#4835).
//!
//! The retired Python `ComicVineClient.request` wrapped every provider call in
//! a response cache, a rolling-hour per-endpoint request budget
//! (`DEFAULT_REQUESTS_PER_HOUR = 180`) and a throttle cooldown that honours the
//! `Retry-After` ComicVine returned. Browser traffic (search, resolve, series
//! roster) must not spend the shared provider allowance faster than that, so
//! the same three controls wrap `provider_response` here. They live on
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
    comicvine_repair::{provider_response, ProviderFailure},
    outbound::OutboundHttp,
};
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

/// A bucket's throttle window. `recorded_at` is when the 429 was observed, not
/// when the window ends: Python's `reset(..., observed_at=...)` keeps a cooldown
/// recorded at or after the successful request started (#4634312998).
struct Cooldown {
    recorded_at: Instant,
    until: Instant,
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

    fn admit(&self, bucket: &str, cache_key: &str, now: Instant) -> Admission {
        let mut inner = self.lock();
        let cached = inner.cache.get(cache_key).cloned();
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
            inner.cooldowns.remove(bucket);
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

    /// Record a provider throttle and return any cached payload for the same
    /// request (Python returned it instead of raising).
    fn record_throttle(
        &self,
        bucket: &str,
        cache_key: &str,
        retry_after: u32,
        now: Instant,
    ) -> Option<Value> {
        let mut inner = self.lock();
        inner.cooldowns.insert(
            bucket.to_owned(),
            Cooldown {
                recorded_at: now,
                until: now + Duration::from_secs(u64::from(retry_after)),
            },
        );
        inner.cache.get(cache_key).map(|(_, value)| value.clone())
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
        let bucket = resource.split('/').next().unwrap_or(resource);
        let cache_key = format!("{resource}?{extra_query}");
        // The same timestamp bounds admission and the request's start, so a
        // sibling 429 observed while this call is in flight is never cleared.
        let request_started_at = Instant::now();
        match self.admit(bucket, &cache_key, request_started_at) {
            Admission::Cached(value) | Admission::Denied(_, Some(value)) => return Ok(value),
            Admission::Denied(wait, None) => return Err(ProviderFailure::RateLimited(wait)),
            Admission::Go => {}
        }
        match provider_response(outbound, resource, extra_query, api_key).await {
            Ok(value) => {
                self.record_success(
                    bucket,
                    cache_key,
                    &value,
                    request_started_at,
                    Instant::now(),
                );
                Ok(value)
            }
            Err(ProviderFailure::RateLimited(wait)) => self
                .record_throttle(bucket, &cache_key, wait, Instant::now())
                .ok_or(ProviderFailure::RateLimited(wait)),
            Err(failure) => Err(failure),
        }
    }
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
        limits.admit(bucket, key, now) == Admission::Go
    }

    #[test]
    fn budget_is_per_bucket_and_rolls_off_after_an_hour() {
        let limits = ComicVineLimits::default();
        let start = Instant::now();
        for n in 0..REQUESTS_PER_HOUR {
            assert!(go(&limits, "search", &format!("k{n}"), start));
        }
        assert!(matches!(
            limits.admit("search", "other", start),
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
        assert_eq!(limits.record_throttle("issues", "k", 90, start), None);
        assert_eq!(
            limits.admit("issues", "k", start + Duration::from_secs(10)),
            Admission::Denied(80, None)
        );
        assert!(go(&limits, "issues", "k", start + Duration::from_secs(91)));
        limits.record_throttle("issues", "k", 90, start);
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
        limits.record_throttle("search", "sibling", 90, base + Duration::from_secs(12));
        // Our success lands at t=15 but must not erase the newer cooldown.
        limits.record_success(
            "search",
            "late-success".into(),
            &Value::Null,
            request_started_at,
            base + Duration::from_secs(15),
        );
        assert_eq!(
            limits.admit("search", "next", base + Duration::from_secs(20)),
            Admission::Denied(82, None)
        );

        // A cooldown recorded before our request started is cleared as usual.
        let older = ComicVineLimits::default();
        older.record_throttle("issues", "sibling", 90, base + Duration::from_secs(5));
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
            limits.admit("search", "q", start + Duration::from_secs(60)),
            Admission::Cached(payload.clone())
        );
        // Past the TTL a live call is attempted again.
        let later = start + CACHE_TTL + Duration::from_secs(1);
        assert!(go(&limits, "search", "q", later));
        // A provider 429 on that live call answers with the older payload,
        // and the cooldown it records keeps serving it without a live call.
        assert_eq!(
            limits.record_throttle("search", "q", 120, later),
            Some(payload.clone())
        );
        assert_eq!(
            limits.admit("search", "q", later + Duration::from_secs(1)),
            Admission::Denied(119, Some(payload))
        );
        // A request with no cached payload is refused while cooling down.
        assert_eq!(
            limits.admit("search", "other", later + Duration::from_secs(1)),
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
}
