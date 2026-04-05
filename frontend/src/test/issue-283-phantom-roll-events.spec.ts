import { test, expect } from './fixtures';
import { createThread, setupAuthenticatedPage, getAuthToken } from './helpers';

test.describe('Issue #283: Phantom Roll Events on Snooze', () => {
  test('should not create roll event when snoozing from rating view', async ({ page }) => {
    await setupAuthenticatedPage(page);

    const token = await getAuthToken(page);

    // Create a thread for rolling
    await createThread(page, {
      title: `Test Thread ${Date.now()}`,
      format: 'comic',
      issues_remaining: 5,
      total_issues: 10,
      issue_range: '1-10',
    });

    // Roll the thread
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForSelector('#main-die-3d', { state: 'visible', timeout: 10000 });

    const mainDie = page.locator('#main-die-3d');
    await mainDie.click();
    await page.waitForSelector('#rating-input', { state: 'visible', timeout: 10000 });

    // Get session history after roll - should have 1 "roll" event
    // First get the current session to get session ID
    const currentSession = await page.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(currentSession.ok()).toBeTruthy();
    const currentSessionData = await currentSession.json();

    const sessionAfterRoll = await page.request.get(`/api/sessions/${currentSessionData.id}/details`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(sessionAfterRoll.ok()).toBeTruthy();
    const sessionDataRoll = await sessionAfterRoll.json();

    // Count the number of "roll" type events
    const rollEventsAfterRoll = sessionDataRoll.events.filter((e: any) => e.type === 'roll');
    expect(rollEventsAfterRoll.length).toBe(1);

    // Rate the thread
    await page.fill('#rating-input', '4');
    await page.click('button:has-text("Save & Continue")');

    // Review form now appears - submit it (empty is fine)
    await expect(page.locator('[data-testid="modal"]')).toBeVisible({ timeout: 5000 });
    await Promise.all([
      page.waitForResponse(r => r.url().includes('/api/rate/')),
      page.click('button[type="submit"]'), // Save Review button
    ]);

    // Wait for roll view to return
    await page.waitForSelector('#main-die-3d', { state: 'visible', timeout: 10000 });
    await page.waitForLoadState('networkidle');

    // Get session history after rate - should have 1 "roll" and 1 "rate" event
    const currentSession2 = await page.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(currentSession2.ok()).toBeTruthy();
    const currentSessionData2 = await currentSession2.json();

    const sessionAfterRate = await page.request.get(`/api/sessions/${currentSessionData2.id}/details`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(sessionAfterRate.ok()).toBeTruthy();
    const sessionDataRate = await sessionAfterRate.json();

    const rollEventsAfterRate = sessionDataRate.events.filter((e: any) => e.type === 'roll');
    const rateEvents = sessionDataRate.events.filter((e: any) => e.type === 'rate');

    expect(rollEventsAfterRate.length).toBe(1);
    expect(rateEvents.length).toBe(1);

    // Now roll again and snooze
    await mainDie.click();
    await page.waitForSelector('#rating-input', { state: 'visible', timeout: 10000 });

    // Snooze the thread from rating view
    const snoozeButton = page.locator('button:has-text("Snooze")');
    await snoozeButton.click();

    // Wait for roll view to return
    await page.waitForSelector('#main-die-3d', { state: 'visible', timeout: 10000 });
    await page.waitForLoadState('networkidle');

    // Get session history after snooze - should NOT have an additional "roll" event
    const currentSession3 = await page.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(currentSession3.ok()).toBeTruthy();
    const currentSessionData3 = await currentSession3.json();

    const sessionAfterSnooze = await page.request.get(`/api/sessions/${currentSessionData3.id}/details`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(sessionAfterSnooze.ok()).toBeTruthy();
    const sessionDataSnooze = await sessionAfterSnooze.json();

    const rollEventsAfterSnooze = sessionDataSnooze.events.filter((e: any) => e.type === 'roll');
    const snoozeEvents = sessionDataSnooze.events.filter((e: any) => e.type === 'snooze');

    // Should still have only 2 roll events (from the two rolls we made)
    // The snooze action should NOT create a "roll" event
    expect(rollEventsAfterSnooze.length).toBe(2);
    expect(snoozeEvents.length).toBe(1);
  });

  test('should only have original roll and rate events after snooze', async ({ page }) => {
    await setupAuthenticatedPage(page);

    const token = await getAuthToken(page);

    // Create a thread for rolling
    await createThread(page, {
      title: `Snooze Event Thread ${Date.now()}`,
      format: 'comic',
      issues_remaining: 5,
      total_issues: 10,
      issue_range: '1-10',
    });

    // Roll the thread
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForSelector('#main-die-3d', { state: 'visible', timeout: 10000 });

    const mainDie = page.locator('#main-die-3d');
    await mainDie.click();
    await page.waitForSelector('#rating-input', { state: 'visible', timeout: 10000 });

    // Rate the thread
    await page.fill('#rating-input', '5');
    await page.click('button:has-text("Save & Continue")');

    // Review form now appears - submit it (empty is fine)
    await expect(page.locator('[data-testid="modal"]')).toBeVisible({ timeout: 5000 });
    await Promise.all([
      page.waitForResponse(r => r.url().includes('/api/rate/')),
      page.click('button[type="submit"]'), // Save Review button
    ]);

    // Wait for roll view to return
    await page.waitForSelector('#main-die-3d', { state: 'visible', timeout: 10000 });
    await page.waitForLoadState('networkidle');

    // Now roll again
    await mainDie.click();
    await page.waitForSelector('#rating-input', { state: 'visible', timeout: 10000 });

    // Snooze the thread from rating view
    const snoozeButton = page.locator('button:has-text("Snooze")');
    await snoozeButton.click();

    // Wait for roll view to return
    await page.waitForSelector('#main-die-3d', { state: 'visible', timeout: 10000 });
    await page.waitForLoadState('networkidle');

    // Get final session history
    const currentSession4 = await page.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(currentSession4.ok()).toBeTruthy();
    const currentSessionData4 = await currentSession4.json();

    const finalSession = await page.request.get(`/api/sessions/${currentSessionData4.id}/details`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(finalSession.ok()).toBeTruthy();
    const finalSessionData = await finalSession.json();

    // Verify we have exactly:
    // - 2 "roll" events (from the two rolls)
    // - 1 "rate" event (from the first rating)
    // - 1 "snooze" event (from the snooze)
    const rollEvents = finalSessionData.events.filter((e: any) => e.type === 'roll');
    const rateEvents = finalSessionData.events.filter((e: any) => e.type === 'rate');
    const snoozeEvents = finalSessionData.events.filter((e: any) => e.type === 'snooze');

    expect(rollEvents.length).toBe(2);
    expect(rateEvents.length).toBe(1);
    expect(snoozeEvents.length).toBe(1);

    // Verify the event types are correct
    const allEventTypes = finalSessionData.events.map((e: any) => e.type);
    expect(allEventTypes).toEqual(expect.arrayContaining(['roll', 'roll', 'rate', 'snooze']));

    // Verify no unexpected event types
    const unexpectedEvents = allEventTypes.filter((t: string) => !['roll', 'rate', 'snooze'].includes(t));
    expect(unexpectedEvents.length).toBe(0);
  });

  test('should verify phantom roll events are not created across multiple snooze cycles', async ({ page }) => {
    await setupAuthenticatedPage(page);

    const token = await getAuthToken(page);

    // Create multiple threads for testing
    for (let i = 0; i < 5; i++) {
      await createThread(page, {
        title: `Multi Snooze Thread ${Date.now()}-${i}`,
        format: 'comic',
        issues_remaining: 5,
        total_issues: 10,
        issue_range: '1-10',
      });
    }

    // Track the expected number of roll events
    let expectedRollCount = 0;

    // Perform multiple roll-rate-snooze cycles
    for (let i = 0; i < 3; i++) {
      // Roll
      await page.goto('/');
      await page.waitForLoadState('networkidle');
      await page.waitForSelector('#main-die-3d', { state: 'visible', timeout: 10000 });

      const mainDie = page.locator('#main-die-3d');
      await mainDie.click();
      await page.waitForSelector('#rating-input', { state: 'visible', timeout: 10000 });

      expectedRollCount++;

      // Verify roll count is correct so far
      const currentSession = await page.request.get('/api/sessions/current/', {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(currentSession.ok()).toBeTruthy();
      const currentSessionData = await currentSession.json();

      const sessionAfterRoll = await page.request.get(`/api/sessions/${currentSessionData.id}/details`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const sessionData = await sessionAfterRoll.json();
      const actualRollCount = sessionData.events.filter((e: any) => e.type === 'roll').length;
      expect(actualRollCount).toBe(expectedRollCount);

      // Rate
      await page.fill('#rating-input', '3');
      await page.click('button:has-text("Save & Continue")');
      
    // Review form now appears - submit it (empty is fine)
    await expect(page.locator('[data-testid="modal"]')).toBeVisible({ timeout: 5000 });
    await Promise.all([
      page.waitForResponse(r => r.url().includes('/api/rate/')),
      page.click('button:has-text("Skip")'), // Skip button (doesn't require text)
    ]);
      
      await page.waitForSelector('#main-die-3d', { state: 'visible', timeout: 10000 });
      await page.waitForLoadState('networkidle');

      // Roll again to get into rating view
      await mainDie.click();
      await page.waitForSelector('#rating-input', { state: 'visible', timeout: 10000 });

      expectedRollCount++;

      // Verify roll count is still correct
      const currentSession2 = await page.request.get('/api/sessions/current/', {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(currentSession2.ok()).toBeTruthy();
      const currentSessionData2 = await currentSession2.json();

      const sessionAfterSecondRoll = await page.request.get(`/api/sessions/${currentSessionData2.id}/details`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const sessionData2 = await sessionAfterSecondRoll.json();
      const actualRollCount2 = sessionData2.events.filter((e: any) => e.type === 'roll').length;
      expect(actualRollCount2).toBe(expectedRollCount);

      // Snooze
      const snoozeButton = page.locator('button:has-text("Snooze")');
      await snoozeButton.click();
      await page.waitForSelector('#main-die-3d', { state: 'visible', timeout: 10000 });
      await page.waitForLoadState('networkidle');

      // Verify snooze did NOT create a roll event
      const currentSession3 = await page.request.get('/api/sessions/current/', {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(currentSession3.ok()).toBeTruthy();
      const currentSessionData3 = await currentSession3.json();

      const sessionAfterSnooze = await page.request.get(`/api/sessions/${currentSessionData3.id}/details`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const sessionData3 = await sessionAfterSnooze.json();
      const actualRollCount3 = sessionData3.events.filter((e: any) => e.type === 'roll').length;
      expect(actualRollCount3).toBe(expectedRollCount);
    }

    // Final verification: total roll events should equal the number of times we rolled
    const currentSessionFinal = await page.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(currentSessionFinal.ok()).toBeTruthy();
    const currentSessionDataFinal = await currentSessionFinal.json();

    const finalSession = await page.request.get(`/api/sessions/${currentSessionDataFinal.id}/details`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const finalSessionData = await finalSession.json();
    const finalRollCount = finalSessionData.events.filter((e: any) => e.type === 'roll').length;

    // We rolled twice per cycle, for 3 cycles = 6 roll events
    expect(finalRollCount).toBe(6);
  });
});
