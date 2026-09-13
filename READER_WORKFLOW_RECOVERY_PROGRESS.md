# Reader Workflow Recovery — Temporary Resume Checklist

> Temporary handoff file created on 2026-09-12. Delete this file when the reader-workflow
> recovery is complete and the production cutover has been verified.

## Working state

- Repository: `JoshCLWren/comic-pile`
- Branch: `manual/2482-explicit-reader-order-migration`
- Pull request: #2485
- Tracking issue: #2482
- Starting `main`: `ade255f207d816f30ddd25da9ce32c8c91ac7328`
- Production was **not** mutated during this work.
- This checkpoint is progress, not a claim that the feature is shipped.
- Runtime switch `LEGACY_DEPENDENCY_BLOCKING_ENABLED` remains enabled until the cutover
  audit proves: no active reader project requires a legacy `reading_plan_order` Dependency.

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
- [x] Confirmed legacy Reading Order import remains on Step 23B / `from-reading-order`, not the
      Step 27 Dependency-debris batch path.
- [x] Audited and fixed `get_blocking_explanations` / batch / `:getBlockingInfo` to use continuity
      blockers when the legacy switch is disabled (legacy rows only while the switch stays on).
- [x] Integrated backend golden path for missing-comic materialization, replay/idempotency,
      canonical reload/provenance, Roll eligibility, and no dependency-group execution state.
- [x] Focused Chromium Playwright coverage for index → create plan → CBL discovery → series
      choice → individual override → commit → canonical result (plus `/api/test/cbl-source` seed).

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

- [ ] Run the batch dry-run against the real production snapshot using read-only access.
- [ ] Do not apply the production batch without explicit user authorization.
- [ ] Prove the release condition before disabling legacy runtime blocking globally:
      no active reader project requires a legacy `reading_plan_order` Dependency.
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
- The historical audit found active legacy reader-order state and `needs_review` rows, but that is
  not a current production observation. The production batch dry-run is the source of truth.
- The runtime switch must remain enabled until the cutover audit proves the release condition.
- Prior push of `fa2235f4f` was interrupted mid pre-push suite; remote may still lag local HEAD
  until a complete hook-backed push succeeds.
