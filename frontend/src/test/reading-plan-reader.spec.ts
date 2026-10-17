import { test, expect } from './fixtures'
import type { Page } from '@playwright/test'
import { createThread, getAuthToken } from './helpers'

type JsonRequestHeaders = {
  'Content-Type': string
  'X-CSRF-Token': string
  Authorization?: string
}

async function getCsrf(page: Page, token: string | null): Promise<string> {
  const response = token
    ? await page.request.get('/api/auth/csrf', {
        headers: { Authorization: `Bearer ${token}` },
      })
    : await page.request.get('/api/auth/csrf')
  expect(response.ok()).toBeTruthy()
  // SAFETY: the test reads only csrf_token from the response body
  const data = await response.json() as { csrf_token?: string }
  expect(data.csrf_token).toBeDefined()
  return data.csrf_token!
}

async function authHeaders(page: Page): Promise<JsonRequestHeaders> {
  const token = await getAuthToken(page)
  const csrf = await getCsrf(page, token)
  const headers = {
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrf,
  } satisfies JsonRequestHeaders
  if (token) {
    return { ...headers, Authorization: `Bearer ${token}` }
  }
  return headers
}

async function firstIssueId(page: Page, headers: JsonRequestHeaders, threadId: number): Promise<number> {
  const response = await page.request.get(`/api/v1/threads/${threadId}/issues`, { headers })
  expect(response.ok(), await response.text()).toBeTruthy()
  // SAFETY: the test reads only the issue ids listed here
  const data = await response.json() as { issues: Array<{ id: number }> }
  expect(data.issues.length).toBeGreaterThan(0)
  return data.issues[0].id
}

test.describe('Reading Plan reader surface', () => {
  test('shows progress, available now, and canonical blockers at phone and desktop', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const headers = await authHeaders(page)
    const xmen = await createThread(page, {
      title: 'Reader X-Men',
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const cable = await createThread(page, {
      title: 'Reader Cable',
      format: 'Comics',
      issues_remaining: 1,
      total_issues: 1,
    })
    const xmenIssue = await firstIssueId(page, headers, xmen.id)
    const cableIssue = await firstIssueId(page, headers, cable.id)
    const dependency = await page.request.post('/api/v1/dependencies/', {
      headers,
      data: {
        source_type: 'issue',
        source_id: xmenIssue,
        target_type: 'issue',
        target_id: cableIssue,
      },
    })
    expect(dependency.ok(), await dependency.text()).toBeTruthy()
    const created = await page.request.post('/api/v1/continuity-plans/', {
      headers,
      data: {
        name: 'Reader AoA Plan',
        ordering_mode: 'informational',
        lanes: [{ id: 'main', name: 'Main', order: 0 }],
        nodes: [
          { id: 'x1', node_type: 'issue', ref_id: xmenIssue, lane_id: 'main', position: 0 },
          { id: 'c1', node_type: 'issue', ref_id: cableIssue, lane_id: 'main', position: 1 },
        ],
      },
    })
    expect(created.ok(), await created.text()).toBeTruthy()
    // SAFETY: the test reads only the created plan id
    const plan = await created.json() as { id: number }

    for (const viewport of [
      { width: 390, height: 844, label: 'phone' },
      { width: 768, height: 1024, label: 'tablet' },
      { width: 1280, height: 800, label: 'desktop' },
    ]) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      await page.goto(`/continuity-plans/${plan.id}`, { waitUntil: 'domcontentloaded' })
      await expect(page.getByTestId('reading-plan-reader')).toBeVisible()
      await expect(page.getByRole('heading', { name: 'Reader AoA Plan' })).toBeVisible()
      await expect(page.getByTestId('plan-progress')).toContainText('0%')
      await expect(page.getByText('Informational', { exact: true })).toBeVisible()
      await expect(page.getByRole('heading', { name: 'Available now' })).toBeVisible()
      await expect(page.getByTestId('available-now')).toContainText('Reader X-Men')
      await expect(page.getByRole('heading', { name: 'Blocked next' })).toBeVisible()
      await expect(page.getByTestId('blocked-next')).toContainText('Blocked by Reader X-Men: #1')
      await expect(page.getByRole('button', { name: 'Edit plan' })).toBeVisible()
      await expect(page.getByRole('link', { name: /crossovers page/i })).toHaveCount(0)
      await page.screenshot({
        path: `test-results/reading-plan-reader-${viewport.label}.png`,
        fullPage: true,
      })
    }

    await page.goto('/crossovers', { waitUntil: 'domcontentloaded' })
    await expect(page).toHaveURL(/\/continuity-plans$/)
    await expect(page.getByRole('heading', { name: 'Reading Plans' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Add from CBL' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Browse CBL sources' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Crossover events' })).toBeVisible()
    for (const viewport of [
      { width: 390, height: 844, label: 'phone' },
      { width: 768, height: 1024, label: 'tablet' },
      { width: 1280, height: 800, label: 'desktop' },
    ]) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      await page.screenshot({
        path: `test-results/reading-plans-index-${viewport.label}.png`,
        fullPage: true,
      })
    }
  })
})

// The ordinary lane proves disabled-mode safety; an enabled local fixture also proves strict execution.
test('Option E explains strict Julix blockers consistently and supports direct list reading', async ({ authenticatedPage: page }) => {
  const headers = await authHeaders(page)
  const first = await createThread(page, { title: 'Julix Dead Remembered', format: 'Comics', issues_remaining: 1, total_issues: 1 })
  const later = await createThread(page, { title: 'Julix King of Fear', format: 'Comics', issues_remaining: 1, total_issues: 1 })
  const firstIssue = await firstIssueId(page, headers, first.id)
  const laterIssue = await firstIssueId(page, headers, later.id)
  const createdList = await page.request.post('/api/v1/custom-cbls', { headers, data: { name: 'Julix strict acceptance', mode: 'strict', issue_ids: [firstIssue, laterIssue] } })
  expect(createdList.ok(), await createdList.text()).toBeTruthy()
  // SAFETY: successful list creation returns a numeric id; this test reads only that id.
  const list = await createdList.json() as { id: number }
  const reader = await page.request.get(`/api/v1/custom-cbls/${list.id}/reader`, { headers })
  expect(reader.ok(), await reader.text()).toBeTruthy()
  // SAFETY: the owned reader endpoint returns execution_mode; no other response fields are read.
  const projection = await reader.json() as { execution_mode: string }
  expect(projection.execution_mode).toBe(process.env.OPTION_E_EXPECTED_MODE ?? 'legacy')
  const enabled = projection.execution_mode === 'option_e'
  const dependency = await page.request.post('/api/v1/dependencies/', { headers, data: { source_type: 'issue', source_id: firstIssue, target_type: 'issue', target_id: laterIssue } })
  expect(dependency.ok(), await dependency.text()).toBeTruthy()
  const createPlan = await page.request.post('/api/v1/continuity-plans/', { headers, data: { name: 'Reader entry point', lanes: [{ id: 'main', name: 'Main', order: 0 }], nodes: [] } })
  expect(createPlan.ok(), await createPlan.text()).toBeTruthy()
  // SAFETY: successful plan creation returns a numeric id; this test reads only that id.
  const plan = await createPlan.json() as { id: number }
  const reason = enabled ? 'Strict order in Julix strict acceptance: waiting on Julix Dead Remembered #1' : 'Blocked by Julix Dead Remembered: #1'

  for (const width of [390, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto(`/thread/${later.id}`)
    await expect(page.getByRole('region', { name: 'Next issue availability' })).toContainText(reason)
    await expect(page.getByText('Nothing blocks this series', { exact: true })).toHaveCount(0)
    await page.goto('/')
    await page.getByRole('button', { name: /series waiting for earlier issues/ }).click()
    await expect(page.getByText(reason, { exact: true }).first()).toBeVisible()
    await page.goto('/queue')
    const card = page.getByTestId('queue-thread-item').filter({ hasText: 'Julix King of Fear' })
    await expect(card).toContainText(reason)
    await expect(card.getByRole('button', { name: 'Read & Rate' })).toBeDisabled()
    await page.goto(`/continuity-plans/${plan.id}/edit`)
    await page.getByRole('button', { name: 'Create or edit custom CBL', exact: true }).click()
    await page.getByRole('combobox', { name: 'Custom CBL', exact: true }).selectOption(String(list.id))
    await page.getByRole('button', { name: 'Read this list', exact: true }).click()
    const listReader = page.getByRole('region', { name: 'Read Julix strict acceptance', exact: true })
    if (enabled) {
      await expect(listReader).toContainText(reason)
      await expect(listReader.getByRole('button', { name: 'Mark read', exact: true })).toHaveCount(1)
    } else {
      await expect(listReader).toContainText('Reading List execution is not active yet')
      await expect(listReader.getByRole('button', { name: 'Mark read', exact: true })).toHaveCount(0)
    }
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    const theme = width === 390 ? 'classic' : width === 768 ? 'ink-gold' : 'command-center'
    await page.evaluate((name) => document.documentElement.setAttribute('data-theme', name), theme)
    await listReader.screenshot({ path: `test-results/option-e-reader-${width}-${theme}.png` })
  }
  if (!enabled) {
    const marked = await page.request.post(`/api/v1/issues/${firstIssue}:markRead`, { headers })
    expect(marked.ok(), await marked.text()).toBeTruthy()
    await page.goto(`/thread/${later.id}`)
    await expect(page.getByRole('region', { name: 'Next issue availability' })).toContainText('Next unread: #1')
    return
  }
  const listReader = page.getByRole('region', { name: 'Read Julix strict acceptance', exact: true })
  await listReader.getByRole('button', { name: 'Mark read', exact: true }).click()
  await expect(listReader.getByRole('button', { name: 'Mark unread', exact: true })).toHaveCount(1)
  await expect(listReader).not.toContainText(reason)
  await expect(listReader.getByRole('button', { name: 'Mark read', exact: true })).toHaveCount(1)
  await page.goto(`/thread/${later.id}`)
  await expect(page.getByRole('region', { name: 'Next issue availability' })).toContainText('Next unread: #1')
})
