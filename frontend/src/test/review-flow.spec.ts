import { test, expect } from './fixtures';
import { SELECTORS, setRangeInput } from './helpers';

test.describe('Review Feature E2E Tests', () => {
  test('should complete full review flow: rate → write review → save → view', async ({ authenticatedWithThreadsPage }) => {
    // Navigate to a thread and start rating
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Select the first thread
    const firstThreadCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await expect(firstThreadCard).toBeVisible({ timeout: 10000 });
    await firstThreadCard.click();
    
    // Start reading
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });
    
    // Set a rating
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.5');
    
    // Submit the rating
    const submitButton = authenticatedWithThreadsPage.locator(SELECTORS.rate.submitButton);
    // Just click the button without waiting for response to see if it hangs
    await submitButton.click();
    
    // Wait a bit to see what happens
    await authenticatedWithThreadsPage.waitForTimeout(5000);
    
    // Wait for review modal to appear
    const reviewModal = authenticatedWithThreadsPage.locator('[data-testid="modal"]');
    await expect(reviewModal).toBeVisible({ timeout: 10000 });
    await expect(authenticatedWithThreadsPage.getByText('Write a Review?')).toBeVisible();
    
    // Verify thread and rating information is displayed
    await expect(authenticatedWithThreadsPage.locator('text=Reviewing')).toBeVisible();
    await expect(authenticatedWithThreadsPage.locator('text=Rating:')).toBeVisible();
    await expect(authenticatedWithThreadsPage.locator('text=4.5')).toBeVisible();
    
    // Write a review
    const textarea = authenticatedWithThreadsPage.locator('textarea[placeholder*="Share your thoughts"]');
    await expect(textarea).toBeVisible();
    await textarea.fill('This was an amazing issue! Great character development and artwork.');
    
    // Verify character count updates
    const characterCount = authenticatedWithThreadsPage.locator('text=/\\d+\\/2000 characters/');
    await expect(characterCount).toHaveText('55/2000 characters');
    
    // Save the review
    const saveButton = authenticatedWithThreadsPage.locator('button:has-text("Save Review")');
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse((response) =>
        response.url().includes('/api/reviews/') && response.request().method() === 'POST'
      ),
      saveButton.click(),
    ]);
    
    // Wait for modal to close and return to roll page
    await expect(reviewModal).not.toBeVisible({ timeout: 10000 });
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.roll.mainDie)).toBeVisible();
    
    // Navigate to thread detail page to verify review is displayed
    await authenticatedWithThreadsPage.goto('/queue');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Click on the thread again to view details
    const threadCardAgain = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await threadCardAgain.click();
    
    // Wait for thread detail page and check for reviews section
    await authenticatedWithThreadsPage.waitForURL(/\/thread\/\d+/);
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Verify review is displayed
    const reviewText = authenticatedWithThreadsPage.locator('text=This was an amazing issue!');
    await expect(reviewText).toBeVisible({ timeout: 10000 });
    await expect(authenticatedWithThreadsPage.locator('text=Rating: 4.5')).toBeVisible();
  });

  test('should skip review writing', async ({ authenticatedWithThreadsPage }) => {
    // Navigate to a thread and start rating
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Select the first thread
    const firstThreadCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await expect(firstThreadCard).toBeVisible({ timeout: 10000 });
    await firstThreadCard.click();
    
    // Start reading
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });
    
// Set a rating
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.5');
    
    // Submit the rating
    const submitButton = authenticatedWithThreadsPage.locator(SELECTORS.rate.submitButton);
    // Just click the button without waiting for response to see if it hangs
    await submitButton.click();
    
    // Wait a bit to see what happens
    await authenticatedWithThreadsPage.waitForTimeout(5000);
    
    // Wait for review modal to appear
    const reviewModal = authenticatedWithThreadsPage.locator('[data-testid="modal"]');
    await expect(reviewModal).toBeVisible({ timeout: 10000 });
    
    // Skip writing a review
    const skipButton = authenticatedWithThreadsPage.locator('button:has-text("Skip")');
    await skipButton.click();
    
    // Verify modal closes and returns to roll page
    await expect(reviewModal).not.toBeVisible({ timeout: 10000 });
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.roll.mainDie)).toBeVisible();
  });

  test('should edit existing review', async ({ authenticatedWithThreadsPage }) => {
    // First, create a review by going through the normal flow
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Select the first thread
    const firstThreadCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await expect(firstThreadCard).toBeVisible({ timeout: 10000 });
    await firstThreadCard.click();
    
    // Start reading
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });
    
    // Set a rating and create a review
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.0');
    const submitButton = authenticatedWithThreadsPage.locator(SELECTORS.rate.submitButton);
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse((response) =>
        response.url().includes('/api/rate/') && response.request().method() === 'POST'
      ),
      submitButton.click(),
    ]);
    
    // Wait for review modal and write a review
    const reviewModal = authenticatedWithThreadsPage.locator('[data-testid="modal"]');
    await expect(reviewModal).toBeVisible({ timeout: 10000 });
    
    const textarea = authenticatedWithThreadsPage.locator('textarea[placeholder*="Share your thoughts"]');
    await textarea.fill('Original review text');
    
    const saveButton = authenticatedWithThreadsPage.locator('button:has-text("Save Review")');
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse((response) =>
        response.url().includes('/api/reviews/') && response.request().method() === 'POST'
      ),
      saveButton.click(),
    ]);
    
    await expect(reviewModal).not.toBeVisible();
    
    // Now, rate the same issue again to trigger edit flow
    // Go back to roll page and start again
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Click the same thread
    const threadCardAgain = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await threadCardAgain.click();
    
    // Start reading again
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });
    
    // Set the same rating again
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.0');
    
    // Submit the rating
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse((response) =>
        response.url().includes('/api/rate/') && response.request().method() === 'POST'
      ),
      submitButton.click(),
    ]);
    
    // Verify edit modal appears with existing review
    await expect(reviewModal).toBeVisible({ timeout: 10000 });
    await expect(authenticatedWithThreadsPage.getByText('Edit Review')).toBeVisible();
    await expect(textarea).toHaveValue('Original review text');
    
    // Edit the review
    await textarea.fill('Updated review text with more details');
    const updateButton = authenticatedWithThreadsPage.locator('button:has-text("Update Review")');
    
    // Save the updated review
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse((response) =>
        response.url().includes('/api/reviews/') && (response.request().method() === 'PUT' || response.request().method() === 'POST')
      ),
      updateButton.click(),
    ]);
    
    await expect(reviewModal).not.toBeVisible();
    
    // Verify the review was updated by checking thread details
    await authenticatedWithThreadsPage.goto('/queue');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    const threadCardFinal = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await threadCardFinal.click();
    
    await authenticatedWithThreadsPage.waitForURL(/\/thread\/\d+/);
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Verify updated review is displayed
    await expect(authenticatedWithThreadsPage.locator('text=Updated review text with more details')).toBeVisible();
  });

  test('should handle network error during review submission', async ({ authenticatedWithThreadsPage }) => {
    // Navigate to a thread and start rating
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Select the first thread
    const firstThreadCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await expect(firstThreadCard).toBeVisible({ timeout: 10000 });
    await firstThreadCard.click();
    
    // Start reading
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });
    
    // Set a rating
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.5');
    
    // Submit the rating
    const submitButton = authenticatedWithThreadsPage.locator(SELECTORS.rate.submitButton);
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse((response) =>
        response.url().includes('/api/rate/') && response.request().method() === 'POST'
      ),
      submitButton.click(),
    ]);
    
    // Wait for review modal
    const reviewModal = authenticatedWithThreadsPage.locator('[data-testid="modal"]');
    await expect(reviewModal).toBeVisible({ timeout: 10000 });
    
    // Mock a network error for review submission
    await authenticatedWithThreadsPage.route('**/api/reviews/', route => route.abort('failed'));
    
    // Write a review
    const textarea = authenticatedWithThreadsPage.locator('textarea[placeholder*="Share your thoughts"]');
    await textarea.fill('This review should fail');
    
    // Try to save the review
    const saveButton = authenticatedWithThreadsPage.locator('button:has-text("Save Review")');
    await saveButton.click();
    
    // Verify error message appears and modal stays open
    const errorMessage = authenticatedWithThreadsPage.locator('.bg-red-500\\/10');
    await expect(errorMessage).toBeVisible({ timeout: 10000 });
    await expect(reviewModal).toBeVisible();
    
    // Verify save button is no longer in saving state
    await expect(saveButton).toHaveText('Save Review');
  });

  test('should enforce character limit in review textarea', async ({ authenticatedWithThreadsPage }) => {
    // Navigate to a thread and start rating
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Select the first thread
    const firstThreadCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await expect(firstThreadCard).toBeVisible({ timeout: 10000 });
    await firstThreadCard.click();
    
    // Start reading
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });
    
    // Set a rating
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.5');
    
    // Submit the rating
    const submitButton = authenticatedWithThreadsPage.locator(SELECTORS.rate.submitButton);
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse((response) =>
        response.url().includes('/api/rate/') && response.request().method() === 'POST'
      ),
      submitButton.click(),
    ]);
    
    // Wait for review modal
    const reviewModal = authenticatedWithThreadsPage.locator('[data-testid="modal"]');
    await expect(reviewModal).toBeVisible({ timeout: 10000 });
    
    // Try to type more than 2000 characters
    const textarea = authenticatedWithThreadsPage.locator('textarea[placeholder*="Share your thoughts"]');
    const longText = 'a'.repeat(2001);
    
    await textarea.fill(longText);
    
    // Verify it's truncated to 2000 characters
    const actualValue = await textarea.inputValue();
    expect(actualValue.length).toBe(2000);
    
    // Verify character count shows 2000/2000
    const characterCount = authenticatedWithThreadsPage.locator('text=/\\d+\\/2000 characters/');
    await expect(characterCount).toHaveText('2000/2000 characters');
  });

  test('should display issue-specific review information', async ({ authenticatedWithThreadsPage }) => {
    // Create a thread with multiple issues first
    const token = await authenticatedWithThreadsPage.evaluate(() => 
      localStorage.getItem('auth_token') || (window as any).__COMIC_PILE_ACCESS_TOKEN
    );
    
    // Create thread
    const createResponse = await authenticatedWithThreadsPage.request.post('/api/threads/', {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: {
        title: 'Multi-issue Test Thread',
        format: 'issue',
        issues_remaining: 3,
      },
    });
    expect(createResponse.ok()).toBeTruthy();
    const thread = await createResponse.json();
    
    // Create issues for the thread
    const issuesResponse = await authenticatedWithThreadsPage.request.post(`/api/v1/threads/${thread.id}/issues`, {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: {
        issue_range: '1-3',
      },
    });
    expect(issuesResponse.ok()).toBeTruthy();
    
    // Navigate to the thread
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Find and click the thread - try multiple selector strategies
    const threadCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black', { hasText: 'Multi-issue Test Thread' }),
    });
    
    // Wait for the thread to be visible
    await threadCard.waitFor({ state: 'attached', timeout: 10000 });
    
    // If still not visible, try alternative selector
    if (await threadCard.count() === 0) {
      // Try a broader selector
      const altThreadCard = authenticatedWithThreadsPage.locator('text=Multi-issue Test Thread').first();
      await altThreadCard.waitFor({ state: 'visible', timeout: 10000 });
      await altThreadCard.click();
    } else {
      await expect(threadCard).toBeVisible({ timeout: 10000 });
      await threadCard.click();
    }
    
    // Start reading
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });
    
    // Set a rating
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '5.0');
    
    // Submit the rating
    const submitButton = authenticatedWithThreadsPage.locator(SELECTORS.rate.submitButton);
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse((response) =>
        response.url().includes('/api/rate/') && response.request().method() === 'POST'
      ),
      submitButton.click(),
    ]);
    
    // Wait for review modal
    const reviewModal = authenticatedWithThreadsPage.locator('[data-testid="modal"]');
    await expect(reviewModal).toBeVisible({ timeout: 10000 });
    
    // Verify issue-specific information is displayed
    await expect(authenticatedWithThreadsPage.locator('text=Reviewing Multi-issue Test Thread #1')).toBeVisible();
    await expect(authenticatedWithThreadsPage.locator('text=Rating:')).toBeVisible();
    await expect(authenticatedWithThreadsPage.locator('text=5.0')).toBeVisible();
    
    // Write and save the review
    const textarea = authenticatedWithThreadsPage.locator('textarea[placeholder*="Share your thoughts"]');
    await textarea.fill('Great first issue!');
    
    const saveButton = authenticatedWithThreadsPage.locator('button:has-text("Save Review")');
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse((response) =>
        response.url().includes('/api/reviews/') && response.request().method() === 'POST'
      ),
      saveButton.click(),
    ]);
    
    await expect(reviewModal).not.toBeVisible();
    
    // Verify the review appears in thread details
    await authenticatedWithThreadsPage.goto('/queue');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    const threadCardAgain = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black', { hasText: 'Multi-issue Test Thread' }),
    });
    await threadCardAgain.click();
    
    await authenticatedWithThreadsPage.waitForURL(/\/thread\/\d+/);
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Verify review is displayed with issue information
    await expect(authenticatedWithThreadsPage.locator('text=Great first issue!')).toBeVisible();
    await expect(authenticatedWithThreadsPage.locator('text=Rating: 5.0')).toBeVisible();
  });

  test('should handle review form cancellation', async ({ authenticatedWithThreadsPage }) => {
    // Navigate to a thread and start rating
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Select the first thread
    const firstThreadCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await expect(firstThreadCard).toBeVisible({ timeout: 10000 });
    await firstThreadCard.click();
    
    // Start reading
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });
    
    // Set a rating
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.5');
    
    // Submit the rating
    const submitButton = authenticatedWithThreadsPage.locator(SELECTORS.rate.submitButton);
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse((response) =>
        response.url().includes('/api/rate/') && response.request().method() === 'POST'
      ),
      submitButton.click(),
    ]);
    
    // Wait for review modal
    const reviewModal = authenticatedWithThreadsPage.locator('[data-testid="modal"]');
    await expect(reviewModal).toBeVisible({ timeout: 10000 });
    
    // Write some text in the textarea
    const textarea = authenticatedWithThreadsPage.locator('textarea[placeholder*="Share your thoughts"]');
    await textarea.fill('This review will be cancelled');
    
    // Close the modal using the close button
    const closeButton = authenticatedWithThreadsPage.locator('button[aria-label="Close modal"]');
    await closeButton.click();
    
    // Verify modal closes and returns to roll page
    await expect(reviewModal).not.toBeVisible({ timeout: 10000 });
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.roll.mainDie)).toBeVisible();
    
    // Rate the same issue again to verify modal is fresh (no pre-filled text)
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    const threadCardAgain = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await threadCardAgain.click();
    
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });
    
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.5');
    
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse((response) =>
        response.url().includes('/api/rate/') && response.request().method() === 'POST'
      ),
      submitButton.click(),
    ]);
    
    // Verify review modal is fresh (no pre-filled text)
    await expect(reviewModal).toBeVisible({ timeout: 10000 });
    await expect(textarea).toHaveValue('');
  });
});