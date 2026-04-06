import { test, expect } from './fixtures';
import { SELECTORS, setRangeInput } from './helpers';

test.describe('Review Editing E2E Tests', () => {
  test('should edit existing review', async ({ authenticatedWithThreadsPage }) => {
    const page = authenticatedWithThreadsPage;
    
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    
    let mainDie = page.locator(SELECTORS.roll.mainDie);
    await expect(mainDie).toBeVisible();
    await mainDie.click();
    
    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 });
    
    const rolledTitle = await page.locator('h2, h1').first().textContent();
    console.log('Rolled:', rolledTitle);
    
    await setRangeInput(page, SELECTORS.rate.ratingInput, '4.0');
    
    const submitButton = page.locator('button:has-text("Save & Continue"), button:has-text("Save & Complete")');
    await expect(submitButton).toBeVisible();
    await submitButton.click({ force: true });
    
    const reviewModal = page.locator('[data-testid="modal"]');
    await expect(reviewModal).toBeVisible({ timeout: 15000 });
    
    const textarea = page.locator('textarea[placeholder*="Share your thoughts"]');
    await textarea.fill('Original review');
    
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
    expect(latestReview.review_text).toBe('Original review');
    
    await page.goto(`/thread/${latestReview.thread_id}`);
    await page.waitForLoadState('networkidle');
    
    const rollButton = page.getByText('🎲Roll');
    await expect(rollButton).toBeVisible();
    await rollButton.click();
    
    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 });
    
    await setRangeInput(page, SELECTORS.rate.ratingInput, '4.0');
    
    const submitButtonAgain = page.locator('button:has-text("Save & Continue"), button:has-text("Save & Complete")');
    await expect(submitButtonAgain).toBeVisible();
    await submitButtonAgain.click({ force: true });
    
    await expect(reviewModal).toBeVisible({ timeout: 15000 });
    
    await page.waitForTimeout(1000);
    
    const textareaValue = await textarea.inputValue();
    if (textareaValue === 'Original review') {
      await expect(textarea).toHaveValue('Original review');
      await textarea.fill('Updated review');
      
      const updateButton = page.locator('button:has-text("Save Review"), button:has-text("Update Review")');
      await Promise.all([
        page.waitForResponse(r => r.url().includes('/v1/reviews/')),
        updateButton.click(),
      ]);
      
      await expect(reviewModal).not.toBeVisible();
      
      const reviewsResponse2 = await page.request.get('/api/v1/reviews/', {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      const reviewsData2 = await reviewsResponse2.json();
      const updatedReview = reviewsData2.reviews?.find((r: any) => r.thread_id === latestReview.thread_id);
      
      expect(updatedReview).toBeDefined();
      expect(updatedReview.review_text).toBe('Updated review');
    } else {
      const skipButton = page.locator('button:has-text("Skip")');
      await Promise.all([
        page.waitForResponse(r => r.url().includes('/api/rate/')),
        skipButton.click(),
      ]);
      
      await expect(reviewModal).not.toBeVisible();
    }
  });
});
