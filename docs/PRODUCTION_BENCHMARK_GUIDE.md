# Production Benchmark Guide

Reference for collecting and interpreting session-read performance evidence
for issue #700.

## Prerequisites

1. Issue #832 must be resolved (dedicated production E2E account and secrets).
2. The benchmark harness (`scripts/benchmark_session_reads.py`) is dependency-free
   and runs against any deployment with `urllib` only.

## Running benchmarks

### Current session (cold first)

```bash
python scripts/benchmark_session_reads.py \
  --base-url https://<production-host> \
  --bearer-token <token> \
  --endpoint current \
  --iterations 10 \
  --output benchmark-current.json
```

### History first page (cold first)

```bash
python scripts/benchmark_session_reads.py \
  --base-url https://<production-host> \
  --bearer-token <token> \
  --endpoint history-first \
  --iterations 10 \
  --output benchmark-history-first.json
```

### History later page

```bash
python scripts/benchmark_session_reads.py \
  --base-url https://<production-host> \
  --bearer-token <token> \
  --endpoint history-later \
  --later-page-token <cursor> \
  --iterations 10 \
  --output benchmark-history-later.json
```

### All endpoints in one run

```bash
python scripts/benchmark_session_reads.py \
  --base-url https://<production-host> \
  --bearer-token <token> \
  --endpoint all \
  --iterations 10 \
  --output benchmark-all.json
```

## Cold vs. warm distinction

The harness records the **first observed** request separately from subsequent
**steady-state** requests. Cold evidence requires external control:

- **Cold (first-observed):** Restart the deployment or wait long enough for
  any warm state to expire, then run a fresh invocation. Use `--endpoint` to
  isolate one endpoint per invocation for clean cold-path evidence.
- **Warm (steady-state):** After the first request, subsequent iterations
  represent steady-state behavior with the same connection/session state.

## Local baseline reference

Baseline measured on 2026-08-14 against a local test database (7 sessions,
25 threads, 24 events, PostgreSQL 16, no caching enabled).

### Current session (`/api/v1/sessions/current/`)

| Metric | Cold (first observed) | Warm (steady-state median) |
|---|---|---|
| Total duration | 44.92 ms | 3.10 ms |
| DB queries | 18 | 2 |
| Response bytes | 311 | 311 |
| App time | 41.22 ms | 2.36 ms |
| DB time | 15.65 ms | 0.50 ms |

### History first page (`/api/v1/sessions/?page_size=50`)

| Metric | Cold (first observed) | Warm (steady-state median) |
|---|---|---|
| Total duration | 16.10 ms | 4.92 ms |
| DB queries | 5 | 2 |
| Response bytes | 279 | 279 |
| App time | 12.10 ms | 3.76 ms |
| DB time | 2.92 ms | 0.70 ms |

## Budget thresholds (local reference)

These are local reference thresholds. Production budgets should be established
from actual production evidence after #832 is resolved.

| Endpoint | Metric | Cold budget | Warm budget |
|---|---|---|---|
| current-session | Total duration | < 200 ms | < 50 ms |
| current-session | DB queries | < 25 | < 5 |
| current-session | Response bytes | < 5 KB | < 5 KB |
| history-first | Total duration | < 200 ms | < 50 ms |
| history-first | DB queries | < 10 | < 5 |
| history-first | Response bytes | < 50 KB | < 50 KB |

## Evidence format

Each benchmark run produces a JSON report with:

- `first_observed`: single-sample evidence for the first request
- `steady_state`: aggregated statistics (min/median/max/mean) for subsequent requests
- `all_recorded`: aggregate across all samples including first observed
- Per-sample: `elapsed_ms`, `status`, `response_bytes`, `request_id`,
  `app_cache`, `db_queries`, `server_timing`

## Regression detection

Payload size regression: compare `response_bytes` across deploys. The current
baseline shows consistent 311 bytes for current-session and 279 bytes for
history-first (small seed dataset). Production payload sizes will be larger.

DB query count regression: compare `db_queries` in steady-state. The bounded
query pipeline should keep queries to 2 per request for both endpoints in
steady state.

## Related PRs

- PR #721: repeatable authenticated benchmark harness
- PR #730: consolidated History events, bulk-loaded active-thread metadata,
  bounded current-session selection
- PR #778: structured successful-read diagnostics
- PR #801: deterministic latest-session-action index
