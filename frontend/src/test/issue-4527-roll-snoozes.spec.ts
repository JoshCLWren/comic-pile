import { test, expect } from '@playwright/test'

const exhaustedMessage = 'No other eligible comics remain. Reset Dice to clear temporary snoozes, or wait until tomorrow.'

for (const count of [1, 25]) {
  test(`daily snoozes with ${count} eligible comics`, async ({ page }) => {
    let pending = 1
    let resets = 0
    const thread = (id: number) => ({
      id, title: `Daily Comic ${id}`, format: 'Comic', tags: [],
      issues_remaining: 2, queue_position: id, issue_id: id * 10,
      issue_number: '1', next_issue_id: id * 10, next_issue_number: '1',
      total_issues: 2, reading_progress: null,
    })
    await page.addInitScript(() => localStorage.setItem('auth_token', 'test-access-token'))
    await page.route('**/api/**', async route => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      if (path.endsWith('/auth/me')) {
        return route.fulfill({ json: { id: 1, username: 'reader', email: 'reader@example.test', preferences: { theme: 'classic' } } })
      }
      if (path.endsWith('/auth/refresh')) return route.fulfill({ json: { access_token: 'test-access-token' } })
      if (path.endsWith('/auth/csrf')) return route.fulfill({ json: { csrf_token: 'test-csrf' } })
      if (path.endsWith('/roll/offer')) {
        if (count === 1) return route.fulfill({ status: 400, json: { detail: exhaustedMessage } })
        // SAFETY: this route receives the real Roll client payload; the assertion below checks its exclusion array.
        const body = request.postDataJSON() as { snoozed_thread_ids: number[] }
        expect(body.snoozed_thread_ids).toEqual([])
        pending = 2
        return route.fulfill({ json: { ...thread(2), thread_id: 2, die_size: 20, result: 1, snoozed_thread_id: 1 } })
      }
      if (path.endsWith('/roll/dismiss-pending')) {
        pending = 0
        return route.fulfill({ json: {} })
      }
      if (path.endsWith('/roll/reset')) {
        resets += 1
        pending = 0
        return route.fulfill({ json: { die: 6, replayed: false } })
      }
      if (path.endsWith('/roll/bootstrap')) {
        const cookie = (await request.allHeaders()).cookie ?? ''
        const excluded = cookie.includes('comicpile_roll_snoozes=%5B1%5D') ? [1] : []
        const ids = Array.from({ length: count }, (_, i) => i + 1).filter(id => !excluded.includes(id)).slice(0, 20)
        return route.fulfill({ json: {
          session_id: 1, user_id: 1, current_die: 20, manual_die: null,
          pending_thread_id: pending || null, last_rolled_result: pending ? 1 : null,
          session_mode: 'warm', active_thread: pending ? thread(pending) : null,
          bandwidth: null, pool_reason: 'ready', last_read: null,
          snoozed_threads: [], snoozed_count: 0, skipped_thread_ids: [], skipped_threads: [],
          rollable: ids.map(id => ({ thread: thread(id), issue: { id: id * 10, number: '1' }, routes: [] })),
        } })
      }
      if (path.includes('/tags')) return route.fulfill({ json: { tags: [], direct_tags: [], effective_tags: [] } })
      if (path.endsWith('/comicvine')) return route.fulfill({ json: null })
      if (path.endsWith('/reader-context')) return route.fulfill({ json: null })
      if (path.endsWith('/reading-orders')) return route.fulfill({ json: { reading_orders: [] } })
      if (path.endsWith('/connected')) return route.fulfill({ json: { connected_threads: [] } })
      if (/\/threads\/\d+$/.test(path)) return route.fulfill({ json: thread(pending || 1) })
      return route.fulfill({ json: [] })
    })
    await page.goto('/')
    await expect(page.getByTestId('rating-view-top')).toBeVisible()
    await page.getByTestId('reroll-offer').click()
    if (count === 1) {
      await expect(page.getByRole('alert')).toContainText('No other eligible comics remain.')
      expect(resets).toBe(0)
      await page.getByRole('button', { name: 'Reset Dice', exact: true }).click()
      await expect(page.getByTestId('reset-dice')).toBeVisible()
      await page.getByTestId('reset-dice').click()
      await expect.poll(() => resets).toBe(1)
      await expect(page.getByTestId('rating-view-top')).not.toBeVisible()
    } else {
      await expect(page.getByTestId('comic-header-title')).toContainText('Daily Comic 2')
      await page.getByRole('button', { name: 'Cancel roll', exact: true }).click()
      const pool = page.locator('[data-roll-pool]')
      await expect(pool).toBeVisible()
      await expect(pool.getByText('Daily Comic 1', { exact: true })).toHaveCount(0)
      await expect(pool.getByText('Daily Comic 21', { exact: true })).toBeAttached()
      await page.reload()
      await expect(page.locator('[data-roll-pool]')).toBeVisible()
      await expect(page.locator('[data-roll-pool]').getByText('Daily Comic 1', { exact: true })).toHaveCount(0)
    }
  })
}
