# TASK-METRICS-001: Task Completion Metrics and Analytics Dashboard

## Current Status

**Status:** BLOCKED - Merge conflict during review
**Priority:** HIGH
**Task Type:** Feature
**Blocked Reason:** Merge conflict during review
**Worktree:** Previously `/home/josh/code/comic-pile-task-metrics` (missing)
**Commit:** 2b27d8e (feat(TASK-METRICS-001): add task metrics endpoint and analytics dashboard)
**Branch:** task/metrics-001

---

## Audit Findings (January 7, 2026)

### Critical Issues

1. **Worktree Missing:** The worktree `/home/josh/code/comic-pile-task-metrics` no longer exists
2. **Merge Conflict:** Task is blocked due to merge conflict during review
3. **Implementation Status:**
   - ✅ MetricsResponse schema added (app/schemas/task.py)
   - ✅ /api/tasks/metrics endpoint implemented (app/api/tasks.py)
   - ✅ /api/tasks/metrics/csv endpoint implemented (app/api/tasks.py)
   - ✅ Coordinator dashboard updated with analytics section (app/templates/coordinator.html)
   - ✅ Tests added (tests/test_task_api.py)
   - ⚠️ Branch has diverged significantly from main (69 files changed, 7732 insertions, 9399 deletions)
   - ❌ Large merge conflict due to unrelated changes included in branch

### What's Implemented (from commit 2b27d8e)

From the retro file created by worker agent Yvonne:

1. **MetricsResponse schema** - All required KPI fields
2. **Metrics endpoint** (`/api/tasks/metrics`) - SQLAlchemy aggregation queries
3. **CSV export endpoint** (`/api/tasks/metrics/csv`) - StreamingResponse
4. **Analytics dashboard** - Updated coordinator.html with visualizations
5. **Tests** - 3 new tests, 46 total tests passing

### What's Wrong

1. **Massive Merge Conflict:**
   - The task/metrics-001 branch includes 69 files changed
   - Many unrelated changes were merged into this branch
   - Branch includes changes to: AGENTS.md, MANAGER_DAEMON.md, WORKER_WORKFLOW.md, many API files, templates, migrations, etc.
   - This makes merging impossible without resolving conflicts

2. **Worktree Missing:**
   - Cannot review or test current implementation
   - Must recreate worktree from branch to review changes

3. **Branch Pollution:**
   - Branch contains changes from multiple other tasks/features
   - Makes it impossible to cleanly merge TASK-METRICS-001 alone

---

## What Needs to be Implemented (Detailed Breakdown)

### 1. Metrics Endpoint in Task API

**Location:** `app/api/tasks.py`

**Endpoint:** `GET /api/tasks/metrics`

**Response Schema:** `app/schemas/task.py:MetricsResponse`

**Fields Required:**
- `total_tasks: int` - Total number of tasks
- `tasks_by_status: Dict[str, int]` - Breakdown by status (pending, in_progress, done, blocked)
- `tasks_by_priority: Dict[str, int]` - Breakdown by priority (LOW, MEDIUM, HIGH, CRITICAL)
- `tasks_by_type: Dict[str, int]` - Breakdown by task_type (feature, bug_fix, spike, etc.)
- `tasks_by_agent: Dict[str, int]` - Breakdown by assigned_agent
- `average_completion_time: Optional[float]` - Avg time to complete tasks (in hours)
- `completed_this_week: int` - Tasks completed in last 7 days
- `completed_this_month: int` - Tasks completed in last 30 days
- `blocked_tasks: int` - Count of blocked tasks
- `stale_tasks: int` - Tasks with no heartbeat > 20 minutes

**Implementation Notes:**
- Use SQLAlchemy aggregation queries (func.count, func.avg)
- Handle timezone-aware datetime comparisons correctly
- Calculate completion time from `created_at` to `updated_at` for completed tasks
- Use conditional logic for stale task detection

### 2. CSV Export Endpoint

**Location:** `app/api/tasks.py`

**Endpoint:** `GET /api/tasks/metrics/csv`

**Response Type:** StreamingResponse with CSV content

**Implementation Notes:**
- Use Python's csv module with StringIO
- Download filename: "task_metrics.csv"
- Include all metric categories in CSV format
- Use StreamingResponse for efficient delivery

### 3. Analytics Dashboard Template

**Location:** `app/templates/coordinator.html`

**Required UI Elements:**

**KPI Cards (4 cards at top):**
- Total Tasks (overall count)
- Completed This Week (count)
- Completed This Month (count)
- Stale Tasks (count with warning color if > 0)

**Charts/Visualizations:**
- Tasks by Status - Bar chart or breakdown
- Tasks by Priority - Bar chart
- Tasks by Type - Bar chart
- Tasks by Agent - List or table breakdown
- Average Completion Time - Display with time unit (hours/days)

**Controls:**
- Refresh metrics button (loads from API via HTMX)
- Download CSV button (links to /api/tasks/metrics/csv)

**Implementation Notes:**
- Use HTMX to fetch metrics from API on page load
- Use Tailwind CSS for responsive design
- Color-code status (green=done, yellow=progress, red=blocked)
- Handle empty states gracefully

### 4. Tests for Metrics Functionality

**Location:** `tests/test_task_api.py`

**Required Tests:**
1. `test_get_metrics_basic` - Test metrics retrieval with sample data
2. `test_get_metrics_csv` - Test CSV export endpoint
3. `test_get_metrics_empty_database` - Test metrics with no tasks
4. `test_get_metrics_with_completed_tasks` - Test completion time calculation
5. `test_get_metrics_stale_tasks` - Test stale task detection
6. `test_get_metrics_blocked_tasks` - Test blocked task counting

**Test Coverage Requirements:**
- Test all metrics calculation logic
- Test edge cases (empty DB, single task, etc.)
- Test timezone handling in completion time calculations
- Test CSV export format and content

### 5. API Documentation

**OpenAPI/Swagger Docs:**
- Metrics endpoint will auto-document via FastAPI
- Ensure response schema is properly defined with Pydantic
- Add example responses to OpenAPI schema if needed
- Verify docs are visible at `/docs` endpoint

---

## Current Blocker: Merge Conflict

### Root Cause Analysis

The task/metrics-001 branch has diverged significantly from main due to:

1. **Branch Pollution:** The branch contains changes from multiple unrelated tasks/features:
   - Documentation changes (AGENTS.md, MANAGER_DAEMON.md, WORKER_WORKFLOW.md)
   - API changes (roll.py, rate.py, session.py, queue.py, thread.py, undo.py)
   - Template changes (404.html, history.html, roll.html, base.html)
   - Migration changes (multiple Alembic migration files)
   - Model changes (session.py, thread.py, snapshot.py)
   - Test changes (multiple test files)
   - Removal of many documentation files and scripts

2. **Divergence:** Main branch has moved forward since the metrics branch was created
3. **No Clean Diff:** The branch cannot be cleanly rebased or merged to main

### Impact

- Cannot review the metrics implementation in isolation
- Cannot merge metrics feature without resolving massive conflicts
- The metrics implementation is likely correct but buried in unrelated changes
- Must recreate the metrics feature in a clean branch

---

## Steps to Complete Missing Implementation

### Option A: Recreate Worktree and Extract Metrics Changes

1. **Recreate worktree from metrics branch:**
   ```bash
   git worktree add /home/josh/code/comic-pile-task-metrics task/metrics-001
   cd /home/josh/code/comic-pile-task-metrics
   ```

2. **Review and extract metrics-specific changes:**
   - Review app/schemas/task.py (MetricsResponse schema)
   - Review app/api/tasks.py (metrics endpoints)
   - Review app/templates/coordinator.html (analytics section)
   - Review tests/test_task_api.py (metrics tests)

3. **Create a new clean branch for just metrics:**
   ```bash
   cd /home/josh/code/comic-pile
   git checkout main
   git checkout -b task/metrics-001-clean
   ```

4. **Cherry-pick or manually port metrics changes:**
   - Copy MetricsResponse schema from metrics branch
   - Copy metrics endpoint implementation
   - Copy coordinator template updates
   - Copy test additions

5. **Test the implementation:**
   - Run `pytest tests/test_task_api.py -k metrics`
   - Run full test suite: `pytest`
   - Verify metrics endpoint returns correct data
   - Verify dashboard displays metrics correctly

6. **Run linting:**
   - `make lint`
   - Fix any linting errors

### Option B: Implement from Scratch (Clean Slate)

1. **Create new clean branch:**
   ```bash
   cd /home/josh/code/comic-pile
   git checkout main
   git checkout -b task/metrics-001-clean
   ```

2. **Implement MetricsResponse schema:**
   - Add to app/schemas/task.py
   - Define all required fields with proper types

3. **Implement metrics endpoints:**
   - Add GET /api/tasks/metrics endpoint to app/api/tasks.py
   - Add GET /api/tasks/metrics/csv endpoint to app/api/tasks.py
   - Use SQLAlchemy aggregation queries
   - Handle timezone-aware datetimes correctly

4. **Update coordinator dashboard:**
   - Add analytics section to app/templates/coordinator.html
   - Use HTMX to fetch metrics from API
   - Add KPI cards, charts, and download button

5. **Add tests:**
   - Add 6 required tests to tests/test_task_api.py
   - Ensure all metrics logic is covered
   - Test edge cases

6. **Run full test and lint suite:**
   - `pytest`
   - `make lint`

---

## Steps to Resolve Merge Conflict

### Option A: Abandon Polluted Branch, Create Clean One (Recommended)

1. **Abandon the polluted branch:**
   ```bash
   git branch -D task/metrics-001  # Local branch
   git push origin --delete task/metrics-001  # If pushed to remote
   ```

2. **Create clean branch and implement:**
   - Follow Option A or B from "Steps to Complete Missing Implementation" above

3. **Mark old worktree path as invalid in task records:**
   - Update task database to set worktree to null or new path
   - Ensure task is not associated with old corrupted branch

### Option B: Attempt Manual Resolution (Not Recommended)

1. **Recreate worktree:**
   ```bash
   git worktree add /home/josh/code/comic-pile-task-metrics task/metrics-001
   cd /home/josh/code/comic-pile-task-metrics
   ```

2. **Attempt rebase to latest main:**
   ```bash
   git fetch origin
   git rebase origin/main
   ```

3. **Resolve conflicts manually:**
   - This will have HUNDREDS of conflicts due to branch pollution
   - Will be extremely time-consuming and error-prone
   - High risk of introducing bugs from unrelated changes

4. **Test thoroughly:**
   - Would require extensive testing to ensure no regressions

**Note:** This approach is NOT recommended due to the massive scope of conflicts.

---

## Acceptance Criteria for Task to be Truly Done

### Code Implementation

- [ ] MetricsResponse schema exists in app/schemas/task.py with all required fields
- [ ] GET /api/tasks/metrics endpoint exists and returns correct MetricsResponse
- [ ] GET /api/tasks/metrics/csv endpoint exists and downloads CSV file
- [ ] Coordinator dashboard has analytics section with KPI cards and visualizations
- [ ] Metrics are calculated correctly using SQLAlchemy aggregation
- [ ] Timezone-aware datetime comparisons handled correctly
- [ ] Stale task detection works (20-minute threshold)
- [ ] CSV export format is correct and includes all metrics

### Tests

- [ ] All 6 required tests exist in tests/test_task_api.py
- [ ] test_get_metrics_basic passes
- [ ] test_get_metrics_csv passes
- [ ] test_get_metrics_empty_database passes
- [ ] test_get_metrics_with_completed_tasks passes
- [ ] test_get_metrics_stale_tasks passes
- [ ] test_get_metrics_blocked_tasks passes
- [ ] Full test suite passes: `pytest` (46+ tests)
- [ ] Test coverage maintained at 90%+ threshold

### Linting and Code Quality

- [ ] `make lint` passes with no errors
- [ ] No ruff linting issues
- [ ] No pyright type checking errors
- [ ] Code follows project conventions (PEP 8, 100-char line limit)
- [ ] No in-line code comments (clear code preferred)

### Documentation

- [ ] API endpoint auto-documents in FastAPI /docs
- [ ] Response schema properly documented
- [ ] Example responses available in OpenAPI spec
- [ ] Task documentation (this file) is complete and accurate

### Functional Testing

- [ ] Metrics endpoint returns correct data for various task states
- [ ] Dashboard displays metrics correctly in browser
- [ ] CSV download works and contains correct data
- [ ] Refresh button reloads metrics via HTMX
- [ ] Average completion time calculated correctly
- [ ] Stale and blocked tasks counted correctly

### Git and Branch Management

- [ ] Task implemented in a clean branch from main
- [ ] Branch contains ONLY metrics-related changes
- [ ] No merge conflicts with main
- [ ] Branch can be cleanly merged to main
- [ ] Worktree exists and is valid (if using worktree)
- [ ] All changes committed to branch

### Manager Daemon Review

- [ ] Task marked as `in_review` via API call
- [ ] Worker agent unclaimed task
- [ ] Manager daemon reviewed and merged to main
- [ ] Worktree removed after successful merge
- [ ] Task status updated to `done`

---

## Additional Notes

### Design Decisions from Original Implementation

From the retro file by worker agent Yvonne:

1. **Schema-first approach:** Define MetricsResponse first, then implement to match
2. **Timezone handling:** Check `datetime.tzinfo` before comparisons, use `datetime.replace(tzinfo=UTC)` for naive conversion
3. **Streaming CSV:** Use FastAPI's StreamingResponse with StringIO for efficiency
4. **Jinja2 power:** Use conditionals, math operations, and string manipulation in templates
5. **Test isolation:** Run specific test suites with `pytest -k` flag
6. **No code comments:** Follow project convention of clear code over comments

### Potential Improvements (for future work)

1. **Add caching** for metrics queries (60-300 second TTL)
2. **Add more visualizations** (time-series charts, pie charts using Chart.js)
3. **Add historical metrics tracking** (metrics_history table for trends)
4. **Configurable stale thresholds** via environment variable
5. **Multiple export formats** (JSON, Excel in addition to CSV)

---

## References

- Original retro file: `retro-metrics-001.md` (from commit 2b27d8e)
- Task API: `app/api/tasks.py`
- Task schemas: `app/schemas/task.py`
- Coordinator template: `app/templates/coordinator.html`
- Task tests: `tests/test_task_api.py`
- MANAGER_RETRO_2026-01-06.md: Task listed as completed by workers

---

**Last Updated:** January 7, 2026
**Audit Date:** January 7, 2026
**Status:** BLOCKED - Needs clean implementation in new branch
