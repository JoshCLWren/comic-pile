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

  const picker = dialog.getByRole('combobox')
  await picker.click()
  await picker.fill(title)
  await expect.poll(() => dialog.getByRole('option').count()).toBeGreaterThan(0)

  const option = dialog.getByRole('option').filter({ hasText: title }).first()
  await option.click()
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

    // #4822 makes the owner-scoped activity stream the reader-visible history,
    // so assert a single rolled action for the picked series there. A second
    // double-click-created roll would appear as a second list item.
    await page.goto('/history')
    const activity = page.getByRole('list', { name: 'Activity history' })
    await expect(activity).toBeVisible()

    const rolledCards = activity.getByRole('listitem').filter({ hasText: 'Rolled' })
    await expect(rolledCards.filter({ hasText: title })).toHaveCount(1)
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

    let overrideGate: (() => void) | undefined
    const overrideInFlight = new Promise<void>((resolve) => {
      overrideGate = resolve
    })
    await page.route('**/roll/override', async (route) => {
      await overrideInFlight
      await route.continue()
    })

    await dialog.getByRole('button', { name: 'Pick this series' }).click()
    await expect(dialog.getByRole('button', { name: 'Selecting...' })).toBeDisabled()

    overrideGate?.()
    await expect(dialog).not.toBeVisible({ timeout: 15000 })
  })
})
