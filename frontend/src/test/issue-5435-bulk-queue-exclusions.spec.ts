import { expect } from '@playwright/test'
import { test } from './fixtures'
import { createThread, getAuthToken, gotoQueue, waitForQueueReady } from './helpers'

async function getCsrf(page: Parameters<typeof getAuthToken>[0], token: string | null): Promise<string> {
  const response = await page.request.get('/api/v2/auth/csrf', {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  // SAFETY: the auth endpoint supplies the CSRF token for these authenticated fixture writes.
  const data = (await response.json()) as { csrf_token?: string }
  expect(data.csrf_token).toBeTruthy()
  return data.csrf_token!
}

async function authHeaders(page: Parameters<typeof getAuthToken>[0]) {
  const token = await getAuthToken(page)
  expect(token).toBeTruthy()
  const csrf = await getCsrf(page, token)
  return {
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrf,
    Authorization: `Bearer ${token}`,
  }
}

async function firstIssueId(page: Parameters<typeof getAuthToken>[0], threadId: number): Promise<number> {
  const headers = await authHeaders(page)
  const response = await page.request.get(`/api/v1/threads/${threadId}/issues`, { headers })
  expect(response.ok(), await response.text()).toBeTruthy()
  // SAFETY: the thread issues endpoint returns issue IDs used to build the reading-list fixture.
  const data = (await response.json()) as { issues: Array<{ id: number }> }
  expect(data.issues.length).toBeGreaterThan(0)
  return data.issues[0].id
}

test.describe('Issue 5435: bulk queue exclusions for reading containers', () => {
  test('removes and restores a reading list group from the queue', async ({ authenticatedPage }) => {
    const page = authenticatedPage
    const alpha = await createThread(page, {
      title: 'Bulk Exclusion Alpha',
      format: 'comic',
      issues_remaining: 1,
      total_issues: 1,
    })
    const beta = await createThread(page, {
      title: 'Bulk Exclusion Beta',
      format: 'comic',
      issues_remaining: 1,
      total_issues: 1,
    })
    const alphaIssue = await firstIssueId(page, alpha.id)
    const betaIssue = await firstIssueId(page, beta.id)

    const headers = await authHeaders(page)
    const listName = `Bulk Queue List ${Date.now()}`
    const createList = await page.request.post('/api/v2/reading-lists', {
      headers,
      data: { name: listName, issue_ids: [alphaIssue, betaIssue] },
    })
    expect(createList.ok(), await createList.text()).toBeTruthy()
    // SAFETY: the reading-list create response provides the id/name used to open the container page.
    const list = (await createList.json()) as { id: number; name: string }

    await page.goto(`/reading-lists/${list.id}`)
    await expect(page.getByRole('heading', { name: 'Edit Reading List' })).toBeVisible()

    await page.getByRole('button', { name: 'Remove all series from Queue' }).click()
    const removeDialog = page.getByRole('dialog', { name: 'Remove all series from Queue' })
    await expect(removeDialog).toBeVisible()
    await expect(removeDialog.getByText('Bulk Exclusion Alpha')).toBeVisible()
    await expect(removeDialog.getByText('Bulk Exclusion Beta')).toBeVisible()
    await removeDialog.getByRole('button', { name: 'Remove from Queue' }).click()
    await expect(removeDialog).toBeHidden()

    await gotoQueue(page)
    await waitForQueueReady(page)
    const activeQueue = page.locator('[data-testid="queue-thread-item"]')
    await expect(activeQueue.filter({ hasText: 'Bulk Exclusion Alpha' })).toHaveCount(0)
    await expect(activeQueue.filter({ hasText: 'Bulk Exclusion Beta' })).toHaveCount(0)

    const removedSection = page.getByTestId('excluded-threads-section')
    await expect(removedSection).toBeVisible()
    await removedSection.getByRole('button', { name: /Show Removed/ }).click()
    const group = removedSection.getByTestId('excluded-group')
    await expect(group).toContainText(listName)
    await expect(group).toContainText('Bulk Exclusion Alpha')
    await expect(group).toContainText('Bulk Exclusion Beta')

    await group.getByRole('button', { name: `Restore all series removed with ${listName}` }).click()
    await expect(group).toHaveCount(0)
    await expect(activeQueue.filter({ hasText: 'Bulk Exclusion Alpha' })).toBeVisible()
    await expect(activeQueue.filter({ hasText: 'Bulk Exclusion Beta' })).toBeVisible()
  })
})
