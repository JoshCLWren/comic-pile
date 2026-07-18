import { test, expect } from './fixtures';

test.describe('Issue #320: Mobile Safari Overscroll Prevention', () => {
  test('viewport meta tag includes viewport-fit=cover', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('meta[name="viewport"]')).toHaveAttribute(
      'content',
      /viewport-fit=cover/,
    );
  });

  test('overscroll-prevention CSS is loaded in stylesheets', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('#root')).toBeVisible();
    await page.waitForFunction(() => document.readyState === 'complete');

    const hasOverscrollBehavior = await page.evaluate(() => {
      const stylesheets = Array.from(document.styleSheets);
      return stylesheets.some((sheet: CSSStyleSheet) => {
        try {
          const rules = Array.from(sheet.cssRules || sheet.rules || []);
          return rules.some((rule: CSSRule) => 
            rule instanceof CSSStyleRule && 
            (rule as CSSStyleRule).cssText.includes('overscroll-behavior')
          );
        } catch {
          return false;
        }
      });
    });

    expect(hasOverscrollBehavior).toBe(true);
  });
});
