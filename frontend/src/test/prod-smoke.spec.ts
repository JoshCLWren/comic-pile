import { expect, test, type Page } from '@playwright/test';
import { SELECTORS } from './helpers';

type TestUser = {
  username: string;
  email: string;
  password: string;
};

function createProdSmokeUser(): TestUser {
  const nonce = `${Date.now()}_${Math.floor(Math.random() * 1_000_000)}`;
  return {
    username: `prod_smoke_${nonce}`,
    email: `prod_smoke_${nonce}@example.com`,
    password: 'ProdSmokePass123!',
  };
}

async function createAuthenticatedUser(page: Page): Promise<string> {
  const user = createProdSmokeUser();

  const registerResponse = await page.request.post('/api/auth/register', {
    data: user,
    timeout: 15000,
  });
  expect(registerResponse.ok()).toBeTruthy();

  const loginResponse = await page.request.post('/api/auth/login', {
    data: { username: user.username, password: user.password },
    timeout: 15000,
  });
  expect(loginResponse.ok()).toBeTruthy();

  const loginData = await loginResponse.json();
  const token = loginData.access_token as string;
  expect(token).toBeTruthy();

  return token;
}

async function loginExistingUser(
  page: Page,
  username: string,
  password: string,
): Promise<string> {
  const loginResponse = await page.request.post('/api/auth/login', {
    data: { username, password },
    timeout: 15000,
  });
  expect(loginResponse.ok()).toBeTruthy();

  const loginData = await loginResponse.json();
  const token = loginData.access_token as string;
  expect(token).toBeTruthy();
  return token;
}

function getExistingUserCredentials() {
  const username = process.env.PROD_TEST_USERNAME;
  const password = process.env.PROD_TEST_PASSWORD;
  return { username, password };
}

async function seedThreads(
  page: Page,
  token: string,
  threads: Array<{ title: string; format: string; issues_remaining: number }>,
): Promise<void> {
  for (const thread of threads) {
    const response = await page.request.post('/api/threads/', {
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: thread,
      timeout: 15000,
    });
    expect(response.ok()).toBeTruthy();
  }
}

test.describe('Production Smoke', () => {
  test('roll/rate/queue routes load without chunk 404s', async ({ page }) => {
    const health = await page.request.get('/health');
    expect(health.ok()).toBeTruthy();

    const token = await createAuthenticatedUser(page);
    await seedThreads(page, token, [
      { title: 'Prod Smoke A', format: 'Comic', issues_remaining: 3 },
      { title: 'Prod Smoke B', format: 'Manga', issues_remaining: 2 },
      { title: 'Prod Smoke C', format: 'Novel', issues_remaining: 4 },
    ]);

    await page.addInitScript((authToken: string) => {
      localStorage.setItem('auth_token', authToken);
    }, token);

    const chunkFailures: string[] = [];
    page.on('response', (response) => {
      const url = response.url();
      if (url.includes('/assets/') && url.endsWith('.js') && response.status() >= 400) {
        chunkFailures.push(`${response.status()} ${url}`);
      }
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await expect(page.locator(SELECTORS.roll.mainDie)).toBeVisible();

    await page.click(SELECTORS.roll.mainDie);
    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });
    await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible();

    await page.goto('/queue');
    await page.waitForLoadState('networkidle');
    await expect(page.locator(SELECTORS.threadList.container)).toBeVisible();

    expect(chunkFailures, `Chunk load failures: ${chunkFailures.join(', ')}`).toEqual([]);
  });

  test('roll, rate, save and continue routes back to roll view (existing prod user)', async ({
    page,
  }) => {
    const health = await page.request.get('/health');
    expect(health.ok()).toBeTruthy();

    const { username, password } = getExistingUserCredentials();
    test.skip(!username || !password, 'Set PROD_TEST_USERNAME and PROD_TEST_PASSWORD for existing-user smoke');

    const token = await loginExistingUser(page, username as string, password as string);

    await page.addInitScript((authToken: string) => {
      localStorage.setItem('auth_token', authToken);
    }, token);

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await expect(page.locator(SELECTORS.roll.mainDie)).toBeVisible();

    await page.click(SELECTORS.roll.mainDie);
    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });
    await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible();

    await page.click(SELECTORS.rate.submitButton);
    await page.waitForURL('**/', { timeout: 10000 });
    await expect(page.locator(SELECTORS.roll.mainDie)).toBeVisible();
  });

  test('leave and return to / before submit keeps same active thread (existing prod user)', async ({
    page,
  }) => {
    const health = await page.request.get('/health');
    expect(health.ok()).toBeTruthy();

    const { username, password } = getExistingUserCredentials();
    test.skip(!username || !password, 'Set PROD_TEST_USERNAME and PROD_TEST_PASSWORD for existing-user smoke');

    const token = await loginExistingUser(page, username as string, password as string);

    await page.addInitScript((authToken: string) => {
      localStorage.setItem('auth_token', authToken);
    }, token);

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await expect(page.locator(SELECTORS.roll.mainDie)).toBeVisible();

    await page.click(SELECTORS.roll.mainDie);
    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });
    await expect(page.locator(SELECTORS.thread.title)).toBeVisible();
    const titleBefore = (await page.locator(SELECTORS.thread.title).innerText()).trim();

    const beforeSession = await page.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(beforeSession.ok()).toBeTruthy();
    const beforeData = await beforeSession.json();
    const activeBefore = beforeData.active_thread?.id;
    expect(activeBefore).toBeTruthy();

    await page.goto('/history');
    await page.waitForLoadState('networkidle');

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await expect(page.locator(SELECTORS.roll.mainDie)).toBeVisible();

    const afterSession = await page.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(afterSession.ok()).toBeTruthy();
    const afterData = await afterSession.json();
    expect(afterData.active_thread?.id).toBe(activeBefore);
    expect(afterData.active_thread?.title).toBe(titleBefore);
  });

  test('double roll animation works correctly', async ({ page }) => {
    // This test specifically checks the dice animation on consecutive rolls
    // which has been reported as not working in production
    const health = await page.request.get('/health');
    expect(health.ok()).toBeTruthy();

    const token = await createAuthenticatedUser(page);
    await seedThreads(page, token, [
      { title: 'Double Roll Test A', format: 'Comic', issues_remaining: 5 },
      { title: 'Double Roll Test B', format: 'Manga', issues_remaining: 5 },
      { title: 'Double Roll Test C', format: 'Novel', issues_remaining: 5 },
    ]);

    await page.addInitScript((authToken: string) => {
      localStorage.setItem('auth_token', authToken);
    }, token);

    // Collect browser console logs
    const consoleLogs: Array<{ type: string; text: string }> = [];
    page.on('console', (msg) => {
      consoleLogs.push({ type: msg.type(), text: msg.text() });
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const mainDie = page.locator('#main-die-3d');
    await expect(mainDie).toBeVisible();

    // Helper function to check rolling state
    const getDieState = async () => {
      return mainDie.evaluate((el) => ({
        className: el.className,
        hasRollingClass: el.classList.contains('dice-state-rolling'),
      }));
    };

    // ========== FIRST ROLL ==========
    console.log('Starting first roll...');
    const beforeFirst = await getDieState();
    expect(beforeFirst.hasRollingClass).toBe(false);

    await mainDie.click();

    // Check animation started
    await page.waitForTimeout(100);
    const duringFirst = await getDieState();
    console.log('First roll state:', duringFirst);

    // Wait for rating view
    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 });
    console.log('First roll completed - rating view visible');

    // ========== RETURN TO ROLL VIEW ==========
    // Click Save & Continue
    await page.click(SELECTORS.rate.submitButton);

    // Wait for navigation back to roll page
    await expect(mainDie).toBeVisible({ timeout: 15000 });
    console.log('Back at roll view after first rating');

    // Wait for state to fully settle
    await page.waitForTimeout(1000);

    // ========== SECOND ROLL ==========
    console.log('Starting second roll...');
    const beforeSecond = await getDieState();
    console.log('Before second roll:', beforeSecond);

    // The die should NOT be in rolling state before we click
    expect(beforeSecond.hasRollingClass).toBe(false);

    await mainDie.click();

    // Check animation started for second roll
    await page.waitForTimeout(100);
    const duringSecond = await getDieState();
    console.log('Second roll state:', duringSecond);

    // THIS IS THE KEY ASSERTION - the animation should be playing
    expect(
      duringSecond.hasRollingClass,
      `Second roll animation should be active. ` +
        `Before: ${JSON.stringify(beforeSecond)}, ` +
        `After: ${JSON.stringify(duringSecond)}. ` +
        `Relevant logs: ${consoleLogs
          .filter((l) => l.text.includes('isRolling') || l.text.includes('rolling'))
          .map((l) => `[${l.type}]${l.text}`)
          .join('; ')}`
    ).toBe(true);

    // Wait for second rating view to confirm roll completed
    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 });
    console.log('Second roll completed successfully');
  });
});
