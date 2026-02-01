# Local Testing Guide

This guide shows you how to set up a local test environment with sample data.

## Quick Start

### Option 1: Seed Your Dev Database (Recommended)

The fastest way to get test data locally:

```bash
python scripts/seed_dev_db.py
```

This creates:
- **User**: `test@example.com` / `testpass123`
- **5 Threads**: Superman, Batman, Wonder Woman, The Flash, Aquaman
- **Active Session**: Start die = 6

The script is idempotent - run it again to refresh the data.

### Option 2: Run E2E Tests

E2E tests automatically create a test server with seeded data:

```bash
# Run all E2E tests
make test-integration
# or
pytest tests_e2e/

# Run specific test
pytest tests_e2e/test_api_workflows.py::test_roll_dice_updates_session -v
```

**Test credentials**: `test_user@example.com` / `testpassword`

### Option 3: Use Unit Test Fixtures

Unit tests use the `auth_api_client_async` fixture which auto-creates a test user:

```python
async def test_my_feature(auth_api_client_async: AsyncClient, async_db: AsyncSession):
    # auth_api_client_async is already authenticated as test_user@example.com
    # async_db is a test database session
    response = await auth_api_client_async.get("/api/threads/")
    assert response.status_code == 200
```

## Key Fixtures

### E2E Fixtures (`tests_e2e/conftest.py`)

| Fixture | Scope | Description |
|---------|-------|-------------|
| `async_db` | function | Async DB session with transaction rollback |
| `auth_api_client_async` | function | Authenticated API client (ASGI transport) |
| `test_server_url` | session | Live HTTP server on free port with seeded data |
| `browser_page` | function | Playwright page with localStorage cleared |

### Unit Test Fixtures (`tests/conftest.py`)

| Fixture | Scope | Description |
|---------|-------|-------------|
| `db` | function | Sync wrapper around async DB session |
| `client` | function | FastAPI test client with auth override |
| `sample_user` | function | Test user with 3 threads |

## Common Patterns

### Creating Test Threads

```python
from app.models import Thread

thread = Thread(
    title="Test Comic",
    format="Comic",
    issues_remaining=5,
    queue_position=1,
    user_id=user.id,
)
async_db.add(thread)
await async_db.commit()
```

### Making Authenticated Requests

```python
response = await auth_api_client_async.post("/api/roll/")
assert response.status_code == 200
```

### Querying the Database

```python
from sqlalchemy import select

result = await async_db.execute(select(Thread).where(Thread.user_id == user_id))
threads = result.scalars().all()
```

## Troubleshooting

**Database connection errors?**
- Ensure PostgreSQL is running: `psql postgres -c "SELECT 1"`
- Check your `.env` file has `DATABASE_URL` set

**Test isolation issues?**
- E2E tests use transaction rollback - data doesn't persist
- Use `seed_dev_db.py` for persistent data across test runs

**Port conflicts?**
- E2E tests auto-find free ports
- Check `.pytest_cache` for stuck test servers
