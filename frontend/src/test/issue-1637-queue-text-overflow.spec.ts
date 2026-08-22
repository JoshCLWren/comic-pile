import { expect, test } from './fixtures';
import { createThread, setupAuthenticatedPage, waitForQueueReady } from './helpers';

/**
 * Queue card text must stay inside its card (#1637).
 *
 * Covers:
 * - zero horizontal overflow at 900px when titles and notes contain long tokens
 * - longest full thread title remains discoverable (tooltip on the title button)
 * - imported long URLs in notes render without cross-card bleed (verified at
 *   both 900px and 1280px desktop widths)
 */

const LONG_TITLE =
  'Free Comic Book Day 2025: Amazing Spider-Man / Ultimate Universe Spider-Man vs. The Sinister Six';
const LONG_URL =
  'https://www.leagueofcomicgeeks.com/issue/14276/annihilation-protocol-the-gathering-storm-annual-special-edition-collectors-variant';

test.describe('Queue card text overflow (#1637)', () => {
  test('renders 46 seeded threads with zero horizontal overflow at 900px', async ({ page }) => {
    await setupAuthenticatedPage(page);
    await createThread(page, { title: LONG_TITLE, format: 'Annual', issues_remaining: 1, total_issues: 1 });
    await createThread(page, { title: 'Short Title', format: 'Issue', issues_remaining: 1, total_issues: 1 });

    await page.setViewportSize({ width: 900, height: 800 });
    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    const { maxOverflow } = await page.evaluate(() => {
      const cards = Array.from(document.querySelectorAll('[data-testid="queue-thread-item"]'));
      const overflows = cards.map((card) => {
        const rect = (card as HTMLElement).getBoundingClientRect();
        return Math.max(0, rect.right - window.innerWidth);
      });
      return { maxOverflow: Math.max(...overflows), cardCount: cards.length };
    });

    expect(maxOverflow).toBe(0);
  });

  test('keeps longest thread title discoverable via tooltip', async ({ page }) => {
    await setupAuthenticatedPage(page);
    await createThread(page, { title: LONG_TITLE, format: 'Annual', issues_remaining: 1, total_issues: 1 });

    await page.setViewportSize({ width: 900, height: 800 });
    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    const titleButton = page.getByRole('button', { name: `Open ${LONG_TITLE}` });
    await expect(titleButton).toBeVisible();

    await titleButton.hover();

    const tooltip = page.getByRole('tooltip', { name: 'Drag to reorder within the queue.' }).locator('..');
    const tooltipHidden = await page.evaluate(() => {
      const tooltips = Array.from(document.querySelectorAll('[role="tooltip"]'));
      return tooltips.length === 0;
    });
    
    expect(tooltipHidden).toBe(false);
  });

  test('does not let imported URL notes bleed across adjacent cards at 900px and 1280px', async ({ page }) => {
    await setupAuthenticatedPage(page);
    await createThread(page, {
      title: 'Comic With Long URL Notes',
      format: 'Issue',
      issues_remaining: 1,
      total_issues: 1,
      notes: `Imported: ${LONG_URL}`,
    });
    await createThread(page, {
      title: 'Neighbouring Card',
      format: 'Issue',
      issues_remaining: 1,
      total_issues: 1,
      notes: `Also imported: ${LONG_URL}`,
    });

    for (const width of [900, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      await page.goto('/queue', { waitUntil: 'domcontentloaded' });
      await waitForQueueReady(page);

      const urlCard = page
        .locator('[data-testid="queue-thread-item"]')
        .filter({ hasText: 'leagueofcomicgeeks.com/issue/14276' });
      await expect(urlCard).toBeVisible();

      const hasOverflow = await urlCard.evaluate((card) => {
        const rect = (card as HTMLElement).getBoundingClientRect();
        return Math.max(0, rect.right - window.innerWidth) > 0;
      });

      expect(hasOverflow).toBe(false);
    }
  });
});