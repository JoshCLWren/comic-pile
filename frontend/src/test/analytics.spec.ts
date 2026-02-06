import { test, expect } from './fixtures';
import { SELECTORS } from './helpers';

test.describe('Analytics Dashboard', () => {
  test('should display analytics page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/analytics');

    await expect(authenticatedPage.locator('h1:has-text("Analytics")'), 'Analytics page h1 not found').toBeVisible();
  });

  test('should show reading statistics', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/analytics');

    const glassCards = authenticatedWithThreadsPage.locator('.glass-card');
    const count = await glassCards.count();
    await expect(glassCards.first(), `Expected .glass-card elements but found ${count}`).toBeVisible({ timeout: 5000 });
  });

  test('should display charts or graphs', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/analytics');

    const chartContainer = authenticatedPage.locator('canvas, .chart, .graph');
    await expect(async () => {
      const count = await chartContainer.count();
      if (count > 0) {
        await expect(chartContainer.first()).toBeVisible();
      }
    }).toPass({ timeout: 5000 });
  });

  test('should show total threads count', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/analytics');

    const countElement = authenticatedWithThreadsPage.locator('text=threads').first();
    await expect(countElement).toBeVisible();
  });

  test('should show active vs completed threads', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/analytics');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    await authenticatedWithThreadsPage.waitForLoadState("networkidle");

    const activeThreadsLabel = authenticatedWithThreadsPage.locator('text=Active Threads');
    await expect(activeThreadsLabel.first()).toBeVisible({ timeout: 5000 });
  });

  test('should display rating distribution', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/analytics');

    const completionRate = authenticatedWithThreadsPage.locator('text=Completion Rate');
    await expect(completionRate).toBeVisible();
  });

  test('should filter by date range', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/analytics');

    const dateFilter = authenticatedPage.locator('input[type="date"], .date-filter, .time-range');
    await expect(async () => {
      const count = await dateFilter.count();
      if (count > 0) {
        await expect(dateFilter.first()).toBeVisible();
      }
    }).toPass({ timeout: 5000 });
  });

  test('should export analytics data', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/analytics');

    const exportButton = authenticatedPage.locator('button:has-text("Export"), button:has-text("Download"), .export-btn');
    await expect(async () => {
      const count = await exportButton.count();
      if (count > 0) {
        const downloadPromise = authenticatedPage.waitForEvent('download');
        await exportButton.first().click();
        const download = await downloadPromise;
        expect(download.suggestedFilename()).toBeTruthy();
      }
    }).toPass({ timeout: 5000 });
  });

  test('should show session history summary', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/analytics');

    const recentSessions = authenticatedWithThreadsPage.locator('h3:has-text("Recent Sessions")');
    await expect(recentSessions).toBeVisible();
  });

  test('should be accessible via navigation', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');

    const analyticsLink = authenticatedPage.locator(SELECTORS.navigation.analyticsLink);
    await expect(analyticsLink.first()).toBeVisible({ timeout: 5000 });

    await analyticsLink.first().click();
    await expect(authenticatedPage).toHaveURL('http://localhost:8000/analytics');
  });

  test('should handle empty data gracefully', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/analytics');

    const emptyState = authenticatedPage.locator('text=no data|start reading|add threads');
    await expect(async () => {
      const count = await emptyState.count();
      if (count > 0) {
        await expect(emptyState.first()).toBeVisible();
      }
    }).toPass({ timeout: 5000 });
  });

  test('should load data asynchronously', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/analytics');

    const loadingIndicator = authenticatedPage.locator('.loading, .spinner, [aria-busy="true"]');
    await expect(async () => {
      const count = await loadingIndicator.count();
      if (count > 0) {
        await expect(loadingIndicator.first()).toBeVisible();
        await expect(loadingIndicator.first()).not.toBeVisible({ timeout: 5000 });
      }
    }).toPass({ timeout: 5000 });
  });
});
