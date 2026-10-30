import { expect } from '@playwright/test'
import { test } from './fixtures'
import { createThread } from './helpers'

for (const width of [375, 1280]) {
  test(`tag color radios support keyboard selection at ${width}px`, async ({ authenticatedPage: page }) => {
    await page.setViewportSize({ width, height: 900 })
    const thread = await createThread(page, { title: 'Tag keyboard fixture', format: 'Issue', issues_remaining: 1, total_issues: 1 })
    await page.goto(`/thread/${thread.id}`)
    await page.getByRole('button', { name: 'Edit tags', exact: true }).first().click()
    const group = page.getByRole('radiogroup', { name: 'Tag color', exact: true })
    const radios = group.getByRole('radio')
    await expect(group).toBeVisible()
    const first = radios.first()
    await first.click()
    await first.press('ArrowLeft')
    await expect(radios.last()).toBeFocused()
    await expect(radios.last()).toHaveAttribute('aria-checked', 'true')
    await radios.last().press('ArrowRight')
    await expect(first).toBeFocused()
    await expect(first).toHaveAttribute('aria-checked', 'true')
    await expect(group.locator('[tabindex="0"]')).toHaveCount(1)
    await page.getByRole('textbox', { name: 'New tag name', exact: true }).fill('A'.repeat(100))
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    const dialog = page.getByRole('dialog')
    for (let index = 0; index < 12; index += 1) {
      await page.keyboard.press('Tab')
      await expect.poll(() => dialog.evaluate(element => element.contains(document.activeElement))).toBe(true)
    }
    for (let index = 0; index < 12; index += 1) {
      await page.keyboard.press('Shift+Tab')
      await expect.poll(() => dialog.evaluate(element => element.contains(document.activeElement))).toBe(true)
    }
    await page.keyboard.press('Escape')
    await expect(group).toHaveCount(0)
  })
}
