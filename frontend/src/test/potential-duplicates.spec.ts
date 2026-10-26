import { expect } from '@playwright/test'
import { test } from './fixtures'
import { createThread, gotoQueue } from './helpers'

for (const width of [390, 1280]) {
  test(`create and rename warn about existing editions at ${width}px`, async ({ authenticatedPage: page }) => {
    await page.setViewportSize({ width, height: 900 })
    await createThread(page, { title: 'Spider-Man', format: 'Comic', issues_remaining: 2 })
    await createThread(page, { title: 'Saga', format: 'Comic', issues_remaining: 2 })
    await gotoQueue(page)
    await page.getByRole('button', { name: /add series/i }).first().click()
    await page.locator('#create-thread-title').fill('Amazing Spider-Man')
    await expect(page.getByRole('alert').filter({ hasText: 'Similar series found' })).toContainText('Spider-Man')
    await page.locator('#create-thread-title').fill('')
    await expect(page.getByText('Checking for potential duplicates...')).toHaveCount(0)
    await expect(page.getByRole('alert').filter({ hasText: 'Similar series found' })).toHaveCount(0)
    await page.getByRole('button', { name: 'Close modal' }).click()
    const saga = page.getByTestId('queue-thread-item').filter({ hasText: 'Saga' })
    await saga.getByRole('button', { name: 'Series actions' }).click()
    await page.getByRole('menu').getByRole('menuitem', { name: /edit/i }).click()
    await page.locator('#edit-thread-title').fill('Amazing Spider-Man')
    await expect(page.getByRole('alert').filter({ hasText: 'Similar series found' })).toContainText('Spider-Man')
    await page.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(saga).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  })
}
