# Local HTTP traffic replay and CPU profiling

This is a draft, local-only profiling harness for [#4277](https://github.com/JoshCLWren/comic-pile/issues/4277). It helps determine which FastAPI paths spend actual Python CPU, instead of mistaking waits on Neon or HTTP latency for CPU usage.

## Prerequisites

- macOS (including Apple Silicon) or Linux with the repository's Python dependencies installed (including Uvicorn). On macOS the profiler uses the optional `psutil` package. Run with `uv run --with psutil python ...`.
- A **disposable, production-shaped copy** of ComicPile's database on **loopback PostgreSQL**, with schema migrations already applied. Do not point this harness at Neon or your working local database. You can use the repo's existing local-clone process to prepare an isolated copy.
- An existing login for the local test database. Provide its password via an environment variable, not the command line. Alternatively, provide an access token issued for that same local database and the current JWT signing key.
- A locally configured JWT secret and other normal backend settings. Do not use production secrets or credentials for this experiment.

The script rejects database connections outside localhost/127.0.0.1/::1, explicitly overrides DATABASE_URL and TEST_DATABASE_URL in the child process, listens on 127.0.0.1 only, and never sends replayed API requests to the HAR's original host. It runs the production-style FastAPI startup path against the **local-only database**, but disables the Neon monitor and selected third-party API credentials. A password-based setup generates **one ephemeral JWT signing secret shared across all replay subprocesses**. If providing a preexisting local access token instead, export the matching local SECRET_KEY explicitly. It does not intentionally access Vercel or Neon. Some app endpoints may independently call external services; keep provider credentials disabled or use a network-isolated container if complete offline execution is required.

## Run the basic profile

Set these two environment variables in your current shell (substitute your actual **local test** database URL and **local test** password):

- LOCAL_PROFILE_DATABASE_URL: e.g. postgresql+asyncpg://comicpile:comicpile_password@127.0.0.1:5435/comicpile_profile
- LOCAL_PROFILE_PASSWORD: the password of an existing user in that local database

Then, from the repository root, run:

    uv run --with psutil python scripts/profile_local_traffic.py --username YOUR_LOCAL_TEST_USERNAME

The harness starts a separate single-worker Python process for authentication setup. For each database-delay profile, it then starts one process for sequential cold/warm samples and another fresh process for the concurrent request burst. It does **not** start the normal four-worker Docker Compose service with auto-reload.

Defaults: 0, 100 and 500 ms simulated delay; 8 concurrent request workers; three isolated measurements per route. The built-in read-only GET route set includes auth/me, Roll bootstrap, threads, preferences, identity inbox and reading mode.

Reports and server logs go to a timestamped directory under .profile-local, which is gitignored. Files and directory permissions are restricted. The JSON report retains route paths but not query parameters, tokens, cookies, bodies, or actual HAR origins.

## Replay an existing Chrome HAR

Run:

    uv run --with psutil python scripts/profile_local_traffic.py --username YOUR_LOCAL_TEST_USERNAME --har /path/to/traffic.har --speed 10 --delays 0,100,500

This **does not play back browser writes**. It replays only GET requests under /api, strips original hosts, headers, cookies and auth, refuses URLs with sensitive query parameter names, and preserves the relative timing of eligible entries (accelerated by --speed). It uses the local login/token from the environment instead.

A HAR from production can reference issue/thread IDs that are not preserved in an imported local database. Such requests may return 404. Confirm the status column before attributing CPU to a successful operation. Use the built-in route workload when you do not have a suitable HAR.

You can also replay explicit safe routes (repeat --route):

    uv run --with psutil python scripts/profile_local_traffic.py --username YOUR_LOCAL_TEST_USERNAME --route /api/v1/auth/me --route /api/v1/roll/bootstrap --delays 0,50,250

## What is measured

The report shows:

- **Application startup CPU:** total user+system CPU for the single Uvicorn server process up to TCP readiness.
- **Cold auth request CPU:** process CPU between immediately before and after the first /auth/me request; this includes deferred import/router registration.
- **Isolated route CPU:** per-process CPU delta around one sequential GET, repeated several times. The last measurement is treated as a rough warm baseline.
- **Warm and fresh burst CPU:** CPU delta of the **whole server process** around a concurrent set of GET requests. The cold/fresh burst also reports CPU spent before listen separately.
- **Wall time, status, reported SQL query counts, and cold marker** per request.

Unlike ComicPile's existing process_time_ms log value, which is based on perf_counter(), this script reads **user+system CPU** from /proc/PID/stat on Linux or psutil on macOS. CPU sampling has limited granularity; very short requests may read as zero. Use multiple runs, reasonable datasets and medians before deciding what to optimize.

The database proxy adds a configurable delay **per TCP network chunk in both directions**, not per SQL statement. It approximates network RTT/wake latency and can intentionally cause timeouts with larger delays; it does not reproduce Neon exactly. If wall time rises while process CPU stays similar, the slower result is primarily waiting rather than CPU execution.

## Important limitations

1. A local single-worker process is not an exact replica of Vercel's scheduling, cold starts, memory provisioning, or billable Active CPU accounting.
2. Under concurrent requests, a process-wide CPU delta **cannot be attributed to individual requests**. The isolated route experiments are the per-route approximation; compare against observed request frequencies before estimating a monthly CPU bill.
3. This prototype replays GET traffic only. It **does not** simulate the full stateful rating/snooze/queue mutation workflow or transaction rollback. That requires a separately resettable fixture and a browser-driven scenario.
4. The harness does not create data snapshots, perform migrations, or copy production data. You must point it at a **disposable** local database with representative data.
5. For genuine CPU call-stack flamegraphs, run py-spy or a local cProfile investigation against the top-ranked paths after the initial data has identified them. This script measures CPU totals rather than profiling individual Python functions.

This is a draft measurement tool, not a production instrumentation change. See #4273 for the larger, whole-interaction billing attribution goal.

## Work Mac with existing Docker databases

Do **not** use port 5432 if it belongs to an unrelated `organizations_db` container. Use a **new named, disposable database** in a dedicated PostgreSQL container and bind it to loopback only, on a free high port such as 55435. Do not stop or change unrelated work containers. First confirm the port is free; then create a dedicated container and initialize its schema with the repository's migration workflow before profiling. The script will not create a database or fixture.
