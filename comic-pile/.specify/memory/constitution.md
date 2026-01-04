# Comic Pile Constitution

**Version**: 1.0.0 | **Ratified**: 2026-01-03 | **Last Amended**: 2026-01-03

---

## Core Principles

### I. API-First Design

Build clear, documented REST endpoints that can serve both HTMX and future native clients. FastAPI automatically generates interactive API documentation at `/docs` (Swagger UI) and `/redoc`. Design REST endpoints with clear request/response schemas using Pydantic. Test endpoints independently with httpx.AsyncClient before building UI.

### II. Minimal Dependencies

Keep the stack lean with FastAPI, SQLAlchemy, and standard library where possible. Favor descriptive snake_case for functions and variables. Use Pydantic dataclasses and SQLAlchemy models for typed data containers. Never assume a library is available without checking the project's existing dependencies in pyproject.toml.

### III. Mobile-First UX

Design touch-friendly interfaces with large buttons (≥44px touch targets) and responsive layouts. Use semantic HTML for accessibility. Prefer HTMX for interactivity (AJAX requests without writing JavaScript). Minimize custom JavaScript - use HTMX attributes and Tailwind CSS instead.

### IV. Data Integrity

Never lose user data. Validate inputs and provide clear error messages. When touching logic or input handling, ensure tests are added to maintain 96% coverage. Always write a regression test when fixing a bug. If you break something while fixing it, fix both in the same PR.

### V. Clarity Over Cleverness

Write explicit helpers, document design decisions in pull requests, and leave the code approachable for hobbyist contributors. Code comments are discouraged - prefer clear code and commit messages. Follow standard PEP 8 spacing (4 spaces, 100-character soft wrap).

---

## Technology Stack

**Backend:**
- FastAPI (Python 3.13)
- Database: SQLite with SQLAlchemy ORM
- Migrations: Alembic
- Testing: pytest with httpx.AsyncClient
- Code Quality: ruff linting, pyright type checking

**Frontend:**
- HTMX + Jinja2 templates
- Tailwind CSS (CDN or compiled)
- Minimal custom JavaScript

**Coverage Requirement:** 96% threshold (configured in pyproject.toml)

---

## Development Workflow

### Build & Test Commands

```bash
source .venv/bin/activate      # Activate virtual environment (once per session)
uv sync --all-extras            # Install dependencies
make dev                        # Run FastAPI dev server with hot reload
pytest                         # Run tests
make pytest                    # Run test suite with coverage
make lint                      # Run ruff and pyright
make seed                      # Populate database with Faker sample data
make migrate                   # Run Alembic migrations (alembic upgrade head)
```

### Branch Workflow

Always create a phase branch from `main` before making changes:
```bash
git checkout main && git checkout -b phase/2-database-models
```

Use descriptive branch names like `phase/2-database-models`. When phase is complete, merge to main via the merge-phaseX make target.

### Git Worktrees (Parallel Work)

Create a branch per phase: `git switch -c phase/2-database-models`
Add a worktree: `git worktree add ../comic-pile-p2 phase/2-database-models`
Work only in that worktree for the phase; run tests there.
Keep the branch updated: `git fetch` then `git rebase origin/main`
**CRITICAL:** For agent worktrees, keep until task is merged to main (status becomes 'done'), not just when marked in_review. Manager daemon needs worktree to review and merge.
When merged, remove it: `git worktree remove ../comic-pile-p2`
Clean stale refs: `git worktree prune`
WIP limit: 3 phases total in progress across all worktrees.

---

## Agent System Principles

### Task API as Source of Truth

Always use Task API for all work. Never make direct file edits, even for small fixes. Create tasks for everything (bug fixes, features, investigations, testing). Workers claim tasks before starting work. 409 Conflict prevents duplicate claims automatically.

### Active Monitoring (Not Passive Claims)

Set up continuous monitoring loops that check task status every 2-5 minutes. Watch for stale tasks (no heartbeat for 20+ minutes). Watch for blocked tasks that need unblocking. Respond quickly when workers report issues. Don't wait for user to prompt "keep polling" - monitor proactively.

### Delegate Immediately, Never Investigate Yourself

When user reports any issue, create a task INSTANTLY. NEVER investigate issues yourself - you're a coordinator, not an executor. Workers complete tasks faster than manager investigating manually. Examples: "Website slow" → Create performance investigation task, "d10 looks horrible" → Create d10 geometry fix task.

### Manager Daemon Integration

Manager daemon runs continuously and automatically:
- Reviews and merges in_review tasks
- Runs pytest and make lint
- Detects stale workers (20+ min no heartbeat)
- Stops when all tasks done and no active workers

**DO NOT:**
- Never click "Auto-Merge All In-Review Tasks" button - daemon handles it
- Never manually merge tasks - daemon handles it
- Never run tests/linting on in_review tasks - daemon handles it

The manager must still handle blocked tasks, recover abandoned work, resolve merge conflicts, launch and coordinate workers, monitor for issues, and create new tasks.

**CRITICAL:** Never use Worker Pool Manager without manager-daemon.py running.

### Worker Reliability Management

Monitor worker health closely (heartbeat, status updates). Relaunch proactively when issues arise (no heartbeat for 20+ minutes). Check for heartbeat failures. If worker reports blockers multiple times, intervene and ask if they need help. Maximum 3 concurrent workers.

### Browser Testing Delegation

NEVER attempt browser testing or manual testing yourself. Create a task: "Open browser and test [feature]" with clear test cases. Delegate to worker agent. Worker opens browser and performs testing. Worker reports findings in status notes. Managers coordinate, workers execute.

---

## Code Quality Standards

### Pre-commit Hook

A pre-commit hook is installed in `.git/hooks/pre-commit` that automatically runs:
- Check for type/linter ignores in staged files
- Run the shared lint script (`scripts/lint.sh`)

The lint script runs:
- Python compilation check
- Ruff linting
- Any type usage check (ruff ANN401 rule - disallows `Any` type)
- Pyright type checking

**The hook will block commits containing:**
- `# type: ignore`
- `# noqa`
- `# ruff: ignore`
- `# pylint: ignore`

### Ruff Configuration

From `pyproject.toml`:
- Line length: 100 characters
- Python version: 3.13
- Enabled rules: E, F, I, N, UP, B, C4, D, ANN401
- Ignored: D203, D213, E501
- Code comments are discouraged - prefer clear code and commit messages

### Quality Gates

- Run linting after each change: `make lint` or `bash scripts/lint.sh`
- Use specific types instead of `Any` in type annotations (ruff ANN401 rule)
- Run tests when you touch logic or input handling: `pytest`
- Always write a regression test when fixing a bug
- If you break something while fixing it, fix both in the same PR
- Do not use in-line comments to disable linting or type checks
- Do not narrate your code with comments; prefer clear code and commit messages

---

## Testing Guidelines

Automated tests live in `tests/` and run with `pytest` (or `make pytest`). When adding tests, keep `pytest` naming like `test_dice_ladder_step_up`. Use httpx.AsyncClient for API integration tests. Use fixtures from `conftest.py` for shared test setup.

### Coverage Requirements

Always run `pytest --cov=comic_pile --cov-report=term-missing` to check missing coverage. When touching logic or input handling, ensure tests are added to maintain coverage. Strategies for increasing coverage:
- Add tests for remaining uncovered edge cases
- Add tests for complex error handling paths
- Add tests for API endpoints with httpx.AsyncClient
- Add tests for business logic (dice ladder, queue management, session detection)

---

## Database Development

Define SQLAlchemy models in `app/models/`. Use Alembic for all schema changes: `alembic revision --autogenerate -m "description"`. Run migrations: `make migrate` or `alembic upgrade head`. Use Pydantic schemas for API validation in `app/schemas/`. Keep database operations in service layer, not in route handlers.

---

## Project Structure

```
comic-pile/
├── app/                    # FastAPI application
│   ├── __init__.py
│   ├── main.py            # FastAPI app factory
│   ├── api/               # API route handlers
│   ├── models/            # SQLAlchemy database models
│   ├── schemas/           # Pydantic request/response schemas
│   └── templates/         # Jinja2 templates
├── comic_pile/            # Core package (dice ladder, queue, session logic)
├── scripts/               # Utility scripts (seed data, etc.)
├── tests/                 # pytest test suite
├── static/                # Static assets (CSS, JS)
├── alembic/               # Alembic migration files
├── agents/                # Agent system (manager daemon, etc.)
├── pyproject.toml         # Project configuration
└── uv.lock                # Dependency lockfile
```

---

## Product Philosophy

### Core Philosophy (from PRD)

This app exists to **support an existing ritual**, not optimize or gamify it.

Key principles:
- **Chaos is allowed** - The queue reflects what you can read now, not everything you've ever read
- **Ratings and movement encode intent, not notes** - No notes system in the app
- **Dice are sacred** - The dice ladder self-corrects chaos
- **Time, not mood, defines sessions** - 6-hour gap defines session boundary, no manual "new session" button
- **The queue reflects what you can read now, not everything you've ever read**

### Reading Thread

A **thread** represents a mini reading order, equivalent to one row in your spreadsheet (e.g., "Hellboy Omnibus Vol 2", "Declustered X-Men", "Majestic"). Threads are atomic units for: Rolling, Reading, Rating, and Queue movement.

### Dice Ladder

Allowed dice (ordered): `d4 → d6 → d8 → d10 → d12 → d20`

Rules:
- New session always starts at **d6**
- After each read + rating:
  - Rating ≥ 4.0 → step **down** one die
  - Rating < 4.0 → step **up** one die
- Only **one step per read**
- Bounds: d4 stays d4 on success, d20 stays d20 on failure

Intent: d4 is the reward state, larger dice explore deeper into the queue, the ladder self-corrects chaos.

Manual overrides do not bypass ladder logic.

### Queue Management

- The queue is a **single ordered list**, top to bottom
- Ordering is authoritative
- Rolls always operate on the **top N rows**, where N is the die size
- Completed threads disappear from the queue by default (can be reactivated)
- New or reactivated threads always insert at **position 1**
- No cap, chaos is acceptable

After rating:
- Rating ≥ 4.0 → move thread to **front**
- Rating < 4.0 → move thread to **back**

---

## Governance

### Amendment Process

This constitution supersedes all other practices. Amendments require:
1. Documentation of the change with rationale
2. Approval via pull request
3. Migration plan if breaking changes
4. Update of this document's "Last Amended" date and version

### Compliance Verification

All PRs and reviews must verify compliance with this constitution. Complexity must be justified with clear reasoning. Use project-specific guidance files for runtime development:
- AGENTS.md for agent system workflows
- WORKFLOW_PATTERNS.md for proven successful patterns
- MANAGER_DAEMON.md for daemon responsibilities
- TECH_DEBT.md for known issues to avoid
- ARCHITECTURE_TASK_API.md for architectural decisions

### Enforcement

Pre-commit hook blocks commits with linter/type check ignores. CI/CD runs full test suite and linting. Manual code reviews verify adherence to principles. Technical debt tracked in TECH_DEBT.md and addressed via Task API.
