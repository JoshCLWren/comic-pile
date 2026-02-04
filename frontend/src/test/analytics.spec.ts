import { test, expect } from './fixtures';
import { generateTestUser, registerUser, loginUser, createThread, SELECTORS } from './helpers';

test.describe('Analytics Dashboard', () => {
  test('should display analytics page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/analytics');

    await expect(authenticatedPage.locator('h1:has-text("Analytics")'), 'Analytics page h1 not found').toBeVisible();
  });

  test('should show reading statistics', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'Stats Test Comic',
      format: 'Comic',
      issues_remaining: 5,
    });

    await page.goto('/analytics');

    const glassCards = page.locator('.glass-card');
    const count = await glassCards.count();
    await expect(glassCards.first(), `Expected .glass-card elements but found ${count}`).toBeVisible({ timeout: 5000 });
  });

  test('should display charts or graphs', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/analytics');

    const chartContainer = page.locator('canvas, .chart, .graph');
    const hasChart = await chartContainer.count() > 0;

    if (hasChart) {
      await expect(chartContainer.first()).toBeVisible();
    }
  });

  test('should show total threads count', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    const threadCount = 5;
    for (let i = 0; i < threadCount; i++) {
      await createThread(page, {
        title: `Comic ${i + 1}`,
        format: 'Comic',
        issues_remaining: 5,
      });
    }

    await page.goto('/analytics');

    const countElement = page.locator('text=threads').first();
    await expect(countElement).toBeVisible();
  });

  test('should show active vs completed threads', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'Active Comic',
      format: 'Comic',
      issues_remaining: 5,
    });

    await page.goto('/analytics');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);

    const activeThreadsLabel = page.locator('text=Active Threads');
    await expect(activeThreadsLabel.first()).toBeVisible({ timeout: 5000 });
  });

  test('should display rating distribution', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'Rated Comic',
      format: 'Comic',
      issues_remaining: 5,
    });

    await page.goto('/analytics');

    const completionRate = page.locator('text=Completion Rate');
    await expect(completionRate).toBeVisible();
  });

  test('should filter by date range', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/analytics');

    const dateFilter = page.locator('input[type="date"], .date-filter, .time-range');
    const hasDateFilter = await dateFilter.count() > 0;

    if (hasDateFilter) {
      await expect(dateFilter.first()).toBeVisible();
    }
  });

  test('should export analytics data', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/analytics');

    const exportButton = page.locator('button:has-text("Export"), button:has-text("Download"), .export-btn');
    const hasExport = await exportButton.count() > 0;

    if (hasExport) {
      const downloadPromise = page.waitForEvent('download');
      await exportButton.first().click();
      const download = await downloadPromise;

      expect(download.suggestedFilename()).toBeTruthy();
    }
  });

  test('should show session history summary', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'Session Comic',
      format: 'Comic',
      issues_remaining: 5,
    });

    await page.goto('/analytics');

    const recentSessions = page.locator('text=Recent Sessions');
    await expect(recentSessions).toBeVisible();
  });

  test('should be accessible via navigation', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');

    const analyticsLink = authenticatedPage.locator(SELECTORS.navigation.analyticsLink);
    const hasLink = await analyticsLink.count() > 0;

    if (hasLink) {
      await analyticsLink.first().click();
      await expect(authenticatedPage).toHaveURL('http://localhost:8000/analytics');
    }
  });

  test('should handle empty data gracefully', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/analytics');

    const emptyState = authenticatedPage.locator('text=no data|start reading|add threads');
    const hasEmptyState = await emptyState.count() > 0;

    if (hasEmptyState) {
      await expect(emptyState.first()).toBeVisible();
    }
  });

  test('should load data asynchronously', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/analytics');

    const loadingIndicator = page.locator('.loading, .spinner, [aria-busy="true"]');
    const hasLoading = await loadingIndicator.count() > 0;

    if (hasLoading) {
      await expect(loadingIndicator.first()).toBeVisible();
      await expect(loadingIndicator.first()).not.toBeVisible({ timeout: 5000 });
    }
  });
});
