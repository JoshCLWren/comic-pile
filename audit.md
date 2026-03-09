Audit: Dependency Management, Issue Ordering, and Admin UX

Status update (March 8, 2026)

This document started as a pre-fix audit. The insert/reorder/delete issue APIs, the
`Thread.issues` ordering fix, the `(thread_id, issue_number)` uniqueness guard, and the
`IssueToggleList` drag/delete workflow described below have since shipped. The remaining
architectural concern is that dependency edges can still disagree with canonical
`Issue.position` ordering inside a thread.

Part 1: Findings (Ordered by Severity)

🔴 CRITICAL: Two Competing Sources of Truth for In-Thread Reading Order

The core design flaw. The system maintains two independent, unsynchronized ordering systems:

Issue.position (integer) — controls visible UI order. Used by list_issues (app/api/issue.py:54-90), mark_issue_read next-unread calculation (app/api/issue.py:455-464), rate.py next-unread calculation (app/api/rate.py:267-274), and the IssueList.tsx / IssueToggleList frontends.
Dependency edges (DAG) — controls roll blocking via get_blocked_thread_ids (comic_pile/dependencies.py:32-42), which checks if thread.next_unread_issue_id has unread source issues.

These two systems can silently disagree. When annuals were inserted:

Dependencies said: #79 → Annual → #80
Position said: Annual is at position 131 (end of thread)
The UI showed the annual at the bottom
next_unread_issue_id still advanced by position order, ignoring dependency order entirely

Impact: The system can present issues in a visually wrong reading order while dependency blocking works on a completely different ordering. There is no validation, no warning, and no detection of this drift.

Resolved (post-fix): Insert, Move/Reorder, and Delete APIs Exist

The issue-management APIs discussed as missing in the original audit are now implemented:

- `POST /api/v1/threads/{thread_id}/issues` accepts `insert_after_issue_id` and shifts later
  `Issue.position` values before inserting new issues.
- `POST /api/v1/issues/{issue_id}:move` moves a single issue relative to another issue.
- `POST /api/v1/threads/{thread_id}/issues:reorder` rewrites canonical in-thread order from
  an explicit ordered list of issue IDs.
- `DELETE /api/v1/issues/{issue_id}` deletes one issue, compacts later positions, and updates
  issue-tracking metadata on the thread.

The annuals workflow no longer needs direct SQL for insertion, reordering, or cleanup.

🟠 HIGH: Thread.issues Relationship Orders by issue_number, Not position

File: app/models/thread.py:105-113

issues: Mapped[list["Issue"]] = relationship(
    ...
    order_by="Issue.issue_number",
)

The Thread model's issues relationship sorts by issue_number (string sort), while every API endpoint sorts by Issue.position (integer sort). This means:

If you ever access thread.issues via the ORM relationship (instead of a manual query), you get issue_number alphabetical order — where "Annual 1998" sorts before "2" because strings sort lexicographically.
The API correctly uses Issue.position, but this relationship is a landmine for any future code that touches thread.issues directly.

🟠 HIGH: next_unread_issue_id Can Drift from Dependency Order

next_unread_issue_id is always set to the lowest-position unread issue (app/api/issue.py:455-464, app/api/rate.py:267-274). It never considers dependency ordering.

If dependency order says "read Annual before #80" but position order says "#80 comes before Annual", then next_unread_issue_id will point to #80, and the user will be told to read #80 — even though the Annual is a prerequisite. The blocking system will prevent the thread from being rollable (if the Annual's dependency target is #80), but the UI will show #80 as "next" with no explanation of why the thread is blocked.

Resolved (post-fix): Duplicate Detection for Issues

The model and migrations now enforce `UniqueConstraint("thread_id", "issue_number")` via
`uq_issue_thread_number`, and the API surfaces the conflict instead of allowing duplicate issue
numbers to accumulate in a thread.

🟡 MEDIUM: Scripts Were Compensating for Missing Core Product Features

The scripts directory reveals a pattern of operational band-aids:

Script
Pre-fix gap / current replacement
add_xmen_annuals.py
Pre-fix insert-position gap; replaced by `POST /api/v1/threads/{id}/issues` plus dependency APIs
complete_annual_dependencies.py
Pre-fix batch dependency creation gap; replaced by `POST /api/v1/dependencies/`
create_xmen_dependencies.py
Missing cross-thread reading order UI
check_xmen_dependencies.py
Pre-fix dependency audit gap; replaced in part by `GET /api/v1/threads/{thread_id}/issues:validateOrder`
fix_thread_positions.py
Pre-fix `Thread.queue_position` repair workflow
audit_thread_positions.py
Pre-fix queue-audit workflow

These scripts are now deprecated reference material. Several originally existed because core
product features were missing; the issue-management APIs and UI now cover the main insertion,
reorder, and delete flows directly.

🟡 MEDIUM: Blocking Logic Only Checks next_unread_issue_id

File: comic_pile/dependencies.py:32-42

The issue-level blocking query joins target_thread.next_unread_issue_id to target_issue.id. This means:

Only the single next unread issue is checked for dependencies
If issue #80 is the next unread and is blocked by the Annual, the thread is blocked ✓
But if issue #80 is read and issue #81 also has a dependency on something unread, and the user manually marks #80 as read, then #81 becomes next — and its blocking status is recalculated correctly

This works as designed but creates a subtle issue: if position order and dependency order disagree about what "next" means, the blocking check uses position order (via next_unread_issue_id), potentially checking the wrong issue for blocks.

Resolved (post-fix): IssueToggleList Supports Reorder and Delete

`IssueToggleList` in `frontend/src/pages/QueuePage.tsx` now supports drag-and-drop reorder, read
toggle, and inline delete actions. It calls the issue-management APIs directly and keeps the edit
modal open while issue mutations complete.

🟡 MEDIUM: No Dependency View on Individual Issues

The DependencyBuilder.tsx shows dependencies at the thread level. You can see "this thread blocks / is blocked by" and create issue-level dependencies. But there is no way to:

View all dependencies for a specific issue
See which issues within the current thread have incoming/outgoing edges
Detect that an annual at position 131 has a dependency edge saying it should be between positions 79 and 80

---

Part 2: Architecture Diagnosis

Is the current design coherent?

No. The design has two ordering systems that serve overlapping purposes without coordination:

position is the canonical display and progression order. Every API query uses it. next_unread_issue_id is derived from it. The UI renders by it.
Issue-level dependencies were designed for cross-thread blocking (e.g., "read X-Men #85 before Magneto War #1"), but they are also being used for intra-thread ordering (e.g., "read #79 before Annual before #80" — all within the same thread).

Using dependencies for intra-thread ordering is a category error. Dependencies control blocking (rollability), not display order. The system was never designed for them to substitute for position-based ordering.

What should be the canonical source of truth for in-thread order?

position should be canonical for in-thread ordering. Dependencies should not be used to express "this issue comes after that issue" within the same thread. Position already does that. The problem is that the system lacks the tools to manage position correctly.

What should dependencies be used for?

Cross-thread blocking only. Dependencies should express: "you cannot read Thread B until you've finished Issue X in Thread A." This is genuinely graph-shaped and can't be modeled by position alone.

Intra-thread dependencies (like #79 → Annual → #80 within the same thread) are a workaround for the inability to insert the Annual at position 79.5. If position management worked, these wouldn't be needed.

---

Part 3: Concrete Recommendations

Shipped Fixes

- `POST /api/v1/issues/{issue_id}:move` for single-issue moves
- `POST /api/v1/threads/{thread_id}/issues:reorder` for bulk reorder
- `DELETE /api/v1/issues/{issue_id}` for individual deletion
- `POST /api/v1/threads/{thread_id}/issues` with `insert_after_issue_id`
- `uq_issue_thread_number` to block duplicate issue numbers
- `Thread.issues` ordering by `Issue.position`

Medium-Term Redesign

Remove intra-thread issue-level dependencies. Once position management works, delete any dependency where source_issue.thread_id == target_issue.thread_id. These are noise.
Add a "validate order" API — GET /threads/{thread_id}/issues:validateOrder that checks whether any cross-thread issue dependencies imply a different reading order than the current position order, and returns warnings.
Add bulk reposition API — POST /threads/{thread_id}/issues:reorder accepting an ordered list of issue IDs. Sets positions 1..N accordingly.
Add dependency view per issue — GET /issues/{issue_id}/dependencies returning incoming and outgoing edges, so the UI can show dependency context on individual issues.

Migration Concerns

Existing intra-thread dependencies should be audited before removal — some may have been created as workarounds and can be safely deleted after positions are corrected.
Any position gaps or duplicates in existing data should be fixed by running the equivalent of fix_thread_positions.py but for issue positions within threads.
The (thread_id, issue_number) unique constraint needs a data cleanup migration first to remove existing duplicates.

---

Part 4: Frontend/Admin Workflow Recommendations

Shipped UI Features

- Issue reorder in `IssueToggleList` via drag-and-drop
- Delete individual issue from the edit modal

Remaining UI Gaps

- "Insert after" in issue creation so users can choose placement without relying on append-then-reorder
- Per-issue dependency indicator for incoming/outgoing edges
- Order validation warning when cross-thread dependency order disagrees with in-thread positions
- Bulk operations such as multi-select mark read/delete/move

Workflows That Should Never Require Direct SQL

After implementing the above, these should all be possible in the UI:

Insert an annual between two existing issues
Reorder issues after import
Delete duplicate issues
Verify that reading order matches dependency order
View why a thread is blocked at the issue level

---

Part 5: Testing Plan

Shipped Regression Coverage

- Insert issue at specific position: covered by API tests for middle insertion, append-after-last,
  invalid insert target, and next-unread updates.
- Reorder issue within thread: covered by move/reorder API tests and frontend unit tests for drag
  semantics.
- Delete single issue: covered by API tests for middle/last/final deletion and dependency cleanup.
- `next_unread_issue_id` validity after issue deletion/reorder: covered by API tests for delete,
  move, reorder, and blocked-status refresh.
- Position uniqueness within thread: covered by the unique constraint plus integrity/conflict tests.
- Position/dependency order agreement: covered by `issues:validateOrder` tests.
- `Thread.issues` relationship order vs API order: covered by relationship-order regression tests.

Remaining High-Value Coverage

- Cross-thread dependency UI surfacing at the per-issue level
- End-to-end tests for insert-after from the frontend once that UI exists
- More concurrency-specific tests for interleaved issue mutations in the edit modal

---

Summary Diagram
✓ Mermaid
View on mermaid.live
┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐ ┌──────────────────────────────────────────────────────────────────────────────────┐ ┌────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                "Current: Two Competing Order Systems"                                                 │ │                           "Problem: Annual Insertion"                            │ │                                         "Missing: Required APIs"                                           │
│                                                                                                                                       │ │                                                                                  │ │                                                                                                            │
│                                                                                                                                       │ │                                                                                  │ │                                                                                                            │
│ ┌────────────────────────────────────────────────┐                                         ┌────────────────────────────────────────┐ │ │                ┌───────────────────────────────────────────────────────────────┐ │ │ ┌────────────────────────┐     ┌───────────────────┐     ┌──────────────────┐     ┌──────────────────────┐ │
│ │                                                │                                         │                                        │ │ │                │                                                               │ │ │ │                        │     │                   │     │                  │     │                      │ │
│ │      "Issue.position (controls UI order)"      │         ├"can─d"Annual─attpos┬131"──────┤    "Issue creation always appends"     │ │ │             ┌──┤            "Script creates deps #79 → Annual → #80"           │ │ │ │ "❌ Insert at position" │     │ "❌ Reorder issue" │     │ "❌ Delete issue" │     │ "❌ Order validation" │ │
│ │                                                │                              │          │                                        │ │ │             │  │                                                               │ │ │ │                        │     │                   │     │                  │     │                      │ │
│ └────────────────────────┬───────────────────────┘                              │          └────────────────────────────────────────┘ │ │             │  └───────────────────────────────────────────────────────────────┘ │ │ └────────────────────────┘     └───────────────────┘     └──────────────────┘     └──────────────────────┘ │
│                          │                                                      │                                                     │ │             │                                                                    │ │                                                                                                            │
│                          │                                                      │                                                     │ │             │                                                                    │ └────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
│                          │                                                      │                                                     │ │             │                                                                    │                                                                                                               
│                          │                                                      │                                                     │ │             │                                                                    │                                                                                                               
│                    "determines"                                                 └───────────────────────────────┬───────────"says─pos─~80"────────────┴──────────────────────────────────┐                                 │                                                                                                               
│                          │                                                                                      │                     │ │                                                │                                 │                                                                                                               
│                          │                                                                                      │                     │ │                                                │                                 │                                                                                                               
│                          │                                                                                      │                     │ │                                                │                                 │                                                                                                               
│                          ▼                                                                                      ▼                     │ │                                                ▼                                 │                                                                                                               
│ ┌────────────────────────────────────────────────┐                                         ┌────────────────────────────────────────┐ │ │                ┌───────────────────────────────────────────────────────────────┐ │                                                                                                               
│ │                                                │                                         │                                        │ │ │                │                                                               │ │                                                                                                               
│ │ "next_unread_issue_id (derived from position)" │          ◄──────"blocks─based─on"───────┤ "Dependency edges (controls blocking)" │ │ │   ├───────────►│ "ORDER DRIFT: UI shows Annual at end Deps say it's in middle" │ │                                                                                                               
│ │                                                │                                         │                                        │ │ │                │                                                               │ │                                                                                                               
│ └────────────────────────────────────────────────┘                                         └────────────────────────────────────────┘ │ │                └───────────────────────────────────────────────────────────────┘ │                                                                                                               
│                                                                                                                                       │ │                                                                                  │                                                                                                               
└───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘ └──────────────────────────────────────────────────────────────────────────────────┘                                                                                                               
Bottom line: The design is fundamentally incoherent. position and dependency edges serve overlapping purposes without coordination, and the system lacks the basic CRUD operations (insert-at-position, reorder, delete) needed to manage issue ordering through the product. The 6 operational scripts and the manual SQL incident are symptoms of this gap. The fix is straightforward: make position canonical and fully manageable via API/UI, reserve dependencies for cross-thread blocking only, and add the missing issue management endpoints.
