/**
 * Issue #3575: History must search/filter the reader's chronological activity
 * on the server (text, series, activity type and reader-local dates), expose a
 * clear/reset action, and tell the truth when a filtered page has no rows.
 *
 * The activity resource is stubbed at the network edge so the assertions
 * observe the exact query parameters the real History page sends and the exact
 * order of the rows it renders. Auth still uses a genuinely registered user.
 */
import { expect, type APIRequestContext, type Page } from '@playwright/test'
import { test } from './auth-fixtures'
import { generateTestUser } from './helpers'

const ACTIVITY_PATH = '/api/v2/activity'

type ActivityRow = {
  event_id: number
  type: string
  timestamp: string
  die_before: number | null
  die_after: number | null
  rating: number | null
  issue_id: number | null
  thread_id: number | null
  thread_title: string | null
  issue_number: string | null
  session_id: number | null
}

const rolled: ActivityRow = {
  event_id: 1050511,
  type: 'roll',
  timestamp: '2026-11-08T15:42:35.028000Z',
  die_before: 6,
  die_after: null,
  rating: null,
  issue_id: 1121330,
  thread_id: 3153,
  thread_title: 'Saga',
  issue_number: '4',
  session_id: null,
}

const rated: ActivityRow = {
  event_id: 1050517,
  type: 'rate',
  timestamp: '2026-11-08T16:01:54.388000Z',
  die_before: 10,
  die_after: 8,
  rating: 4.5,
  issue_id: 52329,
  thread_id: 8417,
  thread_title: 'Astro City: Astra',
  issue_number: '2',
  session_id: null,
}

function activityBody(items: ActivityRow[]) {
  return JSON.stringify({
    activities: items,
    events: items,
    items,
    next_page_token: null,
    next_cursor: null,
  })
}

async function registerRealUser(page: Page, request: APIRequestContext): Promise<void> {
  const user = generateTestUser()
  const registered = await request.post('/api/v2/auth/register', {
    data: { username: user.username, email: user.email, password: user.password },
  })
  expect(registered.ok(), `register failed: ${registered.status()}`).toBeTruthy()
  const loggedIn = await request.post('/api/v2/auth/login', {
    data: { username: user.username, password: user.password },
  })
  expect(loggedIn.ok(), `login failed: ${loggedIn.status()}`).toBeTruthy()
  const body = (await loggedIn.json()) as { access_token?: string }
  expect(body.access_token, 'login response must carry an access token').toBeTruthy()
  await page.addInitScript((accessToken: string) => {
    localStorage.setItem('auth_token', accessToken)
    const clientWindow = window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }
    clientWindow.__COMIC_PILE_ACCESS_TOKEN = accessToken
  }, body.access_token!)
}

test.describe('History search and filters (issue #3575)', () => {
  test('combined filters reach the activity resource and chronology is preserved', async ({
    page,
    request,
  }) => {
    const requests: URL[] = []
    await page.route(
      (url) => url.pathname === ACTIVITY_PATH,
      async (route) => {
        requests.push(new URL(route.request().url()))
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: activityBody([rolled, rated]),
        })
      },
    )
    await registerRealUser(page, request)
    await page.goto('/history')

    const list = page.getByRole('list', { name: 'Activity history' })
    await expect(list.getByRole('listitem')).toHaveCount(2)
    await expect(list.getByRole('listitem').first()).toContainText('Rolled · Saga #4')

    await page.getByRole('searchbox', { name: 'Search activity' }).fill('Saga')
    await page.getByRole('searchbox', { name: 'Series' }).fill('Paper Girls')
    await page.getByRole('combobox', { name: 'Activity type' }).selectOption('roll')
    await page.getByLabel('From date').fill('2026-11-08')
    await page.getByLabel('To date').fill('2026-11-09')

    // Text inputs settle through a short debounce; wait for the final request
    // that carries every control, not the intermediate keystroke requests.
    await expect
      .poll(() => {
        const params = requests.at(-1)?.searchParams
        if (!params) return ''
        return [
          params.get('q'),
          params.get('series'),
          params.get('type'),
          params.get('date_from'),
          params.get('date_to'),
        ].join('|')
      })
      .toBe('Saga|Paper Girls|roll|2026-11-08|2026-11-09')
    const latest = requests.at(-1)!
    expect(latest.searchParams.get('series')).toBe('Paper Girls')
    expect(latest.searchParams.get('type')).toBe('roll')
    expect(latest.searchParams.get('date_from')).toBe('2026-11-08')
    expect(latest.searchParams.get('date_to')).toBe('2026-11-09')
    expect(latest.searchParams.get('timezone')).toBeTruthy()
    expect(latest.searchParams.get('limit')).toBe('50')

    // Filtering replaces the stream in place; it never reorders cached rows.
    await expect(list.getByRole('listitem').first()).toContainText('Rolled · Saga #4')

    await page.getByRole('button', { name: 'Clear filters' }).click()
    await expect(page.getByRole('combobox', { name: 'Activity type' })).toHaveValue('')
    await expect(page.getByRole('searchbox', { name: 'Search activity' })).toHaveValue('')
    await expect(page.getByRole('searchbox', { name: 'Series' })).toHaveValue('')
    await expect(page.getByRole('button', { name: 'Clear filters' })).toBeDisabled()
    await expect(list.getByRole('listitem')).toHaveCount(2)
  })

  test('a filtered empty result is distinct from an empty history', async ({ page, request }) => {
    await page.route(
      (url) => url.pathname === ACTIVITY_PATH,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: activityBody([]),
        })
      },
    )
    await registerRealUser(page, request)
    await page.goto('/history')

    await expect(page.getByText('No activity yet')).toBeVisible()
    await page.getByRole('combobox', { name: 'Activity type' }).selectOption('reset_dice')

    await expect(page.getByText('No activity matches these filters')).toBeVisible()
    await expect(page.getByText('No activity yet')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Clear filters' })).toBeEnabled()

    await page.getByRole('button', { name: 'Clear filters' }).click()
    await expect(page.getByText('No activity yet')).toBeVisible()
  })
})
