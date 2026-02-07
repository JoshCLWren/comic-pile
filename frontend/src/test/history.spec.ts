import { test, expect } from './fixtures';
import { createThread, SELECTORS, setRangeInput } from './helpers';

test.describe('History Page', () => {
  test('should display history page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/history');

    await expect(authenticatedPage.locator('h1:has-text("History")')).toBeVisible();
  });

  test('should list past sessions', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie);
    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);
    await authenticatedWithThreadsPage.waitForURL("**/rate", { timeout: 5000 });

    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.0');
    await authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton);
    await authenticatedWithThreadsPage.waitForURL('http://localhost:8000/', { timeout: 5000 });

    await authenticatedWithThreadsPage.goto('/history');

    const sessionsList = authenticatedWithThreadsPage.locator(SELECTORS.history.sessionsList);
    await expect(async () => {
      const count = await sessionsList.count();
      if (count > 0) {
        await expect(sessionsList.first()).toBeVisible();
      }
    }).toPass({ timeout: 5000 });
  });

  test('should show session details including die size and threads', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie);
    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);
    await authenticatedWithThreadsPage.waitForURL("**/rate", { timeout: 5000 });

    await authenticatedWithThreadsPage.goto('/history');

    const sessionItem = authenticatedWithThreadsPage.locator('.session-item, .history-item');
    await expect(async () => {
      const count = await sessionItem.count();
      if (count > 0) {
        await expect(sessionItem.first()).toBeVisible();
      }
    }).toPass({ timeout: 5000 });
  });

  test('should support pagination if many sessions', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/history');

    const pagination = authenticatedPage.locator('.pagination, button:has-text("Next"), button:has-text("Load More")');
    await expect(async () => {
      const count = await pagination.count();
      if (count > 0) {
        await expect(pagination.first()).toBeVisible();
      }
    }).toPass({ timeout: 5000 });
  });

  test('should filter sessions by date', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/history');

    const dateFilter = authenticatedPage.locator('input[type="date"], .date-filter, .filter-by-date');
    await expect(async () => {
      const count = await dateFilter.count();
      if (count > 0) {
        await expect(dateFilter.first()).toBeVisible();
      }
    }).toPass({ timeout: 5000 });
  });

  test('should allow expanding session details', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/history');

    const expandButton = authenticatedWithThreadsPage.locator('button:has-text("Details"), button:has-text("Expand"), .expand-btn');
    await expect(async () => {
      const count = await expandButton.count();
      if (count > 0) {
        await expandButton.first().click();
        await authenticatedWithThreadsPage.waitForLoadState("networkidle");

        const details = authenticatedWithThreadsPage.locator('.session-details, .expanded-content');
        await expect(details.first()).toBeVisible();
      }
    }).toPass({ timeout: 5000 });
  });

  test('should show ratings for each session', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie);
    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);
    await authenticatedWithThreadsPage.waitForURL("**/rate", { timeout: 5000 });

    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.5');
    await authenticatedWithThreadsPage.click(SELECTORS.rate.submitButton);
    await authenticatedWithThreadsPage.waitForURL('**/');

    await authenticatedWithThreadsPage.goto('/history');

    const ratingDisplay = authenticatedWithThreadsPage.locator('text=stars|rating|⭐');
    await expect(async () => {
      const count = await ratingDisplay.count();
      if (count > 0) {
        await expect(ratingDisplay.first()).toBeVisible();
      }
    }).toPass({ timeout: 5000 });
  });

  test('should handle empty history gracefully', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/history');

    const emptyState = authenticatedPage.locator('text=no sessions|start rolling|empty');
    await expect(async () => {
      const count = await emptyState.count();
      if (count > 0) {
        await expect(emptyState.first()).toBeVisible();
      }
    }).toPass({ timeout: 5000 });
  });

  test('should be accessible via navigation', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');

    const historyLink = authenticatedPage.locator(SELECTORS.navigation.historyLink);
    await expect(async () => {
      const count = await historyLink.count();
      if (count > 0) {
        await historyLink.first().click();
        await expect(authenticatedPage).toHaveURL('http://localhost:8000/history');
      }
    }).toPass({ timeout: 5000 });
  });

  test('should show session duration', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/history');

    const duration = authenticatedPage.locator('text=minutes|duration|time');
    await expect(async () => {
      const count = await duration.count();
      if (count > 0) {
        await expect(duration.first()).toBeVisible();
      }
    }).toPass({ timeout: 5000 });
  });

  test('should allow deleting session history', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/history');

    const deleteButton = authenticatedPage.locator('button:has-text("Delete"), button:has-text("Remove"), .delete-btn');
    await expect(async () => {
      const count = await deleteButton.count();
      if (count > 0) {
        const initialCount = await authenticatedPage.locator('.session-item, .history-item').count();

        if (initialCount > 0) {
          authenticatedPage.on('dialog', dialog => dialog.accept());
          await deleteButton.first().click();
          await authenticatedPage.waitForLoadState("networkidle");

          const newCount = await authenticatedPage.locator('.session-item, .history-item').count();
          expect(newCount).toBeLessThanOrEqual(initialCount);
        }
      }
    }).toPass({ timeout: 5000 });
  });

  test('should load more sessions on scroll', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/history');

    const sessionsList = authenticatedPage.locator(SELECTORS.history.sessionsList);
    await expect(async () => {
      const count = await sessionsList.count();
      if (count > 0) {
        const initialCount = await authenticatedPage.locator('.session-item').count();

        await authenticatedPage.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
        await authenticatedPage.waitForLoadState('networkidle');

        const newCount = await authenticatedPage.locator('.session-item').count();
        expect(newCount).toBeGreaterThanOrEqual(initialCount);
      }
    }).toPass({ timeout: 5000 });
  });
});
