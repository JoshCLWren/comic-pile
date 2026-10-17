/**
 * Issue #3466: Double-clicking "Create Series" creates two identical series
 *
 * Acceptance criteria:
 * - Create Series is disabled from first click until response arrives
 * - Server is idempotent for duplicate create requests
 * - Test double-clicks Create Series and asserts exactly one series is created
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import { gotoQueue, waitForQueueReady, dismissRollNudgeIfPresent } from './helpers'

test.describe('Issue #3466: Create Series double-click prevention', () => {
  test('double-clicking Create Series creates only one series', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await gotoQueue(page)
    await waitForQueueReady(page)

    const uniqueTitle = `DoubleClick Test ${Date.now()}`
    await page.getByRole('button', { name: /add series/i }).first().click()
    await page.locator('#create-thread-title').fill(uniqueTitle)
    const formatSelect = page.locator('#create-thread-format')
    if (await formatSelect.isVisible()) {
      await formatSelect.selectOption({ index: 1 })
    }
    await page.locator('#create-thread-issues').fill('1-3')

    const createButton = page.getByRole('button', { name: /create series/i })
    // Double click rapidly
    await createButton.dblclick()

    // Wait for creation to settle
    await expect(page.getByText(uniqueTitle)).toBeVisible({ timeout: 15000 })

    // Assert exactly one instance appears in the queue
    const matches = page.getByText(uniqueTitle)
    const count = await matches.count()
    expect(count).toBe(1)

    await dismissRollNudgeIfPresent(page)
  })
})
