import { expect } from './fixtures';
import { test } from './fixtures';
import { waitForQueueReady } from './helpers';

test.describe('Virtualized drag-to-reorder (#583-D)', () => {
  test('drag reorder works within the virtualized list', async ({ authenticatedWithLargeQueuePage }) => {
    const page = authenticatedWithLargeQueuePage;

    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    const list = page.locator('[data-testid="queue-thread-list"]');
    await expect(list).toBeVisible();

    // Get the first card's drag handle (⠿ button with aria-label="Drag to reorder")
    const firstCard = page.locator('[data-testid="queue-thread-item"]').first();
    const dragHandle = firstCard.locator('button[aria-label="Drag to reorder"]');
    await expect(dragHandle).toBeVisible();

    // Find a visible lower target card (the 5th visible one)
    const visibleCards = page.locator('[data-testid="queue-thread-item"]');
    const cardCount = await visibleCards.count();
    if (cardCount < 5) {
      throw new Error(`Expected at least 5 visible cards, found ${cardCount}`);
    }

    const targetCard = visibleCards.nth(4);
    await expect(targetCard).toBeVisible();

    // Read the text of the first and target items before drag
    const sourceText = await firstCard.textContent();
    const targetText = await targetCard.textContent();

    // Perform the drag: drag the handle from card #1 onto card #5
    await dragHandle.dragTo(targetCard, { force: true });

    // After the drop, refetch threads to confirm reorder happened.
    // The queue should have changed — the originally-#1 thread is no longer at position 1.
    await page.waitForTimeout(500); // allow the mutation + refetch to complete

    // Verify the first card changed (drag reorder happened)
    const firstCardAfter = page.locator('[data-testid="queue-thread-item"]').first();
    const firstTextAfter = await firstCardAfter.textContent();

    // The first card should either be the former target (moved up) or something different
    // from the original first (we don't know exact position — just verify it changed)
    if (sourceText && firstTextAfter) {
      expect(sourceText).not.toBe(firstTextAfter);
    }

    // Also verify the target card changed (its position was affected)
    const targetCardAfter = visibleCards.nth(4);
    const targetTextAfter = await targetCardAfter.textContent();
    if (targetText && targetTextAfter) {
      expect(targetText).not.toBe(targetTextAfter);
    }
  });

  test('dragging near the bottom edge auto-scrolls to reveal off-screen items', async ({ authenticatedWithLargeQueuePage }) => {
    const page = authenticatedWithLargeQueuePage;

    // Use a narrower viewport to ensure single-column mode for simpler edge detection
    await page.setViewportSize({ width: 375, height: 812 });

    await page.goto('/queue', { waitUntil: 'domcontentloaded' });
    await waitForQueueReady(page);

    const list = page.locator('[data-testid="queue-thread-list"]');
    await expect(list).toBeVisible();

    // Set scrollTop to 0 for a clean baseline
    await list.evaluate((el) => { el.scrollTop = 0; });
    const initialScrollTop = await list.evaluate((el) => el.scrollTop);
    expect(initialScrollTop).toBe(0);

    // Dispatch a series of real DragEvent dragover events near the bottom edge.
    // The component's container onDragOver handler auto-scrolls via
    // virtualizer.scrollToIndex when clientY is within EDGE_SCROLL_ZONE (80px)
    // of the bottom of the container.
    const scrolled = await list.evaluate((el) => {
      const rect = el.getBoundingClientRect();
      const dataTransfer = new DataTransfer();

      // Fire multiple dragover events near the bottom edge to simulate
      // a dragged item hovering there.  Each event triggers one scroll step.
      for (let i = 0; i < 5; i++) {
        const event = new DragEvent('dragover', {
          clientY: rect.bottom - 40, // well within the 80-px edge zone
          bubbles: true,
          cancelable: true,
          dataTransfer,
        });
        el.dispatchEvent(event);
      }

      // Return scrollTop after the events (scrollToIndex is async, but a
      // small settle-time wait happens in the caller)
      return el.scrollTop;
    });

    // Wait for the virtualizer's smooth scroll to settle
    await page.waitForTimeout(500);

    // Read final scrollTop
    const finalScrollTop = await list.evaluate((el) => el.scrollTop);

    // The auto-scroll should have increased scrollTop beyond the baseline
    expect(finalScrollTop).toBeGreaterThan(initialScrollTop);
  });
});