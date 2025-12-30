AGENT ASSIGNMENT - Phase 1, Worktree p1-wt5
============================================

Phase: 1 (Cleanup & FastAPI Setup)
Worktree: comic-pile-p1-wt5 (create this)
Branch: phase/1-cleanup-fastapi-setup
Dependencies: Tasks 1.1-1.8 completed

TASK 1.9: Rewrite CONTRIBUTING.md
Status: pending

Instructions:
- File: CONTRIBUTING.md
- Remove all cdisplayagain references
- Add FastAPI development workflow:
  - Run server: uvicorn app.main:app
  - API docs at /docs
  - HTMX for frontend interactivity
  - Jinja2 for templates
  - Tailwind CSS for styling
- Add testing guidelines:
  - pytest for tests
  - httpx.AsyncClient for API integration tests
  - 96% coverage requirement maintained
- Keep: Pre-commit hook, ruff, pyright
- Commit: feat(1.9): rewrite CONTRIBUTING.md for FastAPI + HTMX

QUALITY CHECKS:
1. bash scripts/lint.sh
2. pyright .

UPDATE TASKS.md after completing task.

TASK 1.10: Update README.md
Status: pending

Instructions:
- File: README.md
- Update description: "Dice-Driven Comic Reading Tracker - FastAPI + HTMX + Tailwind CSS"
- Remove comic viewer references
- Add tech stack section:
  - FastAPI (backend)
  - HTMX (frontend interactivity)
  - Jinja2 (templating)
  - Tailwind CSS (styling)
  - SQLAlchemy + Alembic (database)
  - SQLite (storage)
- Update quick start:
  - uv sync --all-extras
  - make dev (run server)
  - API docs: http://localhost:8000/docs
- Update development section:
  - make run tests
  - make lint
  - make seed (Faker data)
- Keep: Python 3.13, 96% coverage, pre-commit hook
- Commit: feat(1.10): update README for FastAPI app

QUALITY CHECKS:
1. bash scripts/lint.sh
2. pyright .

UPDATE TASKS.md after completing task.

PHASE COORDINATOR NOTES
=======================

When all tasks (1.1-1.10) are marked ✅ in TASKS.md:

1. Review all worktrees (should be clean or have commits)
2. Run quality checks:
   - make pytest
   - make lint
   - pyright .
3. Ensure no # type: ignore, # noqa in code
4. Merge phase to main:
   - git checkout main
   - git merge --no-ff phase/1-cleanup-fastapi-setup
   - git push origin main
5. Clean up worktrees:
   - make cleanup-phase1
6. Update TASKS.md merge history
7. Proceed to Phase 2: make create-phase2
