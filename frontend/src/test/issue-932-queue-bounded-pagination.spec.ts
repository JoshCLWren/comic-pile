import { expect, test } from './fixtures';
import { waitForQueueReady } from './helpers';

/**
 * Bounded incremental Queue loading (#932).
 *
 * The Queue must request exactly one bounded page on first navigation and
 * append later pages only through an explicit incremental interaction. Search
 * and sort changes must reset to the first compatible page. These behaviors
 * are covered at the hook level in `useQueue.test.tsx`; this spec exercises
 * them end-to-end against a real backend with a multi-page queue.
 */
test.describe('Bounded incremental Queue loading (#932)', () => {
  test('requests only the first bounded page on initial navigation', async ({ authenticatedWithLargeQueuePage }) => {
    const page = authenticatedWithLargeQueuePage;

    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    // The first page is bounded (page_size 50) and renders in the plain grid
    // before the virtualization threshold, so every card is mounted.
    await expect(page.getByTestId('queue-thread-item')).toHaveCount(50);
    await expect(page.getByTestId('queue-infinite-scroll-sentinel')).toBeVisible();
  });

  test('appends the next page incrementally and reaches the end of the list', async ({ authenticatedWithLargeQueuePage }) => {
    const page = authenticatedWithLargeQueuePage;

    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    // Scroll to the near-end sentinel to trigger the incremental load.
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    const container = page.locator('#queue-container');
    await container.evaluate((element) => element.scrollTo({ top: element.scrollHeight }));

    // The second page (threads 51-60) is appended; the final thread becomes
    // visible without discarding the first page.
    await expect(page.getByText('Test Thread 60')).toBeVisible({ timeout: 10000 });

    // Returning to the top keeps the first page intact (no scroll loss).
    await container.evaluate((element) => element.scrollTo({ top: 0 }));
    await expect(page.getByText('Test Thread 1')).toBeVisible();

    // After the final page there is no further cursor, so the sentinel is gone.
    await expect(page.getByTestId('queue-infinite-scroll-sentinel')).toHaveCount(0);
  });

  test('resets to the first compatible page when the search changes', async ({ authenticatedWithLargeQueuePage }) => {
    const page = authenticatedWithLargeQueuePage;

    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    const search = page.getByPlaceholder('Search...');
    await search.fill('Test Thread 1');

    // The search term does not match the tail of the library, so the
    // out-of-range thread must disappear and the list must reload from the
    // first compatible page.
    await expect(page.getByText('Test Thread 60')).toHaveCount(0);
    await expect(page.getByText('Test Thread 1')).toBeVisible();
  });

  test('resets the loaded pages when the sort order changes', async ({ authenticatedWithLargeQueuePage }) => {
    const page = authenticatedWithLargeQueuePage;

    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    await page.getByRole('button', { name: 'A-Z' }).click();

    // The sort change is a distinct query key, so the loader resets to the
    // first compatible page and keeps the queue intact.
    await expect(page.getByText('Test Thread 1')).toBeVisible();
    await expect(page.getByTestId('queue-thread-item').first()).toBeVisible();
  });

  test('offers a retry affordance when the next-page request fails and recovers', async ({ authenticatedWithLargeQueuePage }) => {
    const page = authenticatedWithLargeQueuePage;

    // Only abort cursor-paginated continuation requests; let the first page load.
    await page.route('**/v1/threads/**', async (route) => {
      const url = route.request().url();
      if (url.includes('page_token')) {
        await route.abort();
      } else {
        await route.continue();
      }
    });

    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));

    const retry = page.getByTestId('queue-load-more-retry');
    await expect(retry).toBeVisible({ timeout: 10000 });

    // Recover: stop aborting and retry the incremental load.
    await page.unroute('**/v1/threads/**');
    await retry.click();

    await expect(page.getByText('Test Thread 60')).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId('queue-infinite-scroll-sentinel')).toHaveCount(0);
  });
});
