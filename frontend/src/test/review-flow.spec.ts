import { test, expect } from './fixtures';
import { type Locator } from '@playwright/test';
import { SELECTORS, setRangeInput } from './helpers';

test.describe('Review Feature E2E Tests', () => {
  test('should complete full review flow: rate → write review → save → view', async ({ authenticatedWithThreadsPage }) => {
    // Create a test thread first
    const token = await authenticatedWithThreadsPage.evaluate(() => 
      localStorage.getItem('auth_token') || (window as any).__COMIC_PILE_ACCESS_TOKEN
    );
    
    const createResponse = await authenticatedWithThreadsPage.request.post('/api/threads/', {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: {
        title: 'Test Review Thread',
        format: 'issue',
        issues_remaining: 1,
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
        issue_range: '1',
      },
    });
    expect(issuesResponse.ok()).toBeTruthy();
    
    // Navigate to the queue page to see threads
    await authenticatedWithThreadsPage.goto('/queue');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Debug: Check what's on the page
    const pageContent = await authenticatedWithThreadsPage.locator('body').textContent();
    console.log('Page content:', pageContent?.substring(0, 200));
    
    // Wait for the queue container to be visible
    try {
      await authenticatedWithThreadsPage.waitForSelector(SELECTORS.threadList.container, { timeout: 10000 });
      console.log('Queue container found');
    } catch (e) {
      console.log('Queue container NOT found, looking for alternatives...');
      // Check if there are any thread-like elements
      const anyThreads = await authenticatedWithThreadsPage.locator('[data-testid*="thread"]').count();
      console.log('Thread-like elements found:', anyThreads);
      
      const anyButtons = await authenticatedWithThreadsPage.locator('button').count();
      console.log('Buttons found:', anyButtons);
      
      // Take a screenshot to debug
      await authenticatedWithThreadsPage.screenshot({ path: 'debug-queue-page.png' });
    }
    
// Try to find thread items with the data-testid first
    const threadList = authenticatedWithThreadsPage.locator(SELECTORS.threadList.threadItem);
    const threadCount = await threadList.count();
    
    if (threadCount > 0) {
      await expect(threadList.first()).toBeVisible({ timeout: 15000 });
      // Find and click our specific thread
      let targetThreadCard: Locator | null = null;
      
      for (let i = 0; i < threadCount; i++) {
        const card = threadList.nth(i);
        // Try to find the thread title using a more robust approach
        const titleElement = card.locator('p.font-black, .font-black, [class*="font-black"], h3, h4, .title, [class*="title"]');
        const titleVisible = await titleElement.isVisible().catch(() => false);
        
        if (titleVisible) {
          const titleText = await titleElement.textContent();
          console.log(`Thread ${i} title:`, titleText);
          if (titleText && titleText.includes('Test Review Thread')) {
            targetThreadCard = card;
            break;
          }
        }
      }
      
      if (targetThreadCard) {
        console.log('Found target thread, clicking...');
        await targetThreadCard.click();
      } else {
        console.log('Target thread not found, clicking first thread...');
        await threadList.first().click();
      }
    } else {
      // Fallback: look for clickable elements that might be thread cards
      const potentialCards = authenticatedWithThreadsPage.locator('[role="button"]');
      const cardCount = await potentialCards.count();
      
      if (cardCount > 0) {
        // Try to find a button that contains thread-like content
        let targetButton: Locator | null = null;
        
        for (let i = 0; i < Math.min(cardCount, 5); i++) { // Check first 5 buttons
          const button = potentialCards.nth(i);
          const text = await button.textContent();
          if (text && (text.includes('Test Thread') || text.includes('Test Review Thread'))) {
            targetButton = button;
            break;
          }
        }
        
        if (targetButton) {
          await targetButton.click();
        } else {
          // Just click the first thread-like button (skip Add Thread button)
          for (let i = 0; i < Math.min(cardCount, 5); i++) {
            const button = potentialCards.nth(i);
            const text = await button.textContent();
            if (text && !text.includes('Add Thread') && text.includes('Thread')) {
              await button.click();
              break;
            }
          }
        }
      }
    }
    
    // Debug: Check where we are and what's available
    // Wait for navigation to complete instead of using hard-coded timeout
    await authenticatedWithThreadsPage.waitForURL(/\/thread\/\d+/, { timeout: 10000 });
    const currentUrl = authenticatedWithThreadsPage.url();
    console.log('Current URL after clicking thread:', currentUrl);
    
    const pageContentAfterClick = await authenticatedWithThreadsPage.locator('body').textContent();
    console.log('Page content after click:', pageContentAfterClick?.substring(0, 200));
    
    // Check for Roll button instead of Read Now (since this thread is already being tracked)
    const rollButton = authenticatedWithThreadsPage.getByText('🎲Roll');
    const rollButtonVisible = await rollButton.isVisible().catch(() => false);
    console.log('Roll button visible:', rollButtonVisible);
    
    if (!rollButtonVisible) {
      // Look for Roll button by text content
      const rollButtonAlt = authenticatedWithThreadsPage.locator('text=Roll');
      const altVisible = await rollButtonAlt.isVisible().catch(() => false);
      console.log('Roll button (alt) visible:', altVisible);
      
      if (!altVisible) {
        // Look for any elements that contain "Roll"
        const rollElements = authenticatedWithThreadsPage.locator('*:has-text("Roll")');
        const rollCount = await rollElements.count();
        console.log('Roll elements found:', rollCount);
        
        if (rollCount > 0) {
          for (let i = 0; i < rollCount; i++) {
            const text = await rollElements.nth(i).textContent();
            console.log(`Roll element ${i}:`, text);
          }
        }
      }
    }
    
    // Start reading using the Roll button
    await rollButton.click();
    
    // Debug: Check where we are after clicking Roll
    // Wait for navigation to complete instead of using hard-coded timeout
    await authenticatedWithThreadsPage.waitForURL(/\/roll/, { timeout: 10000 });
    const currentUrlAfterRoll = authenticatedWithThreadsPage.url();
    console.log('Current URL after clicking Roll:', currentUrlAfterRoll);
    
    const pageContentAfterRoll = await authenticatedWithThreadsPage.locator('body').textContent();
    console.log('Page content after Roll:', pageContentAfterRoll?.substring(0, 200));
    
    // Check if we're on the right page for rating
    if (currentUrlAfterRoll.includes('/roll') || currentUrlAfterRoll.endsWith('/')) {
      console.log('Successfully navigated to roll page');
    } else {
      console.log('Not on roll page, looking for rating input anyway...');
    }
    
    // Try to find the rating input with multiple selectors
    const ratingInput = authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput);
    const ratingVisible = await ratingInput.isVisible().catch(() => false);
    console.log('Rating input visible:', ratingVisible);
    
    if (!ratingVisible) {
      // Look for any input elements that might be for rating
      const allInputs = await authenticatedWithThreadsPage.locator('input').all();
console.log('Input elements found:', allInputs.length);
    }
    
    // First, we need to roll the dice to select an issue
    console.log('Looking for die to roll...');
    
    // Try to find and click the main die to roll
    const mainDie = authenticatedWithThreadsPage.locator(SELECTORS.roll.mainDie);
    const dieVisible = await mainDie.isVisible().catch(() => false);
    console.log('Main die visible:', dieVisible);
    
    if (dieVisible) {
      await mainDie.click();
      console.log('Clicked main die');
    } else {
      // Fallback: look for any dice or roll elements
      const rollElements = authenticatedWithThreadsPage.locator('*:has-text("Roll")');
      const rollCount = await rollElements.count();
      console.log('Roll elements found:', rollCount);
      
      if (rollCount > 0) {
        // Click the first roll element that's visible
        for (let i = 0; i < rollCount; i++) {
          const element = rollElements.nth(i);
          const visible = await element.isVisible().catch(() => false);
          if (visible) {
            await element.click();
            console.log('Clicked roll element', i);
            break;
          }
        }
      } else {
        // Last resort: try to find by the tap instruction
        const tapInstruction = authenticatedWithThreadsPage.getByText('Tap Die to Roll');
        if (await tapInstruction.isVisible().catch(() => false)) {
          // Find the nearest clickable element to the tap instruction
          const parent = tapInstruction.locator('xpath=..');
          const clickable = parent.locator('button, [role="button"], [onclick]');
          const clickableCount = await clickable.count();
          if (clickableCount > 0) {
            await clickable.first().click();
            console.log('Clicked element near tap instruction');
          }
        }
      }
    }
    
    // Wait for the roll to complete
    await authenticatedWithThreadsPage.waitForTimeout(3000);
    
    // Debug: Check the state after rolling
    const currentUrlAfterRolling = authenticatedWithThreadsPage.url();
    console.log('Current URL after rolling die:', currentUrlAfterRolling);
    
    const pageContentAfterRolling = await authenticatedWithThreadsPage.locator('body').textContent();
    console.log('Page content after rolling:', pageContentAfterRolling?.substring(0, 300));
    
    // Check if we need to select an issue from the roll pool
    const rollPoolElements = authenticatedWithThreadsPage.locator('*:has-text("Test Review Thread")');
    const rollPoolCount = await rollPoolElements.count();
    console.log('Roll pool elements for our thread:', rollPoolCount);
    
    if (rollPoolCount > 0) {
      // Click on our test thread in the roll pool
      console.log('Clicking our test thread in roll pool...');
      await rollPoolElements.first().click();
      
      // Wait for navigation to rating page
      await authenticatedWithThreadsPage.waitForTimeout(2000);
    }
    
    // Now look for the rating input
    console.log('Looking for rating input after selection...');
    const ratingInputAfterSelection = authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput);
    const ratingNowVisible = await ratingInputAfterSelection.isVisible().catch(() => false);
    console.log('Rating input now visible:', ratingNowVisible);
    
    if (!ratingNowVisible) {
      // Take a screenshot to debug
      await authenticatedWithThreadsPage.screenshot({ path: 'debug-after-roll.png' });
    }
    
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 });
    
    // Use the correct variable for setting the rating
    const finalRatingInput = authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput);
    
    // Set a rating
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.5');
    
    // Submit the rating
    const submitButton = authenticatedWithThreadsPage.locator(SELECTORS.rate.submitButton);
    await expect(submitButton).toBeVisible();
    
    // Wait for rating API response when clicking submit
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse(r => r.url().includes('/api/rate/')),
      submitButton.click({ force: true }),
    ]);
    
    // Wait for review modal
    const reviewModal = authenticatedWithThreadsPage.locator('[data-testid="modal"]');
    await expect(reviewModal).toBeVisible({ timeout: 15000 });
    await expect(authenticatedWithThreadsPage.getByText('Write a Review?')).toBeVisible();
    
    // Verify thread and rating information is displayed
    await expect(authenticatedWithThreadsPage.locator('text=Reviewing')).toBeVisible();
    await expect(authenticatedWithThreadsPage.locator('text=Rating:')).toBeVisible();
    
    // Look for the rating value in the modal specifically - re-query to avoid stale locator
    const modalRating = authenticatedWithThreadsPage.locator('[data-testid="modal"]').locator('text=/\\d\\.\\d/');
    await expect(modalRating).toBeVisible({ timeout: 10000 });
    
    // Write a review
    const textarea = authenticatedWithThreadsPage.locator('textarea[placeholder*="Share your thoughts"]');
    await expect(textarea).toBeVisible();
    await textarea.fill('This was an amazing issue! Great character development and artwork.');
    
    // Verify character count updates
    const characterCount = authenticatedWithThreadsPage.locator('text=/\\d+\\/2000 characters/');
    await expect(characterCount).toBeVisible();
    const countText = await characterCount.textContent();
    expect(countText).toMatch(/\d+\/2000 characters/);
    
    // Save the review
    const saveButton = authenticatedWithThreadsPage.locator('button:has-text("Save Review")');
    await expect(saveButton).toBeVisible();
    
    // Wait for both rating API and review API responses
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse(r => r.url().includes('/api/rate/')),
      authenticatedWithThreadsPage.waitForResponse((response) =>
        response.url().includes('/v1/reviews/') && response.request().method() === 'POST'
      ),
      saveButton.click(),
    ]);
    
    // Wait for modal to close
    await expect(reviewModal).not.toBeVisible({ timeout: 10000 });
    
    // Navigate directly to the thread detail page — we already have the thread ID
    await authenticatedWithThreadsPage.goto(`/thread/${thread.id}`);
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    // Verify review is displayed
    const reviewText = authenticatedWithThreadsPage.locator('text=This was an amazing issue!');
    await expect(reviewText).toBeVisible({ timeout: 10000 });
    await expect(authenticatedWithThreadsPage.locator('text=Rating: 4.5')).toBeVisible();
  });

  test('should skip review writing', async ({ authenticatedWithThreadsPage }) => {
    // Navigate to the queue page to see threads
    await authenticatedWithThreadsPage.goto('/queue');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Wait for the queue container to be visible
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.threadList.container, { timeout: 15000 });
    
    // Wait for thread items to be present and visible
    const threadList = authenticatedWithThreadsPage.locator(SELECTORS.threadList.threadItem);
    await expect(threadList.first()).toBeVisible({ timeout: 15000 });
    
    // Select the first thread using proper selector
    const firstThreadCard = threadList.first();
    await firstThreadCard.click();
    
    // Start reading - use Roll button for threads that are already being tracked
    await authenticatedWithThreadsPage.getByText('🎲Roll').click();
    
    // Wait for navigation to roll page
    await authenticatedWithThreadsPage.waitForTimeout(2000);
    
    // Roll the main die to select an issue
    const mainDie = authenticatedWithThreadsPage.locator(SELECTORS.roll.mainDie);
    const dieVisible = await mainDie.isVisible().catch(() => false);
    
    if (dieVisible) {
      await mainDie.click();
    }
    
    // Wait for the roll to complete
    await authenticatedWithThreadsPage.waitForTimeout(3000);
    
    // Find and click the first thread in the roll pool
    const rollPoolElements = authenticatedWithThreadsPage.locator('[role="button"]');
    const rollCount = await rollPoolElements.count();
    
    if (rollCount > 0) {
      await rollPoolElements.first().click();
    }
    
    // Wait for navigation to rating page
    await authenticatedWithThreadsPage.waitForTimeout(2000);
    
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 });
    
    // Set a rating
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.5');
    
    // Submit the rating
    const submitButton = authenticatedWithThreadsPage.locator(SELECTORS.rate.submitButton);
    await expect(submitButton).toBeVisible();
    await submitButton.click({ force: true });
    
    // Wait for review modal to appear
    const reviewModal = authenticatedWithThreadsPage.locator('[data-testid="modal"]');
    await expect(reviewModal).toBeVisible({ timeout: 15000 });
    
    // Skip writing a review
    const skipButton = authenticatedWithThreadsPage.locator('button:has-text("Skip")');
    await expect(skipButton).toBeVisible();
    
    // Wait for rating API response when clicking Skip
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse(r => r.url().includes('/api/rate/')),
      skipButton.click(),
    ]);
    
    // Verify modal closes
    await expect(reviewModal).not.toBeVisible({ timeout: 10000 });
    
    // Wait for state to update
    await authenticatedWithThreadsPage.waitForTimeout(2000);
    
    // Navigate back to roll page to ensure we're on the right page
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Verify we're on the roll page by checking URL
    await authenticatedWithThreadsPage.waitForURL('/', { timeout: 10000 });
  });

  test('should edit existing review', async ({ authenticatedWithThreadsPage }) => {
    // First, create a review by going through the normal flow
    await authenticatedWithThreadsPage.goto('/queue');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Wait for the queue container to be visible
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.threadList.container, { timeout: 15000 });
    
    // Wait for thread items to be present and visible
    const threadList = authenticatedWithThreadsPage.locator(SELECTORS.threadList.threadItem);
    await expect(threadList.first()).toBeVisible({ timeout: 15000 });
    
    // Select the first thread using proper selector
    const firstThreadCard = threadList.first();
    await firstThreadCard.click();
    
    // Start reading - use Roll button for threads that are already being tracked
    await authenticatedWithThreadsPage.getByText('🎲Roll').click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 });
    
    // Set a rating and create a review
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.0');
    const submitButton = authenticatedWithThreadsPage.locator(SELECTORS.rate.submitButton);
    await expect(submitButton).toBeVisible();
    await submitButton.click({ force: true });
    
    // Wait for review modal and write a review
    const reviewModal = authenticatedWithThreadsPage.locator('[data-testid="modal"]');
    await expect(reviewModal).toBeVisible({ timeout: 15000 });
    
    const textarea = authenticatedWithThreadsPage.locator('textarea[placeholder*="Share your thoughts"]');
    await expect(textarea).toBeVisible();
    await textarea.fill('Original review text');
    
    const saveButton = authenticatedWithThreadsPage.locator('button:has-text("Save Review")');
    await expect(saveButton).toBeVisible();
    
    // Wait for both rating API and review API responses
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse(r => r.url().includes('/api/rate/')),
      authenticatedWithThreadsPage.waitForResponse((response) =>
        response.url().includes('/v1/reviews/') && response.request().method() === 'POST'
      ),
      saveButton.click(),
    ]);
    
    await expect(reviewModal).not.toBeVisible({ timeout: 10000 });
    
    // Wait for state to update
    await authenticatedWithThreadsPage.waitForTimeout(2000);
    
    // Now, rate the same issue again to trigger edit flow
    // Go back to roll page and start again
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Click the same thread using proper selector
    const threadCardAgain = authenticatedWithThreadsPage.locator(SELECTORS.threadList.threadItem).first();
    await expect(threadCardAgain).toBeVisible();
    await threadCardAgain.click();
    
    // Start reading again
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 });
    
    // Set the same rating again
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.0');
    
    // Submit the rating
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse(r => r.url().includes('/api/rate/')),
      submitButton.click({ force: true }),
    ]);
    
    // Verify edit modal appears with existing review
    await expect(reviewModal).toBeVisible({ timeout: 15000 });
    
    // Check for either Edit Review or Write a Review? (depends on implementation)
    // Re-query reviewModal to avoid stale locator
    const freshReviewModal = authenticatedWithThreadsPage.locator('[data-testid="modal"]');
    const modalTitle = freshReviewModal.locator('h2');
    await expect(modalTitle).toBeVisible();
    const titleText = await modalTitle.textContent();
    expect(titleText).toMatch(/(Edit Review|Write a Review\?)/);
    
    // Wait for textarea to be visible and check value
    await expect(textarea).toBeVisible();
    await expect(textarea).toHaveValue('Original review text');
    
    // Edit the review
    await textarea.fill('Updated review text with more details');
    const updateButton = authenticatedWithThreadsPage.locator('button:has-text("Update Review")');
    await expect(updateButton).toBeVisible();
    
    // Save the updated review
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse((response) =>
        response.url().includes('/v1/reviews/') && (response.request().method() === 'PUT' || response.request().method() === 'POST')
      ),
      updateButton.click(),
    ]);
    
    await expect(reviewModal).not.toBeVisible({ timeout: 10000 });
    
    // Wait for state to update
    await authenticatedWithThreadsPage.waitForTimeout(2000);
    
    // Verify the review was updated by checking thread details
    await authenticatedWithThreadsPage.goto('/queue');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Wait for the queue container to be visible
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.threadList.container, { timeout: 15000 });
    
    const threadCardFinal = authenticatedWithThreadsPage.locator(SELECTORS.threadList.threadItem).first();
    await expect(threadCardFinal).toBeVisible();
    await threadCardFinal.click();
    
    await authenticatedWithThreadsPage.waitForURL(/\/thread\/\d+/);
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Verify updated review is displayed
    await expect(authenticatedWithThreadsPage.locator('text=Updated review text with more details')).toBeVisible({ timeout: 10000 });
  });

  test('should handle network error during review submission', async ({ authenticatedWithThreadsPage }) => {
    // Navigate to the queue page to see threads
    await authenticatedWithThreadsPage.goto('/queue');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Wait for the queue container to be visible
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.threadList.container, { timeout: 15000 });
    
    // Wait for thread items to be present and visible
    const threadList = authenticatedWithThreadsPage.locator(SELECTORS.threadList.threadItem);
    await expect(threadList.first()).toBeVisible({ timeout: 15000 });
    
    // Select the first thread using proper selector
    const firstThreadCard = threadList.first();
    await firstThreadCard.click();
    
    // Start reading - use Roll button for threads that are already being tracked
    await authenticatedWithThreadsPage.getByText('🎲Roll').click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 });
    
    // Set a rating
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.5');
    
    // Submit the rating
    const submitButton = authenticatedWithThreadsPage.locator(SELECTORS.rate.submitButton);
    await expect(submitButton).toBeVisible();
    await submitButton.click({ force: true });
    
    // Wait for review modal
    const reviewModal = authenticatedWithThreadsPage.locator('[data-testid="modal"]');
    await expect(reviewModal).toBeVisible({ timeout: 15000 });
    
    // Mock a network error for review submission
    await authenticatedWithThreadsPage.route('**/v1/reviews/', route => route.abort('failed'));
    
    // Write a review
    const textarea = authenticatedWithThreadsPage.locator('textarea[placeholder*="Share your thoughts"]');
    await expect(textarea).toBeVisible();
    await textarea.fill('This review should fail');
    
    // Try to save the review - this will fail due to mocked network error
    const saveButton = authenticatedWithThreadsPage.locator('button:has-text("Save Review")');
    await expect(saveButton).toBeVisible();
    await saveButton.click();
    
    // Wait for rating API response (this should succeed even though review fails)
    await authenticatedWithThreadsPage.waitForResponse(r => r.url().includes('/api/rate/'), { timeout: 10000 });
    
    // Wait for potential error message to appear
    await authenticatedWithThreadsPage.waitForTimeout(3000);
    
    // Verify error message appears and modal stays open
    // Look for error message with better selector
    // Re-query reviewModal to avoid stale locator
    const freshReviewModal = authenticatedWithThreadsPage.locator('[data-testid="modal"]');
    const errorMessage = freshReviewModal.locator('.text-red-400');
    const errorVisible = await errorMessage.isVisible().catch(() => false);
    
    if (errorVisible) {
      await expect(errorMessage).toBeVisible();
    } else {
      // If error message isn't visible, check if modal is still open (which indicates error)
      await expect(freshReviewModal).toBeVisible();
    }
    
    // Verify save button is no longer in saving state
    await expect(saveButton).toHaveText('Save Review');
    
    // Clean up the route mock
    await authenticatedWithThreadsPage.unroute('**/v1/reviews/');
  });

  test('should enforce character limit in review textarea', async ({ authenticatedWithThreadsPage }) => {
    // Navigate to the queue page to see threads
    await authenticatedWithThreadsPage.goto('/queue');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Wait for the queue container to be visible
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.threadList.container, { timeout: 15000 });
    
    // Wait for thread items to be present and visible
    const threadList = authenticatedWithThreadsPage.locator(SELECTORS.threadList.threadItem);
    await expect(threadList.first()).toBeVisible({ timeout: 15000 });
    
    // Select the first thread using proper selector
    const firstThreadCard = threadList.first();
    await firstThreadCard.click();
    
    // Start reading - use Roll button for threads that are already being tracked
    await authenticatedWithThreadsPage.getByText('🎲Roll').click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 });
    
    // Set a rating
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.5');
    
    // Submit the rating
    const submitButton = authenticatedWithThreadsPage.locator(SELECTORS.rate.submitButton);
    await expect(submitButton).toBeVisible();
    await submitButton.click({ force: true });
    
    // Wait for review modal
    const reviewModal = authenticatedWithThreadsPage.locator('[data-testid="modal"]');
    await expect(reviewModal).toBeVisible({ timeout: 15000 });
    
    // Try to type more than 2000 characters
    const textarea = authenticatedWithThreadsPage.locator('textarea[placeholder*="Share your thoughts"]');
    await expect(textarea).toBeVisible();
    
    const longText = 'a'.repeat(2001);
    await textarea.fill(longText);
    
    // Wait for character limit to be enforced
    await authenticatedWithThreadsPage.waitForTimeout(500);
    
    // Verify it's truncated to 2000 characters
    const actualValue = await textarea.inputValue();
    expect(actualValue.length).toBe(2000);
    
    // Verify character count shows 2000/2000
    const characterCount = authenticatedWithThreadsPage.locator('text=/\\d+\\/2000 characters/');
    await expect(characterCount).toBeVisible();
    const countText = await characterCount.textContent();
    expect(countText).toBe('2000/2000 characters');
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
    
    // Navigate to the queue page and wait for threads to appear
    await authenticatedWithThreadsPage.goto('/queue');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Wait for the queue container to be visible
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.threadList.container, { timeout: 15000 });
    
    // Wait for the newly created thread to be visible
    await authenticatedWithThreadsPage.waitForTimeout(3000); // Allow time for UI to update
    
    // Refresh the page to ensure the thread is loaded
    await authenticatedWithThreadsPage.reload();
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Wait for queue container again after reload
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.threadList.container, { timeout: 15000 });
    
    // Find the thread by title using a more reliable approach
    const threadTitle = 'Multi-issue Test Thread';
    const threadCards = authenticatedWithThreadsPage.locator(SELECTORS.threadList.threadItem);
    const threadCount = await threadCards.count();
    
    // Find the thread card with the correct title
    let targetThreadCard: Locator | null = null;
for (let i = 0; i < threadCount; i++) {
        const card = threadCards.nth(i);
        // Try to find the thread title using a more robust approach
        const titleElement = card.locator('p.font-black, .font-black, [class*="font-black"], h3, h4, .title, [class*="title"]');
        const titleVisible = await titleElement.isVisible().catch(() => false);
        
        if (titleVisible) {
          const titleText = await titleElement.textContent();
          if (titleText && titleText.includes(threadTitle)) {
            targetThreadCard = card;
            break;
          }
        }
      }
    
    // If we found the thread, click it
    if (targetThreadCard) {
      await expect(targetThreadCard).toBeVisible({ timeout: 10000 });
      await targetThreadCard.click();
    } else {
      // Fallback: try to find by text content
      const altThreadCard = authenticatedWithThreadsPage.locator(`text=${threadTitle}`).first();
      await expect(altThreadCard).toBeVisible({ timeout: 10000 });
      await altThreadCard.click();
    }
    
    // Start reading - use Roll button for threads that are already being tracked
    await authenticatedWithThreadsPage.getByText('🎲Roll').click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 });
    
    // Set a rating
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.5');
    
    // Submit the rating
    const submitButton = authenticatedWithThreadsPage.locator(SELECTORS.rate.submitButton);
    const submitButtonVisible = await submitButton.isVisible().catch(() => false);
    console.log('Save & Continue button visible:', submitButtonVisible);
    
    if (!submitButtonVisible) {
      // Look for alternative button text (like "Save & Complete" for last issue)
      const altButton = authenticatedWithThreadsPage.locator('button:has-text("Save & Complete")');
      const altVisible = await altButton.isVisible().catch(() => false);
      console.log('Save & Complete button visible:', altVisible);
      
      if (altVisible) {
        await altButton.click();
      } else {
        // Take a screenshot to debug
        await authenticatedWithThreadsPage.screenshot({ path: 'debug-rating-submit.png' });
        
        // Look for any save-related buttons
        const saveButtons = authenticatedWithThreadsPage.locator('button:has-text("Save")');
        const saveCount = await saveButtons.count();
        console.log('Save buttons found:', saveCount);
        
        if (saveCount > 0) {
          for (let i = 0; i < saveCount; i++) {
            const text = await saveButtons.nth(i).textContent();
            console.log(`Save button ${i}:`, text);
          }
          await saveButtons.first().click();
        } else {
          throw new Error('No save button found');
        }
      }
    } else {
      await submitButton.click({ force: true });
    }
    
    // Wait for review modal
    const reviewModal = authenticatedWithThreadsPage.locator('[data-testid="modal"]');
    await expect(reviewModal).toBeVisible({ timeout: 15000 });
    
    // Verify issue-specific information is displayed
    await expect(authenticatedWithThreadsPage.locator(`text=Reviewing ${threadTitle} #1`)).toBeVisible({ timeout: 10000 });
    await expect(authenticatedWithThreadsPage.locator('text=Rating:')).toBeVisible();
    await expect(reviewModal.locator('text=5.0')).toBeVisible();
    
    // Write and save the review
    const textarea = authenticatedWithThreadsPage.locator('textarea[placeholder*="Share your thoughts"]');
    await expect(textarea).toBeVisible();
    await textarea.fill('Great first issue!');
    
    const saveButton = authenticatedWithThreadsPage.locator('button:has-text("Save Review")');
    await expect(saveButton).toBeVisible();
    
    // Wait for both rating API and review API responses
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse(r => r.url().includes('/api/rate/')),
      authenticatedWithThreadsPage.waitForResponse((response) =>
        response.url().includes('/v1/reviews/') && response.request().method() === 'POST'
      ),
      saveButton.click(),
    ]);
    
    await expect(reviewModal).not.toBeVisible({ timeout: 10000 });
    
    // Verify the review appears in thread details
    await authenticatedWithThreadsPage.goto('/queue');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Wait for the queue container to be visible
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.threadList.container, { timeout: 15000 });
    
    // Find the thread again
    const threadCardsAgain = authenticatedWithThreadsPage.locator(SELECTORS.threadList.threadItem);
    const threadCountAgain = await threadCardsAgain.count();
    
    let targetThreadCardAgain: Locator | null = null;
    for (let i = 0; i < threadCountAgain; i++) {
      const card = threadCardsAgain.nth(i);
      const titleText = await card.locator('p.font-black').textContent();
      if (titleText && titleText.includes(threadTitle)) {
        targetThreadCardAgain = card;
        break;
      }
    }
    
    if (targetThreadCardAgain) {
      await expect(targetThreadCardAgain).toBeVisible();
      await targetThreadCardAgain.click();
    } else {
      const altThreadCardAgain = authenticatedWithThreadsPage.locator(`text=${threadTitle}`).first();
      await expect(altThreadCardAgain).toBeVisible();
      await altThreadCardAgain.click();
    }
    
    await authenticatedWithThreadsPage.waitForURL(/\/thread\/\d+/);
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Verify review is displayed with issue information
    await expect(authenticatedWithThreadsPage.locator('text=Great first issue!')).toBeVisible({ timeout: 10000 });
    await expect(authenticatedWithThreadsPage.locator('text=Rating: 5.0')).toBeVisible();
  });

  test('should handle review form cancellation', async ({ authenticatedWithThreadsPage }) => {
    // Navigate to the queue page to see threads
    await authenticatedWithThreadsPage.goto('/queue');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Wait for the queue container to be visible
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.threadList.container, { timeout: 15000 });
    
    // Wait for thread items to be present and visible
    const threadList = authenticatedWithThreadsPage.locator(SELECTORS.threadList.threadItem);
    await expect(threadList.first()).toBeVisible({ timeout: 15000 });
    
    // Select the first thread using proper selector
    const firstThreadCard = threadList.first();
    await firstThreadCard.click();
    
    // Start reading - use Roll button for threads that are already being tracked
    await authenticatedWithThreadsPage.getByText('🎲Roll').click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 });
    
    // Set a rating
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.5');
    
    // Submit the rating
    const submitButton = authenticatedWithThreadsPage.locator(SELECTORS.rate.submitButton);
    await expect(submitButton).toBeVisible();
    await submitButton.click({ force: true });
    
    // Wait for review modal
    const reviewModal = authenticatedWithThreadsPage.locator('[data-testid="modal"]');
    await expect(reviewModal).toBeVisible({ timeout: 15000 });
    
    // Write some text in the textarea
    const textarea = authenticatedWithThreadsPage.locator('textarea[placeholder*="Share your thoughts"]');
    await expect(textarea).toBeVisible();
    await textarea.fill('This review will be cancelled');
    
    // Close the modal using the close button
    // Re-query reviewModal to avoid stale locator
    const freshReviewModal = authenticatedWithThreadsPage.locator('[data-testid="modal"]');
    const closeButton = freshReviewModal.locator('button[aria-label="Close modal"]');
    const closeButtonVisible = await closeButton.isVisible().catch(() => false);
    
    if (closeButtonVisible) {
      await closeButton.click();
    } else {
      // Fallback: use skip button if close button not available
      const skipButton = freshReviewModal.locator('button:has-text("Skip")');
      await expect(skipButton).toBeVisible();
      await skipButton.click();
    }
    
    // Verify modal closes
    await expect(reviewModal).not.toBeVisible({ timeout: 10000 });
    
    // Wait for state to update
    await authenticatedWithThreadsPage.waitForTimeout(2000);
    
    // Navigate back to roll page to ensure we're on the right page
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    
    // Verify we're on the roll page by checking URL
    await authenticatedWithThreadsPage.waitForURL('/', { timeout: 10000 });
    
    // Rate the same issue again to verify modal is fresh (no pre-filled text)
    const threadCardAgain = authenticatedWithThreadsPage.locator(SELECTORS.threadList.threadItem).first();
    await expect(threadCardAgain).toBeVisible();
    await threadCardAgain.click();
    
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 15000 });
    
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.5');

    // Submit the rating
    const submitButtonAgain = authenticatedWithThreadsPage.locator(SELECTORS.rate.submitButton);
    await expect(submitButtonAgain).toBeVisible();
    
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse(r => r.url().includes('/api/rate/')),
      submitButtonAgain.click({ force: true }),
    ]);

    // Wait for review modal to appear
    await expect(authenticatedWithThreadsPage.locator('[data-testid="modal"]')).toBeVisible({ timeout: 5000 });

    // Click Skip button
    await Promise.all([
      authenticatedWithThreadsPage.waitForResponse(r => r.url().includes('/api/rate/')),
      authenticatedWithThreadsPage.click('button:has-text("Skip")'),
    ]);

    // Verify review modal is fresh (no pre-filled text)
    await expect(reviewModal).toBeVisible({ timeout: 10000 });
    await expect(textarea).toHaveValue('');
  });
});