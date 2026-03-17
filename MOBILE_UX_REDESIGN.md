# Mobile UX Redesign — Based on Browser Audit

The browser audit (3 sessions, 15 threads, 124 dependencies) revealed that dependency management is basically unusable on mobile. The flowchart is hidden entirely, the dependency builder is a flat dump, and thread cards show a 🔒 with no context.

## User Review Required

> [!IMPORTANT]
> This plan is scoped to fix the **top issues found in the audit**. It does NOT add new backend features (like a ReadingOrder entity). All changes are frontend-only except removing Simple Counter logic. This keeps the scope tight and shippable.
> [!WARNING]
> Removing Simple Counter means all new threads will use individual issue tracking. Existing simple-counter threads will still work but can't be created anymore.

---

## Proposed Changes

### Phase 1: Remove Simple Counter (Issue #6) ✅ COMPLETE

Default `trackingMode` to `'tracked'`, remove the toggle, and always show the tracked-issues form fields.

#### [MODIFY] `frontend/src/pages/QueuePage.tsx`

- ✅ Line 598: Change default `trackingMode: 'simple'` → `'tracked'`
- ✅ Line 852: Change reset default `trackingMode: 'simple'` → `'tracked'`
- ✅ Lines 1255–1281: Remove the Simple Counter / Track Individual Issues toggle UI entirely
- ✅ Lines 1284–1300: Remove the conditional — always show the tracked-issues form

---

### Phase 2: Inline Blocking Info on Queue Cards (Issues #2, #3) ✅ COMPLETE

Show *what* is blocking directly on each thread card, not just a 🔒.

#### [MODIFY] `frontend/src/pages/QueuePage.tsx`

- ✅ Expand the existing 🔒 indicator area on thread cards to include a one-line summary like "Blocked by: Ultimate X-Men #7" (the next unread prerequisite)
- ✅ Fetch blocking info from the existing `/api/v1/dependencies/blocking/{thread_id}` endpoint
- ✅ Show a count of remaining blockers, e.g., "🔒 3 issues to read first"
- ✅ Tapping the blocking info opens the dependency builder directly (skip the action sheet)

---

### Phase 3: Mobile Dependency Visualizer (Issue #1) ✅ COMPLETE

The flowchart is `hidden md:block` — make it work on mobile with a vertical timeline layout.

#### [MODIFY] `frontend/src/components/DependencyTimeline.tsx`

- ✅ Redesign from a read-only list into an interactive vertical timeline
- ✅ Show reading order sequence with ✅ (read), 🔵 (next to read), ⬜ (upcoming) status indicators
- ✅ Make it the default view on mobile (below `md` breakpoint)
- ✅ Add thread/issue labels like "Ultimate Spider-Man #3 → Ultimate X-Men #8"

#### [MODIFY] `frontend/src/components/DependencyFlowchart.tsx`

- ✅ Remove `hidden md:block` — conditionally render Timeline on mobile, Flowchart on desktop
- ✅ Pass proper data to DependencyTimeline including read/unread status

#### [MODIFY] `frontend/src/components/DependencyBuilder.tsx`

- ✅ Move the "View Flowchart" toggle to the top of the modal (not buried at the bottom)
- ✅ Make the close (×) button sticky at the top when scrolling
- ✅ Group the flat dependency list by thread name instead of one flat dump

---

### Phase 4: Roll Page Context (Issue #5) ✅ COMPLETE

Explain why threads are missing from the roll pool.

#### [MODIFY] `frontend/src/pages/RollPage.tsx`

- ✅ Add a small info line below the pool like "14 threads hidden (blocked by dependencies)"
- ✅ Tapping it shows a collapsible list of blocked threads with their blocker

---

## Verification Plan

### Existing Tests (must still pass)

All existing Playwright and unit tests must remain green. These cover the dependency system thoroughly.

```bash
# Playwright E2E (must build frontend first)
cd frontend && npm run build && npx playwright test dependencies.spec.ts --project=chromium
cd frontend && npm run build && npx playwright test flowchart.spec.ts --project=chromium

# Unit tests
cd frontend && npm test -- --run
```

### New Playwright Tests

#### Remove Simple Counter
- Test that the Create Thread modal no longer shows a "Simple counter" button
- Test that new threads are created with issue tracking by default

#### Inline Blocking Info
- Test that a blocked thread's card shows the blocking thread name
- Test that tapping the blocking info opens the dependency builder

#### Mobile Timeline
- Test at mobile viewport that the dependency view shows a vertical timeline (not the horizontal SVG)
- Test that the timeline shows read/unread status indicators

```bash
cd frontend && npm run build && npx playwright test --project=chromium
```

### Browser Testing

After implementation, I'll test in Chrome at mobile width (same setup as the audit) and compare against the screenshots in the walkthrough.
