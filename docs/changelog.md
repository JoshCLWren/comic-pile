## Changelog

- 2026-03-27: Expandable blocked threads section with detailed blocking reasons (closes #363).
- Roll pool now shows "N threads hidden (blocked by dependencies)" as expandable section
- Expanded view displays each blocked thread with primary blocking reason
- Threads link to queue page with highlighting for easy navigation
- Mobile-friendly design with touch targets ≥44px and scrollable list
- Section hidden entirely when no threads are blocked

- 2026-03-27: Add follow-up actions to roll result display (closes #363).
- Add "Mark as Read", "Skip to Next", "Archive Thread", and "Reset Thread" buttons
- Fix missing undoApi import in RollPage component
- Remove unused showBlockedThreads prop from ThreadPool component

- 2026-03-27: Fix blocked threads display on roll page (closes #363).
- Fix double "blocked by" prefix in expanded blocked threads list
- Refetch blocked threads list after rating, rolling, and migration to keep
  the count and reasons up-to-date without navigating away
- Add missing `is_blocked` field to `BlockingInfoResponse` TypeScript type

- 2026-03-27: TypeScript fixes for Roll Page and Thread types (closes #363).
- Fix setSnoozedExpanded and setBlockedExpanded to accept functional updates
- Add touch_friendly field to Thread type for proper type checking

- 2026-03-27: Prevent GitHub Projects (classic) GraphQL API usage (closes #363).
- Added comment in roll.py to prevent future use of deprecated GitHub API
- Added documentation in docs/github_api_deprecation.md
- Added preventive measures to avoid future deprecated API usage
- Added protective comments in code
- Updated development guidelines to include GitHub API monitoring best practices

- 2026-03-27: Fix Roll Pool UI for blocked threads (closes #363).
- Make the blocked-threads section expandable and clearly describe blocking
 reasons by rendering text like "blocked by <reason>" alongside thread titles.
- Improve accessibility labels to reflect blocking context.
