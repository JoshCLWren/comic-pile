import { test, expect } from './fixtures';
import { createThread } from './helpers';

test.describe('Issue #1111: Set Current Issue from Roll Edit', () => {
  test.beforeEach(async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await expect(authenticatedWithThreadsPage.locator('#root')).toBeVisible();
  });

  test('Edit Thread opens the in-context Set Current Issue modal instead of navigating to the queue', async ({
    authenticatedWithThreadsPage,
  }) => {
    const page = authenticatedWithThreadsPage;
    await createThread(page, {
      title: 'Black Panther',
      format: 'comic',
      issues_remaining: 20,
      total_issues: 20,
      issue_range: '1-20',
    });
    await page.goto('/');

    const threadCard = page.getByRole('button', { name: /Black Panther/i });
    await expect(threadCard).toBeVisible({ timeout: 10000 });
    await threadCard.click();
    await page.getByRole('button', { name: /Edit Thread/i }).click();

    await expect(page.getByRole('dialog', { name: 'Set Current Issue' })).toBeVisible();
    await expect(page.getByLabel('Issue Number')).toHaveValue('1');
  });

  test('set current issue to #20 atomically corrects the thread and opens the active roll at #20', async ({
    authenticatedWithThreadsPage,
  }) => {
    const page = authenticatedWithThreadsPage;
    const thread = await createThread(page, {
      title: 'Black Panther',
      format: 'comic',
      issues_remaining: 20,
      total_issues: 20,
      issue_range: '1-20',
    });
    await page.goto('/');

    // Correct the reading position forward from #1 to #20 in one atomic operation.
    const threadCard = page.getByRole('button', { name: /Black Panther/i });
    await expect(threadCard).toBeVisible({ timeout: 10000 });
    await threadCard.click();
    await page.getByRole('button', { name: /Edit Thread/i }).click();

    const issueInput = page.getByLabel('Issue Number');
    await expect(issueInput).toBeVisible();
    await issueInput.fill('20');
    await page.getByRole('button', { name: 'Set Current Issue' }).click();

    // The active roll is retained and now presents the corrected issue #20.
    await expect(page.getByRole('heading', { name: /Black Panther #20/i })).toBeVisible({ timeout: 10000 });

    // Server state is atomic: issues 1-19 read, #20 unread/current, one issue left.
    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    const response = await page.request.get(`/api/threads/${thread.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(response.ok()).toBeTruthy();
    const threadData = await response.json();
    expect(threadData.next_unread_issue_number).toBe('20');
    expect(threadData.issues_remaining).toBe(1);
  });
});