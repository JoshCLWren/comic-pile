/**
 * Password reset frontend flow (#2779) acceptance tests.
 *
 * Covers:
 * - Login page exposes a discoverable "Forgot password?" path
 * - Forgot-password request screen uses email only as recovery identity
 * - Known and unknown email requests render the same acknowledgement
 * - Reset screen consumes the URL token without persisting/logging it
 * - Password validation follows current auth rules (min 6 chars)
 * - Expired/used/invalid tokens render a safe actionable state
 * - Successful reset returns the user to username login
 * - Existing login/register behavior remains unchanged
 */
import { test, expect } from './fixtures'
import {
  generateTestUser,
  registerUser,
  getPasswordResetToken,
} from './helpers'

const MOBILE_VIEWPORT = { width: 390, height: 844 }
const KNOWN_ACK_TEXT =
  'If an account exists for that email, a reset link has been sent'

test.describe('AUTH-002: Password reset flow', () => {
  test('login page exposes a discoverable Forgot password? link', async ({
    page,
  }) => {
    await page.goto('/login', { waitUntil: 'domcontentloaded' })
    await expect(
      page.getByRole('link', { name: /forgot password\?/i }),
    ).toBeVisible()
  })

  test('forgot-password request page asks for email with username-login context', async ({
    page,
  }) => {
    await page.goto('/forgot-password', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('h1')).toHaveText(/forgot password/i)
    await expect(page.locator('input[name="email"]')).toBeVisible()
    await expect(page.getByText(/not your username/i)).toBeVisible()
  })

  test('known and unknown email requests render the same acknowledgement', async ({
    page,
  }) => {
    const user = generateTestUser()
    await registerUser(page, user)
    // Registration signs the user in; the forgot-password screen is a public
    // route that redirects authenticated users, so sign out first.
    await page.evaluate(() => localStorage.clear())

    await page.goto('/forgot-password', { waitUntil: 'domcontentloaded' })
    await page.fill('input[name="email"]', user.email)
    await page.click('button[type="submit"]')

    await expect(page).toHaveURL(/\/forgot-password/)
    await expect(page.locator('h1')).toHaveText(/check your email/i)
    const knownAck = await page.locator('text=' + KNOWN_ACK_TEXT).textContent()

    await page.goto('/forgot-password', { waitUntil: 'domcontentloaded' })
    await page.fill('input[name="email"]', 'nonexistent_user@example.com')
    await page.click('button[type="submit"]')

    const unknownAck = await page.locator('text=' + KNOWN_ACK_TEXT).textContent()
    expect(unknownAck).toBe(knownAck)
  })

  test('valid reset consumes token from URL and redirects to login on success', async ({
    page,
  }) => {
    const user = generateTestUser()
    await registerUser(page, user)

    const token = await getPasswordResetToken(page, user.email)
    // The reset screen is a public route that redirects authenticated users,
    // so sign out after minting the token and before driving the flow.
    await page.evaluate(() => localStorage.clear())

    await page.goto(`/reset-password?token=${encodeURIComponent(token)}`, {
      waitUntil: 'domcontentloaded',
    })
    await expect(page.locator('h1')).toHaveText(/reset password/i)
    await expect(page.locator('input[name="newPassword"]')).toBeVisible()
    await expect(page.locator('input[name="confirmPassword"]')).toBeVisible()

    await page.fill('input[name="newPassword"]', 'BrandNewPw1!')
    await page.fill('input[name="confirmPassword"]', 'BrandNewPw1!')
    await page.click('button[type="submit"]')

    await page.waitForURL(/\/login/, { timeout: 10000 })
  })

  test('successful reset allows re-login with the new password', async ({
    page,
  }) => {
    const user = generateTestUser()
    await registerUser(page, user)

    const token = await getPasswordResetToken(page, user.email)
    // The reset screen is a public route that redirects authenticated users,
    // so sign out after minting the token and before driving the flow.
    await page.evaluate(() => localStorage.clear())

    await page.goto(`/reset-password?token=${encodeURIComponent(token)}`, {
      waitUntil: 'domcontentloaded',
    })
    await page.fill('input[name="newPassword"]', 'BrandNewPw1!')
    await page.fill('input[name="confirmPassword"]', 'BrandNewPw1!')
    await page.click('button[type="submit"]')

    await page.waitForURL(/\/login/)
    await expect(page.locator('h1')).toHaveText(/welcome/i)

    await page.fill('input[name="username"]', user.username)
    await page.fill('input[name="password"]', 'BrandNewPw1!')
    await page.click('button[type="submit"]')

    await page.waitForURL('**/', { timeout: 10000 })
    const tokenInStorage = await page.evaluate(
      () => localStorage.getItem('auth_token'),
    )
    expect(tokenInStorage).toBeTruthy()
  })

  test('missing token renders safe actionable state', async ({ page }) => {
    await page.goto('/reset-password', {
      waitUntil: 'domcontentloaded',
    })

    await expect(page.locator('h1')).toHaveText(/invalid reset link/i)
    await expect(page.getByRole('link', { name: /request a new reset link/i })).toBeVisible()
    await expect(
      page.locator('input[name="newPassword"]'),
    ).not.toBeVisible()
  })

  test('bogus token renders safe actionable state on submit', async ({ page }) => {
    await page.goto('/reset-password?token=invalid-token-value', {
      waitUntil: 'domcontentloaded',
    })

    await expect(page.locator('h1')).toHaveText(/reset password/i)
    await page.fill('input[name="newPassword"]', 'BrandNewPw1!')
    await page.fill('input[name="confirmPassword"]', 'BrandNewPw1!')
    await page.click('button[type="submit"]')

    await expect(page.getByText(/expired, been used, or is invalid/i)).toBeVisible({ timeout: 10000 })
    await expect(page).toHaveURL(/\/reset-password/)
  })

  test('token is not persisted to localStorage or sessionStorage after reset', async ({
    page,
  }) => {
    const user = generateTestUser()
    await registerUser(page, user)

    const token = await getPasswordResetToken(page, user.email)
    // The reset screen is a public route that redirects authenticated users,
    // so sign out after minting the token and before driving the flow.
    await page.evaluate(() => localStorage.clear())

    await page.goto(`/reset-password?token=${encodeURIComponent(token)}`, {
      waitUntil: 'domcontentloaded',
    })
    await page.fill('input[name="newPassword"]', 'BrandNewPw1!')
    await page.fill('input[name="confirmPassword"]', 'BrandNewPw1!')
    await page.click('button[type="submit"]')

    await page.waitForURL(/\/login/)

    const storageKeys = await page.evaluate(() => {
      const keys: string[] = []
      for (let i = 0; i < localStorage.length; i++) {
        keys.push(localStorage.key(i) || '')
      }
      for (let i = 0; i < sessionStorage.length; i++) {
        keys.push(sessionStorage.key(i) || '')
      }
      return keys
    })

    expect(storageKeys).not.toContain('reset_token')
    expect(storageKeys.some(k => k.toLowerCase().includes('reset'))).toBe(false)
  })

  test('used token after successful reset renders safe actionable state', async ({
    page,
  }) => {
    const user = generateTestUser()
    await registerUser(page, user)

    const token = await getPasswordResetToken(page, user.email)
    // The reset screen is a public route that redirects authenticated users,
    // so sign out after minting the token and before driving the flow.
    await page.evaluate(() => localStorage.clear())

    await page.goto(`/reset-password?token=${encodeURIComponent(token)}`, {
      waitUntil: 'domcontentloaded',
    })
    await page.fill('input[name="newPassword"]', 'BrandNewPw1!')
    await page.fill('input[name="confirmPassword"]', 'BrandNewPw1!')
    await page.click('button[type="submit"]')

    await page.waitForURL(/\/login/)

    await page.goto('/login', { waitUntil: 'domcontentloaded' })
    await page.evaluate(() => localStorage.clear())

    await page.goto(`/reset-password?token=${encodeURIComponent(token)}`, {
      waitUntil: 'domcontentloaded',
    })

    await page.fill('input[name="newPassword"]', 'AnotherNewPw1!')
    await page.fill('input[name="confirmPassword"]', 'AnotherNewPw1!')
    await page.click('button[type="submit"]')

    await expect(page.getByText(/expired, been used, or is invalid/i)).toBeVisible({ timeout: 5000 })
  })

  test('password shorter than 6 characters is rejected', async ({ page }) => {
    const user = generateTestUser()
    await registerUser(page, user)

    const token = await getPasswordResetToken(page, user.email)
    // The reset screen is a public route that redirects authenticated users,
    // so sign out after minting the token and before driving the flow.
    await page.evaluate(() => localStorage.clear())

    await page.goto(`/reset-password?token=${encodeURIComponent(token)}`, {
      waitUntil: 'domcontentloaded',
    })
    await page.fill('input[name="newPassword"]', 'ab')
    await page.fill('input[name="confirmPassword"]', 'ab')
    await page.click('button[type="submit"]')

    await expect(page.getByText(/at least 6 characters/i)).toBeVisible({ timeout: 5000 })
  })

  test('mismatched passwords are rejected', async ({ page }) => {
    const user = generateTestUser()
    await registerUser(page, user)

    const token = await getPasswordResetToken(page, user.email)
    // The reset screen is a public route that redirects authenticated users,
    // so sign out after minting the token and before driving the flow.
    await page.evaluate(() => localStorage.clear())

    await page.goto(`/reset-password?token=${encodeURIComponent(token)}`, {
      waitUntil: 'domcontentloaded',
    })
    await page.fill('input[name="newPassword"]', 'NewPassword1!')
    await page.fill('input[name="confirmPassword"]', 'DifferentPassword1!')
    await page.click('button[type="submit"]')

    await expect(page.getByText(/passwords do not match/i)).toBeVisible({ timeout: 5000 })
  })

  test('existing login behavior remains unchanged', async ({ page }) => {
    const user = generateTestUser()
    await registerUser(page, user)
    await page.evaluate(() => localStorage.clear())

    await page.goto('/login', { waitUntil: 'domcontentloaded' })
    await page.fill('input[name="username"]', user.username)
    await page.fill('input[name="password"]', user.password)
    await page.click('button[type="submit"]')

    await page.waitForURL('**/', { timeout: 10000 })
    const tokenInStorage = await page.evaluate(
      () => localStorage.getItem('auth_token'),
    )
    expect(tokenInStorage).toBeTruthy()
  })

  test('mobile: forgot-password flow is usable', async ({ page }) => {
    await page.setViewportSize(MOBILE_VIEWPORT)
    const user = generateTestUser()
    await registerUser(page, user)
    await page.evaluate(() => localStorage.clear())

    await page.goto('/forgot-password', { waitUntil: 'domcontentloaded' })
    await page.fill('input[name="email"]', user.email)
    await page.click('button[type="submit"]')

    await expect(page.locator('h1')).toHaveText(/check your email/i)
    await expect(page).toHaveURL(/\/forgot-password/)
  })

  test('mobile: reset-password flow is usable', async ({ page }) => {
    await page.setViewportSize(MOBILE_VIEWPORT)
    const user = generateTestUser()
    await registerUser(page, user)

    const token = await getPasswordResetToken(page, user.email)
    // The reset screen is a public route that redirects authenticated users,
    // so sign out after minting the token and before driving the flow.
    await page.evaluate(() => localStorage.clear())

    await page.goto(`/reset-password?token=${encodeURIComponent(token)}`, {
      waitUntil: 'domcontentloaded',
    })
    await page.fill('input[name="newPassword"]', 'BrandNewPw1!')
    await page.fill('input[name="confirmPassword"]', 'BrandNewPw1!')
    await page.click('button[type="submit"]')

    await page.waitForURL(/\/login/, { timeout: 10000 })
  })
})
