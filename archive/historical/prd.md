Absolutely. Below is the **complete, consolidated documentation** we’ve built together. This is the single source of truth that records:

* All **decisions**
* All **rules**
* The **PRD**
* The **interaction model**
* The **wireframes**
* The **data model**
* The answers to every major design question you resolved

Nothing speculative, nothing unfinished. This is a v1 spec you can hand to Future You and start building immediately.

---

# Dice-Driven Comic Reading App

**Full Design & Product Documentation (v1)**

---

## 1. Core Philosophy

This app exists to **support an existing ritual**, not optimize or gamify it.

Key principles:

* Chaos is allowed.
* Ratings and movement encode intent, not notes.
* Dice are sacred.
* Time, not mood, defines sessions.
* The queue reflects *what you can read now*, not everything you’ve ever read.

---

## 2. Core Concepts

### 2.1 Reading Thread

A **thread** represents a mini reading order, equivalent to one row in your spreadsheet.

Examples:

* *Hellboy Omnibus Vol 2*
* *Declustered X-Men*
* *Majestic*
* *Conan Saga*

Threads are atomic units for:

* Rolling
* Reading
* Rating
* Queue movement

---

### 2.2 Queue

* The queue is a **single ordered list**, top to bottom.
* Ordering is authoritative.
* Rolls always operate on the **top N rows**, where N is the die size.

Completed threads:

* Disappear from the queue by default
* Can be reactivated later

New or reactivated threads:

* Always insert at **position 1**
* No cap, chaos is acceptable

---

### 2.3 Dice Ladder (Finalized)

**Allowed dice (ordered):**

```
d4 → d6 → d8 → d10 → d12 → d20
```

**Rules:**

* New session always starts at **d6**
* After each read + rating:

  * Rating ≥ 4.0 → step **down** one die
  * Rating < 4.0 → step **up** one die
* Only **one step per read**
* Bounds:

  * d4 stays d4 on success
  * d20 stays d20 on failure

**Intent:**

* d4 is the reward state
* Larger dice explore deeper into the queue
* The ladder self-corrects chaos

Manual overrides **do not bypass ladder logic**.

---

## 3. Session Model

### 3.1 Session Boundary

* A session is defined strictly by time.
* If **6 hours** pass without activity → new session.
* Less than 6 hours → resume session automatically.
* No manual “start new session” button.

---

### 3.2 Session Scope

* A session may include:

  * Multiple rolls
  * Multiple reads
  * Multiple ratings
* Dice ladder persists throughout the session.

---

### 3.3 Pending Reads

If you:

* Roll and select a thread
* But do not read or rate it

Then:

* That thread becomes a **pending read**

On resume (within 6 hours):

* App surfaces: *“You were about to read X”*
* You may:

  * Continue
  * Override

If overridden:

* Original pick is logged as **rolled but skipped**
* No penalties, no movement

---

## 4. Roll Behavior

### 4.1 Roll Pool Definition (Final)

* Rolls always operate on:

  * **The first N active threads**, top to bottom
  * Where N = current die denomination

Example:

* d6 → rows 1–6
* d4 → rows 1–4

Completed threads are excluded automatically.

---

### 4.2 Manual Override

* Rare but essential
* Used when:

  * Sleepy
  * Traveling
  * One issue left
  * Just feel like it

Override behavior:

* Logs override event
* Does not touch skipped thread
* Ladder still updates after rating

---

## 5. Rating Model

### 5.1 Rating Scale

* Range: **0.5 → 5.0**
* Step: **0.5**
* Ratings are:

  * Primarily local to the read
  * Softly influenced by momentum
  * Accepted as-is, no correction

---

### 5.2 Progress Rules

* If you rate it, you read it.
* Rating always decrements **issues remaining by 1**.

**Caveat (Omnibus Formatting):**

* Sometimes you unintentionally read 2 issues.
* Rate screen supports adjusting “issues read” (default 1).

No notes system exists.

---

### 5.3 Queue Movement

After rating:

* Rating ≥ 4.0 → move thread to **front**
* Rating < 4.0 → move thread to **back**

Movement is immediate and authoritative.

---

## 6. Completion Semantics

* If issues remaining hits **0**:

  * Thread is marked **completed**
  * Removed from roll pool
  * Hidden from queue by default

Completion does **not** mean:

* Finished forever

Reactivation:

* When new issues are owned
* Thread re-enters queue at **position 1**

---

## 7. Staleness Awareness

* Chaos can starve threads indefinitely.
* App tracks:

  * Last read timestamp
  * Last rating timestamp
  * Last review timestamp (imported)

Behavior:

* Informational only
* Subtle nudges like:

  * *“Not touched in 47 days”*
* No forced selection
* No dice bias

---

## 8. Time Tracking

* Raw timestamps recorded for:

  * Rolls
  * Reads
  * Ratings
  * Overrides
  * Corrections

No derived labels:

* No “night reading”
* No productivity framing

Raw data only.

---

## 9. Reviews & External Data

* You review everything on **League of Comic Geeks**
* App supports:

  * Storing review URLs
  * Importing scraped review timestamps later
* No in-app reviews or notes

---

## 10. Export Policy

* **Raw data export only**
* JSON / CSV
* Narrative summaries are view-only

---

## 11. Narrative Session Summary

Sessions are shown as **generated summaries**, not logs.

Example:

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

## 12. Data Model (JSON v1)

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

## 13. Wireframes (Text)

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

---

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

---

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

