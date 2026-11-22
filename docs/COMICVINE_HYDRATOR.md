# ComicVine hydrator

The ComicVine hydrator inspects comics that already exist in ComicPile and writes a machine-readable JSON report. It does not modify threads, issues, reading progress, ratings, dependencies, continuity rules, or confirmed provider mappings.

## Durable ledger backfill (live Rust path)

A successful Queue → Add Series import commits one `comicvine_metadata_refresh_requests` row for every roster-only confirmed issue identity, so creator hydration no longer depends on the Roll issue page being opened. The scheduled repair drain (`GET /api/v2/maintenance/comicvine-metadata-repairs`) claims due rows in bounded batches with 120-second leases, preserved backoff, and a distinct `no_credits` outcome for legitimate empty credit lists.

For identities imported before that fix, use the CRON_SECRET-authenticated backfill endpoint. It scans confirmed ComicVine issue identities in ascending id order, enqueues only those lacking deep metadata, and never remaps an identity, fabricates credits, or touches reading/rating state. Already-hydrated identities and identities with any existing request row are skipped. `limit` is bounded to 1–500; pass the returned `last_identity_id` back as `after_identity_id` to resume. The report includes `dry_run`, `scanned`, `eligible`, `enqueued`, `already_present`, and before/after `pending` counts.

```bash
# Dry run: counts only, no ledger writes.
curl -X POST -H "Authorization: Bearer $CRON_SECRET" \
  'https://comic-pile.vercel.app/api/v2/maintenance/comicvine-hydration-backfill?dry_run=true&limit=50'

# Apply a batch, then resume with the reported last_identity_id.
curl -X POST -H "Authorization: Bearer $CRON_SECRET" \
  'https://comic-pile.vercel.app/api/v2/maintenance/comicvine-hydration-backfill?limit=50&after_identity_id=12345'
```

## Read-issue identity and creator backfill (historical Python operator)

The retired Python entrypoint below is retained for provenance only; it is not present in the Rust-only checkout. Use the durable ledger backfill above for live repair. <!-- docs-path-check: ignore -->

Use `scripts/backfill_read_comicvine.py` as the single operator entrypoint for read <!-- docs-path-check: ignore -->
issues. It targets only the explicitly exported `DATABASE_URL` and runs four resumable
stages in order:

1. prove and persist every identity supported by the configured local ComicVine SQLite snapshot;
2. hydrate every creator payload available from stored metadata or that snapshot;
3. use ComicVine only for identities still unresolved after the local stages; and
4. hydrate creator metadata for identities that became satisfiable in stage 3.

A run can be interrupted and rerun. Confirmed mappings, normalized metadata, provider
responses, request pacing, and resource cooldowns are persisted or enforced by the
operator. A throttle on one resource defers only work needing that resource; other
resources continue. Headerless throttles use bounded per-resource backoff, and a
successful request resets that resource's backoff.

Set `COMICVINE_API_KEY` only when provider-dependent work remains. The operator
paces uncached live request starts at 1.5 seconds. Set `COMICVINE_LOCAL_DB` (or
`COMICPILE_COMICVINE_SQLITE_PATH`) to a local snapshot path to enable local-first
identity and creator work. The command never falls back to test or local databases.

Preview the same four stages without writes or provider calls:

```bash
DATABASE_URL=... uv run python scripts/backfill_read_comicvine.py \
  --user-id 1 --dry-run
```

Run or resume the live pipeline:

```bash
COMICVINE_API_KEY=... DATABASE_URL=... uv run python scripts/backfill_read_comicvine.py \
  --user-id 1 --report .cache/comicvine-read-backfill.json
```

The JSON report records phase order, per-issue results, pending work, throttled
resources, and live request counts. `--refresh` forces provider metadata refresh
for already mapped issues; without it, stored and local data are exhausted first.

### Confirmed-mapping-only creator repair

`--confirmed-only` runs the creator stages for issues that already have a confirmed
ComicVine issue mapping and never remaps identity or performs fuzzy matching. It
deduplicates by canonical `external_identity_id`, so sibling ComicPile issues that
share one provider identity are hydrated once. Stages 1 and 3 (identity resolution)
are skipped; stages 2 and 4 (local and provider creator hydration) still run with the
usual pacing, checkpointing, `--limit`, and resumability.

`--include-unread` widens the inventory to read and unread non-test issues and implies
`--confirmed-only`. Unread and read rows that share one provider identity collapse to a
single backfill result.

```bash
# Inventory only: no writes, no provider calls.
DATABASE_URL=... uv run python scripts/backfill_read_comicvine.py \
  --user-id 1 --confirmed-only --include-unread --dry-run

# Bounded repair of already mapped issues.
COMICVINE_API_KEY=... DATABASE_URL=... uv run python scripts/backfill_read_comicvine.py \
  --user-id 1 --confirmed-only --include-unread --limit 50 \
  --report .cache/comicvine-confirmed-repair.json
```

The report separates already-hydrated (`complete`, with a creator-credit count),
sparse/roster-only (`needs-normalization`), never-deep-hydrated (`needs-hydration` or
`planned-local`), provider-dependent, rate-limited, failed, and unresolved outcomes. It
also records the before/after coverage counts (`inventory` plus `summary`) and per-phase
provider request counts, so an operator can confirm that no bulk provider fan-out
occurred.

## Report-only local run

Use the local ComicVine snapshot and optional CBL mirror first. This mode does not require a ComicVine API key and does not make provider requests.

```bash
uv run python scripts/hydrate_comicvine_issues.py \
  --user-id 1 \
  --cbl-mirror ../CBL-ReadingLists \
  --comicvine-db ./localcv.db \
  --output .cache/comicvine-hydrator/user-1-report.json
```

For composite ComicPile threads that span multiple provider volumes, add an explicit segment map. Segment declarations scope a volume to a position range and never assert that the whole thread belongs to one ComicVine volume.

```bash
uv run python scripts/hydrate_comicvine_issues.py \
  --user-id 1 \
  --comicvine-db ./localcv.db \
  --segment-map ./comicvine-volume-segments.json \
  --output .cache/comicvine-hydrator/user-1-segmented.json
```

## Budgeted live refresh

Set `COMICVINE_API_KEY` in the environment. The default ceiling is 180 requests per hour for each endpoint bucket, with a persistent request ledger in the cache directory so restarting the command does not reset the rolling budget.

```bash
COMICVINE_API_KEY=... uv run python scripts/hydrate_comicvine_issues.py \
  --user-id 1 \
  --comicvine-db ./localcv.db \
  --cache-dir .cache/comicvine-hydrator \
  --live-refresh \
  --output .cache/comicvine-hydrator/user-1-live.json
```

Successful provider responses are cached. Rerunning the same command reuses those cached responses unless `--force-refresh` is supplied.

## Optional deep issue and story-arc hydration

Deep hydration is separate from basic identity resolution. It requests the singular ComicVine issue resource only for already matched issues, verifies that the returned provider ID still equals the confirmed identity, and stores the metadata only in the report.

```bash
COMICVINE_API_KEY=... uv run python scripts/hydrate_comicvine_issues.py \
  --user-id 1 \
  --comicvine-db ./localcv.db \
  --cache-dir .cache/comicvine-hydrator \
  --deep-hydration \
  --output .cache/comicvine-hydrator/user-1-deep.json
```

To hydrate story arcs discovered in deep issue responses, add `--hydrate-story-arcs`. Story-arc IDs are deduplicated across all hydrated issues before any story-arc request is made, so a shared arc is fetched at most once per pass and then benefits from the persistent response cache on later runs.

```bash
COMICVINE_API_KEY=... uv run python scripts/hydrate_comicvine_issues.py \
  --user-id 1 \
  --comicvine-db ./localcv.db \
  --cache-dir .cache/comicvine-hydrator \
  --deep-hydration \
  --hydrate-story-arcs \
  --output .cache/comicvine-hydrator/user-1-deep-arcs.json
```

`--hydrate-story-arcs` requires `--deep-hydration`. Provider throttling stops the affected endpoint pass cleanly, leaves already collected report data intact, and records budget exhaustion so a later rerun can continue using the same cache and request ledger.
