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

  test('mobile roll page: die is visible and roll works', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(MOBILE_VIEWPORT)
    await createThread(page, {
      title: 'Mobile Roll Thread',
      format: 'Issue',
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
    await expect(pool.getByText('Mobile Roll Thread')).toBeVisible()
  })

  test('mobile queue page is navigable and shows threads', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize(MOBILE_VIEWPORT)
    await createThread(page, {
      title: 'Mobile Queue Thread',
      format: 'Comic',
      issues_remaining: 2,
      total_issues: 2,
    })

    const mobileNav = page.getByRole('navigation', { name: 'Mobile navigation' })
    await expect(mobileNav).toBeVisible()
    await mobileNav.getByRole('link', { name: /queue/i }).click()

    await waitForQueueReady(page)
    await expect(page.getByText('Mobile Queue Thread')).toBeVisible({ timeout: 10000 })
  })

  test('mobile rating flow works end-to-end', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await page.setViewportSize(MOBILE_VIEWPORT)
    await createThread(page, {
      title: 'Mobile Rate Thread',
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })

    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await waitForRollPageReady(page)

    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 15000 })
    await page.getByText('Mobile Rate Thread').first().click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })

    await page.locator('#rating-input').fill('3')

    const rateResponse = page.waitForResponse(
      (resp) => resp.url().includes('/api/v1/rate/') && resp.request().method() === 'POST',
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

    const addBtn = page.getByRole('button', { name: /add thread/i }).first()
    await addBtn.click()

    await page.locator('#create-thread-title').fill('Mobile Created Thread')
    await page.locator('#create-thread-issues').fill('1-3')
    await page.getByRole('button', { name: /create thread/i }).click()

    await expect(page.getByText('Mobile Created Thread')).toBeVisible({ timeout: 10000 })
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
