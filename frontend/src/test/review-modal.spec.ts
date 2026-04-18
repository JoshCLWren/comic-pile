import { test, expect } from './fixtures';
import { SELECTORS, setRangeInput } from './helpers';

test.describe('Review Modal Behavior E2E Tests', () => {
  test('does not open the cancellation modal while reviews are disabled', async ({ authenticatedWithThreadsPage }) => {
    const page = authenticatedWithThreadsPage;
    
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    
    const mainDie = page.locator(SELECTORS.roll.mainDie);
    await expect(mainDie).toBeVisible();
    await mainDie.click();
    
    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 });
    
    await setRangeInput(page, SELECTORS.rate.ratingInput, '4.5');
    
    const submitButton = page.locator('button:has-text("Save & Continue"), button:has-text("Save & Complete")');
    await expect(submitButton).toBeVisible();
    await Promise.all([
      page.waitForResponse((response) => response.url().includes('/api/rate/')),
      submitButton.click({ force: true }),
    ]);

    await expect(page.locator('[data-testid="modal"]')).toHaveCount(0);
    await expect(page.locator('textarea[placeholder*="Share your thoughts"]')).toHaveCount(0);
    await expect(page.locator(SELECTORS.roll.mainDie)).toBeVisible();
  });
});
