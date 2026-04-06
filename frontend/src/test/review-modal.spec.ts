import { test, expect } from './fixtures';
import { SELECTORS, setRangeInput } from './helpers';

test.describe('Review Modal Behavior E2E Tests', () => {
  test('should handle review form cancellation', async ({ authenticatedWithThreadsPage }) => {
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
    await submitButton.click({ force: true });
    
    const reviewModal = page.locator('[data-testid="modal"]');
    await expect(reviewModal).toBeVisible({ timeout: 15000 });
    
    const textarea = page.locator('textarea[placeholder*="Share your thoughts"]');
    await textarea.fill('This review will be cancelled');
    
    const closeButton = reviewModal.locator('button[aria-label="Close modal"]');
    const closeButtonVisible = await closeButton.isVisible().catch(() => false);
    
    if (closeButtonVisible) {
      await closeButton.click();
    } else {
      const skipButton = page.locator('button:has-text("Skip")');
      await expect(skipButton).toBeVisible();
      await Promise.all([
        page.waitForResponse(r => r.url().includes('/api/rate/')),
        skipButton.click(),
      ]);
    }
    
    await expect(reviewModal).not.toBeVisible();
    
    await page.waitForTimeout(2000);
  });
});
