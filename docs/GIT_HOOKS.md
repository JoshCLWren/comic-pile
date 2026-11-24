# Git hooks

The repository installs local pre-commit, pre-push and prepare-commit-msg hooks.
They are a fast local gate, not a replacement for required CI.

## Never bypass hooks

**Never use `git commit --no-verify` or `git push --no-verify`.** Do not skip,
disable or weaken a hook to avoid fixing a failure. Fix the code, test or tooling
problem and rerun the check.

## Installation and prerequisites

```bash
make sync                              # Python tooling environment
pnpm install --frozen-lockfile
bash scripts/install-git-hooks.sh
```

The installer preserves pre-existing hooks under
`.git/hooks/comic-pile-originals/`. Cursor Cloud can remap `core.hooksPath`; rerun
the installer so its dispatcher can chain to the installed hooks.

## Pre-commit

`.githooks/pre-commit` blocks staged dependency directories, backup artifacts and
Python ignore comments, then runs `bash scripts/lint.sh --staged`.

The shared lint script currently checks Python syntax, prohibited ignore/`Any`
patterns and relevant frontend ESLint. It does **not** run Ruff or ty. Before a
Python push, run the required whole-repository pair directly:

```bash
ruff check .
ty check --error-on-warning
```

Path-filtered Ruff or ty is not a valid CI substitute.

## Pre-push

`.githooks/pre-push` requires the Python tooling environment and pnpm, then runs:

1. `bash scripts/lint.sh`.
2. Frontend unit tests (`cd frontend && pnpm test`).
3. The rendered Chromium UI audit (`pnpm run audit:ui`).

A successful verification stamp can suppress duplicate work for the same HEAD
for one hour. Full Rust/backend suites, aggregate coverage and product Playwright
suites remain CI responsibilities; run focused local tests for changed behavior.

## Prepare-commit-msg

When `OPENCODE_MODEL` is set, the hook adds the producing model trailer used by
factory provenance. Do not fabricate or edit provenance markers.

## Manual validation

```bash
bash scripts/lint.sh --staged   # approximate pre-commit scope
bash scripts/lint.sh            # shared lint script
ruff check .
ty check --error-on-warning
```

Hooks live in the working tree's Git common directory and are not cloned with
the repository. Reinstall them in each checkout/worktree as required.
