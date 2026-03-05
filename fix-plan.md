# Fix Plan for PR #240

## Executive Summary
Fix 4 critical P0 issues across backend parser, frontend ID collision, and test infrastructure. No time estimates provided per request.

---

## P0 Issues

### 1. Range Expansion DoS Vulnerability
**File:** `app/utils/issue_parser.py:62`  
**Problem:** Large ranges like "1-99999999" expand before MAX_ISSUES check  
**Fix:** Add pre-expansion validation before line 62

### 2. Dashed Literals Bypass Length Limit  
**File:** `app/utils/issue_parser.py:72-76`  
**Problem:** Literal length check happens after dash processing  
**Fix:** Move length check to before dash handling

### 3. ID Collision in Issue Edges
**File:** `frontend/src/components/DependencyBuilder.tsx:136`  
**Problem:** Using math formula `-(id * 100000)` for edge IDs causes collisions  
**Fix:** Use unique string format: `issue-edge-${src}-${tgt}-${timestamp}`

### 4. Tests Create Issue Dependencies Without Issues
**File:** `frontend/src/test/flowchart.spec.ts`  
**Problem:** Tests call dependency API with issue IDs that don't exist  
**Fix:** Create issues via `/api/v1/threads/{id}/issues` endpoint before creating dependencies

### 5. Thread Deletion Returns 500 Error
**File:** Backend error handling (likely `app/api/thread.py`)  
**Problem:** Deleting thread with dependencies causes 500 instead of proper error  
**Fix:** Wrap deletion in try/catch, return 409 or 400 with any error message

---

## Implementation Details

### Issue #0 Display
- Display issue numbers as-is (#0, #1, #-1, #1.5, etc.)
- Preserve user-specified order in range strings
- Don't imply order from numeric boundaries

### Error Handling
- Fix the 500 error first
- Any non-500 response is acceptable
- Message content secondary to status code

### Test Fix Strategy
- Call `/api/v1/threads/{id}/issues` with `{issue_range: "1-20"}` before creating dependencies
- Use actual API to create issues, then create dependencies referencing those issue IDs

---

## Files to Modify
1. `app/utils/issue_parser.py` (2 fixes)
2. `frontend/src/components/DependencyBuilder.tsx` (1 fix)
3. `frontend/src/test/flowchart.spec.ts` (test setup fixes)
4. Backend thread deletion endpoint (fix 500 error)

---

## Verification
- Range "1-99999" should reject before expansion
- Issue edge IDs should be unique strings
- Tests should pass with proper issue creation
- Thread deletion with dependencies should not 500
