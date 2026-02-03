import { test as base, type Page, type APIRequestContext, type Expect } from '@playwright/test';

type TestFixtures = {
  authenticatedPage: Page;
  testUser: {
    email: string;
    password: string;
    username: string;
    accessToken?: string;
  };
  request: APIRequestContext;
};

let sharedUser: { email: string; password: string; username: string; accessToken?: string } | null = null;
let userSetupLock = false;

async function getOrCreateSharedUser(request: APIRequestContext) {
  if (sharedUser) {
    return sharedUser;
  }

  while (userSetupLock) {
    await new Promise(resolve => setTimeout(resolve, 100));
  }

  if (sharedUser) {
    return sharedUser;
  }

  userSetupLock = true;
  try {
    const timestamp = Date.now();
    const counter = Math.floor(Math.random() * 10000);
    const testUser = {
      username: `shared_test_${timestamp}_${counter}`,
      email: `shared_test_${timestamp}_${counter}@example.com`,
      password: 'TestPass123!',
    };

    const registerResponse = await request.post('/api/auth/register', {
      data: testUser,
    });

    if (!registerResponse.ok()) {
      throw new Error(`Shared user registration failed: ${registerResponse.status()}`);
    }

    const loginResponse = await request.post('/api/auth/login', {
      data: {
        username: testUser.username,
        password: testUser.password,
      },
    });

    if (!loginResponse.ok()) {
      throw new Error(`Shared user login failed: ${loginResponse.status()}`);
    }

    const loginData = await loginResponse.json();
    testUser.accessToken = loginData.access_token;
    sharedUser = testUser;

    return sharedUser;
  } finally {
    userSetupLock = false;
  }
}

export const test = base.extend<TestFixtures>({
  authenticatedPage: async ({ page, request }, use) => {
    const testUser = await getOrCreateSharedUser(request);

    await page.addInitScript((token: string) => {
      localStorage.setItem('auth_token', token);
    }, testUser.accessToken!);

    await page.goto('/');

    await use(page);

    await page.evaluate(() => localStorage.clear());
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
