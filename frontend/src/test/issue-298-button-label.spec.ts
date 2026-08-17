import { test, expect } from './fixtures';
import { createThread } from './helpers';

test.describe('Issue #298 - Button Label on Last Issue', () => {
  test('should display "Mark read & complete" when rating the last issue', async ({ authenticatedWithThreadsPage }) => {
    const token = await authenticatedWithThreadsPage.evaluate(() =>
      localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN
    );
    expect(token).toBeTruthy();

    // Create a thread with exactly 1 issue remaining (the last issue)
    const thread = await createThread(authenticatedWithThreadsPage, {
      title: 'Last Issue Test Thread',
      format: 'issue',
      issues_remaining: 1,
      total_issues: 10,
    });

    // Set the thread pending so the rating view auto-opens on the roll page
    const setPendingResponse = await authenticatedWithThreadsPage.request.post(
      `/api/threads/${thread.id}/set-pending`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      }
    );
    expect(setPendingResponse.ok()).toBeTruthy();

    // Reload to the roll page; the pending thread opens the rating view directly
    await authenticatedWithThreadsPage.goto('/');
    await expect(authenticatedWithThreadsPage.locator('[data-testid="rating-actions"]')).toBeVisible();

    // Verify we're on the rating view
    await expect(authenticatedWithThreadsPage.locator('#rating-input')).toBeVisible();

    // When this is the last issue, the submit button reads "Mark read & complete"
    const submitButton = authenticatedWithThreadsPage.locator('[data-testid="save-and-continue"]');
    await expect(submitButton).toBeVisible();
    await expect(submitButton).toHaveText('Mark read & complete');

    // The multi-issue label must NOT be present
    await expect(submitButton).not.toHaveText('Mark read & save');
  });

  test('should display "Mark read & save" when multiple issues remain', async ({ authenticatedWithThreadsPage }) => {
    const token = await authenticatedWithThreadsPage.evaluate(() =>
      localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN
    );
    expect(token).toBeTruthy();

    // Create a thread with multiple issues remaining
    const thread = await createThread(authenticatedWithThreadsPage, {
      title: 'Multiple Issues Test Thread',
      format: 'issue',
      issues_remaining: 5,
      total_issues: 10,
    });

    // Set the thread pending so the rating view auto-opens on the roll page
    const setPendingResponse = await authenticatedWithThreadsPage.request.post(
      `/api/threads/${thread.id}/set-pending`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      }
    );
    expect(setPendingResponse.ok()).toBeTruthy();

    // Reload to the roll page; the pending thread opens the rating view directly
    await authenticatedWithThreadsPage.goto('/');
    await expect(authenticatedWithThreadsPage.locator('[data-testid="rating-actions"]')).toBeVisible();

    // Verify we're on the rating view
    await expect(authenticatedWithThreadsPage.locator('#rating-input')).toBeVisible();

    // When issues remain, the submit button reads "Mark read & save"
    const submitButton = authenticatedWithThreadsPage.locator('[data-testid="save-and-continue"]');
    await expect(submitButton).toBeVisible();
    await expect(submitButton).toHaveText('Mark read & save');

    // The last-issue label must NOT be present
    await expect(submitButton).not.toHaveText('Mark read & complete');
  });
});
