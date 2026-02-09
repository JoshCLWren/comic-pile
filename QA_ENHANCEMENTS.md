# Comic Pile QA Issues & Enhancement Plan

**Created**: 2026-02-07
**Status**: Ready for Implementation
**Total PRs**: 13 (11 code, 2 cleanup)

---

## Quick Summary

This document captures all QA issues identified during production testing, organized into small, focused PRs for incremental implementation. Each PR is designed to be completable in 1-3 hours.

### Priority Breakdown
- **Quick Wins** (4 PRs, ~2.5 hours): Git cleanup, snooze bug, queue positions, markdown cleanup
- **High Impact** (3 PRs, ~4-6 hours): Session UI cleanup, history copy, mobile dice selector
- **Complex** (3 PRs, ~6-9 hours): Snoozed comics with modifiers, session flow, stale reminder
- **Backend** (2 PRs, ~3-4 hours): Remove backup code, analytics audit/fix
- **Polish** (1 PR, ~2-3 hours): Quick actions on comics

### NOT Included (Needs Discovery/Planning)
- **Onboarding Wizard** - See "Planning Tasks" section below

---

## Part 1: Git Worktree Cleanup (PR 0)

### Status
✅ **Ready to implement** - All decisions made

### Changes

> **⚠️ WARNING:** These commands operate outside the repository and will permanently delete data. 
> - Verify you're in the correct directory: `pwd` should show `/path/to/comic-pile`
> - List what will be deleted first: `ls ../comic-pile-*`
> - Check worktree list: `git worktree list`
> - Ensure backups exist if needed

**Remove 3 Git Worktrees:**
```bash
git worktree remove ../comic-pile-phase4  # Abandoned auth work (394MB)
git worktree remove ../comic-pile-phase5  # Abandoned auth work (7.4MB)
# Keep: comic-pile-cleanup (still active work)
```

**Remove 24 Stale Directories:**
```bash
# Spike directories
rm -rf ../comic-pile-spike-00{1,2,3,4}

# Task directories (all abandoned)
rm -rf ../comic-pile-task-api-004
rm -rf ../comic-pile-task-critical-00{1,2,6}
rm -rf ../comic-pile-task-deploy-00{1,2,3}
rm -rf ../comic-pile-TASK-FEAT-007
rm -rf ../comic-pile-task-lint-001
rm -rf ../comic-pile-task-rollback-001
rm -rf ../comic-pile-task-security-001
rm -rf ../comic-pile-task-test-001
rm -rf ../comic-pile-task-workflow-001

# UX directories
rm -rf ../comic-pile-ux-00{5,7,204}

# Artifacts
rm -f ../comic_pile.db
```

**Impact:**
- Space savings: ~574MB
- Cleaner directory structure
- No impact on active development

**Estimated Time:** 10 minutes

---

## Part 2: Frontend UX Fixes (PRs 1-9)

### PR 1: Fix Snooze Re-render Bug ✅

**Issue:** API succeeds when unsnoozing, but UI doesn't update to show the thread is no longer snoozed.

**Files:**
- `frontend/src/pages/RollPage.jsx` - Add refetch after unsnooze
- `frontend/src/pages/RatePage.jsx` - Add refetch after snooze

**Root Cause:** Pages don't refetch session data after snooze/unsnooze mutations complete.

**Solution:**

The codebase uses custom hooks with useState/useEffect that return a `refetch` function. After mutations, pages must manually call `refetch()` to update data.

**RollPage.jsx (around line 300+):**
```jsx
// Find the unsnooze button onClick
// Before:
onClick={() => unsnoozeMutation.mutate(thread.id)}

// After:
onClick={() => unsnoozeMutation.mutate(thread.id).then(() => refetchSession()).catch(() => {
  // Optional: error handling
})}
```

**RatePage.jsx (around line 160+):**
```jsx
// Find the snooze handler
// Before:
await snoozeMutation.mutate();
navigate('/');

// After:
await snoozeMutation.mutate();
refetchSession();
navigate('/');
```

**Pattern Note:**
- `useSession()` returns `{ data, isPending, isError, error, refetch }`
- All data hooks return a `refetch` function for manual updates
- Call `refetch()` in `.then()` after mutations to refresh stale data
- See QueuePage.jsx lines 50, 57, 63 for examples of this pattern

**Estimated:** 30 minutes

---

### PR 2: Add Queue Position Numbers ✅

**Issue:** Queue view doesn't show which position each thread is in.

**Files:**
- `frontend/src/pages/QueuePage.jsx:240-330`

**Solution:**
```jsx
<div className="flex items-start gap-3">
  <span className="text-2xl font-black text-teal-500/30">
    #{thread.queue_position}
  </span>
  <div className="flex-1 min-w-0">
    <h3 className="text-lg font-bold text-white truncate">
      {thread.title}
    </h3>
    <p className="text-sm text-slate-400">{thread.format}</p>
  </div>
</div>
```

**Estimated:** 30 minutes

---

### PR 3: Remove Session UI Indicators ✅

**Issue:** Session terminology visible to users, but sessions should be opaque/background.

**User Feedback:** "I want sessions to be a background thing for timing when session ends so that somebody who is reading for a long time can come back and not have to restart their ladder progression."

**Files:**
- `frontend/src/pages/RatePage.jsx:138-143` - Remove "Session Safe" indicator
- `frontend/src/pages/RatePage.jsx:437-444` - Remove "Finish Session" button
- `frontend/src/pages/RollPage.jsx` - Remove "Active Session" text

**Remove from UI:**
- "Session Safe" shield icon
- "Active Session" status text
- "Finish Session" button (never used)

**Keep in Backend:**
- All 6-hour timeout logic (works perfectly for user's morning/night reading pattern)
- Session persistence for ladder progression
- All database schema and API endpoints

**Add TODO Comment:**
```python
# comic_pile/session.py
def _session_gap_hours() -> int:
    # TODO: Make session_gap_hours configurable in future
    # Currently hardcoded to 6 hours based on user's reading pattern
    # (early morning vs late night sessions, rarely < 6 hours apart)
    return get_session_settings().session_gap_hours
```

**Estimated:** 1-2 hours

---

### PR 4: Improve History View Copy ✅

**Issue:** History view language is confusing (even to the author who wrote the app).

**Files:**
- `frontend/src/pages/HistoryPage.jsx:60-106`

**Current → Improved:**
- "Ladder: d4, d6, d8" → "Dice progression: d4 → d6 → d8"
- "Roll: 3" → "Rolled: 3 of d6"
- Add session duration: "Duration: 2h 15m"
- Add comics read: "Comics read: 3"
- "Details" button → "View Full Session"
- Add page subtitle: "Your reading session history"

**Example Output:**
```
Jan 25, 2:30 PM
Dice progression: d4 → d6 → d8
Batman: The Dark Knight Returns
Rolled: 3 of d6
Duration: 2h 15m · Comics read: 3
[View Full Session]
```

**Estimated:** 1 hour

---

### PR 5: Mobile Dice Selector Overhaul ✅

**Issue:** Dice selector vertically stacked on mobile, wasting vertical space. User uses app primarily on mobile (iPhone).

**Files:**
- `frontend/src/pages/RollPage.jsx:183-210`

**Current:** All dice buttons shown (d4, d6, d8, d10, d12, d20, Auto)
**Problem:** Takes too much vertical space on mobile

**Solution:**

**Mobile (<768px):**
- Show single button with current die: "d6"
- Tap button → opens modal/bottom sheet with all dice options
- Use Modal component (already imported)

**Desktop (≥768px):**
- Keep current horizontal layout
- All dice visible

**Implementation:**
```jsx
<div className="die-selector">
  {/* Desktop: All dice visible */}
  <div className="hidden md:flex gap-2">
    {DICE_LADDER.map((die) => (
      <button key={die} onClick={() => handleSetDie(die)}>
        d{die}
      </button>
    ))}
    <button onClick={handleClearManualDie}>Auto</button>
  </div>

  {/* Mobile: Current die only */}
  <div className="md:hidden">
    <button onClick={() => setIsDieModalOpen(true)}>
      d{currentDie}
    </button>
  </div>
</div>

{/* Modal for mobile */}
<Modal
  isOpen={isDieModalOpen}
  onClose={() => setIsDieModalOpen(false)}
  title="Select Die"
>
  <div className="grid grid-cols-3 gap-2">
    {DICE_LADDER.map((die) => (
      <button
        key={die}
        onClick={() => {
          handleSetDie(die)
          setIsDieModalOpen(false)
        }}
        className={die === currentDie ? 'active' : ''}
      >
        d{die}
      </button>
    ))}
    <button
      onClick={() => {
        handleClearManualDie()
        setIsDieModalOpen(false)
      }}
    >
      Auto
    </button>
  </div>
</Modal>
```

**Estimated:** 2-3 hours

---

### PR 6: Snoozed Comics in Dice Pool (D&D Modifiers) ⚠️ COMPLEX

**Issue:** When comics are snoozed, the dice pool should exclude them AND display the offset like D&D stat modifiers.

**User Requirement:**
- 8 total comics, positions 1-2 are snoozed
- Rolling d6 should select from comics 3-8 (eligible pool only)
- Display: "Roll: 3 +2" (die result + snoozed offset)
- Modifier visible at all times if snoozes exist
- "It should be in their face and it should go away and change based on snoozes"

**Files:**
- `app/api/roll.py` - Calculate and return offset
- `app/schemas/session.py` - Add offset field to response
- `frontend/src/pages/RollPage.jsx` - Display modifier

### User Clarifications:

**1. Modifier Visibility:**
> "at all times if there's a snooze. it should be in their face and it should go away and change based on snoozes."

- Modifier always visible when snoozes exist
- Shows during AND after roll
- Updates dynamically when snoozes change
- Goes away when no snoozes

**2. Snoozed Comics in Pool:**
> "i think a snoozed badge or emoji would be more fun than greying them out."

- Show snoozed comics in pool with badge/emoji
- Use 😴 or "Snoozed" badge
- Visual indicator, not greyed out

**3. Dice Selector Label:**
> "d6 is fine for now."

- Keep current "d6" label
- Don't show "d6 (6 comics)"

### Backend Changes:

**app/api/roll.py:**
```python
# In roll endpoint
snoozed_ids = current_session.snoozed_thread_ids or []
snoozed_count = len(snoozed_ids)

# Get eligible pool (excludes snoozed)
threads = await get_roll_pool(user_id, db, snoozed_ids)

# Roll selects from eligible pool only
pool_size = len(threads)
die_size = min(current_die, pool_size)  # Don't roll larger than pool

# Result is index into eligible pool (0-based)
selected_index = random.randint(0, die_size - 1)
selected_thread = threads[selected_index]

# Calculate offset for display
offset = snoozed_count

return {
    "thread_id": selected_thread.id,
    "result": selected_index + 1,  # 1-based for display
    "offset": offset,
    "snoozed_count": snoozed_count,
    # ... other fields
}
```

**app/schemas/session.py:**
```python
class RollResponse(BaseModel):
    thread_id: int
    result: int  # 1-based result from die
    offset: int  # Number of snoozed comics (modifier)
    snoozed_count: int  # For display
```

### Frontend Display:

**Roll Result Display:**
```jsx
{/* After roll completes */}
<div className="roll-result-container">
  <div className="roll-value">
    {rolledValue}
    {snoozedCount > 0 && (
      <span className="modifier text-teal-400">
        +{snoozedCount}
      </span>
    )}
  </div>
  {snoozedCount > 0 && (
    <p className="modifier-explanation text-[10px] text-slate-500">
      {snoozedCount} snoozed comic{snoozedCount > 1 ? 's' : ''} offset
    </p>
  )}
</div>
```

**Dice Pool Display:**
```jsx
{/* In roll pool list */}
<div className="pool-thread flex items-center gap-3 px-4 py-2">
  <span className="position text-lg">
    #{index + 1}
  </span>
  <div className="flex-1">
    <p className="title">{thread.title}</p>
  </div>
  {/* Snoozed badge */}
  {isSnoozed && (
    <span className="snoozed-badge">
      😴 Snoozed
    </span>
  )}
</div>
```

**Always-Visible Indicator (in header):**
```jsx
{/* In roll page header, when snoozes exist */}
{session.snoozed_threads?.length > 0 && (
  <div className="snoozed-indicator">
    <span className="modifier-badge">
      +{session.snoozed_threads.length}
    </span>
    <span className="text-[9px] text-slate-500">
      snoozed offset active
    </span>
  </div>
)}
```

### UX Flow Example:
1. User has 8 comics, snoozes positions 1-2
2. Header shows: "+2 snoozed offset active"
3. Dice selector shows: "d6" (6 eligible comics)
4. Roll pool shows:
   - 😴 Snoozed Comic #1
   - 😴 Snoozed Comic #2
   - #3 Eligible Comic
   - #4 Eligible Comic
   - #5 Eligible Comic
   - #6 Eligible Comic
   - #7 Eligible Comic
   - #8 Eligible Comic
5. User rolls, gets: "3"
6. Display shows: "3 +2" (rolls 3, plus 2 offset = Comic #5)
7. Comics #1-2 never selected by dice

**Estimated:** 3-4 hours

---

### PR 7: Make Stale Reminder Tappable ✅

**Issue:** "You haven't touched X in N days" reminder is display-only. User should be able to tap and read that comic now.

**Files:**
- `frontend/src/pages/RollPage.jsx:314-328`
- `app/api/thread.py` (may need new endpoint)

**Current:** Display banner with no interaction
**Desired:** Tap banner → navigate to rate page with that thread as pending

**Implementation:**

**Frontend:**
```jsx
<div
  onClick={handleReadStale}
  className="px-4 pb-4 cursor-pointer hover:bg-amber-500/10 transition-colors"
  role="button"
  tabIndex={0}
  onKeyDown={(e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      handleReadStale()
    }
  }}
>
  <div className="px-4 py-3 bg-amber-500/5 border border-amber-500/10 rounded-xl">
    {/* ... existing reminder content ... */}
    <p className="text-[9px] text-amber-300/70 text-center">
      Tap to read now
    </p>
  </div>
</div>

// Handler:
async function handleReadStale() {
  try {
    await api.setPendingThread(staleThread.id)
    navigate('/rate')
  } catch (error) {
    console.error('Failed to set pending thread:', error)
  }
}
```

**Backend (if needed):**
```python
# app/api/thread.py
@router.post("/{thread_id}/set-pending")
async def set_pending_thread(
    thread_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set a thread as pending for rating (skip roll)."""
    thread = await db.get(Thread, thread_id)

    if not thread or thread.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Thread not found")

    current_session = await get_or_create(current_user.id, db)
    current_session.pending_thread_id = thread_id
    await db.commit()

    return {"status": "pending_set", "thread_id": thread_id}
```

**Estimated:** 1-2 hours

---

### PR 8: Quick Actions on Comics (Roll Pool & Queue)

**Issue:** Selecting a comic from roll pool or queue should give action options, not just select it.

**Files:**
- `frontend/src/pages/RollPage.jsx` - Roll pool interactions
- `frontend/src/pages/QueuePage.jsx` - Queue interactions

**Desired Actions:**
- "Read Now" (same as rolling, navigate to rate)
- "Move to Front"
- "Move to Back"
- "Snooze" / "Unsnooze"
- "Edit Thread"

**Implementation:**

**Use Modal for Action Sheet:**
```jsx
const [selectedThread, setSelectedThread] = useState(null)
const [isActionSheetOpen, setIsActionSheetOpen] = useState(false)

function handleThreadClick(thread) {
  setSelectedThread(thread)
  setIsActionSheetOpen(true)
}

function handleAction(action) {
  setIsActionSheetOpen(false)

  switch (action) {
    case 'read':
      // Set as pending and navigate to rate
      api.setPendingThread(selectedThread.id).then(() => {
        navigate('/rate')
      })
      break
    case 'move-front':
      queueApi.moveToFront(selectedThread.id).then(() => {
        refetchThreads()  // Refresh queue after move
      })
      break
    case 'move-back':
      queueApi.moveToBack(selectedThread.id).then(() => {
        refetchThreads()  // Refresh queue after move
      })
      break
    case 'snooze':
      if (selectedThread.is_snoozed) {
        snoozeApi.unsnooze(selectedThread.id).then(() => {
          refetchSession()  // Refresh session to update snoozed list
          refetchThreads()  // Refresh queue to show updated status
        })
      } else {
        snoozeApi.snooze().then(() => {
          refetchSession()  // Refresh session to update snoozed list
          refetchThreads()  // Refresh queue to show updated status
        })
      }
      break
    case 'edit':
      navigate(`/queue/${selectedThread.id}/edit`)
      break
  }
}
```

**Action Sheet UI:**
```jsx
<Modal
  isOpen={isActionSheetOpen}
  onClose={() => setIsActionSheetOpen(false)}
  title={selectedThread?.title}
>
  <div className="space-y-2">
    <button onClick={() => handleAction('read')}>
      📖 Read Now
    </button>
    <button onClick={() => handleAction('move-front')}>
      ⬆️ Move to Front
    </button>
    <button onClick={() => handleAction('move-back')}>
      ⬇️ Move to Back
    </button>
    <button onClick={() => handleAction('snooze')}>
      {selectedThread?.is_snoozed ? '🔔 Unsnooze' : '😴 Snooze'}
    </button>
    <button onClick={() => handleAction('edit')}>
      ✏️ Edit Thread
    </button>
  </div>
</Modal>
```

**Apply to Both Pages:**
- Roll pool: Wrap thread cards in clickable div
- Queue: Same action sheet for consistency

**Estimated:** 2-3 hours

---

### PR 9: Fix Session Flow After Rating

**Issue:** After rating, if session has pending thread, should stay on rate page. Currently always goes to roll page.

**Files:**
- `frontend/src/pages/RatePage.jsx:102-110`
- `app/api/rate.py` - Ensure pending_thread_id is set correctly

**Current Behavior:**
1. Roll → navigate to rate
2. Rate comic → navigate to roll (always)
3. User has to roll again even if pending thread exists

**Desired Behavior:**
1. Roll → navigate to rate
2. Rate comic → check session state
3. If pending_thread_id exists → stay on rate with next thread
4. If no pending_thread_id → go to roll page

**Implementation:**

**Frontend:**
```javascript
// In RatePage.jsx
// Get refetch function from useSession hook
const { data: session, refetch: refetchSession } = useSession()

async function handleRatingSubmit(ratingData) {
  try {
    await rateApi.rate(ratingData)

    // Refetch session to check for pending thread
    const updatedSession = await sessionApi.getCurrent()

    if (updatedSession.pending_thread_id) {
      // Stay on rate page, it will load new pending thread
      refetchSession()
    } else {
      // No pending thread, go back to roll
      navigate('/')
    }
  } catch (error) {
    setErrorMessage(error.response?.data?.detail || 'Failed to save rating')
  }
}
```

**Pattern Note:**
- Use `sessionApi.getCurrent()` to fetch updated session data
- Call `refetchSession()` to update the hook's state
- Don't navigate away if `pending_thread_id` exists
- The `useSession` hook will auto-load the new pending thread on next render

**Backend Verification:**
- Ensure rate endpoint clears pending_thread_id after rating
- Ensure session returns updated pending_thread_id if set

**Estimated:** 2 hours

---

## Part 3: Backend Fixes (PRs 10-11)

### PR 10: Remove SQLite Backup Code

**Issue:** Backup code errors in production. It's for SQLite, but app now uses PostgreSQL. Dead code that needs removal.

**User Feedback:** "I need to get rid of the database backup code that errors out in prod because it's for sqlite or something. It's dead code and needs to go away."

**Files:**
- `app/main.py:500-566` - Startup backup trigger
- `scripts/backup_database.py` - Entire file (unused)
- `app/config.py:197-252` - BackupSettings class
- `.env.example` - AUTO_BACKUP_ENABLED variable

**What to Remove:**

**app/main.py:**
```python
# Remove this entire section (lines 500-566):
@app.on_event("startup")
async def startup_event():
    # ... existing DB init ...

    # REMOVE THIS PART:
    if app_settings.backup.enabled and db_success:
        logger.info("Running automatic database backup...")
        # subprocess call to backup_database.py
```

**scripts/backup_database.py:**
- Delete entire file (unused, designed for SQLite)

**app/config.py:**
```python
# Remove BackupSettings class (lines 197-252):
class BackupSettings(BaseSettings):
    # ... remove all backup config ...

# Remove from AppSettings:
class AppSettings(BaseSettings):
    # ... keep other settings ...
    # REMOVE: backup: BackupSettings = Field(default_factory=BackupSettings)
```

**.env.example:**
```bash
# Remove this line:
# AUTO_BACKUP_ENABLED=true
```

**What to Keep:**
- `scripts/backup_postgres.sh` - Manual pg_dump backup (still useful)

**Estimated:** 1 hour

---

### PR 11: Analytics Audit & Data Fix

**Issue:** Analytics showing 77.2 hours average session duration when sessions should be ~6 hours max.

**User Feedback:** "I think we need to make sure that the analytics are measuring info correctly before we decide."

**Files:**
- `app/api/analytics.py:67-81`

### Phase 1: Audit Data (First)

**Create Audit Script:** `scripts/audit_session_durations.py`
```python
"""Audit session duration data to identify outliers."""

import asyncio
from sqlalchemy import select, func
from app.models import Session as SessionModel
from app.database import get_db

async def audit_sessions():
    async for db in get_db():
        # Check session durations
        result = await db.execute(
            select(
                SessionModel.id,
                SessionModel.started_at,
                SessionModel.ended_at,
                (func.extract("epoch", SessionModel.ended_at - SessionModel.started_at) / 3600).label("hours")
            )
            .where(SessionModel.ended_at.isnot(None))
            .order_by("hours DESC")
            .limit(20)
        )

        print("\n=== TOP 20 LONGEST SESSIONS ===\n")
        for session_id, started, ended, hours in result:
            print(f"Session {session_id}: {hours:.1f} hours ({started} → {ended})")

        # Count by duration buckets
        buckets = await db.execute(
            select(
                case(
                    (func.extract("epoch", SessionModel.ended_at - SessionModel.started_at) / 3600 < 1, "< 1 hour"),
                    (func.extract("epoch", SessionModel.ended_at - SessionModel.started_at) / 3600 < 6, "1-6 hours"),
                    (func.extract("epoch", SessionModel.ended_at - SessionModel.started_at) / 3600 < 12, "6-12 hours"),
                    else_="> 12 hours"
                ).label("bucket"),
                func.count()
            )
            .where(SessionModel.ended_at.isnot(None))
            .group_by("bucket")
        )

        print("\n=== SESSION DURATION BUCKETS ===\n")
        for bucket, count in buckets:
            print(f"{bucket}: {count} sessions")

        break
```

**Run Audit:**
```bash
python scripts/audit_session_durations.py
```

### Phase 2: Fix Based on Audit Results

**Likely Issues:**
1. Sessions from SQLite → PostgreSQL migration with bad timestamps
2. Sessions never properly closed (left open for days)
3. Test data from development

**Possible Fixes (choose based on audit):**

**Option A: Filter Outliers**
```python
# Exclude sessions > 12 hours (clearly wrong data)
avg_duration_result = await db.execute(
    select(
        func.avg(
            func.extract("epoch", SessionModel.ended_at - SessionModel.started_at) / 3600
        )
    ).where(
        SessionModel.user_id == current_user.id,
        SessionModel.ended_at.isnot(None),
        SessionModel.started_at > datetime.now(UTC) - timedelta(days=90),  # Recent only
        func.extract("epoch", SessionModel.ended_at - SessionModel.started_at) / 3600 < 12  # Exclude outliers
    )
).scalar()
```

**Option B: Data Migration (if really bad)**
- Create script to fix or delete obviously bad sessions
- Example: sessions where (ended_at - started_at) > 24 hours

**Option C: Add Date Filter**
```python
# Count sessions from last 90 days for more accurate average
ninety_days_ago = datetime.now(UTC) - timedelta(days=90)

avg_duration_result = await db.execute(
    select(
        func.avg(...)
    ).where(
        SessionModel.user_id == current_user.id,
        SessionModel.ended_at.isnot(None),
        SessionModel.started_at >= ninety_days_ago
    )
).scalar()
```

**Update Label:**
```python
"average_session_hours": avg_session_hours,
"average_session_label": f"Last 90 days"  # Add context
```

**Estimated:** 2-3 hours (1 hour audit + 1-2 hours fix)

---

## Part 4: Documentation Cleanup (PR 12)

### PR 12: Markdown File Cleanup

**Issue:** Many outdated markdown files in root directory need cleanup.

**Files to Delete:**
- `FIX_TRACKING.md` - CodeRabbit fix tracking (all 77 issues completed)
- `d10_woes.md` - D10 geometry investigation (resolved Jan 2026)
- `THREAD_REPOSITIONING_FIX_PLAN.md` - Completed fix session log
- `PLANNING.md` - Check if current, likely outdated
- `session-ses_*.md` - Temporary chat logs (5+ files)
- `TASKS_DOCKER_BROWSER_TESTS.md` - Completed task tracking
- `TASKS_DOCKER_BROWSER_TESTS_SUMMARY.md` - Completed summary
- `E2E_FIX_PROGRESS.md` - Historical
- `E2E_TEST_SUMMARY.md` - Historical
- `E2E_FIXES_REPORT.md` - Historical
- `PLAYWRIGHT_OPTIMIZATION_PLAN.md` - Historical
- `CI_FIXES_SUMMARY.md` - Historical
- `ASYNC_REFACTOR_PLAN.md` - Historical (async refactor completed)
- `ASYNC_REFACTOR_PR_DESCRIPTION.md` - Historical
- `CI_FAILURES_ANALYSIS.md` - Historical
- `CODERABBIT_AUDIT.md` - Historical CodeRabbit review
- `ASYNC_REFACTOR_SUMMARY.md` - Historical
- `TEST_SLIDER_QUEUE.md` - Historical
- `BRANCH_QA_TEST_PLAN.md` - Historical
- `SUB_AGENT_PROTOCOL.md` - Internal AI agent docs (move to docs/ or delete)
- `AGENT_GUIDELINES.md` - Merge into AGENTS.md

**Files to Keep:**
- `README.md` - Main project readme
- `AGENTS.md` - Development guidelines (merge AGENT_GUIDELINES.md into this)
- `prd.md` - Product requirements
- `SECURITY.md` - Security policy
- `CONTRIBUTING.md` - Contribution guide
- `ROLLBACK.md` - Rollback procedures
- `TECH_DEBT.md` - Technical debt tracking (review and update if needed)
- `LOCAL_TESTING.md` - Local testing guide (actually useful)
- `frontend/README.md` - Frontend docs
- `tests_e2e/README.md` - E2E test docs
- `frontend/src/test/README.md` - Test docs
- All files in `docs/` directory

**Actions:**
1. Review each file before deleting
2. Move any useful content to appropriate docs
3. Delete outdated files
4. Update AGENTS.md if merging AGENT_GUIDELINES.md

**Estimated:** 30 minutes

---

## Part 5: Planning Tasks (No Code Yet)

### Task: Onboarding Wizard for Logged-Out Users

**Status:** 🚧 **Needs Discovery & Planning** - NOT ready for implementation

**Overview:**
Create an onboarding/tutorial experience for new users who haven't created an account yet. This should be a guided walkthrough explaining how to use the app.

**User Feedback:** "actually tapping any comic in the roll pool or queue should give you the option of reading/rating like rolling would. another idea I've had is for logged out users to enter a demo mode where it explains and walks through the user setting up their threads and explaining how to use the app like an onboarding tutorial/wizard."

### Phase 1: Discovery & Research (TODO)

**Questions to Answer:**
1. **Target Audience:** Who is this for?
   - Complete comics beginners?
   - People familiar with comics but new to queue/dice systems?
   - Both?

2. **Format:** What type of onboarding?
   - Interactive walkthrough (click-through tutorial)
   - Video tutorial
   - Interactive demo mode (sample data, guided actions)
   - Documentation/FAQ page
   - Combination?

3. **Scope:** What needs explaining?
   - Core concept: Random selection + queue management
   - Adding threads (comics) to queue
   - Rolling the dice
   - Rating reading experience
   - Queue movement (good ratings → front, bad → back)
   - Dice ladder progression
   - Sessions (if still opaque to users)
   - Snoozing comics
   - History/analytics

4. **Entry Point:** When does onboarding trigger?
   - First visit to site (logged out)
   - After creating account?
   - Accessible from help menu anytime?

5. **Deliverables:** What will we create?
   - Mockups/wireframes
   - User flow diagrams
   - Content copy (what text explains each concept)
   - Technical specification
   - Implementation plan broken into PRs

### Phase 2: Planning (TODO)

**Using AI Assistance:**
User will work with AI to help with:
- Content writing (clear explanations)
- UX design (user flow, wireframes)
- Technical architecture
- Breakdown into implementable tasks

**Deliverables:**
1. **UX Design Document**
   - User flows for each onboarding step
   - Wireframes or mockups
   - Interaction design

2. **Content Document**
   - Copy for each explanation
   - Terminology definitions
   - Examples

3. **Technical Specification**
   - Component structure
   - State management (onboarding progress)
   - Storage (localStorage for progress?)
   - Demo data generation

4. **Implementation Plan**
   - Breakdown into PRs (likely 5-10 PRs)
   - Estimated effort for each
   - Dependencies between PRs

### Phase 3: Implementation (FUTURE)

**Likely Components:**
- Onboarding flow component
- Demo mode setup (sample threads, sessions)
- Tooltip/guide component
- Progress tracking
- Skip/on-demand replay options

**Estimated Effort:** Unknown until planning complete (likely 20-40 hours)

**Status:** NOT ready for implementation. Complete discovery and planning phases first.

---

## Part 6: Execution Order

### Week 1: Quick Wins & Git Cleanup

**Day 1 (3 hours):**
- PR 0: Git cleanup (10 min)
- PR 1: Snooze re-render bug (30 min)
- PR 2: Queue position numbers (30 min)
- PR 12: Markdown cleanup (30 min)
- PR 10: Remove backup code (1 hour)

**Day 2 (3-4 hours):**
- PR 3: Remove session UI (1-2 hours)
- PR 4: History copy improvements (1 hour)

### Week 2: High Impact UX

**Day 3 (2-3 hours):**
- PR 5: Mobile dice selector (2-3 hours)

**Day 4-5 (3-4 hours):**
- PR 6: Snoozed comics with modifiers (3-4 hours) ⚠️ Complex

**Day 6 (1-2 hours):**
- PR 7: Stale reminder tappable (1-2 hours)

### Week 3: Polish & Backend

**Day 7 (2 hours):**
- PR 9: Session flow fix (2 hours)

**Day 8 (2-3 hours):**
- PR 8: Quick actions on comics (2-3 hours)

**Day 9-10 (2-3 hours):**
- PR 11: Analytics audit + fix (2-3 hours)

### Total Estimated Time: ~25-30 hours across 3 weeks

---

## Part 7: PR Checklist Template

For each PR, ensure:

**Before Implementation:**
- [ ] Issue understood and reproducible
- [ ] Files to modify identified
- [ ] Solution approach documented
- [ ] Edge cases considered
- [ ] Tests planned (if applicable)

**During Implementation:**
- [ ] Code follows AGENTS.md guidelines
- [ ] Type annotations added (no `Any`)
- [ ] Docstrings updated (Google style)
- [ ] Error handling added
- [ ] Linting passes: `ruff check`, `ty check`
- [ ] Tests pass: `pytest` (backend), `npm test` (frontend)
- [ ] Manual testing completed

**Before Commit:**
- [ ] Changes tested locally
- [ ] No hardcoded secrets
- [ ] Database migrations included (if needed)
- [ ] Documentation updated
- [ ] Commit message follows conventions

**After Merge:**
- [ ] Deploy to production
- [ ] Monitor for issues
- [ ] Update this document (mark PR complete)

---

## Part 8: Progress Tracking

### Completed PRs
- ✅ PR #0: Git Worktree Cleanup (completed 2026-02-09)
- ✅ PR #1: Fix Snooze Re-render Bug (merged PR #172)
- ✅ PR #2: Add Queue Position Numbers (merged PR #166)
- ✅ PR #3: Remove Session UI Indicators (merged 2026-02-08)
- ✅ PR #4: Improve History View Copy (merged 2026-02-08)
- ✅ PR #5: Mobile Dice Selector Overhaul (merged 2026-02-09)
- ✅ PR #6: Snoozed Comics with D&D Modifiers (merged 2026-02-09)
- ✅ PR #7: Make Stale Reminder Tappable (merged 2026-02-09)
- ✅ PR #10: Remove SQLite Backup Code (merged 2026-02-09)
- ✅ PR #12: Markdown File Cleanup (merged PR #167)

### In Progress
- None yet

### Blocked / Awaiting Decisions
- None currently (all questions answered)

### Planning Tasks
- Onboarding Wizard: Awaiting discovery phase

---

## Notes

- **Session 6-hour timeout**: User confirmed this is correct for their use case (morning vs night reading sessions). May be configurable in future, but no code changes needed yet except TODO comment.

- **Analytics 77.2 hours**: Requires data audit before fixing. Likely caused by migration artifacts or sessions never properly closed.

- **Mobile UX Priority**: User uses app primarily on iPhone. Mobile improvements are high priority.

- **PR Size Goal**: Keep each PR completable in 1-3 hours to avoid fatigue and enable incremental progress.

- **Testing**: Manual testing required for most frontend changes. Automated tests where possible.

---

**Last Updated**: 2026-02-09
**Next Review**: After completing PR #5 (Mobile Dice Selector)
