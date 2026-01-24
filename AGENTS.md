# AGENTS.md

Guidelines for AI agents working in this codebase.

## Project Overview

Comic Pile is a dice-driven comic reading tracker built with:
- **Backend**: Python 3.13, FastAPI, SQLAlchemy, PostgreSQL
- **Frontend**: React 19, Vite, Tailwind CSS, React Query
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

- Tests in `tests/` directory, test files: `test_*.py`, functions: `test_*`
- Use `@pytest.mark.asyncio` for async tests
- Test both success and error paths
- Write regression tests for bug fixes
- Maintain 96% coverage threshold

### Key Fixtures (from `tests/conftest.py`)
```python
# Authenticated HTTP client
async def test_example(auth_client, sample_data):
    response = await auth_client.post("/api/roll/")
    assert response.status_code == 200

# Database session
def test_db_example(db):
    thread = db.get(Thread, 1)
```

## Frontend Code Style

- Functional components with hooks
- React Query for server state
- React Router for navigation

```jsx
import { useQuery, useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

export default function ExamplePage() {
  const navigate = useNavigate()
  const { data } = useQuery({ queryKey: ['key'], queryFn: fetchFn })
  // ...
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