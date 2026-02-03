import { test, expect } from './fixtures';
import { generateTestUser, registerUser, loginUser, createThread, SELECTORS } from './helpers';

test.describe('Thread Management', () => {
  test('should create a new thread successfully', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/queue');
    await page.click('button:has-text("Add Thread")');

    await page.fill('label:has-text("Title") + input', 'Saga');
    await page.fill('label:has-text("Format") + input', 'Comic');
    await page.click('button[type="submit"]');

    await expect(page.locator('text=Saga')).toBeVisible();
  });

  test('should create multiple threads', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/queue');

    const threads = [
      { title: 'Superman', format: 'Comic' },
      { title: 'Batman', format: 'Comic' },
      { title: 'Wonder Woman', format: 'Comic' },
    ];

    for (const thread of threads) {
      await page.click('button:has-text("Add Thread")');
      await page.fill('label:has-text("Title") + input', thread.title);
      await page.fill('label:has-text("Format") + input', thread.format);
      await page.click('button[type="submit"]');
      await page.waitForTimeout(500);
    }

    for (const thread of threads) {
      await expect(page.locator(`text=${thread.title}`)).toBeVisible();
    }
  });

  test('should validate thread title is required', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.click('button:has-text("Add Thread")');

    await authenticatedPage.click('button[type="submit"]');
    await authenticatedPage.waitForTimeout(1000);

    const hasInvalidInput = await authenticatedPage.locator('input:invalid').count() > 0;
    expect(hasInvalidInput).toBe(true);
  });

  test('should validate thread format is required', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.click('button:has-text("Add Thread")');

    await authenticatedPage.fill('label:has-text("Title") + input', 'Test Comic');
    await authenticatedPage.click('button[type="submit"]');
    await authenticatedPage.waitForTimeout(1000);

    const hasInvalidInput = await authenticatedPage.locator('input:invalid').count() > 0;
    expect(hasInvalidInput).toBe(true);
  });

  test('should display thread queue in correct order', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    const threadTitles = ['First Thread', 'Second Thread', 'Third Thread'];

    for (const title of threadTitles) {
      await createThread(page, {
        title,
        format: 'Comic',
        issues_remaining: 5,
      });
    }

    await page.goto('/queue');
    await page.waitForSelector('#queue-container', { timeout: 5000 });
    await page.reload();
    await page.waitForSelector('#queue-container', { timeout: 5000 });

    const threadElements = page.locator('#queue-container h3');
    const count = await threadElements.count();

    expect(count).toBeGreaterThanOrEqual(3);

    for (let i = 0; i < Math.min(count, 3); i++) {
      const text = await threadElements.nth(i).textContent();
      expect(text).toContain(threadTitles[i]);
    }
  });

  test('should edit existing thread', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'Original Title',
      format: 'Comic',
      issues_remaining: 10,
    });

    await page.goto('/queue');
    await page.waitForSelector('#queue-container');

    const threadItem = page.locator('#queue-container .glass-card').first();
    await threadItem.locator('button[aria-label="Edit thread"]').click();

    await page.fill('label:has-text("Title") + input', 'Updated Title');
    await page.click('button:has-text("Save Changes")');

    await expect(page.locator('text=Updated Title')).toBeVisible();
  });

  test('should delete thread', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'To Be Deleted',
      format: 'Comic',
      issues_remaining: 5,
    });

    await page.goto('/queue');
    await page.waitForSelector('#queue-container');

    page.on('dialog', dialog => dialog.accept());

    const threadItem = page.locator('#queue-container .glass-card').filter({ hasText: 'To Be Deleted' });
    await threadItem.locator('button[aria-label="Delete thread"]').click();

    await page.waitForTimeout(2000);

    await page.reload();
    await page.waitForLoadState('networkidle');

    const deletedText = page.locator('text=To Be Deleted');
    const isVisible = await deletedText.count() > 0;
    expect(isVisible).toBe(false);
  });

  test('should show validation error for negative issues remaining', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.click('button:has-text("Add Thread")');

    await authenticatedPage.fill('label:has-text("Title") + input', 'Test Comic');
    await authenticatedPage.fill('label:has-text("Format") + input', 'Comic');
    await authenticatedPage.fill('input[type="number"]', '-1');
    await authenticatedPage.click('button[type="submit"]');
    await authenticatedPage.waitForTimeout(1000);

    const hasInvalidInput = await authenticatedPage.locator('input:invalid').count() > 0;
    expect(hasInvalidInput).toBe(true);
  });
});
