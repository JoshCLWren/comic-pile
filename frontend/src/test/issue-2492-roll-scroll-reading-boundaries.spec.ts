/**
 * ISSUE-2492: Rolling must never leave the reader partway through the
 * reading-boundaries content that loads asynchronously after a roll.
 *
 * A comic with reading boundaries exposes reader-context content (local chain,
 * paths, edges) that arrives asynchronously after the rating view anchors.
 * The late content mounts inside the rating surface and grows the page while
 * the enter transition is settling, which can carry the viewport into the
 * middle of the reading boundaries. These specs roll a comic that exposes
 * reading-context content and verify the rating surface start still lands at
 * the top of the viewport with the cover art and decisions visible at every
 * supported viewport class.
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage, waitForRollPageReady } from './helpers'

const VIEWPORTS = [
  { name: 'phone portrait', width: 390, height: 844 },
  { name: 'tablet portrait', width: 768, height: 1024 },
  { name: 'tablet landscape', width: 1024, height: 768 },
  { name: 'wide desktop', width: 1536, height: 864 },
]

test.describe('issue #2492: fresh roll keeps the rating start at the top when reading boundaries load', () => {
  for (const viewport of VIEWPORTS) {
    test(`stays at the cover art and decisions after reading boundaries load on ${viewport.name}`, async ({
      authenticatedPage,
    }) => {
      const page = authenticatedPage
      await page.setViewportSize({ width: viewport.width, height: viewport.height })

      // Enough threads to make the Roll page tall enough to scroll. Each thread
      // owns issues so whichever comic is rolled exposes reader-context
      // "reading boundaries" content that loads after the rating view anchors.
      for (let index = 0; index < 3; index++) {
        await createThread(page, {
          title: `Reading Boundaries Thread ${index + 1}`,
          format: 'Issue',
          issues_remaining: 10,
          total_issues: 10,
        })
      }

      await gotoRollPage(page)
      await waitForRollPageReady(page)

      // The page must actually be scrollable, otherwise the retained-offset
      // precondition cannot be modeled.
      const isScrollable = await page.evaluate(
        () => document.documentElement.scrollHeight > window.innerHeight,
      )
      expect(isScrollable).toBe(true)

      // Start from a non-zero scroll position so the fresh roll must move the
      // viewport to the rating surface start.
      await page.evaluate(() => window.scrollTo(0, 380))
      const preRollOffset = await page.evaluate(() => window.scrollY)
      expect(preRollOffset).toBeGreaterThan(0)

      // Dispatch the click without Playwright's auto-scroll normalization so
      // the pre-roll offset survives through the in-place transition.
      await page.locator('#main-die-3d').dispatchEvent('click')

      // The roll resolves into the rating view for the selected comic.
      await expect(page.locator('#rating-input')).toBeVisible({ timeout: 20000 })
      await expect(page.getByTestId('rating-view-top')).toBeVisible()

      // Reading-boundaries content loads asynchronously into the rating
      // surface; wait for it so any late layout growth is represented before
      // the final position is asserted.
      await expect(page.getByTestId('rating-region-reading-context')).toBeVisible({ timeout: 20000 })

      // The rating surface start must still be at the top of the viewport with
      // the cover art and decisions visible, never the middle of the reading
      // boundaries that mounted during the transition.
      await page.waitForFunction(() => {
        const top = document.querySelector('[data-testid="rating-view-top"]')
        if (!top || top.getBoundingClientRect().height === 0) return false
        return Math.abs(top.getBoundingClientRect().top) < 8
      }, undefined, { timeout: 10000 })

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