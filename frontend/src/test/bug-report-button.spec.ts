import { test, expect } from './fixtures'

// Firefox-only test verifying the skipFonts fix for:
//   TypeError: can't access property "trim", a is undefined
// html-to-image crashes on Firefox when processing font-face CSS rules
// unless skipFonts: true is passed to toBlob.
//
// Note: toBlob requires GPU rendering and always fails in headless environments.
// We test what we can verify headlessly:
//   1. The button is visible when authenticated
//   2. Clicking it opens the modal (fallback path when capture fails)
//   3. No font-processing "trim" crash appears in the console

test.describe('Bug Report Button - Firefox', () => {
  test('opens modal and no trim crash on Firefox', async ({ authenticatedPage }) => {
    const consoleErrors: string[] = []
    authenticatedPage.on('console', msg => {
      if (msg.type() === 'error') consoleErrors.push(msg.text())
    })

    const button = authenticatedPage.locator('[aria-label="Report a bug"]')
    await expect(button).toBeVisible()
    await button.click()

    // Modal must open — either with screenshot (headed) or without (headless fallback)
    const modal = authenticatedPage.getByRole('dialog', { name: 'Report a Bug' })
    await expect(modal).toBeVisible({ timeout: 10000 })

    // The specific Firefox font-processing bug produces this message.
    // It must not appear after the skipFonts fix.
    const trimCrashes = consoleErrors.filter(e =>
      e.includes("can't access property \"trim\"") ||
      e.includes("Cannot read properties of undefined (reading 'trim')")
    )
    expect(trimCrashes, 'Font-processing trim crash should not occur').toHaveLength(0)
  })
})
