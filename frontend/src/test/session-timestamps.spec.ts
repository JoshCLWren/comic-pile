import { test, expect } from './fixtures';
import { SELECTORS, setRangeInput, createThread } from './helpers';

test.describe('Session Timestamp Consistency (Issue #245)', () => {
  test('should display consistently formatted timestamps on Session Details page', async ({ authenticatedPage }) => {
    // First, create a session with some activity
    await authenticatedPage.goto('/');

    const mainDieExists = await authenticatedPage.locator(SELECTORS.roll.mainDie).count();
    
    // If no threads exist, create one
    if (mainDieExists === 0) {
      await createThread(authenticatedPage, {
        title: 'Timestamp Test Thread',
        format: 'issue',
        issues_remaining: 5,
      });
      
      // Reload to see the new thread
      await authenticatedPage.reload();
      await authenticatedPage.waitForLoadState('networkidle');
    }

    await authenticatedPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });

    // Roll the die to create an event
    await authenticatedPage.click(SELECTORS.roll.mainDie);
    await authenticatedPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 5000 });

    // Rate to create another event
    await setRangeInput(authenticatedPage, SELECTORS.rate.ratingInput, '4.0');
    await authenticatedPage.click(SELECTORS.rate.submitButton);
    await authenticatedPage.waitForLoadState('networkidle');

    // Navigate to history to get a session ID
    await authenticatedPage.goto('/history');
    await authenticatedPage.waitForLoadState('networkidle');

    // Find the first session link and navigate to it
    const sessionLink = authenticatedPage.locator('a[href^="/session/"]').first();
    const sessionCount = await sessionLink.count();

    // If no sessions exist (shouldn't happen after roll/rate), create activity first
    if (sessionCount === 0) {
      await authenticatedPage.goto('/');
      
      // Ensure we have a thread
      const hasDie = await authenticatedPage.locator(SELECTORS.roll.mainDie).count();
      if (hasDie === 0) {
        await createThread(authenticatedPage, {
          title: 'Timestamp Test Thread 2',
          format: 'issue',
          issues_remaining: 5,
        });
        await authenticatedPage.reload();
        await authenticatedPage.waitForLoadState('networkidle');
      }
      
      // Wait for die to be visible before clicking
      await authenticatedPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });
      
      // Create activity
      await authenticatedPage.click(SELECTORS.roll.mainDie);
      await authenticatedPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 5000 });
      await setRangeInput(authenticatedPage, SELECTORS.rate.ratingInput, '3.0');
      await authenticatedPage.click(SELECTORS.rate.submitButton);
      await authenticatedPage.waitForLoadState('networkidle');
      
      // Now go back to history
      await authenticatedPage.goto('/history');
      await authenticatedPage.waitForLoadState('networkidle');
    }

    await sessionLink.click();
    await authenticatedPage.waitForLoadState('networkidle');

    // Wait for Session Details page to load
    await expect(authenticatedPage.locator('h1:has-text("Session Details")')).toBeVisible();

    // Collect all timestamp text from the page
    const timestampSelector = authenticatedPage.locator(
      'p:has-text("AM"), p:has-text("PM"), p:has-text("—")'
    );

    const timestampCount = await timestampSelector.count();
    expect(timestampCount).toBeGreaterThan(0);

    const timestamps: string[] = [];
    for (let i = 0; i < timestampCount; i++) {
      const text = await timestampSelector.nth(i).textContent();
      if (text && text !== '—' && text.trim() !== '') {
        timestamps.push(text.trim());
      }
    }

    // Verify we have timestamps to check
    expect(timestamps.length).toBeGreaterThan(0);

    // All timestamps should follow the same format: "MMM D H:MM AM/PM"
    // Examples: "Jan 15 2:30 PM", "Dec 3 11:45 AM"
    const timestampPattern = /^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2} \d{1,2}:\d{2} (AM|PM)$/;

    for (const timestamp of timestamps) {
      expect(timestamp).toMatch(timestampPattern);
    }

    // Extract and compare session start/end times with event and snapshot timestamps
    // to ensure they're using the same timezone semantics
    const startedAtText = await authenticatedPage
      .locator('p:has-text("Started") + p')
      .textContent();
    const endedAtText = await authenticatedPage
      .locator('p:has-text("Ended") + p')
      .textContent();

    if (startedAtText && startedAtText !== '—') {
      expect(startedAtText.trim()).toMatch(timestampPattern);
    }

    if (endedAtText && endedAtText !== 'Active') {
      expect(endedAtText.trim()).toMatch(timestampPattern);
    }

    // Check snapshot timestamps if any exist
    const snapshotTimestamps = authenticatedPage.locator(
      '.glass-card p:has-text("Created")'
    );
    const snapshotCount = await snapshotTimestamps.count();

    for (let i = 0; i < snapshotCount; i++) {
      const snapshotText = await snapshotTimestamps.nth(i).textContent();
      if (snapshotText && snapshotText !== '—') {
        expect(snapshotText.trim()).toMatch(timestampPattern);
      }
    }

    // Check event timeline timestamps if any exist
    const eventTimestamps = authenticatedPage.locator(
      '.glass-card span:has-text("AM"), .glass-card span:has-text("PM")'
    );
    const eventCount = await eventTimestamps.count();

    for (let i = 0; i < eventCount; i++) {
      const eventText = await eventTimestamps.nth(i).textContent();
      if (eventText && eventText !== '—') {
        expect(eventText.trim()).toMatch(timestampPattern);
      }
    }
  });

  test('should handle sessions without events gracefully', async ({ authenticatedPage }) => {
    // Get or create the current session (will create if none exists)
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));

    const currentResponse = await authenticatedPage.request.get('/api/sessions/current/', {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });

    expect(currentResponse.ok()).toBeTruthy();
    const sessionData = await currentResponse.json();
    const sessionId = sessionData.id;

    // Navigate directly to the session URL (note: sessions is plural in the route)
    await authenticatedPage.goto(`/sessions/${sessionId}`);
    await authenticatedPage.waitForLoadState('networkidle');

    // Page should load without errors even with no events/snapshots
    await expect(authenticatedPage.locator('h1:has-text("Session Details")')).toBeVisible();

    // Timestamps should still be formatted correctly
    const startedAtText = await authenticatedPage
      .locator('p:has-text("Started") + p')
      .textContent();

    expect(startedAtText).toBeTruthy();
    if (startedAtText) {
      expect(startedAtText).not.toBe('—');

      const timestampPattern = /^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2} \d{1,2}:\d{2} (AM|PM)$/;
      expect(startedAtText.trim()).toMatch(timestampPattern);
    }
  });
});
