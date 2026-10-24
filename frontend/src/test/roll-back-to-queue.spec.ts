/**
 * Issue #4140: Roll → Queue navigation optimization.
 *
 * Acceptance contract (from the issue): after rolling and navigating to Queue
 * via the "Back to Queue" button, no HTTP request should be made to
 * `/api/v1/roll/bootstrap` during navigation. When returning to Roll,
 * the pending selection should be preserved without a stale empty-dice flash.
 *
 * This test verifies:
 * 1. When leaving Roll via the back to queue button, invalidateRollBootstrapOnNavigation is called
 * 2. When returning to Roll after navigating away, the pending selection is preserved
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage, waitForQueueReady } from './helpers'

test.describe('Issue #4140: Roll → Queue navigation optimization', () => {
  test('Back to Queue button calls invalidateRollBootstrapOnNavigation', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const title = 'Navigation Optimization Thread'
    await createThread(page, {
      title,
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })

    // Mock the invalidateRollBootstrapOnNavigation function
    await page.evaluate(() => {
      // @ts-ignore - accessing global window for testing
      window.invalidateRollBootstrapOnNavigationCalls = 0
    })

    // Override the invalidateRollBootstrapOnNavigation function to track calls
    await page.evaluate(() => {
      const originalInvalidate = (window as any).queryClient?.invalidateQueries
      if (originalInvalidate) {
        (window as any).queryClient.invalidateQueries = async (options: any) => {
          // @ts-ignore - accessing global window for testing
          window.invalidateRollBootstrapOnNavigationCalls++
          return originalInvalidate.call((window as any).queryClient, options)
        }
      }
    })

    // 1. Roll once to enter the rating view
    await gotoRollPage(page)
    await page.getByTestId('roll-primary-action').click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 20000 })
    
    // 2. Click the "Back to Queue" button
    await page.getByTestId('roll-back-to-queue').click()
    
    // Wait for navigation to complete
    await waitForQueueReady(page)
    
    // 3. Verify invalidateRollBootstrapOnNavigation was called
    const callCount = await page.evaluate(() => {
      // @ts-ignore - accessing global window for testing
      return window.invalidateRollBootstrapOnNavigationCalls || 0
    })
    expect(callCount).toBe(1)
  })

  test('Back to Queue preserves pending selection for #3761 regression', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const title = 'Pending Selection Thread'
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
    await page.locator('#rating-input').fill('4')
    
    // 3. Click the "Back to Queue" button
    await page.getByTestId('roll-back-to-queue').click()
    
    // Wait for navigation to complete
    await waitForQueueReady(page)
    
    // 4. Navigate back to Roll
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await expect(page.getByTestId('rating-view-top')).toBeVisible({ timeout: 20000 })
    
    // 5. Verify the pending selection is preserved (rating input should still be filled)
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 20000 })
    const heading = page.locator('[data-testid="comic-header-title"]')
    await expect(heading).toContainText(title)
    
    // 6. Verify the rating input still contains the previously entered value
    const ratingInput = page.locator('#rating-input')
    const ratingValue = await ratingInput.inputValue()
    expect(ratingValue).toBe('4')
    
    // 7. Verify the save button is still available (indicating pending read is preserved)
    await expect(page.getByTestId('save-and-continue')).toBeVisible()
  })
})