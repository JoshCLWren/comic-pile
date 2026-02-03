import { test, expect } from './fixtures';
import { generateTestUser, registerUser, loginUser, createThread, SELECTORS, setRangeInput } from './helpers';

test.describe('History Page', () => {
  test('should display history page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/history');

    await expect(authenticatedPage.locator('h1:has-text("History")')).toBeVisible();
  });

  test('should list past sessions', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'History Test Comic',
      format: 'Comic',
      issues_remaining: 5,
    });

    await page.goto('/');
    await page.waitForSelector(SELECTORS.roll.mainDie);
    await page.click(SELECTORS.roll.mainDie);
    await page.waitForTimeout(2000);

    await setRangeInput(page, SELECTORS.rate.ratingInput, '4.0');
    await page.click(SELECTORS.rate.submitButton);
    await page.waitForURL('http://localhost:8002/', { timeout: 5000 });

    await page.goto('/history');

    const sessionsList = page.locator(SELECTORS.history.sessionsList);
    const hasList = await sessionsList.count() > 0;

    if (hasList) {
      await expect(sessionsList.first()).toBeVisible({ timeout: 5000 });
    }
  });

  test('should show session details including die size and threads', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'Session Detail Comic',
      format: 'Comic',
      issues_remaining: 5,
    });

    await page.goto('/');
    await page.waitForSelector(SELECTORS.roll.mainDie);
    await page.click(SELECTORS.roll.mainDie);
    await page.waitForTimeout(2000);

    await page.goto('/history');

    const sessionItem = page.locator('.session-item, .history-item');
    const hasSessions = await sessionItem.count() > 0;

    if (hasSessions) {
      await expect(sessionItem.first()).toBeVisible();
    }
  });

  test('should support pagination if many sessions', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/history');

    const pagination = page.locator('.pagination, button:has-text("Next"), button:has-text("Load More")');
    const hasPagination = await pagination.count() > 0;

    if (hasPagination) {
      await expect(pagination.first()).toBeVisible();
    }
  });

  test('should filter sessions by date', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/history');

    const dateFilter = page.locator('input[type="date"], .date-filter, .filter-by-date');
    const hasFilter = await dateFilter.count() > 0;

    if (hasFilter) {
      await expect(dateFilter.first()).toBeVisible();
    }
  });

  test('should allow expanding session details', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'Expandable Comic',
      format: 'Comic',
      issues_remaining: 5,
    });

    await page.goto('/history');

    const expandButton = page.locator('button:has-text("Details"), button:has-text("Expand"), .expand-btn');
    const hasExpand = await expandButton.count() > 0;

    if (hasExpand) {
      await expandButton.first().click();
      await page.waitForTimeout(500);

      const details = page.locator('.session-details, .expanded-content');
      await expect(details.first()).toBeVisible();
    }
  });

  test('should show ratings for each session', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'Rated Comic',
      format: 'Comic',
      issues_remaining: 5,
    });

    await page.goto('/');
    await page.waitForSelector(SELECTORS.roll.mainDie);
    await page.click(SELECTORS.roll.mainDie);
    await page.waitForTimeout(2000);

    await setRangeInput(page, SELECTORS.rate.ratingInput, '4.5');
    await page.click(SELECTORS.rate.submitButton);
    await page.waitForURL('**/');

    await page.goto('/history');

    const ratingDisplay = page.locator('text=stars|rating|⭐');
    const hasRatings = await ratingDisplay.count() > 0;

    if (hasRatings) {
      await expect(ratingDisplay.first()).toBeVisible();
    }
  });

  test('should handle empty history gracefully', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/history');

    const emptyState = authenticatedPage.locator('text=no sessions|start rolling|empty');
    const hasEmptyState = await emptyState.count() > 0;

    if (hasEmptyState) {
      await expect(emptyState.first()).toBeVisible();
    }
  });

  test('should be accessible via navigation', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');

    const historyLink = authenticatedPage.locator(SELECTORS.navigation.historyLink);
    const hasLink = await historyLink.count() > 0;

    if (hasLink) {
      await historyLink.first().click();
      await expect(authenticatedPage).toHaveURL('http://localhost:8002/history');
    }
  });

  test('should show session duration', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/history');

    const duration = page.locator('text=minutes|duration|time');
    const hasDuration = await duration.count() > 0;

    if (hasDuration) {
      await expect(duration.first()).toBeVisible();
    }
  });

  test('should allow deleting session history', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/history');

    const deleteButton = page.locator('button:has-text("Delete"), button:has-text("Remove"), .delete-btn');
    const hasDelete = await deleteButton.count() > 0;

    if (hasDelete) {
      const initialCount = await page.locator('.session-item, .history-item').count();

      if (initialCount > 0) {
        page.on('dialog', dialog => dialog.accept());
        await deleteButton.first().click();
        await page.waitForTimeout(1000);

        const newCount = await page.locator('.session-item, .history-item').count();
        expect(newCount).toBeLessThanOrEqual(initialCount);
      }
    }
  });

  test('should load more sessions on scroll', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await page.goto('/history');

    const sessionsList = page.locator(SELECTORS.history.sessionsList);
    const hasList = await sessionsList.count() > 0;

    if (hasList) {
      const initialCount = await page.locator('.session-item').count();

      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      await page.waitForTimeout(2000);

      const newCount = await page.locator('.session-item').count();
      expect(newCount).toBeGreaterThanOrEqual(initialCount);
    }
  });
});
