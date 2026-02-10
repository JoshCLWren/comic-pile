import { test as base, type Page, type Request, type GotoOptions } from '@playwright/test';

type TestFixtures = {
  page: Page;
  freshUserPage: Page;
  authenticatedPage: Page;
  authenticatedWithThreadsPage: Page;
  testUser: {
    email: string;
    password: string;
    username: string;
    accessToken?: string;
  };
};

type TestUser = {
  username: string;
  email: string;
  password: string;
};

async function registerWithRetry(request: Request, testUser: TestUser, maxRetries = 3): Promise<{ accessToken: string }> {
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      const registerResponse = await request.post('/api/auth/register', {
        data: testUser,
        timeout: 10000,
      });

      if (!registerResponse.ok()) {
        const bodyText = await registerResponse.text();
        const error = new Error(
          `Fixture registration failed for ${testUser.username}: ${registerResponse.status()} ${registerResponse.statusText()}. Response: ${bodyText}`
        );
        console.error(error.message);
        throw error;
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
        const error = new Error(
          `Fixture login failed for ${testUser.username}: ${loginResponse.status()} ${loginResponse.statusText()}. Response: ${bodyText}`
        );
        console.error(error.message);
        throw error;
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

async function createThreadsForUser(request: Request, accessToken: string, threadCount: number): Promise<void> {
  for (let i = 0; i < threadCount; i++) {
    let success = false;
    let attempts = 0;
    const maxAttempts = 7;

    while (!success && attempts < maxAttempts) {
      const response = await request.post('/api/threads/', {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'application/json',
        },
        data: {
          title: `Test Thread ${i + 1}`,
          format: 'issue',
          issues_remaining: 10,
        },
        timeout: 10000,
      });

      if (response.ok()) {
        success = true;
      } else if (response.status() === 429) {
        attempts++;
        const jitter = Math.random() * 1000;
        const backoffMs = Math.min(3000 * Math.pow(1.5, attempts - 1) + jitter, 20000);
        await new Promise(resolve => setTimeout(resolve, backoffMs));
      } else {
        throw new Error(`Failed to create thread ${i + 1}: ${response.status()} ${response.statusText()}`);
      }
    }

    if (!success) {
      throw new Error(`Failed to create thread ${i + 1} after ${maxAttempts} attempts`);
    }
  }

  let attempts = 0;
  while (attempts < 10) {
    const threadsResponse = await request.get('/api/threads/', {
      headers: { 'Authorization': `Bearer ${accessToken}` }
    });
    if (threadsResponse.ok()) {
      const threads = await threadsResponse.json();
      if (threads.length >= threadCount) {
        return;
      }
    }
    await new Promise(resolve => setTimeout(resolve, 500));
    attempts++;
  }
  throw new Error('Threads not visible after creation');
}

export const test = base.extend<TestFixtures>({
  page: async ({ page }, use) => {
    await use(page);
  },

  freshUserPage: async ({ page, request }, use) => {
    const timestamp = Date.now();
    const counter = Math.floor(Math.random() * 10000);
    const workerId = process.pid;
    const testUser = {
      username: `auth_fresh_${timestamp}_${counter}_${workerId}`,
      email: `auth_fresh_${timestamp}_${counter}_${workerId}@example.com`,
      password: 'TestPass123!',
    };

    const { accessToken } = await registerWithRetry(request, testUser);

    await page.addInitScript((token: string) => {
      localStorage.setItem('auth_token', token);
    }, accessToken);

    await page.goto('/');

    await use(page);

    await page.evaluate(() => localStorage.clear());

    try {
      await request.post('/api/auth/logout', {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
        },
      });
    } catch (e) {
      console.warn('Failed to logout fresh user:', e);
    }
  },

  authenticatedPage: async ({ page, request }, use) => {
    const timestamp = Date.now();
    const counter = Math.floor(Math.random() * 10000);
    const workerId = process.pid;
    const testUser = {
      username: `auth_${timestamp}_${counter}_${workerId}`,
      email: `auth_${timestamp}_${counter}_${workerId}@example.com`,
      password: 'TestPass123!',
    };

    const { accessToken } = await registerWithRetry(request, testUser);

    await page.addInitScript((token: string) => {
      localStorage.setItem('auth_token', token);
    }, accessToken);

    await page.goto('/');

    await use(page);

    await page.evaluate(() => localStorage.clear());
  },

  authenticatedWithThreadsPage: async ({ page, request }, use) => {
    const timestamp = Date.now();
    const counter = Math.floor(Math.random() * 10000);
    const workerId = process.pid;
    const testUser = {
      username: `auth_threads_${timestamp}_${counter}_${workerId}`,
      email: `auth_threads_${timestamp}_${counter}_${workerId}@example.com`,
      password: 'TestPass123!',
    };

    const { accessToken } = await registerWithRetry(request, testUser);
    await createThreadsForUser(request, accessToken, 3);

    await page.addInitScript((token: string) => {
      localStorage.setItem('auth_token', token);
    }, accessToken);

    await page.goto('/');

    await use(page);

    await page.evaluate(() => localStorage.clear());
  },

  testUser: async ({}, use) => {
    const timestamp = Date.now();
    const counter = Math.floor(Math.random() * 10000);
    const workerId = process.pid;
    const testUser = {
      username: `test_${timestamp}_${counter}_${workerId}`,
      email: `test_${timestamp}_${counter}_${workerId}@example.com`,
      password: 'TestPass123!',
    };
    await use(testUser);
  },
});

export { expect } from '@playwright/test';
