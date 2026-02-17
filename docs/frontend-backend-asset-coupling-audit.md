# Frontend/Backend Asset Coupling Audit

Date: 2026-02-17
Scope: FastAPI static asset serving, frontend build/deploy flow, CI/deploy guardrails, and related test/doc drift.

## Executive Summary

The app currently works in production for core flows, but the deploy architecture still allows a class of silent failures where backend health is green while frontend assets are missing or stale. The highest-risk issues are fail-open SPA fallback behavior, mutable deploy workflow patterns, and configuration/documentation drift around database drivers and frontend artifact paths.

## Findings

### 1. Silent fallback when frontend build is missing
Severity: High

Evidence:
- `app/main.py` - `_serve_spa_index_response()`
- `app/main.py` - `serve_root()`
- `app/main.py` - `serve_react_spa()`

Details:
- `_serve_spa_index_response()` serves fallback inline HTML when `static/react/index.html` is missing.
- This can mask missing/failed frontend builds and still return a 200 from `/`.
- Combined with `/health` checking only DB connectivity, deployment can look healthy while UI is effectively broken.

Risk:
- False-positive deploy health.
- Incident detection delayed until manual user verification.

Recommendation:
- In production mode, fail fast if `static/react/index.html` or required assets are missing.
- Reserve fallback HTML only for explicit test mode.

---

### 2. Static asset mounts are conditional (fail-open behavior)
Severity: High

Evidence:
- `app/main.py` - static mount block in `create_app()`

Details:
- Static mounts for `/static` and `/assets` are only mounted if directories exist.
- Missing build outputs do not fail startup.

Risk:
- Startup succeeds with incomplete runtime surface.

Recommendation:
- Add startup assertions for asset presence in production.
- Abort startup (`sys.exit(1)` or exception) when required frontend artifacts are absent.

---

### 3. Mutable deploy workflow in `make deploy-prod`
Severity: High

Evidence:
- `Makefile` - `deploy-prod` target

Details:
- Deploy target builds frontend locally, stages all changes (`git add -A`), auto-commits with timestamp, pushes main, then deploys.
- This conflates code authoring and release operations, and can ship unrelated local changes.

Risk:
- Non-deterministic releases.
- Reduced traceability and reproducibility.

Recommendation:
- Remove auto-add/auto-commit from deploy target.
- Build immutable artifact in CI and deploy that exact artifact.

---

### 4. Async DB policy drift in compose/runtime docs
Severity: Medium

Evidence:
- `docker-compose.prod.yml` - app service `DATABASE_URL`
- `docker-compose.yml` - app service `DATABASE_URL`
- `pyproject.toml` - dependency declarations

Details:
- Multiple runtime/default configs still use `postgresql+psycopg://` despite project policy requiring asyncpg-only for application runtime.
- `app/config.py` converts URLs, which prevents immediate breakage but hides inconsistency.

Risk:
- Confusing operator behavior.
- Increased chance of incorrect setup or regressions in new scripts/services.

Recommendation:
- Normalize runtime/default connection URLs to `postgresql+asyncpg://`.
- Keep sync driver usage isolated to migration tooling only.

---

### 5. Test fragility from stale selectors
Severity: Medium

Evidence:
- `frontend/src/test/helpers.ts` - `SELECTORS.threadList.threadItem`

Details:
- `threadItem: '.thread-item'` no longer matches current queue markup.
- This causes false negatives in smoke/e2e checks despite working UI.

Risk:
- E2E trust erosion and noisy failures.

Recommendation:
- Add explicit `data-testid` attributes for critical surfaces.
- Migrate smoke/e2e selectors to stable test IDs.

---

### 6. Docs drift around frontend build output path
Severity: Low

Evidence:
- `frontend/vite.config.js` - build `outDir`
- `AGENTS.md` - Playwright build guidance

Details:
- Build output is `static/react`, but some docs/instructions still mention `frontend/dist`.

Risk:
- Operator confusion and misdiagnosis during incidents.

Recommendation:
- Update docs to consistently reference `static/react`.

---

### 7. Production Docker image includes excessive context and runtime files
Severity: High
Status: Remediated in this PR

Evidence:
- `Dockerfile` - runtime stage targeted `COPY` statements
- `.dockerignore` - node/test artifact ignore entries

Details:
- Remediated in this PR by replacing broad runtime copy behavior with targeted runtime `COPY` statements.
- Remediated in this PR by excluding dependency/test artifact noise from Docker context.

Risk:
- Larger image and slower builds/deploys.
- Increased runtime attack surface and non-essential files shipped to production.

Recommendation:
- Add explicit ignore rules for `node_modules`, `frontend/node_modules`, reports, and local artifacts.
- Replace broad runtime `COPY . .` with targeted `COPY` statements for required backend code/config only.

---

### 8. Docker build reproducibility and supply-chain hardening gaps
Severity: Medium
Status: Remediated in this PR

Evidence:
- `Dockerfile` - pinned Node frontend builder stage
- `Dockerfile` - frontend dependency install/build steps

Details:
- Remediated in this PR by using a pinned Node image in a dedicated frontend build stage instead of curl-based setup.
- Frontend build now runs via deterministic lockfile-based install in the dedicated builder stage.

Risk:
- Lower reproducibility and harder dependency provenance guarantees.
- Build behavior can drift unexpectedly with ecosystem changes.

Recommendation:
- Use a pinned Node toolchain strategy (for example, a dedicated pinned Node build stage).
- Remove `--legacy-peer-deps` by resolving dependency constraints in `package.json`/lockfile.

---

### 9. Runtime command defaults are brittle in Docker
Severity: Medium
Status: Remediated in this PR

Evidence:
- `Dockerfile` - runtime `CMD`

Details:
- Remediated in this PR with default-safe runtime command values using `${PORT:-8000}` and `${WEB_CONCURRENCY:-2}`.

Risk:
- Startup failure when `PORT` is absent in non-platform environments.
- Worker count may mismatch container resources.

Recommendation:
- Use safe defaults and tunable env vars (for example `${PORT:-8000}` and `${WEB_CONCURRENCY:-2}`).

## Current Strengths

- Dockerfile build flow already produces frontend assets during image build:
  - `Dockerfile` - `frontend-builder` stage `npm run build`
- CI Playwright job explicitly builds frontend before browser tests:
  - `.github/workflows/ci-sharded.yml` - Playwright job build step
- Production smoke coverage catches chunk load failures in key routes:
  - `frontend/src/test/prod-smoke.spec.ts` - chunk failure response listener
- Dockerfile already separates build and runtime stages:
  - `Dockerfile` - `python-builder` and runtime stages
- Runtime container already runs as non-root user:
  - `Dockerfile` - `useradd` and `USER appuser`

These are good foundations; the remaining issues are mostly fail-fast and process hardening.

## Prioritized Remediation Plan

### Phase 1 (Immediate)
1. Enforce production startup asset checks.
2. Remove fail-open fallback HTML behavior in production.
3. Add post-deploy asset gate that validates `/` and referenced JS/CSS asset URLs return 200.

### Phase 2 (Short-Term)
1. Replace mutable `make deploy-prod` workflow with CI-built immutable artifact deployment.
2. Normalize runtime DB URL defaults/configs to asyncpg.

### Phase 3 (Stabilization)
1. Introduce `data-testid` attributes for queue/rate/smoke-critical elements.
2. Refactor smoke/e2e selectors away from style/text coupling.
3. Update docs to remove stale path and workflow instructions.

### Phase 4 (Docker Hardening)
1. Tighten `.dockerignore` to cut local dependency/context bloat.
2. Replace runtime `COPY . .` with minimal targeted copies.
3. Make Docker runtime command default-safe and worker-configurable.
4. Remove `--legacy-peer-deps` from production build path.
5. Pin Node build toolchain strategy for reproducible frontend builds.

## Acceptance Criteria

- Production startup fails if frontend artifact set is incomplete.
- No deploy path requires local manual `npm run build` as a hidden prerequisite.
- No runtime configs default to `postgresql+psycopg://`.
- Smoke tests run with stable selectors and do not fail from purely cosmetic DOM changes.
- Documentation reflects actual artifact path and deploy behavior.
- Production Docker image excludes non-runtime code/dependencies and has deterministic build inputs.

## Notes

This audit targets coupling risks and operational robustness, not feature correctness. Exploratory production checks on 2026-02-17 did not show obvious user-facing regressions in core flows, which increases confidence that current risk is primarily in deployment/test architecture rather than immediate product behavior.
