# Production startup diagnostics

ComicPile emits structured process and request timing so a slow first request can be separated into application startup, dependency work, and route execution. The Vercel entry point imports the startup clock before the application factory, which also lets us distinguish time spent before ComicPile user code starts from time spent inside the app.

## Cold versus warm

A request is **cold** only when it is the first request handled by the current application process. Later requests in the same process are **warm**. Use the deployment identifier and process-start timestamp to group events from one process.

The process snapshot records:

- one-based request number;
- cold/warm classification;
- process age when the request began;
- whether application startup completed;
- total measured startup duration;
- Vercel deployment or commit identifier when available.

Request diagnostics add total route duration, database query count and time, cache outcome and time, HTTP status, and request ID. Production sanitization removes request bodies, query strings, user/session identifiers, cookies, and authorization headers.

## Reading a slow request

1. Filter deployment logs to `event=application_startup` for the process startup record.
2. Find the first request with `cold_request=true` and correlate it by deployment ID plus `process_started_at_ns`.
3. Compare `startup_duration_ms` with the external time-to-first-byte captured by the timing script.
4. Compare `process_time_ms`, database time, and cache time inside that first request.
5. Review the `httpstat` phase breakdown for DNS, TCP, TLS, and other externally visible transport time before attributing latency to application startup. Only the remainder not explained by those phases, measured startup, or measured request work can be treated as pre-application/platform time.
6. Repeat the same path immediately and verify the response marker before treating it as warm (`X-App-Cold-Request: 0`).

A cold request is suspicious when measured application startup exceeds 1,000 ms or total request duration exceeds the configured slow-request threshold. A warm request is suspicious when database or cache duration dominates the request, or when unexplained application time remains after subtracting dependency time.

## Reproduced baseline from 2026-08-06

A controlled five-minute idle test reproduced the production delay twice:

- potential cold `GET /`: 8.493 s total;
- subsequent `GET /`: 0.261 s total;
- subsequent `GET /openapi.json`: 0.651 s total;
- independent cold `GET /`: 8.546 s TTFB / total;
- independent subsequent `GET /`: 0.235 s TTFB / 0.236 s total.

The cold root response reported zero application database queries, so that observed eight-second delay was not route-level database work. Historical captures that predate `X-App-Cold-Request` should not be relabeled warm unless the process identity or an equivalent marker proves it.

## Repeatable capture

From the repository root with Vercel CLI 48.9.0+ authenticated to ComicPile and the standalone `httpstat` executable available on `PATH`, run:

```bash
scripts/capture-production-startup-timing.sh
```

The script writes a bounded artifact containing portable timestamps and `vercel httpstat` output for a potential-cold root request and two potential-warm follow-ups. Use the captured `X-App-Cold-Request` response header to classify each request and `X-Request-ID` to correlate it with application logs. It does not print response bodies, credentials, environment variables, or user data.

Thresholds are diagnostic defaults, not availability guarantees. Adjust `SLOW_REQUEST_THRESHOLD_MS` only after collecting a representative baseline, and never use a higher threshold to hide a regression.
