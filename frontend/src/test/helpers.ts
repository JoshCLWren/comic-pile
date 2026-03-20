import { type Page, expect } from '@playwright/test';

type Violation = {
  id: string;
  description: string;
  impact?: string | null;
  nodes: Array<{ target: unknown[] }>;
};

type WindowWithAccessToken = Window & { __COMIC_PILE_ACCESS_TOKEN?: string };

type TestUser = {
  email: string;
  password: string;
  username: string;
  accessToken?: string;
};

let userIdCounter = 0;

export function generateTestUser(): TestUser {
  const timestamp = Date.now();
  const counter = ++userIdCounter;
  const workerId = process.pid || 0;
  return {
    username: `testuser_${timestamp}_${counter}_${workerId}`,
    email: `testuser_${timestamp}_${counter}_${workerId}@example.com`,
    password: 'TestPass123!',
  };
}

export async function registerUser(page: Page, user: TestUser): Promise<void> {
  await page.goto('/register', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('input[name="username"]', { state: 'visible', timeout: 10000 });
  await page.fill('input[name="username"]', user.username);
  await page.fill('input[name="email"]', user.email);
  await page.fill('input[name="password"]', user.password);
  await page.fill('input[name="confirmPassword"]', user.password);
  await page.click('button[type="submit"]');

  try {
    await page.waitForURL('**/', { timeout: 5000 });
  } catch {
    const url = page.url();
    const bodyText = await page.locator('body').textContent();
    throw new Error(
      `Registration failed for user ${user.username}. URL: ${url}. Page content: ${bodyText?.slice(0, 200)}...`
    );
  }
}

export async function loginUser(page: Page, user: TestUser): Promise<string> {
  const response = await page.request.post('/api/auth/login', {
    data: {
      username: user.username,
      password: user.password,
    },
  });

  expect(response.ok()).toBeTruthy();
  const data = await response.json();
  user.accessToken = data.access_token;

  await page.evaluate((token: string) => {
    localStorage.setItem('auth_token', token);
    (window as WindowWithAccessToken).__COMIC_PILE_ACCESS_TOKEN = token;
  }, user.accessToken);

  await page.addInitScript((token: string) => {
    localStorage.setItem('auth_token', token);
    (window as WindowWithAccessToken).__COMIC_PILE_ACCESS_TOKEN = token;
  }, user.accessToken);

  return user.accessToken;
}

export async function getAuthToken(page: Page): Promise<string | null> {
  return await page.evaluate(() => {
    const win = window as WindowWithAccessToken;
    return localStorage.getItem('auth_token') ?? win.__COMIC_PILE_ACCESS_TOKEN ?? null;
  });
}

export async function createThread(
  page: Page,
  threadData: { title: string; format: string; issues_remaining: number; total_issues?: number; issue_range?: string }
): Promise<{ id: number }> {
  const token = await getAuthToken(page);

  const dataWithoutTotal = {
    title: threadData.title,
    format: threadData.format,
    issues_remaining: threadData.issues_remaining,
  };

  let success = false;
  let attempts = 0;
  const maxAttempts = 7;
  let threadId: number | null = null;

  while (!success && attempts < maxAttempts) {
    const response = await page.request.post('/api/threads/', {
      data: dataWithoutTotal,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      },
    });

    if (response.ok()) {
      success = true;
      const thread = await response.json();
      threadId = thread.id;

      // If total_issues or issue_range is specified, create the issues
      if ((threadData.total_issues || threadData.issue_range) && threadId) {
        const issueRange = threadData.issue_range || `1-${threadData.total_issues}`;
        
        let issueSuccess = false;
        let issueAttempts = 0;
        while (!issueSuccess && issueAttempts < 3) {
          const issuesResponse = await page.request.post(`/api/v1/threads/${threadId}/issues`, {
            data: { issue_range: issueRange },
            headers: {
              'Content-Type': 'application/json',
              ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
            },
          });

          if (issuesResponse.ok()) {
            issueSuccess = true;
            
            // If issues_remaining is 0, mark all issues as read
            if (threadData.issues_remaining === 0 && threadId) {
              const issuesListResponse = await page.request.get(`/api/v1/threads/${threadId}/issues`, {
                headers: {
                  ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
                },
              });
              
              if (issuesListResponse.ok()) {
                const issuesData = await issuesListResponse.json();
                for (const issue of issuesData.issues) {
                  await page.request.post(`/api/v1/issues/${issue.id}:markRead`, {
                    headers: {
                      ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
                    },
                  });
                }
              }
            }
          } else if (issuesResponse.status() === 429) {
            issueAttempts++;
            await new Promise(resolve => setTimeout(resolve, 1000));
          } else {
            const errorText = await issuesResponse.text();
            throw new Error(`Failed to create issues: ${issuesResponse.status()} ${errorText}`);
          }
        }
      }
    } else if (response.status() === 429) {
      attempts++;
      const jitter = Math.random() * 1000;
      const backoffMs = Math.min(3000 * Math.pow(1.5, attempts - 1) + jitter, 20000);
      await new Promise(resolve => setTimeout(resolve, backoffMs));
    } else {
      throw new Error(`Failed to create thread: ${response.status()} ${response.statusText}`);
    }
  }

  if (!success) {
    throw new Error(`Failed to create thread after ${maxAttempts} attempts`);
  }

  if (!threadId) {
    throw new Error('Thread creation succeeded without returning an id');
  }

  return { id: threadId };
}

export async function setupAuthenticatedPage(
  page: Page,
  user?: TestUser
): Promise<TestUser> {
  const testUser = user || generateTestUser();

  await registerUser(page, testUser);
  await loginUser(page, testUser);

  // Use 'domcontentloaded' instead of 'load' to avoid timeout in SPAs
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('[aria-label="Roll pool collection"]', { state: 'visible', timeout: 10000 }).catch(() => {});

  return testUser;
}

export async function cleanupTestUser(page: Page, _user: TestUser): Promise<void> {
  await page.evaluate(() => {
    localStorage.clear();
    delete (window as WindowWithAccessToken).__COMIC_PILE_ACCESS_TOKEN;
  });
}

export async function setRangeInput(page: Page, selector: string, value: string): Promise<void> {
  await page.evaluate(
    ({ selector, value }) => {
      const input = document.querySelector(selector) as HTMLInputElement;
      if (input) {
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }
    },
    { selector, value }
  );
}

export function formatA11yViolations(violations: Violation[]): string {
  if (violations.length === 0) return '';
  return violations
    .map((v) => `  - ${v.id}: ${v.description} (impact: ${v.impact})\n    Targets: ${v.nodes.map((n) => n.target.map(String).join(', ')).join('; ')}`)
    .join('\n');
}

export const SELECTORS = {
  auth: {
    usernameInput: 'input[name="username"]',
    emailInput: 'input[name="email"]',
    passwordInput: 'input[name="password"]',
    confirmPasswordInput: 'input[name="confirmPassword"]',
    submitButton: 'button[type="submit"]',
  },
  threadList: {
    container: '#queue-container',
    threadItem: '[data-testid=\"queue-thread-item\"]',
    newThreadButton: 'button:has-text("Add Thread")',
    titleInput: 'label:has-text("Title") + input',
    formatSelect: 'label:has-text("Format") + select',
    issuesRemainingInput: 'label:has-text("Issues Remaining") + input, label:has-text("Issues") + input',
  },
  roll: {
    dieSelector: '#die-selector',
    mainDie: '#main-die-3d',
    rollButton: 'button[aria-label="roll"]',
    tapInstruction: '#tap-instruction',
    headerDieLabel: '#header-die-label',
  },
  rate: {
    ratingInput: '#rating-input',
    submitButton: 'button:has-text("Save & Continue")',
    snoozeButton: 'button:has-text("Snooze")',
  },
  thread: {
    title: '#thread-info h2',
  },
  navigation: {
    homeLink: 'a[href="/"]',
    queueLink: 'a[href="/queue"]',
    analyticsLink: 'a[href="/analytics"]',
    historyLink: 'a[href="/history"]',
  },
  dashboard: {
    threadsContainer: '.your-threads',
  },
  analytics: {
    chartContainer: '.chart-container',
  },
  history: {
    sessionsList: '#sessions-list',
  },
  issues: {
    issueList: '.issue-list',
    issueItem: '.issue-item',
    issueNumber: '.issue-number',
    nextBadge: '.next-badge',
    progressBar: '.progress-bar',
    progressFill: '.progress-fill',
    progressText: '.progress-text',
    filter: 'select[aria-label="Filter issues"]',
    issueIcon: '.issue-icon',
    readDate: '.read-date',
  },
  threadCreate: {
    issuesInput: 'input[placeholder*="0-25"]',
    issuePreview: 'p:has-text("Will create")',
  },
  rollResult: {
    issueNumber: '.reading-progress', // Use the reading progress container which contains issue info
    readingProgress: '.reading-progress',
    issueOf: 'span:has-text("of")',
    completedLabel: 'span:has-text("Completed")',
    inProgressLabel: 'span:has-text("In Progress")',
  },
} as const;
