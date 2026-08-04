import { expect, test } from '@playwright/test'
import { setupAuthenticatedPage } from './helpers'

const MOBILE_WIDTHS = [320, 375, 414] as const

for (const width of MOBILE_WIDTHS) {
  test(`mobile form controls remain contained at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 812 })
    await setupAuthenticatedPage(page)
    await page.goto('/queue')
    await expect(page.getByRole('heading', { name: 'Read Queue' })).toBeVisible()

    await page.getByRole('button', { name: 'Add Thread' }).click()

    const controls = page.locator('input:visible, textarea:visible, select:visible')
    const count = await controls.count()
    expect(count).toBeGreaterThan(0)

    for (let index = 0; index < count; index += 1) {
      const control = controls.nth(index)
      await control.focus()

      const metrics = await page.evaluate(() => {
        const root = document.getElementById('root')
        const active = document.activeElement
        const fontSize = active instanceof HTMLElement
          ? Number.parseFloat(window.getComputedStyle(active).fontSize)
          : 0

        return {
          documentWidth: document.documentElement.scrollWidth,
          viewportWidth: document.documentElement.clientWidth,
          rootWidth: root?.scrollWidth ?? 0,
          rootClientWidth: root?.clientWidth ?? 0,
          fontSize,
        }
      })

      expect(metrics.documentWidth).toBeLessThanOrEqual(metrics.viewportWidth)
      expect(metrics.rootWidth).toBeLessThanOrEqual(metrics.rootClientWidth)
      expect(metrics.fontSize).toBeGreaterThanOrEqual(16)
    }
  })
}
