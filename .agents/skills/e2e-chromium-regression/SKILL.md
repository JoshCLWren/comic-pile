---
name: e2e-chromium-regression
description: Run, triage, and maintain the inventory-driven Chromium regression lane (P0 core scope plus scheduled P1/P2 discovery). Use when running playwright.regression.config.ts or frontend/scripts/e2e-regression.mjs, when the E2E Chromium Regression workflow fails, or when changing docs/e2e-behavior-inventory.yaml.
metadata:
  opencode/slash: "true"
---

# Chromium regression lane

Coverage source of truth: `docs/e2e-behavior-inventory.yaml`. Scopes: `p0`, `p1-p2` (scheduled default), and `all`. Policy and CI details: `docs/E2E_CHROMIUM_REGRESSION.md`.

## Slot-safe local runtime

Parallel sessions share host ports. Claim the smallest free slot `N` under the local-factory port policy and keep every port/log slot-specific.

1. Disposable PostgreSQL:

   ```bash
   export E2E_POSTGRES_PUBLISH="$((5437+N)):5432"
   docker compose -f docker-compose.test.yml up -d postgres-test
   export E2E_TEST_DB_URL="postgresql://postgres:postgres@localhost:$((5437+N))/comic_pile_test"
   MIGRATE_DATABASE_URL="$E2E_TEST_DB_URL" cargo run --locked -p comicpile-migrate -- up
   ```

2. Build and start native Rust plus the same-origin ingress:

   ```bash
   pnpm --filter frontend run build
   export E2E_NATIVE_PORT="$((8010+N))"
   export E2E_BACKEND_PORT="$((9000+N))"
   export BASE_URL="http://127.0.0.1:${E2E_BACKEND_PORT}"
   nohup env TEST_ENVIRONMENT=true RUST_ROLL_ENV=development \
     RUST_ROLL_BIND="127.0.0.1:${E2E_NATIVE_PORT}" \
     RUST_ROLL_DATABASE_URL="$E2E_TEST_DB_URL" \
     RUST_ROLL_JWT_SECRET="test-secret-key-for-testing-only" \
     cargo run --locked -p comicpile-roll-service \
     > "/tmp/opencode/comicpile-e2e-native-${E2E_NATIVE_PORT}.log" 2>&1 &
   nohup env NATIVE_ROLL_URL="http://127.0.0.1:${E2E_NATIVE_PORT}" \
     INGRESS_PORT="$E2E_BACKEND_PORT" python3 scripts/e2e_native_ingress.py \
     > "/tmp/opencode/comicpile-e2e-ingress-${E2E_BACKEND_PORT}.log" 2>&1 &
   deadline=$((SECONDS + 60))
   until curl -fsS "http://127.0.0.1:${E2E_NATIVE_PORT}/api/v2/health" >/dev/null; do
     if (( SECONDS >= deadline )); then
       echo "Native service did not become ready; inspect the slot-specific log." >&2
       exit 1
     fi
     sleep 1
   done
   curl -fsS "http://127.0.0.1:${E2E_NATIVE_PORT}/api/v2/health"
   test "$(curl -s -o /dev/null -w '%{http_code}' "${BASE_URL}/api/v2/threads")" = 401
   ```

   `TEST_ENVIRONMENT=true` is mandatory: it disables native in-process auth throttling for fixture-speed browser traffic. `RUST_ROLL_DATABASE_URL` is the single DB pin — a plain `postgresql://` URL. Do not add a second DB variable or a SQLAlchemy driver prefix; Python is only the static/API ingress and tooling runtime; never start `uvicorn app.main:app`. Restart the native process after Rust changes.

3. Run the inventory lane from `frontend/`:

   ```bash
   cd frontend
   export E2E_SELECTOR_PYTHON="$PWD/../.venv/bin/python"
   node scripts/e2e-regression.mjs --scope p0 --list
   node scripts/e2e-regression.mjs --scope p0 --skip-build
   node scripts/e2e-regression.mjs --scope p1-p2 --skip-build
   ```

Evidence: `frontend/test-results/regression/results.json`, `selection.json`, traces/screenshots/video, and the slot-specific native/ingress logs. The config fails closed without a selection manifest; repair the selector/inventory rather than bypassing it.

## Scope rules

- P0 failures are owned repair work and block the change when that scope is run.
- P1/P2 failures are discovery signals. Reconcile against existing issues/PRs and attach evidence there. The backlog freeze prohibits new issues/sub-issues without explicit owner authorization; never create one ticket per failed test.
- Never skip/delete a spec, add retries/sleeps, or weaken assertions to get green. The workflow keeps `contents: read` and has no issue/label powers.

## Triage playbook

| Signature | Cause / check |
|---|---|
| Storm of 429s | Native backend missing `TEST_ENVIRONMENT=true` |
| `POST /api/v2/dependencies/` 422 | Payload needs current `source_type`/`target_type` (`issue`) fields |
| Roll heading count 0 | Inspect optional-reading-card disclosures and the network ledger; do not resurrect retired pillars |
| Queue/roll click timeout | Dismiss the Roll-nudge modal with `dismissRollNudgeIfPresent` |
| `nav` locator mismatch | Use `page.getByLabel('Desktop navigation')` |
| Auth copy selector failure | Match the current error text, not stale CSS classes |
| Scroll equality failure | Account for virtualization geometry; use shared scroll helpers |
| `dice-command` 405 | Verify exact method/path in `native/roll-service/src/lib.rs` |

Shared helpers: `frontend/src/test/helpers.ts` and `auth-fixtures.ts`. For trace forensics, parse `.network` JSONL request/status records before asserting what the client called.

## Changing the lane

- Inventory edits: run `tests/test_e2e_regression_select.py` and `--list` for every affected scope.
- Selector/config/workflow edits: validate YAML and the step-summary walker against real `results.json` (`suites[].specs[].tests[]`).
- After lane changes, run `--list` for all scopes and one real P0 run end to end.
