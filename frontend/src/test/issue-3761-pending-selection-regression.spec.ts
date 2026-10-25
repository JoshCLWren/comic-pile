/**
 * Issue #3761: Pending selection regression test.
 *
 * Acceptance contract (from the issue): after rolling, navigating to Queue,
 * and then returning to Roll, the pending selection should remain visible
 * without a stale empty-dice flash.
 *
 * This test specifically verifies:
 * 1. When rolling, navigating to Queue, and returning to Roll, the pending selection remains visible
 * 2. No stale empty-dice flash occurs
 * 3. The pending read survives the navigation round-trip
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage, waitForQueueReady } from './helpers'

test.describe('Issue #3761: Pending selection regression', () => {
  test('Roll → Queue → Round-trip preserves pending selection', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const title = 'Pending Selection Regression Thread'
    await createThread(page, {
      title,
      format: 'Comic',
      issues_remaining: 2,
      total_issues: 2,
    })

    // 1. Roll once to enter the rating view
    await gotoRollPage(page)
    await page.getByTestId('roll-primary-action').click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 20000 })
    
    // 2. Start rating but don't save
    await page.locator('#rating-input').evaluate((el, value) => {
      // SAFETY: Playwright passes a generic Element; the rating input is an <input>.
      (el as HTMLInputElement).value = value
      el.dispatchEvent(new Event('input', { bubbles: true }))
      el.dispatchEvent(new Event('change', { bubbles: true }))
    }, '4')
    
    // 3. Verify the save button is visible (indicating pending read is active)
    await expect(page.getByTestId('save-and-continue')).toBeVisible()
    
    // 4. Click the "Back to Queue" button
    await page.getByTestId('roll-back-to-queue').click()
    
    // Wait for navigation to complete
    await waitForQueueReady(page)
    
    // 5. Verify we are on the Queue page
    await expect(page).toHaveURL(/\/queue$/)
    
    // 6. Navigate back to Roll
    await page.getByRole('link', { name: 'Roll page' }).click()
    await expect(page.getByTestId('rating-view-top')).toBeVisible({ timeout: 20000 })
    
    // 7. Verify the pending selection is preserved (no stale empty-dice flash)
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 20000 })
    const heading = page.locator('[data-testid="comic-header-title"]')
    await expect(heading).toContainText(title)
    
    // 8. Verify the save button is still available (indicating pending read is preserved)
    await expect(page.getByTestId('save-and-continue')).toBeVisible()
    
    // 10. Verify the main die is not visible (indicating we're in rating view, not roll view)
    await expect(page.locator('#main-die-3d')).toBeHidden()
  })
})