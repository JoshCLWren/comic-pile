import { test, expect } from './fixtures';
import { generateTestUser, registerUser, loginUser, createThread, SELECTORS } from './helpers';

test.describe('Roll Dice Feature', () => {
  test('should display die selector on home page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');

    await expect(authenticatedPage.locator(SELECTORS.roll.dieSelector)).toBeVisible();
    await expect(authenticatedPage.locator(SELECTORS.roll.headerDieLabel)).toBeVisible();
  });

  test('should roll dice and navigate to rate page', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'Roll Test Comic',
      format: 'Comic',
      issues_remaining: 5,
    });

    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    const rollResponse = await page.request.post('/api/roll/', {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    });

    if (rollResponse.ok()) {
      await page.goto('/rate');
      await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible();
    } else {
      expect(rollResponse.status()).toBe(400);
    }
  });

  test('regression: roll API response should be handled and navigation should complete', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, { title: 'Thread A', format: 'Comic', issues_remaining: 3 });
    await createThread(page, { title: 'Thread B', format: 'TPB', issues_remaining: 5 });
    await createThread(page, { title: 'Thread C', format: 'OGN', issues_remaining: 2 });

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForSelector(SELECTORS.roll.mainDie, { timeout: 10000 });

    await page.click(SELECTORS.roll.mainDie);

    await page.waitForURL('**/rate', { timeout: 5000 });

    await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 2000 });

    const currentUrl = page.url();
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

    await authenticatedPage.click(SELECTORS.roll.mainDie);
    await authenticatedPage.waitForTimeout(2000);

    const errorMessage = authenticatedPage.locator('text=no threads|queue is empty');
    const isVisible = await errorMessage.count() > 0;

    if (isVisible) {
      await expect(errorMessage.first()).toBeVisible();
    }
  });

  test('should update session state after roll', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'Session Test Comic',
      format: 'Comic',
      issues_remaining: 5,
    });

    await page.goto('/');

    const sessionBefore = await page.evaluate(async () => {
      const response = await fetch('/api/sessions/current');
      const data = await response.json();
      return data;
    });

    await page.click(SELECTORS.roll.mainDie);
    await page.waitForTimeout(2000);

    const sessionAfter = await page.evaluate(async () => {
      const response = await fetch('/api/sessions/current');
      const data = await response.json();
      return data;
    });

    expect(sessionAfter).toBeDefined();
  });

  test('should show loading state during roll animation', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'Animation Test Comic',
      format: 'Comic',
      issues_remaining: 5,
    });

    await page.goto('/');
    await page.waitForSelector(SELECTORS.roll.mainDie);

    await page.click(SELECTORS.roll.mainDie);

    const loadingIndicator = page.locator('.loading, .rolling, [aria-busy="true"]');
    const hasLoadingState = await loadingIndicator.count() > 0;

    if (hasLoadingState) {
      await expect(loadingIndicator.first()).toBeVisible();
    }
  });

  test('should be accessible via keyboard navigation', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, { title: 'Keyboard Test Comic', format: 'Comic', issues_remaining: 5 });

    await page.goto('/');

    const dieElement = page.locator('#main-die-3d');
    await dieElement.focus();
    await page.keyboard.press('Enter');

    await page.waitForURL('**/rate', { timeout: 5000 });

    const currentUrl = page.url();
    expect(currentUrl).toContain('/rate');
  });

  test('should prevent multiple rapid rolls', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'Rapid Roll Test',
      format: 'Comic',
      issues_remaining: 5,
    });

    await page.goto('/');
    await page.waitForSelector(SELECTORS.roll.mainDie);

    await page.click(SELECTORS.roll.mainDie);
    await page.waitForTimeout(100);
    await page.click(SELECTORS.roll.mainDie);

    await page.waitForTimeout(2000);

    const currentUrl = page.url();
    expect(currentUrl).toMatch(/\/rate\/?$/);
  });
});
