import { expect, test } from './fixtures';
import {
  queueCardMentionsTitle,
  queueThreadTitle,
  readQueueViewport,
  scrollAppTo,
  scrollAppUntil,
  waitForQueueReady,
} from './helpers';

/**
 * Queue pagination regression suite (#2571), repaired for #2725.
 *
 * The original suite claimed to prove five-page bidirectional scrolling with
 * real virtualization, but it scrolled `window` (a no-op: html/body overflow
 * is hidden) and asserted that every loaded card was mounted. Production
 * virtualizes against `#root`, so those assertions could not see the blank
 * spacer failure.
 *
 * This rewrite uses the real page scroller and painted-viewport checks.
 */
test.describe('Queue pagination regression (#2571)', () => {
  test.describe.configure({ timeout: 480_000 })
  test('survives bidirectional traversal of 5+ pages of data', async ({ authenticatedWithProductionQueuePage }) => {
    const page = authenticatedWithProductionQueuePage;

    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    await expect(page.getByTestId('queue-thread-item').first()).toBeVisible();
    await expect(queueThreadTitle(page, 'Test Thread 1')).toBeVisible();
    const initial = await readQueueViewport(page);
    expect(initial.visibleCount).toBeGreaterThan(0);
    expect(initial.mounted).toBeLessThan(250);

    await scrollAppUntil(
      page,
      async () => (await readQueueViewport(page)).visibleTitles.some((text) => queueCardMentionsTitle(text, 'Test Thread 100')),
      'page 2',
    );
    expect((await readQueueViewport(page)).visibleCount).toBeGreaterThan(0);

    await scrollAppTo(page, 0);
    await expect(queueThreadTitle(page, 'Test Thread 1')).toBeVisible();

    await scrollAppUntil(
      page,
      async () => (await readQueueViewport(page)).visibleTitles.some((text) => queueCardMentionsTitle(text, 'Test Thread 150')),
      'page 3',
    );
    expect((await readQueueViewport(page)).visibleCount).toBeGreaterThan(0);

    await scrollAppUntil(
      page,
      async () => (await readQueueViewport(page)).visibleTitles.some((text) => queueCardMentionsTitle(text, 'Test Thread 200')),
      'page 4',
    );
    await scrollAppUntil(
      page,
      async () => (await readQueueViewport(page)).visibleTitles.some((text) => queueCardMentionsTitle(text, 'Test Thread 250')),
      'page 5',
    );
    await expect(page.getByTestId('queue-infinite-scroll-sentinel')).toHaveCount(0);

    await scrollAppTo(page, 0);
    await expect(queueThreadTitle(page, 'Test Thread 1')).toBeVisible();

    await scrollAppUntil(
      page,
      async () => (await readQueueViewport(page)).visibleTitles.some((text) => queueCardMentionsTitle(text, 'Test Thread 75')),
      'revisit page 2 region',
    );
    expect((await readQueueViewport(page)).visibleCount).toBeGreaterThan(0);
  });

  test('pagination stability across different sort keys', async ({ authenticatedWithProductionQueuePage }) => {
    const page = authenticatedWithProductionQueuePage;
    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    const sorts = [
      { name: 'Title', selector: 'button:has-text("Title")' },
      { name: 'Position', selector: 'button:has-text("Position")' },
      { name: 'Recently Added', selector: 'button:has-text("Recently added")' },
    ];

    for (const sort of sorts) {
      await page.locator(sort.selector).click();
      await waitForQueueReady(page);

      await scrollAppUntil(
        page,
        async () => (await readQueueViewport(page)).visibleIndexes.some((index) => index >= 40),
        `${sort.name} advanced window`,
      );
      expect((await readQueueViewport(page)).visibleCount).toBeGreaterThan(0);

      await scrollAppTo(page, 0);
      await expect(page.getByTestId('queue-thread-item').first()).toBeVisible();
    }
  });
});
