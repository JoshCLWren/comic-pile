# Local Testing Guide

## 🚫 CORE PRINCIPLE: NEVER SKIP TESTS

**TESTS MUST NEVER BE SKIPPED - EVER.**

When running tests locally:
- ✅ Fix failing tests before moving on
- ✅ Investigate root causes
- ❌ **NEVER skip tests to save time**
- ❌ **NEVER ignore test failures**

Local testing is your opportunity to catch issues before they reach CI. Take advantage of it.

## What runs where

Comic Pile has no Python application runtime. Testing is split across three
surfaces:

| Surface | Location | Command |
| --- | --- | --- |
| Rust API behavior | `native/roll-service` (unit + DB-backed HTTP tests) | `cargo test -p comicpile-roll-service <filter>` |
| Frontend unit/contract tests | `frontend/src/unit`, colocated `*.test.ts(x)` | `pnpm --filter frontend exec vitest run <file>` |
| Browser E2E (Chromium) | `frontend/src/test` (Playwright, TypeScript) | `BASE_URL=http://localhost:5173 make verify-e2e` |
| Repository tooling | `tests/` (pytest, Node test files) | `uv run python -m pytest tests/test_<name>.py` |

The legacy Python pytest/Playwright suite under `tests_e2e/` was removed with
the Python API. `tests_e2e/README.md` now only points at the maintained
browser suite.

## Quick start

### 1. Local database

```bash
make db-up        # PostgreSQL on host port 5435
make db-down      # stop it without deleting data
```

The local defaults in `.env.example` already point at this database. The
migration runner reads `MIGRATE_DATABASE_URL`, falling back to `DATABASE_URL`;
load `.env` into the shell first, because neither the Make targets nor the Rust
binaries read `.env` themselves:

```bash
set -a; . ./.env; set +a
make migrate
```

For repository tooling tests or git hooks, create the Python environment once
with `uv venv && uv sync --all-extras`. The running application does not need it.

### 2. Create an account instead of seeding

There is no seed command. Start the app with `make dev`, then register through
the UI to create a user and queue. The read-only guest Demo page at `/demo`
serves fabricated fixtures and writes nothing.

### 3. Run the API for browser tests

Playwright specs run against a same-origin server. For the normal development
path, start Vite and the native service together with `make dev`, then point
Playwright at `http://localhost:5173`. Vite proxies `/api` to the native service.

To run only the native API directly against a disposable database (for focused
HTTP testing, not browser E2E), apply migrations first and run:

```bash
RUST_ROLL_BIND=127.0.0.1:8010 \
RUST_ROLL_DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5437/comic_pile_test" \
RUST_ROLL_JWT_SECRET="test-secret-key-for-testing-only" \
cargo run --locked -p comicpile-roll-service
```

`make docker-test-up` builds the frontend and starts the maintained same-origin
test topology (PostgreSQL on 5437, the native service behind nginx on 8000). Use
`BASE_URL=http://localhost:8000 make verify-e2e` with that topology. See
[`docs/E2E_CHROMIUM_REGRESSION.md`](docs/E2E_CHROMIUM_REGRESSION.md) for the full
ingress contract and the inventory-driven regression lane.

### 4. Run tests

```bash
# Rust: one focused test or module
cargo test -p comicpile-roll-service roll_offer

# Frontend: one focused file
pnpm --filter frontend exec vitest run src/unit/queryKeys.test.ts

# Browser: Chromium Playwright (builds first; requires a running same-origin server)
BASE_URL=http://localhost:5173 make verify-e2e

# Repository tooling: one test file
uv run python -m pytest tests/test_markdown_docs.py -v
```

Full suites run in CI. Run only the files or cases that cover your change
locally, plus focused regressions for a bug you are fixing.

## Common patterns

### Rust request test

Handler tests build the router from `native/roll-service/src/lib.rs` and call it
with `tower::ServiceExt::oneshot`. Every native route module is expected to have
a DB-backed HTTP test; the `native-route-db-test-guard` CI job enforces that
coverage with `node scripts/check_native_route_db_tests.mjs`.

```rust
let response = app
    .clone()
    .oneshot(Request::builder().uri("/api/v2/health").body(Body::empty())?)
    .await?;
assert_eq!(response.status(), StatusCode::OK);
```

### Frontend query test

Unit tests mock the service layer with `msw` and render through the shared
`QueryClient`. Follow the cache-effect and query-key rules in
[`docs/REACT_ARCHITECTURE.md`](docs/REACT_ARCHITECTURE.md).

## Troubleshooting

**Native service exits at startup?**
- It requires `RUST_ROLL_DATABASE_URL` and `RUST_ROLL_JWT_SECRET`. It does not
  read `.env`.
- `RUST_ROLL_DATABASE_URL` must be a plain `postgresql://` URL (no `+asyncpg`).
- In development the bind address must be loopback.

**Migrations say "set MIGRATE_DATABASE_URL or DATABASE_URL"?**
- Export the environment first: `set -a; . ./.env; set +a`.

**Database connection errors?**
- Ensure PostgreSQL is running (`make db-up`) and the URL points at port 5435.

**Port conflicts?**
- Dev PostgreSQL 5435, test PostgreSQL 5437, local native API 8010, Vite 5173.
  The Docker test topology serves the frontend through nginx on 8000.
