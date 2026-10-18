/**
 * Issue #3467: Double-clicking "Pick this series" logged two identical ROLLED
 * cards in the session timeline.
 *
 * Acceptance criteria:
 * - Pick this series is disabled while the request is in flight.
 * - The server ignores a duplicate pick for the same thread in the same session,
 *   so no duplicate event is recorded.
 * - A test double-clicks and asserts exactly one timeline event.
 */
import { expect, type Locator, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage, waitForRollPageReady } from './helpers'

async function openOverridePicker(page: Page, title: string): Promise<Locator> {
  await page.getByRole('button', { name: 'Pick manually' }).click()
  const dialog = page.getByRole('dialog', { name: 'Pick manually' })
  await expect(dialog).toBeVisible()

  const select = dialog.locator('select')
  await expect.poll(() => select.locator('option').count()).toBeGreaterThan(1)

  const option = select.locator('option').filter({ hasText: title }).first()
  const value = await option.getAttribute('value')
  if (!value) throw new Error(`Series "${title}" was not offered in the picker`)
  await select.selectOption(value)
  return dialog
}

test.describe('Issue #3467: Pick this series double-click prevention', () => {
  test('double-clicking Pick this series logs exactly one ROLLED event', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const title = `Double Click Pick ${Date.now()}`
    await createThread(page, {
      title,
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })

    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const dialog = await openOverridePicker(page, title)
    await dialog.getByRole('button', { name: 'Pick this series' }).dblclick()

    await expect(dialog).not.toBeVisible({ timeout: 15000 })
    await expect(page.getByTestId('rating-pillars-grid')).toBeVisible({ timeout: 15000 })

    // The duplicate only ever surfaced in the session timeline, so open the
    // newest session and assert a single ROLLED card for the picked series.
    await page.goto('/history')
    await page
      .getByRole('list', { name: 'Session history' })
      .getByRole('listitem')
      .first()
      .getByRole('link', { name: /View full session/ })
      .click()
    await expect(page.getByRole('heading', { name: 'Event Timeline' })).toBeVisible()

    const rolledCards = page.locator('article').filter({ hasText: 'Rolled' })
    await expect(rolledCards).toHaveCount(1)
    await expect(rolledCards.first()).toContainText(title)
  })

  test('Pick this series is disabled while the request is in flight', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const title = `Disabled Pick ${Date.now()}`
    await createThread(page, {
      title,
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })

    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const dialog = await openOverridePicker(page, title)

    const overrideGate: { release?: () => void } = {}
    const overrideInFlight = new Promise<void>((resolve) => {
      overrideGate.release = resolve
    })
    await page.route('**/roll/override', async (route) => {
      await overrideInFlight
      await route.continue()
    })

    await dialog.getByRole('button', { name: 'Pick this series' }).click()
    await expect(dialog.getByRole('button', { name: 'Selecting...' })).toBeDisabled()

    overrideGate.release?.()
    await expect(dialog).not.toBeVisible({ timeout: 15000 })
  })
})
