1. DEAD CODE: ReadingOrderTimeline.tsx:56 - condition `issueTimeline.length === 0` never executes because buildReadingOrderTimelineEntries always returns at least one span entry
2. MISSING ARIA: Timeline/Flowchart toggle buttons (DependencyBuilder.tsx:459-480) lack role="tablist", role="tab", aria-selected, aria-controls for screen reader accessibility
3. INSUFFICIENT TESTS: readingOrderTimeline.test.ts has only 3 basic tests - missing edge cases for gates at issue #1, gate at final issue, multiple gates same issue, null next_unread_issue
4. MISSING E2E TESTS: No Playwright tests verify Reading Order Timeline rendering, gate status badges, position indicators, or Timeline/Graph tab switching
5. UNRELATED CHANGE: app/database.py increases pool_size (5→20) and max_overflow (10→30) without load testing or clear justification
6. UNRELATED CHANGE: app/models/issue.py removes ix_issue_thread_id index - potential performance regression on thread queries
7. UNRELATED CHANGE: docker-compose.test.yml adds max_connections=200 without justification
8. UNRELATED CHANGE: IssueList.tsx modifies loadIssues signature and dependencies - bug fix unrelated to #371
9. UNRELATED CHANGE: ThreadPool.tsx changes "Snoozed"→"Paused" - UX improvement unrelated to #371
10. UNRELATED CHANGE: RollPage/index.tsx adds tooltips to snoozed offset - unrelated to #371
11. UNRELATED CHANGE: CollectionToolbar.tsx changes "+ New Collection"→"Create new collection" - unrelated to #371
12. UNRELATED CHANGE: dependencyHelpers.ts changes "Blocking:"→"Blocks:" - unrelated to #371
13. UNRELATED CHANGE: playwright.config.ts reduces workers (4→1) - slows down CI, unrelated to #371
14. EDGE CASE BUG: When extractIssueNumber fails (no '#' in label), gate displays "Issue #??" - confusing UX, should fallback to targetIssueId or show "Unknown issue"
15. EDGE CASE BUG: Multiple gates at same issue number render as separate cards without visual grouping - user must scan through duplicates
16. ACCEPTANCE CRITERIUM FAIL: "On mobile, the timeline is vertical and scrollable" - implementation uses fixed viewport height (max-h-[50vh]) without responsive breakpoints; mobile layout not explicitly tested