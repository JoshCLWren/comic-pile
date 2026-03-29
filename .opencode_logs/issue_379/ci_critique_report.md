# Failing CI Checks

## Failing CI Checks

- **E2E Playwright Tests (Shards 1/8 to 8/8)**: `real bug`
  These failures are due to a **timeout** in `fixtures.ts:265`, where the test waits for `selector=[aria-label="Filter by collection"]` to load but it never appears within 10000ms.
  
  **Failing Tests and Files** (complete list):
  - `frontend/src/test/roll.spec.ts:5:3` - "Roll Dice Feature: should display die selector on home page"
  - `frontend/src/test/roll.spec.ts:34:3` - "Roll Dice Feature: should show tap instruction on first visit"
  - `frontend/src/test/network.spec.ts:237:3` - "Network & API Tests: should sanitize user input in requests"
  - `frontend/src/test/network.spec.ts:251:3` - "Network & API Tests: should include proper error messages in API responses"
  - `frontend/src/test/roll.spec.ts:358:5` - "Issue Metadata Persistence: should persist issue metadata after page reload"
  - `frontend/src/test/roll.spec.ts:436:5` - Issue Metadata Persistence: should persist issue metadata after 409 conflict recovery


## Acceptance Criteria to Fix

1. **Identify and refactor `authenticatedPage` fixture in fixtures.tsx to use a more stable selector**, such as the visual "Roll Dice" tab.
2. **Eliminate dependency on `aria-label="Filter by collection" selector`**, as it causeswatch CI timeouts.
3. **Add fallback handling or retry logic** for selectors that depend on pre-populated data not visible in CI setups.