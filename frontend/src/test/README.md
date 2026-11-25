# Frontend browser tests

Maintained browser coverage lives here as TypeScript Playwright `*.spec.ts` files. The normal configuration runs Chromium only; Firefox and WebKit are optional diagnostics, not required release coverage.

## Setup

Follow the root README to install prerequisites, start PostgreSQL, apply migrations, and run `make dev` (Vite on `:5173`, native Rust API on `:8010`). Export the native environment variables documented in the README; the standalone service does not load `.env` itself.

Build before Playwright, then run one focused spec:

```bash
cd frontend
pnpm run build
BASE_URL=http://localhost:5173 pnpm exec playwright test <spec> --project=chromium
```

For the Docker same-origin topology, run `make docker-test-up`, then from `frontend/`:

```bash
BASE_URL=http://localhost:8000 pnpm exec playwright test <spec> --project=chromium
```

`BASE_URL` defaults to `http://localhost:9000` when unset. Full suites and aggregate coverage run in CI unless explicitly requested; use focused files for local iteration.

## Current spec families

The directory contains P0 core-journey specs (`p0-*.spec.ts`) and issue/behavior specs covering Roll, direct manual Read/Rate, Queue, dependencies/reading order, Reading Lists, continuity plans, auth/outage recovery, ComicVine identity, creators, SEO, accessibility, responsive geometry, and request budgets. Examples include:

- `p0-roll-selection.spec.ts`
- `issue-5525-roll-manual-read.spec.ts`
- `p0-snooze-unsnooze.spec.ts`
- `reading-list-gate-authoring.spec.ts`
- `issue-3923-comicvine-mapping.spec.ts`
- `issue-3068-seo-route-cleanup.spec.ts`

Treat this as a navigation sample, not an exhaustive inventory. The canonical inventory-driven lane uses `docs/e2e-behavior-inventory.yaml` and `frontend/playwright.regression.config.ts`; see `docs/E2E_CHROMIUM_REGRESSION.md`.

## Fixtures and helpers

Use the shared fixtures and helpers in this directory rather than duplicating login/setup logic. `authenticatedWithThreadsPage` creates isolated deterministic data; helpers such as `waitForQueueReady`, `dismissRollNudgeIfPresent`, and the scroll helpers live in `helpers.ts`. Keep API mocking at the shared fixture/service boundary so tests exercise the same client behavior as the browser.

## Evidence and debugging

The normal config retains traces on failure and captures screenshots on failure. Video is not enabled by default. Useful commands:

```bash
cd frontend
pnpm exec playwright test <spec> --project=chromium --debug
pnpm exec playwright show-trace test-results/<test-name>/trace.zip
pnpm exec playwright show-report
```

When a test fails, preserve the trace/network evidence and reproduce against the exact head. Never add retries, sleeps, skips, or weakened assertions merely to get green.
