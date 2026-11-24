# Operational health endpoints

ComicPile exposes a dependency-free liveness endpoint so monitoring can
distinguish process availability from database readiness.

## Production liveness

`GET /api/v2/health` is the production liveness probe. It returns HTTP 200 with
`status`, `runtime`, `service`, `build` and `process` objects plus the
`X-ComicPile-API-Runtime: rust` header, without opening a PostgreSQL connection.
The build/process fields identify the executable, source revision, compiler,
lock hash, OS and architecture. Production deployment smoke checks status, body,
revision and runtime marker, plus a separate rejected-login request.

The public bare `/health`, `/docs`, `/redoc` and `/openapi.json` paths return
**404 at Vercel ingress** (see the explicit rewrite in `vercel.json`). They do
not start a runtime or serve the SPA shell. Use `/api/v2/health` for production
liveness, and read the checked-in generated contracts
(`native/contracts/v2-runtime.openapi.json`,
`frontend/src/generated/openapi.json`) for the API surface.

## Local development

The native service serves `GET /health` and `GET /api/v2/health` locally on
`:8010`. Neither touches the database. There is no local Swagger/ReDoc surface;
the checked-in OpenAPI contracts are the reference.

The former Python `/api/v1/health/*` probes (dependency, warmup, cache-quota,
keepalive) were retired with the Python API. There is no cache dependency in the
current runtime.

## Database readiness

Liveness intentionally does not prove database availability. Verify readiness
with a real request that reads data, or run the migration planner against the
same database:

```bash
MIGRATE_DATABASE_URL="postgresql://..." cargo run --locked -p comicpile-migrate -- plan
```

`plan` exits 0 when current, 10 when migrations are pending, and another nonzero
code when the check fails closed. The production workflow applies `up` only for
exit 10. The CI `migration-health` job uses the same runner against disposable
PostgreSQL.

## Response semantics

- `200 ok`: the process can serve a request; this does not prove database readiness.
- `401`: authentication is enforced on protected paths; the health route is public.
- `503`: a request handler or dependency is unavailable. Database transport
  failures can return 503 while the process remains alive and healthy.
- Connection failure or no listener: the process/network path is unavailable.

Responses and logs never include connection strings, credentials, exception text,
user data or queried records. Health build metadata is intentional and contains
no secret values.

## Logging

The native service emits structured `tracing` logs; set the filter with
`RUST_ROLL_LOG` (default `info`). Logs report request outcomes and bounded
error kinds without credential values. The Python-era request middleware
metrics (`Server-Timing`, performance-to-GitHub filing) no longer exist in the
runtime; `PERF_ALARM_*` variables are retained only for older deployment
configuration and have no effect on the native service.

## Regression thresholds

Investigate repeated request latency or pool timeouts. The pool is bounded by
`RUST_ROLL_POOL_SIZE` (default 4, max 32) with
`RUST_ROLL_POOL_TIMEOUT_MS` (default 2000) and a per-request timeout of
`RUST_ROLL_REQUEST_TIMEOUT_MS` (default 10000). A timeout always warrants
investigation; raising a bound is not a fix for a slow query.
