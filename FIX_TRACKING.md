# CodeRabbit Fix Tracking

**PR**: #164 - "Fix ladder"
**Total Issues Requiring Fixes**: 29
**Last Updated**: 2026-01-31

## Fix Workflow States
- `TODO` - Not started
- `IN_PROGRESS` - Sub-agent working on fix
- `REVIEW` - Implemented, needs peer review
- `DONE` - Fixed and verified (linter + tests pass)
- `FAILED` - Fix failed, needs retry or manual intervention

## Progress Summary
| State | Count |
|-------|-------|
| TODO | 25 |
| IN_PROGRESS | 0 |
| REVIEW | 0 |
| DONE | 4 |
| FAILED | 0 |

---

## 🔴 CRITICAL PRIORITY

### [CRIT-001] `app/utils/retry.py:51` - Blocking time.sleep() in async function
- **Comment ID**: 2733288289
- **State**: `DONE` ✅
- **Assigned To**: ses_3ea7cf3c1ffeWsUgKO5htpFNUu
- **Reviewer**: ses_3ea7bd99fffeyyeT2lo6sUMV7h
- **Error**: Blocking `time.sleep()` blocks event loop in async function
- **Fix Required**: Replace with `asyncio.sleep()`
- **Attempts**: 1
- **Last Error**: None
- **Verification**: ✅ Passed all checks (ruff, ty, pytest)
- **Completed**: 2026-01-31

### [CRIT-002] `app/main.py:378, 440` - BLE001 violations (broad exception handling)
- **Comment ID**: 2733311966
- **State**: `DONE` ✅
- **Assigned To**: ses_3ea7b4e2dffecCETLO0Ab70xM8 (attempt 1), ses_3ea766718ffe1HhkzgLsXw2qYw (attempt 2)
- **Reviewer**: ses_3ea779290ffe2wCyCYwgyz4ad7 (review 1 - REJECTED), ses_3ea747bc5ffel4bfPXiR1LsmRj (review 2 - APPROVED)
- **Error**: `except Exception` too broad at lines 87, 365, 381, 426, 445, 463-467
- **Fix Required**: Catch specific exceptions
- **Attempts**: 2
- **Last Error**: None - Fixed on retry
- **Verification**: ✅ Passed all checks (ruff, ty, pytest)
- **Completed**: 2026-01-31

### [CRIT-003] `frontend/src/pages/RatePage.jsx:155` - Calls non-existent mutateAsync()
- **Comment ID**: 2733305530
- **State**: `DONE` ✅
- **Assigned To**: ses_3ea735805ffeZKMgYqq4myQOoX
- **Reviewer**: ses_3ea71a0c3ffetRPNFdRa3P57ig
- **Error**: Hook exports `mutate` but code called `mutateAsync()`
- **Fix Required**: Change to `mutate()`
- **Attempts**: 1
- **Last Error**: None
- **Verification**: ✅ Passed all checks (npm test, lint)
- **Completed**: 2026-01-31

---

## 🟠 HIGH PRIORITY

### [HIGH-001] React Query architecture mismatch (3 comments)
- **Comment IDs**: 2733288260, 2733288283, 2733288291
- **State**: `TODO`
- **Files**: `frontend/src/main.jsx`, `frontend/src/hooks/useSession.js`, `frontend/src/hooks/useThread.js`
- **Issue**: React Query removed but AGENTS.md still requires it
- **Decision Required**: Remove from AGENTS.md OR restore React Query
- **Assigned To**: None
- **Reviewer**: None
- **Attempts**: 0
- **Verification**: Check AGENTS.md, verify frontend builds

### [HIGH-002] `app/api/admin.py:253` - Redundant loop with unused variable
- **Comment ID**: 2733288314
- **State**: `DONE` ✅
- **Assigned To**: ses_3ea705c6bffenpC0LPdfh5nMTi
- **Reviewer**: ses_3ea69a3a9ffej2PsYLaBLoW3i7
- **Error**: Loop queries same sessions multiple times
- **Fix Required**: Remove redundant outer loop
- **Attempts**: 1
- **Last Error**: None
- **Verification**: ✅ Passed all checks (ruff, ty, pytest)
- **Completed**: 2026-01-31
- **Performance Improvement**: O(T×S×E) → O(S×E) where T=test threads

### [HIGH-003] `frontend/src/pages/QueuePage.jsx` - Stale UI after mutations
- **Comment ID**: 2733305530
- **State**: `TODO`
- **Assigned To**: None
- **Reviewer**: None
- **Error**: create/edit/reactivate mutations don't refresh thread list
- **Fix Required**: Add invalidation/refetch after mutations
- **Attempts**: 0
- **Verification**: npm test, manual UI test

### [HIGH-004] CI workflow hard-coded secrets
- **Comment ID**: 2733305763
- **File**: `.github/workflows/ci-sharded.yml:29-39`
- **State**: `TODO`
- **Assigned To**: None
- **Reviewer**: None
- **Error**: SECRET_KEY, DATABASE_URL, POSTGRES_PASSWORD exposed
- **Fix Required**: Use GitHub Secrets
- **Attempts**: 0
- **Verification**: CI workflow runs without hardcoded secrets

---

## 🟡 MEDIUM PRIORITY

### [MED-001] Type annotations missing in test files
- **Comments**: 21-30
- **Files**: Multiple test files
- **State**: `TODO`
- **Assigned To**: None
- **Reviewer**: None
- **Fix Required**: Add type hints to test functions
- **Attempts**: 0
- **Verification**: ty check

### [MED-002] Docstrings missing Args/Returns sections
- **Comments**: Multiple
- **State**: `TODO`
- **Assigned To**: None
- **Reviewer**: None
- **Fix Required**: Add Google-style docstrings
- **Attempts**: 0
- **Verification**: ruff check, ty check

### [MED-003] Test quality issues (17 issues)
- **Comment ID**: 2733213241
- **State**: `TODO`
- **Assigned To**: None
- **Reviewer**: None
- **Fix Required**: Fix typos, add missing fields, improve fixtures
- **Attempts**: 0
- **Verification**: pytest, coverage checks

### [MED-004] Ruff B008 violations (Depends in defaults)
- **Comments**: Multiple
- **File**: `app/api/queue.py`
- **State**: `TODO`
- **Assigned To**: None
- **Reviewer**: None**
- **Fix Required**: Move Depends() to function body
- **Attempts**: 0
- **Verification**: ruff check

### [MED-005] Ruff ARG001 violations (unused fixtures)
- **Comments**: Multiple
- **Files**: Multiple test files
- **State**: `TODO`
- **Assigned To**: None
- **Reviewer**: None
- **Fix Required**: Remove unused fixtures or use them
- **Attempts**: 0
- **Verification**: ruff check, pytest

---

## 🟢 LOW PRIORITY

### [LOW-001] Markdown formatting issues
- **Comments**: Multiple
- **State**: `TODO`
- **Fix Required**: Fix list indentation, markdownlint violations
- **Verification**: markdownlint

---

## Change Log

### 2026-01-31
- Initial tracking file created with 29 issues requiring fixes
- Categorized by priority: 3 critical, 4 high, 5 medium, 1 low
- Ready to dispatch sub-agents for fixes
