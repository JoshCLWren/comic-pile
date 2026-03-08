Audit: Dependency Management, Issue Ordering, and Admin UX

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

🔴 CRITICAL: No API to Insert Issues at a Specific Position

File: app/api/issue.py:252-264

next_new_position = max_position + 1
for issue_number in issue_numbers:
    if issue_number not in existing_issues:
        issue = Issue(thread_id=thread_id, issue_number=issue_number,
                      position=next_new_position, status="unread")
        ...
        next_new_position += 1

Issue creation always appends. There is no insert_after parameter, no position parameter, no way to specify where an issue belongs. The extensive docstring (lines 155-203) even acknowledges this as a deliberate design choice, arguing that insertion "would require shifting all subsequent issues, which is error-prone."

This forced the annuals incident: annuals went to the end, requiring manual SQL to reposition.

🔴 CRITICAL: No API to Reorder Issues Within a Thread

There is no reorder/move endpoint for issues anywhere in app/api/issue.py. The issue API has exactly 5 endpoints:

GET /threads/{thread_id}/issues (list)
POST /threads/{thread_id}/issues (create, append-only)
GET /issues/{issue_id} (get one)
POST /issues/{issue_id}:markRead
POST /issues/{issue_id}:markUnread

No PATCH /issues/{issue_id} for position updates. No POST /threads/{thread_id}/issues:reorder. No bulk reposition.

🔴 CRITICAL: No API to Delete Individual Issues

There is no DELETE /issues/{issue_id} endpoint. Issue deletion only happens in:

Session restore (app/api/session.py:845,875) — bulk wipe of all issues in a thread
Undo (app/api/undo.py:134) — same bulk wipe

When duplicate annuals were created in production, there was no API to remove them. Direct SQL was the only option.

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

🟠 HIGH: No Duplicate Detection for Issues

The create endpoint deduplicates by issue_number (app/api/issue.py:254-255), but:

There is no unique constraint on (thread_id, issue_number) in the database schema (app/models/issue.py:34-39 — only indexes, not constraints)
If a race condition or script runs twice, duplicates can be created
The annuals incident included 3 duplicate annuals that had to be manually cleaned up

🟡 MEDIUM: Scripts Are Compensating for Missing Core Product Features

The scripts directory reveals a pattern of operational band-aids:

Script
What it compensates for
add_xmen_annuals.py
Missing "insert issue at position" UI/API
complete_annual_dependencies.py
Missing "create dependency chain" batch UI
create_xmen_dependencies.py
Missing cross-thread reading order UI
check_xmen_dependencies.py
Missing dependency audit/validation UI
fix_thread_positions.py
Missing position integrity enforcement
audit_thread_positions.py
Missing admin health dashboard

These scripts all hit the production API over HTTP with hardcoded thread IDs and issue numbers. They are brittle, non-repeatable, and the existence of 6 operational scripts for what should be core product features is a red flag.

🟡 MEDIUM: Blocking Logic Only Checks next_unread_issue_id

File: comic_pile/dependencies.py:32-42

The issue-level blocking query joins target_thread.next_unread_issue_id to target_issue.id. This means:

Only the single next unread issue is checked for dependencies
If issue #80 is the next unread and is blocked by the Annual, the thread is blocked ✓
But if issue #80 is read and issue #81 also has a dependency on something unread, and the user manually marks #80 as read, then #81 becomes next — and its blocking status is recalculated correctly

This works as designed but creates a subtle issue: if position order and dependency order disagree about what "next" means, the blocking check uses position order (via next_unread_issue_id), potentially checking the wrong issue for blocks.

🟡 MEDIUM: No Frontend Workflow for Issue Reordering

The IssueToggleList component (frontend/src/pages/QueuePage.tsx:74-201) only supports:

Viewing issues (sorted by position from API)
Toggling read/unread status
Adding new issues (append-only)

No drag-and-drop reorder, no "move after" button, no position editor. The IssueList.tsx component is equally read-only for ordering.

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

Minimum Viable Fix (can ship in days)

Add POST /issues/{issue_id}:move endpoint — accepts { "after_issue_id": int | null }. If null, move to position 1. Shifts subsequent issues' positions. This is the #1 missing feature.
Add DELETE /issues/{issue_id} endpoint — deletes a single issue, shifts subsequent positions down, updates next_unread_issue_id and issues_remaining/total_issues.
Add insert_after_issue_id parameter to POST /threads/{thread_id}/issues — optional; when provided, new issues are inserted after the specified issue instead of appending.
Add unique constraint on (thread_id, issue_number) — prevents duplicate issues at the DB level.
Fix Thread.issues relationship ordering — change order_by="Issue.issue_number" to order_by="Issue.position" at app/models/thread.py:111.

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

Missing UI Features (Priority Order)

Issue reorder in IssueToggleList — add drag-and-drop or "move up/move down" buttons on each issue pill. This is the highest-impact UX improvement.
"Insert after" in issue creation — when adding issues, let the user pick where they go (with a dropdown of existing issues to insert after, or an "insert at position" field).
Delete individual issue — add a delete button/action on each issue in the list.
Per-issue dependency indicator — show a small dependency icon on issues that have incoming/outgoing edges. Clicking opens detail.
Order validation warning — when position order disagrees with cross-thread dependency order, show a banner: "⚠️ Issue ordering may not match reading order dependencies."
Bulk operations — select multiple issues → mark read, delete, move.

Workflows That Should Never Require Direct SQL

After implementing the above, these should all be possible in the UI:

Insert an annual between two existing issues
Reorder issues after import
Delete duplicate issues
Verify that reading order matches dependency order
View why a thread is blocked at the issue level

---

Part 5: Testing Plan

Missing Tests (Priority Order)

Test
Why It's Missing
Risk
Insert issue at specific position
API doesn't support it yet
Entire annual workflow broken
Reorder issue within thread
API doesn't support it yet
Forces SQL for normal maintenance
Delete single issue
API doesn't support it yet
Can't clean up duplicates
next_unread_issue_id validity after issue deletion
No delete API exists
Could point to deleted issue
next_unread_issue_id validity after reorder
No reorder API exists
Could advance past blocked issues
Position uniqueness within thread
No DB constraint
Data corruption
Dependency consistency after issue move
No move API exists
Orphaned dependency edges
Position-dependency order agreement
No validation exists
Silent wrong reading order
Thread.issues relationship order vs API order
Not tested
ORM returns wrong order
Duplicate issue creation prevention
No unique constraint
Data corruption
Concurrent issue creation race condition
Tested via locking but no duplicate guard
Position collisions

Recommended Regression Tests (Add First)

test_create_issues_appends_to_end — verify that creating issues always appends and doesn't corrupt existing positions. (May already partially exist in test_api_issues.py.)
test_thread_issues_relationship_order — verify that thread.issues returns issues in the correct order (will fail today due to issue_number ordering).
test_next_unread_issue_id_after_manual_position_change — simulate the annual scenario: create issues 1-100, then add "Annual" at position 101, manually update its position to 80, verify next_unread_issue_id still makes sense.
test_intra_thread_dependency_does_not_affect_position_order — verify that creating a dependency between two issues in the same thread doesn't change their visible order.
test_duplicate_issue_number_rejected — once the unique constraint is added, verify 409/400 on duplicate creation.

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
