import { test, expect } from './fixtures';

test.describe('Set Pending Thread (Manual Selection)', () => {
  test('should click thread in queue and navigate to rate page', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/queue');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    await authenticatedWithThreadsPage.waitForSelector('#queue-container', { state: 'visible', timeout: 5000 });

    const firstThreadCard = authenticatedWithThreadsPage.locator('#queue-container .glass-card').first();
    await expect(firstThreadCard).toBeVisible({ timeout: 5000 });

    const threadTitle = await firstThreadCard.locator('h3').textContent();

    await firstThreadCard.click();

    await expect(async () => {
      const modal = authenticatedWithThreadsPage.locator('.fixed.inset-0.z-50');
      await expect(modal).toBeVisible();
    }).toPass({ timeout: 5000 });

    const readButton = authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).first();
    await expect(readButton).toBeVisible({ timeout: 3000 });

    await Promise.all([
      authenticatedWithThreadsPage.waitForURL('**/rate', { timeout: 5000 }),
      readButton.click(),
    ]);

    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    const currentUrl = authenticatedWithThreadsPage.url();
    expect(currentUrl).toContain('/rate');

    await expect(authenticatedWithThreadsPage.locator('#rating-input')).toBeVisible({ timeout: 3000 });

    const ratePageTitle = authenticatedWithThreadsPage.locator('#thread-info h2');
    await expect(ratePageTitle).toBeVisible({ timeout: 3000 });

    const ratePageTitleText = await ratePageTitle.textContent();
    expect(ratePageTitleText).toBe(threadTitle);
  });

  test('should return correct RollResponse structure when setting thread as pending', async ({ authenticatedWithThreadsPage }) => {
    const token = await authenticatedWithThreadsPage.evaluate(() => localStorage.getItem('auth_token'));

    const threadsResponse = await authenticatedWithThreadsPage.request.get('/api/threads/', {
      headers: {
        'Authorization': `Bearer ${token}`,
      },
    });

    expect(threadsResponse.ok()).toBeTruthy();
    const threads = await threadsResponse.json();
    expect(threads.length).toBeGreaterThan(0);
    const threadId = threads[0].id;

    const response = await authenticatedWithThreadsPage.request.post(`/api/threads/${threadId}/set-pending`, {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    });

    expect(response.status()).toBe(200);

    const data = await response.json();

    expect(data).toHaveProperty('thread_id');
    expect(data).toHaveProperty('title');
    expect(data).toHaveProperty('format');
    expect(data).toHaveProperty('issues_remaining');
    expect(data).toHaveProperty('queue_position');
    expect(data).toHaveProperty('die_size');
    expect(data).toHaveProperty('result');
    expect(data).toHaveProperty('offset');
    expect(data).toHaveProperty('snoozed_count');

    expect(data.result).toBe(0);
    expect(typeof data.die_size).toBe('number');
    expect(data.die_size).toBeGreaterThan(0);

    expect(data.thread_id).toBe(threadId);
    expect(data.title).toBe(threads[0].title);
    expect(data.format).toBe(threads[0].format);
  });

  test('should update session pending_thread_id', async ({ authenticatedWithThreadsPage }) => {
    const token = await authenticatedWithThreadsPage.evaluate(() => localStorage.getItem('auth_token'));

    const threadsResponse = await authenticatedWithThreadsPage.request.get('/api/threads/', {
      headers: {
        'Authorization': `Bearer ${token}`,
      },
    });

    const threads = await threadsResponse.json();
    const threadId = threads[0].id;

    const setPendingResponse = await authenticatedWithThreadsPage.request.post(`/api/threads/${threadId}/set-pending`, {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    });

    expect(setPendingResponse.status()).toBe(200);

    const sessionResponse = await authenticatedWithThreadsPage.request.get('/api/sessions/current/', {
      headers: {
        'Authorization': `Bearer ${token}`,
      },
    });

    expect(sessionResponse.ok()).toBeTruthy();
    const session = await sessionResponse.json();

    expect(session.pending_thread_id).toBe(threadId);
    expect(session.pending_thread_id).toBeDefined();
  });

  test('should return 404 for non-existent thread', async ({ authenticatedWithThreadsPage }) => {
    const token = await authenticatedWithThreadsPage.evaluate(() => localStorage.getItem('auth_token'));

    const response = await authenticatedWithThreadsPage.request.post('/api/threads/99999/set-pending', {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    });

    expect(response.status()).toBe(404);
  });

  test('should return 400 for thread with no issues remaining', async ({ authenticatedWithThreadsPage, request }) => {
    const token = await authenticatedWithThreadsPage.evaluate(() => localStorage.getItem('auth_token'));

    const createResponse = await request.post('/api/threads/', {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: {
        title: 'No Issues Thread',
        format: 'Comic',
        issues_remaining: 0,
      },
    });

    expect(createResponse.ok()).toBeTruthy();
    const createdThread = await createResponse.json();

    const response = await authenticatedWithThreadsPage.request.post(`/api/threads/${createdThread.id}/set-pending`, {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    });

    expect(response.status()).toBe(400);

    const error = await response.json();
    expect(error.detail).toContain('has no issues remaining');
  });
});
