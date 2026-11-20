# Chromium regression discovery (scheduled + dispatch)

Issue: [#1483](https://github.com/JoshCLWren/comic-pile/issues/1483) (epic [#1476](https://github.com/JoshCLWren/comic-pile/issues/1476))

This is the broader P1/P2 Chromium regression lane. It runs on a daily
schedule and on explicit manual dispatch — it is **not** a required
pull-request gate. The required P0 PR gate is separate (`playwright.p0.config.ts`).

## Coverage source of truth

`docs/e2e-behavior-inventory.yaml` is the single source of truth. Every
`covered` behavior lists the Playwright spec files (basenames under
`frontend/src/test/`) that own its scenario ID, and the selector:

```bash
python3 scripts/e2e_regression_select.py --scope p1-p2 --output selection.json
```

resolves a priority scope to that spec list:

| Scope | Priorities | Typical use |
| --- | --- | --- |
| `p1-p2` | P1, P2 | Default scheduled discovery run |
| `p0` | P0 | Full core-journey sweep |
| `all` | P0, P1, P2 | Complete inventory sweep |

Selection fails closed: a `covered` behavior that references a missing spec
file stops the run instead of silently losing coverage. Spec files that exist
but are referenced by no inventory behavior are reported as `unmapped_specs`
so inventory drift stays visible.

## Running locally

```bash
make verify-e2e-regression            # scope p1-p2 (default)
make verify-e2e-regression SCOPE=all  # full inventory sweep
# or directly:
pnpm --filter frontend run test:e2e:regression -- --scope p0 --list
```

Prerequisites mirror the normal Playwright suite: one origin must serve on
`BASE_URL` (default `http://127.0.0.1:9000`) with a reachable database, and
the backend must run with `TEST_ENVIRONMENT=true` so the disposable test
database uses the browser-suite contract (rate limits disabled — the fixture
layer registers users and creates data at test speed, exactly like
`docker-compose.test.yml` does for `api-test`).

Native v2 resources are real production paths, so the same-origin server must
route `/api/v2/*` to the Rust service and everything else to FastAPI. The CI
workflow uses `scripts/e2e_native_ingress.py` (Python on `:9001`, native Roll on
`:8010`, ingress on `:9000`) and gives both processes the same `SECRET_KEY`
through `ENVIRONMENT=test`. Without that routing, Queue and Roll fail with the
native path's 404/401 rather than exercising the product.

## CI workflow

`.github/workflows/e2e-chromium-regression.yml`:

- **Schedule:** daily at 04:47 UTC.
- **Dispatch:** Actions → *E2E Chromium Regression* → *Run workflow* with a
  `scope` (`p1-p2` default) and worker count.
- The job builds the frontend and native v2 service, applies migrations, starts
  FastAPI and the native service behind the `:9000` ingress, runs the
  inventory-selected suite with Chromium only, and uploads artifacts for every
  run — including failures.

### Artifacts

| Artifact | Contents |
| --- | --- |
| `regression-results-<run>` | `results.json` (structured outcomes), `selection.json` (what ran and why), per-test trace/screenshot/video output, backend log |
| `regression-report-<run>` | HTML report with traces, screenshots, and video attached to failures |

## Defect path: no auto-ticket creation

**This pipeline never creates GitHub issues and never applies issue or PR
labels.** Zero executable issues are created directly from individual failed
tests, and no `bug`, `ralph-task`, or factory-owner label is applied because a
test failed. The workflow runs with `permissions: contents: read` only, and the
run summary restates the contract.

A failing run is a *signal*. To turn it into product work:

1. **Reproduce** the failure from the uploaded artifacts (trace + JSON results
   + backend log) on the recorded head.
2. **Reconcile** it against existing open issues, PRs, and closed bug history.
   Search before creating anything.
3. **Group to one root cause.** Multiple failing tests that share a product
   behavior or root cause become *one* canonical product bug — not one issue
   per failed test. Repeated observations of the same regression update or
   reference that same canonical bug instead of creating duplicates.
4. **Create normal product work only after reconciliation**, using the
   repository's standard issue workflow (priority labels, `ralph-status`,
   factory state machine). That issue then flows through normal backlog
   selection like any other.

## Optional Firefox/WebKit diagnostics

Only Chromium runs in this lane. Firefox and WebKit remain optional
diagnostic browsers unless separately justified and added later; they are not
part of the scheduled contract.

## Keeping the inventory current

When you add or retire Chromium coverage:

- Add the spec file to the owning behavior's `specs` list (or add a new
  behavior entry with a stable scenario ID).
- Never edit statuses speculatively: `covered` requires an existing spec file,
  enforced by `tests/test_e2e_behavior_inventory.py` and by selection failing
  closed.
- Scenario IDs are the ownership boundary — cite the inventory IDs your work
  owns so two factories do not build duplicate coverage.
