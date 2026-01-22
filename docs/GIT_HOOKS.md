# Git Hooks Setup

This repository uses git hooks to enforce code quality checks.

## Available Hooks

### Pre-Commit Hook
Runs automatically before each commit.

**What it does:**
- Runs `bash scripts/lint.sh` to check code quality

**What it checks:**
- Python syntax
- Ruff linting
- Any type usage (ruff ANN401)
- ty type checking (ty check --error-on-warning).
- ESLint for JavaScript
- htmlhint for HTML templates

**What happens on failure:**
- Commit is aborted
- You'll see which linting step failed
- Can bypass with `git commit --no-verify` (not recommended)

### Pre-Push Hook
Runs automatically before each push to remote.

**What it does:**
- Runs `pytest --cov=comic_pile` with 96% coverage requirement

**What it checks:**
- All tests pass
- Test coverage meets 96% threshold

**What happens on failure:**
- Push is aborted
- You'll see which tests failed
- Can bypass with `git push --no-verify` (not recommended)

## Installation

Clone the repository and run:

```bash
bash scripts/install-git-hooks.sh
```

This copies the hooks from `.githooks/` to `.git/hooks/`.

## Manual Installation

If you need to install hooks manually, copy them from `.githooks/` to `.git/hooks/`:
- `.githooks/pre-commit` → `.git/hooks/pre-commit`
- `.githooks/pre-push` → `.git/hooks/pre-push`

Make them executable:
```bash
chmod +x .git/hooks/pre-commit .git/hooks/pre-push
```

## Bypassing Hooks

**Not recommended**, but if you need to bypass:

```bash
# Bypass pre-commit hook
git commit --no-verify

# Bypass pre-push hook
git push --no-verify
```

## Why Hooks Exist

These hooks prevent broken code from being committed or pushed:
- Catches linting errors locally before CI
- Catches test failures locally before CI
- Reduces CI/CD failures
- Faster feedback loop (local vs remote)

## Note on Hooks and Git

The hooks in `.git/hooks/` are not tracked by git. When other developers clone the repository, they need to run the installation script to set up their local hooks.
