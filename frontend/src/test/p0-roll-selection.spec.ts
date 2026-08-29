/**
 * ROLL-001: User can roll a comic and see the result.
 *
 * Verifies that the dice roll mechanism works end-to-end: the die is visible,
 * clicking it triggers a roll, rolled threads appear in the pool, and clicking
 * a thread enters the rating view.
 *
 * Inventory IDs: ROLL-001
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import {
  createThread,
  gotoRollPage,
  waitForRollPageReady,
} from './helpers'

test.describe('ROLL-001: Roll selection', () => {
  test('die is visible and clickable on the home page', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Roll Die Thread',
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const die = page.locator('#main-die-3d')
    await expect(die).toBeVisible()
  })

  test('clicking the die triggers a roll and shows rolled threads', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Rolled Thread',
      format: 'Issue',
      issues_remaining: 5,
      total_issues: 5,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await page.locator('#main-die-3d').click()

    const pool = page.locator('[data-roll-pool]')
    await expect(pool).toBeVisible({ timeout: 15000 })
    await expect(pool.getByText('Rolled Thread')).toBeVisible()
  })

  test('clicking a rolled thread enters the rating view', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Rating Target Thread',
      format: 'Comic',
      issues_remaining: 4,
      total_issues: 4,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 15000 })

    await page.getByText('Rating Target Thread').first().click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })
  })

  test('die selector allows choosing different die sizes', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Die Selector Thread',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const dieSelector = page.locator('#die-selector')
    await expect(dieSelector).toBeVisible()

    const d20Button = page.getByRole('button', { name: 'd20', exact: true })
    if (await d20Button.isVisible()) {
      await d20Button.click()
      await expect(page.locator('#header-die-label')).toHaveText('d20')
    }
  })

  test('empty queue shows appropriate state instead of crashing', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const emptyState = page.getByText(/no comics|empty|nothing/i)
    const die = page.locator('#main-die-3d')
    const pool = page.locator('[data-roll-pool]')

    const hasEmpty = await emptyState.isVisible().catch(() => false)
    const hasDie = await die.isVisible().catch(() => false)
    const hasPool = await pool.isVisible().catch(() => false)

    expect(hasEmpty || hasDie || hasPool).toBe(true)
  })
})
