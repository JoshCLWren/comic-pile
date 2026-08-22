# Cache lookup latency: Upstash REST vs Neon point SELECT

Updated: 2026-08-22  
Script: `scripts/benchmark_cache_latency.py`  
Run command (from Vercel region, e.g. a one-shot serverless function or `vercel run`):

    DATABASE_URL=postgresql://... \
    UPSTASH_REDIS_REST_URL=https://... \
    UPSTASH_REDIS_REST_TOKEN=... \
    VERCEL_BASE_URL=https://comic-pile.vercel.app \
    VERCEL_BEARER_TOKEN=... \
        python scripts/benchmark_cache_latency.py \
            --iterations 30 \
            --warmups 3 \
            --location "vercel:iad1" \
            --output docs/CACHE_LOOKUP_LATENCY_2026-08.json

Issue: #1782

## Quota context

Upstash Redis free-tier REST quota is exhausted.  The automated quota pause is
expected to lift on or before approximately 2026-08-28.  The benchmark script
handles this gracefully: any HTTP 429 response is recorded as `"status":
"quota_blocked"` rather than aborting, so the Neon and uncached-queue paths can
still be measured independently.

Until the reset, the **Neon point SELECT** and **uncached queue read** rows
below are the only live measurements.  The **Upstash REST GET** row is recorded
with the exact observed quota-blocked pattern so a post-reset run can be
compared directly.

## Measurements

| Path | Samples | Min (ms) | Median (ms) | P95 (ms) | Max (ms) | Mean (ms) | Status |
|---|---|---|---|---|---|---|---|
| Upstash REST GET | 0 | — | — | — | — | — | `quota_blocked` (HTTP 429 quotaหมด) |
| Neon point SELECT (KV table) | 0 | — | — | — | — | — | *Awaiting run* |
| Uncached queue read (`/api/v1/sessions/current/`) | 0 | — | — | — | — | — | *Awaiting run* |

"0 samples" means: no successful samples were collected in the pre-reset
window.  A post-reset run will populate these cells with the actual measured
distribution.  Re-run the script with the same `--iterations 30 --warmups 3`
flags to fill the table.

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

**Hypothesis (to be verified after quota reset):**

The raw Upstash REST hop should outperform a Neon point SELECT when measured
from the same Vercel region, because Upstash is an in-memory edge cache at a
colocation that is likely nearer to Vercel's `iad1` region than Neon's GCP
`us-east1`.  The p50 delta determines whether caching is worth the 350 000
command/month budget documented in `docs/CACHE_COMMAND_BUDGET.md`.

Once both samples are available the decision rule is:

- **Upstash REST p50 < 2× Neon p50** → Upstash is meaningfully faster; re-enable
  gate in `docs/CACHE_REENABLE_DECISION.md` can proceed when command-rate
  evidence is also in range.
- **Upstash REST p50 ≥ 2× Neon p50, or Neon p50 ≤ 3 ms** → Neon point reads
  are not meaningfully slower; the re-enable gate can consider Enabling
  `REDIS_URL` against a local or managed Redis instead, or accept that
  the per-request overhead justifies keeping the cache disabled.
- **Either path shows high variance (p95 / p50 > 5×)** → investigate network
  instability before declaring a stable default.

The uncached queue read baseline (path 3) is required context: if path 1 and
path 2 are both sub-millisecond but path 3 is 100 ms, caching only helps when
the cached object is large or the uncached cache-miss cost is proportionally
significant at the application layer.

## Re-run procedure

After the Upstash quota resets (target: 2026-08-28 or earlier):

1. Confirm quota restored by running `python scripts/benchmark_cache_latency.py
   --iterations 1 --warmups 0` and verifying `"status": "ok"` in the
   `upstash_rest_get` section.
2. Run the full benchmark:
   `python scripts/benchmark_cache_latency.py --iterations 30 --warmups 3
   --location "vercel:iad1" --output docs/CACHE_LOOKUP_LATENCY_2026-08.json
3. Replace the placeholder numbers in the summary table above with the values
   from the JSON file.
4. Update the "Provider decision memo" section with the measured ratio and a
   concrete action on `docs/CACHE_REENABLE_DECISION.md`.

## Related documents and code

- `docs/CACHE_REENABLE_DECISION.md` – the live re-enable gate this benchmark feeds
- `docs/CACHE_COMMAND_BUDGET.md` – 350 000 command/month budget constraint
- `app/cache.py` – `UpstashCache`, circuit breaker, `@cached` decorator
- `app/cache_generation.py` – generation-namespace invalidation (the atomic
  `INCR` that makes all prior generation keys unreachable without a SCAN)
- `scripts/benchmark_session_reads.py` – existing HTTP performance harness
- `scripts/pool_benchmark.py` – database connection-pool microbenchmarks

## JSON output schema (version 1)

```jsonc
{
  "schema_version": "1",          // bump on any structural change
  "measured_from": "vercel:iad1", // deployment vantage identifier
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