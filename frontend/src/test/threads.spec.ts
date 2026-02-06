import { test, expect } from './fixtures';
import { createThread, SELECTORS } from './helpers';

test.describe('Thread Management', () => {
  test('should create a new thread successfully', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector('button:has-text("Add Thread")', { state: 'visible', timeout: 10000 });

    await authenticatedPage.click('button:has-text("Add Thread")');
    await authenticatedPage.waitForSelector('label:has-text("Title") + input', { state: 'visible', timeout: 5000 });

    await authenticatedPage.fill('label:has-text("Title") + input', 'Saga');
    await authenticatedPage.fill('label:has-text("Format") + input', 'Comic');
    await authenticatedPage.click('button[type="submit"]');
    
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForTimeout(1000);

    await authenticatedPage.waitForSelector('text=Saga', { state: 'visible', timeout: 15000 });
    await expect(authenticatedPage.locator('text=Saga')).toBeVisible();
  });

  test('should create multiple threads', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    const threads = [
      { title: 'Superman', format: 'Comic' },
      { title: 'Batman', format: 'Comic' },
      { title: 'Wonder Woman', format: 'Comic' },
    ];

    for (const thread of threads) {
      await authenticatedPage.click('button:has-text("Add Thread")');
      await authenticatedPage.waitForSelector('label:has-text("Title") + input', { state: 'visible', timeout: 5000 });
      
      await authenticatedPage.fill('label:has-text("Title") + input', thread.title);
      await authenticatedPage.fill('label:has-text("Format") + input', thread.format);
      await authenticatedPage.click('button[type="submit"]');
      
      await authenticatedPage.waitForLoadState("networkidle");
      await authenticatedPage.waitForTimeout(500);
      
      const closeButton = authenticatedPage.locator('button[aria-label="Close"], button:has-text("×"), button:has-text("Cancel")').first();
      if (await closeButton.count() > 0) {
        await closeButton.click();
      }
    }

    for (const thread of threads) {
      await expect(authenticatedPage.locator(`text=${thread.title}`)).toBeVisible();
    }
  });

  test('should validate thread title is required', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.click('button:has-text("Add Thread")');

    await authenticatedPage.click('button[type="submit"]');
    await authenticatedPage.waitForLoadState("networkidle");

    const hasInvalidInput = await authenticatedPage.locator('input:invalid').count() > 0;
    expect(hasInvalidInput).toBe(true);
  });

  test('should validate thread format is required', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.click('button:has-text("Add Thread")');

    await authenticatedPage.fill('label:has-text("Title") + input', 'Test Comic');
    await authenticatedPage.click('button[type="submit"]');
    await authenticatedPage.waitForLoadState("networkidle");

    const hasInvalidInput = await authenticatedPage.locator('input:invalid').count() > 0;
    expect(hasInvalidInput).toBe(true);
  });

  test('should display thread queue in correct order', async ({ authenticatedPage }) => {
    const threadTitles = ['First Thread', 'Second Thread', 'Third Thread'];

    for (const title of threadTitles) {
      await createThread(authenticatedPage, {
        title,
        format: 'Comic',
        issues_remaining: 5,
      });
    }

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForSelector('#queue-container', { timeout: 5000 });
    await authenticatedPage.reload();
    await authenticatedPage.waitForSelector('#queue-container', { timeout: 5000 });

    const threadElements = authenticatedPage.locator('#queue-container h3');
    const count = await threadElements.count();

    expect(count).toBeGreaterThanOrEqual(3);

    for (let i = 0; i < Math.min(count, 3); i++) {
      const text = await threadElements.nth(i).textContent();
      expect(text).toContain(threadTitles[i]);
    }
  });

  test('should edit existing thread', async ({ authenticatedPage }) => {
    await createThread(authenticatedPage, {
      title: 'Original Title',
      format: 'Comic',
      issues_remaining: 10,
    });

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector('#queue-container', { state: 'visible', timeout: 5000 });

    const threadItem = authenticatedPage.locator('#queue-container .glass-card').first();
    await threadItem.locator('button[aria-label="Edit thread"]').click();

    await authenticatedPage.fill('label:has-text("Title") + input', 'Updated Title');
    await authenticatedPage.click('button:has-text("Save Changes")');
    await authenticatedPage.waitForLoadState('networkidle');

    await authenticatedPage.waitForSelector('text=Updated Title', { state: 'visible', timeout: 5000 });
    await expect(authenticatedPage.locator('text=Updated Title')).toBeVisible();
  });

  test('should delete thread', async ({ authenticatedPage }) => {
    await createThread(authenticatedPage, {
      title: 'To Be Deleted',
      format: 'Comic',
      issues_remaining: 5,
    });

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForSelector('#queue-container', { state: 'visible', timeout: 5000 });

    authenticatedPage.on('dialog', dialog => dialog.accept());

    const threadItem = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: 'To Be Deleted' });
    await threadItem.waitFor({ state: 'visible', timeout: 5000 });
    await threadItem.locator('button[aria-label="Delete thread"]').click();

    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.reload();
    await authenticatedPage.waitForLoadState('networkidle');

    const deletedText = authenticatedPage.locator('text=To Be Deleted');
    await expect(async () => {
      const isVisible = await deletedText.count() > 0;
      expect(isVisible).toBe(false);
    }).toPass({ timeout: 5000 });
  });

  test('should show validation error for negative issues remaining', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.click('button:has-text("Add Thread")');

    await authenticatedPage.fill('label:has-text("Title") + input', 'Test Comic');
    await authenticatedPage.fill('label:has-text("Format") + input', 'Comic');
    await authenticatedPage.fill('input[type="number"]', '-1');
    await authenticatedPage.click('button[type="submit"]');
    await authenticatedPage.waitForLoadState("networkidle");

    const hasInvalidInput = await authenticatedPage.locator('input:invalid').count() > 0;
    expect(hasInvalidInput).toBe(true);
  });
});
