import { test, expect } from '@playwright/test'
import {
  login,
  setupSession,
} from './fixtures'

test.describe('Issue #3147: Focus management after Roll and Queue actions', () => {
  test('focus moves to result after ROLL AGAIN', async ({ page }) => {
    await login(page)
    await setupSession(page)
    await page.goto('/')

    const rollBtn = page.getByTestId('roll-primary-action')
    await rollBtn.click()

    // Verify focus is on the rating view top
    await expect(page.locator('[data-testid="rating-view-top"]')).toBeFocused()
  })

  test('focus returns to trigger after Queue menu action', async ({ page }) => {
    await login(page)
    await setupSession(page)
    await page.goto('/queue')

    const menuBtn = page.getByLabel('Series actions').first()
    await menuBtn.focus()
    await page.keyboard.press('Enter')

    const menuItem = page.getByRole('menuitem').first()
    await menuItem.focus()
    await page.keyboard.press('Enter')

    // Verify focus returns to the menu button
    await expect(menuBtn).toBeFocused()
  })
})
