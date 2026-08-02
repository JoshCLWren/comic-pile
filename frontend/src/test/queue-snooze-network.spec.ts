import { expect, test } from './fixtures'
import { createThread, gotoQueue, waitForThreadInQueue } from './helpers'

function isFullThreadListGet(method: string, url: string): boolean {
  if (method !== 'GET') return false
  const parsed = new URL(url)
  return parsed.pathname === '/api/threads/' || parsed.pathname === '/api/threads'
}

function isSessionGet(method: string, url: string): boolean {
  return method === 'GET' && new URL(url).pathname === '/api/sessions/current/'
}

test.describe('Queue snooze request sequence', () => {
  test('snooze and unsnooze refresh session without refetching the full thread list', async ({ authenticatedPage }) => {
    const title = `Queue Snooze Network ${Date.now()}`
    const { id } = await createThread(authenticatedPage, {
      title,
      format: 'Comics',
      issues_remaining: 5,
    })

    await gotoQueue(authenticatedPage)
    await waitForThreadInQueue(authenticatedPage, title)

    const threadCard = authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: title })
    await expect(threadCard).toBeVisible()

    const observedRequests: Array<{ method: string; url: string }> = []
    authenticatedPage.on('request', request => {
      observedRequests.push({ method: request.method(), url: request.url() })
    })

    observedRequests.length = 0
    await Promise.all([
      authenticatedPage.waitForResponse(response =>
        response.request().method() === 'POST' &&
        new URL(response.url()).pathname === '/api/snooze/' &&
        response.ok(),
      ),
      threadCard.getByLabel('Snooze').click(),
    ])

    await expect(threadCard.getByLabel('Unsnooze')).toBeVisible()
    await expect.poll(() => observedRequests.some(request => isSessionGet(request.method, request.url))).toBe(true)
    expect(observedRequests.some(request => isFullThreadListGet(request.method, request.url))).toBe(false)

    observedRequests.length = 0
    await Promise.all([
      authenticatedPage.waitForResponse(response =>
        response.request().method() === 'POST' &&
        new URL(response.url()).pathname === `/api/snooze/${id}/unsnooze` &&
        response.ok(),
      ),
      threadCard.getByLabel('Unsnooze').click(),
    ])

    await expect(threadCard.getByLabel('Snooze')).toBeVisible()
    await expect.poll(() => observedRequests.some(request => isSessionGet(request.method, request.url))).toBe(true)
    expect(observedRequests.some(request => isFullThreadListGet(request.method, request.url))).toBe(false)
  })
})
