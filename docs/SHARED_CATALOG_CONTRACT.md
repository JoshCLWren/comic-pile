# Shared Catalog Identity Contract

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

Migration: `alembic/versions/m5d300000001_add_catalog_identity_tables.py`
(revises `f2a3b4c5d6e7`). The migration is purely additive: it creates the two
new tables, adds the two nullable columns, and creates the matching indexes.
It does not scan or backfill personal rows, does not delete data, and makes no
provider network calls.

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
`ensure_catalog_issue` in `app/services/catalog.py`; there is no public write
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

## Non-goals (v1)

- No alias or cross-provider auto-merging.
- No automatic matching by title, issue number, or volume year.
- No public write API.
- No replacement of personal primary keys or same-reader canonical-identity
  behavior.

## Application rollback

The migration is additive-only. Application rollback is:

1. `alembic downgrade f2a3b4c5d6e7` drops the two nullable columns (indexes
   first) and then the two catalog tables in reverse dependency order.
2. Revert the model, repository, and service code.

No personal data is migrated, so rollback is safe and does not scan or rewrite
reader libraries. Existing `external_identities`, `issues`, and `threads`
content other than the two new nullable columns is unchanged.

## Verification

- `tests/test_migration_graph_integrity.py::test_migration_history_has_a_single_head`
  enforces one Alembic head.
- `tests/test_catalog_migration.py` exercises upgrade and downgrade against a
  populated temporary PostgreSQL schema and asserts personal rows survive both
  directions.
- `tests/test_catalog_models.py`, `tests/test_catalog_repository.py`, and
  `tests/test_catalog_service.py` cover identity invariants, confirmed-only
  creation, concurrency-safe get-or-create, and additive series linking.
- Full-repo Python CI pair: `bash scripts/check-python-ci-lint.sh`.
