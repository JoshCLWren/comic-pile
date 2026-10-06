import { expect } from '@playwright/test'
import { test } from './fixtures'

test.describe('Issue #3147: Focus management after Roll and Queue actions', () => {
  test('focus moves to result after ROLL AGAIN', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/')

    const rollBtn = authenticatedPage.getByTestId('roll-primary-action')
    await rollBtn.click()

    // Verify focus is on the rating view top
    await expect(authenticatedPage.locator('[data-testid="rating-view-top"]')).toBeFocused()
  })

  test('focus returns to trigger after Queue menu action', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue')

    const menuBtn = authenticatedPage.getByLabel('Series actions').first()
    await menuBtn.focus()
    await authenticatedPage.keyboard.press('Enter')

    const menuItem = authenticatedPage.getByRole('menuitem').first()
    await menuItem.focus()
    await authenticatedPage.keyboard.press('Enter')

    // Verify focus returns to the menu button
    await expect(menuBtn).toBeFocused()
  })
})
