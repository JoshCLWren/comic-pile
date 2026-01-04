# Product Requirements Summary - Comic Pile

This document summarizes the core product requirements and design decisions from the PRD, providing essential context for development decisions.

---

## Core Philosophy

**This app exists to support an existing ritual, not optimize or gamify it.**

Key principles:
- **Chaos is allowed** - The queue reflects what you can read now, not everything you've ever read
- **Ratings and movement encode intent, not notes** - No notes system in the app
- **Dice are sacred** - The dice ladder self-corrects chaos through step-up/step-down
- **Time, not mood, defines sessions** - 6-hour gap defines session boundary, no manual "new session" button
- **The queue reflects what you can read now, not everything you've ever read**

---

## Core Concepts

### Reading Thread

A **thread** represents a mini reading order, equivalent to one row in a spreadsheet.

**Examples:**
- *Hellboy Omnibus Vol 2*
- *Declustered X-Men*
- *Majestic*
- *Conan Saga*

**Threads are atomic units for:**
- Rolling
- Reading
- Rating
- Queue movement

### Queue

- The queue is a **single ordered list**, top to bottom
- Ordering is authoritative
- Rolls always operate on the **top N rows**, where N is the current die size
- Completed threads:
  - Disappear from the queue by default
  - Can be reactivated later
- New or reactivated threads:
  - Always insert at **position 1**
  - No cap, chaos is acceptable

### Dice Ladder

**Allowed dice (ordered):**
```
d4 → d6 → d8 → d10 → d12 → d20
```

**Rules:**
- New session always starts at **d6**
- After each read + rating:
  - Rating ≥ 4.0 → step **down** one die
  - Rating < 4.0 → step **up** one die
- Only **one step per read**
- Bounds:
  - d4 stays d4 on success
  - d20 stays d20 on failure

**Intent:**
- d4 is the reward state
- Larger dice explore deeper into the queue
- The ladder self-corrects chaos

**Manual overrides do not bypass ladder logic** - Ladder still updates after rating regardless of selection method.

---

## Session Model

### Session Boundary

- A session is defined strictly by time
- If **6 hours** pass without activity → new session
- Less than 6 hours → resume session automatically
- No manual "start new session" button

### Session Scope

A session may include:
- Multiple rolls
- Multiple reads
- Multiple ratings
- Dice ladder persists throughout the session

### Pending Reads

If you:
- Roll and select a thread
- But do not read or rate it

Then:
- That thread becomes a **pending read**

On resume (within 6 hours):
- App surfaces: *"You were about to read X"*
- You may:
  - Continue
  - Override

If overridden:
- Original pick is logged as **rolled but skipped**
- No penalties, no movement

---

## Roll Behavior

### Roll Pool Definition

- Rolls always operate on:
  - **The first N active threads**, top to bottom
  - Where N = current die denomination

**Example:**
- d6 → rows 1–6
- d4 → rows 1–4

Completed threads are excluded automatically.

### Manual Override

- Rare but essential
- Used when:
  - Sleepy
  - Traveling
  - One issue left
  - Just feel like it

**Override behavior:**
- Logs override event
- Does not touch skipped thread
- Ladder still updates after rating

---

## Rating Model

### Rating Scale

- Range: **0.5 → 5.0**
- Step: **0.5**
- Ratings are:
  - Primarily local to the read
  - Softly influenced by momentum
  - Accepted as-is, no correction

### Progress Rules

- If you rate it, you read it
- Rating always decrements **issues remaining by 1**

**Caveat (Omnibus Formatting):**
- Sometimes you unintentionally read 2 issues
- Rate screen supports adjusting "issues read" (default 1)

**No notes system exists** - PRD explicitly excludes note-taking from the app.

### Queue Movement

After rating:
- Rating ≥ 4.0 → move thread to **front**
- Rating < 4.0 → move thread to **back**

Movement is immediate and authoritative.

---

## Completion Semantics

- If issues remaining hits **0**:
  - Thread is marked **completed**
  - Removed from roll pool
  - Hidden from queue by default

**Completion does NOT mean:**
- Finished forever

**Reactivation:**
- When new issues are owned
- Thread re-enters queue at **position 1**

---

## Staleness Awareness

- Chaos can starve threads indefinitely
- App tracks:
  - Last read timestamp
  - Last rating timestamp
  - Last review timestamp (imported)

**Behavior:**
- Informational only
- Subtle nudges like:
  - *"Not touched in 47 days"*
- No forced selection
- No dice bias

---

## Time Tracking

- Raw timestamps recorded for:
  - Rolls
  - Reads
  - Ratings
  - Overrides
  - Corrections

**No derived labels:**
- No "night reading"
- No productivity framing

Raw data only.

---

## Reviews & External Data

- You review everything on **League of Comic Geeks**
- App supports:
  - Storing review URLs
  - Importing scraped review timestamps later
- No in-app reviews or notes

**Feature Status:**
- `last_review_at` field exists in Thread model (TASK-110 completed)
- Import endpoint in review but not merged (TASK-111)

---

## Export Policy

- **Raw data export only**
- JSON / CSV
- Narrative summaries are view-only

**Feature Status:**
- JSON export implemented (`GET /admin/export/json/`)
- CSV export implemented (`GET /admin/export/csv/`)
- Narrative summary export in review but not merged (TASK-112)

---

## Narrative Session Summary

Sessions are shown as **generated summaries**, not logs.

**Example:**

> **Session: Dec 29, 8:12 PM – 10:03 PM**
> Started at d6
> Ladder path: d6 → d4 → d6
>
> Read:
>
> * Hellboy (Omnibus v2) — ★★★★☆
> * Majestic #4 — ★★★★½
>
> Skipped:
>
> * Doom Patrol
>
> Completed:
>
> * Hellboy (Omnibus v2)

Raw events still exist underneath.

---

## Data Model (JSON v1)

```json
{
  "settings": {
    "session_gap_hours": 6,
    "start_die": 6,
    "rating_scale": { "min": 0.5, "max": 5.0, "step": 0.5 }
  },
  "dice_ladder": [4, 6, 8, 10, 12, 20],
  "threads": [
    {
      "id": "thread_hellboy",
      "title": "Hellboy",
      "format": "Trade",
      "issues_remaining": 3,
      "status": "active",
      "queue_position": 4,
      "last_rating": 4.0,
      "last_activity_at": "2025-12-30T01:10:00-06:00"
    }
  ],
  "sessions": [
    {
      "id": "session_001",
      "started_at": "2025-12-30T19:00:00-06:00",
      "start_die": 6,
      "events": [
        {
          "type": "roll",
          "die": 6,
          "result": 4,
          "selected_thread_id": "thread_hellboy",
          "selection_method": "rolled"
        },
        {
          "type": "rate",
          "thread_id": "thread_hellboy",
          "rating": 4.5,
          "issues_read": 1,
          "queue_move": "front",
          "die_after": 4
        }
      ]
    }
  ]
}
```

---

## Wireframes (Text)

### Roll Screen

```
Session: Active
Current die: d6
Rolling among top 6 threads

[ ROLL d6 ]

Result: 4
Picked: Hellboy (Omnibus)

[ Start Reading ] [ Override ]

Stale suggestion:
"You haven't touched Dial H in 51 days"
```

### Rate Screen

```
Thread: Hellboy (Omnibus)

Rating:
0.5 1.0 1.5 2.0 2.5
3.0 3.5 4.0 4.5 5.0

Issues read: [1] (+ / -)

Queue effect:
>=4.0 → move front
<4.0 → move back

[ Save Rating ]
```

### Queue Screen

```
Active die: d6
Roll pool: rows 1–6 (highlighted)

1. Squadron Supreme ★★★★★
2. Justice League ★★★★½
3. Starman ★★★★
4. Hellboy ★★★★
5. Conan Saga ★★★★
6. Earth 2 ★★★★

Completed hidden by default
```

---

## PRD Alignment Status

**Current Compliance:** ~90%

**Completed Features (Tasks Done):**
- ✅ Dice ladder system (d4-d20)
- ✅ Queue management (front, back, position)
- ✅ Session detection (6-hour gap)
- ✅ Roll and override behavior
- ✅ Rating system (0.5-5.0 scale)
- ✅ Queue movement based on rating
- ✅ Thread completion and reactivation
- ✅ Staleness tracking (last read, rating timestamps)
- ✅ `last_review_at` field in Thread model
- ✅ Narrative summary generation (build_narrative_summary function)
- ✅ JSON export
- ✅ CSV import/export

**In Progress (Tasks in Review):**
- ⏳ Review timestamp import API (TASK-111)
- ⏳ Narrative summary export (TASK-112)

**PRD Misses Documented:**
- See PRD_MISSES.md for detailed gap analysis

**Overall Status:** PRD alignment nearly complete, 2 tasks in review awaiting merge.

---

## Key Implementation Notes

### Session Detection

Session detection in `comic_pile/session.py`:
- `is_active()` checks if session ended < 6 hours ago
- `get_or_create()` returns active session or creates new one
- No manual session creation - purely time-based

### Dice Ladder Logic

Dice ladder in `comic_pile/dice_ladder.py`:
- `step_up()` and `step_down()` functions
- Ladder: `[4, 6, 8, 10, 12, 20]`
- Bounds enforced (d4 can't step down, d20 can't step up)
- Used in rate flow (`app/api/rate.py`)

### Queue Operations

Queue logic in `comic_pile/queue.py`:
- `move_to_front()` - move thread to position 1, shift others down
- `move_to_back()` - move thread to last position
- `move_to_position()` - move thread to specific position
- Called from rate API and queue API

### Narrative Summaries

Session summaries in `app/api/session.py`:
- `build_narrative_summary()` generates markdown summary
- Shows roll path, reads, ratings, completions
- Used in session details view (`/sessions/{id}/details`)

---

## Design Decisions Rationale

### Why No Notes System?

- Ratings and queue movement encode intent
- Notes would add complexity without clear purpose
- Review system (League of Comic Geeks) handles detailed reviews
- App focuses on tracking, not documentation

### Why 6-Hour Session Boundary?

- Natural break point for reading sessions
- Accommodates reading sessions spanning hours
- Prevents session fragmentation from short breaks
- No manual intervention required

### Why d6 Starting Die?

- Middle of the ladder (not too shallow, not too deep)
- Allows both stepping up (poor reads) and down (good reads)
- Balanced exploration vs. reward

### Why Move Front/Back on Rating?

- High ratings (≥4.0) → keep reading what you enjoy
- Low ratings (<4.0) → move on to something else
- Simple binary decision, no nuanced positioning
- Ladder exploration handles the rest

### Why Allow Chaos?

- No cap on queue size
- No forced selection of stale threads
- Manual overrides always available
- Reflects real-world reading habits (chaotic but personal)

---

## Future Enhancements (Not in PRD)

These are ideas mentioned in retrospectives or tech debt, but not part of the core PRD:

- **d10 3D rendering improvements** - Current rendering has visibility issues
- **Multi-user support** - Would require authentication/authorization
- **Rate limiting** - For production deployment
- **Background job queue** - For large CSV imports/exports
- **API versioning** - For breaking changes
- **Redis caching** - For multi-instance deployments

**Note:** These are not priorities unless specifically requested or justified by scale requirements.
