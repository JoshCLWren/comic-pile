import { test as base, type APIRequestContext, type Page, type TestInfo } from '@playwright/test';
import { getCollectionsEnabled } from './helpers';

type TestFixtures = {
  page: Page;
  allowExpectedBrowserFailures: {
    allow: () => void;
    isAllowed: () => boolean;
  };
  freshUserPage: Page;
  authenticatedPage: Page;
  authenticatedWithThreadsPage: Page;
  authenticatedWithLargeQueuePage: Page;
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

async function getCsrfToken(request: APIRequestContext, accessToken: string): Promise<string> {
  const response = await request.get('/api/auth/csrf', {
    headers: {
      'Authorization': `Bearer ${accessToken}`,
    },
    timeout: 10000,
  });

  if (!response.ok()) {
    throw new Error(`Failed to fetch CSRF token: ${response.status()} ${response.statusText()}`);
  }

  const data = await response.json() as { csrf_token?: string };
  if (!data.csrf_token) {
    throw new Error('CSRF bootstrap response did not include csrf_token');
  }

  return data.csrf_token;
}

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
  const csrfToken = await getCsrfToken(request, accessToken);
  const headers = {
    'Authorization': `Bearer ${accessToken}`,
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrfToken,
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
			headers,
			params: { page_size: 200 },
		});
		if (threadsResponse.ok()) {
			const response = await threadsResponse.json();
			const threads = response.threads ?? response;
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

function isExpectedAnonymousAuthProbe(message: string): boolean {
  return (
    message.includes('api/auth/me') || message.includes('api/auth/refresh')
  ) && (message.includes('401') || message.includes('due to access control checks'));
}

function isExpectedBrowserNoise(message: string): boolean {
  return (
    (message.includes('GPU stall due to ReadPixels') && message.includes('GL Driver Message'))
    || message.includes("Couldn't load preload assets")
    || message.includes('Failed to load resource: the server responded with a status of 401 (Unauthorized)')
    || (message.includes('Network Error') && message.includes('/assets/'))
    || message.includes('Failed to fetch collections: Error: Network error. Please check your connection and try again.')
    || message.includes('Failed to snooze thread: Network error. Please check your connection and try again.')
    || (message.includes('XMLHttpRequest cannot load') && message.includes('due to access control checks.'))
    || message.includes('TypeError: Importing a module script failed.')
    || message.includes('WARNING: Too many active WebGL contexts. Oldest context will be lost.')
  );
}

async function assertBrowserHealth(
  testInfo: TestInfo,
  consoleMessages: string[],
  pageErrors: string[],
  failedRequests: string[],
  allowExpectedBrowserFailures: boolean,
): Promise<void> {
  const unexpectedConsoleMessages = consoleMessages.filter(
    (message) => !isExpectedAnonymousAuthProbe(message) && !isExpectedBrowserNoise(message),
  );
  const unexpectedPageErrors = pageErrors.filter(
    (message) => !isExpectedAnonymousAuthProbe(message) && !isExpectedBrowserNoise(message),
  );
  const failures = [
    ...(allowExpectedBrowserFailures
      ? []
      : unexpectedConsoleMessages.map((message) => `console: ${message}`)),
    ...unexpectedPageErrors.map((message) => `pageerror: ${message}`),
    ...(allowExpectedBrowserFailures
      ? []
      : failedRequests.map((message) => `requestfailed: ${message}`)),
  ];

  if (failures.length === 0) {
    return;
  }

  await testInfo.attach('browser-health-failures', {
    body: failures.join('\n'),
    contentType: 'text/plain',
  });
  throw new Error(`Browser health checks failed:\n${failures.join('\n')}`);
}

export const test = base.extend<TestFixtures>({
  allowExpectedBrowserFailures: async ({}, use) => {
    let expectedBrowserFailures = false;
    await use({
      allow: () => {
        expectedBrowserFailures = true;
      },
      isAllowed: () => expectedBrowserFailures,
    });
  },

  page: async ({ page, allowExpectedBrowserFailures }, use, testInfo) => {
    const consoleMessages: string[] = [];
    const pageErrors: string[] = [];
    const failedRequests: string[] = [];

    page.on('console', (message) => {
      if (message.type() === 'error' || message.type() === 'warning') {
        consoleMessages.push(`${message.type()}: ${message.text()} @ ${message.location().url}`);
      }
    });
    page.on('pageerror', (error) => {
      pageErrors.push(error.stack ?? error.message);
    });
    page.on('requestfailed', (request) => {
      const errorText = request.failure()?.errorText ?? '';
      if (
        errorText === 'net::ERR_ABORTED'
        || errorText === 'Load request cancelled'
        || request.url().includes('fonts.googleapis.com')
        || request.url().includes('fonts.gstatic.com')
      ) {
        return;
      }
      failedRequests.push(`${request.method()} ${request.url()} — ${errorText || 'unknown error'}`);
    });

    await use(page);
    await assertBrowserHealth(
      testInfo,
      consoleMessages,
      pageErrors,
      failedRequests,
      allowExpectedBrowserFailures.isAllowed(),
    );
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

     if (await getCollectionsEnabled(page)) {
       await page.locator('[aria-label="Filter by collection"]').waitFor({ state: 'visible' });
     }

     await page.locator('#root').waitFor({ state: 'visible' });

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

  authenticatedWithLargeQueuePage: async ({ page, request }, use) => {
    const counter = ++fixtureUserCounter;
    const timestamp = Date.now();
    const workerId = process.pid ?? 0;
    const testUser = {
      username: `auth_large_${timestamp}_${counter}_${workerId}`,
      email: `auth_large_${timestamp}_${counter}_${workerId}@example.com`,
      password: 'TestPass123!',
    };

    const { accessToken } = await registerWithRetry(request, testUser);
    await createThreadsForUser(request, accessToken, 60);

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
