# Local testing guide

## Never skip tests

Fix failing tests and their root cause. Never skip, disable or weaken a test to
make a run green, and never use CI as a substitute for a locally reproducible
check.

## Prerequisites

- Docker for disposable PostgreSQL/test stacks.
- Rust/Cargo, Node.js and pnpm for application builds/tests.
- Python 3.14 and uv for repository tooling tests and lint/type checks:

  ```bash
  make sync
  ```

There is no Python application runtime. The legacy Python API and
`tests_e2e/` pytest/Playwright suite were removed; `tests_e2e/README.md` only
points to the maintained TypeScript browser suite.

## What runs where

| Surface | Location | Focused local command |
| --- | --- | --- |
| Rust API behavior | `native/roll-service` | `cargo test -p comicpile-roll-service <filter>` |
| Frontend unit/contract | `frontend/src/unit`, colocated tests | `pnpm --filter frontend exec vitest run <file>` |
| Browser E2E | `frontend/src/test` | Playwright against a same-origin test ingress |
| Repository tooling | `tests/`, Node test files | `python3 -m pytest tests/<file>.py` or `node --test <file>` |

Full Rust/frontend suites and aggregate coverage run in CI. Use focused files or
cases locally.

## Local application database

```bash
make db-up        # PostgreSQL on host port 5435
make db-down      # stop without deleting data
set -a; . ./.env; set +a
make migrate
```

The migration runner reads `MIGRATE_DATABASE_URL`, falling back to
`DATABASE_URL`. The standalone native service reads `RUST_ROLL_DATABASE_URL` and
`RUST_ROLL_JWT_SECRET` directly; neither binary loads `.env` for you.

There is no seed command. Run `make dev`, register through the UI, or use the
read-only `/demo` fixture page.

## Browser test topology

Playwright expects one origin that serves both the built frontend and `/api`.
The standalone API on `:8010` is not that origin by itself.

### Docker nginx topology

```bash
make docker-test-up
BASE_URL=http://127.0.0.1:8000 pnpm --filter frontend run test:e2e:quick
make docker-test-down
```

`make docker-test-up` builds the frontend, applies migrations and starts native
Rust behind nginx on `:8000`, with PostgreSQL on `:5437`. The Compose file also
defines Redis, but the native runtime does not use it.

### Slot-safe regression topology

For parallel local sessions, follow
[`.agents/skills/e2e-chromium-regression/SKILL.md`](../.agents/skills/e2e-chromium-regression/SKILL.md).
It starts a slot-specific PostgreSQL database, native Rust and
`scripts/e2e_native_ingress.py`, then exports `BASE_URL` (default ingress
`:9000`). Set `TEST_ENVIRONMENT=true` so fixture-speed auth registration is not
throttled. Never use a production or shared database.

`make verify-e2e` and the direct Playwright configs do not set `BASE_URL` for
you. Set it to the origin actually serving the suite.

## Common commands

```bash
# Rust: focused module/test; full workspace suite runs in CI
cargo test -p comicpile-roll-service roll_offer

# Frontend: focused unit file
pnpm --filter frontend exec vitest run src/unit/queryKeys.test.ts

# Browser: build first, then run against the chosen BASE_URL
pnpm --filter frontend run build
pnpm --filter frontend exec playwright test --project=chromium

# Repository tooling: focused file
python3 -m pytest tests/test_markdown_docs.py -v

# Documentation mechanics
python3 scripts/check_markdown_docs.py
node scripts/check_doc_code_paths.mjs
```

## Rust request tests

DB-backed HTTP tests build the real router and call it with
`tower::ServiceExt::oneshot` against a disposable migrated PostgreSQL database.
Set `RUST_ROLL_TEST_DATABASE_URL`; missing configuration fails rather than
skipping. Every native route module requires such a test, enforced by
`node scripts/check_native_route_db_tests.mjs`.

## Frontend query tests

Unit tests mock the service layer with MSW and render through the shared
`QueryClient`. Follow the cache-effect and query-key rules in
[`docs/REACT_ARCHITECTURE.md`](docs/REACT_ARCHITECTURE.md).

## Troubleshooting

- **Native startup failure:** provide `RUST_ROLL_DATABASE_URL` and
  `RUST_ROLL_JWT_SECRET`; use a plain `postgresql://` URL for the standalone
  process and a loopback bind in development.
- **Migration URL missing:** export `.env` before `make migrate`.
- **Wrong browser origin:** confirm `BASE_URL` matches nginx/ingress, not the
  standalone `:8010` API.
- **429 during browser fixtures:** set `TEST_ENVIRONMENT=true` and do not opt
  back into rate limiting unless the test specifically covers it.
- **Port conflicts:** dev PostgreSQL 5435, test PostgreSQL 5437, Vite 5173,
  standalone API 8010, Docker nginx 8000, regression ingress 9000.
