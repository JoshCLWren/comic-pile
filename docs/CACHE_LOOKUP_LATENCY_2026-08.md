# Cache lookup latency: Upstash REST vs Neon point SELECT

Updated: 2026-09-05  
Script: `scripts/benchmark_cache_latency.py`  
Preferred vantage: Vercel region `cle1` (`vercel.json` `regions`).  
Measurement workflow: `.github/workflows/cache-latency-benchmark.yml` (`workflow_dispatch` or push of the script/workflow). That job runs on `ubuntu-latest` and records `measured_from: github-actions:ubuntu-latest` when a same-region `cle1` runner is not available. The decision rule compares Upstash and Neon from the same vantage, so a same-host ratio is still valid.

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
The 2026-09-05 measurement run did not receive HTTP 429; Upstash was skipped
because production credentials were not decryptable (see below), not because
quota was still blocked.

## Measurements

Committed JSON: `docs/CACHE_LOOKUP_LATENCY_2026-08.json`  
Workflow run: GitHub Actions `Cache Latency Benchmark` on 2026-09-05  
Vantage: `github-actions:ubuntu-latest` (preferred `vercel:cle1` not available
in this runner). Iterations 30, warmups 3.

| Path | Samples | Min (ms) | Median (ms) | P95 (ms) | Max (ms) | Mean (ms) | Status |
|---|---|---|---|---|---|---|---|
| Upstash REST GET | 0 | — | — | — | — | — | skipped: Vercel `KV_REST_API_*` values pulled as `[SENSITIVE]`; no GitHub `UPSTASH_REDIS_REST_*` secrets |
| Neon point SELECT (KV table) | 30 | 115.849 | 143.303 | 151.812 | 152.833 | 141.518 | ok |
| Uncached queue read (`/api/v1/sessions/current/`) | 0 | — | — | — | — | — | skipped: no `VERCEL_BEARER_TOKEN` |

An earlier same-vantage Neon run landed at p50=569.314 ms (also 30 ok samples).
That colder connect-included hop is recorded here as context; the committed
JSON is the later 143.303 ms distribution. Both are far above the 3 ms
"Neon already fast" threshold. Neon p95/p50 on the committed run is 1.06×
(stable; not an investigate signal).

`provider_recommendation()` cannot run until Upstash p50/p95 exist. Neon
alone does not flip the production provider.

### Operator steps to finish the Upstash row

The Deploy Production `VERCEL_TOKEN` can list production env **key names**
(`KV_REST_API_URL`, `KV_REST_API_TOKEN`, `KV_REST_API_READ_ONLY_TOKEN`,
`REDIS_URL`) but `vercel pull` writes `[SENSITIVE]` for those values. Native
`UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` are **absent** from
Vercel production env. Do not invent or commit the values.

Josh should do one of the following, then re-run **Cache Latency Benchmark**:

1. Add GitHub Actions secrets `UPSTASH_REDIS_REST_URL` and
   `UPSTASH_REDIS_REST_TOKEN` (REST URL + token from the Upstash / Vercel KV
   console). The workflow already reads those secret names.
2. Or grant the deploy token permission to decrypt production env and confirm
   `vercel pull --environment=production` writes real `KV_REST_API_URL` values
   rather than `[SENSITIVE]`.
3. Optional: `UPSTASH_EMAIL` + `UPSTASH_API_KEY` GitHub secrets so
   `make cache-usage` can include provider month-to-date commands.
4. Optional: a session bearer as `VERCEL_BEARER_TOKEN` if the uncached queue
   path should be measured.

`REDIS_URL` is present in production env but is the RESP/local path. Do not
use it for this REST comparison; production must not enable
`CACHE_LOCAL_REDIS_DEV`.

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

The go/no-go ruling for the production provider lives in
`CACHE_PROVIDER_DECISION_2026-08.md` (issue #2216): **Postgres**, with remote
Redis re-enable marked **NEED MORE DATA**. The command census is a GO (1,990
projected commands/month). Upstash REST p50 is still missing, so
`provider_recommendation()` cannot run. The rule itself is unchanged:

**Hypothesis (still unverified — Upstash row empty):**

The raw Upstash REST hop should outperform a Neon point SELECT when measured
from the same Vercel region, because Upstash is an in-memory edge cache at a
colocation that is likely nearer to Vercel's `cle1` region than Neon's GCP
`us-east1`.  The p50 delta determines whether caching is worth the 350 000
command/month budget documented in `docs/CACHE_COMMAND_BUDGET.md`.

Once both samples are available the decision rule is:

- **Upstash REST p50 < 2× Neon p50** → Upstash is meaningfully faster; re-enable
  gate in `docs/CACHE_REENABLE_DECISION.md` can proceed when command-rate
  evidence is also in range.
- **Upstash REST p50 ≥ 2× Neon p50, or Neon p50 ≤ 3 ms** → Neon point reads
  are not meaningfully slower; staying on the Postgres provider is justified.
- **Either path shows high variance (p95 / p50 > 5×)** → investigate network
  instability before declaring a stable default.

The uncached queue read baseline (path 3) is required context: if path 1 and
path 2 are both sub-millisecond but path 3 is 100 ms, caching only helps when
the cached object is large or the uncached cache-miss cost is proportionally
significant at the application layer.

## Re-run procedure

1. Supply decryptable Upstash REST credentials (GitHub Actions secrets
   `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN`, or a Vercel token
   that can decrypt `KV_REST_API_*`).
2. Re-run **Cache Latency Benchmark** (`workflow_dispatch`) or:
   `python scripts/benchmark_cache_latency.py --iterations 30 --warmups 3
   --location "vercel:cle1" --redact --output docs/CACHE_LOOKUP_LATENCY_2026-08.json`
3. Replace the Upstash row in the summary table from the redacted JSON.
4. Feed both medians into `provider_recommendation()` and update
   `CACHE_PROVIDER_DECISION_2026-08.md` plus `CACHE_REENABLE_DECISION.md`.

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