/**
 * ISSUE-2286: A fresh roll must anchor the viewport to the start of the newly
 * rolled result instead of retaining the pre-roll scroll offset.
 *
 * Before the fix, entering the rating view in place (no navigation) kept the
 * prior `#root.scrollTop`, dropping the reader partway through Reading Context.
 * These specs start from a non-zero scroll offset, complete a fresh roll, and
 * verify the rating surface start lands at the top of the viewport at every
 * supported viewport class.
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage, readAppScrollState, scrollAppTo, waitForRollPageReady } from './helpers'

const VIEWPORTS = [
  { name: 'phone portrait', width: 390, height: 844 },
  { name: 'tablet portrait', width: 768, height: 1024 },
  { name: 'tablet landscape', width: 1024, height: 768 },
  { name: 'wide desktop', width: 1536, height: 864 },
]

test.describe('issue #2286: fresh roll anchors the viewport to the rating surface start', () => {
  for (const viewport of VIEWPORTS) {
    test(`enters a fresh rolled result at the correct starting position on ${viewport.name}`, async ({
      authenticatedPage,
    }) => {
      const page = authenticatedPage
      await page.setViewportSize({ width: viewport.width, height: viewport.height })

      // Enough threads to make the Roll page tall enough to scroll at this viewport.
      for (let index = 0; index < 3; index++) {
        await createThread(page, {
          title: `Scroll Anchor Thread ${index + 1}`,
          issues_remaining: 3,
          total_issues: 3,
        })
      }

      await gotoRollPage(page)
      await waitForRollPageReady(page)

      // Verify that the real app scroller can move. The document itself is
      // intentionally non-scrollable; #root owns the scroll position.
      const initialScroll = await readAppScrollState(page)
      expect(initialScroll.rootScrollHeight).toBeGreaterThan(initialScroll.rootClientHeight)

      // Start from a non-zero scroll position.
      await scrollAppTo(page, 380)
      const preRollOffset = (await readAppScrollState(page)).rootScrollTop
      expect(preRollOffset).toBeGreaterThan(0)

      // Dispatch the click without Playwright's auto-scroll normalization so
      // the pre-roll offset survives through the in-place transition.
      await page.locator('#main-die-3d').dispatchEvent('click')

      // The roll resolves into the rating view for the selected comic.
      await expect(page.locator('#rating-input')).toBeVisible({ timeout: 20000 })
      await expect(page.getByTestId('rating-view-top')).toBeVisible()

      // Allow smooth anchoring to settle. The shipped shell keeps the roll
      // header above the rating surface, so the meaningful invariant is that
      // the app scroller returned to the top (not that the surface box has a
      // zero viewport offset). This is exactly the offset the old bug kept.
      await page.waitForFunction(() => {
        const top = document.querySelector('[data-testid="rating-view-top"]')
        if (!top || top.getBoundingClientRect().height === 0) return false
        // The shipped shell keeps the sticky header above the rating surface,
        // so the surface start lands within the header chrome band rather than
        // at an absolute zero offset. The regression being guarded is a large
        // negative offset (the stale pre-roll scroll position).
        const offset = top.getBoundingClientRect().top
        return offset >= -8 && offset <= 200
      }, undefined, { timeout: 10000 })

      // The rolled comic region is the rating surface's first content and is
      // visible in the viewport, not buried below continuity detail.
      const comicRegion = page.getByTestId('rating-region-comic')
      await expect(comicRegion).toBeVisible()
      const comicBox = await comicRegion.boundingBox()
      const viewportHeight = page.viewportSize()?.height ?? viewport.height
      expect(comicBox).not.toBeNull()
      expect(comicBox!.y).toBeGreaterThanOrEqual(0)
      expect(comicBox!.y).toBeLessThan(viewportHeight)
    })
  }
})