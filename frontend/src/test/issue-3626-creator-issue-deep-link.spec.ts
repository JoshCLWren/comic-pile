/**
 * Issue #3626: creator issue links deep-link to the exact canonical issue.
 *
 * Contract exercised here (the parts only a real browser can prove):
 * 1. A creator issue link opens `/thread/<id>?issue=<issue_id>#issue-<issue_id>`
 *    and the thread page focuses, scrolls to, and highlights that canonical
 *    issue — not the top of the series and not a same-numbered issue elsewhere.
 * 2. Identically numbered comics in different series resolve to different rows.
 * 3. Reload and Back restore the same target; plain thread navigation stays
 *    unfocused and unhighlighted.
 * 4. Unknown targets fail safely without focusing an arbitrary row.
 * 5. Arrival mutates no reading state: no issue writes are issued and the
 *    issue stays unread.
 *
 * Backend seeding is real (threads/issues are created through the API); the
 * creator payload is fulfilled at the network layer exactly as the creator
 * detail page consumes it, matching the approach in
 * `issue-2030-creator-detail.spec.ts`.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { authHeaders, createThread } from './helpers'

type IssueRow = { id: number; issue_number: string; status: string }

async function listIssues(page: Page, threadId: number): Promise<IssueRow[]> {
  const headers = await authHeaders(page)
  const response = await page.request.get(`/api/v1/threads/${threadId}/issues?page_size=100`, {
    headers,
  })
  expect(response.ok()).toBeTruthy()
  // SAFETY: the test reads only the issue fields this spec asserts on.
  const data = (await response.json()) as { issues: IssueRow[] }
  return data.issues
}

async function issueByNumber(
  page: Page,
  threadId: number,
  issueNumber: string,
): Promise<IssueRow> {
  const issues = await listIssues(page, threadId)
  const issue = issues.find((candidate) => candidate.issue_number === issueNumber)
  expect(issue, `issue #${issueNumber} should exist in thread ${threadId}`).toBeTruthy()
  return issue as IssueRow
}

function deepLink(threadId: number, issueId: number): string {
  return `/thread/${threadId}?issue=${issueId}#issue-${issueId}`
}

function creatorPayload(issue: {
  issueId: number
  issueNumber: string
  threadId: number
  threadTitle: string
}) {
  return {
    summary: {
      canonical_creator_key: 'creator:1672',
      display_name: 'Mike Mignola',
      normalized_roles: ['writer', 'artist'],
      average_rating: 5,
      ratings_count: 1,
      read_unrated_count: 0,
      upcoming_count: 0,
    },
    coverage: {
      rated_issues_total: 1,
      rated_issues_with_creator_metadata: 1,
      ratings_complete: true,
      read_unrated_issues_total: 0,
      read_unrated_issues_with_creator_metadata: 0,
      read_unrated_complete: true,
      unread_issues_total: 1,
      unread_issues_with_creator_metadata: 1,
      upcoming_complete: false,
    },
    role_stats: [
      { role: 'writer', issue_count: 1, rated_issue_count: 1, average_rating: 5 },
    ],
    series_groups: [],
    series_groups_total: 0,
    series_groups_complete: true,
    rated_population_scope: 'headline_roles_only',
    headline_roles: ['writer', 'artist'],
    rated_issues: [],
    read_unrated_issues: [],
    upcoming_issues: [],
    next_cursor: null,
    rating_distribution: null,
    insights: {
      min_series_sample: 1,
      series_sample_met: false,
      series_message: 'Not enough series for a conclusion.',
      excluded_incomplete_series_count: 0,
      individual_issue_limit: 3,
      individual_issues_combined: false,
      strongest_series: null,
      weakest_series: null,
      most_rated_series: null,
      highest_rated_issues: [
        {
          issue_id: issue.issueId,
          issue_number: issue.issueNumber,
          thread_id: issue.threadId,
          thread_title: issue.threadTitle,
          effective_rating: 5,
          roles: ['writer'],
          sort_key: String(issue.issueId),
        },
      ],
      lowest_rated_issues: [],
    },
  }
}

test.describe('Issue #3626: creator issue deep links', () => {
  test('creator issue link opens, focuses, scrolls to, and highlights the exact canonical issue', async ({
    authenticatedPage: page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 720 })
    const hellboy = await createThread(page, {
      title: 'Hellboy Deep Link',
      format: 'Issue',
      issues_remaining: 120,
      total_issues: 120,
    })
    const target = await issueByNumber(page, hellboy.id, '115')

    const issueWrites: string[] = []
    page.on('request', (request) => {
      if (request.method() === 'GET') return
      if (/\/api\/v1\/issues\//.test(request.url())) {
        issueWrites.push(`${request.method()} ${request.url()}`)
      }
    })

    await page.route('**/v1/creators/*', (route) =>
      route.fulfill({
        json: creatorPayload({
          issueId: target.id,
          issueNumber: target.issue_number,
          threadId: hellboy.id,
          threadTitle: 'Hellboy Deep Link',
        }),
      }),
    )
    await page.goto('/creators/creator:1672', { waitUntil: 'domcontentloaded' })
    await page
      .getByRole('link', { name: 'Open Hellboy Deep Link #115 in its thread' })
      .click()

    await expect(page).toHaveURL(new RegExp(`/thread/${hellboy.id}\\?issue=${target.id}#issue-${target.id}$`))
    const row = page.locator(`#issue-${target.id}`)
    await expect(row).toBeVisible()
    // Focus is the accessible target: keyboard and assistive technology land on
    // the issue the link named, with a stable name.
    await expect(row).toBeFocused()
    await expect(row).toHaveAttribute('aria-label', 'Issue #115 in Hellboy Deep Link')
    // The row is scrolled into view (it lives on the second issue page) and is
    // visually identified on arrival.
    await expect(row).toBeInViewport()
    await expect(row).toHaveClass(/issue-deep-link-target/)
    await expect(row).toHaveCSS('outline-style', 'solid')

    // #3626 / #3581: arrival must not mark read, rate, or otherwise mutate the
    // issue. No issue write requests were issued and the status is unchanged.
    expect(issueWrites).toEqual([])
    const [unchanged] = await listIssues(page, hellboy.id).then((issues) =>
      issues.filter((issue) => issue.id === target.id),
    )
    expect(unchanged.status).toBe('unread')

    // The highlight is an arrival cue, not permanent drift: moving focus on
    // with the keyboard clears it.
    await row.press('Tab')
    await expect(row).not.toHaveClass(/issue-deep-link-target/)
  })

  test('identically numbered issues in different series stay distinct targets', async ({
    authenticatedPage: page,
  }) => {
    const first = await createThread(page, {
      title: 'Hellboy Alpha',
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })
    const second = await createThread(page, {
      title: 'Hellboy Beta',
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })
    const firstIssue = await issueByNumber(page, first.id, '2')
    const secondIssue = await issueByNumber(page, second.id, '2')
    expect(firstIssue.id).not.toBe(secondIssue.id)

    await page.goto(deepLink(first.id, firstIssue.id), { waitUntil: 'domcontentloaded' })
    await expect(page.locator(`#issue-${firstIssue.id}`)).toBeFocused()

    await page.goto(deepLink(second.id, secondIssue.id), { waitUntil: 'domcontentloaded' })
    const secondRow = page.locator(`#issue-${secondIssue.id}`)
    await expect(secondRow).toBeFocused()
    await expect(secondRow).toContainText('#2')
    await expect(page.locator(`#issue-${firstIssue.id}`)).toHaveCount(0)
  })

  test('reload and Back restore the issue target; plain thread navigation stays unchanged', async ({
    authenticatedPage: page,
  }) => {
    const thread = await createThread(page, {
      title: 'Hellboy History',
      format: 'Issue',
      issues_remaining: 12,
      total_issues: 12,
    })
    const target = await issueByNumber(page, thread.id, '9')

    await page.goto(deepLink(thread.id, target.id), { waitUntil: 'domcontentloaded' })
    await expect(page.locator(`#issue-${target.id}`)).toBeFocused()

    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.locator(`#issue-${target.id}`)).toBeFocused()
    await expect(page.locator(`#issue-${target.id}`)).toHaveClass(/issue-deep-link-target/)

    // Ordinary thread navigation without an issue anchor is unchanged: no row
    // is focused and none is highlighted.
    await page.goto(`/thread/${thread.id}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Hellboy History' })).toBeVisible()
    await expect(page.locator('.issue-deep-link-target')).toHaveCount(0)
    await expect(page.locator(`#issue-${target.id}`)).not.toBeFocused()

    // Back returns to the deep link and restores the same target.
    await page.goBack({ waitUntil: 'domcontentloaded' })
    await expect(page).toHaveURL(new RegExp(`/thread/${thread.id}\\?issue=${target.id}#issue-${target.id}$`))
    await expect(page.locator(`#issue-${target.id}`)).toBeFocused()
  })

  test('unknown issue targets fail safely without retargeting another row', async ({
    authenticatedPage: page,
  }) => {
    const thread = await createThread(page, {
      title: 'Hellboy Missing Target',
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })
    const issues = await listIssues(page, thread.id)
    const unknownIssueId = Math.max(...issues.map((issue) => issue.id)) + 100000

    await page.goto(deepLink(thread.id, unknownIssueId), { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Hellboy Missing Target' })).toBeVisible()
    await expect(page.locator('.issue-deep-link-target')).toHaveCount(0)
    for (const issue of issues) {
      await expect(page.locator(`#issue-${issue.id}`)).not.toBeFocused()
    }
    // The visible list is intact, so the reader can recover manually.
    await expect(page.locator(`#issue-${issues[0].id}`)).toBeVisible()
  })
})
