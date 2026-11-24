# ComicVine runtime metadata refresh

Comic Vine issue intelligence is stored reader/catalog data. A normal issue read does not perform synchronous provider I/O. The native service returns stored metadata and, when the issue is eligible, durably enqueues a refresh request.

## Current flow

1. `GET /api/v2/issues/{issue_id}/comicvine` reads the current stored projection and records eligible work in `comicvine_metadata_refresh_requests`. The retained `/api/v1/issues/{issue_id}/comicvine` path is a native compatibility alias, not a Python runtime.
2. `native/roll-service/src/comicvine_repair.rs` drains bounded work using leased queue rows (`FOR UPDATE SKIP LOCKED`). Provider 420/429 responses defer the item with bounded backoff; repeated failures mark it failed with a retry window.
3. `GET /api/v2/maintenance/comicvine-metadata-repairs` invokes the authenticated native worker. Vercel Cron and `.github/workflows/comicvine-metadata-repair.yml` call the same endpoint under the configured `CRON_SECRET` boundary.
4. `GET /api/v2/maintenance/comicvine-metadata-backfill` provides the dry-run-default, resumable native backfill for confirmed identities.

See [VERCEL_DEPLOYMENT.md](VERCEL_DEPLOYMENT.md#comicvine-creator-repair-cadence-4623) for cadence/activation and [API.md](API.md) for the generated operation contracts.

## Retired behavior

The Python `app.comicvine_hydration.hydrate_issue` path, in-process/advisory-lock refresh task, `COMICVINE_CACHE_DIR`, `comicvine_fallback_*` log family, local SQLite hydrator, and one-retry fallback are retired. Do not reintroduce them as a documentation fix.

Current implementation and tests live in `native/roll-service/src/comicvine_issue.rs`, `native/roll-service/src/comicvine_repair.rs`, and the corresponding native tests.
