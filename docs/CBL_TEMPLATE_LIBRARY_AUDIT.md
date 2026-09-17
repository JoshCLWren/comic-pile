# CBL Template Library Audit

**Audit date:** 2026-09-17
**Status:** Complete — measured
**Supersedes:** The 2026-09-17 inferred revision of this document
**Based on architecture:** `docs/READING_GRAPH_ADR.md`

## Goal

Produce a measured audit for making the existing CBL Git clone the browsable import/export template
library for Reading Plans under `docs/READING_GRAPH_ADR.md`.

This is documentation/audit work only. No production data, sync jobs, APIs, frontend behavior, CBL
files, Reading Plans, dependencies, or runtime eligibility were modified. All production access was
read-only `SELECT`.

## Method

Every number below was measured on 2026-09-17, not estimated. Three sources were used:

1. The local clone at `/mnt/bigdata/CBL-ReadingLists`, at mirror HEAD
   `7b6ad0b182ccb06cc00cc2e184c43064a290d8bb` ("Exclude Absolute Green Lantern from reading order"),
   1158 commits, not a shallow clone.
2. The real application parser `app/cbl_ingest.parse_cbl_mirror`, executed over the whole mirror.
3. Read-only queries against the production Neon database via `CLONE_PROD_DB_URL`.

The previous revision of this document labelled its structure and counts "Inferred" and
"estimation". Those inferred figures were wrong by large margins and are corrected here. See
[Corrections to the previous audit](#corrections-to-the-previous-audit).

### Reproducing the mirror inventory

```bash
# Total .cbl files
find /mnt/bigdata/CBL-ReadingLists -type f -name '*.cbl' | wc -l

# Parse the whole mirror with the application parser
cd /mnt/extra/josh/code/comic-pile
PYTHONPATH=. uv run python -c "
from pathlib import Path
from app.cbl_ingest import parse_cbl_mirror
parsed, failures = parse_cbl_mirror(Path('/mnt/bigdata/CBL-ReadingLists'))
print('total     ', len(parsed) + len(failures))
print('parseable ', len(parsed))
print('failures  ', len(failures))
print('entries   ', sum(len(p.books) for p in parsed))
for f in failures:
    print('FAIL', f.source_path, '-', f.message)
"
```

## Measured Mirror Inventory

| Measure | Value |
| --- | --- |
| `.cbl` files | 1,706 |
| Parseable | 1,701 (99.71%) |
| Unparseable | 5 (0.29%) |
| Total ordered entries across parseable lists | 333,605 |
| Entries per list (min / median / mean / max) | 1 / 52 / 196.1 / 3,180 |
| Lists with zero entries | 0 |
| Entries carrying both ComicVine series and issue ids | 333,586 of 333,605 (99.994%) |
| Distinct ComicVine series ids | 9,020 |
| Distinct ComicVine issue ids | 76,447 |
| Lists with no `<NumIssues>` element | 23 |
| Lists whose `<NumIssues>` disagrees with actual entry count | 0 |
| Lists whose `<Name>` equals the filename stem | 1,562 of 1,701 |
| Duplicate content hashes | 1 pair |
| Duplicate source paths | 0 |
| Full-mirror parse wall time | ~8 seconds |

Whole-mirror parsing is cheap: about 8 seconds of pure CPU for 1,706 files and 333,605 entries, with
no database or network access. This single measurement invalidates most of the previous revision's
architecture, which was built around avoiding parse cost.

### Files per top-level publisher directory

The mirror has 15 publisher directories plus a `README.md`. It is heavily Marvel- and DC-weighted:

| Directory | Files | Parsed | Failed |
| --- | --- | --- | --- |
| Marvel | 1,118 | 1,113 | 5 |
| DC | 472 | 472 | 0 |
| Other | 49 | 49 | 0 |
| Valiant | 13 | 13 | 0 |
| Boom | 10 | 10 | 0 |
| Image | 10 | 10 | 0 |
| Dark Horse | 9 | 9 | 0 |
| IDW | 7 | 7 | 0 |
| Zenescope | 6 | 6 | 0 |
| Vertigo | 4 | 4 | 0 |
| Archie Comics | 3 | 3 | 0 |
| Dynamite | 2 | 2 | 0 |
| Avatar Press | 1 | 1 | 0 |
| Chaos Comics | 1 | 1 | 0 |
| Rebellion | 1 | 1 | 0 |

### Actual directory structure

368 directories. Publisher directories subdivide by intent rather than by series, and nesting is
between 2 and 7 path components deep:

```
CBL-ReadingLists/
├── README.md
├── Marvel/            Characters, Creator Runs, Events, Master Reading Order, Star Wars, Teams
├── DC/                Characters, Creator Runs, Events, Master Reading Order, Teams
├── Image/             Characters, Events, Master Reading Order
├── Dark Horse/        Characters, Star Wars, Umbrella Academy
├── Other/             Multiple Publishers, Star Wars, Teenage Mutant Ninja Turtles,
│                      The Authority, unsorted
└── (Valiant, Boom, IDW, Zenescope, Vertigo, Archie Comics, Dynamite,
     Avatar Press, Chaos Comics, Rebellion)
```

The deepest paths run seven components, for example
`Marvel/Master Reading Order/Marvel Guides/Alternate Universes/Ultimate Marvel (Earth-1610)/Part 1 Brave New World/[Marvel] 2000-2015 Part 1.1 Ultimate Origins (MG).cbl`.

Two practical consequences for any browse UI:

- **Publisher is derivable from the first path segment.** It does not need to be stored or extracted
  from content.
- **`unsorted` directories are real and common** (`DC/Characters/unsorted/…`,
  `Marvel/Teams/unsorted/…`, `Other/unsorted/…`). A directory-faithful browser will surface
  `unsorted` as a visible node. 6 of the 13 lists currently in production live under an `unsorted`
  path.

### The 5 parse failures, in full

All five are in Marvel, and all five are genuine source-data defects rather than parser bugs. Four
are `Book` elements missing a required `Series` or `Number`; one carries the literal string `None`
where an integer `Volume` or `Year` is expected.

| File | Failure |
| --- | --- |
| `Marvel/Master Reading Order/CMRO/Expanded/[Marvel] CMRO Expanded Reading Order-Part 04.cbl` | book 463 is missing required Series or Number |
| `Marvel/Master Reading Order/CMRO/Expanded/[Marvel] CMRO Expanded Reading Order-Part 05.cbl` | expected integer value, got `'None'` |
| `Marvel/Master Reading Order/CMRO/Misc/[Marvel] CMRO Romance-Teen Reading Order-Part 02.cbl` | book 15 is missing required Series or Number |
| `Marvel/Master Reading Order/CMRO/Misc/[Marvel] CMRO Western Reading Order.cbl` | book 76 is missing required Series or Number |
| `Marvel/Teams/Fantastic Four/[Marvel] [Post-Civil War - Secret Wars] Fantastic Four (Comic Book Herald).cbl` | book 102 is missing required Series or Number |

Notably, **zero files fail on malformed XML**. The previous revision listed `ET.ParseError` first
among expected failure modes and predicted 5–10% unparseable; the real rate is 0.29% and the real
cause is always a missing or non-integer attribute.

Because `_parse_book` raises on the first bad `Book`, one defective entry discards an entire file.
Part 04 loses all of its entries over a single malformed book at position 463. This is an
all-or-nothing policy choice, not an inherent limit — a per-entry skip-with-diagnostic policy would
recover these five files. `sync_cbl_lists` already treats failed paths as `protected_paths` so a
malformed file cannot erase previously imported state.

### Other measured source-data facts

- **One duplicate content-hash pair.** `[Marvel] Marvel Master Reading Order Part #01 (WEB-CBRO).cbl`
  exists byte-identically under both `Marvel/Master Reading Order/CBRO - With Events/` and
  `Marvel/Master Reading Order/CBRO/`. Any dedupe-by-hash assumption must tolerate two distinct
  source paths sharing a hash.
- **19 entries lack a ComicVine issue id.** These are prose or apparatus rows rather than real
  issues, for example `The Superman Post-Crisis Chronology #25`–`#29` in
  `DC/Characters/unsorted/Superman/Essential Superman 001 (Post-Crisis 1).cbl` and
  `The Secret Origin of Wonder Woman #1`. They parse successfully and will persist as entries with a
  null identity FK.
- **The largest lists are very large.** The top five range from 2,475 to 3,180 entries
  (`[Marvel] Marvel Master Reading Order Part #10 (WEB-CBRO).cbl` is the largest). Any preview or
  adoption UI must paginate entries, not just lists.

## Measured Production State

Read-only queries against the production database, one `cbl_sources` row:

| Table | Rows |
| --- | --- |
| `cbl_sources` | 1 |
| `cbl_source_lists` | 13 (13 active, 0 inactive) |
| `cbl_source_entries` | 2,764 |

The single source row:

| Column | Value |
| --- | --- |
| `id` | 3 |
| `repository` | `/mnt/bigdata/CBL-ReadingLists` |
| `revision_sha` | `1a4e17d10d1fe802cb5d4804414c8a1320072167` |
| `synced_at` | 2026-09-10 00:13:24Z |

All 13 persisted lists, with mirror reconciliation:

| id | Name | Entries | Stored revision | File in mirror | Hash matches |
| --- | --- | --- | --- | --- | --- |
| 3 | The Unnamed Universe | 71 | `428c61fe` | yes | yes |
| 9 | [1997-2000] X-Men Era Ten Aftermath (UXRO) | 210 | `7b6ad0b1` | yes | yes |
| 10 | The New Gods 001 | 262 | `7b6ad0b1` | yes | yes |
| 11 | Absolute Universe Reading Order | 76 | `7b6ad0b1` | yes | yes |
| 12 | [Marvel] [2024-2026] The New Marvel Ultimate Universe 2.0 (CBH) | 130 | `7b6ad0b1` | yes | yes |
| 13 | [Image] Supreme [1992-2015] | 94 | `7b6ad0b1` | yes | yes |
| 19 | Alpha Flight | 228 | `7b6ad0b1` | yes | yes |
| 20 | Doom Patrol 1 | 273 | `7b6ad0b1` | yes | yes |
| 21 | [Marvel] Wolverine no Events (WEB-CBRO) | 599 | `7b6ad0b1` | yes | yes |
| 22 | Fantastic Four 001 - Early Years | 288 | `7b6ad0b1` | yes | yes |
| 23 | America's Best Comics | 129 | `7b6ad0b1` | yes | yes |
| 24 | Teen Titans With Events (WEB-CBRO) | 389 | `7b6ad0b1` | yes | yes |
| 26 | [Dark Horse] B.P.R.D. Plague of Frogs Omnibus Vol. 3 (Issues) | 15 | `1a4e17d1` | **no** | **no** |

Every entry in production carries both a series and an issue external-identity FK (2,764 of 2,764).
Production holds 10,048 `external_identities` rows in total.

12 of the 13 lists reconcile perfectly: the file exists at the recorded `source_path` and its current
SHA-256 equals the stored `content_hash`. Provenance for those 12 is intact and verifiable.

### The orphan row

List 26 does not reconcile, and the mismatch is not a stale-revision artifact:

- No file exists at `Dark Horse/Characters/Hellboy/[Dark Horse] B.P.R.D. Plague of Frogs Omnibus Vol. 3 (Issues).cbl`.
- That path has **never** existed in any of the mirror's 1158 commits. A full-history tree scan for
  `Plague of Frogs Omnibus Vol. 3` returns nothing.
- Its recorded `revision_sha` `1a4e17d1…` — which is also the source row's revision — **is not a
  commit object in the mirror repository at all** (`git cat-file -t` fails).
- Its 15 entries are `B.P.R.D.: The Universal Machine` #1–#5 and similar, matching the shape of the
  Step 21 B.P.R.D. recovery work (`tests/test_bprd_integrated_golden_path.py` builds a near-identical
  list at `Dark Horse/B.P.R.D. Plague of Frogs Omnibus Vol. 3.cbl`).

So production's only recorded source revision cannot be resolved back to the mirror, and one of its
13 active lists points at a file that never existed. This row is a hand-seeded recovery artifact, not
mirror-derived data. It should be reconciled or removed before any full sync, and it is the reason a
naive "deactivate everything not in the mirror" run would silently drop it.

## Why Only 13 Lists Are in Production

The measured answer is simple: **a full-mirror sync has never been run against production.** The
supporting evidence, in order of strength:

**1. The id sequence proves it.** `cbl_source_lists_id_seq.last_value` is **26**. A full-mirror sync
would insert 1,701 lists and drive the sequence past 1,700. At most 26 list rows have ever been
allocated in the entire history of this database, of which 13 survive. No amount of later deletion
could lower the sequence. `cbl_sources_id_seq.last_value` is 5, against 1 surviving source row.

**2. It is not an API limit.** `discover_cbl_source_lists`
(`app/repositories/cbl_source_repository.py`) filters only on `active = True` and applies the
caller's `limit`. The endpoint's default is 25 and its ceiling is 100
(`app/api/cbl_sources.py:36`). With 13 active rows, the endpoint already returns all 13 — the API is
not withholding anything. The 13 is a persistence fact, not a presentation fact.

**3. It is not a parse-coverage problem.** 1,701 of 1,706 files parse. The 1,688 lists absent from
production parse cleanly and were simply never synced.

**4. The mixed revisions are expected, not evidence of corruption.** Lists carry three different
`revision_sha` values (`428c61fe`, `7b6ad0b1`, `1a4e17d1`). This is correct behavior:
`sync_cbl_lists` skips unchanged lists early and deliberately does not restamp their revision, so a
list keeps the revision at which its content last changed. Zero inactive rows likewise means the most
recent sync's input included all then-existing paths, so the deactivation pass never fired.

The 13 are the residue of targeted, per-list recovery work — the same campaign recorded in
`docs/recovery/` — rather than a library-scale import. That work needed a handful of specific reading
orders and imported exactly those.

### A latent hazard that will break the first real sync

Production's `cbl_sources.repository` is the local absolute path `/mnt/bigdata/CBL-ReadingLists`. The
documented default in `scripts/sync_cbl_mirror.py` is `JoshCLWren/CBL-ReadingLists`. Because
`sync_cbl_lists` locates the existing source by exact `repository` string match
(`app/cbl_sync.py:82`), running the sync script with its default `--repository` would **not** find
source 3. It would create a second source row and insert all 1,701 lists fresh, leaving the original
13 stranded on an orphaned source and duplicating every list. Whoever runs the first full sync must
either pass `--repository /mnt/bigdata/CBL-ReadingLists` or migrate the existing row's identity
first. This is also why the repository column should hold a stable remote identity, not a machine
path.

### The real cost blocker for a full sync

Parsing is not the bottleneck; identity persistence is. `_build_entry` (`app/cbl_sync.py:200`) awaits
`upsert_external_identity` once per non-null ComicVine id, per entry, with no batching and no
in-run memoization. For the full mirror that is **667,172 sequential awaited round trips** to resolve
only **85,467 distinct identities** (9,020 series + 76,447 issue) — roughly 7.8× more database
round trips than the data requires. On top of that, a changed list deletes and re-inserts all of its
entries.

A full sync would also grow `cbl_source_entries` from 2,764 to 333,605 rows, a factor of about 121.
That row count is unremarkable for PostgreSQL; the round-trip count is the thing that makes the
current implementation impractical to run at mirror scale. Batching and de-duplicating identity
upserts is the single highest-value fix, and it is a change to existing code rather than new schema.

## Current API and Frontend Surfaces

Verified against the live route table (`app.main.app.routes`), not the generated schema:

- `GET /api/v1/issue-identity/cbl-sources` — active persisted lists, default limit 25, max 100
- `GET /api/v1/issue-identity/cbl/{list_id}/adoption-preview`
- `POST /api/v1/issue-identity/cbl/{list_id}/adoption-plan`
- `GET /api/v1/issue-identity/cbl/{list_id}/reconciliation`
- `POST /api/v1/cbl/{list_id}/reading-plans/{plan_id}/adoption-commit`
- `GET|POST /api/v1/custom-cbls`, `GET /api/v1/custom-cbls/issue-search`,
  `GET|PUT|DELETE /api/v1/custom-cbls/{list_id}`, `GET /api/v1/custom-cbls/{list_id}/export`,
  `POST /api/v1/custom-cbls/{list_id}/reading-plans/{plan_id}:apply`

Two corrections to the previous revision's endpoint list: the `reconciliation` endpoint exists and
was omitted, and the custom-CBL paths are mounted under `/api/v1/custom-cbls` (the router is included
into `dependency.router` in `app/api/__init__.py:28`).

**Separate finding:** `frontend/src/generated/openapi.json` contains no `custom-cbls` paths even
though the live app serves all six. The generated schema is stale with respect to the custom-CBL
router. That is a real defect but outside this audit's scope; it should be tracked on its own issue
rather than fixed as a side effect of an audit.

There is no filesystem browsing surface of any kind. Discovery is limited to a bounded `ILIKE` over
the `name` and `source_path` of already-persisted lists.

## Schema Assessment: No New Tables Are Justified

The previous revision proposed three new tables — `cbl_file_index`, `cbl_content_metadata`, and
`cbl_search_index`. **The measured data does not support any of them, and this revision withdraws all
three.** Each was justified by an assumption that measurement contradicts:

| Proposed table | Stated justification | Measured reality |
| --- | --- | --- |
| `cbl_file_index` | Avoid expensive parsing; enable lazy parse | Full-mirror parse is ~8s of pure CPU. A separate index to avoid an 8-second scan is not worth its own invalidation problem. `cbl_source_lists` already stores `source_path`, `content_hash`, `revision_sha`, and `active`. |
| `cbl_content_metadata` | Store publisher, series, date range for search | Publisher is the first path segment. Series, `volume_year`, and `publication_year` are already columns on `cbl_source_entries`. `declared_issue_count` is already on `cbl_source_lists`. This table would duplicate existing columns. |
| `cbl_search_index` | `TSVECTOR` full-text search | The search corpus is 1,701 names and paths. `ILIKE` over 1,701 rows needs no full-text infrastructure. If it ever does, a `pg_trgm` index on existing columns comes first, not a new table. |

The proposal also assumed 5,000 files and ~50,000 entries. The real figures are 1,706 files and
333,605 entries — fewer files and 6.7× more entries than assumed, which further undercuts a
per-file index while making per-entry write efficiency the thing that actually matters.

**Conclusion: the existing three-table schema (`cbl_sources`, `cbl_source_lists`,
`cbl_source_entries`) is sufficient for a browsable, searchable, clone-backed template library at
measured scale.** What is missing is a completed sync and a browse API over data the schema already
models — not more tables. If a future measurement demonstrates a specific query that the current
schema cannot serve acceptably, that measurement should be recorded here before any table is
proposed.

## Recommendations

Ordered by measured value. Every item below is a change to existing code, data, or configuration; no
new tables.

1. **Batch and de-duplicate identity upserts in `_build_entry`.** 667,172 awaited round trips for
   85,467 distinct identities is the one measured blocker to a mirror-scale sync. Memoize within a
   run and batch the upserts.
2. **Reconcile the source identity before the first full sync.** Decide whether production's
   `repository` becomes `JoshCLWren/CBL-ReadingLists` or stays the local path, and migrate
   deliberately. Running the script's default against the current row silently duplicates the whole
   library.
3. **Resolve the orphan.** List 26 references a path that never existed and a revision that is not a
   commit. Decide whether to delete it or re-seed it from a real mirror file, and record the
   decision. Do not let a blind sync deactivate it as a side effect.
4. **Run a real full-mirror sync**, first with `--dry-run` (the script already supports it) to
   confirm the expected 1,688 inserts and 0 deactivations, then for real with an explicit
   `--revision-sha` that is an actual mirror commit.
5. **Paginate the discovery endpoint.** The current max of 100 is adequate for 13 lists and
   inadequate for 1,701. Add cursor pagination and a directory/publisher filter over
   `source_path` — both are queries against existing columns.
6. **Consider per-entry parse recovery.** A skip-with-diagnostic policy for individual malformed
   `Book` elements would recover all 5 currently-unparseable files, which between them hold thousands
   of valid entries discarded over one bad row each. This is a deliberate policy change and should be
   decided explicitly, not drifted into.

## Frozen Semantics (unchanged from `docs/READING_GRAPH_ADR.md`)

This audit does not reinterpret the ADR. CBL semantics remain:

- CBL is a template/recipe and provenance source, not runtime execution authority.
- Importing a CBL creates or connects material to a reader-owned Reading Plan.
- The reader may alter the imported plan without mutating the source template.
- Source path, revision, and source positions remain available for provenance and reviewable refresh.
- Source refresh must not silently overwrite reader adaptations.
- A Reading Plan may export a CBL when its representation flattens faithfully enough for the format.

### Import, refresh, and export

**Import/connect.** Browse or search the persisted library, preview parsed entries with resolution
status, choose entries, then commit to a Reading Plan retaining source path, revision, content hash,
and source position. The existing `adoption-preview` → `adoption-plan` → `adoption-commit` chain
already implements this shape.

**Refresh.** Content hash is the change signal, and 12 of 13 production lists prove it works today:
each stored hash still equals the current file's hash. Refresh compares stored hash against the file
at the recorded `revision_sha`, presents a diff, and applies only reader-approved changes. Reader
adaptations are never silently overwritten. The orphan row shows the failure mode to guard: a stored
revision that cannot be resolved to the source must surface as an explicit provenance error rather
than as a silent no-op or a deactivation.

**Export flattening.** A CBL is a flat ordered list of `Book` elements. A Reading Plan whose order is
a single total sequence exports faithfully. A plan with parallel branches or partial ordering cannot
be represented without choosing an arbitrary linearization, so export must either refuse or clearly
mark the chosen flattening as lossy. Export must always be able to emit the reader's current state,
not only a CBL-compatible subset.

### Custom CBL classification

**Keep, and merge the discovery surface.** Custom CBL authoring is a distinct capability with its own
working endpoints and no overlap in storage with mirror-backed sources. The duplication is in
discovery and adoption UI, not in the data model. Recommendation: keep custom CBL authoring as-is,
and unify only the browse/preview/adopt surface so a reader sees personal and mirror-backed templates
in one place. No table changes are implied. Retire nothing.

## Corrections to the Previous Audit

The previous revision was produced without reading the clone, running the parser, or querying
production. Its material errors:

| Claim | Reality |
| --- | --- |
| Directory tree with `Marvel/Avengers/avengers-1963-1969.cbl`, `Independent/`, `Custom/` | Invented. Real layout subdivides by Characters / Creator Runs / Events / Master Reading Order / Teams; there is no `Independent/` or `Custom/` directory, and filenames are not slug-cased. |
| "Total CBL files: ~500-2000" | 1,706 |
| "Parseable: ~90-95%" | 99.71% |
| "Unparseable: ~5-10% (malformed XML, missing required fields)" | 0.29%, and zero malformed-XML failures |
| "`CBLSourceEntry`: ~50,000 entries" | 333,605 entries at mirror scale; 2,764 in production today |
| "~5000 files" in storage projections | 1,706 files |
| Production limited to "the most recently synced repository" | Only one source row has ever survived; the constraint is that no full sync ever ran |
| Production exposure explained by `active = True` filtering | 0 of 13 rows are inactive; the filter excludes nothing today |
| Three new tables required | None justified at measured scale |
| Custom CBL endpoint list, no `reconciliation` endpoint | `reconciliation` exists; custom-CBL routes verified live but missing from the generated OpenAPI schema |

Its acceptance-criteria checklist also marked the inventory criterion satisfied while recording only
estimates, and marked the clone-usage criterion satisfied with the parenthetical "inferred from code
analysis". Both are now satisfied by measurement.

## Acceptance Criteria

- [x] Audit uses the configured local clone — parser executed against `/mnt/bigdata/CBL-ReadingLists`
      at HEAD `7b6ad0b1`
- [x] Total/parseable/unparseable inventory recorded with reproducible commands — 1,706 / 1,701 / 5,
      all five failures listed individually
- [x] Reason production exposes only a subset identified — no full-mirror sync has ever run, proven
      by `cbl_source_lists_id_seq.last_value = 26`
- [x] Proposed UI can browse/search the clone-backed library without granting CBL execution authority
- [x] Import, refresh, reader adaptation, and export semantics explicit
- [x] Custom CBL classified — keep authoring, merge discovery surface, retire nothing
- [x] Export flattening limitations and recommended behavior documented
