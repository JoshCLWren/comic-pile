import { test, expect } from './fixtures';
import { SELECTORS, setRangeInput } from './helpers';

test.describe('Review Creation E2E Tests', () => {
  test('should complete full review flow', async ({ authenticatedWithThreadsPage }) => {
    const page = authenticatedWithThreadsPage;
    
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    
    const mainDie = page.locator(SELECTORS.roll.mainDie);
    await expect(mainDie).toBeVisible();
    await mainDie.click();
    
    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 });
    
    const rolledTitle = await page.locator('h2, h1').first().textContent();
    console.log('Rolled:', rolledTitle);
    
    await setRangeInput(page, SELECTORS.rate.ratingInput, '4.5');
    
    const submitButton = page.locator('button:has-text("Save & Continue"), button:has-text("Save & Complete")');
    await expect(submitButton).toBeVisible();
    await submitButton.click({ force: true });
    
    const reviewModal = page.locator('[data-testid="modal"]');
    await expect(reviewModal).toBeVisible({ timeout: 15000 });
    
    const textarea = page.locator('textarea[placeholder*="Share your thoughts"]');
    await textarea.fill('Great review!');
    
    const saveButton = page.locator('button:has-text("Save Review")');
    await Promise.all([
      page.waitForResponse(r => r.url().includes('/api/rate/')),
      page.waitForResponse(r => r.url().includes('/v1/reviews/')),
      saveButton.click(),
    ]);
    
    await expect(reviewModal).not.toBeVisible();
    
    const token = await page.evaluate(() => 
      localStorage.getItem('auth_token') || (window as any).__COMIC_PILE_ACCESS_TOKEN
    );
    
    const reviewsResponse = await page.request.get('/api/v1/reviews/', {
      headers: { 'Authorization': `Bearer ${token}` },
    });
    const reviewsData = await reviewsResponse.json();
    const latestReview = reviewsData.reviews?.[0];
    
    expect(latestReview).toBeDefined();
    expect(latestReview.review_text).toBe('Great review!');
    
    await page.goto(`/thread/${latestReview.thread_id}`);
    await page.waitForLoadState('networkidle');
    await expect(page.locator(`text=${latestReview.review_text}`)).toBeVisible();
  });

  test('should skip review writing', async ({ authenticatedWithThreadsPage }) => {
    const page = authenticatedWithThreadsPage;
    
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    
    const mainDie = page.locator(SELECTORS.roll.mainDie);
    await expect(mainDie).toBeVisible();
    await mainDie.click();
    
    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 });
    
    await setRangeInput(page, SELECTORS.rate.ratingInput, '3.5');
    
    const submitButton = page.locator('button:has-text("Save & Continue"), button:has-text("Save & Complete")');
    await expect(submitButton).toBeVisible();
    await submitButton.click({ force: true });
    
    const reviewModal = page.locator('[data-testid="modal"]');
    await expect(reviewModal).toBeVisible({ timeout: 15000 });
    
    const skipButton = page.locator('button:has-text("Skip")');
    await expect(skipButton).toBeVisible();
    
    await Promise.all([
      page.waitForResponse(r => r.url().includes('/api/rate/')),
      skipButton.click(),
    ]);
    
    await expect(reviewModal).not.toBeVisible();
    
    await page.waitForTimeout(2000);
  });
});
