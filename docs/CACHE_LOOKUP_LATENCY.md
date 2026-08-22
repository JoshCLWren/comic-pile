# Cache lookup latency comparison

Updated: 2026-08-22

Feeds the provider decision memo (see `docs/CACHE_REENABLE_DECISION.md`). Question: is a
Postgres-backed cache lookup fast enough compared with an external Redis service?

## Production Postgres point-read (measured)

Method: the deployed dependency-health endpoint executes exactly one trivial query
(`SELECT 1`) per request against production Neon; its real database time is reported in the
`Server-Timing` response header (`db;dur`) by request logging middleware. 40 samples collected
over ~10 seconds on 2026-08-22.

| Stat   | Single query time |
| ------ | ----------------- |
| min    | 3.16 ms           |
| median | 3.85 ms           |
| p95    | 6.18 ms           |
| max    | 7.20 ms           |

Interpretation: a KV-shaped indexed read on Neon costs about **4 ms** in production. This is
the realistic upper bound for a Postgres-cache hit; cached values avoid recomputing expensive
queue/continuity queries entirely.

## Upstash REST lookup (pending)

The Upstash free-tier database was quota-hard-stopped at measurement time (resets
approximately 2026-08-28), so no comparable REST round-trip could be captured. Re-run
`scripts/benchmark_cache_lookup_latency.py --samples 200` after the reset with
`UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` (or legacy `KV_REST_API_*`) set, ideally
via a temporary timing route deployed in-region so both sides share one vantage.

## Decision framing

- If Upstash same-region lands near 1–2 ms, Redis wins on raw latency but adds a vendor,
  command metering, and quota risk.
- At ~4 ms per hit, Postgres caching already removes the dominant cost of uncached requests
  while adding zero vendors and transactional invalidation.
