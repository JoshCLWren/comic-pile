import { test, expect } from '@playwright/test';

test.describe('D10 Geometry Visual Regression', () => {
  test('D10 shape verification', async ({ page }) => {
    await page.goto('http://localhost:8000/rate');
    await page.waitForSelector('.dice-3d canvas', { timeout: 10000 });
    await page.waitForTimeout(1000);

    const diceContainer = page.locator('.dice-3d').first();
    await expect(diceContainer).toHaveScreenshot('d10-shape.png', {
      maxDiffPixels: 100,
      threshold: 0.15,
    });
  });
});
