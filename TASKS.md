# Task Tracking - Dice-Driven Comic Tracker
# FastAPI + HTMX + Tailwind CSS + SQLite

**Last Updated**: 2025-12-31 (Task database system implemented)
**Current Phase**: 10 (PRD Alignment)
**Overall Progress**: 64/76 tasks (84%)

---

## Task Database System

**IMPORTANT**: Task state is now stored in the database instead of this file. All task tracking operations should use the API endpoints below. This file is kept for historical reference and task descriptions.

### API Endpoints

All task operations are performed via REST API endpoints at `/api/tasks/`:

#### Initialize Tasks
```bash
POST /api/tasks/initialize
```
Initializes all 12 PRD tasks in the database. Idempotent - can be run multiple times safely.

Example:
```bash
curl -X POST http://localhost:8000/api/tasks/initialize
```

#### List All Tasks
```bash
GET /api/tasks/
```
Returns all tasks with current state.

Example:
```bash
curl http://localhost:8000/api/tasks/
```

#### Get Single Task
```bash
GET /api/tasks/{task_id}
```
Get details for a specific task.

Example:
```bash
curl http://localhost:8000/api/tasks/TASK-101
```

#### Claim a Task
```bash
POST /api/tasks/{task_id}/claim
```
Claims a task for an agent. Sets status to "in_progress" and records agent name and worktree.

Request body:
```json
{
  "agent_name": "agent-1",
  "worktree": "comic-pile-task-101"
}
```

Example:
```bash
curl -X POST http://localhost:8000/api/tasks/TASK-101/claim \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "agent-1", "worktree": "comic-pile-task-101"}'
```

#### Update Status Notes
```bash
POST /api/tasks/{task_id}/update-notes
```
Appends a note to the task's status_notes field. Notes are timestamped and preserved.

Request body:
```json
{
  "notes": "Started implementing narrative summary function"
}
```

Example:
```bash
curl -X POST http://localhost:8000/api/tasks/TASK-101/update-notes \
  -H "Content-Type: application/json" \
  -d '{"notes": "Started implementing narrative summary function"}'
```

#### Set Task Status
```bash
POST /api/tasks/{task_id}/set-status
```
Changes the task status. Valid statuses: `pending`, `in_progress`, `blocked`, `in_review`, `done`.

Request body:
```json
{
  "status": "in_review"
}
```

Example:
```bash
curl -X POST http://localhost:8000/api/tasks/TASK-101/set-status \
  -H "Content-Type: application/json" \
  -d '{"status": "in_review"}'
```

#### Filter Tasks by Status
```bash
GET /api/tasks/by-status/{status}
```
Get all tasks with a specific status.

Example:
```bash
curl http://localhost:8000/api/tasks/by-status/pending
curl http://localhost:8000/api/tasks/by-status/in_progress
```

#### Get Tasks by Agent
```bash
GET /api/tasks/by-agent/{agent_name}
```
Get all tasks assigned to a specific agent.

Example:
```bash
curl http://localhost:8000/api/tasks/by-agent/agent-1
```

#### Get Ready Tasks
```bash
GET /api/tasks/ready
```
Get tasks that are ready for claiming. Returns tasks that are:
- status = "pending" (not claimed)
- blocked_reason = NULL (not blocked)
- All dependencies are "done" (check dependencies)
- Ordered by priority (HIGH first, then MEDIUM, then LOW)

Example:
```bash
curl http://localhost:8000/api/tasks/ready
```

#### Task Heartbeat
```bash
POST /api/tasks/{task_id}/heartbeat
```
Update task heartbeat to show active work. Only allowed by the assigned agent.

Request body:
```json
{
  "agent_name": "agent-1"
}
```

Example:
```bash
curl -X POST http://localhost:8000/api/tasks/TASK-101/heartbeat \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "agent-1"}'
```

Returns 403 if not assigned to the requesting agent.

#### Unclaim Task
```bash
POST /api/tasks/{task_id}/unclaim
```
Unclaim a task - resets to pending status and clears assignment. Only allowed by the assigned agent (or admin).

Request body:
```json
{
  "agent_name": "agent-1"
}
```

Example:
```bash
curl -X POST http://localhost:8000/api/tasks/TASK-101/unclaim \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "agent-1"}'
```

Returns 403 if not assigned to the requesting agent.

#### Coordinator Data
```bash
GET /api/tasks/coordinator-data
```
Get all tasks grouped by status for coordinator dashboard.

Example:
```bash
curl http://localhost:8000/api/tasks/coordinator-data
```

Returns:
```json
{
  "pending": [...],
  "in_progress": [...],
  "blocked": [...],
  "in_review": [...],
  "done": [...]
}
```

### Agent Workflow

When working on a PRD alignment task:

1. **Claim task** when you start work:
   ```bash
   curl -X POST http://localhost:8000/api/tasks/TASK-101/claim \
     -H "Content-Type: application/json" \
     -d '{"agent_name": "your-agent-name", "worktree": "your-worktree-path"}'
   ```
   - Returns 409 Conflict if task is already claimed by another agent
   - Includes current assignee name, worktree, and claim time in conflict response

2. **Send heartbeat** every 5-10 minutes while actively working:
   ```bash
   curl -X POST http://localhost:8000/api/tasks/TASK-101/heartbeat \
     -H "Content-Type: application/json" \
     -d '{"agent_name": "your-agent-name"}'
   ```
   - Updates task's `last_heartbeat` timestamp
   - Returns 403 if you're not the assigned agent
   - Helps coordinator see who's actively working

3. **Update notes** frequently to document progress:
   ```bash
   curl -X POST http://localhost:8000/api/tasks/TASK-101/update-notes \
     -H "Content-Type: application/json" \
     -d '{"notes": "Created narrative summary function"}'
   ```

4. **Set status** when task state changes:
   - When complete and ready for review: set to `in_review`
   - When blocked by dependency: set to `blocked` with reason:
     ```bash
     curl -X POST http://localhost:8000/api/tasks/TASK-101/set-status \
       -H "Content-Type: application/json" \
       -d '{"status": "blocked", "blocked_reason": "Waiting for TASK-102", "blocked_by": "TASK-102"}'
     ```
   - When unblocked or continuing: set to `in_progress` or `pending`
   - When approved: set to `done`

5. **Unclaim task** if abandoning work:
   ```bash
   curl -X POST http://localhost:8000/api/tasks/TASK-101/unclaim \
     -H "Content-Type: application/json" \
     -d '{"agent_name": "your-agent-name"}'
   ```
   - Only allowed by assigned agent (or admin)
   - Resets status to `pending`
   - Clears assigned_agent and worktree fields
   - Adds note: "Unclaimed by {agent_name}"

6. **Check task status** anytime:
   ```bash
   curl http://localhost:8000/api/tasks/TASK-101
   ```

7. **Use coordinator dashboard** for task visibility:
   - Open http://localhost:8000/tasks/coordinator
   - Shows all tasks grouped by status
   - Auto-refreshes every 10 seconds
   - Has Claim/Unclaim buttons for quick actions
   - Displays agent, worktree, last_update for each task

8. **Get ready tasks** to see what can be claimed:
   ```bash
   curl http://localhost:8000/api/tasks/ready
   ```
   - Returns tasks that are:
     - Status: pending (not claimed)
     - Not blocked (blocked_reason = NULL)
     - All dependencies are "done"
   - Ordered by priority: HIGH first, then MEDIUM, then LOW

2. **Update notes** frequently to document progress:
   ```bash
   curl -X POST http://localhost:8000/api/tasks/TASK-101/update-notes \
     -H "Content-Type: application/json" \
     -d '{"notes": "Created narrative summary function"}'
   ```

3. **Set status** when task state changes:
   - When complete and ready for review: set to `in_review`
   - When blocked by dependency: set to `blocked`
   - When approved: set to `done`

4. **Check task status** anytime:
   ```bash
   curl http://localhost:8000/api/tasks/TASK-101
   ```

### Why Database Instead of This File?

- **No git conflicts**: Multiple agents can update task state simultaneously
- **Real-time status**: Always see current task assignments and progress
- **History tracking**: Status notes preserve complete history
- **Programmatic access**: Easy to build dashboards and reporting tools

---

## Legend
- 🟢 **pending**: Not started
- 🟡 **in_progress**: Agent working on it
- 🟣 **review**: Agent finished, awaiting review
- 🔴 **blocked**: Waiting on dependency
- ✅ **completed**: Done and tested
- ❌ **failed**: Failed, needs retry

---

## Phase 1: Cleanup & FastAPI Setup
**Branch**: `phase/1-cleanup-fastapi-setup`
**Status**: Complete ✅
**Dependencies**: None
**Worktrees Created**: 0/5

| ID | Task | Status | Agent | Worktree | Tested | Linted | Committed | Notes |
|----|-------|---------|----------|----------|----------|------------|--------|
| 1.1 | Rename package `comic-pile/` → `comic_pile/` | ✅ | p1-wt1 | - | - | abc | Directory renamed, import works |
| 1.2 | Update imports across all files | ✅ | p1-wt1 | - | - | abc123 | main.py, test_example.py updated, __init__.py fixed |
| 1.3 | Update pyproject.toml package name | ✅ | - | ✅ | ✅ | 1114170 | Package name updated to comic_pile |
| 1.4 | Add FastAPI dependencies | ✅ | - | ✅ | ✅ | 1114170 | All deps installed, imports verified, tests + lint pass |
| 1.5 | Remove old template code | ✅ | - | - | - | - | a4b99b3 | Delete main.py, comic_pile/core.py |
| 1.6 | Update Makefile for FastAPI | ✅ | - | - | - | - | 70d77b7 | Remove cdisplayagain targets, add FastAPI targets |
| 1.7 | Update CI workflow | ✅ | - | - | - | - | 5b70d53 | Remove Tkinter/unnar deps, update coverage package |
| 1.8 | Rewrite AGENTS.md | ✅ | - | - | - | - | 4b7260e | FastAPI + HTMX context, remove comic viewer references |
| 1.9 | Rewrite CONTRIBUTING.md | ✅ | - | - | - | - | 23318c4 | FastAPI development workflow, remove comic viewer references |
| 1.10 | Update README.md | ✅ | - | - | - | - | a1b11f5 | New app description, FastAPI setup instructions |

**Phase Complete When**: All 10 tasks ✅, phase branch linted & tested, merged to main

---

## Phase 2: Database & Models
**Branch**: `phase/2-database-models`
**Status**: Complete ✅
**Dependencies**: Phase 1 merged to main
**Worktrees Created**: 0/4

| ID | Task | Status | Agent | Worktree | Tested | Linted | Committed | Notes |
|----|-------|---------|----------|----------|----------|------------|--------|
| 2.11 | Create FastAPI app structure (app/, templates/, static/) | ✅ | p2-w1 | - | - | - | 0b61592 | App structure with CORS |
| 2.12 | Create SQLAlchemy models (User, Thread, Session, Event, etc.) | ✅ | p2-w1 | - | - | - | aec8f81 | All models with relationships |
| 2.13 | Create database connection | ✅ | p2-w4 | - | - | - | 831e36a | SQLAlchemy session factory, engine config |
| 2.14 | Set up Alembic (migrations) | ✅ | p2-w4 | - | - | - | 831e36a | Alembic initialized, initial migration created |
| 2.15 | Create Pydantic schemas (ThreadCreate, RollResponse, etc.) | ✅ | p2-w2 | - | - | - | 7d317ed | Request/response validation |
| 2.16 | Implement dice ladder logic (step_down, step_up, bounds) | ✅ | p2-w2 | - | - | - | 898ec5c | DICE_LADDER = [4, 6, 8, 10, 12, 20] |
| 2.17 | Implement queue logic (move_to_front, move_to_back, get_roll_pool) | ✅ | p2-w3 | - | - | - | 17aed9c | Queue position management |
| 2.18 | Implement session logic (is_active, should_start_new, get_or_create) | ✅ | p2-w3 | - | - | - | d7cb956 | 6-hour gap detection |

---

## Phase 3: REST API Endpoints
**Branch**: `phase/3-rest-api`
**Status**: Complete ✅
**Dependencies**: Phase 2 merged to main
**Worktrees Created**: 0/6

| ID | Task | Status | Agent | Worktree | Tested | Linted | Committed | Notes |
|----|-------|---------|----------|----------|----------|------------|--------|
| 3.19 | Thread CRUD API (GET /threads/, POST /threads/, etc.) | ✅ | p3-w1 | - | - | - | e99f70c | All CRUD endpoints |
| 3.20 | Roll API (POST /roll/, POST /roll/override/) | ✅ | p3-w1 | - | - | - | e99f70c | Dice roll + override |
| 3.21 | Rate API (POST /rate/) | ✅ | p3-w2 | - | ✅ | ✅ | 9bace14 | Decrement issues, move queue, update die |
| 3.22 | Queue API (PUT /threads/{id}/position/) | ✅ | p3-w2 | - | ✅ | ✅ | 4f6c6a3 | For drag/drop - move_to_position, front, back |
| 3.23 | Session API (GET /session/current/, GET /sessions/) | ✅ | p3-w3 | - | - | - | e99f70c | With narrative summaries |
| 3.24 | Admin API (import CSV, export JSON/CSV) | ✅ | p3-w3 | - | - | - | e05ebbc | Google Sheets compatibility |
| 3.25 | Setup CORS (allow local network access) | ✅ | p3-w4 | - | - | - | 0b61592 | origins=["*"] for dev |
| 3.26 | Set up Jinja2Templates (configure template directory) | ✅ | p3-w4 | - | - | - | 876670e | Base template created |
| 3.27 | Mount static files (/static route) | ✅ | p3-w4 | - | - | - | 19626a5 | CSS/JS/images |
| 3.28 | Create main FastAPI app (wire up all routes) | ✅ | p3-w5 | - | - | - | 57f64f6 | All routers wired up |
| 3.29 | Auto-generate API docs (FastAPI /docs endpoint) | ✅ | p3-w5 | - | - | - | 57f64f6 | Automatic via FastAPI |
| 3.30 | Add startup event (initialize database on app startup) | ✅ | p3-w5 | - | - | - | 57f64f6 | Tables created on startup |

---

## Phase 4: Frontend - Templates & Views
**Branch**: `phase/4-templates-views`
**Status**: Complete ✅
**Dependencies**: Phase 3 merged to main
**Worktrees Created**: 0/4

| ID | Task | Status | Agent | Worktree | Tested | Linted | Committed | Notes |
|----|-------|---------|----------|----------|----------|------------|--------|
| 4.31 | Create base template (Tailwind, HTMX, SortableJS, mobile meta) | ✅ | p4-w1 | - | - | - | 6a74bc5 | Bottom navigation toolbar |
| 4.32 | Create roll screen (die display, ROLL button, result area) | ✅ | p4-w1 | - | - | - | 81012ed | Flat dice faces |
| 4.33 | Create rate screen (rating slider, issues input, queue effect preview) | ✅ | p4-w2 | - | - | - | f9e644a | 0.5-5.0 rating |
| 4.34 | Create queue screen (list threads, highlight roll pool, staleness) | ✅ | p4-w2 | - | - | - | 117bd40 | Drag/drop ready |
| 4.35 | Create session history (narrative summaries, expandable details) | ✅ | p4-w3 | - | - | - | d5e1df5 | Session list with ladder path |
| 4.36 | Create add thread modal (title, format, issues remaining) | ✅ | p4-w3 | - | - | - | a1e8d0e | HTMX form submission |
| 4.37 | Create reactivation modal (select completed thread, issues to add) | ✅ | p4-w4 | - | - | - | 117bd40 | Must add > 0 issues |
| 4.38 | Create override modal (select thread to read instead of roll) | ✅ | p4-w4 | - | - | - | 117bd40 | |

---

## Phase 5: Frontend - Interactive Features
**Branch**: `phase/5-interactive-features`
**Status**: Complete ✅
**Dependencies**: Phase 4 merged to main
**Worktrees Created**: 0/2

| ID | Task | Status | Agent | Worktree | Tested | Linted | Committed | Notes |
|----|-------|---------|----------|----------|----------|------------|--------|
| 5.39 | Implement flat dice visualization (CSS classes, roll animation) | ✅ | p5-w1 | - | - | - | 891ebb9 | Simple faces with numbers |
| 5.40 | Implement drag/drop queue (SortableJS, mobile polyfill) | ✅ | p5-w1 | - | - | - | a2dfdfd | AJAX PUT to position API |
| 5.41 | Implement bottom navigation (active states, transitions) | ✅ | p5-w2 | - | - | - | f95a0e9 | Touch-friendly buttons (44px+) |
| 5.42 | Add stale thread indicators (color-coded badges) | ✅ | p5-w2 | - | - | - | af1fed7 | Green/yellow/red based on days |
| 5.43 | Add loading states (htmx-request class, spinners) | ✅ | p5-w3 | - | - | - | a2dfdfd | Disable buttons during request |

---

## Phase 6: Testing
**Branch**: `phase/6-testing`
**Status**: Complete ✅
**Dependencies**: Phase 3 & 5 merged to main
**Worktrees Created**: 0/3

| ID | Task | Status | Agent | Worktree | Tested | Linted | Committed | Notes |
|----|-------|---------|----------|----------|----------|------------|--------|
| 6.44 | Create test fixtures (in-memory SQLite, sample data) | ✅ | p6-w1 | - | - | - | ba29d7a | Override user_id=1 |
| 6.45 | Test dice ladder logic (step up/down, bounds) | ✅ | p6-w1 | - | - | - | 2455824 | Full ladder traversal |
| 6.46 | Test session logic (6-hour gap, auto-new) | ✅ | p6-w1 | - | - | - | cc557d4 | |
| 6.47 | Test roll mechanism (valid selection, overflow) | ✅ | p6-w2 | - | - | - | 3c6267c | |
| 6.48 | Test rating flow (decrement, queue move, die update) | ✅ | p6-w2 | - | - | - | 3c6267c | Thread completion |
| 6.49 | Test queue reordering (position updates) | ✅ | p6-w2 | - | - | - | 3c6267c | |
| 6.50 | Test API endpoints (httpx.AsyncClient, all CRUD) | ✅ | p6-w3 | - | - | - | e5553a2 | Integration tests |
| 6.51 | Test CSV import (valid format, invalid data, duplicates) | ✅ | p6-w3 | - | - | - | ff64836 | Google Sheets format |

---

## Phase 7: Data Import & Seeding
**Branch**: `phase/7-data-import`
**Status**: Complete ✅
**Dependencies**: Phase 2 merged to main
**Worktrees Created**: 0/2

| ID | Task | Status | Agent | Worktree | Tested | Linted | Committed | Notes |
|----|-------|---------|----------|----------|----------|------------|--------|
| 7.52 | Create seed command (Faker, 20-30 sample threads) | ✅ | - | - | ✅ | ✅ | 1ad600d | 25 threads, 7 sessions, events |
| 7.53 | Create CSV importer (parse, validate, insert at position 1) | ✅ | - | - | ✅ | - | - | Already implemented, all tests pass |
| 7.54 | Create CSV exporter (active threads, download) | ✅ | - | - | ✅ | ✅ | 780ef51 | Filters issues_remaining > 0 |
| 7.55 | Create JSON exporter (full database backup) | ✅ | - | - | ✅ | ✅ | 9ea5b92 | Downloadable with headers |

---

## Phase 8: Polish & Mobile Optimization
**Branch**: `phase/8-polish`
**Status**: Complete ✅
**Dependencies**: Phase 4, 5, 6 merged to main
**Worktrees Created**: 0/2

| ID | Task | Status | Agent | Worktree | Tested | Linted | Committed | Notes |
|----|-------|---------|----------|----------|----------|------------|--------|
| 8.56 | Mobile-responsive Tailwind CSS (touch targets, bottom nav) | ✅ | p8-w1 | - | ✅ | ✅ | c18f373 | Min 44px buttons |
| 8.57 | Performance optimization (caching, indexes, lazy load) | ✅ | p8-w2 | - | ✅ | ✅ | 827445a | |
| 8.58 | Error handling (HTTP errors, user-friendly messages) | ✅ | p8-w3 | - | ✅ | ✅ | 827445a | Inline form validation |
| 8.59 | Dice refinement (smooth animation, clear result display) | ✅ | p8-w1 | - | ✅ | ✅ | 827445a | 0.5s animation |
| 8.60 | Accessibility (ARIA labels, keyboard nav, contrast) | ✅ | p8-w2 | - | ✅ | ✅ | d9c8af5 | Alt text for images |
| 8.61 | Create development script (make dev, make test, make seed, make migrate) | ✅ | p8-w3 | - | ✅ | ✅ | c18f373 | | |

---

## Phase 9: Documentation
**Branch**: `phase/9-documentation`
**Status**: Complete ✅
**Dependencies**: Phase 8 merged to main
**Worktrees Created**: 0/2

| ID | Task | Status | Agent | Worktree | Tested | Linted | Committed | Notes |
|----|-------|---------|----------|----------|----------|------------|--------|
| | 9.62 | Update README.md (tech stack, setup, API docs, mobile access) | ✅ | p9-w1 | - | - | - | 28ab435 | |
| | 9.63 | Create API documentation (OpenAPI tags, CSV format, examples) | ✅ | p9-w2 | - | - | - | 924b7b5 | |
| | 9.64 | Update AGENTS.md & CONTRIBUTING.md (FastAPI, HTMX, Tailwind) | ✅ | p9-w1 | - | - | - | - | Verified current |

---

## Worktree Registry for PRD Alignment

| Worktree Name | Branch | Assigned Tasks | Status | Last Updated |
|--------------|----------|----------------|----------|--------------|
| (current dir) | phase/10-prd-alignment | TASK-101 | Not Created | - |

---

## Worktree Registry (Historical)

| Worktree Name | Branch | Assigned Tasks | Status | Last Updated |
|--------------|----------|----------------|----------|--------------|
| (current dir) | phase/1-cleanup-fastapi-setup | 1.1-1.4 | All Complete | 2025-12-30 |
| comic-pile-p1-wt2 | phase/1-cleanup-fastapi-setup | 1.3, 1.4 | Not Created | - |
| comic-pile-p1-wt3 | phase/1-cleanup-fastapi-setup | 1.5, 1.6 | Not Created | - |
| comic-pile-p1-wt4 | phase/1-cleanup-fastapi-setup | 1.7, 1.8 | Not Created | - |
| comic-pile-p1-wt5 | phase/1-cleanup-fastapi-setup | 1.9, 1.10 | Not Created | - |

---

## Merge History

| Phase | Branch | Merged By | Date | Quality Check |
|-------|----------|------------|-------|--------------|
| - | - | - | - |

---

## Blocked Tasks & Dependencies

| Task | Blocking Task | Resolution |
|------|---------------|-------------|
| 2.11 - 2.18 | Phase 1 (all tasks) | Wait for Phase 1 complete |
| 3.19 - 3.30 | Phase 2 (all tasks) | Wait for Phase 2 complete |
| 4.31 - 4.38 | Phase 3 (all tasks) | Wait for Phase 3 complete |
| 5.39 - 5.43 | Phase 4 (all tasks) | Wait for Phase 4 complete |
| 6.44 - 6.51 | Phase 3 & 5 complete | Wait for API + interactive features |
| 7.52 - 7.55 | Phase 2 complete | Wait for database models |
| 8.56 - 8.61 | Phase 4, 5, 6 complete | Wait for frontend + tests |
| 9.62 - 9.64 | Phase 8 complete | Wait for polish phase |
| TASK-109 | TASK-108 | Wait for issues read adjustment UI |
| TASK-111 | TASK-110 | Wait for last_review_at field addition |
| TASK-112 | TASK-101 | Wait for narrative summaries implementation |

---

## Pre-Merge Checklist (Phase Coordinator)

Before merging a phase branch to main:

- [ ] All tasks in phase marked ✅
- [ ] All commits have descriptive messages (conventional commits)
- [ ] `make pytest` passes with 96%+ coverage
- [ ] `make lint` passes
- [ ] `pyright .` passes
- [ ] No `# type: ignore`, `# noqa`, or similar workarounds in staged files
- [ ] All worktrees pruned: `git worktree prune`
- [ ] All worktree directories cleaned up
- [ ] Phase branch rebased on latest main: `git rebase main`
- [ ] Merge tested in clean main checkout
- [ ] TASKS.md updated with merge info

---

## Git Workflow Reference

### Creating a Phase Branch
```bash
git checkout main
git pull
git checkout -b phase/1-cleanup-fastapi-setup
```

### Creating a Worktree
```bash
git worktree add ../comic-pile-p1-wt1 phase/1-cleanup-fastapi-setup
cd ../comic-pile-p1-wt1
```

### Working in a Worktree
```bash
# Make changes
# Run tests
pytest --cov=comic_pile --cov-fail-under=96

# Run lint
make lint

# Commit
git add .
git commit -m "feat(1.1): rename package directory comic-pile to comic_pile"
```

### Removing a Worktree (After Merge)
```bash
git worktree remove ../comic-pile-p1-wt1
rm -rf ../comic-pile-p1-wt1
```

### Merging a Phase (Coordinator Only)
```bash
git checkout main
git pull
git merge --no-ff phase/1-cleanup-fastapi-setup

# Quality checks
make pytest
make lint
pyright .

# If passes, push
git push origin main

# Cleanup worktrees
make cleanup-phase1
```

---

# PRD Alignment Tasks (Phase 10)

**Branch**: `phase/10-prd-alignment`
**Status**: 🟢 pending
**Dependencies**: All previous phases merged to main
**Worktrees Created**: 0/3 (max allowed per AGENTS.md)

## Agent Instructions for PRD Alignment

### Port Allocation

To prevent conflicts, each agent's dev server uses a different port:

- Main repo (task API source of truth): **8000**
- Agent worktree 1: **8001**
- Agent worktree 2: **8002**
- Agent worktree 3: **8003**

**Starting your dev server:**
```bash
# In your worktree, set your unique port
PORT=8001 make dev

# Or export as environment variable
export PORT=8001
make dev
```

**Connecting to Task API:**
All agents query the task API on the **main repo** (port 8000):
```bash
http://localhost:8000/api/tasks/
```

**Important:** Never start your dev server on port 8000 from a worktree - that port is reserved for the main repo task API.

### Overview
These tasks address gaps between current implementation and PRD specifications identified in the PRD audit. All tasks are designed for agentic parallel execution using git worktrees.

### Claiming Tasks
- When you start working on a task, move it from **Todo** to **In Progress**
- Add your agent name to `Assigned Agent:` field
- Add your worktree name to `Worktree:` field
- Update status notes with your initial approach

### Workflow for Each Task
1. Read the task description and check dependencies
2. Create a git worktree for your work (see Git Worktree section below)
3. Implement following the references provided (file:line)
4. Update `Status Notes:` frequently with progress
5. Run `make lint` and `pytest` before marking complete
6. If blocked, move to **Blocked** section and document blocker
7. When complete, move to **In Review** with final notes

### Communication Guidelines
- Update status notes at each major milestone
- Be specific about blockers: what's blocking, what's needed
- Reference code locations using file:line format
- If task is more complex than estimated, break it into sub-tasks

### Git Worktree Instructions

**Why worktrees?**
- Allows parallel work on different features without branch conflicts
- Each agent works in an isolated directory
- Prevents breaking existing functionality
- Maintains clean main branch for reference

**Creating a worktree for PRD alignment:**
```bash
# From main branch, create the phase branch if not exists
git checkout main
git checkout -b phase/10-prd-alignment

# Add a worktree for your work
git worktree add ../comic-pile-prd-PRD-TASK-ID phase/10-prd-alignment

# Example for TASK-101:
# git worktree add ../comic-pile-prd-101 phase/10-prd-alignment

# Work in the worktree directory
cd ../comic-pile-prd-101
```

**Working in the worktree:**
```bash
# Make your changes
# Run tests: pytest
# Run lint: make lint

# Commit changes with conventional commit format
git add .
git commit -m "feat(TASK-101): complete narrative session summaries"
```

**Syncing with main:**
```bash
# Periodically update from main
git fetch origin
git rebase origin/main
```

**Cleanup when done:**
```bash
# After merging to main, clean up worktree
cd /home/josh/code/comic-pile
git worktree remove ../comic-pile-prd-101
```

**Rules:**
- Maximum 3 active worktrees for this phase (per AGENTS.md)
- Always work from a worktree, never from main branch
- Never push directly to main - push to feature branch
- Create pull requests from feature branch
- Test thoroughly before marking as In Review

---

## Todo

### TASK-101: Complete Narrative Session Summaries
**Priority:** HIGH
**Dependencies:** None
**Estimated Effort:** 4 hours

**Description:**
Implement narrative session summaries that show consolidated "Read:", "Skipped:", and "Completed:" lists per Section 11 of PRD.

**Required Changes:**
- Update session summary generation to aggregate events into categories
- Modify session details template to display narrative format
- Format must match PRD example with session header and categorized lists

**References:**
- PRD Section 11: Lines 306-330 (narrative summary format)
- Current implementation: `app/api/session.py:28-49` (build_ladder_path function)
- Current template: `app/templates/session_details.html:1-39`
- Session model: `app/models/session.py:17-44`
- Event model: `app/models/event.py:16-45`

**Implementation Approach:**
1. Create new function `build_narrative_summary(session_id, db)` in `app/api/session.py`
2. Query all events for session and group by type
3. Filter for "rate" events to build "Read:" list with ratings
4. Filter for "rolled_but_skipped" events to build "Skipped:" list
5. Check thread status changes for "Completed:" list
6. Update `app/templates/session_details.html` to display narrative summary before event logs
7. Ensure proper formatting with emojis and spacing per PRD

**Assigned Agent:** [unassigned]
**Worktree:** [unassigned]
**Status Notes:** [initial state]

---

### TASK-102: Add Staleness Awareness UI
**Priority:** MEDIUM
**Dependencies:** None
**Estimated Effort:** 3 hours

**Description:**
Display stale thread suggestions on roll screen per Section 7 of PRD: "You haven't touched X in 51 days"

**Required Changes:**
- Add API endpoint to fetch stale threads
- Display stale suggestion below roll pool on roll screen
- Informational only (no forced selection)

**References:**
- PRD Section 7: Lines 248-266 (staleness awareness)
- Existing helper: `comic_pile/queue.py:114-129` (get_stale_threads function)
- Thread model: `app/models/thread.py:16-47`
- Roll page template: `app/templates/roll.html:1-226`

**Implementation Approach:**
1. Add endpoint `GET /threads/stale?days=7` in `app/api/thread.py`
2. Use existing `get_stale_threads()` helper
3. Return stalest thread (most days inactive) with day count
4. Add API call in roll.html JavaScript to fetch stale thread
5. Display suggestion UI in roll template below pool display
6. Style as subtle nudge (not prominent, informational)

**Assigned Agent:** [unassigned]
**Worktree:** [unassigned]
**Status Notes:** [initial state]

---

### TASK-103: Queue UI Enhancements - Roll Pool Highlighting
**Priority:** MEDIUM
**Dependencies:** None
**Estimated Effort:** 2 hours

**Description:**
Add visual highlighting to roll pool threads (top N) in queue screen per Section 13 wireframe.

**Required Changes:**
- Highlight threads 1-N based on current die size
- Add visual distinction (border, background color)
- Show roll pool count

**References:**
- PRD Section 13: Lines 426-441 (queue wireframe)
- Queue template: `app/templates/queue.html:16-33`
- Queue API: `app/api/queue.py:1-113`
- Session die tracking: `comic_pile/session.py:65-84`

**Implementation Approach:**
1. Fetch current session die in queue page (add JS to call `/sessions/current/`)
2. Pass current die to thread list rendering
3. Add CSS class `roll-pool-item` to threads in roll pool (position <= die_size)
4. Style with border and subtle background color
5. Update roll pool count display to match die size

**Assigned Agent:** [unassigned]
**Worktree:** [unassigned]
**Status Notes:** [initial state]

---

### TASK-104: Queue UI Enhancements - Completed Threads Toggle
**Priority:** MEDIUM
**Dependencies:** None
**Estimated Effort:** 2 hours

**Description:**
Add "Show Completed" toggle button to queue screen to show/hide completed threads.

**Required Changes:**
- Add toggle button to queue UI
- Add endpoint to fetch all threads including completed
- Show/hide completed threads based on toggle state

**References:**
- PRD Section 13: Line 440 ("Completed hidden by default")
- Thread API: `app/api/thread.py:21-41` (list_threads)
- Queue template: `app/templates/queue.html:1-71`
- Thread model: `app/models/thread.py:26` (status field)

**Implementation Approach:**
1. Modify `list_threads()` endpoint to accept `include_completed` query parameter
2. Return all threads when true, only active when false
3. Add toggle button in queue template
4. Add JavaScript to re-fetch thread list on toggle
5. Store toggle state in localStorage for persistence

**Assigned Agent:** [unassigned]
**Worktree:** [unassigned]
**Status Notes:** [initial state]

---

### TASK-105: Queue UI Enhancements - Star Ratings Display
**Priority:** MEDIUM
**Dependencies:** None
**Estimated Effort:** 2 hours

**Description:**
Display star ratings (★★★★☆) in queue list based on `last_rating` field per wireframe.

**Required Changes:**
- Convert rating float to star display
- Show stars next to thread title
- Handle null ratings (no display)

**References:**
- PRD Section 13: Lines 430-437 (wireframe with stars)
- Thread model: `app/models/thread.py:27` (last_rating field)
- Queue template: `app/templates/queue.html:1-71`

**Implementation Approach:**
1. Create JavaScript function to convert rating to stars
2. Rating of 4.5 → "★★★★½", 4.0 → "★★★★☆", etc.
3. Add star display to thread item in queue template
4. Use gray/empty stars for unrated threads
5. Format: "3. Starman ★★★★"

**Assigned Agent:** [unassigned]
**Worktree:** [unassigned]
**Status Notes:** [initial state]

---

### TASK-106: Remove Unused Dice Ladder Functions
**Priority:** MEDIUM
**Dependencies:** None
**Estimated Effort:** 1 hour

**Description:**
Remove `step_up_to_max()` and `step_down_to_min()` functions from dice_ladder.py as they violate PRD Section 2.3.

**Required Changes:**
- Remove functions from code
- Verify no references exist
- Update tests if needed

**References:**
- PRD Section 2.3: Line 102 ("Manual overrides do not bypass ladder logic")
- Functions to remove: `comic_pile/dice_ladder.py:42-63`
- Tests: `tests/test_dice_ladder.py`

**Implementation Approach:**
1. Search codebase for references to `step_up_to_max` and `step_down_to_min`
2. If none found, remove functions from `comic_pile/dice_ladder.py`
3. If tests reference them, update or remove tests
4. Run `pytest` to ensure no breakage
5. Run `make lint` to ensure clean

**Assigned Agent:** [unassigned]
**Worktree:** [unassigned]
**Status Notes:** [initial state]

---

### TASK-107: Remove Notes Field from Events
**Priority:** MEDIUM
**Dependencies:** None
**Estimated Effort:** 2 hours

**Description:**
Remove `notes` field from Event model and database as PRD Section 5.2 states "No notes system exists".

**Required Changes:**
- Remove notes field from Event model
- Create migration to drop notes column
- Verify no code references

**References:**
- PRD Section 5.2: Line 214 ("No notes system exists")
- Event model: `app/models/event.py:34` (notes field)
- Initial migration: `alembic/versions/cdb492422a59_initial_schema.py:98`

**Implementation Approach:**
1. Search codebase for all references to `notes` field in events
2. Remove field from `app/models/event.py`
3. Create Alembic migration: `alembic revision --autogenerate -m "remove_notes_from_events"`
4. Manually edit migration to only drop notes column
5. Test migration: `make migrate` and verify database
6. Run `pytest` to ensure no breakage

**Assigned Agent:** [unassigned]
**Worktree:** [unassigned]
**Status Notes:** [initial state]

---

### TASK-108: Issues Read Adjustment UI
**Priority:** LOW
**Dependencies:** None
**Estimated Effort:** 2 hours

**Description:**
Add increment/decrement controls to rating form to adjust issues read (currently hardcoded to 1).

**Required Changes:**
- Add +/- buttons to rating form
- Update submit to send selected value
- Display current issues read count

**References:**
- PRD Section 5.2: Line 212 ("issues read: [1] (+ / -)")
- Rating request: `app/schemas/thread.py:61-65` (RateRequest schema)
- Rating form: `app/api/roll.py:103-118` (HTML form)
- Submit function: `app/templates/roll.html:176-212` (submitRating JavaScript)

**Implementation Approach:**
1. Add input field for issues_read in rating form HTML
2. Add +/- buttons to increment/decrement value
3. Initialize to 1, minimum 1
4. Update submitRating() to include issues_read in request body
5. Update rating form UI to show current value

**Assigned Agent:** [unassigned]
**Worktree:** [unassigned]
**Status Notes:** [initial state]

---

### TASK-109: Queue Effect Preview Enhancement
**Priority:** LOW
**Dependencies:** TASK-108
**Estimated Effort:** 1 hour

**Description:**
Add explicit queue movement preview text to rating form per PRD Section 13.

**Required Changes:**
- Update rating form to show queue effect text
- Dynamic update based on rating value
- Display prominently below rating slider

**References:**
- PRD Section 13: Lines 417-419 (queue effect preview)
- Current implementation: `app/api/roll.html:150-174` (updateRatingDisplay function)
- Rating form: `app/api/roll.py:103-118`

**Implementation Approach:**
1. Update `updateRatingDisplay()` function in roll.html
2. Add queue effect text to display
3. Rating >= 4.0: "Excellent! Die steps down 🎲 Move to front"
4. Rating < 4.0: "Okay. Die steps up 🎲 Move to back"
5. Ensure text updates dynamically as slider moves

**Assigned Agent:** [unassigned]
**Worktree:** [unassigned]
**Status Notes:** [initial state]

---

### TASK-110: Add last_review_at Field to Threads
**Priority:** LOW
**Dependencies:** None
**Estimated Effort:** 1 hour

**Description:**
Add `last_review_at` timestamp field to Thread model for storing imported review timestamps.

**Required Changes:**
- Add field to Thread model
- Create migration
- Update JSON export to include field

**References:**
- PRD Section 7: Line 254 ("last review timestamp (imported)")
- Thread model: `app/models/thread.py:16-47`
- JSON export: `app/api/admin.py:129-203`

**Implementation Approach:**
1. Add `last_review_at` field to `app/models/thread.py` (DateTime, nullable)
2. Create Alembic migration: `alembic revision --autogenerate -m "add_last_review_at_to_threads"`
3. Update `export_json()` to include `last_review_at` in output
4. Test migration: `make migrate`

**Assigned Agent:** [unassigned]
**Worktree:** [unassigned]
**Status Notes:** [initial state]

---

### TASK-111: Review Timestamp Import API
**Priority:** LOW
**Dependencies:** TASK-110
**Estimated Effort:** 3 hours

**Description:**
Add API endpoint to import review timestamps from League of Comic Geeks.

**Required Changes:**
- Create import endpoint for review data
- Accept CSV/JSON with thread_id, review_url, review_timestamp
- Update thread records

**References:**
- PRD Section 9: Lines 288-295 ("importing scraped review timestamps")
- Admin API: `app/api/admin.py:19-91` (CSV import pattern)
- Thread model: `app/models/thread.py:16-47`

**Implementation Approach:**
1. Create endpoint `POST /admin/import/reviews/` in `app/api/admin.py`
2. Accept CSV with columns: thread_id, review_url, review_timestamp
3. Parse CSV and validate thread_id exists
4. Update thread's last_review_at field
5. Return success/error report similar to CSV import
6. Add tests for new endpoint

**Assigned Agent:** [unassigned]
**Worktree:** [unassigned]
**Status Notes:** [initial state]

---

### TASK-112: Narrative Summary Export
**Priority:** LOW
**Dependencies:** TASK-101
**Estimated Effort:** 3 hours

**Description:**
Add export endpoint to generate narrative session summaries in readable text/markdown format.

**Required Changes:**
- Create export endpoint for narrative summaries
- Generate summaries for all sessions
- Format as readable per Section 11
- Trigger download from history page

**References:**
- PRD Section 10: Lines 298-303 ("Raw data export only")
- PRD Section 11: Lines 306-330 (narrative summary format)
- Export endpoints: `app/api/admin.py:94-203`
- History page: `app/templates/history.html:1-99`

**Implementation Approach:**
1. Reuse `build_narrative_summary()` function from TASK-101
2. Create endpoint `GET /admin/export/summary/` in `app/api/admin.py`
3. Query all sessions, generate narrative for each
4. Format as markdown with proper headers and spacing
5. Return as StreamingResponse for download
6. Add export button in history.html
7. File name: `session_summaries_{date}.md`

**Assigned Agent:** [unassigned]
**Worktree:** [unassigned]
**Status Notes:** [initial state]

---

## In Progress

*No tasks in progress yet*

---

## Blocked

*No blocked tasks yet*

---

## In Review

*No tasks in review yet*

---

## Done

*No tasks completed yet*

---

## PRD Alignment Summary

**Total Tasks:** 12
- High Priority: 1
- Medium Priority: 5
- Low Priority: 6

**Estimated Total Effort:** 26 hours

**No-Dependency Tasks (can start immediately):**
- TASK-101: Complete Narrative Session Summaries
- TASK-102: Add Staleness Awareness UI
- TASK-103: Queue UI Enhancements - Roll Pool Highlighting
- TASK-104: Queue UI Enhancements - Completed Threads Toggle
- TASK-105: Queue UI Enhancements - Star Ratings Display
- TASK-106: Remove Unused Dice Ladder Functions
- TASK-107: Remove Notes Field from Events
- TASK-108: Issues Read Adjustment UI
- TASK-110: Add last_review_at Field to Threads

**Tasks with Dependencies:**
- TASK-109: Queue Effect Preview Enhancement (depends on TASK-108)
- TASK-111: Review Timestamp Import API (depends on TASK-110)
- TASK-112: Narrative Summary Export (depends on TASK-101)

---

## PRD Alignment Progress Tracking

**Started:** [date]
**Completed:**
- [ ] TASK-101: Complete Narrative Session Summaries
- [ ] TASK-102: Add Staleness Awareness UI
- [ ] TASK-103: Queue UI Enhancements - Roll Pool Highlighting
- [ ] TASK-104: Queue UI Enhancements - Completed Threads Toggle
- [ ] TASK-105: Queue UI Enhancements - Star Ratings Display
- [ ] TASK-106: Remove Unused Dice Ladder Functions
- [ ] TASK-107: Remove Notes Field from Events
- [ ] TASK-108: Issues Read Adjustment UI
- [ ] TASK-109: Queue Effect Preview Enhancement
- [ ] TASK-110: Add last_review_at Field to Threads
- [ ] TASK-111: Review Timestamp Import API
- [ ] TASK-112: Narrative Summary Export

**Completion Percentage:** 0%
