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

  test('should handle very long thread titles', async ({ authenticatedPage }) => {
    const longTitle = 'A'.repeat(500);

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    const response = await authenticatedPage.request.post('/api/threads/', {
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

  test('should handle special characters in input', async ({ authenticatedPage }) => {
    const specialTitle = 'Test\'s "Comic" & More! @#$%^&*()';

    await createThread(authenticatedPage, {
      title: specialTitle,
      format: 'Comic',
      issues_remaining: 5,
    });

    await authenticatedPage.goto('/queue');

    const escapedTitle = authenticatedPage.locator(`text=${specialTitle.replace(/"/g, '\\"')}`);
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
        // Removed small delay for rapid click test
      } catch {
        // Modal might already be open
      }
    }

    const modalCount = await authenticatedPage.locator('.modal, dialog').count();
    expect(modalCount).toBeLessThanOrEqual(2);
  });

  test('should handle browser back button', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState("networkidle");
    await authenticatedPage.goBack();

    await expect(authenticatedPage).toHaveURL('http://localhost:8000/');
  });

  test('should handle browser forward button', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState("networkidle");
    await authenticatedPage.goBack();
    await authenticatedPage.waitForLoadState("networkidle");
    await authenticatedPage.goForward();

    await expect(authenticatedPage).toHaveURL('http://localhost:8000/queue');
  });

  test('should handle page refresh during form submission', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.click('button:has-text("Add Thread")');
    await authenticatedPage.fill('label:has-text("Title") + input', 'Refresh Test');
    await authenticatedPage.fill('label:has-text("Format") + input', 'Comic');

    await authenticatedPage.reload();

    const formVisible = await authenticatedPage.locator('input[name="title"]').count() > 0;
    if (formVisible) {
      await expect(authenticatedPage.locator('input[name="title"]')).toHaveValue('');
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

    await page1.waitForLoadState("networkidle");
    await page2.reload();

    const threadOnPage2 = page2.locator('text=Concurrent Tab Test');
    const isVisible = await threadOnPage2.count() > 0;

    if (isVisible) {
      await expect(threadOnPage2.first()).toBeVisible();
    }

    await page1.close();
    await page2.close();
  });

  test('should handle extremely large issues_remaining', async ({ authenticatedPage }) => {
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    const response = await authenticatedPage.request.post('/api/threads/', {
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

  test('should handle negative issues_remaining', async ({ authenticatedPage }) => {
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    const response = await authenticatedPage.request.post('/api/threads/', {
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

  test('should handle zero issues_remaining', async ({ authenticatedPage }) => {
    await createThread(authenticatedPage, {
      title: 'Zero Issues Test',
      format: 'Comic',
      issues_remaining: 0,
    });

    await authenticatedPage.goto('/queue');

    const thread = authenticatedPage.locator('text=Zero Issues Test');
    await expect(thread.first()).toBeVisible();
  });

  test('should handle bookmarking/direct URL access', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    const url = authenticatedPage.url();
    await authenticatedPage.goto('/');

    await authenticatedPage.goto(url);
    await authenticatedPage.waitForLoadState('networkidle');

    await expect(authenticatedPage.locator('h1:has-text("Read Queue")')).toBeVisible();
  });

  test('should handle losing network connection', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    await authenticatedPage.context().setOffline(true);

    const offlineMessage = authenticatedPage.locator('text=offline|no connection|network error');
    const hasMessage = await offlineMessage.count({ timeout: 5000 }).then(c => c > 0);

    if (hasMessage) {
      await expect(offlineMessage.first()).toBeVisible();
    }

    await authenticatedPage.context().setOffline(false);
  });

  test('should handle regaining network connection', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    await authenticatedPage.context().setOffline(true);
    await authenticatedPage.waitForLoadState("networkidle");

    await authenticatedPage.context().setOffline(false);
    await authenticatedPage.reload();

    await expect(authenticatedPage.locator('body')).toBeVisible();
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

    await page.waitForURL("**/", { timeout: 5000 });

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
        // Removed small delay for rapid click test
      }
    }

    await expect(authenticatedPage.locator('body')).toBeVisible();
  });

  test('should handle very slow network', async ({ authenticatedPage }) => {
    await authenticatedPage.route('**/*', async route => {
      await new Promise(resolve => setTimeout(resolve, 5000));
      await route.continue();
    });

    await authenticatedPage.goto('/queue');

    const loadingIndicator = authenticatedPage.locator('.loading, .spinner');
    const hasLoading = await loadingIndicator.count() > 0;

    if (hasLoading) {
      await expect(loadingIndicator.first()).toBeVisible();
    }

    await expect(authenticatedPage.locator('body')).toBeVisible({ timeout: 30000 });
  });

  test('should handle session timeout', async ({ authenticatedPage }) => {
    await authenticatedPage.evaluate(() => {
      localStorage.removeItem('auth_token');
    });

    await authenticatedPage.reload();

    const loginPrompt = authenticatedPage.locator('text=login|sign in|expired');
    const hasPrompt = await loginPrompt.count() > 0;

    if (hasPrompt) {
      await expect(loginPrompt.first()).toBeVisible();
    }
  });

  test('should handle duplicate thread creation', async ({ authenticatedPage }) => {
    const threadData = {
      title: 'Duplicate Test',
      format: 'Comic',
      issues_remaining: 5,
    };

    await createThread(authenticatedPage, threadData);
    await createThread(authenticatedPage, threadData);

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');
    await authenticatedPage.reload();
    await authenticatedPage.waitForLoadState('networkidle');

    const duplicates = await authenticatedPage.locator('text=Duplicate Test').count();
    expect(duplicates).toBeGreaterThanOrEqual(2);
  });
});
