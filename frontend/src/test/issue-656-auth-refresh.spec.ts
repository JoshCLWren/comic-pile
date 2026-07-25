import { expect, test } from './fixtures'
import { generateTestUser } from './helpers'

test('recovers authentication when /auth/me initially returns missing-bearer 403', async ({ page }) => {
  const user = generateTestUser()
  const registerResponse = await page.request.post('/api/auth/register', {
    data: {
      username: user.username,
      email: user.email,
      password: user.password,
    },
  })
  expect(registerResponse.ok()).toBeTruthy()

  // Keep the refresh cookie from registration, but reproduce a fresh browser bootstrap
  // with no in-memory access token.
  await page.goto('/login')
  await page.evaluate(() => {
    localStorage.clear()
    delete (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN
  })

  let meRequestCount = 0
  await page.route('**/api/auth/me', async (route) => {
    meRequestCount += 1
    if (meRequestCount === 1) {
      await route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Not authenticated' }),
      })
      return
    }
    await route.continue()
  })

  await page.goto('/')

  await expect(page).toHaveURL('/')
  await expect(page.getByText(user.username, { exact: true })).toBeVisible()
  await expect(page.getByText('Not authenticated', { exact: true })).toHaveCount(0)
  expect(meRequestCount).toBeGreaterThanOrEqual(2)
})
