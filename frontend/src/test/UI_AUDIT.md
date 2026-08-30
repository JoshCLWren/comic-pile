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

`frontend/test-results/` is already ignored by the repository, so generated audit evidence stays local unless a specific artifact is deliberately promoted later. The output directory is cleared at the beginning of each run so stale screenshots cannot masquerade as current evidence.

## Covered states

Each viewport gets a fresh `authenticatedWithThreadsPage` fixture, which creates an isolated authenticated user with three deterministic ten-issue threads. The Roll rating scenario saves the same rating inside that viewport's isolated fixture before History is captured, so viewport comparisons begin from equivalent state instead of sharing mutations from earlier viewport passes. The audit does not depend on production reading data.

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

## Screenshot stability

The audit controls user-visible volatility so repeated captures are useful as future regression evidence:

- the browser clock is fixed for audit pages
- Chromium uses the `en-US` locale and UTC timezone
- the generated fixture username is rewritten only in browser responses to a fixed display value
- History session timestamps are rewritten only in browser responses to fixed display values
- CSS animation/transition timing is disabled and fonts are awaited before capture
- the WebGL dice canvas is masked because GPU rendering is not a stable cross-machine pixel source; its surrounding rendered geometry is still audited

The server-side fixture identity and persisted records are not rewritten by this stabilization layer.

## What is measured

Geometry checks use the rendered page rather than Tailwind class names. Evidence includes `getBoundingClientRect()`, viewport dimensions, document and element scroll dimensions, computed positioning and overflow styles, visibility, and rectangle intersections.

The report can warn about:

- document-level horizontal overflow
- fixed or sticky chrome intersecting meaningful content
- interactive elements escaping nearby semantic containers
- controls clipped by non-scrollable ancestors
- fixed/sticky controls rendered outside their reachable viewport, or controls outside reachable document width
- dialogs exceeding the usable viewport without an internal vertical scroll path
- substantial collisions between independent interactive controls
- large vertical blank regions in stable states where that check is meaningful

Warnings include the state, route, viewport, element descriptions, concrete measurements, and confidence needed to reproduce and triage the observation. They are intentionally diagnostic. A warning does not make the audit command fail. Fixture setup, navigation, browser-health, screenshot, or report-generation failures still fail the harness.

## Computed-style inventory

For visible semantic page elements, panels, and controls, the JSON and Markdown reports inventory useful computed-style signals such as radii, typography, colors, shadows, spacing, dimensions, border treatments, button/control treatments, and card/panel treatments. Counts and representative elements are included for context.

The inventory is descriptive evidence, not a list of defects. A unique value is not automatically a problem.
