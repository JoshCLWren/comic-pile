# ComicPile FastAPI Database Round-Trip Audit

## Executive summary

ComicPile's current performance bottleneck is primarily excessive sequential database round trips rather than raw Python compute. Controlled benchmarking against the production Neon database showed:

- persistent `SELECT 1` p50: approximately **34 ms**
- new connection + `SELECT 1` p50: approximately **408 ms**
- `GET /api/v1/roll/bootstrap` sequential p50 from a home Debian host: approximately **813 ms**
- `roll/bootstrap` commonly lands around **0.8–1.5+ seconds** outside the warm Vercel path

A powerful home machine and a tiny GCP `e2-micro` produced broadly similar bootstrap latency, while warm Vercel was substantially faster. That strongly indicates network round-trip count and connection reuse are the highest-value application-level levers.

This document is a corrected canonical summary of the August 2026 local API audit. Static query counts below are estimates until proven by runtime query-count instrumentation. SQLAlchemy identity-map behavior and conditional branches can make some static counts lower or higher in practice.

## Highest-priority findings

| Priority | Endpoint / area | Estimated problem | Target |
|---|---|---|---|
| P0 | `GET /api/v1/roll/bootstrap` | Roughly 25–35 sequential SQL trips on common/conditional paths | 1–3 bootstrap DB trips after auth |
| P0 | `POST /api/v1/roll/` | Repeated session/die/pool/thread work | Materially reduce sequential trips while preserving transaction correctness |
| P1 | `GET /api/v1/sessions/current/` | Re-resolves session, die, active thread and related state | 1–2 DB trips after auth |
| P1 | `GET /api/v1/sessions/{id}/details` | Multiple helper-driven reads for one response | 1–3 DB trips after auth |
| P1 | Rate / snooze / undo | Re-read state after mutation plus per-thread/per-issue work | Bulk operations and fewer re-fetches |
| P1 | Continuity/readiness graph | Broad snapshot loaded through multiple separate queries | Load once per request, bounded and reusable |
| P1 | Per-thread issue helpers | N+1 unread counts and next-issue metadata | Constant-query bulk loaders |
| P1 | Authentication | Two sequential DB reads before endpoint logic | Measure and safely reduce if possible |
| P1 | SQLAlchemy pooling on Vercel | Pool size 1, overflow churn, pre-ping cost may hurt Fluid concurrency | Benchmark small pool variants without increasing memory |

## `roll/bootstrap` canary

The bootstrap path is the clearest example of the problem. The request currently composes many reusable helpers that each perform their own database work. The observed/static call chain includes:

1. authenticated-user resolution
2. authoritative current-session resolution
3. session refresh/re-resolution
4. active or pending thread resolution
5. current die resolution
6. roll-recovery / continuity readiness
7. roll-pool query
8. dependency route labels
9. snoozed-thread summaries
10. blocked count and blocked rows
11. stale count and oldest stale row

Continuity readiness is particularly expensive because the current snapshot loader reads threads, issues, dependency groups, memberships, continuity rules, and selected members through multiple separate bounded queries.

At a measured persistent Neon RTT of roughly 34 ms, even ten strictly sequential trips cost roughly 340 ms in network time before meaningful database or Python work. Twenty-five trips can account for roughly 850 ms of network waiting. This matches observed bootstrap latency surprisingly well.

The desired redesign is a purpose-built read projection rather than a chain of general domain helpers. Use SQLAlchemy Core, CTEs, aggregates, JSON/array aggregation, or another explicit projection shape to return the first Roll screen in one or a very small number of database conversations.

Do not blindly copy prototype SQL from the original local audit. Build the final query from the actual response contract and validate it with tests and `EXPLAIN (ANALYZE, BUFFERS)`.

## N+1 and duplicate-work patterns

The audit identified several recurring patterns worth removing across hot endpoints:

- `Thread.get_issues_remaining(db)` can issue one unread-count query per thread.
- next-unread issue metadata can be loaded one thread at a time.
- session state is sometimes selected, refreshed, and then passed to helpers that resolve the same state again.
- response builders can perform `db.get(Thread, ...)` or similar lookups inside loops.
- full snapshot/state capture can load issues separately for each thread.
- continuity/readiness can rebuild the same broad graph snapshot more than once in a request path.

Preferred replacements are grouped counts, `WHERE ... IN (...)` metadata loads, bounded projection queries, and explicit reuse of already-loaded ORM state where correctness allows it.

## Authentication overhead

Every authenticated endpoint currently performs two database reads before its own route logic:

1. revoked-token lookup by JTI
2. user lookup by username

At approximately 34 ms RTT, that can represent roughly 68 ms of network waiting before a hot endpoint begins its own database work.

This is systemic, but it is not the first optimization to ship. Any change must preserve token verification, logout/revocation behavior, user deletion/disable semantics, multi-instance behavior, and user scoping. Candidate approaches such as embedding stable user identity in the signed token or short-TTL revocation caching must be measured and threat-modeled rather than applied casually.

## SQLAlchemy / Neon connection behavior

ComicPile creates one module-level async SQLAlchemy engine per Python process. The current configuration is approximately:

```python
pool_size=1
max_overflow=2
pool_pre_ping=True
pool_recycle=3600
```

The application already uses Neon's pooled hostname, so the effective path is:

```text
FastAPI / SQLAlchemy application pool
    -> asyncpg client connections
    -> Neon pooled endpoint (PgBouncer)
    -> Postgres
```

The application pool and Neon pool solve different problems. Do not replace SQLAlchemy pooling with `NullPool`, a singleton physical connection, or another PgBouncer layer.

The current configuration may be inefficient on Vercel Fluid Compute because only one connection is retained in the normal pool while overflow connections can be created under concurrency and later discarded. `pool_pre_ping=True` may also add a checkout round trip.

Do not jump to a generic pool size such as 10–20. Benchmark small controlled variants such as pool size 1, 2, and 3, reduced/no overflow, and pre-ping on/off while keeping function memory unchanged. The smallest stable low-latency configuration should win.

## Existing indexes

The schema already contains useful indexes for the dominant thread and issue predicates, including composite thread indexes for user/status/blocked/queue position and issue indexes for thread/status/position. The primary bottleneck is therefore not obviously missing indexes.

Potential index changes should only be made after query consolidation and only when `EXPLAIN (ANALYZE, BUFFERS)` demonstrates a real plan problem. Areas worth checking include latest-event/current-die access paths and revoked-token JTI lookup, but no index should be added based only on static speculation.

## Frontend fanout

The Roll frontend already has a bootstrap API, which is the correct high-level direction. The major problem is that the backend bootstrap handler internally fans out into many database operations. Secondary Roll-side requests for reading-order, connected-thread, or dependency data should be reviewed after the bootstrap projection is fixed, but they are not the first-order latency problem.

## Factory execution issues

The audit has been decomposed into focused factory-ready issues:

- #1254 Reduce `roll/bootstrap` to 1–3 database round trips
- #1255 Reduce `POST /roll` database round trips and duplicate session work
- #1256 Build efficient current-session and session-details read projections
- #1257 Eliminate per-thread issue-count and issue-metadata N+1 queries
- #1258 Make continuity graph loading bounded and reusable per request
- #1259 Reduce database round trips in rate, snooze, and undo mutation paths
- #1260 Measure and tune SQLAlchemy pooling for Vercel Fluid Compute
- #1261 Reduce authenticated-request database overhead

Recommended execution order:

1. #1254
2. #1257 and #1258
3. #1260
4. #1255 and #1256
5. #1259
6. #1261

## Validation rule

No performance optimization should merge based on code inspection alone. Each change should attach before/after evidence appropriate to its scope:

- actual SQL query count where practical
- sequential vs concurrent benchmark timings
- error/401/5xx behavior
- response-contract tests
- query-count regression tests for N+1 fixes
- `EXPLAIN (ANALYZE, BUFFERS)` for any index or complex consolidated query

The goal is not "fewer lines" or "more clever SQL." The goal is fewer network conversations, stable correctness, low memory usage, and measurably faster hot-path behavior on Vercel + Neon.
