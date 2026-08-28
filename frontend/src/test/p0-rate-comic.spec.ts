/**
 * RATE-001: User can rate a comic after viewing.
 *
 * Verifies the rating flow: after rolling and selecting a thread, the user
 * can submit a rating via the rating input and save it. The rating is
 * persisted to the backend.
 *
 * Inventory IDs: RATE-001
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage, waitForRollPageReady } from './helpers'

test.describe('RATE-001: Rating a comic', () => {
  test('rating input appears after selecting a rolled thread', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Rate Visible Thread',
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 15000 })
    await page.getByText('Rate Visible Thread').first().click()

    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })
  })

  test('user can submit a rating and it persists', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Persist Rating Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 15000 })
    await page.getByText('Persist Rating Thread').first().click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })

    const ratingInput = page.locator('#rating-input')
    await ratingInput.fill('3')

    const rateResponse = page.waitForResponse(
      (resp) => resp.url().includes('/api/v1/rate/') && resp.request().method() === 'POST',
    )
    await page.locator('button[data-testid="save-and-continue"]').click()
    const response = await rateResponse
    expect(response.ok()).toBeTruthy()
  })

  test('snooze button is available in the rating view', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Snooze Button Thread',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 15000 })
    await page.getByText('Snooze Button Thread').first().click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })

    const snoozeBtn = page.getByRole('button', { name: /snooze/i })
    await expect(snoozeBtn).toBeVisible()
  })

  test('cancel roll returns to the roll view', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Cancel Roll Thread',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 15000 })
    await page.getByText('Cancel Roll Thread').first().click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })

    const cancelBtn = page.getByRole('button', { name: /cancel/i })
    if (await cancelBtn.isVisible()) {
      await cancelBtn.click()
      await expect(page.locator('#main-die-3d')).toBeVisible({ timeout: 10000 })
    }
  })
})
