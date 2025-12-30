# Task Tracking - Dice-Driven Comic Tracker
# FastAPI + HTMX + Tailwind CSS + SQLite

**Last Updated**: 2025-12-30
**Current Phase**: 1
**Overall Progress**: 10/64 tasks (16%)

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
**Status**: Blocked
**Dependencies**: Phase 3 & 5 merged to main
**Worktrees Created**: 0/3

| ID | Task | Status | Agent | Worktree | Tested | Linted | Committed | Notes |
|----|-------|---------|----------|----------|----------|------------|--------|
| 6.44 | Create test fixtures (in-memory SQLite, sample data) | 🔴 | - | - | - | - | Override user_id=1 |
| 6.45 | Test dice ladder logic (step up/down, bounds) | 🔴 | - | - | - | - | Full ladder traversal |
| 6.46 | Test session logic (6-hour gap, auto-new) | 🔴 | - | - | - | - | |
| 6.47 | Test roll mechanism (valid selection, overflow) | 🔴 | - | - | - | - | |
| 6.48 | Test rating flow (decrement, queue move, die update) | 🔴 | - | - | - | - | Thread completion |
| 6.49 | Test queue reordering (position updates) | 🔴 | - | - | - | - | |
| 6.50 | Test API endpoints (httpx.AsyncClient, all CRUD) | 🔴 | - | - | - | - | Integration tests |
| 6.51 | Test CSV import (valid format, invalid data, duplicates) | 🔴 | - | - | - | - | Google Sheets format |

---

## Phase 7: Data Import & Seeding
**Branch**: `phase/7-data-import`
**Status**: Blocked
**Dependencies**: Phase 2 merged to main
**Worktrees Created**: 0/2

| ID | Task | Status | Agent | Worktree | Tested | Linted | Committed | Notes |
|----|-------|---------|----------|----------|----------|------------|--------|
| 7.52 | Create seed command (Faker, 20-30 sample threads) | 🔴 | - | - | - | - | `python -m scripts.seed_data` |
| 7.53 | Create CSV importer (parse, validate, insert at position 1) | 🔴 | - | - | - | - | Match Google Sheets format |
| 7.54 | Create CSV exporter (active threads, download) | 🔴 | - | - | - | - | `threads_export.csv` |
| 7.55 | Create JSON exporter (full database backup) | 🔴 | - | - | - | - | All data + relationships |

---

## Phase 8: Polish & Mobile Optimization
**Branch**: `phase/8-polish`
**Status**: Blocked
**Dependencies**: Phase 4, 5, 6 merged to main
**Worktrees Created**: 0/2

| ID | Task | Status | Agent | Worktree | Tested | Linted | Committed | Notes |
|----|-------|---------|----------|----------|----------|------------|--------|
| 8.56 | Mobile-responsive Tailwind CSS (touch targets, bottom nav) | 🔴 | - | - | - | - | Min 44px buttons |
| 8.57 | Performance optimization (caching, indexes, lazy load) | 🔴 | - | - | - | - | |
| 8.58 | Error handling (HTTP errors, user-friendly messages) | 🔴 | - | - | - | - | Inline form validation |
| 8.59 | Dice refinement (smooth animation, clear result display) | 🔴 | - | - | - | - | 0.5s animation |
| 8.60 | Accessibility (ARIA labels, keyboard nav, contrast) | 🔴 | - | - | - | - | Alt text for images |
| 8.61 | Create development script (make dev, make test, make seed, make migrate) | 🔴 | - | - | - | - | |

---

## Phase 9: Documentation
**Branch**: `phase/9-documentation`
**Status**: Blocked
**Dependencies**: Phase 8 merged to main
**Worktrees Created**: 0/2

| ID | Task | Status | Agent | Worktree | Tested | Linted | Committed | Notes |
|----|-------|---------|----------|----------|----------|------------|--------|
| 9.62 | Update README.md (tech stack, setup, API docs, mobile access) | 🔴 | - | - | - | - | |
| 9.63 | Create API documentation (OpenAPI tags, CSV format, examples) | 🔴 | - | - | - | - | |
| 9.64 | Update AGENTS.md & CONTRIBUTING.md (FastAPI, HTMX, Tailwind) | 🔴 | - | - | - | - | Testing requirements |

---

## Worktree Registry

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
