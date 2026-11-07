import { test, expect } from '@playwright/test'
import type { ReadingPlanReaderView } from '../services/api-continuity-plans'
import type { IssueCard } from '../services/issueCardsApi'

/** Rendered transport regression: page batches own metadata, including blocked cards. */
for (const width of [390, 1280]) {
  test(`shared blocked issue card uses one batch and exact direct save at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const issue = {
      occurrence_id: 'blocked', issue_id: 75, thread_id: 8, thread_title: 'Cable',
      issue_number: '75', lane_id: 'main', display_position: 0, status: 'unread',
      availability: 'blocked' as const, blockers: [], source_paths: [],
    }
    const view: ReadingPlanReaderView = {
      plan_id: 12, name: 'Direct reading', ordering_mode: 'informational',
      progress: { total_issues: 1, read_issues: 0 }, available_now: [], blocked_next: [issue],
      lanes: [{ id: 'main', name: 'Main', order: 0, issues: [issue] }], sources: [],
      release_sources: [], release_candidates: [],
    }
    const card: IssueCard = {
      issue_id: 75, thread_id: 8, thread_title: 'Cable', issue_number: '75', status: 'unread',
      rating: null, mapping_state: 'unmapped', has_confirmed_identity: false,
    }
    const batches: unknown[] = []
    const writes: unknown[] = []
    const unexpectedWrites: string[] = []
    await page.route('**/api/**', async (route) => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      const body = (() => {
      if (path === '/api/v2/auth/me') {
        return { id: 1, username: 'reader', email: 'reader@example.test', preferences: { theme: 'classic' } }
      } else if (path === '/api/v2/auth/csrf') {
        return { csrf_token: 'test-csrf' }
      } else if (path === '/api/v2/continuity-plans/12/reader') {
        return view
      } else if (path.includes('/tags/effective/thread/')) {
        return { thread_id: 8, issues: [] }
      } else if (path.includes('/tags/effective/plan/')) {
        return { target_type: 'ContinuityPlan', target_id: 12, direct_tags: [], effective_tags: [] }
      } else if (path === '/api/v2/issues/cards') {
        batches.push(request.postDataJSON())
        return { items: [card] }
      } else if (path === '/api/v2/issues/75' && request.method() === 'PATCH') {
        writes.push(request.postDataJSON())
        card.status = 'read'
        card.rating = 4
        return {
          issue: card,
          thread: { thread_id: 8, issues_remaining: 0, status: 'completed' },
          read_event_created: true, rating_event_created: true, replayed: false,
        }
      } else if (request.method() !== 'GET') {
        unexpectedWrites.push(`${request.method()} ${path}`)
      }
      return {}
      })()
      await route.fulfill({ json: body })
    })
    await page.addInitScript(() => localStorage.setItem('auth_token', 'test-access-token'))
    await page.goto('/continuity-plans/12', { waitUntil: 'domcontentloaded' })
    const row = page.getByTestId('blocked-next').getByRole('article', { name: 'Issue Cable #75' })
    await expect(row.getByRole('button', { name: 'Read now', exact: true })).toBeEnabled()
    await expect.poll(() => batches).toEqual([{ issue_ids: [75] }])
    await row.getByRole('button', { name: 'Read now', exact: true }).click()
    await expect(row.getByRole('slider')).toHaveValue('3.5')
    await row.getByRole('button', { name: 'Cancel', exact: true }).click()
    expect(writes).toEqual([])
    await row.getByRole('button', { name: 'Read now', exact: true }).focus()
    await page.keyboard.press('Enter')
    await row.getByRole('slider').focus()
    await page.keyboard.press('ArrowRight')
    await expect(row.getByRole('slider')).toHaveValue('4')
    await row.getByRole('button', { name: 'Mark read & save' }).click()
    await expect(row.getByText('Rated 4', { exact: false })).toBeVisible()
    expect(writes).toEqual([expect.objectContaining({ source: 'direct', status: 'read', rating: 4, idempotency_key: expect.any(String) })])
    expect(unexpectedWrites).toEqual([])
    await expect(row.getByRole('button', { name: 'Mark unread', exact: true })).toBeEnabled()
    await expect.poll(() => batches).toEqual([{ issue_ids: [75] }, { issue_ids: [75] }])
    await expect(page).toHaveURL(/\/continuity-plans\/12$/)
  })
}
