import { test, expect } from './fixtures';
import { createThread, setupAuthenticatedPage, getAuthToken } from './helpers';

test.describe('Issue #293: Snoozed Thread Persistence', () => {
  test('should prevent overriding to a snoozed thread', async ({ page, request }) => {
    await setupAuthenticatedPage(page);

    const token = await getAuthToken(page);

    // Create a thread that will be snoozed
    const snoozedThread = await createThread(page, {
      title: `Snoozed Thread ${Date.now()}`,
      format: 'comic',
      issues_remaining: 5,
      total_issues: 10,
      issue_range: '1-10',
    });

    // Create some other threads for the roll pool
    for (let i = 0; i < 3; i++) {
      await createThread(page, {
        title: `Pool Thread ${Date.now()}-${i}`,
        format: 'comic',
        issues_remaining: 5,
        total_issues: 10,
        issue_range: '1-10',
      });
    }

    // Set the thread as pending and snooze it
    await page.request.post(`/api/threads/${snoozedThread.id}/set-pending`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    await page.waitForTimeout(500);

    // Snooze the thread
    const snoozeResponse = await page.request.post('/api/snooze/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(snoozeResponse.ok()).toBeTruthy();

    // Verify thread is in snoozed list via session endpoint
    const sessionResponse = await page.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(sessionResponse.ok()).toBeTruthy();
    const sessionData = await sessionResponse.json();
    const wasSnoozed = sessionData.snoozed_threads.some((t: any) => t.id === snoozedThread.id);
    expect(wasSnoozed).toBe(true);

    // Perform a normal roll to get an active thread
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForSelector('#main-die-3d', { state: 'visible', timeout: 10000 });

    const mainDie = page.locator('#main-die-3d');
    await mainDie.click();
    await page.waitForSelector('#rating-input', { state: 'visible', timeout: 10000 });

    // Try to override to the snoozed thread - should fail with 400
    const overrideResponse = await page.request.post('/api/roll/override', {
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      data: {
        thread_id: snoozedThread.id,
      },
    });

    // Should return 400 with error message about snoozed thread
    expect(overrideResponse.status()).toBe(400);

    const errorData = await overrideResponse.json();
    expect(errorData.detail).toBeDefined();
    expect(errorData.detail).toBeTruthy();
    expect(errorData.detail).toMatch(/snooz/i);

    // Verify the thread is still in the snoozed list after failed override
    const sessionAfterResponse = await page.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(sessionAfterResponse.ok()).toBeTruthy();
    const sessionAfter = await sessionAfterResponse.json();
    const stillSnoozed = sessionAfter.snoozed_threads.some((t: any) => t.id === snoozedThread.id);
    expect(stillSnoozed).toBe(true);
  });

  test('should show snoozed-offset badge correctly when snoozed', async ({ page, request }) => {
    const pageUnderTest = page;

    await setupAuthenticatedPage(pageUnderTest);

    const token = await getAuthToken(pageUnderTest);

    // Create enough threads for d20 pool
    for (let i = 0; i < 20; i++) {
      await createThread(pageUnderTest, {
        title: `Pool Thread ${Date.now()}-${i}`,
        format: 'comic',
        issues_remaining: 5,
        total_issues: 10,
        issue_range: '1-10',
      });
    }

    // Create a thread to snooze
    const snoozedThread = await createThread(pageUnderTest, {
      title: `Snoozed Badge Thread ${Date.now()}`,
      format: 'comic',
      issues_remaining: 5,
      total_issues: 10,
      issue_range: '1-10',
    });

    // Set die to d20
    const setDieResponse = await request.post('/api/roll/set-die?die=20', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(setDieResponse.ok()).toBeTruthy();

    // Set the thread as pending and snooze it
    await pageUnderTest.request.post(`/api/threads/${snoozedThread.id}/set-pending`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    await pageUnderTest.waitForTimeout(500);

    const snoozeResponse = await pageUnderTest.request.post('/api/snooze/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(snoozeResponse.ok()).toBeTruthy();

    // Refresh to see updated state
    await pageUnderTest.goto('/');
    await pageUnderTest.waitForLoadState('networkidle');

    // Verify die is d20
    const headerDieLabel = pageUnderTest.locator('#header-die-label');
    await expect(headerDieLabel).toContainText('d20');

    // The snoozed-offset badge should NOT be visible when die is d20
    const snoozedOffsetBadge = pageUnderTest.locator('.modifier-badge');
    await expect(snoozedOffsetBadge).not.toBeVisible();

    // Verify thread is in snoozed list via session API
    const sessionResponse = await pageUnderTest.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(sessionResponse.ok()).toBeTruthy();
    const sessionData = await sessionResponse.json();

    // Verify the thread is in snoozed_threads
    const isInSnoozedList = sessionData.snoozed_threads.some((t: any) => t.id === snoozedThread.id);
    expect(isInSnoozedList).toBe(true);

    // The snoozed-offset badge should STILL not be visible
    await expect(snoozedOffsetBadge).not.toBeVisible();
  });

  test('should maintain snoozed state consistency across operations', async ({ page, request }) => {
    await setupAuthenticatedPage(page);

    const token = await getAuthToken(page);

    // Create a thread to snooze
    const snoozedThread = await createThread(page, {
      title: `Multi Snooze Thread ${Date.now()}`,
      format: 'comic',
      issues_remaining: 5,
      total_issues: 10,
      issue_range: '1-10',
    });

    // Create some other threads
    for (let i = 0; i < 4; i++) {
      await createThread(page, {
        title: `Pool Thread ${Date.now()}-${i}`,
        format: 'comic',
        issues_remaining: 5,
        total_issues: 10,
        issue_range: '1-10',
      });
    }

    // Set the thread as pending and snooze it
    await page.request.post(`/api/threads/${snoozedThread.id}/set-pending`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    await page.waitForTimeout(500);

    const snoozeResponse = await page.request.post('/api/snooze/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(snoozeResponse.ok()).toBeTruthy();

    // Perform multiple roll and rate cycles
    for (let i = 0; i < 3; i++) {
      // Roll to get an active thread
      await page.goto('/');
      await page.waitForLoadState('networkidle', { timeout: 30000 });
      await page.waitForSelector('#main-die-3d', { state: 'visible', timeout: 10000 });

      const mainDie = page.locator('#main-die-3d');
      await mainDie.click();
      await page.waitForSelector('#rating-input', { state: 'visible', timeout: 10000 });

      // Verify the thread is still in the snoozed list
      const snoozedResponse = await page.request.get('/api/sessions/current/', {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(snoozedResponse.ok()).toBeTruthy();
      const snoozed = await snoozedResponse.json();
      const isStillSnoozed = snoozed.snoozed_threads.some((t: any) => t.id === snoozedThread.id);
      expect(isStillSnoozed).toBe(true);

      // Rate the thread to clear active slot
      await page.request.post('/api/rate/', {
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        data: {
          rating: 4.0,
          finish_session: false,
        },
      });

      await page.waitForTimeout(500);
    }

    // Final verification: thread should still be in snoozed list after multiple cycles
    const finalSessionResponse = await page.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(finalSessionResponse.ok()).toBeTruthy();
    const finalSession = await finalSessionResponse.json();
    const stillSnoozed = finalSession.snoozed_threads.some((t: any) => t.id === snoozedThread.id);
    expect(stillSnoozed).toBe(true);
  });
});
