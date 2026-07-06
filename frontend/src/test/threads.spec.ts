import { test, expect } from './fixtures';
import {
  createThread,
  gotoQueue,
  SELECTORS,
  waitForEditThreadModal,
  waitForThreadInQueue,
} from './helpers';

test.describe('Thread Management', () => {
  test('should create a new thread successfully', async ({ authenticatedPage }) => {
    await gotoQueue(authenticatedPage);
    await expect(authenticatedPage.getByRole('button', { name: 'Add Thread' })).toBeVisible();

    await authenticatedPage.click('button:has-text("Add Thread")');
    await authenticatedPage.waitForSelector('label:has-text("Title") + input', { state: 'visible', timeout: 5000 });

    await authenticatedPage.fill('label:has-text("Title") + input', 'Saga');
    await authenticatedPage.selectOption('label:has-text("Format") + select', 'Comics');
    await authenticatedPage.fill(SELECTORS.threadCreate.issuesInput, '1-10');
    await Promise.all([
      authenticatedPage.waitForResponse((response) =>
        response.url().includes('/api/threads/') &&
        response.request().method() === 'POST' &&
        response.status() < 300
      ),
      authenticatedPage.click('button[type="submit"]'),
    ]);
    
    await waitForThreadInQueue(authenticatedPage, 'Saga');
  });

  test('should create multiple threads', async ({ authenticatedPage }) => {
    await gotoQueue(authenticatedPage);

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
      await authenticatedPage.fill(SELECTORS.threadCreate.issuesInput, '1-10');
      await Promise.all([
        authenticatedPage.waitForResponse((response) =>
          response.url().includes('/api/threads/') &&
          response.request().method() === 'POST' &&
          response.status() < 300
        ),
        authenticatedPage.click('button[type="submit"]'),
      ]);
      await waitForThreadInQueue(authenticatedPage, thread.title);
      
      const closeButton = authenticatedPage.locator('button[aria-label="Close"], button:has-text("×"), button:has-text("Cancel")').first();
      if (await closeButton.count() > 0) {
        await closeButton.click();
      }
    }

    for (const thread of threads) {
      await expect(authenticatedPage.locator('#queue-container h3').filter({ hasText: thread.title })).toBeVisible();
    }
  });

  test('should validate thread title is required', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.click('button:has-text("Add Thread")');

    await authenticatedPage.click('button[type="submit"]');
    await expect(authenticatedPage.locator('select:invalid, input:invalid').first()).toBeAttached();

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

    await gotoQueue(authenticatedPage);
    await authenticatedPage.reload();
    await waitForThreadInQueue(authenticatedPage, threadTitles[0]);

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

    await gotoQueue(authenticatedPage);

    const threadItem = authenticatedPage.locator('#queue-container .glass-card').first();
    await threadItem.locator('button[aria-label="Edit thread"]').click();
    await waitForEditThreadModal(authenticatedPage);

    await authenticatedPage.fill('label:has-text("Title") + input', 'Updated Title');
    await Promise.all([
      authenticatedPage.waitForResponse((response) =>
        response.url().includes('/api/threads/') &&
        response.request().method() === 'PUT' &&
        response.status() < 300
      ),
      authenticatedPage.click('button:has-text("Save Changes")'),
    ]);

    await waitForThreadInQueue(authenticatedPage, 'Updated Title');
  });

  test('should delete thread', async ({ authenticatedPage }) => {
    await createThread(authenticatedPage, {
      title: 'To Be Deleted',
      format: 'Comics',
      issues_remaining: 5,
    });

    await gotoQueue(authenticatedPage);

    authenticatedPage.on('dialog', dialog => dialog.accept());

    const threadItem = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: 'To Be Deleted' });
    await threadItem.waitFor({ state: 'visible', timeout: 5000 });
    await Promise.all([
      authenticatedPage.waitForResponse((response) =>
        response.url().includes('/api/threads/') &&
        response.request().method() === 'DELETE'
      ),
      threadItem.locator('button[aria-label="Delete thread"]').click(),
    ]);
    await authenticatedPage.reload({ waitUntil: 'domcontentloaded' });
    await expect(authenticatedPage.getByRole('heading', { name: 'Read Queue' })).toBeVisible();

    const deletedText = authenticatedPage.locator('text=To Be Deleted');
    await expect(async () => {
      const isVisible = await deletedText.count() > 0;
      expect(isVisible).toBe(false);
    }).toPass({ timeout: 5000 });
  });

  test('should validate issues_remaining is non-negative', async ({ authenticatedPage }) => {
    await gotoQueue(authenticatedPage);
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
