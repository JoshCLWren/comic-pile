# ComicPile Performance Experiment Reconnaissance

Read-only repository reconnaissance, 2026-07-25.

## Executive summary

ComicPile is a FastAPI application deployed from a custom multi-stage Dockerfile.
The repository establishes CPython 3.14, uv 0.11.28, Uvicorn 0.44.0, two workers by
default, and async SQLAlchemy with asyncpg. The production database pool is small:
`pool_size=1`, `max_overflow=2`, `pool_timeout=30`, `pool_recycle=3600`, and
`pool_pre_ping=True` in `app/database.py`.

No repository load-test harness, profiler, metrics, tracing, successful-request timing,
query-count instrumentation, or pool-wait instrumentation was found. `/health` is the
only readiness-style route and executes `SELECT 1`.

The application is likely more database/pool/serialization-sensitive than interpreter-
CPU-sensitive for normal traffic. Pure-Python candidates exist in issue parsing,
dependency processing, queue logic, and session-summary construction, but none is proven
hot without profiling.

## Current deployment control

Evidence:

- `pyproject.toml`: `requires-python = ">=3.14"`; direct dependencies.
- `uv.lock`: `version = 1`, `revision = 3`, `requires-python = ">=3.14"`.
- `Dockerfile`: `python:3.14-slim`; uv `0.11.28`; Node `22.23.1-trixie-slim`; pnpm
  `10.15.0`; `uv sync --locked --no-dev`; Uvicorn start command.
- `Dockerfile.ci`: asserts Python 3.14.
- `railway.json`: Dockerfile builder using `Dockerfile`; no Railway start or healthcheck
  settings are committed.

Start command:

```text
/app/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 \
  --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2}
```

Known control values:

| Setting | Value |
|---|---|
| Python | CPython 3.14 from `python:3.14-slim` |
| uv | 0.11.28 |
| ASGI server | Uvicorn 0.44.0 |
| Workers | 2 unless `WEB_CONCURRENCY` overrides it |
| Host | `0.0.0.0` |
| Port | Railway `PORT`, fallback 8000 |
| Event loop | Not explicitly configured; uvloop is available through standard extras |
| HTTP parser | Not explicitly configured; httptools is available |
| Proxy headers | Not configured in repository |
| Keep-alive/timeouts | Uvicorn defaults; no overrides found |
| Health route | `GET /health` |
| Migration at startup | No; production startup skips table creation and migrations |

The application is created at import time by `app.main:app = create_app()`. Startup calls
`app.lifecycle.init_database`, which retries `SELECT 1` three times with a one-second delay.
Production skips `Base.metadata.create_all`. Frontend assets are checked during app creation.

The control must also fix the Railway region, CPU, memory, replicas/autoscaling, database
region/size, actual environment variables, image digest, healthcheck behavior, and traffic.
Those values cannot be determined from this repository.

## Runtime and dependencies

Locked direct production versions from `uv.lock`:

```text
fastapi 0.135.3              uvicorn 0.44.0
sqlalchemy 2.0.49            alembic 1.18.4
jinja2 3.1.6                 pydantic 2.12.5
python-multipart 0.0.26      psycopg 3.3.3
asyncpg 0.31.0               slowapi 0.1.9
python-dotenv 1.2.2          python-jose 3.5.0
bcrypt 5.0.0                 email-validator 2.3.0
pydantic-settings 2.13.1     filelock 3.25.2
PyGithub 2.9.0               pytest-xdist 3.8.2
PyYAML 6.0.3
```

Native/ABI-sensitive packages include asyncpg, psycopg-binary, bcrypt, cryptography,
cffi, greenlet, uvloop, httptools, pydantic-core, and PyYAML. The lock contains
implementation/platform markers for uvloop, cffi, pycparser, psycopg-binary, greenlet,
tzdata, and colorama. PyPy, GraalPy, and free-threaded CPython therefore require separate
wheel and dependency validation. No mypyc, Cython, Rust application extension, or custom
build system exists. `pyproject.toml` has no `[build-system]` section; uv represents the
project as `source = { virtual = "." }`.

The code uses `StrEnum`, PEP 604 unions, built-in generics, `datetime.UTC`, and
`zip(..., strict=True)`. These require Python 3.10/3.11 or newer, but no clearly
3.14-specific syntax was found. The project still enforces 3.14 in packaging, Docker, CI,
Ruff, and ty.

## Architecture and database

Application creation and route registration are in `app/main.py:create_app`. Middleware
registration is CORS, `SecurityHeadersMiddleware`, CSRF middleware, and error-only request
logging from `app/middleware/request_logging.py`. Exception handlers are registered by
`app/exception_handlers.py:register_exception_handlers`.

Authenticated requests generally pass through `app.auth:get_current_user`, which verifies
JWTs, checks `RevokedToken`, and looks up `User`. Database dependency injection is
`app.database:get_db`, backed by async SQLAlchemy:

```python
create_async_engine(
    ASYNC_DATABASE_URL,
    pool_recycle=3600,
    pool_size=1,
    max_overflow=2,
    pool_timeout=30,
    pool_pre_ping=True,
)
```

Sessions use `expire_on_commit=False` and close after request completion. Alembic uses
psycopg only in `alembic/env.py`; application access is asyncpg-only.

Important database-heavy paths include `app/api/session.py:get_current_session`,
`list_sessions`, `get_session_details`, `build_narrative_summary`, and `build_ladder_path`;
`app/api/rate.py:snapshot_thread_states`; broad admin exports; and dependency enrichment in
`app/api/dependency.py`. Several paths use `.scalars().all()` over historical or export data.
The repository has useful indexes on thread ownership/status/position, issue thread/position,
event session/time, session user/time, dependencies, and snapshots.

Two Uvicorn workers create two independent SQLAlchemy engines and pools, allowing up to six
database connections under the configured pool settings. Worker-count experiments therefore
also change database concurrency.

Railway database persistence and topology are not provable from the repository. The app has
no database volume; `docker-compose.prod.yml` only defines a local named PostgreSQL volume.
Using production `DATABASE_URL` for writes can mutate real users, queues, sessions, events,
and tokens. Use a cloned database/isolated Railway service for write tests. For read
tests, use a frozen benchmark user and GET-only routes.

## Endpoint candidates

Closest minimal route: `GET /api/auth/csrf`, handler
`app.api.auth:get_csrf_token`; it has no database query and requires no auth. It is not a
static route because middleware and FastAPI still run.

Other recommended workloads:

| Workload | Request | Handler | Safety |
|---|---|---|---|
| Readiness | `GET /health` | `app.main:health_check` | Safe; executes `SELECT 1` |
| Single record | `GET /api/threads/{id}` + bearer token | `app.api.thread:get_thread` | Read-only, but use isolated/frozen data |
| Typical list | `GET /api/threads/?page_size=50` + bearer token | `list_threads` | Read-only, frozen data recommended |
| Large list | `GET /api/v1/threads/{id}/issues?page_size=100` + bearer token | `list_issues` | Read-only, fixture thread recommended |
| CPU candidate | `GET /api/v1/threads/{id}/connected` + bearer token | `get_thread_connected_threads` | Profile first; isolated data recommended |
| DB-heavy | `GET /api/sessions/{id}/details` + bearer token | `get_session_details` | Multiple queries; isolated data recommended |
| Validation error | Malformed `POST /api/threads/` JSON | `create_thread` | Safe if validation fails before mutation |

All registered route modules are under `app/api/`: auth, threads, queue, roll, rate,
snooze, undo, sessions, analytics, admin exports/imports, bug reports, issues,
dependencies, reading orders, debug, and test helpers. `app/main.py` also registers
`/api/v1/sessions/*` as an alias for `/api/sessions/*`.

## CPU candidates

No profiling evidence establishes a hotspot. Candidates are:

- `app/utils/issue_parser.py:parse_issue_ranges` — pure-Python range parsing/expansion;
  covered by `tests/test_issue_parser.py` and CSV tests.
- `app/api/dependency.py:get_thread_connected_threads` — dependency aggregation;
  covered by `tests/test_dependency_api.py`.
- `app/api/dependency.py:check_thread_dependency_order` — ordering analysis;
  covered by dependency API tests.
- `app/api/session.py:build_narrative_summary` and `build_ladder_path` — event grouping and
  path construction; covered by history/session tests.
- `app/api/thread.py:_threads_to_responses` — bulk issue mapping and response-model
  construction; covered by thread/API tests.
- `app/api/issue.py:_assign_issue_positions` — issue position recalculation; covered by
  issue and queue tests.

These are better selective-compilation candidates than SQLAlchemy route code, but only after
input-size-aware profiling.

## Runtime assessment

| Candidate | Feasibility | Assessment |
|---|---|---|
| Current CPython 3.14 | High | Required control |
| Uvicorn/worker changes | High | Directly relevant; worker changes multiply DB pools |
| Newer ordinary CPython | Medium | Requires new Docker/lock/CI validation; relevance unknown |
| CPython JIT | Low/medium | Custom image and native-wheel validation; low relevance before profiling |
| Free-threaded CPython | Low/medium | asyncpg, bcrypt, greenlet, Uvicorn, and ABI validation required |
| PyPy | Low | Native packages and uvloop compatibility are significant blockers |
| GraalPy | Low | Native extension and ABI compatibility blockers |
| mypyc selected modules | Medium | Plausible for typed parser/graph helpers; no build setup exists |
| Cython/Rust extraction | Medium | Possible but premature without a measured hotspot |
| Alternative ASGI server | Medium | Test only with equivalent lifespan, parser, loop, and proxy behavior |

Use separate branches and likely separate lockfiles for non-CPython variants. Do not combine
runtime, server, dependency, and application changes in one experiment.

## Existing testing and observability

There are 78 backend test files under `tests/`, frontend Vitest tests under
`frontend/src/unit/`, and TypeScript Playwright tests under `frontend/src/test/`. Playwright
supports Chromium, Firefox, and WebKit. `tests/conftest.py` provides async PostgreSQL engines,
transaction rollback fixtures, and `get_db` overrides. CI checks migrations and a 94% backend
coverage threshold.

Existing observability is limited to:

- `/health` database check;
- error-only request logs with `process_time_ms` in `app/middleware/request_logging.py`;
- Python application logs;
- Railway dashboard metrics, which must be inspected externally.

There is no existing load test, benchmark, profiler, metrics exporter, tracing, successful
request timing, query-count instrumentation, pool-wait measurement, or response-size metric.

## Recommended harness and procedure

Use k6 or wrk2 from a fixed external host, preferably in the same region as an isolated Railway
service. Obtain one bearer token before each run using a dedicated benchmark user; do not load
the login route during steady-state tests. Use fixed keep-alive behavior and record status,
latency, bytes, and route for every request.

Suggested concurrency levels are 1, 2, 4, 8, 16, and 32. Use a 2–5 minute warm-up, a five-
minute measured period, and at least three repetitions. Use a 10-second timeout for ordinary
reads and 30 seconds for broad session/export routes. Emit JSON and CSV.

Record commit SHA, image digest, Python/runtime, Uvicorn settings, database identity, Railway
region/resources, row counts, timestamps, warm-up duration, load-generator version, errors,
and status distribution. Capture Railway CPU/memory graphs and deployment/restart events.

Use the proposed sequence exactly:

```text
Control -> Experiment A -> Control -> Experiment B -> Control -> Experiment C -> Control
```

Each control should be a fresh deployment of the control image. Separate cold-start tests from
warm steady-state tests. For JIT runtimes, report warm-up curves separately.

## Prioritized experiment matrix

| ID | Experiment | Independent variable | Priority |
|---|---|---|---|
| M1 | External latency harness | Measurement tooling | P0 |
| M2 | Query/pool instrumentation | Temporary instrumentation | P0 |
| M3 | Repeated-control variance | None; repeated control | P0 |
| M4 | Cold versus warm protocol | Test phase | P0 |
| S1 | One versus two workers | `WEB_CONCURRENCY` | P1 |
| S2 | asyncio versus uvloop | Event loop | P1 |
| S3 | httptools versus h11 | HTTP parser | P2 |
| S4 | Alternative ASGI server | Server | P2 |
| C1 | Newer ordinary CPython | Python image/version | P2 |
| C2 | CPython JIT | Interpreter build | P3 |
| C3 | Free-threaded CPython | Interpreter ABI | P4 |
| R1 | PyPy | Runtime implementation | P3 |
| R2 | GraalPy | Runtime implementation | P4 |
| K1 | mypyc issue parser | Selected module compilation | P3 |
| K2 | mypyc dependency helpers | Selected module compilation | P3 |
| K3 | Cython/Rust helper | Native extraction | P4 |
| A1 | Session query reduction | Query shape | P2, only after profiling |
| A2 | Dependency graph optimization | Pure-Python algorithm | P2, only after profiling |
| A3 | Issue parser optimization | Parser algorithm | P3, only after profiling |
| A4 | Response construction optimization | Serialization path | P3, only after profiling |

Do not combine optimizations until each is measured independently.

## Unknowns requiring Railway inspection

Railway dashboard/environment inspection is required for actual region, CPU, memory,
replicas/autoscaling, `WEB_CONCURRENCY`, `LOG_LEVEL`, database endpoint/region/size/limits,
proxy behavior, healthcheck frequency, restart history, current image digest, production
migration state, traffic volume, and availability of an isolated benchmark environment.

## Machine-readable summary

```json
{
  "control": {
    "python": "CPython 3.14 from python:3.14-slim",
    "build_command": "Railway Dockerfile builder; uv sync --locked --no-dev; pnpm --filter frontend run build",
    "start_command": "/app/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2}",
    "asgi_server": "uvicorn 0.44.0",
    "workers": 2,
    "event_loop": null,
    "http_parser": null,
    "database": "PostgreSQL",
    "database_driver": "asyncpg 0.31.0",
    "pool_settings": {"pool_size": 1, "max_overflow": 2, "pool_timeout": 30, "pool_recycle": 3600, "pool_pre_ping": true},
    "health_route": "/health"
  },
  "benchmark_routes": [
    {"workload": "minimal framework/server overhead", "method": "GET", "path": "/api/auth/csrf", "handler": "app.api.auth.get_csrf_token", "auth_required": false, "read_only": true, "safe_for_production_load_test": true, "notes": "Closest lightweight route; no DB query."},
    {"workload": "readiness", "method": "GET", "path": "/health", "handler": "app.main.health_check", "auth_required": false, "read_only": true, "safe_for_production_load_test": true, "notes": "Executes SELECT 1."},
    {"workload": "small single-record read", "method": "GET", "path": "/api/threads/{thread_id}", "handler": "app.api.thread.get_thread", "auth_required": true, "read_only": true, "safe_for_production_load_test": false, "notes": "Use frozen benchmark data."},
    {"workload": "typical list", "method": "GET", "path": "/api/threads/?page_size=50", "handler": "app.api.thread.list_threads", "auth_required": true, "read_only": true, "safe_for_production_load_test": false, "notes": "Includes response construction."},
    {"workload": "large paginated list", "method": "GET", "path": "/api/v1/threads/{thread_id}/issues?page_size=100", "handler": "app.api.issue.list_issues", "auth_required": true, "read_only": true, "safe_for_production_load_test": false, "notes": "Requires a large fixture thread."},
    {"workload": "CPU-heavy read candidate", "method": "GET", "path": "/api/v1/threads/{thread_id}/connected", "handler": "app.api.dependency.get_thread_connected_threads", "auth_required": true, "read_only": true, "safe_for_production_load_test": false, "notes": "Profile before treating as CPU-heavy."},
    {"workload": "database-heavy read", "method": "GET", "path": "/api/sessions/{session_id}/details", "handler": "app.api.session.get_session_details", "auth_required": true, "read_only": true, "safe_for_production_load_test": false, "notes": "Multiple queries."},
    {"workload": "validation-error path", "method": "POST", "path": "/api/threads/", "handler": "app.api.thread.create_thread", "auth_required": true, "read_only": false, "safe_for_production_load_test": false, "notes": "Malformed payload must fail before mutation."}
  ],
  "runtime_candidates": [
    {"name": "CPython 3.14 control", "feasibility": "high", "blockers": [], "required_changes": [], "relevance": "Required baseline", "confidence": "high"},
    {"name": "Uvicorn/server configuration", "feasibility": "high", "blockers": ["Workers multiply DB pools"], "required_changes": ["Change WEB_CONCURRENCY or explicit server options"], "relevance": "Directly relevant", "confidence": "high"},
    {"name": "Newer ordinary CPython", "feasibility": "medium", "blockers": ["Docker, CI, project metadata, and lock target 3.14"], "required_changes": ["New image and validated lock"], "relevance": "Unknown until profiling", "confidence": "medium"},
    {"name": "CPython JIT", "feasibility": "low", "blockers": ["Custom interpreter image", "native-wheel validation"], "required_changes": ["Custom Python build"], "relevance": "Low before CPU profiling", "confidence": "low"},
    {"name": "Free-threaded CPython", "feasibility": "low", "blockers": ["Native extension and ABI compatibility"], "required_changes": ["Free-threaded image and lock"], "relevance": "Low for async I/O", "confidence": "low"},
    {"name": "PyPy", "feasibility": "low", "blockers": ["asyncpg", "bcrypt", "greenlet", "uvloop"], "required_changes": ["Separate lock resolution"], "relevance": "Only for proven pure Python hotspot", "confidence": "low"},
    {"name": "GraalPy", "feasibility": "low", "blockers": ["Native extension compatibility"], "required_changes": ["Custom image and lock"], "relevance": "Low", "confidence": "low"},
    {"name": "mypyс selected modules", "feasibility": "medium", "blockers": ["No mypyc build setup"], "required_changes": ["Compile profiled helpers"], "relevance": "Parser/graph helpers", "confidence": "medium"},
    {"name": "Alternative ASGI server", "feasibility": "medium", "blockers": ["ASGI lifespan and comparability"], "required_changes": ["Server command and dependencies"], "relevance": "Server-only experiment", "confidence": "medium"}
  ],
  "cpu_candidates": [
    {"file": "app/utils/issue_parser.py", "symbol": "parse_issue_ranges", "reason": "Range parsing and expansion", "pure_python": true, "typed": true, "request_path": true, "tests": ["tests/test_issue_parser.py", "tests/test_csv_import.py"]},
    {"file": "app/api/dependency.py", "symbol": "get_thread_connected_threads", "reason": "Dependency aggregation", "pure_python": true, "typed": true, "request_path": true, "tests": ["tests/test_dependency_api.py"]},
    {"file": "app/api/dependency.py", "symbol": "check_thread_dependency_order", "reason": "Dependency/order analysis", "pure_python": true, "typed": true, "request_path": true, "tests": ["tests/test_dependency_api.py", "tests/test_dependencies.py"]},
    {"file": "app/api/session.py", "symbol": "build_narrative_summary", "reason": "Groups session events", "pure_python": true, "typed": true, "request_path": true, "tests": ["tests/test_history.py", "tests/test_session_history_integration.py"]},
    {"file": "app/api/thread.py", "symbol": "_threads_to_responses", "reason": "Response-model construction", "pure_python": true, "typed": true, "request_path": true, "tests": ["tests/test_thread_api.py"]},
    {"file": "app/api/issue.py", "symbol": "_assign_issue_positions", "reason": "Issue position recalculation", "pure_python": true, "typed": true, "request_path": true, "tests": ["tests/test_issue_api.py"]}
  ],
  "unknowns": ["Railway region", "CPU/memory allocation", "replicas/autoscaling", "actual WEB_CONCURRENCY", "database region/size/limits", "proxy/cache behavior", "healthcheck frequency", "restart history", "production traffic", "current image digest", "production migration state", "isolated benchmark environment"]
}
```
