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

`db::require_owned_thread` and `db::require_owned_reading_session` require that verified
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

### Core scalar reading loader (#4304)

`reading_inputs::load_core_inputs` requires an opaque authenticated identity and
uses two parameterized bulk SELECTs inside a bounded repeatable-read, read-only
transaction. It includes inactive threads, empty threads, and read issues. Threads
are ordered by identity; issues by thread, natural position, then identity. Queue
position, stored next-issue pointers and blocked flags are retained as diagnostics,
never used to choose eligibility. Missing or cross-thread pointers fail closed;
failed or canceled transactions discard their physical pool connection.

The local parity example is a CLI only, with no public HTTP route. On a disposable
PostgreSQL database (schema creation privileges required):

```bash
cd native/roll-service
cargo build --locked --example reading_snapshot
cd ../..
PYTHONPATH=. uv run pytest native/roll-service/parity/test_core_inputs.py -q -s --no-cov
```

Set `RUST_ROLL_TEST_DATABASE_URL` to that disposable database. The test creates and
removes a unique synthetic schema, compares scalar identity/status/order and stored
queue diagnostics with Python `load_shadow_inputs`, and injects invalid pointers
only inside that schema. Both loaders use read-only repeatable-read transactions.
The test prints Python oracle CPU/wall time and native child-process CPU/wall time;
the latter includes startup and authentication. These are diagnostic timings, not
equivalent-workload performance claims (#4312 owns that gate). The native loader
uses two data queries plus BEGIN/ROLLBACK; authentication queries are additional.
Exclusions, volume resolution, lists and prerequisites remain scoped to #4305.

### Complete Option E input loader (#4305)

`option_inputs::load_option_inputs` reads the core scalars and remaining constraints
in one bounded, repeatable-read, read-only transaction. Nine bulk data queries
cover owned lists/curated placements, reader prerequisites, confirmed and catalog
volume evidence, per-list overlap decisions, durable exclusions and catalog issue
volumes. No historical dependency, stored frontier or blocked flag chooses
eligibility. No production route exposes these intermediate inputs.

Volume exclusion matching intentionally differs from overlap resolution: any
confirmed/catalog identity can match an exclusion, while an overlap requires
exactly one distinct Comic Vine series key. Candidate mappings are ignored.
Numeric `4050-` IDs lose leading zeroes without machine-integer overflow;
provider names use Unicode case folding. Missing or ambiguous volume evidence
stays unknown. Entries preserve skipped/hold/after_previous intent and repeated
issue placements across different lists.

The execution loader rejects unresolved references. The explicitly diagnostic
`load_option_diagnostics` preserves owned entry/dependency IDs for parity tools;
never feed that unchecked result into an eligibility evaluator. Foreign object
metadata is never loaded, and every execution consumer must use the checked
loader. The checked execution loader also enforces the global cycle-validation gate below.

With a disposable local PostgreSQL URL in `RUST_ROLL_TEST_DATABASE_URL`:

```sh
cargo build --locked --examples
cd ../..
PYTHONPATH=. uv run pytest native/roll-service/parity/ -q -s --no-cov
```

The Option E parity test creates/drops a unique schema, loads the same synthetic
records through Python and Rust, and compares every constraint and diagnostic.
It includes conflicting and equivalent volume mappings, canonical issue volumes,
strict/loose lists, curated insertion order, duplicate placements, skipped gates,
read inactive prerequisite sources, historical dependencies, foreign exclusions,
and prerequisites touching a foreign account in either direction. It performs
no production reads or writes. An existing private real-data snapshot is not
bundled; no assertion here claims verification against production records.

### Global stored-constraint validation (#4306)

`load_option_inputs` now returns `ValidatedReadingInputs`, whose private constructor
state can only be obtained after reference checks and global cycle validation.
Candidate projection must consume this checked type. Diagnostic snapshots remain
available solely for parity tooling. No endpoint or production routing is changed.

`reading_constraints::validate` ports Python's natural series order, strict/loose
lists, hold and after_previous gates, exact per-list volume overlaps, and explicit
prerequisites. Read and excluded issues remain in the graph; skipped placements
are omitted. Missing references and stranded prerequisite sources fail closed.
It returns stable minimum-ID topological order or a concrete cycle with origins
and prerequisite provenance. Unknown list names use stable numeric labels; the
adapter accepts an optional list-name map for reader-facing explanations. Public
HTTP failures remain generic and do not expose graph contents.

The topology and residual cycle walk are iterative. Strict order uses the same
transitive reduction as Python, keeping ordinary long lists linear in edge count.
The offline `constraint_validation` example reads sanitized JSON lines from stdin;
it needs no database, credentials or Python subprocess at runtime.

```sh
cargo build --locked --examples
cd ../..
PYTHONPATH=. uv run pytest native/roll-service/parity/test_constraint_validation.py -q --no-cov
```

CI automatically runs this matrix in the existing native parity lane. It compares
complete order/error/path/provenance payloads against Python across 250 seeded
cross-list graphs, corrupt inputs, and 20,000-entry acyclic and residual-cycle
fixtures. Existing database loader parity verifies owner scoping and ignored
historical dependencies before this pure validator runs.

## Native reading-session bootstrap (#4307)

`reading_session::bootstrap` is an authenticated internal service entry point for
response assembly. It is deliberately not mounted as a partial public bootstrap
endpoint. Pass a validated `SessionPolicy` with the Python backend's
`SESSION_GAP_HOURS` and `START_DIE` settings (defaults 6 hours and d6). The injectable
`bootstrap_at` clock exists for deterministic parity; production callers use
`bootstrap`. The runtime image must include IANA `tzdata` at `/usr/share/zoneinfo`,
the same database used by Python `ZoneInfo`.

The read-only `resolve_current_session` accepts a caller-owned transaction. It
includes recent event and pending-issue activity, prefers pending work, and uses
activity/start/id tie breakers. Bootstrap holds Python's per-user advisory
transaction lock, rechecks authority, initializes missing bandwidth once, and
creates a full-library session-start snapshot in the same commit as the new
session. It preserves initialized/manual bandwidth, intent, pending context,
snoozes/skips, and the suspended automatic die. Browser timezone is captured only
when absent, after the checkpoint, as in Python. It never writes roll/rate/cancel
events, issue status, thread queue positions, or snoozes.

History-based bandwidth uses bounded batched owner-scoped queries, observed
issue/thread median precedence, confirmed identity era fallbacks, and the Python
v1 inference rules. A savepoint permits the same neutral balanced fallback when
inference fails without committing an aborted transaction. Deadlock retries are
bounded to three attempts inside one overall deadline. Failed/cancelled work
discards the connection, rolling back session and checkpoint together.

`parity/test_session_bootstrap.py` runs Python and Rust on the same seeded initial
state in a unique disposable schema, rolls back Python, then compares every
persisted session field and snapshot payload. It tests fresh/reused/expired
sessions, pending context, recent cancellation activity, cutoff equality,
manual/automatic dice, modes, timezone validation, observed/era bandwidth,
foreign/missing session IDs, repeated GETs, concurrent first creation, checkpoint
failure, and request cancellation before commit. It also asserts threads,
issues, and events remain unchanged. Timestamp spelling is normalized; values,
nulls, ordering, and state are not discarded. No production data is used.

```sh
cargo build --locked --examples
PYTHONPATH=. uv run pytest native/roll-service/parity/test_session_bootstrap.py -q --no-cov
```

Run the Python command from the repository root with
`RUST_ROLL_TEST_DATABASE_URL` pointing at disposable PostgreSQL, as in CI. The
existing Native Rust Roll workflow discovers this parity file automatically.
Full response projection, recovery, and routing remain the separately scoped
#4308–#4314 work; no production routing or preview deployment changes are made.
