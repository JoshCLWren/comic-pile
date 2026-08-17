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

async function createPlan(
  page: Page,
  token: string | null,
  csrf: string,
  name: string,
  threadIds: number[],
): Promise<number> {
  const headers = {
    ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrf,
  }
  const response = await page.request.post('/api/v1/continuity-plans/', {
    headers,
    data: {
      name,
      ordering_mode: 'informational',
      lanes: [{ id: 'main', name: 'Main', order: 0 }],
      nodes: threadIds.map((threadId, position) => ({
        id: `node-${threadId}-${position}`,
        node_type: 'thread',
        ref_id: threadId,
        lane_id: 'main',
        position,
      })),
    },
  })
  expect(response.ok(), `plan create failed: ${await response.text()}`).toBeTruthy()
  const plan = await response.json() as { id: number }
  return plan.id
}

async function createReadingOrder(
  page: Page,
  token: string | null,
  csrf: string,
  name: string,
  items: Array<{ thread_id: number; position: number }> = [],
): Promise<number> {
  const headers = {
    ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrf,
  }
  const response = await page.request.post('/api/test/reading-orders', {
    headers,
    data: { name, items },
  })
  expect(response.ok(), `reading order create failed: ${await response.text()}`).toBeTruthy()
  const order = await response.json() as { id: number }
  return order.id
}

test.describe('Continuity plan projection', () => {
  test('previews and confirms a projection into an existing reading order', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const token = await getAuthToken(page)
    const csrf = await getCsrf(page, token)

    const firstThread = await createThread(page, { title: 'Projection Alpha', format: 'Comics', issues_remaining: 3 })
    const secondThread = await createThread(page, { title: 'Projection Beta', format: 'Comics', issues_remaining: 3 })
    const planId = await createPlan(page, token, csrf, 'Projection plan', [firstThread.id, secondThread.id])
    const orderId = await createReadingOrder(page, token, csrf, 'Projection order')

    await page.goto(`/continuity-plans/${planId}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('button', { name: 'Project to reading order' })).toBeVisible({ timeout: 10000 })
    await page.getByRole('button', { name: 'Project to reading order' }).click()

    const dialog = page.getByTestId('plan-projection-dialog')
    await expect(dialog).toBeVisible()
    await page.getByTestId('projection-reading-order-select').selectOption(String(orderId))
    await page.getByRole('button', { name: 'Preview projection' }).click()

    await expect(page.getByText('Projection Alpha')).toBeVisible()
    await expect(page.getByText('Projection Beta')).toBeVisible()
    await expect(page.getByText('2 positions')).toBeVisible()

    await page.getByRole('button', { name: 'Confirm projection' }).click()
    await expect(page.getByText('Projection applied')).toBeVisible()
    await expect(page.getByText(/2 added/)).toBeVisible()
  })

  test('reports duplicate-thread conflicts before any mutation', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const token = await getAuthToken(page)
    const csrf = await getCsrf(page, token)

    const thread = await createThread(page, { title: 'Duplicate Thread', format: 'Comics', issues_remaining: 3 })
    // The same thread appears twice in the plan.
    const planId = await createPlan(page, token, csrf, 'Duplicate plan', [thread.id, thread.id])
    const orderId = await createReadingOrder(page, token, csrf, 'Duplicate order')

    await page.goto(`/continuity-plans/${planId}`, { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Project to reading order' }).click()
    await page.getByTestId('projection-reading-order-select').selectOption(String(orderId))
    await page.getByRole('button', { name: 'Preview projection' }).click()

    await expect(page.getByText(/Resolve conflicts before projecting/)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Confirm projection' })).toBeDisabled()
  })

  test('canceling projection leaves both the plan and reading order unchanged', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const token = await getAuthToken(page)
    const csrf = await getCsrf(page, token)

    const thread = await createThread(page, { title: 'Rollback Thread', format: 'Comics', issues_remaining: 3 })
    const planId = await createPlan(page, token, csrf, 'Rollback plan', [thread.id])
    const orderId = await createReadingOrder(page, token, csrf, 'Rollback order')

    await page.goto(`/continuity-plans/${planId}`, { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Project to reading order' }).click()
    await page.getByTestId('projection-reading-order-select').selectOption(String(orderId))
    await page.getByRole('button', { name: 'Preview projection' }).click()
    await expect(page.getByText('Rollback Thread')).toBeVisible()

    // Close without confirming.
    await page.getByRole('button', { name: 'Close modal' }).click()
    await expect(page.getByTestId('plan-projection-dialog')).not.toBeVisible()

    // Verify the reading order still has no items.
    const listResponse = await page.request.get('/api/v1/reading-orders/', {
      headers: { ...(token ? { 'Authorization': `Bearer ${token}` } : {}) },
    })
    expect(listResponse.ok()).toBeTruthy()
    const list = await listResponse.json() as { reading_orders: Array<{ id: number; total_items: number }> }
    const order = list.reading_orders.find((candidate) => candidate.id === orderId)
    expect(order).toBeDefined()
    expect(order!.total_items).toBe(0)
  })
})
