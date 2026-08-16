# August 2026 ComicPile performance benchmark findings

## Purpose

Record the controlled measurements that led to the current Vercel + Neon optimization work so future performance changes have a concrete baseline.

## Measurements

### Home Debian host against production Neon

Authenticated ComicPile ran in Docker against the production Neon database.

`GET /api/v1/roll/bootstrap`:

- single request: ~1.76 s
- sequential 20 requests: avg ~1.03 s, p50 ~0.81 s, p95 ~1.50 s
- concurrency 5: avg ~0.93 s, p50 ~0.79 s, p95 ~1.42 s
- concurrency 10: avg ~1.38 s, p50 ~1.41 s, p95 ~2.10 s

Database microbenchmarks from the same container:

- new asyncpg connection + `SELECT 1`: p50 ~408 ms, p95 ~427 ms
- persistent asyncpg connection + `SELECT 1`: p50 ~34 ms, p95 ~35 ms

The host had roughly 62 GiB RAM and substantial CPU available, so these results are not explained by memory starvation.

### GCP `e2-micro`

A temporary GCP `e2-micro` in `us-east1` ran the same FastAPI application against Neon.

Representative authenticated `roll/bootstrap` results:

- single request: ~1.33 s
- sequential p50: ~0.71 s
- concurrency 5 p50: ~0.98 s
- concurrency 10 p50: ~1.47 s

The tiny GCP VM and the much larger home host produced broadly similar hot-path latency.

### Vercel

Warm Vercel requests were substantially faster than either always-on experiment. Earlier controlled warm bootstrap observations were roughly in the low hundreds of milliseconds rather than the ~0.8–1.5 s range seen from hosts with larger network RTT to Neon.

## Conclusions

1. Raw Python compute is not the dominant hot-path bottleneck.
2. Database network round-trip count is a major latency amplifier.
3. Physical connection creation is very expensive compared with reusing an existing connection.
4. Query consolidation and connection-pool reuse are higher-value than simply buying more CPU or RAM.
5. Vercel remains the preferred runtime to tune because its warm path is already the fastest measured topology.
6. Performance work should preserve current memory allocation and prove improvements with before/after measurements.

## Related work

- `docs/API_DATABASE_ROUND_TRIP_AUDIT.md`
- #1254 through #1261
- #687 performance roadmap
- #834 production startup/page-load tracking
