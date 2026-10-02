/**
 * Roll layout containment guard.
 *
 * This is intentionally geometry-based. The repeated Roll regressions were all
 * structurally valid DOM that looked fine to class-level tests while cover/header
 * content escaped its grid track and painted underneath the decision card.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage } from './helpers'

const THREAD_TITLE =
  'Annihilation Nova Extremely Long Responsive Layout Regression Guard'
const GEOMETRY_TOLERANCE_PX = 2

const COVER_DATA_URI = (() => {
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="600"><rect width="400" height="600" fill="#111"/></svg>'
  return `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`
})()

const VIEWPORTS = [
  { width: 320, height: 800 },
  { width: 375, height: 812 },
  { width: 768, height: 1024 },
  { width: 1024, height: 800 },
  { width: 1280, height: 800 },
  { width: 1440, height: 900 },
  { width: 1600, height: 900 },
  { width: 1920, height: 1080 },
]

interface RectSnapshot {
  left: number
  right: number
  top: number
  bottom: number
  width: number
  height: number
}

interface LayoutGeometry {
  root: { scrollWidth: number; clientWidth: number }
  comic: RectSnapshot
  decision: RectSnapshot
  cover: RectSnapshot
  header: RectSnapshot
  title: RectSnapshot
  progress: RectSnapshot | null
  controls: RectSnapshot
}

function intersects(a: RectSnapshot, b: RectSnapshot): boolean {
  const overlapWidth = Math.min(a.right, b.right) - Math.max(a.left, b.left)
  const overlapHeight = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
  return overlapWidth > GEOMETRY_TOLERANCE_PX && overlapHeight > GEOMETRY_TOLERANCE_PX
}

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
        comicvine_issue_id: '105477',
        comicvine_url: null,
        series_name: 'Annihilation: Nova',
        series_id: 105477,
        issue_number: '3',
        name: 'Safety In Numbers',
        description: null,
        image_url: COVER_DATA_URI,
        cover_date: '2006-06-21',
        store_date: '2006-06-21',
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
        comicvine_issue_id: '105477',
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
  await expect(page.getByTestId('comic-header-controls')).toBeVisible()
  // #3008: correction actions are collapsed behind one quiet overflow trigger
  // and the mapping status stays readable beside it.
  await expect(page.getByTestId('comic-mapping-status')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Comic corrections' })).toBeVisible()
  await page.evaluate(async () => {
    if (document.fonts) await document.fonts.ready
  })
  await page.waitForTimeout(300)
}

async function readGeometry(page: Page): Promise<LayoutGeometry> {
  return page.evaluate(() => {
    const requiredRect = (selector: string) => {
      const element = document.querySelector(selector)
      if (!element) throw new Error(`Missing required element: ${selector}`)
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
    const optionalRect = (selector: string) => {
      const element = document.querySelector(selector)
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
    if (!root) throw new Error('Missing #root')

    return {
      root: { scrollWidth: root.scrollWidth, clientWidth: root.clientWidth },
      comic: requiredRect('[data-testid="rating-region-comic"]'),
      decision: requiredRect('[data-testid="rating-region-decision"]'),
      cover: requiredRect('[data-testid="comic-cover"]'),
      header: requiredRect('[data-testid="comic-header-row"]'),
      title: requiredRect('[data-testid="comic-header-title"]'),
      progress: optionalRect('[data-testid="comic-progress-line"]'),
      controls: requiredRect('[data-testid="comic-header-controls"]'),
    }
  })
}

function expectHorizontallyContained(child: RectSnapshot, parent: RectSnapshot, label: string) {
  expect(child.left, `${label} must not escape the comic region on the left`).toBeGreaterThanOrEqual(
    parent.left - GEOMETRY_TOLERANCE_PX,
  )
  expect(child.right, `${label} must not escape the comic region on the right`).toBeLessThanOrEqual(
    parent.right + GEOMETRY_TOLERANCE_PX,
  )
}

test.describe('Roll layout containment', () => {
  for (const viewport of VIEWPORTS) {
    test(`no Roll region or control overlap at ${viewport.width}px`, async ({ authenticatedPage }) => {
      const page = authenticatedPage
      await page.setViewportSize(viewport)
      await createThread(page, {
        title: THREAD_TITLE,
        format: 'Comic',
        issues_remaining: 2,
        total_issues: 4,
      })

      await enterRatingView(page)
      const geometry = await readGeometry(page)

      expect(
        geometry.root.scrollWidth,
        'Roll must not introduce horizontal page scrolling',
      ).toBeLessThanOrEqual(geometry.root.clientWidth + GEOMETRY_TOLERANCE_PX)

      for (const [label, rect] of [
        ['cover', geometry.cover],
        ['header', geometry.header],
        ['title', geometry.title],
        ['controls', geometry.controls],
      ] as const) {
        expectHorizontallyContained(rect, geometry.comic, label)
        expect(intersects(rect, geometry.decision), `${label} must never paint under DecisionCard`).toBe(false)
      }
      if (geometry.progress) {
        expectHorizontallyContained(geometry.progress, geometry.comic, 'progress')
        expect(intersects(geometry.progress, geometry.decision), 'progress must never paint under DecisionCard').toBe(false)
      }

      expect(intersects(geometry.comic, geometry.decision), 'primary Roll regions must never intersect').toBe(false)

      if (viewport.width >= 1024) {
        expect(
          geometry.header.left,
          'desktop header must occupy the track beside the cover',
        ).toBeGreaterThanOrEqual(geometry.cover.right - GEOMETRY_TOLERANCE_PX)
      } else {
        expect(
          geometry.header.top,
          'narrow layout must stack the header below the comic identity rail',
        ).toBeGreaterThanOrEqual(geometry.cover.bottom - GEOMETRY_TOLERANCE_PX)
      }
    })
  }
})
