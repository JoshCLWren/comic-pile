import { test, expect } from './fixtures';
import type { APIRequestContext } from '@playwright/test';

async function createCollection(request: APIRequestContext, token: string, name: string) {
  const response = await request.post('/api/v1/collections/', {
    data: { name },
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok()) {
    throw new Error(`Failed to create collection: ${response.status()} ${response.statusText()}`);
  }

  const data = await response.json();
  return data.id as number;
}

async function createThreadInCollection(
  request: APIRequestContext,
  token: string,
  collectionId: number,
  title: string
) {
  const response = await request.post('/api/threads/', {
    data: {
      title,
      format: 'Comics',
      issues_remaining: 10,
      collection_id: collectionId,
    },
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok()) {
    throw new Error(`Failed to create thread: ${response.status()} ${response.statusText()}`);
  }

  return response.json();
}

test.describe('Collections', () => {
  test('create and switch collections from roll pool dropdown', async ({ authenticatedPage, request }) => {
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);
    if (!token) throw new Error('No auth token found');

    const collectionName = `Test Collection ${Date.now()}`;
    const collectionId = await createCollection(request, token, collectionName);

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    const selector = authenticatedPage.getByLabel('Roll pool collection');
    await expect(selector).toBeVisible();
    await selector.selectOption(String(collectionId));
    await expect(selector).toHaveValue(String(collectionId));
  });

  test('shows collection badge on threads', async ({ authenticatedPage, request }) => {
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);
    if (!token) throw new Error('No auth token found');

    const collectionName = `Comics Collection ${Date.now()}`;
    const collectionId = await createCollection(request, token, collectionName);
    const threadTitle = `Thread in ${collectionName}`;
    await createThreadInCollection(request, token, collectionId, threadTitle);

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    const threadCard = authenticatedPage.locator('[data-testid="queue-thread-item"]').filter({ hasText: threadTitle });
    await expect(threadCard).toBeVisible();
    await expect(threadCard.locator('[data-testid="collection-badge"]')).toHaveText(collectionName);
  });

  test('deletes collection and moves threads', async ({ authenticatedPage, request }) => {
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);
    if (!token) throw new Error('No auth token found');

    const collectionName = `Delete Me ${Date.now()}`;
    const collectionId = await createCollection(request, token, collectionName);
    const threadTitle = `Thread to move from ${collectionName}`;
    await createThreadInCollection(request, token, collectionId, threadTitle);

    await request.delete(`/api/v1/collections/${collectionId}`, {
      headers: { 'Authorization': `Bearer ${token}` },
    });

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    const threadCard = authenticatedPage.locator('[data-testid="queue-thread-item"]').filter({ hasText: threadTitle });
    await expect(threadCard).toBeVisible();
    await expect(threadCard.locator('[data-testid="collection-badge"]')).toHaveCount(0);
  });

  test('filters threads by selected collection on Roll page', async ({ authenticatedPage, request }) => {
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);
    if (!token) throw new Error('No auth token found');

    const collectionAName = `Filter A ${Date.now()}`;
    const collectionBName = `Filter B ${Date.now()}`;
    const collectionAId = await createCollection(request, token, collectionAName);
    const collectionBId = await createCollection(request, token, collectionBName);

    const threadAName = `Thread A ${Date.now()}`;
    const threadBName = `Thread B ${Date.now()}`;
    await createThreadInCollection(request, token, collectionAId, threadAName);
    await createThreadInCollection(request, token, collectionBId, threadBName);

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    const selector = authenticatedPage.getByLabel('Roll pool collection');

    await selector.selectOption(String(collectionAId));
    await authenticatedPage.waitForLoadState('networkidle');

    const threadA = authenticatedPage.locator(`text="${threadAName}"`);
    const threadB = authenticatedPage.locator(`text="${threadBName}"`);

    await expect(threadA).toBeVisible({ timeout: 10000 });

    await selector.selectOption(String(collectionBId));
    await authenticatedPage.waitForLoadState('networkidle');

    await expect(threadB).toBeVisible({ timeout: 10000 });

    await selector.selectOption('all');
    await authenticatedPage.waitForLoadState('networkidle');

    await expect(authenticatedPage.locator(`text="${threadAName}"`)).toBeVisible({ timeout: 10000 });
    await expect(authenticatedPage.locator(`text="${threadBName}"`)).toBeVisible({ timeout: 10000 });
  });
});
