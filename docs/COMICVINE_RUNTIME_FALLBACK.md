# ComicVine runtime metadata hydration

Comic Vine issue intelligence is stored reader/catalog data. Hydration is
request/response work, never a background job: there is no queue, lease,
dispatch, cron, drain or polling loop.

## Current flow

1. `GET /api/v2/issues/{issue_id}/comicvine` reads the stored projection and
   derives `metadata_status` from metadata freshness alone. An incomplete
   confirmed identity reports `needs_hydration`; the read never writes an
   enqueue row. The retained `/api/v1/issues/{issue_id}/comicvine` path is a
   native compatibility alias, not a Python runtime.
2. `native/roll-service/src/comicvine_provider.rs` owns the shared transport,
   credential boundary, normalization and freshness policy. Provider 420/429
   responses are surfaced as bounded, truthful outcomes for the current request;
   nothing is deferred to a worker.
3. Confirming or remapping an exact issue calls one bounded awaited provider
   fetch after the mapping transaction commits. A provider failure, timeout,
   invalid response or missing credits preserves the confirmed mapping and any
   valid already-stored metadata.
4. `POST /api/v2/comicvine/issues/{issue_id}/metadata:refresh` is the explicit
   Retry path: it rechecks ownership, targets only the currently confirmed
   identity, awaits a fresh bounded hydration and never remaps or changes
   reading state, ratings, order or ownership.

The `comicvine_metadata_refresh_requests` ledger was retired by
`native/migrate/migrations/V7__retire_comicvine_metadata_refresh_requests.sql`.
Pending/deferred/failed rows contained only retry scheduling state; dropping
them did not change canonical identity metadata, mappings, credits or user data.
Previously hydrated metadata is preserved.

## Retired behavior

The Python `app.comicvine_hydration.hydrate_issue` path, in-process/advisory-lock
refresh task, `COMICVINE_CACHE_DIR`, `comicvine_fallback_*` log family, local
SQLite hydrator, and one-retry fallback are retired. The Vercel cron, GitHub
Actions repair drain, repository dispatch wake, `CRON_SECRET`-authenticated
maintenance endpoints, bounded backfill and ledger-backed enqueue/claim/lease
machinery are retired by #5842. Do not reintroduce any of them.

Current implementation and tests live in `native/roll-service/src/comicvine_issue.rs`,
`native/roll-service/src/comicvine_provider.rs`, `native/roll-service/src/comicvine_v2.rs`
and the corresponding native tests.
