# Documentation Fix Summary

## Problems Identified

### 1. Worker Workflow Unclear
**Issue:** Workers didn't know complete end-to-end workflow from claim to merge.
- Workers were told to mark tasks as `in_review` but not told to wait for daemon
- Workers didn't know manager daemon automatically marks tasks `done` after merge
- Workers didn't know they should keep worktrees alive after unclaiming
- TASKS.md incorrectly said "When approved: set to `done`" (workers never approve)

### 2. Worktree Lifecycle Confusion
**Issue:** Conflicting guidance on when to remove worktrees.
- AGENTS.md said "keep until task is merged to main"
- But workers might remove worktrees after marking `in_review`
- Only worker-pool-manager-prompt.txt had correct complete instructions
- MANAGER_AGENT_PROMPT.md didn't explicitly tell workers to keep worktrees alive

### 3. Redundant / Outdated Information
**Issue:** Multiple documents overlapping with inconsistent information.
- MANAGER_DAEMON.md and MANAGER_AGENT_PROMPT.md both described daemon responsibilities
- AGENTS.md had agent-specific advice mixed with general worktree guidance
- TASKS.md had duplicate Agent Workflow section (lines 218-289 appeared twice)
- Instructions scattered across 4 different files

### 4. Missing Consolidated Worker Document
**Issue:** No single document workers could follow from start to finish.
- Workers had to piece together instructions from 4 different files
- Workflow was fragmented and hard to follow

## Fixes Applied

### 1. Created WORKER_WORKFLOW.md
**New document** providing complete end-to-end worker workflow:
- Step-by-step workflow from claim to merge
- Task status flow diagram
- Troubleshooting common scenarios (blocked tasks, merge conflicts, dependencies)
- Clear list of what workers NEVER do
- API call examples for each workflow step
- Port allocation guidance

### 2. Updated MANAGER_DAEMON.md
**Clarified daemon responsibilities and manager/daemon division:**
- Emphasized daemon's PRIMARY FUNCTION is reviewing and merging in_review tasks
- Added detailed steps of what daemon does (git operations, tests, linting, merging)
- Added explicit instruction: "Workers must keep worktrees alive until task status becomes 'done'"
- Added detailed list of what daemon does (automated) vs what manager must do
- Added explicit list of what manager NEVER does with daemon running

### 3. Updated MANAGER-7-PROMPT.md
**Updated worker launch instructions:**
- Changed to reference WORKER_WORKFLOW.md for complete workflow
- Added critical instruction: "Keep worktree alive until task status is 'done'"
- Clarified manager daemon handles review, test, and merge automatically
- Removed redundant workflow steps from launch prompt (now in WORKER_WORKFLOW.md)
- Emphasized daemon automatically marks tasks 'done' after merge

### 4. Updated AGENTS.md
**Simplified git worktrees section:**
- Removed agent-specific advice (moved to WORKER_WORKFLOW.md)
- Added clear CRITICAL note about keeping worktrees alive until 'done'
- Added examples for creating, working in, and removing worktrees
- Added dedicated agent workflow subsection for worktrees
- Reorganized agent documentation to separate manager vs worker docs
- References WORKER_WORKFLOW.md for worker agents

### 5. Updated TASKS.md
**Cleaned up Task Database System section:**
- Added reference to WORKER_WORKFLOW.md at top of section
- Removed duplicate Agent Workflow section (kept only API reference)
- Clarified workers should read WORKER_WORKFLOW.md for complete workflow
- Kept API endpoint documentation for reference purposes

## Workflow Clarifications

### Task Status Flow (Now Clear)
```
pending (unclaimed)
  ↓
  claim()
in_progress (worker is working)
  ↓
  set-status("in_review") + unclaim()
in_review (daemon is reviewing)
  ↓
  daemon merges to main
done (merged) ← Worker removes worktree here
```

### Worker Responsibilities (Now Clear)
✅ DO:
- Claim tasks via POST /api/tasks/{task_id}/claim
- Work in worktree, test, commit
- Send heartbeats every 5-10 minutes
- Update status notes at milestones
- Mark tasks as in_review when complete and tested
- Unclaim after marking in_review
- **Keep worktree alive until task status becomes 'done'**
- Remove worktree only after task is 'done'

❌ NEVER:
- Set status to 'done' yourself (daemon does this)
- Call /api/tasks/{task_id}/merge-to-main yourself (daemon does this)
- Remove worktree before task is 'done' (daemon needs it)
- Merge to main manually (daemon does this)
- Mark tasks as in_review without testing
- Work on tasks you haven't claimed

### Manager Daemon Responsibilities (Now Clear)
✅ Daemon DOES:
- Review all in_review tasks (every 2 minutes)
- Run pytest and make lint in worktrees
- Merge tasks to main via /api/tasks/{task_id}/merge-to-main
- Set task status to 'done' on successful merge
- Set task status to 'blocked' on failures
- Auto-unblock agent confusion tasks
- Detect and report stale workers
- Shut down when all work is done

❌ Daemon DOES NOT:
- Resolve merge conflicts (manager must intervene)
- Fix test failures (manager creates tasks or guides workers)
- Fix lint failures (manager creates tasks or guides workers)
- Unclaim stale tasks (manager must do this)

### Manager Responsibilities (With Daemon Running)
✅ Manager DOES:
- Handle merge conflicts (daemon can't auto-resolve)
- Handle test/lint failures (create tasks or guide workers)
- Recover abandoned work (unclaim stale tasks, reassign)
- Create resolution tasks when daemon marks tasks blocked
- Launch and coordinate workers
- Monitor for API failures
- Create new tasks when needed
- Handle edge cases daemon can't auto-resolve

❌ Manager DOES NOT:
- Manually merge tasks (daemon handles it)
- Run tests/linting on in_review tasks (daemon handles it)
- Call /api/tasks/{task_id}/merge-to-main (daemon handles it)
- Click "Auto-Merge All" button (daemon handles it automatically)
- Unclaim in_review tasks (let daemon review first)

## Documentation Structure (Now Clean)

### For Manager Agents
1. **MANAGER-7-PROMPT.md** - Complete manager agent prompt
2. **MANAGER_DAEMON.md** - Daemon responsibilities and setup
3. **WORKFLOW_PATTERNS.md** - Proven patterns and failures to avoid

### For Worker Agents
1. **WORKER_WORKFLOW.md** - Complete end-to-end workflow (READ THIS FIRST)
2. **TASKS.md** - API endpoint reference and task descriptions

### For Everyone
- **AGENTS.md** - Repository guidelines, tech stack, project structure
- **worker-pool-manager-prompt.txt** - Worker Pool Manager agent instructions

## Impact

### Before Fixes
- Workers confused about when to remove worktrees
- Workers didn't know daemon automatically marks tasks 'done'
- Instructions scattered across 4 documents
- Duplicate and conflicting information
- No single source of truth for worker workflow

### After Fixes
- Workers have single document (WORKER_WORKFLOW.md) for complete workflow
- Clear task status flow diagram
- Explicit list of worker responsibilities and limitations
- Clear division between daemon vs manager responsibilities
- All references point to WORKER_WORKFLOW.md for agent workflow
- Redundant information removed from TASKS.md
- AGENTS.md simplified and organized

## Verification

All commits:
```
7547481 docs: add WORKER_WORKFLOW.md reference to TASKS.md
7a7d430 docs: simplify AGENTS.md worktree section and update agent docs
855b43f docs: update worker launch instructions to reference WORKER_WORKFLOW.md
75bff36 docs: clarify manager daemon responsibilities and manager/daemon division
fa94a8d docs: add WORKER_WORKFLOW.md with complete end-to-end worker instructions
```

All documentation now points to WORKER_WORKFLOW.md as the single source of truth for worker agent workflow.
