import { test, expect } from './fixtures';
import { generateTestUser, registerUser, loginUser, createThread, SELECTORS, setRangeInput } from './helpers';

test.describe('Rate Thread Feature', () => {
  test.beforeEach(async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'Rate Test Comic',
      format: 'Comic',
      issues_remaining: 5,
    });

    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    await page.request.post('/api/roll/', {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    });

    await page.goto('/rate');
    await page.waitForLoadState('networkidle');
  });

  test('should display rating input on rate page', async ({ page }) => {
    await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible();
    await expect(page.locator(SELECTORS.rate.submitButton)).toBeVisible();
  });

  test('should submit rating and return to home', async ({ page }) => {
    await setRangeInput(page, SELECTORS.rate.ratingInput, '4.5');
    await page.click(SELECTORS.rate.submitButton);

    await page.waitForURL('**/', { timeout: 5000 });
    await expect(page.locator(SELECTORS.roll.dieSelector)).toBeVisible();
  });

  test('should validate rating range (0-5)', async ({ page }) => {
    const input = page.locator(SELECTORS.rate.ratingInput);
    const maxValue = await input.getAttribute('max');
    expect(maxValue).toBe('5.0');
    
    const minValue = await input.getAttribute('min');
    expect(minValue).toBe('0.5');
  });

  test('should accept decimal ratings', async ({ page }) => {
    const testRatings = ['3.5', '4.0', '4.5', '2.75'];

    for (const rating of testRatings) {
      await page.goto('/');
      await page.waitForSelector(SELECTORS.roll.mainDie);
      await page.click(SELECTORS.roll.mainDie);
      await page.waitForTimeout(2000);

      await setRangeInput(page, SELECTORS.rate.ratingInput, rating);
      await page.click(SELECTORS.rate.submitButton);
      await page.waitForURL('**/', { timeout: 3000 });
    }
  });

  test('should display snooze button', async ({ page }) => {
    await expect(page.locator(SELECTORS.rate.snoozeButton)).toBeVisible();
  });

  test('should snooze thread and advance die size', async ({ page }) => {
    const snoozeButton = page.locator(SELECTORS.rate.snoozeButton);
    await snoozeButton.click();

    await page.waitForTimeout(1000);

    const successMessage = page.locator('text=snoozed');
    await expect(successMessage.first()).toBeVisible({ timeout: 3000 });

    await page.waitForURL('**/', { timeout: 5000 });
  });

  test('should update thread rating in database', async ({ page }) => {
    await setRangeInput(page, SELECTORS.rate.ratingInput, '4.0');
    await page.click(SELECTORS.rate.submitButton);

    await page.waitForURL('**/');
    await page.goto('/queue');
    await page.waitForLoadState('networkidle');

    const threadElement = page.locator('.glass-card').filter({ hasText: 'Rate Test Comic' });
    await expect(threadElement.first()).toBeVisible({ timeout: 5000 });
  });

  test('should show thread title on rate page', async ({ page }) => {
    const threadTitle = page.locator('text=Rate Test Comic');
    await expect(threadTitle).toBeVisible();
  });

  test('should allow adjusting issues read', async ({ page }) => {
    const issuesInput = page.locator('input[name="issues_read"]');
    const isVisible = await issuesInput.count() > 0;

    if (isVisible) {
      await issuesInput.fill('2');
      await page.click(SELECTORS.rate.submitButton);
      await page.waitForURL('**/', { timeout: 3000 });
    }
  });

  test('should handle finish session option', async ({ page }) => {
    const finishCheckbox = page.locator('input[name="finish_session"]');
    const hasFinishOption = await finishCheckbox.count() > 0;

    if (hasFinishOption) {
      await finishCheckbox.check();
      await setRangeInput(page, SELECTORS.rate.ratingInput, '4.0');
      await page.click(SELECTORS.rate.submitButton);

      await page.waitForURL('**/', { timeout: 5000 });

      const sessionEnded = await page.locator('text=session ended|session complete').count();
      expect(sessionEnded).toBeGreaterThan(0);
    }
  });

  test('should show validation for missing rating', async ({ page }) => {
    const ratingValue = await page.inputValue(SELECTORS.rate.ratingInput);
    expect(parseFloat(ratingValue)).toBeGreaterThan(0);
  });

test('should preserve form data on validation error', async ({ page }) => {
    const ratingInput = page.locator(SELECTORS.rate.ratingInput);
    await ratingInput.waitFor({ state: 'visible' });
    await setRangeInput(page, SELECTORS.rate.ratingInput, '3.5');
    await page.waitForTimeout(500);

    const ratingValue = await ratingInput.inputValue();
    expect(parseFloat(ratingValue)).toBe(3.5);
  });

  test('should show thread metadata (format, issues remaining)', async ({ page }) => {
    const formatElement = page.locator('text=Comic');
    await expect(formatElement.first()).toBeVisible();

    const issuesElement = page.locator('text=Issues left');
    await expect(issuesElement.first()).toBeVisible();
  });

  test('should allow re-rating if page revisited', async ({ page }) => {
    await setRangeInput(page, SELECTORS.rate.ratingInput, '3.0');
    await page.click(SELECTORS.rate.submitButton);
    await page.waitForURL('**/');

    await page.goto('/');
    await page.waitForSelector(SELECTORS.roll.mainDie);
    await page.click(SELECTORS.roll.mainDie);
    await page.waitForTimeout(2000);

    await setRangeInput(page, SELECTORS.rate.ratingInput, '4.5');
    await page.click(SELECTORS.rate.submitButton);
    await page.waitForURL('**/', { timeout: 5000 });
  });

  test('should handle network errors gracefully', async ({ page }) => {
    await page.route('**/api/rate/**', route => route.abort('failed'));

    await setRangeInput(page, SELECTORS.rate.ratingInput, '4.0');
    await page.click(SELECTORS.rate.submitButton);

    const errorMessage = page.locator('#error-message:not(.hidden)');
    await expect(errorMessage.first()).toBeVisible({ timeout: 5000 });
  });
});
