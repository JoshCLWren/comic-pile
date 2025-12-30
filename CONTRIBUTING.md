# Contributing

Thanks for contributing to cdisplayagain. This project values a fast, lightweight
viewer and clear, approachable code. Please follow the checks below for any code
change.

## Pre-commit hook

A pre-commit hook is installed in `.git/hooks/pre-commit` that automatically runs:
- Check for type/linter ignores in staged files
- Run the shared lint script (`scripts/lint.sh`)

The lint script runs:
- Python compilation check
- Ruff linting
- Any type usage check (ruff ANN401 rule)
- Pyright type checking

The hook will block commits containing `# type: ignore`, `# noqa`, `# ruff: ignore`, or `# pylint: ignore`.

To test the hook manually: `make githook` or `bash scripts/lint.sh`

## Code quality standards

- Run linting after each change:
  - `make lint` or `bash scripts/lint.sh`
- Use specific types instead of `Any` in type annotations (ruff ANN401 rule)
- Run tests when you touch logic or input handling:
  - `uv run python -m pytest`
- Perform manual smoke checks (CBZ + CBR) before sharing UI changes:
  - Open a sample archive, page through images, toggle fit/zoom, and confirm
    temporary directories are cleaned.
- Always write a regression test when fixing a bug.
- If you break something while fixing it, fix both in the same PR.
- Do not check in sample comics or proprietary content.
- Do not use in-line comments to disable linting or type checks.
- Do not narrate your code with comments; prefer clear code and commit messages.
- Do not use `pytest.skip` in test files; all tests must run in CI.

## Style guidelines

- Keep helpers explicit and descriptive (snake_case), and annotate public
  functions with precise types.
- Avoid shell-specific shortcuts; prefer Python APIs and `pathlib.Path` helpers.
- Do not mutate archives or leave temporary files behind.

## Branch workflow

- Always create a feature branch from `main` before making changes:
  - `git checkout -b feature-name`
  - Use descriptive names like `fix-zoom-bug` or `add-cbr-support`
- Push the feature branch to create a pull request
- After your PR is merged, update your local `main`:
  - `git checkout main`
  - `git pull`
  - Delete the merged branch: `git branch -d feature-name`

## Pull request guidelines

- Use imperative, component-scoped commit messages (e.g., "Add CBR extraction error copy")
- Bundle related changes per commit
- PR summary should describe user impact and testing performed
- Attach screenshots when UI is affected
