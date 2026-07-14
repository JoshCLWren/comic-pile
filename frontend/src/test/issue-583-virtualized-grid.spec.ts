import { expect } from './fixtures';
import { test } from './fixtures';
import { waitForQueueReady } from './helpers';

test.describe('Responsive multi-column virtualized grid (#583-C)', () => {
  test('renders 3 columns at desktop viewport (1280×720)', async ({ authenticatedWithLargeQueuePage }) => {
    const page = authenticatedWithLargeQueuePage;

    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    // Wait for the virtualized list to be visible
    const list = page.locator('[data-testid="queue-thread-list"]');
    await expect(list).toBeVisible();

    // At 1280px we expect 3 columns. Read the grid-template-columns from the
    // first virtualized row's inner grid container.
    const firstRowGrid = list.locator('[data-index="0"] > div').first();
    await expect(firstRowGrid).toBeVisible();

    const gridTemplateColumns = await firstRowGrid.evaluate((el) => {
      return getComputedStyle(el).gridTemplateColumns;
    });

    // With 3 equal columns, the value should be something like "405.656px 405.656px 405.656px"
    const columnCount = gridTemplateColumns.split(/\s+/).length;
    expect(columnCount).toBe(3);

    // Assert all 3 visible items in the first row exist
    const firstRowItems = list.locator('[data-index="0"] [data-testid="queue-thread-item"]');
    await expect(firstRowItems).toHaveCount(3);

    // Assert the grid gap matches the Tailwind gap-4 (1rem = 16px)
    const gap = await firstRowGrid.evaluate((el) => {
      return getComputedStyle(el).gap;
    });
    expect(gap).toBe('16px 16px');
  });

  test('renders 1 column at mobile viewport (375×812)', async ({ authenticatedWithLargeQueuePage }) => {
    const page = authenticatedWithLargeQueuePage;

    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    const list = page.locator('[data-testid="queue-thread-list"]');
    await expect(list).toBeVisible();

    // At 375px (single column), the component uses the single-column path.
    // Each virtual row contains one item directly (no grid wrapper).
    // Verify by checking data-index="0" has exactly one queue-thread-item child.
    const firstRowItems = list.locator('[data-index="0"] [data-testid="queue-thread-item"]');
    await expect(firstRowItems).toHaveCount(1);
  });

  test('scroll reveals more virtualized items', async ({ authenticatedWithLargeQueuePage }) => {
    const page = authenticatedWithLargeQueuePage;

    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    const list = page.locator('[data-testid="queue-thread-list"]');
    await expect(list).toBeVisible();

    // Initially visible items
    const initialItems = await list.locator('[data-testid="queue-thread-item"]').count();

    // Scroll the list container far down
    await list.evaluate((el) => {
      el.scrollTop = 2000;
    });
    await page.waitForTimeout(300);

    // After scrolling, new items should be visible
    const scrolledItems = await list.locator('[data-testid="queue-thread-item"]').count();
    expect(scrolledItems).toBeGreaterThan(initialItems);
  });

  test('swipe action on a virtualized row card navigates to roll page', async ({ authenticatedWithLargeQueuePage }) => {
    const page = authenticatedWithLargeQueuePage;

    // Use mobile viewport where swipe actions are relevant
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    // Click the Read swipe action button on the first virtualized card
    await page
      .locator('[data-testid="queue-thread-item"]')
      .first()
      .locator('button[aria-label="Read"]')
      .evaluate((btn) => (btn as HTMLButtonElement).click());

    // After clicking Read in the queue, the user should be navigated to the roll page
    // We expect either a URL change or a specific UI state
    await page.waitForURL(/^\/(roll)?$/, { timeout: 5000 }).catch(() => {
      // Fallback: if URL didn't change (same SPA page), check for roll page indicators
    });

    // The roll page should show the die or roll pool
    const mainDie = page.locator('[data-testid="d20-die"]');
    const rollPool = page.locator('[data-roll-pool]');
    await expect(mainDie.or(rollPool).first()).toBeVisible({ timeout: 5000 });
  });
});
