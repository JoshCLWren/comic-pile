# Mignolaverse issue-level CBL expansion

ComicPile's source CBL clone already contains a collection-level roadmap:

`Dark Horse/Characters/Hellboy/[Dark Horse] Hellboy (Mignolaverse) TPB Reading Order.cbl`

That file is useful ordering evidence, but its 106 entries represent collected editions rather than the individual comics ComicPile needs for Roll and strict Reading Plans.

`scripts/expand_collection_cbl.py` expands those collection entries into issue-level CBL rows using the developer-local ComicVine snapshot. The operator is intentionally fail-closed:

- it reads ComicVine `Collects` / `Collecting` metadata and linked source series IDs;
- explicit issue ranges such as `#1-5` are resolved exactly;
- a linked series with no range is accepted only when it is small enough to plausibly represent the complete mini/one-shot series;
- nested collection records are recursively peeled until source issues are reached;
- repeated ComicVine issue IDs are emitted once, preserving their first source-order appearance;
- unresolved or ambiguous material is written to a JSON report instead of guessed;
- optional operator overrides can supply explicit source-series evidence for stubborn collection records.

## Mignolaverse run

From the ComicPile repository, with `../CBL-ReadingLists` as the local CBL clone and `./localcv.db` as the local ComicVine snapshot:

```bash
uv run python scripts/expand_collection_cbl.py \
  "../CBL-ReadingLists/Dark Horse/Characters/Hellboy/[Dark Horse] Hellboy (Mignolaverse) TPB Reading Order.cbl" \
  --comicvine-db ./localcv.db \
  --output-cbl "../CBL-ReadingLists/Dark Horse/Characters/Hellboy/[Dark Horse] Hellboy (Mignolaverse) Complete Reading Order (Issues).cbl" \
  --report .cache/mignolaverse-cbl-expansion.json \
  --name "[Dark Horse] Hellboy (Mignolaverse) Complete Reading Order (Issues)" \
  --strict
```

A strict run exits non-zero when any collection cannot be proven. The generated CBL and report are still written so the operator can inspect exactly what resolved and what needs explicit evidence.

## Overrides

Overrides are keyed by the collection's ComicVine issue ID. Each source series may declare an exact issue list or `"all"` for a proven complete mini/one-shot series:

```json
{
  "218369": [
    {"series_id": 3739, "series_name": "Dark Horse Presents", "issues": ["100", "101", "102"]},
    {"series_id": 21658, "series_name": "Hellboy: Christmas Special", "issues": "all"},
    {"series_id": 6061, "series_name": "Hellboy: Almost Colossus", "issues": "all"}
  ]
}
```

Rerun with `--overrides path/to/overrides.json --strict`. Overrides are explicit operator evidence, not fuzzy title guesses.

## Ordering audit

The maintained **World of Hellboy Reading Order by Julix** remains a useful human audit source for places where stories from one collected edition are intentionally split around other books:

`https://docs.google.com/spreadsheets/d/1g_6LwKE4T73xoIKnCj0X3d_b1aDRnzdLNun8gDqXOPs/`

Do not copy that sheet into ComicPile. Use it to review the generated issue list and to decide explicit overrides or Reading Plan placement where the collection-level CBL lacks story-granular ordering.

## Import into ComicPile

After the generated issue-level CBL is reviewed and committed to the CBL clone:

1. synchronize the CBL mirror with `scripts/sync_cbl_mirror.py`;
2. discover the new source through ComicPile's CBL source UI/API;
3. preview reconciliation against the existing Mignolaverse/B.P.R.D. Reading Plan;
4. include verified existing and missing-importable entries;
5. commit through the targeted Reading Plan adoption endpoint.

The adoption path reuses canonical owned issues, preserves read state/history, materializes only identity-backed missing issues, records `source_cbl_placements`, and recompiles strict continuity rules without creating legacy dependency ordering.
