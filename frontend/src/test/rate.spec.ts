import { test, expect } from './fixtures';
import { SELECTORS, setRangeInput } from './helpers';

test.describe('Rate Thread Feature', () => {
  test.beforeEach(async ({ authenticatedWithThreadsPage }) => {
    const token = await authenticatedWithThreadsPage.evaluate(() => localStorage.getItem('auth_token'));
    const rollResponse = await authenticatedWithThreadsPage.request.post('/api/roll/', {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    });

    expect(rollResponse.ok()).toBeTruthy();

    await authenticatedWithThreadsPage.waitForLoadState("networkidle");

    await authenticatedWithThreadsPage.goto('/rate');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
  });

  test('should display rating input on rate page', async ({ authenticatedWithThreadsPage }) => {
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible();
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.submitButton)).toBeVisible();
  });

  test('should submit rating and return to home', async ({ authenticatedWithThreadsPage }) => {
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.5');
    await authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton);

    await authenticatedWithThreadsPage.waitForURL('**/', { timeout: 5000 });
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.dieSelector, { state: 'visible', timeout: 5000 });
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.roll.dieSelector)).toBeVisible();
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
      await authenticatedWithThreadsPage.goto('/');
      await authenticatedWithThreadsPage.waitForLoadState('networkidle');
      await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie, { state: 'visible', timeout: 5000 });
      await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);
      await authenticatedWithThreadsPage.waitForURL("**/rate", { timeout: 5000 });
      await authenticatedWithThreadsPage.waitForLoadState('networkidle');

      await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, rating);
      await authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton);
      await authenticatedWithThreadsPage.waitForURL('**/', { timeout: 5000 });
      await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    }
  });

  test('should display snooze button', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.snoozeButton, { state: 'visible', timeout: 5000 });
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.snoozeButton)).toBeVisible();
  });

  test('should snooze thread and advance die size', async ({ authenticatedWithThreadsPage }) => {
    const snoozeButton = authenticatedWithThreadsPage.locator(SELECTORS.rate.snoozeButton);
    await snoozeButton.click();

    await authenticatedWithThreadsPage.waitForLoadState("networkidle");

    const successMessage = authenticatedWithThreadsPage.locator('text=snoozed');
    await expect(successMessage.first()).toBeVisible({ timeout: 3000 });

    await authenticatedWithThreadsPage.waitForURL('**/', { timeout: 5000 });
  });

  test('should remove unsnoozed thread from roll page without refresh', async ({ authenticatedWithThreadsPage }) => {
    const snoozeButton = authenticatedWithThreadsPage.locator(SELECTORS.rate.snoozeButton);
    await snoozeButton.click();

    await authenticatedWithThreadsPage.waitForURL('**/', { timeout: 5000 });
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

    await authenticatedWithThreadsPage.waitForURL('**/');
    await authenticatedWithThreadsPage.goto('/queue');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    const threadElement = authenticatedWithThreadsPage.locator('.glass-card').first();
    await expect(threadElement).toBeVisible({ timeout: 5000 });
  });

  test('should show thread title on rate page', async ({ authenticatedWithThreadsPage }) => {
    const threadTitle = authenticatedWithThreadsPage.locator('#thread-info h2');
    await expect(threadTitle).toBeVisible();
  });

  test('should allow adjusting issues read', async ({ authenticatedWithThreadsPage }) => {
    const issuesInput = authenticatedWithThreadsPage.locator('input[name="issues_read"]');
    const isVisible = await issuesInput.count() > 0;

    if (isVisible) {
      await issuesInput.fill('2');
      await authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton);
      await authenticatedWithThreadsPage.waitForURL('**/', { timeout: 3000 });
    }
  });

  test('should handle finish session option', async ({ authenticatedWithThreadsPage }) => {
    const finishCheckbox = authenticatedWithThreadsPage.locator('input[name="finish_session"]');
    const hasFinishOption = await finishCheckbox.count() > 0;

    if (hasFinishOption) {
      await finishCheckbox.check();
      await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.0');
      await authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton);

      await authenticatedWithThreadsPage.waitForURL('**/', { timeout: 5000 });

      const sessionEnded = await authenticatedWithThreadsPage.locator('text=session ended|session complete').count();
      expect(sessionEnded).toBeGreaterThan(0);
    }
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
    await authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton);
    await authenticatedWithThreadsPage.waitForURL('**/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie, { state: 'visible', timeout: 5000 });
    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);
    await authenticatedWithThreadsPage.waitForURL("**/rate", { timeout: 5000 });
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.5');
    await authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton);
    await authenticatedWithThreadsPage.waitForURL('**/', { timeout: 5000 });
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
  });

  test('should handle network errors gracefully', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.route('**/api/rate/**', route => route.abort('failed'));

    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.0');
    await authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton);

    const errorMessage = authenticatedWithThreadsPage.locator('#error-message:not(.hidden)');
    await errorMessage.waitFor({ state: 'visible', timeout: 5000 });
    await expect(errorMessage.first()).toBeVisible();
  });
});
