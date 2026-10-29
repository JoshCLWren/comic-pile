# Die Mode Functionality Analysis - Issue #4279

## Issue Summary
Issue #4279 relates to die mode persistence and AUTO control behavior on the Roll page:
- Manual die mode is lost when navigating Queue -> Roll (die resets to AUTO d6) but preserved when navigating Glossary -> Roll
- Clicking AUTO to clear manual override disables the button without switching; AUTO only takes effect after a reload, eventually resuming d8

This is distinct from HistoryPage die display (issue #4243).

## Investigation Results

### Issue Status: RESOLVED ✅

The root causes were identified and fixed in this PR:

1. **Manual die mode lost on navigation to Roll** (`frontend/src/pages/RollPage/useRollBootstrapSync.ts:37-43`): The bootstrap sync effect projected `bootstrap.current_die` (the auto/ladder die) onto page state but ignored `bootstrap.manual_die`. When the Roll page mounted after navigation, `currentDie` was reset to the auto die instead of the pinned manual die. Fix: sync `currentDie` to `bootstrap.manual_die ?? bootstrap.current_die` so manual mode survives page remount on any navigation path (Queue -> Roll and Glossary -> Roll).

2. **AUTO switch requires reload** (`frontend/src/pages/RollPage/useRollActions.ts:285-291`): `handleClearManualDie` awaited the `clearManualDieMutation` without optimistically updating local `currentDie`. The UI only reflected AUTO mode after the bootstrap cache invalidation triggered a refetch. Fix: set `currentDie` optimistically to `bootstrap.current_die` before the mutation, so AUTO takes effect immediately without a reload.

### Root Cause (HistoryPage fix, unrelated to #4279)
Issue #4243 was caused by HistoryPage displaying `session.current_die` instead of `session.start_die`. This was fixed in commit #4258 in `frontend/src/pages/HistoryPage.tsx`.

### Verification

1. **Frontend Tests for HistoryPage (issue #4243, not #4279):** All tests pass, including:
   - Test: `reports the session start die in activity line, not the evolving current die (issue #4243)`
   - Location: `frontend/src/unit/HistoryPage.test.tsx` (lines 503-534)
   - Status: ✅ PASSING

2. **Issue #4279 die-mode regression tests:** All pass:
   - `frontend/src/unit/RollPage.roll-mode-control.test.tsx` — 7 tests, ✅ PASSING
   - `frontend/src/unit/rollDieModeReadout.test.tsx` — 5 tests, ✅ PASSING
   - `frontend/src/unit/useRoll.test.tsx` — ✅ PASSING
   - `frontend/src/unit/useRollActions.snooze.test.tsx` — ✅ PASSING
   - `frontend/src/unit/useRollBootstrap.test.tsx` — ✅ PASSING
   - `frontend/src/unit/useRollBootstrapTimezone.test.tsx` — ✅ PASSING

3. **Frontend lint:** `pnpm run lint` — 0 errors (pre-existing warnings only)
4. **Frontend typecheck:** `pnpm run typecheck` — clean

### Files Changed

- `frontend/src/pages/RollPage/useRollBootstrapSync.ts` — project `currentDie` onto `bootstrap.manual_die ?? bootstrap.current_die` so manual mode persists across navigation
- `frontend/src/pages/RollPage/useRollActions.ts` — optimistically set `currentDie` in `handleClearManualDie` so AUTO clears manual override immediately
- `die_mode_analysis.md` — corrected to reflect that issue #4279 is resolved with code changes

### No Further Action Required
Issue #4279 is resolved. Manual die mode persists consistently across all navigation paths to Roll, and clicking AUTO immediately clears the manual override without requiring a reload.

---

*Analysis completed on: 2026-10-28*
*Status: Issue #4279 resolved; code changes fix manual die persistence and immediate AUTO switch*
