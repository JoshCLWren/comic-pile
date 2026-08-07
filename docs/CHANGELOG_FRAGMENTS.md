# Changelog fragment workflow

ComicPile keeps historical release notes in `docs/changelog.md`, but new pull requests do not edit that shared archive.

For each user-facing product, behavior, deployment, operational, or factory-tooling pull request:

1. Create `docs/changelog.d/YYYY-MM-DD-<pr-number>.md`.
2. Start the file with `## YYYY-MM-DD` matching the filename.
3. Add a user-recognizable feature-area heading.
4. Add a short bullet explaining what changed and why it matters.
5. Link the pull request using its actual number.

The Vite build validates every fragment, sorts fragments newest-first, rejects duplicate PR numbers, and prepends them to the frozen historical archive when producing `/changelog.md` for the What’s New page.

Documentation-only, test-only, generated-artifact-only, or strictly internal refactors may omit a fragment only when the pull request body explicitly states `Changelog: not user-facing`.
