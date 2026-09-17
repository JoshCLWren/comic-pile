# Production Benchmark Guide for Issue #700

This guide documents how to run the session-read benchmark against production to validate performance budgets for the current-session and History endpoints.

## Prerequisites

- Disposable per-run production account created and cleaned up by the rebuilt
  browser-test suite (blocked by #1664; the obsolete dedicated-account path from
  #832 is no longer a dependency). No long-lived production credentials.
- `scripts/benchmark_session_reads.py` (already merged in PR #721)

## Benchmark Harness

The benchmark harness is a dependency-free Python script that records:
- Elapsed time (ms)
- HTTP status code
- Response payload size (bytes)
- Request ID (X-Request-ID header)
- Cache status (X-App-Cache header)
- Database query count (X-App-DB-Queries header)
- Server timing (Server-Timing header)

## Running the Benchmark

### Against Production (after #1664)

```bash
# Set up environment variables
export PROD_BASE_URL=https://comic-pile.vercel.app
export PROD_BEARER_TOKEN=<token for the disposable per-run account created by the
  #1664 suite helper; the account is deleted after the run, so never reuse a
  token across runs or store it as a long-lived secret>

# Record the deployment identifier for the evidence attachment (Vercel
# deployment ID or the production SHA under test); the harness records base_url
# but not the deployment, and issue #700 requires both cold/warm samples to be
# tied to an explicit deployment.
export PROD_DEPLOYMENT_ID=<vercel deployment id or production SHA>

# Run cold-path measurements (fresh deployment, no prior requests)
# Each endpoint in separate invocation for true first-request evidence
python scripts/benchmark_session_reads.py \
  --base-url "$PROD_BASE_URL" \
  --bearer-token "$PROD_BEARER_TOKEN" \
  --endpoint current \
  --iterations 5 \
  --output production-current-session.json

python scripts/benchmark_session_reads.py \
  --base-url "$PROD_BASE_URL" \
  --bearer-token "$PROD_BEARER_TOKEN" \
  --endpoint history-first \
  --iterations 5 \
  --output production-history-first.json

# For later History page, need a cursor token from first page
# First, get a cursor token:
curl -H "Authorization: Bearer $PROD_BEARER_TOKEN" \
  "$PROD_BASE_URL/api/v1/sessions/?page_size=50" | jq -r '.next_page_token'

# Then run with the cursor:
export LATER_PAGE_TOKEN=<cursor_from_above>
python scripts/benchmark_session_reads.py \
  --base-url "$PROD_BASE_URL" \
  --bearer-token "$PROD_BEARER_TOKEN" \
  --endpoint history-later \
  --later-page-token "$LATER_PAGE_TOKEN" \
  --iterations 5 \
  --output production-history-later.json
```

### Against Local/Staging

```bash
# Start local server
make dev-api

# In another terminal, run benchmark
python scripts/benchmark_session_reads.py \
  --base-url http://localhost:8000 \
  --cookie "refresh_token=<token_from_login>" \
  --endpoint all \
  --iterations 5 \
  --output local-benchmark.json
```

## Interpreting Results

The benchmark output separates:
- **first_observed**: First recorded request (cold-path candidate)
- **steady_state**: Aggregate of subsequent requests (iterations 2-N)
- **all_recorded**: Aggregate of all requests

Attach each JSON report together with its `PROD_DEPLOYMENT_ID` so cold and warm
samples stay tied to the deployment they measured.

Note: `Server-Timing` is currently stripped somewhere on the Vercel deployment
path (see `docs/PRODUCTION_PROFILE.md`); expect `server_timing: null` in
production reports. That is an observed deployment-path limitation, not a
harness failure — correlate application time via `X-Request-ID` against the
structured `Slow HTTP request` warnings and Vercel runtime logs instead.

### Key Metrics to Record

| Metric | Cold Budget Target | Warm Budget Target |
|--------|-------------------|-------------------|
| current-session elapsed_ms | TBD | TBD |
| history-first elapsed_ms | TBD | TBD |
| history-later elapsed_ms | TBD | TBD |
| current-session db_queries | TBD | TBD |
| history-first db_queries | TBD | TBD |
| history-later db_queries | TBD | TBD |
| current-session response_bytes | TBD | TBD |
| history-first response_bytes | TBD | TBD |
| history-later response_bytes | TBD | TBD |

### Cache Status Values

- `hit`: Cache hit
- `miss`: Cache miss
- `not-used`: Cache not used for this request
- `mixed`: Mix of hits and misses
- `write`: Cache write
- `bypass`: Cache bypassed
- `timeout`: Cache operation timed out
- `error`: Cache error

## Establishing Budgets

1. Run at least 5 cold-path measurements (separate deployments or after deployment idle period)
2. Run at least 10 warm-path measurements (steady state)
3. Calculate median, p95, and max for each metric
4. Set budgets at p95 + 20% margin
5. Document in issue #700 and update this guide

## Regression Detection

The benchmark output can be compared against previous runs using:
- `scripts/update_production_performance_history.py` (for browser milestones)
- Custom comparison for API benchmarks

File focused regression issues for any independent failure or budget miss.

## Current Status

- ✅ Benchmark harness merged (PR #721)
- ✅ Query plan optimization merged (PR #730)
- ✅ Structured diagnostics merged (PR #778)
- ✅ Latest-session-action index merged (PR #801)
- ⏳ Blocked by #1664 (disposable per-run accounts via the rebuilt browser-test suite)
- ⏳ Production cold/warm measurements pending
- ⏳ Budget documentation pending
- ⏳ Regression issue filing pending