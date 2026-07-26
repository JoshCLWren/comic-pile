# Railway load-testing harness

`scripts/railway_loadtest.py` is a repeatable HTTP/1.1 load generator for the deployed
ComicPile API. It uses the repository's locked `httpx` development dependency, reuses
connections, excludes warm-up requests from results, records p50/p95/p99 latency, RPS,
status counts, errors, and response bytes, and writes JSON results. Combined profiles also
emit separate summaries for every route, so `/health`, `/api/auth/csrf`, and mixed scenarios
can be compared directly.

The default profile is read-only and unauthenticated:

- `GET /health` — application plus PostgreSQL `SELECT 1`.
- `GET /api/auth/csrf` — closest lightweight application route; no database query.

No credentials are required for the default profile. Authenticated profiles read a bearer
token from an environment variable and never write its value to the result file.

## Control baseline

Run the default safe control against the current production deployment:

```bash
uv run python scripts/railway_loadtest.py \
  --profile control-safe \
  --concurrency 1 \
  --concurrency 2 \
  --concurrency 4 \
  --concurrency 8 \
  --warmup-seconds 10 \
  --duration-seconds 30 \
  --interval-ms 200 \
  --output benchmarks/results/control-$(date -u +%Y%m%dT%H%M%SZ).json
```

The default URL is `https://app-production-72b9.up.railway.app`. Override it with:

```bash
PROD_BASE_URL=https://example.up.railway.app \
uv run python scripts/railway_loadtest.py --profile control-safe
```

`--interval-ms 200` limits each client to approximately five requests per second. Use
`--interval-ms 0` only for an explicitly approved saturation run.

The default schedule is deliberately paced: each client issues one request, waits for its
response, then sleeps for `interval_ms`. Therefore measured RPS is the achieved rate of that
closed-loop client model, not the server's maximum capacity. The JSON result records this
schedule explicitly. `--interval-ms 0` changes to an open-loop-per-client loop and should be
used only for an approved saturation test.

For short harness validation use the `smoke` preset (1/2/4/8 concurrency, 10-second warm-up,
30-second measurement). For scientific runs use the `results` preset (1/2/4/8/16/32,
45-second warm-up, 180-second measurement), then repeat the complete control at least three
times before comparing variants:

```bash
make railway-control-results
```

Run `make railway-control-results` three separate times without deploying or changing
configuration between runs. Before each run, verify `/health`, record the Railway deployment
ID and dashboard resource values, avoid using the application manually, and save the UTC start
and end times. The target uses the `control-results` run-set, so it creates files named
`benchmarks/results/control-results-<timestamp>.json`; it does not select prior smoke or route-
validation files.

The generated `benchmarks/control-environment.json` contains repository-derived metadata and
explicitly records unavailable Railway values as `null`. Dashboard-only values can be supplied
without changing the code:

```bash
RAILWAY_DEPLOYMENT_ID=... \
RAILWAY_REGION=... \
RAILWAY_CPU_ALLOCATION=... \
RAILWAY_MEMORY_ALLOCATION=... \
RAILWAY_REPLICA_COUNT=... \
RAILWAY_AUTOSCALING_STATUS=... \
DATABASE_REGION=... \
DATABASE_PLAN=... \
make railway-control-results
```

The result embeds the same redacted metadata object. Database identity is a SHA-256 digest of
the configured database URL; database URLs, credentials, tokens, and cookies are never saved. The
deployment URL is recorded in `run.base_url`.

### Request-level failure diagnostics

Use the isolated c32 preset for pressure-boundary diagnostics. It keeps the current two-route,
45-second warm-up, 180-second measurement, 200 ms paced schedule and 10-second timeout, but
does not belong to the ordinary `control-results` run set:

```bash
make railway-control-c32-diagnostic
```

Run the target three separate times. Each result is named
`benchmarks/results/control-c32-diagnostic-<timestamp>.json`; optional failure details are also
written as timestamped NDJSON. Every unsuccessful request includes a millisecond UTC timestamp,
route, concurrency, virtual-client ID, sequence number, generated `X-Benchmark-Request-ID`,
exception/status details, elapsed time, timeout, safe response snippets, and allowlisted response
headers. Successful requests remain aggregated. Each concurrency result also records exact warm-up
and measurement window boundaries.

### Recorded control run

The first corrected control run was recorded on 2026-07-25 against
`https://app-production-72b9.up.railway.app` using CPython 3.14.2, HTTP/1.1, a 10-second
warm-up, a 30-second measurement window per concurrency level, and 200 ms per-client
request spacing. All 1,546 measured requests returned HTTP 200 with zero transport errors.

| Concurrency | Requests | RPS | p50 | p95 | p99 |
|---:|---:|---:|---:|---:|---:|
| 1 | 103 | 3.41 | 87.14 ms | 99.63 ms | 303.55 ms |
| 2 | 207 | 6.89 | 87.72 ms | 98.48 ms | 114.91 ms |
| 4 | 415 | 13.70 | 86.44 ms | 106.64 ms | 191.80 ms |
| 8 | 821 | 27.15 | 86.81 ms | 130.97 ms | 196.14 ms |

Raw result: `benchmarks/results/control-20260725T182700Z.json`. These are control
measurements for this exact client protocol, not a claim about maximum Railway capacity;
Railway CPU/memory, region, database placement, and production traffic were not captured
in the repository result.

A route-separated c4 validation run is also recorded at
`benchmarks/results/control-route-separated-c4-20260725T184000Z.json`. It produced:

| Route | Requests | RPS | p50 | p95 | p99 |
|---|---:|---:|---:|---:|---:|
| `/api/auth/csrf` | 104 | 6.82 | 82.78 ms | 89.02 ms | 203.17 ms |
| `/health` | 105 | 6.88 | 89.06 ms | 102.45 ms | 196.05 ms |

This is a validation sample, not an additional repeated scientific control.

## Authenticated read profile

Do not pass tokens on the command line. Supply one through the environment:

```bash
export RAILWAY_BENCHMARK_TOKEN='redacted-bearer-token'
uv run python scripts/railway_loadtest.py \
  --profile authenticated-read \
  --concurrency 1 \
  --concurrency 2 \
  --concurrency 4 \
  --warmup-seconds 30 \
  --duration-seconds 300 \
  --token-env RAILWAY_BENCHMARK_TOKEN \
  --output benchmarks/results/control-authenticated-$(date -u +%Y%m%dT%H%M%SZ).json
```

The authenticated profile currently requests `GET /api/threads/`. It should only be used
with a frozen benchmark user/data set. The harness does not create or mutate data.

## Cold-start and warm-steady-state protocol

The harness cannot redeploy Railway. Run cold-start measurements as a separate procedure:

1. Record commit SHA, Railway deployment ID, image digest, region, CPU, memory, replica count,
   `WEB_CONCURRENCY`, and database identity.
2. Deploy or restart the control image through the approved Railway workflow.
3. Poll `GET /health` once per second until HTTP 200; record readiness time and restart events.
4. Send one first authenticated request separately, if credentials are available.
5. Run the harness warm-up and measured phases.
6. Capture Railway CPU/memory graphs and application logs for the same UTC window.

For runtime comparisons, use:

```text
Control -> Experiment A -> Control -> Experiment B -> Control -> Experiment C -> Control
```

Each control must be a fresh deployment of the control image. Keep database, region,
resources, workers, event loop, parser, logging, client location, and request mix fixed.

## Result format

Each result contains:

- `schema_version`
- deployment URL and route profile
- route paths and concurrency matrix
- warm-up, duration, timeout, interval, HTTP/2, and user-agent settings
- whether a token was supplied, never the token itself
- Python implementation/platform metadata
- per-concurrency request count, RPS, p50/p95/p99, status counts, error count, and bytes
- per-route versions of the same statistics under each concurrency result
- redacted control metadata, including run-set and scheduling model
- versioned per-concurrency failure diagnostics and exact phase windows

Keep result files private if they contain production timing or route information. Do not
include credentials or database URLs in them.

## Comparing repeated controls

After at least two compatible `control-results` runs exist:

```bash
make railway-control-compare
```

The comparison groups combined and route-level results by route, concurrency, scheduling
mode, interval, warm-up, and measurement duration. It reports statistics across each run's
reported RPS/p50/p95/p99 values. It does not merge raw percentile samples into a fabricated
global percentile.

The comparison flags nonzero errors, RPS coefficient of variation above 10%, p95 ranges above
15% of median p95, missing routes/concurrency levels, and incompatible metadata. It rejects
incompatible runs unless `--allow-incompatible` is explicitly supplied. Use the Make target
to select only the intended set:

```bash
make railway-control-compare
```

No performance conclusion should be based on one run. The control must be repeated between
later deployment experiments using the same route mix, schedule, resources, database, region,
and client location. A later experiment is ready only when control variability is understood
well enough to distinguish deployment effects from Railway or network variance.

For the isolated c32 diagnostic, compare only its three files:

```bash
make railway-control-c32-compare
```

The diagnostic comparison reports failures by route and exception type, failure timestamps and
request IDs, timeout counts, non-2xx status distributions, maximum latency, and p95 range. Its
`--run-set control-c32-diagnostic` check rejects accidental inclusion of ordinary control files.

## Safety boundaries

- Default profile is GET-only and unauthenticated.
- The harness has no write profile.
- Do not load-test login, roll, rate, queue mutation, session mutation, imports, exports, or
  bug-report routes against production.
- Use an isolated Railway service and database for write-path tests.
- Record production traffic, health probes, restarts, autoscaling, region, and database
  placement before interpreting results.
