# E2E Tests

Playwright end-to-end tests for the Comic Pile application.

## Test Suites

### 1. Python Playwright Tests (tests_e2e/)
**Status**: ✅ Working in CI

These are pytest-based Playwright tests that run in Docker containers. They start their own backend server and are used in the CI pipeline.

```bash
# Run all Python E2E tests
pytest tests_e2e/ -m integration

# Run specific test file
pytest tests_e2e/test_browser_ui.py -v

# Run with video recording
pytest tests_e2e/ -m integration --video=retain-on-failure
```

**Test Files**:
- `test_api_workflows.py` - API integration tests
- `test_browser_ui.py` - Browser UI tests (registration, login, roll, rate, queue, history)
- `test_dice_ladder_e2e.py` - Dice ladder behavior tests

### 2. TypeScript Playwright Tests (frontend/src/test/)
**Status**: ✅ Working

These are Node.js-based Playwright tests with comprehensive coverage including accessibility and visual regression.

```bash
# Run all TypeScript E2E tests
cd frontend && npm run test:e2e

# Run in UI mode (interactive)
npm run test:e2e:ui

# Run specific test file
npx playwright test auth.spec.ts

# Run with headed browser
npm run test:e2e:headed
```

**Test Files**:
- `auth.spec.ts` - Authentication flow tests (8 tests)
- `threads.spec.ts` - Thread management tests (8 tests)
- `roll.spec.ts` - Dice rolling tests (11 tests)
- `rate.spec.ts` - Rating feature tests (14 tests)
- `analytics.spec.ts` - Analytics dashboard tests (12 tests)
- `history.spec.ts` - Session history tests (12 tests)
- `accessibility.spec.ts` - WCAG a11y tests (14 tests)
- `visual.spec.ts` - Screenshot regression tests (16 tests)
- `network.spec.ts` - API/network tests (15 tests)
- `edge-cases.spec.ts` - Edge case tests (20 tests)

## Known Issues

MissingGreenlet errors in `app/api/session.py` and `app/api/rate.py` have been fixed. If you encounter similar issues, ensure all SQLAlchemy model attributes are extracted into variables **before** `await db.commit()` (see `AGENTS.md` for the required pattern).

## CI Configuration

The CI pipeline (`.github/workflows/ci-sharded.yml`) runs:

1. **Python E2E Tests** ✅
   - `test-e2e-api` - API workflow tests
   - `test-e2e-dice-ladder` - Dice ladder behavior tests
   - `test-e2e-browser-*` - Individual browser UI tests (sharded for parallel execution)

2. **TypeScript E2E Tests** ✅
   - `test-e2e-playwright` - Playwright tests

## Local Development

### Running Python E2E Tests Locally

```bash
# Set environment variables
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/comic_pile_test"
export TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/comic_pile_test"
export SECRET_KEY="test-secret-key-for-testing-only"

# Run tests
pytest tests_e2e/test_browser_ui.py -v --no-cov
```

### Running TypeScript E2E Tests Locally

```bash
# Install dependencies
cd frontend
npm install
npx playwright install chromium

# Start backend (in separate terminal)
cd ..
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Run tests
cd frontend
npx playwright test --project=chromium
```

## Test Structure

### TypeScript Test Helpers

```typescript
import { test, expect } from './fixtures';
import { generateTestUser, loginUser, SELECTORS } from './helpers';

test('example test', async ({ authenticatedPage }) => {
  await authenticatedPage.goto('/');
  await expect(authenticatedPage.locator('h1')).toBeVisible();
});
```

**Fixtures**:
- `authenticatedPage` - Page with auto-login
- `testUser` - Generated test user data

**Helpers**:
- `generateTestUser()` - Create test user data
- `registerUser(page, user)` - Register via API
- `loginUser(page, user)` - Login and store token
- `createThread(page, data)` - Create thread via API
- `SELECTORS` - Centralized element selectors

### Python Test Helpers

```python
def login_with_playwright(page, test_server_url, email, password=None):
    """Helper function to login via browser."""
    login_response = requests.post(
        f"{test_server_url}/api/auth/login",
        json={"username": email, "password": password},
    )
    access_token = login_response.json()["access_token"]
    page.add_init_script(f"localStorage.setItem('auth_token', {json.dumps(access_token)})")
    page.goto(f"{test_server_url}/")
```

## Debugging Failed Tests

### TypeScript Tests

```bash
# Run with debug mode
npm run test:e2e:debug

# View trace
npx playwright show-trace test-results/<test-name>/trace.zip

# View screenshots
ls test-results/*/test-failed-*.png

# View HTML report
npx playwright show-report
```

### Python Tests

```bash
# Run single test with verbose output
pytest tests_e2e/test_browser_ui.py::test_root_url_renders_dice_ladder -vv

# Run with headed browser
pytest tests_e2e/test_browser_ui.py --headed

# Keep browser open on failure
pytest tests_e2e/test_browser_ui.py --debug
```

## Best Practices

1. **Isolation**: Each test should clean up after itself
2. **Fixtures**: Use provided fixtures for common operations
3. **Selectors**: Use centralized selectors from helpers
4. **Waits**: Avoid arbitrary timeouts; use waitForSelector/waitForURL
5. **CI-First**: Write tests that pass in CI environment (Docker + PostgreSQL)

## Next Steps

1. **Add more Python E2E tests** for coverage gaps
2. **Add visual regression baseline images** for screenshot tests
3. **Set up accessibility dashboard** for tracking a11y violations
