import { expect, test } from './fixtures';
import { waitForQueueReady } from './helpers';

test.describe('Queue interaction containment (#625)', () => {
  test('keeps mobile cards clipped while exposing actions through the shared overlay', async ({ authenticatedWithLargeQueuePage }) => {
    const page = authenticatedWithLargeQueuePage;

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    const firstCard = page.locator('[data-testid="queue-thread-item"]').first();
    await expect(firstCard).toBeVisible();
    await expect
      .poll(() => firstCard.evaluate((element) => getComputedStyle(element).overflow))
      .toBe('hidden');

    const actionsTrigger = firstCard.getByRole('button', { name: 'Thread actions' });
    await expect(actionsTrigger).toBeVisible();
    await expect(actionsTrigger).toHaveAttribute('aria-expanded', 'false');

    await actionsTrigger.click();

    const menu = page.getByRole('menu', { name: 'Thread actions' });
    await expect(menu).toBeVisible();
    await expect(actionsTrigger).toHaveAttribute('aria-expanded', 'true');
    await expect(menu.getByRole('menuitem')).toHaveCount(6);
    await expect(menu.getByRole('menuitem', { name: 'Edit thread' })).toBeVisible();
    await expect(menu.getByRole('menuitem', { name: 'Manage dependencies' })).toBeVisible();
    await expect(menu.getByRole('menuitem', { name: 'Delete thread' })).toBeVisible();

    const overlayLayer = menu.locator('xpath=..');
    await expect(overlayLayer).toHaveAttribute('data-overlay-root', 'true');
    await expect(overlayLayer).toHaveAttribute('data-overlay-layer', 'menu');

    const menuEscapesCard = await menu.evaluate((element, card) => !card.contains(element), await firstCard.elementHandle());
    expect(menuEscapesCard).toBe(true);

    const menuBox = await menu.boundingBox();
    expect(menuBox).not.toBeNull();
    expect(menuBox!.x).toBeGreaterThanOrEqual(0);
    expect(menuBox!.y).toBeGreaterThanOrEqual(0);
    expect(menuBox!.x + menuBox!.width).toBeLessThanOrEqual(390);
    expect(menuBox!.y + menuBox!.height).toBeLessThanOrEqual(844);
  });

  test('vertical mobile scrolling leaves a resting card unshifted', async ({ authenticatedWithLargeQueuePage }) => {
    const page = authenticatedWithLargeQueuePage;

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    const firstCard = page.locator('[data-testid="queue-thread-item"]').first();
    const foreground = firstCard.locator(':scope > div').nth(1);
    await expect(firstCard).toBeVisible();

    await expect
      .poll(() => foreground.evaluate((element) => getComputedStyle(element).transform))
      .toBe('matrix(1, 0, 0, 1, 0, 0)');

    await page.mouse.wheel(0, 500);

    await expect
      .poll(() => foreground.evaluate((element) => getComputedStyle(element).transform))
      .toBe('matrix(1, 0, 0, 1, 0, 0)');
    await expect
      .poll(() => firstCard.evaluate((element) => getComputedStyle(element).overflow))
      .toBe('hidden');
  });
});
