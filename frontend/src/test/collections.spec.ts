import { test, expect } from './fixtures';
import type { APIRequestContext } from '@playwright/test';

/**
 * Helper to create a collection via API
 */
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
  return data.id;
}

/**
 * Helper to create a thread in a specific collection via API
 */
async function createThreadInCollection(
  request: APIRequestContext,
  token: string,
  collectionId: number,
  title: string
) {
  const response = await request.post('/api/threads/', {
    data: {
      title,
      format: 'Comic',
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
  test('create and switch collections', async ({ authenticatedPage, request }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('networkidle');

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    if (!token) {
      throw new Error('No auth token found');
    }

    const collectionName = `Test Collection ${Date.now()}`;
    const collectionId = await createCollection(request, token, collectionName);

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    await expect(authenticatedPage.locator('text=' + collectionName)).toBeVisible();

    await authenticatedPage.click('text=' + collectionName);
    await authenticatedPage.waitForLoadState('networkidle');

    await expect(
      authenticatedPage.locator('.sidebar__item--active').filter({ hasText: collectionName })
    ).toBeVisible();
  });

  test('shows collection badge on threads', async ({ authenticatedPage, request }) => {
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    if (!token) {
      throw new Error('No auth token found');
    }

    const collectionName = `Comics Collection ${Date.now()}`;
    const collectionId = await createCollection(request, token, collectionName);
    const threadTitle = `Thread in ${collectionName}`;

    await createThreadInCollection(request, token, collectionId, threadTitle);

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    const threadCard = authenticatedPage.locator('[data-testid="queue-thread-item"]').filter({ hasText: threadTitle });
    await expect(threadCard).toBeVisible();

    await expect(
      threadCard.locator(`text=${collectionName}`)
    ).toBeVisible();
  });

  test('deletes collection and moves threads', async ({ authenticatedPage, request }) => {
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    if (!token) {
      throw new Error('No auth token found');
    }

    const collectionName = `Delete Me ${Date.now()}`;
    const collectionId = await createCollection(request, token, collectionName);
    const threadTitle = `Thread to move from ${collectionName}`;

    await createThreadInCollection(request, token, collectionId, threadTitle);

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    await expect(authenticatedPage.locator('text=' + collectionName)).toBeVisible();

    authenticatedPage.on('dialog', dialog => dialog.accept());

    const deleteButton = authenticatedPage.locator(
      `[aria-label="Delete ${collectionName} collection"]`
    );
    await expect(deleteButton).toBeVisible();
    await deleteButton.click();

    await authenticatedPage.waitForLoadState('networkidle');

    await expect(async () => {
      const isVisible = await authenticatedPage.locator('text=' + collectionName).count() > 0;
      expect(isVisible).toBe(false);
    }).toPass({ timeout: 5000 });

    const threadCard = authenticatedPage.locator('[data-testid="queue-thread-item"]').filter({ hasText: threadTitle });
    await expect(threadCard).toBeVisible();

    const badgeCount = await threadCard.locator('.inline-flex').count();
    expect(badgeCount).toBe(0);
  });

  test('filters threads by collection', async ({ authenticatedPage, request }) => {
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    if (!token) {
      throw new Error('No auth token found');
    }

    const collectionAName = `Collection A ${Date.now()}`;
    const collectionBName = `Collection B ${Date.now()}`;
    const collectionAId = await createCollection(request, token, collectionAName);
    const collectionBId = await createCollection(request, token, collectionBName);

    const threadAName = `Thread in ${collectionAName}`;
    const threadBName = `Thread in ${collectionBName}`;

    await createThreadInCollection(request, token, collectionAId, threadAName);
    await createThreadInCollection(request, token, collectionBId, threadBName);

    await authenticatedPage.goto('/queue');
    await authenticatedPage.waitForLoadState('networkidle');

    await expect(authenticatedPage.locator('text=' + threadAName)).toBeVisible();
    await expect(authenticatedPage.locator('text=' + threadBName)).toBeVisible();

    await authenticatedPage.click('text=' + collectionAName);
    await authenticatedPage.waitForLoadState('networkidle');

    await expect(authenticatedPage.locator('text=' + threadAName)).toBeVisible();
    await expect(authenticatedPage.locator('text=' + threadBName)).toHaveCount(0);

    await authenticatedPage.click('text=' + collectionBName);
    await authenticatedPage.waitForLoadState('networkidle');

    await expect(authenticatedPage.locator('text=' + threadBName)).toBeVisible();
    await expect(authenticatedPage.locator('text=' + threadAName)).toHaveCount(0);

    await authenticatedPage.click('text=All Collections');
    await authenticatedPage.waitForLoadState('networkidle');

    await expect(authenticatedPage.locator('text=' + threadAName)).toBeVisible();
    await expect(authenticatedPage.locator('text=' + threadBName)).toBeVisible();
  });
});
