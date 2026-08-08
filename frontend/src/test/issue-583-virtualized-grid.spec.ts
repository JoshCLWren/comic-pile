import { expect } from './fixtures';
import { test } from './fixtures';
import { waitForQueueReady } from './helpers';

test.describe('Responsive multi-column virtualized grid (#583-C)', () => {
  test('renders 3 columns at desktop viewport (1280×720)', async ({ authenticatedWithLargeQueuePage }) => {
    const page = authenticatedWithLargeQueuePage;

    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    const list = page.locator('[data-testid="queue-thread-list"]');
    await expect(list).toBeVisible();

    const firstRowGrid = list.locator('[data-index="0"] > div').first();
    await expect(firstRowGrid).toBeVisible();

    const gridTemplateColumns = await firstRowGrid.evaluate((el) => {
      return getComputedStyle(el).gridTemplateColumns;
    });

    const columnCount = gridTemplateColumns.split(/\s+/).length;
    expect(columnCount).toBe(3);

    const firstRowItems = list.locator('[data-index="0"] [data-testid="queue-thread-item"]');
    await expect(firstRowItems).toHaveCount(3);

    const { rowGap, columnGap } = await firstRowGrid.evaluate((el) => {
      const cs = getComputedStyle(el);
      return { rowGap: cs.rowGap, columnGap: cs.columnGap };
    });
    expect(rowGap).toBe('16px');
    expect(columnGap).toBe('16px');
  });

  test('renders 1 column at mobile viewport (375×812)', async ({ authenticatedWithLargeQueuePage }) => {
    const page = authenticatedWithLargeQueuePage;

    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    const list = page.locator('[data-testid="queue-thread-list"]');
    await expect(list).toBeVisible();

    const firstRowItems = list.locator('[data-index="0"] [data-testid="queue-thread-item"]');
    await expect(firstRowItems).toHaveCount(1);
  });

  test('keeps an open thread action menu above the following virtual row', async ({ authenticatedWithLargeQueuePage }) => {
    const page = authenticatedWithLargeQueuePage;

    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    const firstCard = page.locator('[data-index="0"] [data-testid="queue-thread-item"]').first();
    const threadActions = firstCard.getByLabel('Thread actions', { exact: true });
    await threadActions.hover();
    await expect(page.getByText('Thread actions', { exact: true })).toHaveCount(0);
    await expect.poll(() => firstCard.evaluate((element) => getComputedStyle(element).overflow)).toBe('hidden');
    await threadActions.click();

    const menu = page.getByRole('menu', { name: 'Thread actions' });
    await expect(menu).toBeVisible();

    const menuBox = await menu.boundingBox();
    if (!menuBox) {
      throw new Error('Expected the thread actions menu to have a bounding box.');
    }
    await menu.hover({ position: { x: 16, y: menuBox.height - 16 } });
  });

  test('scroll reveals more virtualized items', async ({ authenticatedWithLargeQueuePage }) => {
    const page = authenticatedWithLargeQueuePage;

    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    const list = page.locator('[data-testid="queue-thread-list"]');
    await expect(list).toBeVisible();

    const virtualRows = list.locator('[data-index]');
    const initialLastIndex = await virtualRows.last().getAttribute('data-index');
    expect(initialLastIndex).not.toBeNull();

    await list.evaluate((el) => {
      el.scrollTop = 2000;
    });

    await expect.poll(async () => virtualRows.last().getAttribute('data-index'), {
      timeout: 10000,
    }).not.toBe(initialLastIndex);

    const scrolledLastIndex = await virtualRows.last().getAttribute('data-index');
    expect(Number(scrolledLastIndex)).toBeGreaterThan(Number(initialLastIndex));
  });

  test('visible Read action on a virtualized row card navigates to roll page', async ({ authenticatedWithLargeQueuePage }) => {
    const page = authenticatedWithLargeQueuePage;

    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    await page
      .locator('[data-testid="queue-thread-item"]')
      .first()
      .getByRole('button', { name: /Read/ })
      .click();

    await expect
      .poll(async () => new URL(page.url()).pathname)
      .toMatch(/^\/(roll)?$/);

    const mainDie = page.locator('[data-testid="d20-die"]');
    const rollPool = page.locator('[data-roll-pool]');
    await expect(mainDie.or(rollPool).first()).toBeVisible({ timeout: 5000 });
  });
});
