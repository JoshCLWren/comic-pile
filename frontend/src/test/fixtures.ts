import { test as base, type Page, type Expect } from '@playwright/test';

type TestFixtures = {
  authenticatedPage: Page;
  testUser: {
    email: string;
    password: string;
    username: string;
  };
};

export const test = base.extend<TestFixtures>({
  authenticatedPage: async ({ page }, use) => {
    const timestamp = Date.now();
    const counter = Math.floor(Math.random() * 10000);
    const testUser = {
      email: `auth_test_${timestamp}_${counter}@example.com`,
      password: 'TestPass123!',
      username: `auth_test_${timestamp}_${counter}`,
    };

    await page.goto('/register');
    await page.fill('input[name="username"]', testUser.username);
    await page.fill('input[name="email"]', testUser.email);
    await page.fill('input[name="password"]', testUser.password);
    await page.fill('input[name="confirmPassword"]', testUser.password);
    await page.click('button[type="submit"]');
    await page.waitForURL('**/', { timeout: 5000 });

    await use(page);

    await page.evaluate(() => localStorage.clear());
  },

  testUser: async ({}, use) => {
    const timestamp = Date.now();
    const counter = Math.floor(Math.random() * 10000);
    const testUser = {
      email: `test_${timestamp}_${counter}@example.com`,
      password: 'TestPass123!',
      username: `test_${timestamp}_${counter}`,
    };
    await use(testUser);
  },
});

export { expect } from '@playwright/test';
