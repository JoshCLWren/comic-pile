import { test, expect } from './fixtures';
import { createThread } from './helpers';

test.describe('Issue #326: Collapsible Issue List', () => {
  test('should show only issues around next unread by default when thread has many issues', async ({ authenticatedPage }) => {
    const timestamp = Date.now();
    const uniqueTitle = `Collapsible Test ${timestamp}`;

    // Create a thread with many issues
    await createThread(authenticatedPage, {
      title: uniqueTitle,
      format: 'Comics',
      issues_remaining: 20,
      issue_range: '1-20',
    });

    // Navigate to queue page
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector('#queue-container', { state: 'visible', timeout: 5000 });

    // Open the edit modal
    const threadItem = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: uniqueTitle });
    await threadItem.waitFor({ state: 'visible', timeout: 5000 });
    await threadItem.locator('button[aria-label="Edit thread"]').click();

    // Wait for edit modal to open
    await authenticatedPage.waitForSelector('h2:has-text("Edit Thread")', { state: 'visible', timeout: 5000 });
    const editModal = authenticatedPage.locator('.fixed.inset-0').filter({ hasText: 'Edit Thread' });
    await expect(editModal).toBeVisible();

    // Wait for issues to load (not loading state)
    await expect(editModal.locator('text=Loading issues…')).not.toBeVisible({ timeout: 10000 });

    // Check that "Show all" button is present
    const showAllButton = editModal.getByRole('button', { name: 'Show all 20' });
    await expect(showAllButton).toBeVisible();

    // Check that only a subset of issues is visible
    const visibleIssueCount = await editModal.locator('[data-testid^="issue-pill-"]').count();
    expect(visibleIssueCount).toBeLessThan(20);
    expect(visibleIssueCount).toBeGreaterThan(0);
  });

  test('should expand to show all issues when "Show all" button is clicked', async ({ authenticatedPage }) => {
    const timestamp = Date.now();
    const uniqueTitle = `Expand Test ${timestamp}`;

    // Create a thread with many issues
    await createThread(authenticatedPage, {
      title: uniqueTitle,
      format: 'Comics',
      issues_remaining: 15,
      issue_range: '1-15',
    });

    // Navigate to queue page
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector('#queue-container', { state: 'visible', timeout: 5000 });

    // Open the edit modal
    const threadItem = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: uniqueTitle });
    await threadItem.locator('button[aria-label="Edit thread"]').click();

    // Wait for edit modal to open
    await authenticatedPage.waitForSelector('h2:has-text("Edit Thread")', { state: 'visible', timeout: 5000 });
    const editModal = authenticatedPage.locator('.fixed.inset-0').filter({ hasText: 'Edit Thread' });

    // Wait for issues to load (not loading state)
    await expect(editModal.locator('text=Loading issues…')).not.toBeVisible({ timeout: 10000 });

    // Click "Show all" button
    const showAllButton = editModal.getByRole('button', { name: 'Show all 15' });
    await showAllButton.click();

    // Check that "Show fewer" button is now visible
    await expect(editModal.getByRole('button', { name: 'Show fewer' })).toBeVisible();

    // Check that all issues are now visible
    await expect(editModal.locator('[data-testid^="issue-pill-"]')).toHaveCount(15, { timeout: 10000 });
  });

  test('should collapse back to show fewer issues when "Show fewer" button is clicked', async ({ authenticatedPage }) => {
    const timestamp = Date.now();
    const uniqueTitle = `Collapse Test ${timestamp}`;

    // Create a thread with many issues
    await createThread(authenticatedPage, {
      title: uniqueTitle,
      format: 'Comics',
      issues_remaining: 12,
      issue_range: '1-12',
    });

    // Navigate to queue page
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector('#queue-container', { state: 'visible', timeout: 5000 });

    // Open the edit modal
    const threadItem = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: uniqueTitle });
    await threadItem.locator('button[aria-label="Edit thread"]').click();

    // Wait for edit modal to open
    await authenticatedPage.waitForSelector('h2:has-text("Edit Thread")', { state: 'visible', timeout: 5000 });
    const editModal = authenticatedPage.locator('.fixed.inset-0').filter({ hasText: 'Edit Thread' });

    // Wait for issues to load (not loading state)
    await expect(editModal.locator('text=Loading issues…')).not.toBeVisible({ timeout: 10000 });

    // Expand to show all issues
    const showAllButton = editModal.getByRole('button', { name: 'Show all 12' });
    await showAllButton.click();
    await expect(editModal.getByRole('button', { name: 'Show fewer' })).toBeVisible();

    // Collapse to show fewer issues
    const showFewerButton = editModal.getByRole('button', { name: 'Show fewer' });
    await showFewerButton.click();

    // Check that "Show all" button is back
    await expect(editModal.getByRole('button', { name: 'Show all 12' })).toBeVisible();

    // Check that only a subset of issues is visible again
    const visibleIssueCount = await editModal.locator('[data-testid^="issue-pill-"]').count();
    expect(visibleIssueCount).toBeLessThan(12);
  });

  test('should show all issues when thread has 5 or fewer issues', async ({ authenticatedPage }) => {
    const timestamp = Date.now();
    const uniqueTitle = `Small Thread Test ${timestamp}`;

    // Create a thread with few issues
    await createThread(authenticatedPage, {
      title: uniqueTitle,
      format: 'Comics',
      issues_remaining: 3,
      issue_range: '1-3',
    });

    // Navigate to queue page
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector('#queue-container', { state: 'visible', timeout: 5000 });

    // Open the edit modal
    const threadItem = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: uniqueTitle });
    await threadItem.locator('button[aria-label="Edit thread"]').click();

    // Wait for edit modal to open
    await authenticatedPage.waitForSelector('h2:has-text("Edit Thread")', { state: 'visible', timeout: 5000 });
    const editModal = authenticatedPage.locator('.fixed.inset-0').filter({ hasText: 'Edit Thread' });

    // Wait for issues to load (not loading state)
    await expect(editModal.locator('text=Loading issues…')).not.toBeVisible({ timeout: 10000 });

    // Check that "Show all" button is NOT present
    const showAllButton = editModal.getByRole('button', { name: /Show all/i });
    await expect(showAllButton).not.toBeVisible();

    // Check that all issues are visible
    await expect(editModal.locator('[data-testid^="issue-pill-"]')).toHaveCount(3, { timeout: 10000 });
  });

  test('should still allow issue toggling when list is collapsed', async ({ authenticatedPage }) => {
    const timestamp = Date.now();
    const uniqueTitle = `Toggle Test ${timestamp}`;

    // Create a thread with many issues
    await createThread(authenticatedPage, {
      title: uniqueTitle,
      format: 'Comics',
      issues_remaining: 10,
      issue_range: '1-10',
    });

    // Navigate to queue page
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector('#queue-container', { state: 'visible', timeout: 5000 });

    // Open the edit modal
    const threadItem = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: uniqueTitle });
    await threadItem.locator('button[aria-label="Edit thread"]').click();

    // Wait for edit modal to open
    await authenticatedPage.waitForSelector('h2:has-text("Edit Thread")', { state: 'visible', timeout: 5000 });
    const editModal = authenticatedPage.locator('.fixed.inset-0').filter({ hasText: 'Edit Thread' });

    // Find a visible unread issue and toggle it
    const firstVisibleIssue = editModal.locator('[data-testid^="issue-toggle-"]').first();
    await expect(firstVisibleIssue).toBeVisible();

    // Get the initial status
    const initialText = await firstVisibleIssue.textContent();

    // Click to toggle
    await firstVisibleIssue.click();

    // Verify the issue status changed (optimistic UI update)
    await expect(async () => {
      const newText = await firstVisibleIssue.textContent();
      expect(newText).not.toBe(initialText);
    }).toPass();
  });
});
