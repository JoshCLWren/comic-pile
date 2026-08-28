/**
 * AUTH-001: User can sign in with email/password and obtain a session.
 *
 * Covers the core authentication journey: register a fresh user, sign in
 * via the login form, verify the session is established by checking that
 * the protected home page renders, and that invalid credentials are rejected.
 *
 * Inventory IDs: AUTH-001
 */
import { test, expect } from './fixtures'
import {
  generateTestUser,
  registerUser,
  loginUser,
} from './helpers'

const MOBILE_VIEWPORT = { width: 390, height: 844 }

test.describe('AUTH-001: Authentication and startup', () => {
  test('user can register and then sign in with email/password', async ({
    page,
  }) => {
    const user = generateTestUser()
    await registerUser(page, user)
    await page.evaluate(() => localStorage.clear())

    await page.goto('/login', { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('input[name="username"]', { state: 'visible' })

    await page.fill('input[name="username"]', user.username)
    await page.fill('input[name="password"]', user.password)
    await page.click('button[type="submit"]')

    await page.waitForURL('**/', { timeout: 10000 })
    const token = await page.evaluate(() => localStorage.getItem('auth_token'))
    expect(token).toBeTruthy()
  })

  test('invalid credentials show error and stay on login page', async ({
    page,
  }) => {
    await page.goto('/login', { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('input[name="username"]', { state: 'visible' })

    await page.fill('input[name="username"]', 'nonexistent_user_xyz')
    await page.fill('input[name="password"]', 'wrong_password_123')
    await page.click('button[type="submit"]')

    await expect(page.locator('.text-red-400')).toBeVisible({ timeout: 5000 })
    await expect(page).toHaveURL(/\/login/)
  })

  test('unauthenticated user is redirected to login', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await expect(page).toHaveURL(/\/login/)
  })

  test('login form is reachable from register page', async ({ page }) => {
    await page.goto('/register', { waitUntil: 'domcontentloaded' })
    await expect(
      page.getByRole('link', { name: /sign in/i }),
    ).toBeVisible()
    await page.getByRole('link', { name: /sign in/i }).click()
    await expect(page).toHaveURL(/\/login/)
  })

  test('session persists across page reload', async ({ page }) => {
    const user = generateTestUser()
    await registerUser(page, user)
    await loginUser(page, user)

    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await page.locator('#root').waitFor({ state: 'visible' })
    const tokenBefore = await page.evaluate(() => localStorage.getItem('auth_token'))

    await page.reload({ waitUntil: 'domcontentloaded' })
    const tokenAfter = await page.evaluate(() => localStorage.getItem('auth_token'))
    expect(tokenAfter).toBe(tokenBefore)
  })

  test('mobile viewport: login form works correctly', async ({ page }) => {
    await page.setViewportSize(MOBILE_VIEWPORT)
    const user = generateTestUser()
    await registerUser(page, user)
    await page.evaluate(() => localStorage.clear())

    await page.goto('/login', { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('input[name="username"]', { state: 'visible' })

    await page.fill('input[name="username"]', user.username)
    await page.fill('input[name="password"]', user.password)
    await page.click('button[type="submit"]')

    await page.waitForURL('**/', { timeout: 10000 })
    const token = await page.evaluate(() => localStorage.getItem('auth_token'))
    expect(token).toBeTruthy()
  })
})
