# Operational health endpoints

ComicPile exposes separate bounded endpoints so monitoring can distinguish process startup from dependency availability.

## Endpoint selection

- `GET /api/v1/health/live` confirms only that the FastAPI process can serve a request. It does not query Neon or Upstash and is the correct liveness probe.
- `GET /api/v1/health/dependencies` checks Neon and Upstash independently with a two-second timeout per dependency. Use it for dependency alerts and diagnosis.
- `GET /api/v1/health/warmup` exercises the same cheap, read-only database and cache path used by dependency monitoring. Use it when intentionally warming an idle deployment.
- `GET /api/v1/health/cache-quota` reports the monthly cache command budget snapshot (issue #1751): `status` (`ok` / `near-limit` / `over-budget`), `observed_commands`, `budget`, `remaining`, `usage_ratio`, `alerted`, and `throttling`. It is purely in-process — no database or cache connection and no alert side effects — so monitoring can poll it freely to watch for the near-limit band before the hard budget is reached. See `docs/CACHE_COMMAND_BUDGET.md` for the guardrail rules.
- `GET /api/health` remains the hidden legacy database health boundary for existing callers.

Set `HEALTH_CHECK_TOKEN` in production and send it as `X-Health-Token` to access the detailed dependency, warm-up, and cache-quota endpoints. Missing or invalid tokens receive a generic 404 so operational detail is not advertised. The liveness endpoint remains public because it contains no infrastructure detail.

## Response semantics

- `200 healthy`: database and cache both responded within their bounds.
- `207 degraded`: the database is healthy but the cache is unavailable or timed out. ComicPile can continue through its cache fallback path.
- `503 unhealthy`: the database is unavailable or timed out.

Responses contain only status and duration fields. They never include connection strings, hostnames, credentials, exception text, user data, or queried records.

Structured logs emit the aggregate status, each dependency status, each dependency duration, and total duration. Compare these fields with request-level timing to separate function startup latency from Neon, Upstash, and route execution latency.

## Regression thresholds

Investigate repeated database or cache probe durations above 500 ms while warm. A timeout always warrants investigation. Cold invocations may be slower, but the endpoint remains bounded and identifies the dependency responsible rather than allowing one hung provider to consume the whole monitoring request.

## Performance telemetry and GitHub filing

**Automatic performance-to-GitHub issue filing is disabled by default** (issue #3726).
`PERF_ALARM_GITHUB_ISSUES_ENABLED=false` prevents automatic GitHub lookups,
comments, claims, and issue creation for request samples and readiness-critical
coroutine timeouts, including severe events. It does not disable diagnostics,
logging, request warnings, error-level budget violations, startup timing, DB query
counts/execution time, timeout enforcement, or health monitoring. Startup
readiness samples already log separately without filing. Existing
`perf_alarm_counters` and `perf_alarm_incidents` rows are preserved.

Treat the `Server-Timing: app;dur=...` value as the **request middleware's
total span**, not an isolated route/business-logic timer. The `db;dur` metric
measures instrumented SQL execution only; it does not include waiting for a
connection, middleware, other awaits, or platform overhead outside the measured
span. The remainder (`app;dur - db;dur`) is **unattributed**, not proof
that application code is slow or that the platform is responsible. Compare
warm/cold classification, DB queries and execution time, request/deployment
identifiers, process/startup diagnostics, actual error/timeout evidence, and
repeated requests before assigning an owner.

Actionable investigations include reproducible warm regressions with supporting
timing breakdowns, an unusual query count or high measured DB execution time,
hard timeouts, and user-visible outages. File and triage these as focused,
human-reviewed GitHub issues with evidence of recurrence or impact. A single
marginal overrun of the 1000 ms budget is not itself a factory task. Hard failures
remain visible through logs and health/monitoring surfaces when filing is off.

**Optional legacy opt-in:** Set `PERF_ALARM_GITHUB_ISSUES_ENABLED=true` only
after explicitly accepting the older automatic-filing behavior. When enabled:

- **Fingerprint.** One open issue per `kind + method + route template`. Warm/cold,
  workload class and dominant phase are evidence, not distinct issues. Legacy
  hashes and method/route identity are checked for reuse.
- **Durable counters.** Warm hits and incident identity are shared in Postgres.
- **Never file under budget.** Request timings at or below 1000 ms do not file;
  500-999 ms warnings are still logged.
- **Cold/startup.** Cold requests and startup-readiness samples never file.
  Hard startup failures log at WARNING.
- **Daily breach threshold.** `PERF_ALARM_DAILY_BREACH_THRESHOLD` defaults to 3
  warm over-budget hits per route per UTC day (valid 1-100). Closed regressions
  require the same threshold.
- **Comment throttle.** At most one comment per fingerprint per hour.
- **Coroutine timeouts.** Readiness-critical coroutine hard timeouts are an
  **immediate filing exception**, bypassing the daily threshold when opt-in is
  enabled. They still raise/log normally with filing disabled.

Opt-in can again produce noisy, high-priority factory issues on repeated threshold
breaches; it is not a recommended substitute for investigating performance.
The existing 500 ms warning, 1000 ms request-violation, and startup hard-deadline
budgets are unchanged by this switch.
