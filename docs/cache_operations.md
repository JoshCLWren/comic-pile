# Cache operations

ComicPile's remote Redis cache is disabled by default. The application serves database-backed results unless `CACHE_ENABLED=true` is set alongside a complete Redis configuration.

ComicPile uses Vercel for production deployments only. Pull-request validation runs locally and in GitHub Actions; there is no Vercel Preview environment to configure or support.

## Environment matrix

| Environment | Cache setting | Redis service |
| --- | --- | --- |
| Production | `CACHE_ENABLED=false` or omitted | Remove Upstash variables while the cache redesign is pending |
| CI | `CACHE_ENABLED=true` | Disposable workflow Redis service |
| Local tests | `CACHE_ENABLED=true` | Disposable Docker Redis from `docker-compose.test.yml` |
| Local development | Explicit opt-in only | Developer-owned local Redis |

When caching is disabled, Redis credentials alone do not activate the client. FastAPI startup skips Redis initialization and its `PING`, decorated reads execute their underlying database function, and invalidation calls remain harmless because the cache client is uninitialized.

## Re-enabling remote caching

Do not re-enable remote caching merely because the Upstash quota resets. First complete the bounded invalidation work in issue #869, establish a conservative command budget, and confirm cache initialization no longer delays application readiness.
