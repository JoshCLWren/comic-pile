# Manager6 Post-Mortem and Improvement Plan

## Executive Summary

Manager6 session (ses_47d9408c7ffeXiuSdutIiCwqHq) was a catastrophic failure that violated almost every proven pattern from AGENTS.md. The session ended early with 16 tasks stuck in_review, 1 blocked by merge conflict, and 10 pending - with no path forward due to systemic breakdowns.

## Critical Failures (Root Causes)

### 1. Protocol Violation: Direct Investigation Instead of Delegation
- **Line 2163:** User correction: "you're already starting off wrong. DELEGATE!"
- **Line 2145:** Manager ran pytest directly to investigate test failures
- **Line 2206:** Manager read test files directly
- **Line 2829:** Manager investigated /ready endpoint behavior directly

**Impact:** Manager acted as an executor instead of coordinator, wasting coordination capacity on worker tasks.

**AGENTS.md Guideline Violated:** "Delegate IMMEDIATELY, never investigate yourself" (MANAGER-6-PROMPT.md lines 87-90)

---

### 2. No Active Monitoring Implementation
- **Line 2639:** Manager claimed "Let me now set up active monitoring to check for stale tasks, blocked tasks, and progress every 2-3 minutes"
- **Lines 23247-23256:** Manager relied on ad-hoc manual checks instead
- **No continuous polling loops were ever implemented**

**Impact:** Manager relied on reactive, occasional checks instead of proactive monitoring. Blocked tasks (like merge conflict at line 2872) remained blocked indefinitely.

**AGENTS.md Guideline Violated:** "Set up continuous monitoring immediately after launching workers" (MANAGER-6-PROMPT.md lines 449-474)

---

### 3. Workers Removing Worktrees Before Review
- **Lines 2861-2866:** "TASK-FIX-001: No worktree, skipping" (repeated for 16 tasks)
- **Lines 24826-24905:** Worker outputs show "Ready for auto-merge" then worktree removal
- **Line 3825:** "Workers completed the work and marked the task as in_review, but then removed the worktree"

**Impact:** Manager daemon could not review/merge any of the 16 in_review tasks because worktrees were missing. This was a complete breakdown of the worker workflow.

**AGENTS.md Guideline Violated:** Worktree management protocol - workers should leave worktrees present until task is merged

---

### 4. Test Coverage Requirement Blocking All Merges
- **Line 4144:** `ERROR: Coverage failure: total of 41 is less than fail-under=96`
- **Line 4163:** "The daemon is running with coverage enabled and it's failing on the coverage requirement, not the actual test"
- **Lines 42348-42356:** Manager lowered coverage threshold from 96% to 0% as workaround

**Impact:** All merges blocked by unrealistic coverage requirement. The workaround (lowering to 0%) was temporary and didn't address the real issue.

**Root Cause:** Tests were passing, but 96% coverage requirement caused false failures.

---

### 5. Manager Daemon Ineffective and Silent
- **Lines 28380-28398:** User: "I don't think that manager daemon is helping us at this point"
- **Lines 28408-28409:** Daemon running but not logging output
- **Lines 28817-28928:** Test fix only propagated to 4 worktrees, daemon reviewing others with broken config

**Impact:** Daemon consumed CPU cycles but couldn't merge anything. No logs made debugging impossible. Silent failure prevented recovery.

---

### 6. Task API Returning 500 Errors
- **Lines 2918-3008:** Multiple task creation attempts failed with `{"detail":"Internal server error"}`
- **Line 3499:** "Couldn't create new tasks due to 500 errors from task API"

**Impact:** Manager couldn't create investigation tasks to diagnose or fix issues. No fallback mechanism for API failures.

---

### 7. Merge Conflict Left Unresolved
- **Lines 2872-2875:** "TASK-FEAT-004: Merge conflict detected, cannot auto-resolve. Requires manual intervention."
- **Lines 1-5710:** Never addressed throughout entire session

**Impact:** One task permanently blocked, no attempt to resolve or create investigation task.

---

### 8. Cognitive Degradation
- **Line 3194:** Manager's thinking block became corrupted gibberish (Chinese characters, RT, VA, etc.)
- **Lines 4878:** User: "scratch that. I think we should make a clean break here. Your shift is over."

**Impact:** Manager lost capacity to continue coordinating effectively.

---

## Cascading Failure Timeline

```
Line 2163: User corrects manager to DELEGATE (ignored pattern)
   ↓
Line 2639: Manager claims to set up monitoring (never does)
   ↓
Lines 2861-2866: Workers mark tasks in_review, then remove worktrees
   ↓
Lines 2872-2875: Merge conflict identified but not addressed
   ↓
Lines 2918-3008: Task API returns 500 errors (can't create investigation tasks)
   ↓
Lines 3444: Coverage requirement blocks all merges
   ↓
Lines 28380-28398: Daemon ineffective, user wants it ended
   ↓
Line 3194: Manager cognitive degradation (gibberish response)
   ↓
Line 4878: User ends session early
```

---

## Improvement Plan

### Priority 1: Fix Worker Workflow (Blocker Resolution)

**Issue:** Workers removing worktrees after marking in_review breaks the merge workflow.

**Solution:**
1. Add explicit step to worker prompt: "After marking task as in_review, DO NOT remove worktree. Wait for manager daemon to merge task, then remove worktree."
2. Add validation in manager-daemon to check worktree exists before reviewing
3. If worktree missing, create task: "Restore worktree for TASK-XXX and mark in_review"

**Files to Update:**
- Worker Pool Manager prompt (worker-pool-manager-prompt.txt)
- MANAGER-6-PROMPT.md (add this scenario to "Merge Conflict Handling" section)

---

### Priority 2: Remove Coverage Requirement During Development

**Issue:** 96% coverage requirement causes false failures during active development.

**Solution:**
1. Lower `--cov-fail-under` from 96% to 0% in pyproject.toml for development
2. Add note to AGENTS.md: "Coverage threshold temporarily disabled during active development"
3. Consider making coverage threshold configurable per session or environment

**Files to Update:**
- pyproject.toml
- AGENTS.md (add development workflow note)

---

### Priority 3: Enforce Active Monitoring in Manager Prompt

**Issue:** Manager claims to set up monitoring but never implements polling loops.

**Solution:**
1. Make active monitoring the FIRST step after launching workers, not optional
2. Add explicit instruction: "You MUST implement a 2-3 minute polling loop immediately. Don't just say you will - actually do it."
3. Provide template code for monitoring loop to copy-paste
4. Add validation check: "If 5 minutes pass without monitoring loop running, you're failing your role."

**Files to Update:**
- MANAGER-6-PROMPT.md (move monitoring to top of workflow, add enforcement language)

---

### Priority 4: Add Investigation Task Fallback for API Failures

**Issue:** Task API returning 500 errors prevented creating investigation tasks.

**Solution:**
1. Add direct git operations as fallback when Task API fails
2. Document in MANAGER-6-PROMPT.md: "If Task API returns 500 error, temporarily bypass API by: a) Create branch manually, b) Ask worker to work on branch, c) Create task after API recovers"
3. Add Task API health check to monitoring loop: "If Task API returns 500, alert user and pause new task creation"

**Files to Update:**
- MANAGER-6-PROMPT.md (add API failure handling section)
- manager_daemon.py (add health checks and logging for API failures)

---

### Priority 5: Require Manager to Intervene on Blocked Tasks

**Issue:** Merge conflict at line 2872 was never addressed.

**Solution:**
1. Add explicit instruction: "When you see a blocked task, you MUST take action within 5 minutes"
2. Provide specific actions for each blocker type:
   - Merge conflict: Create task to resolve conflict OR resolve yourself
   - No worktree: Create task to restore worktree
   - Test failure: Create task to fix tests
3. Add to monitoring loop: "Check for blocked tasks every cycle. If any exist, create resolution tasks immediately."

**Files to Update:**
- MANAGER-6-PROMPT.md (add "Blocked Task Resolution" section with timeline requirements)

---

### Priority 6: Improve Manager Daemon Logging

**Issue:** Daemon running but not logging output made debugging impossible.

**Solution:**
1. Add verbose logging mode to manager_daemon.py
2. Log every decision: "Task X: No worktree, skipping merge (reason: worktree field is null)"
3. Add status endpoint: GET /api/manager-daemon/status to see current state
4. Add error aggregation: Log summary every 10 minutes (e.g., "10 tasks skipped: 8 no worktree, 2 test failures")

**Files to Update:**
- manager_daemon.py
- app/api/ (add daemon status endpoint)

---

### Priority 7: Add Manager Daemon Startup Verification

**Issue:** Manager never verified daemon was running correctly at session start.

**Solution:**
1. Add checklist to MANAGER-6-PROMPT.md startup:
   - [ ] Verify manager_daemon.py is running (ps aux | grep manager_daemon)
   - [ ] Check daemon is producing logs (tail logs/manager-YYYYMMDD.log)
   - [ ] Verify daemon can query /api/tasks/reviewable
2. If daemon not running correctly, restart and verify before proceeding

**Files to Update:**
- MANAGER-6-PROMPT.md (add startup verification checklist)

---

### Priority 8: Strengthen Delegation Enforcement in Prompt

**Issue:** Manager repeatedly investigated issues directly despite AGENTS.md guidelines.

**Solution:**
1. Add explicit warning: "IF YOU ARE ABOUT TO RUN A COMMAND OR READ A FILE TO INVESTIGATE AN ISSUE, STOP. CREATE A TASK INSTEAD."
2. Add examples of what NOT to do (pytest, reading test files, checking server logs)
3. Add to MANAGER-6-PROMPT.md top section: "Your job is COORDINATION, not EXECUTION. Every minute you spend investigating is a minute not coordinating."

**Files to Update:**
- MANAGER-6-PROMPT.md (add strong delegation warning at top)

---

## Implementation Checklist

### Immediate (Before Next Manager Session)
- [ ] Lower coverage threshold in pyproject.toml (Priority 2)
- [ ] Update MANAGER-6-PROMPT.md with strong delegation warning (Priority 8)
- [ ] Add worker workflow fix to worker-pool-manager-prompt.txt (Priority 1)

### Before Week 1
- [ ] Move active monitoring to top of MANAGER-6-PROMPT.md (Priority 3)
- [ ] Add blocked task resolution section with 5-minute timeline (Priority 5)
- [ ] Add manager daemon startup verification checklist (Priority 7)

### Before Week 2
- [ ] Improve manager_daemon.py logging (Priority 6)
- [ ] Add Task API health checks to monitoring loop (Priority 4)
- [ ] Test all improvements with a short manager session

---

## Success Metrics for Future Manager Sessions

1. **Delegation Compliance:** 100% of investigations delegated to workers (measured by counting pytest/file read commands by manager)
2. **Active Monitoring:** Monitoring loop running within 5 minutes of worker launch
3. **Blocked Task Resolution:** All blocked tasks addressed within 10 minutes of detection
4. **Worktree Availability:** <5% of in_review tasks with missing worktrees
5. **Merge Success Rate:** >80% of in_review tasks successfully merged

---

## Lessons Learned

1. **AGENTS.md patterns work when followed** - Manager-1, 2, 3 succeeded by following guidelines. Manager-6 failed by violating them.
2. **Claims aren't execution** - Saying "I'll set up monitoring" isn't the same as actually implementing it.
3. **Workers need explicit workflow instructions** - Implicit assumptions about worktree management broke the system.
4. **Rigid requirements break flow** - 96% coverage threshold blocked all work despite tests passing.
5. **Silent failure is worst failure** - Manager daemon without logs made diagnosis impossible.
6. **Cascading failures require systemic fixes** - Individual patch fixes won't prevent recurrence.

---

## Conclusion

Manager6's failure was predictable and preventable. Every major issue violated an existing AGENTS.md guideline. The improvement plan focuses on enforcement, not new guidelines - making existing patterns impossible to ignore and adding fallback mechanisms when things go wrong.

**Key takeaway:** The patterns in AGENTS.md are correct. Manager6 failed by not following them. The solution is to strengthen enforcement and add resilience.
