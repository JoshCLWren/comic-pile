import { test, expect } from './fixtures';
import { createThread } from './helpers';

test.describe('Thread Detail View', () => {
  test('should navigate to thread detail view when clicking a thread', async ({ authenticatedPage }) => {
    await createThread(authenticatedPage, {
      title: 'Detail View Test',
      format: 'Comics',
      issues_remaining: 10,
    });

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector('#queue-container', { state: 'visible', timeout: 5000 });

    const threadCard = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: 'Detail View Test' });
    await threadCard.waitFor({ state: 'visible', timeout: 5000 });
    await threadCard.click();

    await authenticatedPage.waitForURL('**/thread/**', { timeout: 5000 });
    expect(authenticatedPage.url()).toMatch(/\/thread\/\d+/);

    await expect(authenticatedPage.locator('h1:has-text("Detail View Test")')).toBeVisible();
  });

  test('should display thread details including title, format, and progress', async ({ authenticatedPage }) => {
    await createThread(authenticatedPage, {
      title: 'Progress Test',
      format: 'Comics',
      issues_remaining: 10,
    });

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    const threadCard = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: 'Progress Test' });
    await threadCard.waitFor({ state: 'visible', timeout: 5000 });
    await threadCard.click();

    await authenticatedPage.waitForURL('**/thread/**', { timeout: 5000 });
    await authenticatedPage.waitForSelector('h1:has-text("Progress Test")', { state: 'visible', timeout: 5000 });

    await expect(authenticatedPage.locator('h1:has-text("Progress Test")')).toBeVisible();
    await expect(authenticatedPage.locator('text=Comics')).toBeVisible();
    await expect(authenticatedPage.locator('text=10 issues')).toBeVisible();
  });

  test('should display migrated thread with issue tracking', async ({ authenticatedPage }) => {
    const thread = await createThread(authenticatedPage, {
      title: 'Migrated Thread',
      format: 'Comics',
      issues_remaining: 10,
      issue_range: '1-10',
    });

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    const threadCard = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: 'Migrated Thread' });
    await threadCard.waitFor({ state: 'visible', timeout: 5000 });
    await threadCard.click();

    await authenticatedPage.waitForURL('**/thread/**', { timeout: 5000 });
    await authenticatedPage.waitForSelector('h1:has-text("Migrated Thread")', { state: 'visible', timeout: 5000 });

    await expect(authenticatedPage.locator('h1:has-text("Migrated Thread")')).toBeVisible();
    await expect(authenticatedPage.locator('text=Reading Progress')).toBeVisible();
    await expect(authenticatedPage.locator('text=0%')).toBeVisible();
  });

  test('should allow editing thread from detail view', async ({ authenticatedPage }) => {
    await createThread(authenticatedPage, {
      title: 'Edit From Detail',
      format: 'Comics',
      issues_remaining: 5,
    });

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    const threadCard = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: 'Edit From Detail' });
    await threadCard.waitFor({ state: 'visible', timeout: 5000 });
    await threadCard.click();

    await authenticatedPage.waitForURL('**/thread/**', { timeout: 5000 });
    await authenticatedPage.waitForSelector('h1:has-text("Edit From Detail")', { state: 'visible', timeout: 5000 });

    await authenticatedPage.click('button:has-text("Edit")');
    await authenticatedPage.waitForSelector('label:has-text("Title") + input', { state: 'visible', timeout: 5000 });

    await authenticatedPage.fill('label:has-text("Title") + input', 'Updated Title');
    await authenticatedPage.click('button:has-text("Save Changes")');
    await authenticatedPage.waitForLoadState('networkidle');

    await expect(authenticatedPage.locator('h1:has-text("Updated Title")')).toBeVisible();
  });

  test('should navigate back to queue when clicking back button', async ({ authenticatedPage }) => {
    await createThread(authenticatedPage, {
      title: 'Back Button Test',
      format: 'Comics',
      issues_remaining: 8,
    });

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    const threadCard = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: 'Back Button Test' });
    await threadCard.waitFor({ state: 'visible', timeout: 5000 });
    await threadCard.click();

    await authenticatedPage.waitForURL('**/thread/**', { timeout: 5000 });
    await authenticatedPage.waitForSelector('h1:has-text("Back Button Test")', { state: 'visible', timeout: 5000 });

    await authenticatedPage.click('button:has-text("Back to Queue")');
    await authenticatedPage.waitForURL('**/queue', { timeout: 5000 });

    await expect(authenticatedPage.locator('#queue-container')).toBeVisible();
  });

  test('should display thread notes in detail view', async ({ authenticatedPage }) => {
    await createThread(authenticatedPage, {
      title: 'Notes Test',
      format: 'Comics',
      issues_remaining: 5,
    });

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    const threadCard = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: 'Notes Test' });
    await threadCard.waitFor({ state: 'visible', timeout: 5000 });

    await threadCard.locator('button[aria-label="Edit thread"]').click();
    await authenticatedPage.waitForSelector('label:has-text("Notes") + textarea', { state: 'visible', timeout: 5000 });

    await authenticatedPage.fill('label:has-text("Notes") + textarea', 'These are test notes for the thread');
    await authenticatedPage.click('button:has-text("Save Changes")');
    await authenticatedPage.waitForLoadState('networkidle');

    await threadCard.click();
    await authenticatedPage.waitForURL('**/thread/**', { timeout: 5000 });

    await expect(authenticatedPage.locator('text=These are test notes for the thread')).toBeVisible();
  });

  test('should expand and collapse issue list', async ({ authenticatedPage }) => {
    const thread = await createThread(authenticatedPage, {
      title: 'Issue List Test',
      format: 'Comics',
      issues_remaining: 5,
      issue_range: '1-5',
    });

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    const threadCard = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: 'Issue List Test' });
    await threadCard.waitFor({ state: 'visible', timeout: 5000 });
    await threadCard.click();

    await authenticatedPage.waitForURL('**/thread/**', { timeout: 5000 });
    await authenticatedPage.waitForSelector('h1:has-text("Issue List Test")', { state: 'visible', timeout: 5000 });

    await expect(authenticatedPage.locator('text=Issues (5)')).toBeVisible();
    await expect(authenticatedPage.locator('text=Next up: #1')).toBeVisible();

    await authenticatedPage.click('button:has-text("Expand")');
    await authenticatedPage.waitForSelector('text=#1', { state: 'visible', timeout: 5000 });

    const issueList = authenticatedPage.locator('.glass-card').filter({ hasText: 'Issues (5)' });
    await expect(issueList.locator('text=#1').first()).toBeVisible();
    await expect(issueList.locator('text=#2').first()).toBeVisible();
    await expect(issueList.locator('text=#3').first()).toBeVisible();

    await authenticatedPage.click('button:has-text("Collapse")');
    await authenticatedPage.waitForSelector('text=Next up: #1', { state: 'visible', timeout: 5000 });

    await expect(authenticatedPage.locator('text=Next up: #1')).toBeVisible();
  });
});
