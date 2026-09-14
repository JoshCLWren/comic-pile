# Reader Workflow Recovery — Temporary Resume Checklist

> Temporary handoff file created on 2026-09-12. Delete this file when the reader-workflow
> recovery is complete and the production cutover has been verified.

## Current production state (2026-09-13)

- Repository: `JoshCLWren/comic-pile`
- Tracking issue: #2482
- Migration implementation: PR #2485, merged as `d74fbc43433de9a5469e8cea5b573ea0fa3386fb`.
- Production-query chunking fix: PR #2498, merged as
  `caf2fed2a81e18aa0ada331faab58f767549daf0`.
- Replay-classification fix: PR #2499, merged as
  `c4d4f0655078a91d23e7bb2c36664e61a9abd0d5`.
- The guarded production batch **was applied** with explicit authorization. Eleven clean
  manifests created Reading Plans 21–31 and retired 119 `reading_plan_order` Dependencies.
- The receipt and verification artifacts are local at
  `/mnt/extra/josh/code/comic-pile-step27-operations/20260913T202907Z/`.
- The corrected post-apply replay reports 13 already migrated, 13 blocked by identity/source,
  3 behavior mismatches, and zero safe migrations left unapplied.
- This checkpoint is progress, not a claim that the feature is shipped.
- Runtime switch `LEGACY_DEPENDENCY_BLOCKING_ENABLED` remains enabled until the cutover
  audit proves every remaining `reading_plan_order` Dependency is gone (including dormant
  edges), every `needs_review`/unclassified row is cleared, and surviving standalones are
  canonically mirrored — not merely that today's `next_unread_issue_id` is unaffected.

### Applied production manifests

| Manifest | Plan ID | Dependencies retired |
| --- | ---: | ---: |
| Astro City | 21 | 10 |
| Black Panther: Priest | 22 | 1 |
| ClanDestine | 23 | 2 |
| Daredevil Crossovers | 24 | 4 |
| Hickman Stage 1 | 25 | 19 |
| JLI / Breakdowns | 26 | 52 |
| Majestic Recovery | 27 | 1 |
| Nova Annual | 28 | 2 |
| Planetary / Authority | 29 | 7 |
| Starlin Cosmic | 30 | 18 |
| WildC.A.T.s Satellite | 31 | 3 |

## Frozen architecture

- Reading Plan / `ContinuityPlan` is canonical reader-owned intent.
- CBL is source ordering and provenance, represented through a Reading Plan.
- Compiled continuity rules determine hard eligibility before Roll.
- Legacy `reading_plan_order` Dependencies are migration debris.
- Genuine standalone prerequisites remain valid.
- `DependencyGroupMembership.sequence_order` is not a Roll authority.
- Do not guess unresolved source identity or hand-code project-specific migrations.

## Implemented in this checkpoint

- [x] Generalized source-backed and explicitly classified reader-order migration specs.
- [x] Registered every canonical Step 14 explicit family exactly once.
- [x] Registered all canonical high-confidence CBL source hashes, including the group-16 source.
- [x] Made source matching fail closed when identity is absent or ambiguous.
- [x] Preserved standalone prerequisites and rejected `needs_review` intersections.
- [x] Preserved partial-order semantics instead of turning dependency graphs into total orders.
- [x] Added deterministic dry-run tokens and database-snapshot drift refusal.
- [x] Added a batch CLI that categorizes safe, blocked, already migrated, and standalone state.
- [x] Added exact-snapshot batch apply with a durable receipt staged before commit.
- [x] Added a cutover audit and guarded `LEGACY_DEPENDENCY_BLOCKING_ENABLED` runtime switch.
- [x] Added Roll regression tests showing canonical rules work with raw legacy blocking disabled.
- [x] Exposed Reading Plan CBL source paths in the list API.
- [x] Added persistent `New Reading Plan` and `Add from CBL` index actions.
- [x] Added CBL source discovery, preview, series choices, item overrides, stale-preview refresh,
      unresolved-item blocking, commit results, and canonical query-cache updates.
- [x] Preserved CBL provenance/reader metadata when a plan is edited and saved.
- [x] Replaced frontend implementation-first copy with Reading Plan product language.
- [x] Coordinator/batch status and receipt edge-case tests.
- [x] Explicit + source-backed `needs_review` intersection refusal regressions.
- [x] Integrated Step 23B legacy Reading Orders into the Step 27 batch as
      already-migrated / safe-to-migrate / blocked status (not a permanent exclusion).
- [x] Strengthened already-migrated proof (node set + compiled-rule / fingerprint checks).
- [x] Audited and fixed `get_blocking_explanations` / batch / `:getBlockingInfo` to use continuity
      blockers when the legacy switch is disabled (legacy rows only while the switch stays on).
- [x] Integrated backend golden path for missing-comic materialization, replay/idempotency,
      canonical reload/provenance, Roll eligibility, and no dependency-group execution state.
- [x] Focused Chromium Playwright coverage for strict CBL commit + Roll eligibility until earlier
      issue is read (plus `/api/test/cbl-source` seed).
- [x] CBL commit expands `series_group_id` decisions into per-position overrides.
- [x] Plan mutations invalidate Roll/Queue/session caches; index Add-from-CBL uses an explicit chooser.

## Validation completed for this checkpoint

- [x] Focused backend migration/cutover/API tests: 15 passed (prior checkpoint).
- [x] Focused frontend Reading Plan/CBL tests: 73 passed (prior checkpoint).
- [x] Full-repo `ruff check .` and `ty check --error-on-warning` passed (this turn).
- [x] Frontend typecheck passed (this turn).
- [x] Frontend lint passed with eight existing warnings and no errors (this turn).
- [x] Frontend production build passed (this turn).
- [x] Focused pytest for coordinator / blocking / CBL golden-path suites (this turn).
- [x] `cd frontend && pnpm test` passed (this turn).
- [x] Focused Chromium Playwright CBL golden-path spec passed against local TEST_ENVIRONMENT API.

## Remaining production cutover (operator-gated)

- [x] Run the batch dry-run against the real production snapshot using read-only access.
- [x] Apply all 11 clean manifests from their exact verified snapshots and save the receipt.
- [x] Replay the batch after apply and verify all 11 are idempotently `already-migrated`.
- [ ] Reconcile the 13 identity/source-blocked manifests without guessing:
      Alpha Flight, America's Best Comics, DC K.O., Doom Patrol, Fantastic Four Early Years,
      Fourth World, New Gods, Supreme, Teen Titans, Ultimate Universe, Unnamed Universe,
      Wolverine, and X-Men Era Ten.
- [ ] Resolve the three behavior mismatches before migration: Doctor Strange Epic Vol. 10,
      Starman Compendiums, and Starman/JSA Bridge.
- [ ] Classify or reconcile active `needs_review` Dependency 1929.
- [ ] Re-run dry-run/apply for newly clean manifests using exact snapshots and a new receipt.
- [ ] Prove the release condition before disabling legacy runtime blocking globally:
      every remaining `reading_plan_order` Dependency is gone or canonically represented,
      every `needs_review`/unclassified row is a hard stop, and surviving standalones have
      continuity mirrors (dormant debt still blocks; point-in-time Roll equality is extra).
- [x] Reconcile issue/PR factory labels after push and report exact production blockers.
- [ ] Delete this temporary file after the feature and production cutover are verified.

## Useful commands

```bash
git status --short
bash scripts/install-git-hooks.sh
bash scripts/check-python-ci-lint.sh
uv run pytest -o addopts='' \
  tests/test_reader_order_cutover.py \
  tests/test_reader_order_migration_coordinator.py \
  tests/test_blocking_explanations_legacy_cutover.py \
  tests/test_explicit_reader_order_migration.py \
  tests/test_source_backed_reader_order_migration.py \
  tests/test_reader_order_manifest_registry.py \
  tests/test_reading_plan_cbl_integrated_golden_path.py \
  tests/test_reader_workflow_legacy_order_compatibility.py \
  tests/test_canonical_reading_plan_1619.py -q
uv run python scripts/reader_order_migration.py --help
cd frontend && pnpm run lint && pnpm run typecheck && pnpm run build && pnpm test
cd frontend && pnpm exec playwright test src/test/reading-plan-cbl-golden-path.spec.ts --project=chromium
```

## Known cautions

- Do not run PostgreSQL-backed pytest processes concurrently; they share test database state.
- A focused Vitest projection test currently prints a harmless `Network Error` to stderr while
  passing; investigate before calling the full UI verification clean.
- The post-apply production cutover audit is current: 2,229 active `reading_plan_order`, 54 active
  `standalone_prerequisite`, and one active `needs_review` Dependency remain. There are no
  unclassified rows, no `sequence_order` blockers, and no missing/mismatched standalone mirrors.
- The current identity/source blockers are intentionally untouched. Most have unresolved CBL
  identity; DC K.O. and Ultimate Universe overlap existing plans/rules; Fantastic Four has source
  edges outside its source set; Fourth World still has generated reader-order rows inside the
  proposed plan. Consult the saved per-manifest snapshots for exact IDs and counts.
- The behavior mismatches are fail-closed: Doctor Strange and Starman/JSA would change Roll
  eligibility; Starman Compendiums does not exactly match the reviewed Step 23B issue set.
- The runtime switch must remain enabled until the cutover audit proves the release condition.
