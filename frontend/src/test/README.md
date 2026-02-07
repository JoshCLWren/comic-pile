# E2E Tests

Playwright end-to-end tests for the Comic Pile application.

## Test Structure

```
frontend/src/test/
├── fixtures.ts          # Test fixtures (auth, pages)
├── helpers.ts           # Test utilities and factories
├── auth.spec.ts         # Authentication flow tests
├── threads.spec.ts      # Thread management tests
├── roll.spec.ts         # Dice rolling feature tests
├── rate.spec.ts         # Rating functionality tests
├── analytics.spec.ts    # Analytics dashboard tests
├── history.spec.ts      # Session history tests
├── accessibility.spec.ts # WCAG accessibility tests
├── visual.spec.ts       # Visual regression tests
├── network.spec.ts      # Network/API integration tests
└── edge-cases.spec.ts   # Edge case and error handling tests
```

## Running Tests

```bash
# Run all E2E tests
cd frontend && npm run test:e2e

# Run tests in UI mode (interactive)
npm run test:e2e:ui

# Run tests in headed mode (visible browser)
npm run test:e2e:headed

# Debug tests
npm run test:e2e:debug

# Run specific test file
npx playwright test auth.spec.ts

# Run tests matching a pattern
npx playwright test -g "should login"
```

## Test Categories

### 1. Authentication Tests (`auth.spec.ts`)
- User registration
- Login/logout flows
- Password validation
- Session persistence
- Token handling

### 2. Thread Management Tests (`threads.spec.ts`)
- Create/edit/delete threads
- Queue ordering
- Form validation
- Thread metadata

### 3. Roll Feature Tests (`roll.spec.ts`)
- Dice rolling functionality
- 3D dice rendering
- Die size selection
- Roll animation
- Session state

### 4. Rate Feature Tests (`rate.spec.ts`)
- Rating submission
- Snooze functionality
- Issues tracking
- Session completion
- Form validation

### 5. Analytics Tests (`analytics.spec.ts`)
- Statistics display
- Charts/graphs
- Data filtering
- Export functionality

### 6. History Tests (`history.spec.ts`)
- Session history
- Pagination
- Session details
- Filtering

### 7. Accessibility Tests (`accessibility.spec.ts`)
- WCAG 2.1 AA compliance
- ARIA attributes
- Keyboard navigation
- Color contrast
- Focus management

### 8. Visual Regression Tests (`visual.spec.ts`)
- Page screenshots
- Component screenshots
- Cross-browser checks
- Responsive design

### 9. Network Tests (`network.spec.ts`)
- API request validation
- Error handling
- Retry logic
- Rate limiting
- CORS

### 10. Edge Cases Tests (`edge-cases.spec.ts`)
- Empty states
- Invalid inputs
- Network failures
- Concurrent operations
- Browser storage issues

## Writing New Tests

### Using Fixtures

```typescript
import { test, expect } from './fixtures';

test('my test', async ({ authenticatedPage }) => {
  // authenticatedPage is already logged in
  await authenticatedPage.goto('/');
  await expect(authenticatedPage.locator('h1')).toBeVisible();
});
```

### Using Helpers

```typescript
import { test, expect } from './fixtures';
import { generateTestUser, loginUser, createThread, SELECTORS } from './helpers';

test('my test', async ({ page }) => {
  const user = generateTestUser();
  await registerUser(page, user);
  await loginUser(page, user);

  await createThread(page, {
    title: 'Test Comic',
    format: 'Comic',
    issues_remaining: 5,
  });
});
```

### Using Selectors

```typescript
import { SELECTORS } from './helpers';

await page.click(SELECTORS.auth.submitButton);
await expect(page.locator(SELECTORS.roll.dieSelector)).toBeVisible();
```

## Best Practices

1. **Isolation**: Each test should be independent and clean up after itself
2. **Fixtures**: Use provided fixtures for common operations (auth, pages)
3. **Selectors**: Use centralized selectors from `helpers.ts`
4. **Waits**: Avoid arbitrary timeouts; use `waitForSelector` or `waitForURL`
5. **Assertions**: Be specific with expectations (text, visibility, state)
6. **Data**: Use helper functions to generate test data
7. **Accessibility**: Include a11y checks for new features
8. **Network**: Verify API calls and error handling

## Debugging

### Playwright Inspector

```bash
npm run test:e2e:debug
```

### Screenshots

Screenshots are automatically captured on failure. View them in:
- `test-results/` - Latest run
- `playwright-report/` - HTML report

### Traces

Traces are captured on first retry. View them:
```bash
npx playwright show-trace trace.zip
```

### HTML Report

```bash
npx playwright show-report
```

## CI/CD

Tests run in CI with:
- Single worker (avoid conflicts)
- 2 retries on failure
- Video recording
- Screenshot capture
- Trace recording

## Cross-Browser Testing

Tests run on:
- Chromium (Chrome)
- Firefox
- WebKit (Safari)
- Mobile Chrome (Pixel 5)
- Mobile Safari (iPhone 12)

To run specific browsers:
```bash
npx playwright test --project=chromium
npx playwright test --project=firefox
```
