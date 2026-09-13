import { test, expect } from './fixtures'
import type { Page } from '@playwright/test'
import { createThread, getAuthToken } from './helpers'

type EligibilityExpectation = {
  eligible: boolean
}

async function getCsrf(page: Page, token: string | null): Promise<string> {
  const response = await page.request.get('/api/auth/csrf', {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
  expect(response.ok()).toBeTruthy()
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
  const response = await page.request.get(`/api/v1/threads/${threadId}/issues`, {
    headers,
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  const data = await response.json() as { issues: Array<{ id: number }> }
  expect(data.issues.length).toBeGreaterThan(0)
  return data.issues[0].id
}

async function assertRollEligibility(
  page: Page,
  threadId: number,
  expectation: EligibilityExpectation,
): Promise<void> {
  const headers = await authHeaders(page)
  const response = await page.request.post(
    `/api/v1/threads/${threadId}:getBlockingInfo`,
    { headers },
  )
  expect(response.ok(), await response.text()).toBeTruthy()
  const payload = await response.json() as { is_blocked: boolean }
  expect(payload.is_blocked).toBe(!expectation.eligible)

  const bootstrap = await page.request.get('/api/v1/roll/bootstrap', { headers })
  expect(bootstrap.ok(), await bootstrap.text()).toBeTruthy()
  const roll = await bootstrap.json() as {
    roll_pool: Array<{ id: number }>
    blocked_threads: Array<{ id: number }>
  }
  const inPool = roll.roll_pool.some((thread) => thread.id === threadId)
  const inBlocked = roll.blocked_threads.some((thread) => thread.id === threadId)
  expect(inPool).toBe(expectation.eligible)
  if (!expectation.eligible) {
    expect(inBlocked || payload.is_blocked).toBe(true)
  }
}

test.describe('Reading Plan CBL golden path', () => {
  test('index → create strict plan → CBL → commit → Roll eligibility', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const headers = await authHeaders(page)

    const earlier = await createThread(page, {
      title: 'Golden Path Earlier Series',
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const later = await createThread(page, {
      title: 'Golden Path Later Series',
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const earlierIssueId = await getFirstIssueId(page, earlier.id)
    const laterIssueId = await getFirstIssueId(page, later.id)
    const fixtureSuffix = `${earlier.id}-${Date.now()}`
    const sourceName = `Golden Path Browser Source ${fixtureSuffix}`
    const sourcePath = `Fixtures/Golden Path Browser ${fixtureSuffix}.cbl`

    const seed = await page.request.post('/api/test/cbl-source', {
      headers,
      data: {
        name: sourceName,
        source_path: sourcePath,
        content_hash: `browser-${fixtureSuffix}`,
        revision_sha: `browser-revision-${fixtureSuffix}`,
        repository: `JoshCLWren/CBL-ReadingLists-fixture-${fixtureSuffix}`,
        entries: [
          {
            position: 1,
            series_name: 'Golden Path Earlier Series',
            issue_number: '1',
            issue_id: earlierIssueId,
          },
          {
            position: 2,
            series_name: 'Golden Path Later Series',
            issue_number: '1',
            issue_id: laterIssueId,
          },
          {
            position: 3,
            series_name: 'Golden Path Missing Series',
            issue_number: '1',
            volume_year: 2002,
            comicvine_issue_id: `4000-browser-missing-${fixtureSuffix}`,
          },
        ],
      },
    })
    expect(seed.ok(), await seed.text()).toBeTruthy()

    await page.goto('/continuity-plans', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Reading Plans' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'New Reading Plan' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Add from CBL' })).toBeVisible()

    await page.getByRole('button', { name: 'New Reading Plan' }).click()
    await expect(page.getByRole('heading', { name: 'New Reading Plan' })).toBeVisible()

    await page.getByLabel('Plan name').fill(`Golden Path Browser Plan ${fixtureSuffix}`)
    await page.getByRole('radio', { name: /Strict sequential/i }).check()
    await page.getByRole('button', { name: 'Save plan' }).click()
    await expect(page).toHaveURL(/\/continuity-plans\/\d+/)

    await page.getByRole('button', { name: 'Add from CBL' }).click()
    await page.getByLabel('Search source lists').fill(sourceName)
    await page.getByRole('button', { name: 'Search' }).click()
    await page.getByRole('button', { name: new RegExp(sourceName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }).click()

    await expect(page.getByText('Already in ComicPile')).toHaveCount(2)
    await expect(page.getByText(/Missing · choose whether to add/i)).toBeVisible()

    const missingSeriesChoice = page.getByRole('group', {
      name: 'Golden Path Missing Series series choice',
    })
    await missingSeriesChoice.getByRole('button', { name: 'Include' }).click()
    await expect(page.getByText('Missing · selected to add')).toBeVisible()

    const missingRow = page.locator('li').filter({
      hasText: 'Golden Path Missing Series #1',
    })
    await expect(missingRow.getByRole('checkbox', { name: 'Include' })).toBeChecked()
    await missingRow.getByRole('checkbox', { name: 'Include' }).click()
    await expect(page.getByText('Excluded')).toBeVisible()
    await expect(missingRow.getByRole('checkbox', { name: 'Include' })).not.toBeChecked()
    await missingRow.getByRole('checkbox', { name: 'Include' }).click()
    await expect(page.getByText('Missing · selected to add')).toBeVisible()
    await expect(missingRow.getByRole('checkbox', { name: 'Include' })).toBeChecked()

    await expect(page.getByRole('button', { name: 'Add selected material' })).toBeEnabled()
    await page.getByRole('button', { name: 'Add selected material' }).click()
    await expect(
      page.getByRole('status').filter({ hasText: 'Added material to this Reading Plan' }),
    ).toContainText(/created 1 · reused 2/i)

    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByText('CBL-backed')).toBeVisible()
    await expect(page.getByText(sourcePath)).toBeVisible()

    const planId = Number(page.url().match(/\/continuity-plans\/(\d+)/)?.[1])
    expect(planId).toBeGreaterThan(0)
    const planResponse = await page.request.get(`/api/v1/continuity-plans/${planId}`, {
      headers,
    })
    expect(planResponse.ok(), await planResponse.text()).toBeTruthy()
    const plan = await planResponse.json() as {
      ordering_mode: string
      nodes: Array<{
        ref_id: number
        source_cbl_placements?: Array<{ source_path: string }>
      }>
    }
    expect(plan.ordering_mode).toBe('strict_sequential')
    expect(plan.nodes.length).toBe(3)
    expect(plan.nodes[0]?.ref_id).toBe(earlierIssueId)
    expect(plan.nodes[1]?.ref_id).toBe(laterIssueId)
    expect(
      plan.nodes.flatMap((node) =>
        (node.source_cbl_placements ?? []).map((placement) => placement.source_path),
      ),
    ).toEqual([sourcePath, sourcePath, sourcePath])

    await assertRollEligibility(page, later.id, { eligible: false })

    const markRead = await page.request.post(
      `/api/v1/issues/${earlierIssueId}:markRead`,
      { headers },
    )
    expect(markRead.ok(), await markRead.text()).toBeTruthy()
    await assertRollEligibility(page, later.id, { eligible: true })
  })
})
