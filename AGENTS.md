# Repository Guidelines

## Project Ethos
- **Minimal dependencies:** Keep the stack lean with FastAPI, SQLAlchemy, and standard library where possible.
- **Mobile-first UX:** Design touch-friendly interfaces with large buttons and responsive layouts.
- **Respect data integrity:** Never lose user data, validate inputs, and provide clear error messages.
- **Prefer clarity over cleverness:** Write explicit helpers, document design decisions in pull requests, and leave the code approachable for hobbyist contributors.

## Environment Variable: RALPH_MODE

When `RALPH_MODE=true`, agents operate in Ralph mode:
- No manager/worker protocols
- Autonomous iteration only
- Direct file edits, tests, commits
- Work from GitHub Issues, not Task API

When `RALPH_MODE=false` or unset:
- Full manager/worker coordination system
- Workers claim tasks via API
- Manager daemon coordinates and reviews
- Use existing workflows

### GitHub Integration (Ralph Mode)

Ralph mode uses GitHub Issues as single source of truth:

**Requirements:**
- `GITHUB_TOKEN`: Personal Access Token with `repo` scope
- `GITHUB_REPO`: Repository name (default: anomalyco/comic-pile)

**Features:**
- No file corruption (Git-backed)
- Email notifications (built-in)
- Audit trail (issue history)
- Collaboration (comments, mentions)
- Accessible from anywhere
- Better search (GitHub UI)
- Auto-backup (Git history)

See `docs/RALPH_GITHUB_SETUP.md` for complete setup guide.

### How to Use

```bash
# Ralph mode (single agent, autonomous)
export RALPH_MODE=true
python scripts/ralph_orchestrator.py

# Manager/worker mode (multi-agent coordination)
export RALPH_MODE=false
python agents/manager_daemon.py &
# Then launch workers normally
```

### Agent Behavior

| RALPH_MODE | Behavior |
|-------------|----------|
| `true` | Read docs/RALPH_MODE.md, iterate autonomously, complete tasks one by one |
| `false` | Follow WORKER_WORKFLOW.md, claim via Task API, coordinate with manager |

### Checking RALPH_MODE

Agents should detect RALPH_MODE at start:

```python
import os

RALPH_MODE = os.getenv("RALPH_MODE", "false").lower() == "true"

if RALPH_MODE:
    # Ralph mode behavior
    print("🔄 Entering Ralph mode")
    print("   Reading: docs/RALPH_MODE.md")
    # Autonomous iteration, no coordination
else:
    # Manager/worker mode behavior
    print("📋 Entering manager/worker mode")
    print("   Reading: WORKER_WORKFLOW.md")
    # Full coordination system
```

### Ralph Ownership and Quality Control

**CRITICAL:** Ralph mode agents own the entire task lifecycle and must meet strict quality standards.

**Ownership Requirements:**
- **Direct accountability:** You are responsible for completing the task end-to-end
- **No delegation:** Do not create subtasks or delegate work
- **Self-correction:** Fix all failures yourself through iteration
- **Complete work:** Continue until all tests pass and linting is clean

**Quality Control Gates:**
- All code must pass `make lint` (ruff, pyright, ESLint, htmlhint)
- All tests must pass with 90%+ coverage (configured in pyproject.toml)
- No type/linter ignores allowed (`# type: ignore`, `# noqa`, etc.)
- Pre-commit hook will block commits with quality violations
- Regression tests required for all bug fixes

**Code Standards Are Strict:**
- Follow PEP 8 spacing (4 spaces, 100-character soft wrap)
- Use specific types, not `Any` (ruff ANN401 rule)
- Annotate all public functions with precise types
- Avoid code comments - prefer clear code and commit messages
- Run `make lint` after every change
- Run `pytest` when touching logic or input handling

**Reference:** See `docs/RALPH_MODE.md` for complete Ralph mode philosophy and workflow patterns.

## Tech Stack
- **Backend:** FastAPI (Python 3.13)
- **Database:** PostgreSQL with SQLAlchemy ORM
- **Migrations:** Alembic
- **Frontend:** React + Vite
- **Styling:** Tailwind CSS
- **Testing:** pytest with httpx.AsyncClient for API tests, httpx for E2E tests
- **Code Quality:** ruff linting, pyright type checking, ESLint (JS), htmlhint (HTML), 96% coverage requirement

## Project Structure & Module Organization
```
comic-pile/
├── app/                    # FastAPI application
│   ├── __init__.py
│   ├── main.py            # FastAPI app factory
│   ├── api/               # API route handlers
│   ├── models/            # SQLAlchemy database models
│   ├── schemas/           # Pydantic request/response schemas
│   └── templates/         # React components
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
2. Run `npm install` to install JavaScript linting tools (ESLint, htmlhint)
3. Run `make migrate` to create the database schema
4. Run `make seed` to populate sample data (optional)
5. Run `make dev` to start the development server
6. Open http://localhost:8000 to view the app
7. Open http://localhost:8000/docs to view API documentation

## Git Worktrees (Parallel Work)
Use git worktrees to work on multiple phases in parallel without branch conflicts:

### Creating Worktrees
```bash
# Create a branch
git checkout -b phase/2-database-models

# Add a worktree for that branch
git worktree add ../comic-pile-p2 phase/2-database-models

# Work in the worktree
cd ../comic-pile-p2
```

### Working in Worktrees
- Run tests and linting in the worktree
- Commit changes in the worktree
- Keep the branch updated: `git fetch && git rebase origin/main`

### Removing Worktrees
```bash
# When work is complete and merged
cd /home/josh/code/comic-pile  # Return to main repo
git worktree remove ../comic-pile-p2
git worktree prune
```

### Agent Workflow for Worktrees
**CRITICAL:** For worker agents using Task API:
- Create worktree after claiming a task
- **Keep worktree alive until task status becomes `done`**
- Manager daemon needs worktree to review and merge tasks marked `in_review`
- Only remove worktree after daemon successfully merges to main
- See WORKER_WORKFLOW.md for complete agent workflow

### Limits
- WIP limit: 3 active worktrees maximum (per AGENTS.md guidelines)

## Test Coverage Requirements
- Current target: 90% coverage threshold (configured in `pyproject.toml` with `--cov-fail-under=90`)
- Always run `pytest --cov=comic_pile --cov-report=term-missing` to check missing coverage
- When touching logic or input handling, ensure tests are added to maintain coverage
- Strategies for increasing coverage:
  - Add tests for remaining uncovered edge cases
  - Add tests for complex error handling paths
  - Add tests for API endpoints with httpx.AsyncClient
  - Add tests for business logic (dice ladder, queue management, session detection)
- To check coverage for specific files/modules: `pytest --cov=comic_pile --cov-report=term-missing <test_file>`

## API-First Development Guidelines
- Design REST endpoints with clear request/response schemas using Pydantic
- Use FastAPI's automatic OpenAPI documentation at `/docs`
- Test endpoints independently with httpx.AsyncClient before building UI
- Keep business logic in separate modules, not in route handlers
- Use database models for persistence, Pydantic schemas for API contracts

## Frontend Development Guidelines
- Keep React components in `app/templates/` with JSX syntax
- Use Tailwind CSS for styling (CDN or compiled)
- Design mobile-first with touch targets ≥44px
- Use semantic HTML for accessibility

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
- ESLint for JavaScript files (static/js/*.js)
- htmlhint for HTML templates (app/templates/*.html)

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

### Regression Test Patterns

**When fixing bugs, always add regression tests following these patterns:**

1. **Backend/API Bugs (e.g., BUG-205)**: Add API tests using `httpx.AsyncClient` to verify the bug is fixed and won't regress. Example: `test_get_session_current_uses_selected_thread_id`

2. **Frontend/Visual Bugs (e.g., BUG-201, BUG-202, BUG-203, BUG-206)**: These are harder to test automatically. Options:
   - Use Playwright for functional checks (e.g., dice displays correct numbers)
   - Verify backend API behavior covers the bug scenario
   - Document the bug and fix in commit message for future reference
   - Manual verification via browser testing may be required

3. **UX Improvement Bugs (e.g., BUG-203 - font size)**: These are subjective improvements. Regression testing via automated tests is difficult. Focus on:
   - Backend API tests for related functionality
   - Commit messages documenting the change
   - Manual verification during code review

## Agent System Documentation

For detailed agent workflow documentation, see:

### Manager Agent
- **MANAGER-7-PROMPT.md** - Manager agent coordination prompt with active monitoring and task handling
- **MANAGER_DAEMON.md** - Manager daemon responsibilities, setup, and integration with Worker Pool Manager
- **WORKFLOW_PATTERNS.md** - Proven successful patterns and critical failures to avoid from manager sessions

### Worker Agents
- **WORKER_WORKFLOW.md** - Complete end-to-end workflow for worker agents using Task API (READ THIS FIRST)
- **worker-pool-manager-prompt.txt** - Worker Pool Manager agent prompt for automated worker spawning

### Key Principles
- Always use Task API for all work
- Trust the Task API state
- Active monitoring (not passive claims)
- Delegate immediately, never investigate yourself
- Worker reliability management
- Worktree management
- Manager daemon integration
- Merge conflict handling
- Browser testing delegation
