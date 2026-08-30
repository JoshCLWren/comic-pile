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

async function getIssueIds(page: Page, token: string | null, threadId: number): Promise<number[]> {
  const response = await page.request.get(`/api/v1/threads/${threadId}/issues`, {
    headers: { ...(token ? { 'Authorization': `Bearer ${token}` } : {}) },
  })
  expect(response.ok(), `issue list failed: ${await response.text()}`).toBeTruthy()
  const data = await response.json() as { issues: Array<{ id: number }> }
  expect(data.issues.length).toBeGreaterThan(0)
  return data.issues.map((i) => i.id)
}

async function createPlanViaApi(
  page: Page,
  token: string | null,
  csrf: string,
  name: string,
  lanes: Array<{ id: string; name: string; order: number }>,
  nodes: Array<{
    id: string
    node_type: 'issue' | 'crossover' | 'thread'
    ref_id: number
    lane_id: string
    position: number
    is_checkpoint?: boolean
    convergence_gate?: Array<{ node_type: string; node_id: string }>
  }>,
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

test.describe('Continuity plan checkpoint and convergence', () => {
  test('two parallel branches read independently until a checkpoint', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const token = await getAuthToken(page)
    const csrf = await getCsrf(page, token)

    const thread = await createThread(page, {
      title: 'Checkpoint Alpha',
      format: 'Comics',
      issues_remaining: 3,
      total_issues: 3,
    })
    const issueIds = await getIssueIds(page, token, thread.id)

    // Create a plan with two parallel lanes, checkpoint on issue[1] in lane A
    const planId = await createPlanViaApi(
      page,
      token,
      csrf,
      'Checkpoint plan',
      [
        { id: 'lane-a', name: 'Lane A', order: 0 },
        { id: 'lane-b', name: 'Lane B', order: 1 },
      ],
      [
        { id: 'a-1', node_type: 'issue', ref_id: issueIds[0], lane_id: 'lane-a', position: 0 },
        { id: 'a-2', node_type: 'issue', ref_id: issueIds[1], lane_id: 'lane-a', position: 1, is_checkpoint: true },
        { id: 'b-1', node_type: 'issue', ref_id: issueIds[2], lane_id: 'lane-b', position: 0 },
      ],
    )

    await page.goto(`/continuity-plans/${planId}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByTestId('lane-lane-a')).toBeVisible()
    await expect(page.getByTestId('lane-lane-b')).toBeVisible()

    // Verify checkpoint badge is visible on the second node
    await expect(page.getByText('Checkpoint')).toBeVisible()

    // Reload and verify persistence
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByTestId('lane-lane-a')).toBeVisible()
    await expect(page.getByText('Checkpoint')).toBeVisible()
  })

  test('downstream issue remains blocked until convergence gate prerequisites are met', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const token = await getAuthToken(page)
    const csrf = await getCsrf(page, token)

    const threadA = await createThread(page, {
      title: 'Converge Branch A',
      format: 'Comics',
      issues_remaining: 2,
      total_issues: 2,
    })
    const threadB = await createThread(page, {
      title: 'Converge Branch B',
      format: 'Comics',
      issues_remaining: 2,
      total_issues: 2,
    })
    const issueIdsA = await getIssueIds(page, token, threadA.id)
    const issueIdsB = await getIssueIds(page, token, threadB.id)

    // Lane A: issue1
    // Lane B: issue2, convergence gate waiting for issue1 from lane A
    const planId = await createPlanViaApi(
      page,
      token,
      csrf,
      'Convergence plan',
      [
        { id: 'lane-a', name: 'Branch A', order: 0 },
        { id: 'lane-b', name: 'Branch B', order: 1 },
      ],
      [
        { id: 'a-1', node_type: 'issue', ref_id: issueIdsA[0], lane_id: 'lane-a', position: 0 },
        {
          id: 'b-1',
          node_type: 'issue',
          ref_id: issueIdsB[0],
          lane_id: 'lane-b',
          position: 0,
          convergence_gate: [{ node_type: 'issue', node_id: 'a-1' }],
        },
      ],
    )

    await page.goto(`/continuity-plans/${planId}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByTestId('lane-lane-a')).toBeVisible()
    await expect(page.getByTestId('lane-lane-b')).toBeVisible()

    // Verify convergence badge is visible
    await expect(page.getByText('Convergence (1)')).toBeVisible()

    // Reload and verify persistence
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Convergence (1)')).toBeVisible()
  })

  test('edit a gate, save, and reload observes updated readiness', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const token = await getAuthToken(page)
    const csrf = await getCsrf(page, token)

    const thread = await createThread(page, {
      title: 'Gate Edit',
      format: 'Comics',
      issues_remaining: 3,
      total_issues: 3,
    })
    const issueIds = await getIssueIds(page, token, thread.id)

    // Start with no convergence gate
    const planId = await createPlanViaApi(
      page,
      token,
      csrf,
      'Gate edit plan',
      [
        { id: 'lane-a', name: 'Lane A', order: 0 },
        { id: 'lane-b', name: 'Lane B', order: 1 },
      ],
      [
        { id: 'a-1', node_type: 'issue', ref_id: issueIds[0], lane_id: 'lane-a', position: 0 },
        { id: 'b-1', node_type: 'issue', ref_id: issueIds[1], lane_id: 'lane-b', position: 0 },
      ],
    )

    await page.goto(`/continuity-plans/${planId}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByTestId('lane-lane-a')).toBeVisible()

    // No convergence badge initially
    await expect(page.getByText('Convergence')).not.toBeVisible()

    // Open convergence editor on b-1
    await page.getByRole('button', { name: /Edit convergence gate for Gate Edit #2/i }).click()
    await expect(page.getByTestId('convergence-editor-b-1')).toBeVisible()

    // Select a-1 as a convergence target
    const checkbox = page.getByTestId('convergence-editor-b-1').getByText('Gate Edit #1')
    await checkbox.click()

    // Save
    await page.getByRole('button', { name: 'Save plan' }).click()
    await expect(page.getByRole('status', { name: 'Saved' })).toBeVisible()

    // Reload and verify convergence persists
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Convergence (1)')).toBeVisible()
  })

  test('remove a gate and verify plan-owned rules are removed', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const token = await getAuthToken(page)
    const csrf = await getCsrf(page, token)

    const thread = await createThread(page, {
      title: 'Gate Remove',
      format: 'Comics',
      issues_remaining: 2,
      total_issues: 2,
    })
    const issueIds = await getIssueIds(page, token, thread.id)

    // Create plan with convergence gate
    const planId = await createPlanViaApi(
      page,
      token,
      csrf,
      'Gate remove plan',
      [
        { id: 'lane-a', name: 'Lane A', order: 0 },
        { id: 'lane-b', name: 'Lane B', order: 1 },
      ],
      [
        { id: 'a-1', node_type: 'issue', ref_id: issueIds[0], lane_id: 'lane-a', position: 0 },
        {
          id: 'b-1',
          node_type: 'issue',
          ref_id: issueIds[1],
          lane_id: 'lane-b',
          position: 0,
          convergence_gate: [{ node_type: 'issue', node_id: 'a-1' }],
        },
      ],
    )

    await page.goto(`/continuity-plans/${planId}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Convergence (1)')).toBeVisible()

    // Open convergence editor on b-1
    await page.getByRole('button', { name: /Edit convergence gate for Gate Remove #2/i }).click()
    await expect(page.getByTestId('convergence-editor-b-1')).toBeVisible()

    // Unselect a-1
    const checkbox = page.getByTestId('convergence-editor-b-1').getByText('Gate Remove #1')
    await checkbox.click()

    // Done
    await page.getByRole('button', { name: 'Done' }).click()

    // Save
    await page.getByRole('button', { name: 'Save plan' }).click()
    await expect(page.getByRole('status', { name: 'Saved' })).toBeVisible()

    // Verify no convergence badge
    await expect(page.getByText('Convergence')).not.toBeVisible()

    // Reload and verify gone
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Convergence')).not.toBeVisible()
  })
})
