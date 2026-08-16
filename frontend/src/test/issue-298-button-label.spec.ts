import { test, expect } from './fixtures';
import { createThread, SELECTORS } from './helpers';

test.describe('Issue #298 - Button Label on Last Issue', () => {
  test('should display "Mark read & complete" when rating the last issue', async ({ authenticatedWithThreadsPage }) => {
    const token = await authenticatedWithThreadsPage.evaluate(() =>
      localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN
    );
    expect(token).toBeTruthy();

    // Create a thread with exactly 1 issue remaining
    const thread = await createThread(authenticatedWithThreadsPage, {
      title: 'Last Issue Test Thread',
      format: 'issue',
      issues_remaining: 1,
      total_issues: 1,
    });

    // Set the thread as pending
    const setPendingResponse = await authenticatedWithThreadsPage.request.post(
      `/api/threads/${thread.id}/set-pending`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      }
    );
    expect(setPendingResponse.ok()).toBeTruthy();

    // Reload the page to see the pending thread
    await authenticatedWithThreadsPage.goto('/');
    await expect(authenticatedWithThreadsPage.locator('#root')).toBeVisible();

    // Click on the first thread card
    const firstThreadCard = authenticatedWithThreadsPage.getByRole('button', { name: thread.title });
    await expect(firstThreadCard).toBeVisible({ timeout: 10000 });
    await firstThreadCard.click();

    // Click "Read Now"
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });

    // Verify we're on the rating view
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible();

    // Check that the submit button shows "Mark read & complete" (not "Mark read & save")
    const submitButton = authenticatedWithThreadsPage.locator('button:has-text("Mark read & complete")');
    await expect(submitButton).toBeVisible();

    // Verify the non-last button text is NOT present
    const oldButton = authenticatedWithThreadsPage.locator('button:has-text("Mark read & save")');
    await expect(oldButton).toHaveCount(0);
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

    // Set the thread as pending
    const setPendingResponse = await authenticatedWithThreadsPage.request.post(
      `/api/threads/${thread.id}/set-pending`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      }
    );
    expect(setPendingResponse.ok()).toBeTruthy();

    // Reload the page to see the pending thread
    await authenticatedWithThreadsPage.goto('/');
    await expect(authenticatedWithThreadsPage.locator('#root')).toBeVisible();

    // Click on the first thread card
    const firstThreadCard = authenticatedWithThreadsPage.getByRole('button', { name: thread.title });
    await expect(firstThreadCard).toBeVisible({ timeout: 10000 });
    await firstThreadCard.click();

    // Click "Read Now"
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });

    // Verify we're on the rating view
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible();

    // Check that the submit button shows "Mark read & save" (not "Mark read & complete")
    const submitButton = authenticatedWithThreadsPage.locator('button:has-text("Mark read & save")');
    await expect(submitButton).toBeVisible();

    // Verify the last-issue button text is NOT present
    const newButton = authenticatedWithThreadsPage.locator('button:has-text("Mark read & complete")');
    await expect(newButton).toHaveCount(0);
  });
});
