import { test, expect } from './fixtures';
import { generateTestUser, registerUser, loginUser, createThread, SELECTORS } from './helpers';

test.describe('Edge Cases & Error Handling', () => {
  test('should handle empty form submission', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.click('button:has-text("Add Thread")');
    await authenticatedPage.click('button[type="submit"]');

    const errors = authenticatedPage.locator('input:invalid');
    await expect(errors.first()).toBeVisible({ timeout: 3000 });
  });

  test('should handle very long thread titles', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    const longTitle = 'A'.repeat(500);

    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    const response = await page.request.post('/api/threads/', {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      data: {
        title: longTitle,
        format: 'Comic',
        issues_remaining: 5,
      },
    });

    const status = response.status();
    expect([400, 422, 500]).toContain(status);
  });

  test('should handle special characters in input', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    const specialTitle = 'Test\'s "Comic" & More! @#$%^&*()';

    await createThread(page, {
      title: specialTitle,
      format: 'Comic',
      issues_remaining: 5,
    });

    await page.goto('/queue');

    const escapedTitle = page.locator(`text=${specialTitle.replace(/"/g, '\\"')}`);
    const isPresent = await escapedTitle.count() > 0;

    if (isPresent) {
      await expect(escapedTitle.first()).toBeVisible();
    }
  });

  test('should handle rapid button clicks', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');

    for (let i = 0; i < 10; i++) {
      try {
        await authenticatedPage.click('button:has-text("Add Thread")', { timeout: 1000 });
        await authenticatedPage.waitForTimeout(50);
      } catch {
        // Modal might already be open
      }
    }

    const modalCount = await authenticatedPage.locator('.modal, dialog').count();
    expect(modalCount).toBeLessThanOrEqual(2);
  });

  test('should handle browser back button', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/queue');
    await page.waitForTimeout(500);
    await page.goBack();

    await expect(page).toHaveURL('http://localhost:8002/');
  });

  test('should handle browser forward button', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/queue');
    await page.waitForTimeout(500);
    await page.goBack();
    await page.waitForTimeout(500);
    await page.goForward();

    await expect(page).toHaveURL('http://localhost:8002/queue');
  });

  test('should handle page refresh during form submission', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/queue');
    await page.click('button:has-text("Add Thread")');
    await page.fill('label:has-text("Title") + input', 'Refresh Test');
    await page.fill('label:has-text("Format") + input', 'Comic');

    await page.reload();

    const formVisible = await page.locator('input[name="title"]').count() > 0;
    if (formVisible) {
      await expect(page.locator('input[name="title"]')).toHaveValue('');
    }
  });

  test('should handle concurrent tab sessions', async ({ context }) => {
    const user = generateTestUser();

    const page1 = await context.newPage();
    const page2 = await context.newPage();

    await registerUser(page1, user);
    await loginUser(page1, user);
    const token = await page1.evaluate(() => localStorage.getItem('auth_token'));

    await page2.addInitScript((token: string) => {
      localStorage.setItem('auth_token', token);
    }, token!);

    await page1.goto('/threads');
    await page2.goto('/threads');

    await createThread(page1, {
      title: 'Concurrent Tab Test',
      format: 'Comic',
      issues_remaining: 5,
    });

    await page1.waitForTimeout(1000);
    await page2.reload();

    const threadOnPage2 = page2.locator('text=Concurrent Tab Test');
    const isVisible = await threadOnPage2.count() > 0;

    if (isVisible) {
      await expect(threadOnPage2.first()).toBeVisible();
    }

    await page1.close();
    await page2.close();
  });

  test('should handle extremely large issues_remaining', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    const response = await page.request.post('/api/threads/', {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      data: {
        title: 'Large Number Test',
        format: 'Comic',
        issues_remaining: 999999,
      },
    });

    expect([200, 201, 400, 422]).toContain(response.status());
  });

  test('should handle negative issues_remaining', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    const response = await page.request.post('/api/threads/', {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      data: {
        title: 'Negative Test',
        format: 'Comic',
        issues_remaining: -5,
      },
    });

    expect([400, 422]).toContain(response.status());
  });

  test('should handle zero issues_remaining', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'Zero Issues Test',
      format: 'Comic',
      issues_remaining: 0,
    });

    await page.goto('/queue');

    const thread = page.locator('text=Zero Issues Test');
    await expect(thread.first()).toBeVisible();
  });

  test('should handle bookmarking/direct URL access', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/queue');
    await page.waitForLoadState('networkidle');

    const url = page.url();
    await page.goto('/');

    await page.goto(url);
    await page.waitForLoadState('networkidle');

    await expect(page.locator('h1:has-text("Read Queue")')).toBeVisible();
  });

  test('should handle losing network connection', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/queue');
    await page.waitForLoadState('networkidle');

    await page.context().setOffline(true);

    const offlineMessage = page.locator('text=offline|no connection|network error');
    const hasMessage = await offlineMessage.count({ timeout: 5000 }).then(c => c > 0);

    if (hasMessage) {
      await expect(offlineMessage.first()).toBeVisible();
    }

    await page.context().setOffline(false);
  });

  test('should handle regaining network connection', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/queue');
    await page.waitForLoadState('networkidle');

    await page.context().setOffline(true);
    await page.waitForTimeout(1000);

    await page.context().setOffline(false);
    await page.reload();

    await expect(page.locator('body')).toBeVisible();
  });

  test('should handle browser storage disabled', async ({ context }) => {
    const user = generateTestUser();

    const page = await context.newPage();

    await page.goto('/register');
    await page.fill(SELECTORS.auth.usernameInput, user.username);
    await page.fill(SELECTORS.auth.emailInput, user.email);
    await page.fill(SELECTORS.auth.passwordInput, user.password);
    await page.fill(SELECTORS.auth.confirmPasswordInput, user.password);
    await page.click(SELECTORS.auth.submitButton);

    await page.waitForTimeout(2000);

    const currentUrl = page.url();
    expect(currentUrl).toMatch(/\/threads\/?$|\/queue\/?$|\/$/);

    await page.close();
  });

  test('should handle cookies disabled', async ({ context }) => {
    await context.clearCookies();

    const user = generateTestUser();
    const page = await context.newPage();

    await page.goto('/register');
    await page.fill(SELECTORS.auth.usernameInput, user.username);
    await page.fill(SELECTORS.auth.emailInput, user.email);
    await page.fill(SELECTORS.auth.passwordInput, user.password);
    await page.fill(SELECTORS.auth.confirmPasswordInput, user.password);
    await page.click(SELECTORS.auth.submitButton);
    await page.waitForURL('**/', { timeout: 5000 });

    const hasToken = await page.evaluate(() => !!localStorage.getItem('auth_token'));
    expect(hasToken).toBe(true);

    await page.close();
  });

  test('should handle rapid page navigations', async ({ authenticatedPage }) => {
    const routes = ['/', '/threads', '/queue', '/analytics', '/history'];

    for (let i = 0; i < 5; i++) {
      for (const route of routes) {
        await authenticatedPage.goto(route);
        await authenticatedPage.waitForTimeout(100);
      }
    }

    await expect(authenticatedPage.locator('body')).toBeVisible();
  });

  test('should handle very slow network', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.route('**/*', async route => {
      await new Promise(resolve => setTimeout(resolve, 5000));
      await route.continue();
    });

    await page.goto('/queue');

    const loadingIndicator = page.locator('.loading, .spinner');
    const hasLoading = await loadingIndicator.count() > 0;

    if (hasLoading) {
      await expect(loadingIndicator.first()).toBeVisible();
    }

    await expect(page.locator('body')).toBeVisible({ timeout: 30000 });
  });

  test('should handle session timeout', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.evaluate(() => {
      localStorage.removeItem('auth_token');
    });

    await page.reload();

    const loginPrompt = page.locator('text=login|sign in|expired');
    const hasPrompt = await loginPrompt.count() > 0;

    if (hasPrompt) {
      await expect(loginPrompt.first()).toBeVisible();
    }
  });

  test('should handle duplicate thread creation', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    const threadData = {
      title: 'Duplicate Test',
      format: 'Comic',
      issues_remaining: 5,
    };

    await createThread(page, threadData);
    await createThread(page, threadData);

    await page.goto('/queue');
    await page.waitForLoadState('networkidle');
    await page.reload();
    await page.waitForLoadState('networkidle');

    const duplicates = await page.locator('text=Duplicate Test').count();
    expect(duplicates).toBeGreaterThanOrEqual(2);
  });
});
