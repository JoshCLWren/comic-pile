# Native Roll service

Independent Rust/Axum service foundation for #4302, part of #4299. It serves
`GET /health`, stable JSON errors, and a bounded lazy PostgreSQL pool. The CPU
spike at `experiment/native-rust-cpu-spike-20261029:scripts/rust_cpu_spike/`
proved the Axum/native runtime; its partial last-read handler is deliberately
not promoted as a working bootstrap endpoint. Auth and complete owner-scoped
Roll behavior arrive through #4303–#4310 using the **existing OpenAPI contract**
(`frontend/src/generated/openapi.json`), Python behavior oracle #4301, and
parity gates #4311. A bootstrap request currently gets 404, never partial JSON.

## Build and test

Install rustup, the platform C compiler, pkg-config and OpenSSL development
headers. Commands run from `native/roll-service`; `rust-toolchain.toml` pins
Rust 1.85.0 including rustfmt/clippy, and Cargo.lock pins all dependencies.
Cargo's resolver selects dependencies compatible with that minimum Rust version.

```sh
cargo fmt --all --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked --all-targets
cargo build --release --locked
```

The `Native Rust Roll` GitHub Actions job runs these checks and publishes the
Linux x86_64 release binary. It does not deploy previews or change ingress.
The standalone binary is `target/release/comicpile-roll-service` and depends
on the build platform's OpenSSL/runtime libraries. It is not a Vercel function;
provider selection and actual ingress verification belong to #4313.

## Configuration

Use process environment or a local secret manager. Do not put secret values
in command arguments, commits, logs, issue comments or fixtures.

| Variable | Required/default | Meaning |
| --- | --- | --- |
| RUST_ROLL_ENV | development | development or production |
| RUST_ROLL_BIND | 127.0.0.1:8010 | Socket address; development rejects non-loopback binds |
| RUST_ROLL_DATABASE_URL | required | Native postgres URI, **without** SQLAlchemy's `+asyncpg`; production requires `sslmode=require` |
| RUST_ROLL_JWT_SECRET | required | Same signing secret as Python when authenticated handlers are enabled; no insecure default |
| RUST_ROLL_LOG | info | Valid tracing filter; output is structured JSON |
| RUST_ROLL_POOL_SIZE | 4 | Maximum concurrent PostgreSQL connections, range 1–32 |
| RUST_ROLL_POOL_TIMEOUT_MS | 2000 | Wait/create/recycle timeout, range 1–30000 ms |
| RUST_ROLL_REQUEST_TIMEOUT_MS | 10000 | Request deadline, range 1–60000 ms |

Defaults only expose a loopback listener. Production requires explicit environment
selection, provider binding and credential provisioning; this task provisions none.
TLS uses the native trust store with certificate/hostname verification enabled;
no invalid-certificate bypass exists. The pool opens connections lazily, so process
startup and health do not depend on PostgreSQL availability. Health is liveness,
not database readiness. Pool checkout failure is bounded; query/statement timeout
and auth-specific outage mapping are subsequent handler work, not implicit retries.

SIGINT/SIGTERM stops accepting new connections and drains ongoing work under the
request deadline, then closes the pool. A hard drain deadline of request timeout
plus one second bounds shutdown even for connections still sending headers. Request timeout cancels the handler future
and returns HTTP 503 `{"detail":"Request timed out"}`. Later mutation handlers must
use transactions and cancellation-safe rollback; this foundation performs no writes.
404/405 also return the Python-style `detail` envelope. Startup failures report
static descriptions only; dependency errors are never serialized.

Logs contain method, status, elapsed milliseconds and a listener address. They
omit URI/query, headers, tokens, database config and upstream error text. Config
and credential-bearing state deliberately do not derive Debug. Integration tests
send secret canaries through headers/query and assert they never appear in process
logs; they prove health with an unreachable DB and successful SIGTERM shutdown.
Additional network tests stall a real PostgreSQL handshake to prove the configured
create timeout, finish an in-flight HTTP handler during drain, enforce the hard
drain deadline for stuck work, and hold incomplete HTTP headers during SIGTERM.

## Routing and rollout

There is no public route switch, deployment environment, CORS policy, auth
substitute or Python reverse proxy here. Existing Python routes continue serving
Roll. The complete native bootstrap must pass JSON/status/state parity,
performance, frontend/E2E, exact-head CI and Greptile 5/5 gates before #4313 can
review deployment and exercise ingress rollback. Never route public bootstrap
traffic to this foundation's 404.

## Authentication and owned reads

`auth::AuthenticatedUser` is an Axum extractor with an opaque identity. It
verifies HS256 access credentials, optional NumericDate claims, JTI revocation,
user existence and the password-change epoch using Python's current semantics.
There is no disabled-user column in the canonical Python model. Refresh tokens
are rejected; authentication neither rotates cookies nor creates reading history.
The signing secret must match Python's `SECRET_KEY` before any future integration.

`db::require_owned_thread` and `db::require_owned_session` require that verified
identity and scope SQL by `user_id`. Missing and foreign rows both return 404.
These are foundations for later Roll handlers; no new public probe or partial
bootstrap endpoint is mounted. Reading-history sessions do not authenticate users.

Pool acquisition and query execution have bounded deadlines with no automatic
retries. Completed queries return connections to the pool; canceled/timed-out
queries discard the physical connection so pending PostgreSQL work cannot leak
into subsequent requests. Query/programming errors stay 500, while connection,
resource and pool failures return the sanitized Python database-unavailable 503
envelope and `Retry-After: 30`. Credentials and dependency messages are never logged.

Tests require a **disposable local PostgreSQL** connection (the Rust SQL tests use
connection-local temporary tables and never alter application tables):

```sh
export RUST_ROLL_TEST_DATABASE_URL=postgresql://localhost/native_auth_test
cargo test --locked --all-targets
```

Missing test configuration fails instead of silently skipping integration tests.
CI provisions PostgreSQL. `tests/fixtures/roll-v2/auth-matrix.json` is consumed by
both Rust integration tests and `tests/test_native_auth_matrix.py`, pinning valid
credentials and exact auth rejection status/detail/challenge across languages.
Python tests use the existing isolated database fixtures. Run them with the
repository's disposable `TEST_DATABASE_URL` and `DATABASE_URL`, never a live library.
