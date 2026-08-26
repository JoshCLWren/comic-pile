import { test, expect } from './fixtures';
import type { APIRequestContext, Page } from '@playwright/test';
import {
  createThread,
  generateTestUser,
  loginUser,
  registerUser,
} from './helpers';

type TestUser = {
  email: string;
  password: string;
  username: string;
  accessToken?: string;
};

type IssueInfo = { id: number; position: number };

const DESKTOP_VIEWPORT = { width: 1920, height: 1080 };
const MOBILE_VIEWPORT = { width: 390, height: 844 };

/**
 * Region names that the Open Design dogfood audit saw exposed multiple times
 * in the post-roll view (issue #1883). Each must resolve to exactly one
 * accessible instance per viewport.
 */
const REGION_NAMES = [
  'Crossovers',
  'Your rating',
  'Continuity Correction',
  'Dependency & Continuity Edges',
] as const;

async function getCsrfToken(request: APIRequestContext, token: string): Promise<string> {
  const response = await request.get('/api/auth/csrf', {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok()) {
    throw new Error(`Failed to fetch CSRF token: ${response.status()}`);
  }
  const data = (await response.json()) as { csrf_token?: string };
  if (!data.csrf_token) {
    throw new Error('CSRF bootstrap response did not include csrf_token');
  }
  return data.csrf_token;
}

async function apiPost(
  page: Page,
  user: TestUser,
  path: string,
  data: unknown,
): Promise<Record<string, unknown>> {
  const csrfToken = await getCsrfToken(page.request, user.accessToken ?? '');
  const response = await page.request.post(path, {
    data,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${user.accessToken ?? ''}`,
      'X-CSRF-Token': csrfToken,
    },
  });
  if (!response.ok()) {
    throw new Error(`POST ${path} failed: ${response.status()} ${await response.text()}`);
  }
  return (await response.json()) as Record<string, unknown>;
}

async function listIssues(page: Page, user: TestUser, threadId: number): Promise<IssueInfo[]> {
  const response = await page.request.get(`/api/v1/threads/${threadId}/issues`, {
    headers: { Authorization: `Bearer ${user.accessToken ?? ''}` },
  });
  if (!response.ok()) {
    throw new Error(`Listing issues for thread ${threadId} failed: ${response.status()}`);
  }
  const data = (await response.json()) as { issues: IssueInfo[] };
  return data.issues;
}

/**
 * Builds the full post-roll context the audit exercised:
 * two threads joined by an issue dependency (connected-thread web) and one
 * shared crossover group containing issues from both threads.
 */
async function seedInterrelatedThreads(
  page: Page,
  user: TestUser,
): Promise<void> {
  const threadA = await createThread(page, {
    title: 'Alpha Cluster',
    format: 'Comic',
    issues_remaining: 5,
    total_issues: 5,
  });
  const threadB = await createThread(page, {
    title: 'Beta Signal',
    format: 'Comic',
    issues_remaining: 3,
    total_issues: 3,
  });

  const issuesA = await listIssues(page, user, threadA.id);
  const issuesB = await listIssues(page, user, threadB.id);
  expect(issuesA.length).toBeGreaterThanOrEqual(5);
  expect(issuesB.length).toBeGreaterThanOrEqual(3);

  await apiPost(page, user, '/api/v1/reading-order-groups/', { name: 'Cosmic Clash' })
    .then(async (group) => {
      const groupId = group.id as number;
      await apiPost(page, user, `/api/v1/reading-order-groups/${groupId}/issue-ranges`, {
        thread_id: threadA.id,
        start_position: 1,
        end_position: issuesA.length,
      });
      await apiPost(page, user, `/api/v1/reading-order-groups/${groupId}/issue-ranges`, {
        thread_id: threadB.id,
        start_position: 1,
        end_position: issuesB.length,
      });
    });

  await apiPost(page, user, '/api/v1/dependencies/', {
    source_type: 'issue',
    source_id: issuesA[0].id,
    target_id: issuesB[0].id,
  });
}

async function enterRatingView(page: Page): Promise<void> {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  const mainDie = page.getByTestId('main-die-3d');
  await expect(mainDie).toBeVisible({ timeout: 15000 });
  await mainDie.click();
  await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 });
}

async function assertExactlyOneInstancePerRegion(page: Page): Promise<void> {
  for (const name of REGION_NAMES) {
    const byRole = page.getByRole('heading', { name, exact: true });
    await expect(byRole).toHaveCount(1);
    await expect(byRole.first()).toBeVisible();

    // A DOM-present but accessibility-hidden duplicate (display:none,
    // visually clipped, or off-screen responsive copy) would still match a
    // text query while being invisible. Guard both surfaces explicitly.
    const domCopies = page.locator('h2, h3, h4').filter({ hasText: name });
    await expect(domCopies).toHaveCount(1);
    await expect(domCopies.first()).toBeVisible();
  }

  // The active regions must keep their accessible names and remain reachable
  // in the focus order rather than hiding behind inert duplicates.
  await expect(page.locator('#rating-heading')).toHaveCount(1);
  await expect(page.locator('#rating-input')).toBeVisible();
  await page.locator('#rating-input').focus();
  await expect(page.locator('#rating-input')).toBeFocused();
}

test.describe('issue #1883: Roll post-roll view exposes one accessible instance per region', () => {
  let user: TestUser;

  test.beforeEach(async ({ page }) => {
    user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);
    await seedInterrelatedThreads(page, user);
  });

  test('desktop widths expose exactly one instance of each Roll region', async ({ page }) => {
    await page.setViewportSize(DESKTOP_VIEWPORT);
    await enterRatingView(page);
    await assertExactlyOneInstancePerRegion(page);
  });

  test('mobile widths expose exactly one instance of each Roll region', async ({ page }) => {
    await page.setViewportSize(MOBILE_VIEWPORT);
    await enterRatingView(page);
    await assertExactlyOneInstancePerRegion(page);
  });
});
