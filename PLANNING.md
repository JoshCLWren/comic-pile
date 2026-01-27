# Comic Pile - Bug Tracking & Planning

## Active Bugs

### 1. Finishing session doesn't clear snoozed_thread_ids
- **Severity**: High
- **Location**: `app/api/rate.py`
- **Test**: `tests_e2e/test_dice_ladder_e2e.py::test_finish_session_clears_snoozed` (xfail)
- **Issue**: When a session ends via `finish_session=True` in the rate endpoint, `session.snoozed_thread_ids` is never cleared. The snoozed thread list persists to the next session.
- **Expected**: `session.snoozed_thread_ids` should be `None` or `[]` after session ends
- **Actual**: `session.snoozed_thread_ids` retains snoozed thread IDs
- **Fix needed**: Clear `snoozed_thread_ids` in rate endpoint when `finish_session` is true

## Confirmed Working (No Bugs)

### Dice Ladder Behavior
- ✅ Rating < 4 → die steps UP (`test_rate_low_rating` in test_rate_api.py:59-103)
- ✅ Rating >= 4 → die steps DOWN (`test_rate_high_rating` in test_rate_api.py:107-151)
- ✅ Snoozing → die steps UP (`test_snooze_success` in test_snooze_api.py:11-76)
- ✅ All E2E tests pass in `tests_e2e/test_dice_ladder_e2e.py`

## Technical Debt / Refactoring

### 1. Remove React Query
- **Reason**: Adding complexity without solving real problems
- **Issues**:
  - Cross-deployment cache pollution
  - Excessive polling (5s intervals)
  - Duplicate state management (RQ data + local useState)
  - Shotgun cache invalidation
  - `staleTime: 30000` never actually used
- **Action**: Replace `useQuery`/`useMutation` with simple `useEffect` + `useState` hooks
- **Hooks to refactor**:
  - `frontend/src/hooks/useSession.js`
  - `frontend/src/hooks/useRoll.js`
  - `frontend/src/hooks/useRate.js`
  - `frontend/src/hooks/useSnooze.js`
  - `frontend/src/hooks/useThread.js`
  - `frontend/src/hooks/useUndo.js`
  - `frontend/src/hooks/useQueue.js`
  - `frontend/src/hooks/useAnalytics.js`
- **Files to update**:
  - `frontend/src/services/api.js` - Remove QueryClient, revert to plain axios
  - `frontend/src/main.jsx` - Remove QueryClientProvider
  - All pages that use custom hooks

### 2. Session State Duplication
- **Location**: `frontend/src/pages/RatePage.jsx`, `frontend/src/pages/RollPage.jsx`
- **Issue**: Managing same data in React Query state AND local useState
- **Fix**: After React Query removal, use single source of truth with useState

### 3. Remove Excessive Polling
- **Location**: `frontend/src/hooks/useSession.js` line 8
- **Issue**: `refetchInterval: 5000` polls API every 5 seconds
- **Fix**: Remove polling, rely on manual refetches or navigation-based fetches

## Notes from Session

### Production Issue - "Session spanning two deployments"
- **User observation**: Session appeared to cache incorrectly between deployments
- **Root cause**: React Query cache persistence across deployments
- **Current mitigation**: Set `staleTime: 0` and `gcTime: 0` in frontend/src/services/api.js
- **Better fix**: Remove React Query entirely (see refactoring section above)

### Test Coverage
- **Current**: Tests prove dice ladder behavior works correctly
- **Missing**: Frontend unit tests after React Query removal
- **Action**: Update frontend tests in `frontend/src/test/` after refactoring

## Completed Work
- ✅ Created E2E tests for dice ladder behavior (tests_e2e/test_dice_ladder_e2e.py)
- ✅ Created test for session bug (tests_e2e/test_dice_ladder_e2e.py::test_finish_session_clears_snoozed)
- ✅ Identified React Query as source of deployment cache issues
- ✅ Confirmed backend logic is working (all rate/snooze/roll tests pass)
