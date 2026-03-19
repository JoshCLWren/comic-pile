# Dependency Blocking Fix Plan

**Planner/Reviewer:** Sonnet 4.6
**Implementer:** claude-opus-4-6
**Date:** 2026-03-18
**Branch:** `fix/dependency-blocking-logic`

---

## Context

Two bugs discovered via prod DB diagnostic for user `Josh_Digital_Comics`:

1. **Blocking logic too aggressive** — `get_blocked_thread_ids` marks a thread blocked if *any* issue
   in it has an unread prerequisite, including issues far in the future. Correct behavior: only block
   when the **next unread issue** has an unread prerequisite.

2. **Dark Knights: Death Metal stale state** — All 7 issues are read (`read_at` populated) but the
   thread has `status='active'`, `issues_remaining=1`, `next_unread_issue_id=10619` (pointing at
   already-read issue #7). Stale denormalized data. Blocks a roll slot for a fully-read series.

---

## Part A — SQL Fix (Pending Josh's Review)

**Run against prod before deploying the code fix.**

```sql
-- Fix Dark Knights: Death Metal stale state (thread id=352, user id=25)
-- Verified: all 7 issues have read_at populated, none have status='unread'
UPDATE threads
SET
    status             = 'completed',
    issues_remaining   = 0,
    next_unread_issue_id = NULL,
    reading_progress   = 'completed'
WHERE id = 352
  AND user_id = 25
  AND (SELECT COUNT(*) FROM issues WHERE thread_id = 352 AND status = 'unread') = 0;
```

**The `AND ... COUNT(*) = 0` guard** ensures the UPDATE only fires if there are truly no unread
issues. If something is wrong with our diagnosis, the WHERE clause will match 0 rows and nothing
changes. Safe to run.

**Run via:**
```bash
railway connect Postgres < scripts/fix_death_metal.sql | tee /tmp/fix_death_metal_result.txt
```

---

## Part B — Code Fix: Blocking Logic

### File: `comic_pile/dependencies.py`

#### `get_blocked_thread_ids` — change the issue-level join

**Current (too aggressive):**
```python
issue_result = await db.execute(
    select(target_thread.c.id)
    .join(target_issue, target_thread.c.id == target_issue.c.thread_id)  # ALL issues
    .join(Dependency, Dependency.target_issue_id == target_issue.c.id)
    .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
    .join(source, source_issue.c.thread_id == source.c.id)
    .where(target_thread.c.user_id == user_id)
    .where(source.c.user_id == user_id)
    .where(source_issue.c.status != "read")
)
```

**Fixed (next-unread-only):**
```python
issue_result = await db.execute(
    select(target_thread.c.id)
    .join(                                                                 # only the next unread issue
        target_issue,
        target_issue.c.id == target_thread.c.next_unread_issue_id,
    )
    .join(Dependency, Dependency.target_issue_id == target_issue.c.id)
    .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
    .join(source, source_issue.c.thread_id == source.c.id)
    .where(target_thread.c.user_id == user_id)
    .where(source.c.user_id == user_id)
    .where(source_issue.c.status != "read")
    .where(target_thread.c.next_unread_issue_id.isnot(None))
)
```

#### `get_blocking_explanations` — same fix

**Current:**
```python
.join(target_issue, target_thread.c.id == target_issue.c.thread_id)
.where(target_thread.c.id == thread_id)
```

**Fixed:**
```python
.join(target_issue, target_issue.c.id == target_thread.c.next_unread_issue_id)
.where(target_thread.c.id == thread_id)
.where(target_thread.c.next_unread_issue_id.isnot(None))
```

---

## Part C — Post-Deploy: Refresh Blocked Flags

After deploying the code fix, the denormalized `is_blocked` flags on all threads need to be
recalculated. Add a one-shot script:

### File: `scripts/refresh_blocked_flags.py`

```python
#!/usr/bin/env python3
"""One-time script: refresh is_blocked flags for all users after blocking logic fix.

Usage:
    COMIC_PILE_USERNAME=Josh_Digital_Comics COMIC_PILE_PASSWORD=... \
        python scripts/refresh_blocked_flags.py
"""

import os, sys, requests

BASE_URL = os.environ.get("COMIC_PILE_API_URL", "https://your-app.up.railway.app")

def main() -> int:
    username = os.environ["COMIC_PILE_USERNAME"]
    password = os.environ["COMIC_PILE_PASSWORD"]

    resp = requests.post(f"{BASE_URL}/auth/login", json={"username": username, "password": password})
    resp.raise_for_status()
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Triggering any dep read/write refreshes blocked status.
    # Easiest: hit GET /v1/dependencies/blocked which calls get_blocked_thread_ids
    # then call the admin refresh endpoint if it exists, otherwise use a dep create/delete cycle.
    blocked = requests.get(f"{BASE_URL}/api/v1/dependencies/blocked", headers=headers)
    blocked.raise_for_status()
    print(f"Blocked thread IDs (post-fix): {blocked.json()}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

> **Note:** `refresh_user_blocked_status` is called automatically by the dep create/delete
> endpoints. But the flags currently in the DB are stale (set under the old logic). The fastest
> prod fix is to run a raw SQL UPDATE after deployment — see below.

### SQL to recalculate `is_blocked` for user 25 post-deploy

This can be run immediately after deployment to fix the stale flags without waiting for a user
action:

```sql
-- Step 1: clear all is_blocked flags for user 25
UPDATE threads SET is_blocked = false WHERE user_id = 25;

-- Step 2: set is_blocked=true only for threads whose NEXT UNREAD issue has an unread prerequisite
UPDATE threads t
SET is_blocked = true
WHERE t.user_id = 25
  AND t.next_unread_issue_id IS NOT NULL
  AND EXISTS (
      SELECT 1
      FROM dependencies d
      JOIN issues src_i ON src_i.id = d.source_issue_id
      JOIN threads src_t ON src_t.id = src_i.thread_id
      WHERE d.target_issue_id = t.next_unread_issue_id
        AND src_t.user_id = 25
        AND src_i.status != 'read'
  );
```

---

## Part D — Tests to Write / Update

File: `tests/test_dependencies.py`

1. **New test: thread with future-issue dep is NOT blocked**
   - Thread A has issues #1–5; dep: `Thread B #1 → Thread A #5`
   - Thread A's next unread = #1
   - Assert: Thread A is NOT in `get_blocked_thread_ids` result
   - Assert: after A reads up to #4 (next unread = #5), Thread A IS blocked

2. **Existing test: thread blocked when NEXT issue has unread prereq** — should still pass

3. **Update `get_blocking_explanations` tests** to reflect same scope change

File: `tests/test_dependency_api.py`

4. **API test: `GET /v1/dependencies/blocked`** — verify thread not blocked until prereq issue
   is the next unread

---

## Reviewer Checklist (Sonnet 4.6)

Before merging:
- [ ] `get_blocked_thread_ids` join changed to `next_unread_issue_id` (not `thread_id`)
- [ ] `get_blocking_explanations` join changed to match
- [ ] `.where(... .isnot(None))` guard added to both
- [ ] New regression test passes (future-issue dep does not block current reads)
- [ ] Existing blocking tests still pass
- [ ] `make pytest` passes at ≥96% coverage
- [ ] `make lint` clean
- [ ] PR description explains the behavioral change and links to this plan doc
- [ ] SQL refresh script for prod `is_blocked` flags included in PR notes

---

## Behavioral Summary (for PR description)

**Before:** A thread was blocked if any of its issues had an unread prerequisite, even if that
issue was 8 issues away from the current read position.

**After:** A thread is blocked only when its *next unread issue* has an unread prerequisite.
The block appears exactly when it becomes relevant — not before.

**Example:** Absolute Batman #5 (next unread) can be read freely. When the reader reaches
#13 (which requires Absolute Evil #1 first), the thread blocks at that point.
