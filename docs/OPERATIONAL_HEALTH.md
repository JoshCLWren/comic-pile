# Operational health endpoints

ComicPile exposes separate bounded endpoints so monitoring can distinguish process startup from dependency availability.

## Endpoint selection

- `GET /api/v1/health/live` confirms only that the FastAPI process can serve a request. It does not query Neon or Upstash and is the correct liveness probe.
- `GET /api/v1/health/dependencies` checks Neon and Upstash independently with a two-second timeout per dependency. Use it for dependency alerts and diagnosis.
- `GET /api/v1/health/warmup` exercises the same cheap, read-only database and cache path used by dependency monitoring. Use it when intentionally warming an idle deployment.
- `GET /api/health` remains the hidden legacy database health boundary for existing callers.

Set `HEALTH_CHECK_TOKEN` in production and send it as `X-Health-Token` to access the detailed dependency and warm-up endpoints. Missing or invalid tokens receive a generic 404 so operational detail is not advertised. The liveness endpoint remains public because it contains no infrastructure detail.

## Response semantics

- `200 healthy`: database and cache both responded within their bounds.
- `207 degraded`: the database is healthy but the cache is unavailable or timed out. ComicPile can continue through its cache fallback path.
- `503 unhealthy`: the database is unavailable or timed out.

Responses contain only status and duration fields. They never include connection strings, hostnames, credentials, exception text, user data, or queried records.

Structured logs emit the aggregate status, each dependency status, each dependency duration, and total duration. Compare these fields with request-level timing to separate function startup latency from Neon, Upstash, and route execution latency.

## Regression thresholds

Investigate repeated database or cache probe durations above 500 ms while warm. A timeout always warrants investigation. Cold invocations may be slower, but the endpoint remains bounded and identifies the dependency responsible rather than allowing one hung provider to consume the whole monitoring request.
