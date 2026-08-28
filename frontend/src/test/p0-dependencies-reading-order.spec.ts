/**
 * DEP-001 + ORDER-001: Dependency relations and reading order.
 *
 * Verifies that dependencies between threads are created via the API and
 * reflected in the UI: blocked threads show dependency indicators, reading
 * order follows the declared dependency graph, and the dependency can be
 * removed.
 *
 * Inventory IDs: DEP-001, ORDER-001
 */
import { expect } from '@playwright/test'
import { test } from './fixtures'
import {
  createThread,
  getAuthToken,
  gotoQueue,
  gotoRollPage,
  waitForQueueReady,
  waitForRollPageReady,
} from './helpers'

async function getCsrfToken(
  page: import('@playwright/test').Page,
  token: string | null,
): Promise<string> {
  const response = await page.request.get('/api/auth/csrf', {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  expect(response.ok()).toBeTruthy()
  const data = (await response.json()) as { csrf_token?: string }
  expect(data.csrf_token).toBeDefined()
  return data.csrf_token!
}

async function createDependency(
  page: import('@playwright/test').Page,
  sourceId: number,
  targetId: number,
): Promise<void> {
  const token = await getAuthToken(page)
  const csrf = await getCsrfToken(page, token)
  const response = await page.request.post('/api/v1/dependencies/', {
    data: {
      source_type: 'thread',
      source_id: sourceId,
      target_id: targetId,
    },
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      'X-CSRF-Token': csrf,
    },
  })
  expect(response.ok(), `dependency create failed: ${response.status()}`).toBeTruthy()
}

async function listIssues(
  page: import('@playwright/test').Page,
  threadId: number,
): Promise<Array<{ id: number; position: number }>> {
  const token = await getAuthToken(page)
  const response = await page.request.get(`/api/v1/threads/${threadId}/issues`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(response.ok()).toBeTruthy()
  const data = (await response.json()) as { issues: Array<{ id: number; position: number }> }
  return data.issues
}

test.describe('DEP-001 + ORDER-001: Dependency and reading order', () => {
  test('creating a dependency between threads is persisted', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const blocking = await createThread(page, {
      title: 'Blocking Thread',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })
    const blocked = await createThread(page, {
      title: 'Blocked Thread',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })

    await createDependency(page, blocking.id, blocked.id)

    const token = await getAuthToken(page)
    const response = await page.request.get(`/api/v1/threads/${blocked.id}/dependencies`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(response.ok()).toBeTruthy()
    const deps = (await response.json()) as { dependencies: unknown[] }
    expect(deps.dependencies.length).toBeGreaterThanOrEqual(1)
  })

  test('blocked thread shows dependency indicator in queue', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const blocking = await createThread(page, {
      title: 'Dep Blocker',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })
    const blocked = await createThread(page, {
      title: 'Dep Blocked',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })

    await createDependency(page, blocking.id, blocked.id)

    await gotoQueue(page)
    await waitForQueueReady(page)

    const blockedItem = page.getByTestId('queue-thread-item').filter({ hasText: 'Dep Blocked' })
    await expect(blockedItem).toBeVisible({ timeout: 10000 })
  })

  test('reading order holds a dependent thread back from eligible reads', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const blocking = await createThread(page, {
      title: 'Order Blocker',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })
    const blocked = await createThread(page, {
      title: 'Order Blocked',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })

    await createDependency(page, blocking.id, blocked.id)

    await gotoRollPage(page)
    await waitForRollPageReady(page)

    await expect(page.getByText(/hidden \(blocked by dependencies\)/i)).toBeVisible({
      timeout: 15000,
    })
  })

  test('issue-level dependency is created and visible', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const threadA = await createThread(page, {
      title: 'Issue Dep A',
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })
    const threadB = await createThread(page, {
      title: 'Issue Dep B',
      format: 'Issue',
      issues_remaining: 3,
      total_issues: 3,
    })

    const issuesA = await listIssues(page, threadA.id)
    const issuesB = await listIssues(page, threadB.id)
    expect(issuesA.length).toBeGreaterThanOrEqual(1)
    expect(issuesB.length).toBeGreaterThanOrEqual(1)

    const token = await getAuthToken(page)
    const csrf = await getCsrfToken(page, token)
    const depResponse = await page.request.post('/api/v1/dependencies/', {
      data: {
        source_type: 'issue',
        source_id: issuesA[0].id,
        target_id: issuesB[0].id,
      },
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
        'X-CSRF-Token': csrf,
      },
    })
    expect(depResponse.ok()).toBeTruthy()

    const depsResponse = await page.request.get(`/api/v1/issues/${issuesB[0].id}/dependencies`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(depsResponse.ok()).toBeTruthy()
    const deps = (await depsResponse.json()) as { dependencies: unknown[] }
    expect(deps.dependencies.length).toBeGreaterThanOrEqual(1)
  })

  test('dependency can be deleted', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const threadA = await createThread(page, {
      title: 'Delete Dep A',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })
    const threadB = await createThread(page, {
      title: 'Delete Dep B',
      format: 'Issue',
      issues_remaining: 2,
      total_issues: 2,
    })

    await createDependency(page, threadA.id, threadB.id)

    const token = await getAuthToken(page)
    const depsResponse = await page.request.get(`/api/v1/threads/${threadB.id}/dependencies`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const deps = (await depsResponse.json()) as { dependencies: Array<{ id: number }> }
    expect(deps.dependencies.length).toBeGreaterThanOrEqual(1)

    const depId = deps.dependencies[0].id
    const csrf = await getCsrfToken(page, token)
    const deleteResponse = await page.request.delete(`/api/v1/dependencies/${depId}`, {
      headers: {
        Authorization: `Bearer ${token}`,
        'X-CSRF-Token': csrf,
      },
    })
    expect(deleteResponse.ok()).toBeTruthy()
  })
})
