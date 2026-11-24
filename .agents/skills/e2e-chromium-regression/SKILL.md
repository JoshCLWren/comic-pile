---
name: e2e-chromium-regression
description: Run, triage, and maintain the inventory-driven Chromium regression lane (P0 gate scope plus scheduled P1/P2 discovery). Use when running playwright.regression.config.ts or scripts/e2e-regression.mjs, when the e2e-chromium-regression workflow fails, when browser specs fail with 429/422/400/405 or missing roll regions, when changing docs/e2e-behavior-inventory.yaml, or when reconciling discovery failures into existing product work or owner-authorized issues.
metadata:
  opencode/slash: "true"
---

# Chromium regression lane

Coverage source of truth is `docs/e2e-behavior-inventory.yaml`. Scopes: `p0`
(PR-gate trust — must stay green), `p1-p2` (default scheduled discovery — reds
are catalogued, not auto-ticked), `all`. Policy detail:
`docs/E2E_CHROMIUM_REGRESSION.md`. Entry points:
`frontend/scripts/e2e-regression.mjs` and
`make verify-e2e-regression SCOPE=...`.

## Local run contract

Parallel local sessions share machine-global host ports and `/tmp` paths even
though Compose projects are per-directory. Claim a port slot first (see
`local-factory-next-task`): pick the smallest free N in 1–9 and export it for
the whole session.

1. Start a slot-specific disposable PostgreSQL database. Redis is not required:

   ```bash
   export E2E_POSTGRES_PUBLISH="$((5437+N)):5432"
   docker compose -f docker-compose.test.yml up -d postgres-test
   ```

2. Build the frontend unless you are deliberately reusing a current build in
   this worktree:

   ```bash
   pnpm --filter frontend run build
   ```

3. Apply migrations, start native Rust, and start the same-origin ingress. Use
   a plain PostgreSQL URL for the native service; it does not accept SQLAlchemy
   driver suffixes. `TEST_ENVIRONMENT=true` disables fixture-speed auth
   throttling unless a test explicitly opts back in.

   ```bash
   export E2E_NATIVE_PORT="$((8010+N))"
   export E2E_BACKEND_PORT="$((9000+N))"
   export BASE_URL="http://127.0.0.1:${E2E_BACKEND_PORT}"
   export E2E_TEST_DB_URL="postgresql://postgres:postgres@localhost:$((5437+N))/comic_pile_test"
   export E2E_NATIVE_LOG="/tmp/comicpile-e2e-native-${E2E_BACKEND_PORT}.log"
   export E2E_INGRESS_LOG="/tmp/comicpile-e2e-ingress-${E2E_BACKEND_PORT}.log"

   MIGRATE_DATABASE_URL="$E2E_TEST_DB_URL" \
     cargo run --locked -p comicpile-migrate -- up

   RUST_ROLL_DATABASE_URL="$E2E_TEST_DB_URL" \
   RUST_ROLL_JWT_SECRET="test-secret-key-for-testing-only" \
   RUST_ROLL_ENV=development RUST_ROLL_BIND="127.0.0.1:${E2E_NATIVE_PORT}" \
   TEST_ENVIRONMENT=true AUTO_BACKUP_ENABLED=false \
     nohup cargo run --locked -p comicpile-roll-service \
       > "$E2E_NATIVE_LOG" 2>&1 &

   NATIVE_ROLL_URL="http://127.0.0.1:${E2E_NATIVE_PORT}" \
   INGRESS_PORT="$E2E_BACKEND_PORT" \
     nohup python3 scripts/e2e_native_ingress.py \
       > "$E2E_INGRESS_LOG" 2>&1 &

   curl -fsS "${BASE_URL}/api/v2/health"
   ```

   All Playwright configs read `BASE_URL`. The ingress serves `static/react`
   and proxies every `/api/*` request to native Rust, matching production. The
   Python ingress helper is test tooling, not an application runtime. Restart
   the native process after backend edits or rebases; `cargo run` does not
   provide a production reload mechanism.

4. Run from the frontend package:

   ```bash
   cd frontend
   node scripts/e2e-regression.mjs --scope p0 --list
   node scripts/e2e-regression.mjs --scope p0 --skip-build
   node scripts/e2e-regression.mjs --scope p1-p2 --skip-build
   ```

Evidence: `frontend/test-results/regression/results.json` plus
traces/screenshots/videos, the slot-unique native and ingress logs, and the HTML
report under `frontend/playwright-report/regression/`. The scheduled workflow
uploads `regression-results-*` / `regression-report-*` artifacts. The config
refuses to run without a selection manifest; fix the selector or inventory
instead of bypassing it.

## Scope rules

- **P0 failures are owned, not catalogued.** Reproduce, then fix the spec or
  product before pushing. A red P0 scope blocks the change.
- **P1/P2 failures are discovery.** Group by root cause and reconcile against
  existing issues/PRs. The backlog freeze prohibits new issues or sub-issues
  without explicit interactive owner authorization. Never skip or delete a spec
  to get green; never let the workflow grow issue-creation or label powers
  (`permissions: contents: read`).

## Triage playbook (verified failure classes)

| Signature | Cause / fix |
|---|---|
| Storm of 429s | Native backend missing `TEST_ENVIRONMENT=true` |
| `POST /api/v2/dependencies/` 422 | Payload needs `source_type`/`target_type` (`'issue'`) |
| `set-pending` 400 "blocked by a dependency" | Product contract since #3359: `set-pending` the blocking thread, or assert the 400 + blocked-card UI |
| Roll heading count 0 (`Crossovers`, `Your Reading Boundaries`, `Continuity Correction`) | Optional-cards refactor: live surface is `OptionalReadingCards` disclosures ("Reading Context (optional)"). No `/reading-order-groups/threads/{id}/groups` call means context was never requested |
| Click timeouts on Queue/roll | Roll-nudge modal backdrop: `dismissRollNudgeIfPresent(page)` (helpers) |
| `nav` locator mismatches | `page.getByLabel('Desktop navigation')`, not `page.locator('nav')` |
| Auth error-copy selectors fail | `getByText(/incorrect username or password/i)` etc., not stale class selectors |
| Scroll-position `toBe` equality fails | Virtualization geometry; bound the assertion; `scrollAppUntil`/`scrollAppTo` in helpers |
| `dice-command` 405 | Verify exact method/path against `native/roll-service/src/lib.rs` before blaming the backend |

Shared helpers live in `frontend/src/test/helpers.ts` (`waitForQueueReady`,
`dismissRollNudgeIfPresent`, `scrollAppUntil`); persistent vs `replyOnce` HTTP
mocking layers live in `frontend/src/test/auth-fixtures.ts`.

Trace forensics: unzip the per-test `trace.zip`; the `.network` file is JSONL —
parse `snapshot.request.url` / `snapshot.response.status` to see exactly which
calls fired (or did not) before an assertion.

## Changing the lane itself

- Inventory edits: keep `tests/test_e2e_regression_select.py` green; every
  covered behavior needs real spec mappings. Check `selection.json` for
  `unmapped_specs` and `skipped_behaviors`.
- Selector/config/workflow edits: run
  `tests/test_e2e_regression_select.py`, validate the workflow YAML, and verify
  the step-summary failure walker against a real `results.json` (it must walk
  `suites[].specs[].tests[]`, not `suite.tests`).
- After such a change, re-run `--list` for every scope plus one real `p0` run
  end-to-end.
