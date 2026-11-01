/**
 * Issue #4503 (parent #4499): reading/continuity and identity request budgets.
 *
 * These are authenticated browser/network checks against the real app shell:
 * exact HTTP method + path counts for each route's cold load. The deterministic
 * per-action matrix lives in
 * `src/unit/continuityIdentityRequestBudget.test.tsx`; this spec proves the
 * same budgets hold in Chromium with the production build, real auth, and the
 * navigation badge mounted.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { authHeaders } from './helpers'

type ApiCall = { method: string; path: string; query: URLSearchParams }

function collectApiCalls(page: Page): ApiCall[] {
  const calls: ApiCall[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (!url.pathname.startsWith('/api/')) return
    calls.push({ method: request.method(), path: url.pathname, query: url.searchParams })
  })
  return calls
}

function countCalls(calls: ApiCall[], method: string, path: string): number {
  return calls.filter((call) => call.method === method && call.path === path).length
}

/**
 * Wait until the expected traffic has arrived, then allow one short quiet
 * window so a duplicate request fired from a late effect still fails the
 * exact budget below instead of racing the assertion.
 */
async function settleCalls(page: Page, count: () => number, minimum = 1) {
  await expect.poll(count, { timeout: 15000 }).toBeGreaterThanOrEqual(minimum)
  await page.waitForTimeout(300)
}

async function expectNoDuplicateIdentityProbe(calls: ApiCall[]) {
  const identityCalls = calls.filter(
    (call) => call.method === 'GET' && call.path === '/api/v1/identity-inbox',
  )
  expect(identityCalls).toHaveLength(1)
  expect(identityCalls[0].query.get('limit')).toBe('20')
}

test.describe('Issue #4503 route request budgets', () => {
  test('identity inbox cold load issues one list request and no badge probe', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const calls = collectApiCalls(page)

    await page.goto('/identity-inbox')
    await expect(page.getByRole('heading', { name: 'Identity Inbox' })).toBeVisible()
    await settleCalls(
      page,
      () => calls.filter((call) => call.path === '/api/v1/identity-inbox').length,
    )

    await expectNoDuplicateIdentityProbe(calls)
  })

  test('reading plans index cold load issues one plans request', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const calls = collectApiCalls(page)

    await page.goto('/continuity-plans')
    await expect(page.getByRole('heading', { name: 'Reading Plans' })).toBeVisible()
    await settleCalls(page, () => countCalls(calls, 'GET', '/api/v1/continuity-plans/'))

    expect(countCalls(calls, 'GET', '/api/v1/continuity-plans/')).toBe(1)
  })

  test('new reading plan requests planner collections once', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const calls = collectApiCalls(page)

    await page.goto('/continuity-plans/new')
    await expect(page.getByRole('heading', { name: 'New Reading Plan' })).toBeVisible()
    await settleCalls(page, () => countCalls(calls, 'GET', '/api/v1/threads/'), 1)
    await settleCalls(page, () => countCalls(calls, 'GET', '/api/v1/reading-order-groups/'), 1)

    expect(countCalls(calls, 'GET', '/api/v1/threads/')).toBe(1)
    expect(countCalls(calls, 'GET', '/api/v1/reading-order-groups/')).toBe(1)
  })

  test('crossover events route requests groups and threads once', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const calls = collectApiCalls(page)

    await page.goto('/continuity-plans/events')
    await expect(page.getByRole('heading', { name: 'Crossover events' })).toBeVisible()
    await settleCalls(page, () => countCalls(calls, 'GET', '/api/v1/reading-order-groups/'), 1)
    await settleCalls(page, () => countCalls(calls, 'GET', '/api/v1/threads/'), 1)

    expect(countCalls(calls, 'GET', '/api/v1/reading-order-groups/')).toBe(1)
    expect(countCalls(calls, 'GET', '/api/v1/threads/')).toBe(1)
  })

  test('reading plan detail requests the reader and plan tags once', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const headers = await authHeaders(page)
    const created = await page.request.post('/api/v1/continuity-plans/', {
      headers,
      data: { name: 'Request budget plan', ordering_mode: 'informational', lanes: [], nodes: [] },
    })
    expect(created.ok()).toBeTruthy()
    // SAFETY: the create endpoint echoes the persisted plan; this test reads only its numeric id.
    const plan = (await created.json()) as { id: number }

    const calls = collectApiCalls(page)
    await page.goto(`/continuity-plans/${plan.id}`)
    await expect(page.getByRole('heading', { name: 'Request budget plan' })).toBeVisible()
    await settleCalls(
      page,
      () => countCalls(calls, 'GET', `/api/v1/continuity-plans/${plan.id}/reader`),
    )
    await settleCalls(
      page,
      () => countCalls(calls, 'GET', `/api/v1/tags/effective/plan/${plan.id}/`),
      1,
    )

    expect(countCalls(calls, 'GET', `/api/v1/continuity-plans/${plan.id}/reader`)).toBe(1)
    expect(countCalls(calls, 'GET', `/api/v1/tags/effective/plan/${plan.id}/`)).toBe(1)
  })
})
