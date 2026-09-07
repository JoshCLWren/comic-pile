/**
 * Issue #2299 acceptance: a selected long series title on the Continuity
 * Planner create page stays identifiable at tablet portrait.
 *
 * The selected title used to live only inside a single-line `type="search"`
 * input, whose value is clipped at narrow (tablet) widths and hides the
 * distinguishing suffix. These browser-level checks assert that after choosing
 * a long title the full string is rendered as wrapping selection text that is
 * not horizontally clipped, ellipsized, or horizontally overflowing the page at
 * the reported production viewports (800x1094 and 820x1180), while the
 * selection/search workflow still works end to end.
 */
import { expect, test } from './fixtures'
import type { Page } from '@playwright/test'
import { createThread } from './helpers'

const TABLET_PORTRAIT = { width: 800, height: 1094 } as const
const TABLET_PORTRAIT_820 = { width: 820, height: 1180 } as const

const LONG_TITLE =
  'B.P.R.D.: PLAGUE OF FROGS (COMPLETE OMNIBUS COLLECTION, NEW PRINTING 2025)'

function titlePattern(title: string): RegExp {
  return new RegExp(title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
}

async function selectedTitleGeometry(page: Page) {
  return page.evaluate(() => {
    const el = document.querySelector<HTMLElement>('[data-testid="selected-thread-title"]')
    if (!el) return null
    const styles = window.getComputedStyle(el)
    return {
      clientWidth: el.clientWidth,
      scrollWidth: el.scrollWidth,
      clientHeight: el.clientHeight,
      scrollHeight: el.scrollHeight,
      overflowX: styles.overflowX,
      overflowY: styles.overflowY,
      textOverflow: styles.textOverflow,
      whiteSpace: styles.whiteSpace,
      textContent: el.textContent,
    }
  })
}

test.describe('Continuity Planner selected series title (#2299)', () => {
  for (const viewport of [TABLET_PORTRAIT, TABLET_PORTRAIT_820]) {
    test(`keeps a long selected title fully legible at ${viewport.width}x${viewport.height}`, async ({
      authenticatedPage,
    }) => {
      const page = authenticatedPage
      await createThread(page, {
        title: LONG_TITLE,
        format: 'omnibus',
        issues_remaining: 2,
        total_issues: 2,
      })

      await page.setViewportSize(viewport)
      await page.goto('/continuity-plans/new', { waitUntil: 'domcontentloaded' })
      await expect(page.getByRole('heading', { name: 'Sequential planner' })).toBeVisible()

      const search = page.getByRole('searchbox', { name: 'Comic series' })
      await expect(search).toBeVisible()
      await search.fill('B.P.R.D.')
      await page.getByRole('option', { name: titlePattern(LONG_TITLE) }).click()

      const readout = page.getByTestId('selected-thread-value')
      await expect(readout).toBeVisible()
      await expect(readout).toContainText(LONG_TITLE)

      const geometry = await selectedTitleGeometry(page)
      expect(geometry, 'selected title readout should render after selection').not.toBeNull()
      expect(geometry!.textContent).toBe(LONG_TITLE)
      expect(geometry!.whiteSpace).not.toBe('nowrap')
      expect(geometry!.textOverflow).not.toBe('ellipsis')
      expect(
        geometry!.scrollWidth,
        'selected title must wrap instead of clipping horizontally',
      ).toBeLessThanOrEqual(geometry!.clientWidth + 1)
      expect(
        geometry!.scrollHeight,
        'long title should visually wrap to more than one line',
      ).toBeGreaterThan(geometry!.clientHeight)

      const pageLayout = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        innerWidth: window.innerWidth,
      }))
      expect(pageLayout.scrollWidth).toBeLessThanOrEqual(pageLayout.innerWidth)

      // Selection/search workflow stays intact: issues load for the selected
      // series and an issue can still be added while the title stays legible.
      const issueSelect = page.getByRole('combobox', { name: 'Issue' })
      await expect(issueSelect).toBeEnabled()
      await issueSelect.selectOption({ label: '#1' })
      await page.getByRole('button', { name: 'Add issue' }).click()
      await expect(page.getByTestId('lane-main').getByText(`#1`)).toBeVisible()
      await expect(readout).toContainText(LONG_TITLE)
    })
  }

  test('searching after a selection clears the readout instead of hiding a stale title', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: LONG_TITLE,
      format: 'omnibus',
      issues_remaining: 2,
      total_issues: 2,
    })

    await page.setViewportSize(TABLET_PORTRAIT)
    await page.goto('/continuity-plans/new', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Sequential planner' })).toBeVisible()

    const search = page.getByRole('searchbox', { name: 'Comic series' })
    await search.fill('B.P.R.D.')
    await page.getByRole('option', { name: titlePattern(LONG_TITLE) }).click()
    await expect(page.getByTestId('selected-thread-value')).toContainText(LONG_TITLE)

    // Typing a fresh search clears the previous selection as before.
    await search.fill('B.P.R.D.: HELL')
    await expect(page.getByTestId('selected-thread-value')).toHaveCount(0)
  })
})