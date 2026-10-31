# Request amplification and Active CPU contract

Issue #4273 separates three things that the latency budget used to blur: HTTP
wall time, Python process CPU, and Vercel billed Active CPU. This document is the
contract for the deterministic checks in
`tests/test_request_amplification_contract.py`, the measurement method for the
production-shaped replay lab (#4277), and the manual operator step for comparing
billed usage before and after a change.

It deliberately does **not** claim a production CPU ranking. The current
connector cannot read per-project historical Active CPU billing, so every
route-level number below is a local workload estimate, not a billing statement.

## What this branch verifies

Run the focused contract from the repository root:

```bash
bash scripts/check-python-ci-lint.sh
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5437/comic_pile_test \
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5437/comic_pile_test \
  .venv/bin/python -m pytest tests/test_request_amplification_contract.py -v
```

The module asserts:

| Contract | Assertion |
| --- | --- |
| Wall time is not CPU | A 500 ms wait logs `process_time_ms >= 450` while `cpu_time_ms < 300` and below three quarters of the wall time. This is the local control for the replay lab's 500 ms DB-delay experiment. |
| Identity lookups stay bounded | Five protected requests from one already authenticated session never run more than one SELECT each, and the only SELECT is the joined user/revocation lookup. |
| Identity SQL is separable | `get_current_user()` records its repository SQL in an explicit identity scope; responses expose `X-App-Auth-DB-Queries`, and logs carry `identity_database_queries` / `identity_database_time_ms` as a subset of the request total. |
| Counters count invocations | Three completed requests to one route record exactly three invocations, independent of log lines. |
| Counters aggregate by template | Two different thread ids record under `/api/v1/threads/{thread_id}`, not raw numeric paths. |

Existing coverage supplies the rest of the instrumentation contract:

- `tests/test_request_logging_observability.py` proves `cpu_time_ms` is sampled
  with `time.process_time()` and that structured fields survive both an
  application-configured and a platform-configured root logger.
- `tests/test_performance_diagnostics.py` proves the middleware exposes the
  identity SQL subset without changing the total query count.
- `tests/test_auth_query_count.py` proves one protected request runs exactly one
  joined identity SELECT before the #4275 cutover.
- `tests/test_traffic_metrics.py` proves counters are process-local, bounded by
  a cardinality cap, and exposed only to authenticated callers.

## Measurement method for route CPU (#4277)

Per-route CPU attribution is a replay-lab deliverable, not something the running
server can infer from request logs. Use this method there:

1. **Isolate the process.** Start one local Python process against the loopback
   PostgreSQL fixture. Do not sample concurrent traffic for per-route numbers.
2. **Measure process CPU, not wall time.** Sample `time.process_time()` (or the
   equivalent `/proc/<pid>/stat` utime+stime) immediately before and after each
   request in the server process. Never use `time.perf_counter()` for CPU, and
   never treat the compatibility field `process_time_ms` as CPU.
3. **Profile cold imports separately.** Create a fresh process for every cold
   sample, point the first request at the route under test, and include import,
   lifespan, and first-request CPU in the cold figure. Restart between samples
   so a warm sample cannot inherit cold work.
4. **Run warm samples one at a time.** Repeat each route enough times to report a
   median and a spread (at least 10 warm samples). Report wall time, process CPU,
   `X-App-DB-Queries`, and the SQL duration separately so a database wait is
   never reported as Python CPU.
5. **Keep one controlled parallel scenario.** Fire the realistic concurrent
   view load once and report only the aggregate process-CPU delta for the batch
   plus the number of in-flight requests. Do not divide that delta across
   requests or count the same CPU for two of them; assign nothing per route from
   a parallel run.
6. **Cover the suite.** `GET /api/v1/auth/me`, Roll bootstrap (the routed native
   Rust handler, not the retired Python path), rate, `GET /api/v1/threads/`,
   preferences, and creators summaries. State the runtime each route actually
   executes and do not label a route with a language inferred from its API
   version.

Rank routes only as a workload estimate:

```text
estimated total CPU[route] = median warm CPU per invocation × distinct invocations[route]
```

Use distinct invocations from a credible counter source (per-route counters or a
fleet collector), never the number of log events, and never Vercel
`group_by=requestPath` log counts. Publish the method and path template,
cold/warm split, SQL time versus wait time, sample size, and the min/max or
interquartile spread alongside the ranking. If fleet invocation totals are not
available, omit the multiplication and label the result a per-request profile.

## Counting request amplification per view

A view that issues N protected HTTP requests may currently run N identity SELECTs
and may start N Python invocations. Report these separately for every scenario:

- unique protected HTTP requests by method and route template;
- Python invocations (cold and warm);
- SQL statements run solely by `get_current_user()`, distinct from business SQL;
- total database connections;
- process CPU for the scenario.

The request middleware now carries the identity subset directly:
`X-App-Auth-DB-Queries` counts SQL executed inside
`identity_database_query_scope()`, while `X-App-DB-Queries` remains the total.
The same values appear in slow/cold/error log records as
`identity_database_queries` and `identity_database_time_ms`. A collector must
still sum these per request across a view; the headers do not by themselves
produce a view-level total or a fleet total.

The five required scenarios are (1) cold authenticated app load, (2) Roll
bootstrap plus cancel, (3) Queue navigation, (4) rating then the next Roll, and
(5) one auth outage with successful recovery. Browser fan-out is measured with
the existing Playwright request recorder; it is a separate cold-start source even
after identity SQL reaches zero.

The zero-repeat assertion for scenario (1) is blocked on #4275: the current
authenticated request still performs one joined user/revocation SELECT. When that
cutover lands, tighten the fixture in
`tests/test_request_amplification_contract.py` from "at most one per request" to
"zero for N requests from one authenticated session". Do not claim billed CPU
savings from SQL removal without that measurement.

## Comparing billed Active CPU around a change

Vercel's Hobby plan bills Active CPU, not wall time, so SQL-latency wins alone do
not prove a CPU reduction. Before and after a deployment, an operator records
usage for the **same single UTC day** on both sides; never compare month-to-date
cumulative totals, which mix unrelated days of traffic.

1. Open the Vercel project's Usage panel for the exact day and record Active CPU,
   provisioned memory, and function invocations. The observability metric API is
   not available to this team (it returned `404 Observability Data not found`,
   and Observability Plus is not enabled), so this is a manual dashboard step.
2. Record the number of successful production user actions for the same day from
   application data. Do not substitute log-event counts.
3. Expand the oldest and newest samples from the day so a single burst does not
   stand in for the daily figure.
4. Compare only days with comparable traffic. If traffic or account shape
   changed materially, mark the comparison inconclusive instead of normalizing
   it away.
5. Keep the result beside the deployed SHA and the date; usage is not attributable
   to a deployment without that pairing.

## Retention and safety

- Hobby runtime logs are retained for **one hour**
  ([Vercel runtime log limits](https://vercel.com/docs/logs/runtime)). Copy the
  structured request records while the deployment is still serving; there is no
  next-day historical read.
- Do not log raw tokens, cookies, request bodies, or user identity fields, and do
  not add per-request database writes or high-cardinality route keys.
- Do not enable paid observability, keep functions awake for sampling, or
  reintroduce health/keepalive database activity (#4129).
- Benchmark runs are local-only. Do not mutate production or provision a preview
  environment for them.

## Remaining unverified criteria

Merge of this contract does not close #4273. Still outstanding:

- the isolated cold/warm CPU suite, parallel scenario, and route ranking from
  #4277;
- the zero-repeat identity assertion after the #4275 cutover;
- the browser request-fan-out counts for the five scenarios, including cold-start
  invocation counts;
- a real daily billed-usage comparison for a deployed change.
