import { expect } from '@playwright/test'
import { test } from './fixtures'
import { createThread } from './helpers'

test.describe('Issue #3147: Focus management after Roll and Queue actions', () => {
  test('focus moves to result after ROLL AGAIN', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    // The primary Roll CTA only mounts when there is rollable content.
    await createThread(page, {
      title: 'Focus Roll Thread',
      issues_remaining: 2,
      total_issues: 2,
    })
    await page.goto('/')

    const rollBtn = page.locator('#main-die-3d')
    await expect(rollBtn).toBeVisible()
    await rollBtn.click()

    // Verify focus is on the rating view top
    await expect(page.locator('[data-testid="rating-view-top"]')).toBeFocused()
  })

  test('focus returns to trigger after Queue menu action', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    // Queue row actions only render for an actual thread card.
    await createThread(page, {
      title: 'Focus Queue Thread',
      issues_remaining: 2,
      total_issues: 2,
    })
    await page.goto('/queue')

    const menuBtn = page.getByLabel('Series actions').first()
    await expect(menuBtn).toBeVisible()
    await menuBtn.focus()
    await page.keyboard.press('Enter')

    const menuItem = page.getByRole('menuitem').first()
    await menuItem.focus()
    await page.keyboard.press('Enter')

    // Verify focus returns to the menu button
    await expect(menuBtn).toBeFocused()
  })
})
