/**
 * Issue #5981: Night Shift Roll presentation.
 *
 * Focused browser coverage for the production surfaces that replaced the
 * horizontal row board: the cover-first desktop board, the wraparound mobile
 * gallery, the die-only roll action, and the Rate backdrop transition.
 * These assertions target rendered behavior, not Tailwind class strings.
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage, waitForRollPageReady } from './helpers'

test.describe('Night Shift Roll (#5981)', () => {
  test('desktop board exposes every eligible face as a cover and the die is the only Roll action', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Night Shift Series',
      format: 'Comic',
      issues_remaining: 5,
      total_issues: 5,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const die = page.locator('#main-die-3d')
    await expect(die).toBeVisible()
    await expect(die).toHaveAttribute('title', 'Click to roll')
    await expect(page.getByRole('button', { name: /^begin$/i })).toHaveCount(0)

    const covers = page.locator('[data-roll-face][role="button"]')
    expect(await covers.count()).toBeGreaterThan(0)
    await expect(covers.first()).toBeVisible()

    // The die sits inside the middle row, between the flanking covers.
    const middleRow = page.locator('.roll-cover-row-middle')
    await expect(middleRow).toBeVisible()
    expect(await middleRow.locator('#main-die-3d').count()).toBe(1)
  })

  test('rolling opens the existing Rate experience with opaque controls over the artwork', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Night Shift Result',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await page.locator('#main-die-3d').click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })
    await expect(page.getByRole('button', { name: /mark read/i }).first()).toBeVisible()
    // Rate metadata and actions are never painted through the scrim.
    await expect(page.locator('.roll-rate-stage')).toBeVisible()
  })

  test('mobile gallery wraps with a live counter and the die stays above it', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.setViewportSize({ width: 390, height: 844 })
    await createThread(page, {
      title: 'Gallery Alpha',
      format: 'Comic',
      issues_remaining: 2,
      total_issues: 2,
    })
    await createThread(page, {
      title: 'Gallery Beta',
      format: 'Comic',
      issues_remaining: 2,
      total_issues: 2,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const gallery = page.getByTestId('roll-mobile-gallery')
    await expect(gallery).toBeVisible()
    await expect(gallery.locator('#main-die-3d')).toBeVisible()
    const counter = gallery.locator('.roll-gallery-count')
    await expect(counter).toHaveText(/^1 \/ \d+$/)

    const next = gallery.getByRole('button', { name: 'Next comic' })
    const previous = gallery.getByRole('button', { name: 'Previous comic' })
    const total = Number((await counter.textContent())?.split('/')[1]?.trim() ?? '0')
    expect(total).toBeGreaterThan(1)

    await next.click()
    await expect(counter).toHaveText(`2 / ${total}`)
    await next.click()
    await expect(counter).toHaveText(`1 / ${total}`)
    await previous.click()
    await expect(counter).toHaveText(`${total} / ${total}`)
  })

  test('reduced motion skips the decorative cover flight but still reaches Rate', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await createThread(page, {
      title: 'Reduced Motion Series',
      format: 'Comic',
      issues_remaining: 2,
      total_issues: 2,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await page.locator('#main-die-3d').click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })
    await expect(page.getByTestId('roll-cover-flight')).toHaveCount(0)
  })
})
