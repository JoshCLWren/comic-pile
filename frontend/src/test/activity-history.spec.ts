import { expect, test } from '@playwright/test'

const activity = (event_id: number, action_display: string) => ({
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
  action_display,
})

test('History loads activity, continues a cursor page, and refreshes', async ({ page }) => {
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
        ? { events: [activity(2, 'Snoozed First Series (d6 → d8)')], next_page_token: null }
        : { events: [activity(1, 'Rolled First Series #1')], next_page_token: '123:1' }) })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })

  await page.goto('/history')
  await expect(page.getByRole('heading', { name: 'History' })).toBeVisible()
  await expect(page.getByText('Rolled First Series #1')).toBeVisible()
  await page.getByRole('button', { name: 'Load more' }).click()
  await expect(page.getByText('Snoozed First Series (d6 → d8)')).toBeVisible()
  expect(requests).toContain('?page_token=123:1')
  await page.getByRole('button', { name: 'Refresh' }).click()
  await expect(page.getByText('Rolled First Series #1')).toBeVisible()
  expect(requests.filter((search) => search === '').length).toBeGreaterThanOrEqual(2)
})
