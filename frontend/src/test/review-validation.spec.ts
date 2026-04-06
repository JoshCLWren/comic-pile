import { test, expect } from './fixtures';
import { SELECTORS, setRangeInput } from './helpers';

test.describe('Review Validation E2E Tests', () => {
  test('should enforce character limit in review textarea', async ({ authenticatedWithThreadsPage }) => {
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
    await expect(textarea).toBeVisible();
    
    const longText = 'a'.repeat(2001);
    await textarea.fill(longText);
    await page.waitForTimeout(500);
    
    const actualValue = await textarea.inputValue();
    expect(actualValue.length).toBe(2000);
    
    const characterCount = page.locator('text=/\\d+\\/2000 characters/');
    await expect(characterCount).toBeVisible();
    const countText = await characterCount.textContent();
    expect(countText).toBe('2000/2000 characters');
  });
});
