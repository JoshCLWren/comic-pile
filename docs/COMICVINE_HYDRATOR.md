# ComicVine hydrator

The ComicVine hydrator inspects comics that already exist in ComicPile and writes a machine-readable JSON report. It does not modify threads, issues, reading progress, ratings, dependencies, continuity rules, or confirmed provider mappings.

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
