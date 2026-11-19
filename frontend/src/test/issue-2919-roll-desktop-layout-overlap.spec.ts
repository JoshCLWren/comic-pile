/**
 * Issue #2919: the Roll result layout must not overlap the comic cover or clip
 * its interactive content past the right viewport edge.
 *
 * Reported symptom at roughly 1792x896: the action/details panel sat on top of
 * the cover, the selected-series details on the far right were pushed partly
 * offscreen, and the layout left a large unused gap on the left/middle.
 *
 * Acceptance contract asserted here, in rendered geometry rather than class
 * strings:
 * 1. The cover region and the action/details region occupy non-overlapping
 *    regions and tile the grid side by side.
 * 2. Nothing is clipped beyond the right viewport edge.
 * 3. The result layout introduces no horizontal overflow.
 * 4. It holds at ~1440, ~1600, ~1792, and ~1920 px.
 * 5. Cover prominence and control hierarchy are preserved (the cover keeps its
 *    existing height cap instead of being shrunk to make the row fit).
 *
 * Measurement notes that keep these assertions falsifiable:
 * - `#root` owns the shell scroll box and already clips horizontally, so
 *   `document.documentElement.scrollWidth` can never exceed the viewport width.
 *   The meaningful horizontal-overflow signal is `#root`'s own
 *   `scrollWidth` versus `clientWidth`, plus the rendered boxes of the two
 *   rating regions. Measuring the document element here would make every
 *   assertion in this file vacuously true.
 * - Containment must come from layout, not from a clip. The last test pins the
 *   mobile sticky action cluster: the only scroll container between the action
 *   bar and the shell scroll owner may be `#root` itself. A nested
 *   `overflow-x-hidden`/`overflow-y-hidden` wrapper inside the rating view
 *   would silently turn `#root`'s children into a second scroll container and
 *   break the sticky cluster without ever producing document-level overflow.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage } from './helpers'

const THREAD_TITLE = 'Layout Issue 2919'
const MOBILE_VIEWPORT = { width: 390, height: 844 }

/** Sub-pixel rounding only; a real layout error is measured in tens of pixels. */
const GEOMETRY_TOLERANCE_PX = 2

/** Small opaque SVG so the cover never reaches the production image optimizer. */
const COVER_DATA_URI = (() => {
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="600"><rect width="400" height="600" fill="#111"/></svg>'
  return `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`
})()

const VIEWPORTS = [
  { label: '1440', width: 1440, height: 900 },
  { label: '1600', width: 1600, height: 900 },
  { label: '1792', width: 1792, height: 896 },
  { label: '1920', width: 1920, height: 1080 },
]

interface RatingGeometry {
  viewportWidth: number
  viewportHeight: number
  root: { scrollWidth: number; clientWidth: number }
  comic: DOMRectSnapshot | null
  decision: DOMRectSnapshot | null
  actions: DOMRectSnapshot | null
  cover: DOMRectSnapshot | null
}

interface DOMRectSnapshot {
  left: number
  right: number
  top: number
  bottom: number
  width: number
  height: number
}

/**
 * Freezes every route the rating view can touch so measured geometry depends
 * only on the layout, never on whichever series happens to be in the queue or
 * on how slowly a live continuity request resolves.
 */
async function installRatingRoutes(page: Page): Promise<void> {
  await page.route('**/v1/threads/*/reading-orders', (route) =>
    route.fulfill({ json: { reading_orders: [] } }),
  )
  await page.route('**/v1/threads/*/connected', (route) =>
    route.fulfill({ json: { connected_threads: [] } }),
  )
  await page.route('**/v1/reading-order-groups/threads/*/groups', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/v1/issues/*/reader-context', (route) => route.fulfill({ json: null }))
  await page.route('**/v1/creators/summaries', (route) =>
    route.fulfill({ json: { summaries: {}, coverage: null } }),
  )
  await page.route('**/v1/issues/*/comicvine', (route) =>
    route.fulfill({
      json: {
        comicvine_issue_id: '2919',
        comicvine_url: null,
        series_name: 'Layout Series',
        series_id: 2919,
        issue_number: '1',
        name: 'Layout Issue',
        description: null,
        image_url: COVER_DATA_URI,
        cover_date: '2020-01-01',
        store_date: null,
        creators: [],
        story_arcs: [],
      },
    }),
  )
  await page.route('**/v1/comicvine/issues/*/identity', (route) =>
    route.fulfill({
      json: {
        issue_id: 1,
        thread_id: 1,
        thread_title: THREAD_TITLE,
        has_confirmed_identity: true,
        confirmed_mappings: [],
        candidate_mappings: [],
        has_unresolved: false,
      },
    }),
  )
}

async function enterRatingView(page: Page): Promise<void> {
  await installRatingRoutes(page)
  await gotoRollPage(page)
  await page.locator('#main-die-3d').click()
  await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 20000 })
  await page.getByText(THREAD_TITLE, { exact: true }).first().click()
  await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })
  await expect(page.getByTestId('rating-actions')).toBeVisible()
  await expect(page.getByTestId('comic-cover')).toBeVisible()
  await page.evaluate(async () => {
    if (document.fonts) {
      await document.fonts.ready
    }
  })
  // Let the mocked intelligence/identity responses settle so measured boxes are
  // final rather than mid-skeleton.
  await page.waitForTimeout(300)
}

async function readRatingGeometry(page: Page): Promise<RatingGeometry> {
  return page.evaluate(() => {
    const snapshot = (element: Element | null) => {
      if (!element) return null
      const rect = element.getBoundingClientRect()
      return {
        left: rect.left,
        right: rect.right,
        top: rect.top,
        bottom: rect.bottom,
        width: rect.width,
        height: rect.height,
      }
    }
    const root = document.getElementById('root')
    return {
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      root: {
        scrollWidth: root?.scrollWidth ?? 0,
        clientWidth: root?.clientWidth ?? 0,
      },
      comic: snapshot(document.querySelector('[data-testid="rating-region-comic"]')),
      decision: snapshot(document.querySelector('[data-testid="rating-region-decision"]')),
      actions: snapshot(document.querySelector('[data-testid="rating-actions"]')),
      cover: snapshot(document.querySelector('[data-testid="comic-cover"]')),
    }
  })
}

test.describe('Issue #2919 Roll result layout overlap and clipping', () => {
  for (const viewport of VIEWPORTS) {
    test(`cover, controls, and metadata stay contained at ${viewport.label}px`, async ({
      authenticatedPage,
    }) => {
      const page = authenticatedPage
      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      await createThread(page, {
        title: THREAD_TITLE,
        format: 'Comic',
        issues_remaining: 3,
        total_issues: 3,
      })

      await enterRatingView(page)

      const geometry = await readRatingGeometry(page)
      expect(geometry.comic, 'the comic region must be present').not.toBeNull()
      expect(geometry.decision, 'the action/details region must be present').not.toBeNull()
      expect(geometry.actions, 'the roll controls must be present').not.toBeNull()
      expect(geometry.cover, 'the cover must be present').not.toBeNull()

      // The two regions tile the desktop grid side by side. Overlap here is the
      // exact defect the report described.
      expect(
        geometry.decision!.left,
        'the action/details region must start at or after the cover region ends',
      ).toBeGreaterThanOrEqual(geometry.comic!.right - GEOMETRY_TOLERANCE_PX)
      expect(
        Math.abs(geometry.decision!.top - geometry.comic!.top),
        'both regions must share the grid row instead of being offset vertically',
      ).toBeLessThanOrEqual(GEOMETRY_TOLERANCE_PX)

      // Nothing escapes the right viewport edge.
      expect(geometry.decision!.right).toBeLessThanOrEqual(
        geometry.viewportWidth + GEOMETRY_TOLERANCE_PX,
      )
      expect(geometry.actions!.right).toBeLessThanOrEqual(
        geometry.viewportWidth + GEOMETRY_TOLERANCE_PX,
      )
      expect(geometry.cover!.right).toBeLessThanOrEqual(
        geometry.comic!.right + GEOMETRY_TOLERANCE_PX,
      )

      // No horizontal overflow in the shell scroll box.
      expect(
        geometry.root.scrollWidth,
        'the Roll result must not introduce horizontal scrolling',
      ).toBeLessThanOrEqual(geometry.root.clientWidth + GEOMETRY_TOLERANCE_PX)

      // Cover prominence is preserved: the cover keeps its established
      // viewport-relative height cap rather than being shrunk to make room.
      expect(geometry.cover!.height).toBeGreaterThan(0)
      expect(geometry.cover!.height).toBeLessThanOrEqual(geometry.viewportHeight * 0.5)
    })
  }

  test('the rating view adds no nested scroll container around the action cluster', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(MOBILE_VIEWPORT)
    await createThread(page, {
      title: THREAD_TITLE,
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })

    await enterRatingView(page)

    const result = await page.evaluate(() => {
      const root = document.getElementById('root')
      const actions = document.querySelector('[data-testid="rating-actions"]')
      if (!root || !actions) {
        // SAFETY: Both arrays are empty when root or actions is null, so the type assertion is safe
        return { scrollContainers: [] as string[], position: null as string | null }
      }

      const scrollContainers: string[] = []
      let current: Element | null = actions.parentElement
      while (current && current !== root) {
        const style = window.getComputedStyle(current)
        if (
          style.overflowY !== 'visible' ||
          style.overflowX !== 'visible'
        ) {
          const testid = current.getAttribute('data-testid')
          scrollContainers.push(testid ? `[data-testid="${testid}"]` : current.tagName.toLowerCase())
        }
        current = current.parentElement
      }

      return {
        scrollContainers,
        position: window.getComputedStyle(actions).position,
      }
    })

    // DecisionCard actions remain in normal flow (#2711); the shell owns scrolling.
    expect(result.position).toBe('static')
    expect(
      result.scrollContainers,
      'only #root may scroll around the rating action cluster; a nested overflow wrapper can clip actions without any page-level overflow',
    ).toEqual([])
  })
})
