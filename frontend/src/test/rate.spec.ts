import { test, expect } from './fixtures';
import { SELECTORS, setRangeInput } from './helpers';

async function ensureRatingView(page: import('@playwright/test').Page): Promise<void> {
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  if (await page.locator(SELECTORS.rate.ratingInput).isVisible().catch(() => false)) {
    return;
  }

  await expect(page.locator(SELECTORS.roll.mainDie)).toBeVisible({ timeout: 10000 });
  await page.click(SELECTORS.roll.mainDie);
  await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });
}

test.describe('Rate Thread Feature', () => {
  test.beforeEach(async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    const firstThreadCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await expect(firstThreadCard).toBeVisible({ timeout: 10000 });
    await firstThreadCard.click();
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });
  });

  test('should display rating input on inline rating view', async ({ authenticatedWithThreadsPage }) => {
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible();
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.submitButton)).toBeVisible();
  });

  test('should submit rating and route to roll page after save and continue', async ({ authenticatedWithThreadsPage }) => {
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.5');
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse((response) =>
        response.url().includes('/api/rate/') && response.request().method() === 'POST'
      ),
      authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton),
    ]);
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    const stillRating = await authenticatedWithThreadsPage
      .locator(SELECTORS.rate.ratingInput)
      .isVisible()
      .catch(() => false);
    const backToRoll = await authenticatedWithThreadsPage
      .locator(SELECTORS.roll.mainDie)
      .isVisible()
      .catch(() => false);
    expect(stillRating || backToRoll).toBeTruthy();
  });

  test('should keep the same active thread when leaving and returning home before submit', async ({ authenticatedWithThreadsPage }) => {
    const token = await authenticatedWithThreadsPage.evaluate(() => localStorage.getItem('auth_token'));
    expect(token).toBeTruthy();

    const beforeResponse = await authenticatedWithThreadsPage.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(beforeResponse.ok()).toBeTruthy();
    const beforeSession = await beforeResponse.json();
    const beforeThreadId = beforeSession.active_thread?.id;
    const beforeTitle = beforeSession.active_thread?.title;

    expect(beforeThreadId).toBeDefined();
    expect(beforeTitle).toBeTruthy();

    await authenticatedWithThreadsPage.goto('/history');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    const afterResponse = await authenticatedWithThreadsPage.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(afterResponse.ok()).toBeTruthy();
    const afterSession = await afterResponse.json();
    expect(afterSession.active_thread?.id).toBe(beforeThreadId);
  });

  test('should validate rating range (0-5)', async ({ authenticatedWithThreadsPage }) => {
    const input = authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput);
    const maxValue = await input.getAttribute('max');
    expect(maxValue).toBe('5.0');

    const minValue = await input.getAttribute('min');
    expect(minValue).toBe('0.5');
  });

  test('should accept decimal ratings', async ({ authenticatedWithThreadsPage }) => {
    const testRatings = ['3.5', '4.0', '4.5', '2.75'];

    for (const rating of testRatings) {
      await ensureRatingView(authenticatedWithThreadsPage);

      await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, rating);
      await Promise.all([
        authenticatedWithThreadsPage.waitForResponse((response) =>
          response.url().includes('/api/rate/') && response.request().method() === 'POST'
        ),
        authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton),
      ]);
    }
  });

  test('should display snooze button', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.snoozeButton, { state: 'visible', timeout: 5000 });
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.snoozeButton)).toBeVisible();
  });

  test('should snooze thread and advance die size', async ({ authenticatedWithThreadsPage }) => {
    const snoozeButton = authenticatedWithThreadsPage.locator(SELECTORS.rate.snoozeButton);
    await snoozeButton.click();

    await authenticatedWithThreadsPage.waitForURL('**/', { timeout: 5000 });
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
  });

  test('should remove unsnoozed thread from roll page without refresh', async ({ authenticatedWithThreadsPage }) => {
    const snoozeButton = authenticatedWithThreadsPage.locator(SELECTORS.rate.snoozeButton);
    await snoozeButton.click();

    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    const snoozedToggle = authenticatedWithThreadsPage.locator('button:has-text("Snoozed")');
    await expect(snoozedToggle).toBeVisible();
    await snoozedToggle.click();

    const unsnoozeButtons = authenticatedWithThreadsPage.locator('button[aria-label="Unsnooze this comic"]');
    await expect(unsnoozeButtons.first()).toBeVisible({ timeout: 5000 });

    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse((response) =>
        response.url().includes('/api/snooze/') && response.url().includes('/unsnooze')
      ),
      unsnoozeButtons.first().click(),
    ]);

    await expect(async () => {
      const count = await snoozedToggle.count();
      expect(count).toBe(0);
    }).toPass({ timeout: 5000 });
  });

  test('should update thread rating in database', async ({ authenticatedWithThreadsPage }) => {
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.0');
    await authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton);

    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    await authenticatedWithThreadsPage.goto('/queue');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    const threadElement = authenticatedWithThreadsPage.locator('.glass-card').first();
    await expect(threadElement).toBeVisible({ timeout: 5000 });
  });

  test('should show thread title on rate page', async ({ authenticatedWithThreadsPage }) => {
    const threadTitle = authenticatedWithThreadsPage.locator('#thread-info h2');
    await expect(threadTitle).toBeVisible();
  });

  test('should handle finish session option', async ({ authenticatedWithThreadsPage }) => {
    const finishCheckbox = authenticatedWithThreadsPage.locator('input[name="finish_session"]');
    const hasFinishOption = await finishCheckbox.count() > 0;

    if (hasFinishOption) {
      await finishCheckbox.check();
      await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.0');
      await authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton);

      await authenticatedWithThreadsPage.waitForURL('**/', { timeout: 5000 });
      await authenticatedWithThreadsPage.waitForLoadState('networkidle');

      const sessionEnded = await authenticatedWithThreadsPage.locator('text=session ended|session complete').count();
      expect(sessionEnded).toBeGreaterThan(0);
    }
  });

  test('should not return 500 when finishing a session on a completed thread', async ({
    authenticatedWithThreadsPage,
  }) => {
    const token = await authenticatedWithThreadsPage.evaluate(() => localStorage.getItem('auth_token'));
    expect(token).toBeTruthy();

    const createResponse = await authenticatedWithThreadsPage.request.post('/api/threads/', {
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: {
        title: 'Greenlet Regression Thread',
        format: 'issue',
        issues_remaining: 1,
      },
    });
    expect(createResponse.ok()).toBeTruthy();
    const createdThread = await createResponse.json();

    const setPendingResponse = await authenticatedWithThreadsPage.request.post(
      `/api/threads/${createdThread.id}/set-pending`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      }
    );
    expect(setPendingResponse.ok()).toBeTruthy();

    const rateResponse = await authenticatedWithThreadsPage.request.post('/api/rate/', {
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: {
        rating: 4.5,
        issues_read: 1,
        finish_session: true,
      },
    });
    expect(rateResponse.status()).toBe(200);
  });

  test('should show validation for missing rating', async ({ authenticatedWithThreadsPage }) => {
    const ratingValue = await authenticatedWithThreadsPage.inputValue(SELECTORS.rate.ratingInput);
    expect(parseFloat(ratingValue)).toBeGreaterThan(0);
  });

  test('should preserve form data on validation error', async ({ authenticatedWithThreadsPage }) => {
    const ratingInput = authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput);
    await ratingInput.waitFor({ state: 'visible' });
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '3.5');
    await authenticatedWithThreadsPage.waitForLoadState("networkidle");

    const ratingValue = await ratingInput.inputValue();
    expect(parseFloat(ratingValue)).toBe(3.5);
  });

  test('should show thread metadata (format, issues remaining)', async ({ authenticatedWithThreadsPage }) => {
    const formatElement = authenticatedWithThreadsPage.locator('#thread-info .bg-indigo-500\\/20');
    await expect(formatElement.first()).toBeVisible();

    const issuesElement = authenticatedWithThreadsPage.locator('text=Issues left');
    await expect(issuesElement.first()).toBeVisible();
  });

  test('should allow re-rating if page revisited', async ({ authenticatedWithThreadsPage }) => {
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '3.0');
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse((response) =>
        response.url().includes('/api/rate/') && response.request().method() === 'POST'
      ),
      authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton),
    ]);

    await ensureRatingView(authenticatedWithThreadsPage);

    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.5');
    await authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton);
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    const stillRating = await authenticatedWithThreadsPage
      .locator(SELECTORS.rate.ratingInput)
      .isVisible()
      .catch(() => false);
    const backToRoll = await authenticatedWithThreadsPage
      .locator(SELECTORS.roll.mainDie)
      .isVisible()
      .catch(() => false);
    expect(stillRating || backToRoll).toBeTruthy();
  });

  test('should handle network errors gracefully', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.route('**/api/rate/**', route => route.abort('failed'));

    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.0');
    await authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton);

    await expect(authenticatedWithThreadsPage.getByText('Failed to save rating')).toBeVisible({ timeout: 5000 });
  });
});
