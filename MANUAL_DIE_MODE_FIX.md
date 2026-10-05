# Fix for Issue #3144: Manual die mode shows a ladder move that never happens

## Problem
When a manual die was set (e.g., d20 via the die selector), the die would stay pinned in manual mode, but the rating card would still show a ladder move like "d20 → d12" (for a 5.0) or "d20 → d30" (for a 1.0). This was confusing because the UI promised a die change that would never happen due to manual mode overriding it.

## Solution
Modified the DecisionCard component to detect manual die mode and display appropriate messaging:

### Changes Made

1. **Updated DecisionCard Component** (`/frontend/src/pages/RollPage/components/DecisionCard.tsx`):
   - Added `manualDie` prop to the component interface
   - Modified ladder display logic to show "Manual die pinned at d{currentDie}" when in manual mode
   - Added JSDoc documentation explaining the manual die mode behavior

2. **Updated RatingView Data Structure** (`/frontend/src/pages/RollPage/useRatingView.ts`):
   - Added `manualDie` to the `RatingViewData` interface
   - Added `bootstrap` parameter to `UseRatingViewParams` interface
   - Extract `manualDie` from bootstrap data in the return value

3. **Updated RollPage Component** (`/frontend/src/pages/RollPage/index.tsx`):
   - Pass `bootstrap` data to the `useRatingView` hook

4. **Updated RatingView Component** (`/frontend/src/pages/RollPage/components/RatingView.tsx`):
   - Pass `manualDie` prop from the data object to the DecisionCard

### Behavior Changes

**Manual Die Mode** (`manualDie !== null`):
- Shows: "Manual die pinned at d{currentDie}"
- Does NOT show the ladder move
- Example: "Manual die pinned at d20"

**Auto Mode** (`manualDie === null`):
- Shows normal ladder move: "d{currentDie} → d{predictedDie}"
- Example: "d6 → d8" or "d20 → d12"

### Testing

1. **Unit Tests** (`/frontend/src/unit/DecisionCard.test.tsx`):
   - Test manual die mode messaging
   - Test auto mode ladder display
   - Test rating functionality in both modes
   - Test loading states and error handling

2. **E2E Tests** (`/frontend/src/test/decision-card-manual-die-mode.spec.ts`):
   - Test manual die mode shows correct messaging
   - Test auto mode shows ladder move
   - Test switching between manual and auto modes

3. **Logic Verification**:
   - Created and ran verification script to confirm logic works correctly
   - All test cases passed

## Impact
- **User Experience**: Eliminates confusion by clearly indicating when the die is pinned in manual mode
- **Consistency**: UI now accurately reflects the actual behavior of the system
- **Backward Compatibility**: All existing functionality remains intact
- **Accessibility**: Clear messaging helps users understand the system behavior

## Files Modified
1. `/frontend/src/pages/RollPage/components/DecisionCard.tsx` - Main fix
2. `/frontend/src/pages/RollPage/useRatingView.ts` - Data structure updates
3. `/frontend/src/pages/RollPage/index.tsx` - Bootstrap data passing
4. `/frontend/src/pages/RollPage/components/RatingView.tsx` - Prop passing

## Files Added
1. `/frontend/src/unit/DecisionCard.test.tsx` - Unit tests
2. `/frontend/src/test/decision-card-manual-die-mode.spec.ts` - E2E tests

## Verification
The fix has been verified to work correctly through:
- Logic testing with verification script
- Unit tests covering all scenarios
- E2E tests covering real browser interactions
- Manual testing of the complete user flow

The solution addresses the exact issue described in #3144 and provides a clear, user-friendly experience for both manual and auto die modes.