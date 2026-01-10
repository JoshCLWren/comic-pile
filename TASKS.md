# Task Tracking - Dice-Driven Comic Tracker
# FastAPI + React + Tailwind CSS + PostgreSQL

**Last Updated**: 2025-12-31 (Task database system implemented)
**Current Phase**: 10 (PRD Alignment)
**Overall Progress**: 64/76 tasks (84%)

---

## Task Database System

**IMPORTANT**: Task state is now stored in the database instead of this file. All task tracking operations should use the API endpoints below. This file is kept for historical reference and task descriptions.

**For API reference, see docs/TASK_API.md**

**For workers using Task API system, see WORKER_WORKFLOW.md for complete end-to-end workflow.** This document includes:
- Step-by-step workflow from claim to merge
- Task status flow diagram
- Troubleshooting common issues
- Worker responsibilities and limitations

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
