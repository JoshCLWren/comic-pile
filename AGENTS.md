# AGENTS.md

Guidelines for AI agents working in this codebase.

## Agent Ownership Policy

All AI agents working in this codebase are **high-ownership agents**.

**Key Principle**: If you find a bug (pre-existing or new), it is your responsibility to fix it. You are not a lazy AI that ignores problems and pushes them to human reviewers.

**Requirements**:
- **Never use `--no-verify` or bypass hooks** to avoid fixing issues
- **Never say "this is pre-existing" and walk away** - fix it anyway
- **Fix all test failures** before committing, even if the failure appears to be pre-existing
- **Write regression tests** for bugs you find and fix
- **Update documentation** when you find gaps or outdated information

**If a test fails**:
1. Investigate why it fails
2. Fix the root cause (even if "pre-existing")
3. Verify the fix works
4. Add a regression test if applicable

**If you find documentation gaps**:
1. Update the relevant documentation
2. Add examples if helpful

## Project Overview

Comic Pile is a dice-driven comic reading tracker built with:

## CRITICAL: Async PostgreSQL Only - NO Sync psycopg2

**This project uses asyncpg (async PostgreSQL) ONLY. NEVER use synchronous psycopg2.**

**Database Access Rules**:
- ✅ **USE**: `asyncpg` (async), `create_async_engine()`, `AsyncSession`
- ❌ **NEVER USE**: `psycopg2`, `psycopg`, `create_engine()` (sync), `Session` (sync)

**Why async-only?**
- Weeks of refactoring converted entire codebase to async
- Mixing sync/async causes event loop conflicts and greenlet errors
- Sync code WILL BREAK the application

**If you need to create tables in tests**:
- Use module-scoped `@pytest_asyncio.fixture` with `create_async_engine()`
- Call `await conn.run_sync(Base.metadata.create_all)`
- See `tests_e2e/conftest.py:_create_database_tables` for example

**Violating this rule will undo weeks of work and break the application.**
- **Backend**: Python 3.13, FastAPI, SQLAlchemy, PostgreSQL
- **Frontend**: React 19, Vite, Tailwind CSS
- **Package managers**: `uv` (Python), `npm` (frontend)

## Build/Lint/Test Commands

### Linting
```bash
make lint                    # Run all linters (Python + JS + HTML)
bash scripts/lint.sh         # Same as above
ruff check .                 # Python linting only
ty check --error-on-warning  # Python type checking only
```

### Testing
```bash
pytest                       # or: make pytest
make test                    # With coverage report
pytest tests/test_roll_api.py -v                   # Single test file
pytest tests/test_roll_api.py::test_roll_success -v # Single test function
pytest -k "roll" -v          # Pattern matching
cd frontend && npm test      # Frontend tests
make test-integration        # E2E tests (Playwright)
```

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

 **Use TypeScript Playwright tests** (in `frontend/src/test/`) for browser automation.

 **Python Playwright tests are NOT supported** due to fundamental event loop conflicts:
 - pytest-asyncio requires managing the event loop for async tests
 - Playwright's async fixtures need their own event loop
 - These two systems cannot coexist in the same test suite
 - Multiple attempts to fix this have failed (9+ commits, all reverted)

 **TypeScript Playwright Configuration**:
 - File: `frontend/playwright.config.ts`
 - Automatically starts Uvicorn via `webServer` config
 - Tests run in isolated environment
 - All browser tests work correctly

 **Running TypeScript Browser Tests**:
 ```bash
 cd frontend
 npx playwright test --project=chromium
 ```

 ### API Tests

API tests use in-memory SQLite for fast unit testing:

- Tests in `tests/` directory, test files: `test_*.py`, functions: `test_*`
- Use `@pytest.mark.asyncio` for async tests
- Test both success and error paths
- Write regression tests for bug fixes
- Maintain 96% coverage threshold

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

 ## Docker Test Environment

 ### Docker Compose Test Configuration

 File: `docker-compose.test.yml`

 **Purpose**: Provides isolated PostgreSQL database and API server for testing

 **Services**:
 - `postgres-test`: PostgreSQL 16 on port 5437
 - `api-test`: FastAPI application on port 8000 (optional, for manual testing)

 **Usage**:
 ```bash
 # Start test environment
 make docker-test-up

 # Check health
 make docker-test-health

 # View logs
 make docker-test-logs

 # Stop test environment
 make docker-test-down
 ```

 **Environment File**: `.env.test`
 - Contains `DATABASE_URL` pointing to localhost:5437
 - Contains test `SECRET_KEY`
 - Source with: `source .env.test`

 **Port Conflicts**:
 - Dev PostgreSQL: port 5435 (from docker-compose.yml)
 - Test PostgreSQL: port 5437 (from docker-compose.test.yml)
 - CI PostgreSQL: port 5432 (GitHub Actions service)

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