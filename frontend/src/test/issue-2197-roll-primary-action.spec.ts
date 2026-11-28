/**
 * Issue #2197 / #5981: Roll primary-action hierarchy.
 *
 * The #2197 finding removed a competing solid "Pick manually" button. Night
 * Shift (#5981) goes one step further: the die itself is the only Roll action,
 * with a tooltip and accessible name, and no separate BEGIN/ROLL button may
 * reintroduce the ambiguity. "Pick manually" stays demoted in the header.
 *
 * These are rendered-behavior assertions (accessible names, tooltips and
 * computed styles), not class-string checks.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage, waitForRollPageReady } from './helpers'

async function computedBackground(page: Page, selector: string): Promise<string> {
  return page.locator(selector).evaluate((el) => getComputedStyle(el).backgroundColor)
}

test.describe('Roll primary-action hierarchy (#2197, #5981)', () => {
  test('the die is the sole Roll action and manual pick stays secondary', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Primary Action Thread',
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const die = page.locator('#main-die-3d')
    await expect(die).toBeVisible()
    await expect(die).toHaveAttribute('title', 'Click to roll')
    await expect(die).toHaveAccessibleName('Roll the dice')

    // No parallel BEGIN / ROLL CTA may own the happy path.
    await expect(page.getByRole('button', { name: /^begin$/i })).toHaveCount(0)
    await expect(page.getByRole('button', { name: /^roll again$/i })).toHaveCount(0)

    const pick = page.getByRole('button', { name: 'Pick manually' })
    await expect(pick).toBeVisible()
    const pickBg = await computedBackground(page, 'button:has-text("Pick manually")')
    const dieBg = await computedBackground(page, '#main-die-3d')
    expect(pickBg).not.toBe(dieBg)

    const dieOpacity = await die.evaluate((el) => Number(getComputedStyle(el).opacity))
    expect(dieOpacity).toBeGreaterThan(0.85)
  })

  test('clicking the die rolls and the die reflects the rolling state', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Keyboard Roll Thread',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const die = page.locator('#main-die-3d')
    await expect(die).toBeEnabled()
    await die.click()
    await expect(die).toBeDisabled({ timeout: 3000 })
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })
  })

  test('pressing Enter on the focused die triggers a roll', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    await createThread(page, {
      title: 'Enter Roll Thread',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })
    await gotoRollPage(page)
    await waitForRollPageReady(page)

    const die = page.locator('#main-die-3d')
    await die.focus()
    await expect(die).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })
  })
})
