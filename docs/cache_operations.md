# Cache operations

ComicPile's remote Redis cache is disabled by default in production (as of 2026-09-21) due to free-tier quota exhaustion. The application serves database-backed results unless `CACHE_ENABLED=true` is set alongside a complete Redis configuration.

ComicPile uses Vercel for production deployments only. Pull-request validation runs locally and in GitHub Actions; there is no Vercel Preview environment to configure or support.

## Environment matrix

| Environment | Cache setting | Redis service |
| --- | --- | --- |
| Production | `CACHE_ENABLED=false` (enforced 2026-09-21) | Upstash disabled due to quota exhaustion |
| CI | `CACHE_ENABLED=true` | Disposable workflow Redis service |
| Local tests | `CACHE_ENABLED=true` | Disposable Docker Redis from `docker-compose.test.yml` |
| Local development | Explicit opt-in only | Developer-owned local Redis |

When caching is disabled, Redis credentials alone do not activate the client. FastAPI startup skips Redis initialization and its `PING`, decorated reads execute their underlying database function, and invalidation calls remain harmless because the cache client is uninitialized.

## Re-enabling remote caching

Redis caching will remain disabled until a fresh Neon hot-path evidence pass demonstrates that the cache provides sufficient benefit to justify the free-tier quota usage. Do not re-enable merely because the Upstash quota resets. See `docs/CACHE_REENABLE_DECISION.md` for the re-enablement criteria and process.
