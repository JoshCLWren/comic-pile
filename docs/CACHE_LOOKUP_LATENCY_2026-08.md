# Cache lookup latency: Upstash REST vs Neon point SELECT

Updated: 2026-09-05  
Script: `scripts/benchmark_cache_latency.py` plus temporary `GET /api/v1/health/cache-latency`  
Preferred vantage: Vercel region `cle1` (`vercel.json` `regions`).  
Upstash was measured from Hobby production (`vercel:cle1`). Neon stays the
existing `github-actions:ubuntu-latest` distribution (cle1 Neon was not
re-measured). Mixed vantages are called out in the table and JSON.

Run command:

    DATABASE_URL=postgresql://... \
    UPSTASH_REDIS_REST_URL=https://... \
    UPSTASH_REDIS_REST_TOKEN=... \
    VERCEL_BASE_URL=https://comic-pile.vercel.app \
    VERCEL_BEARER_TOKEN=... \
        python scripts/benchmark_cache_latency.py \
            --iterations 30 \
            --warmups 3 \
            --location "vercel:cle1" \
            --redact \
            --output docs/CACHE_LOOKUP_LATENCY_2026-08.json

Issues: #1782, #2216

## Quota context

Upstash Redis free-tier REST quota was exhausted through approximately
2026-08-28. HTTP 429 responses are recorded as `"status": "quota_blocked"`.
The 2026-09-05 production-runtime probe did not receive HTTP 429
(`quota_blocked=false`).

## Measurements

Committed JSON: `docs/CACHE_LOOKUP_LATENCY_2026-08.json`  
Workflow run: https://github.com/JoshCLWren/comic-pile/actions/runs/33986556893  
One-shot deploy: https://comic-pile-4kvkaxz5x-joshclwrens-projects.vercel.app  
Production alias restored to: `dpl_9E9NbZS8LTGZe5evKcwBtdD1dLhC` (`main` `a95cba45`)  
Iterations 30, warmups 3. `CACHE_PROVIDER` was never flipped.

| Path | Samples | Min (ms) | Median (ms) | P95 (ms) | Max (ms) | Mean (ms) | Vantage | Status |
|---|---|---|---|---|---|---|---|---|
| Upstash REST GET | 30 | 6.579 | 7.088 | 7.807 | 7.872 | 7.150 | `vercel:cle1` production | ok |
| Neon point SELECT (KV table) | 30 | 115.849 | 143.303 | 151.812 | 152.833 | 141.518 | `github-actions:ubuntu-latest` | ok |
| Uncached queue read (`/api/v1/sessions/current/`) | 0 | — | — | — | — | — | — | skipped: no `VERCEL_BEARER_TOKEN` |

Neon comparison remains the existing GHA number; cle1 Neon was not
re-measured. An earlier same-vantage Neon run landed at p50=569.314 ms
(also 30 ok samples) and is context only.

`provider_recommendation(LatencySample(7.088, 7.807), LatencySample(143.303, 151.812))`
returned **`"upstash"`** (GO redis). Production stays on Postgres until Josh
confirms the documented env flips. Remove `GET /api/v1/health/cache-latency`
after this measurement / before merge to `main`.

## What each measurement captures

### Upstash REST GET

The raw `GET` against the Upstash REST endpoint that the application would
issue on every cache lookup when `CACHE_ENABLED=true`.  The request mirrors
the call performed by `upstash_redis.asyncio.Redis.get` (the class used by
`UpstashCache` in `app/cache.py`), stripped to the minimum HTTP call the
library makes: a single `GET` with an `Authorization: Bearer <token>` header.

This is the closest available in-Vercel-region measurement of the hop that
would replace the uncached Neon read described below.

### Neon point SELECT

An `asyncpg` connection (same driver the production FastAPI app uses:
`postgresql+asyncpg://`) executes:

    SELECT key, value, created_at FROM bench_cache_kv WHERE key = $1 LIMIT 1

against an intentionally narrow KV-style table with a `TEXT PRIMARY KEY` on
`key`.  The table is created with `CREATE TABLE IF NOT EXISTS` and populated
idempotently so reruns do not require setup steps.  The connection is opened
and closed per-sample period (new pool each time) to keep the measurement
consistent with a cold-cache hop.

This is the hypothetical latency if the cache backing were replaced by a
PostgreSQL key-value table over the same Neon connection.

### Uncached queue read

An authenticated `GET` to `/api/v1/sessions/current/` from an external vantage
point (Vercel region) issued with a bearer token.  In production the FastAPI
application returns the active session and the associated thread queue
alongside other read data.  This request is routed through the application
layer (FastAPI middleware, rate-limiter, dependency injection, SQLAlchemy
query) and returns the database result through the full response pipeline.

The result is the stalest realistic baseline: end-to-end app + database with
no cache layer active (`CACHE_ENABLED=false` by default) — exactly the
production state today.

The comparison between path 2 and path 3 answers "how much latency does the
application stack add to a raw Postgres point read?"

## Provider decision memo

The go/no-go ruling lives in `CACHE_PROVIDER_DECISION_2026-08.md` (issue
#2216): **GO redis** from `provider_recommendation() == "upstash"`. Production
is still Postgres; this PR does not apply env flips.

The rule itself is unchanged:

- **Upstash REST p50 < 2× Neon p50** and Neon p50 > 3 ms → `"upstash"`
- **Upstash REST p50 ≥ 2× Neon p50, or Neon p50 ≤ 3 ms** → `"postgres"`
- **Either path p95 / p50 > 5×** → `"investigate"`

Measured: 7.088 < 2 × 143.303 (286.606) and 143.303 > 3; Upstash p95/p50 =
1.10×; Neon p95/p50 = 1.06×. Result: `"upstash"`.

## Re-run procedure

Do not add GitHub secrets. Do not start another production one-shot unless
Upstash samples return to 0. The 2026-09-05 production-runtime probe already
filled the Upstash row.

## Related documents and code

- `CACHE_PROVIDER_DECISION_2026-08.md` – the go/no-go memo this benchmark feeds
- `docs/CACHE_REENABLE_DECISION.md` – the live re-enable gate this benchmark feeds
- `docs/CACHE_COMMAND_BUDGET.md` – 350 000 command/month budget constraint
- `docs/CACHE_TRAFFIC_CENSUS_2026-09.json` – Vercel runtime-log census feeding `project_monthly_cache_commands()`
- `app/cache.py` – `UpstashCache`, circuit breaker, `@cached` decorator
- `app/cache_generation.py` – generation-namespace invalidation (the atomic
  `INCR` that makes all prior generation keys unreachable without a SCAN)
- `scripts/benchmark_session_reads.py` – existing HTTP performance harness
- `scripts/pool_benchmark.py` – database connection-pool microbenchmarks

## JSON output schema (version 1)

```jsonc
{
  "schema_version": "1",          // bump on any structural change
  "measured_from": "vercel:cle1", // deployment vantage identifier
  "iterations": 30,
  "warmups_per_path": 3,
  "kv_table": "bench_cache_kv",
  "upstash_rest_get": {
    "endpoint": "https://us1-xxx.upstash.io/get/comic_pile_cache_latency_bench_key_v1",
    "quota_blocked": false,
    "runs": [
      {
        "path": "upstash_rest_get",
        "iteration": 0,
        "elapsed_ms": 12.3,
        "status": "ok",
        "http_status": 200,
        "upstash_error": null,
        "error_detail": null
      }
    ],
    "summary": {
      "samples": 30,
      "elapsed_ms": {
        "min": 9.8,
        "p50": 12.1,
        "p95": 18.4,
        "max": 22.5,
        "mean": 12.9
      }
    }
  },
  "neon_point_select": { "runs": [...], "summary": {...} },
  "uncached_queue_read": { "runs": [...], "summary": {...} },
  "provider_decision": "Upstash REST path p50=12.1 ms; 0.8× slower than Neon point SELECT p50=15.3 ms; Uncached queue read p50=98.2 ms",
  "_note_upstash_quota": "..."
}
```