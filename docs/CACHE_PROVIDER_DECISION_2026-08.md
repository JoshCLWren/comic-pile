# Production cache provider decision

Updated: 2026-09-05
Owner: issue #2216 (follow-up to #1785)

## Decision

**Recommendation: GO redis.** `provider_recommendation()` returned `"upstash"`.

**Current production remains Postgres.** This issue does not flip
`CACHE_PROVIDER`, `CACHE_ENABLED`, or any other production env var. The
Hobby production alias was restored to `dpl_9E9NbZS8LTGZe5evKcwBtdD1dLhC`
(`main` `a95cba45`) after the one-shot probe. Josh should confirm the
documented env flips before anything changes at runtime.

Both gates of the executable rule are now closed:

| Gate | Result |
| --- | --- |
| Command budget | **GO** — 1,990 conservative commands/month (pathological 18,321) vs 350k / 150k headroom |
| Latency | **GO** — Upstash p50 7.088 ms < 2× Neon p50 143.303 ms; Neon p50 > 3 ms; both p95/p50 < 5× |
| Overall | **GO redis** (document-only; production stays Postgres until Josh flips) |

## Why the rule returns Upstash

1. **Production-runtime Upstash REST GET succeeded.** A gated
   `GET /api/v1/health/cache-latency` ran inside Hobby production (`cle1`)
   where `KV_REST_API_URL` / `KV_REST_API_TOKEN` are real process env.
   Actions: https://github.com/JoshCLWren/comic-pile/actions/runs/33986556893
   — 30 samples, p50=7.088 ms, p95=7.807 ms, no HTTP 429.
2. **Neon comparison uses the existing GHA number.** cle1 Neon was not
   re-measured. The committed Neon point SELECT remains p50=143.303 ms /
   p95=151.812 ms from `github-actions:ubuntu-latest`. That mixed vantage is
   explicit: Upstash is same-region production; Neon is the earlier runner
   hop Josh authorized as the comparison.
3. **Command budget is satisfied.** Vercel production runtime logs (7-day
   Hobby window, 2026-09-05) map to 1,990 conservative monthly commands via
   `project_monthly_cache_commands()`. Pathological upper bound treating every
   request as a 5-command roll is 18,321. Both preserve the 150,000-command
   headroom. See `docs/CACHE_TRAFFIC_CENSUS_2026-09.json`.
4. **Production config is unchanged.** `PRODUCTION_CACHE_PROVIDER` stays
   `"postgres"`. The one-shot deploy set only `CACHE_LATENCY_PROBE_ENABLED=true`
   and never `CACHE_PROVIDER=redis`. After measurement, `vercel promote`
   restored `dpl_9E9NbZS8LTGZe5evKcwBtdD1dLhC`.

## The numbers

### Monthly command budget

| Item | Commands/month |
| --- | ---: |
| Upstash Free allowance | 500,000 |
| ComicPile application budget | **350,000** |
| Reserved headroom | **150,000 (30%)** |
| Conservative census projection (2026-09-05) | **1,990** |
| Pathological all-roll bound | **18,321** |

### Latency (2026-09-05)

| Path | p50 (ms) | p95 (ms) | Samples | Vantage |
| --- | ---: | ---: | ---: | --- |
| Upstash REST GET | 7.088 | 7.807 | 30 | `vercel:cle1` production runtime |
| Neon point SELECT | 143.303 | 151.812 | 30 | `github-actions:ubuntu-latest` |
| Uncached queue read | — | — | 0 | skipped; no bearer token |

Upstash p95/p50 = 1.10× (stable). Neon p95/p50 = 1.06× (stable). Upstash p50
is 0.049× the Neon p50 (about 20× faster than the GHA Neon hop) and well
under the 286.6 ms (2× Neon p50) GO threshold.

```
provider_recommendation(
    LatencySample(p50_ms=7.088, p95_ms=7.807),
    LatencySample(p50_ms=143.303, p95_ms=151.812),
) == "upstash"
```

### Contract that keeps production config aligned with this memo

`app/cache_provider_decision.py` still pins:

- `PRODUCTION_CACHE_PROVIDER = "postgres"` — **currently deployed** provider.
  Unchanged until Josh applies the flips below.
- `provider_recommendation(upstash, neon)` — now returns `"upstash"` on the
  committed samples.
- `project_monthly_cache_commands(flow_counts)` — census is under budget.

`tests/test_cache_provider_decision.py` continues to assert that the runtime
default resolves to `PRODUCTION_CACHE_PROVIDER` (Postgres) so this PR cannot
silently change production behavior.

## Next env flips — Josh confirms; this PR does not apply them

1. `CACHE_PROVIDER=redis`
2. `CACHE_ENABLED=true`
3. `CACHE_QUOTA_THROTTLE_ENABLED=true` (recommended from day one)

Rollback remains `CACHE_ENABLED=false`.

Remove temporary `GET /api/v1/health/cache-latency` before merging this
branch to `main` so Deploy Production does not republish the probe.

## Verification for this memo

- Artifact `cache-provider-evidence` from Actions run 33986556893
- `provider_recommendation(LatencySample(7.088, 7.807), LatencySample(143.303, 151.812)) == "upstash"`
- `pytest --no-cov tests/test_cache_provider_decision.py tests/test_cache_traffic_census.py tests/test_cache_latency_probe.py`
- Production alias `comic-pile.vercel.app` → `dpl_9E9NbZS8LTGZe5evKcwBtdD1dLhC`

## References

- `CACHE_REENABLE_DECISION.md` — re-enable gate; now GO pending Josh's flips
- `CACHE_COMMAND_BUDGET.md` — budget and 2026-09 census
- `CACHE_LOOKUP_LATENCY_2026-08.md` / `.json` — latency table and raw samples
- `CACHE_TRAFFIC_CENSUS_2026-09.json` — Vercel runtime-log census
- `app/cache_provider_decision.py` + `tests/test_cache_provider_decision.py`
