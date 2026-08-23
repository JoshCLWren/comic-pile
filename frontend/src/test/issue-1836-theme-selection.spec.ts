import { expect, test } from './fixtures';
import type { Page } from '@playwright/test';
import { setupAuthenticatedPage } from './helpers';

/**
 * Theme selection must visibly change the UI (#1836).
 *
 * The user reported that changing themes "does nothing", with a 503 on the
 * preferences PATCH. Two things were wrong:
 *   1. The dominant chrome (page background, nav bar, glass panels, body text)
 *      read static :root tokens, never the per-theme --theme-* values, so the
 *      page background stayed the same regardless of selection.
 *   2. The frontend now applies and mirrors the choice locally before any
 *      server sync, so a transient 503 must never block the visual change.
 *
 * These tests prove that selecting a theme updates the document theme and the
 * real computed design tokens that drive the page background.
 */

const THEME_TOKENS: Record<string, { bgMain: string }> = {
  classic: { bgMain: '#1a1410' },
  'ink-gold': { bgMain: '#15100c' },
  'command-center': { bgMain: '#0b0c1e' },
};

async function selectThemeByName(page: Page, themeId: string) {
  const appearanceGroup = page.locator('[role="group"][aria-label="Appearance"]');
  const button = appearanceGroup.getByRole('button', { name: themeId, exact: true });
  await expect(button).toBeVisible();
  await button.click();
}

test.describe('Theme selection changes the applied theme (#1836)', () => {
  test('selecting a theme updates the document theme attribute and background token', async ({ page }) => {
    await setupAuthenticatedPage(page);
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    // Baseline: starts on the default theme.
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'classic');

    for (const themeId of ['ink-gold', 'command-center', 'classic'] as const) {
      await selectThemeByName(page, themeId);

      // The selection is applied immediately and survives any server 503.
      await expect(page.locator('html')).toHaveAttribute('data-theme', themeId);

      // The dominant background token actually follows the selection.
      const bgMain = await page.evaluate(() =>
        window.getComputedStyle(document.documentElement).getPropertyValue('--bg-main').trim(),
      );
      expect(bgMain).toBe(THEME_TOKENS[themeId].bgMain);
    }
  });

  test('theme choice persists in localStorage even when the preferences PATCH fails', async ({
    page,
  }) => {
    await setupAuthenticatedPage(page);
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    // Force every preferences request to fail like the reported 503 outage.
    await page.route('**/users/me/preferences', (route) => route.fulfill({ status: 503, body: '' }));

    await selectThemeByName(page, 'command-center');

    await expect(page.locator('html')).toHaveAttribute('data-theme', 'command-center');
    const stored = await page.evaluate(() => localStorage.getItem('comic-pile-theme'));
    expect(stored).toBe('command-center');

    // Reload: the locally mirrored choice is restored without a server round trip.
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'command-center');
  });
});
