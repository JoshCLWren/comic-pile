import { test as base, type Page } from '@playwright/test';

type TestFixtures = {
  authenticatedPage: Page;
  testUser: {
    email: string;
    password: string;
    username: string;
    accessToken?: string;
  };
};

export const test = base.extend<TestFixtures>({
  authenticatedPage: async ({ page, request }, use) => {
    const timestamp = Date.now();
    const counter = Math.floor(Math.random() * 10000);
    const testUser = {
      username: `auth_test_${timestamp}_${counter}`,
      email: `auth_test_${timestamp}_${counter}@example.com`,
      password: 'TestPass123!',
    };

    await request.post('/api/auth/register', {
      data: testUser,
    });

    const loginResponse = await request.post('/api/auth/login', {
      data: {
        username: testUser.username,
        password: testUser.password,
      },
    });

    if (!loginResponse.ok()) {
      throw new Error(`Login failed: ${loginResponse.status()}`);
    }

    const loginData = await loginResponse.json();
    const accessToken = loginData.access_token;

    await page.addInitScript((token: string) => {
      localStorage.setItem('auth_token', token);
    }, accessToken);

    await page.goto('/');

    await use(page);

    await page.evaluate(() => localStorage.clear());

    try {
      await request.delete('/api/auth/logout', {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
        },
      });
    } catch (e) {
    }
  },

  testUser: async ({}, use) => {
    const timestamp = Date.now();
    const counter = Math.floor(Math.random() * 10000);
    const testUser = {
      username: `test_${timestamp}_${counter}`,
      email: `test_${timestamp}_${counter}@example.com`,
      password: 'TestPass123!',
    };
    await use(testUser);
  },
});

export { expect } from '@playwright/test';
