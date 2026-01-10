# Executive Summary: Remaining Tasks by Phase

## Quick Stats
- **Total Remaining:** 19 tasks
- **Blocked:** 1 (needs immediate attention)
- **In Progress:** 3 (2 agents actively working)
- **In Review:** 6 (ready to merge, pending verification)
- **Pending:** 9 (ready to start)

---

## PHASE 1: Unblock & Complete Critical Workflow (1-2 workers)

### Immediate Action Required
**TASK-API-003** (BLOCKED, MEDIUM, Bob)
- Title: Add DELETE endpoint to Task API
- Status: Merge conflict during review
- Worktree: /home/josh/code/comic-pile-delete-endpoint
- Action: Resolve merge conflict, merge to main
- Blocker for: None, but needs cleanup

### In Progress - Keep Working
**TASK-COV-001** (IN_PROGRESS, HIGH, Helen)
- Title: Add test coverage for HTMX frontend
- Worktree: /home/josh/code/comic-pile (main repo)
- No dependencies
- Action: Continue work, mark in_review when done

**TASK-FEAT-002** (IN_PROGRESS, MEDIUM, Kevin)
- Title: Add Undo/History Functionality
- Worktree: comic-pile-task-204
- No dependencies
- Action: Continue work, mark in_review when done

**TASK-WORKFLOW-001** (IN_PROGRESS, HIGH, opencode)
- Title: Fix critical Task API workflow issues
- Worktree: comic-pile-TASK-WORKFLOW-001
- Changes pushed: commit 7fa3152
- Action: Complete remaining work, mark in_review
- Note: This fixes the worktree=null blocking issue

---

## PHASE 2: Merge & Validate In-Review Tasks (2-3 workers)

### Ready for Review - High Priority
**TASK-API-004** (IN_REVIEW, HIGH, unassigned, worktree:null)
- Title: Add PATCH endpoint and improve error responses
- No dependencies
- Action: Julia completed work. Mark done if tests pass.

**TASK-LINT-001** (IN_REVIEW, HIGH, unassigned, worktree:null)
- Title: Add linting for JavaScript and HTML
- No dependencies
- Action: Ivan completed work. Mark done if tests pass.

### Ready for Review - Critical Priority
**TASK-CRITICAL-001** (IN_REVIEW, CRITICAL, Charlie, worktree:comic-pile-phase)
- Title: Fix worktree null bug in /unclaim endpoint
- No dependencies
- Action: Charlie completed work. Merge to main.

**TASK-CRITICAL-006** (IN_REVIEW, CRITICAL, Heidi, worktree:null)
- Title: Add buffer session convergence criteria
- No dependencies
- Action: Heidi completed work. Mark done if tests pass.

### Ready for Review - Medium Priority
**TASK-TEST-001** (IN_REVIEW, HIGH, unassigned, worktree:null)
- Title: Test dockerized application locally
- Dependencies: TASK-DOCKER-002, TASK-DB-004, TASK-DB-005
- Note: All dependencies are now done
- Action: Verify work, mark done

**TASK-UNBLOCK-001** (IN_REVIEW, HIGH, unassigned, worktree:comic-pile-unblock-001)
- Title: Unblock 11 stuck in_review tasks
- Note: Already accomplished (11 tasks now done)
- Action: Mark as done

---

## PHASE 3: Testing & Deployment (2 workers, sequential)

### Phase 3A: Docker Testing
**TASK-TEST-001** (IN_REVIEW → DONE) - See Phase 2
- Once marked done, enables:
  - TASK-DEPLOY-001 (MEDIUM) - Docker compose prod
  - TASK-ROLLBACK-001 (MEDIUM) - Rollback docs
  - TASK-TEST-002 (MEDIUM) - PostgreSQL backup scripts

### Phase 3B: Production Deployment
**TASK-DEPLOY-001** (PENDING, MEDIUM)
- Title: Create docker-compose.prod.yml for production
- Dependency: TASK-TEST-001 (now in_review)
- Action: Create docker-compose.prod.yml, mark in_review

**TASK-SECURITY-001** (PENDING, HIGH)
- Title: Perform security audit of Docker setup
- Dependency: TASK-DEPLOY-001
- Action: After TASK-DEPLOY-001 done, audit Docker config

### Phase 3C: Infrastructure Documentation
**TASK-DEPLOY-002** (PENDING, LOW)
- Title: Update Makefile with Docker commands
- Dependency: TASK-TEST-001 (now in_review)
- Action: Add docker commands to Makefile, mark in_review

**TASK-DEPLOY-003** (PENDING, LOW)
- Title: Create production deployment documentation
- Dependencies: TASK-DEPLOY-001, TASK-DEPLOY-002
- Action: Write deployment docs, mark in_review

**TASK-ROLLBACK-001** (PENDING, MEDIUM)
- Title: Document and test rollback procedures
- Dependency: TASK-TEST-001 (now in_review)
- Action: Document rollback process, test it, mark in_review

**TASK-TEST-002** (PENDING, MEDIUM)
- Title: Create PostgreSQL backup and restore scripts
- Dependency: TASK-TEST-001 (now in_review)
- Action: Write backup/restore scripts, test, mark in_review

---

## PHASE 4: Low Priority & Cleanup (1 worker, opportunistic)

**TASK-CLEANUP-001** (PENDING, LOW)
- Title: Clean up completed task worktrees
- No dependencies
- Action: Remove stale worktrees (heidi, ivan, maria, grace, patty)

**UX-204** (PENDING, MEDIUM)
- Title: Clarify relationship between dice roll and comic number
- No dependencies
- Action: Add explanatory UI text or tooltips, mark in_review

**TEST-PLACEHOLDER** (PENDING, LOW)
- Title: Test Placeholder
- No dependencies
- Action: Mark done (no actual work needed)

---

## Concurrency Summary

### Maximum Concurrent Workers by Phase

| Phase | Workers | Tasks | Notes |
|--------|----------|---------|--------|
| Phase 1 | 3 | TASK-API-003 (resolve), TASK-COV-001, TASK-FEAT-002, TASK-WORKFLOW-001 | Helen, Kevin, opencode working. Bob on TASK-API-003 resolution |
| Phase 2 | 3 | TASK-API-004, TASK-LINT-001, TASK-CRITICAL-001, TASK-CRITICAL-006, TASK-TEST-001, TASK-UNBLOCK-001 | Can work on 3 in parallel, unassigned workers pick up tasks |
| Phase 3A | 1 | TASK-TEST-001 | Sequential - must complete before Phase 3B/3C |
| Phase 3B | 2 | TASK-DEPLOY-001, TASK-SECURITY-001 | Parallel after TASK-TEST-001 done |
| Phase 3C | 2 | TASK-DEPLOY-002, TASK-DEPLOY-003 | Parallel after TASK-DEPLOY-001 done |
| Phase 4 | 1 | TASK-CLEANUP-001, UX-204, TEST-PLACEHOLDER | Opportunistic cleanup |

---

## Key Dependencies Graph

```
TASK-DOCKER-002 (done) ──┐
TASK-DB-004 (done) ───┤
TASK-DB-005 (done) ───┘
                         │
                         ↓
                   TASK-TEST-001 (in_review)
                    ╱  │  ╲
          TASK-DEPLOY-001  TASK-TEST-002  TASK-ROLLBACK-001
                 │               │
                 ↓               ↓
          TASK-SECURITY-001     (done enables more tasks)
                 │
                 ↓
          (enables Phase 4)

          TASK-DEPLOY-002 (pending)
                 │
                 ↓
          TASK-DEPLOY-003 (pending)
```

---

## Critical Path

**Tasks on critical path (must complete to unblock others):**

1. TASK-API-003 (BLOCKED) - **Immediately unblock this**
2. TASK-TEST-001 (IN_REVIEW) - **Mark done to unblock 4 tasks**
3. TASK-DEPLOY-001 (PENDING) - **Unblocks TASK-SECURITY-001**
4. TASK-DEPLOY-002 (PENDING) - **Unblocks TASK-DEPLOY-003**

**Tasks NOT on critical path (can do anytime):**
- TASK-COV-001 (in_progress)
- TASK-FEAT-002 (in_progress)
- TASK-WORKFLOW-001 (in_progress)
- TASK-API-004, TASK-LINT-001, TASK-CRITICAL-001, TASK-CRITICAL-006 (all in_review)
- TASK-CLEANUP-001, UX-204, TEST-PLACEHOLDER (low priority)

---

## Immediate Action Items (Next 15 minutes)

1. **Resolve TASK-API-003 merge conflict** - Worktree exists, fix and merge
2. **Verify TASK-API-004 work** - Helen/Ivan completed, mark done if tests pass
3. **Verify TASK-LINT-001 work** - Ivan completed, mark done if tests pass
4. **Complete TASK-WORKFLOW-001** - opencode started, finish and mark in_review
5. **Mark TASK-UNBLOCK-001 as done** - Already accomplished (11 tasks now done)

---

## Worker Assignment Recommendations

| Worker | Assigned Task | Status | Action |
|---------|----------------|----------|---------|
| Helen | TASK-COV-001 | in_progress | Continue work |
| Kevin | TASK-FEAT-002 | in_progress | Continue work |
| opencode | TASK-WORKFLOW-001 | in_progress | Complete, mark in_review |
| Bob | TASK-API-003 | blocked | Resolve merge conflict immediately |
| Unassigned | TASK-API-004 | in_review | Mark done (work complete) |
| Unassigned | TASK-LINT-001 | in_review | Mark done (work complete) |
| Unassigned | TASK-CRITICAL-001 | in_review | Merge to main |
| Unassigned | TASK-CRITICAL-006 | in_review | Mark done if tests pass |
| Unassigned | TASK-TEST-001 | in_review | Mark done (dependencies satisfied) |
| Unassigned | TASK-UNBLOCK-001 | in_review | Mark done (work complete) |

**Total Active Workers:** 3 (Helen, Kevin, opencode)
**Available Workers:** Unlimited (unassigned tasks ready to claim)
