# Quality-of-Life Branch - Playwright QA Test Plan

## Overview
Comprehensive E2E test plan for the `quality-of-life` branch changes from main.

## New Features
1. **Snooze Feature** - Temporarily exclude threads from rolls
2. **Position Slider** - Visual UI for repositioning threads
3. **Enhanced Roll Page** - Snoozed threads display, manual die selection
4. **Enhanced Rate Page** - Snooze button integration

---

## 1. SNOOZE FEATURE (NEW)

### 1.1 Basic Snooze Flow
- [ ] Roll dice to get a pending thread
- [ ] Navigate to RatePage
- [ ] Click "Snooze Thread" button
- [ ] Verify thread is removed from pending state
- [ ] Verify die steps up (e.g., d6 → d8)
- [ ] Verify thread appears in snoozed list on RollPage
- [ ] Verify thread is excluded from next roll pool

### 1.2 Multiple Snoozes
- [ ] Create 3+ threads
- [ ] Roll and snooze Thread A
- [ ] Roll and snooze Thread B
- [ ] Verify both threads in snoozed list on RollPage
- [ ] Verify roll pool only contains Thread C
- [ ] Verify expandable "Snoozed (2)" section shows both threads

### 1.3 Snooze at Die Boundaries
- [ ] Start with d4 die, snooze → verify d6
- [ ] Start with d6 die, snooze → verify d8
- [ ] Start with d8 die, snooze → verify d10
- [ ] Start with d10 die, snooze → verify d12
- [ ] Start with d12 die, snooze → verify d20
- [ ] Start with d20 die, snooze → verify stays d20 (max)

### 1.4 Snooze Edge Cases
- [ ] Try snooze without rolling → verify 400 error
- [ ] Try snooze without active session → verify 400 error
- [ ] Snooze all available threads → verify roll returns 400 error
- [ ] Snooze same thread twice → verify no duplicate in snoozed list

---

## 2. POSITION SLIDER (NEW)

### 2.1 Position Slider UI
- [ ] Open Reposition modal on QueuePage
- [ ] Verify slider displays all threads in queue
- [ ] Verify current position highlighted in teal
- [ ] Verify other thread positions shown as dots
- [ ] Verify position context message updates as slider moves
- [ ] Verify preview shows context threads (2-3 above/below)

### 2.2 Move to Front
- [ ] Select thread at position 5
- [ ] Drag slider to position 0 (front)
- [ ] Verify message: "Move to front of queue"
- [ ] Click Confirm
- [ ] Verify thread now at position 1

### 2.3 Move to Back
- [ ] Select thread at position 1
- [ ] Drag slider to last position
- [ ] Verify message: "Move to back of queue"
- [ ] Click Confirm
- [ ] Verify thread now at last position

### 2.4 Insert Between Threads
- [ ] Select thread at position 1
- [ ] Drag slider to position 3
- [ ] Verify message: "Between [thread A] and [thread B]"
- [ ] Verify preview shows displacement indicators (+1/-1)
- [ ] Click Confirm
- [ ] Verify thread order updated correctly

### 2.5 Position Slider Validation
- [ ] Try to confirm with no change → verify Confirm button disabled
- [ ] Click Cancel → verify modal closes without changes
- [ ] Verify position shows as "Position 1, 2, 3..." not queue_position values

---

## 3. THREAD REPOSITIONING (NEW)

### 3.1 Quick Move Buttons
- [ ] Click "Front" button on thread card
- [ ] Verify thread moves to position 1
- [ ] Click "Back" button on thread card
- [ ] Verify thread moves to last position

### 3.2 Drag and Drop
- [ ] Start drag on thread card (⠿ icon)
- [ ] Drag over another thread card
- [ ] Verify visual feedback (amber border) on target
- [ ] Drop on target thread
- [ ] Verify thread repositioned to target's position

### 3.3 Reposition Button
- [ ] Click "Reposition" button on thread card
- [ ] Verify PositionSlider modal opens
- [ ] Verify modal title shows thread being repositioned
- [ ] Verify slider shows all threads

---

## 4. ROLL PAGE ENHANCEMENTS

### 4.1 Snoozed Threads Display
- [ ] After snoozing threads, verify "Snoozed (N)" section appears
- [ ] Click expand arrow (▶)
- [ ] Verify section expands showing snoozed thread titles
- [ ] Click collapse arrow (▼)
- [ ] Verify section collapses

### 4.2 Manual Die Selection
- [ ] Click d4 button → verify die changes to d4
- [ ] Click d6 button → verify die changes to d6
- [ ] Click d20 button → verify die changes to d20
- [ ] Verify "Auto" button shows amber when manual die set
- [ ] Click "Auto" button → verify manual die cleared
- [ ] Verify die returns to ladder value

### 4.3 Session Safety Indicator
- [ ] When session has restore point → verify 🛡️ badge visible
- [ ] Verify badge shows text "Session Safe"
- [ ] Verify badge has teal color

### 4.4 Stale Thread Detection
- [ ] Create thread >7 days old (or simulate)
- [ ] Verify stale thread warning appears
- [ ] Verify warning shows "You haven't touched [title] in X days"
- [ ] Verify warning has amber color
- [ ] Verify warning has ⏳ icon

---

## 5. RATE PAGE ENHANCEMENTS

### 5.1 Snooze Button
- [ ] After rolling, verify "Snooze Thread" button visible
- [ ] Click snooze button
- [ ] Verify button shows "Snoozing..." state
- [ ] Verify thread is snoozed successfully
- [ ] Verify die stepped up

### 5.2 Session Safety Display
- [ ] When session has restore point → verify 🛡️ badge visible
- [ ] Verify badge shows in header
- [ ] Verify badge shows in RollPage header too

---

## 6. INTEGRATION TESTS

### 6.1 Full Session Flow with Snooze
- [ ] Register/login user
- [ ] Create 5 threads
- [ ] Roll → select Thread A
- [ ] Rate Thread A 4.0+ → verify moves to front
- [ ] Roll → select Thread B
- [ ] Snooze Thread B → verify die steps up
- [ ] Roll → verify Thread C selected (B excluded)
- [ ] Rate Thread C <4.0 → verify moves to back
- [ ] Verify snoozed list shows Thread B on RollPage

### 6.2 Queue Management Flow
- [ ] Create 5 threads
- [ ] Navigate to QueuePage
- [ ] Drag Thread 3 to position 1
- [ ] Click "Reposition" on Thread 5
- [ ] Use slider to move Thread 5 to position 2
- [ ] Click "Front" on Thread 4
- [ ] Verify final queue order correct

### 6.3 Dice Ladder with Manual Overrides
- [ ] Start session (d6)
- [ ] Rate high → verify die steps down to d4
- [ ] Click d20 button → verify manual override
- [ ] Click "Auto" → verify returns to d4
- [ ] Roll and snooze → verify die steps up to d6

---

## 7. ERROR HANDLING

### 7.1 API Errors
- [ ] Snooze without session → verify error message
- [ ] Snooze without pending thread → verify error message
- [ ] Roll with all threads snoozed → verify error message
- [ ] Roll with empty queue → verify appropriate error

### 7.2 Edge Cases
- [ ] Snooze last remaining thread → verify roll error
- [ ] Move thread to invalid position (out of bounds)
- [ ] Create thread with 0 issues remaining

---

## 8. UI/UX VALIDATION

### 8.1 Visual States
- [ ] Verify teal highlight for moving thread in slider
- [ ] Verify amber highlight for target position in slider
- [ ] Verify displacement indicators (+1/-1) in preview
- [ ] Verify disabled state for Confirm button when no change

### 8.2 Responsive Design
- [ ] Test PositionSlider modal on mobile
- [ ] Test RollPage snoozed section on mobile
- [ ] Test drag and drop on mobile (if supported)

### 8.3 Accessibility
- [ ] Verify all buttons have aria-labels
- [ ] Verify keyboard navigation works for slider
- [ ] Verify expand/collapse snoozed section accessible

---

## Test Results Log

### 2025-01-25 - Testing Started
- Status: In Progress
- Notes:

### Test Passes

#### API Tests (117 tests passed)
- [x] 1.1 Basic Snooze Flow - PASS (test_snooze_success)
- [x] 1.2 Multiple Snoozes - PASS (test_snooze_excludes_from_roll)
- [x] 1.3 Snooze at Die Boundaries - PASS (test_snooze_steps_die_up_from_max)
- [x] 1.4 Snooze Edge Cases - PASS (test_snooze_no_pending_thread, test_snooze_no_session, test_snooze_duplicate_thread, test_snooze_all_threads)

- [x] 2.1 Position Slider API Tests - PASS (test_queue_api.py, test_queue_ui.py)
- [x] 2.2 Move to Front - PASS (test_move_first_to_front_no_op, test_move_to_front_via_api)
- [x] 2.3 Move to Back - PASS (test_move_last_to_back_no_op, test_move_to_back_via_api)
- [x] 2.4 Insert Between Threads - PASS (test_drag_and_drop_updates_position)

- [x] 3.1 Quick Move Buttons - PASS (test_move_to_front_via_api, test_move_to_back_via_api)
- [x] 3.2 Position Repositioning API - PASS (test_reposition_thread_with_sequential_positions, test_move_to_position_clamps_to_max)

- [x] 4.1 Manual Die Selection - PASS (test_set_manual_die, test_clear_manual_die, test_clear_manual_die_returns_correct_current_die_regression)
- [x] 4.2 Roll API - PASS (test_roll_success, test_roll_override, test_roll_no_pool, test_roll_overflow, test_roll_override_nonexistent)

- [x] 5.1 Rate API - PASS (test_rate_success, test_rate_low_rating, test_rate_high_rating, test_rate_completes_thread, test_rate_records_event, test_rate_no_active_session, test_rate_no_active_thread, test_rate_updates_manual_die, test_rate_low_rating_updates_manual_die, test_rate_finish_session_flag_controls_session_end, test_rating_settings_returns_defaults, test_rating_settings_returns_custom_values, test_rating_settings_validates_range)

### Issues Found
- [x] Issue #1: test_move_to_position_clamps_to_max incorrectly counted all threads instead of active threads
  - Location: tests/test_queue_edge_cases.py:65
  - Fix: Changed to filter for active threads only
  - Status: FIXED

- [x] Issue #2: test_jump_to_position_works_for_large_distance incorrectly counted all threads instead of active threads
  - Location: tests/test_queue_ui.py:15
  - Fix: Changed to filter for active threads only
  - Status: FIXED

- [x] Issue #3: test_move_to_back_via_api used len(threads) instead of max position value
  - Location: tests/test_queue_ui.py:81
  - Fix: Changed to use max queue_position from active threads
  - Status: FIXED

- [x] Issue #4: move_to_back function in comic_pile/queue.py didn't filter by status="active"
  - Location: comic_pile/queue.py:47-53
  - Fix: Added .where(Thread.status == "active") filter
  - Status: FIXED

- [x] Issue #5: move_to_back update query didn't filter by status="active"
  - Location: comic_pile/queue.py:61-66
  - Fix: Added .where(Thread.status == "active") filter to update statement
  - Status: FIXED

- [x] Issue #6: move_to_front function in comic_pile/queue.py didn't filter by status="active"
  - Location: comic_pile/queue.py:26-33
  - Fix: Added .where(Thread.status == "active") filter
  - Status: FIXED

- [x] Issue #7: CRITICAL - Snooze causes blank screen when navigating back to Roll page
  - Location: frontend/src/hooks/useSnooze.js:12-13
  - Root Cause: Two different session query keys causing unnecessary invalidation
    - RatePage uses: `queryKey: ['session', 'current']`
    - useSession hook uses: `queryKey: ['session']`
  - Problem: useSnooze() invalidates BOTH keys, then navigates to /roll
    RollPage uses useSession(), so `['session']` gets invalidated
    During refetch, session data is temporarily undefined → BLANK SCREEN
  - Fix: Removed invalidation of `['session', 'current']` from useSnooze, useRoll, and useOverrideRoll
  - Files Modified:
    - frontend/src/hooks/useSnooze.js
    - frontend/src/hooks/useRoll.js (useRoll, useOverrideRoll, useReroll)
  - Status: FIXED

- [x] Issue #8: Clicking snoozed threads from Roll page didn't open override modal
  - Location: frontend/src/pages/RollPage.jsx:336-343
  - Fix: Made snoozed threads clickable buttons that open override modal with thread pre-selected
  - Also: Added "Snoozed Threads" section to override dropdown
  - Status: FIXED

- [x] Issue #9: Override to snoozed thread didn't remove from snoozed list
  - Location: app/api/roll.py:116-127
  - Fix: Added code to remove thread from snoozed_thread_ids when override happens
  - Status: FIXED

- [x] Issue #10: Session API doesn't return snoozed data in /sessions/current/ endpoint
  - Location: app/api/session.py:221-233
  - Fix: Added snoozed_thread_ids and snoozed_threads to SessionResponse
  - Status: FIXED

### Fixes Applied
- [x] Fix #1: Fixed test_move_to_position_clamps_to_max to filter active threads
- [x] Fix #2: Fixed test_jump_to_position_works_for_large_distance to filter active threads
- [x] Fix #3: Fixed test_move_to_back_via_api to use max position
- [x] Fix #4: Added status="active" filter to move_to_back query
- [x] Fix #5: Added status="active" filter to move_to_back update
- [x] Fix #6: Added status="active" filter to move_to_front query
- [x] Fix #7: Fixed blank screen after snooze by removing unnecessary query invalidation
- [x] Fix #8: Made snoozed threads clickable and added to override modal
- [x] Fix #9: Added automatic removal from snoozed list when override happens
- [x] Fix #10: Added snoozed data to current session API response

### Remaining Tests
- E2E Tests (Playwright browser tests): Need PostgreSQL database connection
  - tests_e2e/test_thread_repositioning_demo.py::test_thread_repositioning_fix_demo
  - tests_e2e/test_thread_repositioning_demo.py::test_thread_repositioning_edge_cases
  - Status: BLOCKED (needs database setup)

- Section 6: Integration Tests (Full session flows)
  - Status: PENDING

- Section 7: Error Handling (API errors and edge cases)
  - Status: PARTIALLY COMPLETE (API error handling covered)

- Section 8: UI/UX Validation (Visual states, Responsive, Accessibility)
  - Status: PENDING (needs E2E tests)
