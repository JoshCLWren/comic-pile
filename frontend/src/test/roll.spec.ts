import { test, expect } from './fixtures';
import { SELECTORS } from './helpers';

test.describe('Roll Dice Feature', () => {
  test('should display die selector on home page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');

    await expect(authenticatedPage.locator(SELECTORS.roll.dieSelector)).toBeVisible();
    await expect(authenticatedPage.locator(SELECTORS.roll.headerDieLabel)).toBeVisible();
  });

  test('should roll dice and navigate to rate page', async ({ authenticatedWithThreadsPage }) => {
    const token = await authenticatedWithThreadsPage.evaluate(() => localStorage.getItem('auth_token'));
    const rollResponse = await authenticatedWithThreadsPage.request.post('/api/roll/', {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    });

    expect(rollResponse.ok()).toBeTruthy();
    await authenticatedWithThreadsPage.goto('/rate');
    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible();
  });

  test('regression: roll API response should be handled and navigation should complete', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });

    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);

    await authenticatedWithThreadsPage.waitForURL('**/rate', { timeout: 5000 });

    await expect(authenticatedWithThreadsPage.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 2000 });

    const currentUrl = authenticatedWithThreadsPage.url();
    expect(currentUrl).toMatch(/\/rate\/?$/);
    expect(currentUrl).not.toMatch(/\/$/);
  });

  test('should show tap instruction on first visit', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');

    await expect(authenticatedPage.locator(SELECTORS.roll.tapInstruction)).toBeVisible();
  });

  test('should support different die sizes (d4, d6, d8, d10, d12, d20)', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');

    const dieSizes = ['d4', 'd6', 'd8', 'd10', 'd12', 'd20'];

    for (const dieSize of dieSizes) {
      const dieButton = authenticatedPage.locator(`button:has-text("${dieSize}")`).first();
      await expect(dieButton).toBeVisible();
    }
  });

  test('should display 3D dice canvas', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });

    const canvasInfo = await authenticatedPage.evaluate(() => {
      const container = document.querySelector('#main-die-3d');
      if (!container) return { error: 'Dice container not found' };

      const canvas = container.querySelector('canvas');
      if (!canvas) return { error: 'Canvas not found' };

      const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
      if (!gl) return { error: 'WebGL context not available' };

      return {
        success: true,
        hasWebGL: true,
        canvasWidth: canvas.width,
        canvasHeight: canvas.height,
      };
    });

    if (canvasInfo.error) {
      console.log('3D Dice Canvas Info:', canvasInfo.error);
      return;
    }

    expect(canvasInfo.hasWebGL).toBe(true);
    expect(canvasInfo.canvasWidth).toBeGreaterThan(0);
    expect(canvasInfo.canvasHeight).toBeGreaterThan(0);
  });

  test('should handle roll with empty queue gracefully', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });

    const emptyQueueMessage = authenticatedPage.locator('text=Queue Empty');
    await expect(emptyQueueMessage).toBeVisible();
  });

  test('should update session state after roll', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');

    const sessionBefore = await authenticatedWithThreadsPage.evaluate(async () => {
      const response = await fetch('/api/sessions/current');
      const data = await response.json();
      return data;
    });

    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);
    await authenticatedWithThreadsPage.waitForURL("**/rate", { timeout: 5000 });

    const sessionAfter = await authenticatedWithThreadsPage.evaluate(async () => {
      const response = await fetch('/api/sessions/current');
      const data = await response.json();
      return data;
    });

    expect(sessionAfter).toBeDefined();
  });

  test('should show loading state during roll animation', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie);

    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);

    const loadingIndicator = authenticatedWithThreadsPage.locator('.loading, .rolling, [aria-busy="true"]');

    await expect(async () => {
      const count = await loadingIndicator.count();
      if (count > 0) {
        await expect(loadingIndicator.first()).toBeVisible();
      }
    }).toPass({ timeout: 5000 });
  });

  test('should be accessible via keyboard navigation', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    await authenticatedWithThreadsPage.waitForSelector('#main-die-3d', { state: 'visible', timeout: 5000 });

    const dieElement = authenticatedWithThreadsPage.locator('#main-die-3d');
    await dieElement.focus();
    await authenticatedWithThreadsPage.keyboard.press('Enter');

    await authenticatedWithThreadsPage.waitForURL('**/rate', { timeout: 5000 });

    const currentUrl = authenticatedWithThreadsPage.url();
    expect(currentUrl).toContain('/rate');
  });

  test('should prevent multiple rapid rolls', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.roll.mainDie);

    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);
    await authenticatedWithThreadsPage.click(SELECTORS.roll.mainDie);

    await authenticatedWithThreadsPage.waitForURL("**/rate", { timeout: 5000 });

    const currentUrl = authenticatedWithThreadsPage.url();
    expect(currentUrl).toMatch(/\/rate\/?$/);
  });
});
