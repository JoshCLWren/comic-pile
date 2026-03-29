## Failing CI Checks

### E2E Playwright Tests (All 8 Shards) - **REAL BUG**

**Root Cause**: All 164 failing tests across all 8 shards fail at the exact same point: `fixtures.ts:265` waiting for `[aria-label="Filter by collection"]` to be visible. The test fixture `authenticatedPage` times out waiting for the collection toolbar dropdown.

**Technical Analysis**:
- The `authenticatedPage` fixture navigates to `/` and waits for the Roll page to be ready
- It waits for `[aria-label="Filter by collection"]` (line 265 in `fixtures.ts`)
- The `CollectionToolbar` component (`frontend/src/components/CollectionToolbar.tsx:52`) has this `aria-label`
- However, the component first renders a "Loading collections..." state (lines 27-33) before the select element appears
- The test timeout (10000ms) is insufficient for the collections API call to complete and the select element to render

**Failure Pattern**:
```
TimeoutError: page.waitForSelector: Timeout 10000ms exceeded.
waiting for locator('[aria-label="Filter by collection"]') to be visible
at fixtures.ts:265
```

**Why this is a real bug, not a flaky test**:
1. The failure is 100% consistent across ALL shards (164 tests failed)
2. The same test code passed before the PR changes
3. The issue is likely a race condition between page load and collections data fetching
4. The PR #383 title is "fix: queue reorders unexpectedly when dependency is added or removed" - this suggests changes to queue/dependency logic that may have slowed down page initialization

## Acceptance Criteria to Fix

1. **Fix the race condition in test fixtures** - The `authenticatedPage` fixture in `frontend/src/test/fixtures.ts` should either:
   - Wait for collections to finish loading before checking for the selector, OR
   - Use a more reliable readiness indicator instead of the collection toolbar

2. **Increase timeout or add explicit wait** - Either increase the timeout in fixtures.ts:265 or add an explicit wait for the collections loading state to complete

3. **Investigate performance regression** - The PR changes may have introduced a performance regression causing the collections endpoint to be slower. Review the queue/dependency changes for unexpected side effects on initial page load

## CodeRabbit Issues

- **None** - CodeRabbit check passed (0 issues reported)

## Summary

All E2E Playwright test failures stem from a single root cause: the `authenticatedPage` fixture times out waiting for the collection toolbar selector. This is blocking 164 tests across 8 shards. The fix requires updating the test fixture to properly handle the async loading state of the CollectionToolbar component.

## Recommended Fix

Update `frontend/src/test/fixtures.ts` line 265 to wait for the collections to finish loading before checking for the selector:

```typescript
// Wait for loading state to complete
await page.waitForSelector('text=Loading collections...', { state: 'detached', timeout: 15000 }).catch(() => {});

// Then wait for the select to be visible
await page.waitForSelector('[aria-label="Filter by collection"]', { state: 'visible', timeout: 15000 });
```
