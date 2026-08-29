# Remote cache re-enable decision

Updated: 2026-08-11

## Decision

**Keep remote caching disabled for now.**

ComicPile now has bounded generation-based invalidation, privacy-safe command counting, conservative flow ceilings, and a 350,000-command monthly application budget against the documented 500,000-command Upstash free allowance. The remaining uncertainty is not correctness of the invalidation primitive. It is production demand. The repository does not yet contain a trustworthy recent production request mix that can be translated into an observed monthly cache-command projection, so enabling the provider would spend free-tier budget without evidence that the benefit justifies the risk.

This is deliberately a remain-disabled decision, not a rejection of Redis. Re-enable only after production evidence can demonstrate that projected application commands stay below the 350,000 monthly operating budget with the existing 150,000-command provider headroom.

## Evidence

- `app/config.py` requires `CACHE_ENABLED=true` in addition to provider credentials, so a configured token cannot silently enable caching.
- `app/cache.py` configures the client without a network probe. Startup therefore does not depend on Redis availability; the first real command is lazy and fail-open behavior remains in the cache wrappers.
- `app/cache_generation.py` invalidates a user's cached state with one shared Redis generation `INCR`. Cached reads resolve the active generation and value atomically, so old generation keys become unreachable without `SCAN`.
- `tests/test_cache_reenable_safety.py` exercises two independent application clients sharing one Redis state and proves that an invalidation issued through one client forces the other client to reload rather than serve the stale generation.
- `docs/CACHE_COMMAND_BUDGET.md` and `tests/test_cache_command_budget.py` define conservative cold-cache ceilings for bootstrap, Queue, Roll, rating, snooze, thread, issue, and continuity flows.

The historical benchmark corpus is useful for latency/load testing but is not a production traffic census. It must not be multiplied into a monthly provider forecast and presented as observed user demand.

## Re-enable gate

A future staged enablement may set `CACHE_ENABLED=true` only after all of these are true:

1. A recent production observation window provides counts for the representative cached flows, or an equivalent trustworthy command-rate measurement.
2. The observed mix, multiplied by the documented per-flow ceilings, projects below **350,000 application commands/month**.
3. The projection preserves the **150,000-command (30%) provider headroom** for retries, diagnostics, provider-console activity, and measurement error.
4. Multi-instance generation invalidation and lazy startup tests remain green.
5. The first rollout is reversible without a code deploy.

## Rollback boundary

Rollback is the `CACHE_ENABLED` environment flag. Setting it to `false` disables remote caching while leaving database-backed application correctness intact. Provider URL/token values may remain configured because `RedisSettings.is_configured` is false unless the explicit flag is enabled.

If a staged rollout shows unexpected command growth, cache errors, latency regressions, or stale-data symptoms, disable `CACHE_ENABLED` immediately and investigate from the database-backed path rather than increasing the command budget to accommodate the regression.

## Evaluation progress (issue #1716)

The re-enable evaluation added the operational guardrails the decision was missing. None of these change the remain-disabled verdict; they make a future staged enablement safer and observable.

- **One-command usage report vs budget.** `app/cache_usage.py` and `scripts/cache_usage_report.py` (`make cache-usage`) render observed application command usage against the 350,000-command operating budget and 500,000-command free allowance, with an optional provider month-to-date count from the Upstash console.
- **Quota guardrail: alert + smoke-test throttling.** `app/cache_quota.py` fires a one-shot alert at 80% of the operating budget and, once usage reaches the hard budget, smoke-test throttles a bounded fraction (default 50%) of best-effort value writes through `should_throttle_cache_write()`, consulted by `UpstashCache.set`. Critical generation invalidations are never throttled. The write-drop is **opt-in**: the guardrail starts disarmed and is only armed by `RedisSettings.cache_quota_throttle_enabled` (env `CACHE_QUOTA_THROTTLE_ENABLED`) so normal operation and the test suite never silently drop cache writes; alerting and the budget report remain active regardless.
- **Local Redis client path dev-flagged.** The local Redis client is no longer selectable in production. `RedisSettings.cache_local_redis_dev` (env `CACHE_LOCAL_REDIS_DEV`) must be explicit; `effective_provider` returns `off` for a bare `REDIS_URL`, and `UpstashCache.initialize` refuses `local_url` unless `allow_local=True`. Startup wiring honors the flag.
- **TTL tuning.** Default tiers raised to 120/360/900 seconds to cut cache-command churn; generation invalidation keeps user data fresh so the longer windows do not increase staleness risk.

### Go / no-go memo

**Decision: NO-GO for enabling remote Redis at this time.** The remain-disabled verdict from the prior decision stands. The evaluation is complete: observability, an alert-plus-throttle guardrail, a dev-gated local path, and tuned TTLs are now in place. Enabling `CACHE_ENABLED=true` is still gated behind the production-traffic evidence in the re-enable gate (observed mix projecting below 350,000 commands/month with 30% headroom). A future staged rollout must keep `CACHE_ENABLED` reversible and the quota guardrail active from day one.
