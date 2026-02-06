import { test as base, type Page } from '@playwright/test';

type TestFixtures = {
  page: Page;
  authenticatedPage: Page;
  testUser: {
    email: string;
    password: string;
    username: string;
    accessToken?: string;
  };
};

async function createAutoWaitingPage(page: Page): Promise<Page> {
  const originalGoto = page.goto.bind(page);
  page.goto = async (url: string, options?: any) => {
    const result = await originalGoto(url, options);
    await page.waitForLoadState('networkidle');
    return result;
  };
  return page;
}

async function registerWithRetry(request: any, testUser: any, maxRetries = 3): Promise<{ accessToken: string }> {
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      const registerResponse = await request.post('/api/auth/register', {
        data: testUser,
        timeout: 10000,
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
        timeout: 10000,
      });

      if (!loginResponse.ok()) {
        const bodyText = await loginResponse.text();
        throw new Error(
          `Fixture login failed for ${testUser.username}: ${loginResponse.status()} ${loginResponse.statusText()}. Response: ${bodyText}`
        );
      }

      const loginData = await loginResponse.json();
      return { accessToken: loginData.access_token };
    } catch (e) {
      if (attempt === maxRetries - 1) {
        throw e;
      }
      await new Promise(resolve => setTimeout(resolve, 500 * (attempt + 1)));
    }
  }
  throw new Error('Registration retry failed');
}

export const test = base.extend<TestFixtures>({
  page: async ({ page }, use) => {
    await createAutoWaitingPage(page);
    await use(page);
  },

  authenticatedPage: async ({ page, request }, use) => {
    const timestamp = Date.now();
    const counter = Math.floor(Math.random() * 10000);
    const testUser = {
      username: `auth_test_${timestamp}_${counter}`,
      email: `auth_test_${timestamp}_${counter}@example.com`,
      password: 'TestPass123!',
    };

    const { accessToken } = await registerWithRetry(request, testUser);

    await page.addInitScript((token: string) => {
      localStorage.setItem('auth_token', token);
    }, accessToken);

    const originalGoto = page.goto.bind(page);
    page.goto = async (url: string, options?: any) => {
      const result = await originalGoto(url, options);
      await page.waitForLoadState('networkidle');
      return result;
    };

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    await use(page);

    await page.evaluate(() => localStorage.clear());

    try {
      await request.post('/api/auth/logout', {
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
