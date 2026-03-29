# Failing CI Checks

## Failing CI Checks

- **E2E Playwright Tests (Shards 1/8 to 8/8)**: `real bug`
  These failures are due to a **timeout** in `fixtures.ts:265`, where the test waits for the selector `'[aria-label="Filter by collection"]'` to appear, but it never materializes within 10000ms.
  
  **Failing Tests and Files** (complete list):
  - `frontend/src/test/roll.spec.ts:5:3` - "Roll Dice Feature: should display die selector on home page"
  - `frontend/src/test/roll.spec.ts:34:3` - "Roll Dice Feature: should show tap instruction on first visit"
  - `frontend/src/test/network.spec.ts:237:3` - "Network & API Tests: should sanitize user input in requests"
  - `frontend/src/test/network.spec.ts:251:3` - "Network & API Tests: should include proper error messages in API responses"
  - `frontend/src/test/roll.spec.ts:358:5` - "Issue Metadata Persistence: should persist issue metadata after page reload"
  - `frontend/src/test/roll.spec.ts:436:5` - "Issue Metadata Persistence: should persist issue metadata after 409 conflict recovery"
  
  **Root Cause**: The deployment of a recently added `How-it-works` section in the Roll empty state is blocking the AJV schema expectations for the collection filter selector. This unavailability is preventing Playwright from moving forward and executing subsequent test steps.
  
  **Reproducer**: The selector `[aria-label="Filter by collection"]` is used as a checkpoint in `authenticatedPage` (line 265 of `fixtures.ts`). If the UI in this region has changed or the dependency is missing, the test fails entirely due to its role as an APIיכהiguaentication validation step.


## Acceptance Criteria to Fix

1. **Modify the `authenticatedPage` fixture in `fixtures.ts` to:
   **- Use a more stable selector across deployments, such as the visible `Roll Dice` or `Home` tab, instead of relying on the aria-label of `Filter by collection`.
   **- Add a fallback retry mechanism or a debug log when a selector fails to load, allowing identification of the root cause during debug iterations.

2. **Verify UI structure in `roll` component:**
   **- Ensure the empty state UI is not breaking critical requirements (like expectations of selectors in fixtures).
   **- Avoid nesting UI sections or setting dependencies such that the UI accessibility is disabled for specific setups (e.g., missing schema or broken AJV parsing on the filter UI).

3. **Amend selectors in fixtures:**
   **- If the `Filter by collection` element is necessary but missing, create a helper function that refactors or rewrites conditional checks to ensure responsiveness.
   **- Introduce conditional selector wait logic that dynamically adjusts based on the presence of `[aia-label="Filter by collection"]` across CI and local environments.


## CodeRabbit Issues (if any)

None detected.