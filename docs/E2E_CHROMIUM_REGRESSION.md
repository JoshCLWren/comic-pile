# Chromium regression discovery (scheduled + dispatch)

Issue: [#1483](https://github.com/JoshCLWren/comic-pile/issues/1483) (epic [#1476](https://github.com/JoshCLWren/comic-pile/issues/1476))

This is the broader P1/P2 Chromium regression lane. It runs on a daily
schedule and on explicit manual dispatch — it is **not** a required
pull-request gate. The required P0 PR gate is separate
(`frontend/playwright.p0.config.ts`).

## Coverage source of truth

`docs/e2e-behavior-inventory.yaml` is the single source of truth. Every
`covered` behavior lists the Playwright spec files (basenames under
`frontend/src/test/`) that own its scenario ID. The selector resolves a priority
scope to that spec list:

```bash
python3 scripts/e2e_regression_select.py --scope p1-p2 --output selection.json
```

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

Build the frontend before Playwright. The suite needs one same-origin server at
`BASE_URL` (default `http://127.0.0.1:9000`), a disposable migrated PostgreSQL
database, the native Rust service and the local ingress helper. Redis and a
Python application server are not part of this runtime.

Use the slot-safe commands in
[`.agents/skills/e2e-chromium-regression/SKILL.md`](../.agents/skills/e2e-chromium-regression/SKILL.md)
when other local sessions may be running. Set `TEST_ENVIRONMENT=true` so the
native auth limiter permits fixture-speed user registration. Never point
`RUST_ROLL_DATABASE_URL` or `MIGRATE_DATABASE_URL` at production.

`scripts/e2e_native_ingress.py` is test/dev tooling, not an application route or
a deployed compatibility fallback. It serves `static/react` and proxies every
`/api/*` request to the native service, matching the production Rust ingress.

## CI workflow

`.github/workflows/e2e-chromium-regression.yml`:

- **Schedule:** daily at 04:47 UTC.
- **Dispatch:** Actions → *E2E Chromium Regression* → *Run workflow* with a
  `scope` (`p1-p2` default) and worker count.
- The job builds the frontend and native Rust service, applies refinery
  migrations, starts the native service behind the `:9000` ingress, runs the
  inventory-selected suite with Chromium only, and uploads artifacts for every
  run — including failures.
- One disposable PostgreSQL database is shared through
  `RUST_ROLL_DATABASE_URL`. The workflow retains the historical
  `DATABASE_URL` / `TEST_DATABASE_URL` fields as a guarded CI compatibility
  contract; the native application reads `RUST_ROLL_DATABASE_URL`.

### Artifacts

| Artifact | Contents |
| --- | --- |
| `regression-results-<run>` | `results.json` (structured outcomes), `selection.json` (what ran and why), per-test trace/screenshot/video output, native and ingress logs |
| `regression-report-<run>` | HTML report with traces, screenshots, and video attached to failures |

## Defect path: no auto-ticket creation

**This pipeline never creates GitHub issues and never applies issue or PR
labels.** Zero executable issues are created directly from individual failed
tests, and no `bug`, `ralph-task`, or factory-owner label is applied because a
test failed. The workflow runs with `permissions: contents: read` only, and the
run summary restates the contract.

A failing run is a *signal*. To turn it into product work:

1. **Reproduce** the failure from the uploaded artifacts (trace + JSON results
   + native/ingress logs) on the recorded head.
2. **Reconcile** it against existing open issues, PRs, and closed bug history.
   Search before creating anything.
3. **Group to one root cause.** Multiple failing tests that share a product
   behavior or root cause belong in one canonical record, not one ticket per
   failed test.
4. **Respect the backlog freeze.** Update an existing authorized issue/PR or
   record the evidence in its handoff. Do not create a new issue or sub-issue
   without an explicit interactive owner instruction.

## Optional Firefox/WebKit diagnostics

Only Chromium runs in this lane. Firefox and WebKit remain optional
diagnostic browsers unless separately justified and added later; they are not
part of the scheduled contract.

## Keeping the inventory current

When you add or retire Chromium coverage:

- Add the spec file to the owning behavior's `specs` list (or add a new
  behavior entry with a stable scenario ID).
- Never edit statuses speculatively: `covered` requires an existing spec file,
  enforced by the selector's fail-closed behavior and
  `tests/test_e2e_regression_select.py`.
- Scenario IDs are the ownership boundary — cite the inventory IDs your work
  owns so two factories do not build duplicate coverage.
