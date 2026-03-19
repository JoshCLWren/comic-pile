import { test, expect } from './fixtures';
import { createThread, getAuthToken } from './helpers';

test.describe('Issue #295 - Stale Thread Nudge Count', () => {
  test('should display count indicator when multiple stale threads exist', async ({ freshUserPage }) => {
    const token = await getAuthToken(freshUserPage);
    expect(token).toBeTruthy();

    // Create 3 threads
    const thread1 = await createThread(freshUserPage, {
      title: 'Stale Thread 1',
      format: 'issue',
      issues_remaining: 5,
    });

    const thread2 = await createThread(freshUserPage, {
      title: 'Stale Thread 2',
      format: 'issue',
      issues_remaining: 5,
    });

    const thread3 = await createThread(freshUserPage, {
      title: 'Stale Thread 3',
      format: 'issue',
      issues_remaining: 5,
    });

    // Backdate all 3 threads by 8 days to make them stale
    for (const thread of [thread1, thread2, thread3]) {
      const backdateResponse = await freshUserPage.request.put(
        `/api/threads/${thread.id}/test-backdate?days_ago=8`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );
      expect(backdateResponse.ok()).toBeTruthy();
    }

    // Reload the page to see the stale thread nudge
    await freshUserPage.goto('/');
    await freshUserPage.waitForLoadState('networkidle');

    // The stale thread nudge should be visible with count indicator
    const staleNudge = freshUserPage.locator('text=/3 stale threads/i');
    await expect(staleNudge).toBeVisible({ timeout: 10000 });

    // Verify the full message contains the count and thread title
    const fullMessage = freshUserPage.locator('text=/3 stale threads: Stale Thread 1 neglected for \\d+ days/i');
    await expect(fullMessage).toBeVisible({ timeout: 5000 });
  });

  test('should show count indicator singular form when only one stale thread exists', async ({ freshUserPage }) => {
    const token = await getAuthToken(freshUserPage);
    expect(token).toBeTruthy();

    // Create 1 thread
    const thread = await createThread(freshUserPage, {
      title: 'Single Stale Thread',
      format: 'issue',
      issues_remaining: 5,
    });

    // Backdate the thread by 8 days
    const backdateResponse = await freshUserPage.request.put(
      `/api/threads/${thread.id}/test-backdate?days_ago=8`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      }
    );
    expect(backdateResponse.ok()).toBeTruthy();

    // Reload the page
    await freshUserPage.goto('/');
    await freshUserPage.waitForLoadState('networkidle');

    // The stale thread nudge should be visible with singular count
    const staleNudge = freshUserPage.locator('text=/1 stale thread/i');
    await expect(staleNudge).toBeVisible({ timeout: 10000 });

    // Verify the full message contains the count (singular) and thread title
    const fullMessage = freshUserPage.locator('text=/1 stale thread: Single Stale Thread neglected for \\d+ days/i');
    await expect(fullMessage).toBeVisible({ timeout: 5000 });
  });
});
