/**
 * Issue #2352: Roll comic cover loads through one stable portrait surface.
 *
 * The production defect was a multi-stage cover transition (pulse -> dark
 * frame -> image) rendered inside a frame that became landscape/square when
 * the viewport-height cap won (w-full + max-height + aspect-ratio). These
 * browser checks assert *rendered* cover geometry — bounding boxes, not
 * Tailwind class strings — on a wide desktop and a narrow phone viewport:
 *
 * - the cover frame stays portrait-shaped (narrower than it is tall);
 * - the frame height never exceeds the 45vh viewport budget;
 * - once the intrinsic artwork has loaded, the frame ratio matches the
 *   artwork ratio, proving there are no artificial side gutters or cropping;
 * - neither viewport gains horizontal overflow.
 *
 * This mirrors the deterministic fixture/mocking pattern of issue-1943 so the
 * comic identity routes never depend on whichever production comic happens to
 * be in the queue.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage } from './helpers'

const DESKTOP_VIEWPORT = { width: 1920, height: 1080 }
const PHONE_VIEWPORT = { width: 390, height: 844 }

/** Small opaque SVG used so the cover never hits the image optimizer. */
const COVER_DATA_URI = (() => {
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="600"><rect width="400" height="600" fill="#111"/></svg>'
  return `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`
})()

async function installCoverRoutes(page: Page): Promise<void> {
  await page.route('**/v1/threads/*/reading-orders', (route) =>
    route.fulfill({ json: { reading_orders: [] } }),
  )
  await page.route('**/v1/threads/*/connected', (route) =>
    route.fulfill({ json: { connected_threads: [] } }),
  )
  await page.route('**/v1/reading-order-groups/threads/*/groups', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/v1/issues/*/reader-context', (route) =>
    route.fulfill({ json: null }),
  )
  await page.route('**/v1/issues/*/comicvine', (route) =>
    route.fulfill({ json: { comicvine_issue_id: '77777', comicvine_url: null, series_name: 'Cover Geometry', series_id: 7, issue_number: '1', name: 'One Stable Surface', description: null, image_url: COVER_DATA_URI, cover_date: '2026-01-01', store_date: null, creators: [], story_arcs: [] } }),
  )
  await page.route('**/v1/comicvine/issues/*/identity', (route) =>
    route.fulfill({ json: { issue_id: 1, thread_id: 1, thread_title: 'Cover Geometry Thread', has_confirmed_identity: true, confirmed_mappings: [], candidate_mappings: [], has_unresolved: false } }),
  )
  await page.route('**/v1/continuity/readiness', (route) =>
    route.fulfill({ json: { node_type: 'issue', node_id: 1, is_readable: true, evaluated_issue_id: null, blockers: [] } }),
  )
}

async function enterRatingViewForCover(page: Page, title: string): Promise<void> {
  await installCoverRoutes(page)
  await gotoRollPage(page)
  await page.locator('#main-die-3d').click()
  await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 20000 })
  await page.getByText(title).first().click()
  await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })
  await expect(page.getByTestId('rating-actions')).toBeVisible()
  await expect(page.getByText('ComicVine linked').first()).toBeVisible({ timeout: 10000 })
  await page.evaluate(async () => {
    if (document.fonts) {
      await document.fonts.ready
    }
  })
}

type Box = {
  top: number
  left: number
  right: number
  bottom: number
  width: number
  height: number
} | null

interface CoverGeometry {
  viewport: { width: number; height: number }
  scrollWidth: number
  cover: Box
  img: Box
  naturalWidth: number
  naturalHeight: number
}

async function readCoverGeometry(page: Page): Promise<CoverGeometry> {
  return page.evaluate(() => {
    const box = (el: Element | null): Box => {
      if (!el) return null
      const r = el.getBoundingClientRect()
      return { top: r.top, left: r.left, right: r.right, bottom: r.bottom, width: r.width, height: r.height }
    }
    const cover = document.querySelector('[data-testid="comic-cover"]')
    const img = cover ? cover.querySelector('img') : null
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      scrollWidth: document.documentElement.scrollWidth,
      cover: box(cover),
      img: box(img),
      naturalWidth: img ? img.naturalWidth : 0,
      naturalHeight: img ? img.naturalHeight : 0,
    }
  })
}

async function waitForCoverImageLoaded(page: Page): Promise<void> {
  await page.waitForFunction(() => {
    const img = document.querySelector<HTMLImageElement>('[data-testid="comic-cover"] img')
    return img !== null && img.complete && img.naturalWidth > 0 && img.naturalHeight > 0
  })
  await page.waitForTimeout(250)
}

function assertPortraitCoverWithoutGutters(g: CoverGeometry): void {
  expect(g.cover, 'a confirmed identity must render the cover frame').not.toBeNull()
  expect(
    g.cover!.width,
    'the cover frame must be narrower than it is tall (portrait)',
  ).toBeLessThan(g.cover!.height)
  const coverRatio = g.cover!.width / g.cover!.height
  expect(coverRatio, 'a comic cover must not be square or landscape').toBeGreaterThan(0.5)
  expect(coverRatio, 'a comic cover must stay clearly portrait').toBeLessThan(0.8)
  expect(
    g.cover!.height,
    'the cover must never exceed the 45vh viewport budget',
  ).toBeLessThanOrEqual(Math.round(g.viewport.height * 0.45) + 2)

  const naturalRatio = g.naturalWidth / g.naturalHeight
  expect(naturalRatio, 'the artwork intrinsic size must be known').toBeGreaterThan(0)
  expect(
    coverRatio,
    'the loaded frame must match the artwork ratio so there are no gutters',
  ).toBeCloseTo(naturalRatio, 1)
}

async function createCoverThread(page: Page, title: string): Promise<void> {
  await createThread(page, {
    title,
    format: 'Comic',
    issues_remaining: 3,
    total_issues: 3,
  })
}

test.describe('Roll comic cover keeps one stable portrait surface (issue #2352)', () => {
  test('wide desktop renders a portrait cover frame within the viewport budget that matches the artwork', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await createCoverThread(page, 'Desktop Cover Geometry')
    await enterRatingViewForCover(page, 'Desktop Cover Geometry')
    await waitForCoverImageLoaded(page)

    const g = await readCoverGeometry(page)
    expect(g.img, 'the loaded artwork must be visible inside the cover frame').not.toBeNull()
    expect(g.scrollWidth).toBeLessThanOrEqual(g.viewport.width)
    assertPortraitCoverWithoutGutters(g)
  })

  test('narrow phone renders a portrait cover frame within the viewport budget without overflow', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(PHONE_VIEWPORT)
    await createCoverThread(page, 'Phone Cover Geometry')
    await enterRatingViewForCover(page, 'Phone Cover Geometry')
    await waitForCoverImageLoaded(page)

    const g = await readCoverGeometry(page)
    expect(g.img, 'the loaded artwork must be visible inside the cover frame').not.toBeNull()
    expect(g.scrollWidth).toBeLessThanOrEqual(g.viewport.width)
    assertPortraitCoverWithoutGutters(g)
  })
})