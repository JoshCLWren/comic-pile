# ComicVine runtime metadata hydration

Comic Vine issue intelligence is stored reader/catalog data. Exact-issue map,
remap, import and explicit Retry perform **one bounded, awaited singular
provider fetch inside the HTTP invocation**; they are not background jobs. An
ordinary issue read performs no provider I/O and never enqueues repair work.

## Current interactive flow

1. `POST /api/v2/comicvine/issues/{issue_id}/identity:confirm`,
   `identity:replace` and `POST /api/v2/comicvine/issues:import` commit the
   mapping first, then await one bounded hydration attempt. The fetched cover,
   creator names/roles and deep metadata are merged into the confirmed
   identity's `metadata_json`, so the next
   `GET /api/v2/issues/{issue_id}/comicvine` shows them without polling a
   scheduler. A provider failure never undoes the mapping and never overwrites
   valid same-identity metadata.
2. `POST /api/v2/comicvine/issues/{issue_id}/metadata:refresh` is the explicit
   Retry. It targets only the currently confirmed identity, does not remap, and
   returns a truthful terminal outcome (`complete`, `no_credits`,
   `provider_unavailable`, `rate_limited`, `timeout`, `invalid_response`,
   `provider_not_configured` or `not_confirmed`) plus a provider `Retry-After`
   when throttled. No credits is distinct from a failure.
3. Hydration reads the confirmed identity on a released connection, calls the
   provider outside any transaction or row lock, and rechecks identity and
   ownership at persist so a concurrent A -> B remap cannot be overwritten by a
   late A response. Already-complete cached metadata is reused unless Retry
   forces a fresh attempt.
4. Bulk `series:import` persists the bounded roster only. It never fans out one
   provider request per imported issue and never enqueues per-issue hydration.

## Retained maintenance lane (not used by interactive paths)

The durable `comicvine_metadata_refresh_requests` ledger and
`native/roll-service/src/comicvine_repair.rs` remain for authenticated
maintenance drain/backfill of historical rows. Interactive handlers never
create, claim or dispatch these rows; a successful synchronous hydration may
settle an existing row to a truthful terminal state. The retained
`/api/v1/issues/{issue_id}/comicvine` path is a native compatibility alias, not
a Python runtime.

## Retired behavior

The Python `app.comicvine_hydration.hydrate_issue` path, in-process/advisory-lock
refresh task, `COMICVINE_CACHE_DIR`, `comicvine_fallback_*` log family, local
SQLite hydrator, and one-retry fallback are retired. Do not reintroduce them as
a documentation fix.

Current implementation and tests live in `native/roll-service/src/comicvine_v2.rs`,
`native/roll-service/src/comicvine_issue.rs`,
`native/roll-service/src/comicvine_repair.rs`, and the corresponding native tests.
