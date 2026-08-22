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

## Redis Cloud RESP lookup (GCP us-central1, preliminary)

A free-tier Redis Cloud database (`redis-12024.c280.us-central1-2.gce.cloud.redislabs.com`,
GCP Iowa — the region nearest Vercel's `cle1`/Chicago) was measured with warm sequential
commands over the plain RESP protocol (TLS is disabled on this test database). **Vantage:
developer workstation, not the deployed function** — these numbers include a residential ISP
hop and are therefore upper bounds; in-region numbers must come from a deployed timing route.

| Command | min | median | p95 | max |
| ------- | ---: | ---: | ---: | ---: |
| GET (n=200, 512B value) | 28.18 ms | 29.11 ms | 31.22 ms | 34.34 ms |
| SET (n=50, 512B value) | 28.69 ms | 29.07 ms | 34.03 ms | 34.98 ms |

Interpretation: nearly all of the ~29 ms is workstation-to-Iowa network transit. From inside
`cle1`, the same hop is expected to land in single-digit milliseconds; the decisive comparison
is against Neon's measured 3.85 ms median from the function itself.

## Decision framing

- If Upstash same-region lands near 1–2 ms, Redis wins on raw latency but adds a vendor,
  command metering, and quota risk.
- At ~4 ms per hit, Postgres caching already removes the dominant cost of uncached requests
  while adding zero vendors and transactional invalidation.
