import { type Page } from '@playwright/test';

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
  return {
    username: `testuser_${timestamp}_${counter}`,
    email: `testuser_${timestamp}_${counter}@example.com`,
    password: 'TestPass123!',
  };
}

export async function registerUser(page: Page, user: TestUser): Promise<void> {
  await page.goto('/register');
  await page.fill('input[name="username"]', user.username);
  await page.fill('input[name="email"]', user.email);
  await page.fill('input[name="password"]', user.password);
  await page.fill('input[name="confirmPassword"]', user.password);
  await page.click('button[type="submit"]');

  await page.waitForURL('**/', { timeout: 5000 });
}

export async function loginUser(page: Page, user: TestUser): Promise<string> {
  const response = await page.request.post('/api/auth/login', {
    data: {
      username: user.email,
      password: user.password,
    },
  });

  if (!response.ok()) {
    throw new Error(`Login failed: ${response.status()}`);
  }

  const data = await response.json();
  user.accessToken = data.access_token;

  await page.addInitScript((token: string) => {
    localStorage.setItem('auth_token', token);
  }, user.accessToken);

  return user.accessToken;
}

export async function createThread(
  page: Page,
  threadData: { title: string; format: string; issues_remaining: number }
): Promise<void> {
  const response = await page.request.post('/api/threads/', {
    data: threadData,
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok()) {
    throw new Error(`Failed to create thread: ${response.status()}`);
  }
}

export async function setupAuthenticatedPage(
  page: Page,
  user?: TestUser
): Promise<TestUser> {
  const testUser = user || generateTestUser();

  await registerUser(page, testUser);
  await loginUser(page, testUser);

  await page.goto('/');
  await page.waitForLoadState('networkidle');

  return testUser;
}

export async function cleanupTestUser(page: Page, user: TestUser): Promise<void> {
  await page.evaluate(() => {
    localStorage.clear();
  });
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
    threadItem: '.thread-item',
    newThreadButton: 'button:has-text("new thread")',
    titleInput: 'input[name="title"]',
    formatInput: 'input[name="format"]',
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
    submitButton: '#submit-btn',
    snoozeButton: 'button[aria-label="snooze"]',
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
} as const;
