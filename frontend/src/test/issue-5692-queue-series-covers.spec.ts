import { expect, type Page } from '@playwright/test';
import { test } from './fixtures';
import { scrollAppTo, scrollAppUntil, waitForQueueReady } from './helpers';
import type { ThreadListItem } from '../types';

const COVER_ORIGIN = 'https://covers.example.test';
const BLOCKED_THREAD_ID = 3;
const FAR_DOWN_TITLE = 'Far Down Covered';
const FAILED_COVER_TITLE = 'Failed Fetch Cover';

function coverUrl(name: string): string {
  return `${COVER_ORIGIN}/${name}.svg`;
}

function queueThread(id: number): ThreadListItem {
  return {
    id,
    title: `Queue Series ${id}`,
    format: 'Comic',
    issues_remaining: 12,
    total_issues: 24,
    next_unread_issue_number: '12',
    queue_position: id,
    status: 'active',
    is_blocked: false,
    blocking_reasons: [],
    notes: null,
    last_activity_at: null,
    created_at: '2026-01-01T00:00:00.000Z',
    comicvine_mapping: null,
    series_metadata: null,
    series_cover_image_url: null,
    manual_creator_credits: [],
    tags: [],
  };
}

function queueRows(): ThreadListItem[] {
  const rows = Array.from({ length: 50 }, (_, index) => queueThread(index + 1));
  rows[0] = {
    ...rows[0],
    title: 'Covered Next Unread',
    series_cover_image_url: coverUrl('covered'),
  };
  rows[1] = { ...rows[1], title: 'Uncovered Series' };
  rows[2] = {
    ...rows[2],
    title: 'FF',
    is_blocked: true,
    blocking_reasons: ['Read Fantastic Four #600 first.'],
    series_cover_image_url: coverUrl('blocked-ff'),
  };
  rows[34] = {
    ...rows[34],
    title: FAR_DOWN_TITLE,
    series_cover_image_url: coverUrl('far-down'),
  };
  rows[39] = {
    ...rows[39],
    title: FAILED_COVER_TITLE,
    series_cover_image_url: coverUrl('failed'),
  };
  return rows;
}

async function installQueueRoutes(
  page: Page,
  imageRequests: string[],
  threadRequests: string[],
): Promise<void> {
  const rows = queueRows();

  await page.route('**/v2/threads*', async (route) => {
    threadRequests.push(new URL(route.request().url()).pathname);
    await route.fulfill({
      json: { threads: rows, next_page_token: null, active_count: rows.length },
    });
  });

  await page.route('**/v2/reading-boundaries', async (route) => {
    const payload = route.request().postDataJSON() as { thread_ids?: number[] };
    const ids = Array.isArray(payload.thread_ids) ? payload.thread_ids : [];
    const threads = Object.fromEntries(ids.map((id) => [id, id === BLOCKED_THREAD_ID
      ? {
          thread_id: id,
          state: 'blocked',
          summary: 'FF #12 is waiting on 1 live requirement.',
          blockers: [{
            kind: 'prerequisite',
            origin: 'reader_prerequisite',
            reason: 'Read Fantastic Four #600 first.',
            waiting_on: [{
              issue_id: 600,
              thread_id: 600,
              thread_title: 'Fantastic Four',
              issue_number: '600',
              label: 'Fantastic Four #600',
              volume_label: null,
              reading_lists: [],
            }],
            editor: { kind: 'prerequisite', thread_id: id, label: 'FF prerequisites' },
          }],
        }
      : { thread_id: id, state: 'available', summary: 'Ready to read.', blockers: [] }]));
    await route.fulfill({ json: { threads, evaluator: 'enabled' } });
  });

  await page.route('**/v1/threads/groups:batch', async (route) => {
    await route.fulfill({ json: {} });
  });

  await page.route(`${COVER_ORIGIN}/**`, async (route) => {
    const url = route.request().url();
    imageRequests.push(url);
    if (new URL(url).pathname.endsWith('/failed.svg')) {
      await route.fulfill({ status: 500, contentType: 'text/plain', body: 'cover failed' });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="600"><rect width="400" height="600" fill="#24405c"/></svg>',
    });
  });
}

function queueRow(page: Page, title: string) {
  return page.getByTestId('queue-thread-item').filter({ hasText: title });
}

async function scrollUntilRow(page: Page, title: string): Promise<void> {
  await scrollAppUntil(
    page,
    async () => queueRow(page, title).isVisible(),
    `visible Queue row for ${title}`,
  );
  await expect(queueRow(page, title)).toBeVisible();
}

async function expectLoadedCover(page: Page, title: string, url: string): Promise<void> {
  const cover = queueRow(page, title).getByTestId('queue-thread-series-cover');
  const image = cover.getByRole('img', { name: `Cover for ${title}` });
  await expect(image).toHaveAttribute('src', url);
  await expect(image).toHaveAttribute('loading', 'eager');
  await expect.poll(() => image.evaluate((element) =>
    element instanceof HTMLImageElement && element.complete && element.naturalWidth > 0,
  )).toBe(true);
  await expect(image).toHaveClass(/opacity-100/);
  await expect(cover.getByRole('status')).toHaveCount(0);
  const frame = await cover.boundingBox();
  expect(frame).not.toBeNull();
  expect(frame!.width / frame!.height).toBeCloseTo(2 / 3, 1);
}

test.describe('Queue series cover rendering (#5692)', () => {
  for (const viewport of [
    { name: 'desktop', width: 1440, height: 900 },
    { name: 'phone', width: 390, height: 844 },
  ]) {
    test(`loads far-down, blocked and failed covers without stale rows on ${viewport.name}`, async ({
      authenticatedPage: page,
      allowExpectedBrowserFailures,
    }) => {
      allowExpectedBrowserFailures.allow({ category: 'console', message: 'failed.svg' });
      const imageRequests: string[] = [];
      const threadRequests: string[] = [];
      await installQueueRoutes(page, imageRequests, threadRequests);
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto('/queue', { waitUntil: 'domcontentloaded' });
      await waitForQueueReady(page);

      await expectLoadedCover(page, 'Covered Next Unread', coverUrl('covered'));
      await expectLoadedCover(page, 'FF', coverUrl('blocked-ff'));
      await expect(queueRow(page, 'FF').getByLabelText('Blocked series')).toBeVisible();
      await expect(queueRow(page, 'FF').getByTestId('queue-thread-blocked-detail'))
        .toContainText('FF #12 is waiting on 1 live requirement.');
      await expect(queueRow(page, 'FF').getByTestId('queue-thread-blocked-detail'))
        .toContainText('Read Fantastic Four #600 first.');
      await expect(queueRow(page, 'FF').getByRole('button', { name: 'Read / Rate / Map issue' }))
        .toBeEnabled();

      const uncovered = queueRow(page, 'Uncovered Series');
      await expect(uncovered.getByTestId('queue-thread-series-cover-placeholder'))
        .toHaveAttribute('aria-label', 'No cover for Uncovered Series');
      await expect(uncovered.getByRole('img', { name: 'Cover for Uncovered Series' })).toHaveCount(0);
      await expect(uncovered.getByRole('button', { name: 'Read / Rate / Map issue' })).toBeEnabled();

      const listRequestsBeforeScroll = threadRequests.length;
      await scrollUntilRow(page, FAR_DOWN_TITLE);
      await expectLoadedCover(page, FAR_DOWN_TITLE, coverUrl('far-down'));
      expect(imageRequests).toContain(coverUrl('far-down'));
      expect(threadRequests).toHaveLength(listRequestsBeforeScroll);

      await scrollUntilRow(page, FAILED_COVER_TITLE);
      const failedCover = queueRow(page, FAILED_COVER_TITLE).getByTestId('queue-thread-series-cover');
      await expect(failedCover.getByTestId('queue-thread-series-cover-placeholder'))
        .toHaveAttribute('aria-label', `No cover for ${FAILED_COVER_TITLE}`);
      await expect(failedCover.getByRole('img')).toHaveCount(0);
      await expect(failedCover.getByRole('status')).toHaveCount(0);

      await scrollAppTo(page, 0);
      await expect(queueRow(page, 'Covered Next Unread')).toBeVisible();
      await scrollUntilRow(page, FAR_DOWN_TITLE);
      await expectLoadedCover(page, FAR_DOWN_TITLE, coverUrl('far-down'));

      await scrollAppTo(page, 0);
      await page.reload({ waitUntil: 'domcontentloaded' });
      await waitForQueueReady(page);
      await scrollAppTo(page, 0);
      await scrollUntilRow(page, FAR_DOWN_TITLE);
      await expectLoadedCover(page, FAR_DOWN_TITLE, coverUrl('far-down'));

      if (viewport.name === 'desktop') {
        await page.goto('/', { waitUntil: 'domcontentloaded' });
        await page.goBack({ waitUntil: 'domcontentloaded' });
        await waitForQueueReady(page);
        await scrollAppTo(page, 0);
        await scrollUntilRow(page, FAR_DOWN_TITLE);
        await expectLoadedCover(page, FAR_DOWN_TITLE, coverUrl('far-down'));
      }

      expect(threadRequests.filter((path) => /^\/api\/v2\/threads\/\d+$/.test(path))).toHaveLength(0);
    });
  }
});
