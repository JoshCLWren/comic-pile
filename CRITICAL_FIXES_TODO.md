# Issue #215 - Critical Fixes Todo List

## 🚨 CRITICAL (Must Fix Before Merge)

- [ ] **FIX-001: Double-Wrapped API Payload**
  - **Location:** `frontend/src/pages/QueuePage.jsx:237`
  - **Issue:** Passing `{ issue_range: createForm.issues }` but API already wraps it
  - **Source:** Council (Backend API Integration) + CodeRabbit
  - **Fix:** Change to `await issuesApi.create(result.id, createForm.issues)`
  - **Assigned:** Agent 1

- [ ] **FIX-002: Missing `/v1` Prefix in migrateThread**
  - **Location:** `frontend/src/services/api-issues.ts:71`
  - **Issue:** Uses `/threads/...` instead of `/api/v1/threads/...`
  - **Source:** Council (Senior Frontend, Backend API) + CodeRabbit
  - **Fix:** Change to `/v1/threads/${threadId}:migrateToIssues`
  - **Assigned:** Agent 2

- [ ] **FIX-003: Missing MAX_ISSUES Limit (DoS Vulnerability)**
  - **Location:** `app/utils/issue_parser.py`, `frontend/src/utils/issueParser.ts`
  - **Issue:** No limit on issue count allows resource exhaustion
  - **Source:** Council (Security Architecture)
  - **Fix:** Add MAX_ISSUES = 10000 constant
  - **Assigned:** Agent 3

- [ ] **FIX-004: "Skipped" Status Type Mismatch**
  - **Location:** `frontend/src/types/index.ts:90`
  - **Issue:** Frontend includes 'skipped' but backend doesn't support it
  - **Source:** Council (Senior Frontend Engineer)
  - **Fix:** Remove 'skipped' from union type
  - **Assigned:** Agent 4

- [ ] **FIX-005: Stale Closure in useEffect**
  - **Location:** `frontend/src/components/IssueList.tsx:13-32`
  - **Issue:** loadIssues dependency missing in useEffect
  - **Source:** CodeRabbit
  - **Fix:** Wrap loadIssues in useCallback with proper dependencies
  - **Assigned:** Agent 5

## ⚠️ MAJOR (Fix Before Production)

- [ ] **FIX-006: Silent Error Handling**
  - **Location:** `frontend/src/components/IssueList.tsx:27-30, 49-51`
  - **Issue:** Errors logged but never shown to users
  - **Source:** Council (Frontend, Backend, UI/UX)
  - **Fix:** Add error toast/notification system

- [ ] **FIX-007: Race Condition in toggleIssueStatus**
  - **Location:** `frontend/src/components/IssueList.tsx:34-52`
  - **Issue:** No loading state allows rapid double-clicks
  - **Source:** Council (Frontend, Backend)
  - **Fix:** Add isLoading state to disable interaction

- [ ] **FIX-008: Missing Accessibility**
  - **Location:** `frontend/src/components/IssueList.tsx`
  - **Issue:** No ARIA labels, keyboard nav, screen reader support
  - **Source:** Council (UI/UX Designer)
  - **Fix:** Add proper ARIA attributes and keyboard handlers

- [ ] **FIX-009: Thread Creation UI Confusion**
  - **Location:** `frontend/src/pages/QueuePage.jsx`
  - **Issue:** Two issue-related fields confuse users
  - **Source:** Council (UI/UX Designer)
  - **Fix:** Clarify UI or combine into single field

- [ ] **FIX-010: Misleading Preview Text**
  - **Location:** `frontend/src/pages/QueuePage.jsx:656-660`
  - **Issue:** Shows "#1-5" for non-contiguous ranges like "1,3,5-7"
  - **Source:** CodeRabbit
  - **Fix:** Show actual issue numbers or simplified text

## 🟡 MINOR (Nice to Have)

- [ ] **FIX-011: Remove Unused Variable**
  - **Location:** `frontend/src/test/helpers.ts:96`
  - **Issue:** timestamp variable declared but never used
  - **Source:** CodeRabbit
  - **Fix:** Remove unused variable

- [ ] **FIX-012: Add Memoization**
  - **Location:** `frontend/src/components/IssueList.tsx`
  - **Issue:** Derived values recalculated on every render
  - **Source:** Council (Senior Frontend Engineer)
  - **Fix:** Use useMemo for readCount, progressPercent

- [ ] **FIX-013: Extract Magic Strings**
  - **Location:** `frontend/src/components/IssueList.tsx`
  - **Issue:** Status strings hardcoded
  - **Source:** Council (Senior Frontend Engineer)
  - **Fix:** Extract to constants

## 📊 Progress Tracking

### Phase 1: Critical Fixes (Required for Merge)
- Total: 5 items
- Completed: 5 ✅
- In Progress: 0
- Blocked: 0

**Status:** Phase 1 COMPLETE! All critical bugs fixed.

**Commits:**
- `b7d53d8` - FIX-005: Wrap loadIssues in useCallback
- `bfeb843` - FIX-004: Remove unsupported 'skipped' status
- `6b83107` - FIX-003: Add MAX_ISSUES limit
- (previous commit) - FIX-002: Add /v1 prefix to migrateThread
- (already fixed) - FIX-001: Correct API payload

### Phase 2: Major Fixes (Required for Production)
- Total: 5 items
- Completed: 0
- In Progress: 0
- Blocked: 0

### Phase 3: Minor Improvements
- Total: 3 items
- Completed: 0
- In Progress: 0
- Blocked: 0

## 🎯 Acceptance Criteria

**Phase 1 Complete When:**
- [ ] All critical fixes committed
- [ ] All tests passing (pytest, E2E)
- [ ] Frontend builds without errors
- [ ] Manual testing confirms thread creation with issues works

**Phase 2 Complete When:**
- [ ] All major fixes committed
- [ ] Accessibility audit passes
- [ ] Error handling tested
- [ ] Race conditions prevented

**Phase 3 Complete When:**
- [ ] All minor improvements applied
- [ ] Code is production-ready

## 📝 Notes

- CodeRabbit and Council feedback aligned on all critical issues
- Some fixes are interdependent (e.g., error handling depends on notification system)
- Test fixes should wait until functionality is stable
- Accessibility improvements require careful testing

## 🔗 References

- Council Feedback: See separate document
- CodeRabbit Review: https://github.com/JoshCLWren/comic-pile/pull/229
- Original Issue: #215
- Related PRs: #227 (backend), #228 (API), #213 (migration)
