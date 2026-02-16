import { expect, test, type Page } from '@playwright/test';

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
    await expect(page.locator('#main-die-3d')).toBeVisible();

    await page.click('#main-die-3d');
    await page.waitForURL('**/rate', { timeout: 10000 });
    await expect(page.locator('#rating-input')).toBeVisible();

    await page.goto('/queue');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('#queue-container')).toBeVisible();

    expect(chunkFailures, `Chunk load failures: ${chunkFailures.join(', ')}`).toEqual([]);
  });

  test('roll, rate, save and continue routes back to roll view (existing prod user)', async ({
    page,
  }) => {
    const health = await page.request.get('/health');
    expect(health.ok()).toBeTruthy();

    const username = process.env.PROD_TEST_USERNAME;
    const password = process.env.PROD_TEST_PASSWORD;
    expect(username, 'Set PROD_TEST_USERNAME for existing-user smoke').toBeTruthy();
    expect(password, 'Set PROD_TEST_PASSWORD for existing-user smoke').toBeTruthy();

    const token = await loginExistingUser(page, username as string, password as string);

    await page.addInitScript((authToken: string) => {
      localStorage.setItem('auth_token', authToken);
    }, token);

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('#main-die-3d')).toBeVisible();

    await page.click('#main-die-3d');
    await page.waitForURL('**/rate', { timeout: 10000 });
    await expect(page.locator('#rating-input')).toBeVisible();

    await page.click('#submit-btn');
    await page.waitForURL('**/', { timeout: 10000 });
    await expect(page.locator('#main-die-3d')).toBeVisible();
  });

  test('leave and return to /rate before submit keeps same active thread (existing prod user)', async ({
    page,
  }) => {
    const health = await page.request.get('/health');
    expect(health.ok()).toBeTruthy();

    const username = process.env.PROD_TEST_USERNAME;
    const password = process.env.PROD_TEST_PASSWORD;
    expect(username, 'Set PROD_TEST_USERNAME for existing-user smoke').toBeTruthy();
    expect(password, 'Set PROD_TEST_PASSWORD for existing-user smoke').toBeTruthy();

    const token = await loginExistingUser(page, username as string, password as string);

    await page.addInitScript((authToken: string) => {
      localStorage.setItem('auth_token', authToken);
    }, token);

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('#main-die-3d')).toBeVisible();

    await page.click('#main-die-3d');
    await page.waitForURL('**/rate', { timeout: 10000 });
    await expect(page.locator('#thread-info h2')).toBeVisible();
    const titleBefore = (await page.locator('#thread-info h2').innerText()).trim();

    const beforeSession = await page.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(beforeSession.ok()).toBeTruthy();
    const beforeData = await beforeSession.json();
    const activeBefore = beforeData.active_thread?.id;
    expect(activeBefore).toBeTruthy();

    await page.goto('/history');
    await page.waitForLoadState('networkidle');

    await page.goto('/rate');
    await page.waitForURL('**/rate', { timeout: 10000 });
    await expect(page.locator('#thread-info h2')).toContainText(titleBefore);

    const afterSession = await page.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(afterSession.ok()).toBeTruthy();
    const afterData = await afterSession.json();
    expect(afterData.active_thread?.id).toBe(activeBefore);
  });
});
