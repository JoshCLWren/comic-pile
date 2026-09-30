import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { isObject, isString } from '../utils/runtimeChecks'

// Recovery links and credentials must not be recorded in traces or screenshots.
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

function fixture(operation: 'prepare' | 'inspect' | 'cleanup', username: string): Record<string, unknown> {
  const output = execFileSync('python', ['-m', 'tests_e2e.password_reset_fixture', operation, username], {
    cwd: resolve(process.cwd(), '..'),
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  const value: unknown = JSON.parse(output)
  if (!isObject(value)) throw new Error('Invalid private fixture response')
  return value
}

for (const signedIn of [true, false]) {
  test(`password reset completes with reading history and signedIn=${signedIn}`, async ({ page, context }) => {
    const username = `cp-reset-e2e-${Date.now()}-${signedIn ? 'in' : 'out'}`
    const oldPassword = 'old-e2e-password'
    const newPassword = 'new-e2e-password'
    const registration = await page.request.post('/api/v1/auth/register', {
      data: { username, email: `${username}@example.com`, password: oldPassword },
    })
    expect(registration.status()).toBe(200)
    const credentials: unknown = await registration.json()
    if (!isObject(credentials) || !isString(credentials.access_token) || !isString(credentials.refresh_token)) {
      throw new Error('Registration did not return credentials')
    }
    try {
      const data = fixture('prepare', username)
      if (!isString(data.token)) throw new Error('Recovery fixture was not prepared')
      if (signedIn) {
        await page.addInitScript((token: string) => {
          localStorage.setItem('auth_token', token)
        }, credentials.access_token)
      } else {
        await context.clearCookies()
      }
      try {
        await page.goto(`/reset-password?token=${encodeURIComponent(data.token)}`)
      } catch {
        throw new Error('Recovery page navigation failed; secret URL withheld')
      }
      await expect(page.getByLabel('New Password', { exact: true })).toBeVisible()
      // Let auth bootstrap finish, so the old PublicRoute redirect cannot hide.
      await page.waitForLoadState('networkidle')
      expect(new URL(page.url()).pathname).toBe('/reset-password')
      await page.getByLabel('New Password', { exact: true }).fill(newPassword)
      await page.getByLabel('Confirm New Password').fill(newPassword)
      const resetResponse = page.waitForResponse(response =>
        new URL(response.url()).pathname === '/api/v1/auth/reset-password' && response.request().method() === 'POST')
      await page.getByRole('button', { name: 'Reset Password', exact: true }).click()
      expect((await resetResponse).status()).toBe(200)
      await expect(page.getByText('Password Reset Successfully', { exact: true })).toBeVisible()
      expect(fixture('inspect', username)).toEqual({ sessions: 1, events: 1, snapshots: 1, used_tokens: 1 })

      const csrfResponse = await page.request.get('/api/v1/auth/csrf')
      const csrf: unknown = await csrfResponse.json()
      if (!isObject(csrf) || !isString(csrf.csrf_token)) throw new Error('CSRF bootstrap failed')
      const headers = { 'X-CSRF-Token': csrf.csrf_token }
      expect((await page.request.post('/api/v1/auth/reset-password', {
        headers, data: { token: data.token, new_password: 'replay-must-not-work' },
      })).status()).toBe(400)
      expect((await page.request.get('/api/v1/auth/me', {
        headers: { Authorization: `Bearer ${credentials.access_token}` },
      })).status()).toBe(401)
      expect((await page.request.post('/api/v1/auth/refresh', {
        headers, data: { refresh_token: credentials.refresh_token },
      })).status()).toBe(401)
      expect((await page.request.post('/api/v1/auth/login', {
        data: { username, password: oldPassword },
      })).status()).toBe(401)

      await page.getByRole('link', { name: 'Sign In with New Password' }).click()
      await expect(page.getByLabel('Username')).toBeVisible()
      await page.getByLabel('Username').fill(username)
      await page.getByLabel('Password', { exact: true }).fill(newPassword)
      const loginResponse = page.waitForResponse(response =>
        new URL(response.url()).pathname === '/api/v1/auth/login' && response.request().method() === 'POST')
      await page.getByRole('button', { name: 'Sign In', exact: true }).click()
      expect((await loginResponse).status()).toBe(200)
      await expect.poll(() => new URL(page.url()).pathname).toBe('/')
      await page.reload()
      await page.waitForLoadState('networkidle')
      expect(new URL(page.url()).pathname).toBe('/')
      await expect(page.getByLabel('Username')).toHaveCount(0)
    } finally {
      fixture('cleanup', username)
    }
  })
}
