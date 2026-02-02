# Docker-Based Python Playwright Tests - Implementation Task Sheet

## Overview

Convert broken Python Playwright browser tests to use Docker-based infrastructure, avoiding event loop conflicts by running the API server in an isolated process/container.

**Status**: 🔵 Ready to Start  
**Priority**: High (CI browser tests are broken)  
**Estimated Effort**: 8-12 hours  
**Deadline**: Before next CI run

---

## Problem Statement

**Current Issue**: Python Playwright tests in `tests_e2e/test_browser_ui.py` are fundamentally broken due to event loop conflicts:
- pytest-asyncio creates event loop #1
- Uvicorn daemon thread creates event loop #2  
- Playwright creates event loop #3
- All three conflict → 20-minute timeout → tests fail

**Root Cause**: The `test_server_url` fixture in `tests_e2e/conftest.py` spawns Uvicorn in a daemon thread within the same process, creating event loop conflicts with pytest-asyncio.

**Solution**: Run the API server in a Docker container (or subprocess) with complete process isolation.

---

## Implementation Approach

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ CI/Local Machine                                            │
│                                                             │
│  ┌──────────────┐      ┌──────────────┐                   │
│  │ pytest-asyncio│      │ Playwright   │                   │
│  │ (Event Loop 1)│      │ (Event Loop 2)│                  │
│  └──────────────┘      └──────────────┘                   │
│         │                       │                           │
│         └───────────┬───────────┘                           │
│                     │ HTTP requests                         │
│                     ▼                                       │
│  ┌──────────────────────────────────────────────┐          │
│  │ Docker Container / Subprocess                │          │
│  │                                              │          │
│  │  ┌─────────────────────────────────────┐    │          │
│  │  │ Uvicorn Server (Event Loop 3)       │    │          │
│  │  │ - Isolated process                  │    │          │
│  │  │ - No event loop conflicts           │    │          │
│  │  └─────────────────────────────────────┘    │          │
│  │                                              │          │
│  └──────────────────────────────────────────────┘          │
│                                                             │
└─────────────────────────────────────────────────────────────┘

         ┌─────────────────┐
         │ Docker Compose  │
         │ PostgreSQL only │
         └─────────────────┘
```

**Key Principle**: Each component runs in its own isolated process with its own event loop.

### Design Decisions

1. **No app service in docker-compose.test.yml**
   - Tests spawn their own Uvicorn server (via subprocess)
   - Avoids Docker-in-Docker complications
   - Simpler for local development

2. **Docker provides PostgreSQL only**
   - Tests run on host machine (or CI container)
   - Tests start Uvicorn as subprocess
   - Complete process isolation

3. **HTTP API for test data creation**
   - Remove direct database access from tests
   - Use registration/login APIs instead
   - More realistic end-to-end testing

4. **Backwards compatible**
   - Keep existing API tests (they work fine)
   - Only change browser UI tests
   - Can run both in parallel during migration

---

## Task Breakdown

### Phase 1: Create Docker Infrastructure (2 hours)

#### Task 1.1: Create `docker-compose.test.yml`
**File**: `/mnt/extra/josh/code/comic-pile/docker-compose.test.yml`  
**Owner**: Sub-agent "infrastructure"  
**Deliverables**:
- PostgreSQL service on port 5433
- Health checks configured
- Network setup
- Documentation in comments

**Spec**:
```yaml
services:
  postgres-test:
    image: postgres:16-alpine
    container_name: comic-pile-e2e-postgres
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: comic_pile_test
    ports:
      - "5433:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5
    networks:
      - test-network

networks:
  test-network:
    driver: bridge
```

**Verification**:
```bash
docker compose -f docker-compose.test.yml up -d
docker compose -f docker-compose.test.yml logs
# Should see "database system is ready to accept connections"
docker compose -f docker-compose.test.yml down
```

---

#### Task 1.2: Create `.env.test`
**File**: `/mnt/extra/josh/code/comic-pile/.env.test`  
**Owner**: Sub-agent "infrastructure"  
**Deliverables**:
- Environment variables for local testing
- Points to localhost:5433 (Docker PostgreSQL)
- Clear documentation

**Spec**:
```bash
# Test environment for Docker-based E2E tests
# Source with: source .env.test

# Database configuration (Docker PostgreSQL on port 5433)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/comic_pile_test
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/comic_pile_test

# Application secrets
SECRET_KEY=test-secret-key-for-testing-only

# Disable auto-backup in tests
AUTO_BACKUP_ENABLED=false

# Skip worktree validation in tests
SKIP_WORKTREE_CHECK=true
```

**Verification**:
```bash
source .env.test
echo $DATABASE_URL
# Should print: postgresql+asyncpg://postgres:postgres@localhost:5433/comic_pile_test
```

---

#### Task 1.3: Add Makefile Commands
**File**: `/mnt/extra/josh/code/comic-pile/Makefile`  
**Owner**: Sub-agent "infrastructure"  
**Deliverables**:
- `docker-test-up`: Start Docker test environment
- `docker-test-down`: Stop Docker test environment
- `docker-test-logs`: View logs
- `test-e2e-browser-docker`: Run tests with Docker
- `test-e2e-browser-quick`: Run tests (Docker already running)

**Spec**: Add to Makefile after line 294
```makefile
# Docker test environment for Python Playwright tests
docker-test-up:  ## Start Docker test environment (PostgreSQL only)
    @echo "Starting Docker test environment..."
    docker compose -f docker-compose.test.yml up -d
    @echo "Waiting for PostgreSQL to be ready..."
    @for i in {1..30}; do \
        if pg_isready -h localhost -p 5433 -U postgres 2>/dev/null; then \
            echo "✓ PostgreSQL is ready on port 5433"; \
            exit 0; \
        fi; \
        echo "Waiting for PostgreSQL... ($$i/30)"; \
        sleep 1; \
    done
    @echo "✗ PostgreSQL failed to start"
    exit 1

docker-test-down:  ## Stop Docker test environment
    @echo "Stopping Docker test environment..."
    docker compose -f docker-compose.test.yml down -v

docker-test-logs:  ## Show Docker test environment logs
    docker compose -f docker-compose.test.yml logs -f postgres-test

docker-test-health:  ## Check Docker test environment health
    @echo "Checking Docker test environment..."
    @docker compose -f docker-compose.test.yml ps

# Python Playwright browser tests with Docker
test-e2e-browser-docker:  ## Run Python Playwright tests with Docker (starts and stops Docker)
    @echo "Starting Docker test environment..."
    $(MAKE) docker-test-up
    @echo "Running Python Playwright tests..."
    @pytest tests_e2e/test_browser_ui.py -v --no-cov || ($(MAKE) docker-test-down && exit 1)
    @echo "Stopping Docker test environment..."
    $(MAKE) docker-test-down
    @echo "✓ Tests completed"

test-e2e-browser-quick:  ## Run Python Playwright tests (Docker must already be running)
    @echo "Running Python Playwright tests (assumes Docker is running)..."
    @pytest tests_e2e/test_browser_ui.py -v --no-cov
```

**Verification**:
```bash
make docker-test-up
make docker-test-health
# Should show postgres-test as "healthy"
make docker-test-down
```

---

### Phase 2: Update Test Fixtures (3 hours)

#### Task 2.1: Create New `docker_test_server_url` Fixture
**File**: `/mnt/extra/josh/code/comic-pile/tests_e2e/conftest.py`  
**Owner**: Sub-agent "test-fixtures"  
**Deliverables**:
- New fixture that spawns Uvicorn as subprocess
- Session-scoped (runs once per test session)
- Proper cleanup (kills subprocess after tests)
- Health check before yielding URL
- Error handling if server fails to start

**Implementation Details**:
- Add after line 340 (after old `test_server_url` fixture)
- Use `subprocess.Popen` to spawn Uvicorn
- Wait for `/health` endpoint to respond
- Yield `http://localhost:8000`
- Send SIGTERM on cleanup
- Remove old `test_server_url` fixture (lines 219-340)

**Key Code Structure**:
```python
@pytest_asyncio.fixture(scope="session")
async def docker_test_server_url():
    """Start uvicorn server for Docker-based browser tests.
    
    Spawns Uvicorn as a subprocess to avoid event loop conflicts
    with pytest-asyncio and Playwright.
    """
    import subprocess
    import signal
    
    # Setup database and test data
    test_db_url = get_test_database_url()
    os.environ["DATABASE_URL"] = test_db_url
    await _setup_docker_test_data(test_db_url)
    
    # Start uvicorn as subprocess
    port = 8000
    proc = subprocess.Popen(
        ["python", "-m", "uvicorn", "app.main:app",
         "--host", "0.0.0.0", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    # Wait for server to be ready
    for i in range(60):
        try:
            response = requests.get(f"http://localhost:{port}/health", timeout=1)
            if response.status_code == 200:
                break
        except Exception:
            time.sleep(1)
    else:
        proc.kill()
        raise RuntimeError("Server failed to start")
    
    yield f"http://localhost:{port}"
    
    # Cleanup
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=10)
```

**Verification**:
```python
# Write a simple test to verify fixture works
import pytest

@pytest.mark.asyncio
async def test_docker_server_starts(docker_test_server_url):
    """Verify the Docker test server fixture works."""
    import requests
    
    response = requests.get(f"{docker_test_server_url}/health")
    assert response.status_code == 200
```

---

#### Task 2.2: Create `_setup_docker_test_data` Helper
**File**: `/mnt/extra/josh/code/comic-pile/tests_e2e/conftest.py`  
**Owner**: Sub-agent "test-fixtures"  
**Deliverables**:
- Async function that creates tables and seeds test data
- Uses asyncpg only (no sync psycopg2)
- Creates sample threads for testing
- Creates default user (id=1)

**Implementation Details**:
- Add as module-level function before fixtures
- Use `create_async_engine` with test database URL
- Create tables with `Base.metadata.create_all`
- Seed sample data (3 threads, 1 session)
- Close engine after seeding

**Key Code Structure**:
```python
async def _setup_docker_test_data(test_db_url: str) -> None:
    """Setup test database schema and sample data for Docker tests."""
    from app.models import Session as SessionModel, Thread
    
    engine = create_async_engine(test_db_url, echo=False)
    
    try:
        # Create tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        # Seed data
        async_session_maker = async_sessionmaker(
            bind=engine,
            expire_on_commit=False,
            class_=SQLAlchemyAsyncSession,
        )
        
        async with async_session_maker() as session:
            await _ensure_default_user(session)
            
            threads = [
                Thread(title="Superman", format="Comic", issues_remaining=10,
                       queue_position=1, status="active", user_id=1),
                Thread(title="Batman", format="Comic", issues_remaining=5,
                       queue_position=2, status="active", user_id=1),
                Thread(title="Wonder Woman", format="Comic", issues_remaining=0,
                       queue_position=3, status="completed", user_id=1),
            ]
            for thread in threads:
                session.add(thread)
            await session.flush()
            
            session_obj = SessionModel(start_die=6, user_id=1)
            session.add(session_obj)
            await session.commit()
    finally:
        await engine.dispose()
```

**Verification**:
```python
# Manually test in Python REPL
import asyncio
from tests_e2e.conftest import _setup_docker_test_data, get_test_database_url

asyncio.run(_setup_docker_test_data(get_test_database_url()))
# Should complete without errors
```

---

#### Task 2.3: Update `test_user` Fixture
**File**: `/mnt/extra/josh/code/comic-pile/tests_e2e/conftest.py`  
**Owner**: Sub-agent "test-fixtures"  
**Deliverables**:
- Remove direct database access
- Use HTTP API to register users
- Return email address (for login)
- Function-scoped (creates fresh user per test)

**Implementation Details**:
- Replace existing `test_user` fixture (lines 27-70)
- Use `requests.post` to `/api/auth/register`
- Remove dependency on `async_db`
- Remove `app.dependency_overrides` manipulation

**Key Code Structure**:
```python
@pytest_asyncio.fixture(scope="function")
async def test_user(docker_test_server_url):
    """Create a fresh test user for each test via HTTP API."""
    import time
    
    test_timestamp = int(time.time() * 1000)
    test_email = f"test_{test_timestamp}@example.com"
    
    # Register via API
    response = requests.post(
        f"{docker_test_server_url}/api/auth/register",
        json={
            "username": test_email,
            "email": test_email,
            "password": "testpassword",
        },
        timeout=10,
    )
    assert response.status_code in (200, 201), f"Registration failed: {response.text}"
    
    yield test_email
    
    # No cleanup needed - each test gets fresh database
```

**Verification**:
```python
@pytest.mark.asyncio
async def test_user_fixture(docker_test_server_url, test_user):
    """Verify test_user fixture creates valid user."""
    # Login with the user
    response = requests.post(
        f"{docker_test_server_url}/api/auth/login",
        json={"username": test_user, "password": "testpassword"},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()
```

---

### Phase 3: Update Test Files (3 hours)

#### Task 3.1: Update `tests_e2e/test_browser_ui.py`
**File**: `/mnt/extra/josh/code/comic-pile/tests_e2e/test_browser_ui.py`  
**Owner**: Sub-agent "test-update"  
**Deliverables**:
- Replace all `test_server_url` with `docker_test_server_url`
- Remove all `async_db` parameters from tests
- Update test data creation to use HTTP API
- Update `login_with_playwright` helper

**Changes Required**:

1. **Update `login_with_playwright` helper** (lines 10-25):
```python
def login_with_playwright(page, docker_test_server_url, email, password=None):
    """Helper function to login via browser using HTTP API."""
    if password is None:
        password = "testpassword"
    
    # Get token via API
    login_response = requests.post(
        f"{docker_test_server_url}/api/auth/login",
        json={"username": email, "password": password},
        timeout=10,
    )
    assert login_response.status_code == 200
    access_token = login_response.json()["access_token"]
    
    # Set token in localStorage
    page.add_init_script(f"localStorage.setItem('auth_token', {json.dumps(access_token)})")
    page.goto(f"{docker_test_server_url}/")
    page.wait_for_load_state("networkidle", timeout=5000)
```

2. **Update all test function signatures**:
```python
# OLD:
async def test_root_url_renders_dice_ladder(browser_page, test_server_url, async_db, test_user):

# NEW:
async def test_root_url_renders_dice_ladder(browser_page, docker_test_server_url, test_user):
```

3. **Update test data creation** (for tests that need threads/sessions):
```python
# OLD (direct DB access):
thread = Thread(title="Roll Test Comic", format="Comic", ...)
async_db.add(thread)
await async_db.commit()

# NEW (HTTP API):
# First login to get token
login_response = requests.post(
    f"{docker_test_server_url}/api/auth/login",
    json={"username": test_user, "password": "testpassword"},
)
token = login_response.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# Create thread via API
response = requests.post(
    f"{docker_test_server_url}/api/threads/",
    json={"title": "Roll Test Comic", "format": "Comic", "issues_remaining": 5},
    headers=headers,
)
assert response.status_code in (200, 201)
thread_data = response.json()
```

4. **Remove all imports related to direct database access**:
```python
# Remove these imports:
from app.models import Thread, Session, Event
from sqlalchemy import text

# Keep these:
import json
import pytest
import pytest_asyncio
import requests
```

**Tests to Update**:
- `test_root_url_renders_dice_ladder` (line 74)
- `test_homepage_renders_dice_ladder` (line 87)
- `test_roll_dice_navigates_to_rate` (line 100)
- `test_queue_management_ui` (line 133)
- `test_view_history_pagination` (line 161)
- `test_full_session_workflow` (line 205)
- `test_d10_renders_geometry_correctly` (line 255)
- `test_auth_login_roll_rate_flow` (line 303)

**Verification**:
```bash
# Run a single test to verify it works
pytest tests_e2e/test_browser_ui.py::test_root_url_renders_dice_ladder -v --no-cov
```

---

#### Task 3.2: Update `tests_e2e/conftest.py` - Remove Broken Fixtures
**File**: `/mnt/extra/josh/code/comic-pile/tests_e2e/conftest.py`  
**Owner**: Sub-agent "test-fixtures"  
**Deliverables**:
- Remove old `test_server_url` fixture (lines 219-340)
- Remove old `test_user` fixture (lines 27-70)
- Keep other fixtures (browser_page, async_db, auth_api_client, etc.)

**What to Keep**:
- `_create_database_tables` (lines 38-53) - needed for API tests
- `_ensure_default_user` (lines 56-95) - needed for API tests
- `get_test_database_url` (lines 98-111) - needed for all tests
- `_find_free_port` (lines 114-120) - can remove (not used in Docker approach)
- `set_skip_worktree_check` (lines 126-135) - keep
- `enable_internal_ops` (lines 138-149) - keep
- `async_db` (lines 152-183) - keep (API tests still need it)
- `auth_api_client` (lines 342-356) - keep
- `auth_api_client_async` (lines 359-389) - keep
- `browser_page` (lines 392-399) - keep

**What to Remove**:
- `TEST_SERVER_PORT` (line 123) - not needed
- `test_server_url` (lines 219-340) - replaced by `docker_test_server_url`
- `test_user` (lines 27-70) - replaced by new version

**Verification**:
```bash
# Run API tests to ensure they still work
pytest tests_e2e/test_api_workflows.py -v --no-cov
# Run API dice ladder tests
pytest tests_e2e/test_dice_ladder_e2e.py -v --no-cov
```

---

### Phase 4: CI Integration (2 hours)

#### Task 4.1: Update CI Workflow
**File**: `/mnt/extra/josh/code/comic-pile/.github/workflows/ci-sharded.yml`  
**Owner**: Sub-agent "ci-integration"  
**Deliverables**:
- Replace 8 separate browser test jobs with single Docker-based job
- Simplify configuration
- Add test results upload
- Update documentation in comments

**Current Jobs to Replace** (lines 237-611):
- `test-e2e-browser-root`
- `test-e2e-browser-homepage`
- `test-e2e-browser-roll`
- `test-e2e-browser-queue`
- `test-e2e-browser-history`
- `test-e2e-browser-workflow`
- `test-e2e-browser-d10`
- `test-e2e-browser-auth`

**New Job Spec**:
```yaml
  test-e2e-browser-docker:
    name: E2E Browser Tests (Docker)
    runs-on: ubuntu-latest
    container:
      image: ${{ needs.build.outputs.image-tag }}
    needs: build
    timeout-minutes: 30
    env:
      CI: true
      SECRET_KEY: test-secret-key-for-testing-only
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/comic_pile_test
      TEST_DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/comic_pile_test
      PATH: "/workspace/.venv/bin:/usr/local/bin:/usr/bin:/bin"
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: comic_pile_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Wait for PostgreSQL
        run: |
          for i in {1..30}; do
            if pg_isready -h postgres -p 5432 -U postgres; then
              echo "✓ PostgreSQL is ready"
              exit 0
            fi
            echo "Waiting for PostgreSQL... ($i/30)"
            sleep 2
          done
          echo "✗ PostgreSQL failed to start"
          exit 1

      - name: Run Python Playwright tests
        run: pytest tests_e2e/test_browser_ui.py -v --no-cov

      - name: Upload Playwright test results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: python-playwright-results
          path: test-results/
          retention-days: 7
```

**Verification**:
- Push branch to trigger CI
- Check that `test-e2e-browser-docker` job appears
- Verify job completes successfully

---

#### Task 4.2: Update Documentation
**Files**:
- `README.md` (if it has testing section)
- `AGENTS.md` (update testing patterns)
- `CONTRIBUTING.md` (if it exists)

**Owner**: Sub-agent "documentation"  
**Deliverables**:
- Update testing instructions to reference Docker approach
- Document new Makefile commands
- Update AGENTS.md testing patterns section
- Add troubleshooting section

**Content to Add**:
```markdown
## Running Browser Tests

### Prerequisites
- Docker installed and running
- PostgreSQL running in Docker

### Local Testing
```bash
# Start Docker test environment
make docker-test-up

# Run tests (Docker already running)
pytest tests_e2e/test_browser_ui.py -v --no-cov

# Or use the convenience command (starts and stops Docker)
make test-e2e-browser-docker

# Stop Docker test environment
make docker-test-down
```

### Troubleshooting

**Issue**: "Connection refused" when accessing PostgreSQL
**Solution**: Ensure Docker test environment is running: `make docker-test-up`

**Issue**: Tests timeout after 20 minutes
**Solution**: This is the old event loop conflict. Ensure you're using the new Docker-based fixtures.

**Issue**: "Port 5433 already in use"
**Solution**: Stop the Docker test environment: `make docker-test-down`
```

**Verification**:
- Documentation builds without errors
- Commands work as documented
- Links and references are correct

---

### Phase 5: Testing and Validation (2 hours)

#### Task 5.1: Local Testing
**Owner**: Sub-agent "testing-validation"  
**Deliverables**:
- All 8 browser tests pass locally
- No event loop conflicts
- Test runtime < 10 minutes

**Test Checklist**:
- [ ] `test_root_url_renders_dice_ladder`
- [ ] `test_homepage_renders_dice_ladder`
- [ ] `test_roll_dice_navigates_to_rate`
- [ ] `test_queue_management_ui`
- [ ] `test_view_history_pagination`
- [ ] `test_full_session_workflow`
- [ ] `test_d10_renders_geometry_correctly`
- [ ] `test_auth_login_roll_rate_flow`

**Commands**:
```bash
# Start Docker test environment
make docker-test-up

# Run all browser tests
pytest tests_e2e/test_browser_ui.py -v --no-cov

# Run individual tests
pytest tests_e2e/test_browser_ui.py::test_root_url_renders_dice_ladder -v --no-cov

# Stop Docker test environment
make docker-test-down
```

**Success Criteria**:
- ✅ All 8 tests pass
- ✅ No timeout errors
- ✅ No event loop errors
- ✅ Tests complete in < 10 minutes
- ✅ No zombie processes left behind

---

#### Task 5.2: CI Validation
**Owner**: Sub-agent "testing-validation"  
**Deliverables**:
- All browser tests pass in CI
- Test artifacts uploaded successfully
- CI job completes in < 30 minutes

**Validation Steps**:
1. Push branch to GitHub
2. Watch CI workflow run
3. Check `test-e2e-browser-docker` job
4. Verify test results artifact
5. Check job runtime

**Success Criteria**:
- ✅ CI job passes
- ✅ Test results uploaded
- ✅ Job runtime < 30 minutes
- ✅ No flaky tests

---

#### Task 5.3: Regression Testing
**Owner**: Sub-agent "testing-validation"  
**Deliverables**:
- Existing API tests still pass
- Backend tests still pass
- No breaking changes to other test suites

**Test Commands**:
```bash
# Backend tests
pytest tests/ -v --cov=comic_pile

# E2E API tests
pytest tests_e2e/test_api_workflows.py -v --no-cov

# E2E Dice Ladder tests
pytest tests_e2e/test_dice_ladder_e2e.py -v --no-cov
```

**Success Criteria**:
- ✅ All existing tests still pass
- ✅ No test failures introduced
- ✅ No coverage loss

---

### Phase 6: Cleanup (1 hour)

#### Task 6.1: Remove Old Browser Test Jobs from CI
**File**: `.github/workflows/ci-sharded.yml`  
**Owner**: Sub-agent "cleanup"  
**Deliverables**:
- Delete 8 old browser test jobs (lines 237-611)
- Keep new Docker-based job
- Verify CI still works

**Jobs to Delete**:
- `test-e2e-browser-root`
- `test-e2e-browser-homepage`
- `test-e2e-browser-roll`
- `test-e2e-browser-queue`
- `test-e2e-browser-history`
- `test-e2e-browser-workflow`
- `test-e2e-browser-d10`
- `test-e2e-browser-auth`

**Verification**:
- CI workflow validates successfully
- New job still runs
- No duplicate jobs

---

#### Task 6.2: Update AGENTS.md
**File**: `/mnt/extra/josh/code/comic-pile/AGENTS.md`  
**Owner**: Sub-agent "documentation"  
**Deliverables**:
- Update testing patterns section
- Document Docker-based browser test approach
- Add troubleshooting section
- Remove references to old approach

**Section to Update**: "Testing Patterns" (around line 100)

**New Content**:
```markdown
## Testing Patterns

### Browser UI Tests (Python Playwright)

Browser UI tests use Docker for process isolation to avoid event loop conflicts.

**Architecture**:
- PostgreSQL runs in Docker container (port 5433)
- Tests spawn Uvicorn as subprocess (isolated process)
- Playwright controls browser (separate process)
- Each component has its own event loop

**Running Browser Tests**:
```bash
# Quick start (Docker managed automatically)
make test-e2e-browser-docker

# Manual control
make docker-test-up
pytest tests_e2e/test_browser_ui.py -v --no-cov
make docker-test-down
```

**Writing Browser Tests**:
- Use `docker_test_server_url` fixture (provides server URL)
- Use `test_user` fixture (creates user via HTTP API)
- Never use `async_db` in browser tests (use HTTP API instead)
- Use `login_with_playwright` helper for authentication

**Example**:
```python
@pytest.mark.asyncio
async def test_my_feature(browser_page, docker_test_server_url, test_user):
    page = browser_page
    login_with_playwright(page, docker_test_server_url, test_user)
    await page.goto(f"{docker_test_server_url}/")
    # ... test logic ...
```

**Do's and Don'ts**:
- ✅ Use HTTP API for test data creation
- ✅ Use `docker_test_server_url` fixture
- ✅ Clean up in fixtures (yield pattern)
- ❌ Never use `async_db` in browser tests
- ❌ Never use direct database access in browser tests
- ❌ Never use `test_server_url` (old broken fixture)
```

**Verification**:
- AGENTS.md is accurate
- Instructions work
- No broken links

---

## Success Criteria

### Functional Requirements
- ✅ All 8 browser tests pass locally
- ✅ All 8 browser tests pass in CI
- ✅ No event loop conflicts
- ✅ Test runtime < 10 minutes (local), < 30 minutes (CI)
- ✅ Zero regression in existing tests

### Non-Functional Requirements
- ✅ Code follows project style guidelines
- ✅ All lint checks pass (`make lint`)
- ✅ Type checking passes (`ty check --error-on-warning`)
- ✅ Documentation updated
- ✅ Makefile commands documented and working

### Quality Gates
- ✅ No new security vulnerabilities introduced
- ✅ No increase in test flakiness
- ✅ Docker containers properly cleaned up
- ✅ No zombie processes after tests

---

## Risk Mitigation

### Risk 1: Tests Still Timeout
**Probability**: Low  
**Impact**: High  
**Mitigation**:
- Subprocess approach provides complete process isolation
- Uvicorn runs in separate process with own event loop
- Health check ensures server is ready before tests run
- Timeout on server startup (60 seconds)

**Fallback**: If subprocess approach still has issues, use Docker Compose to run API in separate container.

---

### Risk 2: Breaking Existing Tests
**Probability**: Low  
**Impact**: High  
**Mitigation**:
- Only change `test_browser_ui.py` and fixtures
- Keep all other tests unchanged
- Run full test suite before committing
- Use feature branch for development

**Rollback Plan**: Keep old fixtures commented out for one week, then delete if everything works.

---

### Risk 3: Docker Port Conflicts
**Probability**: Medium  
**Impact**: Low  
**Mitigation**:
- Use port 5433 (different from dev on 5435)
- Add health checks to ensure port is free
- Document port usage in .env.test
- Makefile handles startup gracefully

**Fallback**: If port conflict occurs, document how to change port in docker-compose.test.yml.

---

## Timeline

| Week | Tasks | Owner | Deliverables |
|------|-------|-------|--------------|
| **Week 1, Day 1-2** | Phase 1: Docker Infrastructure | infrastructure | docker-compose.test.yml, .env.test, Makefile commands |
| **Week 1, Day 3-4** | Phase 2: Test Fixtures | test-fixtures | docker_test_server_url fixture, helpers |
| **Week 1, Day 5** | Phase 3: Update Tests | test-update | Updated test_browser_ui.py |
| **Week 2, Day 1** | Phase 4: CI Integration | ci-integration | Updated CI workflow |
| **Week 2, Day 2-3** | Phase 5: Testing & Validation | testing-validation | All tests passing locally and in CI |
| **Week 2, Day 4** | Phase 6: Cleanup & Documentation | cleanup, documentation | Final cleanup, updated docs |

**Total Estimated Effort**: 8-12 hours  
**Target Completion**: 2 weeks

---

## Rollback Plan

If critical issues arise:

1. **Immediate Rollback** (5 minutes):
   ```bash
   git revert <commit-hash>
   git push
   ```

2. **Partial Rollback** (15 minutes):
   - Keep Docker infrastructure (useful for other tests)
   - Restore old `test_server_url` fixture
   - Revert `test_browser_ui.py` changes

3. **Document Issues** (30 minutes):
   - Document what failed
   - Create GitHub issue
   - Propose alternative approach

---

## Next Steps

1. **Review this task sheet** and confirm approach
2. **Assign sub-agents** to each phase
3. **Begin with Phase 1** (Docker Infrastructure)
4. **Track progress** using GitHub project or TODO list
5. **Daily standups** to review progress and blockers

---

## Questions & Answers

**Q: Why not use Docker Compose to run the API server?**  
A: Running Uvicorn as a subprocess is simpler for local development and avoids Docker-in-Docker complications in CI. The subprocess provides complete process isolation, which is what we need.

**Q: What about TypeScript Playwright tests?**  
A: TypeScript tests use Playwright's built-in `webServer` feature and work differently. They're unaffected by these changes and can continue using their current approach.

**Q: Will this slow down the tests?**  
A: Slightly, due to subprocess overhead. However, the current tests don't work at all (20-minute timeout), so any improvement is better. Target is < 10 minutes for all 8 tests.

**Q: What if the subprocess doesn't terminate?**  
A: The fixture sends SIGTERM and waits up to 10 seconds. If it doesn't terminate, the fixture will raise an error. Zombie processes can be cleaned up with `pkill -f uvicorn`.

**Q: Can I run tests while Docker is already running?**  
A: Yes, use `make test-e2e-browser-quick` which assumes Docker is already running.

---

## Appendix: Reference Materials

### Files to Modify
1. `docker-compose.test.yml` (NEW)
2. `.env.test` (NEW)
3. `Makefile` (UPDATE)
4. `tests_e2e/conftest.py` (UPDATE)
5. `tests_e2e/test_browser_ui.py` (UPDATE)
6. `.github/workflows/ci-sharded.yml` (UPDATE)
7. `AGENTS.md` (UPDATE)
8. `README.md` (UPDATE - if applicable)

### Key Fixtures
- `docker_test_server_url` - Spawns Uvic subprocess
- `test_user` - Creates user via HTTP API
- `browser_page` - Playwright page (existing, no changes)

### Environment Variables
- `DATABASE_URL` - PostgreSQL connection string
- `TEST_DATABASE_URL` - Test database override
- `SECRET_KEY` - JWT secret
- `CI` - Set to "true" in CI environment

### Docker Services
- `postgres-test` - PostgreSQL 16 on port 5433

### Ports
- 5433: PostgreSQL (Docker tests)
- 5435: PostgreSQL (dev, from docker-compose.yml)
- 8000: Uvicorn server (subprocess)

---

**Last Updated**: 2025-02-01  
**Status**: 🔵 Ready to Start  
**Owner**: Assigned to sub-agents
