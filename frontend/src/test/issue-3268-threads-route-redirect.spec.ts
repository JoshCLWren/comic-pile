/**
 * Issue #3268: thread detail pages at /threads/* rendered completely blank.
 *
 * The crossover detail page generated /threads/:id links while the app only
 * serves /thread/:id, so every crossover reading-flow action ("Continue
 * Reading", "Read Now", "Open") dead-ended on an unmatched route. Stale
 * bookmarks and shared /threads/:id URLs hit the same blank page.
 *
 * These browser checks prove the reported reading flows land on working pages:
 *
 * 1. A hard navigation to a legacy /threads/:id URL redirects to /thread/:id
 *    and renders the thread detail page instead of a blank document.
 * 2. Crossover reading-flow actions navigate to /thread/:id URLs that render
 *    the target thread.
 */
import { expect, type Page } from '@playwright/test'
import { test } from './fixtures'
import { createThread, getAuthToken } from './helpers'

const THREAD_TITLE = 'Redirect Target Series'
const GROUP_NAME = 'Threads Redirect QA Group'

async function getCsrfToken(
  page: Page,
  token: string | null,
): Promise<string> {
  const response = await page.request.get('/api/auth/csrf', {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  expect(response.ok()).toBeTruthy()
  // SAFETY: the test reads only csrf_token from the response body
  const data = (await response.json()) as { csrf_token?: string }
  expect(data.csrf_token).toBeDefined()
  return data.csrf_token!
}

async function authHeaders(page: Page): Promise<Record<string, string>> {
  const token = await getAuthToken(page)
  const csrf = await getCsrfToken(page, token)
  return {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrf,
  }
}

async function seedThread(page: Page): Promise<number> {
  const thread = await createThread(page, {
    title: THREAD_TITLE,
    format: 'Issue',
    issues_remaining: 1,
    total_issues: 1,
  })
  return thread.id
}

async function seedSingleMemberGroup(page: Page, threadId: number): Promise<number> {
  const headers = await authHeaders(page)
  const createResponse = await page.request.post('/api/v1/reading-order-groups/', {
    headers,
    data: { name: GROUP_NAME },
  })
  expect(createResponse.ok(), `group create failed: ${await createResponse.text()}`).toBeTruthy()
  // SAFETY: the API returns a created record, so its id is always present
  const group = (await createResponse.json()) as { id: number }

  const memberResponse = await page.request.post(
    `/api/v1/reading-order-groups/${group.id}/members`,
    {
      headers,
      data: { thread_id: threadId },
    },
  )
  expect(memberResponse.ok(), `group member failed: ${await memberResponse.text()}`).toBeTruthy()
  return group.id
}

async function assertThreadPageRendered(page: Page): Promise<void> {
  await expect(page.getByRole('heading', { name: THREAD_TITLE })).toBeVisible()
}

test.describe('Issue #3268: /threads/:id must not dead-end on a blank page', () => {
  test('hard navigation to a legacy /threads/:id URL redirects to the working thread page', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const threadId = await seedThread(page)

    await page.goto(`/threads/${threadId}`, { waitUntil: 'domcontentloaded' })

    await expect(page).toHaveURL(new RegExp(`/thread/${threadId}$`))
    await assertThreadPageRendered(page)
  })

  test('crossover Continue Reading lands on a working /thread/:id page', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage
    const threadId = await seedThread(page)
    const groupId = await seedSingleMemberGroup(page, threadId)

    await page.goto(`/crossovers/${groupId}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: GROUP_NAME })).toBeVisible()

    await page.getByRole('link', { name: 'Continue Reading' }).click()
    await expect(page).toHaveURL(new RegExp(`/thread/${threadId}$`))
    await assertThreadPageRendered(page)
  })
})
