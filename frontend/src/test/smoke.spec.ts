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
    username: `smoke_${nonce}`,
    email: `smoke_${nonce}@example.com`,
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

test.describe('Smoke', () => {
  test('roll/rate/queue routes load without chunk 404s', async ({ page }) => {
    const health = await page.request.get('/health');
    expect(health.ok()).toBeTruthy();

    const token = await createAuthenticatedUser(page);
    await seedThreads(page, token, [
      { title: 'Smoke A', format: 'Comics', issues_remaining: 3 },
      { title: 'Smoke B', format: 'Manga', issues_remaining: 2 },
      { title: 'Smoke C', format: 'Novel', issues_remaining: 4 },
    ]);

    await page.addInitScript((authToken: string) => {
      localStorage.setItem('auth_token', authToken);
      (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN =
        authToken;
    }, token);

    const chunkFailures: string[] = [];
    page.on('response', (response) => {
      const url = response.url();
      if (url.includes('/assets/') && url.endsWith('.js') && response.status() >= 400) {
        chunkFailures.push(`${response.status()} ${url}`);
      }
    });

    await page.goto('/');
    await expect(page.locator('#root')).toBeVisible();
    await expect(page.locator(SELECTORS.roll.mainDie)).toBeVisible();

    await page.click(SELECTORS.roll.mainDie);
    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });
    await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible();

    await page.goto('/queue');
    await expect(page.locator('#root')).toBeVisible();
    await expect(page.locator(SELECTORS.threadList.container)).toBeVisible();

    expect(chunkFailures, `Chunk load failures: ${chunkFailures.join(', ')}`).toEqual([]);
  });

  test('roll, rate, save and continue clears pending and returns to roll view', async ({
    page,
  }) => {
    const health = await page.request.get('/health');
    expect(health.ok()).toBeTruthy();

    const token = await createAuthenticatedUser(page);
    await seedThreads(page, token, [
      { title: 'Roll Rate Save A', format: 'Comics', issues_remaining: 3 },
      { title: 'Roll Rate Save B', format: 'Manga', issues_remaining: 2 },
      { title: 'Roll Rate Save C', format: 'Novel', issues_remaining: 4 },
    ]);

    await page.addInitScript((authToken: string) => {
      localStorage.setItem('auth_token', authToken);
      (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN =
        authToken;
    }, token);

    await page.goto('/');
    await expect(page.locator('#root')).toBeVisible();
    await expect(page.locator(SELECTORS.roll.mainDie)).toBeVisible();

    await page.click(SELECTORS.roll.mainDie);
    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });
    await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible();

    await page.click(SELECTORS.rate.submitButton);
    await page.waitForURL('**/', { timeout: 10000 });
    await expect(page.locator(SELECTORS.roll.mainDie)).toBeVisible();
    await expect(page.locator(SELECTORS.rate.ratingInput)).toHaveCount(0);

    const currentSession = await page.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(currentSession.ok()).toBeTruthy();
    const sessionData = await currentSession.json();
    expect(sessionData.pending_thread_id).toBeNull();
  });

  test('leave and return to / before submit keeps same active thread', async ({ page }) => {
    const health = await page.request.get('/health');
    expect(health.ok()).toBeTruthy();

    const token = await createAuthenticatedUser(page);
    await seedThreads(page, token, [
      { title: 'Active Thread A', format: 'Comics', issues_remaining: 5 },
      { title: 'Active Thread B', format: 'Manga', issues_remaining: 5 },
      { title: 'Active Thread C', format: 'Novel', issues_remaining: 5 },
    ]);

    await page.addInitScript((authToken: string) => {
      localStorage.setItem('auth_token', authToken);
      (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN =
        authToken;
    }, token);

    await page.goto('/');
    await expect(page.locator('#root')).toBeVisible();
    await page.goto('/');
    await expect(page.locator('#root')).toBeVisible();
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
    await expect(page.locator('#root')).toBeVisible();

    await page.goto('/');
    await expect(page.locator('#root')).toBeVisible();
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
    const health = await page.request.get('/health');
    expect(health.ok()).toBeTruthy();

    const token = await createAuthenticatedUser(page);
    await seedThreads(page, token, [
      { title: 'Double Roll Test A', format: 'Comics', issues_remaining: 5 },
      { title: 'Double Roll Test B', format: 'Manga', issues_remaining: 5 },
      { title: 'Double Roll Test C', format: 'Novel', issues_remaining: 5 },
    ]);

    await page.addInitScript((authToken: string) => {
      localStorage.setItem('auth_token', authToken);
      (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN =
        authToken;
    }, token);

    const consoleLogs: Array<{ type: string; text: string }> = [];
    page.on('console', (msg) => {
      consoleLogs.push({ type: msg.type(), text: msg.text() });
    });

    await page.goto('/');
    await expect(page.locator('#root')).toBeVisible();

    const mainDie = page.locator('#main-die-3d');
    await expect(mainDie).toBeVisible();

    const getDieState = async () => {
      return mainDie.evaluate((el) => ({
        className: el.className,
        hasRollingClass: el.classList.contains('dice-state-rolling'),
      }));
    };

    console.log('Starting first roll...');
    const beforeFirst = await getDieState();
    expect(beforeFirst.hasRollingClass).toBe(false);

    await mainDie.click();

    await expect.poll(async () => (await getDieState()).hasRollingClass).toBe(true);
    const duringFirst = await getDieState();
    console.log('First roll state:', duringFirst);

    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 });
    console.log('First roll completed - rating view visible');

    await page.click(SELECTORS.rate.submitButton);

    await expect(mainDie).toBeVisible({ timeout: 15000 });
    console.log('Back at roll view after first rating');

    await expect.poll(async () => (await getDieState()).hasRollingClass).toBe(false);

    console.log('Starting second roll...');
    const beforeSecond = await getDieState();
    console.log('Before second roll:', beforeSecond);

    expect(beforeSecond.hasRollingClass).toBe(false);

    await mainDie.click();

    await expect.poll(async () => (await getDieState()).hasRollingClass).toBe(true);
    const duringSecond = await getDieState();
    console.log('Second roll state:', duringSecond);

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

    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 });
    console.log('Second roll completed successfully');
  });
});
