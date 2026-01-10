AGENT ASSIGNMENT - Phase 1, Worktree p1-wt4
============================================

Phase: 1 (Cleanup & FastAPI Setup)
Worktree: comic-pile-p1-wt4 (create this)
Branch: phase/1-cleanup-fastapi-setup
Dependencies: Tasks 1.1-1.6 completed

TASK 1.7: Update CI workflow
Status: pending

Instructions:
- File: .github/workflows/ci.yml
- Remove Tkinter dependencies: libvips, python3-tk, unar, xvfb
- Update: Remove python3-tk from CI setup action
- Update: Test command to pytest (no xvfb needed)
- Update coverage package name: example_module → comic_pile
- Keep: pytest, ruff, pyright
- Commit: feat(1.7): update CI workflow for FastAPI (remove Tkinter/unnar)

QUALITY CHECKS:
1. bash scripts/lint.sh
2. pyright .

UPDATE TASKS.md after completing task.

TASK 1.8: Rewrite AGENTS.md
Status: pending

Instructions:
- File: AGENTS.md
- Remove all cdisplayagain references
- Remove Tkinter/archive handling references
- Add FastAPI development guidelines:
  - API-first development
  - HTMX for interactivity
  - Tailwind CSS for styling
  - SQLAlchemy for database
  - Alembic for migrations
- Add project structure for FastAPI app
- Keep: Python 3.13, ruff, pyright, 96% coverage
- Commit: feat(1.8): rewrite AGENTS.md for FastAPI + HTMX

QUALITY CHECKS:
1. bash scripts/lint.sh
2. pyright .

UPDATE TASKS.md after completing task.
