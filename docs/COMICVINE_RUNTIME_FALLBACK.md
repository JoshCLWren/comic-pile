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

### Individual identity confirmation

Individual ComicVine confirmation and replacement commit the owned issue's explicit provider
identity before refreshing metadata through the same bounded fallback used by sibling approval.
Stored raw issue evidence is normalized first, so an existing provider cover can be recovered
without a network request. Complete fresh metadata, including an explicit provider response with
no cover, does not trigger another lookup. Missing metadata uses the confirmed issue ID and the
existing timeout, retry, and deduplication controls. Provider failure leaves the confirmed mapping
intact; Roll and rating continue to serve stored data through their existing nonblocking reads.
The origin remains excluded from sibling approval.

### Series mapping and incomplete confirmed identities

A confirmed mapping records an external ID; it does not prove that ComicPile has usable
issue metadata. Queue's mapping-health projection separately reports
`metadata_missing_count`, so a thread with confirmed IDs but missing issue numbers or series
names keeps its **Map series** action. Roll's corrections menu exposes the same series flow
directly, without requiring removal of the current issue's identity.

Series previews compare the actual selected ComicVine volume roster with local issue numbers
and external IDs. Existing IDs that agree with the roster but lack usable metadata are shown
as **Missing details** and can be approved for an **Update** alongside new exact matches.
The signed preview binds that refresh eligibility; commit recomputes it and retains ownership,
conflict, expiry, stale-preview, and idempotency checks. An existing confirmation by itself
does not authorize an update to a different provider ID.

Commit saves the already-fetched roster's issue, volume and cover metadata in the same
transaction as the approved mappings, preserving existing populated/deep metadata. This
provides usable basic data even if the bounded post-commit singular-issue hydration cannot
complete. Deep creator/story-arc enrichment still follows the normal runtime fallback.

An all-confirmed volume with verified roster agreement retains its rows and counts rather
than returning an empty “unsafe scope.” Mixed reading threads may contain annuals, specials,
and other titles; those rows remain visible as unmatched, conflicting, or requiring review.
Bootstrap provider failures return a retryable 503 instead of pretending the reader's series
has no safe scope. A missing local series name is nullable at the response boundary and is
filled from live provider data when available.

Regression evidence is in `tests/test_comicvine_production_mapping_cases.py` and
`tests/fixtures/comicvine/production_mapping_cases.json`. The fixture replays public provider
rosters and the Tom Strong/Starman mapping shapes captured on 2026-10-19; it excludes account
IDs, credentials, reading progress and history. The original Tom Strong case had 36 confirmed
IDs, 29 with empty metadata, and a nameless series stub that caused preview response validation
to fail. Starman combined a confirmed main volume with other titles, causing the old
“no new exact matches” path to erase the useful classification details.

Confirmation preserves an existing identity's metadata timestamp when only its URL or local
normalization changes. Those edits are not a provider refresh: stale evidence must remain stale
through the post-commit fallback's own freshness check.
