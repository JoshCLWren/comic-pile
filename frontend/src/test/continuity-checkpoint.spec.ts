import { test, expect } from './fixtures'
import { createThread, getAuthToken } from './helpers'
import type { Page } from '@playwright/test'

async function getCsrf(page: Page, token: string | null): Promise<string> {
  const response = await page.request.get('/api/auth/csrf', {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  })
  expect(response.ok()).toBeTruthy()
  const data = await response.json() as { csrf_token?: string }
  return data.csrf_token!
}

async function getFirstIssueId(page: Page, token: string | null, threadId: number): Promise<number> {
  const response = await page.request.get(`/api/v1/threads/${threadId}/issues`, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  })
  expect(response.ok()).toBeTruthy()
  const data = await response.json() as { issues: Array<{ id: number }> }
  return data.issues[0].id
}

async function createPlan(
  page: Page,
  token: string | null,
  csrf: string,
  payload: Record<string, unknown>,
): Promise<number> {
  const response = await page.request.post('/api/v1/continuity-plans/', {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrf,
    },
    data: payload,
  })
  expect(response.ok(), `plan create failed: ${await response.text()}`).toBeTruthy()
  const plan = await response.json() as { id: number }
  return plan.id
}

test.describe('Continuity planner checkpoint and convergence editing', () => {
  test('parallel branches read independently until configured checkpoints', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const token = await getAuthToken(page)
    const csrf = await getCsrf(page, token)

    const threadA = await createThread(page, { title: 'Branch Alpha', format: 'Comics', issues_remaining: 3, total_issues: 3 })
    const threadB = await createThread(page, { title: 'Branch Beta', format: 'Comics', issues_remaining: 3, total_issues: 3 })
    const issueA = await getFirstIssueId(page, token, threadA.id)
    const issueB = await getFirstIssueId(page, token, threadB.id)

    const planId = await createPlan(page, token, csrf, {
      name: 'Parallel checkpoints',
      ordering_mode: 'informational',
      lanes: [
        { id: 'alpha', name: 'Alpha', order: 0 },
        { id: 'beta', name: 'Beta', order: 1 },
      ],
      nodes: [
        { id: 'a1', node_type: 'issue', ref_id: issueA, lane_id: 'alpha', position: 0 },
        { id: 'a2', node_type: 'issue', ref_id: issueA + 1, lane_id: 'alpha', position: 1 },
        { id: 'a3', node_type: 'issue', ref_id: issueA + 2, lane_id: 'alpha', position: 2 },
        { id: 'b1', node_type: 'issue', ref_id: issueB, lane_id: 'beta', position: 0 },
      ],
      checkpoints: [{ node_id: 'a1' }],
      convergence_gates: [],
    })

    await page.goto(`/continuity-plans/${planId}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByTestId('plan-readiness-panel')).toBeVisible()

    const b1 = page.getByTestId('plan-node-readiness-b1')
    await expect(b1).toHaveAttribute('data-state', 'readable')
    const a3 = page.getByTestId('plan-node-readiness-a3')
    await expect(a3).toHaveAttribute('data-state', 'blocked')
    await expect(page.getByText(/Blocked by a checkpoint until/)).toBeVisible()
  })

  test('downstream step stays blocked until both branches satisfy the convergence gate', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const token = await getAuthToken(page)
    const csrf = await getCsrf(page, token)

    const threadA = await createThread(page, { title: 'Gate Alpha', format: 'Comics', issues_remaining: 2, total_issues: 2 })
    const threadB = await createThread(page, { title: 'Gate Beta', format: 'Comics', issues_remaining: 2, total_issues: 2 })
    const issueA = await getFirstIssueId(page, token, threadA.id)
    const issueB = await getFirstIssueId(page, token, threadB.id)

    const planId = await createPlan(page, token, csrf, {
      name: 'Convergence gate',
      ordering_mode: 'informational',
      lanes: [
        { id: 'alpha', name: 'Alpha', order: 0 },
        { id: 'beta', name: 'Beta', order: 1 },
        { id: 'merge', name: 'Merge', order: 2 },
      ],
      nodes: [
        { id: 'a1', node_type: 'issue', ref_id: issueA, lane_id: 'alpha', position: 0 },
        { id: 'b1', node_type: 'issue', ref_id: issueB, lane_id: 'beta', position: 0 },
        { id: 'm1', node_type: 'issue', ref_id: issueA + 1, lane_id: 'merge', position: 0 },
      ],
      checkpoints: [],
      convergence_gates: [
        { id: 'gate-1', gate_node_id: 'm1', wait_for: [{ node_id: 'a1' }, { node_id: 'b1' }] },
      ],
    })

    await page.goto(`/continuity-plans/${planId}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByTestId('plan-readiness-panel')).toBeVisible()

    const m1 = page.getByTestId('plan-node-readiness-m1')
    await expect(m1).toHaveAttribute('data-state', 'blocked')
    await expect(page.getByText(/Blocked by a convergence gate until/)).toBeVisible()
  })

  test('editing a gate and reloading reflects the updated readiness', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const token = await getAuthToken(page)
    const csrf = await getCsrf(page, token)

    const threadA = await createThread(page, { title: 'Edit Alpha', format: 'Comics', issues_remaining: 2, total_issues: 2 })
    const threadB = await createThread(page, { title: 'Edit Beta', format: 'Comics', issues_remaining: 2, total_issues: 2 })
    const issueA = await getFirstIssueId(page, token, threadA.id)
    const issueB = await getFirstIssueId(page, token, threadB.id)

    const planId = await createPlan(page, token, csrf, {
      name: 'Editable gate',
      ordering_mode: 'informational',
      lanes: [
        { id: 'alpha', name: 'Alpha', order: 0 },
        { id: 'beta', name: 'Beta', order: 1 },
        { id: 'merge', name: 'Merge', order: 2 },
      ],
      nodes: [
        { id: 'a1', node_type: 'issue', ref_id: issueA, lane_id: 'alpha', position: 0 },
        { id: 'b1', node_type: 'issue', ref_id: issueB, lane_id: 'beta', position: 0 },
        { id: 'm1', node_type: 'issue', ref_id: issueA + 1, lane_id: 'merge', position: 0 },
      ],
      checkpoints: [],
      convergence_gates: [
        { id: 'gate-1', gate_node_id: 'm1', wait_for: [{ node_id: 'a1' }] },
      ],
    })

    await page.goto(`/continuity-plans/${planId}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByTestId('plan-readiness-panel')).toBeVisible()
    await expect(page.getByTestId('plan-node-readiness-m1')).toHaveAttribute('data-state', 'blocked')

    await page.getByTestId('gate-node-select').selectOption('m1')
    await page.getByTestId('gate-wait-select').selectOption(['a1', 'b1'])
    await page.getByRole('button', { name: 'Add convergence gate' }).click()
    await expect(page.getByTestId('convergence-gate-gate-2')).toBeVisible()
    await page.getByRole('button', { name: 'Save plan' }).click()
    await expect(page.getByRole('status', { name: 'Saved' })).toBeVisible()

    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByTestId('convergence-gate-gate-2')).toBeVisible()
    await expect(page.getByTestId('plan-node-readiness-m1')).toHaveAttribute('data-state', 'blocked')
  })

  test('removing a gate deletes only the rules that gate compiled', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const token = await getAuthToken(page)
    const csrf = await getCsrf(page, token)

    const threadA = await createThread(page, { title: 'Remove Alpha', format: 'Comics', issues_remaining: 2, total_issues: 2 })
    const threadB = await createThread(page, { title: 'Remove Beta', format: 'Comics', issues_remaining: 2, total_issues: 2 })
    const issueA = await getFirstIssueId(page, token, threadA.id)
    const issueB = await getFirstIssueId(page, token, threadB.id)

    const planId = await createPlan(page, token, csrf, {
      name: 'Removable gate',
      ordering_mode: 'informational',
      lanes: [
        { id: 'alpha', name: 'Alpha', order: 0 },
        { id: 'beta', name: 'Beta', order: 1 },
        { id: 'merge', name: 'Merge', order: 2 },
      ],
      nodes: [
        { id: 'a1', node_type: 'issue', ref_id: issueA, lane_id: 'alpha', position: 0 },
        { id: 'b1', node_type: 'issue', ref_id: issueB, lane_id: 'beta', position: 0 },
        { id: 'm1', node_type: 'issue', ref_id: issueA + 1, lane_id: 'merge', position: 0 },
      ],
      checkpoints: [],
      convergence_gates: [
        { id: 'gate-1', gate_node_id: 'm1', wait_for: [{ node_id: 'a1' }, { node_id: 'b1' }] },
      ],
    })

    await page.goto(`/continuity-plans/${planId}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByTestId('convergence-gate-gate-1')).toBeVisible()

    await page.getByRole('button', { name: 'Remove gate gate-1' }).click()
    await page.getByRole('button', { name: 'Save plan' }).click()
    await expect(page.getByRole('status', { name: 'Saved' })).toBeVisible()

    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByTestId('convergence-gate-gate-1')).toHaveCount(0)

    const rulesResponse = await page.request.get('/api/v1/continuity-rules/', {
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    expect(rulesResponse.ok()).toBeTruthy()
    const rules = (await rulesResponse.json()) as Array<{ note?: string }>
    const planRules = rules.filter((rule) => rule.note === `continuity-plan:${planId}`)
    expect(planRules).toHaveLength(0)
  })
})

