# Remote cache re-enable decision

Updated: 2026-09-05

## Decision

**GO redis — pending Josh's production env flips.**

`provider_recommendation()` returned `"upstash"` on the 2026-09-05 samples.
The production-demand half of the gate is also closed: Vercel production
runtime logs project **1,990** conservative monthly cache commands (pathological
upper bound 18,321), well under 350,000 with 150,000 headroom. See
`docs/CACHE_TRAFFIC_CENSUS_2026-09.json` and `project_monthly_cache_commands()`.

Latency: Upstash REST GET p50=7.088 ms / p95=7.807 ms (n=30) from Hobby
production `vercel:cle1`
(https://github.com/JoshCLWren/comic-pile/actions/runs/33986556893). Neon
point SELECT remains p50=143.303 ms / p95=151.812 ms from
`github-actions:ubuntu-latest` (cle1 Neon was not re-measured).

Josh confirmed the flips. The temporary probe is removed. After merge,
production Vercel env is set to `CACHE_PROVIDER=redis`,
`CACHE_ENABLED=true`, and `CACHE_QUOTA_THROTTLE_ENABLED=true`. Rollback
remains `CACHE_ENABLED=false`. Do not add GitHub secrets.

## TTL tier tuning (issue #1754)

TTL tiers were reviewed against the generation-invalidation model and raised to cut cache-command churn. Defaults moved from `90 / 180 / 360` seconds to **`120 / 360 / 900`** seconds (`app/config.py` `cache_ttl_short/medium/long`).

| Tier | Old default | New default | Primary consumers | Rationale |
| --- | ---: | ---: | --- | --- |
| `SHORT` | 90s | **120s** | Per-request reads: `app/api/session.py`, `app/api/thread.py`, `app/api/issue.py` (high-frequency GETs) | Reads within ~2 min now hit; writes still invalidate immediately via generation bump, so staleness risk is unchanged. |
| `MEDIUM` | 180s | **360s** | Dependency/series resolution in `app/api/dependency.py` | Reference-style data changes rarely; longer window improves hit rate with no correctness cost. |
| `LONG` | 360s | **900s** | Reserved for low-frequency lookups (no current `@cached` consumer in `app/`) | Headroom for future low-churn caching without re-tuning. |

**Why longer TTLs are safe here:** the generation namespace (`cache:user:<user_id>:g<gen>:...`) makes every user-scoped write invalidate all of that user's cached views with one `INCR` on the generation counter. The cached value becomes unreachable the instant a mutation bumps the generation, regardless of remaining TTL. TTL therefore governs only read-to-read freshness *between* writes, never read-after-write staleness. Lengthening the window raises the read hit rate without raising staleness risk.

**Modeled hit-rate effect (no production numbers available):** if a hot key is re-requested on a median spacing of ~100s, the old `SHORT=90s` would miss and refetch, while `SHORT=120s` hits. That is a structural ~25% larger hit window on the highest-frequency tier with zero added invalidation cost. The dominant command savings come from fewer cold-cache refills, bounded by the flow ceilings in `app/cache_metrics.py`.

## Key patterns and invalidation cost

| Pattern | Example | Invalidation | Command cost |
| --- | --- | --- | --- |
| Legacy value key | `cache:get_threads:7:` | TTL-only expiry | 0 (no active invalidation) |
| User value key | `cache:user:7:g3:get_queue:7:` | Generation bump (`INCR`) | **1 command** (no `SCAN`/enumeration) |
| Generation counter | `cache:generation:user:7` | n/a (bumped on write) | **1 command** per mutation |

User-scoped reads resolve their active generation and value atomically (`app/cache_generation.py`), so a single write invalidates every cached view for one user with exactly one `INCR`. Legacy (non-user-scoped) keys are reference data and expire purely by TTL; they carry no active invalidation and are few in number.

## Projected commands/day vs quota

Provider accounting (see `docs/CACHE_COMMAND_BUDGET.md`, `app/cache_metrics.py`):

- Upstash Free allowance: **500,000 commands/month**
- ComicPile application budget: **350,000 commands/month**
- Reserved headroom: **150,000 commands/month (30%)**
- Derived daily envelope (30-day month): ~**11,667 application commands/day**, ~**5,000/day** of headroom.

Conservative cold-cache flow ceilings (worst case; warm reads are cheaper):

| Flow | Ceiling | Command model |
| --- | ---: | --- |
| Roll bootstrap | 4 | two generation-scoped reads, each at most `EVAL + SET` |
| Queue load | 2 | one generation-scoped read, at most `EVAL + SET` |
| Roll | 5 | two cold generation-scoped reads + one `INCR` invalidation |
| Snooze / Rating / Thread / Issue / Continuity mutation | 1 each | one deduplicated user-generation `INCR` |

**Projection model.** For a day with `B` bootstraps, `Q` queue loads, `R` rolls, and `M` mutations:

```
daily_commands = 4*B + 2*Q + 5*R + 1*M
monthly_commands = daily_commands * 30
```

**Worked example — light day** (`B=100, Q=500, R=700, M=1000`):
`4*100 + 2*500 + 5*700 + 1000 = 5,900/day` → **177,000/month**. Under the 350,000 budget. GO-conditional.

**Worked example — heavy day** (`B=200, Q=1000, R=1500, M=2000`):
`4*200 + 2*1000 + 5*1500 + 2000 = 12,300/day` → **369,000/month**. Exceeds the 350,000 budget. NO-GO at this scale.

These are illustrative mixes; the authoritative number is the one-command usage report (`make cache-usage`, `app/cache_usage.py`) once real traffic is observed. Even at the heavy scale, the quota guardrail (`app/cache_quota.py`) self-limits best-effort value writes at the hard budget via `should_throttle_cache_write()`, so billing cannot exceed the plan — but repeated throttling means the cache is providing little benefit, which is itself a NO-GO signal.

## Evidence

- `app/config.py` requires `CACHE_ENABLED=true` in addition to provider credentials, so a configured token cannot silently enable caching.
- `app/cache.py` configures the client without a network probe. Startup therefore does not depend on Redis availability; the first real command is lazy and fail-open behavior remains in the cache wrappers.
- `app/cache_generation.py` invalidates a user's cached state with one shared generation `INCR`. Cached reads resolve the active generation and value atomically, so old generation keys become unreachable without `SCAN`.
- `tests/test_cache_reenable_safety.py` exercises two independent application clients sharing one Redis state and proves that an invalidation issued through one client forces the other client to reload rather than serve the stale generation.
- `docs/CACHE_COMMAND_BUDGET.md` and `tests/test_cache_command_budget.py` define conservative cold-cache ceilings for bootstrap, Queue, Roll, rating, snooze, thread, issue, and continuity flows.
- `app/cache_metrics.py` exposes `UPSTASH_FREE_MONTHLY_COMMANDS`, `CONSERVATIVE_MONTHLY_COMMAND_BUDGET`, and `MONTHLY_HEADROOM_COMMANDS` used by the projection above.

The historical benchmark corpus is useful for latency/load testing but is not a production traffic census. It must not be multiplied into a monthly provider forecast and presented as observed user demand.

## Re-enable gate

A future staged enablement may set `CACHE_ENABLED=true` only after all of these are true:

1. A recent production observation window provides counts for the representative cached flows, or an equivalent trustworthy command-rate measurement (`make cache-usage`).
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

**Decision: GO redis.** `provider_recommendation()` returned `"upstash"`.
Command budget is a GO (1,990 projected commands/month). Josh confirmed:

1. `CACHE_PROVIDER=redis`
2. `CACHE_ENABLED=true`
3. `CACHE_QUOTA_THROTTLE_ENABLED=true`

Rollback remains `CACHE_ENABLED=false`. The temporary
`GET /api/v1/health/cache-latency` route is removed.
