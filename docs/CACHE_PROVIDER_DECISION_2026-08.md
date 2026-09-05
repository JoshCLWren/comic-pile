# Production cache provider decision

Updated: 2026-09-05
Owner: issue #2216 (follow-up to #1785)

## Decision

**Production cache provider remains Postgres.** Remote Redis (Upstash) re-enable:
**NEED MORE DATA / stay Postgres** — not a GO.

The command-budget half of the rule is a GO. The latency half cannot be
evaluated. `vercel env run -e production` (Actions
https://github.com/JoshCLWren/comic-pile/actions/runs/33986154224) injects
`KV_REST_API_URL` / `KV_REST_API_TOKEN` as **empty**. Until
`provider_recommendation(upstash, neon)` can run, production stays on
`CACHE_PROVIDER=postgres`. No environment flip is authorized. Do not add
GitHub secrets.

## Why Postgres stays

1. **Latency evidence is incomplete.** Neon point SELECT from
   `github-actions:ubuntu-latest` is measured (p50=143.303 ms, p95=151.812 ms,
   30 samples). Upstash REST GET has 0 samples. The executable rule in
   `app/cache_provider_decision.py` requires both distributions.
2. **Command budget is satisfied.** Vercel production runtime logs (7-day
   Hobby window, 2026-09-05) map to 1,990 conservative monthly commands via
   `project_monthly_cache_commands()`. Pathological upper bound treating every
   request as a 5-command roll is 18,321. Both preserve the 150,000-command
   headroom. See `docs/CACHE_TRAFFIC_CENSUS_2026-09.json`.
3. **Postgres is the safe, already-configured default.** The runtime still
   resolves to `CACHE_PROVIDER=postgres`. `CACHE_ENABLED` cannot activate Redis
   unless `CACHE_PROVIDER=redis` and credentials are also present.

## The numbers

### Monthly command budget

| Item | Commands/month |
| --- | ---: |
| Upstash Free allowance | 500,000 |
| ComicPile application budget | **350,000** |
| Reserved headroom | **150,000 (30%)** |
| Conservative census projection (2026-09-05) | **1,990** |
| Pathological all-roll bound | **18,321** |

### Latency (2026-09-05, `github-actions:ubuntu-latest`, 30/3)

| Path | p50 (ms) | p95 (ms) | Status |
| --- | ---: | ---: | --- |
| Upstash REST GET | — | — | stopped; `vercel env run` injects empty Sensitive values |
| Neon point SELECT | 143.303 | 151.812 | ok |
| Uncached queue read | — | — | skipped; no bearer token |

Neon p95/p50 = 1.06× (stable). Neon p50 is far above the 3 ms absolute-fast
threshold, so a future Upstash p50 below 286.6 ms would be a latency GO. That
comparison is not available yet.

### Contract that keeps production config aligned with this memo

`app/cache_provider_decision.py` still pins:

- `PRODUCTION_CACHE_PROVIDER = "postgres"` — current production, unchanged.
- `provider_recommendation(upstash, neon)` — applies once both samples exist.
- `project_monthly_cache_commands(flow_counts)` — census is under budget.

`tests/test_cache_provider_decision.py` continues to assert that the runtime
default resolves to `PRODUCTION_CACHE_PROVIDER`.

## Next env flips — only after a Redis GO

Do **not** flip production now. If a later Upstash measurement makes
`provider_recommendation()` return `"upstash"` while the census stays under
350,000, Josh should confirm these flips:

1. `CACHE_PROVIDER=redis`
2. `CACHE_ENABLED=true`
3. `CACHE_QUOTA_THROTTLE_ENABLED=true` (recommended from day one)

Rollback remains `CACHE_ENABLED=false`.

## Operator steps to close NEED MORE DATA

Stopped after the required `vercel env run` path. The Deploy Production
token downloads the production env envelope but leaves Sensitive KV REST
values empty. Closing the latency gate needs a **production-runtime** GET
(the values exist in deployed functions) or a token that can decrypt
Sensitive env vars. Do not add GitHub secrets. Do not use `REDIS_URL`.

## Verification for this memo

- `ruff check` on the touched Python files
- `pytest --no-cov tests/test_benchmark_cache_latency.py tests/test_cache_traffic_census.py tests/test_cache_usage.py tests/test_cache_provider_decision.py`
- `python scripts/check_markdown_docs.py`

## References

- `CACHE_REENABLE_DECISION.md` — live re-enable gate; still not satisfied
- `CACHE_COMMAND_BUDGET.md` — budget and 2026-09 census
- `CACHE_LOOKUP_LATENCY_2026-08.md` / `.json` — latency table and raw samples
- `CACHE_TRAFFIC_CENSUS_2026-09.json` — Vercel runtime-log census
- `app/cache_provider_decision.py` + `tests/test_cache_provider_decision.py`
