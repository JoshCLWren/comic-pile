import { expect, test } from '@playwright/test'
import { isObject, isString } from '../utils/runtimeChecks'

// Exercise the built browser app with deterministic API responses. No real
// credentials or production writes are needed for this session-boundary regression.
test('account switching isolates inbox data and stops signed-out inbox requests', async ({ page }) => {
  let account = ''
  let inboxRequests = 0
  let unsignedInboxRequests = 0
  let refreshRequests = 0
  const crashes: string[] = []
  page.on('pageerror', error => crashes.push(error.message))
  await page.route('**/api/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const respond = (body: unknown, status = 200) => route.fulfill({ status, json: body })
    if (path.endsWith('/auth/csrf')) return respond({ csrf_token: 'test-csrf' })
    if (path.endsWith('/auth/login')) {
      const credentials: unknown = request.postDataJSON()
      if (!isObject(credentials) || !isString(credentials.username) || !isString(credentials.password)) {
        throw new Error('Login request must contain a username and password')
      }
      if (credentials.password !== 'correct-password') {
        return respond({ detail: 'Incorrect username or password' }, 401)
      }
      account = credentials.username
      return respond({ access_token: account + '-token', token_type: 'bearer' })
    }
    if (path.endsWith('/auth/logout')) { account = ''; return respond({}) }
    if (path.endsWith('/auth/refresh')) {
      refreshRequests += 1
      return respond({ detail: 'Missing refresh token' }, 401)
    }
    if (path.endsWith('/auth/me')) {
      return account ? respond({ id: account === 'first' ? 1 : 2, username: account, email: account + '@example.com' })
        : respond({ detail: 'Not authenticated' }, 401)
    }
    if (path.endsWith('/auth/forgot-password')) return respond({ message: 'Reset requested' })
    if (path.endsWith('/users/me/preferences')) return respond({ theme: 'classic', user_id: account === 'first' ? 1 : 2 })
    if (path.endsWith('/identity-inbox')) {
      inboxRequests += 1
      if (!account || !request.headers().authorization) unsignedInboxRequests += 1
      return respond({ items: [{
        mapping_id: account === 'first' ? 1 : 2, issue_id: 10, thread_id: 100,
        thread_title: account + ' private comic', issue_number: '1', status: 'unresolved',
        provider: 'comicvine', source_entry_summary: 'Issue 1', why_stopped: 'No candidate',
        candidates: [], created_at: null, updated_at: null,
      }], total: 1, offset: 0, limit: Number(new URL(request.url()).searchParams.get('limit') ?? 20) })
    }
    if (path.endsWith('/roll/bootstrap')) return respond({
      session_id: account === 'first' ? 1 : 2, user_id: account === 'first' ? 1 : 2,
      current_die: 6, manual_die: null, pending_thread_id: null, last_rolled_result: null,
      session_mode: { bandwidth: 'balanced', intent: 'random' }, active_thread: null,
      roll_pool: [], snoozed_threads: [], snoozed_count: 0, skipped_thread_ids: [],
      skipped_threads: [], blocked_count: 0, blocked_threads: [], stale_thread_count: 0, stale_thread: null,
    })
    if (path.endsWith('/threads/')) return respond({ threads: [], next_page_token: null })
    return respond({})
  })

  async function login(username: string, password = 'correct-password') {
    await page.getByLabel('Username', { exact: true }).fill(username)
    await page.getByLabel('Password', { exact: true }).fill(password)
    await page.getByRole('button', { name: 'Sign In', exact: true }).click()
  }
  async function openInbox(username: string) {
    await page.getByRole('link', { name: 'Identity Inbox page' }).click()
    await expect(page.getByText(username + ' private comic', { exact: true })).toBeVisible()
  }

  await page.goto('/login')
  await expect(page.getByLabel('Username', { exact: true })).toBeVisible()
  expect(inboxRequests).toBe(0)
  await login('first')
  await openInbox('first')
  await page.getByRole('button', { name: 'Log out', exact: true }).click()
  await expect(page.getByLabel('Username', { exact: true })).toBeVisible()
  const beforeWrongPasswords = inboxRequests
  await login('second', 'wrong-password')
  await expect(page.getByText('Incorrect username or password', { exact: true })).toBeVisible()
  await login('second', 'wrong-password')
  await expect(page.getByText('Incorrect username or password', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Forgot password?' }).click()
  await page.getByLabel('Email', { exact: true }).fill('second@example.com')
  await page.getByRole('button', { name: /send reset link/i }).click()
  await page.getByRole('link', { name: /back to sign in/i }).click()
  await expect(page.getByLabel('Username', { exact: true })).toBeVisible()
  expect(inboxRequests).toBe(beforeWrongPasswords)
  expect(refreshRequests).toBe(0)

  await login('second')
  await openInbox('second')
  await expect(page.getByText('first private comic', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Log out', exact: true }).click()
  await expect(page.getByLabel('Username', { exact: true })).toBeVisible()
  await login('first')
  await openInbox('first')
  await expect(page.getByText('second private comic', { exact: true })).toHaveCount(0)
  expect(unsignedInboxRequests).toBe(0)
  expect(crashes).toEqual([])
  await expect(page.getByRole('button', { name: 'Reload ComicPile' })).toHaveCount(0)
})
