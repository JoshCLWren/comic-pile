import { test, expect } from './fixtures';

/**
 * Helper to create a thread without total_issues (old system) via API
 */
async function createOldSystemThread(
  request: any,
  token: string,
  title: string
) {
  const response = await request.post('/api/threads/', {
    data: {
      title,
      format: 'Comic',
      issues_remaining: 10,
    },
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok()) {
    throw new Error(`Failed to create thread: ${response.status()} ${response.statusText()}`);
  }

  const data = await response.json();
  return data;
}

/**
 * Helper to create a migrated thread via API
 */
async function createMigratedThread(
  request: any,
  token: string,
  title: string,
  totalIssues: number
) {
  const response = await request.post('/api/threads/', {
    data: {
      title,
      format: 'Comic',
      issues_remaining: 10,
      total_issues: totalIssues,
    },
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok()) {
    throw new Error(`Failed to create migrated thread: ${response.status()} ${response.statusText()}`);
  }

  const data = await response.json();
  return data;
}

test.describe('Migration Dialog', () => {
  test('dialog appears when clicking rate on old thread', async ({ authenticatedPage, request }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    if (!token) {
      throw new Error('No auth token found');
    }

    const threadTitle = `Old Thread ${Date.now()}`;
    const thread = await createOldSystemThread(request, token, threadTitle);

    // Reload to see the thread in the pool
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    // Open migration dialog
    const threadElement = authenticatedPage.locator('role=button').filter({ hasText: threadTitle }).first();
    await threadElement.click();

    // Wait for action sheet
    const actionSheetTitle = authenticatedPage.locator('h2').filter({ hasText: threadTitle });
    await expect(actionSheetTitle).toBeVisible();

    await authenticatedPage.getByRole('button', { name: 'Read Now' }).click();

    // Wait for migration dialog to be visible
    await expect(authenticatedPage.locator('.migration-dialog__overlay')).toBeVisible();

    // Click backdrop (overlay)
    const overlay = authenticatedPage.locator('.migration-dialog__overlay');
    await overlay.click({ position: { x: 10, y: 10 } });

    // Migration dialog should be closed
    await expect(authenticatedPage.locator('.migration-dialog__overlay')).toHaveCount(0);
  });

  test('dialog does NOT appear for migrated threads', async ({ authenticatedPage, request }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    if (!token) {
      throw new Error('No auth token found');
    }

    const threadTitle = `Migrated Thread ${Date.now()}`;
    const thread = await createMigratedThread(request, token, threadTitle, 50);

    // Reload to see the thread in the pool
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    // Click on the thread to open action sheet
    const threadElement = authenticatedPage.locator('role=button').filter({ hasText: threadTitle }).first();
    await expect(threadElement).toBeVisible();
    await threadElement.click();

    // Wait for action sheet to appear - use a more specific selector
    const actionSheetTitle = authenticatedPage.locator('h2').filter({ hasText: threadTitle });
    await expect(actionSheetTitle).toBeVisible();

    // Click "Read Now"
    const readButton = authenticatedPage.getByRole('button', { name: 'Read Now' });
    await readButton.click();

    // Migration dialog should NOT appear
    await expect(authenticatedPage.locator('.migration-dialog__overlay')).toHaveCount(0);

    // Instead, rating view should appear
    await expect(authenticatedPage.locator('#rating-input')).toBeVisible({ timeout: 10000 });
  });

  test('validation blocks empty inputs', async ({ authenticatedPage, request }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    if (!token) {
      throw new Error('No auth token found');
    }

    const threadTitle = `Old Thread ${Date.now()}`;
    const thread = await createOldSystemThread(request, token, threadTitle);

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    // Open migration dialog
    const threadElement = authenticatedPage.locator('role=button').filter({ hasText: threadTitle }).first();
    await threadElement.click();

    // Wait for action sheet
    const actionSheetTitle = authenticatedPage.locator('h2').filter({ hasText: threadTitle });
    await expect(actionSheetTitle).toBeVisible();

    await authenticatedPage.getByRole('button', { name: 'Read Now' }).click();

    // Wait for migration dialog to be visible
    await expect(authenticatedPage.locator('.migration-dialog__overlay')).toBeVisible();

    // Try to submit with empty fields
    const submitButton = authenticatedPage.locator('.migration-dialog__btn--primary');
    await submitButton.click();

    // Error message should appear
    await expect(authenticatedPage.locator('.migration-dialog__error')).toBeVisible();
    await expect(authenticatedPage.locator('.migration-dialog__error')).toContainText('Please fill in both fields');
  });

  test('validation blocks last_read > total', async ({ authenticatedPage, request }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    if (!token) {
      throw new Error('No auth token found');
    }

    const threadTitle = `Old Thread ${Date.now()}`;
    const thread = await createOldSystemThread(request, token, threadTitle);

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    // Open migration dialog
    const threadElement = authenticatedPage.locator('role=button').filter({ hasText: threadTitle }).first();
    await threadElement.click();

    // Wait for action sheet
    const actionSheetTitle = authenticatedPage.locator('h2').filter({ hasText: threadTitle });
    await expect(actionSheetTitle).toBeVisible();

    await authenticatedPage.getByRole('button', { name: 'Read Now' }).click();

    // Wait for migration dialog to be visible
    await expect(authenticatedPage.locator('.migration-dialog__overlay')).toBeVisible();

    // Enter invalid values (last_read > total)
    await authenticatedPage.fill('#last-issue-read', '15');
    await authenticatedPage.fill('#total-issues', '10');

    // Try to submit
    const submitButton = authenticatedPage.locator('.migration-dialog__btn--primary');
    await submitButton.click();

    // Error message should appear
    await expect(authenticatedPage.locator('.migration-dialog__error')).toBeVisible();
    await expect(authenticatedPage.locator('.migration-dialog__error')).toContainText('Last issue read cannot exceed total issues');
  });

  test('preview updates correctly as user types', async ({ authenticatedPage, request }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    if (!token) {
      throw new Error('No auth token found');
    }

    const threadTitle = `Old Thread ${Date.now()}`;
    const thread = await createOldSystemThread(request, token, threadTitle);

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    // Open migration dialog
    const threadElement = authenticatedPage.locator('role=button').filter({ hasText: threadTitle }).first();
    await threadElement.click();

    // Wait for action sheet
    const actionSheetTitle = authenticatedPage.locator('h2').filter({ hasText: threadTitle });
    await expect(actionSheetTitle).toBeVisible();

    await authenticatedPage.getByRole('button', { name: 'Read Now' }).click();

    // Wait for migration dialog to be visible
    await expect(authenticatedPage.locator('.migration-dialog__overlay')).toBeVisible();

    // Preview should not be visible initially
    await expect(authenticatedPage.locator('.migration-preview')).toHaveCount(0);

    // Enter total issues
    await authenticatedPage.fill('#total-issues', '25');

    // Still no preview without last issue read
    await expect(authenticatedPage.locator('.migration-preview')).toHaveCount(0);

    // Enter last issue read
    await authenticatedPage.fill('#last-issue-read', '15');

    // Preview should now be visible
    await expect(authenticatedPage.locator('.migration-preview')).toBeVisible();
    await expect(authenticatedPage.locator('.migration-preview')).toContainText('#1-#15');
    await expect(authenticatedPage.locator('.migration-preview')).toContainText('#16-#25');
    await expect(authenticatedPage.locator('.migration-preview')).toContainText('#16');
  });

  test('shows migration dialog when reading an old system thread', async ({ authenticatedPage, request }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    if (!token) {
      throw new Error('No auth token found');
    }

    const threadTitle = `Old Thread ${Date.now()}`;
    const thread = await createOldSystemThread(request, token, threadTitle);

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    // Click on the thread to open action sheet
    const threadElement = authenticatedPage.locator('role=button').filter({ hasText: threadTitle }).first();
    await threadElement.click();

    // Wait for action sheet
    const actionSheetTitle = authenticatedPage.locator('h2').filter({ hasText: threadTitle });
    await expect(actionSheetTitle).toBeVisible();

    // Click "Read Now" which should trigger migration check
    await authenticatedPage.getByRole('button', { name: 'Read Now' }).click();

    // Migration dialog should appear
    await expect(authenticatedPage.locator('.migration-dialog__overlay')).toBeVisible();
    await expect(authenticatedPage.locator('#migration-dialog-title')).toContainText('Track Issues');
    await expect(authenticatedPage.locator('#migration-dialog-title')).toContainText(threadTitle);
  });

  test('skip button shows confirmation dialog', async ({ authenticatedPage, request }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    if (!token) {
      throw new Error('No auth token found');
    }

    const threadTitle = `Old Thread ${Date.now()}`;
    const thread = await createOldSystemThread(request, token, threadTitle);

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    // Open migration dialog
    const threadElement = authenticatedPage.locator('role=button').filter({ hasText: threadTitle }).first();
    await threadElement.click();

    // Wait for action sheet
    const actionSheetTitle = authenticatedPage.locator('h2').filter({ hasText: threadTitle });
    await expect(actionSheetTitle).toBeVisible();

    await authenticatedPage.getByRole('button', { name: 'Read Now' }).click();

    // Wait for migration dialog to be visible
    await expect(authenticatedPage.locator('.migration-dialog__overlay')).toBeVisible();

    // Click Skip button
    const skipButton = authenticatedPage.locator('.migration-dialog__btn--secondary').filter({ hasText: 'Skip' });
    await skipButton.click();

    // Confirmation dialog should appear
    await expect(authenticatedPage.locator('.migration-dialog__confirm-overlay')).toBeVisible();
    await expect(authenticatedPage.locator('.migration-dialog__confirm-title')).toContainText('Skip migration?');

    // Cancel should close confirmation
    const cancelButton = authenticatedPage.locator('.migration-dialog__confirm-actions .migration-dialog__btn--secondary').filter({ hasText: 'Cancel' });
    await cancelButton.click();
    await expect(authenticatedPage.locator('.migration-dialog__confirm-overlay')).toHaveCount(0);

    // Migration dialog should still be open
    await expect(authenticatedPage.locator('.migration-dialog__overlay')).toBeVisible();
  });

  test('migration completes successfully and updates thread', async ({ authenticatedPage, request }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    if (!token) {
      throw new Error('No auth token found');
    }

    const threadTitle = `Old Thread ${Date.now()}`;
    const thread = await createOldSystemThread(request, token, threadTitle);

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    // Open migration dialog
    const threadElement = authenticatedPage.locator('role=button').filter({ hasText: threadTitle }).first();
    await threadElement.click();

    // Wait for action sheet
    const actionSheetTitle = authenticatedPage.locator('h2').filter({ hasText: threadTitle });
    await expect(actionSheetTitle).toBeVisible();

    await authenticatedPage.getByRole('button', { name: 'Read Now' }).click();

    // Wait for migration dialog to be visible
    await expect(authenticatedPage.locator('.migration-dialog__overlay')).toBeVisible();

    // Fill in migration data
    await authenticatedPage.fill('#last-issue-read', '15');
    await authenticatedPage.fill('#total-issues', '50');

    // Submit migration
    const submitButton = authenticatedPage.locator('.migration-dialog__btn--primary').filter({ hasText: 'Start Tracking' });
    await submitButton.click();

    // Wait for migration to complete - dialog should close
    await expect(authenticatedPage.locator('.migration-dialog__overlay')).toHaveCount(0, { timeout: 15000 });

    // Rating view should appear (migration proceeded to rating)
    await expect(authenticatedPage.locator('#rating-input')).toBeVisible();

    // Verify migration persists after reload
    await authenticatedPage.reload();
    await authenticatedPage.waitForLoadState('networkidle');

    // Cancel pending roll first so thread appears in pool
    const cancelButton = authenticatedPage.getByText('Cancel Pending Roll');
    if (await cancelButton.isVisible().catch(() => false)) {
      await cancelButton.click();
    }

    // Wait for thread list to update
    await authenticatedPage.waitForTimeout(500);

    // Find the thread element again after reload
    const threadElementReloaded = authenticatedPage.locator('role=button').filter({ hasText: threadTitle }).first();
    await expect(threadElementReloaded).toBeVisible({ timeout: 10000 });
    await threadElementReloaded.click();

    const actionSheetTitleReloaded = authenticatedPage.locator('h2').filter({ hasText: threadTitle });
    await expect(actionSheetTitleReloaded).toBeVisible();

    await authenticatedPage.getByRole('button', { name: 'Read Now' }).click();

    // Migration dialog should NOT appear (thread is already migrated)
    await expect(authenticatedPage.locator('.migration-dialog__overlay')).toHaveCount(0);

    // Rating view should appear directly
    await expect(authenticatedPage.locator('#rating-input')).toBeVisible();
  });

  test('skip allows proceeding to rating with old system', async ({ authenticatedPage, request }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    if (!token) {
      throw new Error('No auth token found');
    }

    const threadTitle = `Old Thread ${Date.now()}`;
    const thread = await createOldSystemThread(request, token, threadTitle);

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    // Open migration dialog
    const threadElement = authenticatedPage.locator('role=button').filter({ hasText: threadTitle }).first();
    await threadElement.click();

    // Wait for action sheet
    const actionSheetTitle = authenticatedPage.locator('h2').filter({ hasText: threadTitle });
    await expect(actionSheetTitle).toBeVisible();

    await authenticatedPage.getByRole('button', { name: 'Read Now' }).click();

    // Wait for migration dialog to be visible
    await expect(authenticatedPage.locator('.migration-dialog__overlay')).toBeVisible();

    // Click Skip, then confirm
    const skipButton = authenticatedPage.locator('.migration-dialog__btn--secondary').filter({ hasText: 'Skip' });
    await skipButton.click();
    
    const confirmButton = authenticatedPage.locator('.migration-dialog__confirm-actions .migration-dialog__btn--primary').filter({ hasText: 'Yes, Skip' });
    await confirmButton.click();

    // Wait for navigation
    await authenticatedPage.waitForLoadState('networkidle');

    // Migration dialog should be closed
    await expect(authenticatedPage.locator('.migration-dialog__overlay')).toHaveCount(0);

    // Rating view should appear
    await expect(authenticatedPage.locator('#rating-input')).toBeVisible();
  });

  test('close button dismisses dialog', async ({ authenticatedPage, request }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    if (!token) {
      throw new Error('No auth token found');
    }

    const threadTitle = `Old Thread ${Date.now()}`;
    const thread = await createOldSystemThread(request, token, threadTitle);

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    // Open migration dialog
    const threadElement = authenticatedPage.locator('role=button').filter({ hasText: threadTitle }).first();
    await threadElement.click();

    // Wait for action sheet
    const actionSheetTitle = authenticatedPage.locator('h2').filter({ hasText: threadTitle });
    await expect(actionSheetTitle).toBeVisible();

    await authenticatedPage.getByRole('button', { name: 'Read Now' }).click();

    // Wait for migration dialog to be visible
    await expect(authenticatedPage.locator('.migration-dialog__overlay')).toBeVisible();

    // Click close button
    const closeButton = authenticatedPage.locator('.migration-dialog__close-btn');
    await closeButton.click();

    // Migration dialog should be closed
    await expect(authenticatedPage.locator('.migration-dialog__overlay')).toHaveCount(0);

    // Should not be in rating view either
    await expect(authenticatedPage.locator('#rating-input')).toHaveCount(0);
  });

  test('escape key closes dialog', async ({ authenticatedPage, request }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    if (!token) {
      throw new Error('No auth token found');
    }

    const threadTitle = `Old Thread ${Date.now()}`;
    const thread = await createOldSystemThread(request, token, threadTitle);

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    // Open migration dialog
    const threadElement = authenticatedPage.locator('role=button').filter({ hasText: threadTitle }).first();
    await threadElement.click();

    // Wait for action sheet
    const actionSheetTitle = authenticatedPage.locator('h2').filter({ hasText: threadTitle });
    await expect(actionSheetTitle).toBeVisible();

    await authenticatedPage.getByRole('button', { name: 'Read Now' }).click();

    // Wait for migration dialog to be visible
    await expect(authenticatedPage.locator('.migration-dialog__overlay')).toBeVisible();

    // Test starting fresh (lastRead === 0)
    await authenticatedPage.fill('#total-issues', '50');
    await authenticatedPage.fill('#last-issue-read', '0');
    await expect(authenticatedPage.locator('.migration-warning')).toBeVisible();
    await expect(authenticatedPage.locator('.migration-warning')).toContainText('Starting fresh');

    // Test completing the series (lastRead === total)
    await authenticatedPage.fill('#last-issue-read', '50');
    await expect(authenticatedPage.locator('.migration-warning')).toBeVisible();
    await expect(authenticatedPage.locator('.migration-warning')).toContainText('Completing the series');

    // Test one issue away from completion
    await authenticatedPage.fill('#last-issue-read', '49');
    await expect(authenticatedPage.locator('.migration-warning')).toBeVisible();
    await expect(authenticatedPage.locator('.migration-warning')).toContainText('One issue away');
  });

  test('backdrop click closes dialog', async ({ authenticatedPage, request }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    if (!token) {
      throw new Error('No auth token found');
    }

    const threadTitle = `Old Thread ${Date.now()}`;
    const thread = await createOldSystemThread(request, token, threadTitle);

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    // Open migration dialog
    const threadElement = authenticatedPage.locator('role=button').filter({ hasText: threadTitle }).first();
    await threadElement.click();

    // Wait for action sheet
    const actionSheetTitle = authenticatedPage.locator('h2').filter({ hasText: threadTitle });
    await expect(actionSheetTitle).toBeVisible();

    await authenticatedPage.getByRole('button', { name: 'Read Now' }).click();

    // Wait for migration dialog to be visible
    await expect(authenticatedPage.locator('.migration-dialog__overlay')).toBeVisible();

    // Press Escape
    await authenticatedPage.keyboard.press('Escape');

    // Migration dialog should be closed
    await expect(authenticatedPage.locator('.migration-dialog__overlay')).toHaveCount(0);
  });
});
