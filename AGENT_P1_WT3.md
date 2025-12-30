AGENT ASSIGNMENT - Phase 1, Worktree p1-wt3
============================================

Phase: 1 (Cleanup & FastAPI Setup)
Worktree: comic-pile-p1-wt3 (create this)
Branch: phase/1-cleanup-fastapi-setup
Dependencies: Tasks 1.1-1.4 completed

TASK 1.5: Remove old template code
Status: pending

Instructions:
- Delete: main.py (no longer needed for FastAPI web app)
- Delete: comic_pile/core.py (template code, will create new app structure later)
- Keep: comic_pile/__init__.py (we added exports)
- Commit: feat(1.5): remove old template code

QUALITY CHECKS:
1. pytest --cov=comic_pile --cov-fail-under=96
2. bash scripts/lint.sh
3. pyright .

UPDATE TASKS.md after completing task.

TASK 1.6: Update Makefile for FastAPI
Status: pending

Instructions:
- Already partially updated with workflow targets
- Need to remove cdisplayagain-related targets:
  - Remove: profile-cbz, profile-cbr, run, smoke
  - Remove: clean-build, build, build-onedir
  - Remove: install, install-bin, install-desktop, mime-query, redo
  - Remove: ci-test-local, ci-test-debian, ci-build-image, ci-check
- Already added: dev, seed, migrate, worktrees, status
- Keep: help, init, lint, pytest, sync, venv, install-githook, githook
- Commit: feat(1.6): update Makefile for FastAPI (remove cdisplayagain targets)

QUALITY CHECKS:
1. bash scripts/lint.sh
2. pyright .

UPDATE TASKS.md after completing task.
