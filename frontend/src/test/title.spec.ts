import { expect, test } from '@playwright/test'

test('uses Comic Pile branding in the browser title', async ({ page }) => {
  await page.goto('/')

  await expect(page).toHaveTitle('Comic Pile')
})
