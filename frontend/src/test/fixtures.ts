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

    const registerResponse = await request.post('/api/auth/register', {
      data: testUser,
    });

    if (!registerResponse.ok()) {
      const bodyText = await registerResponse.text();
      throw new Error(
        `Fixture registration failed for ${testUser.username}: ${registerResponse.status()} ${registerResponse.statusText()}. Response: ${bodyText}`
      );
    }

    const loginResponse = await request.post('/api/auth/login', {
      data: {
        username: testUser.username,
        password: testUser.password,
      },
    });

    if (!loginResponse.ok()) {
      const bodyText = await loginResponse.text();
      throw new Error(
        `Fixture login failed for ${testUser.username}: ${loginResponse.status()} ${loginResponse.statusText()}. Response: ${bodyText}`
      );
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
