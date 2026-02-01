import { test, expect } from './fixtures';
import { generateTestUser, registerUser, loginUser, createThread, SELECTORS } from './helpers';

test.describe('Thread Management', () => {
  test('should create a new thread successfully', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/threads');
    await page.click(SELECTORS.threadList.newThreadButton);

    await page.fill(SELECTORS.threadList.titleInput, 'Saga');
    await page.fill(SELECTORS.threadList.formatInput, 'Comic');
    await page.click(SELECTORS.auth.submitButton);

    await expect(page.locator('text=Saga')).toBeVisible();
  });

  test('should create multiple threads', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/threads');

    const threads = [
      { title: 'Superman', format: 'Comic' },
      { title: 'Batman', format: 'Comic' },
      { title: 'Wonder Woman', format: 'Comic' },
    ];

    for (const thread of threads) {
      await page.click(SELECTORS.threadList.newThreadButton);
      await page.fill(SELECTORS.threadList.titleInput, thread.title);
      await page.fill(SELECTORS.threadList.formatInput, thread.format);
      await page.click(SELECTORS.auth.submitButton);
      await page.waitForTimeout(500);
    }

    for (const thread of threads) {
      await expect(page.locator(`text=${thread.title}`)).toBeVisible();
    }
  });

  test('should validate thread title is required', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/threads');
    await authenticatedPage.click(SELECTORS.threadList.newThreadButton);

    await authenticatedPage.click(SELECTORS.auth.submitButton);

    const errorText = await authenticatedPage.locator('text=title').locator('..').locator('text=required');
    await expect(errorText).toBeVisible({ timeout: 3000 });
  });

  test('should validate thread format is required', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/threads');
    await authenticatedPage.click(SELECTORS.threadList.newThreadButton);

    await authenticatedPage.fill(SELECTORS.threadList.titleInput, 'Test Comic');
    await authenticatedPage.click(SELECTORS.auth.submitButton);

    const errorText = await authenticatedPage.locator('text=format').locator('..').locator('text=required');
    await expect(errorText).toBeVisible({ timeout: 3000 });
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
    await page.waitForSelector(SELECTORS.threadList.container, { timeout: 5000 });

    const threadElements = page.locator('.thread-title');
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
    await page.waitForSelector(SELECTORS.threadList.container);

    const threadItem = page.locator('.thread-item').first();
    await threadItem.locator('.edit-button').click();

    await page.fill('input[name="title"]', 'Updated Title');
    await page.click('button:has-text("Save")');

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
    await page.waitForSelector(SELECTORS.threadList.container);

    const threadItem = page.locator('.thread-item').filter({ hasText: 'To Be Deleted' });
    await threadItem.locator('.delete-button').click();

    await page.click('button:has-text("Confirm")');

    await expect(page.locator('text=To Be Deleted')).not.toBeVisible();
  });

  test('should show validation error for negative issues remaining', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/threads');
    await authenticatedPage.click(SELECTORS.threadList.newThreadButton);

    await authenticatedPage.fill(SELECTORS.threadList.titleInput, 'Test Comic');
    await authenticatedPage.fill(SELECTORS.threadList.formatInput, 'Comic');
    await authenticatedPage.fill('input[name="issues_remaining"]', '-1');
    await authenticatedPage.click(SELECTORS.auth.submitButton);

    const error = await authenticatedPage.locator('text=issues_remaining').locator('..').locator('text=must be');
    await expect(error).toBeVisible({ timeout: 3000 });
  });
});
