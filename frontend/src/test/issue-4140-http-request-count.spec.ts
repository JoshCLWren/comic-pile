/**
 * Issue #4140: Roll → Queue navigation optimization.
 *
 * Acceptance contract (from the issue): after rolling and navigating to Queue
 * via the "Back to Queue" button, no HTTP request should be made to
 * `/api/v1/roll/bootstrap` during navigation.
 *
 * This test specifically verifies:
 * 1. When leaving Roll via the back to queue button, zero HTTP requests are made to `/api/v1/roll/bootstrap`
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage, waitForQueueReady } from './helpers'

test.describe('Issue #4140: HTTP request count verification', () => {
  test('Back to Queue button does not trigger roll bootstrap HTTP request', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const title = 'HTTP Request Count Thread'
    await createThread(page, {
      title,
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })

    // Track HTTP requests to /api/v1/roll/bootstrap
    let bootstrapRequests = 0
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/roll/bootstrap') && request.method() === 'GET') {
        bootstrapRequests++
      }
    })

    // 1. Roll once to enter the rating view
    await gotoRollPage(page)
    await page.getByTestId('roll-primary-action').click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 20000 })
    
    // Initial bootstrap request should have been made
    expect(bootstrapRequests).toBe(1)

    // 2. Click the "Back to Queue" button
    await page.getByTestId('roll-back-to-queue').click()
    
    // Wait for navigation to complete
    await waitForQueueReady(page)
    
    // 3. Verify no additional bootstrap request was made during navigation
    expect(bootstrapRequests).toBe(1) // Should still be 1, not 2
  })

  test('Round-trip Roll → Queue → Roll preserves pending selection', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const title = 'Round-trip Thread'
    await createThread(page, {
      title,
      format: 'Comic',
      issues_remaining: 2,
      total_issues: 2,
    })

    // Track HTTP requests to /api/v1/roll/bootstrap
    let bootstrapRequests = 0
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/roll/bootstrap') && request.method() === 'GET') {
        bootstrapRequests++
      }
    })

    // 1. Roll once to enter the rating view
    await gotoRollPage(page)
    await page.getByTestId('roll-primary-action').click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 20000 })
    
    // Initial bootstrap request should have been made
    expect(bootstrapRequests).toBe(1)

    // 2. Start rating but don't save
    await page.locator('#rating-input').evaluate((el, value) => {
      (el as HTMLInputElement).value = value
      el.dispatchEvent(new Event('input', { bubbles: true }))
      el.dispatchEvent(new Event('change', { bubbles: true }))
    }, '4')

    // 3. Click the "Back to Queue" button
    await page.getByTestId('roll-back-to-queue').click()

    // Wait for navigation to complete
    await waitForQueueReady(page)

    // 4. Verify no additional bootstrap request was made during navigation
    expect(bootstrapRequests).toBe(1) // Should still be 1, not 2
    
    // 5. Navigate back to Roll
    await page.getByRole('link', { name: 'Roll page' }).click()
    await expect(page.getByTestId('rating-view-top')).toBeVisible({ timeout: 20000 })

    // 6. Verify the pending selection is preserved
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 20000 })
    const heading = page.locator('[data-testid="comic-header-title"]')
    await expect(heading).toContainText(title)

    // 7. Verify the save button is still available (indicating pending read is preserved)
    await expect(page.getByTestId('save-and-continue')).toBeVisible()
    
    // 8. Verify a bootstrap request was made when returning to Roll
    expect(bootstrapRequests).toBe(2)
  })
})