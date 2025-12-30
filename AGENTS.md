# Repository Guidelines

## Project Ethos
- **API-first design:** Build clear, documented REST endpoints that can serve both HTMX and future native clients.
- **Minimal dependencies:** Keep the stack lean with FastAPI, SQLAlchemy, and standard library where possible.
- **Mobile-first UX:** Design touch-friendly interfaces with large buttons and responsive layouts.
- **Respect data integrity:** Never lose user data, validate inputs, and provide clear error messages.
- **Prefer clarity over cleverness:** Write explicit helpers, document design decisions in pull requests, and leave the code approachable for hobbyist contributors.

## Tech Stack
- **Backend:** FastAPI (Python 3.13)
- **Database:** SQLite with SQLAlchemy ORM
- **Migrations:** Alembic
- **Frontend:** HTMX + Jinja2 templates
- **Styling:** Tailwind CSS
- **Testing:** pytest with httpx.AsyncClient for API tests
- **Code Quality:** ruff linting, pyright type checking, 96% coverage requirement

## Project Structure & Module Organization
```
comic-pile/
├── app/                    # FastAPI application
│   ├── __init__.py
│   ├── main.py            # FastAPI app factory
│   ├── api/               # API route handlers
│   ├── models/            # SQLAlchemy database models
│   ├── schemas/           # Pydantic request/response schemas
│   └── templates/         # Jinja2 templates
├── scripts/               # Utility scripts (seed data, etc.)
├── tests/                 # pytest test suite
├── static/                # Static assets (CSS, JS)
└── migrations/            # Alembic migration files
```

## Build, Test, and Development Commands
- `source .venv/bin/activate`: activate the virtual environment (do this once per session).
- `uv sync --all-extras`: install dependencies via uv.
- `make dev`: run FastAPI dev server with hot reload (uvicorn app.main:app --reload).
- `pytest`: run tests.
- `make pytest`: run the test suite with coverage.
- `make lint`: run ruff and pyright.
- `make seed`: populate database with Faker sample data.
- `make migrate`: run Alembic migrations (alembic upgrade head).

## Getting Started
1. Run `uv sync --all-extras` to install all dependencies
2. Run `make migrate` to create the database schema
3. Run `make seed` to populate sample data (optional)
4. Run `make dev` to start the development server
5. Open http://localhost:8000 to view the app
6. Open http://localhost:8000/docs to view API documentation

## Git Worktrees (Parallel Work)
Use git worktrees to work on multiple phases in parallel without branch conflicts:
- Create a branch per phase: `git switch -c phase/2-database-models`
- Add a worktree: `git worktree add ../comic-pile-p2 phase/2-database-models`
- Work only in that worktree for the phase; run tests there.
- Keep the branch updated: `git fetch` then `git rebase origin/main` (or merge).
- When merged, remove it: `git worktree remove ../comic-pile-p2`
- Clean stale refs: `git worktree prune`
- WIP limit: 3 phases total in progress across all worktrees.

## Test Coverage Requirements
- Current target: 96% coverage threshold (configured in `pyproject.toml`)
- Always run `pytest --cov=comic_pile --cov-report=term-missing` to check missing coverage
- When touching logic or input handling, ensure tests are added to maintain coverage
- Strategies for increasing coverage:
  - Add tests for remaining uncovered edge cases
  - Add tests for complex error handling paths
  - Add tests for API endpoints with httpx.AsyncClient
  - Add tests for business logic (dice ladder, queue management, session detection)

## API-First Development Guidelines
- Design REST endpoints with clear request/response schemas using Pydantic
- Use FastAPI's automatic OpenAPI documentation at `/docs`
- Test endpoints independently with httpx.AsyncClient before building UI
- Keep business logic in separate modules, not in route handlers
- Use database models for persistence, Pydantic schemas for API contracts

## Frontend Development Guidelines
- Use HTMX for interactivity (AJAX requests without writing JavaScript)
- Keep templates in `app/templates/` with Jinja2 syntax
- Use Tailwind CSS for styling (CDN or compiled)
- Design mobile-first with touch targets ≥44px
- Use semantic HTML for accessibility
- Minimize custom JavaScript - prefer HTMX attributes

## Database Development Guidelines
- Define SQLAlchemy models in `app/models/`
- Use Alembic for all schema changes: `alembic revision --autogenerate -m "description"`
- Run migrations: `make migrate` or `alembic upgrade head`
- Use Pydantic schemas for API validation in `app/schemas/`
- Keep database operations in service layer, not in route handlers

## Coding Style & Naming Conventions
Follow standard PEP 8 spacing (4 spaces, 100-character soft wrap) and favor descriptive snake_case for functions and variables. Use Pydantic dataclasses and SQLAlchemy models for typed data containers. Keep public functions annotated with precise types.

Ruff configuration (from `pyproject.toml`):
- Line length: 100 characters
- Python version: 3.13
- Enabled rules: E, F, I, N, UP, B, C4, D, ANN401
- Ignored: D203, D213, E501
- Code comments are discouraged - prefer clear code and commit messages

## Pre-commit Hook
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

## Code Quality Standards
- Run linting after each change:
  - `make lint` or `bash scripts/lint.sh`
- Use specific types instead of `Any` in type annotations (ruff ANN401 rule)
- Run tests when you touch logic or input handling:
  - `pytest`
- Always write a regression test when fixing a bug.
- If you break something while fixing it, fix both in the same PR.
- Do not use in-line comments to disable linting or type checks.
- Do not narrate your code with comments; prefer clear code and commit messages.

## Branch Workflow
- Always create a phase branch from `main` before making changes:
  - `git checkout main && git checkout -b phase/2-database-models`
- Use descriptive branch names like `phase/2-database-models`
- When phase is complete, merge to main via the merge-phaseX make target

## Testing Guidelines
- Automated tests live in `tests/` and run with `pytest` (or `make pytest`).
- When adding tests, keep `pytest` naming like `test_dice_ladder_step_up`.
- Use httpx.AsyncClient for API integration tests
- Use fixtures from `conftest.py` for shared test setup
- Test both success and error paths for all API endpoints
- Test business logic (dice ladder, queue management, session detection) independently
