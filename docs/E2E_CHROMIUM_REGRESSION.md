# Chromium regression discovery (scheduled + dispatch)

Issue: [#1483](https://github.com/JoshCLWren/comic-pile/issues/1483) (epic [#1476](https://github.com/JoshCLWren/comic-pile/issues/1476))

This is the inventory-driven Chromium regression lane. It runs daily and by explicit manual dispatch. The scheduled workflow is not a required pull-request gate. P0 is the high-trust core scope and must stay green when selected; `playwright.p0.config.ts` remains available for focused P0 reproduction.

## Coverage source of truth

`docs/e2e-behavior-inventory.yaml` maps covered behavior IDs to Playwright specs under `frontend/src/test/`. `scripts/e2e_regression_select.py` resolves a scope and fails closed when a covered behavior names a missing spec.

| Scope | Priorities | Use |
| --- | --- | --- |
| `p0` | P0 | Core-journey verification |
| `p1-p2` | P1, P2 | Default scheduled discovery |
| `all` | P0, P1, P2 | Complete inventory sweep |

The selector reports unmapped specs and skipped behaviors so inventory drift stays visible. Never edit statuses speculatively or delete a spec to get green.

## Local runtime contract

The application runtime is native Rust. Python is used only for repository tooling and the same-origin static/API ingress script; there is no FastAPI backend.

1. Claim a port slot under the local-factory worktree/port policy.
2. Create the Python tooling environment required by the selector (`uv venv && uv sync --all-extras`).
3. Start a disposable PostgreSQL database and apply every migration with `comicpile-migrate`.
4. Build the frontend.
5. Start the native service with `TEST_ENVIRONMENT=true`, a slot-specific loopback bind, and `RUST_ROLL_DATABASE_URL`/`RUST_ROLL_JWT_SECRET`.
6. Start `scripts/e2e_native_ingress.py` on the slot's browser origin. It proxies every `/api/*` request to native Rust and serves `static/react` for other paths.
7. Point `BASE_URL` at that ingress. Check native `/api/v2/health` directly and require an unauthenticated `/api/v2/threads` request through the ingress to return 401; ingress `/health` alone proves only static serving.

The exact slot-safe commands are in `.agents/skills/e2e-chromium-regression/SKILL.md`. Never point a test run at production or a shared reader database, and never pass Redis configuration; Redis is unused.

## Run a scope

From `frontend/` after the runtime is ready:

```bash
E2E_SELECTOR_PYTHON="$PWD/../.venv/bin/python" \
  node scripts/e2e-regression.mjs --scope p0 --list
E2E_SELECTOR_PYTHON="$PWD/../.venv/bin/python" \
  node scripts/e2e-regression.mjs --scope p0 --skip-build
E2E_SELECTOR_PYTHON="$PWD/../.venv/bin/python" \
  node scripts/e2e-regression.mjs --scope p1-p2 --skip-build
```

`make verify-e2e-regression SCOPE=...` is the root wrapper. Build first unless reusing a current per-worktree `static/react` build.

## CI workflow

`.github/workflows/e2e-chromium-regression.yml`:

- runs daily at 04:47 UTC and accepts manual `scope`/worker inputs;
- provisions one disposable PostgreSQL database;
- builds the frontend and native Rust service, applies refinery migrations, and starts native Rust plus `scripts/e2e_native_ingress.py` on `:9000`;
- pins `TEST_ENVIRONMENT=true` so native auth throttling uses the browser-test contract;
- selects specs from the canonical inventory and runs Chromium only; and
- uploads results, selection, traces/screenshots/video, and native/ingress logs for every run, including failures.

The workflow has `contents: read` only and never creates issues or applies issue/PR labels.

## Failure policy

P0 failures are owned repair work: reproduce with focused evidence and fix the product or test before pushing. P1/P2 failures are discovery signals. Preserve `frontend/test-results/regression/results.json`, `selection.json`, traces, screenshots, video, and native/ingress logs.

Reconcile failures against existing issues/PRs and group by root cause. The Rust-cutover backlog freeze prohibits creating a new issue or sub-issue without explicit owner authorization. Attach evidence to the existing canonical issue/PR and request a scope decision when new work is genuinely required. Never create one ticket per failed test.

Firefox and WebKit are optional diagnostics, not required release coverage.

## Maintaining the lane

- Inventory edits: run `tests/test_e2e_regression_select.py` and `--list` for every affected scope.
- Selector/config/workflow edits: validate the workflow YAML and the results walker against a real `results.json` (`suites[].specs[].tests[]`).
- After lane changes, run `--list` for every scope plus one real P0 run end to end.
- Use `/api/v2/dependencies/` for current dependency fixtures; v1 dependency instructions are retired.
