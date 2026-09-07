import { expect, test } from './fixtures';
import { createThread, setupAuthenticatedPage, waitForQueueReady } from './helpers';

/**
 * Queue rows must keep thread titles readable at tablet portrait (#2284).
 *
 * Regression: each queue row flipped to its fixed desktop horizontal layout at
 * the raw viewport `md` breakpoint even though the 288px sidebar had already
 * consumed most of the tablet width. The `shrink-0` action cluster then
 * consumed the whole row and the flexible title region collapsed to roughly
 * one character per line at 800x1094.
 *
 * This spec verifies the rendered contract:
 * - at 800x1094 the title region has meaningful width (not a one-char column)
 * - rows present stacked at tablet width, with actions below the title
 * - no horizontal page overflow is introduced
 * - long titles wrap into a few readable lines rather than hundreds of rows
 * - wide desktop keeps the efficient horizontal row layout
 */

const TABLET = { width: 800, height: 1094 };
const DESKTOP = { width: 1280, height: 900 };

const LONG_TITLE = 'Ultimate Spider-Man: Total Mayhem vs. the Sinister Six Round Two';

function readQueueGeometry() {
  const title = document.querySelector<HTMLButtonElement>('button[aria-label^="Open "]');
  const titleHeading = title?.querySelector('h3');
  const actions = document.querySelector<HTMLElement>('[role="group"][aria-label^="Actions for "]');
  const cards = document.querySelectorAll('[data-testid="queue-thread-item"]');
  const titleRect = title?.getBoundingClientRect();
  const headingRect = titleHeading?.getBoundingClientRect();
  const actionsRect = actions?.getBoundingClientRect();

  return {
    cards: cards.length,
    titleWidth: titleRect?.width ?? 0,
    titleBottom: titleRect?.bottom ?? 0,
    headingHeight: headingRect?.height ?? 0,
    actionsTop: actionsRect?.top ?? Number.POSITIVE_INFINITY,
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  };
}

test.describe('Queue tablet title width (#2284)', () => {
  test('keeps titles readable and stacked at an 800x1094 tablet viewport', async ({ page }) => {
    await setupAuthenticatedPage(page);
    await createThread(page, { title: LONG_TITLE, format: 'Annual', issues_remaining: 1, total_issues: 1 });
    await createThread(page, { title: 'Short Title', format: 'Issue', issues_remaining: 1, total_issues: 1 });

    await page.setViewportSize(TABLET);
    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);
    await expect(page.getByTestId('queue-thread-item')).toHaveCount(2);

    const geometry = await page.evaluate(readQueueGeometry);

    // Title must render with meaningful width — 200px is far above the
    // one-character-per-line collapse that produced near-zero width.
    expect(geometry.titleWidth, 'title region must not collapse to near-zero width').toBeGreaterThanOrEqual(200);
    // A few wrapped lines are fine; a one-char-per-line column would be hundreds of px tall.
    expect(geometry.headingHeight, 'title must not wrap character-by-character').toBeLessThanOrEqual(120);
    // Actions reflow below the title in the stacked presentation.
    expect(geometry.actionsTop, 'actions must sit below the title at tablet width').toBeGreaterThanOrEqual(geometry.titleBottom - 1);
    // No horizontal page overflow may be introduced.
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.innerWidth + 1);
  });

  test('keeps the horizontal row layout when enough content width exists (1280 desktop)', async ({ page }) => {
    await setupAuthenticatedPage(page);
    await createThread(page, { title: LONG_TITLE, format: 'Annual', issues_remaining: 1, total_issues: 1 });
    await createThread(page, { title: 'Short Title', format: 'Issue', issues_remaining: 1, total_issues: 1 });

    await page.setViewportSize(DESKTOP);
    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);
    await expect(page.getByTestId('queue-thread-item')).toHaveCount(2);

    const geometry = await page.evaluate(readQueueGeometry);

    expect(geometry.titleWidth).toBeGreaterThanOrEqual(200);
    // In the horizontal layout the action cluster sits beside the title within
    // the same vertical band (a stacked row would place it below the title).
    expect(geometry.actionsTop, 'actions must stay beside the title on wide desktop').toBeLessThan(geometry.titleBottom);
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.innerWidth + 1);
  });
});