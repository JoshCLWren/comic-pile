import { expect, test } from '@playwright/test'

type ActivityRow = {
  event_id: number
  event_type: string
  timestamp: string
  die_before: number | null
  die_after: number | null
  rating: number | null
  thread_id: number | null
  thread_title: string | null
  issue_id: number | null
  issue_number: string | null
  action_display: string
}

const row = (event_id: number, overrides: Partial<ActivityRow>): ActivityRow => ({
  event_id,
  event_type: 'roll',
  timestamp: '2026-11-08T15:42:35.028Z',
  die_before: 6,
  die_after: null,
  rating: null,
  thread_id: 3153,
  thread_title: 'First Series',
  issue_id: 1121330,
  issue_number: '1',
  action_display: 'Rolled First Series #1',
  ...overrides,
})

/**
 * The owner-reported 09:42→10:01 production sequence (#4822), newest first,
 * exactly as GET /api/v2/activity projects it: causal snooze→roll pairs even
 * where recorded timestamps invert, and the paired rate receipts shown once.
 */
const sequence: ActivityRow[] = [
  row(7, {
    event_type: 'rate',
    timestamp: '2026-11-08T16:01:00Z',
    die_before: 10,
    die_after: 8,
    rating: 4.5,
    thread_id: 8417,
    thread_title: 'Third Series',
    issue_id: 52329,
    issue_number: '2',
    action_display: 'Rated Third Series #2 ⭐4.5',
  }),
  row(4, {
    event_type: 'snooze',
    timestamp: '2026-11-08T15:58:00Z',
    die_before: 8,
    die_after: 10,
    thread_id: 3469,
    thread_title: 'Second Series',
    issue_id: null,
    issue_number: null,
    action_display: 'Snoozed Second Series (d8 → d10)',
  }),
  row(5, {
    timestamp: '2026-11-08T15:55:00Z',
    thread_id: 8417,
    thread_title: 'Third Series',
    issue_id: 52329,
    issue_number: '2',
    action_display: 'Rolled Third Series #2',
  }),
  row(2, {
    event_type: 'snooze',
    timestamp: '2026-11-08T15:50:00Z',
    die_before: 6,
    die_after: 8,
    thread_id: 3153,
    thread_title: 'First Series',
    issue_id: null,
    issue_number: null,
    action_display: 'Snoozed First Series (d6 → d8)',
  }),
  row(3, {
    timestamp: '2026-11-08T15:48:00Z',
    thread_id: 3469,
    thread_title: 'Second Series',
    issue_id: 25301,
    issue_number: '2',
    action_display: 'Rolled Second Series #2',
  }),
  row(1, {}),
]

const displays = sequence.map((entry) => entry.action_display)

test('History renders the reported activity sequence once through load-more and refresh', async ({ page }) => {
  const requests: string[] = []
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/v2/auth/me') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 1, username: 'reader', email: null, is_admin: false }) })
      return
    }
    if (url.pathname === '/api/v2/activity') {
      requests.push(url.search)
      const next = url.searchParams.get('page_token')
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(next
        ? { events: [], next_page_token: null }
        : { events: sequence, next_page_token: '123:1' }) })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })

  await page.goto('/history')
  await expect(page.getByRole('heading', { name: 'History' })).toBeVisible()

  const rows = page.getByRole('listitem')
  await expect(rows).toHaveCount(displays.length)
  for (const [index, display] of displays.entries()) {
    await expect(rows.nth(index)).toContainText(display)
  }

  // The paired rate receipts display exactly once; both snoozes and all rolls show.
  await expect(page.getByText(/⭐4\.5/)).toHaveCount(1)
  await expect(page.getByText(/^Snoozed /)).toHaveCount(2)
  await expect(page.getByText(/^Rolled /)).toHaveCount(3)

  // Server timestamps stay machine-readable on the rendered rows.
  await expect(rows.nth(0).locator('time')).toHaveAttribute('dateTime', '2026-11-08T16:01:00Z')
  await expect(rows.nth(displays.length - 1).locator('time')).toHaveAttribute('dateTime', '2026-11-08T15:42:35.028Z')

  // Continuing the cursor must not duplicate a step.
  await page.getByRole('button', { name: 'Load More Activity' }).click()
  await expect(rows).toHaveCount(displays.length)
  await expect(page.getByRole('button', { name: 'Load More Activity' })).toHaveCount(0)
  await expect(page.getByText(/⭐4\.5/)).toHaveCount(1)
  expect(
    requests.some((search) => new URLSearchParams(search).get('page_token') === '123:1'),
  ).toBe(true)

  // A refresh re-reads the first page without re-rendering any step twice.
  const refreshResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/v2/activity' &&
      response.request().method() === 'GET',
  )
  await page.getByRole('button', { name: 'Refresh' }).click()
  await refreshResponse
  await expect(rows).toHaveCount(displays.length)
  await expect(rows.nth(0)).toContainText('Rated Third Series #2 ⭐4.5')
  await expect(page.getByText(/⭐4\.5/)).toHaveCount(1)
  const firstPageRequests = requests.filter(
    (search) => !new URLSearchParams(search).has('page_token'),
  )
  expect(firstPageRequests.length).toBeGreaterThanOrEqual(2)
})
