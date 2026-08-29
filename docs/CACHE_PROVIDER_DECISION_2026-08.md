# Production cache provider decision

Updated: 2026-08-29
Owner: Factory 71 (issue #1785)

## Decision

**Production cache provider: Postgres.** Remote Redis (Upstash) re-enable: **NO-GO for now.**

This memo records the go/no-go ruling the issue asked for. It is a decision
backed by the numbers below and by a reproducible executable rule, not a
measurement report: the clean post-reset latency comparison and a trustworthy
production traffic census were still outstanding when this memo was committed,
and the decision rule in code will compute the verdict the moment they land.

The production configuration is unchanged and this memo's conclusion requires no
environment flip: with no cache overrides, the runtime resolves to
`CACHE_PROVIDER=postgres`, which is exactly the Postgres provider this memo
chooses. `CACHE_ENABLED` cannot activate Redis unless `CACHE_PROVIDER=redis` and
credentials are also present, so the deployed default and the memo conclusion
agree by construction and by test.

## Why Postgres stays

1. **The re-enable gate needs evidence the census does not yet provide.**
   `CACHE_REENABLE_DECISION.md` re-enables remote caching only after a recent
   production observation window projects application commands below the
   350,000-command monthly budget while preserving the 150,000-command (30%)
   provider headroom. No clean route-traffic census has landed, so the gate is
   not satisfied. Absence of that evidence is itself the conservative outcome.
2. **The latency comparison is not yet measured.** The Upstash free-tier quota
   paused the remote measurements until ~2026-08-28; the post-reset benchmark
   run had not produced committed numbers when this memo was written. Upstash
   REST (path 1) and Neon point SELECT (path 2) remain unmeasured from the Vercel
   region, so no measured ratio supports spending free-tier budget.
3. **Postgres is the safe, already-configured default.** The Postgres cache
   provider shares the application's primary database, keeps the same
   `CacheClient` interface and generation-based invalidation, and requires no
   new dependency or quota. It is the fail-safe choice while remote evidence is
   outstanding.

## The numbers

### Monthly command budget (already documented in `CACHE_COMMAND_BUDGET.md`)

| Item | Commands/month |
| --- | ---: |
| Upstash Free allowance | 500,000 |
| ComicPile application budget | **350,000** |
| Reserved headroom | **150,000 (30%)** |

### Per-flow command ceilings (source: `app/cache_metrics.py`)

| Flow | Ceiling |
| --- | ---: |
| Bootstrap | 4 |
| Queue load | 2 |
| Roll | 5 |
| Snooze | 1 |
| Rating | 1 |
| Thread mutation | 1 |
| Issue mutation | 1 |
| Continuity mutation | 1 |

### Latency decision rule (source: `docs/CACHE_LOOKUP_LATENCY_2026-08.md`)

| Threshold | Meaning |
| --- | --- |
| Upstash REST p50 < 2× Neon point SELECT p50 | Upstash is meaningfully faster; the re-enable gate can proceed when command-rate evidence is also in range |
| Upstash REST p50 ≥ 2× Neon p50, or Neon p50 ≤ 3 ms | Neon point reads are not meaningfully slower; staying on Postgres is justified |
| Either path p95 / p50 > 5× | Unstable measurements; investigate before declaring any default |

### Contract that keeps production config aligned with this memo

`app/cache_provider_decision.py` pins:

- `PRODUCTION_CACHE_PROVIDER = "postgres"` — the memo conclusion.
- `provider_recommendation(upstash, neon)` — applies the latency thresholds above.
- `project_monthly_cache_commands(flow_counts)` — multiplies a monthly per-flow
  census by the ceilings above and reports whether the projection stays below
  the 350,000-command budget.

`tests/test_cache_provider_decision.py` asserts that the runtime default
(`RedisSettings().effective_provider`) resolves to `PRODUCTION_CACHE_PROVIDER`
and pins the decision rule and projection behavior. That test is what makes
"production config matches its conclusion" a machine-checked invariant instead of
a prose claim.

## Outstanding measurement inputs (next worker's fill step)

Neither clean input was available to this run, so they are tabled here with the
exact procedure to close them:

1. **Latency comparison.** Run from the Vercel region after the 2026-08-28 quota
   reset:
   ```text
   python scripts/benchmark_cache_latency.py --iterations 30 --warmups 3 \
     --location "vercel:iad1" --output docs/CACHE_LOOKUP_LATENCY_2026-08.json
   ```
   Then copy the path p50/p95 cells into `CACHE_LOOKUP_LATENCY_2026-08.md` and
   feed the medians into `provider_recommendation()`.
2. **Route-traffic census.** Poll `GET /api/v1/traffic-metrics` periodically
   across instances and reconstruct fleet totals by keeping the maximum count
   per key per `instance_id` (aggregates only; see `app/traffic_metrics.py`).
   Map the route tallies onto the eight documented cache flows and feed the
   monthly counts into `project_monthly_cache_commands()`.

If both land and the rule flips the verdict to "upstash" **and** the projection
stays below 350,000 commands, then — and only then — a future revision may flip
`CACHE_PROVIDER=redis` + `CACHE_ENABLED=true` in production and update this memo.
That flipped state is reversible with the single `CACHE_ENABLED` flag per the
rollback boundary in `CACHE_REENABLE_DECISION.md`.

## Verification for this memo

- `python3 -m py_compile app/cache_provider_decision.py tests/test_cache_provider_decision.py`
- `python3 scripts/check_markdown_docs.py` (local; passes)
- Full runtime test coverage for `tests/test_cache_provider_decision.py` is
  delegated to CI because this runner does not provide the project Python
  environment (`redis`/`pydantic`/Postgres are not installed).

## References

- `CACHE_REENABLE_DECISION.md` — the live re-enable gate this memo does not satisfy yet
- `CACHE_COMMAND_BUDGET.md` — the budget and per-flow ceiling ledger
- `CACHE_LOOKUP_LATENCY_2026-08.md` — the latency comparison and decision rule
- `app/cache_provider_decision.py` + `tests/test_cache_provider_decision.py` — executable rule and config invariant