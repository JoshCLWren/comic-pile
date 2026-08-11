# ComicVine runtime metadata fallback

ComicPile serves issue intelligence from Postgres first. The product may request a best-effort
ComicVine refresh only when the requested ComicPile issue already has a **confirmed issue-level
ComicVine identity** and its stored singular-issue metadata is missing or stale.

## Runtime behavior

`GET /api/v1/issues/{issue_id}/comicvine` keeps the current database-backed response on the request
path. It never waits for ComicVine. When a confirmed mapping needs deeper metadata, the service
schedules a bounded refresh and returns whatever trusted data is already stored.

The fallback does not search ComicVine by title, issue number, or thread mapping. A thread-to-volume
mapping is never promoted into an issue identity. Provider relationship data remains informational
metadata and cannot create dependencies or change Roll eligibility.

Concurrent refreshes are deduplicated in-process and with a PostgreSQL advisory transaction lock so
separate application instances do not intentionally fan out the same confirmed issue lookup. The
provider call uses the existing ComicVine client, a five-second network timeout, one bounded retry
for ordinary provider failures, and no immediate retry after rate limiting. Failures are logged and
do not fail the Roll or rating experience.

Successful refreshes flow through `app.comicvine_hydration.hydrate_issue`, which normalizes curated
fields and retains the full singular provider payload in `external_identities.metadata_json`.

## Production configuration

`COMICVINE_API_KEY` must be configured in the **Vercel production project environment** for the
application runtime. A GitHub Actions repository secret with the same name is available only to
GitHub Actions and is not automatically injected into Vercel functions.

Optional `COMICVINE_CACHE_DIR` controls the existing provider client's response cache and rolling
request ledger. The runtime default is `/tmp/comicpile-comicvine`, which is suitable as a
best-effort serverless cache but must not be treated as durable application state. Postgres remains
the durable metadata store and the cross-instance deduplication boundary.

Never place the API key in frontend environment variables, source files, logs, screenshots, or
artifacts.

## Operations and observability

The fallback emits structured log messages prefixed with `comicvine_fallback_` for successful
hydration, deduplication, missing configuration, rate-limit deferral, ineligible identities, and
bounded provider failures. Logged context contains internal/external numeric IDs and error types,
not credentials or provider URLs containing credentials.

For explicit bulk research or repair work, continue to use the existing
`scripts/hydrate_comicvine_issues.py` workflow. The runtime fallback is deliberately narrow: it
repairs metadata for confirmed issue identities encountered by the product rather than becoming a
candidate-discovery or bulk-import mechanism.
