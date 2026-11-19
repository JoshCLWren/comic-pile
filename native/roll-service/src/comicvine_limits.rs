//! Provider-side controls for the browser-called ComicVine routes (#4835).
//!
//! The retired Python `ComicVineClient` wrapped every provider call in a
//! response cache, a rolling-hour per-endpoint request budget
//! (`DEFAULT_REQUESTS_PER_HOUR = 180`) and a throttle cooldown that honours the
//! `Retry-After` ComicVine returned. Browser traffic (search, resolve, series
//! roster, imports) must not spend the shared provider allowance faster than
//! that, so the same three controls wrap `provider_response` here. They live on
//! [`crate::AppState`] (process-wide, shared by every request, isolated per
//! test state). The metadata-repair worker keeps its own durable deferral
//! queue and calls the provider directly.

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
/// Successful responses are reused for this long (Python reused persisted
/// successful payloads instead of re-spending the allowance).
const CACHE_TTL: Duration = Duration::from_secs(900);
const CACHE_CAPACITY: usize = 256;

#[derive(Default)]
struct Inner {
    cache: HashMap<String, (Instant, Value)>,
    cooldowns: HashMap<String, Instant>,
    requests: HashMap<String, VecDeque<Instant>>,
}

/// Shared cache, per-endpoint rolling budget and cooldown tracker.
#[derive(Default)]
pub struct ComicVineLimits {
    inner: Mutex<Inner>,
}

/// Outcome of the pre-flight check.
enum Admission {
    Cached(Value),
    Denied(u32),
    Go,
}

impl ComicVineLimits {
    fn lock(&self) -> std::sync::MutexGuard<'_, Inner> {
        self.inner
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    fn admit(&self, bucket: &str, cache_key: &str, fresh: bool, now: Instant) -> Admission {
        let mut inner = self.lock();
        if !fresh {
            if let Some((stored, value)) = inner.cache.get(cache_key) {
                if now.duration_since(*stored) < CACHE_TTL {
                    return Admission::Cached(value.clone());
                }
            }
        }
        inner
            .cache
            .retain(|_, (stored, _)| now.duration_since(*stored) < CACHE_TTL);
        if let Some(until) = inner.cooldowns.get(bucket).copied() {
            if until > now {
                return Admission::Denied(remaining_secs(until, now));
            }
            inner.cooldowns.remove(bucket);
        }
        let recent = inner.requests.entry(bucket.to_owned()).or_default();
        while recent
            .front()
            .is_some_and(|stamp| now.duration_since(*stamp) >= WINDOW)
        {
            recent.pop_front();
        }
        if recent.len() >= REQUESTS_PER_HOUR {
            let wait = recent.front().map_or(WINDOW, |oldest| {
                (*oldest + WINDOW).saturating_duration_since(now)
            });
            return Admission::Denied(remaining_secs(now + wait, now));
        }
        recent.push_back(now);
        Admission::Go
    }

    fn record_success(&self, bucket: &str, cache_key: String, value: &Value, now: Instant) {
        let mut inner = self.lock();
        inner.cooldowns.remove(bucket);
        if inner.cache.len() >= CACHE_CAPACITY {
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

    fn record_throttle(&self, bucket: &str, retry_after: u32, now: Instant) {
        self.lock().cooldowns.insert(
            bucket.to_owned(),
            now + Duration::from_secs(u64::from(retry_after)),
        );
    }

    /// One provider call under the cache, budget and cooldown controls.
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

    /// Like [`Self::call`] but never serves a cached payload (series import
    /// must see the provider's current roster); the budget and cooldown still
    /// apply and the fresh payload refreshes the cache.
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
        match self.admit(bucket, &cache_key, fresh, Instant::now()) {
            Admission::Cached(value) => return Ok(value),
            Admission::Denied(wait) => return Err(ProviderFailure::RateLimited(wait)),
            Admission::Go => {}
        }
        let result = provider_response(outbound, resource, extra_query, api_key).await;
        match &result {
            Ok(value) => self.record_success(bucket, cache_key, value, Instant::now()),
            Err(ProviderFailure::RateLimited(wait)) => {
                self.record_throttle(bucket, *wait, Instant::now());
            }
            Err(_) => {}
        }
        result
    }
}

fn remaining_secs(until: Instant, now: Instant) -> u32 {
    let secs = until.saturating_duration_since(now).as_secs_f64().ceil();
    (secs as u32).max(1)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn go(limits: &ComicVineLimits, bucket: &str, key: &str, now: Instant) -> bool {
        matches!(limits.admit(bucket, key, false, now), Admission::Go)
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
            Admission::Denied(wait) if wait >= 3599
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
        limits.record_throttle("issues", 90, start);
        assert!(matches!(
            limits.admit("issues", "k", false, start + Duration::from_secs(10)),
            Admission::Denied(80)
        ));
        assert!(go(&limits, "issues", "k", start + Duration::from_secs(91)));
        limits.record_throttle("issues", 90, start);
        limits.record_success("issues", "k2".into(), &Value::Null, start);
        assert!(go(&limits, "issues", "k3", start + Duration::from_secs(1)));
    }

    #[test]
    fn successful_responses_are_reused_until_the_ttl() {
        let limits = ComicVineLimits::default();
        let start = Instant::now();
        let payload = serde_json::json!({"status_code": 1});
        assert!(go(&limits, "search", "q", start));
        limits.record_success("search", "q".into(), &payload, start);
        assert!(matches!(
            limits.admit("search", "q", false, start + Duration::from_secs(60)),
            Admission::Cached(value) if value == payload
        ));
        assert!(go(
            &limits,
            "search",
            "q",
            start + CACHE_TTL + Duration::from_secs(1)
        ));
    }
}
