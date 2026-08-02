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

    const swipeableCard = authenticatedPage
      .getByTestId('queue-thread-item')
      .filter({ hasText: title })
    await expect(swipeableCard).toBeVisible()

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
      // Swipe actions sit behind the translated card surface. Force-click the
      // action itself so this network contract does not depend on touch gesture
      // emulation, which is covered by Swipeable's focused component tests.
      swipeableCard.getByLabel('Snooze').click({ force: true }),
    ])

    await expect(swipeableCard.getByLabel('Unsnooze')).toBeAttached()
    await expect.poll(() => observedRequests.some(request => isSessionGet(request.method, request.url))).toBe(true)
    expect(observedRequests.some(request => isFullThreadListGet(request.method, request.url))).toBe(false)

    observedRequests.length = 0
    await Promise.all([
      authenticatedPage.waitForResponse(response =>
        response.request().method() === 'POST' &&
        new URL(response.url()).pathname === `/api/snooze/${id}/unsnooze` &&
        response.ok(),
      ),
      swipeableCard.getByLabel('Unsnooze').click({ force: true }),
    ])

    await expect(swipeableCard.getByLabel('Snooze')).toBeAttached()
    await expect.poll(() => observedRequests.some(request => isSessionGet(request.method, request.url))).toBe(true)
    expect(observedRequests.some(request => isFullThreadListGet(request.method, request.url))).toBe(false)

    authenticatedPage.off('request', captureRequest)
  })
})
