# Testing & Quality Guide - Comic Pile

This document provides essential guidance for testing, linting, and maintaining code quality in Comic Pile.

---

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=comic_pile --cov-report=term-missing

# Run specific test file
pytest tests/test_dice_ladder.py

# Run specific test function
pytest tests/test_dice_ladder.py::test_dice_ladder_step_up
```

### Coverage Requirements

- **Minimum threshold:** 96% (configured in pyproject.toml)
- Always check missing coverage: `pytest --cov=comic_pile --cov-report=term-missing`
- When touching logic or input handling, ensure tests are added to maintain coverage

### Strategies for Increasing Coverage

1. **Add tests for remaining uncovered edge cases**
   - Test boundary conditions (empty lists, zero values, etc.)
   - Test error paths (invalid inputs, missing resources)
   - Test concurrency scenarios (race conditions)

2. **Add tests for complex error handling paths**
   - Test all HTTP error responses (400, 404, 422, 409)
   - Test database error handling (unique constraints, foreign keys)
   - Test validation error scenarios

3. **Add tests for API endpoints with httpx.AsyncClient**
   - Test success and error paths for all endpoints
   - Test request/response schemas
   - Test authentication/authorization (when added)

4. **Add tests for business logic**
   - Dice ladder: step up/down at boundaries
   - Queue management: move to front/back/position
   - Session detection: 6-hour timeout edge cases
   - Rating flow: queue movement, issues decrement

### Test Organization

```
tests/
├── conftest.py                    # Shared fixtures
├── test_api_endpoints.py           # API endpoint tests
├── test_dice_ladder.py             # Dice ladder logic tests
├── test_queue_api.py               # Queue API tests
├── test_rate_api.py               # Rate API tests
├── test_roll_api.py               # Roll API tests
├── test_session.py                # Session logic tests
├── test_task_api.py               # Task API tests (agent coordination)
├── test_csv_import.py             # CSV import/export tests
└── integration/
    ├── conftest.py               # Integration test fixtures
    └── test_workflows.py         # End-to-end workflow tests
```

### Fixtures (conftest.py)

Key fixtures available:

```python
# Database fixture (creates fresh database for each test)
@pytest.fixture
def db():
    # Setup
    session = SessionLocal()
    yield session
    # Teardown
    session.rollback()
    session.close()

# Async client fixture (for API tests)
@pytest_asyncio.fixture
async def async_client():
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client
```

### Test Naming

- Use pytest naming: `test_<function_being_tested>`
- Examples:
  - `test_dice_ladder_step_up`
  - `test_roll_dice_returns_valid_result`
  - `test_rate_updates_queue_position`

### Test Structure

```python
def test_feature_being_tested(async_client: AsyncClient):
    # Arrange - setup test data
    thread_data = {"title": "Batman", "format": "TPB", "issues_remaining": 6}
    response = await async_client.post("/threads/", json=thread_data)
    thread_id = response.json()["id"]

    # Act - perform action being tested
    response = await async_client.post("/roll/")

    # Assert - verify expected outcome
    assert response.status_code == 200
    data = response.json()
    assert "thread_id" in data
    assert "result" in data
```

### Async vs Sync Tests

- **Async tests:** Use for API endpoints (FastAPI is async)
- **Sync tests:** Use for business logic (dice ladder, queue, session)
- Use `pytest-asyncio` plugin for async tests
- Use `pytest.mark.asyncio` decorator for async test functions

### Integration Tests

Integration tests live in `tests/integration/test_workflows.py` and test complete user workflows:

```python
async def test_complete_reading_workflow(async_client: AsyncClient):
    # Create thread
    response = await async_client.post("/threads/", json={
        "title": "Batman Vol. 1",
        "format": "TPB",
        "issues_remaining": 6
    })

    # Roll dice
    response = await async_client.post("/roll/")
    thread_id = response.json()["thread_id"]

    # Rate reading
    response = await async_client.post("/rate/", json={
        "rating": 4.5,
        "issues_read": 1
    })

    # Verify thread moved to front (high rating)
    response = await async_client.get("/threads/")
    threads = response.json()
    assert threads[0]["id"] == thread_id
```

### Regression Tests

**Rule:** Always write a regression test when fixing a bug.

```python
def test_regression_d10_rendering_visibility(async_client: AsyncClient):
    """
    Regression test for d10 die rendering visibility issue.
    BUG: d10 die not visible in 3D scene
    FIX: Adjusted geometry in dice3d.js
    """
    response = await async_client.post("/roll/", json={"die_size": 10})
    assert response.status_code == 200

    # Verify d10 is visible in response
    # (This test would need to check 3D rendering, not just API)
```

Add comment linking bug report or task ID for reference.

---

## Linting

### Running Linting

```bash
# Run full lint script (includes type checking)
make lint

# Or run bash script directly
bash scripts/lint.sh

# Run ruff only
ruff check .

# Fix auto-fixable issues
ruff check --fix .

# Format code
ruff format .

# Run type checker only
pyright .
```

### Lint Script (scripts/lint.sh)

The lint script runs:
1. **Python compilation check** - Ensures no syntax errors
2. **Ruff linting** - Checks code style and potential issues
3. **Any type usage check** - Disallows `Any` type (ruff ANN401 rule)
4. **Pyright type checking** - Static type analysis

### Pre-commit Hook

A pre-commit hook is installed in `.git/hooks/pre-commit` that automatically runs:
- Check for type/linter ignores in staged files
- Run the shared lint script (`scripts/lint.sh`)

**The hook will block commits containing:**
- `# type: ignore`
- `# noqa`
- `# ruff: ignore`
- `# pylint: ignore`

### Testing Hook Manually

```bash
# Run hook manually to verify
make githook

# Or run lint script directly
bash scripts/lint.sh
```

---

## Ruff Configuration

### Configuration (pyproject.toml)

```toml
[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "C4", "D", "ANN401"]
ignore = ["D203", "D213", "E501"]
```

### Key Rules

- **E, F, I, N, UP, B, C4:** Code style and potential issues
- **D:** Docstring conventions (pydocstyle)
- **ANN401:** Disallows `Any` type (requires specific types)
- **D203, D213:** Docstring formatting exceptions
- **E501:** Line length exception (configured for 100 chars)

### Common Ruff Errors

1. **F401: Imported but unused**
   ```python
   import os  # F401: 'os' imported but never used
   ```
   **Fix:** Remove unused import

2. **ANN401: Any type not allowed**
   ```python
   def process(data: Any):  # ANN401: Dynamically typed expression
       pass
   ```
   **Fix:** Use specific type
   ```python
   def process(data: dict[str, Any]):
       pass
   ```

3. **UP032: Use f-string instead of format**
   ```python
   message = "Hello {}".format(name)  # UP032
   ```
   **Fix:** Use f-string
   ```python
   message = f"Hello {name}"
   ```

---

## Pyright Configuration

### Configuration (pyproject.toml)

```toml
[tool.pyright]
typeCheckingMode = "strict"
pythonVersion = "3.13"
```

### Common Pyright Errors

1. **Missing type annotations**
   ```python
   def add(a, b):  # Missing type annotations
       return a + b
   ```
   **Fix:** Add type hints
   ```python
   def add(a: int, b: int) -> int:
       return a + b
   ```

2. **Incompatible types**
   ```python
   name: int = "John"  # Type "str" is not assignable to type "int"
   ```
   **Fix:** Correct type
   ```python
   name: str = "John"
   ```

---

## Code Style Guidelines

### Naming Conventions

- **Functions/Variables:** `snake_case`
  ```python
  def get_current_session():
      current_time = datetime.now()
  ```

- **Classes:** `PascalCase`
  ```python
  class ThreadResponse:
      pass
  ```

- **Constants:** `UPPER_SNAKE_CASE`
  ```python
  SESSION_GAP_HOURS = 6
  DICE_LADDER = [4, 6, 8, 10, 12, 20]
  ```

### Imports

- Use `isort` style (handled by ruff)
- Group imports: standard library, third-party, local
- One import per line
- Use specific imports, not `from module import *`

```python
# Standard library
from datetime import datetime
from typing import Optional

# Third-party
from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

# Local
from app.models.thread import Thread
```

### Type Hints

- All public functions must have type annotations
- Use specific types, not `Any`
- Import from `typing` module when needed

```python
from typing import Optional

def get_thread(db: Session, thread_id: int) -> Optional[Thread]:
    """Get a thread by ID, or None if not found."""
    return db.query(Thread).filter(Thread.id == thread_id).first()
```

### Docstrings

- **Use docstrings for public functions and classes**
- Keep them concise but clear
- Use Google or NumPy style (consistent with pydocstyle)
- No inline comments for code explanation

```python
def step_up(die: int) -> int:
    """Step up one die in the ladder.

    Args:
        die: Current die size (must be in DICE_LADDER)

    Returns:
        Next larger die size, or current if at max (d20)

    Example:
        >>> step_up(6)
        8
    """
    # Implementation...
```

---

## Common Anti-Patterns to Avoid

### 1. Not Using Context Managers

**Bad:**
```python
session = SessionLocal()
thread = session.query(Thread).first()
session.close()  # Easy to forget
```

**Good:**
```python
with SessionLocal() as session:
    thread = session.query(Thread).first()
# Automatically closes
```

### 2. Not Testing Error Paths

**Bad:**
```python
def test_roll_dice(async_client: AsyncClient):
    response = await async_client.post("/roll/")
    assert response.status_code == 200
    # Only tests success path
```

**Good:**
```python
def test_roll_dice_no_threads(async_client: AsyncClient):
    response = await async_client.post("/roll/")
    assert response.status_code == 400
    assert "No active threads" in response.json()["detail"]
```

### 3. Using Any Type

**Bad:**
```python
def process(data: Any) -> Any:
    # What is data? What does it return?
    pass
```

**Good:**
```python
def process(thread_data: dict[str, Any]) -> ThreadResponse:
    # Clear input/output types
    pass
```

### 4. Not Handling Transactions

**Bad:**
```python
def move_to_front(db: Session, thread_id: int):
    thread = db.query(Thread).filter(Thread.id == thread_id).one()
    thread.position = 1
    db.commit()  # Commit 1

    # Update all other threads
    for other in db.query(Thread).filter(Thread.id != thread_id).all():
        other.position += 1
    db.commit()  # Commit 2 - if this fails, first commit is not rolled back
```

**Good:**
```python
def move_to_front(db: Session, thread_id: int):
    with db.begin():  # Transaction context
        thread = db.query(Thread).filter(Thread.id == thread_id).one()
        thread.position = 1

        for other in db.query(Thread).filter(Thread.id != thread_id).all():
            other.position += 1
    # Commits or rolls back entire transaction
```

### 5. Inline Comments Instead of Clear Code

**Bad:**
```python
# Get the current session from the database
# If no active session exists (ended > 6 hours ago), create new one
# Check if session ended within the last 6 hours
session = get_or_create(db, user_id)
```

**Good:**
```python
session = get_or_create(db, user_id)  # Handles 6-hour timeout automatically
```

---

## Continuous Integration

### CI Configuration (GitHub Actions)

See `.github/workflows/ci.yml` for CI configuration.

### CI Checks

- Python compilation check
- Ruff linting
- Pyright type checking
- pytest with coverage
- Coverage threshold enforcement (96%)

### Running CI Locally

```bash
# Run CI checks locally
make lint
make pytest
```

---

## Quality Checklist

Before committing code, verify:

### Testing
- [ ] All tests pass: `pytest`
- [ ] Coverage maintained at 96%+: `pytest --cov=comic_pile --cov-report=term-missing`
- [ ] New code has tests (including error paths)
- [ ] Regression tests added for bug fixes
- [ ] Integration tests added for new workflows

### Linting
- [ ] Ruff passes: `ruff check .`
- [ ] Pyright passes: `pyright .`
- [ ] No `# type: ignore`, `# noqa`, etc. in code
- [ ] Code formatted: `ruff format .`

### Code Quality
- [ ] Clear function and variable names (snake_case)
- [ ] Type hints on all public functions
- [ ] Docstrings on public functions and classes
- [ ] No inline comments for code explanation
- [ ] No `Any` types (use specific types)

### Best Practices
- [ ] Database operations use context managers
- [ ] Complex operations use transactions
- [ ] Error paths tested
- [ ] Input validation (Pydantic schemas)
- [ ] No hardcoded values (use constants)

---

## Debugging Tests

### Verbose Output

```bash
pytest -v  # Show test names
pytest -vv  # Show detailed output
pytest -s  # Show print statements
```

### Stopping on First Failure

```bash
pytest -x  # Stop on first failure
pytest --tb=short  # Shorter traceback
```

### Debugging Specific Test

```bash
# Run with Python debugger
pytest --pdb

# Drop into debugger on failure
pytest --pdb -x
```

### Test Isolation

```bash
# Run tests in random order (detects dependency issues)
pytest --random-order

# Run tests in parallel
pytest -n auto
```

---

## Resources

### Documentation

- pytest: https://docs.pytest.org/
- pytest-asyncio: https://pytest-asyncio.readthedocs.io/
- httpx: https://www.python-httpx.org/
- Ruff: https://docs.astral.sh/ruff/
- Pyright: https://microsoft.github.io/pyright/

### Project-Specific Docs

- AGENTS.md - Repository guidelines and workflow
- TECH_DEBT.md - Known technical debt items
- API.md - Full API documentation
- CONTRIBUTING.md - Contributing guidelines

### Make Commands

```bash
make dev          # Run development server
make pytest       # Run tests with coverage
make lint         # Run ruff and pyright
make seed         # Seed database with sample data
make migrate      # Run database migrations
make githook      # Test pre-commit hook
```
