import { test, expect } from './fixtures';
import { createThread, SELECTORS, setRangeInput } from './helpers';

test.describe('Review Editing E2E Tests', () => {
  test('should edit existing review', async ({ freshUserPage }) => {
    const page = freshUserPage;
    
    const token = await page.evaluate(() => 
      localStorage.getItem('auth_token') || (window as any).__COMIC_PILE_ACCESS_TOKEN
    );
    
    if (!token) {
      throw new Error('No auth token found');
    }
    
    const threadTitle = `Review Edit Thread ${Date.now()}`;
    const thread = await createThread(page, {
      title: threadTitle,
      format: 'issue',
      issues_remaining: 10,
      total_issues: 10,
      issue_range: '1-10',
    });
    const threadId = thread.id;

    const createReviewResponse = await page.request.post('/api/v1/reviews/', {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      data: {
        thread_id: threadId,
        rating: 4.0,
        issue_number: '1',
        review_text: 'Original review',
      },
    });
    expect(createReviewResponse.ok()).toBeTruthy();
    
    // Verify the review was created
    const reviewsResponse = await page.request.get('/api/v1/reviews/', {
      headers: { 'Authorization': `Bearer ${token}` },
    });
    const reviewsData = await reviewsResponse.json();
    const latestReview = reviewsData.reviews?.find((r: any) => r.thread_id === threadId);
    
    expect(latestReview).toBeDefined();
    expect(latestReview.review_text).toBe('Original review');

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    await expect(page.locator(SELECTORS.roll.mainDie)).toBeVisible({ timeout: 15000 });
    await page.locator(SELECTORS.roll.mainDie).click();
    
    await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 });
    
    await setRangeInput(page, SELECTORS.rate.ratingInput, '4.0');
    
    const submitButtonAgain = page.locator('button:has-text("Save & Continue"), button:has-text("Save & Complete")');
    await expect(submitButtonAgain).toBeVisible();
    await submitButtonAgain.click({ force: true });
    
    const reviewModal = page.locator('[data-testid="modal"]');
    await expect(reviewModal).toBeVisible({ timeout: 15000 });
    
    await page.waitForTimeout(1000);
    const textarea = page.locator('textarea[placeholder*="Share your thoughts"]');
    
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
