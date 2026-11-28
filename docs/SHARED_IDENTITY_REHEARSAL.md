# Shared-identity rehearsal and owner isolation on local PostgreSQL

<!-- docs-path-check: historical -->
**Issues:** #3231 (this rehearsal), #3221 (evidence migration, PR #5969), #3216 (parent decision)
**Status:** Evidence artifact. No production access, no schema change, no destructive DDL/DML, no
forward migration applied. Destructive cleanup remains separately authorized under #3232.
**Owner decision:** 2A (2026-11-27): global `external_identities` plus confirmed owner-scoped
mappings are the shared catalog. No catalog writers, no backfill, no staging flag.

## Rehearsal boundary

Every check ran against a **disposable local** PostgreSQL 16 database
(`127.0.0.1:5437/comic_pile_test`, started with `docker compose -f docker-compose.test.yml up -d
postgres-test`) through the canonical Rust test harness. `test_support` refuses any host other than
localhost/127.0.0.1/::1/unix socket and any database name that does not contain `test`; the test
role is DML-only and physically cannot create, alter or drop schema objects. No production or shared
database was contacted. Snapshot/session retention (#3229/#3230/#5886) is out of scope and does not
block this rehearsal.

## Two-reader fixture

Two readers confirm the **same** external issue identity (`comicvine:issue 4050-0001`) and reader B
also confirms a distinct edition (`4050-1001`); both reference the same catalog issue row while
owning different issue rows. Reader-specific state is deliberately disjoint:

| Reader-private state | Reader A | Reader B |
| --- | --- | --- |
| Issue IDs | 9201–9204 | 9401–9403 |
| Thread notes / last rating / queue position | `A private notes`, 4.0, 1 | `B private notes`, 3.0, 1 |
| Rating / roll events | 9801 (`rate` 4.0) | 9802 (`roll` 3.0) |
| Reading List mode and gate | `strict`, `after_previous` | `loose`, `hold` |
| Collection exclusion | `comicvine:4050-1000` | `comicvine:4050-2000` |
| Authored prerequisite | `reader` 9202 → 9204 | `reader` 9401 → 9402 |

Reader A also owns a **catalog-only** issue (9201, canonical identity but no confirmed mapping), a
**confirmed-mapping** issue (9203), and an issue with **no mapping and no catalog link** (9204).
Reader B owns the **distinct edition** (9403) and a confirmed metadata-volume issue (9402). This
covers every identity shape named in the acceptance contract.

## Tests and exact results

All commands were run from the repository root with
`RUST_ROLL_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5437/comic_pile_test`.

### New rehearsal coverage (`cargo test -p comicpile-roll-service --lib rehearsal_`)

Result: **6 passed; 0 failed; 0 ignored** (668 other tests filtered out).

| Test | What it proves |
| --- | --- |
| `option_inputs::tests::rehearsal_two_readers_keep_private_state_while_sharing_confirmed_identity` | Both readers confirm identity 8103 and share catalog issue 9001, yet issue IDs, notes, last rating, queue position, Reading List mode/gate, exclusion volume and authored prerequisite are disjoint. |
| `option_inputs::tests::rehearsal_before_after_eligibility_volume_and_blocker_parity` | The pre-#3221 catalog-only volume query ("before") is run literally on the fixture; every key survives the current owner-scoped snapshot CTE ("after"). Exact volume maps, excluded IDs (`A=[9201,9203]`, `B=[9403]`), unsatisfied edges, blocker shapes and eligible frontiers (`A=9202`, `B=9401`) are asserted. A's volume exclusion does not leak to B, whose issues carry the same volume. The unmapped issue gains no invented evidence; the distinct edition keeps its own key `comicvine:2000`. |
| `option_inputs::tests::rehearsal_card_projection_is_owner_scoped_confirmed_only_and_bounded` | One set-based call for a mixed batch returns only the caller's cards in first-request order. Catalog-only and missing-mapping cards are `unmapped` with no provider fields; confirmed cards expose only confirmed identity; A's rating never appears on B's card; the distinct edition stays separate. `validate_cards` rejects a 201-id batch. |
| `issue_identity::guard_db_tests::rehearsal_unknown_identity_fails_closed_and_queries_stay_bounded` | An unknown issue yields `collection_identity_requires_review` with no invented volume. A cross-reader shared catalog fact is not blocked by the other reader's exclusion. A `DbExec` counting wrapper shows 1 fact and 10 repeated facts execute an identical number of statements (≤ 8) — no N+1. |
| `issue_identity::guard_db_tests::rehearsal_rollback_restores_exclusion_state` | Adding a reader-B exclusion changes the guard decision to `collection_volume_excluded`; rolling the transaction back restores the original unexcluded decision. |
| `issue_duplicate_reconciliation::tests::rehearsal_same_owner_duplicate_is_not_a_cross_owner_shared_reference` | Same-owner duplicate pairs are detected exactly as `([9201,9202], "cv-issue:4050-0001")`; reader B's shared reference produces no pair and never appears in A's pairs. |

### Existing equivalent tests (reused, unchanged)

| Command | Result |
| --- | --- |
| `cargo test -p comicpile-roll-service --lib two_reader_parity` | 1 passed (`catalog_only_volume_evidence_survives_two_reader_parity`). |
| `cargo test -p comicpile-roll-service --lib cross_reader_evidence` | 1 passed (`guard_state_preserves_confirmed_catalog_and_cross_reader_evidence`). |
| `cargo test -p comicpile-roll-service --test creators_v2_http two_reader_shared_identity_creator_projection_is_owner_isolated` | 1 passed. |

The new creator HTTP test registers two users, maps both readers' issues to one external identity
carrying `creator_credits`, gives each a private rating, and adds a distinct edition for reader B.
It asserts both projections expose `creator:100` (shared provider metadata) while A sees rating 4.0,
B sees 2.0, A never sees B's `creator:200` edition, and coverage totals stay owner-scoped (A 1,
B 2). A catalog-only issue with no confirmed mapping contributes no creator.

### Rust gates

`cargo fmt --all` then `bash scripts/check-rust-factory-prepush.sh` (format check, Clippy with
`-D warnings`, `cargo check` for the service, migration runner and Vercel crate): **passed**.

No test was skipped, weakened, retried or given a timeout. No existing assertion was removed. The
fixture is recreated with `test_support::reset_for_test` and every read transaction is rolled back;
nothing persisted outside the disposable database.

## Rollback

- Each test holds the crate-wide canonical-schema lock and truncates application tables before
  seeding; afterward the next test resets them again.
- Guard and duplicate probes run inside read-only transactions and end with explicit `rollback()`.
- The exclusion rollback test intentionally writes inside a read-write transaction and rolls it
  back, then verifies the pre-transaction decision through a fresh read-only transaction.
- No migration file was added or edited; no schema is dropped, altered or created by any rehearsal
  step. Recovery is simply "the disposable database is discarded".

## Proposed forward migration and census (prepared, not applied)

The read-only census from `docs/CBL_CATALOG_CONSUMER_CENSUS.md` remains authoritative for consumer
inventory and unresolved-link reporting. The rehearsal adds these preconditions before any #3232
destructive operation:

1. Run the three owner-scoped census queries (catalog-only issues, catalog-only threads, confirmed
   vs canonical disagreement) against an **authorized disposable replica or export only**. Require
   zero catalog-only reader rows and zero confirmed/canonical disagreements, with counts recorded.
2. Require this rehearsal's exact before/after parity, owner isolation, duplicate and unknown-identity
   results to pass on the same pinned commit that is proposed for cleanup.
3. Proposed forward shape (no DDL/DML applied here): for each confirmed mapping already carrying the
   same canonical identity as the reader's catalog FK, drop only the redundant nullable FK columns
   `issues.catalog_issue_id` and `threads.catalog_series_id` and their indexes, after the census
   proves no reader row relies on a catalog-only link. Until then the bounded, owner-scoped read-only
   catalog fallback stays in `option_inputs.rs` and `issue_identity.rs`.
4. Keep `catalog_series` / `catalog_issues` identity evidence and all confirmed mappings intact;
   never derive identity by title or issue number. Any destructive apply, personal reader-data
   repair or snapshot purge requires the separate #3232 authorization with exact scope, pinned SHA,
   dry-run fingerprint, bounded batches, stop conditions, recovery plan and receipt.

## Out of scope

No production access, no destructive apply, no new catalog writer or backfill, no new schema
duplication, no shadow runtime, no automation/schedule change, no reading-session or snapshot
retention change. Out-of-scope discoveries remain recorded here rather than in a new ticket under the
Rust-cutover backlog freeze.
