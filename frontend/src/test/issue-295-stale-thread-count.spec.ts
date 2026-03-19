import { test, expect } from './fixtures';
import { createThread, getAuthToken } from './helpers';

test.describe('Issue #295 - Stale Thread Nudge Count', () => {
  test('should display count indicator when multiple stale threads exist', async ({ authenticatedWithThreadsPage }) => {
    const token = await getAuthToken(authenticatedWithThreadsPage);
    expect(token).toBeTruthy();

    // Create 3 threads
    const thread1 = await createThread(authenticatedWithThreadsPage, {
      title: 'Stale Thread 1',
      format: 'issue',
      issues_remaining: 5,
    });

    const thread2 = await createThread(authenticatedWithThreadsPage, {
      title: 'Stale Thread 2',
      format: 'issue',
      issues_remaining: 5,
    });

    const thread3 = await createThread(authenticatedWithThreadsPage, {
      title: 'Stale Thread 3',
      format: 'issue',
      issues_remaining: 5,
    });

    // Backdate all 3 threads by 8 days to make them stale
    for (const thread of [thread1, thread2, thread3]) {
      const backdateResponse = await authenticatedWithThreadsPage.request.put(
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
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    // The stale thread nudge should be visible
    const staleNudge = authenticatedWithThreadsPage.getByText("You haven't touched");
    await expect(staleNudge).toBeVisible({ timeout: 10000 });

    // Check for count indicator - should show something like "3 stale threads" or similar
    // This assertion will fail initially (the bug), showing that only one thread is displayed without a count
    const countIndicator = authenticatedWithThreadsPage.locator('text=/\\d+\\s+stale threads?/i');
    await expect(countIndicator).toBeVisible({ timeout: 5000 });

    // Verify the count is 3
    const countText = await countIndicator.textContent();
    expect(countText).toMatch(/3\s+stale threads?/i);
  });

  test('should show count indicator singular form when only one stale thread exists', async ({ authenticatedWithThreadsPage }) => {
    const token = await getAuthToken(authenticatedWithThreadsPage);
    expect(token).toBeTruthy();

    // Create 1 thread
    const thread = await createThread(authenticatedWithThreadsPage, {
      title: 'Single Stale Thread',
      format: 'issue',
      issues_remaining: 5,
    });

    // Backdate the thread by 8 days
    const backdateResponse = await authenticatedWithThreadsPage.request.put(
      `/api/threads/${thread.id}/test-backdate?days_ago=8`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      }
    );
    expect(backdateResponse.ok()).toBeTruthy();

    // Reload the page
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    // The stale thread nudge should be visible
    const staleNudge = authenticatedWithThreadsPage.getByText("You haven't touched");
    await expect(staleNudge).toBeVisible({ timeout: 10000 });

    // Count indicator should show "1 stale thread" (singular)
    const countIndicator = authenticatedWithThreadsPage.locator('text=/1\\s+stale thread/i');
    await expect(countIndicator).toBeVisible({ timeout: 5000 });
  });
});
