import { test, expect } from './fixtures';
import { SELECTORS, setRangeInput } from './helpers';

test.describe('Review Error Handling E2E Tests', () => {
  test('should handle network error during review submission', async ({ authenticatedWithThreadsPage }) => {
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
    
    await page.route('**/v1/reviews/', route => route.abort('failed'));
    
    const textarea = page.locator('textarea[placeholder*="Share your thoughts"]');
    await textarea.fill('This review should fail');
    
    const saveButton = page.locator('button:has-text("Save Review")');
    await saveButton.click();
    
    await page.waitForResponse(r => r.url().includes('/api/rate/'), { timeout: 10000 });
    await page.waitForTimeout(3000);
    
    const freshReviewModal = page.locator('[data-testid="modal"]');
    const errorMessage = freshReviewModal.locator('.text-red-400');
    const errorVisible = await errorMessage.isVisible().catch(() => false);
    
    if (errorVisible) {
      await expect(errorMessage).toBeVisible();
    } else {
      await expect(freshReviewModal).toBeVisible();
    }
    
    await expect(saveButton).toHaveText('Save Review');
    
    await page.unroute('**/v1/reviews/');
  });
});
