# Die Mode Functionality Analysis - Issue #4279

## Issue Summary
Issue #4279 relates to die mode persistence and AUTO control behavior on the Roll page:
- Manual die mode is lost when navigating Queue -> Roll (die resets to AUTO d6) but preserved when navigating Glossary -> Roll
- Clicking AUTO to clear manual override disables the button without switching; AUTO only takes effect after a reload, eventually resuming d8

This is distinct from HistoryPage die display (issue #4243).

## Investigation Results

### Issue Status: UNRESOLVED ⚠️

The cited commit #4258 ([MQA-ROLL-005] History session 'Die size' follows the current die instead of the session's recorded die) fixed HistoryPage display for issue #4243. It does not address manual mode persistence across navigation or immediate AUTO switch. No code changes in this PR address the reported navigation inconsistency or AUTO control delay.

### Root Cause (HistoryPage fix, unrelated to #4279)
Issue #4243 was caused by HistoryPage displaying `session.current_die` instead of `session.start_die`. This was fixed in commit #4258 in `frontend/src/pages/HistoryPage.tsx`.

### Verification Limits for This PR
This PR adds documentation only. No code changes were made to Roll page navigation or die-mode mutations.

- The cited `HistoryPage` test (`frontend/src/unit/HistoryPage.test.tsx` lines 503-534) verifies `reports the session start die in activity line, not the evolving current die (issue #4243)`. It renders a mocked session and checks the history label only. It never selects a die, navigates between Queue/Glossary/Roll, or exercises AUTO clearing.
- No test covers manual mode persistence across Queue -> Roll vs Glossary -> Roll navigation.
- No test verifies that clicking AUTO immediately clears manual override without requiring a reload.

Therefore the verification evidence cited in the original draft does not demonstrate resolution of issue #4279.

### Verification

1. **Frontend Tests for HistoryPage (issue #4243, not #4279):** All tests pass, including:
   - Test: `reports the session start die in activity line, not the evolving current die (issue #4243)`
   - Location: `frontend/src/unit/HistoryPage.test.tsx` (lines 503-534)
   - Status: ✅ PASSING
   - Limitation: Does not exercise die selection, navigation, or AUTO control.

2. **Issue #4279 Verification Gap:**
   - Manual mode persistence across Queue -> Roll vs Glossary -> Roll has no automated test coverage in this change.
   - AUTO button immediate switch behavior is not verified by code changes or tests in this PR.
   - No evidence provided for the reported reproduction steps (A2-A5).

### Current Die Mode Implementation

#### Frontend Components:
- **RollHeader.tsx**: Displays die controls and Auto/manual mode toggle
- **useRollActions.ts**: Handles die mode switching actions
- **useRoll.ts**: Contains die mode mutations
- **cacheEffects.ts**: Handles cache invalidation after die mode changes

#### Backend Endpoints:
- **POST /api/roll/set-die**: Sets manual die size for current session
- **POST /api/roll/clear-manual-die**: Clears manual die and returns to automatic mode
- **GET /api/roll/bootstrap**: Returns current die state and manual die status

#### Key Features:
1. **Manual Die Mode**: Users can select specific die sizes (d4, d6, d8, d10, d12, d20, d30, d50, d100)
2. **Auto Mode**: System automatically uses the dice ladder based on available series
3. **Cache Invalidation**: Proper cache updates when die mode changes
4. **History Stability**: Historical sessions show their original start die, not current settings

### No Further Action Required
**Not applicable.** The issue described in #4279 remains unresolved. The HistoryPage fix (commit #4258) addresses issue #4243 only.

### Recommendations
1. Investigate why manual mode is lost on Queue -> Roll navigation but preserved on Glossary -> Roll. Potential causes include React Query invalidation timing (`invalidateRollBootstrapOnNavigation`), component state reset (`state.currentDie` reinitializes to 6 on mount), or differing navigation caching behavior.
2. Verify that `useClearManualDie` mutation invalidates bootstrap immediately and triggers UI update without reload. Check if `invalidateAfterRollDieModeUpdate` causes a refetch race or if `state.currentDie` needs syncing from `bootstrap.current_die` after manual mode clears.
3. Add integration tests covering manual mode persistence across navigation paths and immediate AUTO switch.
4. Document die mode behavior in developer documentation once fixes are verified.

---
*Analysis completed on: 2026-10-28*
*Status: Issue #4279 unresolved; documentation corrected to reflect verification limits*
