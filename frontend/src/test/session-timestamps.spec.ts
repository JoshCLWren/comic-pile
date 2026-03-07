import { test, expect } from './fixtures';
import { SELECTORS, setRangeInput } from './helpers';

test.describe('Session Timestamp Consistency (Issue #245)', () => {
  test('should display consistently formatted timestamps on Session Details page', async ({ authenticatedWithThreadsPage }) => {
    // First, create a session with some activity
    await authenticatedWithThreadsPage.goto('/');

    const mainDieExists = await authenticatedWithThreadsPage.locator(SELECTORS.roll.mainDie).count();
    if (mainDieExists === 0) {
      test.skip(true, 'No main die found - no threads available');
      return;
    }

    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie);

    // Roll the die to create an event
    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 5000 });

    // Rate to create another event
    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.0');
    await authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton);
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    // Navigate to history to get a session ID
    await authenticatedWithThreadsPage.goto('/history');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    // Find the first session link and navigate to it
    const sessionLink = authenticatedWithThreadsPage.locator('a[href^="/session/"]').first();
    const sessionCount = await sessionLink.count();

    if (sessionCount === 0) {
      test.skip(true, 'No sessions found to test');
      return;
    }

    await sessionLink.click();
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    // Wait for Session Details page to load
    await expect(authenticatedWithThreadsPage.locator('h1:has-text("Session Details")')).toBeVisible();

    // Collect all timestamp text from the page
    const timestampSelector = authenticatedWithThreadsPage.locator(
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
    const startedAtText = await authenticatedWithThreadsPage
      .locator('p:has-text("Started") + p')
      .textContent();
    const endedAtText = await authenticatedWithThreadsPage
      .locator('p:has-text("Ended") + p')
      .textContent();

    if (startedAtText && startedAtText !== '—') {
      expect(startedAtText.trim()).toMatch(timestampPattern);
    }

    if (endedAtText && endedAtText !== 'Active') {
      expect(endedAtText.trim()).toMatch(timestampPattern);
    }

    // Check snapshot timestamps if any exist
    const snapshotTimestamps = authenticatedWithThreadsPage.locator(
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
    const eventTimestamps = authenticatedWithThreadsPage.locator(
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
    // Navigate to history
    await authenticatedPage.goto('/history');
    await authenticatedPage.waitForLoadState('networkidle');

    // Look for any existing session
    const sessionLink = authenticatedPage.locator('a[href^="/session/"]').first();
    const sessionCount = await sessionLink.count();

    if (sessionCount > 0) {
      await sessionLink.first().click();
      await authenticatedPage.waitForLoadState('networkidle');

      // Page should load without errors even if no events/snapshots
      await expect(authenticatedPage.locator('h1:has-text("Session Details")')).toBeVisible();

      // Timestamps should still be formatted correctly if present
      const startedAtText = await authenticatedPage
        .locator('p:has-text("Started") + p')
        .textContent();

      if (startedAtText && startedAtText !== '—') {
        const timestampPattern = /^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2} \d{1,2}:\d{2} (AM|PM)$/;
        expect(startedAtText.trim()).toMatch(timestampPattern);
      }
    }
  });
});
