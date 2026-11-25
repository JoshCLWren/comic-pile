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
      identity_version: 1,
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

/** Browser-level conflict recovery through the shared reader, not a simulated hook caller. */
test('mixed-number provider mapping preserves the authored row across cancel and failed conflict reload', async ({ page }) => {
  const issue = {
    occurrence_id: 'arc-three', issue_id: 75, thread_id: 8, thread_title: 'Synthetic arc',
    issue_number: '3', lane_id: 'main', display_position: 0, status: 'unread',
    availability: 'blocked' as const, blockers: [], source_paths: [],
  }
  const view: ReadingPlanReaderView = {
    plan_id: 12, name: 'Mixed numbering', ordering_mode: 'informational',
    progress: { total_issues: 1, read_issues: 0 }, available_now: [], blocked_next: [issue],
    lanes: [{ id: 'main', name: 'Main', order: 0, issues: [issue] }], sources: [],
    release_sources: [], release_candidates: [],
  }
  const card: IssueCard = {
    identity_version: 7, issue_id: 75, thread_id: 8, thread_title: 'Synthetic arc',
    issue_number: '3', overall_issue_number: '100', status: 'unread', rating: null,
    mapping_state: 'unmapped', has_confirmed_identity: false,
  }
  const identity = {
    issue_id: 75, thread_id: 8, thread_title: 'Synthetic arc', issue_number: '3',
    overall_issue_number: '100', identity_version: 8, has_confirmed_identity: false,
    comicvine_issue_id: null, confirmed_mappings: [], candidate_mappings: [], has_unresolved: false,
  }
  const providerIssue = {
    comicvine_issue_id: 8100, series_name: 'Synthetic adjacent provider volume',
    volume_id: 901, issue_number: '100', name: 'Third chapter',
    cover_date: null, store_date: null, image_url: null, site_detail_url: null,
  }
  const writes: unknown[] = []
  const unexpectedWrites: string[] = []
  let reloads = 0
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    let body: unknown = {}
    let status = 200
    if (path === '/api/v2/auth/me') {
      body = { id: 1, username: 'reader', email: 'reader@example.test', preferences: { theme: 'classic' } }
    } else if (path === '/api/v2/auth/csrf') {
      body = { csrf_token: 'test-csrf' }
    } else if (path === '/api/v2/continuity-plans/12/reader') {
      body = view
    } else if (path.includes('/tags/effective/thread/')) {
      body = { thread_id: 8, issues: [] }
    } else if (path.includes('/tags/effective/plan/')) {
      body = { target_type: 'ContinuityPlan', target_id: 12, direct_tags: [], effective_tags: [] }
    } else if (path === '/api/v2/issues/cards') {
      body = { items: [card] }
    } else if (path === '/api/v2/comicvine/search/series') {
      body = { query: '', results: [], total_available: 0, offset: 0, limit: 10, has_more: false, next_offset: null }
    } else if (path === '/api/v2/comicvine/resolve') {
      body = { input: 'synthetic', kind: 'issue', validation_error: null, issue: providerIssue, volume: null, issues: [] }
    } else if (path === '/api/v2/comicvine/issues/75/identity' && method === 'GET') {
      reloads += 1
      if (reloads === 1) {
        status = 503
        body = { detail: 'Identity temporarily unavailable' }
      } else {
        body = card.has_confirmed_identity
          ? { ...identity, identity_version: 9, has_confirmed_identity: true, comicvine_issue_id: '8100', provider_issue_number: '100' }
          : identity
      }
    } else if (path === '/api/v2/comicvine/issues/75/identity:confirm' && method === 'POST') {
      writes.push(request.postDataJSON())
      if (writes.length === 1) {
        status = 409
        body = { detail: 'Identity changed; reload before retrying' }
      } else {
        card.identity_version = 9
        card.mapping_state = 'mapped'
        card.has_confirmed_identity = true
        card.provider_issue_number = '100'
        card.comicvine_issue_id = '8100'
        body = { ...identity, identity_version: 9, has_confirmed_identity: true, comicvine_issue_id: '8100', provider_issue_number: '100' }
      }
    } else if (method !== 'GET') {
      unexpectedWrites.push(`${method} ${path}`)
    }
    await route.fulfill({ status, json: body })
  })
  await page.addInitScript(() => localStorage.setItem('auth_token', 'test-access-token'))
  await page.goto('/continuity-plans/12', { waitUntil: 'domcontentloaded' })
  const row = page.getByTestId('blocked-next').getByRole('article', { name: 'Issue Synthetic arc #3' })
  await expect(row.getByTestId('comic-overall-alias')).toHaveText('OVERALL #100')
  const selectProvider = async () => {
    await row.getByTestId('comic-mapping-map').click()
    await page.getByPlaceholder('Search series title or paste a ComicVine URL').fill(
      'https://comicvine.gamespot.com/synthetic-arc/4000-8100/',
    )
    await expect(page.getByTestId('comicvine-confirm-card')).toContainText('Synthetic adjacent provider volume')
    await expect(page.getByTestId('comicvine-confirm-card')).toContainText('#100')
  }
  await selectProvider()
  await page.getByRole('button', { name: 'Close modal' }).click()
  expect(writes).toEqual([])
  await selectProvider()
  const confirm = page.getByRole('button', { name: 'Confirm Identity' })
  await confirm.click()
  await expect(page.getByRole('alert')).toContainText('Identity changed')
  await expect(confirm).toBeDisabled()
  await page.getByTestId('comicvine-retry').click()
  await expect(page.getByRole('alert')).toContainText('Could not reload')
  await expect(confirm).toBeDisabled()
  expect(writes).toEqual([{ comicvine_issue_id: 8100, expected_version: 7 }])
  await page.getByTestId('comicvine-retry').click()
  await expect(page.getByText(/Current identity reloaded/)).toBeVisible()
  await expect(confirm).toBeEnabled()
  await confirm.click()
  await expect.poll(() => writes).toEqual([
    { comicvine_issue_id: 8100, expected_version: 7 },
    { comicvine_issue_id: 8100, expected_version: 8 },
  ])
  await page.getByRole('button', { name: 'Close modal' }).click()
  await expect(row.getByTestId('comic-provider-issue-number')).toHaveText('PROVIDER #100')
  await expect(row.getByTestId('comic-overall-alias')).toHaveText('OVERALL #100')
  await expect(page.getByTestId('blocked-next').getByRole('article')).toHaveCount(1)
  expect(unexpectedWrites).toEqual([])
})
