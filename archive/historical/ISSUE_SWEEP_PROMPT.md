# Issue Sweep: Complete Issue Management System

## Mission

Implement the full issue-management feature set for Comic Pile in a single sequential workflow. This resolves 13 GitHub issues (17 total, but 3 auto-resolve along the way) following a strict dependency order. Each step builds on the last. **Do not skip steps or reorder.**

## Ground Rules

- Branch from `main` as `issue-sweep/complete-issue-management`
- Commit after each step with the format: `Fix #NNN: <description>`
- Run `make lint` and `pytest` after every commit — **do not proceed if either fails**
- Follow all conventions in `AGENTS.md` (async-only DB, no `# type: ignore`, etc.)
- Extract SQLAlchemy model attributes **before** `await db.commit()` (MissingGreenlet rule)
- All new endpoints go under `app/api/issue.py` with the existing `/api/v1` prefix
- All new schemas go in `app/schemas/issue.py`
- All new frontend API methods go in `frontend/src/services/api-issues.ts`
- Write tests for every new endpoint and every bug fix

---

## Step 1: Fix Thread.issues relationship ordering (#261)

**Model:** haiku ✅

**File:** `app/models/thread.py` line 111

**Change:** `order_by="Issue.issue_number"` → `order_by="Issue.position"`

**Why:** The ORM relationship sorts by string (`issue_number`), where "Annual 1998" sorts before "2". Every API query already uses `Issue.position`, but any code touching `thread.issues` directly gets wrong order. This is a one-line fix that removes a landmine before we add any issue-mutation logic.

**Test:** Add a test in `tests/test_issue_model.py` that creates issues with mixed issue_numbers (including an "Annual") and verifies `thread.issues` returns them in position order, not alphabetical.

**Verify:** `make lint && pytest tests/test_issue_model.py -v`

---

## Step 2: Add unique constraint on (thread_id, issue_number) (#263)

**Model:** haiku ✅

**Create Alembic migration:**
```bash
alembic revision --autogenerate -m "add unique constraint on thread_id issue_number"
```

**What to add:** A `UniqueConstraint("thread_id", "issue_number", name="uq_issue_thread_number")` to `Issue.__table_args__` in `app/models/issue.py`.

**Before migrating:** The migration must handle potential existing duplicates. Add a data cleanup step in the migration's `upgrade()` that:
1. Finds duplicate `(thread_id, issue_number)` pairs
2. Keeps the one with the lowest `id`, deletes the rest
3. Then adds the unique constraint

**Test:** Add a test in `tests/test_issue_api.py` that attempts to create a duplicate issue_number in the same thread and asserts it's rejected (either deduplicated or returns an appropriate error).

**Verify:** `alembic upgrade head && make lint && pytest -v`

---

## Step 3: Make position canonical for in-thread ordering (#257)

**Model:** sonnet 🧠 (design decision + complex join query)

This is a **design documentation + code guardrail** step, not a rewrite. The system already uses `Issue.position` for ordering in all API queries. The problem is that dependency edges can silently disagree with position order, and there's no validation.

**Changes:**

1. **Add a validation helper** in `comic_pile/dependencies.py`:
   ```python
   async def validate_position_dependency_consistency(
       thread_id: int, user_id: int, db: AsyncSession
   ) -> list[str]:
       """Return warnings where position order disagrees with dependency order."""
   ```
   This function should:
   - Find all issue-level dependencies where both source and target are in the same thread
   - Check if source.position < target.position (source should come first in reading order)
   - Return human-readable warnings for any disagreements

2. **Add a validation endpoint** in `app/api/issue.py`:
   ```http
   GET /api/v1/threads/{thread_id}/issues:validateOrder
   ```
   Returns `{"warnings": [...]}` — empty list means no conflicts.

3. **Document** in a code comment on the `Dependency` model (`app/models/dependency.py`) that intra-thread issue dependencies are discouraged — position is canonical for in-thread order, dependencies are for cross-thread blocking.

**This auto-resolves #262 and #265** — both describe symptoms of the position/dependency disagreement. The validation endpoint gives users visibility into conflicts, and the documentation establishes position as the source of truth.

**Test:** Create two issues in a thread, add a dependency that disagrees with position order, call the validation endpoint, assert a warning is returned.

**Verify:** `make lint && pytest -v`

---

## Step 4: Add insert-at-position API (#258)

**Model:** sonnet 🧠 (position-shifting with SELECT FOR UPDATE, next_unread recalc)

**Modify** `POST /api/v1/threads/{thread_id}/issues` in `app/api/issue.py`.

**Schema change** in `app/schemas/issue.py` — add optional field to `IssueCreateRange`:
```python
insert_after_issue_id: int | None = Field(
    default=None,
    description="Insert new issues after this issue ID. If null, append to end."
)
```

**Behavior:**
- When `insert_after_issue_id` is `None` (default): current append behavior, no change
- When `insert_after_issue_id` is provided:
  1. Validate the issue exists and belongs to the same thread
  2. Find its position (`insert_position`)
  3. Shift all issues with `position > insert_position` up by `len(new_issues)` using a bulk UPDATE
  4. Assign new issues positions starting at `insert_position + 1`
  5. Update `next_unread_issue_id` if the insertion changes which unread issue comes first

**Row-level locking:** The existing `SELECT FOR UPDATE` on issue rows already prevents concurrent modifications. Keep that pattern.

**Frontend:** Add the `insert_after_issue_id` parameter to `issuesApi.create()` in `frontend/src/services/api-issues.ts` as an optional second object parameter.

**Tests:**
- Insert issues in the middle of an existing sequence, verify positions shift correctly
- Insert with invalid `insert_after_issue_id`, verify 404
- Insert after the last issue (should behave like append)
- Verify `next_unread_issue_id` is updated correctly when inserting before the current next-unread

**Verify:** `make lint && pytest tests/test_issue_api.py -v`

---

## Step 5: Add reorder/move API (#259)

**Model:** sonnet 🧠 (bulk position reassignment, MissingGreenlet traps)

**Add two new endpoints** in `app/api/issue.py`:

### 5a: Move single issue
```http
POST /api/v1/issues/{issue_id}:move
```

**Schema** (add to `app/schemas/issue.py`):
```python
class IssueMoveRequest(BaseModel):
    """Schema for moving an issue to a new position."""
    after_issue_id: int | None = Field(
        ...,
        description="Move after this issue. null = move to position 1 (top)."
    )
```

**Behavior:**
1. Validate issue exists and user owns the thread
2. Remove issue from its current position (shift others down)
3. If `after_issue_id` is null: insert at position 1 (shift everything up)
4. If `after_issue_id` is provided: insert after that issue
5. Recalculate `next_unread_issue_id` (lowest-position unread)
6. Use `SELECT FOR UPDATE` on all issue rows for the thread

### 5b: Bulk reorder
```http
POST /api/v1/threads/{thread_id}/issues:reorder
```

**Schema:**
```python
class IssueReorderRequest(BaseModel):
    """Schema for bulk reordering issues within a thread."""
    issue_ids: list[int] = Field(
        ..., min_length=1,
        description="Ordered list of issue IDs representing the desired order."
    )
```

**Behavior:**
1. Validate all issue IDs belong to this thread and the user owns it
2. Assign positions 1..N based on the list order
3. Recalculate `next_unread_issue_id`

**Frontend:** Add `issuesApi.move(issueId, afterIssueId)` and `issuesApi.reorder(threadId, issueIds)` to `frontend/src/services/api-issues.ts`.

**Tests:**
- Move issue to top, middle, end — verify all positions
- Move with invalid issue_id — verify 404
- Bulk reorder — verify positions match input order
- Bulk reorder with missing/extra IDs — verify 400
- Verify `next_unread_issue_id` is recalculated after move

**Verify:** `make lint && pytest tests/test_issue_api.py -v`

---

## Step 6: Add delete individual issue API (#260)

**Model:** sonnet 🧠 (cascade + position compaction + thread state transitions)

**Add endpoint** in `app/api/issue.py`:
```http
DELETE /api/v1/issues/{issue_id}
```

**Behavior:**
1. Validate issue exists and user owns the thread
2. Record the issue's position before deletion
3. Delete the issue
4. Shift all issues with `position > deleted_position` down by 1
5. Update thread metadata:
   - `total_issues -= 1`
   - Recalculate `issues_remaining` (count unread)
   - Recalculate `next_unread_issue_id` (lowest-position unread, or None)
   - If no issues remain, set `reading_progress = "completed"` and `status = "completed"`
6. Dependencies referencing this issue cascade-delete via `ondelete="CASCADE"` on the FK
7. Log an event of type `"issue_deleted"`

**Frontend:** Add `issuesApi.delete(issueId)` to `frontend/src/services/api-issues.ts`.

**Tests:**
- Delete middle issue — verify position shift
- Delete last issue — verify no shift needed
- Delete the `next_unread_issue_id` issue — verify it advances to next unread
- Delete all issues — verify thread becomes completed
- Delete non-existent issue — verify 404

**Verify:** `make lint && pytest tests/test_issue_api.py -v`

---

## Step 7: Build frontend issue reordering UI (#266)

**Model:** sonnet 🧠 (React drag-and-drop mirroring existing pattern)

**Modify** `frontend/src/pages/QueuePage.tsx`, specifically the `IssueToggleList` component (line 74+).

**Add drag-and-drop reorder** to the issue pills. Follow the existing thread drag-and-drop pattern in `QueuePage.tsx` (lines 240-370) which uses native HTML5 drag events (`onDragStart`, `onDragOver`, `onDrop`).

**Implementation:**
1. Add `draggable` attribute to each issue button in `IssueToggleList`
2. Add `onDragStart`, `onDragOver`, `onDrop` handlers following the thread reorder pattern
3. On drop: call `issuesApi.move(draggedIssueId, targetIssueId)` or `issuesApi.reorder()` with the full new order
4. Optimistically reorder the UI, revert on API error
5. Add a visual drag indicator (follow the existing thread drag styling)

**Also add a delete button** (small ✕) on each issue pill that calls `issuesApi.delete(issueId)` with a confirmation prompt.

**Tests:** Add a vitest unit test in `frontend/src/unit/` for the reorder state logic. Add a Playwright E2E test if feasible, otherwise test the delete confirmation flow.

**Verify:** `cd frontend && npm test && npm run build`

---

## Step 8: Retire compensating scripts (#264)

**Model:** haiku ✅

**Now that the APIs exist**, the following scripts in `scripts/` are no longer needed for their original purpose:

| Script | Replaced By |
|--------|------------|
| `add_xmen_annuals.py` | `POST /api/v1/threads/{id}/issues` with `insert_after_issue_id` |
| `fix_thread_positions.py` | `POST /api/v1/threads/{id}/issues:reorder` |
| `audit_thread_positions.py` | `GET /api/v1/threads/{id}/issues:validateOrder` |
| `complete_annual_dependencies.py` | `POST /dependencies/` (already exists) |
| `create_xmen_dependencies.py` | `POST /dependencies/` (already exists) |
| `check_xmen_dependencies.py` | `GET /threads/{id}/dependencies` (already exists) |

**Action:** Add a deprecation header comment to each script:
```python
# DEPRECATED: This script is superseded by the issue management API.
# See: POST /api/v1/threads/{id}/issues, POST /api/v1/issues/{id}:move, etc.
# Retained for reference only. Do not use for new operations.
```

Do NOT delete them — they serve as historical reference for the data operations that were performed.

**Verify:** `make lint`

---

## Step 9: Session metadata test coverage (#248)

**Model:** haiku ✅

The session hydration fix is already implemented. `get_active_thread()` and `get_session_with_thread_safe()` both call `_fetch_thread_issue_metadata()` and populate all four issue fields on `ActiveThreadInfo`. Add regression tests.

**Add to `tests/test_session_api.py`:**

1. **Test: session refetch preserves issue metadata**
   - Create a thread with issues, start a session, roll, fetch session via `GET /sessions/current/`
   - Assert `active_thread.next_issue_id` and `active_thread.next_issue_number` are populated
   - Refetch the session — assert they're still present

2. **Test: non-issue-tracked thread has null issue fields**
   - Create a legacy thread (no issues), roll, fetch session
   - Assert `next_issue_id` and `next_issue_number` are null

3. **Test: completed thread has null next_issue**
   - Mark all issues as read, fetch session
   - Assert `next_issue_id` is null

**Verify:** `make lint && pytest tests/test_session_api.py -v`

---

## Step 10: Parallel polish (independent issues)

Each sub-step is independent. Commit separately.

### 10a: Issue pagination improvements (#254)

**Model:** haiku ✅

- Change `IssueToggleList` to use the existing `next_page_token` from `IssueListResponse` for cursor-based infinite scroll instead of hard cap at `page_size: 100`
- Add a "show read" toggle filter that passes `status=unread` vs no filter to `issuesApi.list()`
- Load more on scroll to bottom of the `.max-h-40.overflow-auto` container

**Verify:** `cd frontend && npm test && npm run build`

### 10b: Collection creation success feedback (#246)

**Model:** haiku ✅

- Add a lightweight toast/success-message component (check existing patterns first — the app uses `alert()` and inline errors elsewhere)
- In `frontend/src/components/CollectionDialog.tsx`, after successful create (line 76-78), show a toast: `"Collection '{name}' created"`
- Auto-dismiss after 3 seconds, no extra click required
- No toast on error (existing inline error handling is fine)

**Verify:** `cd frontend && npm test && npm run build`

### 10c: Consolidate toolbar IA (#249)

**Model:** sonnet 🧠

- Audit where collection-management actions live across `RollPage.tsx`, `QueuePage.tsx`, `HistoryPage.tsx`
- Propose the smallest move that reduces fragmentation without breaking existing workflows
- Implement and test, ensuring #246 feedback survives the UI move

**Verify:** `cd frontend && npm test && npm run build`

### 10d: Reading reminders next iteration (#247)

**Model:** sonnet 🧠

- Build on existing `useStaleThreads(7)` hook and `GET /api/threads/stale` endpoint in `RollPage.tsx`
- Add reminder categories: stale (>7 days), blocked (has unresolved dependencies), never-read (no `last_activity_at`)
- Add dismiss/snooze mechanism with localStorage persistence
- Reuse `last_activity_at` from `Thread` model

**Verify:** `cd frontend && npm test && npm run build && make lint && pytest -v`

### 10e: Per-issue dependency view (#267)

**Model:** sonnet 🧠

- Add `GET /api/v1/issues/{issue_id}/dependencies` endpoint returning incoming and outgoing dependency edges for a single issue
- Add a small dependency icon on issue pills in `IssueToggleList` for issues that have dependencies
- Clicking the icon shows the dependency details inline or in a tooltip

**Verify:** `make lint && pytest -v && cd frontend && npm test && npm run build`

---

## Completion Checklist

When all steps are done:

- [ ] `make lint` passes
- [ ] `pytest` passes with ≥96% coverage
- [ ] `cd frontend && npm test` passes
- [ ] `cd frontend && npm run build` succeeds
- [ ] All 17 issues are addressed (13 directly, 3 auto-resolved, 1 deprecated-in-place)
- [ ] Branch is ready for PR

**Issues resolved by this sweep:**
- #257, #258, #259, #260, #261, #262, #263, #264, #265, #266, #267
- #246, #247, #248, #249, #254
- #193 and #220 remain open as ongoing trackers (updated by this work)
