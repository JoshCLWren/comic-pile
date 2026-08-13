# Issue #700: Session-read performance budget methodology

## Goal

Document the budget-setting methodology that closes issue #700 once authenticated
production evidence becomes available. The four observable per-endpoint
performance contracts are:

- cold/first-observed latency after deployment idleness;
- warm/steady-state median latency;
- warm/steady-state p95 latency;
- response-body payload size regression detection.

These are produced by combining the existing benchmark harness
(`scripts/benchmark_session_reads.py`), the existing session-read diagnostics
emitted by the request-logging middleware (`app/middleware/request_logging.py`
and `app/middleware/security_headers.py`), and the budget helper introduced
with this issue (`scripts/session_read_budget.py`).

## Production-evidence boundary

The implementation stages are merged and the harness is in production:

- PR #721 added the repeatable authenticated benchmark harness.
- PR #730 consolidated History events and bulk-loaded active-thread metadata.
- PR #778 added structured successful-read diagnostics.
- PR #801 added the deterministic latest-session-action index.

Production samples still require the dedicated non-personal production account
provisioned by issue #832. Until that account exists, no authenticated
production evidence can be recorded. The methodology, the helper, and the
thresholds below are designed to be runnable the moment that account is
available without changing the harness, the diagnostics, or the public
response contract.

## Cold vs warm distinction

The benchmark harness records every request in one isolated endpoint
invocation and separates the first sample from the remaining samples:

- **first-observed** sample: the single request that runs first against a
  deployment that the harness did not precondition. Whether this is a true cold
  path depends on whether the deployment has been idle long enough to evict
  process-level caches, connection pools, and any edge cache. The harness is
  explicit about this constraint in `first_observed_note` and refuses to
  confuse "first observed" with "cold" when multiple endpoints run in the same
  invocation.
- **steady-state** aggregate: the remaining samples in the same invocation.
  These reflect the warm path the application will hit under normal
  authenticated traffic.

The budget helper consumes that split verbatim. It does not attempt to infer
coldness from latency alone because the deployment must be controlled
externally to guarantee idleness. Run each endpoint in a fresh harness
invocation when collecting cold-path evidence:

```bash
scripts/benchmark_session_reads.py \
    --base-url "$PROD_BASE_URL" \
    --bearer-token "$PROD_BEARER_TOKEN" \
    --endpoint current \
    --warmups 0 \
    --iterations 10 \
    --output artifacts/session-current.json

scripts/benchmark_session_reads.py \
    --base-url "$PROD_BASE_URL" \
    --bearer-token "$PROD_BEARER_TOKEN" \
    --endpoint history-first \
    --warmups 0 \
    --iterations 10 \
    --output artifacts/session-history-first.json
```

## Budget artifact

The budget helper turns each benchmark JSON into a per-endpoint verdict:

```bash
scripts/session_read_budget.py \
    --benchmark-report artifacts/session-current.json \
    --deployment-source production \
    --previous-budget artifacts/budget-previous.json \
    --output artifacts/budget-current.json
```

The artifact distinguishes cold and warm verdicts, surfaces payload-size
regressions against the previously archived budget, and labels every result
with the deployment source so reviewers can audit where each number came from.
A frozen budget artifact is the closure evidence for issue #700.

## Default thresholds

The helper ships with conservative default thresholds derived from the merged
implementation stages. They are deliberately generous until real production
samples tighten them:

| Endpoint | Cold first-observed | Warm median | Warm p95 |
|---|---|---|---|
| `/api/v1/sessions/current/` | 1200 ms | 200 ms | 400 ms |
| `/api/v1/sessions/?page_size=50` | 2500 ms | 600 ms | 1200 ms |

History later pages inherit the same default as the first page until a
later-page baseline exists. The cold-path ceilings include deployment warmup
because the harness cannot guarantee true coldness across Vercel function
instances; once the deployment's idle behaviour is known, the cold ceilings
can be tightened without changing the helper.

## Payload-size regression

Response-body regressions are detected automatically when a previous budget is
provided. The default tolerance is `DEFAULT_PAYLOAD_TOLERANCE_BYTES = 256`,
meaning a payload is only flagged as a regression when it grows by more than
256 bytes relative to the previously archived budget. The helper records both
the new payload range and the prior range so reviewers can confirm that the
public response contract did not silently expand.

## Closure checklist

Issue #700 closes when:

1. The dedicated production account provisioned by #832 exists in GitHub
   Actions secrets.
2. The harness has been run against production for current-session,
   History first page, and History later page, with deployment idleness
   controlled externally.
3. The resulting JSON artifacts have been converted into a budget artifact by
   `scripts/session_read_budget.py` and archived at
   `benchmarks/session-read-budgets/<deployment_id>/<timestamp>.json`.
4. The archived artifact is attached to this issue as the production-evidence
   closure comment and the cold/warm budgets are referenced from the same
   comment.
5. Any regression surfaced during the comparison becomes its own focused
   issue with the failing spec and evidence, rather than being inlined into
   this issue.
