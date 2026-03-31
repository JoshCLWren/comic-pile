# AGENTS.md

Guidelines for AI agents working in this codebase.

## Agent Ownership Policy

All AI agents working in this codebase are **high-ownership agents**.

**Key Principle**: If you find a bug (pre-existing or new), it is your responsibility to fix it. You are not a lazy AI that ignores problems and pushes them to human reviewers.

**Never dismiss failures as "pre-existing."** Fix them. Every time. No exceptions.

## CORE PRINCIPLE: NEVER SKIP TESTS

**⚠️ TESTS MUST NEVER BE SKIPPED - EVER.**

If a test is failing:
- ✅ FIX THE TEST
- ✅ FIX THE CODE THAT BREAKS THE TEST
- ✅ INVESTIGATE ROOT CAUSE
- ❌ **NEVER SKIP THE TEST**

**This applies to:** All automated tests (unit, integration, E2E), all developers (human and AI), all situations (no exceptions).

**Requirements:**
- **Never use `--no-verify` or bypass hooks** to avoid fixing issues
- **Never say "this is pre-existing" and walk away** - fix it anyway
- **Fix all test failures** before committing, even if the failure appears to be pre-existing
- **Write regression tests** for bugs you find and fix
- **Update documentation** when you find gaps or outdated information

## Project Overview

Comic Pile is a dice-driven comic reading tracker built with:
- **Backend**: Python 3.13, FastAPI, SQLAlchemy, PostgreSQL
- **Frontend**: React 19, Vite, Tailwind CSS
- **Package managers**: `uv` (Python), `npm` (frontend)

## CRITICAL: Async PostgreSQL Only - NO Sync psycopg2

**This project uses asyncpg (async PostgreSQL) ONLY. NEVER use synchronous psycopg2.**

**Database Access Rules**:
- ✅ **USE**: `asyncpg` (async), `create_async_engine()`, `AsyncSession`
- ❌ **NEVER USE**: `psycopg2`, `psycopg`, `create_engine()` (sync), `Session` (sync)

**Why async-only?** Weeks of refactoring converted entire codebase to async. Mixing sync/async causes event loop conflicts and greenlet errors. Sync code WILL BREAK the application.

**If you need to create tables in tests**: Use module-scoped `@pytest_asyncio.fixture` with `create_async_engine()`, call `await conn.run_sync(Base.metadata.create_all)`. See `tests_e2e/conftest.py:_create_database_tables` for example.

**Violating this rule will undo weeks of work and break the application.**

## Build/Lint/Test Commands

### Linting
```bash
make lint                    # All linters (Python + JS + HTML)
ruff check .                 # Python only
ty check --error-on-warning  # Python type checking
cd frontend && npm run lint  # Frontend ESLint
```

### Testing
```bash
pytest                                          # All Python tests
make test                                       # With coverage
pytest tests/test_roll_api.py -v                # Single file
pytest tests/test_roll_api.py::test_roll_success -v  # Single function
pytest -k "roll" -v                             # Pattern matching
cd frontend && npm test                         # Frontend unit tests (vitest)
cd frontend && npm run typecheck                # Frontend TypeScript check
```

### E2E Tests (Playwright)
**⚠️ MUST build frontend first:**
```bash
cd frontend && npm run test:e2e        # Builds + runs tests
cd frontend && npm run test:e2e:quick  # Skip build (faster iteration)
cd frontend && npm run build && npx playwright test --headed  # Run with browser visible
```

**Why build required?** Playwright tests run against production build in `static/react/`, not dev server. Without build, tests fail with 404s for CSS/JS assets.

## Python Code Style

### Imports
Order: standard library, third-party, local. Ruff auto-sorts with `ruff check --fix`.

### Type Annotations
- **Required** on all public functions with precise types
- **Never use `Any`** - ruff ANN401 rule enforced
- Use `Mapped[]` for SQLAlchemy model columns
- Use `|` union syntax, not `Union[]` or `Optional[]`

### Naming Conventions
- **Functions/variables**: `snake_case`
- **Classes**: `PascalCase`
- **Constants**: `SCREAMING_SNAKE_CASE`
- **Private**: prefix with `_`

### Docstrings
Google convention, required for modules and public functions. Include Args/Returns sections.

### Formatting
- **Line length**: 100 characters
- **Indentation**: 4 spaces
- **Trailing commas**: Yes, for multi-line structures

### Linter Ignores - PROHIBITED
The pre-commit hook blocks these comments:
- `# type: ignore`
- `# noqa`
- `# ruff: ignore`
- `# pylint: ignore`

Fix the underlying issue instead of suppressing warnings.

### CRITICAL: MissingGreenlet Errors After Database Commits

**Symptom**: `sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called`

**Root Cause**: Accessing SQLAlchemy model attributes after `await db.commit()` causes session expiration. SQLAlchemy lazy-loads attributes on access, but after commit the session is closed/expired.

**Example of buggy code**:
```python
await db.commit()

# This will FAIL - accessing thread.title after commit triggers lazy load
return RollResponse(
    title=thread.title,  # ❌ MissingGreenlet error
    format=thread.format,
)
```

**Required Fix Pattern**:
```python
# Extract all needed attributes BEFORE commit
thread_title = thread.title
thread_format = thread.format
thread_issues = thread.issues_remaining
thread_position = thread.queue_position

await db.commit()

# Use extracted values after commit - safe!
return RollResponse(
    title=thread_title,  # ✅ Works
    format=thread_format,
    issues_remaining=thread_issues,
    queue_position=thread_position,
)
```

**Rule**: If you need data from a SQLAlchemy model after `db.commit()`, extract it into variables BEFORE the commit.

## API Patterns

### Pydantic Schemas
All API input/output uses Pydantic models in `app/schemas/`:
```python
class ThreadCreate(BaseModel):
    """Schema for creating a new thread."""
    title: str = Field(..., min_length=1)
    format: str = Field(..., min_length=1)
    issues_remaining: int = Field(..., ge=0)
    notes: str | None = None
```

### SQLAlchemy Models
Models in `app/models/` use `Mapped` type annotations:
```python
class Thread(Base):
    __tablename__ = "threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    last_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
```

### Error Handling
Use FastAPI's HTTPException with appropriate status codes:
```python
if not thread or thread.user_id != current_user.id:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Thread {thread_id} not found",
    )
```

 ## Testing Patterns

### Browser UI Tests

**Use TypeScript Playwright tests** (in `frontend/src/test/`) for browser automation. Python Playwright tests are NOT supported due to event loop conflicts.

**Running E2E Tests Locally:**

```bash
# Option 1: With Docker (recommended)
docker compose -f docker-compose.test.yml up -d postgres-test
cd frontend && npm run build && npx playwright test --project=chromium
docker compose -f docker-compose.test.yml down

# Option 2: Manual setup
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5437/comic_pile_test
export SECRET_KEY=test-secret-key
.venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# In another terminal:
cd frontend && npm run build
REUSE_EXISTING_SERVER=true npx playwright test --project=chromium
```

**Common Commands:** `npx playwright test --project=chromium` (all), `npx playwright test roll.spec.ts` (single file), `npx playwright test --ui` (interactive), `npx playwright test --headed` (browser visible), `npx playwright test --debug` (debug mode).

### API Tests

API tests use async PostgreSQL test databases. Tests in `tests/` directory, files: `test_*.py`, functions: `test_*`. Use `@pytest.mark.asyncio` for async tests. Test both success and error paths. Maintain 96% coverage threshold.

**Key Fixtures (from `tests/conftest.py`)**:
```python
# Authenticated HTTP client
async def test_example(auth_client, sample_data):
    response = await auth_client.post("/api/roll/")
    assert response.status_code == 200

# Database session
def test_db_example(db):
    thread = db.get(Thread, 1)
```

### Docker Test Environment

File: `docker-compose.test.yml` - PostgreSQL 16 on port 5437.

```bash
make docker-test-up     # Start test environment
make docker-test-health # Check health
make docker-test-logs   # View logs
make docker-test-down   # Stop test environment
```

Port conflicts: Dev (5435), Test (5437), CI (5432).

## Frontend Code Style

- Functional components with hooks
- Custom hooks with useState/useEffect for server state
- React Router for navigation

```jsx
import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../services/api'

export function useResource(id) {
  const [data, setData] = useState(null)
  const [isPending, setIsPending] = useState(true)
  const [isError, setIsError] = useState(false)
  const [error, setError] = useState(null)

  const fetchData = useCallback(async () => {
    if (!id) {
      setIsPending(false)
      return
    }
    setIsPending(true)
    setIsError(false)
    setError(null)
    try {
      const result = await api.getResource(id)
      setData(result)
    } catch (err) {
      setIsError(true)
      setError(err)
    } finally {
      setIsPending(false)
    }
  }, [id])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  return { data, isPending, isError, error, refetch: fetchData }
}

export default function ExamplePage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { data, isPending, isError } = useResource(id)

  if (isPending) return <div>Loading...</div>
  if (isError) return <div>Error loading resource</div>

  return <div>{data?.name}</div>
}
```

## Database Migrations

```bash
alembic revision --autogenerate -m "description"  # Create migration
make migrate  # Run migrations (or: alembic upgrade head)
```

## Git Workflow

- Branch from `main`: `git checkout -b phase/X-description`
- Commit messages: imperative, component-scoped (e.g., "Add thread creation API endpoint")
- Run `make lint` and `make pytest` before committing
- **Update `docs/changelog.md`** when deploying changes to production (add new dated entry, group by feature area, describe what changed not how)
