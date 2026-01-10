AGENT ASSIGNMENT - Phase 1, Worktree p1-wt2
============================================

Phase: 1 (Cleanup & FastAPI Setup)
Worktree: comic-pile-p1-wt2 (create this)
Branch: phase/1-cleanup-fastapi-setup
Dependencies: Tasks 1.1-1.2 completed

TASK 1.3: Update pyproject.toml package name
Status: pending

Instructions:
- File: pyproject.toml
- Change: name = "comic-pile" → name = "comic_pile"
- Also update: line 23 in coverage config (coverage source)
- Change line 30: comic_pile (for coverage reporting)
- Test: Run uv sync to verify no conflicts
- Commit: feat(1.3): update pyproject.toml package name to comic_pile

QUALITY CHECKS (Before marking complete):
1. pytest --cov=comic_pile --cov-fail-under=96
2. bash scripts/lint.sh
3. pyright .

UPDATE TASKS.md after completing task.

TASK 1.4: Add FastAPI dependencies
Status: pending

Instructions:
- File: pyproject.toml
- Add to dependencies: fastapi, uvicorn[standard], sqlalchemy, alembic, jinja2
- Add to dev dependencies: pydantic, faker, httpx
- Run: uv sync --all-extras
- Test: Verify imports work
  - python -c "import fastapi"
  - python -c "import uvicorn"
  - python -c "import sqlalchemy"
  - python -c "import alembic"
  - python -c "import jinja2"
  - python -c "import pydantic"
  - python -c "import faker"
  - python -c "import httpx"
- Commit: feat(1.4): add FastAPI and related dependencies

QUALITY CHECKS:
1. pytest --cov=comic_pile --cov-fail-under=96
2. bash scripts/lint.sh
3. pyright .

UPDATE TASKS.md after completing task.
