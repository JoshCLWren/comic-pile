---
name: e2e-chromium-regression
description: Run, triage, and maintain the inventory-driven Chromium regression lane (P0 gate scope plus scheduled P1/P2 discovery). Use when running playwright.regression.config.ts or scripts/e2e-regression.mjs, when the e2e-chromium-regression workflow fails, when browser specs fail with 429/422/400/405 or missing roll regions, when changing docs/e2e-behavior-inventory.yaml, or when reconciling discovery failures into product issues.
---

# Chromium regression lane

Coverage source of truth is `docs/e2e-behavior-inventory.yaml`. Scopes: `p0` (PR-gate trust —
must stay green), `p1-p2` (default scheduled discovery — reds are catalogued, not auto-ticked),
`all`. Policy detail: `docs/E2E_CHROMIUM_REGRESSION.md`. Entry points:
`frontend/scripts/e2e-regression.mjs` and `make verify-e2e-regression SCOPE=...`.

## Local run contract

1. Test database:

   ```bash
   make docker-test-up   # Postgres 16 on :5437
   ```

2. Frontend build (skip only when reusing an existing `static/react` build):

   ```bash
   pnpm --filter frontend run build
   ```

3. Backend — **`TEST_ENVIRONMENT=true` is mandatory**. The rate-limit gate
   (`app/middleware/rate_limit.py`) only disables throttling in test mode; without it,
   fixture-speed traffic 429s the entire run. Never pass `REDIS_URL` (Redis is unused).

   ```bash
   SECRET_KEY=test-secret-key-for-testing-only TEST_ENVIRONMENT=true AUTO_BACKUP_ENABLED=false \
     DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5437/comic_pile_test \
     nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 9000 > /tmp/backend.log 2>&1 &
   curl -fsS http://127.0.0.1:9000/health
   ```

   uvicorn has no `--reload`: after any backend edit or rebase, kill the old process and
   restart it, or you are testing stale code.

4. Run:

   ```bash
   cd frontend
   node scripts/e2e-regression.mjs --scope p0 --list        # fail-closed manifest check
   node scripts/e2e-regression.mjs --scope p0 --skip-build  # 47 tests, must be green
   node scripts/e2e-regression.mjs --scope p1-p2 --skip-build
   ```

Evidence: `frontend/test-results/regression/results.json` (+ traces/screenshots/videos),
`/tmp/backend.log`, HTML report under `frontend/playwright-report/regression/`. The scheduled
workflow uploads `regression-results-*` / `regression-report-*` artifacts. The config refuses
to run without a selection manifest — that fail-closed behavior is intentional; fix the
selector or inventory instead of bypassing it.

## Scope rules

- **P0 failures are owned, not catalogued.** Reproduce (also against `playwright.p0.config.ts`
  to distinguish pre-existing rot from lane-caused), then fix specs or product before pushing.
  A red P0 scope blocks the change.
- **P1/P2 failures are discovery.** Group by root cause, reconcile against existing
  issues/PRs, and file **one** canonical issue with the full inventory table before creating
  normal product work (pattern: #3507 from #1483). Never skip or delete a spec to get green;
  never let the workflow grow issue-creation or label powers (`permissions: contents: read`).

## Triage playbook (verified failure classes)

| Signature | Cause / fix |
|---|---|
| Storm of 429s | Backend missing `TEST_ENVIRONMENT=true` |
| `POST /api/v1/dependencies/` 422 | Payload needs `source_type`/`target_type` (`'issue'`) |
| `set-pending` 400 "blocked by a dependency" | Product contract since #3359: `set-pending` the blocking thread, or assert the 400 + blocked-card UI |
| Roll heading count 0 (`Crossovers`, `Your Reading Boundaries`, `Continuity Correction`) | Optional-cards refactor: old `ReadingContextPillar`/`YourContextPillar`/`ReadingOrderGroups` are orphaned; live surface is `OptionalReadingCards` disclosures ("Reading Context (optional)"). Trace check: no `GET /reading-order-groups/threads/{id}/groups` call means context was never requested |
| Click timeouts on Queue/roll | Roll-nudge modal backdrop: `dismissRollNudgeIfPresent(page)` (helpers) |
| `nav` locator mismatches | `page.getByLabel('Desktop navigation')`, not `page.locator('nav')` |
| Auth error-copy selectors fail | `getByText(/incorrect username or password/i)` etc., not stale class selectors |
| Scroll-position `toBe` equality fails | Virtualization geometry; bound the assertion; `scrollAppUntil`/`scrollAppTo` in helpers |
| `set-die` 405 | Verify exact method/path against `app/api/roll.py` before blaming the backend |

Shared helpers live in `frontend/src/test/helpers.ts` (`waitForQueueReady`,
`dismissRollNudgeIfPresent`, `scrollAppUntil`); persistent vs `replyOnce` HTTP mocking layers
live in `frontend/src/test/auth-fixtures.ts`.

Trace forensics: unzip the per-test `trace.zip`; the `.network` file is JSONL — parse
`snapshot.request.url` / `snapshot.response.status` to see exactly which calls fired (or
didn't) before an assertion.

## Changing the lane itself

- Inventory edits: keep `tests/test_e2e_behavior_inventory.py` green; every covered behavior
  needs real spec mappings or it is skipped silently — check `selection.json`'s
  `unmapped_specs` and `skipped_behaviors`.
- Selector/config/workflow edits: `tests/test_e2e_regression_select.py`, validate the workflow
  YAML, and verify the step-summary failure walker against a real `results.json` (it must walk
  `suites[].specs[].tests[]`, not `suite.tests`).
- After any such change, re-run `--list` for every scope plus one real `p0` run end-to-end.
