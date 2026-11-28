/**
 * MOBILE-001: Primary mobile interaction path works for core user journeys.
 *
 * Verifies that core flows work on a mobile viewport (390x844): navigation
 * renders the mobile tab bar, the roll page is functional, rating works,
 * and queue management is accessible.
 *
 * Inventory IDs: MOBILE-001
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import {
  createThread,
  gotoQueue,
  rollPoolThreadByTitle,
  waitForQueueReady,
  waitForRollPageReady,
} from './helpers'

const MOBILE_VIEWPORT = { width: 390, height: 844 }

test.describe('MOBILE-001: Primary mobile interaction path', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize(MOBILE_VIEWPORT)
  })

  test('mobile navigation bar is visible on home page', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(MOBILE_VIEWPORT)
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await page.locator('#root').waitFor({ state: 'visible' })

    const mobileNav = page.getByRole('navigation', { name: 'Mobile navigation' })
    await expect(mobileNav).toBeVisible()
  })

  test('mobile navigation keeps all five tabs aligned at narrow phone widths', async ({ authenticatedPage }, testInfo) => {
    const page = authenticatedPage
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    const mobileNav = page.getByRole('navigation', { name: 'Mobile navigation' })

    for (const width of [320, 375, 390, 430]) {
      await page.setViewportSize({ width, height: 844 })
      await expect(mobileNav).toBeVisible()
      await expect(mobileNav.locator('.nav-item')).toHaveCount(5)
      await expect(mobileNav.getByRole('link', { name: 'Reading plans page' })).toHaveText('Plans')
      await page.evaluate(async () => { await document.fonts.ready })

      const tabs = await mobileNav.locator('.nav-item').evaluateAll(items => items.map(item => {
        const icon = item.querySelector('svg')
        const label = item.querySelector('.nav-label')
        if (!icon || !label) throw new Error('Navigation tab must have an icon and label')
        const tabRect = item.getBoundingClientRect()
        const iconRect = icon.getBoundingClientRect()
        const labelRect = label.getBoundingClientRect()
        return {
          width: tabRect.width,
          height: tabRect.height,
          left: tabRect.left,
          right: tabRect.right,
          iconTop: iconRect.top,
          labelTop: labelRect.top,
          labelHeight: labelRect.height,
          lineHeight: Number.parseFloat(getComputedStyle(label).lineHeight),
          labelLeft: labelRect.left,
          labelRight: labelRect.right,
        }
      }))

      const first = tabs[0]
      for (const tab of tabs) {
        expect(tab.width).toBeGreaterThanOrEqual(44)
        expect(tab.height).toBeGreaterThanOrEqual(44)
        expect(Math.abs(tab.width - first.width)).toBeLessThanOrEqual(1)
        expect(Math.abs(tab.height - first.height)).toBeLessThanOrEqual(1)
        expect(Math.abs(tab.iconTop - first.iconTop)).toBeLessThanOrEqual(1)
        expect(Math.abs(tab.labelTop - first.labelTop)).toBeLessThanOrEqual(1)
        expect(tab.labelHeight).toBeLessThanOrEqual(tab.lineHeight + 1)
        expect(tab.labelLeft).toBeGreaterThanOrEqual(tab.left - 1)
        expect(tab.labelRight).toBeLessThanOrEqual(tab.right + 1)
        expect(tab.left).toBeGreaterThanOrEqual(0)
        expect(tab.right).toBeLessThanOrEqual(width)
      }
      await testInfo.attach(`mobile-navigation-${width}`, { body: await mobileNav.screenshot(), contentType: 'image/png' })
    }
  })

  test('mobile roll page: die is visible and roll works', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(MOBILE_VIEWPORT)
    await createThread(page, {
      title: 'Mobile Roll Thread',
      issues_remaining: 3,
      total_issues: 3,
    })

    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await waitForRollPageReady(page)

    const die = page.locator('#main-die-3d')
    await expect(die).toBeVisible()
    await die.click()

    const pool = page.locator('[data-roll-pool]')
    await expect(pool).toBeVisible({ timeout: 15000 })
    await expect(rollPoolThreadByTitle(page, 'Mobile Roll Thread')).toBeVisible()
  })

  test('mobile queue page is navigable and shows threads', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(MOBILE_VIEWPORT)
    await createThread(page, {
      title: 'Mobile Queue Thread',
      issues_remaining: 2,
      total_issues: 2,
    })

    const mobileNav = page.getByRole('navigation', { name: 'Mobile navigation' })
    await expect(mobileNav).toBeVisible()
    await mobileNav.getByRole('link', { name: /queue/i }).click()

    await waitForQueueReady(page)
    await expect(
      page.getByTestId('queue-thread-item').filter({ hasText: 'Mobile Queue Thread' }),
    ).toBeVisible({ timeout: 10000 })
  })

  test('mobile rating flow works end-to-end', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(MOBILE_VIEWPORT)
    await createThread(page, {
      title: 'Mobile Rate Thread',
      issues_remaining: 3,
      total_issues: 3,
    })

    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await waitForRollPageReady(page)

    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 15000 })
    await rollPoolThreadByTitle(page, 'Mobile Rate Thread').click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })

    await page.locator('#rating-input').fill('3')

    const rateResponse = page.waitForResponse(
      (resp) => resp.url().includes('/api/v2/issues/') && resp.request().method() === 'PATCH',
    )
    await page.locator('button[data-testid="save-and-continue"]').click()
    const response = await rateResponse
    expect(response.ok()).toBeTruthy()
  })

  test('mobile queue: create thread via modal', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(MOBILE_VIEWPORT)

    const mobileNav = page.getByRole('navigation', { name: 'Mobile navigation' })
    await expect(mobileNav).toBeVisible()
    await mobileNav.getByRole('link', { name: /queue/i }).click()
    await waitForQueueReady(page)

    const addBtn = page.getByRole('button', { name: /add series/i }).first()
    await addBtn.click()

    await page.locator('#create-thread-title').fill('Mobile Created Thread')
    await page.locator('#create-thread-issues').fill('1-3')
    await page.getByRole('button', { name: /create series/i }).click()

    await expect(
      page.getByTestId('queue-thread-item').filter({ hasText: 'Mobile Created Thread' }),
    ).toBeVisible({ timeout: 10000 })
  })

  test('mobile layout has no horizontal overflow', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(MOBILE_VIEWPORT)
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await page.locator('#root').waitFor({ state: 'visible' })

    const fit = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }))
    expect(fit.scrollWidth).toBeLessThanOrEqual(fit.innerWidth)
  })
})
