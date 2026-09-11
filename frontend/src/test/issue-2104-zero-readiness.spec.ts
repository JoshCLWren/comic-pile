/**
 * Issue #2104: normal Roll, crossover detail, and Reading Plan use must not
 * request the deleted readiness product surface.
 *
 * A 404 from those paths is not acceptable proof. The request must not occur.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, getAuthToken, gotoRollPage, waitForRollPageReady } from './helpers'

const REMOVED_PATH_PATTERN =
  /\/(?:api\/)?v1\/continuity\/(?:readiness|chains)(?:\?|$)|\/(?:api\/)?v1\/continuity-plans\/[^/]+\/readiness(?:\?|$)/

async function getCsrf(page: Page, token: string | null): Promise<string> {
  const headers: Record<string, string> = {}
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  const response = await page.request.get('/api/auth/csrf', { headers })
  expect(response.ok()).toBeTruthy()
  const data = (await response.json()) as { csrf_token?: string }
  expect(data.csrf_token).toBeDefined()
  return data.csrf_token!
}

async function getIssueIds(page: Page, token: string | null, threadId: number): Promise<number[]> {
  const headers: Record<string, string> = {}
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  const response = await page.request.get(`/api/v1/threads/${threadId}/issues`, { headers })
  expect(response.ok(), `issue list failed: ${await response.text()}`).toBeTruthy()
  const data = (await response.json()) as { issues: Array<{ id: number }> }
  expect(data.issues.length).toBeGreaterThan(0)
  return data.issues.map((issue) => issue.id)
}

function attachReadinessProbe(page: Page): string[] {
  const hits: string[] = []
  page.on('request', (request) => {
    const url = request.url()
    if (REMOVED_PATH_PATTERN.test(url)) {
      hits.push(url)
    }
  })
  return hits
}

test.describe('Issue #2104 zero readiness network requests', () => {
  test('Roll, crossover detail, and planner never request deleted readiness paths', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const hits = attachReadinessProbe(page)
    const token = await getAuthToken(page)
    const csrf = await getCsrf(page, token)
    const headers = {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrf,
    }

    const thread = await createThread(page, {
      title: 'Zero Readiness Series',
      format: 'Comic',
      issues_remaining: 2,
      total_issues: 2,
    })
    const issueIds = await getIssueIds(page, token, thread.id)

    const groupResponse = await page.request.post('/api/v1/reading-order-groups/', {
      headers,
      data: { name: 'Zero Readiness Crossover' },
    })
    expect(groupResponse.ok(), await groupResponse.text()).toBeTruthy()
    const group = (await groupResponse.json()) as { id: number }

    const memberResponse = await page.request.post(
      `/api/v1/reading-order-groups/${group.id}/members`,
      { headers, data: { issue_id: issueIds[0] } },
    )
    expect(memberResponse.ok(), await memberResponse.text()).toBeTruthy()

    const planResponse = await page.request.post('/api/v1/continuity-plans/', {
      headers,
      data: {
        name: 'Zero Readiness Plan',
        ordering_mode: 'informational',
        lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
        nodes: [
          {
            id: `issue-${issueIds[0]}`,
            node_type: 'issue',
            ref_id: issueIds[0],
            lane_id: 'main',
            position: 0,
            label: 'Zero Readiness Series #1',
          },
        ],
      },
    })
    expect(planResponse.ok(), await planResponse.text()).toBeTruthy()
    const plan = (await planResponse.json()) as { id: number }

    await gotoRollPage(page)
    await waitForRollPageReady(page)
    await page.locator('#main-die-3d').click()
    await expect(page.locator('[data-roll-pool]')).toBeVisible({ timeout: 15000 })
    await page.getByText('Zero Readiness Series').first().click()
    await expect(page.locator('#rating-input')).toBeVisible({ timeout: 15000 })

    await page.goto(`/crossovers/${group.id}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Reading Order' })).toBeVisible()
    await expect(page.getByText('Zero Readiness Crossover')).toBeVisible()
    await expect(page.getByText('Zero Readiness Series')).toBeVisible()

    await page.goto(`/continuity-plans/${plan.id}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByLabel('Plan name')).toHaveValue('Zero Readiness Plan')
    await expect(page.getByText('Zero Readiness Series #1')).toBeVisible()

    expect(hits, `deleted readiness paths were requested: ${hits.join(', ')}`).toEqual([])
  })
})
