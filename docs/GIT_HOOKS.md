# Git Hooks Setup

This repository uses git hooks to catch local quality problems before CI.

## Never skip checks

When a hook blocks a commit or push, fix the code or the test setup. Do not use
`--no-verify`, disable the hook, or weaken a check to get past it. If a hook itself
is wrong, repair it in a reviewed change rather than bypassing it.

## Available hooks

### Pre-commit hook

Runs automatically before each commit. It:

- Blocks staged type/linter-ignore comments (`# type: ignore`, `# noqa`,
  `# ruff: ignore`, `# pylint: ignore`).
- Blocks forbidden paths such as `node_modules` and `review_critique.md`.
- Blocks backup artifacts (`*.bak`, `*.backup`, `*.orig`, `*~`). Deleting or
  untracking an already-tracked backup is allowed.
- Runs `bash scripts/lint.sh --staged`.

`scripts/lint.sh` performs Python compilation, prohibited-ignore/`Any` checks,
JavaScript/frontend ESLint, and HTML lint when applicable. It does **not** invoke
Ruff or ty.

### Pre-push hook

Runs automatically before each push. It:

1. Runs `bash scripts/lint.sh`.
2. Runs the frontend unit suite (`pnpm test` in `frontend/`).
3. Runs the rendered UI audit (`pnpm run audit:ui`).

The hook does not run Ruff, ty, Rust database tests, or the full Playwright product
suite. Run the checks appropriate to your change separately.

## Required Python CI pair

CI runs these commands over the whole repository:

```bash
ruff check .
ty check --error-on-warning
```

Path-filtered Ruff or ty is not a valid substitute. Run both after the last
Python edit and again after any later edit. ty warnings fail CI, including
`redundant-cast`.

## Installation

Clone the repository and run:

```bash
bash scripts/install-git-hooks.sh
```

This copies the hooks from `.githooks/` to `.git/hooks/`. Cursor and similar hosts
may remap `core.hooksPath`; the installer chains the dispatcher to the repository
hooks. Verify the configured path and installed hooks if a check does not run.

Python tooling and hooks need the project environment:

```bash
uv venv && uv sync --all-extras
```

`make setup` installs frontend dependencies and prepares PostgreSQL, but does not
create this Python environment.

## Manual installation

If you need to install hooks manually, copy them from `.githooks/` to `.git/hooks/`:

- `.githooks/pre-commit` → `.git/hooks/pre-commit`
- `.githooks/pre-push` → `.git/hooks/pre-push`

Make them executable:

```bash
chmod +x .git/hooks/pre-commit .git/hooks/pre-push
```

## Why hooks exist

Hooks provide fast local feedback and reduce avoidable CI failures. They are a
convenience, not proof that every required check ran. A green hook does not replace
focused tests, the full-repo Ruff/ty pair, required CI, or independent review.

The hooks in `.git/hooks/` are not tracked by Git. After cloning, run the
installation script to set them up.
