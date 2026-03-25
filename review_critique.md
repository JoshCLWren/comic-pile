1. toast notification fires on ANY die change when not in manual mode — if die changes for non-Ladder reasons (e.g. session restore, initial load race), a misleading "Pool shrank/grew" toast appears. Should only fire when Ladder algorithm actually triggers the change.
2. toast copy does not match the issue spec — the spec says "Die stepped down to d4 — only 4 eligible threads in pool" but the code emits "Pool shrank to 4 — using d4" which (a) says "Pool shrank" instead of "Die stepped down", (b) redundantly repeats the die size ("to 4 — using d4"), and (c) never mentions thread count as the reason for the change.
3. no new tests for any of the new UI behaviour — RollPage.test.tsx only adds a ToastContext mock import but adds zero test cases for: tooltip content on Ladder indicator, tooltip content on die buttons, tooltip content on Auto button, die picker opacity-50 class when Ladder active, toast shown on die change, mobile modal help text, mobile Auto button checkmark display.
4. node_modules symlink committed to git (commit 3f1b9c2) — points to absolute path /mnt/extra/josh/code/comic-pile/node_modules, will break for all other developers and CI.
5. package-lock.json has unrelated dependency bumps (rollup 4.57.1→4.60.0, ajv, flatted, minimatch, undici) not tied to #367 — noise in PR, should be reverted or split.
6. scripts/opencode_pipeline.sh changes are unrelated to #367 — the diff shows main has newer pipeline code (circuit breakers, model blacklist, gh caching) that this branch lacks. This will conflict and should not be in this PR.
7. activeThreads.length in toast effect dependency array (line 305) is unused inside the effect body — causes unnecessary effect re-runs on every thread list change.
8. commit message "fix: <description> (closes #367)" (3f1b9c2) is an unfilled placeholder — indicates incomplete review of the branch before submission.
9. toast message implies pool size is the cause, but die size is the cause — the Ladder steps down on high ratings (>=4), not because threads were removed. "Pool shrank to 4" misleads users into thinking 4 threads remain; the actual mechanism is "Die stepped down to d4 based on your high rating."
10. Deadlock errors in `test_issues_position_index_improves_pagination` and database integrity violations in `test_http_exception_handler_404` and `test_http_exception_handler_for_nonexistent_thread` indicate unstable test environment
11. Linting warnings in `frontend/src/components/IssueList.tsx` and `frontend/src/contexts/ToastContext.tsx` violate project standards
12. Missing regression tests for the new Ladder mode UX changes
13. No tests for the toast notification logic in `RollPage`
14. No tests for the mobile die picker modal help text
15. No tests for the Auto button tooltip and checkmark behavior
16. No verification that the "Pool shrank/grew" toast messages are accurate to the ladder algorithm
17. No accessibility tests for the new info icon and tooltips
18. No tests for edge cases like rapid die changes or ladder mode toggles
19. Changelog entry lacks specific details about the ladder algorithm behavior
