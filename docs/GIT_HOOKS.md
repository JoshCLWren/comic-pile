# Git Hooks Setup

This repository uses git hooks to enforce code quality checks.

## Principle: fix what hooks flag

Hooks run fast static checks (lint/format/types). Product test suites are not
run in git hooks; CI is the test gate. If a hook blocks you, fix the lint
failure. Never use `--no-verify` or otherwise bypass a hook: `AGENTS.md` and
`docs/ISSUE_EXECUTION_PROTOCOL.md` prohibit it. Fix the failure, push, and let
CI run the product tests. Never force-push or push to main.

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
- Fix the failure and commit again; do not bypass the hook

### Pre-Push Hook
Runs automatically before each push to remote.

**What it does:**
- Runs `bash scripts/lint.sh` (full-repo ruff + ty + frontend lint)

Product test suites do not run on push: no vitest, no rendered UI audit, and no
backend pytest. CI runs those. The Python lint gate still runs its static
hardcoded-ID guard (`pytest tests/test_hardcoded_ids.py`); see `AGENTS.md`,
"Full-repo ruff, ty, and hardcoded-ID guard before every Python push".

**What happens on failure:**
- Push is aborted
- You'll see which check failed
- Fix the failure and push again; do not bypass the hook

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

Do not bypass hooks. `AGENTS.md` and `docs/ISSUE_EXECUTION_PROTOCOL.md` prohibit
`--no-verify` and equivalent suppressions because a bypass hides real lint
failures from the only local gate. Fix the reported failure, then commit or push.

## Why Hooks Exist

These hooks prevent broken code from being committed or pushed:
- Catches linting errors locally before CI
- Reduces CI/CD failures
- Faster feedback loop (local vs remote)

## Note on Hooks and Git

The hooks in `.git/hooks/` are not tracked by git. When other developers clone the repository, they need to run the installation script to set up their local hooks.
