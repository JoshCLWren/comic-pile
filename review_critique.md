1. No PostgreSQL test database configured; tests crash on setup due to missing TEST_DATABASE_URL or DATABASE_URL (env / .env). This blocks validating any acceptance criteria and makes the pytest results unreliable in this environment.
2. Coverage threshold failed: reported coverage below 96% (initial run shows 21% when tests fail to initialize). The failure is environmental, but from a QA perspective the feature set cannot be validated until DB/config is available.
3. Broad test failures across API, issues, and UI test suites indicate environment gating rather than functional regressions in code changes. Even after fixing DB wiring, several tests under tests/test_*.py may still surface issues that require targeted fixes.
4. Lint run passes with two frontend warnings (no errors). Warnings include: React Hook useCallback missing dependency and a refresh rule warning about exporting non-component constants. These are non-blocking but should be cleaned to ensure future CI stability.
5. The PR introduces substantial frontend and pipeline tooling changes (DependencyBuilder, RollPage, issue parser, and opencode_pipeline.sh). Risk: large surface area for regressions; ensure targeted unit tests and UI tests cover critical paths (thread listing, creating threads, migrations, and UI behavior).
6. The review pipeline script (scripts/opencode_pipeline.sh) ships with many operational commands (worktrees, git updates, external tool invocations). In CI this can be brittle if the environment differs. Recommend guard rails or a dedicated CI-only variant to avoid accidental local runs.
7. Edge-case concerns in app/api/thread.py: complex thread state transitions (active/completed/implemented) rely on multiple fields (issues_remaining, next_unread_issue_id, total_issues). While tests would catch inconsistencies, current diff warrants a focused regression test suite around migrate_to_issues, reactivate_thread, and set_pending_thread flows.
8. Edge-case risk in delete_thread: delete path updates Session pending references and logs an event. If there are concurrent operations or partial failures, ensure compensating transactions or robust rollback handling for all paths.
9. Data integrity assumptions in migrate_thread_to_issues_simple: the logic infers total_issues and creates Issue rows. This is fragile around partial pre-existing data; add regression tests for partially populated threads and non-numeric issue numbers.
10. Mobile accessibility and UI quality: RollPage and DependencyBuilder changes should be reviewed for keyboard navigation, focus management, and proper ARIA semantics. No explicit accessibility tests appear in the current suite; consider adding focused a11y tests for critical UI flows.
11. Documentation and changelog updates: ensure docs/changelog.md reflects the UI/API changes and the new pipeline flow. The patch shows a lot of moving parts; without changelog entries, reviewers may miss the scope.
12. Recommendation: add a dedicated test environment configuration (dotenv/.env.test) and CI workflow to validate issue-366 changes in isolation, including a minimal PostgreSQL test instance or a test-dedicated in-memory alternative if feasible.
13. Changes in `app/api/thread.py` remove cache clearing logic without justification
14. Changes in `app/config.py` modify environment file loading order without explanation
15. Changes in `app/utils/issue_parser.py` refactor length validation logic but lack tests for edge cases
16. Changes in `frontend/src/pages/RollPage/index.tsx` introduce tooltips without verifying mobile compatibility
17. Changes in `frontend/src/types/index.ts` allow string IDs for dependencies without type safety guarantees
18. Changes in `scripts/opencode_pipeline.sh` remove circuit breaker logic without justification
19. No verification that tooltips are accessible to screen readers
20. No verification that interactive indicators have clear visual affordances
21. No verification that tooltips fit within existing header space
22. No human review of tooltip copy as required by acceptance criteria
23. No backend tests for the new tooltip functionality
24. No E2E tests for the tooltip interactions