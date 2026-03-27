import { test as base, type APIRequestContext, type Page } from '@playwright/test';

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

let fixtureUserCounter = 0;

async function registerWithRetry(
  request: APIRequestContext,
  testUser: TestUser,
  maxRetries = 3,
): Promise<{ accessToken: string }> {
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      const registerResponse = await request.post('/api/auth/register', {
        data: testUser,
        timeout: 10000,
      });

      if (!registerResponse.ok()) {
        const bodyText = await registerResponse.text();

        if (registerResponse.status() === 400 && bodyText.includes('Username already registered')) {
          const loginResponse = await request.post('/api/auth/login', {
            data: {
              username: testUser.username,
              password: testUser.password,
            },
            timeout: 10000,
          });

          if (loginResponse.ok()) {
            const loginData = await loginResponse.json();
            return { accessToken: loginData.access_token };
          }
        }

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

async function createThreadsForUser(
  request: APIRequestContext,
  accessToken: string,
  threadCount: number,
): Promise<void> {
  const headers = {
    'Authorization': `Bearer ${accessToken}`,
    'Content-Type': 'application/json',
  };

  for (let i = 0; i < threadCount; i++) {
    let success = false;
    let attempts = 0;
    const maxAttempts = 7;

    while (!success && attempts < maxAttempts) {
      const response = await request.post('/api/threads/', {
        headers,
        data: {
          title: `Test Thread ${i + 1}`,
          format: 'issue',
          issues_remaining: 10,
          total_issues: 10,
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
  let threadIds: number[] = [];
  while (attempts < 10) {
    const threadsResponse = await request.get('/api/threads/', {
      headers
    });
    if (threadsResponse.ok()) {
      const threads = await threadsResponse.json();
      if (threads.length >= threadCount) {
        threadIds = threads.slice(0, threadCount).map((t: { id: number }) => t.id);
        break;
      }
    }
    await new Promise(resolve => setTimeout(resolve, 500));
    attempts++;
  }

  if (threadIds.length === 0) {
    throw new Error('Threads not visible after creation');
  }

  for (const threadId of threadIds) {
    let success = false;
    let issueAttempts = 0;
    const maxIssueAttempts = 7;

    while (!success && issueAttempts < maxIssueAttempts) {
      const issueResponse = await request.post(`/api/v1/threads/${threadId}/issues`, {
        headers,
        data: {
          issue_range: '1-10',
        },
        timeout: 10000,
      });

      if (issueResponse.ok()) {
        success = true;
      } else if (issueResponse.status() === 429) {
        issueAttempts++;
        const jitter = Math.random() * 1000;
        const backoffMs = Math.min(3000 * Math.pow(1.5, issueAttempts - 1) + jitter, 20000);
        await new Promise(resolve => setTimeout(resolve, backoffMs));
      } else {
        throw new Error(`Failed to create issues for thread ${threadId}: ${issueResponse.status()} ${issueResponse.statusText()}`);
      }
    }

    if (!success) {
      throw new Error(`Failed to create issues for thread ${threadId} after ${maxIssueAttempts} attempts`);
    }
  }
}

export const test = base.extend<TestFixtures>({
  page: async ({ page }, use) => {
    await use(page);
  },

  freshUserPage: async ({ page, request }, use) => {
    const counter = ++fixtureUserCounter;
    const timestamp = Date.now();
    const workerId = process.pid ?? 0;
    const testUser = {
      username: `auth_fresh_${timestamp}_${counter}_${workerId}`,
      email: `auth_fresh_${timestamp}_${counter}_${workerId}@example.com`,
      password: 'TestPass123!',
    };

    const { accessToken } = await registerWithRetry(request, testUser);

    await page.addInitScript((token: string) => {
      localStorage.setItem('auth_token', token);
      (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN = token;
    }, accessToken);

    await page.goto('/', { waitUntil: 'domcontentloaded' });

    await use(page);

    await page.evaluate(() => {
      localStorage.clear();
      delete (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN;
    });

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
     // Clear any existing auth state first for clean test isolation
     await page.addInitScript(() => localStorage.clear());

     const counter = ++fixtureUserCounter;
     const timestamp = Date.now();
     const workerId = process.pid ?? 0;
     const testUser = {
       username: `auth_${timestamp}_${counter}_${workerId}`,
       email: `auth_${timestamp}_${counter}_${workerId}@example.com`,
       password: 'TestPass123!',
     };

     const { accessToken } = await registerWithRetry(request, testUser);

     await page.addInitScript((token: string) => {
       localStorage.setItem('auth_token', token);
       (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN = token;
     }, accessToken);

     // Navigate to home page
     // Use 'domcontentloaded' instead of 'load' to avoid timeout in SPAs
     await page.goto('/', { waitUntil: 'domcontentloaded' });

     // Wait for auth state to stabilize:
     // 1. Wait for "Checking authentication..." to disappear
     await page.waitForSelector('text=Checking authentication...', { state: 'detached', timeout: 10000 }).catch(() => {
       // Element may not exist if auth is fast, that's OK
     });

     // 2. Wait for "Loading..." states to disappear
     await page.waitForSelector('text=Loading...', { state: 'detached', timeout: 10000 }).catch(() => {
       // Element may not exist, that's OK
     });

  // 3. Wait for collections to finish loading (Loading collections... text should disappear)
  // The CollectionToolbar component shows "Loading collections..." while fetching
  await page.waitForSelector('text=Loading collections...', { state: 'detached', timeout: 15000 }).catch(() => {});
  // 4. Wait for the collection toolbar dropdown to be visible
  await page.waitForSelector('[aria-label="Filter by collection"]', { state: 'visible', timeout: 15000 });

  // 6. Wait for the roll page to be ready (die button is always present on home route)
     await page.waitForSelector('[aria-label="Roll the dice"]', { state: 'visible', timeout: 10000 }).catch(() => {
       // May not exist if no session or in empty state — check for roll pool instead
       return page.waitForSelector('[data-roll-pool]', { state: 'attached', timeout: 5000 }).catch(() => {});
     });

     await use(page);

    // Cleanup: clear localStorage and attempt logout
    await page.evaluate(() => {
      localStorage.clear();
      delete (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN;
    });
    try {
      await request.post('/api/auth/logout', {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
        },
      });
    } catch {
      // Ignore logout errors during cleanup
    }
  },

  authenticatedWithThreadsPage: async ({ page, request }, use) => {
    const counter = ++fixtureUserCounter;
    const timestamp = Date.now();
    const workerId = process.pid ?? 0;
    const testUser = {
      username: `auth_threads_${timestamp}_${counter}_${workerId}`,
      email: `auth_threads_${timestamp}_${counter}_${workerId}@example.com`,
      password: 'TestPass123!',
    };

    const { accessToken } = await registerWithRetry(request, testUser);
    await createThreadsForUser(request, accessToken, 3);

    await page.addInitScript((token: string) => {
      localStorage.setItem('auth_token', token);
      (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN = token;
    }, accessToken);

    // Use 'domcontentloaded' instead of 'load' to avoid timeout in SPAs
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    await use(page);

    await page.evaluate(() => {
      localStorage.clear();
      delete (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN;
    });
  },

  testUser: async ({}, use) => {
    const counter = ++fixtureUserCounter;
    const timestamp = Date.now();
    const workerId = process.pid ?? 0;
    const testUser = {
      username: `test_${timestamp}_${counter}_${workerId}`,
      email: `test_${timestamp}_${counter}_${workerId}@example.com`,
      password: 'TestPass123!',
    };
    await use(testUser);
  },
});

export { expect } from '@playwright/test';
