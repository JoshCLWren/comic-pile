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
  test('snooze and unsnooze refresh session without refetching the full thread list', async ({ authenticatedPage, request }) => {
    const title = `Queue Snooze Network ${Date.now()}`
    const { id } = await createThread(authenticatedPage, {
      title,
      format: 'Comics',
      issues_remaining: 5,
    })

    // The queue Snooze action snoozes the session's pending thread, so establish
    // a pending thread before exercising the request sequence.
    const token = await authenticatedPage.evaluate(
      () => localStorage.getItem('auth_token') ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN,
    )
    const setPendingResponse = await request.post(`/api/threads/${id}/set-pending`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    expect(setPendingResponse.ok()).toBeTruthy()

    await gotoQueue(authenticatedPage)
    await waitForThreadInQueue(authenticatedPage, title)

    const queueCard = authenticatedPage
      .getByTestId('queue-thread-item')
      .filter({ hasText: title })
    await expect(queueCard).toBeVisible()

    const observedRequests: Array<{ method: string; url: string }> = []
    const captureRequest = (request: { method(): string; url(): string }) => {
      observedRequests.push({ method: request.method(), url: request.url() })
    }
    authenticatedPage.on('request', captureRequest)

    observedRequests.length = 0
    await Promise.all([
      authenticatedPage.waitForResponse(response =>
        response.request().method() === 'POST' &&
        new URL(response.url()).pathname === '/api/snooze/' &&
        response.ok(),
      ),
      queueCard.getByRole('button', { name: 'Snooze' }).click(),
    ])

    await expect(queueCard.getByRole('button', { name: 'Unsnooze' })).toBeVisible()
    await expect.poll(() => observedRequests.some(request => isSessionGet(request.method, request.url))).toBe(true)
    expect(observedRequests.some(request => isFullThreadListGet(request.method, request.url))).toBe(false)

    observedRequests.length = 0
    await Promise.all([
      authenticatedPage.waitForResponse(response =>
        response.request().method() === 'POST' &&
        new URL(response.url()).pathname === `/api/snooze/${id}/unsnooze` &&
        response.ok(),
      ),
      queueCard.getByRole('button', { name: 'Unsnooze' }).click(),
    ])

    await expect(queueCard.getByRole('button', { name: 'Snooze' })).toBeVisible()
    await expect.poll(() => observedRequests.some(request => isSessionGet(request.method, request.url))).toBe(true)
    expect(observedRequests.some(request => isFullThreadListGet(request.method, request.url))).toBe(false)

    authenticatedPage.off('request', captureRequest)
  })
})
