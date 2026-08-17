import { expect, test } from './fixtures'

test('Recceovers invisibly from a transient 503 cold start during resume', async ({
  authenticatedPage,
  allowExpectedBrowserFailures,
}) => {
  const page = authenticatedPage
  let meAttempts = 0

  allowExpectedBrowserFailures.allow(
    { category: 'console', message: '503' },
    { category: 'console', message: 'ComicPile reconnecting after transient error' },
  )

  await page.goto('/')
  await expect(page.locator('[data-app-shell-ready]')).toBeVisible()

  // The serverless backend is warming back up: the first couple of resume
  // revalidations return 503, then recover. This must be invisible to the user.
  await page.route('**/api/v1/auth/me', async (route) => {
    meAttempts += 1
    if (meAttempts <= 2) {
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

  await expect.poll(() => meAttempts).toBeGreaterThanOrEqual(3)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.locator('[data-app-shell-ready]')).toBeVisible()
})

test('Retry explicitly refreshes auth after automatic resume recovery fails', async ({
  authenticatedPage,
  allowExpectedBrowserFailures,
}) => {
  const page = authenticatedPage
  let meAttempts = 0
  let refreshAttempts = 0

  allowExpectedBrowserFailures.allow(
    { category: 'console', message: '503' },
    { category: 'console', message: 'ComicPile reconnecting after transient error' },
  )

  await page.goto('/')
  await expect(page.locator('[data-app-shell-ready]')).toBeVisible()

  // More than the patient retry budget of transient 503s, so the reconnect
  // eventually surfaces the error and offers an explicit retry.
  await page.route('**/api/v1/auth/me', async (route) => {
    meAttempts += 1
    if (meAttempts <= 4) {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'temporarily unavailable' }),
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
