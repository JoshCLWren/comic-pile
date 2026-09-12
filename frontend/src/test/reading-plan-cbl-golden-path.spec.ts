import { test, expect } from './fixtures'
import type { Page } from '@playwright/test'
import { createThread, getAuthToken } from './helpers'

async function getCsrf(page: Page, token: string | null): Promise<string> {
  const headers: Record<string, string> = {}
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  const response = await page.request.get('/api/auth/csrf', { headers })
  expect(response.ok()).toBeTruthy()
  const data = await response.json() as { csrf_token?: string }
  expect(data.csrf_token).toBeDefined()
  return data.csrf_token!
}

async function authHeaders(page: Page): Promise<Record<string, string>> {
  const token = await getAuthToken(page)
  const csrf = await getCsrf(page, token)
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrf,
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  return headers
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

test.describe('Reading Plan CBL golden path', () => {
  test('index → create plan → CBL discovery → series/override → commit → canonical result', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const headers = await authHeaders(page)

    const owned = await createThread(page, {
      title: 'Golden Path Owned Series',
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const ownedIssueId = await getFirstIssueId(page, owned.id)
    const fixtureSuffix = `${owned.id}-${Date.now()}`
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
            series_name: 'Golden Path Owned Series',
            issue_number: '1',
            issue_id: ownedIssueId,
          },
          {
            position: 2,
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
    await page.getByRole('button', { name: 'Save plan' }).click()
    await expect(page).toHaveURL(/\/continuity-plans\/\d+/)

    await page.getByRole('button', { name: 'Add from CBL' }).click()
    await page.getByLabel('Search source lists').fill(sourceName)
    await page.getByRole('button', { name: 'Search' }).click()
    await page.getByRole('button', { name: new RegExp(sourceName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }).click()

    await expect(page.getByText('Already in ComicPile')).toBeVisible()
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
    ).toContainText(/created 1 · reused 1/i)

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
      nodes: Array<{
        ref_id: number
        source_cbl_placements?: Array<{ source_path: string }>
      }>
    }
    expect(plan.nodes.length).toBe(2)
    expect(plan.nodes[0]?.ref_id).toBe(ownedIssueId)
    expect(
      plan.nodes.flatMap((node) =>
        (node.source_cbl_placements ?? []).map((placement) => placement.source_path),
      ),
    ).toEqual([sourcePath, sourcePath])
  })
})
