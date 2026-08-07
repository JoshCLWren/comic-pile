# Changelog fragments

User-facing pull requests add one Markdown fragment instead of editing `docs/changelog.md`.

Name each fragment `YYYY-MM-DD-<pr-number>.md`, for example:

```markdown
## 2026-08-06

**Factory reliability**

- Release notes now use merge-friendly fragments so parallel pull requests do not collide ([#883](https://github.com/JoshCLWren/comic-pile/pull/883)).
```

Rules:

- One fragment per pull request.
- The filename date must match the first heading.
- The fragment must link its pull request.
- Keep the entry user-facing and explain why the change matters.
- Do not edit the historical `docs/changelog.md` archive for ordinary new work.
- Use `Changelog: not user-facing` only for genuinely internal changes.

The Vite changelog plugin validates and combines all fragments before the frozen archive, newest first, into the existing static `/changelog.md` asset.
