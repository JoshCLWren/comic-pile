import { expect, test } from './fixtures';
import { createThread, setupAuthenticatedPage, waitForQueueReady } from './helpers';

/**
 * Queue card text must stay inside its card (#1637).
 *
 * Covers:
 * - zero horizontal text overflow at 900px when titles and notes contain long tokens
 * - longest full thread title remains discoverable (native tooltip on the title button)
 * - imported long URLs in notes wrap-break via `overflow-wrap: anywhere` and render
 *   without cross-card bleed (verified at both 900px and 1280px desktop widths)
 */

const LONG_TITLE =
  'Free Comic Book Day 2025: Amazing Spider-Man / Ultimate Universe Spider-Man vs. The Sinister Six';
const LONG_URL =
  'https://www.leagueofcomicgeeks.com/issue/14276/annihilation-protocol-the-gathering-storm-annual-special-edition-collectors-variant';

/**
 * Audits every queue card for horizontal text overflow that would paint outside
 * its own card box.
 *
 * For each descendant element whose computed `overflow-x` is visible (i.e. it
 * does not clip), `scrollWidth` must not exceed `clientWidth`: an excess means
 * unbreakable content paints past the element box and can bleed into adjacent
 * cards. Elements that clip horizontally are skipped along with their subtree
 * because their content cannot paint beyond the clipping edge; their own boxes
 * are still checked against the card bounds.
 */
function auditCardTextOverflow() {
  const CLIPPING = new Set(['hidden', 'clip', 'auto', 'scroll']);
  const violations: string[] = [];
  const cards = Array.from(document.querySelectorAll('[data-testid="queue-thread-item"]'));
  for (const card of cards) {
    const cardRect = card.getBoundingClientRect();
    if (cardRect.right > window.innerWidth + 1) {
      violations.push('card extends past viewport right edge');
    }
    const stack = [card];
    while (stack.length > 0) {
      const el = stack.pop()!;
      if (el.getBoundingClientRect().right > cardRect.right + 1) {
        violations.push(`${el.tagName.toLowerCase()} paints past its card right edge`);
      }
      const clips = CLIPPING.has(window.getComputedStyle(el).overflowX);
      if (!clips) {
        if (el.scrollWidth > el.clientWidth + 1) {
          violations.push(`${el.tagName.toLowerCase()} has unclipped horizontal content overflow`);
        }
        stack.push(...Array.from(el.children));
      }
    }
  }
  return {
    cardCount: cards.length,
    pageScrollWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
    violations,
  };
}

test.describe('Queue card text overflow (#1637)', () => {
  test('keeps long titles and notes inside their cards at 900px', async ({ page }) => {
    await setupAuthenticatedPage(page);
    await createThread(page, { title: LONG_TITLE, format: 'Annual', issues_remaining: 1, total_issues: 1 });
    await createThread(page, { title: 'Short Title', format: 'Issue', issues_remaining: 1, total_issues: 1 });

    await page.setViewportSize({ width: 900, height: 800 });
    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);
    await expect(page.getByTestId('queue-thread-item')).toHaveCount(2);

    const report = await page.evaluate(auditCardTextOverflow);
    expect(report.cardCount).toBe(2);
    expect(report.violations).toEqual([]);
    expect(report.pageScrollWidth).toBeLessThanOrEqual(report.viewportWidth);
  });

  test('keeps the longest thread title discoverable via tooltip', async ({ page }) => {
    await setupAuthenticatedPage(page);
    await createThread(page, { title: LONG_TITLE, format: 'Annual', issues_remaining: 1, total_issues: 1 });

    await page.setViewportSize({ width: 900, height: 800 });
    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    const titleButton = page.getByRole('button', { name: `Open ${LONG_TITLE}` });
    await expect(titleButton).toBeVisible();
    await expect(titleButton).toHaveAttribute('title', LONG_TITLE);
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
      await expect(page.getByTestId('queue-thread-item')).toHaveCount(2);

      const urlCards = page
        .locator('[data-testid="queue-thread-item"]')
        .filter({ hasText: 'leagueofcomicgeeks.com' });
      await expect(urlCards).toHaveCount(2);

      // The issue requires notes to wrap-break with `overflow-wrap: anywhere`.
      const wrapModes = await urlCards
        .locator('p')
        .filter({ hasText: 'leagueofcomicgeeks.com' })
        .evaluateAll((notes) => notes.map((note) => window.getComputedStyle(note).overflowWrap));
      expect(wrapModes).toHaveLength(2);
      for (const wrapMode of wrapModes) {
        expect(wrapMode).toBe('anywhere');
      }

      const report = await page.evaluate(auditCardTextOverflow);
      expect(report.cardCount).toBe(2);
      expect(report.violations).toEqual([]);
      expect(report.pageScrollWidth).toBeLessThanOrEqual(report.viewportWidth);
    }
  });
});
