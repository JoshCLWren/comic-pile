# Blocking UX Polish Plan

**Branch:** `feature/thread-blocking-usability-overhaul`  
**Goal:** Make the dependency/blocking feature feel intuitive before merge.  
**Scope:** Frontend-only changes. No backend/API/schema changes.

---

## 1. Replace `alert()` with inline blocked-thread modal

**File:** `frontend/src/pages/QueuePage.tsx`  
**Current behavior:** When you tap "Read Now" on a blocked thread from the action sheet, a native browser `alert()` fires with the blocking reasons.  
**Target behavior:** Show a styled modal (reuse existing `<Modal>`) with:
- Thread title
- Blocking reasons as a list
- "View Dependencies" button → opens DependencyBuilder for that thread
- "Close" button

**Lines to change:** `QueuePage.tsx` ~L533–537 (`handleAction('read')` case)

---

## 2. Show blocked threads on RollPage in a collapsible section

**File:** `frontend/src/pages/RollPage.tsx`  
**Current behavior:** Blocked threads are silently filtered out of `activeThreads` (line 298). They're invisible — no indication anything is missing.  
**Target behavior:** Add a collapsible "Blocked (N)" section below the roll pool, matching the existing "Snoozed (N)" pattern:

```
Roll Pool (d4)
  #1 Animal Man
  #2 Saga
  #3 Showcase '95
  #4 The Shade

▶ Blocked (1)
   🔒 Starman — Read Showcase '95 #4-5 to unblock

▶ Snoozed (2)
   ...
```

**Implementation:**
- Keep `activeThreads` filtered (pool stays accurate to die size)
- Add `blockedThreads` memo: `threads?.filter(t => t.status === 'active' && t.is_blocked)`
- Fetch blocking reasons for each (same pattern as QueuePage's `refreshBlockedState`)
- Render as collapsible section between pool and snoozed, same styling
- Each blocked item shows 🔒 + title + first blocking reason as subtitle

---

## 3. Default dependency mode to `thread`

**File:** `frontend/src/components/DependencyBuilder.tsx`  
**Current behavior:** `getDefaultDependencyMode()` returns `'issue'` if the thread has a `next_unread_issue_id`, which is most migrated threads. Issue-level is the power-user mode; thread-level is what you want 90% of the time.  
**Target behavior:** Always default to `'thread'`.

**Change:** Line 11 — `return 'thread'` (one-line fix)

---

## 4. Relabel DependencyBuilder with reader-friendly language

**File:** `frontend/src/components/DependencyBuilder.tsx`  
**Changes (copy only, no logic):**

| Current label | New label |
|---|---|
| "Dependency type" | "Block type" |
| "Search prerequisite thread" | "Read first" |
| "Prerequisite issue" | "Read this issue first" |
| "Target issue" | "Before this issue" |
| "This thread is blocked by" | "Must read first" |
| "This thread blocks" | "Unlocks after reading" |
| `Block with thread: ${name}` (button) | `Must read ${name} first` |
| `Block issue #X with: ${name} #Y` (button) | `Read ${name} #Y before #X` |
| "No prerequisites yet." | "No reading prerequisites." |
| "No dependent threads yet." | "Doesn't unlock anything yet." |
| "Adding dependency…" | "Saving…" |
| "Uses each thread's next unread issue." | "Blocks only when the target issue becomes next unread." |

---

## 5. Show "N threads blocked" summary on RollPage

**File:** `frontend/src/pages/RollPage.tsx`  
**Current behavior:** No indication that threads are missing from the pool.  
**Target behavior:** Absorbed into item #2 — the collapsible "Blocked (N)" section serves this purpose. No separate indicator needed.

**Status:** Merged into item #2.

---

## Implementation Order

1. **Item 3** — one-line default change (2 min)
2. **Item 4** — copy pass, no logic (10 min)
3. **Item 1** — replace alert with modal (15 min)
4. **Item 2** — blocked section on RollPage (30 min)

**Total estimate:** ~1 hour

## Verification

- `cd frontend && npm test` — unit tests pass
- `cd frontend && npm run build` — no build errors
- Manual check: create a dependency, confirm blocked thread shows 🔒 on queue, shows in RollPage blocked section, "Read Now" shows styled modal not alert()
- `make lint` — no regressions
