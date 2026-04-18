import { test, expect } from './fixtures';
import { SELECTORS, setRangeInput, submitRatingAndDismissReviewIfShown } from './helpers';

test.describe('Issue 291: Finish Session Button', () => {
  test('should have a "Finish Session" button in rating view', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    const firstThreadCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await expect(firstThreadCard).toBeVisible({ timeout: 10000 });
    await firstThreadCard.click();
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });

    const finishSessionButton = authenticatedWithThreadsPage.locator('button:has-text("Finish Session")');
    await expect(finishSessionButton).toBeVisible({ timeout: 5000 });
  });

  test('should finish session when "Finish Session" button is clicked', async ({ authenticatedWithThreadsPage }) => {
    const token = await authenticatedWithThreadsPage.evaluate(() => 
      localStorage.getItem('auth_token') ?? 
      (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN
    );
    expect(token).toBeTruthy();

    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    const firstThreadCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await expect(firstThreadCard).toBeVisible({ timeout: 10000 });
    await firstThreadCard.click();
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });

    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.0');

    const finishSessionButton = authenticatedWithThreadsPage.locator('button:has-text("Finish Session")');
    
    await submitRatingAndDismissReviewIfShown(authenticatedWithThreadsPage, () =>
      finishSessionButton.click(),
    );

    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    const sessionResponse = await authenticatedWithThreadsPage.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(sessionResponse.ok()).toBeTruthy();
    const session = await sessionResponse.json();

    expect(session.active_thread).toBeNull();
    expect(session.pending_thread_id).toBeNull();
  });

  test('should send finish_session=true when Finish Session button is clicked', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    const firstThreadCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await expect(firstThreadCard).toBeVisible({ timeout: 10000 });
    await firstThreadCard.click();
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });

    await setRangeInput(authenticatedWithThreadsPage, SELECTORS.rate.ratingInput, '4.0');

    const finishSessionButton = authenticatedWithThreadsPage.locator('button:has-text("Finish Session")');
    
    let requestData: unknown = null;
    await authenticatedWithThreadsPage.route('**/api/rate/**', async (route) => {
      const request = route.request();
      requestData = request.postData();
      await route.continue();
    });

    await submitRatingAndDismissReviewIfShown(authenticatedWithThreadsPage, () =>
      finishSessionButton.click(),
    );
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    expect(requestData).toBeTruthy();
    const parsedData = JSON.parse(requestData as string);
    expect(parsedData.finish_session).toBe(true);
  });
});
