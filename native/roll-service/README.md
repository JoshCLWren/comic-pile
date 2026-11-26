# Native Roll service

This is the deployed native Rust/Axum API service. It owns authentication, Roll,
Queue, Reading List, ComicVine, and the other product routes registered in
`native/roll-service/src/lib.rs`. The Vercel entrypoint `api/native_api.rs` and
the standalone binary use the same service/router.

See [docs/API.md](../../docs/API.md),
[docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md), and
[docs/READING_LIST_RUNTIME.md](../../docs/READING_LIST_RUNTIME.md) for current
behavior. Earlier #4302–#4314 Python-parity instructions are historical and were
removed with the Python application; they are not commands to run.

## Build and test

Install rustup, the platform C compiler, pkg-config, and OpenSSL development
headers. The root `rust-toolchain.toml` selects the workspace toolchain, and the
root `Cargo.lock` pins one dependency graph for the service, Vercel ingress, and
migration runner.

From the repository root:

```sh
cargo fmt --all -- --check
cargo clippy --workspace --locked --all-targets -- -D warnings
cargo test --locked -p comicpile-roll-service <focused-filter>
cargo build --release --locked -p comicpile-roll-service
```

Run focused package/module tests locally. Full workspace suites remain a CI gate
unless explicitly requested. CI does not deploy Vercel Preview environments or
change ingress.

The workspace target directory is the repository-root `target/`. When building
from another working directory, set an absolute `CARGO_TARGET_DIR`; Cargo resolves
a relative value against the current working directory.

## Configuration

Use process environment or a local secret manager. Do not put secret values in
command arguments, commits, logs, issue comments, or fixtures.

| Variable | Default | Meaning |
| --- | --- | --- |
| `RUST_ROLL_ENV` | `development` | `development` or `production` |
| `RUST_ROLL_BIND` | `127.0.0.1:8010` | Socket address; development rejects non-loopback binds |
| `RUST_ROLL_DATABASE_URL` | required | Plain native PostgreSQL URI; production requires `sslmode=require` |
| `RUST_ROLL_JWT_SECRET` | required | JWT signing secret; the Vercel entrypoint may fall back to `SECRET_KEY` |
| `RUST_ROLL_LOG` | `info` | Structured tracing filter |
| `RUST_ROLL_POOL_SIZE` | `4` | Maximum PostgreSQL connections, range 1–32 |
| `RUST_ROLL_POOL_TIMEOUT_MS` | `2000` | Pool wait/create/recycle timeout, range 1–30000 ms |
| `RUST_ROLL_REQUEST_TIMEOUT_MS` | `10000` | Request deadline, range 1–60000 ms |

The standalone native binary does not load `.env` and does not normalize
SQLAlchemy URL prefixes. Production requires explicit environment selection and
credentials. TLS uses the native trust store with certificate and hostname
verification; there is no invalid-certificate bypass.

The pool opens connections lazily, so startup and liveness do not prove database
readiness. Pool checkout and request deadlines are bounded, and handler writes
are not implicitly retried. SIGINT/SIGTERM stops accepting connections, drains
work under the request deadline, and closes the pool.

Logs contain method, status, elapsed time, and listener address. They omit URI
query strings, headers, tokens, database configuration, and upstream error text.
Configuration and credential-bearing state do not derive `Debug`.

## Routing and authentication

The standalone service mounts the same native router used by
`api/native_api.rs`. Production Vercel ingress sends `/api/*` to the Rust
entrypoint; there is no Python fallback. Current auth routes publish v2,
retained v1, and unversioned aliases. Registration/login issue bearer access
tokens and refresh cookies; refresh rotates credentials, logout revokes them,
and the access-token extractor rejects refresh tokens.

`auth::AuthenticatedUser` verifies HS256 access credentials, expiry, string
subject/jti, token type, revocation, user existence, and the password-change
credential epoch. Reading-history `ReadingSession` rows are not login
credentials. `db::require_owned_thread` and
`db::require_owned_reading_session` scope SQL by `user_id`; missing and foreign
rows both return 404.

See [docs/API.md](../../docs/API.md) for route families and
[docs/rate_limiting.md](../../docs/rate_limiting.md) for authentication
throttling and durable lockout.

## Health and database readiness

The service exposes dependency-free liveness at `GET /health` and
`GET /api/v2/health`. Neither opens a database connection. Production deployment
checks also verify runtime/build/process identity; use a real authenticated data
request or the migration planner when database readiness must be proven.

See [docs/OPERATIONAL_HEALTH.md](../../docs/OPERATIONAL_HEALTH.md) and
[docs/VERCEL_ARCHITECTURE.md](../../docs/VERCEL_ARCHITECTURE.md).

## Database-backed tests

Tests require a disposable local PostgreSQL database:

```sh
export RUST_ROLL_TEST_DATABASE_URL=postgresql://localhost/native_auth_test
cargo test --locked -p comicpile-roll-service <focused-filter>
```

The shared Rust test harness applies every tracked migration automatically and
truncates/reseeds application tables between cases. Missing test configuration
fails instead of silently skipping integration tests. Never point
`RUST_ROLL_TEST_DATABASE_URL` at production or a shared reader database.

CI runs `scripts/check_native_route_db_tests.mjs` so every native route module
has a PostgreSQL-backed HTTP test.

## Write-handler test rule

Every mounted POST handler must have a disposable-PostgreSQL test that executes
the real write path and resulting rows, not only auth, request-shape, or read
helpers. The #4423 production failure shipped because the offer suite never ran
its INSERT.
