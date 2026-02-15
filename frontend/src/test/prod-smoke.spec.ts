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

async function seedThreads(page: Page, token: string): Promise<void> {
  const threads = [
    { title: 'Prod Smoke A', format: 'Comic', issues_remaining: 3 },
    { title: 'Prod Smoke B', format: 'Manga', issues_remaining: 2 },
    { title: 'Prod Smoke C', format: 'Novel', issues_remaining: 4 },
  ];

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
    await seedThreads(page, token);

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
});

