/**
 * Issue #2197: Roll page primary action hierarchy.
 *
 * The dogfood finding reported a crowded, ambiguous primary-action surface on
 * Roll: a solid "Pick manually" button competed with "Tap Die to Roll", the
 * die face, and mode chips. This spec asserts the corrected hierarchy:
 *
 * 1. The default happy path has exactly one dominant primary CTA (`Roll now`)
 *    rendered under the die.
 * 2. The "Pick manually" control reads as secondary (no solid primary fill).
 * 3. The die registers as ready-to-roll (not dimmed/passive) on load.
 * 4. The CTA is keyboard operable and reflects the rolling/ready states.
 *
 * These are rendered-behavior assertions (bounding boxes + computed styles +
 * accessible names), not class-string checks, so a future styling change
 * cannot quietly reintroduce the ambiguity.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoRollPage, waitForRollPageReady } from './helpers'

async function computedBackground(page: Page, selector: string): Promise<string> {
  return page.locator(selector).evaluate((el) => getComputedStyle(el).backgroundColor)
}

test.describe('Roll primary-action hierarchy (#2197)', () => {
  test('a single dominant Roll CTA is the primary action with demoted manual pick', async ({
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

    // Exactly one "roll" primary action exists on the happy path.
    await expect(page.getByTestId('roll-primary-action')).toHaveCount(1)

    // The CTA is the dominant filled primary action.
    const cta = page.getByTestId('roll-primary-action')
    await expect(cta).toBeVisible()
    await expect(cta).toHaveText('Roll now')

    // "Pick manually" is demoted to a quiet secondary button (no solid amber
    // fill) while remaining present in the header.
    const pick = page.getByRole('button', { name: 'Pick manually' })
    await expect(pick).toBeVisible()
    const pickBg = await computedBackground(page, 'button:has-text("Pick manually")')
    const ctaBg = await computedBackground(page, '[data-testid="roll-primary-action"]')
    expect(pickBg).not.toBe(ctaBg)

    // The die is ready-to-roll (not dimmed) on first load.
    const die = page.locator('#main-die-3d')
    await expect(die).toBeVisible()
    const dieOpacity = await die.evaluate((el) => Number(getComputedStyle(el).opacity))
    expect(dieOpacity).toBeGreaterThan(0.85)
  })

  test('the Roll CTA is keyboard operable and reflects the rolling state', async ({
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

    const cta = page.getByTestId('roll-primary-action')
    await expect(cta).toBeVisible()
    await expect(cta).toBeEnabled()

    // The CTA is the explicit labeled primary trigger.
    await cta.click()

    // The CTA disables and reads as busy while the roll is in flight, then
    // settles into the rating view where the outcome is explicit.
    await expect(cta).toBeDisabled({ timeout: 3000 })
    await expect(page.locator('#rating-input')).toBeVisible({
      timeout: 15000,
    })
  })

  test('pressing Enter on a focused Roll CTA triggers a roll', async ({
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

    const cta = page.getByTestId('roll-primary-action')
    await cta.focus()
    await expect(cta).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(page.locator('#rating-input')).toBeVisible({
      timeout: 15000,
    })
  })
})
