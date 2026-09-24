# ComicVine hydrator

The ComicVine hydrator inspects comics that already exist in ComicPile and writes a machine-readable JSON report. It does not modify threads, issues, reading progress, ratings, dependencies, continuity rules, or confirmed provider mappings.

## Read-issue identity and creator backfill

Use `scripts/backfill_read_comicvine.py` as the single operator entrypoint for read
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
DATABASE_URL=... uv run python scripts/backfill_read_comicvine.py \\
  --user-id 1 --dry-run
```

Run or resume the live pipeline:

```bash
COMICVINE_API_KEY=... DATABASE_URL=... uv run python scripts/backfill_read_comicvine.py \\
  --user-id 1 --report .cache/comicvine-read-backfill.json
```

The JSON report records phase order, per-issue results, pending work, throttled
resources, and live request counts. `--refresh` forces provider metadata refresh
for already mapped issues; without it, stored and local data are exhausted first.

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
