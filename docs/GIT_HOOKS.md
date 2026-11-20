# Git Hooks Setup

This repository uses git hooks to enforce code quality checks.

## Principle: fix what hooks flag

Hooks run static checks (lint/format/types), including the Python hardcoded-ID
regression guard. Product test suites (backend pytest, Vitest, and the rendered
UI audit) run in CI rather than git hooks. If a hook blocks you, fix the
underlying failure; never bypass it with `--no-verify`. Never force-push or push
to main.

## Available Hooks

### Pre-Commit Hook
Runs automatically before each commit.

**What it does:**
- Blocks staged backup artifacts (`*.bak`, `*.backup`, `*.orig`, `*~`) — these are
  editor/LLM leftovers that never belong in version control. Deleting (untracking)
  an already-tracked backup is still allowed.
- Runs `bash scripts/lint.sh` to check code quality

**What it checks:**
- Python syntax
- Full-repo ruff linting (`ruff check .`)
- Any type usage (ruff ANN401)
- Full-repo ty type checking (`ty check --error-on-warning`)
- ESLint for JavaScript
- htmlhint for HTML templates

Path-filtered ruff or ty is not a valid CI substitute. Cursor Cloud remaps
`core.hooksPath`; run `bash scripts/install-git-hooks.sh` so the dispatcher can
still chain to `.git/hooks/pre-commit`.

**What happens on failure:**
- Commit is aborted
- You'll see which linting step failed
- Can bypass with `git commit --no-verify` (not recommended)

### Pre-Push Hook
Runs automatically before each push to remote.

**What it does:**
- Runs `bash scripts/lint.sh` (full-repo ruff + ty + frontend lint)

No tests run on push (no pytest, vitest, or UI audit). CI runs the tests.

**What happens on failure:**
- Push is aborted
- You'll see which check failed
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
- Reduces CI/CD failures
- Faster feedback loop (local vs remote)

## Note on Hooks and Git

The hooks in `.git/hooks/` are not tracked by git. When other developers clone the repository, they need to run the installation script to set up their local hooks.
