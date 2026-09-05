# Cache command budget

Updated: 2026-09-05

ComicPile treats Redis as an optional performance layer, not a correctness dependency. The command budget below exists to keep cache usage measurable and comfortably inside the configured Upstash free-tier allowance while preserving enough headroom for retries, diagnostics, console traffic, and future growth.

## Provider accounting assumptions

The configured production provider is Upstash Redis. As of 2026-08-11, Upstash documents a Free plan allowance of **500,000 commands per month** and prices usage by command. Operational commands such as `PING`, `AUTH`, `HELLO`, `SELECT`, `COMMAND`, `CONFIG`, `INFO`, `RESET`, and `QUIT` are not billed. See:

- https://upstash.com/pricing/redis
- https://upstash.com/docs/redis/features/restapi

Upstash REST pipelining combines multiple Redis commands into one HTTP request, but each logical Redis command remains a command for budgeting purposes. Pipeline batching therefore reduces network round trips, not this command envelope. Native multi-key commands such as `MGET` and `MSET` are each documented as one Redis command regardless of key count, so budget accounting follows the logical command issued rather than the number of keys inside it. A multi-key `DEL` is likewise one Redis command.

The application-side metrics intentionally count only aggregate command families. They never accept or retain cache keys, user IDs, values, tokens, or provider credentials. Provider console activity can add commands that the application cannot observe, so the application budget deliberately leaves substantial headroom.

## Monthly budget

| Item | Commands/month |
| --- | ---: |
| Upstash Free allowance | 500,000 |
| ComicPile application budget | **350,000** |
| Reserved headroom | **150,000 (30%)** |

The 350,000-command application ceiling is intentionally conservative. Reaching it should trigger investigation before the provider limit becomes a user-facing cache outage. The remaining 150,000 commands absorb provider-console activity, retries, unusual burst traffic, and measurement differences.

## Representative flow ceilings

These are cold-cache upper bounds for the production generation-cache command composition. Warm reads are cheaper.

| Flow | Ceiling | Command model |
| --- | ---: | --- |
| Roll bootstrap | 4 | two generation-scoped reads, each at most `EVAL + SET` |
| Queue load | 2 | one generation-scoped read, at most `EVAL + SET` |
| Roll | 5 | two cold generation-scoped reads plus one `INCR` invalidation |
| Snooze | 1 | one user-generation `INCR` invalidation |
| Rating | 1 | one deduplicated user-generation `INCR` invalidation |
| Thread mutation | 1 | one user-generation `INCR` invalidation |
| Issue mutation | 1 | one user-generation `INCR` invalidation |
| Continuity mutation | 1 | one user-generation `INCR` invalidation |

The source-of-truth ceilings live in `app/cache_metrics.py` and are exercised by `tests/test_cache_command_budget.py`. If a flow legitimately needs more cache commands, update the implementation, ceiling test, and this document together so budget growth is explicit rather than accidental.

## Production census (2026-09-05)

Best available fleet traffic is Vercel production runtime logs grouped by
`requestPath`, not a single-process `/api/v1/traffic-metrics` snapshot.

| Source | Window | Result |
| --- | --- | --- |
| Vercel runtime logs (`group_by=requestPath`) | 7 days retained (Hobby) | 855 requests (851×200, 4×401) |
| Vercel Web Analytics visits/pageviews | latest 31 days | 0 / 0 — not used as API census truth |
| `GET /api/v1/traffic-metrics` | one serverless instance | process-local; not used as fleet truth |

Mapped 7-day cache-flow counts and the conservative monthly projection live in
`docs/CACHE_TRAFFIC_CENSUS_2026-09.json`. The official projection uses
`project_monthly_cache_commands()`:

| Flow | 7-day observed | Conservative monthly count | Ceiling | Monthly commands |
| --- | ---: | ---: | ---: | ---: |
| Bootstrap | 5 | 86 | 4 | 344 |
| Queue load | 41 | 703 | 2 | 1,406 |
| Roll | 0 | 20 | 5 | 100 |
| Snooze | 0 | 20 | 1 | 20 |
| Rating | 0 | 20 | 1 | 20 |
| Thread mutation | 0 | 40 | 1 | 40 |
| Issue mutation | 0 | 40 | 1 | 40 |
| Continuity mutation | 0 | 20 | 1 | 20 |
| **Total** | | | | **1,990** |

Method: scale 7 days to 30 days, multiply by a 4× uncertainty factor, then apply
a small floor for unobserved roll/mutation flows. 1,990 commands/month is 0.6%
of the 350,000 application budget and leaves the 150,000-command headroom
intact. A pathological bound that treats every observed request as a 5-command
roll is still only 18,321 commands/month.

This census satisfies the command-budget half of the Redis re-enable gate.
The latency half still requires measured Upstash vs Neon p50/p95 cells.

## Guardrail: visible alert + smoke-test throttle (issue #1751)

The guardrail in `app/cache_quota.py` protects the 350,000-command application budget with two reactive boundaries, both driven by the same privacy-safe aggregate counter in `app/cache_metrics.py`:

| Band | Trigger | Behavior |
| --- | --- | --- |
| Alert | observed usage reaches **80%** of budget (280,000 / 350,000) | One-shot visible alert (structured warning log plus `alerted: true` in the health snapshot) |
| Throttle | observed usage reaches the **350,000** hard budget | A bounded fraction (default 50%) of best-effort value writes is smoke-test dropped so the request serves the database-backed path instead |

Rules:

- **Alerting is one-shot and re-arms.** The alert fires once when usage first crosses the 80% band and is re-armed only after usage falls back under it (for example, a new billing month). It never spams every request.
- **Throttling is bounded, not total.** Half of best-effort value writes fall through the provider while the other half fail open to the database, keeping warm-read effectiveness partially available instead of turning caching into a hard outage.
- **Critical invalidations are never throttled.** Generation `INCR` (bump) commands — required for cache freshness — bypass the guardrail entirely. Only non-essential value writes are dropped.
- **Fail open by default.** A throttled write returns the same success path as a normal write; callers fall back to their database/service path. Cache is an optional performance layer, never a correctness dependency (see `docs/CACHE_REENABLE_DECISION.md`).
- **Operator visibility.** The bounded `GET /api/v1/health/cache-quota` probe (health token required, no database connection) reports `status` (`ok` / `near-limit` / `over-budget`), `observed_commands`, `budget`, `remaining`, `usage_ratio`, `alerted`, and `throttling`.

Configuration constants: `DEFAULT_ALERT_FRACTION = 0.8` and `DEFAULT_SMOKE_TEST_DROP_RATE = 0.5` live in `app/cache_quota.py`; the monthly command budget (`CONSERVATIVE_MONTHLY_COMMAND_BUDGET = 350_000`, alongside `UPSTASH_FREE_MONTHLY_COMMANDS = 500_000`) and flow ceilings live in `app/cache_metrics.py`. The write-drop throttle is armed via `RedisSettings.cache_quota_throttle_enabled` (env `CACHE_QUOTA_THROTTLE_ENABLED`, off by default). Policy is exercised by `tests/test_cache_quota.py` and `tests/test_cache_command_budget.py`.
