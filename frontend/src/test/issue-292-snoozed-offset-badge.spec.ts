import { test, expect } from './fixtures';
import { createThread } from './helpers';

test.describe('Issue #292: Snoozed-offset badge at d20 ceiling', () => {
  test('should NOT show snoozed-offset badge when die is d20 (pool already at max)', async ({ authenticatedPage, request }) => {
    const page = authenticatedPage;

    // Create 21 threads (20 for d20 pool + 1 to snooze)
    for (let i = 0; i < 21; i++) {
      await createThread(page, {
        title: `Test Thread ${i + 1}`,
        format: 'issue',
        issues_remaining: 10,
        total_issues: 10,
      });
    }

    // Set die to d20
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

  // Click on the first thread to open action sheet (roll pool threads open action sheet directly)
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

    // Wait for snooze to complete
    await page.waitForLoadState('networkidle');

    // Go back to roll page
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Verify we're back on roll page
    await expect(page.locator('#main-die-3d')).toBeVisible();

    // The snoozed-offset badge should NOT be visible when die is d20
    // because the pool is already at maximum size (20) and snoozing
    // cannot increase it further
    const snoozedOffsetBadge = page.locator('.modifier-badge');
    await expect(snoozedOffsetBadge).not.toBeVisible();
  });

  test('should show snoozed-offset badge when die is d6 (pool can grow)', async ({ authenticatedPage, request }) => {
    const page = authenticatedPage;

    // Create 7 threads (6 for d6 pool + 1 to snooze)
    for (let i = 0; i < 7; i++) {
      await createThread(page, {
        title: `Test Thread ${i + 1}`,
        format: 'issue',
        issues_remaining: 10,
        total_issues: 10,
      });
    }

    // Set die to d6 (not at max)
    const token = await page.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);
    const setDieResponse = await request.post('/api/roll/set-die?die=6', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(setDieResponse.ok()).toBeTruthy();

    // Refresh to see updated state
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Verify die is d6
  const headerDieLabel = page.locator('#header-die-label');
  await expect(headerDieLabel).toContainText('d6');

  // Click on the first thread to open action sheet (roll pool threads open action sheet directly)
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

    // Wait for snooze to complete
    await page.waitForLoadState('networkidle');

    // Go back to roll page
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Verify we're back on roll page
    await expect(page.locator('#main-die-3d')).toBeVisible();

    // The snoozed-offset badge SHOULD be visible when die is d6
    // because snoozing a thread increases the pool size from 6 to 7
    const snoozedOffsetBadge = page.locator('.modifier-badge');
    await expect(snoozedOffsetBadge).toBeVisible();
    await expect(snoozedOffsetBadge).toContainText('+1');
  });
});
