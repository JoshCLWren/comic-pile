import { test, expect } from './fixtures';
import { SELECTORS } from './helpers';

test.describe('Issue #294: Hide roll instruction when pool is empty', () => {
  test('should not show "Tap Die to Roll" instruction when pool is empty', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });

    const tapInstruction = authenticatedPage.locator(SELECTORS.roll.tapInstruction);
    await expect(tapInstruction).not.toBeVisible();

     const emptyQueueMessage = authenticatedPage.locator('text=Your reading queue is empty — add some comic threads to get started.');
     await expect(emptyQueueMessage).toBeVisible();
  });

  test('should show "Tap Die to Roll" instruction when pool has threads', async ({ authenticatedPage, request }) => {
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);

    await request.post('/api/threads/', {
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      data: {
        title: 'Test Thread',
        format: 'Comics',
        issues_remaining: 5,
      },
    });

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });

    const tapInstruction = authenticatedPage.locator(SELECTORS.roll.tapInstruction);
    await expect(tapInstruction).toBeVisible();
  });
});
