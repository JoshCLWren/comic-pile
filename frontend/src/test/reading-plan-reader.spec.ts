import { test, expect } from './fixtures'
import type { Page } from '@playwright/test'
import { createThread, getAuthToken } from './helpers'

async function getCsrf(page: Page, token: string | null): Promise<string> {
  const headers: Record<string, string> = {}
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  const response = await page.request.get('/api/auth/csrf', { headers })
  expect(response.ok()).toBeTruthy()
  // SAFETY: the test reads only csrf_token from the response body
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

async function firstIssueId(page: Page, headers: Record<string, string>, threadId: number): Promise<number> {
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
      await expect(page.getByRole('heading', { name: 'Blocked by' })).toBeVisible()
      await expect(page.getByTestId('blocked-next')).toContainText('Blocked by Reader X-Men: #1')
      await expect(page.getByRole('button', { name: 'Edit plan' })).toBeVisible()
      await expect(page.getByRole('link', { name: /crossovers page/i })).toHaveCount(0)
      await page.screenshot({
        path: `/opt/cursor/artifacts/screenshots/reading-plan-reader-${viewport.label}.png`,
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
        path: `/opt/cursor/artifacts/screenshots/reading-plans-index-${viewport.label}.png`,
        fullPage: true,
      })
    }
  })
})
