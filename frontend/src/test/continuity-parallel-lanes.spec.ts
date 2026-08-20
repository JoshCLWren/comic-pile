import { test, expect } from './fixtures'
import type { Page } from '@playwright/test'
import { createThread, getAuthToken } from './helpers'

async function getCsrf(page: Page, token: string | null): Promise<string> {
  const response = await page.request.get('/api/auth/csrf', {
    headers: { ...(token ? { 'Authorization': `Bearer ${token}` } : {}) },
  })
  expect(response.ok()).toBeTruthy()
  const data = await response.json() as { csrf_token?: string }
  expect(data.csrf_token).toBeDefined()
  return data.csrf_token!
}

async function getFirstIssueId(page: Page, token: string | null, threadId: number): Promise<number> {
  const response = await page.request.get(`/api/v1/threads/${threadId}/issues`, {
    headers: { ...(token ? { 'Authorization': `Bearer ${token}` } : {}) },
  })
  expect(response.ok(), `issue list failed: ${await response.text()}`).toBeTruthy()
  const data = await response.json() as { issues: Array<{ id: number }> }
  expect(data.issues.length).toBeGreaterThan(0)
  return data.issues[0].id
}

async function createParallelPlan(
  page: Page,
  token: string | null,
  csrf: string,
  name: string,
  lanes: Array<{ id: string; name: string; order: number }>,
  nodes: Array<{ id: string; node_type: 'issue' | 'crossover' | 'thread'; ref_id: number; lane_id: string; position: number }>,
): Promise<number> {
  const response = await page.request.post('/api/v1/continuity-plans/', {
    headers: {
      ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrf,
    },
    data: { name, ordering_mode: 'informational', lanes, nodes },
  })
  expect(response.ok(), `plan create failed: ${await response.text()}`).toBeTruthy()
  const plan = await response.json() as { id: number }
  return plan.id
}

test.describe('Continuity plan parallel lanes', () => {
  test('renders parallel lanes and keeps a newly added lane after reload', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const token = await getAuthToken(page)
    const csrf = await getCsrf(page, token)

    const thread = await createThread(page, { title: 'Parallel Alpha', format: 'Comics', issues_remaining: 2, total_issues: 2 })
    const issueA = await getFirstIssueId(page, token, thread.id)
    const issueB = (await page.request.get(`/api/v1/threads/${thread.id}/issues`, {
      headers: { ...(token ? { 'Authorization': `Bearer ${token}` } : {}) },
    }).then((r) => r.json()) as { issues: Array<{ id: number }> }).issues[1].id

    const planId = await createParallelPlan(
      page,
      token,
      csrf,
      'Two-lane plan',
      [
        { id: 'main', name: 'Reading order', order: 0 },
        { id: 'lane-2', name: 'Lane 2', order: 1 },
      ],
      [
        { id: 'a', node_type: 'issue', ref_id: issueA, lane_id: 'main', position: 0 },
        { id: 'b', node_type: 'issue', ref_id: issueB, lane_id: 'lane-2', position: 0 },
      ],
    )

    await page.goto(`/continuity-plans/${planId}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByTestId('lane-main')).toBeVisible()
    await expect(page.getByTestId('lane-lane-2')).toBeVisible()

    // Add a third lane and persist it.
    await page.getByRole('button', { name: 'Add lane' }).click()
    await expect(page.getByRole('button', { name: 'Remove lane Lane 3' })).toBeVisible()

    await page.getByRole('button', { name: 'Save plan' }).click()
    await expect(page.getByRole('status', { name: 'Saved' })).toBeVisible()

    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByTestId('lane-main')).toBeVisible()
    await expect(page.getByTestId('lane-lane-2')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Remove lane Lane 3' })).toBeVisible()
  })

  test('moves a node between lanes and persists the move across reload', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const token = await getAuthToken(page)
    const csrf = await getCsrf(page, token)

    const thread = await createThread(page, { title: 'Parallel Beta', format: 'Comics', issues_remaining: 2, total_issues: 2 })
    const issues = (await page.request.get(`/api/v1/threads/${thread.id}/issues`, {
      headers: { ...(token ? { 'Authorization': `Bearer ${token}` } : {}) },
    }).then((r) => r.json()) as { issues: Array<{ id: number }> }).issues
    const issueA = issues[0].id
    const issueB = issues[1].id

    const planId = await createParallelPlan(
      page,
      token,
      csrf,
      'Move-lane plan',
      [
        { id: 'main', name: 'Reading order', order: 0 },
        { id: 'lane-2', name: 'Lane 2', order: 1 },
      ],
      [
        { id: 'a', node_type: 'issue', ref_id: issueA, lane_id: 'main', position: 0 },
        { id: 'b', node_type: 'issue', ref_id: issueB, lane_id: 'main', position: 1 },
      ],
    )

    await page.goto(`/continuity-plans/${planId}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByTestId('lane-main')).toBeVisible()

    // Move the first step into the second lane via its lane switcher.
    const moveSelect = page.getByRole('combobox', { name: /Move Parallel Beta #1 to another lane/i })
    await moveSelect.selectOption('lane-2')

    await page.getByRole('button', { name: 'Save plan' }).click()
    await expect(page.getByRole('status', { name: 'Saved' })).toBeVisible()

    await page.reload({ waitUntil: 'domcontentloaded' })
    const laneTwo = page.getByTestId('lane-lane-2')
    await expect(laneTwo).toBeVisible()
    await expect(laneTwo.getByText('Parallel Beta #1')).toBeVisible()
    await expect(page.getByTestId('lane-main').getByText('Parallel Beta #2')).toBeVisible()
  })
})
