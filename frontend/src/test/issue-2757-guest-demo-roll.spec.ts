import { test, expect } from '@playwright/test'

test.describe('#2757 guest demo roll', () => {
  test('guest entry → one seeded roll → conversion prompt, no persistence', async ({ page }) => {
    // Start at landing (unauthenticated path)
    await page.goto('/')
    const tryDemo = page.locator('[data-landing-try-demo]')
    await expect(tryDemo).toBeVisible()

    // Exactly one demo entry point on the logged-out landing page.
    await expect(tryDemo).toHaveCount(1)

    // Enter demo
    await tryDemo.click()
    await expect(page).toHaveURL(/\/demo/)

    // Sample banner visible and explicitly labeled as demo data.
    const demoPage = page.getByTestId('demo-roll-page')
    await expect(demoPage).toBeVisible()
    await expect(demoPage.getByText('Sample / Demo data', { exact: false })).toBeVisible()

    // Deterministic seeded roll loaded.
    await expect(demoPage.getByRole('heading', { name: /The Dark Knight Returns \(Demo\)/ })).toBeVisible()
    await expect(demoPage.getByText('Demo', { exact: true })).toBeVisible()

    // Rating loop works, is keyboard reachable, and stays ephemeral.
    const rating = demoPage.getByTestId('demo-rating-input')
    await expect(demoPage.getByTestId('demo-rated')).toHaveCount(0)
    await rating.focus()
    await expect(rating).toBeFocused()
    await page.keyboard.press('ArrowRight')
    await expect(rating).toHaveValue('4.5')
    await expect(demoPage.getByTestId('demo-rated')).toBeVisible()
    await expect(demoPage.getByTestId('demo-rated')).toContainText('never saved')

    // Conversion CTA present — clear signup/login
    await expect(demoPage.getByTestId('demo-signup-cta')).toBeVisible()
    await expect(demoPage.getByTestId('demo-login-cta')).toBeVisible()

    // No persistent session artifacts: the guest demo never authenticates and
    // never writes an account token, so no real-user persistence is possible.
    const storedToken = await page.evaluate(() => localStorage.getItem('auth_token'))
    expect(storedToken).toBeNull()
    await expect(page.getByTestId('demo-roll-page')).toBeVisible()
  })
})
