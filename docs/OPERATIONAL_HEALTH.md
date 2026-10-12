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

## Performance alarm

Production request timings can open factory GitHub issues through `app/services/performance_issue_service.py` (issues #3245 and #3552). The alarm is noise-controlled:

- **Fingerprint.** One open issue per `kind + method + route template`. Warm/cold, workload class (db-heavy / app-heavy / mixed), and dominant phase are sample evidence, not separate issues. Lookup is rollout-compatible: it matches the current hash, the pre-#3552 `request|METHOD|route|warmth|phase|workload` hashes, and the `- Method + route:` / title identity so issues already open today are reused.
- **Durable counters.** Daily breach counts and open-issue identity live in Postgres (`perf_alarm_counters` keyed by fingerprint + UTC day, `perf_alarm_incidents` for open/closed issue numbers, comment throttle, and filing claims). Process memory cannot implement N-hit filing on Vercel serverless. Concurrent instances increment with an atomic upsert and claim filing before creating an issue.
- **Never file under budget.** Timings at or under the 1000 ms route budget never open an issue. 500-999 ms warnings are recorded locally only. Issue titles never show a duration below the budget.
- **Ignore cold starts.** `warm/cold: cold` requests and `startup.*` readiness samples do not count toward filing. They are logged separately for the cold-start work tracked in issues 3479 and 3480. Those issues do not consume `performance_alarm_ignored_startup`, so a hard startup failure (2.5s or more) still logs at WARNING.
- **Daily breach threshold.** A route files only after **N** warm over-budget hits in the same UTC day, counted in Postgres across instances. N defaults to **3** and is set with `PERF_ALARM_DAILY_BREACH_THRESHOLD` (1-100). Closed-issue regressions use the same threshold: the alarm reads `issue.state` before commenting, never comments on a closed issue, and a previously fixed route must breach N times again before a new issue is filed.
- **Comment throttle.** At most one GitHub comment per fingerprint per hour. GitHub calls run in a worker thread and never block the user request.

Readiness-critical coroutine hard timeouts still file immediately unless that coroutine signature already has an open issue. GitHub API failure is logged and never fails the user request.
