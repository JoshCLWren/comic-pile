# Comic Pile - Bug Tracking & Planning

## Active Bugs
**NONE - All known bugs have been fixed!**

## Previously Completed Bug Fixes

### 1. Finishing session doesn't clear snoozed_thread_ids (COMPLETED)
- **Severity**: High
- **Location**: `app/api/rate.py`
- **Test**: `tests_e2e/test_dice_ladder_e2e.py::test_finish_session_clears_snoozed`
- **Issue**: When a session ends via `finish_session=True` in rate endpoint, `session.snoozed_thread_ids` was never cleared.
- **Fix**: Added `current_session.snoozed_thread_ids = None` when session ends (app/api/rate.py:173)
- **Commit**: `a313a75 Fix: Clear snoozed_thread_ids when session ends`
- **Status**: COMPLETED



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

#### Atomic Tasks (in order):
- [x] 1.1 Create `useSession.js` hook with useState+useEffect (no RQ)
- [x] 1.2 Create `useRate.js` hook with useState+useEffect (no RQ)
- [x] 1.3 Create `useRoll.js` hook with useState+useEffect (no RQ)
- [x] 1.4 Create `useSnooze.js` hook with useState+useEffect (no RQ)
- [x] 1.5 Create `useThread.js` hook with useState+useEffect (no RQ)
- [x] 1.6 Create `useQueue.js` hook with useState+useEffect (no RQ)
- [x] 1.7 Create `useUndo.js` hook with useState+useEffect (no RQ)
- [x] 1.8 Create `useAnalytics.js` hook with useState+useEffect (no RQ)
  - [x] 1.9 Update `main.jsx` to remove QueryClientProvider
  - [x] 1.10 Update `services/api.js` to remove QueryClient export
  - [x] 1.11 Update `RollPage.jsx` to use new hooks
   - [x] 1.12 Update `RatePage.jsx` to use new hooks
   - [x] 1.13 Update `SessionPage.jsx` to use new hooks
 - [x] 1.14 Update `QueuePage.jsx` to use new hooks
 - [x] 1.15 Update other pages using custom hooks
 - [x] 1.16 Run frontend linter and fix any issues
 - [x] 1.17 Update frontend unit tests after refactoring

### 1. Remove React Query - COMPLETED
- **Status**: COMPLETED
- **Completed by**: Task 1.17 (Update frontend unit tests after refactoring)
- **Summary**: All React Query dependencies removed, hooks refactored to use useState+useEffect, all tests passing (47/47)

### 2. Session State Duplication - COMPLETED
- **Location**: `frontend/src/pages/RatePage.jsx`, `frontend/src/pages/RollPage.jsx`
- **Issue**: Managing same data in React Query state AND local useState
- **Fix**: After React Query removal, use single source of truth with useState
- **Status**: COMPLETED (resolved by React Query removal)

### 3. Remove Excessive Polling - COMPLETED
- **Location**: `frontend/src/hooks/useSession.js` line 8
- **Issue**: `refetchInterval: 5000` polls API every 5 seconds
- **Fix**: Remove polling, rely on manual refetches or navigation-based fetches
- **Status**: COMPLETED (resolved by React Query removal)

## Notes from Session

### Production Issue - "Session spanning two deployments"
- **User observation**: Session appeared to cache incorrectly between deployments
- **Root cause**: React Query cache persistence across deployments
- **Current mitigation**: Set `staleTime: 0` and `gcTime: 0` in frontend/src/services/api.js
- **Better fix**: ✅ COMPLETED - Remove React Query entirely (see refactoring section above)

### Test Coverage
- **Backend tests**: 30/30 critical tests passing (rate, snooze, roll)
- **Frontend unit tests**: 47/47 passing after React Query removal
- **E2E tests**: 4/4 passing (dice ladder + snoozed clear bug)
- **Status**: ✅ All tests verified and passing

## Completed Work
- ✅ Created E2E tests for dice ladder behavior (tests_e2e/test_dice_ladder_e2e.py)
- ✅ Created test for session bug (tests_e2e/test_dice_ladder_e2e.py::test_finish_session_clears_snoozed)
- ✅ Identified React Query as source of deployment cache issues
- ✅ Confirmed backend logic is working (all rate/snooze/roll tests pass)
- ✅ Fixed snoozed_thread_ids not cleared when session ends (app/api/rate.py:173)
- ✅ Removed React Query from frontend (17 atomic tasks)
- ✅ Updated all frontend tests to work with new hooks (47/47 passing)
- ✅ Verified all critical backend tests passing
- ✅ Verified E2E tests passing

## Code Review Comments (PR Review Feedback)
### Vetted and Confirmed Issues
- ✅ **useAnalytics.js** - Return shape mismatch: Returns `{ data, isPending, isError }` but `AnalyticsPage.jsx` expects `{ data: metrics, isLoading, error }`
  - **Fix**: Renamed return object keys to match consumer expectations (COMPLETED)
- ✅ **useQueue.js** - Mutations don't rethrow errors, so callers can't handle failures
   - **Fix**: Added `throw error` after `setIsError(true)` in all catch blocks (COMPLETED)
- ✅ **useSession.js** - params = {} causes infinite refetches; state not reset when id becomes falsy
   - **Fix**: Added `EMPTY_PARAMS` constant, reset state in early return
   - **Commit**: fb30e59
- ✅ **useThread.js** - When id becomes falsy, stale data remains in state
  - **Fix**: Added `setData(null)`, `setIsError(false)`, `setIsPending(false)` in early return
  - **Commit**: ed4863c
  - **Status**: COMPLETED
- ✅ **useUndo.js** - Effect doesn't clear isPending on early return; no cancellation handling
   - **Fix**: Added `setIsPending(false)` before return, added isActive flag with cleanup
   - **Commit**: e19b4d5
   - **Status**: COMPLETED
- ❌ **test_dice_ladder_e2e.py** - Stale "BUG" comment in docstring; missing type annotations
  - **Fix needed**: Remove stale comment, add type annotations (AsyncClient, Session)
- ❌ **QueuePage.jsx** - Error handling in mutations fails (mutations swallow errors)
  - **Fix needed**: Add `await` before `moveToPositionMutation.mutate()` calls

### Not Issues (Confirmed)
- ✅ **useRate.js** - Error rethrowing already implemented correctly
- ✅ **useRoll.js** - Error rethrowing already implemented correctly
- ✅ **main.jsx** - React Query properly removed, QueryClientProvider not needed
- ✅ **test_dice_ladder_e2e.py** - Test correctly verifies bug fix
