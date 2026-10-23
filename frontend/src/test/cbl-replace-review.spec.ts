// Run with the local fixture backend's Option E execution enabled.
import { test, expect } from './fixtures'
import type { ReadingListPredecessorChange } from '../services/api-custom-cbl'
import type { Page } from '@playwright/test'
import { createThread, getAuthToken } from './helpers'

async function getCsrf(page: Page, token: string | null): Promise<string> {
  const response = await page.request.get('/api/auth/csrf', {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
  expect(response.ok()).toBeTruthy()
  // SAFETY: the test reads only csrf_token from the response body
  const data = await response.json() as { csrf_token?: string }
  expect(data.csrf_token).toBeDefined()
  return data.csrf_token!
}

async function authHeaders(page: Page) {
  const token = await getAuthToken(page)
  expect(token).toBeTruthy()
  const csrf = await getCsrf(page, token)
  return {
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrf,
    Authorization: `Bearer ${token}`,
  }
}

async function getFirstIssueId(page: Page, threadId: number): Promise<number> {
  const headers = await authHeaders(page)
  const response = await page.request.get(`/api/v1/threads/${threadId}/issues`, { headers })
  expect(response.ok(), await response.text()).toBeTruthy()
  // SAFETY: the test reads only the response fields listed in this type
  const data = await response.json() as { issues: Array<{ id: number }> }
  expect(data.issues.length).toBeGreaterThan(0)
  return data.issues[0].id
}

async function createReadingPlan(page: Page, name: string): Promise<number> {
  await page.goto('/continuity-plans', { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: 'New Reading Plan' }).click()
  await expect(page.getByRole('heading', { name: 'New Reading Plan' })).toBeVisible()
  await page.getByLabel('Plan name').fill(name)
  await page.getByRole('radio', { name: /^Strict/i }).check()
  await page.getByRole('button', { name: 'Save plan' }).click()
  await expect(page).toHaveURL(/\/continuity-plans\/\d+/)
  return Number(page.url().match(/\/continuity-plans\/(\d+)/)?.[1])
}

type ReadingListResponse = {
  id: number
  name: string
  description: string | null
  mode: string
  updated_at: string
  entries: Array<{ issue_id: number; position: number }>
}

async function createReadingList(
  page: Page,
  name: string,
  description: string,
  issueIds: number[],
  mode: 'strict' | 'loose' = 'strict',
): Promise<number> {
  const headers = await authHeaders(page)
  const response = await page.request.post('/api/v1/custom-cbls', {
    headers,
    data: {
      name,
      description,
      mode,
      issue_ids: issueIds,
      entry_intents: Object.fromEntries(
        issueIds.map((issueId) => [issueId, { gate: 'none', skipped: false }]),
      ),
      checkpoint_issue_ids: [],
    },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  // SAFETY: the test reads only the response fields listed in this type
  const created = (await response.json()) as { id: number }
  return created.id
}

async function getReadingList(page: Page, listId: number): Promise<ReadingListResponse> {
  const headers = await authHeaders(page)
  const response = await page.request.get(`/api/v1/custom-cbls/${listId}`, { headers })
  expect(response.ok(), await response.text()).toBeTruthy()
  // SAFETY: the test reads only the response fields listed in this type
  return (await response.json()) as ReadingListResponse
}

async function applyReadingList(
  page: Page,
  listId: number,
  planId: number,
): Promise<void> {
  const headers = await authHeaders(page)
  const response = await page.request.post(
    `/api/v1/custom-cbls/${listId}/reading-plans/${planId}:apply`,
    { headers, data: { lane_id: null } },
  )
  expect(response.ok(), await response.text()).toBeTruthy()
}

async function isThreadBlocked(page: Page, threadId: number): Promise<boolean> {
  const headers = await authHeaders(page)
  const response = await page.request.post(
    `/api/v1/threads/${threadId}:getBlockingInfo`,
    { headers },
  )
  expect(response.ok(), await response.text()).toBeTruthy()
  // SAFETY: the test reads only is_blocked from the response body
  const payload = (await response.json()) as { is_blocked: boolean }
  return payload.is_blocked
}

type PreviewBodyEntry = {
  cbl_position: number
  cbl_entry_id: number
  series_name: string
  issue_number: string
  series_group_id: string
  adoption_class: string
  adoption_decision: string
  adopted: boolean
  resolved_issue_id: number | null
  resolution_status: string
}

function previewBody(sourceListId: number, entries: PreviewBodyEntry[]) {
  return {
    source: {
      source_list_id: sourceListId,
      source_repository: 'shared/cbls',
      source_path: `fixture-${sourceListId}.cbl`,
      content_hash: `fixture-hash-${sourceListId}`,
      revision_sha: `fixture-revision-${sourceListId}`,
    },
    total_positions: entries.length,
    entries,
    summary: {
      reused_existing_count: entries.length,
      missing_would_create_count: 0,
      excluded_count: 0,
      unresolved_count: 0,
      awaiting_opt_in_count: 0,
      final_adopted_count: entries.length,
      final_adopted_order: entries.map((entry) => entry.cbl_position),
      reused_existing_positions: entries.map((entry) => entry.cbl_position),
      missing_would_create_positions: [],
      excluded_positions: [],
      unresolved_positions: [],
      awaiting_opt_in_positions: [],
    },
  }
}

type PreviewEntry = {
  cbl_position: number
  cbl_entry_id: number
  series_name: string
  issue_number: string
  series_group_id: string
  adoption_class: string
  adoption_decision: string
  adopted: boolean
  resolved_issue_id: number | null
  resolution_status: string
}

/**
 * #4027: the replace review is reachable from the Reading List editor, shows
 * exact before/after IDs plus manual extras and graph impact, replaces only the
 * selected list, and Undo restores list membership without touching history.
 */
test.describe('CBL replacement review', () => {
  test('replaces one owned Reading List and undoes list membership only', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const suffix = Date.now()
    const firstTitle = `Replace First ${suffix}`
    const removedTitle = `Replace Removed ${suffix}`
    const manualTitle = `Replace Manual ${suffix}`
    const first = await createThread(page, {
      title: firstTitle,
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const removed = await createThread(page, {
      title: removedTitle,
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const manual = await createThread(page, {
      title: manualTitle,
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const firstIssueId = await getFirstIssueId(page, first.id)
    const removedIssueId = await getFirstIssueId(page, removed.id)
    const manualIssueId = await getFirstIssueId(page, manual.id)

    await createReadingPlan(page, `Replace Review Plan ${suffix}`)
    const builder = page.locator('section[aria-labelledby="custom-cbl-heading"]')
    await builder.getByRole('button', { name: 'Create or edit custom CBL' }).click()
    await page.getByLabel('New custom CBL name').fill(`Replace Review List ${suffix}`)
    await page.getByRole('button', { name: 'Create' }).click()

    for (const series of [firstTitle, removedTitle, manualTitle]) {
      await page.getByLabel('Search issues for custom CBL').fill(series)
      await page.getByRole('button', { name: 'Find issues' }).click()
      await page.getByRole('button', { name: new RegExp(`${series} #1`) }).click()
    }
    await expect(builder.getByRole('list', { name: 'Custom CBL ordered issues' })).toContainText(
      manualTitle,
    )
    await page.getByRole('button', { name: 'Save custom CBL' }).click()
    await expect(builder.getByRole('status')).toContainText('Custom CBL saved.')

    const entries: PreviewEntry[] = [
      {
        cbl_position: 0,
        cbl_entry_id: 1,
        series_name: firstTitle,
        issue_number: '1',
        series_group_id: `first-${suffix}`,
        adoption_class: 'existing',
        adoption_decision: 'included_existing',
        adopted: true,
        resolved_issue_id: firstIssueId,
        resolution_status: 'resolved_exact',
      },
      {
        cbl_position: 1,
        cbl_entry_id: 2,
        series_name: removedTitle,
        issue_number: '1',
        series_group_id: `removed-${suffix}`,
        adoption_class: 'existing',
        adoption_decision: 'included_existing',
        adopted: true,
        resolved_issue_id: removedIssueId,
        resolution_status: 'resolved_exact',
      },
    ]
    await page.route('**/api/v1/issue-identity/cbl-sources*', (route) =>
      route.fulfill({
        json: [
          {
            id: 9001,
            name: 'Replace Review Source',
            source_path: `review-${suffix}.cbl`,
            source_repository: 'shared/cbls',
            declared_issue_count: 2,
            content_hash: 'review-hash',
            revision_sha: 'review-revision',
          },
        ],
      }),
    )
    await page.route('**/api/v1/issue-identity/cbl/9001/adoption-preview', (route) =>
      route.fulfill({
        json: {
          source: {
            source_list_id: 9001,
            source_repository: 'shared/cbls',
            source_path: `review-${suffix}.cbl`,
            content_hash: 'review-hash',
            revision_sha: 'review-revision',
          },
          total_positions: entries.length,
          entries,
          summary: {
            reused_existing_count: 2,
            missing_would_create_count: 0,
            excluded_count: 0,
            unresolved_count: 0,
            awaiting_opt_in_count: 0,
            final_adopted_count: 2,
            final_adopted_order: [0, 1],
            reused_existing_positions: [0, 1],
            missing_would_create_positions: [],
            excluded_positions: [],
            unresolved_positions: [],
            awaiting_opt_in_positions: [],
          },
        },
      }),
    )

    await builder.getByRole('button', { name: 'Replace using CBL' }).click()
    await page.getByLabel('Search global CBL sources').fill('Replace Review')
    await page.getByRole('button', { name: 'Find CBLs' }).click()
    await page.getByRole('button', { name: /Replace Review Source/ }).click()

    const review = page.getByTestId('cbl-replace-review')
    await expect(review).toBeVisible()
    await expect(review.getByTestId(`before-${firstIssueId}`)).toContainText(`${firstIssueId}`)
    await expect(review.getByTestId(`after-${removedIssueId}`)).toContainText(`${removedIssueId}`)
    await expect(review.getByTestId(`manual-${manualIssueId}`)).toBeVisible()
    await expect(review.getByTestId(`saved-${firstIssueId}`)).toBeVisible()
    await expect(review.getByTestId('cbl-replace-graph-impact')).toContainText('Waits-on links')

    await review.getByTestId(`toggle-${removedIssueId}`).uncheck()
    await review.getByRole('button', { name: 'Confirm replacement of this list' }).click()

    const ordered = builder.getByRole('list', { name: 'Custom CBL ordered issues' })
    await expect(ordered).toContainText(firstTitle)
    await expect(ordered).toContainText(manualTitle)
    await expect(ordered).not.toContainText(removedTitle)

    await builder.getByRole('button', { name: 'Undo last replacement' }).click()
    await expect(ordered).toContainText(removedTitle)
    await expect(builder.getByRole('status')).toContainText('Read history and ratings were not changed')
  })

  test('replaces one of two identically named Reading Lists without changing the other', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const suffix = Date.now()
    const firstTitle = `Same Name First ${suffix}`
    const secondTitle = `Same Name Second ${suffix}`
    const replacementTitle = `Same Name Replacement ${suffix}`
    const first = await createThread(page, {
      title: firstTitle,
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const second = await createThread(page, {
      title: secondTitle,
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const replacement = await createThread(page, {
      title: replacementTitle,
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const firstIssueId = await getFirstIssueId(page, first.id)
    const secondIssueId = await getFirstIssueId(page, second.id)
    const replacementIssueId = await getFirstIssueId(page, replacement.id)

    const planId = await createReadingPlan(page, `Same Name Plan ${suffix}`)
    const sharedName = `Same Name List ${suffix}`
    const firstListId = await createReadingList(
      page,
      sharedName,
      'first owned list',
      [firstIssueId],
    )
    const secondListId = await createReadingList(
      page,
      sharedName,
      'second owned list',
      [secondIssueId],
    )
    expect(firstListId).not.toBe(secondListId)

    await page.route('**/api/v1/issue-identity/cbl-sources*', (route) =>
      route.fulfill({
        json: [
          {
            id: 9101,
            name: 'Same Name Source',
            source_path: `same-name-${suffix}.cbl`,
            source_repository: 'shared/cbls',
            declared_issue_count: 1,
            content_hash: 'same-name-hash',
            revision_sha: 'same-name-revision',
          },
        ],
      }),
    )
    await page.route('**/api/v1/issue-identity/cbl/9101/adoption-preview', (route) =>
      route.fulfill({
        json: previewBody(9101, [
          {
            cbl_position: 0,
            cbl_entry_id: 1,
            series_name: replacementTitle,
            issue_number: '1',
            series_group_id: `same-name-replacement-${suffix}`,
            adoption_class: 'existing',
            adoption_decision: 'included_existing',
            adopted: true,
            resolved_issue_id: replacementIssueId,
            resolution_status: 'resolved_exact',
          },
        ]),
      }),
    )

    const builder = page.locator('section[aria-labelledby="custom-cbl-heading"]')
    await builder.getByRole('button', { name: 'Create or edit custom CBL' }).click()
    const select = page.getByLabel('Custom CBL', { exact: true })
    await expect(select).toBeVisible()
    await select.selectOption(String(firstListId))

    await builder.getByRole('button', { name: 'Replace using CBL' }).click()
    await page.getByLabel('Search global CBL sources').fill('Same Name')
    await page.getByRole('button', { name: 'Find CBLs' }).click()
    await page.getByRole('button', { name: /Same Name Source/ }).click()
    // The saved entry stays checked as a manual addition by default. Replace
    // this list's membership with only the CBL source, exactly as reviewed.
    await page.getByTestId(`toggle-${firstIssueId}`).uncheck()
    await page.getByTestId('confirm-replace').click()
    await expect(builder.getByRole('status')).toContainText('Replaced this Reading List')

    const replacedFirst = await getReadingList(page, firstListId)
    const untouchedSecond = await getReadingList(page, secondListId)
    expect(replacedFirst.entries.map((entry) => entry.issue_id)).toEqual([replacementIssueId])
    expect(untouchedSecond.entries.map((entry) => entry.issue_id)).toEqual([secondIssueId])
    expect(untouchedSecond.name).toBe(sharedName)
    expect(planId).toBeGreaterThan(0)
  })

  test('cancel and stale confirmation leave the owned list untouched', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const suffix = Date.now()
    const firstTitle = `Stale First ${suffix}`
    const secondTitle = `Stale Second ${suffix}`
    const first = await createThread(page, {
      title: firstTitle,
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const second = await createThread(page, {
      title: secondTitle,
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const firstIssueId = await getFirstIssueId(page, first.id)
    const secondIssueId = await getFirstIssueId(page, second.id)

    await createReadingPlan(page, `Stale Plan ${suffix}`)
    const listId = await createReadingList(
      page,
      `Stale List ${suffix}`,
      'cancel and stale target',
      [firstIssueId, secondIssueId],
    )

    await page.route('**/api/v1/issue-identity/cbl-sources*', (route) =>
      route.fulfill({
        json: [
          {
            id: 9201,
            name: 'Stale Source',
            source_path: `stale-${suffix}.cbl`,
            source_repository: 'shared/cbls',
            declared_issue_count: 1,
            content_hash: 'stale-hash',
            revision_sha: 'stale-revision',
          },
        ],
      }),
    )
    await page.route('**/api/v1/issue-identity/cbl/9201/adoption-preview', (route) =>
      route.fulfill({
        json: previewBody(9201, [
          {
            cbl_position: 0,
            cbl_entry_id: 1,
            series_name: firstTitle,
            issue_number: '1',
            series_group_id: `stale-first-${suffix}`,
            adoption_class: 'existing',
            adoption_decision: 'included_existing',
            adopted: true,
            resolved_issue_id: firstIssueId,
            resolution_status: 'resolved_exact',
          },
        ]),
      }),
    )

    const builder = page.locator('section[aria-labelledby="custom-cbl-heading"]')
    await builder.getByRole('button', { name: 'Create or edit custom CBL' }).click()
    await page.getByLabel('Custom CBL', { exact: true }).selectOption(String(listId))

    await builder.getByRole('button', { name: 'Replace using CBL' }).click()
    await page.getByLabel('Search global CBL sources').fill('Stale')
    await page.getByRole('button', { name: 'Find CBLs' }).click()
    await page.getByRole('button', { name: /Stale Source/ }).click()
    await page.getByTestId('cancel-replace').click()
    await expect(page.getByTestId('cbl-replace-review')).not.toBeVisible()
    expect((await getReadingList(page, listId)).entries.map((entry) => entry.issue_id)).toEqual([
      firstIssueId,
      secondIssueId,
    ])

    // Another save changes the list version while the review is open.
    const headers = await authHeaders(page)
    const changeRequest = {
      name: `Stale List ${suffix}`,
      description: 'cancel and stale target',
      mode: 'strict',
      issue_ids: [firstIssueId],
      entry_intents: { [firstIssueId]: { gate: 'none', skipped: false } },
      checkpoint_issue_ids: [],
    }
    const previewChange = await page.request.put(`/api/v1/custom-cbls/${listId}`, {
      headers, data: changeRequest,
    })
    expect(previewChange.status(), await previewChange.text()).toBe(409)
    // SAFETY: the server's named predecessor changes are reviewed before resubmission.
    const confirmation = await previewChange.json() as {
      detail: { code: string; predecessor_changes: ReadingListPredecessorChange[] }
    }
    expect(confirmation.detail.code).toBe('reading_list_predecessor_confirmation_required')
    expect(confirmation.detail.predecessor_changes).toHaveLength(1)
    expect(confirmation.detail.predecessor_changes[0]).toMatchObject({
      issue_id: secondIssueId, before_issue_ids: [firstIssueId], after_issue_ids: [],
    })
    const changed = await page.request.put(`/api/v1/custom-cbls/${listId}`, {
      headers,
      data: { ...changeRequest, confirmed_predecessor_changes: confirmation.detail.predecessor_changes },
    })
    expect(changed.ok(), await changed.text()).toBeTruthy()

    await builder.getByRole('button', { name: 'Replace using CBL' }).click()
    await page.getByLabel('Search global CBL sources').fill('Stale')
    await page.getByRole('button', { name: 'Find CBLs' }).click()
    await page.getByRole('button', { name: /Stale Source/ }).click()
    await page.getByTestId('confirm-replace').click()

    await expect(builder.getByRole('alert')).toContainText('changed after you reviewed it')
    expect((await getReadingList(page, listId)).entries.map((entry) => entry.issue_id)).toEqual([
      firstIssueId,
    ])
  })

  test('Undo restores list membership without erasing a saved rating', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const suffix = Date.now()
    const ratedTitle = `Rated Keep ${suffix}`
    const manualTitle = `Rated Manual ${suffix}`
    const rated = await createThread(page, {
      title: ratedTitle,
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const manual = await createThread(page, {
      title: manualTitle,
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const ratedIssueId = await getFirstIssueId(page, rated.id)
    const manualIssueId = await getFirstIssueId(page, manual.id)
    const headers = await authHeaders(page)

    const pending = await page.request.post(`/api/threads/${rated.id}/set-pending`, { headers })
    expect(pending.ok(), await pending.text()).toBeTruthy()
    const rating = await page.request.post('/api/v1/rate/', {
      headers,
      data: { rating: 4.5, finish_session: false, issue_number: '1' },
    })
    expect(rating.ok(), await rating.text()).toBeTruthy()
    const threadAfterRating = await page.request.get(`/api/v1/threads/${rated.id}`, { headers })
    expect(threadAfterRating.ok(), await threadAfterRating.text()).toBeTruthy()
    // SAFETY: the test reads only last_rating from the thread detail
    expect(((await threadAfterRating.json()) as { last_rating: number | null }).last_rating).toBe(4.5)

    await createReadingPlan(page, `Rated Plan ${suffix}`)
    const listId = await createReadingList(
      page,
      `Rated List ${suffix}`,
      'undo keeps rating',
      [ratedIssueId, manualIssueId],
      'loose',
    )

    await page.route('**/api/v1/issue-identity/cbl-sources*', (route) =>
      route.fulfill({
        json: [
          {
            id: 9301,
            name: 'Rated Source',
            source_path: `rated-${suffix}.cbl`,
            source_repository: 'shared/cbls',
            declared_issue_count: 1,
            content_hash: 'rated-hash',
            revision_sha: 'rated-revision',
          },
        ],
      }),
    )
    await page.route('**/api/v1/issue-identity/cbl/9301/adoption-preview', (route) =>
      route.fulfill({
        json: previewBody(9301, [
          {
            cbl_position: 0,
            cbl_entry_id: 1,
            series_name: ratedTitle,
            issue_number: '1',
            series_group_id: `rated-keep-${suffix}`,
            adoption_class: 'existing',
            adoption_decision: 'included_existing',
            adopted: true,
            resolved_issue_id: ratedIssueId,
            resolution_status: 'resolved_exact',
          },
        ]),
      }),
    )

    const builder = page.locator('section[aria-labelledby="custom-cbl-heading"]')
    await builder.getByRole('button', { name: 'Create or edit custom CBL' }).click()
    await page.getByLabel('Custom CBL', { exact: true }).selectOption(String(listId))

    await builder.getByRole('button', { name: 'Replace using CBL' }).click()
    await page.getByLabel('Search global CBL sources').fill('Rated')
    await page.getByRole('button', { name: 'Find CBLs' }).click()
    await page.getByRole('button', { name: /Rated Source/ }).click()
    await page.getByTestId(`toggle-${manualIssueId}`).uncheck()
    await page.getByTestId('confirm-replace').click()
    await expect(
      builder.getByRole('list', { name: 'Custom CBL ordered issues' }),
    ).not.toContainText(manualTitle)

    await builder.getByRole('button', { name: 'Undo last replacement' }).click()
    await expect(builder.getByRole('status')).toContainText('Read history and ratings were not changed')
    await expect(
      builder.getByRole('list', { name: 'Custom CBL ordered issues' }),
    ).toContainText(manualTitle)

    const threadAfterUndo = await page.request.get(`/api/v1/threads/${rated.id}`, { headers })
    expect(threadAfterUndo.ok(), await threadAfterUndo.text()).toBeTruthy()
    // SAFETY: the test reads only last_rating from the thread detail
    expect(((await threadAfterUndo.json()) as { last_rating: number | null }).last_rating).toBe(4.5)
  })

  test('replacement graph impact agrees with Roll blocking after the list is applied', async ({
    authenticatedPage, allowExpectedBrowserFailures,
  }) => {
    const page = authenticatedPage
    const suffix = Date.now()
    const firstTitle = `Overlap First ${suffix}`
    const secondTitle = `Overlap Second ${suffix}`
    const first = await createThread(page, {
      title: firstTitle,
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const second = await createThread(page, {
      title: secondTitle,
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const firstIssueId = await getFirstIssueId(page, first.id)
    const secondIssueId = await getFirstIssueId(page, second.id)

    const planId = await createReadingPlan(page, `Overlap Plan ${suffix}`)
    const listId = await createReadingList(
      page,
      `Overlap List ${suffix}`,
      'graph and roll agreement',
      [firstIssueId, secondIssueId],
      'strict',
    )
    await applyReadingList(page, listId, planId)
    expect(await isThreadBlocked(page, second.id)).toBe(true)

    await page.route('**/api/v1/issue-identity/cbl-sources*', (route) =>
      route.fulfill({
        json: [
          {
            id: 9401,
            name: 'Overlap Source',
            source_path: `overlap-${suffix}.cbl`,
            source_repository: 'shared/cbls',
            declared_issue_count: 2,
            content_hash: 'overlap-hash',
            revision_sha: 'overlap-revision',
          },
        ],
      }),
    )
    await page.route('**/api/v1/issue-identity/cbl/9401/adoption-preview', (route) =>
      route.fulfill({
        json: previewBody(9401, [
          {
            cbl_position: 0,
            cbl_entry_id: 1,
            series_name: secondTitle,
            issue_number: '1',
            series_group_id: `overlap-second-${suffix}`,
            adoption_class: 'existing',
            adoption_decision: 'included_existing',
            adopted: true,
            resolved_issue_id: secondIssueId,
            resolution_status: 'resolved_exact',
          },
          {
            cbl_position: 1,
            cbl_entry_id: 2,
            series_name: firstTitle,
            issue_number: '1',
            series_group_id: `overlap-first-${suffix}`,
            adoption_class: 'existing',
            adoption_decision: 'included_existing',
            adopted: true,
            resolved_issue_id: firstIssueId,
            resolution_status: 'resolved_exact',
          },
        ]),
      }),
    )

    const builder = page.locator('section[aria-labelledby="custom-cbl-heading"]')
    await builder.getByRole('button', { name: 'Create or edit custom CBL' }).click()
    await page.getByLabel('Custom CBL', { exact: true }).selectOption(String(listId))

    await builder.getByRole('button', { name: 'Replace using CBL' }).click()
    await page.getByLabel('Search global CBL sources').fill('Overlap')
    await page.getByRole('button', { name: 'Find CBLs' }).click()
    await page.getByRole('button', { name: /Overlap Source/ }).click()

    const impact = page.getByTestId('cbl-replace-graph-impact')
    await expect(impact).toContainText('1 gain a wait')
    await expect(impact).toContainText('1 lose every wait')
    // The two explicit confirmation dialogs intentionally originate from 409 responses.
    allowExpectedBrowserFailures.allow(
      { category: 'console', message: 'status of 409 (Conflict)' },
      { category: 'console', message: 'API Error: AxiosError: Request failed with status code 409' },
    )
    await page.getByTestId('confirm-replace').click()

    // Reversing a strict list re-changes stored waits, so the server demands
    // the same confirmation the preview warned about before it writes anything.
    const confirmDialog = page.getByRole('dialog', {
      name: 'Confirm replacement waiting changes',
    })
    await expect(confirmDialog).toBeVisible()
    await confirmDialog.getByRole('button', { name: 'Confirm and replace' }).click()
    await expect(builder.getByRole('status')).toContainText('Replaced this Reading List')

    await builder.getByRole('button', { name: 'Apply to this Reading Plan' }).click()
    await expect(builder.getByRole('status')).toContainText('Applied to Reading Plan')

    expect(await isThreadBlocked(page, first.id)).toBe(true)
    expect(await isThreadBlocked(page, second.id)).toBe(false)

    // Undoing a confirmed strict reorder re-changes the same stored waits, so
    // it must ask for the same explicit confirmation instead of failing.
    await builder.getByRole('button', { name: 'Undo last replacement' }).click()
    const undoDialog = page.getByRole('dialog', { name: 'Confirm undo waiting changes' })
    await expect(undoDialog).toBeVisible()
    await undoDialog.getByRole('button', { name: 'Confirm and restore' }).click()
    await expect(builder.getByRole('status')).toContainText(
      'Read history and ratings were not changed',
    )
    const restored = await getReadingList(page, listId)
    expect(restored.entries.map((entry) => entry.issue_id)).toEqual([firstIssueId, secondIssueId])
  })
})
