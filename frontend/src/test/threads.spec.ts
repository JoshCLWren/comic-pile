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
    await authenticatedPage.selectOption('label:has-text("Format") + select', 'Comics');
    await Promise.all([
      authenticatedPage.waitForResponse((response) =>
        response.url().includes('/api/threads/') &&
        response.request().method() === 'POST' &&
        response.status() < 300
      ),
      authenticatedPage.click('button[type="submit"]'),
    ]);
    
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.waitForTimeout(1000);

    await authenticatedPage.waitForSelector('#queue-container h3', { state: 'visible', timeout: 15000 });
    await expect(authenticatedPage.locator('#queue-container h3').filter({ hasText: 'Saga' })).toBeVisible();
  });

  test('should create multiple threads', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    const threads = [
      { title: 'Superman', format: 'Comics' },
      { title: 'Batman', format: 'Comics' },
      { title: 'Wonder Woman', format: 'Comics' },
    ];

    for (const thread of threads) {
      await authenticatedPage.click('button:has-text("Add Thread")');
      await authenticatedPage.waitForSelector('label:has-text("Title") + input', { state: 'visible', timeout: 5000 });
      
      await authenticatedPage.fill('label:has-text("Title") + input', thread.title);
      await authenticatedPage.selectOption('label:has-text("Format") + select', thread.format);
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

    const hasInvalidInput = await authenticatedPage.locator('select:invalid, input:invalid').count() > 0;
    expect(hasInvalidInput).toBe(true);
  });

  test('should display thread queue in correct order', async ({ authenticatedPage }) => {
    const threadTitles = ['First Thread', 'Second Thread', 'Third Thread'];

    for (const title of threadTitles) {
      await createThread(authenticatedPage, {
        title,
        format: 'Comics',
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
      format: 'Comics',
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
      format: 'Comics',
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

  test('should validate issues_remaining is non-negative', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.click('button:has-text("Add Thread")');

    await authenticatedPage.fill('label:has-text("Title") + input', 'Test Comic');
    await authenticatedPage.selectOption('label:has-text("Format") + select', 'Comics');

    const issuesInput = authenticatedPage.locator('input[type="number"]').first();
    await issuesInput.fill('-1');

    const isValid = await issuesInput.evaluate((el) => (el as HTMLInputElement).checkValidity());
    expect(isValid).toBe(false);

    const validationMessage = await issuesInput.evaluate((el) => (el as HTMLInputElement).validationMessage);
    expect(validationMessage).not.toBe('');
  });
});
