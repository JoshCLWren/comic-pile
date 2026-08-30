# Cross-page UI visual and geometry audit

Issue #2043 adds a diagnostic Playwright harness for inspecting rendered Comic Pile UI states across representative viewport classes. It collects evidence. It does not define a visual redesign contract and its warnings are not test failures.

## Run it

From `frontend/`, with the same backend/test prerequisites used by the existing Playwright suite:

```bash
pnpm run audit:ui
```

The command builds the frontend, runs the audit in Chromium with one worker, captures deterministic screenshots, and writes local output under:

- `test-results/ui-audit/report.md`
- `test-results/ui-audit/report.json`
- `test-results/ui-audit/screenshots/`

`frontend/test-results/` is already ignored by the repository, so generated audit evidence stays local unless a specific artifact is deliberately promoted later.

## Covered states

The harness uses `authenticatedWithThreadsPage`, which creates an isolated authenticated user with three deterministic ten-issue threads. It does not depend on production reading data.

It captures:

- Roll
- Roll rating state, entered deterministically through the manual picker
- Queue
- History, after the fixture has saved a rating
- Crossovers
- Continuity Plans index
- Continuity Planner at `/continuity-plans/new`
- the Roll manual-picker dialog

Each state is exercised at 390x844, 820x1180, 1280x900, and 1920x1080.

## What is measured

Geometry checks use the rendered page rather than Tailwind class names. Evidence includes `getBoundingClientRect()`, viewport dimensions, document and element scroll dimensions, computed positioning and overflow styles, visibility, and rectangle intersections.

The report can warn about:

- document-level horizontal overflow
- fixed or sticky chrome intersecting meaningful content
- interactive elements escaping nearby semantic containers
- controls clipped by non-scrollable ancestors
- dialogs exceeding the usable viewport without an internal vertical scroll path
- substantial collisions between independent interactive controls
- large vertical blank regions in stable states where that check is meaningful

Warnings include the state, route, viewport, element descriptions, and concrete measurements needed to reproduce the observation. They are intentionally diagnostic. A warning does not make the audit command fail. Fixture setup, navigation, browser-health, screenshot, or report-generation failures still fail the harness.

## Computed-style inventory

For visible semantic page elements, panels, and controls, the JSON and Markdown reports inventory useful computed-style signals such as radii, typography, colors, shadows, spacing, dimensions, border treatments, button/control treatments, and card/panel treatments. Counts and representative elements are included for context.

The inventory is descriptive evidence, not a list of defects. A unique value is not automatically a problem.
