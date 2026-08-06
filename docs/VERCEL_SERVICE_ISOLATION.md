# Vercel data-service isolation

ComicPile treats Vercel Production and Preview as separate trust boundaries. Preview must never inherit the Production Neon or Upstash services.

## Approved environment matrix

| Environment | Database | Redis | Debug/internal routes |
|---|---|---|---|
| Vercel Production | Production Neon only | Disabled unless deliberately enabled by the cache feature gate | Disabled |
| Vercel Preview | Dedicated Preview Neon branch or no database-backed verification | Always disabled | Disabled |
| GitHub Actions | Disposable PostgreSQL service | Disposable Redis service | Test configuration only |
| Local development | Local developer PostgreSQL | Optional local Redis | Explicit local opt-in only |

## Required Vercel variables

Configure `DATABASE_URL` and `SERVICE_DEPLOYMENT_ENV` independently for Production and Preview. `PRODUCTION_DATABASE_HOST` is a non-secret reference shared with database-backed Preview deployments so the application can compare the real connection target against the approved Production host.

- `SERVICE_DEPLOYMENT_ENV`: `production` in Production and `preview` in Preview.
- `PRODUCTION_DATABASE_HOST`: hostname of the approved Production Neon endpoint, without scheme, credentials, port, or path. Set it in Production and in any database-backed Preview deployment.
- `DATABASE_URL`: Production Neon in Production; a separate Preview Neon branch in Preview, or omit it when Preview does not need database integration.

The guard runs before `app.main` is imported. Production must connect to `PRODUCTION_DATABASE_HOST`. Preview must connect to a different host. Error messages name only missing or conflicting configuration fields and never include URLs, credentials, hosts, or tokens.

## Redis behavior

Preview removes `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`, and `REDIS_URL` from the process environment before application configuration loads, and forces `CACHE_ENABLED=false`. This protects the Production Upstash quota even when Vercel variables were accidentally inherited.

GitHub Actions and local development remain unchanged because they do not set `VERCEL_ENV=production` or `VERCEL_ENV=preview` and continue using disposable/local services.

## Vercel dashboard handoff

1. Scope Production `DATABASE_URL` and `SERVICE_DEPLOYMENT_ENV=production` to Production only.
2. Set `PRODUCTION_DATABASE_HOST` in Production and any database-backed Preview scope. Record only the variable name in evidence, never its value.
3. Remove Production Neon and Upstash credentials from Preview scope.
4. Either omit `DATABASE_URL` from Preview or provision a dedicated Neon Preview branch.
5. Set `SERVICE_DEPLOYMENT_ENV=preview` in Preview.
6. Keep Upstash variables absent from Preview. The application also strips them defensively.
7. Redeploy Production and Preview.
8. Temporarily set a non-secret invalid `PRODUCTION_DATABASE_HOST` in a disposable Preview deployment and verify startup fails with the expected safe configuration error, then restore the correct reference.

## Required handoff evidence

Record the following without copying secret values:

- the variable names present in each Vercel scope;
- the successful Production deployment result;
- the successful isolated Preview deployment result, or confirmation that Preview intentionally omits `DATABASE_URL`;
- the expected failed Preview deployment produced by the intentionally invalid non-secret host reference.

Do not enable `ENABLE_DEBUG_ROUTES`, `ENABLE_INTERNAL_OPS_ROUTES`, or `TEST_ENVIRONMENT` in Preview. The deployment guard rejects those settings and forces Production-style route mounting even when Preview uses isolated data.
