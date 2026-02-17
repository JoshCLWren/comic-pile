import { type Page, expect } from '@playwright/test';
import type { Violation } from '@axe-core/playwright';

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
  await page.goto('/register');
  await page.waitForLoadState('networkidle');
  await page.fill('input[name="username"]', user.username);
  await page.fill('input[name="email"]', user.email);
  await page.fill('input[name="password"]', user.password);
  await page.fill('input[name="confirmPassword"]', user.password);
  await page.click('button[type="submit"]');

  try {
    await page.waitForURL('**/', { timeout: 5000 });
  } catch (error) {
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

  await page.addInitScript((token: string) => {
    localStorage.setItem('auth_token', token);
  }, user.accessToken);

  return user.accessToken;
}

export async function createThread(
  page: Page,
  threadData: { title: string; format: string; issues_remaining: number }
): Promise<void> {
  const token = await page.evaluate(() => localStorage.getItem('auth_token'));

  let success = false;
  let attempts = 0;
  const maxAttempts = 7;

  while (!success && attempts < maxAttempts) {
    const response = await page.request.post('/api/threads/', {
      data: threadData,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      },
    });

    if (response.ok()) {
      success = true;
    } else if (response.status() === 429) {
      attempts++;
      const jitter = Math.random() * 1000;
      const backoffMs = Math.min(3000 * Math.pow(1.5, attempts - 1) + jitter, 20000);
      await new Promise(resolve => setTimeout(resolve, backoffMs));
    } else {
      throw new Error(`Failed to create thread: ${response.status()} ${response.statusText()}`);
    }
  }

  if (!success) {
    throw new Error(`Failed to create thread after ${maxAttempts} attempts`);
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
    .map((v) => `  - ${v.id}: ${v.description} (impact: ${v.impact})\n    Targets: ${v.nodes.map((n) => n.target.join(', ')).join('; ')}`)
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
    threadItem: '.thread-item',
    newThreadButton: 'button:has-text("Add Thread")',
    titleInput: 'label:has-text("Title") + input',
    formatInput: 'label:has-text("Format") + input',
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
