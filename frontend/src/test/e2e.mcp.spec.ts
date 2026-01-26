import { test, expect } from '@playwright/test';

test.describe('MCP end-to-end flow', () => {
  test('register, login, add threads, roll, rate, snooze, navigate', async ({ page }) => {
    // Generate unique credentials for each test run
    const fakeUser = {
      email: `user_${Date.now()}_${Math.random().toString(36).substring(7)}@example.com`,
      password: 'Testpass123!'
    };

    // Register new user
    await page.goto('/register');
    await page.fill('input[name="email"]', fakeUser.email);
    await page.fill('input[name="password"]', fakeUser.password);
    await page.fill('input[name="confirmPassword"]', fakeUser.password);
    await page.click('button[type="submit"]');
    await expect(page.locator('text=Registration successful')).toBeVisible();

    // Login with new user (should auto-login, but double-check)
    await page.goto('/login');
    await page.fill('input[name="email"]', fakeUser.email);
    await page.fill('input[name="password"]', fakeUser.password);
    await page.click('button[type="submit"]');
    await expect(page.locator('text=Dashboard')).toBeVisible();

    // Add two new threads
    await page.goto('/threads');
    await page.click('button', { hasText: /new thread/i });
    await page.fill('input[name="title"]', 'Saga');
    await page.fill('input[name="format"]', 'Comic');
    await page.click('button[type="submit"]');
    await expect(page.locator('text=Saga')).toBeVisible();
    await page.click('button', { hasText: /new thread/i });
    await page.fill('input[name="title"]', 'X-Men');
    await page.fill('input[name="format"]', 'Comic');
    await page.click('button[type="submit"]');
    await expect(page.locator('text=X-Men')).toBeVisible();

    // Roll
    await page.goto('/roll');
    await expect(page.locator('text=Pile Roller')).toBeVisible();
    await page.click('button[aria-label="roll"]');
    await expect(page.locator('text=Rolled')).toBeVisible();

    // Rate
    await page.click('button[aria-label="rate"]');
    await page.click('button[aria-label="4-stars"]');
    await expect(page.locator('text=Rating saved')).toBeVisible();

    // Snooze/Skip
    await page.click('button[aria-label="snooze"]');
    await expect(page.locator('text=Thread snoozed')).toBeVisible();

    // Navigate through major pages
    await page.goto('/dashboard');
    await expect(page.locator('text=Your Threads')).toBeVisible();
    await page.goto('/analytics');
    await expect(page.locator('text=Reading Analytics')).toBeVisible();
    await page.goto('/history');
    await expect(page.locator('text=History')).toBeVisible();
  });
});
