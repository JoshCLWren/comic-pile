# Shared Catalog Identity Contract

> **Historical implementation contract:** The catalog tables and nullable links
> below remain in the schema baseline, but the Python service/repository/test
> workflow described here is retired. No native catalog get-or-create service or
> equivalent Rust test suite exists at this head. Do not present those Python
> entry points as current. Current identity/mapping behavior is documented in
> [COMICVINE_RUNTIME_FALLBACK.md](COMICVINE_RUNTIME_FALLBACK.md) and
> [API.md](API.md); any catalog runtime work requires separate authorization.

<!-- docs-path-check: historical -->

**Issue:** #3220 (child of #3216)
**Status:** Accepted (v1)
**Owners:** DB-scale campaign (#3216)

This document is the durable contract for the shared catalog identity tables
(`catalog_series`, `catalog_issues`) and the nullable reader-library links
(`threads.catalog_series_id`, `issues.catalog_issue_id`). It is the canonical
reference for invariants, confirmed-only rules, lock behavior, and application
rollback. The implementation plan lives in `docs/issue-plans/3220.md`.

## Purpose

A ComicPile issue currently mixes two concerns: shared comic identity and
reader-owned progress. The shared catalog separates those concerns without
replacing any personal primary key. Two different readers can reference one
`CatalogIssue` while retaining their distinct `Issue` IDs, read states, notes,
and ratings.

## Schema

| Object | Kind | Notes |
| --- | --- | --- |
| `catalog_series` | table | `BIGINT` PK; one required unique `canonical_external_identity_id` FK to `external_identities.id` (`ON DELETE RESTRICT`) |
| `catalog_issues` | table | `BIGINT` PK; one required unique `canonical_external_identity_id` FK to `external_identities.id` (`ON DELETE RESTRICT`); nullable `catalog_series_id` FK to `catalog_series.id` (`ON DELETE SET NULL`) |
| `threads.catalog_series_id` | nullable column | indexed; `ON DELETE SET NULL` |
| `issues.catalog_issue_id` | nullable column | indexed; `ON DELETE SET NULL` |

Migration: the tables and nullable links are part of the schema baseline in
`native/migrate/migrations/V1__baseline.sql`. The change is purely additive: it
creates the two tables, adds the two nullable columns, and creates the matching
indexes. It does not scan or backfill personal rows, does not delete data, and
makes no provider network calls. Alembic is retired; new changes are appended as
new `native/migrate/migrations/V<n>__*.sql` files.

## Identity authority

`ExternalIdentity(provider, entity_type, external_id)` remains the single
identity authority and metadata store. Catalog tables only store a foreign key
to that row. Provider JSON is never copied into catalog tables. Display title,
issue number, and volume year are never used as identity keys.

## Confirmed-only rules

A catalog row may be created only for an external identity that:

1. exists (`entity_type` is exactly `series` for `CatalogSeries` and exactly
   `issue` for `CatalogIssue`), and
2. has at least one confirmed mapping of the matching kind
   (`ThreadExternalSeriesMapping.status = 'confirmed'` for series,
   `IssueExternalIdentityMapping.status = 'confirmed'` for issue).

Candidate, unresolved, and rejected mappings never license catalog creation.
Unknown or custom reader entries receive no shared catalog row until identity
is verified. The service entry points are `ensure_catalog_series` and
`ensure_catalog_issue` in `app/services/catalog.py`; there is no public write <!-- docs-path-check: ignore -->
API.

## Concurrency and lock behavior

Get-or-create is keyed only by the exact confirmed external identity id.

- The repository issues `INSERT ... ON CONFLICT DO NOTHING` against the unique
  `canonical_external_identity_id` constraint, then selects the winner.
- A concurrent create therefore produces exactly one catalog row; the loser of
  the race loads the existing row and never overwrites its identity.
- Series linking is additive-only: `UPDATE catalog_issues SET catalog_series_id = ?
  WHERE id = ? AND catalog_series_id IS NULL`. An existing link is never
  rewritten. After the Core `UPDATE`, the repository reloads the row with
  `populate_existing` so callers never observe a stale identity-map instance.
- A catalog issue may exist before its series is resolved. Filling a verified
  series link later is additive and never rewrites reader ownership.

## Reader-library links

`threads.catalog_series_id` and `issues.catalog_issue_id` are nullable and
indexed. Existing libraries work without a backfill and without catalog service
calls. Personal primary keys (`User.id`, `Thread.id`, `Issue.id`) are unchanged.
Deleting a catalog row sets the reader link to `NULL` (`ON DELETE SET NULL`);
it never deletes or rewrites personal rows. Personal reading state (read
status, notes, ratings, queue position, plan intent) is never stored in catalog
tables and is never shared across readers.

## Read-surface compatibility (v1)

v1 is additive: it introduces new tables and new nullable columns only. It must
not narrow or otherwise change any existing read surface. In particular
`search_catalog_series` and `search_catalog_issues` in
`app/repositories/catalog_repository.py` keep their pre-v1 `external_identities` <!-- docs-path-check: ignore -->
semantics, and `series_external_id` stays an existence gate rather than a scope
filter.

Requiring `catalog_series`/`catalog_issues` membership in those searches would
be a wire-contract change and would contradict acceptance criterion 3: nothing in
v1 backfills catalog rows or calls the catalog service, so every pre-existing
library identity would disappear from `/api/v1/catalog/series` and
`/api/v1/catalog/issues`. A later campaign issue that populates catalog rows may
introduce catalog-scoped search behind a separate, explicitly reviewed change.

`tests/test_catalog_repository.py` pins this contract with <!-- docs-path-check: ignore -->
`test_search_catalog_series_includes_identities_without_catalog_row` and
`test_search_catalog_issues_includes_identities_without_catalog_row`.

## Non-goals (v1)

- No alias or cross-provider auto-merging.
- No automatic matching by title, issue number, or volume year.
- No public write API.
- No replacement of personal primary keys or same-reader canonical-identity
  behavior.

## Application rollback

The schema change is additive-only, and the migration runner has no downgrade
path. Application rollback is:

1. Redeploy the previous application revision, which ignores the new nullable
   columns and tables.
2. If the schema itself must be removed, restore a pre-migration backup (see
   [`DATABASE_SAVE_LOAD.md`](DATABASE_SAVE_LOAD.md)) or write a new forward
   migration that drops the two nullable columns (indexes first) and then the
   two catalog tables in reverse dependency order.

No personal data is migrated, so rollback is safe and does not scan or rewrite
reader libraries. Existing `external_identities`, `issues`, and `threads`
content other than the two new nullable columns is unchanged.

## Verification

- Rust tests in `native/roll-service` cover catalog identity invariants,
  confirmed-only creation, concurrency-safe get-or-create, and additive series
  linking (`cargo test -p comicpile-roll-service catalog`).
- The migration runner must plan clean after `up`:
  `cargo run --locked -p comicpile-migrate -- plan`.
- CI requires a DB-backed HTTP test for every native route module
  (`node scripts/check_native_route_db_tests.mjs`).
- Whole-repo Python tooling checks: `ruff check .` and
  `ty check --error-on-warning`.
