/**
 * Issue #2992 (CI bar for #2990 stretch + #2991 vertical title).
 *
 * The #2919/#2942 harnesses prove the two rating regions tile side by side
 * without overlap, but they measure only `rating-region-comic` vs
 * `rating-region-decision`. Those region boxes abut even when the comic
 * *content* (cover / header) hugs the left edge of a huge `1fr` track while
 * the decision card sits hundreds of pixels away on the far right. Green
 * must mean clustered, not just non-overlapping.
 *
 * Contract asserted here at lg+ (~1280+), in rendered geometry:
 * 1. The dead space between comic *content* (cover / title / progress) and
 *    the decision card is on the order of `gap-4`/`gap-6`, not hundreds of
 *    px of empty track (#2990).
 * 2. The series title keeps meaningful horizontal width (not ~1ch), keeps a
 *    sane block height (no one-glyph-per-line cascade), and uses horizontal
 *    writing mode (#2991).
 * 3. The progress line keeps meaningful width when present (#2991).
 * 4. The regions still tile without overlap (preserve the #2952 win).
 *
 * Wide viewports also exercise #2990: expanding the shell must not expand
 * the empty track between the comic content and decision card.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage } from './helpers'

const THREAD_TITLE = 'Density Issue 2992'

/** Sub-pixel rounding only; a real layout error is measured in tens of pixels. */
const GEOMETRY_TOLERANCE_PX = 2

/**
 * Visual-grammar order of magnitude: major regions separate by `gap-4`
 * (16px) / `gap-6` (24px). Anything near 100px+ between content and the
 * decision card is manufactured empty track, not grouping.
 */
const MAX_CONTENT_DECISION_GAP_PX = 96

/** A normal short harness title renders one ~30px line; a one-glyph-per-line cascade is an order of magnitude taller. */
const MAX_TITLE_HEIGHT_PX = 72

/** A collapsed vertical cascade shrinks the title box to ~1ch wide. */
const MIN_TITLE_WIDTH_PX = 80
const MIN_PROGRESS_WIDTH_PX = 48

/** Small opaque SVG so the cover never reaches the production image optimizer. */
const COVER_DATA_URI = (() => {
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="600"><rect width="400" height="600" fill="#111"/></svg>'
  return `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`
})()

const VIEWPORTS = [
  { label: '1024', width: 1024, height: 800 },
  { label: '1280', width: 1280, height: 800 },
  { label: '1440', width: 1440, height: 900 },
  { label: '1920', width: 1920, height: 900 },
  { label: '2560', width: 2560, height: 900 },
]

interface DOMRectSnapshot {
  left: number
  right: number
  top: number
  bottom: number
  width: number
  height: number
}

interface DensityGeometry {
  root: { scrollWidth: number; clientWidth: number }
  grid: DOMRectSnapshot | null
  comic: DOMRectSnapshot | null
  decision: DOMRectSnapshot | null
  cover: DOMRectSnapshot | null
  title: (DOMRectSnapshot & { writingMode: string }) | null
  progress: DOMRectSnapshot | null
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
        comicvine_issue_id: '2992',
        comicvine_url: null,
        series_name: 'Density Series',
        series_id: 2992,
        issue_number: '1',
        name: 'Density Issue',
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
  await expect(page.getByTestId('comic-header-title')).toBeVisible()
  await page.evaluate(async () => {
    if (document.fonts) {
      await document.fonts.ready
    }
  })
  // Let the mocked intelligence/identity responses settle so measured boxes are
  // final rather than mid-skeleton.
  await page.waitForTimeout(300)
}

async function readDensityGeometry(page: Page): Promise<DensityGeometry> {
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
    const titleElement = document.querySelector('[data-testid="comic-header-title"]')
    const titleBox = snapshot(titleElement)
    return {
      root: {
        scrollWidth: root?.scrollWidth ?? 0,
        clientWidth: root?.clientWidth ?? 0,
      },
      grid: snapshot(document.querySelector('[data-testid="rating-pillars-grid"]')),
      comic: snapshot(document.querySelector('[data-testid="rating-region-comic"]')),
      decision: snapshot(document.querySelector('[data-testid="rating-region-decision"]')),
      cover: snapshot(document.querySelector('[data-testid="comic-cover"]')),
      title: titleBox
        ? {
            ...titleBox,
            writingMode: titleElement
              ? window.getComputedStyle(titleElement).writingMode
              : '',
          }
        : null,
      progress: snapshot(document.querySelector('[data-testid="comic-progress-line"]')),
    }
  })
}

test.describe('Issue #2992 Roll density and title guard', () => {
  for (const viewport of VIEWPORTS) {
    test(`comic content clusters with the decision card at ${viewport.label}px`, async ({
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

      const geometry = await readDensityGeometry(page)
      expect(geometry.comic, 'the comic region must be present').not.toBeNull()
      expect(geometry.decision, 'the action/details region must be present').not.toBeNull()
      expect(geometry.cover, 'the cover must be present').not.toBeNull()
      expect(geometry.title, 'the series title must be present').not.toBeNull()

      // Preserve the #2952 win: regions tile side by side without overlap.
      expect(
        geometry.decision!.left,
        'the action/details region must start at or after the cover region ends',
      ).toBeGreaterThanOrEqual(geometry.comic!.right - GEOMETRY_TOLERANCE_PX)

      // #2990: measure content, not region boxes. The region boxes abut even
      // when a huge empty `1fr` track separates the cover/title from the
      // decision card.
      const contentRight = Math.max(geometry.cover!.right, geometry.title!.right)
      const deadSpace = geometry.decision!.left - contentRight
      expect(
        deadSpace,
        `comic content must cluster with the decision card (gap order of gap-4/gap-6, got ${Math.round(deadSpace)}px of dead track)`,
      ).toBeLessThanOrEqual(MAX_CONTENT_DECISION_GAP_PX)

      // #2991: the title must keep meaningful horizontal width, not collapse
      // to ~1ch in a vertical letter cascade.
      expect(
        geometry.title!.width,
        'the series title must keep meaningful horizontal width',
      ).toBeGreaterThanOrEqual(MIN_TITLE_WIDTH_PX)
      expect(
        geometry.title!.height,
        'the series title must not cascade one glyph per line',
      ).toBeLessThanOrEqual(MAX_TITLE_HEIGHT_PX)
      expect(
        geometry.title!.writingMode,
        'the series title must use horizontal typography',
      ).toBe('horizontal-tb')

      // #2991: the progress line must stay readable when present.
      if (geometry.progress) {
        expect(
          geometry.progress.width,
          'the progress line must keep meaningful width',
        ).toBeGreaterThanOrEqual(MIN_PROGRESS_WIDTH_PX)
      }

      // No horizontal overflow in the shell scroll box.
      expect(
        geometry.root.scrollWidth,
        'the Roll result must not introduce horizontal scrolling',
      ).toBeLessThanOrEqual(geometry.root.clientWidth + GEOMETRY_TOLERANCE_PX)
    })
  }
})
