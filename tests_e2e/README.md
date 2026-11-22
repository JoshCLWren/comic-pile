# E2E Tests

## 🚫 CORE PRINCIPLE: NEVER SKIP TESTS

**TESTS MUST NEVER BE SKIPPED - EVER.**

When an E2E test fails:
- ✅ Fix the test
- ✅ Fix the code that breaks the test
- ✅ Investigate root cause (timing, selectors, flakiness)
- ❌ **NEVER skip the test**
- ❌ **NEVER mark it as flaky without fixing it**
- ❌ **NEVER use `.skip()` to work around failures**

E2E tests are your last line of defense against broken user experiences. Treat them with respect.

## Test Suites

> The legacy pytest-based Python Playwright suite that used to live in this directory was removed
> with the Python API. Browser E2E coverage now lives in `frontend/src/test/` (Playwright, TypeScript).
> This directory only holds this README.

### TypeScript Playwright Tests (frontend/src/test/)
**Status**: ✅ Working

These are Node.js-based Playwright tests with comprehensive coverage including accessibility and visual regression.

```bash
# Run all TypeScript E2E tests
cd frontend && pnpm run test:e2e

# Run in UI mode (interactive)
pnpm run test:e2e:ui

# Run specific test file
pnpm exec playwright test auth.spec.ts

# Run with headed browser
pnpm run test:e2e:headed
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

## CI Configuration

The CI pipeline (`.github/workflows/ci.yml`) runs:

1. **TypeScript E2E Tests** ✅
   - `test-e2e-playwright` - Playwright tests

## Local Development

### Running TypeScript E2E Tests Locally

```bash
# Install dependencies
cd frontend
pnpm install
pnpm exec playwright install chromium

# Start backend (in separate terminal)
cd ..
# Start the Rust API against a disposable local test database (never a shared or production one)
RUST_ROLL_BIND=127.0.0.1:8010 \
RUST_ROLL_DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/comic_pile_test" \
RUST_ROLL_JWT_SECRET="test-secret-key-for-testing-only" \
cargo run --locked -p comicpile-roll-service

# Run tests
cd frontend
pnpm exec playwright test --project=chromium
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

## Debugging Failed Tests

### TypeScript Tests

```bash
# Run with debug mode
pnpm run test:e2e:debug

# View trace
pnpm exec playwright show-trace test-results/<test-name>/trace.zip

# View screenshots
ls test-results/*/test-failed-*.png

# View HTML report
pnpm exec playwright show-report
```

## Best Practices

1. **Isolation**: Each test should clean up after itself
2. **Fixtures**: Use provided fixtures for common operations
3. **Selectors**: Use centralized selectors from helpers
4. **Waits**: Avoid arbitrary timeouts; use waitForSelector/waitForURL
5. **CI-First**: Write tests that pass in CI environment (Docker + PostgreSQL)

## Next Steps

1. **Add visual regression baseline images** for screenshot tests
2. **Set up accessibility dashboard** for tracking a11y violations
