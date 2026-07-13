import { test, expect } from './fixtures'
import { gotoQueue } from './helpers'

test.describe('Issue #582: modal scroll lock on #root', () => {
  test('locks #root overflow while a modal is open and restores on close', async ({ authenticatedPage }) => {
    await gotoQueue(authenticatedPage)
    const root = authenticatedPage.locator('#root')

    // Open the Create Thread modal via the Add Thread button.
    await authenticatedPage.getByRole('button', { name: 'Add Thread' }).first().click()
    await expect(authenticatedPage.getByRole('dialog')).toBeVisible()

    // #root is locked while the modal is open.
    await expect(root).toHaveCSS('overflow', 'hidden')

    // Close via Escape.
    await authenticatedPage.keyboard.press('Escape')
    await expect(authenticatedPage.getByRole('dialog')).toHaveCount(0)

    // #root overflow is restored (not hidden).
    const overflow = await root.evaluate((el) => getComputedStyle(el).overflow)
    expect(overflow).not.toBe('hidden')
  })

  test('modal inner container contains overscroll so it cannot chain to #root', async ({ authenticatedPage }) => {
    await gotoQueue(authenticatedPage)
    await authenticatedPage.getByRole('button', { name: 'Add Thread' }).first().click()
    const dialog = authenticatedPage.getByRole('dialog')
    await expect(dialog).toBeVisible()

    // The inner scroll container (overflow-y-auto) must contain overscroll.
    const inner = dialog.locator('div.overflow-y-auto').first()
    await expect(inner).toHaveCSS('overscroll-behavior-y', 'contain')
  })
})
