import { expect, test, type Page } from '@playwright/test';
import { waitForQueueReady, waitForRollPageReady } from './helpers';

type TestUser = {
  username: string;
  email: string;
  password: string;
};

function createUser(): TestUser {
  const nonce = `${Date.now()}_${Math.floor(Math.random() * 1_000_000)}`;
  return {
    username: `prefetch_${nonce}`,
    email: `prefetch_${nonce}@example.com`,
    password: 'PrefetchPass123!',
  };
}

async function createAuthenticatedUser(page: Page): Promise<string> {
  const registerResponse = await page.request.post('/api/auth/register', {
    data: createUser(),
    timeout: 15000,
  });
  expect(registerResponse.ok()).toBeTruthy();
  const registerData = (await registerResponse.json()) as { access_token?: string };
  expect(registerData.access_token).toBeTruthy();
  return registerData.access_token as string;
}

test('prefetches the queue chunk on the Roll screen before navigation', async ({ page }) => {
  const health = await page.request.get('/health');
  expect(health.ok()).toBeTruthy();

  const token = await createAuthenticatedUser(page);
  await page.addInitScript((authToken: string) => {
    localStorage.setItem('auth_token', authToken);
    (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN =
      authToken;
  }, token);

  let queueChunkUrl: string | null = null;
  page.on('response', (response) => {
    const url = new URL(response.url());
    if (!url.pathname.startsWith('/assets/') || !url.pathname.endsWith('.js')) {
      return;
    }
    void response
      .text()
      .then((body) => {
        if (body.includes('Read Queue')) {
          queueChunkUrl = response.url();
        }
      })
      .catch(() => {});
  });

  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await waitForRollPageReady(page);

  await expect
    .poll(() => queueChunkUrl, {
      timeout: 15000,
      message: 'the queue chunk was not prefetched while on the Roll screen',
    })
    .not.toBeNull();

  await page.goto('/queue', { waitUntil: 'domcontentloaded' });
  await waitForQueueReady(page);
});
