# Comic Pile: Understanding Issues and Dependencies for Storyline Reading Orders

## Executive Summary

Comic Pile supports **issue-level dependencies** that enable creating linear reading chains between specific comic issues across different series. This is perfect for storyline reading orders like "Uncanny X-Men #362" → "X-Men #82" → "Uncanny X-Men #363".

---

## 1. Thread and Issue Model Structure

### Thread Model (`app/models/thread.py`)

**Key Fields:**
- `id`: Unique identifier
- `title`: Series name (e.g., "Uncanny X-Men")
- `format`: Format type (e.g., "Comic", "Trade", "Omnibus")
- `issues_remaining`: Counter for backward compatibility
- `total_issues`: Total issue count (NULL = old system, not migrated)
- `next_unread_issue_id`: Foreign key to next unread Issue
- `reading_progress`: "not_started" | "in_progress" | "completed"
- `queue_position`: Position in reading queue
- `status`: "active" | "completed" | "snoozed"
- `blocked_by_thread_ids`: Denormalized list of blocking thread IDs
- `blocked_by_issue_ids`: Denormalized list of blocking issue IDs
- `is_blocked`: Boolean flag for quick filtering

**Relationships:**
- `issues`: One-to-many relationship with Issue records
- `dependencies_out`: Dependencies where this thread blocks others
- `dependencies_in`: Dependencies where this thread is blocked by others

### Issue Model (`app/models/issue.py`)

**Key Fields:**
```python
id: int                          # Unique identifier
thread_id: int                   # Parent thread (CASCADE delete)
issue_number: str                # ISSUE NUMBERS ARE STRINGS - NOT JUST INTEGERS!
position: int                    # Ordering within thread (sequential)
status: str                      # "unread" | "read"
read_at: datetime | None         # When marked as read
created_at: datetime             # Creation timestamp
```

**Critical Indexes:**
- `ix_issue_thread_id`: Fast lookup of all issues in a thread
- `ix_issue_thread_number`: Find specific issue by number within thread
- `ix_issue_thread_position`: Ordered listing of issues

**Relationships:**
- `thread`: Parent Thread
- `dependencies_out`: Issue-level dependencies blocking others
- `dependencies_in`: Issue-level dependencies where this issue is blocked

---

## 2. Issue Numbering System

### **Issue Numbers Are Strings, Not Integers**

**Key Finding:** The `issue_number` field is a `String(50)`, allowing **arbitrary numbering**:

**Examples:**
- Regular issues: `"1"`, `"2"`, `"362"`, `"82"`
- Annuals: `"Annual 1"`, `"Annual 1999"`
- Specials: `"Special"`, `"Director's Cut"`
- Decimals: `"½"`, `"0.5"`
- Alpha-numeric: `"Alpha"`, `"Omega Red"`

**Index Support:**
```sql
CREATE INDEX ix_issue_thread_number ON issues (thread_id, issue_number);
```
This enables fast lookups like: "Find issue #362 in Uncanny X-Men thread"

### Issue Position vs. Issue Number

**Position (`position` field):**
- Always sequential integers: 1, 2, 3, 4...
- Used for ordering issues within a thread
- Automatically assigned on creation

**Issue Number (`issue_number` field):**
- Arbitrary string from the actual comic
- Can be non-sequential, duplicate (across threads), or textual
- Human-readable identifier shown in UI

**Example:**
```text
Thread: Uncanny X-Men
Issues:
  position=1, issue_number="362"
  position=2, issue_number="Annual 1"
  position=3, issue_number="363"
```

---

## 3. Dependency System

### Dependency Model (`app/models/dependency.py`)

**Structure:**
```python
class Dependency:
    id: int
    source_thread_id: int | None      # Thread-level dependency
    target_thread_id: int | None      # Thread-level dependency
    source_issue_id: int | None       # Issue-level dependency
    target_issue_id: int | None       # Issue-level dependency
    created_at: datetime
```

**Constraint:** Exactly ONE dependency type per record:
- Thread-level: `source_thread_id + target_thread_id` populated
- Issue-level: `source_issue_id + target_issue_id` populated

**Uniqueness:**
- `uq_dependency_thread_edge`: One thread→thread dependency per pair
- `uq_dependency_issue_edge`: One issue→issue dependency per pair

### How Dependencies Block Reading

**Thread-Level Blocking:**
```
Thread A (source) ──blocks──> Thread B (target)

Block condition: Thread A.status != "completed"
```
- Thread B is blocked until ALL of Thread A is read
- Used for "finish series A before starting series B"

**Issue-Level Blocking:**
```
Issue #362 (source) ──blocks──> Issue #82 (target)

Block condition:
  1. Issue #362.status != "read" AND
  2. Issue #82 IS the target thread's "next_unread_issue_id"
```
- Thread containing Issue #82 is blocked until Issue #362 is read
- Only blocks if the target issue is the NEXT one to read
- Allows fine-grained "read these specific issues in order" chains

### Circular Dependency Detection

The system prevents cycles using BFS traversal:

```python
# From comic_pile/dependencies.py
async def detect_circular_dependency(
    source_id: int,
    target_id: int,
    dependency_type: str,  # "thread" | "issue"
    db: AsyncSession,
) -> bool:
    # Returns True if adding source→target would create a cycle
```

**Blocked Example:**
```
A → B → C

Cannot add: C → A (would create cycle A→B→C→A)
Allowed: A → C (no cycle)
```

---

## 4. API Endpoints

### Issue Management Endpoints

#### List All Issues in a Thread
```http
GET /api/v1/threads/{thread_id}/issues
Query Params:
  - status: "unread" | "read" (optional)
  - page_size: 1-100 (default: 50)
  - page_token: cursor for pagination

Response:
{
  "issues": [
    {
      "id": 123,
      "thread_id": 5,
      "issue_number": "362",
      "position": 15,
      "status": "unread",
      "read_at": null,
      "created_at": "2024-01-15T10:30:00Z"
    }
  ],
  "total_count": 50,
  "page_size": 50,
  "next_page_token": "15,123"  // "position,id" format
}
```

**Use Case:** "Get all issues from Uncanny X-Men to find issue #362"

#### Get Specific Issue by ID
```http
GET /api/v1/issues/{issue_id}

Response:
{
  "id": 123,
  "thread_id": 5,
  "issue_number": "362",
  "position": 15,
  "status": "unread",
  "read_at": null,
  "created_at": "2024-01-15T10:30:00Z"
}
```

**Use Case:** "Find issue details after getting ID from dependency API"

#### Mark Issue as Read
```http
POST /api/v1/issues/{issue_id}:markRead

Effect:
  1. Marks issue.status = "read"
  2. Sets issue.read_at = now()
  3. Updates thread.next_unread_issue_id to next unread
  4. Decrements thread.issues_remaining
  5. Recalculates all user dependencies (may unblock threads)

No response body (204 No Content)
```

#### Mark Issue as Unread
```http
POST /api/v1/issues/{issue_id}:markUnread

Effect:
  1. Marks issue.status = "unread"
  2. Sets issue.read_at = null
  3. Updates thread.next_unread_issue_id if this issue is earlier
  4. Increments thread.issues_remaining
  5. Reactivates thread if it was completed
  6. Recalculates all user dependencies (may block threads)

No response body (204 No Content)
```

### Dependency Endpoints

#### Create Dependency
```http
POST /api/v1/dependencies/

Request (Issue-level):
{
  "source_type": "issue",
  "source_id": 456,      // Uncanny X-Men #362
  "target_type": "issue",
  "target_id": 789       // X-Men #82
}

Request (Thread-level):
{
  "source_type": "thread",
  "source_id": 5,        // Uncanny X-Men
  "target_type": "thread",
  "target_id": 12        // X-Men
}

Response (201 Created):
{
  "id": 999,
  "source_thread_id": null,
  "target_thread_id": null,
  "source_issue_id": 456,
  "target_issue_id": 789,
  "is_issue_level": true,
  "source_label": "Uncanny X-Men #362",
  "target_label": "X-Men #82",
  "source_issue_thread_id": 5,
  "target_issue_thread_id": 12,
  "created_at": "2024-01-15T10:30:00Z"
}
```

**Validation:**
- Rejects mixed thread/issue dependencies
- Rejects self-dependencies (source_id === target_id)
- Detects and rejects circular dependencies
- Verifies ownership (both threads/issues belong to current user)

#### List Thread Dependencies
```http
GET /api/v1/threads/{thread_id}/dependencies

Response:
{
  "blocking": [
    // Dependencies where this thread blocks others
    {
      "id": 999,
      "source_issue_id": 456,
      "target_issue_id": 789,
      "target_label": "X-Men #82",
      "is_issue_level": true,
      ...
    }
  ],
  "blocked_by": [
    // Dependencies where this thread is blocked
    {
      "id": 998,
      "source_issue_id": 123,
      "target_issue_id": 456,
      "source_label": "Uncanny X-Men #361",
      "is_issue_level": true,
      ...
    }
  ]
}
```

#### Get Blocking Explanation
```http
POST /api/v1/threads/{thread_id}:getBlockingInfo

Response:
{
  "is_blocked": true,
  "blocking_reasons": [
    "Blocked by issue #361 in Uncanny X-Men (thread #5)"
  ]
}
```

#### Delete Dependency
```http
DELETE /api/v1/dependencies/{dependency_id}

Response:
{
  "message": "Dependency deleted"
}
```

#### Get All Blocked Thread IDs
```http
GET /api/v1/dependencies/blocked

Response:
[12, 15, 23]  // Array of blocked thread IDs
```

---

## 5. Frontend Components

### DependencyBuilder Modal (`frontend/src/components/DependencyBuilder.tsx`)

**Features:**
1. **Dependency Type Toggle:**
   - "Issue Level" - Creates dependencies between specific issues
   - "Thread Level" - Creates dependencies between entire threads

2. **Thread Search:**
   - Real-time search with 300ms debounce
   - Filters out current thread
   - Shows thread title and format

3. **Inline Migration (Issue Mode):**
   - Detects if selected thread needs migration (`total_issues === null`)
   - Prompts user to migrate with last_read and total_issues inputs
   - Automatically refreshes thread data after migration

4. **Issue Selection (Issue Mode):**
   - Loads all issues from both source and target threads
   - Dropdowns show: `#issue_number ✅` (read) or `🟢` (unread)
   - Auto-selects each thread's next_unread_issue_id by default

5. **Dependency Listing:**
   - Two sections: "This thread is blocked by" and "This thread blocks"
   - Shows enriched labels: "Uncanny X-Men #362 (Issue-level block)"
   - Delete button for each dependency

6. **Flowchart Visualization:**
   - Toggle button to show/hide flowchart
   - Renders dependency graph as SVG
   - Thread nodes = large rectangles
   - Issue nodes = small diamonds
   - Dashed lines = issue-level dependencies
   - Solid lines = thread-level dependencies

**Key Code Pattern:**
```typescript
// Example: Creating issue-level dependency
await dependenciesApi.createDependency({
  sourceType: 'issue',
  sourceId: sourceIssueId!,  // Uncanny X-Men #362
  targetType: 'issue',
  targetId: targetIssueId!   // X-Men #82
})
```

### IssueList Component (`frontend/src/components/IssueList.tsx`)

**Features:**
- Lists all issues in a thread
- Filter by: All | Unread | Read
- Toggle status with click (unread ↔ read)
- Shows "Next" badge on thread.next_unread_issue_id
- Progress bar and percentage
- Read date for completed issues

**UI Display:**
```
Issues                          [All ▼]
┌─────────────────────────────────┐
│ 🟢 #361                         │
│ 🟢 #362                      Next│
│ ✅ #363         Jan 15, 2024    │
│ ✅ #364         Jan 16, 2024    │
└─────────────────────────────────┘

Read 2 of 50 (4%)
████░░░░░░░░░░░░░░░░░░░░░░░░░░░
```

### API Service (`frontend/src/services/api-issues.ts`)

**Key Methods:**
```typescript
issuesApi.list(threadId, { status, page_size, page_token })
issuesApi.create(threadId, "1-25, Annual 1")
issuesApi.get(issueId)
issuesApi.markRead(issueId)
issuesApi.markUnread(issueId)
issuesApi.migrateThread(threadId, lastIssueRead, totalIssues)
```

---

## 6. Creating Linear Dependency Chains for Storylines

### Use Case: X-Men "Operation: Zero Tolerance" Reading Order

**Scenario:**
The storyline spans multiple series with specific issue order:
```
Uncanny X-Men #362 (1998)
  ↓
X-Men (1991) #82 (1998)
  ↓
Uncanny X-Men #363 (1998)
  ↓
X-Men #83 (1998)
  ↓
Uncanny X-Men #364 (1998)
```

### Step-by-Step Implementation

#### Step 1: Ensure Thread Migration

Both threads must have `total_issues != null` (issue tracking enabled):

```bash
# Check migration status
GET /api/v1/threads/{thread_id}

# Look for:
{
  "total_issues": 376,      // Not null = migrated
  "next_unread_issue_id": 123
}
```

**If Not Migrated:**
```http
POST /api/v1/threads/{thread_id}:migrateToIssues

{
  "last_issue_read": 361,   // Last issue already read
  "total_issues": 376       // Total issues in series
}
```

#### Step 2: Get Issue IDs

**Option A: List All Issues and Find by Number**
```http
GET /api/v1/threads/5/issues?status=unread

# Parse response to find issue_number === "362"
{
  "id": 456,
  "issue_number": "362",
  "position": 362,
  "status": "unread"
}
```

**Option B: Query Directly (backend feature)**
```python
# In app/api/issue.py, add endpoint:
@router.get("/threads/{thread_id}/issues/by-number/{issue_number}")
async def get_issue_by_number(thread_id: int, issue_number: str):
    issue = await db.execute(
        select(Issue).where(
            Issue.thread_id == thread_id,
            Issue.issue_number == issue_number
        )
    )
    return issue_to_response(issue.scalar_one())
```

```http
GET /api/v1/threads/5/issues/by-number/362

Response:
{
  "id": 456,
  "thread_id": 5,
  "issue_number": "362",
  "position": 362,
  "status": "unread"
}
```

#### Step 3: Create Dependencies

```http
# Dependency 1: UX-M #362 → X-Men #82
POST /api/v1/dependencies/
{
  "source_type": "issue",
  "source_id": 456,    // Uncanny X-Men #362
  "target_type": "issue",
  "target_id": 789     // X-Men #82
}

# Dependency 2: X-Men #82 → UX-M #363
POST /api/v1/dependencies/
{
  "source_type": "issue",
  "source_id": 789,    // X-Men #82
  "target_type": "issue",
  "target_id": 457     // Uncanny X-Men #363
}

# Dependency 3: UX-M #363 → X-Men #83
POST /api/v1/dependencies/
{
  "source_type": "issue",
  "source_id": 457,    // Uncanny X-Men #363
  "target_type": "issue",
  "target_id": 790     // X-Men #83
}
```

#### Step 4: Verify Blocking Chain

```http
# Check if X-Men thread is blocked
POST /api/v1/threads/12:getBlockingInfo

Response:
{
  "is_blocked": true,
  "blocking_reasons": [
    "Blocked by issue #82 in X-Men (thread #12)",
    "Blocked by issue #362 in Uncanny X-Men (thread #5)"
  ]
}
```

**Note:** The system shows the entire blocking chain, not just immediate blockers.

#### Step 5: Test the Reading Flow

```bash
# Initial state:
# - Uncanny X-Men next_unread_issue_id = 456 (issue #362)
# - X-Men next_unread_issue_id = 789 (issue #82)
# - X-Men is BLOCKED because #362 is unread

# User reads Uncanny X-Men #362
POST /api/v1/issues/456:markRead

# After marking read:
# - Issue #362 status = "read"
# - Uncanny X-Men next_unread_issue_id = 457 (issue #363)
# - X-Men is still BLOCKED because #82 is still unread

# User reads X-Men #82
POST /api/v1/issues/789:markRead

# After marking read:
# - Issue #82 status = "read"
# - X-Men next_unread_issue_id = 790 (issue #83)
# - Uncanny X-Men #363 is now UNBLOCKED (can be rolled)
# - X-Men #83 is still BLOCKED (waiting for UX-M #363)
```

### Visualization: Dependency Flowchart

The DependencyBuilder component visualizes the chain:

```
┌─────────────────────┐
│ Uncanny X-Men (#5)  │
└─────────────────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌───────┐  ┌───────┐
│ #362  │──│ #363  │  (Issue nodes)
└───────┘  └───────┘
    │         │
    ▼         ▼
┌───────┐  ┌───────┐
│  #82  │──│  #83  │
└───────┘  └───────┘
    │         │
    └────┬────┘
         ▼
┌─────────────────────┐
│   X-Men (#12)       │
└─────────────────────┘
```

- **Solid rectangles** = Thread nodes
- **Small diamonds** = Issue nodes
- **Arrows** = Dependencies
- **Dashed lines** = Issue-level deps
- **Red highlight** = Blocked nodes

---

## 7. Key Implementation Details

### Thread Blocking Logic (`comic_pile/dependencies.py`)

**Issue-Level Blocking Algorithm:**
```python
# Thread is blocked if:
target_thread.next_unread_issue_id == target_issue.id
AND
source_issue.status != "read"
```

**Translation:** The target thread is only blocked if the TARGETED issue is the NEXT one to read. This prevents blocking entire threads when you're still reading earlier issues.

**Example:**
```
Uncanny X-Men issues: [#361 unread, #362 unread, #363 unread]
X-Men issues: [#81 unread, #82 unread, #83 unread]

Dependency: UX-M #362 → X-Men #82

Current state:
  - UX-M next_unread = #361 (not #362 yet)
  - X-Men next_unread = #81 (not #82 yet)

Result: X-Men is NOT blocked yet

After reading X-Men #81:
  - X-Men next_unread = #82 (now matches the dependency target)
  - UX-M #362 is still unread

Result: X-Men is now BLOCKED (can't roll #82 until #362 is read)

After reading UX-M #362:
  - UX-M #362 status = read

Result: X-Men is unblocked
```

### Roll Pool Filtering (`comic_pile/queue.py`)

The dice roll system automatically excludes blocked threads:

```python
async def get_roll_pool(user_id: int, db: AsyncSession) -> list[Thread]:
    # Returns only active threads where is_blocked = False
    pool = await db.execute(
        select(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.status == "active")
        .where(Thread.is_blocked == False)
        .order_by(Thread.queue_position)
    )
    return pool.scalars().all()
```

**Effect:** When you roll the dice, you'll never get a blocked thread, ensuring you always read dependencies in order.

### Denormalized Blocked Status

The `Thread.is_blocked` flag is recalculated on every dependency change:

```python
async def refresh_user_blocked_status(user_id: int, db: AsyncSession):
    blocked_ids = await get_blocked_thread_ids(user_id, db)

    # Reset all flags
    await db.execute(
        update(Thread)
        .where(Thread.user_id == user_id)
        .values(is_blocked=False)
    )

    # Set blocked flags
    if blocked_ids:
        await db.execute(
            update(Thread)
            .where(Thread.user_id == user_id)
            .where(Thread.id.in_(blocked_ids))
            .values(is_blocked=True)
        )
```

**Performance:** Single UPDATE query for all threads, O(n) where n = blocked threads.

---

## 8. Finding Issues by Number

### Backend Implementation

The system doesn't have a dedicated "find issue by number" endpoint yet, but you can:

**Option 1: List and Filter (Current)**
```http
GET /api/v1/threads/5/issues
# Returns all issues, filter client-side for issue_number == "362"
```

**Option 2: Add Dedicated Endpoint (Recommended)**

Add to `app/api/issue.py`:

```python
@router.get("/threads/{thread_id}/issues/by-number/{issue_number}", response_model=IssueResponse)
async def get_issue_by_number(
    thread_id: int,
    issue_number: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> IssueResponse:
    """Get a specific issue by its issue number within a thread.

    Args:
        thread_id: The thread ID to search within.
        issue_number: The issue number to find (e.g., "362", "Annual 1").
        current_user: Authenticated user.
        db: Database session.

    Returns:
        IssueResponse with issue details.

    Raises:
        HTTPException: If thread not found, not owned, or issue not found.
    """
    thread = await db.get(Thread, thread_id)
    if not thread or thread.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    result = await db.execute(
        select(Issue).where(
            Issue.thread_id == thread_id,
            Issue.issue_number == issue_number
        )
    )
    issue = result.scalar_one_or_none()

    if not issue:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue {issue_number} not found in thread {thread_id}",
        )

    return issue_to_response(issue)
```

**Usage:**
```http
GET /api/v1/threads/5/issues/by-number/362
GET /api/v1/threads/5/issues/by-number/Annual%201
```

**Performance:** Uses `ix_issue_thread_number` index for O(log n) lookup.

### Frontend Helper

Add to `frontend/src/services/api-issues.ts`:

```typescript
/**
 * Find a specific issue by number within a thread
 * @param threadId - The thread to search
 * @param issueNumber - The issue number to find (e.g., "362", "Annual 1")
 * @returns The issue if found
 */
getByNumber: async (threadId: number, issueNumber: string): Promise<Issue> => {
  return api.get(`/v1/threads/${threadId}/issues/by-number/${encodeURIComponent(issueNumber)}`)
}
```

---

## 9. Example: Creating Full Storyline Chain

### Scenario: "Age of Apocalypse" Crossover

**Reading Order:**
```
1. X-Men Alpha #1
2. Amazing X-Men #1-4
3. Astonishing X-Men #1-4
4. Factor X #1-4
5. Generation Next #1-4
6. Gambit & the X-Ternals #1-4
7. X-Calibre #1-4
8. X-Man #1-4
9. X-Universe #1-4
10. Amazing X-Men #2
11. X-Omega #1
12. X-Men Alpha #1 (reprint)
```

### Implementation Strategy

#### Option A: Single "Crossover Event" Thread (Not Recommended)

Create one thread "Age of Apocalypse" and add issues in order:
```
Thread: Age of Apocalypse
Issues:
  - X-Men Alpha #1 (position 1)
  - Amazing X-Men #1 (position 2)
  - Amazing X-Men #2 (position 3)
  - ...
```

**Pros:**
- Simple, no dependencies needed
- Linear reading order enforced naturally

**Cons:**
- Issues aren't in their "home" series
- Can't track series completion
- Breaks the "one thread = one series" model

#### Option B: Multiple Threads with Cross-Series Dependencies (Recommended)

Keep series separate, use issue-level dependencies:

```
Thread: X-Men Alpha
  - Issue #1 (position 1)
      ↓
Thread: Amazing X-Men
  - Issue #1 (position 1)
      ↓
Thread: Astonishing X-Men
  - Issue #1 (position 1)
      ↓
...and so on
```

**Dependency Chain:**
```javascript
// X-Men Alpha #1 → Amazing X-Men #1
POST /api/v1/dependencies/
{
  "source_type": "issue",
  "source_id": getXMenAlphaIssueId("1"),
  "target_type": "issue",
  "target_id": getAmazingXMenIssueId("1")
}

// Amazing X-Men #1 → Astonishing X-Men #1
POST /api/v1/dependencies/
{
  "source_type": "issue",
  "source_id": getAmazingXMenIssueId("1"),
  "target_type": "issue",
  "target_id": getAstonishingXMenIssueId("1")
}

// ... continue chain
```

**Pros:**
- Issues stay in their series
- Can track individual series progress
- Dependencies enforce reading order
- Can still read individual series outside crossover

**Cons:**
- More complex setup
- Requires manual dependency creation

#### Option C: Hybrid Approach

Create a dedicated "Crossover Events" thread to track the storyline:

```
Thread: Age of Apocalypse (Tracker)
  - Issue "X-Men Alpha #1" (position 1)
  - Issue "Amazing X-Men #1" (position 2)
  - ...

Thread: X-Men Alpha (Home Series)
  - Issue #1 (position 1)

Thread: Amazing X-Men (Home Series)
  - Issue #1 (position 1)
```

Use dependencies to link tracker issues to actual issues:

```javascript
// Tracker issue → Actual issue
POST /api/v1/dependencies/
{
  "source_type": "issue",
  "source_id": getTrackerIssueId("X-Men Alpha #1"),
  "target_type": "issue",
  "target_id": getXMenAlphaIssueId("1")
}
```

**Pros:**
- Clear visual of reading order
- Issues in home series
- Can mark tracker issues as read for progress

**Cons:**
- Duplicate issue entries
- More maintenance

---

## 10. UI Workflow for Creating Dependencies

### User Story: Creating "Operation: Zero Tolerance" Chain

**Step 1: Open DependencyBuilder**
1. Navigate to Queue page
2. Find "X-Men" thread
3. Click "Dependencies" button
4. Modal opens with "Dependency Type" toggle

**Step 2: Select Issue-Level Dependencies**
1. Click "Issue Level" button (highlights amber)
2. See helper text: "Blocks only when the target issue becomes next unread"

**Step 3: Find Source Thread**
1. Type "uncanny" in search box
2. Wait 300ms for results
3. See "Uncanny X-Men (Comic)" in dropdown
4. Click to select

**Step 4: Handle Migration (If Needed)**
1. System detects Uncanny X-Men needs migration
2. See amber alert: "Uncanny X-Men isn't tracking issues yet"
3. Click "Migrate Now" button
4. Enter "Last issue read: 361"
5. Enter "Total issues: 376"
6. Click "Migrate"
7. System refreshes thread data

**Step 5: Select Issues**
1. Dropdowns populate with issues from both threads
2. Source dropdown: Uncanny X-Men issues
   - #361 ✅
   - #362 🟢 (auto-selected)
   - #363 🟢
3. Target dropdown: X-Men issues
   - #81 ✅
   - #82 🟢 (auto-selected)
   - #83 🟢

**Step 6: Create Dependency**
1. Button text shows: "Block issue #82 with: Uncanny X-Men #362"
2. Click button
3. Button shows "Adding dependency..." (disabled)
4. Success: dependency appears in "This thread is blocked by" section

**Step 7: Create Chain**
1. Repeat steps 3-6 for each link in chain
2. After creating all dependencies, see full list:
   ```
   This thread is blocked by:
   ┌────────────────────────────────────────┐
   │ Uncanny X-Men #362                     │
   │ Issue-level block              [Remove]│
   └────────────────────────────────────────┘
   ```

**Step 8: Visualize Flowchart**
1. Click "▼ View Flowchart" button
2. See dependency graph with arrows
3. Hover over nodes to see thread titles
4. Issue nodes shown as small diamonds

---

## 11. Technical Constraints and Limitations

### Current Limitations

1. **No Bulk Dependency Creation**
   - Must create each dependency individually
   - Would benefit from batch API endpoint

2. **No Dependency Templates**
   - Can't save "storyline templates" for reuse
   - Each crossover must be configured manually

3. **Issue Number Lookup**
   - No dedicated endpoint to find issue by number
   - Must list all issues and filter (see Section 8)

4. **Dependency Editing**
   - Can't modify existing dependencies
   - Must delete and recreate to change

5. **Cross-User Dependencies**
   - Dependencies only work within single user's threads
   - Can't share reading orders between users

### Performance Considerations

1. **Dependency Recalculation**
   - Runs on every dependency create/delete
   - O(n + m) where n = threads, m = dependencies
   - Uses denormalized `is_blocked` flag for O(1) filtering

2. **Issue Listing**
   - Pagination prevents loading thousands of issues
   - Indexes ensure fast lookups by thread_id and issue_number

3. **Circular Dependency Detection**
   - BFS traversal is O(V + E) where V = nodes, E = edges
   - Only runs when creating new dependencies
   - Scales to thousands of dependencies

### Database Schema Notes

**Issue Number as String:**
- Supports arbitrary numbering ("Annual 1", "½", "Alpha")
- Trade-off: Can't sort by issue_number numerically
- Use `position` field for ordering

**Position Field Management:**
- New issues appended at end (max_position + 1)
- No insertion in middle (would require shifting all later positions)
- Prevents race conditions with row-level locking

**Cascade Deletes:**
- Deleting thread deletes all issues (CASCADE)
- Deleting thread deletes all dependencies (CASCADE)
- Prevents orphaned data

---

## 12. Summary and Recommendations

### Key Takeaways

1. **Issue Numbers Are Flexible**
   - Use string field for arbitrary numbering
   - Position field maintains order
   - Supports annuals, specials, decimals

2. **Issue-Level Dependencies Enable Storyline Chains**
   - Block specific issues, not entire threads
   - Only blocks if target issue is next_unread
   - Enables "read these issues in this order"

3. **UI Simplifies Complex Workflows**
   - DependencyBuilder handles migration automatically
   - Visual flowchart shows relationships
   - Issue dropdowns show read/unread status

4. **System Enforces Reading Order**
   - Dice roll excludes blocked threads
   - Can't roll blocked issues
   - Dependencies prevent skipping

### Recommended Implementation for Storyline Reading Orders

**For "Operation: Zero Tolerance" Chain:**

1. **Ensure Series Threads Exist**
   - "Uncanny X-Men" (issues #1-376)
   - "X-Men" (1991 series, issues #1-150)

2. **Migrate Both Threads**
   - Use inline migration in DependencyBuilder
   - Set last_read and total_issues accurately

3. **Create Issue-Level Dependencies**
   - UX-M #362 → X-Men #82
   - X-Men #82 → UX-M #363
   - UX-M #363 → X-Men #83
   - And so on...

4. **Test the Chain**
   - Verify blocking_info shows correct blockers
   - Read each issue in order
   - Confirm next issues unblock as expected

5. **Visualize with Flowchart**
   - Confirm dependency arrows correct
   - Check for accidental cycles
   - Verify no missing links

### Future Enhancements

1. **Bulk Dependency Creation**
   ```json
   POST /api/v1/dependencies/bulk
   {
     "dependencies": [
       {"source_type": "issue", "source_id": 456, "target_type": "issue", "target_id": 789},
       {"source_type": "issue", "source_id": 789, "target_type": "issue", "target_id": 457}
     ]
   }
   ```

2. **Dependency Templates**
   - Save "Operation: Zero Tolerance" as template
   - Apply template to any user's threads
   - Share reading orders between users

3. **Smart Issue Lookup**
   - Dedicated endpoint for finding issue by number
   - Support partial matching ("#36" → #360-369)
   - Batch lookup for multiple issues

4. **Dependency Graph Import/Export**
   - Export reading order as JSON
   - Import from community sources
   - Validate against user's library

5. **Visual Storyline Editor**
   - Drag-and-drop interface
   - Auto-connect issues
   - Preview reading order

---

## 13. Quick Reference

### Essential API Endpoints

```
# Issues
GET    /api/v1/threads/{thread_id}/issues              # List issues
GET    /api/v1/threads/{thread_id}/issues/by-number/{number}  # Find by number
POST   /api/v1/threads/{thread_id}/issues              # Create issues
GET    /api/v1/issues/{issue_id}                       # Get issue
POST   /api/v1/issues/{issue_id}:markRead              # Mark read
POST   /api/v1/issues/{issue_id}:markUnread            # Mark unread

# Dependencies
POST   /api/v1/dependencies/                           # Create dependency
GET    /api/v1/dependencies/{dependency_id}            # Get dependency
DELETE /api/v1/dependencies/{dependency_id}            # Delete dependency
GET    /api/v1/threads/{thread_id}/dependencies        # List thread deps
POST   /api/v1/threads/{thread_id}:getBlockingInfo     # Get blocking reasons
GET    /api/v1/dependencies/blocked                    # Get all blocked IDs

# Thread Migration
POST   /api/v1/threads/{thread_id}:migrateToIssues     # Migrate thread
```

### Issue Status Values

```
"unread" - Not yet read (green circle in UI)
"read"   - Completed (checkmark in UI)
```

### Thread Status Values

```
"active"    - In reading queue
"completed" - All issues read
"snoozed"   - Temporarily removed from queue
```

### Reading Progress Values

```
"not_started" - 0 issues read
"in_progress"  - Some issues read
"completed"    - All issues read
```

### Blocking Conditions

**Thread-Level:**
```
target_thread.is_blocked = true IF
  source_thread.status != "completed" AND
  dependency exists (source_thread → target_thread)
```

**Issue-Level:**
```
target_thread.is_blocked = true IF
  target_thread.next_unread_issue_id == target_issue.id AND
  source_issue.status != "read" AND
  dependency exists (source_issue → target_issue)
```

---

## Appendix A: Database Schema

```sql
-- Threads Table
CREATE TABLE threads (
    id INTEGER PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    format VARCHAR(50) NOT NULL,
    issues_remaining INTEGER DEFAULT 0,
    total_issues INTEGER NULL,
    next_unread_issue_id INTEGER NULL REFERENCES issues(id) ON DELETE SET NULL,
    reading_progress VARCHAR(20) NULL,
    blocked_by_thread_ids JSON NULL,
    blocked_by_issue_ids JSON NULL,
    queue_position INTEGER NOT NULL,
    status VARCHAR(20) DEFAULT 'active',
    is_blocked BOOLEAN DEFAULT FALSE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Issues Table
CREATE TABLE issues (
    id INTEGER PRIMARY KEY,
    thread_id INTEGER NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    issue_number VARCHAR(50) NOT NULL,
    position INTEGER NOT NULL,
    status VARCHAR(20) DEFAULT 'unread',
    read_at TIMESTAMP WITH TIME ZONE NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(thread_id, position)
);

-- Dependencies Table
CREATE TABLE dependencies (
    id INTEGER PRIMARY KEY,
    source_thread_id INTEGER NULL REFERENCES threads(id) ON DELETE CASCADE,
    target_thread_id INTEGER NULL REFERENCES threads(id) ON DELETE CASCADE,
    source_issue_id INTEGER NULL REFERENCES issues(id) ON DELETE CASCADE,
    target_issue_id INTEGER NULL REFERENCES issues(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CHECK (
        (source_thread_id IS NOT NULL AND target_thread_id IS NOT NULL
         AND source_issue_id IS NULL AND target_issue_id IS NULL)
        OR
        (source_thread_id IS NULL AND target_thread_id IS NULL
         AND source_issue_id IS NOT NULL AND target_issue_id IS NOT NULL)
    ),
    UNIQUE(source_thread_id, target_thread_id),
    UNIQUE(source_issue_id, target_issue_id)
);

-- Indexes
CREATE INDEX ix_issue_thread_id ON issues(thread_id);
CREATE INDEX ix_issue_thread_number ON issues(thread_id, issue_number);
CREATE INDEX ix_issue_thread_position ON issues(thread_id, position);
CREATE INDEX ix_thread_user_status_position ON threads(user_id, status, queue_position);
CREATE INDEX ix_thread_user_status_blocked_position ON threads(user_id, status, is_blocked, queue_position);
```

---

## Appendix B: Example Code Snippets

### Python: Creating Dependency Chain

```python
from app.models import Issue, Thread, Dependency
from sqlalchemy import select

async def create_storyline_chain(
    source_thread_id: int,
    target_thread_id: int,
    issue_pairs: list[tuple[str, str]],  # [("362", "82"), ("363", "83")]
    db: AsyncSession,
):
    """Create linear dependency chain between two series.

    Example:
        create_storyline_chain(
            source_thread_id=5,   # Uncanny X-Men
            target_thread_id=12,  # X-Men
            issue_pairs=[("362", "82"), ("363", "83")],
            db=db
        )
    """
    for source_num, target_num in issue_pairs:
        # Find issues
        source_result = await db.execute(
            select(Issue).where(
                Issue.thread_id == source_thread_id,
                Issue.issue_number == source_num
            )
        )
        source_issue = source_result.scalar_one()

        target_result = await db.execute(
            select(Issue).where(
                Issue.thread_id == target_thread_id,
                Issue.issue_number == target_num
            )
        )
        target_issue = target_result.scalar_one()

        # Create dependency
        dependency = Dependency(
            source_issue_id=source_issue.id,
            target_issue_id=target_issue.id
        )
        db.add(dependency)

    await db.commit()
```

### TypeScript: Finding Issue by Number

```typescript
// Helper function to find issue by number
async function findIssueByNumber(
  threadId: number,
  issueNumber: string
): Promise<Issue | null> {
  try {
    const response = await issuesApi.list(threadId)
    const issue = response.issues.find(i => i.issue_number === issueNumber)
    return issue || null
  } catch (error) {
    console.error('Failed to find issue:', error)
    return null
  }
}

// Usage
const issue362 = await findIssueByNumber(5, "362")
if (issue362) {
  console.log(`Found issue ID: ${issue362.id}`)
}
```

### TypeScript: Bulk Dependency Creation (Future Enhancement)

```typescript
// Proposed API wrapper
async function createDependencyChain(
  dependencies: Array<{
    sourceThread: number
    sourceIssue: string
    targetThread: number
    targetIssue: string
  }>
): Promise<void> {
  for (const dep of dependencies) {
    const sourceIssue = await findIssueByNumber(dep.sourceThread, dep.sourceIssue)
    const targetIssue = await findIssueByNumber(dep.targetThread, dep.targetIssue)

    if (!sourceIssue || !targetIssue) {
      throw new Error(`Missing issue: ${dep.sourceIssue} or ${dep.targetIssue}`)
    }

    await dependenciesApi.createDependency({
      sourceType: 'issue',
      sourceId: sourceIssue.id,
      targetType: 'issue',
      targetId: targetIssue.id
    })
  }
}

// Usage
await createDependencyChain([
  { sourceThread: 5, sourceIssue: "362", targetThread: 12, targetIssue: "82" },
  { sourceThread: 5, sourceIssue: "363", targetThread: 12, targetIssue: "83" },
  { sourceThread: 5, sourceIssue: "364", targetThread: 12, targetIssue: "84" }
])
```

---

## Conclusion

Comic Pile's issue-level dependency system provides a robust foundation for creating complex storyline reading orders. The key insights are:

1. **Issue numbers are strings**, supporting arbitrary numbering like "362", "82", "Annual 1"
2. **Dependencies block at the issue level**, only when the target issue is next to read
3. **The UI handles migration automatically**, making it easy to set up dependencies
4. **The system enforces reading order** through the dice roll mechanism

For your use case of creating "Uncanny X-Men #362" → "X-Men #82" → "Uncanny X-Men #363" chains, the existing infrastructure supports this perfectly. You would:

1. Ensure both threads are migrated to issue tracking
2. Find the issue IDs (by listing issues or adding a lookup endpoint)
3. Create dependencies between each pair of issues
4. The system will block the dice roll from skipping ahead in the chain

The flowchart visualization in the DependencyBuilder makes it easy to verify the chain is correct, and the blocking_info endpoint provides clear feedback about why a thread is blocked.
