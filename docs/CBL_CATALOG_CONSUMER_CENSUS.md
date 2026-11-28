# Catalog Indirection Consumer Census and Read-Only Reconciliation

**Issues:** #3221 (implementation PR #5969), #3216 (parent decision)
**Status:** Evidence artifact. No production access, no schema change, no destructive DDL/DML.

## Decision applied

Owner decision 2A (2026-11-27): `external_identities` plus confirmed owner-scoped
mappings are the shared catalog. This change derives issue-level volume evidence
from confirmed issue mapping metadata or a confirmed series mapping only when
identity evidence supports it, never from a title or issue number. No catalog
writer or backfill was added. Existing catalog-only evidence is retained as a
bounded, read-only, owner-scoped fallback until a census/rehearsal proves no such
reader rows remain.

## Consumer census at the reviewed head

Every native consumer of `catalog_series`, `catalog_issues`, and the reader FK
columns is listed here. "Unchanged" means this PR did not alter that consumer.

| Consumer | Kind | Behavior |
| --- | --- | --- |
| `native/roll-service/src/option_inputs.rs:132` | reader FK | Selects `threads.catalog_series_id` into the owner-scoped thread CTE. |
| `native/roll-service/src/option_inputs.rs:137` | reader FK | Selects `issues.catalog_issue_id` into the owner-scoped issue CTE. |
| `native/roll-service/src/option_inputs.rs:157` | read-only catalog fallback | `volume_evidence` keeps confirmed thread series mappings and a bounded `catalog_series` canonical-identity branch. |
| `native/roll-service/src/option_inputs.rs:207` | read-only catalog fallback | `issue_volume_rows` derives evidence from confirmed issue mappings (series entity and metadata volume) and confirmed thread series mappings, `UNION` the original `catalog_issues` -> `catalog_series` canonical-identity branch. |
| `native/roll-service/src/issue_identity.rs:2295` | read-only catalog fallback | Collection guard issue-level volume evidence: confirmed mappings plus the catalog-only canonical identity branch. |
| `native/roll-service/src/issue_identity.rs:2330` | read-only catalog fallback | Collection guard thread-level identity evidence: confirmed mappings plus the catalog-only canonical identity branch. |
| `native/roll-service/src/custom_cbl.rs:871` | read-only consumer | Thread series identity projection joins `catalog_series` canonical identity. Unchanged. |
| `native/roll-service/src/issue_mutation.rs:378` | read-only consumer | `catalog_issue_id IS NOT NULL` as catalog-evidence signal. Unchanged. |
| `native/roll-service/src/issue_mutation.rs:1039` | read-only consumer | Catalog-evidence existence guard on issue mutation. Unchanged. |
| `native/roll-service/src/issue_service.rs:948` | read-only consumer | Issue card projection reads `catalog_issue_id`. Unchanged. |
| `native/roll-service/src/undo_apply.rs:770` | reader FK | Snapshot restore preserves `issues.catalog_issue_id`. Unchanged. |
| `native/roll-service/src/undo_apply.rs:914` | reader FK | Snapshot apply preserves `issues.catalog_issue_id`. Unchanged. |
| `native/roll-service/src/undo_apply.rs:2182` | existing writer | Undo apply inserts the canonical identity into `catalog_issues`; no new catalog writer is introduced by this PR. |
| `native/roll-service/src/catalog_commit.rs` | mapping writer | Persists confirmed mappings and provider metadata; does not create catalog rows or write reader FK links. Unchanged. |
| `native/migrate/migrations/V1__baseline.sql` | schema | Nullable `catalog_series_id` / `catalog_issue_id` with `ON DELETE SET NULL`, and unique canonical-identity FKs. Unchanged. |

## Reporting unresolved links

Both reader FKs are nullable. An unresolved link is a reader row whose catalog
FK is null (or points at a row whose canonical identity is absent) while a
canonical identity is otherwise available. Agents must not query production.
Run these read-only statements against an authorized disposable replica or
export, never against a production database. They report counts and IDs only;
they do not copy provider metadata or rewrite ownership.

```sql
-- Catalog-only issue links: canonical identity exists, no confirmed mapping.
SELECT i.user_id, count(*) AS catalog_only_issues
FROM issues i
JOIN threads t ON t.id = i.thread_id
JOIN catalog_issues ci ON ci.id = i.catalog_issue_id
JOIN catalog_series cs ON cs.id = ci.catalog_series_id
JOIN external_identities e ON e.id = cs.canonical_external_identity_id
WHERE NOT EXISTS (
  SELECT 1 FROM issue_external_identity_mappings m
  WHERE m.issue_id = i.id AND m.status = 'confirmed'
)
GROUP BY i.user_id
ORDER BY i.user_id;

-- Catalog-only thread links: no confirmed thread series mapping.
SELECT t.user_id, count(*) AS catalog_only_threads
FROM threads t
JOIN catalog_series cs ON cs.id = t.catalog_series_id
JOIN external_identities e ON e.id = cs.canonical_external_identity_id
WHERE NOT EXISTS (
  SELECT 1 FROM thread_external_series_mappings m
  WHERE m.thread_id = t.id AND m.status = 'confirmed'
)
GROUP BY t.user_id
ORDER BY t.user_id;

-- Confirmed mapping whose canonical catalog identity disagrees, reported only.
SELECT i.id AS issue_id, t.user_id, ei.external_id AS confirmed_volume,
       e.external_id AS canonical_volume
FROM issues i
JOIN threads t ON t.id = i.thread_id
JOIN issue_external_identity_mappings m
  ON m.issue_id = i.id AND m.status = 'confirmed'
JOIN external_identities ei ON ei.id = m.external_identity_id AND ei.entity_type = 'series'
JOIN catalog_issues ci ON ci.id = i.catalog_issue_id
JOIN catalog_series cs ON cs.id = ci.catalog_series_id
JOIN external_identities e ON e.id = cs.canonical_external_identity_id
WHERE ei.external_id IS DISTINCT FROM e.external_id
ORDER BY t.user_id, i.id;
```

## Two-reader fixture parity evidence

Two synthetic-PostgreSQL fixture tests run against the canonical disposable
test schema (never production):

- `native/roll-service/src/option_inputs.rs` test
  `catalog_only_volume_evidence_survives_two_reader_parity`: runs the pre-change
  catalog branch as the "before" query and the current owner-scoped snapshot CTE
  as "after". It asserts every catalog-only volume key survives, confirmed
  series-entity and metadata-volume evidence is additive, and that eligible
  issue IDs, blockers, queue ordering, strict/loose/hold gates and exclusion
  results match expectations for two readers. A volume exclusion owned by
  reader A must not leak to reader B.
- `native/roll-service/src/issue_identity.rs` test
  `guard_state_preserves_confirmed_catalog_and_cross_reader_evidence`: exercises
  confirmed-mapping, catalog-only, missing-mapping and cross-reader isolation
  cases through `load_collection_guard_state` and `guard_check`.

These tests are additive; no existing assertion was weakened, skipped or given a
retry/timeout.

## Forward migration and cleanup

No forward migration or destructive cleanup is proposed in this PR. A
dependency-free cleanup and exact proposed forward migration are prepared only
after the census above and the #3231 rehearsal produce evidence that no
catalog-only links remain. Destructive production DDL/DML remains separately
authorized under #3232; agents have no production access and perform no
deletion. Coordination with #3676/#4255 (legacy/converted prerequisite
inertness) and #4022/#5840 (catalog identity consumers) is maintained without
changing those scopes.
