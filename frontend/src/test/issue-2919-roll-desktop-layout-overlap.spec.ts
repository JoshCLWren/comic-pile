/**
 * Issue #2919: Fix Roll result layout overlapping cover and clipping offscreen.
 *
 * Acceptance contract:
 * 1. At ~1792×896 the action/details panel must not overlap the comic cover.
 * 2. Cover, roll controls, and metadata must occupy non-overlapping regions.
 * 3. Nothing clipped beyond the right viewport edge.
 * 4. No page-level horizontal scrolling is introduced.
 * 5. Verify at ~1440, ~1600, ~1792, and ~1920 px.
 * 6. Preserve existing cover prominence and control hierarchy.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage } from './helpers'

const COVER_DATA_URI = (() => {
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="600"><rect width="400" height="600" fill="#111"/></svg>'
  return `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`
})()

async function enterRatingView(page: Page, title: string) {
  await gotoRollPage(page)
  await page.locator('#main-die-3d').click()
  await expect(page.getByRole('button', { name: 'Roll' })).toBeVisible({ timeout: 20000 })
  await page.getByText(title).first().click()
  await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })
  await expect(page.getByTestId('rating-actions')).toBeVisible()
  await page.evaluate(async () => {
    if (document.fonts) await document.fonts.ready
  })
}

function assertNoHorizontalOverflow(page: Page) {
  return page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
    bodyScrollWidth: document.body.scrollWidth,
  }))
}

async function readLayoutGeometry(page: Page) {
  return page.evaluate(() => {
    const box = (el: Element | null) => {
      if (!el) return null
      const r = el.getBoundingClientRect()
      return { x: r.x, y: r.y, top: r.top, left: r.left, right: r.right, bottom: r.bottom, width: r.width, height: r.height }
    }
    const cover = document.querySelector('[data-testid="comic-cover"]')
    const comic = document.querySelector('[data-testid="rating-region-comic"]')
    const decision = document.querySelector('[data-testid="rating-region-decision"]')
    const actions = document.querySelector('[data-testid="rating-actions"]')
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      scrollWidth: document.documentElement.scrollWidth,
      cover: box(cover),
      comic: box(comic),
      decision: box(decision),
      actions: box(actions),
    }
  })
}

test.describe('Issue #2919 roll result layout overlap and overflow', () => {
  const VIEWPORTS = [
    { label: '1440p', width: 1440, height: 900 },
    { label: '1600p', width: 1600, height: 900 },
    { label: '1792p', width: 1792, height: 896 },
    { label: '1920p', width: 1920, height: 1080 },
  ]

  for (const vp of VIEWPORTS) {
    test(`no cover/action overlap and no horizontal overflow at ${vp.label}`, async ({ authenticatedPage }) => {
      const page = authenticatedPage
      await page.setViewportSize({ width: vp.width, height: vp.height })
      await createThread(page, { title: 'Layout Issue 2919', format: 'Comic', issues_remaining: 3, total_issues: 3 })

      // Install minimal comicvine data so cover renders
      await page.route('**/v1/issues/*/comicvine', (route) =>
        route.fulfill({
          json: {
            comicvine_issue_id: '2919',
            comicvine_url: null,
            series_name: 'Layout Test',
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
        route.fulfill({ json: { issue_id: 1, thread_id: 1, thread_title: 'Layout Issue 2919', has_confirmed_identity: true, confirmed_mappings: [], candidate_mappings: [], has_unresolved: false } }),
      )
      await page.route('**/v1/issues/*/reader-context', (route) =>
        route.fulfill({ json: null }),
      )

      await enterRatingView(page, 'Layout Issue 2919')

      const g = await readLayoutGeometry(page)
      expect(g.comic).not.toBeNull()
      expect(g.decision).not.toBeNull()
      expect(g.actions).not.toBeNull()

      // Cover and decision must sit side-by-side with no overlap
      if (g.comic && g.decision) {
        expect(g.decision!.left).toBeGreaterThanOrEqual(g.comic!.right)
      }

      // No clipping beyond right viewport edge
      expect(g.decision!.right).toBeLessThanOrEqual(vp.width + 2)

      // No horizontal page overflow
      const overflow = await assertNoHorizontalOverflow(page)
      expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.viewportWidth + 1)
    })
  }
})
