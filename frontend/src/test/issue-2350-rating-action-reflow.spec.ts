/**
 * Issue #2350: the rating action cluster uses available content width on
 * tablet and wraps secondaries out of one cramped row when space is tight.
 *
 * Acceptance criterion #6 requires a rendered regression at 800×1094 and
 * 390×844 that asserts layout geometry (cluster width vs viewport / actual row
 * stacking), not class strings. This spec measures rendered boxes: at tablet
 * width the cluster must span the pillars grid instead of leaving a canyon,
 * and at iPhone width the secondaries must have wrapped into a stacked layout
 * with comfortable tap widths instead of staying one 7–8px-packed row.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage } from './helpers'

const TABLET_VIEWPORT = { width: 800, height: 1094 }
const MOBILE_VIEWPORT = { width: 390, height: 844 }

type Box = {
  left: number
  right: number
  top: number
  bottom: number
  width: number
  height: number
} | null

interface ReflowGeometry {
  viewport: { width: number; height: number }
  scrollWidth: number
  grid: Box
  actionsCell: Box
  secondary: Box
  secondaryButtons: Array<{
    left: number
    right: number
    top: number
    bottom: number
    width: number
    height: number
    text: string
  }>
}

function noIdentity() {
  return {
    issue_id: 1,
    thread_id: 1,
    thread_title: 'Reflow Thread',
    has_confirmed_identity: false,
    confirmed_mappings: [],
    candidate_mappings: [],
    has_unresolved: false,
  }
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
  await page.route('**/v1/issues/*/reader-context', (route) =>
    route.fulfill({ json: null }),
  )
  await page.route('**/v1/issues/*/comicvine', (route) =>
    route.fulfill({ json: null }),
  )
  await page.route('**/v1/comicvine/issues/*/identity', (route) =>
    route.fulfill({ json: noIdentity() }),
  )
  await page.route('**/v1/continuity/readiness', (route) =>
    route.fulfill({
      json: {
        node_type: 'issue',
        node_id: 1,
        is_readable: true,
        evaluated_issue_id: null,
        blockers: [],
      },
    }),
  )
}

async function enterRatingView(page: Page, title: string): Promise<void> {
  await installRatingRoutes(page)
  await gotoRollPage(page)
  await page.locator('#main-die-3d').click()
  await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 20000 })
  await page.getByText(title).first().click()
  await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })
  await expect(page.getByTestId('rating-actions')).toBeVisible()
  await page.evaluate(async () => {
    if (document.fonts) {
      await document.fonts.ready
    }
  })
  await page.waitForTimeout(150)
}

async function readReflowGeometry(page: Page): Promise<ReflowGeometry> {
  return page.evaluate(() => {
    const rect = (element: Element | null): Box => {
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
    const secondary = document.querySelector('[data-testid="rating-secondary-actions"]')
    const buttons = secondary ? Array.from(secondary.querySelectorAll('button')) : []
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      scrollWidth: document.documentElement.scrollWidth,
      grid: rect(document.querySelector('[data-testid="rating-pillars-grid"]')),
      actionsCell: rect(document.querySelector('[data-testid="rating-actions-grid-cell"]')),
      secondary: rect(secondary),
      secondaryButtons: buttons.map((button) => {
        const r = button.getBoundingClientRect()
        return {
          left: r.left,
          right: r.right,
          top: r.top,
          bottom: r.bottom,
          width: r.width,
          height: r.height,
          text: (button.textContent ?? '').trim(),
        }
      }),
    }
  })
}

function distinctRows(buttons: ReflowGeometry['secondaryButtons']): number {
  const tops = buttons.map((button) => Math.round(button.top))
  return new Set(tops).size
}

function assertNoHorizontalOverflow(g: ReflowGeometry): void {
  expect(g.scrollWidth).toBeLessThanOrEqual(g.viewport.width + 1)
}

test.describe('rating action cluster reflow (issue #2350)', () => {
  test('tablet 800×1094: cluster spans available grid width and secondaries are not cramped', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(TABLET_VIEWPORT)
    await createThread(page, {
      title: 'Reflow Tablet Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await enterRatingView(page, 'Reflow Tablet Thread')

    const g = await readReflowGeometry(page)
    expect(g.grid).not.toBeNull()
    expect(g.actionsCell).not.toBeNull()
    expect(g.secondary).not.toBeNull()

    // The cluster must use the available content width, not leave a
    // phone-width column beside empty space (acceptance criterion #1/#6).
    expect(g.actionsCell!.width / g.grid!.width).toBeGreaterThan(0.85)

    expect(g.secondaryButtons).toHaveLength(3)
    // At tablet the three secondaries lay out on one spread row, each with a
    // comfortable tap width instead of a phone-sized squeezed lane.
    const rows = distinctRows(g.secondaryButtons)
    expect(rows).toBe(1)
    for (const button of g.secondaryButtons) {
      expect(button.width).toBeGreaterThanOrEqual(120)
      expect(button.height).toBeGreaterThanOrEqual(44)
    }

    assertNoHorizontalOverflow(g)
  })

  test('phone 390×844: secondaries wrap out of the packed single row and stay tappable', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(MOBILE_VIEWPORT)
    await createThread(page, {
      title: 'Reflow Mobile Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await enterRatingView(page, 'Reflow Mobile Thread')

    const g = await readReflowGeometry(page)
    expect(g.grid).not.toBeNull()
    expect(g.actionsCell).not.toBeNull()
    expect(g.secondary).not.toBeNull()

    expect(g.secondaryButtons).toHaveLength(3)
    // When insufficient width remains for three comfortable lanes the
    // secondaries must stack/wrap instead of staying one 7–8px-packed row
    // (acceptance criteria #2/#3/#6).
    const rows = distinctRows(g.secondaryButtons)
    expect(rows).toBeGreaterThanOrEqual(2)
    for (const button of g.secondaryButtons) {
      expect(button.width).toBeGreaterThanOrEqual(96)
      expect(button.height).toBeGreaterThanOrEqual(44)
    }

    assertNoHorizontalOverflow(g)
  })
})