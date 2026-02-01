# CI E2E Test Failure Analysis

## Summary
The CI run 21535122723 has multiple failures:
1. **Lint job** - Fails with "No virtual environment found"
2. **TypeScript Playwright tests** - Backend server fails to start with async/sync database error
3. **Python Playwright tests** - Status unclear (may work with proper DB setup)

## Issue 1: Lint Job Failure

### Root Cause
The `scripts/lint.sh` script expects to find `.venv/bin/activate` in the current directory, but in CI:
- Code is checked out to: `/__w/comic-pile/comic-pile`
- Venv is at: `/workspace/.venv`
- The `.venv` directory doesn't exist in the checkout directory

### Error Message
```
Running code quality checks...
No virtual environment found. Please run 'uv venv && uv sync --all-extras' first.
```

### Analysis
The lint script (lines 46-64) has CI detection that should check if `ruff` and `python` are in PATH:
```bash
if [ -f "$VENV_PATH" ]; then
    source "$VENV_PATH"
else
    if [ -n "$CI" ]; then
        # Verify required tools are available
        if ! command -v ruff >/dev/null 2>&1; then
            echo "ERROR: ruff not found in PATH (CI environment)"
            exit 1
        fi
        if ! command -v python >/dev/null 2>&1; then
            echo "ERROR: python not found in PATH (CI environment)"
            exit 1
        fi
    else
        echo "No virtual environment found. Please run 'uv venv && uv sync --all-extras' first."
        exit 1
    fi
fi
```

The error comes from the final `else` block (line 61), which means:
1. `.venv/bin/activate` doesn't exist in the checkout directory
2. Either `CI` is not set, OR the tool check failed

The CI environment variables show `CI=true`, so the tool check must be failing.

### Possible Causes
1. `ruff` or `python` commands not found in PATH despite `/workspace/.venv/bin` being in PATH
2. Docker build might not have installed dependencies correctly
3. PATH might not be properly set when the lint script runs

### Recommended Fix
Update the lint script to handle the Docker environment better:
```bash
# In CI, tools may already be in PATH (e.g., from Docker image)
if [ -n "$CI" ]; then
    # Verify required tools are available
    if ! command -v ruff >/dev/null 2>&1; then
        echo "ERROR: ruff not found in PATH (CI environment)"
        echo "Current PATH: $PATH"
        exit 1
    fi
    if ! command -v python >/dev/null 2>&1; then
        echo "ERROR: python not found in PATH (CI environment)"
        echo "Current PATH: $PATH"
        exit 1
    fi
    # Tools found, continue with linting
    echo "CI environment: Using tools from PATH"
else
    echo "No virtual environment found. Please run 'uv venv && uv sync --all-extras' first."
    exit 1
fi
```

OR verify the Docker build is installing dependencies correctly.

## Issue 2: TypeScript Playwright Tests - Backend Startup Failure

### Root Cause
The backend server fails during startup due to mixing sync and async database operations.

### Error Message
```
INFO:     Started server process [741]
INFO:     Waiting for application startup.
Failed to create database tables: greenlet_spawn has not been called; can't call await_only() here. Was IO attempted in an unexpected place?
```

### Analysis
In `app/main.py:405-437`, the `startup_event` is async:
```python
@app.on_event("startup")
async def startup_event():
    """Initialize database on application startup."""
    import asyncio
    from sqlalchemy import text

    # ... async database connection check ...

    if database_ready:
        if app_settings.environment == "production":
            logger.info("Production mode: Skipping table creation (migrations required)")
        else:
            try:
                Base.metadata.create_all(bind=engine)  # <-- LINE 434: SYNC CALL IN ASYNC CONTEXT
                logger.info("Database tables created successfully")
            except Exception as e:
                logger.error(f"Failed to create database tables: {e}")
```

The problem:
1. `startup_event` is an async function
2. It uses `AsyncSessionLocal` to check the database connection (async)
3. Then it calls `Base.metadata.create_all(bind=engine)` where `engine` is a **sync** engine (from `app/database.py:30`)

This mixing of sync and async database operations in an async context causes the greenlet error.

### Why Python Playwright Tests Might Work
The Python Playwright tests (`tests_e2e/test_browser_ui.py`) use the `test_server_url` fixture in `tests_e2e/conftest.py:217-327`, which:
1. Uses `uvicorn.Server` with threading to start the server
2. Seeds the database manually before starting the server
3. The server might be configured differently

### Recommended Fix
Use async engine for table creation in the async startup event:

```python
@app.on_event("startup")
async def startup_event():
    """Initialize database on application startup."""
    import asyncio
    from sqlalchemy import text

    max_retries = 5
    retry_delay = 5  # seconds

    database_ready = False
    for attempt in range(1, max_retries + 1):
        try:
            async with AsyncSessionLocal() as db:
                await db.execute(text("SELECT 1"))
                database_ready = True
                logger.info("Database connection established successfully")
                break
        except Exception as e:
            logger.warning(f"Database connection attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                logger.error("All database connection attempts failed")

    if database_ready:
        if app_settings.environment == "production":
            logger.info("Production mode: Skipping table creation (migrations required)")
        else:
            try:
                # Use async engine for table creation
                from app.database import async_engine
                async with async_engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                logger.info("Database tables created successfully")
            except Exception as e:
                logger.error(f"Failed to create database tables: {e}")
```

## Issue 3: Python Playwright Tests

### Status
These tests use the `test_server_url` fixture which starts its own server. With a properly configured PostgreSQL database, these should work.

The tests require:
- `DATABASE_URL` or `TEST_DATABASE_URL` environment variable pointing to PostgreSQL
- PostgreSQL server running and accessible

### CI Configuration
The CI workflow has PostgreSQL configured as a service, and the Python test jobs have the proper environment variables set. These tests should pass once the database is properly configured.

## Next Steps

1. **Fix lint script** - Add better CI environment detection and error messages
2. **Fix async startup** - Update `app/main.py` to use async engine for table creation
3. **Test locally** - Verify fixes work before committing
4. **Run CI** - Confirm all tests pass

## Files to Modify

1. `scripts/lint.sh` - Better CI environment handling
2. `app/main.py` - Fix async table creation
