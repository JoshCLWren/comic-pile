/**
 * Issue #4350: browser-owned Roll pending selection.
 *
 * The retired `GET /api/v2/roll/bootstrap` and `POST /api/v2/readingSessions`
 * must never appear in a real Roll flow. Pending is an exact browser selection:
 * it survives a reload, is cleared by a committed rate of that same issue, and
 * a cancel clears it without any server call.
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage, startRequestLedger } from './helpers'

function retiredRequestCounts(
  ledger: { count: (method: string, path: string) => number },
): { bootstrap: number; sessionPost: number } {
  return {
    bootstrap: ledger.count('GET', '/api/v2/roll/bootstrap'),
    sessionPost: ledger.count('POST', '/api/v2/readingSessions'),
  }
}

test.describe('Issue #4350: browser-owned Roll pending', () => {
  test('Roll → reload → Rate → next Roll uses no retired request', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Browser Pending Series',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    const ledger = startRequestLedger(page)
    await gotoRollPage(page)

    await page.getByTestId('roll-primary-action').click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 20000 })

    // Reload restores the exact pending selection from browser storage.
    await page.reload()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 20000 })

    await page.locator('#rating-input').evaluate((el, value) => {
      // SAFETY: Playwright passes a generic Element; the rating input is an <input>.
      (el as HTMLInputElement).value = value
      el.dispatchEvent(new Event('input', { bubbles: true }))
      el.dispatchEvent(new Event('change', { bubbles: true }))
    }, '4')
    await page.getByTestId('save-and-continue').click()
    await expect(page.getByTestId('roll-primary-action')).toBeVisible({ timeout: 20000 })

    // A second roll works after the committed rate; neither retired operation
    // was used on either pass.
    await page.getByTestId('roll-primary-action').click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 20000 })
    expect(retiredRequestCounts(ledger)).toEqual({ bootstrap: 0, sessionPost: 0 })
  })

  test('cancel clears pending without a dismiss or bootstrap request', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Cancel Pending Series',
      format: 'Comic',
      issues_remaining: 2,
      total_issues: 2,
    })
    const ledger = startRequestLedger(page)
    await gotoRollPage(page)
    await page.getByTestId('roll-primary-action').click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 20000 })

    const before = retiredRequestCounts(ledger)
    await page.getByRole('button', { name: 'cancel rating' }).click()
    await expect(page.getByTestId('roll-primary-action')).toBeVisible({ timeout: 20000 })
    expect(retiredRequestCounts(ledger)).toEqual(before)

    // Reload must not rehydrate a cancelled selection.
    await page.reload()
    await expect(page.getByTestId('roll-primary-action')).toBeVisible({ timeout: 20000 })
  })
})
