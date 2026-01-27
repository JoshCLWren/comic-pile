# Comic Pile - Bug Tracking & Planning

## Active Bugs

### 1. Finishing session doesn't clear snoozed_thread_ids
- **Severity**: High
- **Location**: `app/api/ate.py`
- **Test**: `tests_e2e/test_dice_ladder_e2e.py::test_finish_session_clears_snoozed` (xfail)
- **Issue**: When a session ends via `finish_session=True` in the rate endpoint, `session.snoozed_thread_ids` is never cleared. The snoozed thread list persists to the next session.
- **Expected**: `session.snoozed_thread_ids` should be `None` or `[]` after session ends
- **Actual**: `session.snoozed_thread_ids` retains snoozed thread IDs
- **Fix needed**: Clear `snoozed_thread_ids` in rate endpoint when `finish_session` is true
- **Status**: QUEUED


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
- [ ] 1.1 Create `useSession.js` hook with useState+useEffect (no RQ)
- [ ] 1.2 Create `useRate.js` hook with useState+useEffect (no RQ)
- [ ] 1.3 Create `useRoll.js` hook with useState+useEffect (no RQ)
- [ ] 1.4 Create `useSnooze.js` hook with useState+useEffect (no RQ)
- [ ] 1.5 Create `useThread.js` hook with useState+useEffect (no RQ)
- [ ] 1.6 Create `useQueue.js` hook with useState+useEffect (no RQ)
- [ ] 1.7 Create `useUndo.js` hook with useState+useEffect (no RQ)
- [ ] 1.8 Create `useAnalytics.js` hook with useState+useEffect (no RQ)
- [ ] 1.9 Update `main.jsx` to remove QueryClientProvider
- [ ] 1.10 Update `services/api.js` to remove QueryClient export
- [ ] 1.11 Update `RollPage.jsx` to use new hooks
- [ ] 1.12 Update `RatePage.jsx` to use new hooks
- [ ] 1.13 Update `SessionPage.jsx` to use new hooks
- [ ] 1.14 Update `QueuePage.jsx` to use new hooks
- [ ] 1.15 Update other pages using custom hooks
- [ ] 1.16 Run frontend linter and fix any issues
- [ ] 1.17 Update frontend unit tests after refactoring

### 2. Session State Duplication
- **Location**: `frontend/src/pages/RatePage.jsx`, `frontend/src/pages/RollPage.jsx`
- **Issue**: Managing same data in React Query state AND local useState
- **Fix**: After React Query removal, use single source of truth with useState
- **Status**: BLOCKED until task 1.1-1.12 complete

### 3. Remove Excessive Polling
- **Location**: `frontend/src/hooks/useSession.js` line 8
- **Issue**: `refetchInterval: 5000` polls API every 5 seconds
- **Fix**: Remove polling, rely on manual refetches or navigation-based fetches
- **Status**: BLOCKED until task 1.1 complete (new hook won't have polling)

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
- **Status**: BLOCKED until task 1.17 complete

## Completed Work
- ✅ Created E2E tests for dice ladder behavior (tests_e2e/test_dice_ladder_e2e.py)
- ✅ Created test for session bug (tests_e2e/test_dice_ladder_e2e.py::test_finish_session_clears_snoozed)
- ✅ Identified React Query as source of deployment cache issues
- ✅ Confirmed backend logic is working (all rate/snooze/roll tests pass)
