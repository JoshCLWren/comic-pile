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

Configure these independently in the Vercel dashboard rather than sharing one value across Production and Preview:

- `SERVICE_DEPLOYMENT_ENV`: `production` in Production and `preview` in Preview.
- `DATABASE_SERVICE_ID`: a stable, non-secret identifier for the actual Neon branch/service used in that scope.
- `PRODUCTION_DATABASE_SERVICE_ID`: the stable identifier for the approved Production Neon service.
- `DATABASE_URL`: Production Neon in Production; a separate Preview Neon branch in Preview, or omit it when Preview does not need database integration.

The guard runs before `app.main` is imported. Production must match the approved Production database identity. Preview must use a different identity. Error messages name only missing or conflicting configuration fields and never include URLs, credentials, hosts, or tokens.

## Redis behavior

Preview removes `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`, and `REDIS_URL` from the process environment before application configuration loads, and forces `CACHE_ENABLED=false`. This protects the Production Upstash quota even when Vercel variables were accidentally inherited.

GitHub Actions and local development remain unchanged because they do not set `VERCEL_ENV=production` or `VERCEL_ENV=preview` and continue using disposable/local services.

## Vercel dashboard handoff

1. Scope Production `DATABASE_URL`, `SERVICE_DEPLOYMENT_ENV=production`, and the matching database service IDs to Production only.
2. Remove Production Neon and Upstash credentials from Preview scope.
3. Either omit `DATABASE_URL` from Preview or provision a dedicated Neon Preview branch and set a distinct `DATABASE_SERVICE_ID`.
4. Set `SERVICE_DEPLOYMENT_ENV=preview` in Preview.
5. Keep Upstash variables absent from Preview. The application also strips them defensively.
6. Redeploy Production and Preview. A mis-scoped deployment should fail immediately with a non-secret configuration error.

Do not enable `ENABLE_DEBUG_ROUTES` or `ENABLE_INTERNAL_OPS_ROUTES` in Preview. The deployment guard rejects either setting even when Preview uses isolated data.