# Comic Pile Critical Audit - Fix Plan

## Date: 2026-01-08

## Executive Summary

The app is fundamentally broken due to a **complete misunderstanding of the PRD** for the roll page UI. Tests pass because they only verify API responses, not UI behavior.

**Root Cause:** The roll page shows N dice (e.g., 6d6) when it should show a single [ ROLL d6 ] button.

---

## Critical Issues Found

### 1. ✗ CRITICAL: Multi-dice UI instead of single roll button
**Status:** BROKEN  
**Impact:** App is unusable  
**Task:** BUG-ROLL-001 (Priority: CRITICAL)

**Current Behavior:**
- Shows N dice of same denomination (e.g., 6 dice if current_die=6)
- Each dice displays over a thread preview (book)
- User sees "6d6 spinning"
- "Tap Anywhere to Roll" text with no clear button

**Intended Behavior:**
- Single indicator showing current die type (d6)
- Explicit [ ROLL d6 ] button
- Roll result shows: "Result: 4 - Picked: Hellboy (Omnibus)"

**Files to Fix:**
- app/templates/roll.html (lines 289-340, 640-644)
- app/api/roll.py (lines 107-150)

---

### 2. ✗ CRITICAL: No regression tests for UI behavior
**Status:** MISSING  
**Impact:** Bugs not caught by tests  
**Task:** REGRESSION-001 (Priority: HIGH)

**Problem:** Tests passed even though app was unusable because they only verified API responses.

**Tests Needed:**
- test_roll_ui.py - Verify roll page shows single button, not multi-dice
- test_roll_workflow_e2e.py - Full Playwright E2E test of roll workflow

---

### 3. ✓ Working: Session detection (6-hour gap)
**Status:** WORKING  
**Impact:** None  
**Task:** REGRESSION-003 (Priority: MEDIUM)

**Finding:** Session detection is working correctly per PRD:
- Session is active if started < 6 hours ago AND ended_at is None
- Session is inactive if started >= 6 hours ago OR ended_at is not None

The "Session Inactive" message is correct behavior - user needs to roll first.

---

### 4. ✓ Working: Roll API
**Status:** WORKING  
**Impact:** None

**Finding:** Roll API endpoints work correctly:
- POST /roll/ returns correct JSON with thread_id, die_size, result
- POST /roll/html returns HTML (but with multi-dice, which is wrong)

The backend logic is correct, only the frontend visualization is wrong.

---

## Why Tests Passed Despite Broken App

### Test Coverage Gap

**What Tests Verify:**
✅ API endpoint responses (JSON)  
✅ Database state changes  
✅ Session logic (time calculations)  
✅ Roll API returns correct die_size

**What Tests DON'T Verify:**
❌ UI rendering (how many dice shown)  
❌ UI interactions (roll button click)  
❌ User workflows (end-to-end experience)  

### Example: test_roll_success
```python
async def test_roll_success(client, sample_data):
    response = await client.post("/roll/")
    assert response.status_code == 200
    data = response.json()
    assert "die_size" in data  # API returns 6 (correct)
    assert "thread_id" in data  # API returns thread ID (correct)
```

This test passes because:
- API returns `die_size: 6` (correct)
- Thread ID is valid (correct)

But it doesn't test:
- Does the UI show 6 dice or 1 button? ❌
- Are the dice spinning? ❌
- Is there a roll button? ❌

---

## Task Execution Plan

### Critical Path (Must Fix First)

1. **BUG-ROLL-001** (CRITICAL, ~3 hours)
   - Fix roll.html to show single [ ROLL d6 ] button
   - Fix /roll/html API to return simple HTML
   - Remove multi-dice visualization
   - Add explicit roll button with click handler

2. **REGRESSION-001** (HIGH, ~2 hours, depends on BUG-ROLL-001)
   - Create test_roll_ui.py
   - Verify roll page shows single button
   - Verify /roll/html returns single result, not multi-dice
   - Prevent future multi-dice regressions

3. **REGRESSION-002** (HIGH, ~3 hours, depends on REGRESSION-001)
   - Create Playwright E2E test for complete workflow
   - Test roll → rate → redirect flow
   - Verify no multi-dice visualization
   - Take screenshots on failure

### Secondary Improvements

4. **UX-001** (MEDIUM, ~1 hour)
   - Improve rate page when session inactive
   - Show "Roll first to rate" with link to /roll
   - Better UX than disabled button

5. **REGRESSION-003** (MEDIUM, ~1.5 hours)
   - Add regression test for 6-hour session gap
   - Verify active/inactive session detection
   - Prevent future regressions

---

## Ralph Orchestrator Execution

The Ralph orchestrator should execute these tasks in priority order:

```bash
export RALPH_MODE=true
python scripts/ralph_orchestrator.py
```

**Task Order:**
1. BUG-ROLL-001 (CRITICAL - fix the broken UI)
2. REGRESSION-001 (HIGH - add UI tests)
3. REGRESSION-002 (HIGH - add E2E tests)
4. UX-001 (MEDIUM - improve UX)
5. REGRESSION-003 (MEDIUM - session regression tests)

---

## Files Modified

### Cleanup
- task.json - Reduced from 128 to 32 active tasks (removed 96 completed)

### New Tasks Added
- BUG-ROLL-001: Fix roll page UI (CRITICAL)
- REGRESSION-001: Add roll UI regression test (HIGH)
- REGRESSION-002: Add Playwright E2E test (HIGH)
- UX-001: Improve rate page UX (MEDIUM)
- REGRESSION-003: Add session gap regression test (MEDIUM)

---

## Test Coverage Requirements

**Current:** API tests only (unit/integration)  
**Target:** API + UI + E2E tests  

**Coverage Goals:**
- API tests: 96% (current target) ✓
- UI tests: 80% (need to add)
- E2E tests: 70% (need to add)
- Overall: 90%+ (current target) ✓

---

## Summary

**Broken:** 1 critical bug (multi-dice UI)  
**Working:** Session detection, Roll API  
**Missing:** 3 regression tests  
**Total Tasks:** 5 new tasks created  

**Next Steps:**
1. Run Ralph orchestrator to fix BUG-ROLL-001
2. Add regression tests to prevent future issues
3. Run make pytest to ensure all tests pass
4. Manual browser testing to verify UX

