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

## Agent Workflow Patterns (Proven to Work)

Based on manager-1, manager-2, manager-3 retrospectives:

### Successful Patterns:

1. **Always Use Task API for All Work**
   - Never make direct file edits, even for small fixes
   - Create tasks for everything (bug fixes, features, investigations, testing)
   - Workers claim tasks before starting work
   - 409 Conflict prevents duplicate claims automatically

2. **Trust the Task API State**
   - Query `/api/tasks/ready` for available work (respects dependencies)
   - Query `/api/tasks/{task_id}` for current status
   - Let status_notes be visibility into worker progress
   - Task API enforces one-task-per-agent via 409 Conflict

3. **Active Monitoring (Not Passive Claims)**
   - Set up continuous monitoring loops that check task status every 2-5 minutes
   - Watch for stale tasks (no heartbeat for 20+ minutes)
   - Watch for blocked tasks that need unblocking
   - Respond quickly when workers report issues
   - Don't wait for user to prompt "keep polling" - monitor proactively

4. **Delegate Immediately, Never Investigate Yourself**
   - When user reports any issue, create a task INSTANTLY
   - NEVER investigate issues yourself - you're a coordinator, not an executor
   - Workers complete tasks faster than manager investigating manually
   - Examples of what to delegate:
     - "Website slow" → Create performance investigation task
     - "d10 looks horrible" → Create d10 geometry fix task
     - "404 errors" → Create task to investigate and fix
     - "Open browser and test" → Create task for testing

5. **Worker Reliability Management**
   - Monitor worker health closely (heartbeat, status updates)
   - Relaunch proactively when issues arise (no heartbeat for 20+ minutes)
   - Check for heartbeat failures
   - If worker reports blockers multiple times, intervene and ask if they need help
   - Maximum 3 concurrent workers

6. **Worktree Management**
   - Create all worktrees at session start before launching workers
   - Verify each worktree exists and is on correct branch
   - Before accepting task claim, check: `git worktree list | grep <worktree-path>`
   - Only accept claim if worktree exists and path is valid
   - After task completion, worker removes worktree

7. **Manager Daemon Integration**
   - Manager daemon runs continuously and automatically:
     - Reviews and merges in_review tasks
     - Runs pytest and make lint
     - Detects stale workers (20+ min no heartbeat)
     - Stops when all tasks done and no active workers
   - NO need to manually click "Auto-Merge All In-Review Tasks" button
   - Only intervene when tasks marked `blocked` (conflicts or test failures)

8. **Merge Conflict Handling**
   - Expect conflicts when multiple workers modify same file
   - Use `git checkout --theirs --ours` to accept both changes
   - Test after resolution to ensure nothing was lost
   - Commit with clear resolution message
   - All conflicts successfully resolved in manager-1 and manager-3

9. **Browser Testing Delegation**
   - NEVER attempt browser testing or manual testing yourself
   - Create a task: "Open browser and test [feature]" with clear test cases
   - Delegate to worker agent
   - Worker opens browser and performs testing
   - Worker reports findings in status notes
   - Managers coordinate, workers execute

### Failed Patterns to Avoid:

1. **NO Active Monitoring**
   - Don't just claim to monitor - actually set up polling loops
   - Don't wait for user to say "keep polling"
   - Manager-3 failed this and lost productivity

2. **Direct File Edits Before Delegation**
   - Don't investigate issues yourself (coordinator 404, d10 geometry, etc.)
   - Don't make direct file edits for any work, no matter how small
   - Manager-2 initially failed this, then corrected
   - Manager-3 failed this repeatedly

3. **Worker Pool Manager Role Violation**
   - Worker Pool Manager NEVER reviews or merges tasks
   - Manager-daemon.py handles ALL reviewing and merging
   - NEVER trust worker claims without verification
   - Workers can and will lie about "tests pass, linting clean"
   - Worker Pool Manager retrospective shows CRITICAL FAILURE from merging broken code

4. **Ad-Hoc Worktree Creation**
   - Don't create worktrees after tasks are claimed
   - Don't allow tasks to be claimed without verifying worktree exists
   - Create all worktrees at session start
   - Manager-3 failed this with 404 errors during reassignment
