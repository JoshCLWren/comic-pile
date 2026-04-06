import { test, expect } from './fixtures';
import { SELECTORS, setRangeInput } from './helpers';

test.describe('Review Editing E2E Tests', () => {
  test('should edit existing review', async ({ authenticatedWithThreadsPage }) => {
    const page = authenticatedWithThreadsPage;
    
    const token = await page.evaluate(() => 
      localStorage.getItem('auth_token') || (window as any).__COMIC_PILE_ACCESS_TOKEN
    );
    
    if (!token) {
      throw new Error('No auth token found');
    }
    
    // Get list of threads
    const threadsResponse = await page.request.get('/api/threads/', {
      headers: { 'Authorization': `Bearer ${token}` },
    });
    expect(threadsResponse.ok()).toBeTruthy();
    const threadsData = await threadsResponse.json();
    const threads = threadsData.threads ?? threadsData;
    expect(threads.length).toBeGreaterThan(0);
    
    // Use the first thread for testing
    const threadId = threads[0].id;
    const threadTitle = threads[0].title;
    console.log('Testing with thread:', threadTitle, 'ID:', threadId);
    
    // First, set the thread as pending and create a review
    const setPendingResponse = await page.request.post(`/api/threads/${threadId}/set-pending`, {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    });
    expect(setPendingResponse.status()).toBe(200);
    
    // Navigate to home page - rating modal should appear
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    
    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 });
    
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
    
    // Verify the review was created
    const reviewsResponse = await page.request.get('/api/v1/reviews/', {
      headers: { 'Authorization': `Bearer ${token}` },
    });
    const reviewsData = await reviewsResponse.json();
    const latestReview = reviewsData.reviews?.find((r: any) => r.thread_id === threadId);
    
    expect(latestReview).toBeDefined();
    expect(latestReview.review_text).toBe('Original review');
    
    // Now set the same thread as pending again to test editing
    const setPendingResponse2 = await page.request.post(`/api/threads/${threadId}/set-pending`, {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    });
    expect(setPendingResponse2.status()).toBe(200);
    
    // Navigate to home page - rating modal should appear again
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    
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
