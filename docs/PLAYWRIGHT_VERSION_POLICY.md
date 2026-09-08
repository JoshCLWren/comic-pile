# Playwright Version Policy

This document is the source of truth for the Playwright version and browser revision
used across the Comic Pile workspace (issue #2390).

## Single intentional declaration

**`@playwright/test` is declared exactly once**: as a `devDependency` in
`frontend/package.json`. The root workspace `package.json` intentionally does **not**
declare Playwright.

All Playwright configs, specs, and invocations live in (or delegate to) the `frontend`
package:

- Configs: `frontend/playwright.config.ts`, `frontend/playwright.audit.config.ts`,
  `frontend/playwright.p0.config.ts`.
- Specs: `frontend/src/test/**/*.spec.ts` and `frontend/src/test/**/*.audit.ts`.
- Entry points: every `Makefile` target and CI job runs Playwright through
  `pnpm --filter frontend ...`, so `frontend/package.json` owns the version.

## Version source of truth

The canonical version is the `@playwright/test` version pinned in `pnpm-lock.yaml`
under the `frontend` importer. `playwright`, `playwright-core`, and `@playwright/test`
must all resolve to the same version (verified by lockfile consistency).

To change the Playwright version:

1. Edit `@playwright/test` in `frontend/package.json`.
2. Run `pnpm install` at the workspace root to update `pnpm-lock.yaml`.
3. Confirm `@playwright/test`, `playwright`, and `playwright-core` resolve to the same
   version in the lockfile.

## Browser revision source of truth

The Chromium browser revision is derived from the pinned `playwright-core` version by
Playwright's package-to-revision mapping. Any browser cache or container key for the
Chromium audit (#2388, #2389) must derive from that pinned Playwright version so a
version change automatically invalidates stale browser caches.

## Current Chromium audit and E2E entry points

These are the required Chromium paths that must continue to run:

- Rendered UI audit: `pnpm run audit:ui` (root) → `scripts/run_ui_audit.sh` →
  `pnpm --filter frontend exec playwright test --config=playwright.audit.config.ts`.
  CI: the `ui-audit` job installs Chromium via
  `pnpm --filter frontend exec playwright install --with-deps chromium`.
- E2E suite: `make verify-e2e` → `pnpm --filter frontend run test:e2e`.
- P0 Chromium suite: `pnpm --filter frontend run test:e2e:p0`
  (`playwright.p0.config.ts`).
- Quick/dev E2E: `pnpm --filter frontend run test:e2e:quick`.
- Prod smoke: `make test-e2e-prod-smoke` → `pnpm --filter frontend run test:e2e:prod-smoke`.

Firefox and WebKit are optional diagnostics only and are not required release coverage.
