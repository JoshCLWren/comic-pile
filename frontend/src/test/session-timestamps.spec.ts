import { test, expect } from './fixtures';
import { SELECTORS, setRangeInput } from './helpers';

test.describe('Session Timestamp Consistency (Issue #245)', () => {
  test('should display timestamps on Session Details page', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');

    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });

    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 5000 });

    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.0');
    await authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton);
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    await authenticatedWithThreadsPage.goto('/history');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    const sessionLink = authenticatedWithThreadsPage.locator('a[href^="/sessions/"]').first();
    await expect(async () => {
      const count = await sessionLink.count();
      if (count > 0) {
        await expect(sessionLink.first()).toBeVisible();
      }
    }).toPass({ timeout: 10000 });

    await sessionLink.first().click();
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    await expect(authenticatedWithThreadsPage.locator('h1:has-text("Session Details")')).toBeVisible();

    const timestampText = authenticatedWithThreadsPage.locator('text=/\\d{1,2}:\\d{2}\\s*[AP]M/i');
    await expect(timestampText.first()).toBeVisible();
  });

  test('should show session start and end labels', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });

    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 5000 });

    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '3.5');
    await authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton);
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    await authenticatedWithThreadsPage.goto('/history');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    const sessionLink = authenticatedWithThreadsPage.locator('a[href^="/sessions/"]').first();
    await expect(async () => {
      const count = await sessionLink.count();
      if (count > 0) {
        await expect(sessionLink.first()).toBeVisible();
      }
    }).toPass({ timeout: 10000 });

    await sessionLink.first().click();
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    await expect(authenticatedWithThreadsPage.locator('h1:has-text("Session Details")')).toBeVisible();

    const startTimeLabel = authenticatedWithThreadsPage.locator('p:has-text("Started")');
    const endTimeLabel = authenticatedWithThreadsPage.locator('p:has-text("Ended")');

    await expect(startTimeLabel).toBeVisible();
    await expect(endTimeLabel).toBeVisible();
  });
});
