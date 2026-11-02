import { expect, test, type Page } from '@playwright/test'

interface ApiRequestRow {
  method: string
  url: string
}

/**
 * Record API requests the browser actually emits.
 *
 * Static assets are excluded; query strings are kept so CSRF and auth probes
 * are distinguishable.
 */
function recordApiRequests(page: Page): ApiRequestRow[] {
  const rows: ApiRequestRow[] = []
  page.on('request', request => {
    const url = new URL(request.url())
    if (url.pathname.startsWith('/api/')) {
      rows.push({ method: request.method(), url: `${url.pathname}${url.search}` })
    }
  })
  return rows
}

async function stubApi(page: Page): Promise<void> {
  await page.route('**/api/**', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '{}',
    }),
  )
}

test('guest /forgot-password renders without any API request', async ({ page }) => {
  await stubApi(page)
  const requests = recordApiRequests(page)

  await page.goto('/forgot-password')

  await expect(page.getByRole('heading', { name: 'Forgot Password' })).toBeVisible()
  await expect(page.getByLabel('Email')).toBeVisible()
  expect(requests).toEqual([])
})

test('guest /reset-password renders and submits without a CSRF probe', async ({ page }) => {
  await stubApi(page)
  await page.route('**/api/v1/auth/reset-password', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"message":"ok"}' }),
  )
  const requests = recordApiRequests(page)

  await page.goto('/reset-password?token=chromium-reset-token')
  await expect(page.getByRole('heading', { name: 'Reset Password' })).toBeVisible()
  expect(requests).toEqual([])

  await page.getByLabel('New Password', { exact: true }).fill('new-password-1')
  await page.getByLabel('Confirm New Password').fill('new-password-1')
  await page.getByRole('button', { name: 'Reset Password' }).click()

  await expect(page.getByRole('link', { name: 'Sign In with New Password' })).toBeVisible()
  expect(requests).toEqual([
    { method: 'POST', url: '/api/v1/auth/reset-password' },
  ])
  expect(requests.some(row => row.url.includes('/api/v1/auth/csrf'))).toBe(false)
})

test('guest /forgot-password submits once without a CSRF probe', async ({ page }) => {
  await stubApi(page)
  await page.route('**/api/v1/auth/forgot-password', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"message":"sent"}' }),
  )
  const requests = recordApiRequests(page)

  await page.goto('/forgot-password')
  await expect(page.getByLabel('Email')).toBeVisible()
  expect(requests).toEqual([])

  await page.getByLabel('Email').fill('reader@example.test')
  await page.getByRole('button', { name: 'Send Reset Link' }).click()

  await expect(page.getByRole('heading', { name: 'Check your email' })).toBeVisible()
  expect(requests).toEqual([
    { method: 'POST', url: '/api/v1/auth/forgot-password' },
  ])
  expect(requests.some(row => row.url.includes('/api/v1/auth/csrf'))).toBe(false)
})

test('a stored token still validates and redirects away from the credential form', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('auth_token', 'stored-browser-token'))
  const requests = recordApiRequests(page)
  await page.route('**/api/v1/auth/me', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: 7, username: 'browser-reader', email: 'browser@example.test' }),
    }),
  )
  await page.route('**/api/v1/users/me/preferences', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ theme: 'classic', user_id: 7 }),
    }),
  )
  await page.route('**/api/v1/identity-inbox**', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], total: 0, offset: 0, limit: 1 }),
    }),
  )
  await page.route('**/api/v2/roll/**', route => route.abort())

  await page.goto('/forgot-password')

  await page.waitForURL(url => url.pathname === '/')
  expect(requests.some(row => row.method === 'GET' && row.url === '/api/v1/auth/me')).toBe(true)
  await expect(page.getByLabel('Email')).toHaveCount(0)
})

test('a rejected stored token shows the credential form after probing once each', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('auth_token', 'stale-browser-token'))
  const requests = recordApiRequests(page)
  await page.route('**/api/v1/auth/me', route =>
    route.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"Not authenticated"}' }),
  )
  await page.route('**/api/v1/auth/refresh', route =>
    route.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"Not authenticated"}' }),
  )

  await page.goto('/forgot-password')

  await expect(page.getByLabel('Email')).toBeVisible()
  expect(requests).toEqual([
    { method: 'GET', url: '/api/v1/auth/me' },
    { method: 'POST', url: '/api/v1/auth/refresh' },
  ])
})
