import { expect, test } from './fixtures';
import { SELECTORS, setRangeInput } from './helpers';

async function openPendingThread(page: import('@playwright/test').Page): Promise<void> {
  await page.goto('/');
  await expect(page.locator('#root')).toBeVisible();

  const firstThreadCard = page.locator('[role="button"]').filter({
    has: page.locator('p.font-black'),
  }).first();
  await expect(firstThreadCard).toBeVisible({ timeout: 10000 });
  await firstThreadCard.click();
  await page.getByText('Read Now', { exact: true }).click();
  await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });
}

async function injectExpiredMutationOnce(
  page: import('@playwright/test').Page,
  endpoint: '/api/rate/' | '/api/snooze/',
): Promise<() => { attempts: number; committedAttempts: number }> {
  let attempts = 0;
  let committedAttempts = 0;

  await page.route(`**${endpoint}`, async (route) => {
    if (route.request().method() !== 'POST') {
      await route.continue();
      return;
    }

    attempts += 1;
    if (attempts === 1) {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Invalid or expired token' }),
      });
      return;
    }

    committedAttempts += 1;
    await route.continue();
  });

  return () => ({ attempts, committedAttempts });
}

test.describe('Roll mutation authentication recovery', () => {
  test('retries an expired-token rating once without losing or duplicating it', async ({
    authenticatedWithThreadsPage,
  }) => {
    await openPendingThread(authenticatedWithThreadsPage);
    const getCounts = await injectExpiredMutationOnce(authenticatedWithThreadsPage, '/api/rate/');

    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.5');
    await authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton);

    await expect(authenticatedWithThreadsPage.locator(SELECTORS.roll.mainDie)).toBeVisible({
      timeout: 10000,
    });
    await expect(authenticatedWithThreadsPage).not.toHaveURL(/\/login(?:\?|$)/);
    await expect.poll(() => getCounts()).toEqual({ attempts: 2, committedAttempts: 1 });
  });

  test('retries an expired-token snooze once without a login detour', async ({
    authenticatedWithThreadsPage,
  }) => {
    await openPendingThread(authenticatedWithThreadsPage);
    const getCounts = await injectExpiredMutationOnce(authenticatedWithThreadsPage, '/api/snooze/');

    await authenticatedWithThreadsPage.click(SELECTORS.rate.snoozeButton);

    await expect(authenticatedWithThreadsPage.locator(SELECTORS.roll.mainDie)).toBeVisible({
      timeout: 10000,
    });
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toHaveCount(0);
    await expect(authenticatedWithThreadsPage).not.toHaveURL(/\/login(?:\?|$)/);
    await expect.poll(() => getCounts()).toEqual({ attempts: 2, committedAttempts: 1 });
  });
});
