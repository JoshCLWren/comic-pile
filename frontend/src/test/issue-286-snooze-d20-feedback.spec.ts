import { test, expect } from './fixtures';
import { createThread } from './helpers';

test.describe('Issue #286: Snooze feedback at d20', () => {
  test('should show feedback when snoozing at d20 (max pool size)', async ({ authenticatedPage, request }) => {
    const page = authenticatedPage;

    // Create 21 threads (20 for d20 pool + 1 to roll)
    for (let i = 0; i < 21; i++) {
      await createThread(page, {
        title: `Test Thread ${i + 1}`,
        format: 'issue',
        issues_remaining: 10,
        total_issues: 10,
      });
    }

    // Set die to d20 (maximum)
    const token = await page.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);
    const setDieResponse = await request.post('/api/roll/set-die?die=20', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(setDieResponse.ok()).toBeTruthy();

    // Refresh to see updated state
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Verify die is d20
    const headerDieLabel = page.locator('#header-die-label');
    await expect(headerDieLabel).toContainText('d20');

    // Click on the first thread to open action sheet
    const firstThread = page.locator('[data-roll-pool] [role="button"]').first();
    await firstThread.click();

    // Click "Read Now" to set thread as pending
    const readButton = page.locator('button:has-text("Read Now")');
    await readButton.click();

    // Wait for rating view to appear
    await page.waitForSelector('#rating-input', { state: 'visible', timeout: 5000 });

    // Snooze the thread
    const snoozeButton = page.locator('button:has-text("Snooze")');
    await snoozeButton.click();

    // Wait for snooze to complete and return to roll page
    await page.waitForLoadState('networkidle');

    // Verify we're back on roll page
    await expect(page.locator('#main-die-3d')).toBeVisible();

    // Verify feedback message is shown about being at max pool size
    // The feedback should indicate that snoozing at d20 has no effect
    const feedbackMessage = page.locator('text=/max|pool|size|already at d20/i');
    await expect(feedbackMessage).toBeVisible();
  });
});
