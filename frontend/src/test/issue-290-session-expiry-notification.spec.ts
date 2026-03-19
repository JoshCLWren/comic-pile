import { test, expect } from './fixtures';
import { SELECTORS } from './helpers';

test.describe('Session Expiry Notification (Issue #290)', () => {
  test('should show notification when session expires', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    const mainDieExists = await authenticatedWithThreadsPage.locator(SELECTORS.roll.mainDie).count();
    if (mainDieExists === 0) {
      test.skip(true, 'No main die found - no threads available');
      return;
    }

    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie);

    const token = await authenticatedWithThreadsPage.evaluate(() => localStorage.getItem('auth_token'));

    const initialResponse = await authenticatedWithThreadsPage.request.get('/api/sessions/current/', {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });

    expect(initialResponse.ok()).toBeTruthy();
    const initialSession = await initialResponse.json();
    const initialSessionId = initialSession.id;

    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 5000 });

    const expireResponse = await authenticatedWithThreadsPage.request.post('/api/test/sessions/expire', {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });

    if (expireResponse.status() !== 404 && expireResponse.status() !== 405) {
      expect(expireResponse.ok()).toBeTruthy();
    }

    await authenticatedWithThreadsPage.reload();
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    const newResponse = await authenticatedWithThreadsPage.request.get('/api/sessions/current/', {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });

    expect(newResponse.ok()).toBeTruthy();
    const newSession = await newResponse.json();
    const newSessionId = newSession.id;

    expect(newSessionId).not.toBe(initialSessionId);

    const notification = authenticatedWithThreadsPage.locator('[data-testid="toast-notification"], .toast, [role="alert"], [role="status"]');
    await expect(notification).toBeVisible({ timeout: 3000 });

    const notificationText = await notification.textContent();
    expect(notificationText).toMatch(/session|expired|ended|new/i);
  });
});
