import { expect, test } from './fixtures'

test('Retry explicitly refreshes auth after automatic resume recovery fails', async ({
  authenticatedPage,
  allowExpectedBrowserFailures,
}) => {
  const page = authenticatedPage
  let meAttempts = 0
  let refreshAttempts = 0

  allowExpectedBrowserFailures.allow(
    { category: 'console', message: '503' },
    { category: 'console', message: 'ComicPile resume validation failed' },
  )

  await page.goto('/')
  await expect(page.locator('[data-app-shell-ready]')).toBeVisible()

  await page.route('**/api/v1/auth/me', async (route) => {
    meAttempts += 1
    if (meAttempts <= 2) {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'internal error' }),
      })
      return
    }
    await route.continue()
  })

  await page.route('**/api/v1/auth/refresh', async (route) => {
    refreshAttempts += 1
    await route.continue()
  })

  await page.evaluate(() => {
    document.dispatchEvent(new Event('visibilitychange'))
  })

  await expect(page.getByRole('alert')).toContainText('ComicPile could not reconnect')

  await page.getByRole('button', { name: 'Retry' }).click()

  await expect(page.getByRole('status')).toContainText('Reconnecting ComicPile')
  await expect.poll(() => refreshAttempts).toBe(1)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.locator('[data-app-shell-ready]')).toBeVisible()
})

test('Automatic recovery retries 503 silently without showing failed state', async ({
  authenticatedPage,
  allowExpectedBrowserFailures,
}) => {
  const page = authenticatedPage
  let meAttempts = 0

  allowExpectedBrowserFailures.allow(
    { category: 'console', message: '503' },
  )

  await page.goto('/')
  await expect(page.locator('[data-app-shell-ready]')).toBeVisible()

  await page.route('**/api/v1/auth/me', async (route) => {
    meAttempts += 1
    if (meAttempts <= 5) {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'temporarily unavailable' }),
      })
      return
    }
    await route.continue()
  })

  await page.evaluate(() => {
    document.dispatchEvent(new Event('visibilitychange'))
  })

  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByRole('status')).toHaveCount(0)

  await page.waitForTimeout(10000)

  await expect(page.getByRole('status')).toContainText('Reconnecting ComicPile')
  await expect(page.getByRole('alert')).toHaveCount(0)
  expect(meAttempts).toBeGreaterThan(2)
})