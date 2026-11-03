# Production startup diagnostics

ComicPile emits structured process and request timing so a slow first request can be separated into application startup, dependency work, and route execution. The Vercel entry point imports the startup clock before the application factory. It cannot measure Vercel provisioning before Python begins executing. Timing measurements inside the application must not be confused with worker lifetime.

## Cold versus warm

A request is **cold** only when it is the first request handled by the current application process. Later requests in the same process are **warm**. Use the deployment identifier and process-start timestamp to group events from one process.

The process snapshot records:

- one-based request number;
- cold/warm classification;
- process age when the request began;
- whether application startup completed;
- `startup_duration_ms`, the sum of measured import, app-creation and lifespan-startup work;
- `process_to_startup_ms`, elapsed worker lifetime until lifespan completed, including any gaps between phases;
- `process_age_ms`, lifetime at the sampled event, and `startup_cpu_ms`, process CPU consumed between diagnostics import and startup completion;
- `heavy_init_duration_ms`, the deferred database-initialization operation only, versus `heavy_init_process_age_ms`, worker age at heavy-init completion;
- Vercel deployment or commit identifier when available.

Request diagnostics add total route duration, database query count and time, HTTP status, and request ID. Production sanitization removes request bodies, query strings, user/session identifiers, cookies, and authorization headers.

## Reading a slow request

1. Filter deployment logs to `event=application_startup` for the process startup record.
2. Find the first request with `cold_request=true` and correlate it by deployment ID plus `process_started_at_ns`.
3. Compare `startup_duration_ms` (summed application phase spans), `process_to_startup_ms` (worker lifetime) and `startup_cpu_ms`. A large gap between process lifetime and active phase durations is **not** automatically CPU-bound startup. Use phase boundaries and Vercel's invocation metrics to investigate suspension or platform waiting. These clocks cannot prove how long Vercel took before importing the diagnostics module.
4. Heavy initialization is intentionally deferred until a non-probe request. Compare `heavy_init_duration_ms` with request duration, not `heavy_init_process_age_ms`. A process can serve a ping, sit idle, and initialize its database much later. The 2,500 ms readiness budget applies only to the work measured on the ping-ready path.
5. Compare `process_time_ms` and database time inside that first request. `process_time_ms` is elapsed wall time despite its historical name; `cpu_time_ms` is the separate process CPU sample described below.
6. Review the `httpstat` phase breakdown for DNS, TCP, TLS, and other externally visible transport time before attributing latency to application startup. Only the remainder not explained by those phases, measured startup, or measured request work can be treated as pre-application/platform time.
7. Repeat the same path immediately and verify the response marker before treating it as warm (`X-App-Cold-Request: 0`).

A cold request is suspicious when measured application startup work exceeds 1,000 ms or total request duration exceeds the configured slow-request threshold. The startup budget does not fire on worker lifetime or heavy-init age alone. A warm request is suspicious when database duration dominates the request, or when unexplained application time remains after subtracting dependency time.

## Timing fields and CPU attribution

Slow, error, and cold request records carry two independent timings:

- `process_time_ms` — elapsed wall-clock time for the request. The name is historical; it is not CPU. It is preserved for existing log consumers and still drives the latency budgets and `Server-Timing`.
- `cpu_time_ms` — process CPU consumed between the start and end of the request, sampled with `time.process_time()`.

`cpu_time_ms` is a process-wide delta. Under async concurrency it includes work performed for other in-flight requests, so it must not be treated as exclusive per-request attribution, divided by request count, or ranked as if each request owned the whole delta. Use it only to tell a CPU-bound request apart from a request that was mostly waiting on I/O, and use isolated one-at-a-time measurements when per-route CPU attribution is required.

These fields describe a single process. They are not Vercel billed Active CPU: billing also depends on invocation volume, provisioned memory, and cold starts, and Vercel's `group_by=requestPath` counts log events rather than invocations. Route-level CPU attribution needs isolated one-at-a-time measurement; the replay lab tracked in #4277 is the intended source for that evidence.

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

### Request record capture window

Vercel retains runtime logs for **one hour** on the Hobby plan ([runtime log limits](https://vercel.com/docs/logs/runtime)), so slow, cold, and error records must be collected while the deployment is still serving; there is no next-day historical read and no paid retention is enabled for this project. Capture the structured records with the dashboard Logs tab or:

```bash
vercel logs --environment production --query '<event or route>' --since 1h
```

Each log record carries these values as structured `extra` attributes (`request_id`, `method`, `path`, `status_code`, `process_time_ms`, `cpu_time_ms`, `database_queries`, `database_time_ms`, `cold_request`, `deployment_id`); a diagnostic filter on the root log handler appends them to the message text, so they appear in deployment logs even when the hosting platform installs its own handler or formatter. Copy them from the log record for every matching row before the window closes. One `cpu_time_ms` value is a single-process sample covering that request window only; repeat the same request and re-capture to see the spread instead of treating one number as a per-request CPU budget.

Thresholds are diagnostic defaults, not availability guarantees. Adjust `SLOW_REQUEST_THRESHOLD_MS` only after collecting a representative baseline, and never use a higher threshold to hide a regression.
