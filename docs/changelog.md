## Changelog

- 2026-03-27: Prevent GitHub Projects (classic) GraphQL API usage (closes #363).
  - Add documentation for GitHub API deprecation in `docs/github_api_deprecation.md`
  - Include preventive measures to avoid future deprecated API usage
  - Add protective comments in GitHub migration scripts
  - Update development guidelines to include GitHub API monitoring best practices

- 2026-03-27: Fix Roll Pool UI for blocked threads (closes #363).
  - Make the blocked-threads section expandable and clearly describe blocking
    reasons by rendering text like "blocked by <reason>" alongside thread titles.
  - Improve accessibility labels to reflect blocking context.
