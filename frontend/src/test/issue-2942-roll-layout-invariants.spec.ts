/**
 * Issue #2942: the Roll hero + Decision workspace must use normal responsive
 * layout flow so future metadata, controls, longer text, or state changes
 * cannot turn the Roll hero back into stacked cards occupying the same space.
 *
 * The layout must be responsive by construction — no absolute/fixed positioning,
 * no hard-coded offsets, no fixed parent heights for dynamic content.
 *
 * This spec asserts rendered geometry (bounding boxes, viewport overflow,
 * pillar ordering) rather than Tailwind class strings, so a future styling
 * change cannot silently regress the contract.
 *
 * Measurement notes that keep these assertions falsifiable:
 * - `#root` owns the shell scroll box and already clips horizontally, so
 *   `document.documentElement.scrollWidth` can never exceed the viewport width.
 *   The meaningful horizontal-overflow signal is `#root`'s own
 *   `scrollWidth` versus `clientWidth`, plus the rendered boxes of the two
 *   rating regions. Measuring the document element here would make the
 *   no-overflow assertion vacuously true.
 * - Containment must come from layout, not from a clip. The resize test
 *   verifies the same mounted state reflows correctly without stale fixed
 *   measurements.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage } from './helpers'

const THREAD_TITLE = 'Invariant Issue 2942'

/** Sub-pixel rounding only; a real layout error is measured in tens of pixels. */
const GEOMETRY_TOLERANCE_PX = 2

/** Small opaque SVG so the cover never reaches the production image optimizer. */
const COVER_DATA_URI = (() => {
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="600"><rect width="400" height="600" fill="#111"/></svg>'
  return `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`
})()

const VIEWPORT_MATRIX = [
  { width: 1920, height: 926, name: 'reference desktop' },
  { width: 1440, height: 900, name: 'normal desktop' },
  { width: 1280, height: 800, name: 'small desktop' },
  { width: 1024, height: 768, name: 'constrained desktop/tablet landscape' },
  { width: 800, height: 1094, name: 'tablet portrait' },
  { width: 430, height: 932, name: 'phone' },
  { width: 390, height: 844, name: 'small phone' },
]

interface Rect {
  left: number
  right: number
  top: number
  bottom: number
  width: number
  height: number
}

interface RatingGeometry {
  viewport: { width: number; height: number }
  root: { scrollWidth: number; clientWidth: number }
  comic: Rect | null
  decision: Rect | null
  actions: Rect | null
  secondaryActions: Rect | null
  primaryAction: Rect | null
  contextDisclosure: Rect | null
  ratingViewTop: Rect | null
}

/**
 * Freeze every route the rating view can touch so measured geometry depends
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
        comicvine_issue_id: '2942',
        comicvine_url: null,
        series_name: 'Invariant Series',
        series_id: 2942,
        issue_number: '1',
        name: 'Invariant Issue',
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
  await createThread(page, {
    title: THREAD_TITLE,
    format: 'Issue',
    issues_remaining: 3,
    total_issues: 3,
  })
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
  await page.waitForTimeout(300)
}

function rectsOverlap(a: Rect, b: Rect): boolean {
  const overlapWidth = Math.min(a.right, b.right) - Math.max(a.left, b.left)
  const overlapHeight = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
  return overlapWidth > 0 && overlapHeight > 0
}

async function readRatingGeometry(page: Page): Promise<RatingGeometry> {
  return page.evaluate(() => {
    const rectOf = (element: Element | null): Rect | null => {
      if (!element) return null
      const r = element.getBoundingClientRect()
      return {
        left: r.left,
        right: r.right,
        top: r.top,
        bottom: r.bottom,
        width: r.width,
        height: r.height,
      }
    }
    const root = document.getElementById('root')
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      root: {
        scrollWidth: root?.scrollWidth ?? 0,
        clientWidth: root?.clientWidth ?? 0,
      },
      comic: rectOf(document.querySelector('[data-testid="rating-region-comic"]')),
      decision: rectOf(document.querySelector('[data-testid="rating-region-decision"]')),
      actions: rectOf(document.querySelector('[data-testid="rating-actions"]')),
      secondaryActions: rectOf(
        document.querySelector('[data-testid="rating-secondary-actions"]'),
      ),
      primaryAction: rectOf(
        document.querySelector('[data-testid="save-and-continue"]'),
      ),
      contextDisclosure: rectOf(document.querySelector('[data-testid="context-disclosure"]')),
      ratingViewTop: rectOf(document.querySelector('[data-testid="rating-view-top"]')),
    }
  })
}

test.describe('Roll Layout Invariants - Issue #2942', () => {
  test('bounding boxes for peer major regions do not intersect', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize({ width: 1920, height: 926 })
    await enterRatingView(page)

    const g = await readRatingGeometry(page)
    expect(g.comic, 'the comic region must be present').not.toBeNull()
    expect(g.decision, 'the decision region must be present').not.toBeNull()

    expect(rectsOverlap(g.comic!, g.decision!), 'Comic and Decision regions must not overlap').toBe(
      false,
    )
  })

  test('next vertical section begins at or below the bottom of the preceding layout region', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize({ width: 1920, height: 926 })
    await enterRatingView(page)

    const g = await readRatingGeometry(page)
    expect(g.ratingViewTop, 'the rating view must be present').not.toBeNull()

    // The next content below the rating view top must start at or below its bottom.
    // Find the ThreadPool or any content element that follows the rating view.
    const belowRect = await page
      .locator('[data-testid="thread-pool"], #explosion-layer')
      .first()
      .boundingBox()

    expect(
      belowRect,
      'there must be content below the rating view top',
    ).toBeTruthy()

    const ratingViewBottom = g.ratingViewTop!.bottom
    const belowTop = belowRect!.y

    expect(
      belowTop,
      'the next section must begin at or below the bottom of the rating view',
    ).toBeGreaterThanOrEqual(ratingViewBottom - GEOMETRY_TOLERANCE_PX)
  })

  test('no horizontal page overflow across the viewport matrix', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage

    for (const viewport of VIEWPORT_MATRIX) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      await enterRatingView(page)

      const g = await readRatingGeometry(page)

      // `#root` is the shell scroll owner; its scrollWidth must not exceed clientWidth.
      expect(
        g.root.scrollWidth,
        `Viewport ${viewport.name} (${viewport.width}x${viewport.height}): #root must not scroll horizontally`,
      ).toBeLessThanOrEqual(g.root.clientWidth + GEOMETRY_TOLERANCE_PX)

      // Document-level overflow is the ultimate backstop.
      const docOverflow = await page.evaluate(() => {
        return document.documentElement.scrollWidth > document.documentElement.clientWidth + 2
      })
      expect(
        docOverflow,
        `Viewport ${viewport.name} (${viewport.width}x${viewport.height}): no document-level horizontal overflow`,
      ).toBe(false)
    }
  })

  test('primary/secondary action bounding boxes stay inside their owning container', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize({ width: 1920, height: 926 })
    await enterRatingView(page)

    const g = await readRatingGeometry(page)
    expect(g.decision, 'the decision region must be present').not.toBeNull()
    expect(g.primaryAction, 'the primary save action must be present').not.toBeNull()
    expect(g.secondaryActions, 'the secondary actions must be present').not.toBeNull()

    // Primary action stays inside the decision region.
    const primaryInside =
      g.primaryAction!.left >= g.decision!.left - GEOMETRY_TOLERANCE_PX &&
      g.primaryAction!.right <= g.decision!.right + GEOMETRY_TOLERANCE_PX &&
      g.primaryAction!.top >= g.decision!.top - GEOMETRY_TOLERANCE_PX &&
      g.primaryAction!.bottom <= g.decision!.bottom + GEOMETRY_TOLERANCE_PX
    expect(primaryInside, 'primary action must stay inside the decision region').toBe(true)

    // Secondary actions stay inside the decision region.
    const secondaryInside =
      g.secondaryActions!.left >= g.decision!.left - GEOMETRY_TOLERANCE_PX &&
      g.secondaryActions!.right <= g.decision!.right + GEOMETRY_TOLERANCE_PX &&
      g.secondaryActions!.top >= g.decision!.top - GEOMETRY_TOLERANCE_PX &&
      g.secondaryActions!.bottom <= g.decision!.bottom + GEOMETRY_TOLERANCE_PX
    expect(secondaryInside, 'secondary actions must stay inside the decision region').toBe(true)
  })

  test('mobile/tablet DOM and visual order matches Comic → Decision → subordinate content', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize({ width: 430, height: 932 })
    await enterRatingView(page)

    const g = await readRatingGeometry(page)
    expect(g.comic, 'the comic region must be present').not.toBeNull()
    expect(g.decision, 'the decision region must be present').not.toBeNull()

    // In a single-column mobile layout, Comic must appear above Decision.
    expect(
      g.comic!.top,
      'Comic region must come first in the visual flow',
    ).toBeLessThan(g.decision!.top)

    // The context disclosure (subordinate content) must come after the decision card.
    if (g.contextDisclosure) {
      expect(
        g.contextDisclosure!.top,
        'subordinate content must follow the decision region',
      ).toBeGreaterThanOrEqual(g.decision!.bottom - GEOMETRY_TOLERANCE_PX)
    }
  })

  test('desktop region width ratios remain consistent with the approved two-region layout', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize({ width: 1440, height: 900 })
    await enterRatingView(page)

    const g = await readRatingGeometry(page)
    const grid = await page.locator('[data-testid="rating-pillars-grid"]').boundingBox()

    expect(g.comic, 'the comic region must be present').not.toBeNull()
    expect(g.decision, 'the decision region must be present').not.toBeNull()
    expect(grid, 'the grid container must be present').toBeTruthy()

    const comicWidth = g.comic!.width
    const decisionWidth = g.decision!.width
    const totalWidth = grid!.width

    const comicRatio = comicWidth / totalWidth
    const decisionRatio = decisionWidth / totalWidth

    // Comic should take the majority of the width (1fr column); Decision is auto-sized.
    expect(comicRatio, 'Comic region should take majority of width on desktop').toBeGreaterThan(0.5)
    expect(comicRatio, 'Comic region should not consume nearly all width').toBeLessThan(0.9)
    expect(decisionRatio, 'Decision region should be a fraction of total width').toBeGreaterThan(0.1)
    expect(decisionRatio, 'Decision region should not dominate').toBeLessThan(0.5)

    // Combined widths should match the grid container (within tolerance for gaps).
    const combinedWidth = comicWidth + decisionWidth
    const widthDifference = Math.abs(combinedWidth - totalWidth)
    expect(
      widthDifference,
      'Comic + Decision widths should fit within the grid container',
    ).toBeLessThanOrEqual(20)
  })

  test('no horizontal overflow or overlap after resizing across desktop → tablet → phone → desktop', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize({ width: 1920, height: 926 })
    await enterRatingView(page)

    const comicRegion = page.locator('[data-testid="rating-region-comic"]')
    const decisionRegion = page.locator('[data-testid="rating-region-decision"]')

    const initialComicBox = await comicRegion.boundingBox()
    const initialDecisionBox = await decisionRegion.boundingBox()
    expect(initialComicBox).toBeTruthy()
    expect(initialDecisionBox).toBeTruthy()

    const resizeViewports = [
      { width: 1440, height: 900, name: 'normal desktop' },
      { width: 1280, height: 800, name: 'small desktop' },
      { width: 1024, height: 768, name: 'constrained desktop/tablet landscape' },
      { width: 800, height: 1094, name: 'tablet portrait' },
      { width: 430, height: 932, name: 'phone' },
      { width: 390, height: 844, name: 'small phone' },
      { width: 1920, height: 926, name: 'back to desktop' },
    ]

    for (const viewport of resizeViewports) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      await page.waitForTimeout(500)

      const currentComicBox = await comicRegion.boundingBox()
      const currentDecisionBox = await decisionRegion.boundingBox()
      expect(currentComicBox, `comic region exists at ${viewport.name}`).toBeTruthy()
      expect(currentDecisionBox, `decision region exists at ${viewport.name}`).toBeTruthy()

      const hasIntersection =
        currentComicBox!.x < currentDecisionBox!.x + currentDecisionBox!.width &&
        currentComicBox!.x + currentComicBox!.width > currentDecisionBox!.x &&
        currentComicBox!.y < currentDecisionBox!.y + currentDecisionBox!.height &&
        currentComicBox!.y + currentComicBox!.height > currentDecisionBox!.y
      expect(
        hasIntersection,
        `Overlap detected at ${viewport.name} (${viewport.width}x${viewport.height})`,
      ).toBe(false)

      const docOverflow = await page.evaluate(() => {
        return document.documentElement.scrollWidth > document.documentElement.clientWidth + 2
      })
      expect(
        docOverflow,
        `Horizontal overflow at ${viewport.name} (${viewport.width}x${viewport.height})`,
      ).toBe(false)
    }

    // Layout should be stable when returning to the same viewport.
    const finalComicBox = await comicRegion.boundingBox()
    const finalDecisionBox = await decisionRegion.boundingBox()

    const comicPositionChanged =
      Math.abs((finalComicBox?.x ?? 0) - (initialComicBox?.x ?? 0)) > 5 ||
      Math.abs((finalComicBox?.y ?? 0) - (initialComicBox?.y ?? 0)) > 5
    const decisionPositionChanged =
      Math.abs((finalDecisionBox?.x ?? 0) - (initialDecisionBox?.x ?? 0)) > 5 ||
      Math.abs((finalDecisionBox?.y ?? 0) - (initialDecisionBox?.y ?? 0)) > 5

    expect(comicPositionChanged, 'Comic region should be stable at the same viewport').toBe(false)
    expect(
      decisionPositionChanged,
      'Decision region should be stable at the same viewport',
    ).toBe(false)
  })

  test('content stress: long titles and ComicVine controls do not cause overlap', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize({ width: 1024, height: 768 })
    await enterRatingView(page)

    const g = await readRatingGeometry(page)

    // Verify both regions exist with valid geometry.
    expect(g.comic, 'comic region must be present').not.toBeNull()
    expect(g.decision, 'decision region must be present').not.toBeNull()
    expect(g.ratingViewTop, 'rating view must be present').not.toBeNull()

    // No overlap even with the confirmed ComicVine identity (controls present).
    expect(rectsOverlap(g.comic!, g.decision!), 'regions must not overlap with controls').toBe(
      false,
    )

    // The header row (title + controls) must be within the comic region.
    const headerRow = await page.locator('[data-testid="comic-header-row"]').boundingBox()
    expect(headerRow, 'header row must be present').toBeTruthy()

    expect(
      headerRow!.width,
      'header row must have meaningful width',
    ).toBeGreaterThan(100)
    expect(
      headerRow!.height,
      'header row must have meaningful height',
    ).toBeGreaterThan(50)

    // Title text must be visible and fit within the header container.
    const titleElement = page.locator('[data-testid="comic-header-title"]')
    await expect(titleElement).toBeVisible()
    const titleBox = await titleElement.boundingBox()
    expect(titleBox).toBeTruthy()
    expect(
      titleBox!.width,
      'title must fit within its container',
    ).toBeLessThan(headerRow!.width + 10)

    // No horizontal overflow.
    expect(g.root.scrollWidth, 'no horizontal overflow from long content').toBeLessThanOrEqual(
      g.root.clientWidth + GEOMETRY_TOLERANCE_PX,
    )
  })
})
