import { test, expect } from './fixtures';
import type { APIRequestContext } from '@playwright/test';

async function createCollection(request: APIRequestContext, token: string, name: string, isDefault = false) {
  const response = await request.post('/api/v1/collections/', {
    data: { name, is_default: isDefault },
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

async function deleteCollection(request: APIRequestContext, token: string, collectionId: number) {
  const response = await request.delete(`/api/v1/collections/${collectionId}`, {
    headers: {
      'Authorization': `Bearer ${token}`,
    },
  });

  if (!response.ok()) {
    throw new Error(`Failed to delete collection: ${response.status()} ${response.statusText()}`);
  }
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

    await deleteCollection(request, token, collectionId);

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    const threadCard = authenticatedPage.locator('[data-testid="queue-thread-item"]').filter({ hasText: threadTitle });
    await expect(threadCard).toBeVisible();
    await expect(threadCard.locator('[data-testid="collection-badge"]')).toHaveCount(0);
  });

  test.skip('filters queue threads by selected collection - TODO: fix race condition in test', async ({ authenticatedPage, request }) => {
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN);
    if (!token) throw new Error('No auth token found');

    const collectionAName = `Collection A ${Date.now()}`;
    const collectionBName = `Collection B ${Date.now()}`;
    const collectionAId = await createCollection(request, token, collectionAName);
    const collectionBId = await createCollection(request, token, collectionBName);

    const threadAName = `Thread in ${collectionAName}`;
    const threadBName = `Thread in ${collectionBName}`;
    await createThreadInCollection(request, token, collectionAId, threadAName);
    await createThreadInCollection(request, token, collectionBId, threadBName);

    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('domcontentloaded');

    const selector = authenticatedPage.getByLabel('Roll pool collection');
    await selector.selectOption(String(collectionAId));
    await authenticatedPage.waitForTimeout(2000); // Wait for collection state to propagate

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('domcontentloaded');
    await authenticatedPage.waitForTimeout(2000); // Wait for threads to load with filter

    // Wait for thread A to be visible before checking thread B is hidden
    // This ensures the collection filter has been applied
    await expect(authenticatedPage.locator(`text=${threadAName}`)).toBeVisible();
    await expect(authenticatedPage.locator(`text=${threadBName}`)).not.toBeVisible();

    await authenticatedPage.goto('/');
    await selector.selectOption(String(collectionBId));
    await authenticatedPage.waitForTimeout(2000); // Wait for collection state to propagate

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('domcontentloaded');
    await authenticatedPage.waitForTimeout(2000); // Wait for threads to load with filter

    // Wait for thread B to be visible before checking thread A is hidden
    await expect(authenticatedPage.locator(`text=${threadBName}`)).toBeVisible();
    await expect(authenticatedPage.locator(`text=${threadAName}`)).not.toBeVisible();

    await authenticatedPage.goto('/');
    await selector.selectOption('all');

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('domcontentloaded');
    await expect(authenticatedPage.locator(`text=${threadAName}`)).toBeVisible();
    await expect(authenticatedPage.locator(`text=${threadBName}`)).toBeVisible();
  });
});
