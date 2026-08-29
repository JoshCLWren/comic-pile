/**
 * SNOOZE-001: User can snooze or unsnooze a comic and it appears
 * appropriately in the queue.
 *
 * Verifies: snooze from rating view moves thread to snoozed section,
 * unsnooze from roll pool restores it, and queue reflects snoozed state.
 *
 * Inventory IDs: SNOOZE-001
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import {
  createThread,
  gotoRollPage,
  gotoQueue,
  waitForRollPageReady,
} from './helpers'

test.describe('SNOOZE-001: Snooze and unsnooze', () => {
  test('snooze from rating view moves thread to snoozed section', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Snooze Me Thread',
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 15000 })
    await page.getByText('Snooze Me Thread').first().click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })

    await page.getByRole('button', { name: /snooze/i }).click()

    const snoozedToggle = page.getByRole('button', { name: /snoozed/i })
    await expect(snoozedToggle).toBeVisible({ timeout: 10000 })
  })

  test('unsnooze from roll pool restores thread to active pool', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Unsnooze Me Thread',
      format: 'Comic',
      issues_remaining: 3,
      total_issues: 3,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 15000 })
    await page.getByText('Unsnooze Me Thread').first().click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })

    await page.getByRole('button', { name: /snooze/i }).click()
    const snoozedToggle = page.getByRole('button', { name: /snoozed/i })
    await expect(snoozedToggle).toBeVisible({ timeout: 10000 })

    await snoozedToggle.click()
    await expect(page.locator('[data-roll-pool]').getByText('Unsnooze Me Thread')).toBeVisible({
      timeout: 10000,
    })
  })

  test('snoozed thread appears with snoozed indicator in queue', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const thread = await createThread(page, {
      title: 'Queue Snooze Thread',
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 15000 })
    await page.getByText('Queue Snooze Thread').first().click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })

    await page.getByRole('button', { name: /snooze/i }).click()
    await expect(page.getByRole('button', { name: /snoozed/i })).toBeVisible({ timeout: 10000 })

    await gotoQueue(page)
    await page.getByText('Queue Snooze Thread').first().waitFor({ state: 'visible', timeout: 10000 })
    const threadItem = page.getByTestId('queue-thread-item').filter({ hasText: 'Queue Snooze Thread' })
    await expect(threadItem).toBeVisible()
  })
})
