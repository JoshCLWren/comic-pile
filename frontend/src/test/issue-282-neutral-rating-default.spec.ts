import { test, expect } from './fixtures';
import { createThread } from './helpers';

test.describe('Issue #282: Neutral rating slider default', () => {
  test('should default to neutral rating (3.0) instead of good threshold (4.0)', async ({ authenticatedPage }) => {
    const page = authenticatedPage;

    // Create a thread for testing
    await createThread(page, {
      title: 'Test Thread for Neutral Rating',
      format: 'issue',
      issues_remaining: 10,
      total_issues: 10,
    });

    // Go to home and verify we can roll
    await page.goto('/');
    await page.waitForLoadState('networkidle');

  // Click on the first thread to open action sheet (roll pool threads open action sheet directly)
  const firstThread = page.locator('[data-roll-pool] [role="button"]').first();
  await firstThread.click();

  // Click "Read Now" to set thread as pending and open rating view
    const readButton = page.locator('button:has-text("Read Now")');
    await readButton.click();

    // Wait for rating view to appear
    await page.waitForSelector('#rating-input', { state: 'visible', timeout: 5000 });

    // Check the initial slider value
    const ratingInput = page.locator('#rating-input');
    const initialValue = await ratingInput.inputValue();
    
    // Check the displayed rating value
    const ratingValueDisplay = page.locator('#rating-value');
    const displayedValue = await ratingValueDisplay.textContent();

    // The rating should default to a neutral value (3.0 for a 0.5-5.0 scale)
    // Currently this will fail because it defaults to 4.0 (the "good" threshold)
    expect(parseFloat(initialValue)).toBe(3.0);
    expect(displayedValue).toBe('3.0');
  });
});
