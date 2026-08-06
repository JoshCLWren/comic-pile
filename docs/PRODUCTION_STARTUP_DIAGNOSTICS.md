# Production startup diagnostics

ComicPile emits structured process and request timing so a slow first request can be separated into startup, dependency, and route work.

## Cold versus warm

A request is **cold** only when it is the first request handled by the current application process. Later requests in the same process are **warm**. Use the deployment identifier and process-start timestamp to group log events from the same invocation.

The process snapshot records:

- one-based invocation number;
- cold/warm classification;
- process age when the request began;
- whether application startup completed;
- total startup duration;
- Vercel deployment or commit identifier when available.

Request diagnostics add total route duration, database query count and time, cache outcome and time, HTTP status, and request ID. Authentication and session bootstrap routes can therefore be filtered by path without logging tokens, cookies, query parameters, or user data in production.

## Reading a slow request

1. Filter structured logs to the request ID.
2. Check `cold_start`. A warm request points away from process initialization.
3. Compare `startup_duration_ms` with `process_time_ms`.
4. Compare database and cache duration with total route duration.
5. Group by deployment ID before comparing releases.

A cold request is suspicious when startup exceeds 1,000 ms or total request duration exceeds the configured slow-request threshold. A warm request is suspicious when database or cache duration dominates the request, or when unexplained application time remains after subtracting dependency time.

Thresholds are diagnostic defaults, not availability guarantees. Adjust `SLOW_REQUEST_THRESHOLD_MS` only after collecting a representative baseline, and never use a higher threshold to hide a regression.
