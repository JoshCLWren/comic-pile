# Production profile

The production profile is a full-account browser workload derived from the original Chrome HAR captured on July 30, 2026 after the Vercel, Neon, and Upstash migration.

The source HAR contained 198 API requests across roughly 201 seconds. It exercised authenticated startup, queue/history/analytics navigation, rating, rolling, snoozing, manual thread selection, queue movement, a large issue editor, dependency management, stale-thread reactivation, manual die changes, and a final rating.

## What changed from the first profiler

The first implementation created a disposable user, generated three small threads, called `/health` before measuring, and installed its network recorder only after setup. That was a useful smoke test, but it did not preserve the original account shape or cold browser path.

The production profile now:

- requires a Playwright storage-state file for the existing production account;
- installs request recording before the first navigation;
- does not warm the deployment with `/health`;
- refuses to run against a toy account by checking minimum thread and session counts;
- visits the same major browser surfaces as the original session;
- performs real roll, rating, snooze, queue movement, thread-detail, and issue-toggle work;
- reports the original HAR request count and observed/source ratio;
- keeps the legacy dependency-fanout and duplicate-GET regression checks.

It does not commit the source HAR, cookies, access tokens, request bodies, or captured IDs.

## Create storage state

Use a local file that is never committed. The simplest path is to sign in with Playwright and save the authenticated browser context:

```bash
cd frontend
PROD_BASE_URL=https://comic-pile.vercel.app \
  pnpm exec playwright codegen \
  --save-storage=../prod-profile-storage-state.json \
  https://comic-pile.vercel.app
```

Sign in, close the codegen browser, and confirm that `prod-profile-storage-state.json` exists. Treat it like a password. The repository ignores `prod-profile-storage-state*.json`.

## Run

```bash
PROD_BASE_URL=https://comic-pile.vercel.app \
PROD_PROFILE_STORAGE_STATE=../prod-profile-storage-state.json \
  pnpm --filter frontend run test:e2e:prod-profile
```

This workload mutates production state through normal browser actions. Run it only against the intended account and review the generated report afterward.

## Account-shape guardrails

Defaults:

| Check | Default |
| --- | ---: |
| Minimum loaded threads | 100 |
| Minimum loaded sessions | 25 |
| Minimum observed browser API requests | 40 |
| Maximum observed browser API requests | 198 |
| Maximum API duration | 5,000 ms |
| Duplicate GET burst window | 250 ms |
| Legacy per-issue dependency requests | 0 |
| Thread dependency batch requests | at least 1 |
| Failed API responses or transport failures | 0 |

The minimums prevent a fresh disposable account from silently standing in for the real workload. Override them only when intentionally profiling a different mature account:

```bash
PROD_PROFILE_MIN_THREADS=75 \
PROD_PROFILE_MIN_SESSIONS=20 \
PROD_PROFILE_MIN_API_REQUESTS=35 \
PROD_PROFILE_MAX_API_REQUESTS=220 \
PROD_PROFILE_MAX_API_MS=8000 \
PROD_PROFILE_DUPLICATE_WINDOW_MS=150 \
  pnpm --filter frontend run test:e2e:prod-profile
```

## Report

Each run attaches `production-profile.json` with:

- source HAR date, duration, action inventory, and 198-request baseline;
- observed account thread/session counts;
- every normalized browser API request;
- response status and wall-clock duration;
- request ID when present, `Server-Timing`, `X-App-Cache`, and `X-App-DB-Queries` (retired Python middleware diagnostics; native Rust does not emit them);
- median, p95, and maximum latency;
- observed/source request ratio;
- duplicate GET bursts, transport failures, and slow responses.

The report is evidence, not a synthetic pass badge. A large drop in request count is expected when fan-out is removed, but a tiny request count or small-account guard failure means the profile is no longer representative.

## Production deployment is native Rust; Python middleware headers are absent

Production traffic is served by the native Rust ingress (`/api/native_roll.rs`
via Vercel). That binary emits only `X-ComicPile-API-Runtime: rust` and the
JSON body's `build`/`process` identity; it does not run the Python
`PerformanceMiddleware`, so none of `X-Request-ID`, `X-App-Cache`,
`X-App-DB-Queries`, or `Server-Timing` are present on production responses
(since #4740 the retired public bare routes `/health`, `/docs`, `/redoc`,
and `/openapi.json` return Vercel 404s and never start Python). Production
liveness is `GET /api/v2/health`.

Consequences for the production profile report:

- `serverTiming`, `X-App-Cache`, `X-App-DB-Queries` and `X-Request-ID` are expected
  to be absent on native Rust responses. Treat that as the current runtime
  property, not a regression.
- Timing and diagnostics evidence comes from the health body's `build`/`process`
  identity, `X-ComicPile-API-Runtime`, structured native request logs and Vercel
  invocation metadata such as `x-vercel-id`.
- There is no local Python middleware container or Vercel Preview comparison
  environment. Use a disposable native service plus ingress for local profiling.

## Native request logging

Set `RUST_ROLL_LOG` (default `info`) to control structured native tracing. Request
logs include method, status and elapsed milliseconds, not bodies, credentials or
SQL. Investigate repeated high latency with the pool/request timeout settings in
[`OPERATIONAL_HEALTH.md`](OPERATIONAL_HEALTH.md); raising a timeout is not a query
fix.
