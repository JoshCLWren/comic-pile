## Changelog

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
