import { test, expect } from './fixtures'

test.describe('Bug Report Button', () => {
  test('opens modal when clicked', async ({ authenticatedPage }) => {
    const consoleErrors: string[] = []
    authenticatedPage.on('console', msg => {
      if (msg.type() === 'error') consoleErrors.push(msg.text())
    })

    const button = authenticatedPage.getByRole('button', { name: /report a bug/i }).last()
    await expect(button).toBeVisible()
    await button.click()

    // Modal must open with the diagnostic info notice
    const modal = authenticatedPage.getByRole('dialog', { name: 'Report a Bug' })
    await expect(modal).toBeVisible({ timeout: 10000 })

    // Verify the diagnostics notice is shown
    await expect(authenticatedPage.getByText(/browser info & console errors/i)).toBeVisible()
  })

  test('moves the bug report entry point into the mobile nav', async ({ authenticatedPage }) => {
    await authenticatedPage.setViewportSize({ width: 390, height: 844 })
    await authenticatedPage.reload({ waitUntil: 'domcontentloaded' })

    await expect(authenticatedPage.getByRole('link', { name: /help page/i })).toHaveCount(0)

    const button = authenticatedPage.getByRole('navigation', { name: /main navigation/i }).getByLabel('Report a bug')
    await expect(button).toBeVisible()
    await button.click()

    const modal = authenticatedPage.getByRole('dialog', { name: 'Report a Bug' })
    await expect(modal).toBeVisible({ timeout: 10000 })
  })
})
