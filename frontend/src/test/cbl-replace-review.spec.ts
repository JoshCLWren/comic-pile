import { test, expect } from './fixtures'
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

async function createReadingPlan(page: Page, name: string): Promise<void> {
  await page.goto('/continuity-plans', { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: 'New Reading Plan' }).click()
  await expect(page.getByRole('heading', { name: 'New Reading Plan' })).toBeVisible()
  await page.getByLabel('Plan name').fill(name)
  await page.getByRole('radio', { name: /^Strict/i }).check()
  await page.getByRole('button', { name: 'Save plan' }).click()
  await expect(page).toHaveURL(/\/continuity-plans\/\d+/)
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
})
