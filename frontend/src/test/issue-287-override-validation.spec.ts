import { test, expect } from './fixtures';
import { createThread, setupAuthenticatedPage, getAuthToken } from './helpers';

test.describe('Issue #287: Override Validation', () => {
  test('should show error when overriding to a blocked thread', async ({ page, request }) => {
    await setupAuthenticatedPage(page);

    const token = await getAuthToken(page);

    // Create a thread to be blocked
    const blockedThread = await createThread(page, {
      title: `Blocked Thread ${Date.now()}`,
      format: 'comic',
      issues_remaining: 5,
      total_issues: 10,
      issue_range: '1-10',
    });

    // Create a thread that will block the first one
    const blockerThread = await createThread(page, {
      title: `Blocker Thread ${Date.now()}`,
      format: 'comic',
      issues_remaining: 5,
      total_issues: 10,
      issue_range: '1-10',
    });

    // Create dependency to block the first thread
    // Get issue IDs for both threads
    const blockerIssuesResponse = await request.get(`/api/v1/threads/${blockerThread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const blockerIssuesData = await blockerIssuesResponse.json();
    const blockerLastIssue = blockerIssuesData.issues[blockerIssuesData.issues.length - 1];

    const blockedIssuesResponse = await request.get(`/api/v1/threads/${blockedThread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const blockedIssuesData = await blockedIssuesResponse.json();
    const blockedFirstIssue = blockedIssuesData.issues[0];

    const depResponse = await request.post('/api/v1/dependencies/', {
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      data: {
        source_type: 'issue',
        source_id: blockerLastIssue.id,
        target_type: 'issue',
        target_id: blockedFirstIssue.id,
      },
    });
    expect(depResponse.ok()).toBeTruthy();

    // Create another rollable thread
    await createThread(page, {
      title: `Normal Thread ${Date.now()}`,
      format: 'comic',
      issues_remaining: 5,
      total_issues: 10,
      issue_range: '1-10',
    });

    // Roll to get a normal thread
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForSelector('#main-die-3d', { state: 'visible', timeout: 10000 });

    const mainDie = page.locator('#main-die-3d');
    await mainDie.click();
    await page.waitForSelector('#rating-input', { state: 'visible', timeout: 10000 });

    // Try to override to the blocked thread via API
    const overrideResponse = await request.post('/api/roll/override', {
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      data: {
        thread_id: blockedThread.id,
      },
    });

    // Should return 422 with error message
    expect(overrideResponse.status()).toBe(422);

    const errorData = await overrideResponse.json();
    expect(errorData.detail).toBeDefined();
    expect(errorData.detail).toBeTruthy();
    expect(errorData.detail).toMatch(/block/i);
  });

  test('should show error when overriding to a completed thread', async ({ page, request }) => {
    await setupAuthenticatedPage(page);

    const token = await getAuthToken(page);

    // Create and complete a thread
    const completedThread = await createThread(page, {
      title: `Completed Thread ${Date.now()}`,
      format: 'comic',
      issues_remaining: 0,
      total_issues: 10,
      issue_range: '1-10',
    });

    // Create a normal rollable thread
    await createThread(page, {
      title: `Normal Thread ${Date.now()}`,
      format: 'comic',
      issues_remaining: 5,
      total_issues: 10,
      issue_range: '1-10',
    });

    // Roll to get a normal thread
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForSelector('#main-die-3d', { state: 'visible', timeout: 10000 });

    const mainDie = page.locator('#main-die-3d');
    await mainDie.click();
    await page.waitForSelector('#rating-input', { state: 'visible', timeout: 10000 });

    // Try to override to the completed thread via API
    const overrideResponse = await request.post('/api/roll/override', {
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      data: {
        thread_id: completedThread.id,
      },
    });

    // Should return 422 with error message
    expect(overrideResponse.status()).toBe(422);

    const errorData = await overrideResponse.json();
    expect(errorData.detail).toBeDefined();
    expect(errorData.detail).toBeTruthy();
    expect(errorData.detail).toMatch(/complet/i);
  });

  test('should provide user-friendly error message for invalid override', async ({ page, request }) => {
    await setupAuthenticatedPage(page);

    const token = await getAuthToken(page);

    // Create a completed thread
    const completedThread = await createThread(page, {
      title: `Completed Thread ${Date.now()}`,
      format: 'comic',
      issues_remaining: 0,
      total_issues: 10,
      issue_range: '1-10',
    });

    // Create a rollable thread
    await createThread(page, {
      title: `Normal Thread ${Date.now()}`,
      format: 'comic',
      issues_remaining: 5,
      total_issues: 10,
      issue_range: '1-10',
    });

    // Roll to get a normal thread
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForSelector('#main-die-3d', { state: 'visible', timeout: 10000 });

    const mainDie = page.locator('#main-die-3d');
    await mainDie.click();
    await page.waitForSelector('#rating-input', { state: 'visible', timeout: 10000 });

    // Try to override to the completed thread
    const overrideResponse = await request.post('/api/roll/override', {
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      data: {
        thread_id: completedThread.id,
      },
    });

    expect(overrideResponse.status()).toBe(422);

    const errorData = await overrideResponse.json();

    // Verify error message is user-friendly (not a generic server error)
    expect(errorData.detail).toBeDefined();
    expect(errorData.detail).toBeTruthy();
    expect(errorData.detail.length).toBeGreaterThan(10);
    expect(errorData.detail.length).toBeLessThan(200);

    // Error should not contain technical stack traces or implementation details
    expect(errorData.detail).not.toMatch(/traceback|exception|error:|failed/i);
  });
});
