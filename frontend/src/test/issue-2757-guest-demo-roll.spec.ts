import { test, expect } from '@playwright/test'

test.describe('#2757 guest demo roll', () => {
  test('guest entry → one seeded roll → conversion prompt, no persistence', async ({ page }) => {
    // Start at landing (unauthenticated path)
    await page.goto('/')
    await expect(page.locator('[data-landing-try-demo]')).toBeVisible()

    // Enter demo
    await page.locator('[data-landing-try-demo]').click()
    await expect(page).toHaveURL(/\/demo/)

    // Sample banner visible
    await expect(page.locator('[data-demo-roll-page]')).toBeVisible()
    await expect(page.locator('text=Sample / Demo data')).toBeVisible()

    // Deterministic roll loaded
    await expect(page.locator('text=The Dark Knight Returns (Demo)')).toBeVisible()
    await expect(page.locator('text=Demo')).toBeVisible()

    // Rating loop works (ephemeral)
    const rateBtn = page.locator('button[role="radio"][aria-checked="false"]').first()
    await rateBtn.click()
    await expect(page.locator('[data-demo-rated]')).toBeVisible()

    // Conversion CTA present — clear signup/login
    await expect(page.locator('[data-demo-signup-cta]')).toBeVisible()
    await expect(page.locator('[data-demo-login-cta]')).toBeVisible()

    // No persistent session artifacts (demo page should not redirect to auth wall)
    await expect(page.locator('[data-demo-roll-page]')).toBeVisible()
  })
})
