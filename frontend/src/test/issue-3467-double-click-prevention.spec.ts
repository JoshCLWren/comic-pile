/**
 * Issue #3467: Double-clicking "Pick this series" logs two identical ROLLED cards in the session timeline
 *
 * Acceptance criteria:
 * - Pick this series is disabled while the request is in flight
 * - The server ignores a duplicate pick for the same thread in the same session, so no duplicate event is recorded
 * - A test double-clicks and asserts exactly one timeline event
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import { gotoRollPage, waitForRollPageReady } from './helpers'

test.describe('Issue #3467: Pick this series double-click prevention', () => {
  test('double-clicking Pick this series creates only one roll event', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    // Open the manual picker
    await page.getByRole('button', { name: /^Pick manually$/ }).click()
    
    // Wait for the modal to appear
    const dialog = page.getByRole('dialog', { name: 'Pick manually' })
    await expect(dialog).toBeVisible()
    
    // Select the first thread in the list
    const threadSelect = dialog.locator('select')
    await expect.poll(async () => threadSelect.locator('option').count()).toBeGreaterThan(1)
    await threadSelect.selectOption({ index: 1 })
    
    // Get the "Pick this series" button
    const pickButton = dialog.getByRole('button', { name: /Pick this series/ })
    
    // Double-click rapidly to simulate the issue
    await pickButton.dblclick()
    
    // Wait for the modal to close and rating view to appear
    await expect(dialog).not.toBeVisible()
    await expect(page.getByTestId('rating-pillars-grid')).toBeVisible()
    
    // Navigate to History to check timeline events
    await page.goto('/history')
    
    // Wait for history to load
    await expect(page.getByRole('heading', { name: /History/i })).toBeVisible()
    
    // Check that only one ROLLED event appears for this thread
    const rolledEvents = page.getByRole('listitem').filter({ hasText: 'ROLLED' })
    const eventCount = await rolledEvents.count()
    
    // Should be exactly one ROLLED event (not two)
    expect(eventCount).toBe(1)
  })

  test('Pick this series button is disabled during request', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    await gotoRoll(page)
    await waitForRollReady(page)

    // Open the manual picker
    await page.getByRole('button', { name: /^Pick manually$/ }).click()
    
    // Wait for the modal to appear
    const dialog = page.getByRole('dialog', { name: 'Pick manually' })
    await expect(dialog).toBeVisible()
    
    // Select the first thread in the list
    const threadSelect = dialog.locator('select')
    await expect.poll(async () => threadSelect.locator('option').count()).toBeGreaterThan(1)
    await threadSelect.selectOption({ index: 1 })
    
    // Get the "Pick this series" button
    const pickButton = dialog.getByRole('button', { name: /Pick this series/ })
    
    // Click once to start the request
    await pickButton.click()
    
    // Button should be disabled during the request
    await expect(pickButton).toBeDisabled()
    await expect(pickButton).toHaveText('Selecting...')
    
    // Wait for the request to complete
    await expect(dialog).not.toBeVisible()
    
    // Button should be enabled again after the modal closes
    // (We can't test this directly since the modal closes, but we can verify
    // the button was disabled during the request)
  })
})