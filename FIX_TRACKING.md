# CodeRabbit Fix Tracking

**PR**: #164 - "Fix ladder"
**Total Issues Requiring Fixes**: 39
**Last Updated**: 2026-01-31 20:30 UTC

## Fix Workflow States
- `TODO` - Not started
- `IN_PROGRESS` - Sub-agent working on fix
- `REVIEW` - Implemented, needs peer review
- `DONE` - Fixed and verified (linter + tests pass)
- `FAILED` - Fix failed, needs retry or manual intervention

## Progress Summary
| State | Count |
|-------|-------|
| TODO | 28 |
| IN_PROGRESS | 0 |
| REVIEW | 0 |
| DONE | 11 |
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

### [CRIT-004] `app/utils/retry.py:3-51` - Missing await on async operation in retry loop
- **Comment ID**: review-3733435337 (2026-01-31T20:17:13Z)
- **State**: `DONE` ✅
- **Assigned To**: ses_3e95665c7ffeo6hTJxjy0ACjJy
- **Reviewer**: ses_3e9550a47ffe1TMZBW4alkcZwW
- **Error**: Previous fix for CRIT-001 had `return operation()` which returns coroutine, bypassing retry logic
- **Fix Required**: Changed to `return await operation()` and updated type to `Callable[[], Awaitable[T]]`
- **Attempts**: 1
- **Last Error**: None - Previous peer review was lazy and missed this bug
- **Verification**: ✅ Passed all checks (ruff, ty, pytest)
- **Completed**: 2026-02-01
- **Note**: This was a bug in CRIT-001 fix that lazy peer review missed

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
- **State**: `DONE` ✅
- **Assigned To**: ses_3e93afd74ffewtSlaTnjg81kKX
- **Reviewer**: ses_3e937ed0bffeadM5n6XkMovdGd
- **Error**: Mutations don't refresh thread list, UI shows stale data
- **Fix Required**: Added `refetch()` calls after all successful mutations
- **Attempts**: 1
- **Last Error**: None
- **Verification**: ✅ Passed all checks (npm test, lint)
- **Completed**: 2026-02-01

### [HIGH-004] CI workflow hard-coded secrets
- **Comment ID**: 2733305763
- **File**: `.github/workflows/ci-sharded.yml:29-39`
- **State**: `DONE` ✅
- **Assigned To**: ses_3e93afd72ffeDJ1tDG5eo8cZyf
- **Reviewer**: ses_3e937ed09ffeuCz2rHB9l8FeJp
- **Error**: Hard-coded SECRET_KEY, DATABASE_URL, POSTGRES_PASSWORD
- **Fix Required**: Replaced with ${{ secrets.NAME }} references
- **Attempts**: 1
- **Last Error**: None
- **Verification**: ✅ All secrets use GitHub Secrets format
- **Completed**: 2026-02-01
- **Security**: Secrets must be configured in GitHub repo settings

### [HIGH-005] `app/api/admin.py:215-263` - Session deletion ignores `selected_thread_id`
- **Comment ID**: review-3733435337 (2026-01-31T20:17:13Z)
- **State**: `DONE` ✅
- **Assigned To**: ses_3e9403d8effe06F7anZarGhNzD
- **Reviewer**: ses_3e93ef4afffewJKy7TmNUc0pOF
- **Error**: Deletion logic only checks `event.thread_id`, ignoring `event.selected_thread_id` (used by roll events)
- **Fix Required**: Added `is_test_event()` helper to check both fields safely
- **Attempts**: 1
- **Last Error**: None
- **Verification**: ✅ Passed all checks (ruff, ty, pytest)
- **Completed**: 2026-02-01
- **Test Added**: `test_delete_test_data_with_selected_thread_id` validates fix

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
- **Reviewer**: None
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

### [MED-006] `app/api/session.py:427-585` - Use UTC-aware timestamps
- **Comment ID**: review-3733435337 (2026-01-31T20:17:13Z)
- **State**: `DONE` ✅
- **Assigned To**: ses_3e93afd71ffe7JPhOFBOzJcIpc
- **Reviewer**: ses_3e937ed08ffeszMjGrq2VM6kGO
- **Error**: `datetime.now()` produces naive timestamp; models store timezone-aware datetimes
- **Fix Required**: Changed to `datetime.now(UTC)` and added UTC import
- **Attempts**: 1
- **Last Error**: None
- **Verification**: ✅ Passed all checks (ruff, ty, pytest)
- **Completed**: 2026-02-01
- **Fix Required**: Change `datetime.now()` to `datetime.now(UTC)` and add `from datetime import UTC`
- **Attempts**: 0
- **Verification**: pytest, manual test

### [MED-007] `comic_pile/session.py:126-129` - Silent exception swallowing in advisory lock
- **Comment ID**: review-3733435337 (2026-01-31T20:17:13Z)
- **State**: `DONE` ✅
- **Assigned To**: ses_3e93afd70ffeHbCkUQUk5KUY8p
- **Reviewer**: ses_3e937ed08ffdg56WJ5wC57rD0z
- **Error**: Bare `except Exception: pass` silently swallows ALL exceptions
- **Fix Required**: Added detailed warning log with context
- **Attempts**: 1
- **Last Error**: None
- **Verification**: ✅ Passed all checks (ruff, ty, pytest)
- **Completed**: 2026-02-01
- **Design**: Preserves graceful degradation (asyncio.Lock still protects)

### [MED-008] `scripts/dev-all.sh:1-39` - Two process management issues
- **Comment ID**: review-3733435337 (2026-01-31T20:17:13Z)
- **State**: `TODO`
- **Assigned To**: None
- **Reviewer**: None
- **Error**: (1) pkill -f kills unrelated Vite/Uvicorn processes, (2) hardcoded ports (8000, 5173)
- **Fix Required**: (1) Save PIDs to variables and kill specific PIDs, (2) Make ports configurable via BACKEND_PORT/FRONTEND_PORT env vars
- **Attempts**: 0
- **Verification**: Run dev-all.sh and verify only correct processes are killed

### [MED-009] `scripts/seed_dev_db.py:15-16` - Missing return type annotation
- **Comment ID**: review-3733435337 (2026-01-31T20:17:13Z)
- **State**: `TODO`
- **Assigned To**: None
- **Reviewer**: None
- **Error**: `async def seed_database` lacks return type annotation
- **Fix Required**: Change to `async def seed_database() -> None:`
- **Attempts**: 0
- **Verification**: ty check

### [MED-010] `SUB_AGENT_PROTOCOL.md:25-36` - Two formatting issues
- **Comment ID**: review-3733435337 (2026-01-31T20:17:13Z)
- **State**: `TODO`
- **Assigned To**: None
- **Reviewer**: None
- **Error**: (1) Fenced code block lacks language specifier, (2) "## Current Assignments" table is malformed
- **Fix Required**: (1) Change ``` to ```text, (2) Add blank line after heading, fix table pipe alignment
- **Attempts**: 0
- **Verification**: markdownlint, visual check

---

## 🟢 LOW PRIORITY

### [LOW-001] Markdown formatting issues
- **Comments**: Multiple
- **State**: `TODO`
- **Fix Required**: Fix list indentation, markdownlint violations
- **Verification**: markdownlint

### [LOW-002] `CODERABBIT_AUDIT.md:440` - Typo "typpos"
- **Comment ID**: review-3733435337 (2026-01-31T20:17:13Z)
- **State**: `TODO`
- **Assigned To**: None
- **Reviewer**: None
- **Error**: Text contains typo "typpos" should be "typos"
- **Fix Required**: Change "typpos" to "typos" in line 440
- **Attempts**: 0
- **Verification**: Manual review

### [LOW-003] `FIX_TRACKING.md:149` - Stray Markdown bold marker
- **Comment ID**: review-3733435337 (2026-01-31T20:17:13Z)
- **State**: `TODO`
- **Assigned To**: None
- **Reviewer**: None
- **Error**: Line 149 has "**Reviewer**: None**" with trailing bold marker
- **Fix Required**: Remove trailing "**" so line reads "**Reviewer**: None"
- **Attempts**: 0
- **Verification**: Manual review, markdownlint

### [LOW-004] `frontend/src/pages/RatePage.jsx:114-124` - Mutation chaining pattern
- **Comment ID**: review-3733435337 (2026-01-31T20:17:13Z)
- **State**: `TODO`
- **Assigned To**: None
- **Reviewer**: None
- **Error**: Uses `.then()/.catch()` chaining on `mutate()` which is fragile if hook changes
- **Fix Required**: Consider using try/catch with await for consistency
- **Attempts**: 0
- **Verification**: npm test

---

## Change Log

### 2026-01-31 20:30 UTC
- 🆕 **NEW CodeRabbit review received** (review-3733435337)
- **10 NEW issues identified**:
  - CRIT-004: Missing await on async operation in retry loop (app/utils/retry.py)
  - HIGH-005: Session deletion ignores selected_thread_id (app/api/admin.py)
  - MED-006: Use UTC-aware timestamps (app/api/session.py)
  - MED-007: Silent exception swallowing in advisory lock (comic_pile/session.py)
  - MED-008: Process management issues in dev-all.sh (2 issues)
  - MED-009: Missing return type annotation (scripts/seed_dev_db.py)
  - MED-010: Two formatting issues (SUB_AGENT_PROTOCOL.md)
  - LOW-002: Typo "typpos" (CODERABBIT_AUDIT.md)
  - LOW-003: Stray bold marker (FIX_TRACKING.md)
  - LOW-004: Mutation chaining pattern (frontend/src/pages/RatePage.jsx)
- **Total issues updated**: 29 → 39
- **Progress**: 5 of 39 completed (12.8%)

### 2026-01-31 14:30 UTC
- ✅ CRIT-001 DONE: Fixed blocking time.sleep() in retry.py (commit: 4cff4b0)
- ✅ CRIT-002 DONE: Fixed all BLE001 violations in main.py (commit: 4cff4b0)
- ✅ CRIT-003 DONE: Fixed mutateAsync() bug in RatePage.jsx (commit: 4cff4b0)
- ✅ HIGH-002 DONE: Fixed redundant loop in admin.py (commit: 1ac4d4c)
- Pushed all fixes to origin/fix-ladder
- **4 of 29 issues completed (13.8%)**

### 2026-01-31
- Initial tracking file created with 29 issues requiring fixes
- Categorized by priority: 3 critical, 4 high, 5 medium, 1 low
- Ready to dispatch sub-agents for fixes
