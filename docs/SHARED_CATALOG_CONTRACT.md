# Shared Catalog Identity Contract

**Issue:** #3220 (child of #3216)  
**Status:** Accepted schema contract; implementation notes below distinguish
current native behavior from the retired Python design.

This document defines the shared catalog identity tables and nullable
reader-library links. The original Python service/repository implementation plan
is retained as history in `docs/issue-plans/3220.md`; it is not current runtime
guidance.

## Purpose

The shared catalog separates comic identity from reader-owned progress. Two
readers can reference one catalog identity while retaining distinct personal
Issue/Thread IDs, read states, notes, and ratings.

## Schema

| Object | Kind | Notes |
| --- | --- | --- |
| `catalog_series` | table | `BIGINT` PK; required unique `canonical_external_identity_id` FK to `external_identities.id` (`ON DELETE RESTRICT`) |
| `catalog_issues` | table | `BIGINT` PK; required unique `canonical_external_identity_id` FK; nullable `catalog_series_id` FK (`ON DELETE SET NULL`) |
| `threads.catalog_series_id` | nullable column | Indexed; `ON DELETE SET NULL` |
| `issues.catalog_issue_id` | nullable column | Indexed; `ON DELETE SET NULL` |

The tables and links are part of `native/migrate/migrations/V1__baseline.sql`.
The change is additive: it does not scan or backfill personal rows, delete data,
or make provider network calls. Alembic is retired; append new changes as
`native/migrate/migrations/V<n>__*.sql` files.

## Identity authority

`ExternalIdentity(provider, entity_type, external_id)` remains the identity and
metadata authority. Catalog tables only reference that row. Provider JSON is
never copied into catalog tables. Display title, issue number, and volume year
are never identity keys.

Candidate, unresolved, and rejected mappings never license catalog creation.
Unknown or custom reader entries receive no shared catalog row until identity is
verified.

## Current native runtime

The current native service consumes catalog links when loading canonical volume
evidence and issue identity:

- `native/roll-service/src/option_inputs.rs` joins `catalog_series` and
  `catalog_issues` into the owner-scoped eligibility snapshot.
- `native/roll-service/src/issue_identity.rs` reads catalog links for issue-card
  identity projection.
- `native/roll-service/src/catalog_commit.rs` persists external identities,
  confirmed Issue/Thread mappings, and provider metadata through the native
  series-mapping commit flow.

There is no current public API that creates `catalog_series` or `catalog_issues`
rows, and the retired Python `ensure_catalog_series` / `ensure_catalog_issue`
service entry points do not exist in the native runtime. The confirmed-only
get-or-create and additive series-linking rules below remain accepted design
invariants for any future native writer; they are not evidence that such a writer
is currently active.

## Concurrency and lock behavior

The accepted get-or-create rule is keyed only by the exact confirmed external
identity ID:

- Insert against the unique `canonical_external_identity_id` constraint with
  `INSERT ... ON CONFLICT DO NOTHING`, then select the winner.
- A concurrent create produces exactly one catalog row; the loser loads the
  existing row and never overwrites identity.
- Series linking is additive-only: set `catalog_issues.catalog_series_id` only
  while it is `NULL`. An existing link is never rewritten.
- A catalog Issue may exist before its series is resolved. Filling a verified
  series link later is additive and never rewrites reader ownership.

These rules describe the accepted contract, not a currently exposed native
catalog-writing service.

## Reader-library links

`threads.catalog_series_id` and `issues.catalog_issue_id` are nullable and indexed.
Existing libraries work without a backfill. Personal primary keys are unchanged.
Deleting a catalog row sets the reader link to `NULL`; it never deletes or rewrites
personal rows. Reading state, notes, ratings, queue position, and list intent are
never stored in catalog tables or shared across readers.

## Read-surface compatibility

Catalog membership must not silently narrow existing identity search. The current
native series-mapping preview/commit operations persist confirmed mappings and
metadata; they are not the retired `/api/v1/catalog/series` or
`/api/v1/catalog/issues` search surface. Use the generated same-path and v2
contracts for current operations.

The Python repository tests that pinned the old catalog search behavior were
retired with the Python API. No native replacement test is claimed by this
historical contract; current caller and contract tests remain authoritative.

## Non-goals

- No alias or cross-provider auto-merging.
- No automatic matching by title, issue number, or volume year.
- No current public catalog write API.
- No replacement of personal primary keys or same-reader identity behavior.
- No use of catalog identity as authorization evidence.

## Application rollback

The schema change is additive-only, and the migration runner has no downgrade
path. Application rollback is:

1. Redeploy the previous application revision, which ignores the nullable columns
   and tables.
2. If the schema itself must be removed, restore a pre-migration backup (see
   [`DATABASE_SAVE_LOAD.md`](DATABASE_SAVE_LOAD.md)) or write a new forward
   migration that drops the nullable columns (indexes first) and then the catalog
   tables in reverse dependency order.

No personal data is migrated, so rollback does not scan or rewrite reader
libraries.

## Verification

- The schema constraints and indexes are pinned by the refinery baseline.
- Native undo tests preserve catalog links when a snapshot omits the key.
- Current identity/caller behavior is covered by the native issue-identity and
  generated-contract tests.
- CI requires a DB-backed HTTP test for every native route module
  (`node scripts/check_native_route_db_tests.mjs`).
- Whole-repo Python tooling checks remain `ruff check .` and
  `ty check --error-on-warning`.
